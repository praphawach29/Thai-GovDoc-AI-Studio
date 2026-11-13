"""
legal_sources.py — คลังข้อกฎหมาย/ระเบียบที่ผู้ใช้ดูแลเอง (เพิ่ม/แก้ไข/ตรวจยืนยัน)
ข้อมูลถูกเก็บใน JSON เพื่อให้แก้ไขและตรวจสอบแหล่งได้ โดยไม่ hardcode ไว้ในโค้ด
"""

import json
from datetime import datetime
from pathlib import Path
from typing import List, Optional
from uuid import uuid4

from pydantic import BaseModel, Field

from core.models import DocType


class LegalReference(BaseModel):
    """รายการข้อกฎหมาย/ระเบียบ พร้อมข้อมูลแหล่งอ้างอิงและสถานะตรวจยืนยัน"""

    id: str = Field(default_factory=lambda: uuid4().hex[:12])
    title: str = ""
    section: Optional[str] = None  # มาตรา/ข้อ
    quote: str = ""
    url: Optional[str] = None
    effective_date: Optional[str] = None
    verified: bool = False
    recorded_by: str = ""
    recorded_at: str = Field(default_factory=lambda: datetime.now().strftime("%Y-%m-%d %H:%M"))


LEGAL_LIBRARY_PATH = Path(__file__).resolve().parent.parent / "data" / "legal_references.json"


class LegalLibrary:
    """โหลด/บันทึก/เพิ่ม/แก้ไข/ลบ รายการข้อกฎหมายใน JSON"""

    def __init__(self, path: Optional[Path] = None):
        self.path = Path(path) if path else LEGAL_LIBRARY_PATH

    def _load(self) -> List[LegalReference]:
        if not self.path.exists():
            return []
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            return [LegalReference.model_validate(item) for item in data]
        except Exception:
            return []

    def _save(self, items: List[LegalReference]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps([item.model_dump() for item in items], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def list(self, verified_only: bool = False) -> List[LegalReference]:
        items = self._load()
        if verified_only:
            return [item for item in items if item.verified]
        return items

    def add(self, ref: LegalReference) -> LegalReference:
        items = self._load()
        items.append(ref)
        self._save(items)
        return ref

    def update(self, ref_id: str, **fields) -> Optional[LegalReference]:
        items = self._load()
        for item in items:
            if item.id == ref_id:
                for key, value in fields.items():
                    if key in LegalReference.model_fields and value is not None:
                        setattr(item, key, value)
                item.recorded_at = datetime.now().strftime("%Y-%m-%d %H:%M")
                self._save(items)
                return item
        return None

    def delete(self, ref_id: str) -> bool:
        items = self._load()
        remaining = [item for item in items if item.id != ref_id]
        if len(remaining) == len(items):
            return False
        self._save(remaining)
        return True


def format_legal_citation(ref: LegalReference) -> str:
    """สร้างข้อความอ้างอิงสำหรับใส่ลงในเอกสาร"""
    parts = [ref.title.strip()]
    if ref.section and ref.section.strip():
        parts.append(ref.section.strip())
    citation = " ".join(parts)
    if ref.quote and ref.quote.strip():
        citation += f"\n{ref.quote.strip()}"
    return citation
