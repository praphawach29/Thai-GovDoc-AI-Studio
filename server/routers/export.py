"""ส่งออกเอกสารจริง: Word (.docx), โค้ด Typst และ PDF (Typst)"""

import logging
import os
import shutil
import tempfile
from io import BytesIO
from pathlib import Path
from typing import Iterable, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field
from pypdf import PdfReader, PdfWriter
from fastapi.responses import FileResponse, PlainTextResponse
from starlette.background import BackgroundTask

from core.layout_profile import get_layout_profile
from core.legal_pages import append_pages, plan_pages
from core.models import GovDocumentSchema, LegalCitation
from core.typst_exporter import compile_typst_to_pdf, generate_typst_content
from core.word_exporter import export_govdoc_to_docx
from server.deps import without_server_paths
from server.auth import CurrentUser, get_current_user, get_supabase
from server.settings import Settings, get_settings
from server.supabase import SupabaseError

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
        shutil.copy(settings.assets_dir / "garuda_krut.png", tmp / "assets" / "garuda_krut.png")
        typ_path.write_text(generate_typst_content(without_server_paths(doc)), encoding="utf-8")
        font_key = doc.font_family or get_layout_profile(None, doc.doc_type).font_key
        ok, message = compile_typst_to_pdf(str(typ_path), str(pdf_path), font_key=font_key)
        if not ok or not pdf_path.exists():
            # ข้อความจาก Typst มี path ภายในเซิร์ฟเวอร์ — เก็บใน log ไม่ส่งให้ผู้ใช้
            logger.error("typst compile failed: %s", message)
            raise HTTPException(status_code=500, detail="สร้าง PDF ไม่สำเร็จ")
        return pdf_path.read_bytes()


def attach_legal_pages(writer, citations: Iterable[LegalCitation], user: Optional[CurrentUser], settings: Settings) -> int:
    """ต่อหน้าของข้อกฎหมายที่เลือก (ไฟล์สแกนต้นฉบับในคลัง) ท้าย PDF — โหมด Supabase เท่านั้น
    ไฟล์ที่หาไม่เจอ/เปิดไม่ได้ ข้ามไป (ไม่ทำให้ส่งออกทั้งฉบับล้มเหลว) คืนจำนวนหน้าที่แนบ"""
    plan = plan_pages(citations)
    if not plan or not isinstance(user, CurrentUser):
        return 0
    client = get_supabase(user, settings)
    added = 0
    for source_id, pages in plan:
        try:
            rows = client.select("legal_sources", {"select": "storage_path", "id": f"eq.{source_id}"})
            if not rows:
                logger.warning("legal source %s not found for attach", source_id)
                continue
            added += append_pages(writer, client.download(settings.source_bucket, rows[0]["storage_path"]), pages)
        except Exception as exc:     # noqa: BLE001 — แนบไม่ได้ ไม่ควรทำให้ได้ PDF หนังสือไม่ได้ (เช่น ไฟล์ถูกลบ)
            logger.warning("attach legal pages from %s failed: %s", source_id, exc)
    return added


def _pdf_response(writer: PdfWriter, legal_pages: int) -> Response:
    out = BytesIO()
    writer.write(out)
    return Response(content=out.getvalue(), media_type="application/pdf",
                    headers={"X-GovDoc-Legal-Pages": str(legal_pages)})


@router.post("/api/v1/export/pdf")
def export_pdf(
    doc: GovDocumentSchema,
    settings: Settings = Depends(get_settings),
    user: Optional[CurrentUser] = Depends(get_current_user),
):
    """PDF คุณภาพเวกเตอร์ผ่าน Typst (ช่องทาง PDF เดียวที่ใช้บนคลาวด์ได้)
    + หน้าข้อกฎหมายที่เลือกจากไฟล์ต้นฉบับต่อท้าย (ปิดได้ด้วย attach_legal_pages)"""
    pdf = render_pdf(doc, settings)
    if not (doc.attach_legal_pages and doc.legal_refs):
        return Response(content=pdf, media_type="application/pdf")
    writer = PdfWriter()
    for page in PdfReader(BytesIO(pdf)).pages:
        writer.add_page(page)
    return _pdf_response(writer, attach_legal_pages(writer, doc.legal_refs, user, settings))


class PdfBundleRequest(BaseModel):
    # เรียงตามลำดับหน้าที่ต้องการ (ชุดเสนอ: ฉบับขั้นสูงสุดอยู่หน้าแรก)
    documents: List[GovDocumentSchema] = Field(min_length=1, max_length=6)


@router.post("/api/v1/export/pdf-bundle")
def export_pdf_bundle(
    req: PdfBundleRequest,
    settings: Settings = Depends(get_settings),
    user: Optional[CurrentUser] = Depends(get_current_user),
):
    """รวมหลายฉบับเป็น PDF ไฟล์เดียว (เช่น ชุดเสนอ สำนัก -> กอง -> กลุ่มงาน)
    หน้าข้อกฎหมายของทุกฉบับแนบครั้งเดียวท้ายชุด"""
    writer = PdfWriter()
    citations: List[LegalCitation] = []
    for doc in req.documents:
        for page in PdfReader(BytesIO(render_pdf(doc, settings))).pages:
            writer.add_page(page)
        if doc.attach_legal_pages:
            citations += doc.legal_refs or []
    return _pdf_response(writer, attach_legal_pages(writer, citations, user, settings))
