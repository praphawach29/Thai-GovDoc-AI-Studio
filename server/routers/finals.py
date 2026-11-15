"""ฉบับจริง: ไฟล์ Word/PDF ที่แก้เสร็จแล้วอัปโหลดกลับเข้าระบบ (โหมด Supabase)

ขั้นตอน (ไฟล์ไม่ผ่าน Vercel ซึ่งรับ request ได้ราว 4.5 MB):
  1. POST /api/v1/documents/{id}/finals/upload-url  → URL ให้เบราว์เซอร์ PUT ไฟล์ตรงเข้า Storage
  2. POST /api/v1/documents/{id}/finals             → เซิร์ฟเวอร์ตรวจไฟล์ อ่าน ที่/วันที่/เรื่อง แล้วบันทึกเป็นฉบับที่ n
  3. GET  /api/v1/documents/{id}/finals             → รายการฉบับจริงทั้งหมด (ล่าสุดก่อน)
  4. GET  /api/v1/documents/{id}/finals/{file_id}/download → URL ดาวน์โหลดชั่วคราว 5 นาที
ไฟล์ถูกเก็บตามที่ได้รับทุกไบต์ แก้/ลบไม่ได้ อัปโหลดใหม่ = ฉบับถัดไป
"""

import logging
import re
from pathlib import Path
from typing import Optional
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from core.final_file import FINAL_SUFFIXES, FinalFileError, inspect_final_file
from server.auth import Profile, get_profile, get_supabase
from server.settings import Settings, get_settings
from server.source_store import MIME_BY_SUFFIX
from server.supabase import SupabaseClient

router = APIRouter(tags=["finals"])
logger = logging.getLogger("govdoc.api")

_LIST_COLUMNS = "id,revision,filename,mime,size_bytes,sha256,doc_number,doc_date,subject,note,uploaded_by,created_at"


class FinalUploadUrlRequest(BaseModel):
    filename: str
    size_bytes: int = Field(ge=1)


class FinalRegisterRequest(BaseModel):
    path: str
    filename: str
    note: Optional[str] = Field(default=None, max_length=500)


def _suffix(filename: str) -> str:
    suffix = Path(filename or "").suffix.lower()
    if suffix not in FINAL_SUFFIXES:
        raise HTTPException(status_code=400, detail="รับเฉพาะไฟล์ Word (.docx) หรือ PDF")
    return suffix


def _require_document(client: SupabaseClient, document_id: UUID) -> None:
    if not client.select("documents", {"select": "id", "id": f"eq.{document_id}"}):
        raise HTTPException(status_code=404, detail="ไม่พบเอกสาร")


def _check_path(profile: Profile, path: str) -> str:
    """รับเฉพาะ path ที่ระบบออกให้: <org_id>/finals/<uuid hex>.docx|.pdf"""
    m = re.fullmatch(r"([0-9a-f-]{36})/finals/[0-9a-f]{32}(\.docx|\.pdf)", path or "")
    if not m or m.group(1) != profile.org_id:
        raise HTTPException(status_code=400, detail="path ของไฟล์ฉบับจริงไม่ถูกต้อง")
    return m.group(2)


def _discard(client: SupabaseClient, settings: Settings, path: str) -> None:
    """ลบไฟล์ที่ตรวจไม่ผ่าน (ยังไม่ได้บันทึกเป็นฉบับจริง) — ลบไม่สำเร็จก็ไม่เป็นไร"""
    try:
        client.remove(settings.source_bucket, path)
    except Exception:
        logger.warning("could not remove rejected final upload %s", path)


@router.post("/api/v1/documents/{document_id}/finals/upload-url")
def final_upload_url(
    document_id: UUID,
    req: FinalUploadUrlRequest,
    profile: Profile = Depends(get_profile),
    client: SupabaseClient = Depends(get_supabase),
    settings: Settings = Depends(get_settings),
):
    suffix = _suffix(req.filename)
    if req.size_bytes > settings.max_upload_bytes:
        raise HTTPException(status_code=413, detail=f"ไฟล์ใหญ่เกิน {settings.max_upload_bytes // (1024 * 1024)} MB")
    _require_document(client, document_id)
    path = f"{profile.org_id}/finals/{uuid4().hex}{suffix}"
    return {"path": path, "upload_url": client.signed_upload_url(settings.source_bucket, path),
            "content_type": MIME_BY_SUFFIX[suffix]}


@router.post("/api/v1/documents/{document_id}/finals", status_code=201)
def register_final(
    document_id: UUID,
    req: FinalRegisterRequest,
    profile: Profile = Depends(get_profile),
    client: SupabaseClient = Depends(get_supabase),
    settings: Settings = Depends(get_settings),
):
    suffix = _check_path(profile, req.path)
    if _suffix(req.filename) != suffix:
        raise HTTPException(status_code=400, detail="นามสกุลไฟล์ไม่ตรงกับที่ขออัปโหลด")
    data = client.download(settings.source_bucket, req.path)
    try:
        if len(data) > settings.max_upload_bytes:
            raise FinalFileError("ไฟล์ใหญ่เกินกำหนด")
        info = inspect_final_file(data, req.filename)
    except FinalFileError as exc:
        _discard(client, settings, req.path)
        raise HTTPException(status_code=422, detail=str(exc))
    row = client.rpc("register_final_file", {
        "p_document_id": str(document_id),
        "p_storage_path": req.path,
        "p_filename": Path(req.filename).name,
        "p_mime": MIME_BY_SUFFIX[suffix],
        "p_size_bytes": info.size_bytes,
        "p_sha256": info.sha256,
        "p_extracted_text": info.text or None,
        "p_doc_number": info.doc_number,
        "p_doc_date": info.doc_date,
        "p_subject": info.subject,
        "p_note": (req.note or "").strip() or None,
    })
    row = row[0] if isinstance(row, list) else row
    return {k: row.get(k) for k in _LIST_COLUMNS.split(",")}


@router.get("/api/v1/documents/{document_id}/finals")
def list_finals(document_id: UUID, client: SupabaseClient = Depends(get_supabase)):
    return client.select("final_files", {
        "select": _LIST_COLUMNS, "document_id": f"eq.{document_id}", "order": "revision.desc",
    })


@router.get("/api/v1/documents/{document_id}/finals/{file_id}/download")
def download_final(
    document_id: UUID,
    file_id: UUID,
    client: SupabaseClient = Depends(get_supabase),
    settings: Settings = Depends(get_settings),
):
    rows = client.select("final_files", {
        "select": "storage_path,filename", "id": f"eq.{file_id}", "document_id": f"eq.{document_id}",
    })
    if not rows:
        raise HTTPException(status_code=404, detail="ไม่พบไฟล์ฉบับจริง")
    return {"url": client.signed_download_url(settings.source_bucket, rows[0]["storage_path"], rows[0]["filename"])}
