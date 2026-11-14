"""ทะเบียนรับ-ส่ง และการออกเลขที่หนังสือ"""

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from core.registry import DocumentRegistry, DuplicateRegistryEntry, IncomingRecord, OutgoingRecord
from server.deps import get_registry

router = APIRouter(tags=["registry"])


class ReserveRequest(BaseModel):
    prefix: str = "ดพร ๐๑๐๒/"
    subject: str
    reserved_by: str = "เจ้าหน้าที่สารบรรณ"
    doc_type: str = "external"


@router.get("/api/v1/registry/next-number")
def get_next_number(
    prefix: str = Query("ดพร ๐๑๐๒/"),
    is_circular: bool = Query(False),
    registry: DocumentRegistry = Depends(get_registry),
):
    """ดูเลขที่ถัดไป — GET ต้องไม่เปลี่ยนข้อมูล จึงไม่กินเลข (ออกเลขจริงผ่าน POST /registry/reserve)"""
    next_no = registry.peek_next_doc_number(prefix=prefix, is_circular=is_circular)
    return {"prefix": prefix, "is_circular": is_circular, "doc_number": next_no}


@router.post("/api/v1/registry/reserve")
def reserve_number(req: ReserveRequest, registry: DocumentRegistry = Depends(get_registry)):
    """ออกเลขและจองไว้ในทะเบียนส่ง"""
    reserved_no = registry.reserve_doc_number(
        prefix=req.prefix, subject=req.subject, reserved_by=req.reserved_by, doc_type=req.doc_type
    )
    return {"status": "success", "reserved_number": reserved_no}


@router.get("/api/v1/registry/outgoing")
def list_outgoing(limit: int = 50, registry: DocumentRegistry = Depends(get_registry)):
    return registry.list_outgoing(limit=limit)


@router.post("/api/v1/registry/outgoing")
def create_outgoing(record: OutgoingRecord, registry: DocumentRegistry = Depends(get_registry)):
    try:
        row_id = registry.register_outgoing(record)
    except DuplicateRegistryEntry as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return {"status": "registered", "registry_id": row_id, "doc_number": record.doc_number}


@router.get("/api/v1/registry/incoming")
def list_incoming(limit: int = 50, registry: DocumentRegistry = Depends(get_registry)):
    return registry.list_incoming(limit=limit)


@router.post("/api/v1/registry/incoming")
def create_incoming(record: IncomingRecord, registry: DocumentRegistry = Depends(get_registry)):
    try:
        row_id = registry.register_incoming(record)
    except DuplicateRegistryEntry as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return {"status": "registered", "registry_id": row_id, "receive_number": record.receive_number}
