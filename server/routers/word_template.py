"""ใช้ไฟล์ Word ที่แนบเป็นแม่แบบ: AI เสนอการแก้ข้อความทีละย่อหน้า → ผู้ใช้ตรวจ → สร้างไฟล์ Word ที่คงรูปแบบเดิม

ไม่เก็บไฟล์บนเซิร์ฟเวอร์ (ประมวลผลในหน่วยความจำ) — หน้าเว็บส่งไฟล์เดิมมาอีกครั้งตอนสร้างไฟล์
"""

import json
from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import Response

from core.docx_template import MAX_SEGMENTS, apply_edits, segments
from core.llm_drafter import structured_call
from core.models import SecretLevel
from core.security import cloud_ai_allowed
from core.template_ai import TemplateEdits, propose_edits
from server.settings import Settings, get_settings, llm_config

router = APIRouter(prefix="/api/v1/studio/word-template", tags=["word-template"])
DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


async def _read_docx(file: UploadFile, settings: Settings) -> bytes:
    if Path(file.filename or "").suffix.lower() != ".docx":
        raise HTTPException(status_code=400, detail="แม่แบบต้องเป็นไฟล์ Word (.docx) — ไฟล์ .doc รุ่นเก่าให้บันทึกเป็น .docx ก่อน")
    data = await file.read(settings.max_upload_bytes + 1)
    if len(data) > settings.max_upload_bytes:
        raise HTTPException(status_code=413, detail=f"ไฟล์ใหญ่เกิน {settings.max_upload_bytes // (1024 * 1024)} MB")
    return data


def _segments(data: bytes):
    try:
        segs = segments(data)
    except Exception:
        raise HTTPException(status_code=400, detail="อ่านไฟล์ Word นี้ไม่ได้ (ไฟล์เสียหรือมีรหัสผ่าน)")
    if not segs:
        raise HTTPException(status_code=400, detail="ไฟล์นี้ไม่มีข้อความให้แก้")
    if len(segs) > MAX_SEGMENTS:
        raise HTTPException(status_code=400, detail=f"ไฟล์ยาวเกินไป ({len(segs)} ย่อหน้า) — แยกเป็นไฟล์ย่อยก่อน")
    return segs


@router.post("/propose")
async def propose(
    file: UploadFile = File(...),
    prompt: str = Form(""),
    source_text: str = Form(""),
    secret: SecretLevel = Form(SecretLevel.NORMAL),
    settings: Settings = Depends(get_settings),
):
    """AI เสนอข้อความใหม่ของย่อหน้าที่ต้องเปลี่ยน (ยังไม่สร้างไฟล์)"""
    if not prompt.strip() and not source_text.strip():
        raise HTTPException(status_code=400, detail="พิมพ์สิ่งที่ต้องการให้แก้ เช่น \"ปรับเป็นปีงบประมาณ 2572\"")
    if not cloud_ai_allowed(secret):
        raise HTTPException(status_code=400, detail="เอกสารชั้นความลับ ไม่ส่งให้ AI ภายนอก — แก้ในไฟล์ Word โดยตรง")
    data = await _read_docx(file, settings)
    segs = _segments(data)
    config = llm_config(settings)
    if not config.any_provider:
        raise HTTPException(status_code=503, detail="ยังไม่ได้ตั้งค่า AI")

    def call(system, text):
        return structured_call(system, text, TemplateEdits, config, timeout_s=90.0, max_tokens=16000)

    try:
        result = propose_edits(segs, prompt, source_text, call)
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=f"AI ไม่ตอบ: {exc}")
    return {**result.model_dump(), "segment_count": len(segs)}


@router.post("/build")
async def build(
    file: UploadFile = File(...),
    edits: str = Form(..., description='JSON {"p12": "ข้อความใหม่", ...}'),
    settings: Settings = Depends(get_settings),
):
    """สร้างไฟล์ Word จากแม่แบบ + ข้อความที่ผู้ใช้ยืนยันแล้ว"""
    data = await _read_docx(file, settings)
    try:
        mapping = json.loads(edits)
        assert isinstance(mapping, dict) and all(isinstance(k, str) and isinstance(v, str) for k, v in mapping.items())
    except (ValueError, AssertionError):
        raise HTTPException(status_code=400, detail="รายการแก้ไขไม่ถูกต้อง")
    _segments(data)
    out, changed = apply_edits(data, mapping)
    name = Path(file.filename or "เอกสาร.docx").stem + " (แก้ไข).docx"
    return Response(out, media_type=DOCX_MIME, headers={
        "Content-Disposition": f"attachment; filename*=UTF-8''{quote(name)}",
        "X-GovDoc-Changed": str(changed),
    })
