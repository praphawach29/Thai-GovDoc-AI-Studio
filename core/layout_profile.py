"""
layout_profile.py — โปรไฟล์การจัดหน้ากระดาษต่อแม่แบบเอกสาร

แยกค่าที่อยู่นอกเนื้อหา (ขอบกระดาษ ฟอนต์ ระยะตัวอักษร การย่อหน้า เส้นหัวฟอร์ม
และรูปแบบเลขหน้า) ออกจาก GovDocumentSchema เพื่อให้แต่ละหน่วยงาน/แม่แบบ
มีหน้าตาเอกสารต่างกันได้โดยไม่ต้องแก้โค้ด exporter
"""

from typing import Dict, Literal, Optional

from pydantic import BaseModel, Field

from core.models import DocType


class PageMargins(BaseModel):
    top_cm: float = 2.5
    bottom_cm: float = 2.0
    left_cm: float = 3.0
    right_cm: float = 2.0
    header_cm: float = 1.2


class LayoutProfile(BaseModel):
    name: str
    description: str = ""
    font_key: Literal["sarabun_new", "psk", "it9"] = "it9"
    margins: PageMargins = Field(default_factory=PageMargins)
    letter_spacing_pt: float = 0.4
    # None = ใช้ระยะย่อหน้าตามลำดับชั้นของ memo block, 0 = ไม่ย่อหน้า
    body_indent_cm: Optional[float] = None
    line_pitch_twips: int = 360
    header_style: Literal["dotted", "segmented", "solid"] = "dotted"
    page_number_style: Literal["thai", "arabic", "none"] = "thai"
    # หัว "บันทึกข้อความ": แบบ กทม. 32 pt / คู่มือการพิมพ์ทั่วไป 29 pt (ระยะบรรทัด Exactly 35 pt)
    memo_title_pt: float = 32
    memo_title_line_pt: float = 35


PROFILES: Dict[str, LayoutProfile] = {
    "standard_memo": LayoutProfile(
        name="standard_memo",
        description="บันทึกข้อความแบบกรุงเทพมหานคร — ค่าเริ่มต้น (ขอบ 3/2/1.5/2 ซม., หัว 32 pt)",
        font_key="it9",
        margins=PageMargins(top_cm=1.5, bottom_cm=2.0, left_cm=3.0, right_cm=2.0, header_cm=1.2),
        letter_spacing_pt=0.4,
        body_indent_cm=None,
        line_pitch_twips=360,
        header_style="dotted",
        page_number_style="thai",
    ),
    "manual_memo": LayoutProfile(
        name="manual_memo",
        description="บันทึกข้อความตามคู่มือการพิมพ์ทั่วไป (ยอดครุฑห่างขอบบน 2.5 ซม., หัว 29 pt)",
        font_key="it9",
        margins=PageMargins(top_cm=2.5, bottom_cm=2.0, left_cm=3.0, right_cm=2.0, header_cm=1.2),
        letter_spacing_pt=0.0,
        body_indent_cm=None,
        line_pitch_twips=360,
        header_style="dotted",
        page_number_style="thai",
        memo_title_pt=29,
    ),
    "standard_external": LayoutProfile(
        name="standard_external",
        description="หนังสือภายนอกมาตรฐาน (ขอบ 3/2/2.5/2 ซม., TH SarabunIT๙)",
        font_key="it9",
        margins=PageMargins(top_cm=2.5, bottom_cm=2.0, left_cm=3.0, right_cm=2.0, header_cm=1.2),
        letter_spacing_pt=0.4,
        body_indent_cm=2.5,
        line_pitch_twips=360,
        header_style="dotted",
        page_number_style="thai",
    ),
    "form_it9_2026": LayoutProfile(
        name="form_it9_2026",
        description="ฟอร์มบันทึกข้อความราชการจากไฟล์จริง (IT9, ขอบ 2.75/1.75/1.75/1.75, เส้นทึบ)",
        font_key="it9",
        margins=PageMargins(top_cm=1.75, bottom_cm=1.75, left_cm=2.75, right_cm=1.75, header_cm=1.25),
        letter_spacing_pt=-0.2,
        body_indent_cm=0.0,
        line_pitch_twips=435,
        header_style="segmented",
        page_number_style="arabic",
    ),
}


def get_layout_profile(name: Optional[str], doc_type: DocType = DocType.INTERNAL) -> LayoutProfile:
    """เลือกโปรไฟล์ตามชื่อ; หากไม่ระบุใช้มาตรฐานตามชนิดหนังสือ"""
    if name and name in PROFILES:
        return PROFILES[name]
    if doc_type == DocType.EXTERNAL:
        return PROFILES["standard_external"]
    return PROFILES["standard_memo"]
