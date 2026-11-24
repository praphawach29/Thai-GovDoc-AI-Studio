"""แจ้งปัญหา / ความเห็นของผู้ใช้ (migration 20261124000016_feedback.sql — โหมด Supabase เท่านั้น)

POST  /api/v1/feedback          ส่งเรื่อง (ผูกกับร่างที่เปิดอยู่ได้) พร้อมข้อมูลประกอบที่หน้าเว็บแนบให้อัตโนมัติ
GET   /api/v1/feedback          ผู้ดูแลเห็นทั้งหน่วยงาน, คนอื่นเห็นเฉพาะของตัวเอง
PATCH /api/v1/feedback/{id}     ผู้ดูแลเปลี่ยนสถานะ: new (ใหม่) / seen (รับทราบ) / done (แก้แล้ว)

สิทธิ์บังคับที่ฐานข้อมูล (RLS) อยู่แล้ว — เซิร์ฟเวอร์กรองซ้ำอีกชั้น
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, field_validator

from server.auth import CurrentUser, Profile, get_profile, get_supabase, require_supabase_user
from server.supabase import SupabaseClient, SupabaseError

router = APIRouter(tags=["feedback"])
logger = logging.getLogger("govdoc.api")

RATINGS = ("ok", "minor", "major", "broken", "idea")
CATEGORIES = ("content", "layout", "export", "source", "speed", "ui", "other")
STATUSES = ("new", "seen", "done")
MAX_CONTEXT_BYTES = 12_000
_COLS = "id,user_id,document_id,rating,category,message,page,context,status,created_at,updated_at"
_MIGRATION_HINT = ("ฐานข้อมูลยังไม่มีระบบแจ้งปัญหา — ให้ผู้ดูแลรัน supabase/migrations/20261124000016_feedback.sql "
                   "ทั้งไฟล์ใน SQL Editor (ถ้ารันแล้ว ให้รัน: notify pgrst, 'reload schema';)")


def _guard(exc: SupabaseError) -> HTTPException:
    text = f"{exc.code} {exc.message}"
    logger.warning("feedback database error %s: %s", exc.status, text)
    if any(k in text for k in ("42703", "42P01", "PGRST204", "PGRST205", "does not exist", "Could not find")):
        return HTTPException(status_code=503, detail=_MIGRATION_HINT)
    if exc.code == "42501" or exc.status == 403:
        return HTTPException(status_code=403, detail="ไม่มีสิทธิ์")
    return HTTPException(status_code=exc.status, detail=exc.message)


def _trim_context(context: Dict[str, Any]) -> Dict[str, Any]:
    """ข้อมูลประกอบจากหน้าเว็บ: ตัดข้อความยาว และไม่ให้เกินขนาดที่ฐานข้อมูลรับ"""
    out: Dict[str, Any] = {}
    for key, value in list(context.items())[:30]:
        if isinstance(value, str):
            value = value[:500]
        elif isinstance(value, list):
            value = [v[:300] if isinstance(v, str) else v for v in value[:20]]
        out[str(key)[:60]] = value
    if len(json.dumps(out, ensure_ascii=False).encode()) > MAX_CONTEXT_BYTES:
        out = {k: v for k, v in out.items() if not isinstance(v, (list, dict))}
        out["truncated"] = True
    return out


class FeedbackIn(BaseModel):
    rating: str
    category: str = "other"
    message: str = Field(default="", max_length=4000)
    document_id: Optional[str] = None
    page: str = Field(default="", max_length=300)
    context: Dict[str, Any] = Field(default_factory=dict)

    @field_validator("rating")
    @classmethod
    def _rating(cls, v: str) -> str:
        if v not in RATINGS:
            raise ValueError("ระดับไม่ถูกต้อง")
        return v

    @field_validator("category")
    @classmethod
    def _category(cls, v: str) -> str:
        if v not in CATEGORIES:
            raise ValueError("หมวดไม่ถูกต้อง")
        return v

    @field_validator("message")
    @classmethod
    def _message(cls, v: str) -> str:
        return (v or "").strip()

    @field_validator("document_id")
    @classmethod
    def _doc(cls, v: Optional[str]) -> Optional[str]:
        """ร่างที่เก็บในเครื่อง (ไม่ใช่ UUID) ไม่ผูก — id ไปอยู่ใน context แทน"""
        if not v:
            return None
        try:
            return str(UUID(str(v)))
        except ValueError:
            return None


class StatusIn(BaseModel):
    status: str

    @field_validator("status")
    @classmethod
    def _status(cls, v: str) -> str:
        if v not in STATUSES:
            raise ValueError("สถานะไม่ถูกต้อง")
        return v


@router.post("/api/v1/feedback", status_code=201)
def feedback_create(
    req: FeedbackIn,
    user: CurrentUser = Depends(require_supabase_user),
    profile: Profile = Depends(get_profile),
    client: SupabaseClient = Depends(get_supabase),
):
    # "ใช้ได้เลย" ส่งได้โดยไม่ต้องพิมพ์ — ระดับอื่นต้องเล่าว่าเกิดอะไร
    if req.rating != "ok" and not req.message:
        raise HTTPException(status_code=400, detail="พิมพ์ข้อเสนอแนะก่อนส่ง" if req.rating == "idea" else "เล่าปัญหาสั้น ๆ ก่อนส่ง")
    context = _trim_context(req.context)
    try:
        row = client.insert("feedback", {
            "org_id": profile.org_id, "user_id": user.id, "document_id": req.document_id,
            "rating": req.rating, "category": req.category, "message": req.message,
            "page": req.page, "context": context, "status": "new",
        })
    except SupabaseError as exc:
        raise _guard(exc)
    return {k: row.get(k) for k in _COLS.split(",")}


@router.get("/api/v1/feedback")
def feedback_list(
    status: Optional[str] = Query(None),
    profile: Profile = Depends(get_profile),
    client: SupabaseClient = Depends(get_supabase),
):
    admin = profile.role == "admin"
    params = {"select": _COLS, "order": "created_at.desc", "limit": "200"}
    if not admin:
        params["user_id"] = f"eq.{profile.user_id}"
    if status in STATUSES:
        params["status"] = f"eq.{status}"
    try:
        rows = client.select("feedback", params)
        people = {p["user_id"]: p for p in client.select("profiles", {"select": "user_id,full_name,email,position"})} if rows else {}
        doc_ids = sorted({r["document_id"] for r in rows if r.get("document_id")})
        docs = ({d["id"]: d for d in client.select("documents", {"select": "id,subject,kind",
                                                                  "id": "in.(" + ",".join(doc_ids) + ")"})}
                if doc_ids else {})
    except SupabaseError as exc:
        raise _guard(exc)
    out = []
    for r in rows:
        who = people.get(r["user_id"], {})
        doc = docs.get(r.get("document_id") or "", {})
        out.append({**r, "reporter": who.get("full_name") or who.get("email") or "", "document_subject": doc.get("subject", "")})
    counts = {s: sum(1 for r in rows if r.get("status", "new") == s) for s in STATUSES}
    return {"admin": admin, "items": out, "counts": counts}


@router.patch("/api/v1/feedback/{feedback_id}")
def feedback_set_status(
    feedback_id: UUID,
    req: StatusIn,
    profile: Profile = Depends(get_profile),
    client: SupabaseClient = Depends(get_supabase),
):
    if profile.role != "admin":
        raise HTTPException(status_code=403, detail="เฉพาะผู้ดูแลของหน่วยงาน")
    try:
        rows = client.update("feedback", {"id": f"eq.{feedback_id}"},
                             {"status": req.status, "updated_at": datetime.now(timezone.utc).isoformat()})
    except SupabaseError as exc:
        raise _guard(exc)
    if not rows:
        raise HTTPException(status_code=404, detail="ไม่พบเรื่องนี้")
    return {"id": str(feedback_id), "status": req.status}
