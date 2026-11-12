"""
test_phase10_hierarchy.py — ทดสอบการสร้างชุดบันทึกตามลำดับชั้น (P3)
"""

import pytest

from core.hierarchy import (
    apply_hierarchy_role,
    build_hierarchy_chain,
    roles_from_profile,
)
from core.models import MemoHierarchyLevel, UserProfileSchema
from core.templates_library import PRESET_TEMPLATES


@pytest.fixture
def base_doc():
    return PRESET_TEMPLATES["bma_general_memo"].schema.model_copy(deep=True)


@pytest.fixture
def profile():
    return UserProfileSchema()


def test_roles_from_profile_cover_four_levels(profile):
    roles = roles_from_profile(profile)
    levels = [role.level for role in roles]
    assert levels == [
        MemoHierarchyLevel.SECTION_TO_DIV,
        MemoHierarchyLevel.DIV_TO_DEPT,
        MemoHierarchyLevel.DEPT_TO_PERM_SEC,
        MemoHierarchyLevel.FINAL_APPROVAL,
    ]
    assert roles[0].recipient.startswith("ผู้อำนวยการ")
    assert roles[2].recipient == "ปลัดกรุงเทพมหานคร"
    assert roles[3].recipient == "ผู้ว่าราชการกรุงเทพมหานคร"


def test_build_default_chain_three_levels_descending(base_doc, profile):
    chain = build_hierarchy_chain(base_doc, profile)

    assert len(chain) == 3
    assert [item.role.level for item in chain] == [
        MemoHierarchyLevel.DEPT_TO_PERM_SEC,
        MemoHierarchyLevel.DIV_TO_DEPT,
        MemoHierarchyLevel.SECTION_TO_DIV,
    ]

    top = chain[0].document
    assert top.salutation == "เรียน ปลัดกรุงเทพมหานคร"
    assert "นำเรียนผู้ว่าราชการกรุงเทพมหานคร" in top.memo_request
    assert top.signatory_name == profile.signatory_name

    middle = chain[1].document
    assert middle.salutation == f"เรียน {profile.signatory_position}"
    assert middle.signatory_position.startswith("ผู้อำนวยการกอง")

    bottom = chain[2].document
    assert bottom.salutation.startswith("เรียน ผู้อำนวยการกอง")
    assert bottom.signatory_position.startswith("หัวหน้า")


def test_chain_documents_are_independent(base_doc, profile):
    chain = build_hierarchy_chain(base_doc, profile)
    chain[0].document.subject = "แก้เฉพาะฉบับบน"
    assert chain[1].document.subject != "แก้เฉพาะฉบับบน"
    assert base_doc.subject != "แก้เฉพาะฉบับบน"


def test_apply_hierarchy_role_updates_only_copy(base_doc, profile):
    role = roles_from_profile(profile)[2]  # สำนัก -> ปลัด
    updated = apply_hierarchy_role(base_doc, role)

    assert updated.salutation == "เรียน ปลัดกรุงเทพมหานคร"
    assert updated.memo_hierarchy_level == MemoHierarchyLevel.DEPT_TO_PERM_SEC
    assert updated.signatory_position == profile.signatory_position
    assert base_doc.salutation != updated.salutation


def test_include_final_approval_adds_fourth_memo(base_doc, profile):
    chain = build_hierarchy_chain(base_doc, profile, include_final_approval=True)
    assert len(chain) == 4
    assert chain[0].role.level == MemoHierarchyLevel.FINAL_APPROVAL
    assert chain[0].document.salutation == "เรียน ผู้ว่าราชการกรุงเทพมหานคร"
