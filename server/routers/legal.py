"""คลังข้อกฎหมาย/ระเบียบ ที่ผู้ใช้ดูแลเอง พร้อมสถานะตรวจยืนยัน

โหมด Supabase: เก็บในตาราง legal_references (แยกตามหน่วยงาน)
โหมดเครื่องเดียว: ไฟล์ data/legal_references.json
"""

from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query

from core.legal_sources import LegalLibrary, LegalReference
from server.auth import CurrentUser, get_current_user, get_profile, get_supabase
from server.settings import Settings, get_settings
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
