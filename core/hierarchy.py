"""
hierarchy.py — สร้างชุดบันทึกข้อความตามลำดับชั้นการเสนอ (Hierarchy Chain)

รองรับการสร้าง 3 ฉบับจากต้นเรื่องเดียว:
  ระดับกลุ่มงาน -> ผอ.กอง
  ระดับกอง -> ผอ.สำนัก
  ระดับสำนัก -> ปลัดกรุงเทพมหานคร
และอัปเดต "เรียน/ประโยคลงท้าย/ผู้ลงนาม" เมื่อผู้ใช้เปลี่ยนผู้รับภายหลัง
"""

from dataclasses import dataclass
from typing import List, Optional

from pydantic import BaseModel

from core.models import (
    GovDocumentSchema,
    MemoHierarchyLevel,
    UserProfileSchema,
)


class HierarchyRole(BaseModel):
    level: MemoHierarchyLevel
    label: str
    recipient: str
    signatory_name: str
    signatory_position: str
    contact_dept: str


@dataclass
class HierarchyMemo:
    role: HierarchyRole
    document: GovDocumentSchema


def _section_head_position(profile: UserProfileSchema) -> str:
    name = (profile.section_name or "กลุ่มงาน").strip()
    return name if name.startswith("หัวหน้า") else f"หัวหน้า{name}"


def _division_head_position(profile: UserProfileSchema) -> str:
    name = (profile.division_name or "กอง").strip()
    return name if name.startswith("ผู้อำนวยการ") else f"ผู้อำนวยการ{name}"


def _dept_head_position(profile: UserProfileSchema) -> str:
    return profile.signatory_position or f"ผู้อำนวยการ{profile.dept_name}"


def roles_from_profile(profile: UserProfileSchema) -> List[HierarchyRole]:
    """สร้างรายการผู้รับ/ผู้ลงนามตามโปรไฟล์หน่วยงาน"""
    section_pos = _section_head_position(profile)
    division_pos = _division_head_position(profile)
    dept_pos = _dept_head_position(profile)

    return [
        HierarchyRole(
            level=MemoHierarchyLevel.SECTION_TO_DIV,
            label="📁 กลุ่มงาน → ผอ.กอง",
            recipient=division_pos,
            signatory_name="[✏️ ชื่อหัวหน้ากลุ่มงาน]",
            signatory_position=section_pos,
            contact_dept=profile.section_name or profile.division_name,
        ),
        HierarchyRole(
            level=MemoHierarchyLevel.DIV_TO_DEPT,
            label="🏢 กอง → ผอ.สำนัก",
            recipient=dept_pos,
            signatory_name="[✏️ ชื่อผู้อำนวยการกอง]",
            signatory_position=division_pos,
            contact_dept=profile.division_name or profile.dept_name,
        ),
        HierarchyRole(
            level=MemoHierarchyLevel.DEPT_TO_PERM_SEC,
            label="🏛️ สำนัก → ปลัดกรุงเทพมหานคร",
            recipient="ปลัดกรุงเทพมหานคร",
            signatory_name=profile.signatory_name,
            signatory_position=dept_pos,
            contact_dept=profile.dept_name,
        ),
        HierarchyRole(
            level=MemoHierarchyLevel.FINAL_APPROVAL,
            label="✍️ ปลัด → ผู้ว่าราชการกรุงเทพมหานคร",
            recipient="ผู้ว่าราชการกรุงเทพมหานคร",
            signatory_name="[✏️ ชื่อปลัดกรุงเทพมหานคร]",
            signatory_position="ปลัดกรุงเทพมหานคร",
            contact_dept="สำนักปลัดกรุงเทพมหานคร",
        ),
    ]


def apply_hierarchy_role(
    document: GovDocumentSchema, role: HierarchyRole
) -> GovDocumentSchema:
    """อัปเดตสำเนาเอกสารให้ส่งถึงผู้รับตามบทบาท (ไม่แก้เอกสารต้นฉบับ)"""
    doc = document.model_copy(deep=True)
    doc.salutation = f"เรียน {role.recipient}"
    doc.memo_request = role.level.default_closing(target_title=role.recipient)
    doc.memo_hierarchy_level = role.level
    doc.signatory_name = role.signatory_name
    doc.signatory_position = role.signatory_position
    doc.contact_dept = role.contact_dept
    return doc


def build_hierarchy_chain(
    document: GovDocumentSchema,
    profile: UserProfileSchema,
    include_final_approval: bool = False,
    levels: Optional[List[MemoHierarchyLevel]] = None,
) -> List[HierarchyMemo]:
    """
    สร้างชุดบันทึกตามลำดับชั้นจากเอกสารตั้งต้น
    ค่าเริ่มต้นเรียงจากระดับสูงไปต่ำ (เหมือนไฟล์จริง: ปลัด -> ผอ.สำนัก -> ผอ.กอง)
    """
    roles = {role.level: role for role in roles_from_profile(profile)}
    if levels is None:
        levels = [
            MemoHierarchyLevel.DEPT_TO_PERM_SEC,
            MemoHierarchyLevel.DIV_TO_DEPT,
            MemoHierarchyLevel.SECTION_TO_DIV,
        ]
        if include_final_approval:
            levels.insert(0, MemoHierarchyLevel.FINAL_APPROVAL)

    chain: List[HierarchyMemo] = []
    for level in levels:
        role = roles.get(level)
        if role is None:
            continue
        chain.append(HierarchyMemo(role=role, document=apply_hierarchy_role(document, role)))
    return chain
