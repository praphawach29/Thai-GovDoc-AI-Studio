"""
profile_manager.py — ระบบจัดการโปรไฟล์หน่วยงานและผู้มีอำนาจลงนามของผู้ใช้งาน
(User Organization Profile Manager)
บันทึกและโหลดค่าการตั้งค่าหน่วยงานอย่างถาวรจาก data/user_profile.json
"""

import json
from pathlib import Path
from typing import Optional

from core.models import UserProfileSchema, MemoHierarchyLevel


PROFILE_FILE = Path(__file__).resolve().parent.parent / "data" / "user_profile.json"


def get_default_profile() -> UserProfileSchema:
    """คืนค่าโปรไฟล์เริ่มต้น (หน่วยงานกรุงเทพมหานคร — กองการกีฬา)"""
    return UserProfileSchema(
        dept_name="สำนักวัฒนธรรม กีฬา และการท่องเที่ยว",
        division_name="กองการกีฬา",
        section_name="กลุ่มงานส่งเสริมกีฬา",
        department_full="สำนักวัฒนธรรม กีฬา และการท่องเที่ยว (กองการกีฬา โทร. ๐ ๒๒๔๖ ๘๐๗๙ โทรสาร ๐ ๒๒๔๖ ๐๒๘๒)",
        doc_origin_code="กท ๐๒๐๔/",
        signatory_name="(นายสิงห์ ลิ้มพิรัตน์)",
        signatory_position="ผู้อำนวยการสำนักวัฒนธรรม กีฬา และการท่องเที่ยว",
        contact_dept="กองการกีฬา (กลุ่มงานส่งเสริมกีฬา)",
        contact_tel="๐ ๒๒๔๖ ๘๐๗๙",
        contact_fax="๐ ๒๒๔๖ ๐๒๘๒",
        contact_email="sports.bma@bangkok.go.th",
        hierarchy_default=MemoHierarchyLevel.DEPT_TO_PERM_SEC
    )


def get_user_profile() -> UserProfileSchema:
    """
    โหลดโปรไฟล์หน่วยงานของผู้ใช้จาก data/user_profile.json
    หากยังไม่มีไฟล์ จะบันทึกค่าเริ่มต้นแล้วส่งคืน
    """
    if not PROFILE_FILE.exists():
        default_prof = get_default_profile()
        save_user_profile(default_prof)
        return default_prof

    try:
        data = json.loads(PROFILE_FILE.read_text(encoding="utf-8"))
        return UserProfileSchema(**data)
    except Exception as e:
        print(f"Error loading user profile: {e}, using default")
        return get_default_profile()


def save_user_profile(profile: UserProfileSchema) -> None:
    """
    บันทึกโปรไฟล์หน่วยงานลงไฟล์ data/user_profile.json
    """
    PROFILE_FILE.parent.mkdir(parents=True, exist_ok=True)
    PROFILE_FILE.write_text(
        profile.model_dump_json(indent=2),
        encoding="utf-8"
    )


def reset_to_default_profile() -> UserProfileSchema:
    """รีเซ็ตโปรไฟล์กลับเป็นค่าเริ่มต้น"""
    default_prof = get_default_profile()
    save_user_profile(default_prof)
    return default_prof

