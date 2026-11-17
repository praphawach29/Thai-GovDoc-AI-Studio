"""ข้อมูลหน่วยงาน (ตาราง org_profile — หนึ่งแถวต่อหน่วยงาน ใช้ร่วมกันทุกคนในหน่วยผ่าน RLS)

GET /api/v1/studio/profile  (server/routers/studio.py) ใช้ load_org_profile() — โหมดเครื่องเดียวอ่าน data/user_profile.json
PUT /api/v1/org-profile     บันทึก (โหมด Supabase เท่านั้น)
ตอนร่าง/เอกสารเปล่า: ส่ง profile ที่รวมแล้วให้ core.studio (ช่องว่าง = ค่าตั้งต้นของระบบ)
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator

from core.models import UserProfileSchema
from core.profile_manager import ORG_PROFILE_FIELDS, apply_org_profile, get_user_profile
from server.auth import CurrentUser, Profile, get_profile, get_supabase, require_supabase_user
from server.settings import Settings
from server.supabase import SupabaseClient, SupabaseError

router = APIRouter(tags=["org-profile"])
logger = logging.getLogger("govdoc.api")

_TABLE = "org_profile"
_MIGRATION_HINT = ("ฐานข้อมูลยังไม่เห็นตารางข้อมูลหน่วยงาน — ให้ผู้ดูแลรัน supabase/migrations/20261116000014_org_profile.sql "
                   "ทั้งไฟล์ใน SQL Editor (ถ้ารันแล้ว ให้รัน: notify pgrst, 'reload schema';)")
_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _schema_guard(exc: SupabaseError) -> HTTPException:
    text = f"{exc.code} {exc.message}"
    logger.warning("org profile database error %s: %s", exc.status, text)
    if any(k in text for k in ("42703", "42P01", "PGRST204", "PGRST205", "does not exist", "Could not find")):
        return HTTPException(status_code=503, detail=_MIGRATION_HINT)
    return HTTPException(status_code=exc.status, detail=exc.message)


def _row(client: SupabaseClient) -> Optional[dict]:
    rows = client.select(_TABLE, {"select": ",".join(ORG_PROFILE_FIELDS) + ",updated_at"})
    return rows[0] if rows else None


def load_org_profile(user: Optional[CurrentUser], settings: Settings) -> UserProfileSchema:
    """โปรไฟล์ตั้งต้น + ข้อมูลหน่วยงานที่บันทึกไว้ — ตารางยังไม่มี/ขัดข้อง = ค่าตั้งต้น (ห้ามทำให้การร่างล้ม)"""
    base = get_user_profile()
    if not isinstance(user, CurrentUser):
        return base
    try:
        return apply_org_profile(base, _row(get_supabase(user, settings)))
    except SupabaseError as exc:
        logger.info("org profile unavailable: %s %s", exc.code, exc.message)
    except Exception:
        logger.exception("org profile lookup failed")
    return base


def _one_line(v: str) -> str:
    return re.sub(r"\s+", " ", v or "").strip()


class OrgProfileIn(BaseModel):
    dept_name: str = Field("", max_length=300)
    department_full: str = Field("", max_length=500)
    doc_origin_code: str = Field("", max_length=50)
    contact_dept: str = Field("", max_length=300)
    contact_tel: str = Field("", max_length=100)
    contact_fax: str = Field("", max_length=100)
    contact_email: str = Field("", max_length=200)

    @field_validator("dept_name", "department_full", "doc_origin_code", "contact_dept", "contact_tel", "contact_fax")
    @classmethod
    def _clean(cls, v: str) -> str:
        v = _one_line(v)
        if "[✏️" in v:
            raise ValueError("ยังเป็นข้อความตัวอย่าง [✏️ ...]")
        return v

    @field_validator("contact_email")
    @classmethod
    def _email(cls, v: str) -> str:
        v = _one_line(v)
        if v and not _EMAIL.match(v):
            raise ValueError("รูปแบบอีเมลไม่ถูกต้อง")
        return v


@router.put("/api/v1/org-profile")
def org_profile_save(
    req: OrgProfileIn,
    user: CurrentUser = Depends(require_supabase_user),
    profile: Profile = Depends(get_profile),
    client: SupabaseClient = Depends(get_supabase),
):
    """บันทึกข้อมูลหน่วยงาน (มีแถวแล้ว = แก้, ยังไม่มี = สร้าง) — มีผลกับร่างใหม่ทุกคนในหน่วยงาน"""
    values = {**req.model_dump(), "updated_by": user.id, "updated_at": datetime.now(timezone.utc).isoformat()}
    try:
        if _row(client) is None:
            client.insert(_TABLE, {"org_id": profile.org_id, **values})
        else:
            client.update(_TABLE, {"org_id": f"eq.{profile.org_id}"}, values)
    except SupabaseError as exc:
        raise _schema_guard(exc)
    merged = apply_org_profile(get_user_profile(), req.model_dump())
    return {**merged.model_dump(mode="json", exclude={"issuing_units"}), "editable": True, "saved": True}
