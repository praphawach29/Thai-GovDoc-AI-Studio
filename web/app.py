"""
app.py — หน้าจอใช้งานหลัก (Interactive Workspace) สำหรับ Thai GovDoc AI Studio
รันด้วย Streamlit: streamlit run web/app.py
"""

import os
import sys
import base64
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
    toggle_doc_numerals
)
from core.audit import AuditManager, compute_doc_diff
from core.word_exporter import export_govdoc_to_docx
from core.typst_exporter import export_govdoc_to_typst, compile_typst_to_pdf
from core.linter import lint_gov_document
from core.registry import DocumentRegistry, OutgoingRecord
from core.thai_segmenter import to_thai_numerals, to_arabic_numerals


st.set_page_config(
    page_title="Thai GovDoc AI Studio - ระบบร่างและผลิตหนังสือราชการไทยอัจฉริยะ",
    page_icon="🏛️",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom Styling ให้ดูพรีเมียมและเป็นทางการ
st.markdown("""
<style>
    .main-title {
        font-size: 2.2rem;
        font-weight: 700;
        color: #1a365d;
        margin-bottom: 0.2rem;
    }
    .sub-title {
        color: #4a5568;
        font-size: 1.05rem;
        margin-bottom: 1.5rem;
    }
    /* A4 Paper Simulation */
    .a4-paper {
        background: white;
        width: 100%;
        max-width: 800px;
        min-height: 1050px;
        padding: 50px 60px 40px 80px;
        margin: 15px auto;
        box-shadow: 0 4px 15px rgba(0,0,0,0.12);
        border: 1px solid #e2e8f0;
        font-family: 'TH Sarabun New', 'Sarabun', 'Angsana New', sans-serif;
        font-size: 16pt;
        line-height: 1.35;
        color: #000;
    }
    .a4-paper p {
        margin-bottom: 8px;
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
    col_left, col_right = st.columns([1, 1.25], gap="large")

    # ----------------- คอลัมน์ซ้าย: แนบไฟล์ต้นเรื่อง -----------------
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
                with st.spinner("กำลังอ่านและสกัดข้อความจากเอกสารต้นเรื่อง..."):
                    ctx = extract_source_document(str(saved_path))
                    st.session_state.source_context = ctx
                    st.session_state.last_uploaded_file = uploaded_file.name
                st.success(f"แนบไฟล์สำเร็จ: {uploaded_file.name}")

            # เลือกเจตนาการร่างหนังสือ (Drafting Intent)
            st.markdown("##### 🎯 เลือกวัตถุประสงค์ในการร่างหนังสือ:")
            intent_choice = st.radio(
                "เจตนาการตอบ/ยกร่าง:",
                options=[
                    (DraftingIntent.ACCEPT, "🤝 หนังสือตอบรับ / ยินดีให้ความอนุเคราะห์"),
                    (DraftingIntent.DECLINE, "❌ หนังสือแจ้งข้อขัดข้อง / ปฏิเสธอย่างสุภาพ"),
                    (DraftingIntent.FORWARD, "📨 หนังสือส่งต่อเรื่อง / แจ้งเวียน"),
                    (DraftingIntent.PROPOSAL, "📑 บันทึกข้อความเสนอผู้บังคับบัญชาเพื่อโปรดพิจารณาอนุมัติ")
                ],
                format_func=lambda x: x[1],
                index=0
            )

            target_doc_type = DocType.INTERNAL if intent_choice[0] == DraftingIntent.PROPOSAL else DocType.EXTERNAL

            if st.button("🚀 AI ยกร่างหนังสือตามต้นเรื่องนี้", type="primary", use_container_width=True):
                with st.spinner("AI กำลังยกร่างโครงสร้าง 3 ภาคตามระเบียบงานสารบรรณ..."):
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
                    st.success("ยกร่างหนังสือราชการสำเร็จแล้ว! ตรวจสอบได้ที่ฝั่งขวา")

        # แสดงผลเอกสารต้นเรื่องและภาพพรีวิว
        if st.session_state.source_context:
            ctx = st.session_state.source_context
            st.markdown("---")
            st.markdown("#### 🔍 ข้อมูลที่สกัดได้จากเอกสารต้นเรื่อง")
            st.info(
                f"**ไฟล์:** {ctx.source_filename} ({'เอกสารสแกน' if ctx.is_scanned else 'ดิจิทัล'})\n\n"
                f"**หน่วยงานต้นเรื่อง:** {ctx.source_dept}\n\n"
                f"**เลขที่เดิม:** {ctx.source_doc_no or 'ไม่ระบุ'}\n\n"
                f"**วันที่เดิม:** {ctx.source_date or 'ไม่ระบุ'}\n\n"
                f"**เรื่องเดิม:** {ctx.source_subject or 'ไม่ระบุ'}"
            )

            if ctx.preview_image_path and os.path.exists(ctx.preview_image_path):
                st.image(ctx.preview_image_path, caption=f"ตัวอย่างหน้าเอกสารต้นเรื่อง: {ctx.source_filename}", use_container_width=True)

            with st.expander("📄 ดูข้อความที่สกัดได้ทั้งหมด (Extracted Text)", expanded=False):
                st.text_area("Raw Text", ctx.raw_text, height=220, disabled=True)
        else:
            st.info("💡 สามารถทดลองใช้งานด้วยข้อมูลตัวอย่าง หรือแนบไฟล์จริง (.pdf, .docx, .txt, .png)")

    # ----------------- คอลัมน์ขวา: ตัวตรวจแก้, Live Preview และ Diff -----------------
    with col_right:
        st.subheader("✍️ 2. ตรวจสอบ แก้ไข และดูตัวอย่างจริง")
        
        tab_editor, tab_preview, tab_diff = st.tabs([
            "✏️ ฟอร์มแก้ไขข้อความ", 
            "👁️ Live A4 Preview", 
            "📊 เปรียบเทียบการแก้ไข (Diff & Audit)"
        ])

        with tab_editor:
            # การควบคุมประเภทและชั้นความเร็ว/ความลับ
            c1, c2, c3, c4 = st.columns(4)
            with c1:
                st.session_state.doc_data.doc_type = st.selectbox(
                    "ประเภทหนังสือ",
                    options=[DocType.EXTERNAL, DocType.INTERNAL],
                    format_func=lambda x: "หนังสือภายนอก" if x == DocType.EXTERNAL else "หนังสือภายใน (บันทึกข้อความ)",
                    index=0 if st.session_state.doc_data.doc_type == DocType.EXTERNAL else 1
                )
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

            # เครื่องมือ Copilot ช่วยเกลาภาษาและแทรกระเบียบ
            st.markdown("###### 🤖 ผู้ช่วย AI Copilot ช่วยเกลาภาษาและแทรกข้อกฎหมาย")
            cp1, cp2, cp3, cp4 = st.columns(4)
            with cp1:
                if st.button("✍️ ปรับเป็นทางการขึ้น", use_container_width=True):
                    st.session_state.doc_data.paragraph_reason = make_formal_tone(st.session_state.doc_data.paragraph_reason)
                    st.session_state.doc_data.paragraph_purpose = make_formal_tone(st.session_state.doc_data.paragraph_purpose)
                    audit_mgr.log_action(st.session_state.doc_data.doc_number, "copilot_formal", "ผู้ใช้", {})
                    st.rerun()
            with cp2:
                if st.button("✂️ สรุปย่อให้กระชับ", use_container_width=True):
                    if st.session_state.doc_data.paragraph_details:
                        st.session_state.doc_data.paragraph_details = make_concise(st.session_state.doc_data.paragraph_details)
                    audit_mgr.log_action(st.session_state.doc_data.doc_number, "copilot_concise", "ผู้ใช้", {})
                    st.rerun()
            with cp3:
                if st.button("⚖️ อ้างอิงระเบียบสารบรรณ", use_container_width=True):
                    st.session_state.doc_data = insert_legal_reference(st.session_state.doc_data, "saraban")
                    audit_mgr.log_action(st.session_state.doc_data.doc_number, "insert_law_saraban", "ผู้ใช้", {})
                    st.rerun()
            with cp4:
                if st.button("🔄 แปลงภายนอก ↔ ภายใน", use_container_width=True):
                    target_t = DocType.INTERNAL if st.session_state.doc_data.doc_type == DocType.EXTERNAL else DocType.EXTERNAL
                    st.session_state.doc_data = convert_doc_type(st.session_state.doc_data, target_t)
                    st.rerun()

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

        # Tab พรีวิวหน้ากระดาษ A4 เสมือนจริง
        with tab_preview:
            doc = st.session_state.doc_data
            disp_date = to_thai_numerals(doc.doc_date) if doc.use_thai_numerals else doc.doc_date
            disp_no = to_thai_numerals(doc.doc_number) if doc.use_thai_numerals else doc.doc_number
            disp_reason = to_thai_numerals(doc.paragraph_reason) if doc.use_thai_numerals else doc.paragraph_reason
            disp_details = to_thai_numerals(doc.paragraph_details) if (doc.paragraph_details and doc.use_thai_numerals) else doc.paragraph_details
            disp_purpose = to_thai_numerals(doc.paragraph_purpose) if doc.use_thai_numerals else doc.paragraph_purpose

            # HTML A4 Preview Template
            if doc.doc_type == DocType.EXTERNAL:
                st.markdown(f"""
                <div class="a4-paper">
                    <div style="text-align: center; margin-bottom: 15px;">
                        <img src="data:image/png;base64,{garuda_b64}" style="height: 3.0cm; width: auto;" alt="ตราครุฑ 3 ซม." />
                    </div>
                    <div style="display: flex; justify-content: space-between; margin-bottom: 8px;">
                        <div style="width: 48%;">ที่  {disp_no}</div>
                        <div style="width: 48%;">{doc.dept_name}</div>
                    </div>
                    <div style="text-align: center; margin-left: 20%; margin-bottom: 15px;">
                        {disp_date}
                    </div>
                    <div style="margin-bottom: 15px;">
                        <p><strong>เรื่อง</strong>  {doc.subject}</p>
                        <p><strong>เรียน</strong>  {doc.salutation}</p>
                    </div>
                    <p class="a4-indent">{disp_reason}</p>
                    {f'<p class="a4-indent">{disp_details}</p>' if disp_details else ''}
                    <p class="a4-indent">{disp_purpose}</p>
                    <div style="text-align: center; margin-left: 45%; margin-top: 35px; margin-bottom: 40px;">
                        <p>{doc.closing}</p>
                        <div style="height: 45px;"></div>
                        <p>{doc.signatory_name}</p>
                        <p>{doc.signatory_position}</p>
                    </div>
                    <div style="font-size: 14pt; margin-top: 25px; color: #444;">
                        <p style="margin: 0;">{doc.contact_dept}</p>
                        <p style="margin: 0;">โทรศัพท์  {doc.contact_tel or ''}</p>
                        <p style="margin: 0;">อีเมล  {doc.contact_email or ''}</p>
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
                        <p><strong>ส่วนราชการ</strong>  {doc.dept_name}</p>
                        <div style="display: flex; justify-content: space-between;">
                            <div style="width: 48%;"><strong>ที่</strong>  {disp_no}</div>
                            <div style="width: 48%;"><strong>วันที่</strong>  {disp_date}</div>
                        </div>
                        <p><strong>เรื่อง</strong>  {doc.subject}</p>
                        <p><strong>เรียน</strong>  {doc.salutation}</p>
                    </div>
                    <hr style="border-top: 1px solid #ccc; margin-bottom: 15px;" />
                    <p class="a4-indent">{disp_reason}</p>
                    {f'<p class="a4-indent">{disp_details}</p>' if disp_details else ''}
                    <p class="a4-indent">{disp_purpose}</p>
                    <div style="text-align: center; margin-left: 45%; margin-top: 50px;">
                        <div style="height: 40px;"></div>
                        <p>{doc.signatory_name}</p>
                        <p>{doc.signatory_position}</p>
                    </div>
                </div>
                """, unsafe_allow_html=True)

        # Tab Diff & Versions
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

            # แสดงรายการเวอร์ชันที่บันทึกไว้
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

        # ส่งออกเอกสาร
        st.markdown("---")
        st.markdown("##### 🖨️ 3. ส่งออกและลงทะเบียนหนังสือ")
        exp_col1, exp_col2, exp_col3 = st.columns(3)

        with exp_col1:
            if st.button("📥 สร้างไฟล์ Word (.docx)", use_container_width=True, type="primary"):
                out_docx = str(uploads_dir / f"{st.session_state.doc_data.subject[:30]}.docx")
                export_govdoc_to_docx(st.session_state.doc_data, out_docx)
                audit_mgr.log_action(st.session_state.doc_data.doc_number, "export_docx", "ผู้ใช้", {"path": out_docx})
                with open(out_docx, "rb") as f:
                    st.download_button(
                        label="⬇️ ดาวน์โหลด .docx สวยงาม",
                        data=f.read(),
                        file_name=f"{st.session_state.doc_data.subject[:30]}.docx",
                        mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                        use_container_width=True
                    )

        with exp_col2:
            if st.button("📄 สร้างไฟล์ Typst (.typ)", use_container_width=True):
                out_typ = str(uploads_dir / f"{st.session_state.doc_data.subject[:30]}.typ")
                export_govdoc_to_typst(st.session_state.doc_data, out_typ)
                audit_mgr.log_action(st.session_state.doc_data.doc_number, "export_typst", "ผู้ใช้", {"path": out_typ})
                with open(out_typ, "rb") as f:
                    st.download_button(
                        label="⬇️ ดาวน์โหลดแม่แบบ Typst",
                        data=f.read(),
                        file_name=f"{st.session_state.doc_data.subject[:30]}.typ",
                        mime="text/plain",
                        use_container_width=True
                    )

        with exp_col3:
            if st.button("📚 บันทึกลงสมุดทะเบียนส่ง", use_container_width=True):
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


# =====================================================================
# TAB 2: E-DOCUMENT REGISTRY
# =====================================================================
with tab_registry:
    st.subheader("📖 สมุดทะเบียนคุมสารบรรณอิเล็กทรอนิกส์")
    
    # เมนูย่อย: ทะเบียนส่ง, ทะเบียนรับ, จองเลข
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
