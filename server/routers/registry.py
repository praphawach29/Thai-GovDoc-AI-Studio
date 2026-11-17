"""ทะเบียนรับ-ส่ง และการออกเลขที่หนังสือ

โหมด Supabase: ออกเลข/จอง/ยกเลิก/ลงรับ ผ่านฟังก์ชันในฐานข้อมูลเท่านั้น (atomic, ห้ามลบ, มี audit)
  — เลขลำดับไม่เคยคำนวณที่ฝั่ง client หรือ API (migration 2 + 13)
โหมดเครื่องเดียว: ใช้ core.registry (SQLite) เฉพาะจอง/ดูรายการ/ลงทะเบียนเดิม

ตรรกะหนังสือราชการ (รูปแบบเลขที่, แบบทะเบียน, Excel/PDF) อยู่ใน core/registry.py และ core/register_export.py
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional
from urllib.parse import quote
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel, Field, ValidationError

from core.models import GovDocumentSchema
from core.register_export import build_incoming_sheet, build_outgoing_sheet, sheet_to_pdf, sheet_to_xlsx
from core.registry import (
    DocumentRegistry, DuplicateRegistryEntry, IncomingRecord, NumberTemplate, OutgoingRecord,
    issue_draft_for, search_rows, split_number_template,
)
from core.thai_date import current_be_year
from core.thai_segmenter import to_thai_numerals
from server.auth import CurrentUser, get_current_user
from server.deps import get_registry
from server.settings import Settings, get_settings
from server.supabase import SupabaseClient, SupabaseError

router = APIRouter(tags=["registry"])
logger = logging.getLogger("govdoc.api")

_OUT_COLUMNS = ("id,book,reg_no,year_be,doc_number,doc_date,from_unit,to_recipient,subject,action_taken,"
                "remark,status,cancel_reason,document_id,incoming_id,created_by,created_at,"
                "issued_at,issued_by,cancelled_at,cancelled_by")
_IN_COLUMNS = ("id,reg_no,year_be,received_at,source_doc_number,source_doc_date,from_org,to_unit,"
               "subject,action_taken,remark,source_file_id,document_id,created_by,created_at")
_OUT_SEARCH = ["doc_number", "subject", "to_recipient", "from_unit", "doc_date", "cancel_reason", "remark", "reg_no"]
_IN_SEARCH = ["source_doc_number", "subject", "from_org", "to_unit", "source_doc_date", "remark", "reg_no"]
_MAX_ROWS = 5000
_MIGRATION_HINT = ("ฐานข้อมูลยังไม่รองรับทะเบียนแบบใหม่ — ให้ผู้ดูแลรัน supabase/migrations/20261116000013_registry_numbering.sql "
                   "ทั้งไฟล์ใน SQL Editor (ถ้ารันแล้ว ให้รัน: notify pgrst, 'reload schema';)")


class ReserveRequest(BaseModel):
    prefix: str = "ดพร ๐๑๐๒/"
    suffix: str = ""                           # รูปแบบเลขอยู่หน้า เช่น "/2569"
    subject: str
    reserved_by: str = "เจ้าหน้าที่สารบรรณ"   # โหมดเครื่องเดียว; โหมด Supabase ใช้ผู้ที่ล็อกอิน
    doc_type: str = "external"
    is_circular: bool = False
    to_recipient: str = ""
    from_unit: str = ""
    document_id: Optional[UUID] = None        # ผูกเลขกับเอกสาร (โหมด Supabase)


class IssueRequest(BaseModel):
    doc_date: Optional[str] = None


class CancelRequest(BaseModel):
    reason: str = Field(min_length=1, max_length=500)


class IncomingRequest(BaseModel):
    source_doc_number: str = ""
    source_doc_date: str = ""
    from_org: str = ""
    subject: str
    to_unit: str = ""
    source_file_id: Optional[UUID] = None
    document_id: Optional[UUID] = None        # เอกสารที่ร่างจากต้นเรื่องนี้ (หนังสือตอบ/บันทึกเสนอ)
    remark: str = ""


class DocumentIssueRequest(BaseModel):
    """ปุ่ม "ออกเลข" ในหน้าแก้ไข — ค่าว่าง = ใช้ค่าจากเอกสาร"""
    subject: str = Field(default="", max_length=1000)
    to_recipient: str = Field(default="", max_length=500)
    doc_date: str = Field(default="", max_length=100)
    from_unit: str = Field(default="", max_length=500)
    prefix: Optional[str] = Field(default=None, max_length=100)    # แก้รหัสเองได้ถ้าช่อง "ที่" ยังไม่มีรหัส
    suffix: Optional[str] = Field(default=None, max_length=100)
    is_circular: Optional[bool] = None
    reserved_id: Optional[int] = None                                 # ใช้เลขที่จองไว้แทนการออกเลขใหม่


def _client(user: Optional[CurrentUser], settings: Settings) -> Optional[SupabaseClient]:
    # isinstance: เรียกฟังก์ชันตรง (เช่นในเทสต์) ค่า default จะเป็นวัตถุ Depends ไม่ใช่ผู้ใช้
    if not isinstance(user, CurrentUser):
        return None
    return SupabaseClient(settings.supabase_url, settings.supabase_publishable_key, user.token)


def _needs_supabase():
    return HTTPException(status_code=501, detail="ใช้ได้เมื่อเชื่อมต่อ Supabase (โหมดเครื่องเดียวยังไม่รองรับ)")


def _require_client(user: Optional[CurrentUser], settings: Settings) -> SupabaseClient:
    client = _client(user, settings)
    if client is None:
        raise _needs_supabase()
    return client


def _rpc(client: SupabaseClient, name: str, params: Dict[str, Any]) -> Any:
    """เรียกฟังก์ชันทะเบียน — ฟังก์ชันใหม่ยังไม่มี (ยังไม่รัน migration 13) = บอกวิธีแก้แทน 404 เฉย ๆ"""
    try:
        return client.rpc(name, params)
    except SupabaseError as exc:
        text = f"{exc.code} {exc.message}"
        if any(k in text for k in ("PGRST202", "42883", "42703", "PGRST204", "Could not find the function")):
            logger.warning("registry rpc %s missing: %s", name, text)
            raise HTTPException(status_code=503, detail=_MIGRATION_HINT)
        raise


# ---------------------------------------------------------------- ช่วยอ่านข้อมูล
def _names(client: SupabaseClient) -> Dict[str, str]:
    """ชื่อผู้ใช้ในหน่วยงาน (RLS ให้เห็นเฉพาะหน่วยงานตัวเอง) สำหรับแสดง "ใคร" ในทะเบียน/audit"""
    try:
        rows = client.select("profiles", {"select": "user_id,full_name"})
    except SupabaseError:
        return {}
    return {str(r.get("user_id")): (r.get("full_name") or "").strip() for r in rows if r.get("user_id")}


def _org_name(client: SupabaseClient, user: CurrentUser) -> str:
    try:
        rows = client.select("profiles", {"select": "organizations(name)", "user_id": f"eq.{user.id}"})
    except SupabaseError:
        return ""
    org = (rows[0].get("organizations") if rows else None) or {}
    return str(org.get("name") or "")


def _year_filter(year: Optional[int]) -> Dict[str, str]:
    return {"year_be": f"eq.{year}"} if year else {}


def _outgoing_rows(client: SupabaseClient, year: Optional[int], status: Optional[str] = None) -> List[Dict[str, Any]]:
    params = {"select": _OUT_COLUMNS, "order": "id.desc", "limit": str(_MAX_ROWS), **_year_filter(year)}
    if status:
        params["status"] = f"eq.{status}"
    return client.select("outgoing_register", params)


def _incoming_rows(client: SupabaseClient, year: Optional[int]) -> List[Dict[str, Any]]:
    params = {"select": _IN_COLUMNS, "order": "id.desc", "limit": str(_MAX_ROWS), **_year_filter(year)}
    return client.select("incoming_register", params)


def _by_reg(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return sorted(rows, key=lambda r: (int(r.get("year_be") or 0), int(r.get("reg_no") or 0)), reverse=True)


def _decorate_outgoing(rows: List[Dict[str, Any]], names: Dict[str, str],
                       incoming_by_id: Dict[Any, Dict[str, Any]]) -> List[Dict[str, Any]]:
    out = []
    for r in rows:
        inc = incoming_by_id.get(r.get("incoming_id")) if r.get("incoming_id") else None
        out.append({
            **r,
            "created_by_name": names.get(str(r.get("created_by") or ""), ""),
            "issued_by_name": names.get(str(r.get("issued_by") or ""), ""),
            "cancelled_by_name": names.get(str(r.get("cancelled_by") or ""), ""),
            "incoming": {"id": inc.get("id"), "reg_no": inc.get("reg_no"), "year_be": inc.get("year_be"),
                         "subject": inc.get("subject")} if inc else None,
        })
    return out


def _replies_by_incoming(outgoing: List[Dict[str, Any]]) -> Dict[Any, List[Dict[str, Any]]]:
    replies: Dict[Any, List[Dict[str, Any]]] = {}
    for r in sorted(outgoing, key=lambda x: int(x.get("id") or 0)):
        if r.get("incoming_id"):
            replies.setdefault(r["incoming_id"], []).append(r)
    return replies


def _decorate_incoming(rows: List[Dict[str, Any]], names: Dict[str, str],
                       replies: Dict[Any, List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
    return [{
        **r,
        "created_by_name": names.get(str(r.get("created_by") or ""), ""),
        "replies": [{"id": x.get("id"), "doc_number": x.get("doc_number"), "doc_date": x.get("doc_date"),
                     "status": x.get("status"), "document_id": x.get("document_id")}
                    for x in replies.get(r.get("id"), [])],
    } for r in rows]


# ---------------------------------------------------------------- เลขที่ถัดไป / จอง / ยืนยัน / ยกเลิก
@router.get("/api/v1/registry/next-number")
def get_next_number(
    prefix: str = Query("ดพร ๐๑๐๒/"),
    suffix: str = Query(""),
    is_circular: bool = Query(False),
    registry: DocumentRegistry = Depends(get_registry),
    user: Optional[CurrentUser] = Depends(get_current_user),
    settings: Settings = Depends(get_settings),
):
    """ดูเลขที่ถัดไป — GET ต้องไม่เปลี่ยนข้อมูล จึงไม่กินเลข (ออกเลขจริงผ่าน POST) และอาจถูกคนอื่นออกก่อนได้"""
    client = _client(user, settings)
    if client is None:
        next_no = registry.peek_next_doc_number(prefix=prefix, is_circular=is_circular)
    else:
        template = NumberTemplate(prefix=prefix, suffix=suffix, is_circular=is_circular)
        book = "outgoing:" + prefix + ("ว" if is_circular else "") + (("|" + suffix) if suffix else "")
        rows = client.select("number_sequences", {
            "select": "last_value", "book": f"eq.{book}", "year_be": f"eq.{current_be_year()}",
        })
        next_no = template.format((rows[0]["last_value"] if rows else 0) + 1)
    return {"prefix": prefix, "suffix": suffix, "is_circular": is_circular, "doc_number": next_no}


@router.post("/api/v1/registry/reserve")
def reserve_number(
    req: ReserveRequest,
    registry: DocumentRegistry = Depends(get_registry),
    user: Optional[CurrentUser] = Depends(get_current_user),
    settings: Settings = Depends(get_settings),
):
    """จองเลขล่วงหน้าในทะเบียนส่ง (เลขออกจากฐานข้อมูล ไม่ซ้ำแม้กดพร้อมกัน)"""
    client = _client(user, settings)
    if client is None:
        if req.is_circular or req.document_id or req.suffix:
            raise _needs_supabase()
        reserved_no = registry.reserve_doc_number(
            prefix=req.prefix, subject=req.subject, reserved_by=req.reserved_by, doc_type=req.doc_type
        )
        return {"status": "success", "reserved_number": reserved_no}
    entry = _rpc(client, "issue_outgoing_number", {
        "p_prefix": req.prefix,
        "p_subject": req.subject,
        "p_to_recipient": req.to_recipient,
        "p_doc_date": None,
        "p_document_id": str(req.document_id) if req.document_id else None,
        "p_suffix": req.suffix,
        "p_from_unit": req.from_unit,
        "p_is_circular": req.is_circular,
        "p_reserve_only": True,
        "p_incoming_id": None,
    })
    return {"status": "success", "reserved_number": entry["doc_number"], "entry": entry}


@router.post("/api/v1/registry/outgoing/{entry_id}/issue")
def issue_number(
    entry_id: int,
    req: IssueRequest,
    user: Optional[CurrentUser] = Depends(get_current_user),
    settings: Settings = Depends(get_settings),
):
    """ยืนยันว่าเลขที่จองถูกใช้ส่งหนังสือจริง (ไม่ผูกเอกสาร)"""
    client = _require_client(user, settings)
    return _rpc(client, "use_reserved_number", {
        "p_id": entry_id, "p_document_id": None, "p_subject": None, "p_to_recipient": None,
        "p_doc_date": req.doc_date, "p_incoming_id": None,
    })


@router.post("/api/v1/registry/outgoing/{entry_id}/cancel")
def cancel_number(
    entry_id: int,
    req: CancelRequest,
    user: Optional[CurrentUser] = Depends(get_current_user),
    settings: Settings = Depends(get_settings),
):
    """ยกเลิกเลข (ต้องมีเหตุผล) — รายการยังอยู่ในทะเบียน และเลขไม่ถูกนำกลับมาใช้"""
    if not req.reason.strip():
        raise HTTPException(status_code=400, detail="ต้องระบุเหตุผลการยกเลิกเลข")
    client = _require_client(user, settings)
    return client.rpc("cancel_outgoing_number", {"p_id": entry_id, "p_reason": req.reason.strip()})


# ---------------------------------------------------------------- ออกเลขจากหน้าแก้ไข
def _load_document(client: SupabaseClient, document_id: UUID) -> Dict[str, Any]:
    docs = client.select("documents", {"select": "id,doc_number,status,workspace", "id": f"eq.{document_id}"})
    if not docs:
        raise HTTPException(status_code=404, detail="ไม่พบเอกสาร")
    return docs[0]


def _workspace_doc(row: Dict[str, Any]) -> GovDocumentSchema:
    raw = (row.get("workspace") or {}).get("doc")
    if not raw:
        raise HTTPException(status_code=422, detail="เอกสารนี้ยังไม่มีเนื้อความ — บันทึกก่อนออกเลข")
    try:
        return GovDocumentSchema.model_validate(raw)
    except ValidationError:
        raise HTTPException(status_code=422, detail="ข้อมูลเอกสารไม่ครบ — บันทึกเอกสารอีกครั้งแล้วลองใหม่")


def _linked_incoming(client: SupabaseClient, row: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """หนังสือรับที่เอกสารนี้ตอบ: ลงรับผูกเอกสารนี้ไว้ หรือเป็นไฟล์ต้นเรื่องเดียวกัน (ฉบับเสนอขั้นถัดไป)"""
    found = client.select("incoming_register", {"select": _IN_COLUMNS, "document_id": f"eq.{row['id']}", "limit": "1"})
    if found:
        return found[0]
    source = (row.get("workspace") or {}).get("sourceFileId")
    if source:
        found = client.select("incoming_register", {"select": _IN_COLUMNS, "source_file_id": f"eq.{source}", "limit": "1"})
        if found:
            return found[0]
    return None


@router.get("/api/v1/registry/documents/{document_id}")
def document_registry(
    document_id: UUID,
    user: Optional[CurrentUser] = Depends(get_current_user),
    settings: Settings = Depends(get_settings),
):
    """สถานะทะเบียนของเอกสาร: เลขที่ออกแล้ว/ยกเลิก, ค่าที่จะลงทะเบียน, เลขที่จองไว้ที่ใช้ได้, หนังสือรับที่เกี่ยวข้อง"""
    client = _require_client(user, settings)
    row = _load_document(client, document_id)
    raw = (row.get("workspace") or {}).get("doc")
    draft = None
    if raw:
        try:
            draft = issue_draft_for(GovDocumentSchema.model_validate(raw))
        except ValidationError:
            draft = None
    try:
        entries = client.select("outgoing_register", {
            "select": _OUT_COLUMNS, "document_id": f"eq.{document_id}", "order": "id.desc",
        })
        reserved = client.select("outgoing_register", {
            "select": _OUT_COLUMNS, "status": "eq.reserved", "order": "id.asc", "limit": "50",
        })
        incoming = _linked_incoming(client, row)
    except SupabaseError as exc:
        if exc.status in (400, 404) or "42703" in exc.code:
            raise HTTPException(status_code=503, detail=_MIGRATION_HINT)
        raise
    names = _names(client)
    if draft and draft.template:
        book = "outgoing:" + draft.template.prefix + ("ว" if draft.template.is_circular else "") + \
               (("|" + draft.template.suffix) if draft.template.suffix else "")
        reserved = [r for r in reserved if r.get("book") == book and not r.get("document_id")]
    else:
        reserved = []
    active = next((e for e in entries if e.get("status") != "cancelled"), None)
    return {
        "draft": draft.model_dump() if draft else None,
        "active": _decorate_outgoing([active], names, {})[0] if active else None,
        "entries": _decorate_outgoing(entries, names, {}),
        "reserved": _decorate_outgoing(reserved, names, {}),
        "incoming": incoming,
    }


@router.post("/api/v1/registry/documents/{document_id}/issue")
def issue_for_document(
    document_id: UUID,
    req: DocumentIssueRequest,
    user: Optional[CurrentUser] = Depends(get_current_user),
    settings: Settings = Depends(get_settings),
):
    """ปุ่ม "ออกเลข": ออกเลขจากฐานข้อมูล (หรือใช้เลขที่จองไว้) ผูกกับเอกสาร ลงทะเบียนส่งพร้อม วันที่ เรื่อง ผู้รับ

    อ่านเอกสารจากเซิร์ฟเวอร์เอง (หน้าแก้ไขบันทึกก่อนเรียก) — ไม่เชื่อเลขที่จากเบราว์เซอร์
    """
    client = _require_client(user, settings)
    row = _load_document(client, document_id)
    draft = issue_draft_for(_workspace_doc(row))
    subject = req.subject.strip() or draft.subject
    if not subject:
        raise HTTPException(status_code=422, detail="ยังไม่มีเรื่อง — ใส่เรื่องของหนังสือก่อนออกเลข")
    incoming = _linked_incoming(client, row)
    common = {
        "p_document_id": str(document_id),
        "p_subject": subject,
        "p_to_recipient": req.to_recipient.strip() or draft.to_recipient,
        "p_doc_date": req.doc_date.strip() or draft.doc_date,
        "p_incoming_id": incoming["id"] if incoming else None,
    }
    if req.reserved_id is not None:
        entry = _rpc(client, "use_reserved_number", {"p_id": req.reserved_id, **common})
    else:
        template = draft.template
        if req.prefix is not None or req.suffix is not None:
            template = NumberTemplate(prefix=(req.prefix or "").strip(), suffix=(req.suffix or "").strip(),
                                      is_circular=bool(req.is_circular))
        if template is None or not (template.prefix + template.suffix).strip():
            if draft.current_number:
                raise HTTPException(status_code=409, detail=f"ช่อง \"ที่\" มีเลขแล้ว ({draft.current_number}) — "
                                                            "ถ้าจะออกเลขใหม่ ให้ลบเลขในช่อง \"ที่\" เหลือแค่รหัส เช่น กท 1205/")
            raise HTTPException(status_code=422, detail="ยังไม่มีรหัสหนังสือในช่อง \"ที่\" (เช่น กท 1205/) — ระบุรหัสก่อนออกเลข")
        entry = _rpc(client, "issue_outgoing_number", {
            "p_prefix": template.prefix, "p_suffix": template.suffix, "p_is_circular": template.is_circular,
            "p_from_unit": req.from_unit.strip() or draft.from_unit, "p_reserve_only": False, **common,
        })
    return {"status": "issued", "doc_number": entry["doc_number"], "entry": entry,
            "incoming": {"id": incoming["id"], "reg_no": incoming.get("reg_no"), "year_be": incoming.get("year_be")} if incoming else None}


# ---------------------------------------------------------------- ทะเบียนส่ง
@router.get("/api/v1/registry/outgoing")
def list_outgoing(
    limit: int = Query(50, ge=1, le=_MAX_ROWS),
    year: Optional[int] = Query(None, ge=2400, le=2700),
    q: str = Query("", max_length=200),
    status: Optional[str] = Query(None, pattern="^(reserved|issued|cancelled)$"),
    registry: DocumentRegistry = Depends(get_registry),
    user: Optional[CurrentUser] = Depends(get_current_user),
    settings: Settings = Depends(get_settings),
):
    client = _client(user, settings)
    if client is None:
        return registry.list_outgoing(limit=limit)
    rows = search_rows(_by_reg(_outgoing_rows(client, year, status)), q, _OUT_SEARCH)[:limit]
    incoming_ids = {r["incoming_id"] for r in rows if r.get("incoming_id")}
    incoming = {}
    if incoming_ids:
        incoming = {i["id"]: i for i in client.select("incoming_register", {
            "select": "id,reg_no,year_be,subject", "id": "in.(" + ",".join(str(x) for x in sorted(incoming_ids)) + ")",
        })}
    return _decorate_outgoing(rows, _names(client), incoming)


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


# ---------------------------------------------------------------- ทะเบียนรับ
@router.get("/api/v1/registry/incoming")
def list_incoming(
    limit: int = Query(50, ge=1, le=_MAX_ROWS),
    year: Optional[int] = Query(None, ge=2400, le=2700),
    q: str = Query("", max_length=200),
    registry: DocumentRegistry = Depends(get_registry),
    user: Optional[CurrentUser] = Depends(get_current_user),
    settings: Settings = Depends(get_settings),
):
    client = _client(user, settings)
    if client is None:
        return registry.list_incoming(limit=limit)
    rows = search_rows(_by_reg(_incoming_rows(client, year)), q, _IN_SEARCH)[:limit]
    replies: Dict[Any, List[Dict[str, Any]]] = {}
    ids = [r["id"] for r in rows if r.get("id") is not None]
    if ids:
        linked = client.select("outgoing_register", {
            "select": "id,incoming_id,doc_number,doc_date,status,document_id",
            "incoming_id": "in.(" + ",".join(str(x) for x in ids) + ")",
        })
        replies = _replies_by_incoming(linked)
    return _decorate_incoming(rows, _names(client), replies)


@router.get("/api/v1/registry/incoming/by-source/{source_file_id}")
def incoming_by_source(
    source_file_id: UUID,
    user: Optional[CurrentUser] = Depends(get_current_user),
    settings: Settings = Depends(get_settings),
):
    """ต้นเรื่องไฟล์นี้ลงรับแล้วหรือยัง (หน้าแก้ไขแสดงเลขรับ หรือฟอร์มลงรับ)"""
    client = _require_client(user, settings)
    rows = client.select("incoming_register", {"select": _IN_COLUMNS, "source_file_id": f"eq.{source_file_id}", "limit": "1"})
    if not rows:
        return {"entry": None}
    names = _names(client)
    linked = client.select("outgoing_register", {
        "select": "id,incoming_id,doc_number,doc_date,status,document_id", "incoming_id": f"eq.{rows[0]['id']}",
    })
    return {"entry": _decorate_incoming(rows, names, _replies_by_incoming(linked))[0]}


@router.post("/api/v1/registry/incoming")
def create_incoming(
    body: dict,
    registry: DocumentRegistry = Depends(get_registry),
    user: Optional[CurrentUser] = Depends(get_current_user),
    settings: Settings = Depends(get_settings),
):
    """ลงทะเบียนรับ — โหมด Supabase ออกเลขทะเบียนรับและเวลารับจากฐานข้อมูล"""
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
    if not req.subject.strip():
        raise HTTPException(status_code=422, detail="ต้องระบุเรื่องของหนังสือที่รับ")
    entry = _rpc(client, "register_incoming", {
        "p_source_doc_number": req.source_doc_number.strip(),
        "p_source_doc_date": req.source_doc_date.strip(),
        "p_from_org": req.from_org.strip(),
        "p_subject": req.subject.strip(),
        "p_to_unit": req.to_unit.strip(),
        "p_source_file_id": str(req.source_file_id) if req.source_file_id else None,
        "p_remark": req.remark.strip(),
        "p_document_id": str(req.document_id) if req.document_id else None,
    })
    return {"status": "registered", "registry_id": entry["id"], "receive_number": str(entry["reg_no"]), "entry": entry}


# ---------------------------------------------------------------- ปี / audit / ส่งออก
@router.get("/api/v1/registry/years")
def registry_years(
    user: Optional[CurrentUser] = Depends(get_current_user),
    settings: Settings = Depends(get_settings),
):
    """ปี พ.ศ. ที่มีในทะเบียน (รวมปีปัจจุบันเสมอ) เรียงใหม่ไปเก่า"""
    client = _require_client(user, settings)
    years = {current_be_year()}
    for table in ("outgoing_register", "incoming_register"):
        years.update(int(r["year_be"]) for r in client.select(table, {"select": "year_be", "limit": str(_MAX_ROWS)})
                     if r.get("year_be"))
    return {"years": sorted(years, reverse=True), "current": current_be_year()}


_AUDIT_ACTIONS = {"reserve": "จองเลข", "issue": "ออกเลข", "cancel": "ยกเลิกเลข", "receive": "ลงรับ",
                  "insert": "เพิ่ม", "update": "แก้ไข"}


@router.get("/api/v1/registry/audit")
def registry_audit(
    entity: str = Query(..., pattern="^(outgoing|incoming)$"),
    entity_id: int = Query(..., ge=1),
    user: Optional[CurrentUser] = Depends(get_current_user),
    settings: Settings = Depends(get_settings),
):
    """ประวัติของรายการในทะเบียน (ใคร ทำอะไร เมื่อไร) จาก audit_log ที่แก้ย้อนหลังไม่ได้"""
    client = _require_client(user, settings)
    rows = client.select("audit_log", {
        "select": "id,action,actor_id,details,at", "entity": f"eq.{entity}_register",
        "entity_id": f"eq.{entity_id}", "order": "id.asc",
    })
    names = _names(client)
    return [{**r, "actor_name": names.get(str(r.get("actor_id") or ""), ""),
             "action_label": _AUDIT_ACTIONS.get(str(r.get("action")), str(r.get("action")))} for r in rows]


@router.get("/api/v1/registry/{kind}/export")
def export_register(
    kind: str,
    format: str = Query("xlsx", pattern="^(xlsx|pdf)$"),
    year: Optional[int] = Query(None, ge=2400, le=2700),
    q: str = Query("", max_length=200),
    thai: bool = Query(True),
    user: Optional[CurrentUser] = Depends(get_current_user),
    settings: Settings = Depends(get_settings),
):
    """พิมพ์ทะเบียนตามแบบในระเบียบงานสารบรรณ (ทั้งปีหรือเฉพาะที่ค้น) เป็น Excel หรือ PDF"""
    if kind not in ("outgoing", "incoming"):
        raise HTTPException(status_code=404, detail="ไม่มีทะเบียนนี้")
    client = _require_client(user, settings)
    year = year or current_be_year()
    org_name = _org_name(client, user)
    if kind == "outgoing":
        rows = search_rows(_outgoing_rows(client, year), q, _OUT_SEARCH)
        ids = sorted({r["incoming_id"] for r in rows if r.get("incoming_id")})
        incoming = {i["id"]: i for i in client.select("incoming_register", {
            "select": "id,reg_no,year_be", "id": "in.(" + ",".join(str(x) for x in ids) + ")"})} if ids else {}
        sheet = build_outgoing_sheet(rows, org_name=org_name, year_be=year, incoming_by_id=incoming,
                                     names=_names(client), thai_digits=thai)
        title = "ทะเบียนหนังสือส่ง"
    else:
        rows = search_rows(_incoming_rows(client, year), q, _IN_SEARCH)
        ids = [r["id"] for r in rows if r.get("id") is not None]
        linked = client.select("outgoing_register", {
            "select": "id,incoming_id,doc_number,doc_date,status",
            "incoming_id": "in.(" + ",".join(str(x) for x in ids) + ")"}) if ids else []
        sheet = build_incoming_sheet(rows, org_name=org_name, year_be=year,
                                     replies_by_incoming=_replies_by_incoming(linked), thai_digits=thai)
        title = "ทะเบียนหนังสือรับ"
    year_text = to_thai_numerals(str(year)) if thai else str(year)
    filename = f"{title}_{year_text}.{format}"
    if format == "xlsx":
        data = sheet_to_xlsx(sheet)
        media = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    else:
        try:
            data = sheet_to_pdf(sheet, thai_digits=thai)
        except RuntimeError as exc:
            logger.error("register pdf failed: %s", exc)
            raise HTTPException(status_code=500, detail="สร้าง PDF ทะเบียนไม่สำเร็จ")
        media = "application/pdf"
    ascii_name = f"{kind}-register-{year}.{format}"
    return Response(content=data, media_type=media, headers={
        "Content-Disposition": f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(filename)}",
        "X-GovDoc-Rows": str(sheet.row_count()),
    })
