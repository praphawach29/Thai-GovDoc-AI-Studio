"""ส่งออกเอกสารจริง: Word (.docx), โค้ด Typst และ PDF (Typst)"""

import logging
import os
import shutil
import tempfile
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Response
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


@router.post("/api/v1/export/pdf")
def export_pdf(doc: GovDocumentSchema, settings: Settings = Depends(get_settings)):
    """PDF คุณภาพเวกเตอร์ผ่าน Typst (ช่องทาง PDF เดียวที่ใช้บนคลาวด์ได้)"""
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
        pdf_bytes = pdf_path.read_bytes()
    return Response(content=pdf_bytes, media_type="application/pdf")
