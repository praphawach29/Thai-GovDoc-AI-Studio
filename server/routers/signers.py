"""รายชื่อผู้ลงนามประจำหน่วยงาน (ตาราง org_signers — ใช้ร่วมกันทุกคนในหน่วยงานผ่าน RLS; โหมด Supabase เท่านั้น)

GET    /api/v1/signers            รายชื่อ (ผู้ลงนามเริ่มต้นก่อน แล้วตามลำดับ)
POST   /api/v1/signers            เพิ่ม
PATCH  /api/v1/signers/{id}       แก้ / ตั้งเป็นผู้ลงนามเริ่มต้น (ล้างคนเดิมให้อัตโนมัติ)
DELETE /api/v1/signers/{id}       ลบ
ตอนร่าง: server/routers/studio.py เรียก load_roster() แล้วเติมชื่อด้วย core/signers.py
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator

from core.signers import OrgSigner, clean_name, clean_position
from server.auth import CurrentUser, Profile, get_profile, get_supabase, require_supabase_user
from server.supabase import SupabaseClient, SupabaseError

router = APIRouter(tags=["signers"])
logger = logging.getLogger("govdoc.api")

_TABLE = "org_signers"
_COLUMNS = "id,full_name,position,stamp,is_default,sort_order"
_MIGRATION_HINT = ("ฐานข้อมูลยังไม่เห็นตารางรายชื่อผู้ลงนาม — ให้ผู้ดูแลรัน supabase/migrations/20261116000012_org_signers.sql "
                   "ทั้งไฟล์ใน SQL Editor (ถ้ารันแล้ว ให้รัน: notify pgrst, 'reload schema';)")
_MAX_SIGNERS = 50


def _schema_guard(exc: SupabaseError) -> HTTPException:
    text = f"{exc.code} {exc.message}"
    logger.warning("org signers database error %s: %s", exc.status, text)
    if any(k in text for k in ("42703", "42P01", "PGRST204", "PGRST205", "does not exist", "Could not find")):
        return HTTPException(status_code=503, detail=_MIGRATION_HINT)
    if "23505" in text or "duplicate key" in text:
        return HTTPException(status_code=409, detail="มีผู้ลงนามเริ่มต้นแล้ว — ลองใหม่อีกครั้ง")
    return HTTPException(status_code=exc.status, detail=exc.message)


def _sorted(rows: List[dict]) -> List[dict]:
    return sorted(rows, key=lambda r: (not r.get("is_default"), r.get("sort_order") or 0, r.get("full_name") or ""))


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _valid_name(v: Optional[str]) -> Optional[str]:
    if v is None:
        return v
    v = clean_name(v)
    if not v:
        raise ValueError("ใส่ชื่อผู้ลงนาม")
    if "[✏️" in v:
        raise ValueError("ชื่อผู้ลงนามยังเป็นข้อความตัวอย่าง")
    return v


def _valid_position(v: Optional[str]) -> Optional[str]:
    if v is None:
        return v
    v = clean_position(v)
    if v.count(chr(10)) > 4:
        raise ValueError("ตำแหน่งยาวได้ไม่เกิน ๕ บรรทัด")
    return v


class SignerIn(BaseModel):
    full_name: str = Field(min_length=1, max_length=200)
    position: str = Field(default="", max_length=600)
    stamp: bool = False
    is_default: bool = False
    sort_order: int = Field(default=0, ge=0, le=10000)

    _name = field_validator("full_name")(_valid_name)
    _position = field_validator("position")(_valid_position)


class SignerPatch(BaseModel):
    full_name: Optional[str] = Field(None, min_length=1, max_length=200)
    position: Optional[str] = Field(None, max_length=600)
    stamp: Optional[bool] = None
    is_default: Optional[bool] = None
    sort_order: Optional[int] = Field(None, ge=0, le=10000)

    _name = field_validator("full_name")(_valid_name)
    _position = field_validator("position")(_valid_position)


def _clear_default(client: SupabaseClient, org_id: str, keep: Optional[str] = None) -> None:
    """ผู้ลงนามเริ่มต้นมีได้คนเดียวต่อหน่วยงาน — ล้างคนเดิมก่อนตั้งคนใหม่"""
    filters = {"org_id": f"eq.{org_id}", "is_default": "eq.true"}
    if keep:
        filters["id"] = f"neq.{keep}"
    client.update(_TABLE, filters, {"is_default": False, "updated_at": _now()})


def load_roster(client: Optional[SupabaseClient]) -> List[OrgSigner]:
    """รายชื่อผู้ลงนามสำหรับตอนร่าง — ตารางยังไม่มี/ฐานข้อมูลขัดข้อง = ไม่มีรายชื่อ (ห้ามทำให้การร่างล้ม)"""
    if client is None:
        return []
    try:
        rows = client.select(_TABLE, {"select": _COLUMNS, "order": "sort_order.asc,created_at.asc"})
    except SupabaseError as exc:
        logger.info("org signers unavailable while drafting: %s %s", exc.code, exc.message)
        return []
    except Exception:                                   # ห้ามทำให้การร่างล้มเพราะรายชื่อผู้ลงนาม
        logger.exception("org signers lookup failed")
        return []
    out = []
    for row in _sorted(rows or []):
        try:
            out.append(OrgSigner(**{**row, "id": str(row.get("id") or "")}))
        except ValueError:
            continue
    return out


@router.get("/api/v1/signers")
def signers_list(client: SupabaseClient = Depends(get_supabase)):
    try:
        rows = client.select(_TABLE, {"select": _COLUMNS, "order": "sort_order.asc,created_at.asc"})
    except SupabaseError as exc:
        raise _schema_guard(exc)
    return _sorted(rows)


@router.post("/api/v1/signers", status_code=201)
def signers_create(
    req: SignerIn,
    user: CurrentUser = Depends(require_supabase_user),
    profile: Profile = Depends(get_profile),
    client: SupabaseClient = Depends(get_supabase),
):
    try:
        existing = client.select(_TABLE, {"select": "id,is_default"})
        if len(existing) >= _MAX_SIGNERS:
            raise HTTPException(status_code=400, detail=f"รายชื่อผู้ลงนามมีได้ไม่เกิน {_MAX_SIGNERS} คน")
        is_default = req.is_default or not existing          # คนแรกของหน่วยงาน = ผู้ลงนามเริ่มต้น
        if is_default:
            _clear_default(client, profile.org_id)
        row = client.insert(_TABLE, {
            "org_id": profile.org_id, "created_by": user.id,
            "full_name": req.full_name, "position": req.position, "stamp": req.stamp,
            "is_default": is_default, "sort_order": req.sort_order or len(existing),
        })
    except SupabaseError as exc:
        raise _schema_guard(exc)
    return {k: row.get(k) for k in _COLUMNS.split(",")}


@router.patch("/api/v1/signers/{signer_id}")
def signers_update(
    signer_id: UUID,
    req: SignerPatch,
    profile: Profile = Depends(get_profile),
    client: SupabaseClient = Depends(get_supabase),
):
    values = req.model_dump(exclude_none=True)
    if not values:
        raise HTTPException(status_code=400, detail="ไม่มีข้อมูลที่จะแก้")
    try:
        if values.get("is_default"):
            _clear_default(client, profile.org_id, keep=str(signer_id))
        rows = client.update(_TABLE, {"id": f"eq.{signer_id}"}, {**values, "updated_at": _now()})
    except SupabaseError as exc:
        raise _schema_guard(exc)
    if not rows:
        raise HTTPException(status_code=404, detail="ไม่พบผู้ลงนามนี้")
    return {k: rows[0].get(k) for k in _COLUMNS.split(",")}


@router.delete("/api/v1/signers/{signer_id}")
def signers_delete(signer_id: UUID, client: SupabaseClient = Depends(get_supabase)):
    try:
        rows = client.select(_TABLE, {"select": "id", "id": f"eq.{signer_id}"})
        if not rows:
            raise HTTPException(status_code=404, detail="ไม่พบผู้ลงนามนี้")
        client._request("DELETE", f"/rest/v1/{_TABLE}", params={"id": f"eq.{signer_id}"})
    except SupabaseError as exc:
        raise _schema_guard(exc)
    return {"id": str(signer_id), "deleted": True}
