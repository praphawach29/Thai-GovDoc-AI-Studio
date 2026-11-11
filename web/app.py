"""
app.py — หน้าจอใช้งานหลัก (Interactive Workspace) สำหรับ Thai GovDoc AI Studio
พัฒนาตามโมเดล Modern GovDoc Studio (Split-Screen Workspace, Smart Placeholders, A4 Canvas & Inline Copilot)
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

import streamlit as st

from core.models import GovDocumentSchema, DocType, UrgencyLevel, SecretLevel, SourceDocumentContext
from core.extractor import extract_source_document
from core.ai_drafter import draft_from_context_rule_based, DraftingIntent
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


st.set_page_config(
    page_title="Thai GovDoc AI Studio - ระบบร่างและผลิตหนังสือราชการไทยอัจฉริยะ",
    page_icon="🏛️",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom Styling ให้ดูพรีเมียมและเป็นทางการตามโมเดล Ekkasarn / Modern Legal Tech
st.markdown("""
<style>
    .main-title {
        font-size: 2.1rem;
        font-weight: 700;
        color: #1a365d;
        margin-bottom: 0.1rem;
    }
    .sub-title {
        color: #4a5568;
        font-size: 1.0rem;
        margin-bottom: 1.2rem;
    }
    /* Status Pills */
    .status-pill {
        padding: 4px 12px;
        border-radius: 9999px;
        font-size: 0.85rem;
        font-weight: 600;
        display: inline-block;
        margin-right: 6px;
    }
    .status-pill-ready {
        background-color: #d1fae5;
        color: #065f46;
        border: 1px solid #10b981;
    }
    .status-pill-warning {
        background-color: #fef3c7;
        color: #92400e;
        border: 1px solid #f59e0b;
    }
    .status-pill-info {
        background-color: #e0f2fe;
        color: #0369a1;
        border: 1px solid #38bdf8;
    }
    
    /* Smart Placeholder Chip */
    .placeholder-chip {
        background-color: #fffbeb;
        color: #b45309;
        border: 1.5px dashed #f59e0b;
        padding: 2px 7px;
        border-radius: 5px;
        font-weight: 600;
        font-size: 0.94em;
        display: inline-block;
        margin: 1px 3px;
        box-shadow: 0 1px 2px rgba(245, 158, 11, 0.15);
    }

    /* A4 Paper Simulation */
    .a4-paper {
        background: white;
        width: 100%;
        max-width: 820px;
        min-height: 1050px;
        padding: 48px 55px 40px 75px;
        margin: 10px auto;
        box-shadow: 0 4px 20px rgba(0,0,0,0.10);
        border: 1px solid #cbd5e1;
        border-radius: 2px;
        font-family: 'TH Sarabun New', 'Sarabun', 'Angsana New', sans-serif;
        font-size: 16pt;
        line-height: 1.35;
        color: #000;
    }
    .a4-paper p {
        margin-bottom: 7px;
        text-align: justify;
    }
    .a4-indent {
        text-indent: 2.5cm;
    }
    .diff-ins {
        background-color: #c6f6d5;
        color: #22543d;
        padding: 2px 4px;
        border-radius: 3px;
        font-weight: 600;
    }
    .diff-del {
        background-color: #fed7d7;
        color: #742a2a;
        text-decoration: line-through;
        padding: 2px 4px;
        border-radius: 3px;
    }
</style>
""", unsafe_allow_html=True)


# โหลดรูปครุฑแบบ Base64 สำหรับแสดงใน HTML
garuda_path = root_dir / "assets" / "garuda.png"
if garuda_path.exists():
    with open(garuda_path, "rb") as f:
        garuda_b64 = base64.b64encode(f.read()).decode("utf-8")
else:
    garuda_b64 = ""

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


def get_docx_bytes(doc_schema: GovDocumentSchema) -> bytes:
    """สร้างไฟล์ Word .docx ในหน่วยความจำและส่งออกเป็น bytes สำหรับดาวน์โหลดใน 1 คลิก"""
    with tempfile.NamedTemporaryFile(suffix=".docx", delete=False) as tmp:
        tmp_path = tmp.name
    try:
        export_govdoc_to_docx(doc_schema, tmp_path)
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


# Initialize Session State
if "doc_data" not in st.session_state:
    st.session_state.doc_data = GovDocumentSchema(
        doc_type=DocType.EXTERNAL,
        urgency=UrgencyLevel.NORMAL,
        secret=SecretLevel.NORMAL,
        use_thai_numerals=False,
        doc_number="ดพร ๐๑๐๒/ว ๑๒๓",
        dept_name="สำนักงานพัฒนารัฐบาลดิจิทัล (องค์การมหาชน) ถนนวิภาวดีรังสิต กรุงเทพฯ ๑๐๔๐๐",
        doc_date="๑๕ มีนาคม ๒๕๖๙",
        subject="การให้ความอนุเคราะห์วิทยากรบรรยายการประยุกต์ใช้ AI ในภาครัฐ",
        salutation="เรียน  อธิการบดีมหาวิทยาลัยเชียงใหม่",
        references=["หนังสือมหาวิทยาลัยเชียงใหม่ ที่ อว ๘๓๙๒/๑๐๒ ลงวันที่ ๕ มีนาคม ๒๕๖๙"],
        attachments=["แบบตอบรับวิทยากร จำนวน ๑ ฉบับ"],
        paragraph_reason="ตามที่ มหาวิทยาลัยเชียงใหม่ ได้มีหนังสือที่อ้างถึง แจ้งความประสงค์ขอความอนุเคราะห์วิทยากรบรรยายในหัวข้อ \"การประยุกต์ใช้ AI ในภาครัฐเพื่อยกระดับงานบริการประชาชน\" ในวันที่ ๒๕ มีนาคม ๒๕๖๙ ความละเอียดแจ้งแล้ว นั้น",
        paragraph_details="สำนักงานพัฒนารัฐบาลดิจิทัล (องค์การมหาชน) ได้พิจารณาแล้ว มีความยินดีและไม่ขัดข้องในการให้ความอนุเคราะห์วิทยากรดังกล่าว โดยได้มอบหมายให้ นายสมชาย ดิจิทัล ตำแหน่งผู้เชี่ยวชาญด้านปัญญาประดิษฐ์ เข้าร่วมบรรยายตามวัน เวลา และสถานที่ดังกล่าว",
        paragraph_purpose="จึงเรียนมาเพื่อโปรดทราบ และได้มอบหมายให้ผู้ประสานงานดำเนินการในส่วนที่เกี่ยวข้องต่อไป",
        closing="ขอแสดงความนับถือ",
        signatory_name="(นางสาวสุดา พัฒนารัฐ)",
        signatory_position="ผู้อำนวยการสำนักงานพัฒนารัฐบาลดิจิทัล",
        contact_dept="ฝ่ายพัฒนาศักยภาพภาครัฐ",
        contact_tel="๐ ๒๖๑๒ ๖๐๐๐ ต่อ ๑๒๓๔",
        contact_fax="๐ ๒๖๑๒ ๖๐๐๑",
        contact_email="contact@dga.or.th"
    )

if "initial_ai_draft" not in st.session_state:
    st.session_state.initial_ai_draft = st.session_state.doc_data.model_copy(deep=True)

if "source_context" not in st.session_state:
    st.session_state.source_context = None

if "last_uploaded_file" not in st.session_state:
    st.session_state.last_uploaded_file = None


# ส่วนหัวหน้าเว็บ
st.markdown('<div class="main-title">🏛️ Thai GovDoc AI Studio</div>', unsafe_allow_html=True)
st.markdown('<div class="sub-title">ระบบร่างและผลิตหนังสือราชการไทยอัจฉริยะ (อ้างอิงระเบียบงานสารบรรณ พ.ศ. ๒๕๒๖)</div>', unsafe_allow_html=True)

# แถบเมนูหลัก
tab_main, tab_registry = st.tabs(["📝 ห้องร่างและตรวจแก้หนังสือ (Studio & Review)", "📖 สมุดทะเบียนคุมสารบรรณ (e-Document Registry)"])

# =====================================================================
# TAB 1: STUDIO & REVIEW
# =====================================================================
with tab_main:
    col_left, col_right = st.columns([1, 1.35], gap="large")

    # ----------------- คอลัมน์ซ้าย: แนบไฟล์ต้นเรื่อง & สั่งการ AI -----------------
    with col_left:
        st.subheader("📂 1. แนบไฟล์ต้นเรื่อง (Source Document)")
        uploaded_file = st.file_uploader(
            "อัปโหลดหนังสือเดิม / บันทึกข้อความ / คำร้อง (PDF, DOCX, TXT, รูปภาพ)",
            type=["pdf", "docx", "txt", "png", "jpg", "jpeg"]
        )

        if uploaded_file is not None:
            # บันทึกไฟล์ลง uploads
            saved_path = uploads_dir / uploaded_file.name
            with open(saved_path, "wb") as f:
                f.write(uploaded_file.getbuffer())

            # สกัดข้อความอัตโนมัติเมื่อมีการอัปโหลดไฟล์ใหม่
            if st.session_state.last_uploaded_file != uploaded_file.name:
                with st.spinner("กำลังอ่านและสกัดข้อความจากเอกสารต้นเรื่อง (OCR / Extraction)..."):
                    ctx = extract_source_document(str(saved_path))
                    st.session_state.source_context = ctx
                    st.session_state.last_uploaded_file = uploaded_file.name
                st.success(f"แนบไฟล์สำเร็จ: {uploaded_file.name}")

            # เลือกเจตนาการร่างหนังสือ (Drafting Intent)
            st.markdown("##### 🎯 เลือกวัตถุประสงค์ในการร่างหนังสือ:")
            intent_choice = st.radio(
                "เจตนาการตอบ/ยกร่าง:",
                options=[
                    (DraftingIntent.MEMO_REVIEW, "📑 บันทึกข้อความรายงานการพิจารณา / เกษียนสั่งการรวมเรื่องเดิม (แนะนำ)"),
                    (DraftingIntent.ACCEPT, "🤝 หนังสือตอบรับ / ยินดีให้ความอนุเคราะห์"),
                    (DraftingIntent.DECLINE, "❌ หนังสือแจ้งข้อขัดข้อง / ปฏิเสธอย่างสุภาพ"),
                    (DraftingIntent.FORWARD, "📨 หนังสือส่งต่อเรื่อง / แจ้งเวียน"),
                    (DraftingIntent.PROPOSAL, "📝 บันทึกข้อความเสนอผู้บังคับบัญชาเพื่อโปรดพิจารณาอนุมัติ")
                ],
                format_func=lambda x: x[1],
                index=0
            )

            is_internal_intent = intent_choice[0] in [DraftingIntent.PROPOSAL, DraftingIntent.MEMO_REVIEW]
            target_doc_type = DocType.INTERNAL if is_internal_intent else DocType.EXTERNAL

            if st.button("🚀 ให้ AI ยกร่างหนังสือตามต้นเรื่องนี้", type="primary", use_container_width=True):
                with st.spinner("AI กำลังวิเคราะห์และยกร่างโครงสร้าง 3 ภาคตามระเบียบงานสารบรรณ..."):
                    ctx = st.session_state.source_context
                    draft = draft_from_context_rule_based(ctx, doc_type=target_doc_type, intent=intent_choice[0])
                    st.session_state.doc_data = draft
                    st.session_state.initial_ai_draft = draft.model_copy(deep=True)
                    # บันทึกเวอร์ชันเริ่มต้นลง Audit
                    audit_mgr.save_version(
                        doc_id=draft.doc_number,
                        doc=draft,
                        author="AI Studio",
                        note=f"ร่างเริ่มต้นจากเอกสารต้นเรื่อง ({intent_choice[1]})"
                    )
                    st.success("ยกร่างหนังสือราชการสำเร็จแล้ว! ตรวจสอบได้ที่หน้ากระดาษฝั่งขวา")

        # แสดงผลเอกสารต้นเรื่องและภาพพรีวิว
        if st.session_state.source_context:
            ctx = st.session_state.source_context
            st.markdown("---")
            st.markdown("#### 🔍 ข้อมูลที่สกัดได้จากเอกสารต้นเรื่อง")
            st.info(
                f"**ไฟล์:** {ctx.source_filename} ({'เอกสารสแกน' if ctx.is_scanned else 'ดิจิทัล'})\n\n"
                f"**หน่วยงานต้นเรื่อง:** {ctx.source_dept or 'ไม่ระบุ'}\n\n"
                f"**เลขที่เดิม:** {ctx.source_doc_no or 'ไม่ระบุ'}\n\n"
                f"**วันที่เดิม:** {ctx.source_date or 'ไม่ระบุ'}\n\n"
                f"**เรื่องเดิม:** {ctx.source_subject or 'ไม่ระบุ'}"
            )

            if ctx.preview_image_path and os.path.exists(ctx.preview_image_path):
                st.image(ctx.preview_image_path, caption=f"ตัวอย่างหน้าเอกสารต้นเรื่อง: {ctx.source_filename}", use_container_width=True)

            with st.expander("📄 ดูข้อความที่สกัดได้ทั้งหมด (Raw Text)", expanded=False):
                st.text_area("Extracted Text", ctx.raw_text, height=200, disabled=True)
        else:
            st.info("💡 สามารถทดลองใช้งานด้วยข้อมูลตัวอย่าง หรือแนบไฟล์จริง (.pdf, .docx, .txt, .png)")

        # กล่อง Copilot ช่วยเหลือด่วน (Conversational Copilot Assistant)
        st.markdown("---")
        st.markdown("##### 💬 AI Copilot สั่งปรับแต่งข้อความเพิ่มเติม")
        c_prompt = st.text_input("พิมพ์คำสั่งให้ AI ช่วย เช่น 'ปรับให้เป็นทางการยิ่งขึ้น', 'ขอให้อ้างระเบียบพัสดุ'", "")
        if st.button("✨ ส่งคำสั่งให้ AI", use_container_width=True) and c_prompt:
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
        # Header Status Bar แสดงสถานะความพร้อมของเอกสาร
        doc = st.session_state.doc_data
        placeholder_count = doc.count_placeholders()

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
                    f'<div style="text-align: right;"><span class="status-pill status-pill-warning">⚠️ มี {placeholder_count} จุดที่ต้องระบุข้อมูล</span></div>',
                    unsafe_allow_html=True
                )
            else:
                st.markdown(
                    '<div style="text-align: right;"><span class="status-pill status-pill-ready">✅ เอกสารพร้อมตรวจและส่งออก</span></div>',
                    unsafe_allow_html=True
                )

        tab_preview, tab_editor, tab_diff = st.tabs([
            "👁️ Live A4 Preview & ส่งออก", 
            "✏️ ฟอร์มแก้ไขข้อความอย่างละเอียด", 
            "📊 เปรียบเทียบการแก้ไข (Diff & Audit)"
        ])

        # ----------------- TAB PREVIEW & QUICK ACTIONS -----------------
        with tab_preview:
            # 1-Click Action Toolbar วางบนหน้ากระดาษ A4 เสมือนจริง
            t1, t2, t3, t4 = st.columns([1.2, 1.2, 1.2, 1.2])
            with t1:
                if st.button("🔢 สลับเลขไทย ↔ อารบิก", use_container_width=True):
                    new_val = not st.session_state.doc_data.use_thai_numerals
                    st.session_state.doc_data = toggle_doc_numerals(st.session_state.doc_data, use_thai=new_val)
                    st.rerun()
            with t2:
                docx_bytes = get_docx_bytes(st.session_state.doc_data)
                st.download_button(
                    label="📥 ดาวน์โหลด Word (.docx)",
                    data=docx_bytes,
                    file_name=f"{st.session_state.doc_data.subject[:30].replace('/', '_')}.docx",
                    mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    use_container_width=True,
                    type="primary"
                )
            with t3:
                typst_bytes = get_typst_bytes(st.session_state.doc_data)
                st.download_button(
                    label="📄 ดาวน์โหลด Typst (.typ)",
                    data=typst_bytes,
                    file_name=f"{st.session_state.doc_data.subject[:30].replace('/', '_')}.typ",
                    mime="text/plain",
                    use_container_width=True
                )
            with t4:
                if st.button("📚 บันทึกลงทะเบียนส่ง", use_container_width=True):
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
                        st.success(f"บันทึกลงทะเบียนส่งเรียบร้อยแล้ว (รหัสทะเบียน: {new_id})")
                    except Exception as e:
                        st.error(f"ไม่สามารถลงทะเบียนได้: {str(e)}")

            # เตรียมข้อความสำหรับแสดงผลพร้อม Smart Placeholder Chips
            doc = st.session_state.doc_data
            disp_date = highlight_placeholders_html(to_thai_numerals(doc.doc_date) if doc.use_thai_numerals else doc.doc_date)
            disp_no = highlight_placeholders_html(to_thai_numerals(doc.doc_number) if doc.use_thai_numerals else doc.doc_number)
            disp_dept = highlight_placeholders_html(doc.dept_name)
            disp_subject = highlight_placeholders_html(doc.subject)
            disp_salutation = highlight_placeholders_html(doc.salutation)
            disp_reason = highlight_placeholders_html(to_thai_numerals(doc.paragraph_reason) if doc.use_thai_numerals else doc.paragraph_reason)
            disp_details = highlight_placeholders_html(to_thai_numerals(doc.paragraph_details) if (doc.paragraph_details and doc.use_thai_numerals) else (doc.paragraph_details or ""))
            disp_purpose = highlight_placeholders_html(to_thai_numerals(doc.paragraph_purpose) if doc.use_thai_numerals else doc.paragraph_purpose)
            disp_closing = highlight_placeholders_html(doc.closing)
            disp_sig_name = highlight_placeholders_html(doc.signatory_name)
            disp_sig_pos = highlight_placeholders_html(doc.signatory_position)

            # เรนเดอร์ส่วนอ้างถึงและสิ่งที่ส่งมาด้วย (ถ้ามี)
            refs_html = ""
            if doc.references:
                ref_items = []
                for idx, r in enumerate(doc.references):
                    h_val = highlight_placeholders_html(to_thai_numerals(r) if doc.use_thai_numerals else r)
                    if idx == 0:
                        ref_items.append(f"<p><strong>อ้างถึง</strong>  {h_val}</p>")
                    else:
                        ref_items.append(f'<p style="margin-left: 2.5cm;">{h_val}</p>')
                refs_html = "".join(ref_items)

            atts_html = ""
            if doc.attachments:
                att_items = []
                for idx, a in enumerate(doc.attachments):
                    h_val = highlight_placeholders_html(to_thai_numerals(a) if doc.use_thai_numerals else a)
                    if idx == 0:
                        att_items.append(f"<p><strong>สิ่งที่ส่งมาด้วย</strong>  {h_val}</p>")
                    else:
                        att_items.append(f'<p style="margin-left: 2.5cm;">{h_val}</p>')
                atts_html = "".join(att_items)

            # HTML A4 Preview Template
            if doc.doc_type == DocType.EXTERNAL:
                st.markdown(f"""
                <div class="a4-paper">
                    <div style="text-align: center; margin-bottom: 15px;">
                        <img src="data:image/png;base64,{garuda_b64}" style="height: 3.0cm; width: auto;" alt="ตราครุฑ 3 ซม." />
                    </div>
                    <div style="display: flex; justify-content: space-between; margin-bottom: 8px;">
                        <div style="width: 48%;">ที่  {disp_no}</div>
                        <div style="width: 48%;">{disp_dept}</div>
                    </div>
                    <div style="text-align: center; margin-left: 20%; margin-bottom: 15px;">
                        {disp_date}
                    </div>
                    <div style="margin-bottom: 12px;">
                        <p><strong>เรื่อง</strong>  {disp_subject}</p>
                        <p><strong>เรียน</strong>  {disp_salutation}</p>
                        {refs_html}
                        {atts_html}
                    </div>
                    <p class="a4-indent">{disp_reason}</p>
                    {f'<p class="a4-indent">{disp_details}</p>' if disp_details else ''}
                    <p class="a4-indent">{disp_purpose}</p>
                    <div style="text-align: center; margin-left: 45%; margin-top: 35px; margin-bottom: 35px;">
                        <p>{disp_closing}</p>
                        <div style="height: 45px;"></div>
                        <p>{disp_sig_name}</p>
                        <p>{disp_sig_pos}</p>
                    </div>
                    <div style="font-size: 14pt; margin-top: 25px; color: #444;">
                        <p style="margin: 0;">{highlight_placeholders_html(doc.contact_dept or '')}</p>
                        <p style="margin: 0;">โทรศัพท์  {highlight_placeholders_html(doc.contact_tel or '')}</p>
                        <p style="margin: 0;">ไปรษณีย์อิเล็กทรอนิกส์  {highlight_placeholders_html(doc.contact_email or '')}</p>
                    </div>
                </div>
                """, unsafe_allow_html=True)
            else:
                st.markdown(f"""
                <div class="a4-paper">
                    <div style="display: flex; align-items: flex-start; margin-bottom: 15px;">
                        <img src="data:image/png;base64,{garuda_b64}" style="height: 1.5cm; width: auto; margin-right: 25px;" alt="ตราครุฑ 1.5 ซม." />
                        <div style="font-size: 29pt; font-weight: bold; text-align: center; width: 80%;">บันทึกข้อความ</div>
                    </div>
                    <div style="margin-bottom: 10px;">
                        <p><strong>ส่วนราชการ</strong>  {disp_dept}</p>
                        <div style="display: flex; justify-content: space-between;">
                            <div style="width: 48%;"><strong>ที่</strong>  {disp_no}</div>
                            <div style="width: 48%;"><strong>วันที่</strong>  {disp_date}</div>
                        </div>
                        <p><strong>เรื่อง</strong>  {disp_subject}</p>
                        <p><strong>เรียน</strong>  {disp_salutation}</p>
                        {refs_html}
                        {atts_html}
                    </div>
                    <hr style="border-top: 1px solid #ccc; margin-bottom: 15px;" />
                    <p class="a4-indent">{disp_reason}</p>
                    {f'<p class="a4-indent">{disp_details}</p>' if disp_details else ''}
                    <p class="a4-indent">{disp_purpose}</p>
                    <div style="text-align: center; margin-left: 45%; margin-top: 45px;">
                        <div style="height: 40px;"></div>
                        <p>{disp_sig_name}</p>
                        <p>{disp_sig_pos}</p>
                    </div>
                </div>
                """, unsafe_allow_html=True)

            # Inline Paragraph Actions (เกลาภาษาระดับย่อหน้า)
            st.markdown("##### ⚡ เครื่องมือลัดเกลาภาษาระดับย่อหน้า (Inline Paragraph Actions)")
            ip1, ip2, ip3 = st.columns(3)
            with ip1:
                st.caption("🔹 จัดการภาคเหตุ:")
                col_i1, col_i2 = st.columns(2)
                with col_i1:
                    if st.button("✍️ ทางการขึ้น", key="btn_p1_formal", use_container_width=True):
                        st.session_state.doc_data.paragraph_reason = copilot_refine_paragraph("reason", st.session_state.doc_data.paragraph_reason, "formal")
                        st.rerun()
                with col_i2:
                    if st.button("✂️ สรุปย่อ", key="btn_p1_concise", use_container_width=True):
                        st.session_state.doc_data.paragraph_reason = copilot_refine_paragraph("reason", st.session_state.doc_data.paragraph_reason, "concise")
                        st.rerun()

            with ip2:
                st.caption("🔹 จัดการภาคข้อเท็จจริง:")
                col_j1, col_j2 = st.columns(2)
                with col_j1:
                    if st.button("✍️ ทางการขึ้น", key="btn_p2_formal", use_container_width=True):
                        if st.session_state.doc_data.paragraph_details:
                            st.session_state.doc_data.paragraph_details = copilot_refine_paragraph("details", st.session_state.doc_data.paragraph_details, "formal")
                            st.rerun()
                with col_j2:
                    if st.button("⚖️ อ้างระเบียบ", key="btn_p2_law", use_container_width=True):
                        if st.session_state.doc_data.paragraph_details:
                            st.session_state.doc_data.paragraph_details = copilot_refine_paragraph("details", st.session_state.doc_data.paragraph_details, "law")
                            st.rerun()

            with ip3:
                st.caption("🔹 จัดการภาคสรุป/เสนอ:")
                col_k1, col_k2 = st.columns(2)
                with col_k1:
                    if st.button("✍️ ทางการขึ้น", key="btn_p3_formal", use_container_width=True):
                        st.session_state.doc_data.paragraph_purpose = copilot_refine_paragraph("purpose", st.session_state.doc_data.paragraph_purpose, "formal")
                        st.rerun()
                with col_k2:
                    if st.button("📌 ใส่ข้อพิจารณา", key="btn_p3_propose", use_container_width=True):
                        st.session_state.doc_data.paragraph_purpose = copilot_refine_paragraph("purpose", st.session_state.doc_data.paragraph_purpose, "propose")
                        st.rerun()

        # ----------------- TAB DETAILED EDITOR -----------------
        with tab_editor:
            # การควบคุมประเภทและชั้นความเร็ว/ความลับ
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

            # ข้อมูลหัวกระดาษ
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

            # อ้างถึง และ สิ่งที่ส่งมาด้วย (รองรับหลายบรรทัด)
            st.markdown("##### 📎 เอกสารอ้างอิงและสิ่งที่ส่งมาด้วย")
            ref_col, att_col = st.columns(2)
            with ref_col:
                current_refs = "\n".join(st.session_state.doc_data.references) if st.session_state.doc_data.references else ""
                new_refs_text = st.text_area("อ้างถึง (แยก ๑ บรรทัดต่อ ๑ ฉบับ)", value=current_refs, height=75)
                st.session_state.doc_data.references = [line.strip() for line in new_refs_text.splitlines() if line.strip()] or None
            with att_col:
                current_atts = "\n".join(st.session_state.doc_data.attachments) if st.session_state.doc_data.attachments else ""
                new_atts_text = st.text_area("สิ่งที่ส่งมาด้วย (แยก ๑ บรรทัดต่อ ๑ ฉบับ)", value=current_atts, height=75)
                st.session_state.doc_data.attachments = [line.strip() for line in new_atts_text.splitlines() if line.strip()] or None

            # เนื้อความ 3 ภาค
            st.markdown("##### 📝 เนื้อความ (โครงสร้าง 3 ภาคมาตรฐาน)")
            st.session_state.doc_data.paragraph_reason = st.text_area(
                "ภาคเหตุ (เกริ่นนำ)", 
                st.session_state.doc_data.paragraph_reason, 
                height=90
            )
            st.session_state.doc_data.paragraph_details = st.text_area(
                "ภาคข้อเท็จจริงและข้อพิจารณา", 
                st.session_state.doc_data.paragraph_details or "", 
                height=90
            )
            st.session_state.doc_data.paragraph_purpose = st.text_area(
                "ภาคความประสงค์หรือภาคสรุป", 
                st.session_state.doc_data.paragraph_purpose, 
                height=70
            )

            # ผู้ลงนาม และคำลงท้าย
            st.markdown("##### ✍️ ลายมือชื่อและผู้ลงนาม")
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

            # ข้อมูลผู้ติดต่อ (สำหรับหนังสือภายนอก)
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
                        st.markdown(f"<div style='background:#f8fafc; padding:8px 12px; border-radius:6px; border:1px solid #e2e8f0;'>{' '.join(diff_html)}</div>", unsafe_allow_html=True)
                        st.write("")

            st.markdown("---")
            st.markdown("##### 💾 บันทึกประวัติเวอร์ชัน (Snapshot Version)")
            v_col1, v_col2 = st.columns([2, 1])
            with v_col1:
                v_note = st.text_input("บันทึกหมายเหตุเวอร์ชัน", value="ผ่านการตรวจทานและปรับข้อความเรียบร้อย")
            with v_col2:
                if st.button("📌 บันทึกเป็นเวอร์ชันใหม่", use_container_width=True):
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

        # Linter Validation Summary ด้านล่าง
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
