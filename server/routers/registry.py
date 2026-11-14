"""ทะเบียนรับ-ส่ง และการออกเลขที่หนังสือ

โหมด Supabase: ออกเลข/ยกเลิก/ลงรับ ผ่านฟังก์ชันในฐานข้อมูล (atomic, ห้ามลบ, มี audit)
โหมดเครื่องเดียว: ใช้ core.registry (SQLite)
"""

from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ValidationError

from core.registry import DocumentRegistry, DuplicateRegistryEntry, IncomingRecord, OutgoingRecord
from core.thai_date import current_be_year
from core.thai_segmenter import to_thai_numerals
from server.auth import CurrentUser, get_current_user
from server.deps import get_registry
from server.settings import Settings, get_settings
from server.supabase import SupabaseClient

router = APIRouter(tags=["registry"])

_OUT_COLUMNS = ("id,reg_no,year_be,doc_number,doc_date,from_unit,to_recipient,subject,action_taken,"
                "remark,status,cancel_reason,document_id,created_at")
_IN_COLUMNS = ("id,reg_no,year_be,received_at,source_doc_number,source_doc_date,from_org,to_unit,"
               "subject,action_taken,remark,source_file_id,created_at")


class ReserveRequest(BaseModel):
    prefix: str = "ดพร ๐๑๐๒/"
    subject: str
    reserved_by: str = "เจ้าหน้าที่สารบรรณ"   # โหมดเครื่องเดียว; โหมด Supabase ใช้ผู้ที่ล็อกอิน
    doc_type: str = "external"
    is_circular: bool = False
    to_recipient: str = ""
    document_id: Optional[UUID] = None        # ผูกเลขกับเอกสาร (โหมด Supabase)


class IssueRequest(BaseModel):
    doc_date: Optional[str] = None


class CancelRequest(BaseModel):
    reason: str


class IncomingRequest(BaseModel):
    source_doc_number: str = ""
    source_doc_date: str = ""
    from_org: str = ""
    subject: str
    to_unit: str = ""
    source_file_id: Optional[UUID] = None
    remark: str = ""


def _client(user: Optional[CurrentUser], settings: Settings) -> Optional[SupabaseClient]:
    # isinstance: เรียกฟังก์ชันตรง (เช่นในเทสต์) ค่า default จะเป็นวัตถุ Depends ไม่ใช่ผู้ใช้
    if not isinstance(user, CurrentUser):
        return None
    return SupabaseClient(settings.supabase_url, settings.supabase_publishable_key, user.token)


def _needs_supabase():
    return HTTPException(status_code=501, detail="ใช้ได้เมื่อเชื่อมต่อ Supabase (โหมดเครื่องเดียวยังไม่รองรับ)")


@router.get("/api/v1/registry/next-number")
def get_next_number(
    prefix: str = Query("ดพร ๐๑๐๒/"),
    is_circular: bool = Query(False),
    registry: DocumentRegistry = Depends(get_registry),
    user: Optional[CurrentUser] = Depends(get_current_user),
    settings: Settings = Depends(get_settings),
):
    """ดูเลขที่ถัดไป — GET ต้องไม่เปลี่ยนข้อมูล จึงไม่กินเลข (ออกเลขจริงผ่าน POST /registry/reserve)"""
    client = _client(user, settings)
    if client is None:
        next_no = registry.peek_next_doc_number(prefix=prefix, is_circular=is_circular)
    else:
        book = "outgoing:" + prefix + ("ว" if is_circular else "")
        rows = client.select("number_sequences", {
            "select": "last_value", "book": f"eq.{book}", "year_be": f"eq.{current_be_year()}",
        })
        seq = str((rows[0]["last_value"] if rows else 0) + 1)
        if any("๐" <= ch <= "๙" for ch in prefix):
            seq = to_thai_numerals(seq)
        next_no = prefix + ("ว " if is_circular else "") + seq
    return {"prefix": prefix, "is_circular": is_circular, "doc_number": next_no}


@router.post("/api/v1/registry/reserve")
def reserve_number(
    req: ReserveRequest,
    registry: DocumentRegistry = Depends(get_registry),
    user: Optional[CurrentUser] = Depends(get_current_user),
    settings: Settings = Depends(get_settings),
):
    """ออกเลขและจองไว้ในทะเบียนส่ง"""
    client = _client(user, settings)
    if client is None:
        if req.is_circular or req.document_id:
            raise _needs_supabase()
        reserved_no = registry.reserve_doc_number(
            prefix=req.prefix, subject=req.subject, reserved_by=req.reserved_by, doc_type=req.doc_type
        )
        return {"status": "success", "reserved_number": reserved_no}
    entry = client.rpc("reserve_outgoing_number", {
        "p_prefix": req.prefix,
        "p_subject": req.subject,
        "p_is_circular": req.is_circular,
        "p_to_recipient": req.to_recipient,
        "p_document_id": str(req.document_id) if req.document_id else None,
    })
    return {"status": "success", "reserved_number": entry["doc_number"], "entry": entry}


@router.post("/api/v1/registry/outgoing/{entry_id}/issue")
def issue_number(
    entry_id: int,
    req: IssueRequest,
    user: Optional[CurrentUser] = Depends(get_current_user),
    settings: Settings = Depends(get_settings),
):
    """ยืนยันว่าเลขที่จองถูกใช้ส่งหนังสือจริง"""
    client = _client(user, settings)
    if client is None:
        raise _needs_supabase()
    return client.rpc("mark_outgoing_issued", {"p_id": entry_id, "p_doc_date": req.doc_date})


@router.post("/api/v1/registry/outgoing/{entry_id}/cancel")
def cancel_number(
    entry_id: int,
    req: CancelRequest,
    user: Optional[CurrentUser] = Depends(get_current_user),
    settings: Settings = Depends(get_settings),
):
    """ยกเลิกเลข (ต้องมีเหตุผล) — รายการยังอยู่ในทะเบียน และเลขไม่ถูกนำกลับมาใช้"""
    client = _client(user, settings)
    if client is None:
        raise _needs_supabase()
    return client.rpc("cancel_outgoing_number", {"p_id": entry_id, "p_reason": req.reason})


@router.get("/api/v1/registry/outgoing")
def list_outgoing(
    limit: int = Query(50, ge=1, le=500),
    registry: DocumentRegistry = Depends(get_registry),
    user: Optional[CurrentUser] = Depends(get_current_user),
    settings: Settings = Depends(get_settings),
):
    client = _client(user, settings)
    if client is None:
        return registry.list_outgoing(limit=limit)
    return client.select("outgoing_register", {"select": _OUT_COLUMNS, "order": "id.desc", "limit": str(limit)})


@router.post("/api/v1/registry/outgoing")
def create_outgoing(
    record: OutgoingRecord,
    registry: DocumentRegistry = Depends(get_registry),
    user: Optional[CurrentUser] = Depends(get_current_user),
):
    """บันทึกทะเบียนส่งด้วยเลขที่กำหนดเอง — โหมดเครื่องเดียวเท่านั้น

    โหมด Supabase ห้ามกำหนดเลขเอง (กันเลขซ้ำ/ข้ามเลข): ใช้ /registry/reserve แล้ว /issue
    """
    if isinstance(user, CurrentUser):
        raise HTTPException(status_code=405, detail="ใช้ POST /api/v1/registry/reserve เพื่อออกเลข แล้ว /issue เมื่อส่งจริง")
    try:
        row_id = registry.register_outgoing(record)
    except DuplicateRegistryEntry as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return {"status": "registered", "registry_id": row_id, "doc_number": record.doc_number}


@router.get("/api/v1/registry/incoming")
def list_incoming(
    limit: int = Query(50, ge=1, le=500),
    registry: DocumentRegistry = Depends(get_registry),
    user: Optional[CurrentUser] = Depends(get_current_user),
    settings: Settings = Depends(get_settings),
):
    client = _client(user, settings)
    if client is None:
        return registry.list_incoming(limit=limit)
    return client.select("incoming_register", {"select": _IN_COLUMNS, "order": "id.desc", "limit": str(limit)})


@router.post("/api/v1/registry/incoming")
def create_incoming(
    body: dict,
    registry: DocumentRegistry = Depends(get_registry),
    user: Optional[CurrentUser] = Depends(get_current_user),
    settings: Settings = Depends(get_settings),
):
    """ลงทะเบียนรับ — โหมด Supabase ออกเลขทะเบียนรับให้อัตโนมัติ"""
    client = _client(user, settings)
    try:
        record = IncomingRecord(**body) if client is None else None
        req = IncomingRequest(**body) if client is not None else None
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=exc.errors(include_url=False, include_context=False))
    if client is None:
        try:
            row_id = registry.register_incoming(record)
        except DuplicateRegistryEntry as exc:
            raise HTTPException(status_code=409, detail=str(exc))
        return {"status": "registered", "registry_id": row_id, "receive_number": record.receive_number}
    entry = client.rpc("register_incoming", {
        "p_source_doc_number": req.source_doc_number,
        "p_source_doc_date": req.source_doc_date,
        "p_from_org": req.from_org,
        "p_subject": req.subject,
        "p_to_unit": req.to_unit,
        "p_source_file_id": str(req.source_file_id) if req.source_file_id else None,
        "p_remark": req.remark,
    })
    return {"status": "registered", "registry_id": entry["id"], "receive_number": str(entry["reg_no"]), "entry": entry}
