"""ผู้ใช้ของหน่วยงาน (migration 20261123000015_org_invites.sql — โหมด Supabase เท่านั้น, เฉพาะผู้ดูแล)

GET    /api/v1/users                 ผู้ใช้ในหน่วยงาน + คำเชิญ
POST   /api/v1/users/invites         เชิญด้วยอีเมล (ผู้ถูกเชิญลงทะเบียนเองที่หน้าเข้าสู่ระบบ)
DELETE /api/v1/users/invites/{id}    ยกเลิกคำเชิญที่ยังไม่ถูกใช้
PATCH  /api/v1/users/{user_id}       เปลี่ยนบทบาท / ระงับ ('disabled') / เปิดใช้คืน

ไม่ใช้ service role key: ทุกคำขอวิ่งด้วย token ของผู้ดูแล ผ่าน RLS + ฟังก์ชัน admin_set_role ในฐานข้อมูล
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator

from server.auth import CurrentUser, Profile, get_profile, get_supabase, require_supabase_user
from server.supabase import SupabaseClient, SupabaseError

router = APIRouter(tags=["users"])
logger = logging.getLogger("govdoc.api")

ROLES = ("admin", "clerk", "drafter", "approver")
_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]{2,}$")
_MIGRATION_HINT = ("ฐานข้อมูลยังไม่มีระบบเชิญผู้ใช้ — ให้ผู้ดูแลรัน supabase/migrations/20261123000015_org_invites.sql "
                   "ทั้งไฟล์ใน SQL Editor (ถ้ารันแล้ว ให้รัน: notify pgrst, 'reload schema';)")
_PROFILE_COLS = "user_id,email,full_name,position,role,created_at"
_INVITE_COLS = "id,email,full_name,position,role,created_at,expires_at,used_at,revoked_at"


def _guard(exc: SupabaseError) -> HTTPException:
    text = f"{exc.code} {exc.message}"
    logger.warning("users database error %s: %s", exc.status, text)
    if any(k in text for k in ("42703", "42P01", "42883", "PGRST202", "PGRST204", "PGRST205", "does not exist", "Could not find")):
        return HTTPException(status_code=503, detail=_MIGRATION_HINT)
    if "23505" in text or "duplicate key" in text:
        return HTTPException(status_code=409, detail="อีเมลนี้มีคำเชิญที่ยังใช้ได้อยู่แล้ว")
    if exc.code in ("P0001", "P0002", "22023", "42501") or exc.status in (400, 403):
        return HTTPException(status_code=400 if exc.code != "42501" else 403, detail=exc.message)
    return HTTPException(status_code=exc.status, detail=exc.message)


def require_admin(profile: Profile = Depends(get_profile)) -> Profile:
    if profile.role != "admin":
        raise HTTPException(status_code=403, detail="เฉพาะผู้ดูแลของหน่วยงาน")
    return profile


def invite_state(row: dict, now: datetime) -> str:
    """สถานะคำเชิญสำหรับแสดงผล: used / revoked / expired / open"""
    if row.get("used_at"):
        return "used"
    if row.get("revoked_at"):
        return "revoked"
    expires = row.get("expires_at")
    if expires and datetime.fromisoformat(str(expires).replace("Z", "+00:00")) <= now:
        return "expired"
    return "open"


class InviteIn(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    full_name: str = Field(default="", max_length=200)
    position: str = Field(default="", max_length=300)
    role: str = "drafter"

    @field_validator("email")
    @classmethod
    def _email(cls, v: str) -> str:
        v = v.strip().lower()
        if not _EMAIL.match(v):
            raise ValueError("รูปแบบอีเมลไม่ถูกต้อง")
        return v

    @field_validator("full_name", "position")
    @classmethod
    def _text(cls, v: str) -> str:
        v = " ".join((v or "").split())
        if "[✏️" in v:
            raise ValueError("ยังเป็นข้อความตัวอย่าง")
        return v

    @field_validator("role")
    @classmethod
    def _role(cls, v: str) -> str:
        if v not in ROLES:
            raise ValueError("บทบาทไม่ถูกต้อง")
        return v


class RoleIn(BaseModel):
    role: str

    @field_validator("role")
    @classmethod
    def _role(cls, v: str) -> str:
        if v not in ROLES + ("disabled",):
            raise ValueError("บทบาทไม่ถูกต้อง")
        return v


@router.get("/api/v1/users")
def users_list(admin: Profile = Depends(require_admin), client: SupabaseClient = Depends(get_supabase)):
    try:
        users = client.select("profiles", {"select": _PROFILE_COLS, "order": "created_at.asc"})
        invites = client.select("org_invites", {"select": _INVITE_COLS, "order": "created_at.desc", "limit": "100"})
    except SupabaseError as exc:
        raise _guard(exc)
    now = datetime.now(timezone.utc)
    return {
        "me": admin.user_id,
        "users": users,
        "invites": [{**r, "state": invite_state(r, now)} for r in invites],
    }


@router.post("/api/v1/users/invites", status_code=201)
def invite_create(
    req: InviteIn,
    user: CurrentUser = Depends(require_supabase_user),
    admin: Profile = Depends(require_admin),
    client: SupabaseClient = Depends(get_supabase),
):
    try:
        if client.select("profiles", {"select": "user_id", "email": f"eq.{req.email}"}):
            raise HTTPException(status_code=409, detail="อีเมลนี้เป็นผู้ใช้ในหน่วยงานอยู่แล้ว")
        row = client.insert("org_invites", {
            "org_id": admin.org_id, "created_by": user.id, "email": req.email,
            "full_name": req.full_name, "position": req.position, "role": req.role,
        })
    except SupabaseError as exc:
        raise _guard(exc)
    return {**{k: row.get(k) for k in _INVITE_COLS.split(",")}, "state": "open"}


@router.delete("/api/v1/users/invites/{invite_id}")
def invite_revoke(invite_id: UUID, admin: Profile = Depends(require_admin), client: SupabaseClient = Depends(get_supabase)):
    try:
        rows = client.update("org_invites", {"id": f"eq.{invite_id}", "used_at": "is.null", "revoked_at": "is.null"},
                             {"revoked_at": datetime.now(timezone.utc).isoformat()})
    except SupabaseError as exc:
        raise _guard(exc)
    if not rows:
        raise HTTPException(status_code=404, detail="ไม่พบคำเชิญที่ยังใช้ได้")
    return {"id": str(invite_id), "revoked": True}


@router.patch("/api/v1/users/{user_id}")
def user_set_role(user_id: UUID, req: RoleIn, admin: Profile = Depends(require_admin),
                  client: SupabaseClient = Depends(get_supabase)):
    if str(user_id) == admin.user_id and req.role != "admin":
        raise HTTPException(status_code=400, detail="เปลี่ยนบทบาทของตัวเองไม่ได้ — ให้ผู้ดูแลคนอื่นทำ")
    try:
        client.rpc("admin_set_role", {"target": str(user_id), "new_role": req.role})
    except SupabaseError as exc:
        raise _guard(exc)
    return {"user_id": str(user_id), "role": req.role}
