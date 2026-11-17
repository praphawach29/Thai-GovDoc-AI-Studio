"""
profile_manager.py — ระบบจัดการโปรไฟล์หน่วยงานและผู้มีอำนาจลงนามของผู้ใช้งาน
(User Organization Profile Manager)
บันทึกและโหลดค่าการตั้งค่าหน่วยงานอย่างถาวรจาก data/user_profile.json
"""

import os
import json
import tempfile
from pathlib import Path
from typing import Optional

from core.models import UserProfileSchema, MemoHierarchyLevel

_ROOT_DIR = Path(__file__).resolve().parent.parent
if os.environ.get("VERCEL") or not os.access(_ROOT_DIR, os.W_OK):
    PROFILE_FILE = Path(tempfile.gettempdir()) / "data" / "user_profile.json"
else:
    PROFILE_FILE = _ROOT_DIR / "data" / "user_profile.json"
# ไฟล์ที่มากับโค้ด: บนคลาวด์ (เขียนได้เฉพาะ /tmp) ใช้อ่านเมื่อยังไม่มีสำเนาที่แก้ไว้
BUNDLED_PROFILE_FILE = _ROOT_DIR / "data" / "user_profile.json"


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


# ข้อมูลหน่วยงานที่แก้จากหน้าเว็บได้ (ตาราง org_profile โหมด Supabase) — ผู้ลงนามอยู่ที่รายชื่อผู้ลงนามของหน่วย
ORG_PROFILE_FIELDS = ("dept_name", "department_full", "doc_origin_code", "contact_dept",
                      "contact_tel", "contact_fax", "contact_email")


def apply_org_profile(base: UserProfileSchema, row: Optional[dict]) -> UserProfileSchema:
    """ทับค่าในโปรไฟล์ตั้งต้นด้วยข้อมูลหน่วยงานที่บันทึกไว้ (ช่องว่าง = ใช้ค่าตั้งต้น ยกเว้นอีเมล/โทรสารที่ลบได้)"""
    if not row:
        return base
    values = {}
    for key in ORG_PROFILE_FIELDS:
        value = row.get(key)
        if value is None:
            continue
        value = str(value).strip()
        if value or key in ("contact_email", "contact_fax"):
            values[key] = value or ("" if key == "contact_fax" else None)
    return base.model_copy(update=values)


def get_user_profile() -> UserProfileSchema:
    """
    โหลดโปรไฟล์หน่วยงานของผู้ใช้จาก data/user_profile.json
    หากยังไม่มีไฟล์ จะบันทึกค่าเริ่มต้นแล้วส่งคืน
    """
    if not PROFILE_FILE.exists() and PROFILE_FILE != BUNDLED_PROFILE_FILE and BUNDLED_PROFILE_FILE.exists():
        try:
            return UserProfileSchema(**json.loads(BUNDLED_PROFILE_FILE.read_text(encoding="utf-8")))
        except Exception as e:
            print(f"Error loading bundled profile: {e}, using default")
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
    try:
        PROFILE_FILE.parent.mkdir(parents=True, exist_ok=True)
        PROFILE_FILE.write_text(
            profile.model_dump_json(indent=2),
            encoding="utf-8"
        )
    except OSError:
        pass


def reset_to_default_profile() -> UserProfileSchema:
    """รีเซ็ตโปรไฟล์กลับเป็นค่าเริ่มต้น"""
    default_prof = get_default_profile()
    save_user_profile(default_prof)
    return default_prof

