"""
api.py — REST API Backend สำหรับ Thai GovDoc AI Studio (FastAPI)
รองรับการเชื่อมต่อกับระบบ e-Office, สารบรรณอิเล็กทรอนิกส์, และ Web / Mobile Services
"""

import os
import shutil
import tempfile
from pathlib import Path
from typing import Optional, List

from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Query, Response
from fastapi.responses import FileResponse, PlainTextResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from core.models import GovDocumentSchema, SourceDocumentContext, DocType, UrgencyLevel, SecretLevel
from core.extractor import extract_source_document
from core.ai_drafter import draft_from_context_rule_based, draft_from_context_llm, DraftingIntent, copilot_refine_text
from core.word_exporter import export_govdoc_to_docx
from core.typst_exporter import export_govdoc_to_typst, generate_typst_content, compile_typst_to_pdf
from core.linter import lint_gov_document, LintResult
from core.registry import DocumentRegistry, OutgoingRecord, IncomingRecord


app = FastAPI(
    title="Thai GovDoc AI Studio API",
    description="ระบบบริการ API อัจฉริยะสำหรับสกัด ยกร่าง ตรวจสอบ และผลิตหนังสือราชการไทยตามระเบียบงานสารบรรณ พ.ศ. ๒๕๒๖",
    version="2.0.0"
)

# อนุญาต CORS สำหรับการเรียกใช้งานข้ามโดเมน
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

registry = DocumentRegistry()
uploads_dir = Path(__file__).resolve().parent.parent / "uploads"
uploads_dir.mkdir(exist_ok=True)


class DraftRequest(BaseModel):
    context: SourceDocumentContext
    doc_type: DocType = DocType.EXTERNAL
    intent: DraftingIntent = DraftingIntent.ACCEPT
    use_llm: bool = False
    api_key: Optional[str] = None


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
async def extract_document(file: UploadFile = File(...)):
    """
    อัปโหลดไฟล์ต้นเรื่อง (PDF, Scan, Image, DOCX, TXT)
    เพื่อสกัดข้อความและ Metadata (ที่, วันที่, เรื่อง, เรียน, ส่วนราชการ)
    """
    suffix = Path(file.filename).suffix.lower()
    if suffix not in [".pdf", ".docx", ".doc", ".txt", ".png", ".jpg", ".jpeg", ".tiff"]:
        raise HTTPException(status_code=400, detail=f"Unsupported file type: {suffix}")

    # บันทึกไฟล์ลง uploads
    target_path = uploads_dir / file.filename
    with open(target_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    try:
        ctx = extract_source_document(str(target_path))
        return ctx
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Extraction failed: {str(e)}")


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
        return draft_from_context_llm(req.context, doc_type=req.doc_type, intent=req.intent, api_key=req.api_key)
    return draft_from_context_rule_based(req.context, doc_type=req.doc_type, intent=req.intent)


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
# 5. Export: ผลิตเอกสารจริง (DOCX และ Typst)
# ---------------------------------------------------------------------
@app.post("/api/v1/export/docx")
def export_docx(doc: GovDocumentSchema):
    """
    ส่งออกหนังสือราชการเป็นไฟล์ Microsoft Word (.docx)
    พร้อมการตัดคำภาษาไทยด้วย Zero-Width Space และ OpenXML Thai Distributed
    """
    with tempfile.NamedTemporaryFile(delete=False, suffix=".docx") as tmp:
        tmp_path = tmp.name

    export_govdoc_to_docx(doc, tmp_path)
    filename = f"{doc.subject[:30].replace(' ', '_')}.docx"
    return FileResponse(
        tmp_path,
        filename=filename,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )


@app.post("/api/v1/export/typst", response_class=PlainTextResponse)
def export_typst(doc: GovDocumentSchema):
    """
    สร้างโค้ด Typst (.typ) สำหรับหนังสือราชการ
    """
    return generate_typst_content(doc)


# ---------------------------------------------------------------------
# 6. Registry: ระบบทะเบียนคุมและออกเลขที่หนังสือ
# ---------------------------------------------------------------------
@app.get("/api/v1/registry/next-number")
def get_next_number(prefix: str = Query("ดพร ๐๑๐๒/"), is_circular: bool = Query(False)):
    """
    ขอรับเลขที่หนังสือราชการลำดับถัดไป (Auto-increment)
    """
    next_no = registry.get_next_doc_number(prefix=prefix, is_circular=is_circular)
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
    row_id = registry.register_outgoing(record)
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
    row_id = registry.register_incoming(record)
    return {"status": "registered", "registry_id": row_id, "receive_number": record.receive_number}

