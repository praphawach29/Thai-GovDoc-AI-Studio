"""API ของหน้าเว็บ Thai GovDoc AI Studio (หน้าแรก + หน้าแก้ไขเอกสาร)"""

from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel

from core.issuing_units import apply_issuing_unit, pick_unit
from core.models import DocType, GovDocumentSchema, IssuingUnit, SecretLevel, Signer, UrgencyLevel, parse_form_key
from core.profile_manager import get_user_profile
import time

from core.fact_check import check_facts
from core.signers import OrgSigner, fill_document_signers
from core.studio import (
    MAX_REFERENCES,
    StudioCheck,
    StudioStep,
    read_source_text,
    StudioDraftResult,
    check_document,
    create_blank_document,
    normalize_for_editor,
    start_draft,
)
from core.templates_library import get_preset_template, list_preset_templates
from server import source_store
from server.auth import CurrentUser, get_current_user, get_profile, get_supabase
from server.deps import save_upload
from server.routers.examples import example_finder
from server.routers.org_profile import load_org_profile
from server.routers.signers import load_roster
from server.settings import Settings, get_settings, llm_config
from server.supabase import SupabaseClient

router = APIRouter(tags=["studio"])


class StudioDraftResponse(StudioDraftResult):
    # โหมด Supabase: แถวใน source_files ของไฟล์ต้นเรื่อง (ผูกกับเอกสารภายหลังได้)
    source_file_id: Optional[str] = None


class BlankRequest(BaseModel):
    # คีย์ประเภท: internal / external / stamp_letter / ... (core.models.FORM_KEYS)
    doc_type: str = "internal"
    unit_key: Optional[str] = None


def _form(key: Optional[str]):
    """คีย์ประเภทจากหน้าเว็บ → (DocType, DocumentKind) หรือ None; ไม่รู้จัก = 400"""
    try:
        return parse_form_key(key)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


class ApplyUnitRequest(BaseModel):
    doc: GovDocumentSchema
    unit_key: Optional[str] = None


_UNIT_COLUMNS = ("key,label,dept_name,doc_number_format,contact_dept,contact_tel,contact_fax,"
                 "blank_day,is_default,recipient,signers,review_party,request_text")


def load_units(user: Optional[CurrentUser], settings: Settings) -> List[IssuingUnit]:
    """หน่วยออกหนังสือ: โหมด Supabase อ่านตาราง org_units ของหน่วยงาน, โหมดเครื่องเดียวอ่านโปรไฟล์"""
    if isinstance(user, CurrentUser):
        rows = get_supabase(user, settings).select(
            "org_units", {"select": _UNIT_COLUMNS, "order": "sort_order.asc,label.asc"}
        )
        if rows:
            return [IssuingUnit(**row) for row in rows]
    return get_user_profile().issuing_units


def _author(user: Optional[CurrentUser], settings: Settings) -> Optional[Signer]:
    """ชื่อ/ตำแหน่งของผู้ใช้ที่ล็อกอิน (ใช้เป็นผู้ลงนามที่เป็นผู้เสนอเรื่อง)"""
    if not isinstance(user, CurrentUser):
        return None
    try:
        profile = get_profile(user, get_supabase(user, settings))
    except HTTPException:
        return None
    name = profile.full_name.strip()
    return Signer(name=f"({name})" if name else "", position=profile.position.strip(), is_author=True)


def _roster(user: Optional[CurrentUser], settings: Settings) -> List[OrgSigner]:
    """รายชื่อผู้ลงนามของหน่วยงาน (โหมด Supabase เท่านั้น; ไม่มี/ขัดข้อง = รายการว่าง)"""
    if not isinstance(user, CurrentUser):
        return []
    return load_roster(get_supabase(user, settings))


def _fill_signers(doc: GovDocumentSchema, user, settings, fresh: bool = False) -> GovDocumentSchema:
    """หนังสือภายนอก: ผู้ลงนามจากรายชื่อของหน่วยงาน (ตำแหน่งตรงกัน หรือผู้ลงนามเริ่มต้นเมื่อร่างใหม่)"""
    return fill_document_signers(doc, _roster(user, settings), use_default=fresh)


def _apply_unit(doc: GovDocumentSchema, unit_key: Optional[str], user, settings,
                fresh: bool = False) -> GovDocumentSchema:
    """fresh = ร่างใหม่ (ใช้ภาคความประสงค์มาตรฐานของหน่วยแทนข้อความที่ร่างมา และผู้ลงนามเริ่มต้นของหน่วยงาน)"""
    units = load_units(user, settings)
    unit = pick_unit(units, unit_key)
    if unit_key and (unit is None or unit.key != unit_key):
        raise HTTPException(status_code=404, detail="ไม่พบหน่วยออกหนังสือนี้")
    if unit is None:
        return doc
    return apply_issuing_unit(doc, unit, author=_author(user, settings), units=units, replace_request=fresh,
                              roster=_roster(user, settings), use_default=fresh)


@router.get("/api/v1/studio/units")
def studio_units(
    user: Optional[CurrentUser] = Depends(get_current_user),
    settings: Settings = Depends(get_settings),
):
    """หน่วยออกหนังสือที่เลือกได้ (ส่วนราชการ + รูปแบบเลขที่)"""
    return [u.model_dump() for u in load_units(user, settings)]


@router.post("/api/v1/studio/apply-unit", response_model=GovDocumentSchema)
def studio_apply_unit(
    req: ApplyUnitRequest,
    user: Optional[CurrentUser] = Depends(get_current_user),
    settings: Settings = Depends(get_settings),
):
    """เปลี่ยนหน่วยออกหนังสือของเอกสาร: ส่วนราชการ, เลขที่ (เว้นเขียนมือ), วันที่, ผู้ประสาน"""
    return _apply_unit(req.doc, req.unit_key, user, settings)


@router.get("/api/v1/studio/profile")
def studio_profile(
    user: Optional[CurrentUser] = Depends(get_current_user),
    settings: Settings = Depends(get_settings),
):
    """ข้อมูลหน่วยงาน สำหรับแสดง/แก้บนหน้าแรก — editable = แก้จากหน้าเว็บได้ (โหมด Supabase)"""
    profile = load_org_profile(user, settings)
    return {**profile.model_dump(mode="json", exclude={"issuing_units"}), "editable": isinstance(user, CurrentUser)}


@router.post("/api/v1/studio/draft", response_model=StudioDraftResponse)
async def studio_draft(
    prompt: str = Form(""),
    doc_type: Optional[str] = Form(None),           # คีย์ประเภท (ว่าง = อัตโนมัติ)
    urgency: UrgencyLevel = Form(UrgencyLevel.NORMAL),
    secret: SecretLevel = Form(SecretLevel.NORMAL),
    file: Optional[UploadFile] = File(None),
    source_path: Optional[str] = Form(None),     # โหมด Supabase: ไฟล์ที่อัปโหลดตรงเข้า Storage แล้ว
    source_name: Optional[str] = Form(None),
    unit_key: Optional[str] = Form(None),        # หน่วยออกหนังสือ (ไม่ระบุ = หน่วยตั้งต้น)
    template: Optional[UploadFile] = File(None),  # (เดิม) ต้นแบบไฟล์เดียว — ใช้ references แทน
    references: List[UploadFile] = File(default=[]),  # ต้นแบบ: คู่มือ PDF / แบบฟอร์ม / ฉบับก่อนที่อนุมัติ (PDF/Word/ภาพ ≤ 3 ไฟล์)
    settings: Settings = Depends(get_settings),
    user: Optional[CurrentUser] = Depends(get_current_user),
):
    """เริ่มร่างจากคำสั่งที่พิมพ์และ/หรือไฟล์ต้นเรื่อง (สกัด → จำแนก → ร่าง → ตรวจ)

    โหมด Supabase: ไฟล์ต้นเรื่องทุกไฟล์ถูกเก็บใน Storage + ตาราง source_files
    และไฟล์ชั่วคราวบนเซิร์ฟเวอร์ถูกลบทันทีหลังอ่านเสร็จ
    """
    form = _form(doc_type)
    internal = form is not None and form[0] == DocType.INTERNAL
    has_file = file is not None and bool(file.filename)
    if not has_file and not source_path and not prompt.strip():
        raise HTTPException(status_code=400, detail="พิมพ์คำสั่งหรือแนบไฟล์ต้นเรื่องก่อนเริ่มร่าง")

    stored = None   # (path, filename, bytes) ที่ต้องบันทึกลง source_files
    saved_path: Optional[Path] = None
    if user is None:
        if source_path:
            raise HTTPException(status_code=400, detail="source_path ใช้ได้เมื่อเชื่อมต่อ Supabase เท่านั้น")
        if has_file:
            saved_path = await save_upload(file, settings)
    else:
        client = get_supabase(user, settings)
        profile = get_profile(user, client)
        if source_path:
            data, saved_path = source_store.download_source(client, settings, profile, source_path)
            stored = (source_path, source_name or Path(source_path).name, data)
        elif has_file:
            saved_path = await save_upload(file, settings)
            data = saved_path.read_bytes()
            path = source_store.new_storage_path(profile, file.filename)
            client.upload(settings.source_bucket, path, data, source_store.MIME_BY_SUFFIX[saved_path.suffix])
            stored = (path, file.filename, data)

    started = time.monotonic()
    ref_files = [f for f in [template, *references] if f is not None and f.filename]
    if len(ref_files) > MAX_REFERENCES:
        raise HTTPException(status_code=400, detail=f"แนบต้นแบบได้ไม่เกิน {MAX_REFERENCES} ไฟล์")
    ref_texts, ref_steps = [], []
    for f in ref_files:
        name, text, error = await read_reference(f, settings, secret)
        if text:
            ref_texts.append((name, text))
        else:
            ref_steps.append(StudioStep(key="reference", label="อ่านไฟล์ต้นแบบไม่สำเร็จ", ok=False, detail=f"{name}: {error}"))

    # ผู้รับและชื่อผู้พิจารณาของหน่วยที่เลือก ช่วยให้ AI เขียนข้อพิจารณาได้ตรงขั้นการเสนอ
    unit = pick_unit(load_units(user, settings), unit_key)
    try:
        result = start_draft(
            prompt=prompt,
            file_path=str(saved_path) if saved_path else None,
            form_hint=doc_type or None,
            urgency=urgency,
            secret=secret,
            llm=llm_config(settings),
            recipient=unit.recipient if unit and (form is None or internal) else "",
            review_party=unit.review_party if unit and (form is None or internal) else "",
            # สำนวนจากหนังสือฉบับจริงของหน่วยงาน (คลังตัวอย่าง) — โหมด Supabase เท่านั้น
            find_examples=example_finder(client) if user is not None else None,
            profile=load_org_profile(user, settings),
            references=ref_texts,
            budget_used_s=time.monotonic() - started,
        )
        result.steps[:0] = ref_steps
    finally:
        if user is not None and saved_path is not None:
            saved_path.unlink(missing_ok=True)

    response = StudioDraftResponse(**result.model_dump())
    if response.document is not None and response.document.doc_type == DocType.INTERNAL:
        # บันทึกข้อความ: ส่วนราชการ/เลขที่/วันที่ ตามหน่วยออกหนังสือที่เลือก
        response.document = _apply_unit(response.document, unit_key, user, settings, fresh=True)
    elif response.document is not None:
        response.document = _fill_signers(response.document, user, settings, fresh=True)
    display_name = Path(file.filename).name if has_file else (Path(stored[1]).name if stored else None)
    if response.context is not None and display_name:
        response.context.source_filename = display_name
    if stored is not None:
        response.source_file_id = source_store.record_source_file(
            client, user, profile, path=stored[0], filename=stored[1], data=stored[2],
            ctx=response.context, secret=secret,
        )
    return response


async def read_reference(upload: UploadFile, settings: Settings, secret: SecretLevel) -> tuple:
    """ข้อความของไฟล์ต้นแบบ (PDF/Word/ภาพ — สแกนให้ AI อ่าน) ไม่เก็บไฟล์: คืน (ชื่อ, ข้อความ, สาเหตุที่อ่านไม่ได้)
    ชนิดไฟล์ไม่รองรับ = 400 (ผู้ใช้ต้องรู้ทันที) / อ่านไม่ออก = ข้ามไฟล์นั้นแล้วร่างต่อ"""
    name = Path(upload.filename or "").name
    path = await save_upload(upload, settings)
    try:
        text, error = read_source_text(str(path), llm_config(settings), secret)
    finally:
        path.unlink(missing_ok=True)
    return name, text, error


@router.post("/api/v1/studio/blank", response_model=GovDocumentSchema)
def studio_blank(
    req: BlankRequest,
    user: Optional[CurrentUser] = Depends(get_current_user),
    settings: Settings = Depends(get_settings),
):
    """เอกสารเปล่าตามประเภทที่เลือก (บันทึกข้อความ / หนังสือภายนอก / หนังสือประทับตรา / ...) พร้อม placeholder"""
    doc_type, kind = _form(req.doc_type) or (DocType.INTERNAL, None)
    doc = normalize_for_editor(create_blank_document(doc_type, profile=load_org_profile(user, settings), kind=kind))
    if doc_type == DocType.INTERNAL:
        doc = _apply_unit(doc, req.unit_key, user, settings, fresh=True)
    else:
        doc = _fill_signers(doc, user, settings, fresh=True)
    return doc


@router.get("/api/v1/studio/templates")
def studio_templates():
    """รายการแม่แบบมาตรฐาน (ไม่รวมเนื้อหา)"""
    return [
        {"id": t.template_id, "title": t.title, "category": t.category, "doc_type": t.doc_type.value}
        for t in list_preset_templates()
    ]


@router.get("/api/v1/studio/templates/{template_id}", response_model=GovDocumentSchema)
def studio_template(template_id: str):
    t = get_preset_template(template_id)
    if t is None:
        raise HTTPException(status_code=404, detail="ไม่พบแม่แบบ")
    return normalize_for_editor(t.schema.model_copy(deep=True))


class FactCheckRequest(BaseModel):
    doc: GovDocumentSchema
    source_text: str = ""      # ข้อความที่อ่านจากต้นเรื่อง + คำสั่งที่ผู้ใช้พิมพ์


@router.post("/api/v1/studio/fact-check")
def studio_fact_check(req: FactCheckRequest):
    """วันที่ เวลา ตัวเลขในร่างที่หาในต้นเรื่องไม่เจอ (AI อาจอ่านไฟล์สแกนคลาด)"""
    issues = check_facts(req.doc, req.source_text)
    return {"checked": len(req.source_text.strip()) >= 40, "issues": [i.model_dump() for i in issues]}


@router.post("/api/v1/studio/check", response_model=StudioCheck)
def studio_check(doc: GovDocumentSchema):
    """ตรวจ placeholder ที่ค้าง + ระเบียบสารบรรณ ในครั้งเดียว"""
    return check_document(doc)
