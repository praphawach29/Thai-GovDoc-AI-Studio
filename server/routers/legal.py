"""คลังข้อกฎหมาย/ระเบียบ ที่ผู้ใช้ดูแลเอง พร้อมสถานะตรวจยืนยัน"""

from fastapi import APIRouter, HTTPException, Query

from core.legal_sources import LegalLibrary, LegalReference

router = APIRouter(tags=["legal"])


@router.get("/api/v1/legal/references")
def list_legal_references(verified_only: bool = Query(False)):
    lib = LegalLibrary()
    return {"references": [ref.model_dump() for ref in lib.list(verified_only=verified_only)]}


@router.post("/api/v1/legal/references")
def add_legal_reference(ref: LegalReference):
    saved = LegalLibrary().add(ref)
    return {"status": "created", "reference": saved.model_dump()}


@router.put("/api/v1/legal/references/{ref_id}")
def update_legal_reference(ref_id: str, ref: LegalReference):
    updated = LegalLibrary().update(ref_id, **{k: v for k, v in ref.model_dump().items() if k != "id"})
    if updated is None:
        raise HTTPException(status_code=404, detail="Reference not found")
    return {"status": "updated", "reference": updated.model_dump()}
