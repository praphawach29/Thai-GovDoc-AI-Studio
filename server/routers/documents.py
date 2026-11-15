"""เอกสารที่เก็บบนเซิร์ฟเวอร์ (โหมด Supabase): ร่างที่กำลังแก้ + ประวัติเวอร์ชัน"""

from typing import Any, Dict, List, Literal, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from core.models import GovDocumentSchema
from server.auth import CurrentUser, Profile, get_profile, get_supabase, require_supabase_user
from server.supabase import SupabaseClient

router = APIRouter(tags=["documents"])

_LIST_COLUMNS = "id,subject,kind,doc_type,status,doc_number,urgency,secret_level,current_version,updated_at"
# ค่าสรุปจาก workspace สำหรับรายการงาน (เลือกเฉพาะส่วนที่ใช้ ไม่ดึงต้นเรื่องทั้งฉบับ)
_SUMMARY_COLUMNS = (
    "unit_key:workspace->>unitKey,source_name:workspace->>sourceName,edit_status:workspace->doc->>edit_status,"
    "placeholders:workspace->check->placeholders,issues:workspace->check->lint->issues"
)


class DocumentIn(BaseModel):
    doc: GovDocumentSchema
    # สถานะหน้าแก้ไขอื่น ๆ (ต้นเรื่อง, ผลตรวจ, คำสั่ง, ขั้นตอน) — เก็บคู่กับเอกสาร
    workspace: Dict[str, Any] = Field(default_factory=dict)


class VersionIn(BaseModel):
    doc: GovDocumentSchema
    note: Optional[str] = None
    edit_instruction: Optional[str] = None


def _columns(doc: GovDocumentSchema) -> Dict[str, Any]:
    """ค่าที่ใช้ค้น/แสดงรายการ เก็บเป็นคอลัมน์แยกจากตัวเอกสาร"""
    return {
        "kind": doc.kind.value,
        "doc_type": doc.doc_type.value,
        "urgency": doc.urgency.value,
        "secret_level": doc.secret.value,
        "subject": doc.subject[:500],
    }


def _workspace(body: DocumentIn) -> Dict[str, Any]:
    ws = dict(body.workspace)
    ws["doc"] = body.doc.model_dump(mode="json")
    return ws


class StatusIn(BaseModel):
    # เก็บ (ซ่อนจากรายการงาน) หรือดึงกลับมาเป็นร่าง — สถานะอื่นมาจากทะเบียน/การออกเลข
    status: Literal["archived", "draft"]


def _summary(row: Dict[str, Any]) -> Dict[str, Any]:
    """รายการงาน: นับจุดที่ต้องแก้ (ต้องระบุ + ข้อควรแก้ตามระเบียบ) จากผลตรวจล่าสุดที่หน้าแก้ไขบันทึกไว้"""
    out = {k: v for k, v in row.items() if k not in ("placeholders", "issues")}
    placeholders: List[Any] = row.get("placeholders") or []
    issues: List[Any] = row.get("issues") or []
    out["todo"] = len(placeholders) + len(issues)
    return out


@router.get("/api/v1/documents")
def list_documents(
    limit: int = Query(30, ge=1, le=200),
    archived: bool = Query(False, description="true = เฉพาะเอกสารที่เก็บแล้ว"),
    client: SupabaseClient = Depends(get_supabase),
):
    rows = client.select("documents", {
        "select": _LIST_COLUMNS + "," + _SUMMARY_COLUMNS, "order": "updated_at.desc", "limit": str(limit),
        "status": "eq.archived" if archived else "neq.archived",
    })
    return [_summary(r) for r in rows]


@router.patch("/api/v1/documents/{document_id}/status")
def set_document_status(document_id: UUID, body: StatusIn, client: SupabaseClient = Depends(get_supabase)):
    """เก็บเอกสาร (ฉบับทดลอง/ไม่ใช้แล้ว) ออกจากรายการงาน — ไม่ลบ ดึงกลับได้ ประวัติเวอร์ชันยังอยู่ครบ"""
    rows = client.update("documents", {"id": f"eq.{document_id}"}, {"status": body.status})
    if not rows:
        raise HTTPException(status_code=404, detail="ไม่พบเอกสาร")
    return {"id": str(document_id), "status": rows[0].get("status", body.status)}


@router.post("/api/v1/documents", status_code=201)
def create_document(
    body: DocumentIn,
    user: CurrentUser = Depends(require_supabase_user),
    profile: Profile = Depends(get_profile),
    client: SupabaseClient = Depends(get_supabase),
):
    row = client.insert(
        "documents",
        {"org_id": profile.org_id, "owner_id": user.id, "workspace": _workspace(body), **_columns(body.doc)},
    )
    version = client.rpc(
        "save_document_version",
        {"p_document_id": row["id"], "p_content": body.doc.model_dump(mode="json"), "p_note": "สร้างเอกสาร"},
    )
    return {"id": row["id"], "version": version}


@router.get("/api/v1/documents/{document_id}")
def get_document(document_id: UUID, client: SupabaseClient = Depends(get_supabase)):
    rows = client.select("documents", {"select": _LIST_COLUMNS + ",workspace", "id": f"eq.{document_id}"})
    if not rows:
        raise HTTPException(status_code=404, detail="ไม่พบเอกสาร")
    return rows[0]


@router.patch("/api/v1/documents/{document_id}")
def autosave_document(document_id: UUID, body: DocumentIn, client: SupabaseClient = Depends(get_supabase)):
    """บันทึกอัตโนมัติ: แก้ร่างที่กำลังทำ (ไม่สร้างเวอร์ชันใหม่)"""
    rows = client.update(
        "documents", {"id": f"eq.{document_id}"}, {"workspace": _workspace(body), **_columns(body.doc)}
    )
    if not rows:
        raise HTTPException(status_code=404, detail="ไม่พบเอกสาร")
    return {"id": str(document_id), "updated_at": rows[0].get("updated_at")}


@router.post("/api/v1/documents/{document_id}/versions", status_code=201)
def save_version(document_id: UUID, body: VersionIn, client: SupabaseClient = Depends(get_supabase)):
    """เก็บจุดบันทึก (ลบ/แก้ภายหลังไม่ได้)"""
    version = client.rpc(
        "save_document_version",
        {
            "p_document_id": str(document_id),
            "p_content": body.doc.model_dump(mode="json"),
            "p_edit_instruction": body.edit_instruction,
            "p_note": body.note,
        },
    )
    return {"id": str(document_id), "version": version}


@router.get("/api/v1/documents/{document_id}/versions")
def list_versions(document_id: UUID, client: SupabaseClient = Depends(get_supabase)):
    return client.select(
        "document_versions",
        {
            "select": "version_no,note,edit_instruction,created_at,created_by",
            "document_id": f"eq.{document_id}",
            "order": "version_no.desc",
        },
    )


@router.get("/api/v1/documents/{document_id}/versions/{version_no}")
def get_version(document_id: UUID, version_no: int, client: SupabaseClient = Depends(get_supabase)):
    rows = client.select(
        "document_versions",
        {"select": "version_no,content,note,created_at", "document_id": f"eq.{document_id}",
         "version_no": f"eq.{version_no}"},
    )
    if not rows:
        raise HTTPException(status_code=404, detail="ไม่พบเวอร์ชันนี้")
    return rows[0]
