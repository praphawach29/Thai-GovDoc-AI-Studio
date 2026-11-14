"""
api.py — REST API Backend สำหรับ Thai GovDoc AI Studio (FastAPI)
รองรับการเชื่อมต่อกับระบบ e-Office, สารบรรณอิเล็กทรอนิกส์, และ Web / Mobile Services
"""

import logging
import os
import shutil
import tempfile
from uuid import uuid4
from pathlib import Path
from typing import Optional, List

from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Query, Response
from fastapi.responses import FileResponse, PlainTextResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from starlette.background import BackgroundTask
from pydantic import BaseModel

from core.models import (
    GovDocumentSchema,
    SourceDocumentContext,
    DocType,
    UrgencyLevel,
    SecretLevel,
    DocumentKind,
    IntakeAssessment,
)
from core.extractor import extract_source_document
from core.ai_drafter import draft_from_context_rule_based, draft_from_context_llm, DraftingIntent, copilot_refine_text
from core.intake import assess_intake
from core.legal_sources import LegalLibrary, LegalReference
from core.word_exporter import export_govdoc_to_docx
from core.typst_exporter import export_govdoc_to_typst, generate_typst_content, compile_typst_to_pdf
from core.linter import lint_gov_document, LintResult
from core.registry import DocumentRegistry, DuplicateRegistryEntry, OutgoingRecord, IncomingRecord


app = FastAPI(
    title="Thai GovDoc AI Studio API",
    description="ระบบบริการ API อัจฉริยะสำหรับสกัด ยกร่าง ตรวจสอบ และผลิตหนังสือราชการไทยตามระเบียบงานสารบรรณ พ.ศ. ๒๕๒๖",
    version="2.0.0"
)

# อนุญาต CORS สำหรับการเรียกใช้งานข้ามโดเมน
# อนุญาตเฉพาะโดเมนที่กำหนด (คั่นด้วยจุลภาคใน GOVDOC_ALLOWED_ORIGINS)
# ค่าเริ่มต้นคือเครื่องตัวเอง; ห้ามใช้ "*" คู่กับ credentials
_allowed_origins = [
    o.strip()
    for o in os.environ.get(
        "GOVDOC_ALLOWED_ORIGINS", "http://localhost:8600,http://127.0.0.1:8600"
    ).split(",")
    if o.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT"],
    allow_headers=["Content-Type", "Authorization"],
)

registry = DocumentRegistry()
uploads_dir = Path(__file__).resolve().parent.parent / "uploads"
uploads_dir.mkdir(exist_ok=True)
logger = logging.getLogger("govdoc.api")

_ALLOWED_SOURCE_SUFFIXES = {".pdf", ".docx", ".txt", ".png", ".jpg", ".jpeg", ".tif", ".tiff"}
_MAX_UPLOAD_BYTES = 50 * 1024 * 1024


async def _save_upload(file: UploadFile) -> Path:
    """ตรวจชนิด/ขนาดไฟล์ แล้วบันทึกด้วยชื่อที่ระบบสร้างเอง

    ห้ามใช้ชื่อไฟล์จากผู้ใช้เป็น path (เช่น "../core/api.py" จะเขียนทับไฟล์นอก uploads/)
    """
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in _ALLOWED_SOURCE_SUFFIXES:
        raise HTTPException(status_code=400, detail=f"ไม่รองรับไฟล์ชนิด {suffix or '(ไม่มีนามสกุล)'}")
    data = await file.read(_MAX_UPLOAD_BYTES + 1)
    if len(data) > _MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="ไฟล์ใหญ่เกิน 50 MB")
    target = uploads_dir / f"{uuid4().hex}{suffix}"
    target.write_bytes(data)
    return target


def _without_server_paths(doc: GovDocumentSchema) -> GovDocumentSchema:
    """ไม่ให้ผู้เรียก API ชี้ไฟล์บนเซิร์ฟเวอร์ผ่าน signature_image_path

    มิฉะนั้นใครก็ฝังลายมือชื่อ/ไฟล์ภาพใดก็ได้บนเครื่องลงในเอกสาร
    การแนบลายมือชื่อจะทำผ่านระบบผู้ใช้/Storage ในขั้นถัดไป
    """
    if doc.signature_image_path:
        return doc.model_copy(update={"signature_image_path": None})
    return doc


class DraftRequest(BaseModel):
    context: SourceDocumentContext
    doc_type: DocType = DocType.EXTERNAL
    intent: DraftingIntent = DraftingIntent.ACCEPT
    use_llm: bool = False
    api_key: Optional[str] = None
    secret: SecretLevel = SecretLevel.NORMAL
    allow_cloud: bool = True


class IntakeRequest(BaseModel):
    context: SourceDocumentContext
    kind: DocumentKind = DocumentKind.EXTERNAL_LETTER
    include_law: bool = False
    include_references: bool = False
    include_attachments: bool = False


class RefineRequest(BaseModel):
    text: str
    command: str  # formal, concise, to_thai_nums, to_arabic_nums


class ReserveRequest(BaseModel):
    prefix: str = "ดพร ๐๑๐๒/"
    subject: str
    reserved_by: str = "เจ้าหน้าที่สารบรรณ"
    doc_type: str = "external"


# ---------------------------------------------------------------------
# 1. Health & Meta
# ---------------------------------------------------------------------
@app.get("/api/v1/health")
def health_check():
    return {
        "status": "healthy",
        "service": "Thai GovDoc AI Studio API",
        "version": "2.0.0",
        "standards": "ระเบียบสำนักนายกรัฐมนตรีว่าด้วยงานสารบรรณ พ.ศ. ๒๕๒๖"
    }


# ---------------------------------------------------------------------
# 2. Ingestion: สกัดข้อความและข้อมูลต้นเรื่อง
# ---------------------------------------------------------------------
@app.post("/api/v1/extract", response_model=SourceDocumentContext)
async def extract_document(
    file: UploadFile = File(...),
    secret: SecretLevel = Form(SecretLevel.NORMAL),
    allow_cloud: bool = Form(True),
):
    """
    อัปโหลดไฟล์ต้นเรื่อง (PDF, Scan, Image, DOCX, TXT)
    เพื่อสกัดข้อความและ Metadata (ที่, วันที่, เรื่อง, เรียน, ส่วนราชการ)
    """
    target_path = await _save_upload(file)
    try:
        ctx = extract_source_document(
            str(target_path),
            allow_cloud=allow_cloud,
            secret=secret,
        )
    except Exception:
        logger.exception("extract failed for %s", target_path.name)
        raise HTTPException(status_code=500, detail="สกัดข้อความจากไฟล์ไม่สำเร็จ")
    ctx.source_filename = Path(file.filename or "").name
    return ctx


# ---------------------------------------------------------------------
# 3. AI Drafting: ยกร่างหนังสือราชการ
# ---------------------------------------------------------------------
@app.post("/api/v1/draft", response_model=GovDocumentSchema)
def draft_document(req: DraftRequest):
    """
    สร้างร่างหนังสือราชการตามโครงสร้าง 3 ภาค (ภาคเหตุ, ภาคพิจารณา, ภาคประสงค์)
    โดยสามารถเลือกเจตนา (ตอบรับ / ปฏิเสธ / ส่งต่อ / เสนออนุมัติ)
    """
    if req.use_llm:
        return draft_from_context_llm(
            req.context,
            doc_type=req.doc_type,
            intent=req.intent,
            api_key=req.api_key,
            secret=req.secret,
            allow_cloud=req.allow_cloud,
        )
    return draft_from_context_rule_based(
        req.context,
        doc_type=req.doc_type,
        intent=req.intent,
        secret=req.secret,
    )


@app.post("/api/v1/copilot/refine")
def copilot_refine(req: RefineRequest):
    """
    ผู้ช่วย AI Copilot สำหรับขัดเกลาข้อความเฉพาะจุด
    """
    result = copilot_refine_text(req.text, req.command)
    return {"original": req.text, "refined": result, "command": req.command}


# ---------------------------------------------------------------------
# 4. Validation: ตรวจสอบความถูกต้องตามระเบียบงานสารบรรณ
# ---------------------------------------------------------------------
@app.post("/api/v1/validate", response_model=LintResult)
def validate_document(doc: GovDocumentSchema):
    """
    ตรวจสอบความถูกต้องของหนังสือราชการด้วย Sarabun Rules Linter
    (ตรวจวันที่, ตราครุฑ, โครงสร้าง 3 ภาค, คำขึ้นต้น-ลงท้าย, ความสอดคล้องตัวเลข)
    """
    return lint_gov_document(doc)


@app.post("/api/v1/placeholders")
def check_placeholders(doc: GovDocumentSchema):
    """
    ตรวจสอบ Smart Placeholders ที่ยังค้างอยู่ในเอกสาร
    """
    placeholders = doc.find_placeholders()
    return {
        "count": len(placeholders),
        "has_placeholders": len(placeholders) > 0,
        "placeholders": placeholders
    }


# ---------------------------------------------------------------------
# 4.1 Intake: ตรวจข้อมูลขาดและสร้างคำถามก่อนร่าง (deterministic)
# ---------------------------------------------------------------------
@app.post("/api/v1/intake/questions", response_model=IntakeAssessment)
def intake_questions(req: IntakeRequest):
    return assess_intake(
        req.context,
        req.kind,
        include_law=req.include_law,
        include_references=req.include_references,
        include_attachments=req.include_attachments,
    )


# ---------------------------------------------------------------------
# 4.2 คลังข้อกฎหมาย/ระเบียบ (ผู้ใช้ดูแลเอง + สถานะตรวจยืนยัน)
# ---------------------------------------------------------------------
@app.get("/api/v1/legal/references")
def list_legal_references(verified_only: bool = Query(False)):
    lib = LegalLibrary()
    return {"references": [ref.model_dump() for ref in lib.list(verified_only=verified_only)]}


@app.post("/api/v1/legal/references")
def add_legal_reference(ref: LegalReference):
    lib = LegalLibrary()
    saved = lib.add(ref)
    return {"status": "created", "reference": saved.model_dump()}


@app.put("/api/v1/legal/references/{ref_id}")
def update_legal_reference(ref_id: str, ref: LegalReference):
    lib = LegalLibrary()
    updated = lib.update(ref_id, **{k: v for k, v in ref.model_dump().items() if k != "id"})
    if updated is None:
        raise HTTPException(status_code=404, detail="Reference not found")
    return {"status": "updated", "reference": updated.model_dump()}


# ---------------------------------------------------------------------
# 5. Export: ผลิตเอกสารจริง (DOCX และ Typst)
# ---------------------------------------------------------------------
@app.post("/api/v1/export/docx")
def export_docx(doc: GovDocumentSchema):
    """
    ส่งออกหนังสือราชการเป็นไฟล์ Microsoft Word (.docx)
    พร้อมการตัดคำภาษาไทยด้วย Zero-Width Space และ OpenXML Thai Distributed
    """
    doc = _without_server_paths(doc)
    with tempfile.NamedTemporaryFile(delete=False, suffix=".docx") as tmp:
        tmp_path = tmp.name

    export_govdoc_to_docx(doc, tmp_path)
    filename = f"{doc.subject[:30].replace(' ', '_')}.docx"
    return FileResponse(
        tmp_path,
        filename=filename,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        # ลบไฟล์ชั่วคราวหลังส่งเสร็จ ไม่ให้สะสมบนเซิร์ฟเวอร์
        background=BackgroundTask(os.remove, tmp_path),
    )


@app.post("/api/v1/export/typst", response_class=PlainTextResponse)
def export_typst(doc: GovDocumentSchema):
    """
    สร้างโค้ด Typst (.typ) สำหรับหนังสือราชการ
    """
    return generate_typst_content(_without_server_paths(doc))


# ---------------------------------------------------------------------
# 6. Registry: ระบบทะเบียนคุมและออกเลขที่หนังสือ
# ---------------------------------------------------------------------
@app.get("/api/v1/registry/next-number")
def get_next_number(prefix: str = Query("ดพร ๐๑๐๒/"), is_circular: bool = Query(False)):
    """
    ขอรับเลขที่หนังสือราชการลำดับถัดไป (Auto-increment)
    """
    # GET ต้องไม่เปลี่ยนข้อมูล: แค่ดูเลขถัดไป ไม่กินเลข (ออกเลขจริงผ่าน POST /registry/reserve)
    next_no = registry.peek_next_doc_number(prefix=prefix, is_circular=is_circular)
    return {"prefix": prefix, "is_circular": is_circular, "doc_number": next_no}


@app.post("/api/v1/registry/reserve")
def reserve_number(req: ReserveRequest):
    """
    จองเลขที่หนังสือราชการล่วงหน้า
    """
    reserved_no = registry.reserve_doc_number(
        prefix=req.prefix,
        subject=req.subject,
        reserved_by=req.reserved_by,
        doc_type=req.doc_type
    )
    return {"status": "success", "reserved_number": reserved_no}


@app.get("/api/v1/registry/outgoing")
def list_outgoing(limit: int = 50):
    """
    เรียกดูรายการสมุดทะเบียนส่งหนังสือราชการ
    """
    return registry.list_outgoing(limit=limit)


@app.post("/api/v1/registry/outgoing")
def create_outgoing(record: OutgoingRecord):
    """
    บันทึกหนังสือราชการลงสมุดทะเบียนส่ง
    """
    try:
        row_id = registry.register_outgoing(record)
    except DuplicateRegistryEntry as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return {"status": "registered", "registry_id": row_id, "doc_number": record.doc_number}


@app.get("/api/v1/registry/incoming")
def list_incoming(limit: int = 50):
    """
    เรียกดูรายการสมุดทะเบียนรับหนังสือราชการ
    """
    return registry.list_incoming(limit=limit)


@app.post("/api/v1/registry/incoming")
def create_incoming(record: IncomingRecord):
    """
    บันทึกหนังสือราชการลงสมุดทะเบียนรับ
    """
    try:
        row_id = registry.register_incoming(record)
    except DuplicateRegistryEntry as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return {"status": "registered", "registry_id": row_id, "receive_number": record.receive_number}



# ---------------------------------------------------------------------
# 7. GovDoc Studio (web/studio): หน้าแรก + หน้าแก้ไขเอกสาร
# ---------------------------------------------------------------------
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from core.profile_manager import get_user_profile
from core.studio import (
    StudioCheck,
    StudioDraftResult,
    check_document,
    create_blank_document,
    normalize_for_editor,
    start_draft,
)

_ROOT_DIR = Path(__file__).resolve().parent.parent
class BlankRequest(BaseModel):
    doc_type: DocType = DocType.INTERNAL


@app.get("/api/v1/studio/profile")
def studio_profile():
    """โปรไฟล์หน่วยงาน/ผู้ลงนาม สำหรับแสดงบนหน้าแรก"""
    return get_user_profile()


@app.post("/api/v1/studio/draft", response_model=StudioDraftResult)
async def studio_draft(
    prompt: str = Form(""),
    doc_type: Optional[DocType] = Form(None),
    urgency: UrgencyLevel = Form(UrgencyLevel.NORMAL),
    secret: SecretLevel = Form(SecretLevel.NORMAL),
    file: Optional[UploadFile] = File(None),
):
    """เริ่มร่างจากคำสั่งที่พิมพ์และ/หรือไฟล์ต้นเรื่อง (สกัด → จำแนก → ร่าง → ตรวจ)"""
    saved_path: Optional[Path] = None
    if file is not None and file.filename:
        saved_path = await _save_upload(file)
    elif not prompt.strip():
        raise HTTPException(status_code=400, detail="พิมพ์คำสั่งหรือแนบไฟล์ต้นเรื่องก่อนเริ่มร่าง")

    result = start_draft(
        prompt=prompt,
        file_path=str(saved_path) if saved_path else None,
        doc_type_hint=doc_type,
        urgency=urgency,
        secret=secret,
    )
    if result.context is not None and file is not None and file.filename:
        result.context.source_filename = Path(file.filename).name
    return result


@app.post("/api/v1/studio/blank", response_model=GovDocumentSchema)
def studio_blank(req: BlankRequest):
    """เอกสารเปล่า (บันทึกข้อความ / หนังสือภายนอก) พร้อม placeholder"""
    return normalize_for_editor(create_blank_document(req.doc_type))


@app.get("/api/v1/studio/templates")
def studio_templates():
    """รายการแม่แบบมาตรฐาน (ไม่รวมเนื้อหา)"""
    from core.templates_library import list_preset_templates

    return [
        {"id": t.template_id, "title": t.title, "category": t.category, "doc_type": t.doc_type.value}
        for t in list_preset_templates()
    ]


@app.get("/api/v1/studio/templates/{template_id}", response_model=GovDocumentSchema)
def studio_template(template_id: str):
    from core.templates_library import get_preset_template

    t = get_preset_template(template_id)
    if t is None:
        raise HTTPException(status_code=404, detail="ไม่พบแม่แบบ")
    return normalize_for_editor(t.schema.model_copy(deep=True))


@app.post("/api/v1/studio/check", response_model=StudioCheck)
def studio_check(doc: GovDocumentSchema):
    """ตรวจ placeholder ที่ค้าง + ระเบียบสารบรรณ ในครั้งเดียว"""
    return check_document(doc)


@app.post("/api/v1/export/pdf")
def export_pdf(doc: GovDocumentSchema):
    """ส่งออก PDF คุณภาพเวกเตอร์ผ่าน Typst"""
    with tempfile.TemporaryDirectory() as tmp_dir:
        typ_path = Path(tmp_dir) / "document.typ"
        pdf_path = Path(tmp_dir) / "document.pdf"
        # Typst อ่านไฟล์ได้เฉพาะภายใต้ root (โฟลเดอร์ชั่วคราว) จึงจำลองโครงสร้าง templates/ + assets/
        tmp = Path(tmp_dir)
        shutil.copytree(_ROOT_DIR / "templates" / "typst", tmp / "templates" / "typst")
        (tmp / "assets").mkdir()
        shutil.copy(_ROOT_DIR / "assets" / "garuda.svg", tmp / "assets" / "garuda.svg")
        typ_path.write_text(generate_typst_content(_without_server_paths(doc)), encoding="utf-8")
        ok, message = compile_typst_to_pdf(str(typ_path), str(pdf_path))
        if not ok or not pdf_path.exists():
            # ข้อความจาก Typst มี path ภายในเซิร์ฟเวอร์ — เก็บใน log ไม่ส่งให้ผู้ใช้
            logger.error("typst compile failed: %s", message)
            raise HTTPException(status_code=500, detail="สร้าง PDF ไม่สำเร็จ")
        pdf_bytes = pdf_path.read_bytes()
    return Response(content=pdf_bytes, media_type="application/pdf")


app.mount("/studio", StaticFiles(directory=_ROOT_DIR / "web" / "studio", html=True), name="studio")
app.mount("/assets", StaticFiles(directory=_ROOT_DIR / "assets"), name="assets")


@app.get("/", include_in_schema=False)
def root_redirect():
    return RedirectResponse(url="/studio/")
