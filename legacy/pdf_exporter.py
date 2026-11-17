"""
pdf_exporter.py — ตัวสร้างไฟล์ PDF เวกเตอร์คุณภาพสูงตามมาตรฐานระเบียบงานสารบรรณ
ใช้ Headless Browser Engine (Microsoft Edge / Chrome) ที่มีอยู่ในระบบ Windows
เพื่อสร้างไฟล์ PDF คมชัดระดับ Vector พร้อมฝังฟอนต์ Sarabun และตราครุฑจริง
"""

import html
import os
import shutil
import base64
import tempfile
import subprocess
from pathlib import Path
from typing import Optional

from core.models import GovDocumentSchema, DocType
from core.thai_segmenter import to_thai_numerals
from core.memo_layout import render_memo_blocks_html


def _find_headless_shell() -> list:
    """หา chrome-headless-shell (Playwright) ซึ่งเหมาะกับเซิร์ฟเวอร์/คลาวด์

    Chrome/Chromium ตัวเต็มอาจค้างตอนสร้าง profile ใหม่ (--user-data-dir) บนเครื่อง
    ที่ไม่มี dbus หรือออกอินเทอร์เน็ตไม่ได้ ส่วน headless shell ไม่มีปัญหานี้
    """
    found = [shutil.which("chrome-headless-shell")]
    roots = [os.environ.get("PLAYWRIGHT_BROWSERS_PATH"), str(Path.home() / ".cache" / "ms-playwright")]
    for root in roots:
        if root and os.path.isdir(root):
            found.extend(sorted(
                (str(p) for p in Path(root).glob("chromium_headless_shell-*/chrome-headless-shell-*/chrome-headless-shell")),
                reverse=True,
            ))
    return found


def _find_browser_executable() -> Optional[str]:
    """ค้นหา Browser Executable สำหรับใช้ในการเรนเดอร์ PDF แบบ Headless

    ลำดับ: ตัวแปร GOVDOC_PDF_BROWSER → Edge/Chrome บน Windows → chrome-headless-shell
    → Edge/Chrome/Chromium บน Linux/Mac
    """
    candidates = [
        os.environ.get("GOVDOC_PDF_BROWSER"),
        # Microsoft Edge บน Windows
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        # Google Chrome บน Windows
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        *_find_headless_shell(),
        # Linux / Mac fallbacks
        shutil.which("msedge"),
        shutil.which("google-chrome"),
        shutil.which("chromium"),
        shutil.which("chrome"),
    ]
    for c in candidates:
        if c and os.path.exists(c):
            return c
    return None


_FONT_FACES = [
    ("THSarabunNew.ttf", "normal", "normal"),
    ("THSarabunNew-Bold.ttf", "bold", "normal"),
    ("THSarabunNew-Italic.ttf", "normal", "italic"),
    ("THSarabunNew-BoldItalic.ttf", "bold", "italic"),
]


def _local_font_faces_css() -> str:
    """ประกาศ @font-face ของ TH Sarabun New จาก assets/fonts (ไม่พึ่งอินเทอร์เน็ต)

    เดิมใช้ Google Fonts ซึ่งทำให้ headless browser ค้างเมื่อเครื่องไม่มีอินเทอร์เน็ต
    (on-prem / cloud sandbox) และเป็นฟอนต์ Sarabun ไม่ใช่ TH Sarabun New ตามระเบียบ
    """
    fonts_dir = Path(__file__).resolve().parent.parent / "assets" / "fonts"
    rules = []
    for filename, weight, style in _FONT_FACES:
        font_path = fonts_dir / filename
        if font_path.exists():
            rules.append(
                "@font-face { font-family: 'TH Sarabun New'; "
                f"src: url('{font_path.as_uri()}') format('truetype'); "
                f"font-weight: {weight}; font-style: {style}; }}"
            )
    return "\n".join(rules)


def _html_escaped_copy(data: GovDocumentSchema) -> GovDocumentSchema:
    """สำเนาเอกสารที่ escape ข้อความทุกช่อง (str และ list ของ str) สำหรับใส่ใน HTML"""
    updates = {}
    for name in type(data).model_fields:
        if name == "signature_image_path":
            continue
        value = getattr(data, name)
        if isinstance(value, str):
            updates[name] = html.escape(value, quote=True)
        elif isinstance(value, list) and all(isinstance(v, str) for v in value):
            updates[name] = [html.escape(v, quote=True) for v in value]
    return data.model_copy(update=updates)


def generate_govdoc_html(data: GovDocumentSchema, garuda_path: Optional[str] = None) -> str:
    """สร้างโค้ด HTML มาตรฐาน A4 สำหรับแปลงเป็น PDF"""
    root_dir = Path(__file__).resolve().parent.parent
    if not garuda_path:
        # ลำดับความสำคัญ: 1. Vector SVG 2. PNG
        svg_candidate = root_dir / "assets" / "garuda.svg"
        png_candidate = root_dir / "assets" / "garuda.png"
        if svg_candidate.exists():
            garuda_path = str(svg_candidate)
        elif png_candidate.exists():
            garuda_path = str(png_candidate)

    garuda_b64 = ""
    garuda_mime = "image/png"
    if garuda_path and os.path.exists(garuda_path):
        with open(garuda_path, "rb") as f:
            garuda_b64 = base64.b64encode(f.read()).decode("utf-8")
        if garuda_path.endswith(".svg"):
            garuda_mime = "image/svg+xml"

    # จัดการลายมือชื่อ ถ้ามี
    sig_html = '<div style="height: 40px;"></div>'
    if getattr(data, "signature_image_path", None) and os.path.exists(data.signature_image_path):
        with open(data.signature_image_path, "rb") as f:
            sig_b64 = base64.b64encode(f.read()).decode("utf-8")
        sig_html = f'<div style="text-align: center; margin: 4px 0;"><img src="data:image/png;base64,{sig_b64}" style="height: 38px; width: auto;" alt="ลายมือชื่อ" /></div>'

    # ข้อความทุกช่องมาจากผู้ใช้/AI ต้อง escape ก่อนใส่ใน HTML
    # มิฉะนั้นข้อความอย่าง <iframe src="file:///etc/passwd"> จะถูก Chrome เรนเดอร์ลง PDF
    raw = data
    data = _html_escaped_copy(data)

    fmt_date = to_thai_numerals(data.doc_date) if data.use_thai_numerals else data.doc_date
    fmt_number = to_thai_numerals(data.doc_number) if data.use_thai_numerals else data.doc_number
    fmt_reason = to_thai_numerals(data.paragraph_reason) if data.use_thai_numerals else data.paragraph_reason
    fmt_details = to_thai_numerals(data.paragraph_details) if (data.paragraph_details and data.use_thai_numerals) else (data.paragraph_details or "")
    fmt_purpose = to_thai_numerals(data.paragraph_purpose) if data.use_thai_numerals else data.paragraph_purpose

    # ส่วนอ้างถึง
    refs_html = ""
    if data.references:
        items = []
        for idx, r in enumerate(data.references):
            val = to_thai_numerals(r) if data.use_thai_numerals else r
            if idx == 0:
                items.append(f"<p><strong>อ้างถึง</strong>&nbsp;&nbsp;{val}</p>")
            else:
                items.append(f'<p style="margin-left: 2.2cm;">{val}</p>')
        refs_html = "".join(items)

    # สิ่งที่ส่งมาด้วย
    atts_html = ""
    if data.attachments:
        items = []
        for idx, a in enumerate(data.attachments):
            val = to_thai_numerals(a) if data.use_thai_numerals else a
            if idx == 0:
                items.append(f"<p><strong>สิ่งที่ส่งมาด้วย</strong>&nbsp;&nbsp;{val}</p>")
            else:
                items.append(f'<p style="margin-left: 2.2cm;">{val}</p>')
        atts_html = "".join(items)

    if data.doc_type == DocType.EXTERNAL:
        # หนังสือภายนอก
        body_content = f"""
        <div class="garuda-center">
            <img src="data:{garuda_mime};base64,{garuda_b64}" style="height: 3.0cm; width: auto;" alt="ตราครุฑ 3 ซม." />
        </div>
        <div class="row-between">
            <div style="width: 48%;"><strong>ที่</strong>&nbsp;&nbsp;{fmt_number}</div>
            <div style="width: 48%; text-align: left;">{data.dept_name}</div>
        </div>
        <div class="date-center">
            {fmt_date}
        </div>
        <div style="margin-bottom: 14px;">
            <p><strong>เรื่อง</strong>&nbsp;&nbsp;{data.subject}</p>
            <p><strong>{data.salutation}</strong></p>
            {refs_html}
            {atts_html}
        </div>
        <p class="indent">{fmt_reason}</p>
        {f'<p class="indent">{fmt_details}</p>' if fmt_details else ''}
        <p class="indent">{fmt_purpose}</p>
        <div class="closing-block">
            <p>{data.closing}</p>
            {sig_html}
            <p>{data.signatory_name}</p>
            <p>{data.signatory_position}</p>
        </div>
        <div class="footer-contact">
            <p style="margin:0;">{data.contact_dept or ''}</p>
            <p style="margin:0;">โทรศัพท์&nbsp;&nbsp;{data.contact_tel or ''}</p>
            {f'<p style="margin:0;">โทรสาร&nbsp;&nbsp;{data.contact_fax}</p>' if data.contact_fax else ''}
            {f'<p style="margin:0;">ไปรษณีย์อิเล็กทรอนิกส์&nbsp;&nbsp;{data.contact_email}</p>' if data.contact_email else ''}
        </div>
        """
    else:
        # บันทึกข้อความ (หนังสือภายใน) — โครงสร้างตาม core.memo_layout
        num = (lambda t: to_thai_numerals(t)) if data.use_thai_numerals else (lambda t: t)
        # memo_layout escape ข้อความเองแล้ว จึงส่งข้อมูลดิบ (กันการ escape ซ้ำ)
        memo_sections_rendered = render_memo_blocks_html(raw.get_memo_blocks(), transform=num)

        dept_value = data.dept_name
        if data.contact_tel and data.contact_tel not in dept_value:
            dept_value = f"{dept_value}  โทร. {data.contact_tel}"
        clean_sub = data.subject.strip()
        if clean_sub.startswith("เรื่อง"):
            clean_sub = clean_sub[len("เรื่อง"):].strip()
        sal = data.salutation.strip()
        sal_label = "กราบเรียน" if sal.startswith("กราบเรียน") else "เรียน"
        sal_body = sal[len(sal_label):].strip() if sal.startswith(sal_label) else sal
        sig_space_html = sig_html if (data.signature_image_path and os.path.exists(data.signature_image_path)) else '<div style="height: 55px;"></div>'

        body_content = f"""
        <div class="memo-head">
            <img src="data:{garuda_mime};base64,{garuda_b64}" style="height: 1.5cm; width: auto;" alt="ตราครุฑ 1.5 ซม." />
            <div class="memo-title">บันทึกข้อความ</div>
        </div>
        <div class="memo-field"><span class="memo-label">ส่วนราชการ</span><span class="memo-value">{num(dept_value)}</span></div>
        <div class="memo-field">
            <span class="memo-label">ที่</span><span class="memo-value" style="flex: 0 0 6.2cm;">{fmt_number}</span>
            <span class="memo-label" style="margin-left: 0.3cm;">วันที่</span><span class="memo-value">{fmt_date}</span>
        </div>
        <div class="memo-field"><span class="memo-label">เรื่อง</span><span class="memo-value">{num(clean_sub)}</span></div>
        <p style="margin-top: 6pt;">{sal_label}&nbsp;&nbsp;{sal_body}</p>
        {refs_html}
        {atts_html}
        <div class="memo-body">
        {memo_sections_rendered}
        </div>
        <div class="closing-block" style="margin-top: 25px;">
            {sig_space_html}
            <p>{data.signatory_name}</p>
            <p>{data.signatory_position}</p>
        </div>
        """

    page_counter_style = "thai" if data.use_thai_numerals else "decimal"
    html = f"""<!DOCTYPE html>
<html lang="th">
<head>
<meta charset="utf-8">
<style>
{_local_font_faces_css()}
@page {{
    size: A4 portrait;
    margin: 25mm 20mm 20mm 30mm; /* บน 2.5 ซม. ขวา 2 ซม. ล่าง 2 ซม. ซ้าย 3 ซม. */
    @top-center {{
        content: "-" counter(page, {page_counter_style}) "-";
        font-family: 'TH Sarabun New', 'TH Sarabun PSK', 'Sarabun', sans-serif;
        font-size: 16pt;
    }}
}}
@page :first {{
    @top-center {{ content: none; }}
}}
body {{
    font-family: 'TH Sarabun New', 'TH Sarabun PSK', 'Sarabun', sans-serif;
    font-size: 16pt;
    line-height: 1.55;
    color: #000000;
    margin: 0;
    padding: 0;
    background: #ffffff;
}}
p, div, span, td, strong {{
    font-family: 'TH Sarabun New', 'TH Sarabun PSK', 'Sarabun', sans-serif;
}}
p {{
    font-size: 16pt;
    margin-top: 0;
    margin-bottom: 6pt;
    text-align: justify;
    text-justify: inter-cluster;
}}
.indent {{
    text-indent: 2.5cm;
}}
.garuda-center {{
    text-align: center;
    margin-bottom: 10px;
}}
.row-between {{
    display: flex;
    justify-content: space-between;
    margin-bottom: 6pt;
}}
.date-center {{
    text-align: center;
    margin-left: 20%;
    margin-bottom: 12pt;
}}
.closing-block {{
    text-align: center;
    margin-left: 45%;
    margin-top: 24pt;
    margin-bottom: 24pt;
}}
.memo-head {{
    position: relative;
    height: 1.6cm;
    margin-bottom: 4pt;
}}
.memo-head img {{
    position: absolute;
    left: 0;
    top: 0;
}}
.memo-title {{
    text-align: center;
    font-size: 29pt;
    font-weight: bold;
    line-height: 1.6cm;
}}
.memo-field {{
    display: flex;
    align-items: baseline;
    line-height: 1.35;
}}
.memo-label {{
    font-size: 20pt;
    font-weight: bold;
    margin-right: 0.25cm;
    white-space: nowrap;
}}
.memo-value {{
    flex: 1;
    border-bottom: 1px dotted #000;
    padding-left: 0.15cm;
}}
.memo-body p {{
    margin-bottom: 0;
    line-height: 1.4;
    /* Chromium กระจายช่องว่างได้เฉพาะที่ช่องว่างระหว่างคำ ทำให้ภาษาไทยเว้นห่างผิดปกติ จึงชิดซ้ายแทน
       (ไฟล์ Word ยังใช้ Thai Distributed ตามมาตรฐาน) */
    text-align: left;
}}
.memo-body .memo-heading {{
    page-break-after: avoid;
}}
.footer-contact {{
    font-size: 14pt;
    margin-top: 28pt;
    color: #000000;
    line-height: 1.35;
}}
</style>
</head>
<body>
{body_content}
</body>
</html>
"""
    return html


def export_govdoc_to_pdf(data: GovDocumentSchema, output_path: str, garuda_path: Optional[str] = None) -> str:
    """
    แปลง GovDocumentSchema เป็นไฟล์ PDF คุณภาพสูง (Vector PDF)
    """
    browser_exe = _find_browser_executable()
    if not browser_exe:
        raise RuntimeError("ไม่พบ Browser Executable (Microsoft Edge หรือ Google Chrome) สำหรับเรนเดอร์ PDF")

    html_code = generate_govdoc_html(data, garuda_path)
    with tempfile.NamedTemporaryFile(suffix=".html", delete=False, mode="w", encoding="utf-8") as tmp_html:
        tmp_html.write(html_code)
        tmp_html_path = tmp_html.name

    out_file = Path(output_path).resolve()
    out_file.parent.mkdir(parents=True, exist_ok=True)

    temp_profile_dir = tempfile.mkdtemp(prefix="govdoc_edge_")
    cmd = [
        browser_exe,
        "--headless",
        "--disable-gpu",
        "--no-sandbox",
        "--disable-dev-shm-usage",
        f"--user-data-dir={temp_profile_dir}",
        "--no-pdf-header-footer",
        f"--print-to-pdf={str(out_file)}",
        tmp_html_path
    ]

    try:
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if not out_file.exists() or out_file.stat().st_size == 0:
            raise RuntimeError(f"การสร้างไฟล์ PDF ล้มเหลว: {res.stderr or res.stdout}")
        return str(out_file)
    finally:
        try:
            os.remove(tmp_html_path)
        except OSError:
            pass
        try:
            shutil.rmtree(temp_profile_dir, ignore_errors=True)
        except OSError:
            pass


def get_pdf_bytes(data: GovDocumentSchema, garuda_path: Optional[str] = None) -> bytes:
    """สร้างและคืนค่าเป็น bytes ของไฟล์ PDF สำหรับดาวน์โหลดใน 1 คลิก"""
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp_pdf:
        tmp_pdf_path = tmp_pdf.name
    try:
        export_govdoc_to_pdf(data, tmp_pdf_path, garuda_path)
        with open(tmp_pdf_path, "rb") as f:
            return f.read()
    finally:
        try:
            os.remove(tmp_pdf_path)
        except OSError:
            pass
