"""
app.py — หน้าจอใช้งานหลัก (Interactive Workspace) สำหรับ Thai GovDoc AI Studio
พัฒนาตามโมเดล Modern GovDoc Studio (Split-Screen Workspace, Compact Modern Typography, Smart Placeholders & A4 Canvas)
รันด้วย Streamlit: streamlit run web/app.py
"""

import os
import re
import sys
import base64
import tempfile
from pathlib import Path

# เพิ่ม Root directory เข้า sys.path
root_dir = Path(__file__).resolve().parent.parent
if str(root_dir) not in sys.path:
    sys.path.insert(0, str(root_dir))

# รีเฟรชโมดูล core ทุกครั้งที่บันทึกไฟล์เพื่อป้องกัน Streamlit แคช sys.modules ตัวเก่า
import importlib
for mod in ["core.models", "core.profile_manager", "core.extractor", "core.templates_library", "core.linter", "core.memo_layout", "core.ai_drafter", "core.word_exporter", "core.pdf_exporter"]:
    if mod in sys.modules:
        try:
            importlib.reload(sys.modules[mod])
        except Exception:
            pass

import streamlit as st

from core.models import GovDocumentSchema, DocType, UrgencyLevel, SecretLevel, SourceDocumentContext, MemoHierarchyLevel, UserProfileSchema, ExportOptions
from core.profile_manager import get_user_profile, save_user_profile, reset_to_default_profile
from core.extractor import extract_source_document, extract_from_raw_text
from core.ai_drafter import draft_from_context_rule_based, draft_from_context_llm, DraftingIntent
from core.templates_library import PRESET_TEMPLATES
from core.pdf_exporter import get_pdf_bytes, export_govdoc_to_pdf
from core.copilot import (
    make_formal_tone,
    make_concise,
    insert_legal_reference,
    convert_doc_type,
    toggle_doc_numerals,
    copilot_refine_paragraph
)
from core.audit import AuditManager, compute_doc_diff
from core.word_exporter import export_govdoc_to_docx
from core.typst_exporter import export_govdoc_to_typst, generate_typst_content
from core.linter import lint_gov_document
from core.registry import DocumentRegistry, OutgoingRecord
from core.thai_segmenter import to_thai_numerals, to_arabic_numerals
from core.memo_layout import render_memo_blocks_html, split_consideration_and_request, SECTION_ORDER


st.set_page_config(
    page_title="Thai GovDoc AI Studio - ระบบร่างและผลิตหนังสือราชการไทยอัจฉริยะ",
    page_icon="🏛️",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# Custom Styling ปรับขนาดตัวอักษรและระยะขอบให้กะทัดรัด สวยงาม ทันสมัย แบบ Modern SaaS / Ekkasarn.com
st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Sarabun:ital,wght@0,300;0,400;0,500;0,600;0,700;1,400&display=swap');

    /* 1. Reset & Global Layout */
    .block-container {
        padding-top: 0.9rem !important;
        padding-bottom: 2rem !important;
        padding-left: 1.8rem !important;
        padding-right: 1.8rem !important;
        max-width: 98% !important;
    }
    header[data-testid="stHeader"] {
        display: none !important;
    }
    
    /* 2. Top Navigation Bar */
    .top-navbar {
        display: flex;
        justify-content: space-between;
        align-items: center;
        background: #ffffff;
        border: 1px solid #e2e8f0;
        border-radius: 8px;
        padding: 8px 16px;
        margin-bottom: 0.75rem;
        box-shadow: 0 1px 3px rgba(0, 0, 0, 0.03);
    }
    .brand-section {
        display: flex;
        align-items: center;
        gap: 8px;
    }
    .brand-title {
        font-size: 1.15rem;
        font-weight: 700;
        color: #0f172a;
        margin: 0;
        letter-spacing: -0.01em;
    }
    .brand-badge {
        font-size: 0.75rem;
        color: #475569;
        background: #f1f5f9;
        border: 1px solid #e2e8f0;
        padding: 2px 7px;
        border-radius: 5px;
        font-weight: 500;
    }

    /* 3. Typography Scaled Down to Fit Standard Screens */
    h1, h2, h3, .stSubheader {
        font-size: 0.96rem !important;
        font-weight: 600 !important;
        color: #1e293b !important;
        margin-top: 0.2rem !important;
        margin-bottom: 0.4rem !important;
    }
    h4, h5 {
        font-size: 0.86rem !important;
        font-weight: 600 !important;
        color: #334155 !important;
        margin-top: 0.25rem !important;
        margin-bottom: 0.25rem !important;
    }
    p, span, label, div {
        font-size: 0.83rem !important;
    }
    .stRadio label {
        font-size: 0.82rem !important;
        margin-bottom: 2px !important;
    }
    .stTextInput input, .stTextArea textarea, .stSelectbox select {
        font-size: 0.82rem !important;
        padding: 0.3rem 0.5rem !important;
        border-radius: 5px !important;
    }

    /* 4. Tabs Styling */
    .stTabs [data-baseweb="tab-list"] {
        gap: 12px;
        border-bottom: 1px solid #e2e8f0;
    }
    .stTabs [data-baseweb="tab"] {
        font-size: 0.83rem !important;
        font-weight: 500 !important;
        padding: 5px 8px !important;
        color: #64748b;
    }
    .stTabs [aria-selected="true"] {
        font-weight: 600 !important;
        color: #0284c7 !important;
        border-bottom-color: #0284c7 !important;
    }

    /* 5. Buttons Styling - Single Line, Perfectly Fitted */
    .stButton button, .stDownloadButton button {
        font-size: 0.72rem !important;
        padding: 0.15rem 0.35rem !important;
        height: 32px !important;
        min-height: 32px !important;
        border-radius: 5px !important;
        font-weight: 500 !important;
        white-space: nowrap !important;
        overflow: hidden !important;
        text-overflow: ellipsis !important;
        display: flex !important;
        align-items: center !important;
        justify-content: center !important;
        line-height: 1.2 !important;
        transition: all 0.15s ease;
    }
    .stButton button {
        border: 1px solid #cbd5e1 !important;
        background-color: #ffffff !important;
        color: #334155 !important;
        box-shadow: 0 1px 2px rgba(0,0,0,0.02) !important;
    }
    .stButton button:hover {
        border-color: #94a3b8 !important;
        background-color: #f8fafc !important;
        color: #0f172a !important;
    }
    .stButton button[kind="primary"] {
        background-color: #0f172a !important;
        color: #ffffff !important;
        border-color: #0f172a !important;
        font-size: 0.85rem !important;
        height: 38px !important;
        min-height: 38px !important;
        padding: 0.4rem 1rem !important;
    }
    .stButton button[kind="primary"]:hover {
        background-color: #1e293b !important;
        color: #ffffff !important;
    }
    .stDownloadButton button {
        border: 1px solid #059669 !important;
        background-color: #10b981 !important;
        color: #ffffff !important;
    }
    .stDownloadButton button:hover {
        background-color: #059669 !important;
        color: #ffffff !important;
    }
    .stButton button p, .stDownloadButton button p,
    .stButton button div, .stDownloadButton button div,
    .stButton button span, .stDownloadButton button span {
        font-size: 0.72rem !important;
        white-space: nowrap !important;
        word-break: keep-all !important;
        overflow: hidden !important;
        text-overflow: ellipsis !important;
        margin: 0 !important;
        padding: 0 !important;
        line-height: 1.2 !important;
    }
    .stButton button[kind="primary"] p {
        font-size: 0.85rem !important;
    }

    /* 6. Status Pills */
    .status-pill {
        padding: 2px 9px;
        border-radius: 9999px;
        font-size: 0.76rem;
        font-weight: 600;
        display: inline-block;
        margin-right: 4px;
    }
    .status-pill-ready {
        background-color: #ecfdf5;
        color: #047857;
        border: 1px solid #a7f3d0;
    }
    .status-pill-warning {
        background-color: #fffbeb;
        color: #b45309;
        border: 1px solid #fde68a;
    }
    .status-pill-info {
        background-color: #f0f9ff;
        color: #0369a1;
        border: 1px solid #bae6fd;
    }
    
    /* 7. Smart Placeholder Chip */
    .placeholder-chip {
        background-color: #fef3c7;
        color: #92400e;
        border: 1px dashed #d97706;
        padding: 1px 5px;
        border-radius: 4px;
        font-weight: 600;
        font-size: 0.90em;
        display: inline-block;
        margin: 0 2px;
    }

    /* 8. A4 Paper Simulation - Calibrated to fit on screen cleanly like Ekkasarn */
    .a4-paper {
        background: #ffffff;
        width: 100%;
        max-width: 680px;
        min-height: 940px;
        padding: 36px 42px 36px 52px !important; /* อัตราส่วนขอบกระดาษจริง: ซ้าย 3 ซม. ขวา 2 ซม. บน-ล่าง 2.5 ซม. */
        margin: 6px auto 16px auto !important;
        box-shadow: 0 4px 20px rgba(0,0,0,0.12), 0 1px 3px rgba(0,0,0,0.06) !important;
        border: 1px solid #cbd5e1 !important;
        border-radius: 2px !important;
        font-family: 'TH Sarabun New', 'TH Sarabun PSK', 'Sarabun', sans-serif !important;
        font-size: 14.5px !important;  /* เทียบเท่าขนาด 16pt ของจริง */
        line-height: 1.55 !important;
        color: #000000 !important;
        box-sizing: border-box !important;
    }
    .a4-paper p, .a4-paper div, .a4-paper span, .a4-paper td, .a4-paper strong {
        font-family: 'TH Sarabun New', 'TH Sarabun PSK', 'Sarabun', sans-serif !important;
    }
    .a4-paper p {
        font-size: 14.5px !important;
        margin-bottom: 6px !important;
        text-align: justify !important;
        line-height: 1.55 !important;
    }
    .a4-indent {
        text-indent: 2.2cm !important; /* ตามระเบียบงานสารบรรณ ย่อหน้า ๒.๕ ซม. */
    }
    /* เนื้อความบันทึกข้อความ: ย่อหน้าต่อเนื่องไม่เว้นบรรทัด ระยะย่อหน้ากำหนดจาก core.memo_layout */
    .a4-paper p.memo-heading, .a4-paper p.memo-body, .a4-paper p.memo-request {
        margin-bottom: 0 !important;
        text-align: left !important;
    }
    .a4-paper .memo-field {
        display: flex;
        align-items: baseline;
        font-size: 14.5px;
        line-height: 1.5;
    }
    .a4-paper .memo-label {
        font-size: 18px;
        font-weight: bold;
        margin-right: 8px;
        white-space: nowrap;
    }
    .a4-paper .memo-value {
        flex: 1;
        border-bottom: 1px dotted #000;
        padding-left: 4px;
    }
    .diff-ins {
        background-color: #dcfce7;
        color: #166534;
        padding: 1px 3px;
        border-radius: 2px;
        font-weight: 600;
    }
    .diff-del {
        background-color: #fee2e2;
        color: #991b1b;
        text-decoration: line-through;
        padding: 1px 3px;
        border-radius: 2px;
    }
</style>
""", unsafe_allow_html=True)


# โหลดรูปครุฑแบบ Base64 สำหรับแสดงใน HTML พรีวิว (ใช้ Vector SVG คมชัด 100% หรือ PNG ความละเอียดสูง)
garuda_svg_path = root_dir / "assets" / "garuda.svg"
garuda_png_path = root_dir / "assets" / "garuda.png"
if garuda_svg_path.exists():
    with open(garuda_svg_path, "rb") as f:
        garuda_b64 = base64.b64encode(f.read()).decode("utf-8")
        garuda_mime = "image/svg+xml"
elif garuda_png_path.exists():
    with open(garuda_png_path, "rb") as f:
        garuda_b64 = base64.b64encode(f.read()).decode("utf-8")
        garuda_mime = "image/png"
else:
    garuda_b64 = ""
    garuda_mime = "image/png"

registry = DocumentRegistry()
audit_mgr = AuditManager()
uploads_dir = root_dir / "uploads"
uploads_dir.mkdir(exist_ok=True)


def highlight_placeholders_html(text: str) -> str:
    """
    ตรวจจับ [ระบุ...], [✏️ ระบุ...] หรือ {{...}} แล้วครอบด้วย <span class="placeholder-chip">✏️ ...</span>
    """
    if not text:
        return ""
    def repl(m):
        raw = m.group(0)
        clean = raw.strip("[]{}").replace("✏️", "").strip()
        return f'<span class="placeholder-chip">✏️ {clean}</span>'
    return re.sub(r'\[(?:✏️\s*)?ระบุ[^\]]*\]|\{\{[^\}]+\}\}', repl, text)


def get_docx_bytes(doc_schema: GovDocumentSchema, options: ExportOptions | None = None) -> bytes:
    """สร้างไฟล์ Word .docx ในหน่วยความจำและส่งออกเป็น bytes สำหรับดาวน์โหลดใน 1 คลิก"""
    with tempfile.NamedTemporaryFile(suffix=".docx", delete=False) as tmp:
        tmp_path = tmp.name
    try:
        export_govdoc_to_docx(doc_schema, tmp_path, options=options)
        with open(tmp_path, "rb") as f:
            data = f.read()
    finally:
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except Exception:
                pass
    return data


def get_typst_bytes(doc_schema: GovDocumentSchema) -> bytes:
    """สร้างไฟล์ Typst .typ และส่งออกเป็น bytes สำหรับดาวน์โหลดใน 1 คลิก"""
    content = generate_typst_content(doc_schema)
    return content.encode("utf-8")

# ----------------- MODAL DIALOGS สำหรับปุ่มดินสอแก้ไขด่วนตามหัวข้อ -----------------

@st.dialog("✏️ แก้ไขข้อมูลส่วนหัวหนังสือ", width="large")
def edit_header_dialog():
    doc = st.session_state.doc_data
    st.caption("แก้ไขข้อมูลส่วนราชการ เลขที่ วันที่ ชื่อเรื่อง คำขึ้นต้น และเอกสารแนบ")
    
    col1, col2 = st.columns([2, 1])
    with col1:
        dept = st.text_input("ส่วนราชการเจ้าของเรื่อง", value=doc.dept_name, key="dlg_in_dept")
    with col2:
        tel = st.text_input("หมายเลขโทรศัพท์ (ถ้ามี)", value=doc.contact_tel or "", key="dlg_in_tel")
        
    c_n1, c_n2 = st.columns(2)
    with c_n1:
        no = st.text_input("ที่ (เลขที่หนังสือ)", value=doc.doc_number, key="dlg_in_no")
    with c_n2:
        date = st.text_input("วันที่ (เช่น ๑๕ มีนาคม ๒๕๖๙)", value=doc.doc_date, key="dlg_in_date")
        
    sub = st.text_input("เรื่อง", value=doc.subject, key="dlg_in_sub")
    sal = st.text_input("คำขึ้นต้น (เช่น เรียน ผู้อำนวยการ... / กราบเรียน...)", value=doc.salutation, key="dlg_in_sal")
    
    c_ref, c_att = st.columns(2)
    with c_ref:
        ref_text = "\n".join(doc.references) if doc.references else ""
        new_ref = st.text_area("อ้างถึง (๑ บรรทัดต่อ ๑ ฉบับ)", value=ref_text, height=65, key="dlg_in_ref")
    with c_att:
        att_text = "\n".join(doc.attachments) if doc.attachments else ""
        new_att = st.text_area("สิ่งที่ส่งมาด้วย (๑ บรรทัดต่อ ๑ ฉบับ)", value=att_text, height=65, key="dlg_in_att")
        
    col_save, col_cancel = st.columns([2, 1])
    with col_save:
        if st.button("💾 บันทึกการแก้ไขส่วนหัว", key="save_dlg_hdr", type="primary", use_container_width=True):
            doc.dept_name = dept.strip()
            doc.contact_tel = tel.strip() or None
            doc.doc_number = no.strip()
            doc.doc_date = date.strip()
            doc.subject = sub.strip()
            doc.salutation = sal.strip()
            doc.references = [line.strip() for line in new_ref.splitlines() if line.strip()] or None
            doc.attachments = [line.strip() for line in new_att.splitlines() if line.strip()] or None
            st.session_state.doc_data = doc
            st.success("บันทึกข้อมูลส่วนหัวสำเร็จ!")
            st.rerun()
    with col_cancel:
        if st.button("ปิดหน้าต่าง", key="close_dlg_hdr", use_container_width=True):
            st.rerun()


@st.dialog("✏️ แก้ไขเนื้อความ: ๑. ต้นเรื่อง", width="large")
def edit_intro_dialog():
    doc = st.session_state.doc_data
    current_val = doc.memo_intro or doc.paragraph_reason or ""
    st.caption("ระบุความเป็นมา การขอความอนุเคราะห์ คำร้อง หรือหนังสือที่ส่งเข้ามา")
    
    val = st.text_area("เนื้อความ ๑. ต้นเรื่อง", value=current_val, height=150, key="dlg_in_intro")
    
    h1, h2 = st.columns(2)
    with h1:
        if st.button("✍️ ปรับสำนวนให้เป็นทางการ", key="btn_intro_formal", use_container_width=True):
            val = make_formal_tone(val)
    with h2:
        if st.button("✂️ ย่อข้อความให้กระชับ", key="btn_intro_concise", use_container_width=True):
            val = make_concise(val)

    col_save, col_cancel = st.columns([2, 1])
    with col_save:
        if st.button("💾 บันทึกต้นเรื่อง", key="save_dlg_intro", type="primary", use_container_width=True):
            doc.memo_intro = val.strip()
            doc.paragraph_reason = val.strip()
            st.session_state.doc_data = doc
            st.success("บันทึกต้นเรื่องสำเร็จ!")
            st.rerun()
    with col_cancel:
        if st.button("ปิดหน้าต่าง", key="close_dlg_intro", use_container_width=True):
            st.rerun()


@st.dialog("✏️ แก้ไขเนื้อความ: ๒. ข้อเท็จจริง", width="large")
def edit_facts_dialog():
    doc = st.session_state.doc_data
    current_val = doc.memo_facts or doc.paragraph_details or ""
    st.caption("ระบุรายละเอียดข้อเท็จจริงจากการตรวจสอบ ข้อมูลโครงการ วัน เวลา สถานที่ และผู้เข้าร่วม")
    
    val = st.text_area("เนื้อความ ๒. ข้อเท็จจริง", value=current_val, height=170, key="dlg_in_facts")
    
    h1, h2 = st.columns(2)
    with h1:
        if st.button("✍️ ปรับสำนวนให้เป็นทางการ", key="btn_facts_formal", use_container_width=True):
            val = make_formal_tone(val)
    with h2:
        if st.button("✂️ ย่อข้อความให้กระชับ", key="btn_facts_concise", use_container_width=True):
            val = make_concise(val)

    col_save, col_cancel = st.columns([2, 1])
    with col_save:
        if st.button("💾 บันทึกข้อเท็จจริง", key="save_dlg_facts", type="primary", use_container_width=True):
            doc.memo_facts = val.strip()
            doc.paragraph_details = val.strip()
            st.session_state.doc_data = doc
            st.success("บันทึกข้อเท็จจริงสำเร็จ!")
            st.rerun()
    with col_cancel:
        if st.button("ปิดหน้าต่าง", key="close_dlg_facts", use_container_width=True):
            st.rerun()


@st.dialog("✏️ แก้ไขเนื้อความ: ๓. ข้อกฎหมาย (ถ้ามี)", width="large")
def edit_law_dialog():
    doc = st.session_state.doc_data
    current_val = doc.memo_law or ""
    st.caption("ระบุระเบียบ กฎหมาย หรือข้อบังคับที่เกี่ยวข้อง (สามารถเว้นว่างได้หากไม่มีเรื่องที่ต้องอ้างกฎหมาย)")
    
    val = st.text_area("เนื้อความ ๓. ข้อกฎหมาย", value=current_val, height=140, key="dlg_in_law")
    
    st.markdown("###### ⚖️ ตัวช่วยแทรกข้อกฎหมายและระเบียบที่ใช้บ่อย:")
    l1, l2, l3 = st.columns(3)
    with l1:
        if st.button("🏛️ ระเบียบตราสัญลักษณ์/สถานที่ กทม.", key="law_bma_btn", use_container_width=True):
            val = "ตามระเบียบกรุงเทพมหานครว่าด้วยการใช้ตราเครื่องหมายราชการของกรุงเทพมหานคร พ.ศ. ๒๕๓๓ ข้อ ๖ กำหนดว่าการนำตราเครื่องหมายราชการของกรุงเทพมหานครไปใช้ ต้องได้รับความเห็นชอบจากผู้ว่าราชการกรุงเทพมหานครหรือผู้ที่ได้รับมอบหมาย และระเบียบกรุงเทพมหานครว่าด้วยการใช้สถานที่ของกรุงเทพมหานคร พ.ศ. ๒๕๓๖"
    with l2:
        if st.button("📦 พ.ร.บ. จัดซื้อจัดจ้างพัสดุ", key="law_proc_btn", use_container_width=True):
            val = "ตามพระราชบัญญัติการจัดซื้อจัดจ้างและการบริหารพัสดุภาครัฐ พ.ศ. ๒๕๖๐ และระเบียบกระทรวงการคลังว่าด้วยการจัดซื้อจัดจ้างและการบริหารพัสดุภาครัฐ พ.ศ. ๒๕๖๐ หมวด ๒ เรื่องการเตรียมการจัดซื้อจัดจ้าง"
    with l3:
        if st.button("📑 ระเบียบงานสารบรรณ", key="law_saraban_btn", use_container_width=True):
            val = "ตามระเบียบสำนักนายกรัฐมนตรีว่าด้วยงานสารบรรณ พ.ศ. ๒๕๒๖ และที่แก้ไขเพิ่มเติม กำหนดให้หน่วยงานของรัฐสามารถประสานงานและยกร่างบันทึกข้อความเพื่อเสนอผู้บังคับบัญชาพิจารณาได้ตามอำนาจหน้าที่"

    col_save, col_clear, col_cancel = st.columns([1.5, 1, 1])
    with col_save:
        if st.button("💾 บันทึกข้อกฎหมาย", key="save_dlg_law", type="primary", use_container_width=True):
            doc.memo_law = val.strip() if val.strip() else None
            st.session_state.doc_data = doc
            st.success("บันทึกข้อกฎหมายสำเร็จ!")
            st.rerun()
    with col_clear:
        if st.button("🗑️ ลบ/ไม่ระบุกฎหมาย", key="clear_dlg_law", use_container_width=True):
            doc.memo_law = None
            st.session_state.doc_data = doc
            st.success("ลบข้อกฎหมายเรียบร้อย (ระบบจะจัดเรียง ๓ หัวข้อให้อัตโนมัติ)")
            st.rerun()
    with col_cancel:
        if st.button("ปิดหน้าต่าง", key="close_dlg_law", use_container_width=True):
            st.rerun()


@st.dialog("✏️ แก้ไขเนื้อความ: ๔. ข้อพิจารณาและเสนอแนะ", width="large")
def edit_consideration_dialog():
    doc = st.session_state.doc_data
    current_val = doc.memo_consideration or doc.paragraph_purpose or ""
    st.caption("รวมข้อพิจารณาและข้อเสนอแนะไว้ในย่อหน้าเดียวกัน พร้อมประโยคลงท้ายเสนอผู้บังคับบัญชา")
    
    val = st.text_area("เนื้อความ ๔. ข้อพิจารณาและเสนอแนะ", value=current_val, height=160, key="dlg_in_cons")
    
    h1, h2 = st.columns(2)
    with h1:
        if st.button("✍️ ปรับสำนวนให้เป็นทางการ", key="btn_cons_formal", use_container_width=True):
            val = make_formal_tone(val)
    with h2:
        if st.button("📌 ใส่ข้อเสนอเห็นชอบโปรดลงนาม", key="btn_cons_propose", use_container_width=True):
            if "จึงเรียนมาเพื่อโปรด" not in val:
                val = val.rstrip() + "\n\nจึงเรียนมาเพื่อโปรดพิจารณา หากเห็นชอบโปรดลงนามในหนังสือที่แนบมาพร้อมนี้"

    st.markdown("###### 🏛️ ประโยคลงท้ายตามระดับชั้นการเสนอหนังสือ:")
    cl1, cl2 = st.columns(2)
    with cl1:
        if st.button("📁 ระดับกลุ่มงาน (เสนอ ผอ.กอง)", key="btn_cl_sec", use_container_width=True):
            closing = "จึงเรียนมาเพื่อโปรดพิจารณานำเรียนผู้อำนวยการกองการกีฬาลงนามในหนังสือที่แนบ"
            lines = [l for l in val.splitlines() if not l.strip().startswith("จึงเรียนมาเพื่อ")]
            val = "\n".join(lines).rstrip() + "\n\n" + closing
        if st.button("🏛️ ระดับสำนัก (เสนอ ปลัด นำเรียนผู้ว่าฯ)", key="btn_cl_dept", use_container_width=True):
            closing = "จึงเรียนมาเพื่อโปรดพิจารณา หากเห็นชอบโปรดนำเรียนผู้ว่าราชการกรุงเทพมหานคร เพื่อโปรดพิจารณาให้ความเห็นชอบและสั่งการตามที่เสนอข้างต้น"
            lines = [l for l in val.splitlines() if not l.strip().startswith("จึงเรียนมาเพื่อ")]
            val = "\n".join(lines).rstrip() + "\n\n" + closing
    with cl2:
        if st.button("🏢 ระดับกอง (เสนอ ผอ.สำนัก)", key="btn_cl_div", use_container_width=True):
            closing = "จึงเรียนมาเพื่อโปรดพิจารณาลงนามหนังสือเรียนปลัดกรุงเทพมหานครที่แนบ"
            lines = [l for l in val.splitlines() if not l.strip().startswith("จึงเรียนมาเพื่อ")]
            val = "\n".join(lines).rstrip() + "\n\n" + closing
        if st.button("✍️ เสนอผู้มีอำนาจสั่งการ (อนุมัติ/ลงนาม)", key="btn_cl_appr", use_container_width=True):
            closing = "จึงเรียนมาเพื่อโปรดพิจารณา หากเห็นชอบโปรดลงนามในหนังสือที่แนบมาพร้อมนี้"
            lines = [l for l in val.splitlines() if not l.strip().startswith("จึงเรียนมาเพื่อ")]
            val = "\n".join(lines).rstrip() + "\n\n" + closing

    col_save, col_cancel = st.columns([2, 1])
    with col_save:
        if st.button("💾 บันทึกข้อพิจารณาและเสนอแนะ", key="save_dlg_cons", type="primary", use_container_width=True):
            doc.memo_consideration = val.strip()
            doc.paragraph_purpose = val.strip()
            st.session_state.doc_data = doc
            st.success("บันทึกข้อพิจารณาและเสนอแนะสำเร็จ!")
            st.rerun()
    with col_cancel:
        if st.button("ปิดหน้าต่าง", key="close_dlg_cons", use_container_width=True):
            st.rerun()


@st.dialog("✏️ แก้ไขข้อมูลผู้ลงนามและลายมือชื่อ", width="medium")
def edit_signatory_dialog():
    doc = st.session_state.doc_data
    st.caption("แก้ไขชื่อเต็ม ตำแหน่งผู้ลงนาม และจัดการลายมือชื่อดิจิทัล")
    
    name = st.text_input("ชื่อเต็มผู้ลงนาม (เช่น (นายสมชาย ใจดี))", value=doc.signatory_name, key="dlg_in_signame")
    pos = st.text_input("ตำแหน่งผู้ลงนาม", value=doc.signatory_position, key="dlg_in_sigpos")
    
    st.markdown("###### ✍️ ลายมือชื่อดิจิทัล:")
    uploaded_sig = st.file_uploader("อัปโหลดไฟล์ภาพลายมือชื่อ (PNG โปร่งใส แนะนำ / JPG)", type=["png", "jpg", "jpeg"], key="dlg_sig_file_uploader")
    if uploaded_sig is not None:
        uploads_dir = Path(__file__).resolve().parent.parent / "uploads"
        uploads_dir.mkdir(parents=True, exist_ok=True)
        sig_path = uploads_dir / f"signature_{uploaded_sig.name}"
        with open(sig_path, "wb") as f_s:
            f_s.write(uploaded_sig.getbuffer())
        doc.signature_image_path = str(sig_path)
        st.success("อัปโหลดลายมือชื่อสำเร็จ")
    
    if doc.signature_image_path and os.path.exists(doc.signature_image_path):
        st.image(doc.signature_image_path, width=120, caption="ลายมือชื่อปัจจุบัน")
        if st.button("🗑️ ปลดลายมือชื่อออกจากเอกสาร", key="btn_clear_sig_dlg"):
            doc.signature_image_path = None
            st.rerun()

    col_save, col_cancel = st.columns([2, 1])
    with col_save:
        if st.button("💾 บันทึกข้อมูลผู้ลงนาม", key="save_dlg_sig", type="primary", use_container_width=True):
            doc.signatory_name = name.strip()
            doc.signatory_position = pos.strip()
            st.session_state.doc_data = doc
            st.success("บันทึกข้อมูลผู้ลงนามสำเร็จ!")
            st.rerun()
    with col_cancel:
        if st.button("ปิดหน้าต่าง", key="close_dlg_sig", use_container_width=True):
            st.rerun()


@st.dialog("✏️ แก้ไขข้อมูลติดต่อสอบถาม (สำหรับหนังสือภายนอก)", width="medium")
def edit_contact_dialog():
    doc = st.session_state.doc_data
    st.caption("แก้ไขข้อมูลกลุ่มงาน/กองเจ้าของเรื่อง และช่องทางติดต่อท้ายกระดาษ")
    
    dept = st.text_input("กลุ่มงาน/กองเจ้าของเรื่อง", value=doc.contact_dept or "", key="dlg_in_cdept")
    tel = st.text_input("โทรศัพท์", value=doc.contact_tel or "", key="dlg_in_ctel")
    fax = st.text_input("โทรสาร", value=doc.contact_fax or "", key="dlg_in_cfax")
    email = st.text_input("ไปรษณีย์อิเล็กทรอนิกส์ (อีเมล)", value=doc.contact_email or "", key="dlg_in_cemail")
    
    col_save, col_cancel = st.columns([2, 1])
    with col_save:
        if st.button("💾 บันทึกข้อมูลติดต่อ", key="save_dlg_contact", type="primary", use_container_width=True):
            doc.contact_dept = dept.strip()
            doc.contact_tel = tel.strip() or None
            doc.contact_fax = fax.strip() or None
            doc.contact_email = email.strip() or None
            st.session_state.doc_data = doc
            st.success("บันทึกข้อมูลติดต่อสำเร็จ!")
            st.rerun()
    with col_cancel:
        if st.button("ปิดหน้าต่าง", key="close_dlg_contact", use_container_width=True):
            st.rerun()


@st.dialog("✏️ เติมข้อมูลจุดที่ต้องระบุ (Smart Placeholders)", width="medium")
def edit_placeholders_dialog():
    doc = st.session_state.doc_data
    placeholders = doc.find_placeholders()
    if not placeholders:
        st.info("ไม่พบจุดที่ต้องระบุข้อมูลเพิ่มเติมในเอกสารนี้แล้วครับ")
        if st.button("ปิด"):
            st.rerun()
        return

    st.caption("กรอกข้อมูลเพื่อแทนที่เครื่องหมาย [✏️ ระบุ...] ในเอกสารทันที")
    unique_phs = list(dict.fromkeys([p[1] for p in placeholders]))
    replacements = {}
    
    for i, ph in enumerate(unique_phs):
        label = ph.replace("[✏️", "").replace("[", "").replace("]", "").strip()
        replacements[ph] = st.text_input(f"เติมข้อมูลสำหรับ: {label}", key=f"ph_fill_input_{i}")

    if st.button("💾 แทนที่ข้อมูลทั้งหมดในเอกสาร", type="primary", use_container_width=True):
        def _replace_all(text: str) -> str:
            if not text:
                return text
            for old_p, new_v in replacements.items():
                if new_v and new_v.strip():
                    text = text.replace(old_p, new_v.strip())
            return text

        doc.dept_name = _replace_all(doc.dept_name)
        doc.doc_number = _replace_all(doc.doc_number)
        doc.doc_date = _replace_all(doc.doc_date)
        doc.subject = _replace_all(doc.subject)
        doc.salutation = _replace_all(doc.salutation)
        doc.paragraph_reason = _replace_all(doc.paragraph_reason)
        doc.paragraph_details = _replace_all(doc.paragraph_details)
        doc.paragraph_purpose = _replace_all(doc.paragraph_purpose)
        doc.memo_intro = _replace_all(doc.memo_intro)
        doc.memo_facts = _replace_all(doc.memo_facts)
        doc.memo_law = _replace_all(doc.memo_law)
        doc.memo_consideration = _replace_all(doc.memo_consideration)
        doc.signatory_name = _replace_all(doc.signatory_name)
        doc.signatory_position = _replace_all(doc.signatory_position)
        if doc.references:
            doc.references = [_replace_all(r) for r in doc.references]
        if doc.attachments:
            doc.attachments = [_replace_all(a) for a in doc.attachments]

        st.session_state.doc_data = doc
        st.success("แทนที่ข้อมูลเรียบร้อยแล้ว!")
        st.rerun()



# Initialize Session State
if "doc_data" in st.session_state and not hasattr(st.session_state.doc_data, "get_memo_sections"):
    try:
        st.session_state.doc_data = GovDocumentSchema.model_validate(st.session_state.doc_data.model_dump())
    except Exception:
        pass

if "user_profile" not in st.session_state:
    st.session_state.user_profile = get_user_profile()

current_profile = st.session_state.user_profile

if "doc_data" not in st.session_state:
    st.session_state.doc_data = GovDocumentSchema(
        doc_type=DocType.INTERNAL,
        urgency=UrgencyLevel.NORMAL,
        secret=SecretLevel.NORMAL,
        use_thai_numerals=False,
        doc_number="๑๒๓/๒๕๖๙",
        dept_name=current_profile.department_full,
        doc_date="๑๕ มีนาคม ๒๕๖๙",
        subject="รายงานการพิจารณาคำขอความอนุเคราะห์จัดการแข่งขันกีฬา",
        salutation="เรียน  ผู้อำนวยการสำนักวัฒนธรรม กีฬา และการท่องเที่ยว",
        references=["หนังสือสมาคมกีฬา ที่ สวปท. ๑๕/๒๕๖๙ ลงวันที่ ๒๓ กันยายน ๒๕๖๙"],
        attachments=["สรุปผลการพิจารณา จำนวน ๑ ฉบับ"],
        paragraph_reason="ตามที่ สมาคมกีฬา ได้มีหนังสือที่อ้างถึง ขอความอนุเคราะห์จัดการแข่งขันกีฬา ความละเอียดแจ้งแล้ว นั้น",
        paragraph_details="จากการตรวจสอบข้อเท็จจริงพบว่า กิจกรรมดังกล่าวเป็นประโยชน์ต่อการพัฒนาเยาวชนและส่งเสริมกีฬาในกรุงเทพมหานคร",
        paragraph_purpose="จึงเรียนมาเพื่อโปรดพิจารณา หากเห็นชอบโปรดลงนามในหนังสือที่แนบมาพร้อมนี้",
        memo_intro="ตามที่ สมาคมกีฬา ได้มีหนังสือที่อ้างถึง ขอความอนุเคราะห์จัดการแข่งขันกีฬา ความละเอียดแจ้งแล้ว นั้น",
        memo_facts="๑. จากการตรวจสอบข้อเท็จจริง กิจกรรมดังกล่าวเป็นประโยชน์ต่อเยาวชนในพื้นที่กรุงเทพมหานคร\n๒. รายการคำขอประกอบด้วยการใช้อาคารกีฬา และการอำนวยความสะดวกด้านอุปกรณ์",
        memo_law="๑. ระเบียบกรุงเทพมหานครว่าด้วยการใช้สถานที่และศูนย์กีฬา พ.ศ. ๒๕๕๕",
        memo_consideration="เห็นควรให้การสนับสนุนและอำนวยความสะดวกในการจัดกิจกรรมดังกล่าว",
        memo_request="จึงเรียนมาเพื่อโปรดพิจารณาลงนามหนังสือเรียนปลัดกรุงเทพมหานครที่แนบ",
        memo_hierarchy_level=MemoHierarchyLevel.DIV_TO_DEPT,
        closing="",
        signatory_name=current_profile.signatory_name,
        signatory_position=current_profile.signatory_position,
        contact_dept=current_profile.contact_dept,
        contact_tel=current_profile.contact_tel,
        contact_fax=current_profile.contact_fax,
        contact_email=current_profile.contact_email
    )

if "initial_ai_draft" not in st.session_state:
    st.session_state.initial_ai_draft = st.session_state.doc_data.model_copy(deep=True)

if "source_context" not in st.session_state:
    st.session_state.source_context = None

if "last_uploaded_file" not in st.session_state:
    st.session_state.last_uploaded_file = None


# ส่วนหัวหน้าเว็บแบบ Compact Modern Top Bar
st.markdown("""
<div class="top-navbar">
    <div class="brand-section">
        <span style="font-size: 1.25rem;">🏛️</span>
        <div>
            <span class="brand-title">Thai GovDoc AI Studio</span>
            <span class="brand-desc">ระเบียบงานสารบรรณ พ.ศ. ๒๕๒๖</span>
        </div>
    </div>
    <div style="font-size: 0.78rem; color: #64748b;">
        ระบบร่างและตรวจแก้หนังสือราชการอัจฉริยะ (Human-in-the-loop)
    </div>
</div>
""", unsafe_allow_html=True)

# แถบเมนูหลัก (เพิ่มแท็บตั้งค่าหน่วยงานของฉัน)
tab_main, tab_registry, tab_profile = st.tabs([
    "📝 ห้องร่างและตรวจแก้หนังสือ",
    "📖 สมุดทะเบียนคุมสารบรรณ",
    "⚙️ ตั้งค่าหน่วยงานของฉัน"
])

# =====================================================================
# TAB 1: STUDIO & REVIEW
# =====================================================================
with tab_main:
    col_left, col_right = st.columns([0.95, 1.4], gap="medium")

    # ----------------- คอลัมน์ซ้าย: แนบไฟล์ต้นเรื่อง & สั่งการ AI -----------------
    with col_left:
        source_mode = st.radio(
            "โหมดการสร้างร่างหนังสือ:",
            options=["📂 แนบไฟล์ต้นเรื่อง (Source Document)", "📋 เลือกจากแบบฟอร์มมาตรฐาน (Preset Templates)"],
            horizontal=True,
            label_visibility="collapsed"
        )

        if source_mode == "📂 แนบไฟล์ต้นเรื่อง (Source Document)":
            st.subheader("📂 แนบไฟล์ต้นเรื่อง (Source Document)")
            uploaded_file = st.file_uploader(
                "อัปโหลดหนังสือเดิม / คำร้อง (PDF, DOCX, TXT, รูปภาพ)",
                type=["pdf", "docx", "txt", "png", "jpg", "jpeg"],
                label_visibility="collapsed"
            )

            if uploaded_file is not None:
                saved_path = uploads_dir / uploaded_file.name
                with open(saved_path, "wb") as f:
                    f.write(uploaded_file.getbuffer())

                # สกัดข้อความอัตโนมัติเมื่อมีการอัปโหลดไฟล์ใหม่
                if st.session_state.last_uploaded_file != uploaded_file.name:
                    with st.spinner("กำลังอ่านและสกัดข้อความจากเอกสารต้นเรื่อง (Multi-Engine OCR)..."):
                        ctx = extract_source_document(str(saved_path), api_key=st.session_state.get("ai_api_key"))
                        st.session_state.source_context = ctx
                        st.session_state.last_uploaded_file = uploaded_file.name

                if st.session_state.source_context and st.session_state.source_context.extraction_failed:
                    st.error("⚠️ ไม่สามารถถอดข้อความจากไฟล์นี้ได้โดยอัตโนมัติ")
                    st.caption(st.session_state.source_context.extraction_error)
                    st.info("💡 ท่านสามารถพิมพ์หรือวางข้อความสรุปต้นเรื่องด้านล่างนี้เพื่อใช้ยกร่างต่อได้ทันที หรือระบุ GEMINI_API_KEY ด้านล่างแล้วลองใหม่อีกครั้ง")
                    manual_text_in = st.text_area(
                        "📝 ป้อนข้อความหรือใจความสำคัญของหนังสือด้วยตนเอง:",
                        value="",
                        height=110,
                        placeholder="พิมพ์หรือคัดลอกข้อความสรุป เช่น ตามที่ สมาคม... มีหนังสือขอความอนุเคราะห์..."
                    )
                    if st.button("📥 บันทึกข้อความที่ป้อนด้วยตนเองนี้", use_container_width=True) and manual_text_in.strip():
                        new_ctx = extract_from_raw_text(manual_text_in, filename=uploaded_file.name)
                        st.session_state.source_context = new_ctx
                        st.success("บันทึกข้อความต้นเรื่องเรียบร้อยแล้ว!")
                        st.rerun()
                else:
                    eng_badge = f" (สกัดผ่าน {st.session_state.source_context.ocr_engine_used})" if (st.session_state.source_context and st.session_state.source_context.ocr_engine_used) else ""
                    st.success(f"แนบและสกัดข้อมูลสำเร็จ: {uploaded_file.name}{eng_badge}")

                # เลือกเจตนาการร่างหนังสือ (Drafting Intent)
                st.markdown("##### 🎯 วัตถุประสงค์ในการร่างหนังสือ:")
                intent_choice = st.radio(
                    "เจตนาการตอบ/ยกร่าง:",
                    options=[
                        (DraftingIntent.MEMO_REVIEW, "📑 บันทึกข้อความรายงานการพิจารณา / เกษียนเรื่องเดิม (แนะนำ)"),
                        (DraftingIntent.ACCEPT, "🤝 หนังสือตอบรับ / ยินดีให้ความอนุเคราะห์"),
                        (DraftingIntent.DECLINE, "❌ หนังสือแจ้งข้อขัดข้อง / ปฏิเสธอย่างสุภาพ"),
                        (DraftingIntent.FORWARD, "📨 หนังสือส่งต่อเรื่อง / แจ้งเวียน"),
                        (DraftingIntent.PROPOSAL, "📝 บันทึกข้อความเสนอผู้บังคับบัญชาเพื่อพิจารณาอนุมัติ")
                    ],
                    format_func=lambda x: x[1],
                    index=0,
                    label_visibility="collapsed"
                )

                is_internal_intent = intent_choice[0] in [DraftingIntent.PROPOSAL, DraftingIntent.MEMO_REVIEW]
                target_doc_type = DocType.INTERNAL if is_internal_intent else DocType.EXTERNAL

                with st.expander("⚙️ ตั้งค่าโมเดล AI ยกร่าง และ OCR (Gemini / OpenAI)", expanded=False):
                    ai_prov = st.selectbox("AI Engine:", ["Gemini 2.5 Flash (Google)", "OpenAI GPT-4o-mini"], index=0)
                    ai_key_input = st.text_input("API Key (เว้นว่างเพื่อใช้ Local OCR / Rule-based)", value=st.session_state.get("ai_api_key", ""), type="password")
                    if ai_key_input:
                        st.session_state["ai_api_key"] = ai_key_input
                    st.caption("💡 ใส่ Gemini API Key เพื่อให้ระบบอ่านลายมือเกษียนสั่งการและตรายางได้แม่นยำ 100%")
                    if st.button("🔄 รัน OCR ถอดข้อความใหม่อีกครั้ง", use_container_width=True):
                        with st.spinner("กำลังประมวลผล OCR อีกครั้งด้วย API Key/เครื่องมือที่ระบุ..."):
                            re_ctx = extract_source_document(str(saved_path), api_key=st.session_state.get("ai_api_key"))
                            st.session_state.source_context = re_ctx
                            st.rerun()

                if st.button("🚀 ให้ AI ยกร่างหนังสือตามต้นเรื่องนี้", type="primary", use_container_width=True):
                    ctx = st.session_state.source_context
                    if not ctx or ctx.extraction_failed or not (ctx.raw_text or "").strip():
                        st.error("⚠️ ไม่สามารถยกร่างหนังสือได้ เนื่องจากไม่มีข้อความต้นเรื่องที่อ่านได้ กรุณาใส่ API Key หรือกรอกข้อความด้วยตนเองก่อน")
                    else:
                        with st.spinner("AI กำลังวิเคราะห์และยกร่างโครงสร้างตามระเบียบ..."):
                            prov = "openai" if "OpenAI" in ai_prov else "gemini"
                            key = st.session_state.get("ai_api_key")
                            if key:
                                draft = draft_from_context_llm(ctx, doc_type=target_doc_type, intent=intent_choice[0], provider=prov, api_key=key)
                            else:
                                draft = draft_from_context_rule_based(ctx, doc_type=target_doc_type, intent=intent_choice[0])
                            st.session_state.doc_data = draft
                            st.session_state.initial_ai_draft = draft.model_copy(deep=True)
                            audit_mgr.save_version(
                                doc_id=draft.doc_number,
                                doc=draft,
                                author=f"AI Studio ({prov.upper() if key else 'Rule-based'})",
                                note=f"ร่างเริ่มต้นจากเอกสารต้นเรื่อง ({intent_choice[1]})"
                            )
                            st.success("ยกร่างหนังสือสำเร็จ! ตรวจสอบได้ที่หน้ากระดาษฝั่งขวา")
                            st.rerun()
        else:
            # โหมดเลือกจากแม่แบบมาตรฐาน
            st.subheader("📋 แม่แบบหนังสือราชการมาตรฐาน")
            st.caption("แบบฟอร์มสำเร็จรูปตามระเบียบงานสารบรรณ พ.ศ. ๒๕๒๖ พร้อมใช้งานได้ทันที")
            
            categories = sorted(list(set(tmpl.category for tmpl in PRESET_TEMPLATES.values())))
            selected_cat = st.selectbox("หมวดหมู่แบบฟอร์ม:", ["ทั้งหมด"] + categories)

            filtered_templates = {
                k: v for k, v in PRESET_TEMPLATES.items() 
                if selected_cat == "ทั้งหมด" or v.category == selected_cat
            }

            selected_t_id = st.selectbox(
                "เลือกแบบฟอร์มที่ต้องการ:",
                options=list(filtered_templates.keys()),
                format_func=lambda x: filtered_templates[x].title
            )

            curr_tmpl = PRESET_TEMPLATES[selected_t_id]
            st.info(
                f"• **ชื่อแบบฟอร์ม:** {curr_tmpl.title}\n\n"
                f"• **หมวดหมู่:** {curr_tmpl.category}\n\n"
                f"• **ประเภท:** {'หนังสือภายนอก' if curr_tmpl.doc_type == DocType.EXTERNAL else 'หนังสือภายใน (บันทึกข้อความ)'}\n\n"
                f"• **เรื่อง:** {curr_tmpl.schema.subject}"
            )

            if st.button("📋 โหลดแบบฟอร์มนี้สู่หน้ากระดาษ", type="primary", use_container_width=True):
                st.session_state.doc_data = curr_tmpl.schema.model_copy(deep=True)
                st.session_state.initial_ai_draft = curr_tmpl.schema.model_copy(deep=True)
                audit_mgr.save_version(
                    doc_id=curr_tmpl.schema.doc_number,
                    doc=curr_tmpl.schema,
                    author="Preset Template",
                    note=f"โหลดจากแบบฟอร์มมาตรฐาน: {curr_tmpl.title}"
                )
                st.success(f"โหลดแบบฟอร์ม '{curr_tmpl.title}' เรียบร้อยแล้ว!")
                st.rerun()

        # แสดงผลข้อมูลที่สกัดได้
        if st.session_state.source_context:
            ctx = st.session_state.source_context
            st.markdown("---")
            st.markdown("##### 🔍 ข้อมูลสกัดจากเอกสารต้นเรื่อง")
            if ctx.extraction_failed:
                st.warning(f"⚠️ สถานะ: ไม่สามารถถอดข้อความอัตโนมัติ ({ctx.extraction_error})")
            else:
                eng_info = f" • เครื่องมือที่ใช้: **{ctx.ocr_engine_used}**\n\n" if ctx.ocr_engine_used else ""
                st.info(
                    f"• **ไฟล์:** {ctx.source_filename} ({'สแกน' if ctx.is_scanned else 'ดิจิทัล'})\n\n"
                    f"{eng_info}"
                    f"• **หน่วยงานเดิม:** {ctx.source_dept or 'ไม่ระบุ'}\n\n"
                    f"• **เลขที่เดิม:** {ctx.source_doc_no or 'ไม่ระบุ'} | **วันที่เดิม:** {ctx.source_date or 'ไม่ระบุ'}\n\n"
                    f"• **เรื่องเดิม:** {ctx.source_subject or '(ไม่ระบุ/รอการยืนยัน)'}"
                )

                if getattr(ctx, "source_case", None):
                    case = ctx.source_case
                    if len(case.items) > 1:
                        st.markdown("📑 **เอกสารในแฟ้มเรื่อง:**")
                        for it in case.items:
                            status_badge = " (ส่งมาแทนฉบับเดิม)" if it.replaces_item_id else ""
                            st.caption(f"• {it.doc_no or 'ไม่ระบุเลข'} ({it.doc_date or 'ไม่ระบุวัน'}){status_badge}")
                    if case.routing_notes:
                        st.markdown("✍️ **บันทึกเกษียนสั่งการ (Chain of Command):**")
                        for rn in case.routing_notes:
                            st.caption(f"• **{rn.target or 'คำสั่ง'}:** {rn.order_text[:80]}... — *{rn.author}*")
                    if case.requested_items:
                        st.markdown("🎯 **ประเด็นคำขอที่ประมวลได้:**")
                        for req in case.requested_items[:3]:
                            st.caption(f"• {req}")

            if ctx.preview_image_path and os.path.exists(ctx.preview_image_path):
                st.image(ctx.preview_image_path, caption=f"ตัวอย่างเอกสารต้นเรื่อง: {ctx.source_filename}", use_container_width=True)

            if ctx.raw_text:
                with st.expander("📄 ดูข้อความที่สกัดได้ทั้งหมด", expanded=False):
                    st.text_area("Extracted Text", ctx.raw_text, height=160, disabled=True, label_visibility="collapsed")
        else:
            st.info("💡 สามารถทดลองใช้งานด้วยข้อมูลตัวอย่าง หรือแนบไฟล์จริง (.pdf, .docx, .txt, .png)")

        # กล่อง Copilot สั่งการด้วยภาษาธรรมชาติ
        st.markdown("---")
        st.markdown("##### 💬 AI Copilot สั่งเกลาข้อความเพิ่มเติม")
        c_prompt = st.text_input("พิมพ์คำสั่ง เช่น 'ปรับให้เป็นทางการยิ่งขึ้น', 'ขอให้อ้างระเบียบพัสดุ'", "", label_visibility="collapsed", placeholder="พิมพ์คำสั่งให้ AI ช่วย เช่น ปรับให้กระชับ, อ้างระเบียบ...")
        if st.button("✨ ส่งคำสั่งให้ AI ดำเนินการ", use_container_width=True) and c_prompt:
            if "เป็นทางการ" in c_prompt or "สุภาพ" in c_prompt:
                st.session_state.doc_data.paragraph_reason = make_formal_tone(st.session_state.doc_data.paragraph_reason)
                st.session_state.doc_data.paragraph_purpose = make_formal_tone(st.session_state.doc_data.paragraph_purpose)
                st.success("ปรับสำนวนให้เป็นทางการเรียบร้อยแล้ว")
                st.rerun()
            elif "กระชับ" in c_prompt or "ย่อ" in c_prompt:
                if st.session_state.doc_data.paragraph_details:
                    st.session_state.doc_data.paragraph_details = make_concise(st.session_state.doc_data.paragraph_details)
                st.success("ย่อเนื้อความให้กระชับเรียบร้อยแล้ว")
                st.rerun()
            elif "พัสดุ" in c_prompt or "ระเบียบ" in c_prompt:
                st.session_state.doc_data = insert_legal_reference(st.session_state.doc_data, "procurement" if "พัสดุ" in c_prompt else "saraban")
                st.success("แทรกข้อกฎหมายเรียบร้อยแล้ว")
                st.rerun()
            else:
                st.info("AI ได้รับคำสั่งแล้ว: สามารถใช้ปุ่มลัดด้านล่างหรือเกลาข้อความในแบบฟอร์มได้ทันที")

    # ----------------- คอลัมน์ขวา: Interactive Canvas, Live Preview และ Editor -----------------
    with col_right:
        doc = st.session_state.doc_data
        placeholder_count = doc.count_placeholders()

        # Header Status Bar แสดงสถานะ
        status_left, status_right = st.columns([1.5, 1])
        with status_left:
            doc_type_name = "หนังสือภายนอก" if doc.doc_type == DocType.EXTERNAL else "บันทึกข้อความ (หนังสือภายใน)"
            st.markdown(
                f'<span class="status-pill status-pill-info">📄 {doc_type_name}</span>'
                f'<span class="status-pill status-pill-info">{doc.urgency.to_thai()}</span>',
                unsafe_allow_html=True
            )
        with status_right:
            if placeholder_count > 0:
                st.markdown(
                    f'<div style="text-align: right;"><span class="status-pill status-pill-warning">⚠️ มี {placeholder_count} จุดที่ต้องระบุ</span></div>',
                    unsafe_allow_html=True
                )
            else:
                st.markdown(
                    '<div style="text-align: right;"><span class="status-pill status-pill-ready">✅ พร้อมตรวจและส่งออก</span></div>',
                    unsafe_allow_html=True
                )

        tab_preview, tab_editor, tab_diff = st.tabs([
            "👁️ Live A4 Preview & ส่งออก", 
            "✏️ ฟอร์มแก้ไขข้อความ", 
            "📊 ประวัติและการแก้ไข (Diff)"
        ])

        # ----------------- TAB PREVIEW & QUICK ACTIONS -----------------
        with tab_preview:
            # ตัวเลือกการส่งออก Word (ฟอนต์ / ระยะตัวอักษร / ตราครุฑ / การฝังฟอนต์)
            if "export_options" not in st.session_state:
                st.session_state.export_options = ExportOptions()
            _eo = st.session_state.export_options
            with st.expander("⚙️ ตัวเลือกการส่งออก Word (ฟอนต์ / ระยะตัวอักษร / ตราครุฑ)", expanded=False):
                oc1, oc2, oc3 = st.columns(3)
                with oc1:
                    _font = st.selectbox(
                        "ฟอนต์",
                        options=["psk", "sarabun_new"],
                        index=0 if _eo.export_font == "psk" else 1,
                        format_func=lambda v: "TH Sarabun PSK (แนะนำ)" if v == "psk" else "TH Sarabun New",
                        key="exp_font",
                    )
                with oc2:
                    _letterhead = st.selectbox(
                        "ตราครุฑ",
                        options=["garuda", "none"],
                        index=0 if _eo.letterhead == "garuda" else 1,
                        format_func=lambda v: "แสดงตราครุฑ" if v == "garuda" else "ไม่แสดงตราครุฑ",
                        key="exp_letterhead",
                    )
                with oc3:
                    _divider = st.selectbox(
                        "เส้นคั่นใต้ส่วนหัว",
                        options=["none", "line"],
                        index=0 if _eo.divider == "none" else 1,
                        format_func=lambda v: "ไม่มี" if v == "none" else "มีเส้นคั่น",
                        key="exp_divider",
                    )
                oc4, oc5 = st.columns([1, 2])
                with oc4:
                    _spacing = st.number_input(
                        "ระยะห่างตัวอักษร (pt)",
                        min_value=0.0,
                        max_value=2.0,
                        value=float(_eo.letter_spacing_pt),
                        step=0.1,
                        key="exp_spacing",
                    )
                with oc5:
                    _embed = st.checkbox(
                        "ฝังฟอนต์ในไฟล์ Word (เปิดบนเครื่องอื่นแล้วหน้าตาไม่เพี้ยน)",
                        value=bool(_eo.embed_fonts),
                        key="exp_embed",
                    )
                st.session_state.export_options = ExportOptions(
                    export_font=_font,
                    letterhead=_letterhead,
                    divider=_divider,
                    letter_spacing_pt=float(_spacing),
                    embed_fonts=_embed,
                )
                st.caption("ค่าเริ่มต้น: TH Sarabun PSK, ระยะตัวอักษร 0.4 pt, ฝังฟอนต์ — ปรับได้ตามนโยบายหน่วยงาน")

            # 1-Click Action Toolbar ปรับปุ่มให้กะทัดรัด สวยงาม สไตล์โมเดิร์น
            t1, t2, t3, t4, t5 = st.columns([1.05, 1.15, 1.15, 1.1, 1.15], gap="small")
            with t1:
                if st.button("🔢 เลขไทย/อารบิก", use_container_width=True, help="สลับระหว่างเลขไทยและเลขอารบิกทั้งฉบับ"):
                    new_val = not st.session_state.doc_data.use_thai_numerals
                    st.session_state.doc_data = toggle_doc_numerals(st.session_state.doc_data, use_thai=new_val)
                    st.rerun()
            with t2:
                try:
                    pdf_bytes = get_pdf_bytes(st.session_state.doc_data)
                    st.download_button(
                        label="📥 ดาวน์โหลด PDF",
                        data=pdf_bytes,
                        file_name=f"{st.session_state.doc_data.subject[:30].replace('/', '_')}.pdf",
                        mime="application/pdf",
                        use_container_width=True
                    )
                except Exception as _pdf_err:
                    st.button(f"⚠️ PDF ({str(_pdf_err)[:10]})", disabled=True, use_container_width=True)
            with t3:
                docx_bytes = get_docx_bytes(st.session_state.doc_data, st.session_state.export_options)
                st.download_button(
                    label="📥 ดาวน์โหลด Word",
                    data=docx_bytes,
                    file_name=f"{st.session_state.doc_data.subject[:30].replace('/', '_')}.docx",
                    mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    use_container_width=True
                )
            with t4:
                typst_bytes = get_typst_bytes(st.session_state.doc_data)
                st.download_button(
                    label="📄 ดาวน์โหลด Typst",
                    data=typst_bytes,
                    file_name=f"{st.session_state.doc_data.subject[:30].replace('/', '_')}.typ",
                    mime="text/plain",
                    use_container_width=True
                )
            with t5:
                if st.button("📚 บันทึกทะเบียนส่ง", use_container_width=True):
                    rec = OutgoingRecord(
                        doc_number=st.session_state.doc_data.doc_number,
                        doc_type=st.session_state.doc_data.doc_type.value,
                        subject=st.session_state.doc_data.subject,
                        recipient=st.session_state.doc_data.salutation.replace("เรียน", "").strip(),
                        doc_date=st.session_state.doc_data.doc_date,
                        status="sent"
                    )
                    try:
                        new_id = registry.register_outgoing(rec)
                        audit_mgr.log_action(st.session_state.doc_data.doc_number, "register_outgoing", "ผู้ใช้", {"registry_id": new_id})
                        st.success(f"บันทึกสำเร็จ (รหัสทะเบียน: {new_id})")
                    except Exception as e:
                        st.error(f"ไม่สามารถลงทะเบียนได้: {str(e)}")

            # ----------------- แถบปุ่มดินสอแก้ไขด่วนตามหัวข้อต่าง ๆ -----------------
            doc = st.session_state.doc_data
            st.markdown("""
            <div style="display: flex; align-items: center; justify-content: space-between; margin-top: 10px; margin-bottom: 4px;">
                <span style="font-size: 0.82rem; font-weight: 600; color: #1e293b;">✏️ คลิกปุ่มดินสอเพื่อแก้ไขเนื้อหาตามหัวข้อ:</span>
            </div>
            """, unsafe_allow_html=True)

            if doc.doc_type == DocType.INTERNAL:
                e1, e2, e3, e4, e5, e6 = st.columns(6, gap="small")
                with e1:
                    if st.button("✏️ หัวหนังสือ", key="btn_dlg_header", use_container_width=True, help="แก้ไข ส่วนราชการ, ที่, วันที่, เรื่อง, เรียน"):
                        edit_header_dialog()
                with e2:
                    if st.button("✏️ ๑. ต้นเรื่อง", key="btn_dlg_intro", use_container_width=True, help="แก้ไขเนื้อความ ๑. ต้นเรื่อง"):
                        edit_intro_dialog()
                with e3:
                    if st.button("✏️ ๒. ข้อเท็จจริง", key="btn_dlg_facts", use_container_width=True, help="แก้ไขเนื้อความ ๒. ข้อเท็จจริง"):
                        edit_facts_dialog()
                with e4:
                    if st.button("✏️ ๓. ข้อกฎหมาย", key="btn_dlg_law", use_container_width=True, help="แก้ไขหรือแทรกข้อกฎหมาย/ระเบียบ"):
                        edit_law_dialog()
                with e5:
                    if st.button("✏️ ๔. ข้อพิจารณา", key="btn_dlg_consideration", use_container_width=True, help="แก้ไข ๔. ข้อพิจารณาและเสนอแนะ"):
                        edit_consideration_dialog()
                with e6:
                    if st.button("✏️ ผู้ลงนาม", key="btn_dlg_signatory", use_container_width=True, help="แก้ไขชื่อ ตำแหน่ง และลายมือชื่อ"):
                        edit_signatory_dialog()
            else:
                e1, e2, e3, e4, e5, e6 = st.columns(6, gap="small")
                with e1:
                    if st.button("✏️ หัวหนังสือ", key="btn_dlg_ext_header", use_container_width=True):
                        edit_header_dialog()
                with e2:
                    if st.button("✏️ ภาคเหตุ", key="btn_dlg_ext_reason", use_container_width=True):
                        edit_intro_dialog()
                with e3:
                    if st.button("✏️ ภาคข้อเท็จจริง", key="btn_dlg_ext_details", use_container_width=True):
                        edit_facts_dialog()
                with e4:
                    if st.button("✏️ ภาคประสงค์", key="btn_dlg_ext_purpose", use_container_width=True):
                        edit_consideration_dialog()
                with e5:
                    if st.button("✏️ ผู้ลงนาม", key="btn_dlg_ext_sig", use_container_width=True):
                        edit_signatory_dialog()
                with e6:
                    if st.button("✏️ ข้อมูลติดต่อ", key="btn_dlg_ext_contact", use_container_width=True):
                        edit_contact_dialog()

            # แจ้งเตือนจุดที่ต้องระบุข้อมูล พร้อมปุ่มเติมข้อมูลทันที
            active_placeholders = doc.find_placeholders()
            if active_placeholders:
                p_col1, p_col2 = st.columns([3, 1.2], gap="small")
                with p_col1:
                    st.warning(f"⚠️ พบ {len(active_placeholders)} จุดที่ต้องระบุข้อมูลในเอกสาร (เช่น {active_placeholders[0][1]})")
                with p_col2:
                    if st.button("✏️ เติมข้อมูลจุดนี้ทันที", key="btn_quick_fill_phs", type="primary", use_container_width=True):
                        edit_placeholders_dialog()

            # เตรียมข้อความสำหรับแสดงผลพร้อม Smart Placeholder Chips
            doc = st.session_state.doc_data
            disp_date = highlight_placeholders_html(to_thai_numerals(doc.doc_date) if doc.use_thai_numerals else doc.doc_date)
            disp_no = highlight_placeholders_html(to_thai_numerals(doc.doc_number) if doc.use_thai_numerals else doc.doc_number)
            disp_dept = highlight_placeholders_html(doc.dept_name)

            # จัดการชื่อเรื่องและคำขึ้นต้น ไม่ให้มีคำซ้ำ เช่น "เรียน เรียน" หรือ "เรื่อง เรื่อง"
            clean_sub = re.sub(r'^เรื่อง\s*', '', doc.subject).strip()
            disp_subject = highlight_placeholders_html(clean_sub)

            raw_sal = doc.salutation.strip()
            clean_sal = re.sub(r'^(?:กราบเรียน|เรียน)\s*', '', raw_sal).strip()
            is_high_off = raw_sal.startswith("กราบเรียน")
            sal_label = "กราบเรียน" if is_high_off else "เรียน"
            disp_sal_body = highlight_placeholders_html(clean_sal)

            disp_reason = highlight_placeholders_html(to_thai_numerals(doc.paragraph_reason) if doc.use_thai_numerals else doc.paragraph_reason)
            disp_details = highlight_placeholders_html(to_thai_numerals(doc.paragraph_details) if (doc.paragraph_details and doc.use_thai_numerals) else (doc.paragraph_details or ""))
            disp_purpose = highlight_placeholders_html(to_thai_numerals(doc.paragraph_purpose) if doc.use_thai_numerals else doc.paragraph_purpose)
            disp_closing = highlight_placeholders_html(doc.closing)
            disp_sig_name = highlight_placeholders_html(doc.signatory_name)
            disp_sig_pos = highlight_placeholders_html(doc.signatory_position)

            sig_preview_html = '<div style="height: 42px;"></div>'
            if getattr(doc, "signature_image_path", None) and os.path.exists(doc.signature_image_path):
                with open(doc.signature_image_path, "rb") as f_sig:
                    sig_b64 = base64.b64encode(f_sig.read()).decode("utf-8")
                sig_preview_html = f'<div style="text-align: center; margin: 4px 0;"><img src="data:image/png;base64,{sig_b64}" style="height: 38px; width: auto;" alt="ลายมือชื่อ" /></div>'

            # สร้าง HTML เนื้อความบันทึกข้อความ (ใช้ตัวจัดหน้าเดียวกับ Word/PDF — core.memo_layout)
            if not hasattr(doc, "get_memo_blocks"):
                doc = GovDocumentSchema.model_validate(doc.model_dump())
                st.session_state.doc_data = doc
            _num = to_thai_numerals if doc.use_thai_numerals else (lambda t: t)
            rendered_memo_body = render_memo_blocks_html(
                doc.get_memo_blocks(),
                transform=lambda t: highlight_placeholders_html(_num(t)),
                indent_scale=0.88,  # พรีวิวย่อสัดส่วน A4 (เช่นเดียวกับ .a4-indent 2.2 ซม.)
            )

            # เรนเดอร์ส่วนอ้างถึงและสิ่งที่ส่งมาด้วย (ถ้ามี)
            refs_html = ""
            if doc.references:
                ref_items = []
                for idx, r in enumerate(doc.references):
                    h_val = highlight_placeholders_html(to_thai_numerals(r) if doc.use_thai_numerals else r)
                    if idx == 0:
                        ref_items.append(f"<p><strong>อ้างถึง</strong>  {h_val}</p>")
                    else:
                        ref_items.append(f'<p style="margin-left: 1.4cm;">{h_val}</p>')
                refs_html = "".join(ref_items)

            atts_html = ""
            if doc.attachments:
                att_items = []
                for idx, a in enumerate(doc.attachments):
                    h_val = highlight_placeholders_html(to_thai_numerals(a) if doc.use_thai_numerals else a)
                    if idx == 0:
                        att_items.append(f"<p><strong>สิ่งที่ส่งมาด้วย</strong>  {h_val}</p>")
                    else:
                        att_items.append(f'<p style="margin-left: 2.2cm;">{h_val}</p>')
                atts_html = "".join(att_items)

            # HTML A4 Preview Template (Scaled for clean on-screen reading)
            if doc.doc_type == DocType.EXTERNAL:
                st.markdown(f"""
                <div class="a4-paper">
                    <div style="text-align: center; margin-bottom: 12px;">
                        <img src="data:{garuda_mime};base64,{garuda_b64}" style="height: 3.0cm; width: auto; display: inline-block;" alt="ตราครุฑ 3 ซม." />
                    </div>
                    <div style="display: flex; justify-content: space-between; margin-bottom: 6px; font-size: 14.5px;">
                        <div style="width: 48%;"><strong>ที่</strong>  {disp_no}</div>
                        <div style="width: 48%; text-align: left;">{disp_dept}</div>
                    </div>
                    <div style="text-align: center; margin-left: 20%; margin-bottom: 12px; font-size: 14.5px;">
                        {disp_date}
                    </div>
                    <div style="margin-bottom: 12px; font-size: 14.5px;">
                        <p><strong>เรื่อง</strong>  {disp_subject}</p>
                        <p><strong>{sal_label}</strong>  {disp_sal_body}</p>
                        {refs_html}
                        {atts_html}
                    </div>
                    <p class="a4-indent">{disp_reason}</p>
                    {f'<p class="a4-indent">{disp_details}</p>' if disp_details else ''}
                    <p class="a4-indent">{disp_purpose}</p>
                    <div style="text-align: center; margin-left: 45%; margin-top: 28px; margin-bottom: 24px; font-size: 14.5px;">
                        <p>{disp_closing}</p>
                        {sig_preview_html}
                        <p>{disp_sig_name}</p>
                        <p>{disp_sig_pos}</p>
                    </div>
                    <div style="font-size: 12.5px !important; margin-top: 24px; color: #334155; line-height: 1.4;">
                        <p style="margin: 0; font-size: 12.5px !important;">{highlight_placeholders_html(doc.contact_dept or '')}</p>
                        <p style="margin: 0; font-size: 12.5px !important;">โทรศัพท์  {highlight_placeholders_html(doc.contact_tel or '')}</p>
                        <p style="margin: 0; font-size: 12.5px !important;">ไปรษณีย์อิเล็กทรอนิกส์  {highlight_placeholders_html(doc.contact_email or '')}</p>
                    </div>
                </div>
                """, unsafe_allow_html=True)
            else:
                dept_tel_str = f"  โทร. {highlight_placeholders_html(doc.contact_tel)}" if (doc.contact_tel and doc.contact_tel not in doc.dept_name) else ""
                st.markdown(f"""
                <div class="a4-paper">
                    <div style="display: flex; align-items: flex-start; margin-bottom: 12px;">
                        <img src="data:{garuda_mime};base64,{garuda_b64}" style="height: 1.5cm; width: auto; margin-right: 18px;" alt="ตราครุฑ 1.5 ซม." />
                        <div style="font-size: 26px; font-weight: bold; text-align: center; width: 85%; font-family: 'TH Sarabun New', 'Sarabun', sans-serif;">บันทึกข้อความ</div>
                    </div>
                    <div style="margin-bottom: 10px; font-size: 14.5px;">
                        <div class="memo-field"><span class="memo-label">ส่วนราชการ</span><span class="memo-value">{disp_dept}{dept_tel_str}</span></div>
                        <div class="memo-field">
                            <span class="memo-label">ที่</span><span class="memo-value" style="flex: 0 0 42%;">{disp_no}</span>
                            <span class="memo-label" style="margin-left: 8px;">วันที่</span><span class="memo-value">{disp_date}</span>
                        </div>
                        <div class="memo-field"><span class="memo-label">เรื่อง</span><span class="memo-value">{disp_subject}</span></div>
                        <p style="margin-top: 6px;">{sal_label}  {disp_sal_body}</p>
                        {refs_html}
                        {atts_html}
                    </div>
                    {rendered_memo_body}
                    <div style="text-align: center; margin-left: 45%; margin-top: 35px; font-size: 14.5px;">
                        {sig_preview_html}
                        <p>{disp_sig_name}</p>
                        <p>{disp_sig_pos}</p>
                    </div>
                </div>
                """, unsafe_allow_html=True)

            # ----------------- กล่องแก้ไขเนื้อหาและเกลาภาษาตามหัวข้อโดยตรง -----------------
            st.markdown("##### ✏️ แก้ไขเนื้อหาและเกลาภาษาตามหัวข้อโดยตรง")
            if doc.doc_type == DocType.INTERNAL:
                sec_tabs = st.tabs(["๑. ต้นเรื่อง (จำเป็น)", "๒. ข้อเท็จจริง (จำเป็น)", "๓. ข้อกฎหมาย (ถ้ามี)", "๔. ข้อพิจารณาและเสนอแนะ (จำเป็น)", "๕. ประโยคลงท้ายตามระดับชั้น", "✍️ ผู้ลงนาม"])
                with sec_tabs[0]:
                    new_intro = st.text_area("เนื้อความ ๑. ต้นเรื่อง (จำเป็น):", value=doc.memo_intro or doc.paragraph_reason or "", height=95, key="dir_intro")
                    col_b1, col_b2, col_b3 = st.columns([1.2, 1.2, 1])
                    with col_b1:
                        if st.button("✍️ ปรับให้เป็นทางการ", key="dir_b_intro_f", use_container_width=True):
                            doc.memo_intro = make_formal_tone(new_intro)
                            doc.paragraph_reason = doc.memo_intro
                            st.session_state.doc_data = doc
                            st.rerun()
                    with col_b2:
                        if st.button("✂️ ย่อให้กระชับ", key="dir_b_intro_c", use_container_width=True):
                            doc.memo_intro = make_concise(new_intro)
                            doc.paragraph_reason = doc.memo_intro
                            st.session_state.doc_data = doc
                            st.rerun()
                    with col_b3:
                        if st.button("💾 บันทึก", key="dir_b_intro_s", type="primary", use_container_width=True):
                            doc.memo_intro = new_intro.strip()
                            doc.paragraph_reason = doc.memo_intro
                            st.session_state.doc_data = doc
                            st.success("บันทึกต้นเรื่องสำเร็จ")
                            st.rerun()

                with sec_tabs[1]:
                    new_facts = st.text_area("เนื้อความ ๒. ข้อเท็จจริง (จำเป็น):", value=doc.memo_facts or doc.paragraph_details or "", height=95, key="dir_facts")
                    col_b1, col_b2, col_b3 = st.columns([1.2, 1.2, 1])
                    with col_b1:
                        if st.button("✍️ ปรับให้เป็นทางการ", key="dir_b_facts_f", use_container_width=True):
                            doc.memo_facts = make_formal_tone(new_facts)
                            doc.paragraph_details = doc.memo_facts
                            st.session_state.doc_data = doc
                            st.rerun()
                    with col_b2:
                        if st.button("✂️ ย่อให้กระชับ", key="dir_b_facts_c", use_container_width=True):
                            doc.memo_facts = make_concise(new_facts)
                            doc.paragraph_details = doc.memo_facts
                            st.session_state.doc_data = doc
                            st.rerun()
                    with col_b3:
                        if st.button("💾 บันทึก", key="dir_b_facts_s", type="primary", use_container_width=True):
                            doc.memo_facts = new_facts.strip()
                            doc.paragraph_details = doc.memo_facts
                            st.session_state.doc_data = doc
                            st.success("บันทึกข้อเท็จจริงสำเร็จ")
                            st.rerun()

                with sec_tabs[2]:
                    new_law = st.text_area("เนื้อความ ๓. ข้อกฎหมาย (ถ้ามี — สามารถเว้นว่างได้):", value=doc.memo_law or "", height=95, key="dir_law")
                    col_b1, col_b2, col_b3 = st.columns([1.2, 1.2, 1])
                    with col_b1:
                        if st.button("🏛️ แทรกระเบียบ กทม.", key="dir_b_law_bma", use_container_width=True):
                            doc.memo_law = "ตามระเบียบกรุงเทพมหานครว่าด้วยการใช้ตราเครื่องหมายราชการของกรุงเทพมหานคร พ.ศ. ๒๕๓๓ ข้อ ๖ และระเบียบกรุงเทพมหานครว่าด้วยการใช้สถานที่ของกรุงเทพมหานคร พ.ศ. ๒๕๓๖"
                            st.session_state.doc_data = doc
                            st.rerun()
                    with col_b2:
                        if st.button("🗑️ ลบ/ไม่ระบุกฎหมาย", key="dir_b_law_clear", use_container_width=True):
                            doc.memo_law = None
                            st.session_state.doc_data = doc
                            st.rerun()
                    with col_b3:
                        if st.button("💾 บันทึก", key="dir_b_law_s", type="primary", use_container_width=True):
                            doc.memo_law = new_law.strip() if new_law.strip() else None
                            st.session_state.doc_data = doc
                            st.success("บันทึกข้อกฎหมายสำเร็จ")
                            st.rerun()

                with sec_tabs[3]:
                    new_cons = st.text_area("เนื้อความ ๔. ข้อพิจารณาและเสนอแนะ (จำเป็น):", value=doc.memo_consideration or doc.paragraph_purpose or "", height=95, key="dir_cons")
                    col_b1, col_b2, col_b3 = st.columns([1.2, 1.2, 1])
                    with col_b1:
                        if st.button("✍️ ปรับให้เป็นทางการ", key="dir_b_cons_f", use_container_width=True):
                            doc.memo_consideration = make_formal_tone(new_cons)
                            doc.paragraph_purpose = doc.memo_consideration
                            st.session_state.doc_data = doc
                            st.rerun()
                    with col_b2:
                        if st.button("📌 ใส่ข้อเสนอเห็นชอบ", key="dir_b_cons_prop", use_container_width=True):
                            if "จึงเรียนมาเพื่อโปรด" not in new_cons:
                                new_cons = new_cons.rstrip() + "\n\nจึงเรียนมาเพื่อโปรดพิจารณา หากเห็นชอบโปรดลงนามในหนังสือที่แนบมาพร้อมนี้"
                            doc.memo_consideration = new_cons
                            doc.paragraph_purpose = doc.memo_consideration
                            st.session_state.doc_data = doc
                            st.rerun()
                    with col_b3:
                        if st.button("💾 บันทึก", key="dir_b_cons_s", type="primary", use_container_width=True):
                            doc.memo_consideration = new_cons.strip()
                            doc.paragraph_purpose = doc.memo_consideration
                            st.session_state.doc_data = doc
                            st.success("บันทึกข้อพิจารณาและเสนอแนะสำเร็จ")
                            st.rerun()

                with sec_tabs[4]:
                    st.caption("ประโยคลงท้ายเสนอผู้บังคับบัญชาตามระดับชั้น (เกษียนหนังสือ)")
                    current_req = doc.memo_request or (split_consideration_and_request(doc.memo_consideration or "", doc.memo_request)[1]) or "จึงเรียนมาเพื่อโปรดพิจารณา"
                    new_req = st.text_area("ข้อความประโยคลงท้าย:", value=current_req, height=85, key="dir_req")
                    st.markdown("###### 🏛️ เลือกประโยคลงท้ายสำเร็จรูปตามระดับชั้น:")
                    rcl1, rcl2 = st.columns(2)
                    with rcl1:
                        if st.button("📁 ระดับกลุ่มงาน (เสนอ ผอ.กอง)", key="dir_b_req_sec", use_container_width=True):
                            doc.memo_request = "จึงเรียนมาเพื่อโปรดพิจารณานำเรียนผู้อำนวยการกองการกีฬาลงนามในหนังสือที่แนบ"
                            doc.memo_hierarchy_level = MemoHierarchyLevel.SECTION_TO_DIV
                            st.session_state.doc_data = doc
                            st.rerun()
                        if st.button("🏛️ ระดับสำนัก (เสนอ ปลัด นำเรียนผู้ว่าฯ)", key="dir_b_req_dept", use_container_width=True):
                            doc.memo_request = "จึงเรียนมาเพื่อโปรดพิจารณา หากเห็นชอบโปรดนำเรียนผู้ว่าราชการกรุงเทพมหานคร เพื่อโปรดพิจารณาให้ความเห็นชอบและสั่งการตามที่เสนอข้างต้น"
                            doc.memo_hierarchy_level = MemoHierarchyLevel.DEPT_TO_PERM_SEC
                            st.session_state.doc_data = doc
                            st.rerun()
                    with rcl2:
                        if st.button("🏢 ระดับกอง (เสนอ ผอ.สำนัก)", key="dir_b_req_div", use_container_width=True):
                            doc.memo_request = "จึงเรียนมาเพื่อโปรดพิจารณาลงนามหนังสือเรียนปลัดกรุงเทพมหานครที่แนบ"
                            doc.memo_hierarchy_level = MemoHierarchyLevel.DIV_TO_DEPT
                            st.session_state.doc_data = doc
                            st.rerun()
                        if st.button("✍️ เสนอผู้มีอำนาจสั่งการ (อนุมัติ/ลงนาม)", key="dir_b_req_appr", use_container_width=True):
                            doc.memo_request = "จึงเรียนมาเพื่อโปรดพิจารณา หากเห็นชอบโปรดลงนามในหนังสือที่แนบมาพร้อมนี้"
                            doc.memo_hierarchy_level = MemoHierarchyLevel.FINAL_APPROVAL
                            st.session_state.doc_data = doc
                            st.rerun()
                    if st.button("💾 บันทึกประโยคลงท้าย", key="dir_b_req_save", type="primary", use_container_width=True):
                        doc.memo_request = new_req.strip()
                        st.session_state.doc_data = doc
                        st.success("บันทึกประโยคลงท้ายตามระดับชั้นสำเร็จ")
                        st.rerun()

                with sec_tabs[5]:
                    col_s1, col_s2 = st.columns(2)
                    with col_s1:
                        new_sname = st.text_input("ชื่อเต็มผู้ลงนาม:", value=doc.signatory_name, key="dir_sname")
                    with col_s2:
                        new_spos = st.text_input("ตำแหน่งผู้ลงนาม:", value=doc.signatory_position, key="dir_spos")
                    if st.button("💾 บันทึกผู้ลงนาม", key="dir_sig_save", type="primary", use_container_width=True):
                        doc.signatory_name = new_sname.strip()
                        doc.signatory_position = new_spos.strip()
                        st.session_state.doc_data = doc
                        st.success("บันทึกข้อมูลผู้ลงนามสำเร็จ")
                        st.rerun()
            else:
                ext_tabs = st.tabs(["ภาคเหตุ", "ภาคข้อเท็จจริง", "ภาคประสงค์", "✍️ ผู้ลงนาม"])
                with ext_tabs[0]:
                    new_r = st.text_area("เนื้อความภาคเหตุ:", value=doc.paragraph_reason, height=80, key="dir_ext_r")
                    if st.button("💾 บันทึกภาคเหตุ", key="dir_b_ext_r_s", type="primary"):
                        doc.paragraph_reason = new_r.strip()
                        st.session_state.doc_data = doc
                        st.rerun()
                with ext_tabs[1]:
                    new_d = st.text_area("เนื้อความภาคข้อเท็จจริง:", value=doc.paragraph_details or "", height=80, key="dir_ext_d")
                    if st.button("💾 บันทึกภาคข้อเท็จจริง", key="dir_b_ext_d_s", type="primary"):
                        doc.paragraph_details = new_d.strip()
                        st.session_state.doc_data = doc
                        st.rerun()
                with ext_tabs[2]:
                    new_p = st.text_area("เนื้อความภาคความประสงค์:", value=doc.paragraph_purpose, height=80, key="dir_ext_p")
                    if st.button("💾 บันทึกภาคความประสงค์", key="dir_b_ext_p_s", type="primary"):
                        doc.paragraph_purpose = new_p.strip()
                        st.session_state.doc_data = doc
                        st.rerun()
                with ext_tabs[3]:
                    col_s1, col_s2 = st.columns(2)
                    with col_s1:
                        new_sn = st.text_input("ชื่อเต็มผู้ลงนาม:", value=doc.signatory_name, key="dir_ext_sn")
                    with col_s2:
                        new_sp = st.text_input("ตำแหน่งผู้ลงนาม:", value=doc.signatory_position, key="dir_ext_sp")
                    if st.button("💾 บันทึกผู้ลงนาม", key="dir_ext_sig_save", type="primary"):
                        doc.signatory_name = new_sn.strip()
                        doc.signatory_position = new_sp.strip()
                        st.session_state.doc_data = doc
                        st.rerun()

        # ----------------- TAB DETAILED EDITOR -----------------
        with tab_editor:
            c1, c2, c3, c4 = st.columns(4)
            with c1:
                new_type = st.selectbox(
                    "ประเภทหนังสือ",
                    options=[DocType.EXTERNAL, DocType.INTERNAL],
                    format_func=lambda x: "หนังสือภายนอก" if x == DocType.EXTERNAL else "หนังสือภายใน (บันทึกข้อความ)",
                    index=0 if st.session_state.doc_data.doc_type == DocType.EXTERNAL else 1
                )
                if new_type != st.session_state.doc_data.doc_type:
                    st.session_state.doc_data = convert_doc_type(st.session_state.doc_data, new_type)
                    st.rerun()

            with c2:
                st.session_state.doc_data.urgency = st.selectbox(
                    "ชั้นความเร็ว",
                    options=[UrgencyLevel.NORMAL, UrgencyLevel.URGENT, UrgencyLevel.VERY_URGENT, UrgencyLevel.MOST_URGENT],
                    format_func=lambda x: x.to_thai()
                )
            with c3:
                st.session_state.doc_data.secret = st.selectbox(
                    "ชั้นความลับ",
                    options=[SecretLevel.NORMAL, SecretLevel.SECRET, SecretLevel.VERY_SECRET, SecretLevel.TOP_SECRET],
                    format_func=lambda x: x.to_thai()
                )
            with c4:
                st.session_state.doc_data.use_thai_numerals = st.checkbox(
                    "แปลงเป็นเลขไทย (๐-๙)", 
                    value=st.session_state.doc_data.use_thai_numerals
                )

            if st.session_state.doc_data.doc_type == DocType.INTERNAL:
                col_hl1, col_hl2 = st.columns([2.5, 1.5])
                with col_hl1:
                    hl_opts = [
                        MemoHierarchyLevel.DEPT_TO_PERM_SEC,
                        MemoHierarchyLevel.DIV_TO_DEPT,
                        MemoHierarchyLevel.SECTION_TO_DIV,
                        MemoHierarchyLevel.FINAL_APPROVAL,
                        MemoHierarchyLevel.CUSTOM,
                    ]
                    curr_hl = getattr(st.session_state.doc_data, 'memo_hierarchy_level', MemoHierarchyLevel.DEPT_TO_PERM_SEC)
                    hl_idx = hl_opts.index(curr_hl) if curr_hl in hl_opts else 0
                    selected_hl = st.selectbox(
                        "🏢 ระดับชั้นการเสนอหนังสือ (ประโยคลงท้าย)",
                        options=hl_opts,
                        index=hl_idx,
                        format_func=lambda x: x.to_thai() if hasattr(x, 'to_thai') else str(x),
                        key="sb_memo_hierarchy_top"
                    )
                    if selected_hl != st.session_state.doc_data.memo_hierarchy_level:
                        st.session_state.doc_data.memo_hierarchy_level = selected_hl
                        if selected_hl != MemoHierarchyLevel.CUSTOM:
                            st.session_state.doc_data.memo_request = selected_hl.default_closing()
                        st.rerun()
                with col_hl2:
                    st.caption("ℹ️ ระบบจะช่วยตั้งประโยคลงท้าย 'จึงเรียนมาเพื่อ...' ให้สอดคล้องกับระดับชั้นการเสนอโดยอัตโนมัติ")

            st.markdown("##### 📌 ข้อมูลส่วนหัวหนังสือ")
            h1, h2 = st.columns([1.5, 1])
            with h1:
                col_n1, col_n2 = st.columns([2.5, 1])
                with col_n1:
                    st.session_state.doc_data.doc_number = st.text_input("ที่ (เลขที่หนังสือ)", st.session_state.doc_data.doc_number)
                with col_n2:
                    if st.button("🔢 รันเลขถัดไป", use_container_width=True, help="ดึงเลขที่หนังสือลำดับถัดไปจากระบบทะเบียนส่ง"):
                        new_no = registry.get_next_doc_number()
                        st.session_state.doc_data.doc_number = new_no
                        st.rerun()
            with h2:
                st.session_state.doc_data.doc_date = st.text_input("วันที่ (ห้ามมีคำว่าวันที่)", st.session_state.doc_data.doc_date)

            st.session_state.doc_data.dept_name = st.text_input("ส่วนราชการเจ้าของหนังสือ", st.session_state.doc_data.dept_name)
            st.session_state.doc_data.subject = st.text_input("เรื่อง", st.session_state.doc_data.subject)
            st.session_state.doc_data.salutation = st.text_input("คำขึ้นต้น (เช่น เรียน / กราบเรียน)", st.session_state.doc_data.salutation)

            st.markdown("##### 📎 เอกสารอ้างอิงและสิ่งที่ส่งมาด้วย")
            ref_col, att_col = st.columns(2)
            with ref_col:
                current_refs = "\n".join(st.session_state.doc_data.references) if st.session_state.doc_data.references else ""
                new_refs_text = st.text_area("อ้างถึง (แยก ๑ บรรทัดต่อ ๑ ฉบับ)", value=current_refs, height=65)
                st.session_state.doc_data.references = [line.strip() for line in new_refs_text.splitlines() if line.strip()] or None
            with att_col:
                current_atts = "\n".join(st.session_state.doc_data.attachments) if st.session_state.doc_data.attachments else ""
                new_atts_text = st.text_area("สิ่งที่ส่งมาด้วย (แยก ๑ บรรทัดต่อ ๑ ฉบับ)", value=current_atts, height=65)
                st.session_state.doc_data.attachments = [line.strip() for line in new_atts_text.splitlines() if line.strip()] or None

            if st.session_state.doc_data.doc_type == DocType.INTERNAL:
                st.markdown("##### 📝 เนื้อความบันทึกข้อความ (แบบบันทึกเสนอพิจารณา)")
                d = st.session_state.doc_data

                # ค่าเริ่มต้นสำหรับ memo_* (ข้อมูลเดิมที่มีเฉพาะ paragraph_*)
                if not d.memo_intro:
                    d.memo_intro = d.paragraph_reason
                if not d.memo_facts:
                    d.memo_facts = d.paragraph_details or ""
                if not d.memo_consideration and not d.memo_request:
                    d.memo_consideration, d.memo_request = split_consideration_and_request(d.paragraph_purpose, None)

                style_labels = {
                    "bma": "หัวข้อขีดเส้นใต้ (แบบ กทม.): ต้นเรื่อง → ข้อกฎหมาย → ข้อเท็จจริง → ข้อพิจารณาและเสนอแนะ",
                    "numbered": "หัวข้อมีเลขกำกับ: ๑. ต้นเรื่อง ๒. ข้อเท็จจริง ๓. ข้อกฎหมาย ๔. ข้อพิจารณาและเสนอแนะ",
                }
                d.memo_heading_style = st.radio(
                    "รูปแบบหัวข้อ",
                    options=list(style_labels.keys()),
                    index=list(style_labels.keys()).index(d.memo_heading_style),
                    format_func=lambda k: style_labels[k],
                )
                st.caption("แยกข้อด้วยการขึ้นบรรทัดใหม่ — บรรทัดที่ขึ้นต้นด้วย ๑. / ๑.๑ / มาตรา / ข้อ จะจัดย่อหน้าอัตโนมัติ")

                field_specs = {
                    "intro": ("memo_intro", "ต้นเรื่อง", 110,
                              "หนังสือ/คำร้องที่ได้รับ (ที่ ลงวันที่ เรียน เรื่อง) และการสั่งการที่ผ่านมา แยกฉบับเป็น ๑. ๒."),
                    "law": ("memo_law", "ข้อกฎหมาย (ถ้ามี — เว้นว่างได้)", 110,
                            "กฎหมาย ระเบียบ หนังสือสั่งการ บรรทัดละรายการ ตามด้วย 'มาตรา ...' หรือ 'ข้อ ...' — อ้างเฉพาะที่มีอยู่จริง"),
                    "facts": ("memo_facts", "ข้อเท็จจริง", 120,
                              "ผลการประสาน/ตรวจสอบ และรายการคำขอแยกข้อ ๑. ๒. ๓."),
                    "consideration": ("memo_consideration", "ข้อพิจารณาและเสนอแนะ", 120,
                                      "ความเห็นของหน่วยงาน ตามด้วยข้อเสนอ ๑. และข้อย่อย ๑.๑ ๑.๒"),
                }
                for n, key in enumerate(SECTION_ORDER[d.memo_heading_style], start=1):
                    attr, label, height, help_txt = field_specs[key]
                    shown = f"{to_thai_numerals(str(n))}. {label}" if d.memo_heading_style == "numbered" else label
                    setattr(d, attr, st.text_area(shown, getattr(d, attr) or "", height=height, help=help_txt))

                d.memo_request = st.text_area(
                    "ภาคความประสงค์ (ย่อหน้าปิดท้าย)",
                    d.memo_request or "",
                    height=70,
                    help="เช่น 'จึงเรียนมาเพื่อโปรดพิจารณา หากเห็นชอบโปรดลงนามในหนังสือที่แนบ'",
                )

                # อัปเดตฟิลด์ paragraph_* ให้ตรงกันเสมอ (ใช้โดย linter / copilot)
                d.paragraph_reason = d.memo_intro
                d.paragraph_details = d.memo_facts
                d.paragraph_purpose = "\n\n".join(x for x in (d.memo_consideration, d.memo_request) if x)
            else:
                st.markdown("##### 📝 เนื้อความ (โครงสร้าง 3 ภาคมาตรฐาน)")
                st.session_state.doc_data.paragraph_reason = st.text_area(
                    "ภาคเหตุ (เกริ่นนำ)", 
                    st.session_state.doc_data.paragraph_reason, 
                    height=80
                )
                st.session_state.doc_data.paragraph_details = st.text_area(
                    "ภาคข้อเท็จจริงและข้อพิจารณา", 
                    st.session_state.doc_data.paragraph_details or "", 
                    height=80
                )
                st.session_state.doc_data.paragraph_purpose = st.text_area(
                    "ภาคความประสงค์หรือภาคสรุป", 
                    st.session_state.doc_data.paragraph_purpose, 
                    height=65
                )

            st.markdown("##### ✍️ ลายมือชื่อดิจิทัลและผู้ลงนาม")
            sig_col1, sig_col2 = st.columns([1.3, 1])
            with sig_col1:
                uploaded_sig = st.file_uploader(
                    "อัปโหลดไฟล์ลายมือชื่อ (PNG โปร่งใส แนะนำ / JPG)",
                    type=["png", "jpg", "jpeg"],
                    key="sig_img_uploader"
                )
                if uploaded_sig is not None:
                    sig_target_path = uploads_dir / f"signature_{uploaded_sig.name}"
                    with open(sig_target_path, "wb") as f_sig:
                        f_sig.write(uploaded_sig.getbuffer())
                    st.session_state.doc_data.signature_image_path = str(sig_target_path)
                    st.success("บันทึกและฝังลายมือชื่อลงในเอกสารเรียบร้อยแล้ว")
                elif getattr(st.session_state.doc_data, "signature_image_path", None):
                    if st.button("🗑️ ลบลายมือชื่อออกจากเอกสาร"):
                        st.session_state.doc_data.signature_image_path = None
                        st.rerun()
            with sig_col2:
                if getattr(st.session_state.doc_data, "signature_image_path", None) and os.path.exists(st.session_state.doc_data.signature_image_path):
                    st.image(st.session_state.doc_data.signature_image_path, caption="ตัวอย่างลายมือชื่อดิจิทัลที่ใช้งาน", width=120)

            if st.session_state.doc_data.doc_type == DocType.EXTERNAL:
                s1, s2, s3 = st.columns(3)
                with s1:
                    st.session_state.doc_data.closing = st.text_input("คำลงท้าย", st.session_state.doc_data.closing)
                with s2:
                    st.session_state.doc_data.signatory_name = st.text_input("ชื่อเต็มผู้ลงนาม", st.session_state.doc_data.signatory_name)
                with s3:
                    st.session_state.doc_data.signatory_position = st.text_input("ตำแหน่งผู้ลงนาม", st.session_state.doc_data.signatory_position)
            else:
                s1, s2 = st.columns(2)
                with s1:
                    st.session_state.doc_data.signatory_name = st.text_input("ชื่อเต็มผู้ลงนาม", st.session_state.doc_data.signatory_name)
                with s2:
                    st.session_state.doc_data.signatory_position = st.text_input("ตำแหน่งผู้ลงนาม", st.session_state.doc_data.signatory_position)

            if st.session_state.doc_data.doc_type == DocType.EXTERNAL:
                st.markdown("##### 🏢 ส่วนราชการเจ้าของเรื่องและข้อมูลติดต่อ")
                c_c1, c_c2, c_c3 = st.columns(3)
                with c_c1:
                    st.session_state.doc_data.contact_dept = st.text_input("กลุ่มงาน/กองเจ้าของเรื่อง", st.session_state.doc_data.contact_dept)
                with c_c2:
                    st.session_state.doc_data.contact_tel = st.text_input("โทรศัพท์", st.session_state.doc_data.contact_tel or "")
                with c_c3:
                    st.session_state.doc_data.contact_email = st.text_input("อีเมล", st.session_state.doc_data.contact_email or "")

        # ----------------- TAB DIFF & VERSIONS -----------------
        with tab_diff:
            st.markdown("##### 📊 เปรียบเทียบความเปลี่ยนแปลง (AI Draft vs ปัจจุบัน)")
            diff_results = compute_doc_diff(st.session_state.initial_ai_draft, st.session_state.doc_data)
            has_any_change = any(d.has_changes for d in diff_results)

            if not has_any_change:
                st.info("ℹ️ เอกสารฉบับปัจจุบันยังไม่มีการแก้ไขเปลี่ยนแปลงจากร่างเริ่มต้นของ AI")
            else:
                for d in diff_results:
                    if d.has_changes:
                        st.markdown(f"**🔹 {d.field_label}:**")
                        diff_html = []
                        for b in d.diff_blocks:
                            if b.op == "equal":
                                diff_html.append(b.original_text)
                            elif b.op == "delete":
                                diff_html.append(f'<span class="diff-del">{b.original_text}</span>')
                            elif b.op == "insert":
                                diff_html.append(f'<span class="diff-ins">{b.modified_text}</span>')
                            elif b.op == "replace":
                                diff_html.append(f'<span class="diff-del">{b.original_text}</span> <span class="diff-ins">{b.modified_text}</span>')
                        st.markdown(f"<div style='background:#f8fafc; padding:6px 10px; border-radius:5px; border:1px solid #e2e8f0; font-size:0.82rem;'>{' '.join(diff_html)}</div>", unsafe_allow_html=True)
                        st.write("")

            st.markdown("---")
            st.markdown("##### 💾 บันทึกประวัติเวอร์ชัน (Snapshot Version)")
            v_col1, v_col2 = st.columns([2.5, 1])
            with v_col1:
                v_note = st.text_input("บันทึกหมายเหตุเวอร์ชัน", value="ผ่านการตรวจทานและปรับข้อความเรียบร้อย")
            with v_col2:
                if st.button("📌 บันทึกเวอร์ชันใหม่", use_container_width=True):
                    new_v = audit_mgr.save_version(
                        doc_id=st.session_state.doc_data.doc_number,
                        doc=st.session_state.doc_data,
                        author="ผู้ตรวจทาน",
                        note=v_note
                    )
                    st.success(f"บันทึกเป็นเวอร์ชันที่ {new_v} สำเร็จแล้ว!")
                    st.rerun()

            saved_versions = audit_mgr.list_versions(st.session_state.doc_data.doc_number)
            if saved_versions:
                st.markdown("###### 📜 ประวัติเวอร์ชันที่บันทึกไว้:")
                for sv in saved_versions:
                    st.markdown(f"- **เวอร์ชัน {sv.version_num}:** {sv.note} (โดย {sv.author} เมื่อ {sv.created_at})")

        # Linter Validation Summary
        lint_res = lint_gov_document(st.session_state.doc_data)
        st.markdown("---")
        st.markdown("##### 🛡️ ผลการตรวจสอบความถูกต้องตามระเบียบงานสารบรรณ")
        if lint_res.is_valid:
            st.success("✅ ผ่านการตรวจสอบ: เอกสารถูกต้องตามระเบียบงานสารบรรณ พ.ศ. ๒๕๒๖ ครบถ้วน")
        else:
            for err in lint_res.errors:
                st.error(f"❌ **[{err.field}]** {err.message} (แนะนำ: {err.suggestion})")
        for warn in lint_res.warnings:
            st.warning(f"⚠️ **[{warn.field}]** {warn.message} (แนะนำ: {warn.suggestion})")


# =====================================================================
# TAB 2: E-DOCUMENT REGISTRY
# =====================================================================
with tab_registry:
    st.subheader("📖 สมุดทะเบียนคุมสารบรรณอิเล็กทรอนิกส์")
    reg_tab1, reg_tab2, reg_tab3 = st.tabs(["📤 ทะเบียนส่ง (Outgoing)", "📥 ทะเบียนรับ (Incoming)", "🔖 จองเลขหนังสือ (Reserve)"])
    
    with reg_tab1:
        st.markdown("##### 📤 รายการหนังสือส่งออกล่าสุด")
        outgoing_list = registry.list_outgoing()
        if outgoing_list:
            st.dataframe(outgoing_list, use_container_width=True)
        else:
            st.info("ยังไม่มีรายการในสมุดทะเบียนส่ง")

    with reg_tab2:
        st.markdown("##### 📥 รายการหนังสือรับเข้าล่าสุด")
        incoming_list = registry.list_incoming()
        if incoming_list:
            st.dataframe(incoming_list, use_container_width=True)
        else:
            st.info("ยังไม่มีรายการในสมุดทะเบียนรับ")

    with reg_tab3:
        st.markdown("##### 🔖 แบบฟอร์มขอจองเลขที่หนังสือล่วงหน้า")
        with st.form("reserve_form"):
            res_prefix = st.text_input("รหัสหมวดหมู่หนังสือ", value="ดพร ๐๑๐๒/")
            res_subject = st.text_input("เรื่องที่ต้องการจองเลข")
            res_user = st.text_input("ชื่อผู้จองเลข", value="เจ้าหน้าที่สารบรรณ")
            submitted = st.form_submit_button("ยืนยันการจองเลขหนังสือ")
            if submitted and res_subject:
                reserved_no = registry.reserve_doc_number(res_prefix, res_subject, res_user)
                st.success(f"จองเลขสำเร็จ! เลขที่หนังสือที่ได้รับ: **{reserved_no}**")
                st.rerun()

# =====================================================================
# TAB 3: USER ORGANIZATION PROFILE SETTINGS
# =====================================================================
with tab_profile:
    st.subheader("⚙️ ตั้งค่าข้อมูลหน่วยงานของฉัน (User Organization Profile)")
    st.caption("กำหนดชื่อหน่วยงาน สายการบังคับบัญชา และผู้มีอำนาจลงนาม เพื่อใช้เป็นค่าเริ่มต้นอัตโนมัติในการยกร่างหนังสือทุกฉบับ (บันทึกลง data/user_profile.json)")

    prof = get_user_profile()

    with st.form("user_profile_form"):
        col_p1, col_p2 = st.columns(2)
        with col_p1:
            st.markdown("##### 🏛️ ข้อมูลหน่วยงาน / ส่วนราชการ")
            p_dept = st.text_input("ชื่อสำนัก / กรม / หน่วยงานระดับบน:", value=prof.dept_name)
            p_div = st.text_input("ชื่อกอง / ฝ่าย:", value=prof.division_name)
            p_sec = st.text_input("ชื่อกลุ่มงาน / งาน:", value=prof.section_name)
            p_full = st.text_area("ชื่อส่วนราชการเต็ม (สำหรับหัวบันทึกข้อความ):", value=prof.department_full, height=80)
            p_origin = st.text_input("รหัสพยัญชนะนำหน้าเลขที่หนังสือ:", value=prof.doc_origin_code)

        with col_p2:
            st.markdown("##### ✍️ ข้อมูลผู้ลงนามและผู้ประสานงาน")
            p_sig_name = st.text_input("ชื่อ-สกุล ผู้ลงนาม (ในวงเล็บ):", value=prof.signatory_name)
            p_sig_pos = st.text_input("ตำแหน่งผู้ลงนาม:", value=prof.signatory_position)
            p_contact_dept = st.text_input("หน่วยงานเจ้าของเรื่อง/ผู้ประสานงาน:", value=prof.contact_dept)
            p_contact_tel = st.text_input("เบอร์โทรศัพท์ติดต่อ:", value=prof.contact_tel)
            p_contact_fax = st.text_input("เบอร์โทรสาร:", value=prof.contact_fax)
            p_contact_email = st.text_input("อีเมลติดต่อราชการ:", value=prof.contact_email or "")

        btn_save = st.form_submit_button("💾 บันทึกการตั้งค่าหน่วยงาน", type="primary", use_container_width=True)
        if btn_save:
            updated_profile = UserProfileSchema(
                dept_name=p_dept.strip(),
                division_name=p_div.strip(),
                section_name=p_sec.strip(),
                department_full=p_full.strip(),
                doc_origin_code=p_origin.strip(),
                signatory_name=p_sig_name.strip(),
                signatory_position=p_sig_pos.strip(),
                contact_dept=p_contact_dept.strip(),
                contact_tel=p_contact_tel.strip(),
                contact_fax=p_contact_fax.strip(),
                contact_email=p_contact_email.strip(),
                hierarchy_default=prof.hierarchy_default
            )
            save_user_profile(updated_profile)
            st.session_state.user_profile = updated_profile
            st.success("บันทึกการตั้งค่าหน่วยงานสำเร็จ! ร่างหนังสือฉบับต่อไปจะใช้ข้อมูลชุดนี้โดยอัตโนมัติ")
            st.rerun()

    if st.button("🔄 รีเซ็ตเป็นค่าเริ่มต้นของกรุงเทพมหานคร (BMA Default)", use_container_width=True):
        res_prof = reset_to_default_profile()
        st.session_state.user_profile = res_prof
        st.success("รีเซ็ตเป็นค่าเริ่มต้น กทม. เรียบร้อยแล้ว!")
        st.rerun()
