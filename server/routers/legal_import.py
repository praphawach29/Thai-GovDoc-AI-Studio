"""นำเข้าไฟล์กฎหมาย/ระเบียบ (สแกน) เข้าคลังกฎหมาย — โหมด Supabase เท่านั้น

ขั้นตอน (เบราว์เซอร์เป็นผู้คุม เพื่อไม่ชนเพดานเวลา 120 วินาทีของ Vercel):
  1. POST /api/v1/legal/sources/upload-url    → URL ให้เบราว์เซอร์ PUT ไฟล์ตรงเข้า Storage (<org>/legal/)
  2. POST /api/v1/legal/sources               → บันทึกไฟล์ (นับหน้า, sha256)
  3. POST /api/v1/legal/ocr-page (ทีละหน้า)   → AI อ่านภาพหน้าที่เบราว์เซอร์เรนเดอร์จากไฟล์
  4. POST /api/v1/legal/sources/{id}/sections → แยกเป็นข้อ/มาตราพร้อมเลขหน้า บันทึกเป็นรายการ "ยังไม่ยืนยัน"
  5. PATCH /api/v1/legal/references/verify    → ผู้ใช้ตรวจแล้วยืนยัน (AI ใช้ได้เฉพาะรายการที่ยืนยันแล้ว)
"""

from __future__ import annotations

import hashlib
import io
import logging
from pathlib import Path
from typing import List, Optional
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field

from core.legal_import import guess_title, split_sections
from core.llm_drafter import ocr_images_with_llm
from server.auth import CurrentUser, Profile, get_profile, get_supabase, require_supabase_user
from server.settings import Settings, get_settings, llm_config
from server.supabase import SupabaseClient, SupabaseError

router = APIRouter(tags=["legal"])
logger = logging.getLogger("govdoc.api")

_SUFFIXES = {".pdf": "application/pdf"}
_SOURCE_COLUMNS = "id,title,filename,page_count,size_bytes,created_at"
_MIGRATION_HINT = ("ฐานข้อมูลยังไม่เห็นตารางคลังกฎหมาย — ให้ผู้ดูแลรัน supabase/migrations/20261116000008_legal_sources.sql "
                   "ทั้งไฟล์ใน SQL Editor (ถ้ารันแล้ว ให้รัน: notify pgrst, 'reload schema';)")


def _schema_guard(exc: SupabaseError) -> HTTPException:
    """คอลัมน์/ตารางใหม่ยังไม่มี (ยังไม่ได้รัน migration) → บอกให้ชัดแทน error ของฐานข้อมูล"""
    text = f"{exc.code} {exc.message}"
    logger.warning("legal library database error %s: %s", exc.status, text)
    if any(k in text for k in ("42703", "42P01", "PGRST204", "PGRST205", "does not exist", "Could not find")):
        return HTTPException(status_code=503, detail=_MIGRATION_HINT)
    return HTTPException(status_code=exc.status, detail=exc.message)


def _check_path(profile: Profile, path: str) -> str:
    prefix = f"{profile.org_id}/legal/"
    name = path[len(prefix):] if path.startswith(prefix) else ""
    if not name or "/" in name or Path(name).suffix.lower() not in _SUFFIXES or len(Path(name).stem) != 32:
        raise HTTPException(status_code=400, detail="path ของไฟล์กฎหมายไม่ถูกต้อง")
    return path


class UploadUrlIn(BaseModel):
    filename: str
    size_bytes: int = Field(ge=1)


class SourceIn(BaseModel):
    path: str
    filename: str
    title: str = ""


class SectionsIn(BaseModel):
    page_texts: List[str] = Field(max_length=500)
    title: str = ""


class SourceEdit(BaseModel):
    title: str = Field(min_length=1, max_length=300)


class VerifyIn(BaseModel):
    ids: List[UUID] = Field(min_length=1, max_length=500)
    verified: bool = True


@router.post("/api/v1/legal/sources/upload-url")
def legal_upload_url(
    req: UploadUrlIn,
    profile: Profile = Depends(get_profile),
    client: SupabaseClient = Depends(get_supabase),
    settings: Settings = Depends(get_settings),
):
    if Path(req.filename).suffix.lower() not in _SUFFIXES:
        raise HTTPException(status_code=400, detail="รับเฉพาะไฟล์ PDF")
    if req.size_bytes > settings.max_upload_bytes:
        raise HTTPException(status_code=413, detail=f"ไฟล์ใหญ่เกิน {settings.max_upload_bytes // (1024 * 1024)} MB")
    path = f"{profile.org_id}/legal/{uuid4().hex}.pdf"
    return {"path": path, "upload_url": client.signed_upload_url(settings.source_bucket, path)}


@router.post("/api/v1/legal/sources", status_code=201)
def legal_register_source(
    req: SourceIn,
    user: CurrentUser = Depends(require_supabase_user),
    profile: Profile = Depends(get_profile),
    client: SupabaseClient = Depends(get_supabase),
    settings: Settings = Depends(get_settings),
):
    _check_path(profile, req.path)
    data = client.download(settings.source_bucket, req.path)
    try:
        import pypdfium2 as pdfium
        page_count = len(pdfium.PdfDocument(data))
    except Exception:
        client.remove(settings.source_bucket, req.path)
        raise HTTPException(status_code=422, detail="ไฟล์นี้ไม่ใช่ PDF ที่เปิดได้")
    try:
        row = client.insert("legal_sources", {
            "org_id": profile.org_id, "created_by": user.id, "storage_path": req.path,
            "filename": Path(req.filename).name[:255] or "กฎหมาย.pdf", "title": req.title.strip()[:300],
            "page_count": page_count, "size_bytes": len(data), "sha256": hashlib.sha256(data).hexdigest(),
        })
    except SupabaseError as exc:
        raise _schema_guard(exc)
    return {k: row.get(k) for k in _SOURCE_COLUMNS.split(",")}


@router.post("/api/v1/legal/ocr-page")
async def legal_ocr_page(
    image: UploadFile = File(...),
    page: int = Form(..., ge=1),
    user: CurrentUser = Depends(require_supabase_user),
    settings: Settings = Depends(get_settings),
):
    """AI อ่านหนึ่งหน้า (ภาพที่เบราว์เซอร์เรนเดอร์จากไฟล์) — กฎหมายเป็นเอกสารเปิดเผย ใช้ AI ภายนอกได้"""
    from PIL import Image

    raw = await image.read()
    if len(raw) > 8 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="ภาพหน้าใหญ่เกิน 8 MB")
    try:
        img = Image.open(io.BytesIO(raw))
        img.load()
    except Exception:
        raise HTTPException(status_code=400, detail="ภาพหน้าเอกสารไม่ถูกต้อง")
    config = llm_config(settings)
    if not (config.gemini_api_key or config.anthropic_api_key):
        raise HTTPException(status_code=503, detail="ยังไม่ได้ตั้งค่า AI สำหรับอ่านไฟล์สแกน")
    result = ocr_images_with_llm([img], config, budget_s=55.0)
    if not result.text.strip():
        detail = "; ".join(f"{a.provider}: {a.error}" for a in result.attempts) or "AI อ่านหน้านี้ไม่สำเร็จ"
        logger.warning("legal ocr page %s failed: %s", page, detail)
        raise HTTPException(status_code=502, detail=f"อ่านหน้า {page} ไม่สำเร็จ — {detail}")
    return {"page": page, "text": result.text, "provider": result.provider}


@router.post("/api/v1/legal/sources/{source_id}/sections")
def legal_split_sections(
    source_id: UUID,
    req: SectionsIn,
    user: CurrentUser = Depends(require_supabase_user),
    profile: Profile = Depends(get_profile),
    client: SupabaseClient = Depends(get_supabase),
):
    """แยกข้อความทีละหน้าเป็นข้อ/มาตรา บันทึกเป็นรายการ "ยังไม่ยืนยัน" (ทำได้ครั้งเดียวต่อไฟล์)"""
    try:
        rows = client.select("legal_sources", {"select": "id,title,page_count", "id": f"eq.{source_id}"})
        if not rows:
            raise HTTPException(status_code=404, detail="ไม่พบไฟล์กฎหมาย")
        if client.select("legal_references", {"select": "id", "source_id": f"eq.{source_id}", "limit": "1"}):
            raise HTTPException(status_code=409, detail="ไฟล์นี้แยกเป็นข้อไว้แล้ว")
        if len(req.page_texts) != rows[0]["page_count"]:
            raise HTTPException(status_code=400, detail=f"ต้องส่งข้อความครบ {rows[0]['page_count']} หน้า")
        title = (req.title or rows[0]["title"] or guess_title(req.page_texts) or "กฎหมาย/ระเบียบ").strip()[:300]
        client.update("legal_sources", {"id": f"eq.{source_id}"}, {"title": title, "page_texts": req.page_texts})
        sections = split_sections(req.page_texts)
        created = client.insert_many("legal_references", [{
            "org_id": profile.org_id, "recorded_by": user.id, "title": title, "section": s.label,
            "quote": s.text, "verified": False, "source_id": str(source_id),
            "page_from": s.page_from, "page_to": s.page_to, "chapter": s.chapter,
        } for s in sections]) if sections else []
    except SupabaseError as exc:
        raise _schema_guard(exc)
    return {"title": title, "references": created}


@router.get("/api/v1/legal/sources")
def legal_list_sources(client: SupabaseClient = Depends(get_supabase)):
    try:
        return client.select("legal_sources", {"select": _SOURCE_COLUMNS, "order": "created_at.desc"})
    except SupabaseError as exc:
        raise _schema_guard(exc)


@router.get("/api/v1/legal/sources/{source_id}/file-url")
def legal_source_file_url(
    source_id: UUID,
    client: SupabaseClient = Depends(get_supabase),
    settings: Settings = Depends(get_settings),
):
    try:
        rows = client.select("legal_sources", {"select": "storage_path", "id": f"eq.{source_id}"})
    except SupabaseError as exc:
        raise _schema_guard(exc)
    if not rows:
        raise HTTPException(status_code=404, detail="ไม่พบไฟล์กฎหมาย")
    return {"url": client.signed_download_url(settings.source_bucket, rows[0]["storage_path"], expires_in=3600)}


@router.patch("/api/v1/legal/sources/{source_id}")
def legal_rename_source(source_id: UUID, req: SourceEdit, client: SupabaseClient = Depends(get_supabase)):
    """เปลี่ยนชื่อฉบับ — ใช้กับทุกข้อในไฟล์นั้น (ชื่อที่แสดงในหัวข้อ ข้อกฎหมาย ของบันทึก)"""
    title = req.title.strip()
    if not title:
        raise HTTPException(status_code=422, detail="ชื่อว่างไม่ได้")
    try:
        rows = client.update("legal_sources", {"id": f"eq.{source_id}"}, {"title": title})
        if not rows:
            raise HTTPException(status_code=404, detail="ไม่พบไฟล์กฎหมาย")
        refs = client.update("legal_references", {"source_id": f"eq.{source_id}"}, {"title": title})
    except SupabaseError as exc:
        raise _schema_guard(exc)
    return {"title": title, "updated": len(refs)}


@router.patch("/api/v1/legal/references/verify")
def legal_verify(req: VerifyIn, client: SupabaseClient = Depends(get_supabase)):
    """ยืนยัน (หรือยกเลิกยืนยัน) หลายรายการพร้อมกัน — RLS จำกัดเฉพาะของหน่วยงานตัวเอง"""
    ids = ",".join(str(i) for i in req.ids)
    rows = client.update("legal_references", {"id": f"in.({ids})"}, {"verified": req.verified})
    return {"updated": len(rows)}
