"""คลังตัวอย่างของหน่วย — หนังสือฉบับจริงที่ลงนาม/ส่งออกแล้ว ให้ AI เลียนแบบสำนวน (โหมด Supabase เท่านั้น)

อัปโหลดจากหน้าแรก (เบราว์เซอร์เป็นผู้คุม ไม่ชนเพดานเวลา 120 วินาทีของ Vercel):
  1. POST /api/v1/examples/upload-url      → URL ให้เบราว์เซอร์ PUT ไฟล์ตรงเข้า Storage (<org>/examples/)
  2. POST /api/v1/examples                 → DOCX / PDF ที่มีชั้นข้อความ: แยกส่วนแล้วบันทึกทันที
                                             PDF สแกน: ตอบ {needs_ocr, page_count} ให้เบราว์เซอร์อ่านทีละหน้า
  3. POST /api/v1/examples/ocr-page        → AI อ่านหนึ่งหน้า (ภาพที่เบราว์เซอร์เรนเดอร์ด้วย pdf.js)
  4. POST /api/v1/examples (page_texts)    → แยกส่วนจากข้อความทุกหน้าแล้วบันทึก
จากหน้าแก้ไข: POST /api/v1/examples/from-document {document_id} ("นี่คือฉบับจริง" — กดซ้ำ = อัปเดต)
ตอนร่าง: server/routers/studio.py เรียก example_finder() → เลือก ๒–๓ ฉบับที่ใกล้เรื่องที่สุด (core/style_examples)
"""

from __future__ import annotations

import io
import logging
from pathlib import Path
from typing import List, Optional
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from pydantic import BaseModel, Field

from core.models import DocType, GovDocumentSchema
from core.style_examples import ParsedExample, from_document, keywords_of, parse_example, rank_examples
from server.auth import CurrentUser, Profile, get_profile, get_supabase, require_supabase_user
from server.routers.legal_import import ocr_page_image
from server.settings import Settings, get_settings
from server.supabase import SupabaseClient, SupabaseError

router = APIRouter(tags=["examples"])
logger = logging.getLogger("govdoc.api")

_SUFFIXES = {".pdf", ".docx"}
_LIST_COLUMNS = ("id,origin,document_id,filename,doc_type,subject,doc_number,doc_date,"
                 "part_reason,part_details,part_purpose,page_count,created_at")
_MIGRATION_HINT = ("ฐานข้อมูลยังไม่เห็นตารางคลังตัวอย่าง — ให้ผู้ดูแลรัน supabase/migrations/20261116000010_style_examples.sql "
                   "ทั้งไฟล์ใน SQL Editor (ถ้ารันแล้ว ให้รัน: notify pgrst, 'reload schema';)")


def _schema_guard(exc: SupabaseError) -> HTTPException:
    text = f"{exc.code} {exc.message}"
    logger.warning("style examples database error %s: %s", exc.status, text)
    if any(k in text for k in ("42703", "42P01", "PGRST204", "PGRST205", "does not exist", "Could not find")):
        return HTTPException(status_code=503, detail=_MIGRATION_HINT)
    return HTTPException(status_code=exc.status, detail=exc.message)


def _check_path(profile: Profile, path: str) -> str:
    prefix = f"{profile.org_id}/examples/"
    name = path[len(prefix):] if path.startswith(prefix) else ""
    if not name or "/" in name or Path(name).suffix.lower() not in _SUFFIXES or len(Path(name).stem) != 32:
        raise HTTPException(status_code=400, detail="path ของไฟล์ตัวอย่างไม่ถูกต้อง")
    return path


def _row(ex: ParsedExample) -> dict:
    return {
        "doc_type": ex.doc_type.value, "subject": ex.subject, "doc_number": ex.doc_number, "doc_date": ex.doc_date,
        "part_reason": ex.part_reason[:20000], "part_details": ex.part_details[:20000],
        "part_purpose": ex.part_purpose[:20000],
        "keywords": keywords_of(ex.subject, ex.part_reason, ex.part_details, ex.part_purpose),
    }


def _pdf_text(data: bytes) -> tuple:
    """(จำนวนหน้า, ข้อความในชั้นข้อความ) — ไฟล์สแกนได้ข้อความว่าง/น้อย"""
    import pypdfium2 as pdfium

    pdf = pdfium.PdfDocument(data)
    try:
        texts = []
        for page in pdf:
            tp = page.get_textpage()
            texts.append(tp.get_text_range() or "")
            tp.close()
            page.close()
        return len(texts), "\n\n".join(t.strip() for t in texts)
    finally:
        pdf.close()


def _text_layer_ok(text: str, pages: int) -> bool:
    """ชั้นข้อความใช้ได้: ยาวพอและมีหัวหนังสือที่อ่านออก (PDF จาก Word บางไฟล์ได้สระเพี้ยน → ให้ AI อ่านแทน)"""
    compact = text.replace(" ", "")
    return len(compact) >= 120 * max(1, pages) and ("เรื่อง" in compact) and ("เรียน" in compact)


def _docx_text(data: bytes) -> str:
    from docx import Document

    try:
        d = Document(io.BytesIO(data))
    except Exception:
        raise HTTPException(status_code=422, detail="ไฟล์นี้ไม่ใช่ Word (.docx) ที่เปิดได้")
    lines: List[str] = []
    for table in d.tables:                      # หัวบันทึกข้อความบางแบบอยู่ในตาราง
        for row in table.rows:
            for cell in row.cells:
                for p in cell.paragraphs:
                    if p.text.strip() and p.text.strip() not in lines:
                        lines.append(p.text.strip())
    for p in d.paragraphs:
        lines.append(p.text.strip())
    return "\n".join(lines).replace("​", "")


class UploadUrlIn(BaseModel):
    filename: str
    size_bytes: int = Field(ge=1)


class ExampleIn(BaseModel):
    path: str
    filename: str
    # PDF สแกน: ข้อความที่ AI อ่านทีละหน้า (ส่งรอบที่สอง)
    page_texts: Optional[List[str]] = Field(None, max_length=60)


class FromDocumentIn(BaseModel):
    document_id: UUID


@router.post("/api/v1/examples/upload-url")
def example_upload_url(
    req: UploadUrlIn,
    profile: Profile = Depends(get_profile),
    client: SupabaseClient = Depends(get_supabase),
    settings: Settings = Depends(get_settings),
):
    suffix = Path(req.filename).suffix.lower()
    if suffix not in _SUFFIXES:
        raise HTTPException(status_code=400, detail="รับเฉพาะไฟล์ PDF หรือ Word (.docx)")
    if req.size_bytes > settings.max_upload_bytes:
        raise HTTPException(status_code=413, detail=f"ไฟล์ใหญ่เกิน {settings.max_upload_bytes // (1024 * 1024)} MB")
    path = f"{profile.org_id}/examples/{uuid4().hex}{suffix}"
    return {"path": path, "upload_url": client.signed_upload_url(settings.source_bucket, path)}


@router.post("/api/v1/examples", status_code=201)
def example_register(
    req: ExampleIn,
    user: CurrentUser = Depends(require_supabase_user),
    profile: Profile = Depends(get_profile),
    client: SupabaseClient = Depends(get_supabase),
    settings: Settings = Depends(get_settings),
):
    _check_path(profile, req.path)
    data = client.download(settings.source_bucket, req.path)
    pages = 1
    if req.path.endswith(".docx"):
        text = _docx_text(data)
    else:
        try:
            pages, layer = _pdf_text(data)
        except Exception:
            client.remove(settings.source_bucket, req.path)
            raise HTTPException(status_code=422, detail="ไฟล์นี้ไม่ใช่ PDF ที่เปิดได้")
        if req.page_texts is not None:
            if len(req.page_texts) != pages:
                raise HTTPException(status_code=400, detail=f"ต้องส่งข้อความครบ {pages} หน้า")
            text = "\n\n".join(req.page_texts)
        elif _text_layer_ok(layer, pages):
            text = layer
        else:
            if pages > 60:
                client.remove(settings.source_bucket, req.path)
                raise HTTPException(status_code=413, detail="ไฟล์สแกนเกิน ๖๐ หน้า — แยกเฉพาะหน้าหนังสือก่อน")
            from fastapi.responses import JSONResponse
            return JSONResponse(status_code=200, content={"needs_ocr": True, "page_count": pages, "path": req.path})
    ex = parse_example(text)
    if not ex.usable:
        client.remove(settings.source_bucket, req.path)
        raise HTTPException(status_code=422, detail="อ่านเนื้อความของหนังสือในไฟล์นี้ไม่ได้ — ตรวจว่าเป็นหนังสือราชการที่อ่านออก")
    try:
        row = client.insert("style_examples", {
            "org_id": profile.org_id, "created_by": user.id, "origin": "upload", "storage_path": req.path,
            "filename": Path(req.filename).name[:255] or Path(req.path).name, "page_count": pages, **_row(ex),
        })
    except SupabaseError as exc:
        raise _schema_guard(exc)
    return {k: row.get(k) for k in _LIST_COLUMNS.split(",")}


@router.post("/api/v1/examples/ocr-page")
async def example_ocr_page(
    image: UploadFile = File(...),
    page: int = Form(..., ge=1),
    user: CurrentUser = Depends(require_supabase_user),
    settings: Settings = Depends(get_settings),
):
    """AI อ่านหนึ่งหน้าของหนังสือฉบับจริง (หนังสือชั้นปกติ — ระบบคลาวด์ใช้กับเอกสารชั้นปกติเท่านั้น)"""
    return ocr_page_image(await image.read(), page, settings)


@router.post("/api/v1/examples/from-document")
def example_from_document(
    req: FromDocumentIn,
    user: CurrentUser = Depends(require_supabase_user),
    profile: Profile = Depends(get_profile),
    client: SupabaseClient = Depends(get_supabase),
):
    """"นี่คือฉบับจริง": ใช้ข้อความล่าสุดของร่างในระบบเป็นตัวอย่าง (ร่างเดิมเคยกดแล้ว = อัปเดตตัวเดิม)"""
    try:
        docs = client.select("documents", {"select": "id,workspace", "id": f"eq.{req.document_id}"})
        if not docs:
            raise HTTPException(status_code=404, detail="ไม่พบเอกสาร")
        raw = (docs[0].get("workspace") or {}).get("doc")
        if not raw:
            raise HTTPException(status_code=422, detail="เอกสารนี้ยังไม่มีเนื้อความ")
        ex = from_document(GovDocumentSchema.model_validate(raw))
        if not ex.usable or "[✏️" in (ex.subject + ex.part_reason + ex.part_details + ex.part_purpose):
            raise HTTPException(status_code=422, detail="ร่างนี้ยังมีจุด [✏️ ระบุ...] หรือเนื้อความไม่ครบ — แก้ให้เสร็จก่อนเก็บเป็นตัวอย่าง")
        values = _row(ex)
        existing = client.select("style_examples", {"select": "id", "document_id": f"eq.{req.document_id}"})
        if existing:
            from datetime import datetime, timezone
            rows = client.update("style_examples", {"id": f"eq.{existing[0]['id']}"},
                                 {**values, "updated_at": datetime.now(timezone.utc).isoformat()})
            row, created = rows[0], False
        else:
            row = client.insert("style_examples", {
                "org_id": profile.org_id, "created_by": user.id, "origin": "document",
                "document_id": str(req.document_id), "filename": None, **values,
            })
            created = True
    except SupabaseError as exc:
        raise _schema_guard(exc)
    return {"created": created, "example": {k: row.get(k) for k in _LIST_COLUMNS.split(",")}}


@router.get("/api/v1/examples")
def example_list(
    document_id: Optional[UUID] = Query(None),
    client: SupabaseClient = Depends(get_supabase),
):
    params = {"select": _LIST_COLUMNS, "order": "created_at.desc", "limit": "500"}
    if document_id:
        params["document_id"] = f"eq.{document_id}"
    try:
        return client.select("style_examples", params)
    except SupabaseError as exc:
        raise _schema_guard(exc)


@router.get("/api/v1/examples/{example_id}/file-url")
def example_file_url(
    example_id: UUID,
    client: SupabaseClient = Depends(get_supabase),
    settings: Settings = Depends(get_settings),
):
    try:
        rows = client.select("style_examples", {"select": "storage_path", "id": f"eq.{example_id}"})
    except SupabaseError as exc:
        raise _schema_guard(exc)
    if not rows or not rows[0].get("storage_path"):
        raise HTTPException(status_code=404, detail="ไม่พบไฟล์ของตัวอย่างนี้")
    return {"url": client.signed_download_url(settings.source_bucket, rows[0]["storage_path"], expires_in=3600)}


@router.delete("/api/v1/examples/{example_id}")
def example_delete(
    example_id: UUID,
    client: SupabaseClient = Depends(get_supabase),
    settings: Settings = Depends(get_settings),
):
    """ลบตัวอย่างออกจากคลัง (AI จะไม่ใช้อีก) และลบไฟล์ที่อัปโหลด — ร่าง/ฉบับจริงของเอกสารไม่ถูกแตะ"""
    try:
        rows = client.select("style_examples", {"select": "id,storage_path", "id": f"eq.{example_id}"})
        if not rows:
            raise HTTPException(status_code=404, detail="ไม่พบตัวอย่าง")
        client._request("DELETE", "/rest/v1/style_examples", params={"id": f"eq.{example_id}"})
    except SupabaseError as exc:
        raise _schema_guard(exc)
    path = rows[0].get("storage_path")
    if path:
        try:
            client.remove(settings.source_bucket, path)
        except SupabaseError as exc:          # ไฟล์ค้างไม่กระทบการร่าง — บันทึกไว้
            logger.warning("example file not removed %s: %s", path, exc.message)
    return {"id": str(example_id), "deleted": True}


# ---------------------------------------------------------------- ใช้ตอนร่าง
def example_finder(client: SupabaseClient):
    """ฟังก์ชันหาตัวอย่างสำหรับ core.studio.start_draft — ดึงเฉพาะคำสำคัญมาคัดก่อน แล้วค่อยดึงเนื้อความ ๒–๓ ฉบับ"""

    def find(context: str, doc_type: DocType) -> List[dict]:
        try:
            light = client.select("style_examples", {
                "select": "id,subject,keywords", "doc_type": f"eq.{doc_type.value}",
                "order": "created_at.desc", "limit": "500",
            })
        except SupabaseError as exc:
            logger.warning("style examples unavailable (%s): %s", exc.status, exc.message)
            return []
        picked = rank_examples(context, light)
        if not picked:
            return []
        ids = ",".join(str(r["id"]) for r, _ in picked)
        full = {str(r["id"]): r for r in client.select("style_examples", {
            "select": "id,doc_type,subject,part_reason,part_details,part_purpose", "id": f"in.({ids})"})}
        return [{**full[str(r["id"])], "score": score} for r, score in picked if str(r["id"]) in full]

    return find
