"""signers.py — รายชื่อผู้ลงนามประจำหน่วยงาน (ตาราง org_signers) และการเติมชื่อผู้ลงนามลงร่าง

กติกาการเติม (ไม่ทับชื่อที่มีอยู่แล้ว):
  1. ช่องผู้ลงนามที่ชื่อยังว่าง/เป็น placeholder และตำแหน่งตรงกับคนในรายชื่อ → ใช้คนนั้น
     (เทียบตำแหน่งแบบตัดช่องว่างซ้ำ; ตำแหน่งหลายบรรทัดเทียบทั้งข้อความก่อน แล้วจึงเทียบบรรทัดแรก)
  2. ร่างใหม่ (use_default): ช่องผู้ลงนามหลักที่ยังว่าง (ช่องสุดท้ายที่ไม่ใช่ผู้เสนอเรื่อง) → ผู้ลงนามเริ่มต้น
  ผู้เสนอเรื่อง (is_author) ใช้ชื่อของผู้ใช้ที่ล็อกอินเสมอ ไม่เติมจากรายชื่อ
"""

from __future__ import annotations

import re
from typing import Iterable, List, Optional, Sequence

from pydantic import BaseModel, Field

from core.models import GovDocumentSchema, Signer

_PLACEHOLDER = "[✏️"
_SPACES = re.compile(r"\s+")


class OrgSigner(BaseModel):
    """ผู้ลงนามหนึ่งคนในรายชื่อของหน่วยงาน"""
    id: str = ""
    full_name: str = Field(min_length=1, max_length=200, description="ชื่อเต็ม ไม่ต้องมีวงเล็บ เช่น นายสมชาย ใจดี")
    position: str = Field(default="", max_length=600, description="ตำแหน่ง (หลายบรรทัดได้)")
    stamp: bool = False
    is_default: bool = False
    sort_order: int = 0

    def display_name(self) -> str:
        """ชื่อในวงเล็บแบบที่พิมพ์ใต้ลายมือชื่อ"""
        return f"({clean_name(self.full_name)})"

    def clean_position(self) -> str:
        return clean_position(self.position)


def clean_name(name: str) -> str:
    """ตัดวงเล็บครอบและช่องว่างเกิน — เก็บชื่อแบบไม่มีวงเล็บ"""
    s = _SPACES.sub(" ", (name or "").strip())
    if s.startswith("(") and s.endswith(")"):
        s = s[1:-1].strip()
    return s


def clean_position(position: str) -> str:
    """ตำแหน่งหลายบรรทัด: ตัดช่องว่างต่อบรรทัด ทิ้งบรรทัดว่าง"""
    lines = [_SPACES.sub(" ", ln).strip() for ln in (position or "").replace("\r", "").split("\n")]
    return "\n".join(ln for ln in lines if ln)


def _key(text: str) -> str:
    return _SPACES.sub("", text or "")


def is_blank_name(name: Optional[str]) -> bool:
    """ชื่อผู้ลงนามที่ยังต้องกรอก (ว่าง หรือมี placeholder)"""
    s = (name or "").replace(" ", " ").strip().strip("()").strip()
    return not s or _PLACEHOLDER in s


def match_position(roster: Sequence[OrgSigner], position: str) -> Optional[OrgSigner]:
    """คนในรายชื่อที่ตำแหน่งตรงกับช่องผู้ลงนาม (ทั้งข้อความก่อน แล้วบรรทัดแรก)"""
    want = _key(position)
    if not want or _PLACEHOLDER in position:
        return None
    for s in roster:
        if _key(s.position) == want:
            return s
    first = _key(clean_position(position).split("\n")[0])
    for s in roster:
        if _key(s.clean_position().split("\n")[0]) == first:
            return s
    return None


def default_signer(roster: Iterable[OrgSigner]) -> Optional[OrgSigner]:
    return next((s for s in roster if s.is_default), None)


def _take(slot: Signer, person: OrgSigner) -> None:
    slot.name = person.display_name()
    slot.position = person.clean_position() or slot.position
    slot.stamp = slot.stamp or person.stamp


def fill_from_roster(signers: List[Signer], roster: Sequence[OrgSigner], use_default: bool = False) -> List[Signer]:
    """เติมชื่อในช่องผู้ลงนามที่ยังว่าง (แก้ในรายการเดิมและคืนรายการเดิม)"""
    roster = list(roster)
    if not roster:
        return signers
    used = set()
    for slot in signers:
        if slot.is_author or not is_blank_name(slot.name):
            continue
        person = match_position(roster, slot.position)
        if person is not None:
            _take(slot, person)
            used.add(person.id or person.full_name)
    default = default_signer(roster) if use_default else None
    if default is not None and (default.id or default.full_name) not in used:
        target = next((s for s in reversed(signers) if not s.is_author and is_blank_name(s.name)), None)
        if target is not None:
            _take(target, default)
    return signers


def fill_document_signers(doc: GovDocumentSchema, roster: Sequence[OrgSigner],
                          use_default: bool = False) -> GovDocumentSchema:
    """เติมผู้ลงนามของเอกสารทั้งฉบับ (ใช้กับหนังสือภายนอก/เอกสารที่ไม่ผ่านหน่วยออกหนังสือ)

    ผู้ลงนามหลักของหนังสือภายนอกที่มาจากโปรไฟล์ในเครื่อง: ถ้าตำแหน่งตรงกับคนในรายชื่อใช้คนนั้น,
    ไม่งั้นร่างใหม่ใช้ผู้ลงนามเริ่มต้น
    """
    roster = list(roster)
    if not roster:
        return doc
    updated = doc.model_copy(deep=True)
    main = Signer(name=updated.signatory_name, position=updated.signatory_position, stamp=updated.signatory_stamp)
    person = match_position(roster, main.position)
    if person is None and use_default:
        person = default_signer(roster)
    if person is not None and (is_blank_name(main.name) or use_default):
        _take(main, person)
    others = [c.model_copy() for c in (updated.co_signers or [])]
    fill_from_roster(others, [p for p in roster if p is not person])
    updated.signatory_name, updated.signatory_position, updated.signatory_stamp = main.name, main.position, main.stamp
    updated.co_signers = others or updated.co_signers
    return updated
