"""ส่งออกเอกสารจริง: Word (.docx), โค้ด Typst และ PDF (Typst)"""

import logging
import os
import shutil
import tempfile
from io import BytesIO
from pathlib import Path
from typing import List

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field
from pypdf import PdfReader, PdfWriter
from fastapi.responses import FileResponse, PlainTextResponse
from starlette.background import BackgroundTask

from core.models import GovDocumentSchema
from core.typst_exporter import compile_typst_to_pdf, generate_typst_content
from core.word_exporter import export_govdoc_to_docx
from server.deps import without_server_paths
from server.settings import Settings, get_settings

router = APIRouter(tags=["export"])
logger = logging.getLogger("govdoc.api")


@router.post("/api/v1/export/docx")
def export_docx(doc: GovDocumentSchema):
    """Word (.docx) ตัดคำไทยด้วย ZWSP + กระจายแบบไทย + ฝังฟอนต์"""
    doc = without_server_paths(doc)
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


@router.post("/api/v1/export/typst", response_class=PlainTextResponse)
def export_typst(doc: GovDocumentSchema):
    """โค้ด Typst (.typ) ของหนังสือ"""
    return generate_typst_content(without_server_paths(doc))


def render_pdf(doc: GovDocumentSchema, settings: Settings) -> bytes:
    """คอมไพล์เอกสารหนึ่งฉบับเป็น PDF ด้วย Typst"""
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp = Path(tmp_dir)
        typ_path = tmp / "document.typ"
        pdf_path = tmp / "document.pdf"
        # Typst อ่านไฟล์ได้เฉพาะภายใต้ root (โฟลเดอร์ชั่วคราว) จึงจำลองโครงสร้าง templates/ + assets/
        shutil.copytree(settings.typst_templates_dir, tmp / "templates" / "typst")
        (tmp / "assets").mkdir()
        shutil.copy(settings.assets_dir / "garuda.svg", tmp / "assets" / "garuda.svg")
        typ_path.write_text(generate_typst_content(without_server_paths(doc)), encoding="utf-8")
        ok, message = compile_typst_to_pdf(str(typ_path), str(pdf_path))
        if not ok or not pdf_path.exists():
            # ข้อความจาก Typst มี path ภายในเซิร์ฟเวอร์ — เก็บใน log ไม่ส่งให้ผู้ใช้
            logger.error("typst compile failed: %s", message)
            raise HTTPException(status_code=500, detail="สร้าง PDF ไม่สำเร็จ")
        return pdf_path.read_bytes()


@router.post("/api/v1/export/pdf")
def export_pdf(doc: GovDocumentSchema, settings: Settings = Depends(get_settings)):
    """PDF คุณภาพเวกเตอร์ผ่าน Typst (ช่องทาง PDF เดียวที่ใช้บนคลาวด์ได้)"""
    return Response(content=render_pdf(doc, settings), media_type="application/pdf")


class PdfBundleRequest(BaseModel):
    # เรียงตามลำดับหน้าที่ต้องการ (ชุดเสนอ: ฉบับขั้นสูงสุดอยู่หน้าแรก)
    documents: List[GovDocumentSchema] = Field(min_length=1, max_length=6)


@router.post("/api/v1/export/pdf-bundle")
def export_pdf_bundle(req: PdfBundleRequest, settings: Settings = Depends(get_settings)):
    """รวมหลายฉบับเป็น PDF ไฟล์เดียว (เช่น ชุดเสนอ สำนัก -> กอง -> กลุ่มงาน)"""
    writer = PdfWriter()
    for doc in req.documents:
        for page in PdfReader(BytesIO(render_pdf(doc, settings))).pages:
            writer.add_page(page)
    out = BytesIO()
    writer.write(out)
    return Response(content=out.getvalue(), media_type="application/pdf")
