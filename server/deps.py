"""deps.py — ของที่ router ใช้ร่วมกัน (ทะเบียน, การรับไฟล์, การกรองข้อมูลจากผู้เรียก)"""

from functools import lru_cache
from pathlib import Path
from uuid import uuid4

from fastapi import Depends, HTTPException, UploadFile

from core.models import GovDocumentSchema
from core.registry import DocumentRegistry
from server.settings import Settings, get_settings

ALLOWED_SOURCE_SUFFIXES = {".pdf", ".docx", ".txt", ".png", ".jpg", ".jpeg", ".tif", ".tiff"}


@lru_cache
def _registry_for(db_path: str) -> DocumentRegistry:
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    return DocumentRegistry(db_path=db_path)


def get_registry(settings: Settings = Depends(get_settings)) -> DocumentRegistry:
    """ทะเบียนรับ-ส่ง (เทสต์แทนที่ได้ด้วย app.dependency_overrides)"""
    return _registry_for(str(settings.registry_db_path))


async def save_upload(file: UploadFile, settings: Settings) -> Path:
    """ตรวจชนิด/ขนาดไฟล์ แล้วบันทึกด้วยชื่อที่ระบบสร้างเอง

    ห้ามใช้ชื่อไฟล์จากผู้ใช้เป็น path (เช่น "../core/api.py" จะเขียนทับไฟล์นอกโฟลเดอร์อัปโหลด)
    """
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in ALLOWED_SOURCE_SUFFIXES:
        raise HTTPException(status_code=400, detail=f"ไม่รองรับไฟล์ชนิด {suffix or '(ไม่มีนามสกุล)'}")
    data = await file.read(settings.max_upload_bytes + 1)
    if len(data) > settings.max_upload_bytes:
        limit_mb = settings.max_upload_bytes // (1024 * 1024)
        raise HTTPException(status_code=413, detail=f"ไฟล์ใหญ่เกิน {limit_mb} MB")
    settings.upload_dir.mkdir(parents=True, exist_ok=True)
    target = settings.upload_dir / f"{uuid4().hex}{suffix}"
    target.write_bytes(data)
    return target


def without_server_paths(doc: GovDocumentSchema) -> GovDocumentSchema:
    """ไม่ให้ผู้เรียก API ชี้ไฟล์บนเซิร์ฟเวอร์ผ่าน signature_image_path

    มิฉะนั้นใครก็ฝังลายมือชื่อ/ไฟล์ภาพใดก็ได้บนเครื่องลงในเอกสาร
    การแนบลายมือชื่อจะทำผ่านระบบผู้ใช้/Storage ในขั้นถัดไป
    """
    if doc.signature_image_path:
        return doc.model_copy(update={"signature_image_path": None})
    return doc
