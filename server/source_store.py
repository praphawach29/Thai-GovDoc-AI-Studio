"""source_store.py — เก็บไฟล์ต้นเรื่องใน Supabase Storage + ตาราง source_files (โหมด Supabase)"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Optional, Tuple
from uuid import uuid4

from fastapi import HTTPException

from core.models import SecretLevel, SourceDocumentContext
from server.auth import CurrentUser, Profile
from server.deps import ALLOWED_SOURCE_SUFFIXES
from server.settings import Settings
from server.supabase import SupabaseClient

MIME_BY_SUFFIX = {
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".txt": "text/plain",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".tif": "image/tiff",
    ".tiff": "image/tiff",
}
# path ที่ระบบออกให้เท่านั้น: <org_id>/<uuid hex>.<นามสกุลที่อนุญาต>
_PATH_RE = re.compile(r"^([0-9a-f-]{36})/[0-9a-f]{32}(\.[a-z]+)$")


def check_suffix(filename: str) -> str:
    suffix = Path(filename or "").suffix.lower()
    if suffix not in ALLOWED_SOURCE_SUFFIXES:
        raise HTTPException(status_code=400, detail=f"ไม่รองรับไฟล์ชนิด {suffix or '(ไม่มีนามสกุล)'}")
    return suffix


def new_storage_path(profile: Profile, filename: str) -> str:
    return f"{profile.org_id}/{uuid4().hex}{check_suffix(filename)}"


def check_storage_path(profile: Profile, path: str) -> str:
    """รับเฉพาะ path ในโฟลเดอร์หน่วยงานตัวเองที่ระบบออกให้ (กัน path แปลก ๆ จากผู้เรียก)"""
    m = _PATH_RE.match(path or "")
    if not m or m.group(1) != profile.org_id or m.group(2) not in ALLOWED_SOURCE_SUFFIXES:
        raise HTTPException(status_code=400, detail="path ของไฟล์ต้นเรื่องไม่ถูกต้อง")
    return path


def to_temp_file(data: bytes, suffix: str, settings: Settings) -> Path:
    if len(data) > settings.max_upload_bytes:
        raise HTTPException(status_code=413, detail="ไฟล์ใหญ่เกินกำหนด")
    settings.upload_dir.mkdir(parents=True, exist_ok=True)
    target = settings.upload_dir / f"{uuid4().hex}{suffix}"
    target.write_bytes(data)
    return target


def download_source(client: SupabaseClient, settings: Settings, profile: Profile, path: str) -> Tuple[bytes, Path]:
    check_storage_path(profile, path)
    data = client.download(settings.source_bucket, path)
    return data, to_temp_file(data, Path(path).suffix, settings)


def record_source_file(
    client: SupabaseClient,
    user: CurrentUser,
    profile: Profile,
    *,
    path: str,
    filename: str,
    data: bytes,
    ctx: Optional[SourceDocumentContext],
    secret: SecretLevel,
    document_id: Optional[str] = None,
) -> str:
    row = client.insert("source_files", {
        "org_id": profile.org_id,
        "uploaded_by": user.id,
        "storage_path": path,
        "filename": Path(filename or "").name[:255] or Path(path).name,
        "mime": MIME_BY_SUFFIX.get(Path(path).suffix, ""),
        "size_bytes": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
        "extracted_text": (ctx.raw_text if ctx and not ctx.extraction_failed else None),
        "ocr_engine": ctx.ocr_engine_used if ctx else None,
        "secret_level": secret.value,
        "document_id": document_id,
    })
    return row["id"]
