"""
word_exporter.py — ตัวสร้างไฟล์ Microsoft Word (.docx) ตามระเบียบงานสารบรรณ พ.ศ. ๒๕๒๖
ประยุกต์ใช้เทคนิคจาก thaigqsoft/thai-doc-skills (ZWSP Line-breaking, OpenXML thaiDistribute)
"""

import os
import re
from contextvars import ContextVar
from pathlib import Path
from typing import Optional

from docx import Document
from docx.shared import Cm, Pt, Inches, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_LINE_SPACING, WD_TAB_ALIGNMENT, WD_TAB_LEADER, WD_UNDERLINE
from docx.enum.table import WD_TABLE_ALIGNMENT, WD_ALIGN_VERTICAL
from docx.oxml import OxmlElement, parse_xml
from docx.oxml.ns import qn, nsdecls

from core.docx_fonts import FONT_FILES, embed_fonts
from core.layout_profile import LayoutProfile, get_layout_profile
from core.memo_layout import SALUTATION_GAP_PT
from core.models import ExportOptions, GovDocumentSchema, DocType, DocumentKind, SectionKind, UrgencyLevel, SecretLevel
from core.thai_segmenter import insert_zwsp, to_thai_numerals


FONT_NAME = "TH Sarabun New"
DEFAULT_FONT_SIZE = 16
_ACTIVE_FONT: ContextVar[str] = ContextVar("govdoc_font", default=FONT_NAME)
# ระยะห่างตัวอักษรของฉบับ (pt ต่อตัวอักษร) — Word บวกเพิ่มทุกตัวอักษร ต้องรวมตอนวัดความกว้าง
_LETTER_SPACING: ContextVar[float] = ContextVar("govdoc_letter_spacing", default=0.0)
_BODY_ALIGNMENT: ContextVar[str] = ContextVar("govdoc_body_alignment", default="thai_distribute")

# ระเบียบงานสารบรรณ ข้อ 16: ชั้นความเร็วใช้ตัวอักษรสีแดงขนาดไม่เล็กกว่า 32 พอยท์
URGENCY_FONT_PT = 32
SECRET_FONT_PT = 20
MARK_RED = RGBColor(200, 0, 0)


def _font_for_option(font_key: str) -> str:
    return {
        "psk": "TH SarabunPSK",
        "it9": "TH SarabunIT\u0e59",
    }.get(font_key, "TH Sarabun New")


def _apply_thai_distributed(paragraph):
    """จัดแนวเนื้อความตามตัวเลือกผู้ใช้ (ค่าเริ่มต้น Thai Distributed / กระจายแบบไทย)

    ตัวเลือก "left" ใช้เมื่อไม่อยากให้ Word ยืดตัวอักษรในบรรทัดที่คำยาว
    (thaigqsoft/thai-doc-skills แนะนำชิดซ้าย; สำนักงานส่วนใหญ่ใช้กระจายแบบไทย)
    """
    pPr = paragraph._p.get_or_add_pPr()
    # ตรวจสอบว่ามี jc เดิมอยู่หรือไม่ ถ้ามีให้ลบออกก่อน
    for child in list(pPr):
        if child.tag.endswith('jc'):
            pPr.remove(child)
    jc = OxmlElement('w:jc')
    jc.set(qn('w:val'), 'left' if _BODY_ALIGNMENT.get() == "left" else 'thaiDistribute')
    pPr.append(jc)


def _set_exact_line(paragraph, line_pt: float) -> None:
    """ระยะบรรทัดแบบค่าแน่นอน (Exactly) เช่น หัว "บันทึกข้อความ" 35 pt"""
    paragraph.paragraph_format.line_spacing_rule = WD_LINE_SPACING.EXACTLY
    paragraph.paragraph_format.line_spacing = Pt(line_pt)


def _mark_paragraph(container_paragraph, text: str, size_pt: int, align):
    container_paragraph.alignment = align
    run = container_paragraph.add_run(text)
    _set_run_thai_font(run, size_pt=size_pt, bold=True, color=MARK_RED)
    return container_paragraph


def _apply_classification_marks(doc: Document, data: GovDocumentSchema) -> None:
    """ใส่ชั้นความเร็วและชั้นความลับให้หนังสือทุกชนิด

    - ชั้นความลับ: กลางหน้ากระดาษทั้งด้านบนและด้านล่างของ**ทุกหน้า** (หัว/ท้ายกระดาษ)
    - ชั้นความเร็ว: สีแดง 32 pt มุมบนซ้ายของหน้าแรก (ก่อนตราครุฑ)
    """
    if data.urgency != UrgencyLevel.NORMAL:
        body = doc.element.body
        p = doc.add_paragraph()
        p.paragraph_format.space_before = Pt(0)
        p.paragraph_format.space_after = Pt(0)
        _mark_paragraph(p, data.urgency.to_thai(), URGENCY_FONT_PT, WD_ALIGN_PARAGRAPH.LEFT)
        body.remove(p._p)
        body.insert(0, p._p)

    if data.secret == SecretLevel.NORMAL:
        return
    label = data.secret.to_thai()
    for section in doc.sections:
        parts = [section.header, section.footer]
        if section.different_first_page_header_footer:
            parts += [section.first_page_header, section.first_page_footer]
        for part in parts:
            part.is_linked_to_previous = False
            first = part.paragraphs[0]
            if first.text.strip() or first.runs:
                # มีเลขหน้าอยู่แล้ว: ใส่ชั้นความลับเป็นบรรทัดแรกเหนือเลขหน้า
                mark = first.insert_paragraph_before()
            else:
                mark = first
            _mark_paragraph(mark, label, SECRET_FONT_PT, WD_ALIGN_PARAGRAPH.CENTER)


def _set_thai_language(doc: Document) -> None:
    """ระบุภาษาไทยใน style Normal ให้ Word ตัดคำ/ตรวจตัวสะกดภาษาไทยได้เอง"""
    rpr = doc.styles["Normal"].element.get_or_add_rPr()
    for child in list(rpr):
        if child.tag == qn("w:lang"):
            rpr.remove(child)
    lang = OxmlElement("w:lang")
    lang.set(qn("w:val"), "th-TH")
    lang.set(qn("w:bidi"), "th-TH")
    rpr.append(lang)


def _set_run_thai_font(run, font_name=None, size_pt=DEFAULT_FONT_SIZE, bold=False, color=None):
    """
    ตั้งค่าฟอนต์ในระดับ Run ให้ครอบคลุมทั้ง ASCII, High-ANSI และ Complex Script (cs)
    ป้องกันปัญหาฟอนต์เด้งเป็น Angsana หรือ Calibri
    """
    font_name = font_name or _ACTIVE_FONT.get()
    run.font.name = font_name
    run.font.size = Pt(size_pt)
    run.bold = bold
    if color:
        run.font.color.rgb = color

    rPr = run._r.get_or_add_rPr()
    # ลบ rFonts เดิมถ้ามี
    for child in list(rPr):
        if child.tag.endswith('rFonts'):
            rPr.remove(child)

    rFonts = OxmlElement('w:rFonts')
    rFonts.set(qn('w:ascii'), font_name)
    rFonts.set(qn('w:hAnsi'), font_name)
    rFonts.set(qn('w:cs'), font_name)
    rFonts.set(qn('w:eastAsia'), font_name)
    rPr.append(rFonts)


def _set_character_scale(run, percent: int):
    """บีบ/ขยายความกว้างตัวอักษรใน Word (w:w) เช่น 80 = 80%"""
    rPr = run._r.get_or_add_rPr()
    for child in list(rPr):
        if child.tag.endswith("}w"):
            rPr.remove(child)
    width = OxmlElement("w:w")
    width.set(qn("w:val"), str(max(40, min(200, int(percent)))))
    sz = rPr.find(qn("w:sz"))
    if sz is not None:
        sz.addprevious(width)
    else:
        rPr.append(width)


_FONT_DIR = Path(__file__).resolve().parent.parent / "assets" / "fonts"
_MEASURE_FONTS: dict = {}


def _text_width_cm(text: str, font_size_pt: float = 16.0, bold: bool = False) -> float:
    """ความกว้างจริงของข้อความด้วยฟอนต์ที่ใช้ส่งออก (Pillow + raqm จัดสระ/วรรณยุกต์ไทยถูกต้อง)
    ไม่มีไฟล์ฟอนต์ = ประมาณจากจำนวนตัวอักษรที่กินที่ (ไม่นับสระบน-ล่างและวรรณยุกต์)"""
    if not text:
        return 0.0
    files = next((f for f in FONT_FILES.values() if f["family"] == _ACTIVE_FONT.get()), FONT_FILES["sarabun_new"])
    name = files["bold" if bold else "regular"]
    font = _MEASURE_FONTS.get(name)
    if font is None and (_FONT_DIR / name).exists():
        try:
            from PIL import ImageFont
            font = _MEASURE_FONTS[name] = ImageFont.truetype(str(_FONT_DIR / name), 1000)
        except Exception:  # Pillow ไม่มี / อ่านฟอนต์ไม่ได้ → ใช้ค่าประมาณ
            font = None
    extra = len(text) * _LETTER_SPACING.get() / 72 * 2.54   # นับทุกตัวอักษร (รวม ZWSP) เผื่อไว้
    if font is not None:
        return font.getlength(text) / 1000 * font_size_pt / 72 * 2.54 + extra
    spacing = sum(1 for ch in text if not ("\u0e31" <= ch <= "\u0e3a" or "\u0e47" <= ch <= "\u0e4e"))
    return spacing * font_size_pt * 0.42 / 72 * 2.54 + extra


def _fit_run_to_width(run, text: str, available_cm: float, font_size_pt: float = 16.0):
    """บีบตัวอักษรแนวนอน (w:w) ให้ข้อความพอดีหนึ่งบรรทัด"""
    if not text or available_cm <= 0:
        return
    width_cm = _text_width_cm(text, font_size_pt)
    if width_cm > available_cm:
        # ปัดลง 1% เผื่อการปัดเศษของ Word
        _set_character_scale(run, int(available_cm / width_cm * 100) - 1)


def _setup_page_margins(doc: Document, profile: LayoutProfile):
    """กำหนดขนาดขอบกระดาษตาม LayoutProfile ของแม่แบบ"""
    for section in doc.sections:
        section.page_width = Cm(21.0)
        section.page_height = Cm(29.7)
        section.left_margin = Cm(profile.margins.left_cm)
        section.right_margin = Cm(profile.margins.right_cm)
        section.bottom_margin = Cm(profile.margins.bottom_cm)
        section.top_margin = Cm(profile.margins.top_cm)
        section.header_distance = Cm(profile.margins.header_cm)


def _set_doc_grid(doc: Document, line_pitch_twips: int):
    """กำหนด docGrid linePitch ให้ระยะบรรทัดฐานใกล้เคียงแม่แบบต้นฉบับ"""
    for section in doc.sections:
        sectPr = section._sectPr
        for child in list(sectPr):
            if child.tag.endswith("docGrid"):
                sectPr.remove(child)
        grid = OxmlElement("w:docGrid")
        grid.set(qn("w:linePitch"), str(line_pitch_twips))
        sectPr.append(grid)


def _apply_letter_spacing(doc: Document, points: float):
    """
    กำหนดระยะห่างตัวอักษร (character spacing) ที่ style Normal
    ค่า 0.4 pt = 8 twips (w:spacing w:val) ตามที่ Word ใช้
    """
    if not points:
        return
    style = doc.styles["Normal"]
    rPr = style.element.get_or_add_rPr()
    for child in list(rPr):
        if child.tag.endswith("spacing"):
            rPr.remove(child)
    spacing = OxmlElement("w:spacing")
    spacing.set(qn("w:val"), str(int(round(points * 20))))
    rPr.append(spacing)


def _add_divider(doc: Document):
    """เส้นคั่นแนวนอนใต้ส่วนหัว (สำหรับตัวเลือก divider='line')"""
    p = doc.add_paragraph()
    pPr = p._p.get_or_add_pPr()
    pBdr = OxmlElement("w:pBdr")
    bottom = OxmlElement("w:bottom")
    bottom.set(qn("w:val"), "single")
    bottom.set(qn("w:sz"), "6")
    bottom.set(qn("w:space"), "1")
    bottom.set(qn("w:color"), "000000")
    pBdr.append(bottom)
    pPr.append(pBdr)
    # ตั้งระยะหลังสร้าง pBdr เพื่อให้ลำดับ pPr ถูกต้อง (pBdr มาก่อน spacing)
    p.paragraph_format.space_before = Pt(0)
    p.paragraph_format.space_after = Pt(6)


# ความกว้างพื้นที่พิมพ์ของ A4 (21 - ซ้าย 3 - ขวา 2)
TEXT_WIDTH_CM = 16.0
MEMO_LABEL_SIZE = 20


def _add_header_tab(paragraph, position_cm: float = TEXT_WIDTH_CM, style: str = "dotted"):
    """
    เพิ่ม tab stop สำหรับหัวฟอร์ม
    - dotted: เส้นจุดไข่ปลา
    - segmented: เส้นทึบเฉพาะช่วง tab (แบบฟอร์มราชการ)
    - solid: ไม่มี leader แล้ววาดเส้นทึบด้วยขอบล่างย่อหน้า
    """
    if style == "dotted":
        leader = WD_TAB_LEADER.DOTS
    elif style == "segmented":
        leader = WD_TAB_LEADER.LINES
    else:
        leader = WD_TAB_LEADER.SPACES
    paragraph.paragraph_format.tab_stops.add_tab_stop(
        Cm(position_cm), WD_TAB_ALIGNMENT.RIGHT, leader
    )


def _apply_bottom_border(paragraph):
    """ขีดเส้นทึบใต้ย่อหน้า (ใช้ทำหัวฟอร์มแบบ solid)"""
    pPr = paragraph._p.get_or_add_pPr()
    existing = pPr.find(qn("w:pBdr"))
    if existing is not None:
        pPr.remove(existing)
    pBdr = OxmlElement("w:pBdr")
    bottom = OxmlElement("w:bottom")
    bottom.set(qn("w:val"), "single")
    bottom.set(qn("w:sz"), "6")
    bottom.set(qn("w:space"), "1")
    bottom.set(qn("w:color"), "000000")
    pBdr.append(bottom)
    # pBdr ต้องอยู่ก่อน tabs/spacing/ind/jc ตามลำดับ schema
    for tag in ("w:shd", "w:tabs", "w:spacing", "w:ind", "w:jc"):
        element = pPr.find(qn(tag))
        if element is not None:
            element.addprevious(pBdr)
            return
    pPr.append(pBdr)


def _add_page_number_header(doc: Document, style: str = "thai"):
    """
    ใส่เลขหน้ารูปแบบ "-๒-" หรือ "-2-" กึ่งกลางด้านบน เริ่มแสดงตั้งแต่หน้าที่ ๒
    style: thai | arabic | none
    """
    if style == "none":
        return
    thai_numerals = style == "thai"
    for section in doc.sections:
        section.different_first_page_header_footer = True
        if thai_numerals:
            sectPr = section._sectPr
            for child in list(sectPr):
                if child.tag.endswith("pgNumType"):
                    sectPr.remove(child)
            pg_num = OxmlElement("w:pgNumType")
            pg_num.set(qn("w:fmt"), "thaiNumbers")
            cols = sectPr.find(qn("w:cols"))
            if cols is not None:
                cols.addprevious(pg_num)
            else:
                sectPr.append(pg_num)
        p = section.header.paragraphs[0]
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        r1 = p.add_run("-")
        _set_run_thai_font(r1)

        instr = r" PAGE \* ThaiArabic " if thai_numerals else " PAGE "
        r_begin = p.add_run()
        fld_begin = OxmlElement("w:fldChar")
        fld_begin.set(qn("w:fldCharType"), "begin")
        r_begin._r.append(fld_begin)
        r_instr = p.add_run()
        instr_el = OxmlElement("w:instrText")
        instr_el.set(qn("xml:space"), "preserve")
        instr_el.text = instr
        r_instr._r.append(instr_el)
        r_sep = p.add_run()
        fld_sep = OxmlElement("w:fldChar")
        fld_sep.set(qn("w:fldCharType"), "separate")
        r_sep._r.append(fld_sep)
        r_val = p.add_run("๒" if thai_numerals else "2")
        _set_run_thai_font(r_val)
        r_end = p.add_run()
        fld_end = OxmlElement("w:fldChar")
        fld_end.set(qn("w:fldCharType"), "end")
        r_end._r.append(fld_end)

        r2 = p.add_run("-")
        _set_run_thai_font(r2)
        for r in (r_begin, r_instr, r_sep, r_end):
            _set_run_thai_font(r)



def _float_picture_left(run, offset_v_pt: float = 0.0) -> None:
    """เปลี่ยนรูปในบรรทัด (inline) เป็นรูปลอยชิดขอบซ้าย ไม่ตัดข้อความ (wrapNone) อยู่หลังข้อความ"""
    inline = run._r.find('.//' + qn('wp:inline'))
    if inline is None:
        return
    extent = inline.find(qn('wp:extent'))
    cx, cy = extent.get('cx'), extent.get('cy')
    doc_pr = inline.find(qn('wp:docPr'))
    graphic = inline.find(qn('a:graphic'))
    anchor = parse_xml(
        '<wp:anchor %s distT="0" distB="0" distL="0" distR="0" simplePos="0" relativeHeight="1" '
        'behindDoc="1" locked="0" layoutInCell="1" allowOverlap="1">'
        '<wp:simplePos x="0" y="0"/>'
        '<wp:positionH relativeFrom="margin"><wp:posOffset>0</wp:posOffset></wp:positionH>'
        '<wp:positionV relativeFrom="paragraph"><wp:posOffset>%d</wp:posOffset></wp:positionV>'
        '<wp:extent cx="%s" cy="%s"/><wp:effectExtent l="0" t="0" r="0" b="0"/><wp:wrapNone/>'
        '<wp:docPr id="%s" name="%s"/><wp:cNvGraphicFramePr/></wp:anchor>'
        % (nsdecls('wp', 'a', 'pic', 'r'), int(offset_v_pt * 12700), cx, cy,
           doc_pr.get('id'), doc_pr.get('name'))
    )
    anchor.append(graphic)
    inline.getparent().replace(inline, anchor)


def _drop_blank_thumbnail(doc: Document) -> None:
    """แม่แบบของ python-docx มีภาพตัวอย่าง (docProps/thumbnail.jpeg) เปล่า ๆ ติดมา
    Windows Explorer จึงแสดงหน้ากระดาษว่างแทนไอคอน Word — ลบออกให้แสดงไอคอนปกติ"""
    rels = doc.part.package.rels
    for r_id, rel in list(rels.items()):
        if rel.reltype.endswith("/metadata/thumbnail"):
            del rels[r_id]


def _split_first_line(text: str, room_cm: float, size_pt: float = 16.0):
    """แบ่งข้อความเป็น (ส่วนที่พอดีบรรทัดแรก, ส่วนที่เหลือ) ตัดที่ช่องว่าง/ZWSP ระหว่างคำ"""
    if _text_width_cm(text, size_pt) <= room_cm:
        return text, ""
    cut = 0
    for m in re.finditer(r"[\u200b ]", text):
        if _text_width_cm(text[:m.start()], size_pt) > room_cm:
            break
        cut = m.end()
    if cut == 0:
        return text, ""
    return text[:cut], text[cut:]


MEMO_SIGN_INDENT_CM = 6.0


def _add_memo_blocks(doc: Document, data: GovDocumentSchema, profile: LayoutProfile):
    """เขียนเนื้อความบันทึกข้อความจาก MemoBlock (หัวข้อขีดเส้นใต้/ตัวหนา + ย่อหน้าตามลำดับเลขข้อ)"""
    num = (lambda t: to_thai_numerals(t)) if data.use_thai_numerals else (lambda t: t)
    for b in data.get_memo_blocks():
        p = doc.add_paragraph()
        pf = p.paragraph_format
        pf.space_before = Pt(b.space_before_pt)
        pf.space_after = Pt(0)
        pf.line_spacing = 1.0
        indent = b.indent_cm if profile.body_indent_cm is None else profile.body_indent_cm
        if indent > 0:
            pf.first_line_indent = Cm(indent)
        if b.kind == "heading":
            pf.keep_with_next = True
        else:
            _apply_thai_distributed(p)

        if b.lead:
            r_lead = p.add_run(num(b.lead))
            _set_run_thai_font(r_lead, bold=(b.lead_style == "bold"))
            if b.lead_style == "underline":
                r_lead.underline = True
            if b.text:
                r_gap = p.add_run("  ")
                _set_run_thai_font(r_gap)
        if b.text:
            r = p.add_run(insert_zwsp(num(b.text)))
            _set_run_thai_font(r)


def _add_paragraph_with_zwsp(doc: Document, text: str, indent_cm: float = 0.0, 
                             space_after_pt: float = 6.0, justify: bool = True) -> any:
    """สร้างย่อหน้าพร้อมตัดคำและแทรก Zero-Width Space"""
    p = doc.add_paragraph()
    p.paragraph_format.space_after = Pt(space_after_pt)
    p.paragraph_format.line_spacing = 1.0
    if indent_cm > 0:
        p.paragraph_format.first_line_indent = Cm(indent_cm)

    if justify:
        _apply_thai_distributed(p)

    zwsp_text = insert_zwsp(text)
    run = p.add_run(zwsp_text)
    _set_run_thai_font(run, size_pt=DEFAULT_FONT_SIZE)
    return p


def export_govdoc_to_docx(
    data: GovDocumentSchema,
    output_path: str,
    garuda_path: Optional[str] = None,
    options: Optional[ExportOptions] = None,
) -> str:
    """
    สร้างและส่งออกหนังสือราชการเป็นไฟล์ .docx ตามมาตรฐานงานสารบรรณ

    options: ตัวเลือก LayoutProfile / ฟอนต์ / ระยะตัวอักษร / ครุฑ / การฝังฟอนต์
    """
    options = options or ExportOptions()
    profile = get_layout_profile(options.layout_profile, data.doc_type)
    font_key = options.export_font or data.font_family or profile.font_key
    letter_spacing = (
        profile.letter_spacing_pt
        if options.letter_spacing_pt is None
        else options.letter_spacing_pt
    )
    token = _ACTIVE_FONT.set(_font_for_option(font_key))
    align_token = _BODY_ALIGNMENT.set(options.body_alignment)
    spacing_token = _LETTER_SPACING.set(letter_spacing or 0.0)
    try:
        doc = Document()
        doc.core_properties.comments = (
            f"สถานะเอกสาร: {data.edit_status} | แก้ไขล่าสุด: {data.last_edited_at or '-'}"
        )
        doc.core_properties.keywords = f"govdoc,{data.edit_status}"
        _setup_page_margins(doc, profile)
        _apply_letter_spacing(doc, letter_spacing)

        # ตราครุฑ: ปิดได้ผ่าน letterhead="none"
        if options.letterhead == "none":
            garuda_path = None
        elif not garuda_path:
            default_garuda = Path(__file__).resolve().parent.parent / "assets" / "garuda_krut.png"
            if default_garuda.exists():
                garuda_path = str(default_garuda)

        # จัดการแปลงตัวเลขไทย ถ้าเปิดตัวเลือก use_thai_numerals
        fmt_date = to_thai_numerals(data.doc_date) if data.use_thai_numerals else data.doc_date
        fmt_number = to_thai_numerals(data.doc_number) if data.use_thai_numerals else data.doc_number
        fmt_reason = to_thai_numerals(data.paragraph_reason) if data.use_thai_numerals else data.paragraph_reason
        fmt_details = to_thai_numerals(data.paragraph_details) if (data.paragraph_details and data.use_thai_numerals) else data.paragraph_details
        fmt_purpose = to_thai_numerals(data.paragraph_purpose) if data.use_thai_numerals else data.paragraph_purpose

        if data.kind not in (DocumentKind.EXTERNAL_LETTER, DocumentKind.INTERNAL_MEMO):
            _build_special_doc(doc, data, fmt_date, fmt_number, garuda_path, options, profile)
        elif data.sections is not None:
            _build_sections_doc(doc, data, fmt_date, fmt_number, garuda_path, options, profile)
        elif data.doc_type == DocType.EXTERNAL:
            _build_external_doc(doc, data, fmt_date, fmt_number, fmt_reason, fmt_details, fmt_purpose, garuda_path, options, profile)
        else:
            _build_internal_doc(doc, data, fmt_date, fmt_number, fmt_reason, fmt_details, fmt_purpose, garuda_path, options, profile)

        _apply_classification_marks(doc, data)
        _set_thai_language(doc)

        # บันทึกไฟล์
        _set_doc_grid(doc, profile.line_pitch_twips)
        _drop_blank_thumbnail(doc)
        out_file = Path(output_path)
        out_file.parent.mkdir(parents=True, exist_ok=True)
        doc.save(str(out_file))

        # ฝังฟอนต์ TrueType (odttf) เพื่อให้เปิดบนเครื่องอื่นแล้วหน้าตาไม่เพี้ยน
        if options.embed_fonts:
            embed_fonts(out_file, font_key)

        return str(out_file)
    finally:
        _LETTER_SPACING.reset(spacing_token)
        _BODY_ALIGNMENT.reset(align_token)
        _ACTIVE_FONT.reset(token)


def _build_sections_doc(
    doc: Document,
    data: GovDocumentSchema,
    fmt_date: str,
    fmt_number: str,
    garuda_path: Optional[str],
    options: ExportOptions,
    profile: LayoutProfile,
):
    """เรนเดอร์เอกสารตามลำดับหัวข้ออิสระ (data.sections) ให้ใกล้แบบราชการ"""
    internal = data.kind == DocumentKind.INTERNAL_MEMO or data.doc_type == DocType.INTERNAL

    if internal:
        tbl_top = doc.add_table(rows=1, cols=2)
        tbl_top.alignment = WD_TABLE_ALIGNMENT.CENTER
        tbl_top.autofit = False
        for cell, width in zip(tbl_top.rows[0].cells, [Cm(2.5), Cm(13.5)]):
            cell.width = width
            tcPr = cell._tc.get_or_add_tcPr()
            borders = parse_xml(r'<w:tcBorders %s><w:top w:val="none"/><w:left w:val="none"/><w:bottom w:val="none"/><w:right w:val="none"/></w:tcBorders>' % nsdecls('w'))
            tcPr.append(borders)
        if garuda_path and os.path.exists(garuda_path):
            r_g = tbl_top.cell(0, 0).paragraphs[0].add_run()
            r_g.add_picture(garuda_path, height=Cm(1.5))
        p_title = tbl_top.cell(0, 1).paragraphs[0]
        p_title.alignment = WD_ALIGN_PARAGRAPH.CENTER
        r_title = p_title.add_run("บันทึกข้อความ")
        _set_run_thai_font(r_title, size_pt=profile.memo_title_pt, bold=True)
        _set_exact_line(p_title, profile.memo_title_line_pt)
    elif garuda_path and os.path.exists(garuda_path):
        p_g = doc.add_paragraph()
        p_g.alignment = WD_ALIGN_PARAGRAPH.CENTER
        p_g.paragraph_format.space_after = Pt(8)
        p_g.add_run().add_picture(garuda_path, height=Cm(3.0))

    body_indent = 2.5 if profile.body_indent_cm is None else profile.body_indent_cm

    def add_header_line(kind: SectionKind, label: str, value: str):
        p = doc.add_paragraph()
        p.paragraph_format.space_after = Pt(2)
        if kind == SectionKind.SUBJECT:
            p.paragraph_format.left_indent = Cm(1.25)
            p.paragraph_format.first_line_indent = Cm(-1.25)
        if kind == SectionKind.DEPT:
            r_label = p.add_run(f"{label}  ")
            _set_run_thai_font(r_label, size_pt=20, bold=True)
            r_value = p.add_run(insert_zwsp(value))
            _set_run_thai_font(r_value, size_pt=16)
            _fit_run_to_width(r_value, value, TEXT_WIDTH_CM - _text_width_cm(f"{label}  ", 20, bold=True) - 0.3)
            _add_header_tab(p, TEXT_WIDTH_CM, profile.header_style)
            p.add_run("\t")
        elif kind == SectionKind.SUBJECT:
            r_label = p.add_run(f"{label}  ")
            _set_run_thai_font(r_label, size_pt=20, bold=True)
            r_value = p.add_run(insert_zwsp(value))
            _set_run_thai_font(r_value, size_pt=16)
            _add_header_tab(p, TEXT_WIDTH_CM, profile.header_style)
            p.add_run("\t")
        else:  # SALUTATION
            r_label = p.add_run(f"{label}  ")
            _set_run_thai_font(r_label, size_pt=16)
            r_value = p.add_run(insert_zwsp(value))
            _set_run_thai_font(r_value, size_pt=16)
        if profile.header_style == "solid" and kind in (SectionKind.DEPT, SectionKind.SUBJECT):
            _apply_bottom_border(p)

    def add_multiline_field(label: str, content: str):
        p = doc.add_paragraph()
        p.paragraph_format.space_after = Pt(2)
        if label:
            r_label = p.add_run(f"{label}  ")
            _set_run_thai_font(r_label, size_pt=16, bold=True)
        lines = content.splitlines() or [content]
        for index, line in enumerate(lines):
            if index:
                p.add_run().add_break()
            r_value = p.add_run(insert_zwsp(line))
            _set_run_thai_font(r_value, size_pt=16)

    def add_body(label: str, content: str):
        p = doc.add_paragraph()
        p.paragraph_format.space_after = Pt(4)
        p.paragraph_format.first_line_indent = Cm(body_indent)
        _apply_thai_distributed(p)
        if label:
            r_label = p.add_run(f"{label}  ")
            _set_run_thai_font(r_label, size_pt=16)
            r_label.underline = True
        for index, line in enumerate(content.splitlines() or [content]):
            if index:
                p.add_run().add_break()
            r_text = p.add_run(insert_zwsp(line))
            _set_run_thai_font(r_text, size_pt=16)

    for section in data.sections or []:
        if not section.enabled:
            continue
        kind = section.kind
        label = (section.label or kind.default_label()).strip()
        content = (section.content or "").strip()

        if kind == SectionKind.NUMBER_DATE:
            number = to_thai_numerals(section.content) if data.use_thai_numerals else section.content
            date_value = to_thai_numerals(section.secondary) if data.use_thai_numerals else section.secondary
            p = doc.add_paragraph()
            p.paragraph_format.space_after = Pt(2)
            _add_header_tab(p, 7.5, profile.header_style)
            _add_header_tab(p, TEXT_WIDTH_CM, profile.header_style)
            r = p.add_run("ที่  ")
            _set_run_thai_font(r, size_pt=20, bold=True)
            r = p.add_run(insert_zwsp(number))
            _set_run_thai_font(r, size_pt=16)
            p.add_run("\t")
            r = p.add_run("วันที่  ")
            _set_run_thai_font(r, size_pt=20, bold=True)
            r = p.add_run(insert_zwsp(date_value))
            _set_run_thai_font(r, size_pt=16)
            p.add_run("\t")
            continue

        if kind == SectionKind.SIGNATURE:
            if content:
                p = doc.add_paragraph()
                p.paragraph_format.left_indent = Cm(8.0)
                p.paragraph_format.space_after = Pt(2)
                r = p.add_run(content)
                _set_run_thai_font(r, size_pt=16)
            if section.secondary.strip():
                p = doc.add_paragraph()
                p.paragraph_format.left_indent = Cm(8.0)
                p.paragraph_format.space_after = Pt(8)
                r = p.add_run(section.secondary)
                _set_run_thai_font(r, size_pt=16)
            continue

        if kind == SectionKind.CLOSING:
            if content:
                p = doc.add_paragraph()
                p.paragraph_format.space_after = Pt(8)
                if internal or content.startswith("จึงเรียนมาเพื่อ"):
                    p.paragraph_format.first_line_indent = Cm(body_indent)
                    _apply_thai_distributed(p)
                else:
                    p.paragraph_format.left_indent = Cm(8.0)
                r = p.add_run(content)
                _set_run_thai_font(r, size_pt=16)
            continue

        if kind in (SectionKind.DEPT, SectionKind.SUBJECT, SectionKind.SALUTATION):
            if not content:
                continue
            if kind == SectionKind.SALUTATION:
                content = re.sub(r'^(กราบเรียน|เรียน)\s*', '', content)
            elif kind == SectionKind.SUBJECT:
                content = re.sub(r'^เรื่อง\s*', '', content)
            add_header_line(kind, label, content)
            continue

        if kind in (SectionKind.REFERENCES, SectionKind.ATTACHMENTS):
            if content:
                add_multiline_field(label, content)
            continue

        if content:
            add_body(label, content)

    _add_page_number_header(doc, profile.page_number_style)


def _build_special_doc(
    doc: Document,
    data: GovDocumentSchema,
    fmt_date: str,
    fmt_number: str,
    garuda_path: Optional[str],
    options: ExportOptions,
    profile: LayoutProfile,
):
    """สร้างเอกสารชนิดพิเศษ 4 ชนิด (ประทับตรา/สั่งการ/ประชาสัมพันธ์/หลักฐาน)"""
    if garuda_path and os.path.exists(garuda_path):
        p_garuda = doc.add_paragraph()
        p_garuda.alignment = WD_ALIGN_PARAGRAPH.CENTER
        p_garuda.paragraph_format.space_after = Pt(8)
        r_garuda = p_garuda.add_run()
        r_garuda.add_picture(garuda_path, height=Cm(3.0))

    p_title = doc.add_paragraph()
    p_title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p_title.paragraph_format.space_after = Pt(10)
    r_title = p_title.add_run(data.special_title or data.subject)
    _set_run_thai_font(r_title, size_pt=29, bold=True)

    p_meta = doc.add_paragraph()
    p_meta.paragraph_format.space_after = Pt(2)
    p_meta.paragraph_format.tab_stops.add_tab_stop(Cm(TEXT_WIDTH_CM), WD_TAB_ALIGNMENT.RIGHT)
    r_num = p_meta.add_run(f"ที่  {fmt_number}")
    _set_run_thai_font(r_num, size_pt=DEFAULT_FONT_SIZE)
    p_meta.add_run("\t")
    r_date = p_meta.add_run(f"วันที่  {fmt_date}")
    _set_run_thai_font(r_date, size_pt=DEFAULT_FONT_SIZE)

    p_sub = doc.add_paragraph()
    p_sub.paragraph_format.space_after = Pt(6)
    r_sub_h = p_sub.add_run("เรื่อง  ")
    _set_run_thai_font(r_sub_h, size_pt=DEFAULT_FONT_SIZE, bold=True)
    r_sub_v = p_sub.add_run(insert_zwsp(data.subject))
    _set_run_thai_font(r_sub_v, size_pt=DEFAULT_FONT_SIZE)

    if options.divider == "line":
        _add_divider(doc)

    body_indent = 2.5 if profile.body_indent_cm is None else profile.body_indent_cm
    preamble = data.special_preamble or data.paragraph_reason
    _add_paragraph_with_zwsp(doc, preamble, indent_cm=body_indent, space_after_pt=6)

    num = to_thai_numerals if data.use_thai_numerals else (lambda value: value)
    for index, item in enumerate(data.special_items or [], 1):
        p_item = doc.add_paragraph()
        p_item.paragraph_format.space_after = Pt(2)
        p_item.paragraph_format.first_line_indent = Cm(body_indent)
        _apply_thai_distributed(p_item)
        prefix = f"{num(str(index))}.  "
        r_prefix = p_item.add_run(prefix)
        _set_run_thai_font(r_prefix, size_pt=DEFAULT_FONT_SIZE)
        r_item = p_item.add_run(insert_zwsp(item))
        _set_run_thai_font(r_item, size_pt=DEFAULT_FONT_SIZE)

    note = data.special_note or data.paragraph_purpose
    if note:
        _add_paragraph_with_zwsp(doc, note, indent_cm=body_indent, space_after_pt=12)

    if data.kind != DocumentKind.STAMP_LETTER:
        p_close = doc.add_paragraph()
        p_close.paragraph_format.left_indent = Cm(8.0)
        r_close = p_close.add_run(data.closing or "ขอแสดงความนับถือ")
        _set_run_thai_font(r_close, size_pt=DEFAULT_FONT_SIZE)

    p_sig = doc.add_paragraph()
    p_sig.paragraph_format.left_indent = Cm(8.0)
    p_sig.paragraph_format.space_after = Pt(2)
    r_sig = p_sig.add_run(data.signatory_name)
    _set_run_thai_font(r_sig, size_pt=DEFAULT_FONT_SIZE)

    p_pos = doc.add_paragraph()
    p_pos.paragraph_format.left_indent = Cm(8.0)
    p_pos.paragraph_format.space_after = Pt(12)
    r_pos = p_pos.add_run(data.signatory_position)
    _set_run_thai_font(r_pos, size_pt=DEFAULT_FONT_SIZE)

    if data.contact_dept or data.contact_tel:
        p_contact = doc.add_paragraph()
        p_contact.paragraph_format.space_after = Pt(2)
        r_contact = p_contact.add_run(data.contact_dept or "")
        _set_run_thai_font(r_contact, size_pt=14)
        if data.contact_tel:
            r_tel = p_contact.add_run(f"  โทร. {data.contact_tel}")
            _set_run_thai_font(r_tel, size_pt=14)

    _add_page_number_header(doc, profile.page_number_style)


def _build_external_doc(doc: Document, data: GovDocumentSchema, 
                        fmt_date: str, fmt_number: str, 
                        fmt_reason: str, fmt_details: Optional[str], fmt_purpose: str, 
                        garuda_path: Optional[str], options: ExportOptions, profile: LayoutProfile):
    """สร้างโครงสร้างหนังสือภายนอก (ครุฑ 3 ซม. กึ่งกลาง)"""
    
    # 1. ชั้นความลับ / ชั้นความเร็ว ใส่ทีหลังใน _apply_classification_marks (ทุกชนิดหนังสือ)

    # 2. ตราครุฑ 3.0 ซม. กึ่งกลางหน้า
    if garuda_path and os.path.exists(garuda_path):
        p_garuda = doc.add_paragraph()
        p_garuda.alignment = WD_ALIGN_PARAGRAPH.CENTER
        p_garuda.paragraph_format.space_after = Pt(12)
        r_garuda = p_garuda.add_run()
        r_garuda.add_picture(garuda_path, height=Cm(3.0))

    # 3. ส่วนหัว: ที่ (ซ้าย) และ ส่วนราชการ (ขวา)
    # ใช้ตาราง 1 แถว 2 คอลัมน์ ไร้เส้นขอบ เพื่อการจัดวางที่แม่นยำ
    tbl = doc.add_table(rows=1, cols=2)
    tbl.alignment = WD_TABLE_ALIGNMENT.CENTER
    tbl.autofit = False
    
    # กำหนดความกว้างคอลัมน์: ด้านซ้าย 8 ซม., ด้านขวา 8 ซม.
    col_widths = [Cm(7.5), Cm(8.5)]
    for cell, width in zip(tbl.rows[0].cells, col_widths):
        cell.width = width
        # ปลด padding และ border
        tcPr = cell._tc.get_or_add_tcPr()
        borders = parse_xml(r'<w:tcBorders %s><w:top w:val="none"/><w:left w:val="none"/><w:bottom w:val="none"/><w:right w:val="none"/></w:tcBorders>' % nsdecls('w'))
        tcPr.append(borders)

    cell_left = tbl.cell(0, 0)
    p_num = cell_left.paragraphs[0]
    p_num.paragraph_format.space_after = Pt(4)
    r_num = p_num.add_run(f"ที่  {fmt_number}")
    _set_run_thai_font(r_num, size_pt=DEFAULT_FONT_SIZE)

    cell_right = tbl.cell(0, 1)
    p_dept = cell_right.paragraphs[0]
    p_dept.paragraph_format.space_after = Pt(4)
    r_dept = p_dept.add_run(insert_zwsp(data.dept_name))
    _set_run_thai_font(r_dept, size_pt=DEFAULT_FONT_SIZE)
    _fit_run_to_width(r_dept, data.dept_name, 8.5)

    # 4. วันที่ (วางตำแหน่งตรงกลางเยื้องขวา ประมาณ 8 ซม. จากขอบซ้าย)
    p_date = doc.add_paragraph()
    p_date.paragraph_format.left_indent = Cm(8.0)
    p_date.paragraph_format.space_after = Pt(8)
    r_date = p_date.add_run(fmt_date)
    _set_run_thai_font(r_date, size_pt=DEFAULT_FONT_SIZE)

    # 5. เรื่อง, เรียน, อ้างถึง, สิ่งที่ส่งมาด้วย
    # เรื่อง
    clean_sub = re.sub(r'^เรื่อง\s*', '', data.subject.strip())
    p_sub = doc.add_paragraph()
    p_sub.paragraph_format.space_after = Pt(4)
    r_sub_h = p_sub.add_run("เรื่อง  ")
    _set_run_thai_font(r_sub_h, size_pt=DEFAULT_FONT_SIZE, bold=True)
    r_sub_v = p_sub.add_run(insert_zwsp(clean_sub))
    _set_run_thai_font(r_sub_v, size_pt=DEFAULT_FONT_SIZE)

    # เรียน
    sal_text = data.salutation.strip()
    if sal_text.startswith("กราบเรียน"):
        sal_header = "กราบเรียน  "
        clean_sal = re.sub(r'^กราบเรียน\s*', '', sal_text)
    else:
        sal_header = "เรียน  "
        clean_sal = re.sub(r'^เรียน\s*', '', sal_text)

    p_sal = doc.add_paragraph()
    p_sal.paragraph_format.space_after = Pt(4)
    r_sal_h = p_sal.add_run(sal_header)
    _set_run_thai_font(r_sal_h, size_pt=DEFAULT_FONT_SIZE, bold=True)
    r_sal_v = p_sal.add_run(insert_zwsp(clean_sal))
    _set_run_thai_font(r_sal_v, size_pt=DEFAULT_FONT_SIZE)

    # อ้างถึง (ถ้ามี)
    if data.references:
        for idx, ref in enumerate(data.references):
            p_ref = doc.add_paragraph()
            p_ref.paragraph_format.space_after = Pt(4)
            if idx == 0:
                r_ref_h = p_ref.add_run("อ้างถึง  ")
                _set_run_thai_font(r_ref_h, size_pt=DEFAULT_FONT_SIZE, bold=True)
            else:
                p_ref.paragraph_format.left_indent = Cm(1.5)
            r_ref_v = p_ref.add_run(insert_zwsp(ref))
            _set_run_thai_font(r_ref_v, size_pt=DEFAULT_FONT_SIZE)

    # สิ่งที่ส่งมาด้วย (ถ้ามี)
    if data.attachments:
        for idx, att in enumerate(data.attachments):
            p_att = doc.add_paragraph()
            p_att.paragraph_format.space_after = Pt(4)
            if idx == 0:
                r_att_h = p_att.add_run("สิ่งที่ส่งมาด้วย  ")
                _set_run_thai_font(r_att_h, size_pt=DEFAULT_FONT_SIZE, bold=True)
            else:
                p_att.paragraph_format.left_indent = Cm(2.5)
            r_att_v = p_att.add_run(insert_zwsp(att))
            _set_run_thai_font(r_att_v, size_pt=DEFAULT_FONT_SIZE)

    # 6. เนื้อหา 3 ย่อหน้า (ย่อหน้าตาม LayoutProfile + Thai Distributed)
    body_indent = 2.5 if profile.body_indent_cm is None else profile.body_indent_cm
    if options.divider == "line":
        _add_divider(doc)
    _add_paragraph_with_zwsp(doc, fmt_reason, indent_cm=body_indent, space_after_pt=6)

    if fmt_details:
        _add_paragraph_with_zwsp(doc, fmt_details, indent_cm=body_indent, space_after_pt=6)

    _add_paragraph_with_zwsp(doc, fmt_purpose, indent_cm=body_indent, space_after_pt=18)

    # 7. คำลงท้าย และผู้ลงนาม (วางเยื้องขวา 8 ซม.)
    p_close = doc.add_paragraph()
    p_close.paragraph_format.left_indent = Cm(8.0)
    r_close = p_close.add_run(data.closing)
    _set_run_thai_font(r_close, size_pt=DEFAULT_FONT_SIZE)

    if data.signature_image_path and os.path.exists(data.signature_image_path):
        p_close.paragraph_format.space_after = Pt(6)
        p_sign_img = doc.add_paragraph()
        p_sign_img.paragraph_format.left_indent = Cm(8.0)
        p_sign_img.paragraph_format.space_after = Pt(6)
        r_sign_img = p_sign_img.add_run()
        r_sign_img.add_picture(data.signature_image_path, height=Cm(1.2))
    else:
        p_close.paragraph_format.space_after = Pt(48)  # เว้นที่ว่างสำหรับลายเซ็น

    p_sig = doc.add_paragraph()
    p_sig.paragraph_format.left_indent = Cm(8.0)
    p_sig.paragraph_format.space_after = Pt(2)
    r_sig = p_sig.add_run(data.signatory_name)
    _set_run_thai_font(r_sig, size_pt=DEFAULT_FONT_SIZE)

    p_pos = doc.add_paragraph()
    p_pos.paragraph_format.left_indent = Cm(8.0)
    p_pos.paragraph_format.space_after = Pt(24)
    r_pos = p_pos.add_run(data.signatory_position)
    _set_run_thai_font(r_pos, size_pt=DEFAULT_FONT_SIZE)

    # 8. ส่วนราชการเจ้าของเรื่อง (ชิดขอบล่างซ้าย)
    p_contact = doc.add_paragraph()
    p_contact.paragraph_format.space_after = Pt(2)
    r_cdept = p_contact.add_run(insert_zwsp(data.contact_dept))
    _set_run_thai_font(r_cdept, size_pt=14)

    contact_details = []
    if data.contact_tel:
        contact_details.append(f"โทรศัพท์  {data.contact_tel}")
    if data.contact_fax:
        contact_details.append(f"โทรสาร  {data.contact_fax}")
    if data.contact_email:
        contact_details.append(f"ไปรษณีย์อิเล็กทรอนิกส์  {data.contact_email}")

    if contact_details:
        p_cinfo = doc.add_paragraph()
        p_cinfo.paragraph_format.space_after = Pt(2)
        r_cinfo = p_cinfo.add_run(" \n".join(contact_details))
        _set_run_thai_font(r_cinfo, size_pt=14)

    _add_page_number_header(doc, profile.page_number_style)


def _build_internal_doc(doc: Document, data: GovDocumentSchema, 
                        fmt_date: str, fmt_number: str, 
                        fmt_reason: str, fmt_details: Optional[str], fmt_purpose: str, 
                        garuda_path: Optional[str], options: ExportOptions, profile: LayoutProfile):
    """สร้างโครงสร้างหนังสือภายใน / บันทึกข้อความ (ครุฑ 1.5 ซม. ด้านซ้าย)"""

    # 1. หัวกระดาษ: "บันทึกข้อความ" ตัวหนา กึ่งกลางความกว้างข้อความ (ตรงกับ PDF) + ครุฑ 1.5 ซม.
    #    แบบลอยชิดซ้ายในบรรทัดเดียวกัน (ตามไฟล์ต้นแบบบันทึกข้อความของหน่วยงาน) จึงไม่ดันหัวเรื่องออกจากกึ่งกลาง
    p_title = doc.add_paragraph()
    p_title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    # เว้นบนให้สูงรวมเท่าครุฑ 1.5 ซม. (42.5 pt) เพื่อไม่ให้ครุฑล้นเข้าขอบบน
    p_title.paragraph_format.space_before = Pt(max(0.0, 1.5 / 2.54 * 72 - profile.memo_title_line_pt))
    p_title.paragraph_format.space_after = Pt(6)
    _set_exact_line(p_title, profile.memo_title_line_pt)
    if garuda_path and os.path.exists(garuda_path):
        r_g = p_title.add_run()
        r_g.add_picture(garuda_path, height=Cm(1.5))
        _float_picture_left(r_g)   # ฐานครุฑตรงกับเส้นล่างของบรรทัดหัวเรื่อง
    r_title = p_title.add_run("บันทึกข้อความ")
    _set_run_thai_font(r_title, size_pt=profile.memo_title_pt, bold=True)

    # 2. รายละเอียดหัวเรื่อง: หัวข้อ ส่วนราชการ / ที่ / วันที่ / เรื่อง ตัวหนา 20 pt
    #    แบบ dotted (ค่าเริ่มต้น): ข้อความวางบนเส้นประ — ขีดเส้นใต้แบบจุดตั้งแต่หลังหัวข้อจนถึงขอบขวา
    #    (ตามแบบฟอร์มบันทึกข้อความจริง และตรงกับหน้าแก้ไข) โดยขีดเส้นใต้ทั้งข้อความและแท็บท้ายบรรทัด
    on_line = profile.header_style == "dotted"

    def _header_tab(p, pos_cm: float, align=WD_TAB_ALIGNMENT.RIGHT):
        if on_line:
            p.paragraph_format.tab_stops.add_tab_stop(Cm(pos_cm), align, WD_TAB_LEADER.SPACES)
        else:
            _add_header_tab(p, pos_cm, profile.header_style)

    def _line_run(p, text: str):
        r = p.add_run(text)
        _set_run_thai_font(r, size_pt=DEFAULT_FONT_SIZE)
        if on_line:
            r.font.underline = WD_UNDERLINE.DOTTED
        return r

    def _memo_field(p, label: str, value: str):
        r_h = p.add_run(label)
        _set_run_thai_font(r_h, size_pt=MEMO_LABEL_SIZE, bold=True)
        if on_line:
            _set_run_thai_font(p.add_run(" "), size_pt=DEFAULT_FONT_SIZE)
            _line_run(p, "  ")
        else:
            _set_run_thai_font(p.add_run("  "), size_pt=DEFAULT_FONT_SIZE)
        return _line_run(p, insert_zwsp(value))

    dept_value = data.dept_name
    if data.contact_tel and data.contact_tel not in dept_value and "โทร" not in dept_value:
        dept_value = f"{dept_value}  โทร. {data.contact_tel}"
    p_dept = doc.add_paragraph()
    p_dept.paragraph_format.space_after = Pt(0)
    _header_tab(p_dept, TEXT_WIDTH_CM)
    dept_value = to_thai_numerals(dept_value) if data.use_thai_numerals else dept_value
    r_dept = _memo_field(p_dept, "ส่วนราชการ", dept_value)
    # บรรทัดเดียวเสมอ: ความกว้างข้อความ - หัวข้อ 20 pt - ช่องว่าง - เผื่อท้ายเส้น
    room = TEXT_WIDTH_CM - _text_width_cm("ส่วนราชการ   ", MEMO_LABEL_SIZE, bold=True) - 0.3
    _fit_run_to_width(r_dept, insert_zwsp(dept_value), room)   # รวม ZWSP: Word เว้นระยะตัวอักษรให้ด้วย
    _line_run(p_dept, "\t")
    if profile.header_style == "solid":
        _apply_bottom_border(p_dept)

    # ที่ ....... วันที่ ....... (บรรทัดเดียวกัน: "วันที่" เริ่มที่ 7.5 ซม.)
    p_meta = doc.add_paragraph()
    p_meta.paragraph_format.space_after = Pt(0)
    _header_tab(p_meta, 7.5, WD_TAB_ALIGNMENT.LEFT if on_line else WD_TAB_ALIGNMENT.RIGHT)
    _header_tab(p_meta, TEXT_WIDTH_CM)
    _memo_field(p_meta, "ที่", fmt_number)
    _line_run(p_meta, "\t")
    _memo_field(p_meta, "วันที่", fmt_date)
    _line_run(p_meta, "\t")
    if profile.header_style == "solid":
        _apply_bottom_border(p_meta)

    # เรื่อง (บรรทัดที่สองเยื้องตรงกับข้อความ — hanging indent)
    clean_sub = re.sub(r'^เรื่อง\s*', '', data.subject.strip())
    p_sub = doc.add_paragraph()
    p_sub.paragraph_format.space_after = Pt(6)
    p_sub.paragraph_format.left_indent = Cm(1.25)
    p_sub.paragraph_format.first_line_indent = Cm(-1.25)
    _header_tab(p_sub, TEXT_WIDTH_CM)
    sub_value = to_thai_numerals(clean_sub) if data.use_thai_numerals else clean_sub
    if on_line:
        # เส้นประเฉพาะบรรทัดแรก: เรื่องยาวเกิน ส่วนที่ขึ้นบรรทัดที่ ๒ ไม่ขีดเส้นใต้ (ตามแบบฟอร์มจริง)
        room = TEXT_WIDTH_CM - _text_width_cm("เรื่อง", MEMO_LABEL_SIZE, bold=True) \
            - _text_width_cm("   ", DEFAULT_FONT_SIZE) - 0.3
        first, rest = _split_first_line(insert_zwsp(sub_value), room)
        r_h = p_sub.add_run("เรื่อง")
        _set_run_thai_font(r_h, size_pt=MEMO_LABEL_SIZE, bold=True)
        _set_run_thai_font(p_sub.add_run(" "), size_pt=DEFAULT_FONT_SIZE)
        _line_run(p_sub, "  ")
        _line_run(p_sub, first.rstrip())
        # เส้นประยาวถึงขอบขวาเสมอ (แท็บขีดเส้นใต้เติมที่ว่างท้ายบรรทัด) แล้วขึ้นบรรทัดใหม่เอง
        # ส่วนที่เหลือของเรื่องจึงอยู่บรรทัดที่ ๒ (เยื้องตรงข้อความ) โดยไม่มีเส้นประ
        _line_run(p_sub, "\t")
        if rest:
            r_rest = p_sub.add_run()
            r_rest.add_break()
            r_rest.add_text(rest)
            _set_run_thai_font(r_rest, size_pt=DEFAULT_FONT_SIZE)
    else:
        _memo_field(p_sub, "เรื่อง", sub_value)
        p_sub.add_run("\t")
    if profile.header_style == "solid":
        _apply_bottom_border(p_sub)

    # เรียน (ตัวปกติ 16 pt ตามแบบบันทึกข้อความ)
    sal_text = data.salutation.strip()
    if sal_text.startswith("กราบเรียน"):
        sal_header = "กราบเรียน  "
        clean_sal = re.sub(r'^กราบเรียน\s*', '', sal_text)
    else:
        sal_header = "เรียน  "
        clean_sal = re.sub(r'^เรียน\s*', '', sal_text)

    p_sal = doc.add_paragraph()
    p_sal.paragraph_format.space_before = Pt(SALUTATION_GAP_PT)
    p_sal.paragraph_format.space_after = Pt(0)
    r_salh = p_sal.add_run(sal_header)
    _set_run_thai_font(r_salh, size_pt=DEFAULT_FONT_SIZE)
    r_salv = p_sal.add_run(insert_zwsp(clean_sal))
    _set_run_thai_font(r_salv, size_pt=DEFAULT_FONT_SIZE)

    # อ้างถึง (ถ้ามี)
    if data.references:
        for idx, ref in enumerate(data.references):
            p_ref = doc.add_paragraph()
            p_ref.paragraph_format.space_after = Pt(4)
            if idx == 0:
                r_ref_h = p_ref.add_run("อ้างถึง  ")
                _set_run_thai_font(r_ref_h, size_pt=DEFAULT_FONT_SIZE, bold=True)
            else:
                p_ref.paragraph_format.left_indent = Cm(2.5)
            r_ref_v = p_ref.add_run(insert_zwsp(ref))
            _set_run_thai_font(r_ref_v, size_pt=DEFAULT_FONT_SIZE)

    # สิ่งที่ส่งมาด้วย / เอกสารแนบ (ถ้ามี)
    if data.attachments:
        for idx, att in enumerate(data.attachments):
            p_att = doc.add_paragraph()
            p_att.paragraph_format.space_after = Pt(4)
            if idx == 0:
                r_att_h = p_att.add_run("สิ่งที่ส่งมาด้วย  ")
                _set_run_thai_font(r_att_h, size_pt=DEFAULT_FONT_SIZE, bold=True)
            else:
                p_att.paragraph_format.left_indent = Cm(2.5)
            r_att_v = p_att.add_run(insert_zwsp(att))
            _set_run_thai_font(r_att_v, size_pt=DEFAULT_FONT_SIZE)

    # 3. เนื้อความบันทึกข้อความ (ต้นเรื่อง / ข้อกฎหมาย / ข้อเท็จจริง / ข้อพิจารณาและเสนอแนะ / ภาคความประสงค์)
    if options.divider == "line":
        _add_divider(doc)
    _add_memo_blocks(doc, data, profile)

    # เลขหน้า -๒- ด้านบนกึ่งกลาง ตั้งแต่หน้าที่ ๒
    _add_page_number_header(doc, profile.page_number_style)

    # 4. ผู้ลงนาม (บันทึกข้อความไม่มีคำลงท้าย เช่น ขอแสดงความนับถือ)
    if data.signature_image_path and os.path.exists(data.signature_image_path):
        p_sign_img = doc.add_paragraph()
        p_sign_img.paragraph_format.left_indent = Cm(MEMO_SIGN_INDENT_CM)
        p_sign_img.paragraph_format.space_after = Pt(6)
        r_sign_img = p_sign_img.add_run()
        r_sign_img.add_picture(data.signature_image_path, height=Cm(1.2))
    else:
        p_space = doc.add_paragraph()
        p_space.paragraph_format.space_after = Pt(36)

    # ชื่อและตำแหน่งจัดกึ่งกลางในช่วงจาก 6 ซม. ถึงขอบขวา (ตรงกับ PDF / templates/typst/internal.typ)
    p_sig = doc.add_paragraph()
    p_sig.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p_sig.paragraph_format.left_indent = Cm(MEMO_SIGN_INDENT_CM)
    p_sig.paragraph_format.space_after = Pt(2)
    r_sig = p_sig.add_run(data.signatory_name)
    _set_run_thai_font(r_sig, size_pt=DEFAULT_FONT_SIZE)

    p_pos = doc.add_paragraph()
    p_pos.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p_pos.paragraph_format.left_indent = Cm(MEMO_SIGN_INDENT_CM)
    p_pos.paragraph_format.space_after = Pt(4)
    r_pos = p_pos.add_run(data.signatory_position)
    _set_run_thai_font(r_pos, size_pt=DEFAULT_FONT_SIZE)

    # ผู้ลงนามถัดไป (เช่น หัวหน้ากลุ่มงานลงนามต่อจากผู้เสนอเรื่อง) — เว้นที่ลงลายมือชื่อเท่ากัน
    for co in data.co_signers or []:
        p_gap = doc.add_paragraph()
        p_gap.paragraph_format.space_after = Pt(36)
        for text, after in ((co.name, 2), (co.position, 4)):
            p_co = doc.add_paragraph()
            p_co.alignment = WD_ALIGN_PARAGRAPH.CENTER
            p_co.paragraph_format.left_indent = Cm(MEMO_SIGN_INDENT_CM)
            p_co.paragraph_format.space_after = Pt(after)
            _set_run_thai_font(p_co.add_run(text), size_pt=DEFAULT_FONT_SIZE)
