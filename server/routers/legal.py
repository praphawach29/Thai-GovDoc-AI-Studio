"""คลังข้อกฎหมาย/ระเบียบ ที่ผู้ใช้ดูแลเอง พร้อมสถานะตรวจยืนยัน

โหมด Supabase: เก็บในตาราง legal_references (แยกตามหน่วยงาน)
โหมดเครื่องเดียว: ไฟล์ data/legal_references.json
"""

from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from core.legal_sources import LegalLibrary, LegalReference
from server.auth import CurrentUser, get_current_user, get_profile, get_supabase
from core.legal_suggest import LegalPicks, suggest
from core.llm_drafter import structured_call
from server.settings import Settings, get_settings, llm_config
from server.supabase import SupabaseError

router = APIRouter(tags=["legal"])

_FIELDS = ("title", "section", "quote", "url", "effective_date", "verified")
_COLUMNS = "id,title,section,quote,url,effective_date,verified,recorded_by,recorded_at"
# คอลัมน์จากการนำเข้าไฟล์ (migration 8) — ถ้ายังไม่ได้รัน ใช้ชุดเดิม
_IMPORT_COLUMNS = ",source_id,page_from,page_to,chapter"


def _client(user, settings):
    return get_supabase(user, settings) if isinstance(user, CurrentUser) else None


@router.get("/api/v1/legal/references")
def list_legal_references(
    verified_only: bool = Query(False),
    user: Optional[CurrentUser] = Depends(get_current_user),
    settings: Settings = Depends(get_settings),
):
    client = _client(user, settings)
    if client is None:
        return {"references": [ref.model_dump() for ref in LegalLibrary().list(verified_only=verified_only)]}
    params = {"select": _COLUMNS + _IMPORT_COLUMNS, "order": "recorded_at.desc"}
    if verified_only:
        params["verified"] = "eq.true"
    try:
        return {"references": client.select("legal_references", params)}
    except SupabaseError:
        params["select"] = _COLUMNS
        return {"references": client.select("legal_references", params)}


class SuggestRequest(BaseModel):
    text: str = Field(min_length=1, max_length=20000)   # เรื่อง + เนื้อความ + สรุปต้นเรื่อง
    limit: int = Field(5, ge=1, le=10)


@router.post("/api/v1/legal/suggest")
def suggest_legal_references(
    req: SuggestRequest,
    user: Optional[CurrentUser] = Depends(get_current_user),
    settings: Settings = Depends(get_settings),
):
    """ข้อกฎหมายที่เกี่ยวข้องกับเรื่อง จากคลังที่ยืนยันแล้วเท่านั้น (AI เลือก; ไม่มี AI ใช้คำที่ตรงกัน)"""
    client = _client(user, settings)
    if client is None:
        refs = [ref.model_dump() for ref in LegalLibrary().list(verified_only=True)]
    else:
        params = {"select": _COLUMNS + _IMPORT_COLUMNS, "verified": "eq.true", "limit": "1000"}
        try:
            refs = client.select("legal_references", params)
        except SupabaseError:
            params["select"] = _COLUMNS
            refs = client.select("legal_references", params)
    config = llm_config(settings)
    ai = None
    if config.gemini_api_key or config.anthropic_api_key:
        ai = lambda system, prompt: structured_call(system, prompt, LegalPicks, config, timeout_s=25.0)
    picks = suggest(req.text, refs, ai=ai, limit=req.limit)
    by_id = {str(r["id"]): r for r in refs}
    return {"suggestions": [{"reference": by_id[p.id], "reason": p.reason, "by": p.by} for p in picks]}


@router.post("/api/v1/legal/references")
def add_legal_reference(
    ref: LegalReference,
    user: Optional[CurrentUser] = Depends(get_current_user),
    settings: Settings = Depends(get_settings),
):
    client = _client(user, settings)
    if client is None:
        saved = LegalLibrary().add(ref)
        return {"status": "created", "reference": saved.model_dump()}
    profile = get_profile(user, client)
    row = client.insert("legal_references", {
        "org_id": profile.org_id, "recorded_by": user.id,
        **{k: getattr(ref, k) for k in _FIELDS},
    })
    return {"status": "created", "reference": row}


class ReferenceEdit(BaseModel):
    """แก้รายการในคลัง: หัวข้อที่ใช้เรียก (เช่น "ข้อ ๑๔" หรือชื่อที่ตั้งเอง) และเนื้อหา (แก้คำที่ AI อ่านผิด)"""
    section: Optional[str] = Field(None, max_length=200)
    quote: Optional[str] = Field(None, max_length=20000)
    verified: Optional[bool] = None


@router.patch("/api/v1/legal/references/{ref_id}")
def edit_legal_reference(
    ref_id: str,
    req: ReferenceEdit,
    user: Optional[CurrentUser] = Depends(get_current_user),
    settings: Settings = Depends(get_settings),
):
    """แก้เฉพาะช่องที่ส่งมา (ช่องอื่น เช่น เลขหน้า ไฟล์ต้นฉบับ คงเดิม)"""
    values = {}
    if req.section is not None:
        if not req.section.strip():
            raise HTTPException(status_code=422, detail="หัวข้อว่างไม่ได้")
        values["section"] = req.section.strip()
    if req.quote is not None:
        if not req.quote.strip():
            raise HTTPException(status_code=422, detail="เนื้อหาว่างไม่ได้")
        values["quote"] = req.quote.strip()
    if req.verified is not None:
        values["verified"] = req.verified
    if not values:
        raise HTTPException(status_code=422, detail="ไม่มีข้อมูลที่จะแก้")
    client = _client(user, settings)
    if client is None:
        updated = LegalLibrary().update(ref_id, **values)
        if updated is None:
            raise HTTPException(status_code=404, detail="Reference not found")
        return {"status": "updated", "reference": updated.model_dump()}
    try:
        UUID(ref_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Reference not found")
    rows = client.update("legal_references", {"id": f"eq.{ref_id}"}, values)
    if not rows:
        raise HTTPException(status_code=404, detail="Reference not found")
    return {"status": "updated", "reference": rows[0]}


@router.put("/api/v1/legal/references/{ref_id}")
def update_legal_reference(
    ref_id: str,
    ref: LegalReference,
    user: Optional[CurrentUser] = Depends(get_current_user),
    settings: Settings = Depends(get_settings),
):
    client = _client(user, settings)
    if client is None:
        updated = LegalLibrary().update(ref_id, **{k: v for k, v in ref.model_dump().items() if k != "id"})
        if updated is None:
            raise HTTPException(status_code=404, detail="Reference not found")
        return {"status": "updated", "reference": updated.model_dump()}
    try:
        UUID(ref_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Reference not found")
    rows = client.update("legal_references", {"id": f"eq.{ref_id}"}, {k: getattr(ref, k) for k in _FIELDS})
    if not rows:
        raise HTTPException(status_code=404, detail="Reference not found")
    return {"status": "updated", "reference": rows[0]}
