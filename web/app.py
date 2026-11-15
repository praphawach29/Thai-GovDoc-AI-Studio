"""
app.py — หน้าจอใช้งานหลัก (Interactive Workspace) สำหรับ Thai GovDoc AI Studio
พัฒนาตามโมเดล Modern GovDoc Studio (Split-Screen Workspace, Compact Modern Typography, Smart Placeholders & A4 Canvas)
รันด้วย Streamlit: streamlit run web/app.py
"""

import os
import re
import sys
import html
import base64
import tempfile
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict, Any, Tuple

# เพิ่ม Root directory เข้า sys.path
root_dir = Path(__file__).resolve().parent.parent
if str(root_dir) not in sys.path:
    sys.path.insert(0, str(root_dir))

# รีเฟรชโมดูล core ทุกครั้งที่บันทึกไฟล์เพื่อป้องกัน Streamlit แคช sys.modules ตัวเก่า (เฉพาะเมื่อไม่ได้รันผ่าน pytest)
import importlib
if "pytest" not in sys.modules:
    for mod in [
        "core.models", "core.entity_extractor", "core.profile_manager",
        "core.extractor", "core.classifier", "core.templates_library",
        "core.linter", "core.memo_layout", "core.security",
        "core.ai_drafter", "core.word_exporter", "core.pdf_exporter",
        "core.sections", "core.intake", "core.legal_sources",
    ]:
        if mod in sys.modules:
            try:
                importlib.reload(sys.modules[mod])
            except Exception:
                pass

import streamlit as st

from core.classifier import DocumentKind, classify_source_document
from core.special_drafter import draft_special_from_context
from core.hierarchy import apply_hierarchy_role, build_hierarchy_chain, roles_from_profile
from core.sections import ensure_sections, sync_fields_from_sections
from core.layout_profile import get_layout_profile
from core.models import DocumentSection, is_blank_doc_number, GovDocumentSchema, DocType, SectionKind, UrgencyLevel, SecretLevel, SourceDocumentContext, MemoHierarchyLevel, UserProfileSchema, ExportOptions
from core.profile_manager import get_user_profile, save_user_profile, reset_to_default_profile
from core.extractor import extract_source_document, extract_from_raw_text
from core.ai_drafter import draft_from_context_rule_based, draft_from_context_llm, DraftingIntent
from core.templates_library import PRESET_TEMPLATES
from core.pdf_exporter import get_pdf_bytes, export_govdoc_to_pdf
from core.copilot import (
    make_formal_tone,
    make_concise,
    convert_doc_type,
    toggle_doc_numerals,
    copilot_refine_paragraph
)
from core.audit import AuditManager, compute_doc_diff
from core.word_exporter import export_govdoc_to_docx
from core.typst_exporter import export_govdoc_to_typst, generate_typst_content
from core.linter import lint_gov_document
from core.security import cloud_ai_allowed
from core.intake import assess_intake
from core.legal_sources import LegalLibrary, LegalReference, format_legal_citation
from core.verification import verify_draft_against_source
from core.text_checks import check_document_text
from core.registry import DocumentRegistry, OutgoingRecord
from core.thai_segmenter import to_thai_numerals, to_arabic_numerals
from core.thai_date import blank_doc_number, format_thai_date
from core.memo_layout import render_memo_blocks_html, split_consideration_and_request, SECTION_ORDER


st.set_page_config(
    page_title="Thai GovDoc AI Studio - ระบบร่างและผลิตหนังสือราชการไทยอัจฉริยะ",
    page_icon="🏛️",
    layout="wide",
    initial_sidebar_state="expanded"
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
    
    /* 7. Smart Placeholder Chip & Real-Time Clickable Buttons */
    .placeholder-chip {
        background-color: #fef3c7;
        color: #92400e;
        border: 1px dashed #d97706;
        padding: 1px 6px;
        border-radius: 4px;
        font-weight: 600;
        font-size: 0.90em;
        display: inline-block;
        margin: 0 2px;
        text-decoration: none !important;
    }
    .placeholder-chip-btn {
        background-color: #fef3c7;
        color: #92400e !important;
        border: 1px dashed #d97706;
        padding: 1px 7px;
        border-radius: 4px;
        font-weight: 600;
        font-size: 0.90em;
        display: inline-inline;
        margin: 0 2px;
        text-decoration: none !important;
        cursor: pointer;
        transition: all 0.18s ease;
    }
    .placeholder-chip-btn:hover {
        background-color: #fde68a !important;
        border-color: #b45309 !important;
        color: #78350f !important;
        box-shadow: 0 2px 6px rgba(217, 119, 6, 0.35) !important;
        transform: translateY(-1px);
    }
    .doc-pencil-btn {
        display: inline-flex;
        align-items: center;
        justify-content: center;
        background: #f1f5f9;
        color: #0284c7 !important;
        border: 1px solid #cbd5e1;
        border-radius: 4px;
        font-size: 11.5px;
        line-height: 1;
        padding: 2px 5px;
        margin-left: 6px;
        cursor: pointer;
        text-decoration: none !important;
        vertical-align: middle;
        box-shadow: 0 1px 2px rgba(0,0,0,0.06);
        transition: all 0.15s ease-in-out;
    }
    .doc-pencil-btn:hover {
        background: #e0f2fe !important;
        border-color: #38bdf8 !important;
        color: #0369a1 !important;
        transform: scale(1.12);
        box-shadow: 0 2px 5px rgba(2, 132, 199, 0.28) !important;
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
        font-family: 'TH Sarabun New', 'TH SarabunIT๙', 'TH Sarabun PSK', 'Sarabun', sans-serif !important;
        font-size: 14.5px !important;  /* เทียบเท่าขนาด 16pt ของจริง */
        line-height: 1.55 !important;
        color: #000000 !important;
        box-sizing: border-box !important;
    }
    .a4-paper p, .a4-paper div, .a4-paper span, .a4-paper td, .a4-paper strong {
        font-family: 'TH Sarabun New', 'TH SarabunIT๙', 'TH Sarabun PSK', 'Sarabun', sans-serif !important;
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

    /* 9. Modern Hero Ingestion Screen (Ekkasarn AI Aesthetic) */
    .hero-wrapper {
        display: flex;
        flex-direction: column;
        align-items: center;
        justify-content: center;
        max-width: 900px !important;
        margin: clamp(2.4rem, 8vh, 5rem) auto 0.8rem auto !important;
        text-align: center;
        position: relative;
        isolation: isolate;
    }
    .hero-wrapper::before {
        content: "";
        position: absolute;
        z-index: -1;
        width: min(78vw, 850px);
        height: 330px;
        top: 12px;
        left: 50%;
        transform: translateX(-50%);
        border-radius: 50%;
        background: radial-gradient(ellipse, rgba(207, 240, 244, 0.62) 0%, rgba(230, 246, 247, 0.36) 44%, rgba(255, 255, 255, 0) 76%);
        filter: blur(10px);
        pointer-events: none;
    }
    .hero-sparkle-icon {
        display: inline-flex;
        align-items: center;
        justify-content: center;
        width: 44px;
        height: 44px;
        background: linear-gradient(135deg, #ecfdf5 0%, #d1fae5 100%);
        border: 1px solid #a7f3d0;
        border-radius: 14px;
        margin-bottom: 0.6rem;
        box-shadow: 0 4px 12px rgba(16, 185, 129, 0.16);
    }
    .hero-title {
        font-size: clamp(2.1rem, 3.3vw, 3.05rem) !important;
        font-weight: 700 !important;
        color: #0f172a !important;
        margin-bottom: 0.35rem !important;
        letter-spacing: -0.02em !important;
        font-family: 'Sarabun', sans-serif !important;
        line-height: 1.25 !important;
    }
    .hero-subtitle {
        font-size: 1.08rem !important;
        color: #64748b !important;
        margin-bottom: 1.2rem !important;
        font-weight: 400 !important;
    }
    .hero-card-wrapper {
        background: #ffffff;
        border: 1.5px solid #e2e8f0;
        border-radius: 16px;
        padding: 16px 20px;
        box-shadow: 0 4px 20px -2px rgba(15, 23, 42, 0.06);
        max-width: 680px;
        margin: 0 auto;
        transition: all 0.2s ease;
    }
    .st-key-hero_composer,
    div[data-testid="stLayoutWrapper"]:has(> .st-key-hero_composer),
    div:has(> .st-key-hero_composer) {
        max-width: 960px !important;
        width: 100% !important;
        margin-left: auto !important;
        margin-right: auto !important;
    }
    .st-key-hero_composer {
        border-radius: 20px !important;
        border: 1px solid #d7dee7 !important;
        box-shadow: 0 18px 44px -24px rgba(15, 23, 42, 0.22) !important;
        padding: 18px 20px 10px 20px !important;
        background: rgba(246, 248, 250, 0.94) !important;
        transition: all 0.2s ease !important;
    }
    .st-key-hero_composer:focus-within {
        border-color: #a8c6c9 !important;
        box-shadow: 0 0 0 3px rgba(13, 148, 136, 0.08), 0 18px 44px -24px rgba(15, 23, 42, 0.22) !important;
    }
    .st-key-hero_composer div[data-baseweb="textarea"],
    .st-key-hero_composer div[data-baseweb="base-input"] {
        background: transparent !important;
        border: none !important;
        box-shadow: none !important;
        padding: 0 !important;
    }
    .st-key-hero_composer textarea {
        border: none !important;
        box-shadow: none !important;
        background: transparent !important;
        font-size: 0.95rem !important;
        line-height: 1.55 !important;
        padding: 2px 0 !important;
        color: #1e293b !important;
        resize: none !important;
        min-height: 100px !important;
        height: 112px !important;
    }
    .st-key-hero_composer textarea:focus {
        border: none !important;
        box-shadow: none !important;
        outline: none !important;
    }
    .st-key-hero_composer textarea::placeholder {
        color: #788391 !important;
        font-size: 0.92rem !important;
    }
    .st-key-hero_composer label {
        display: none !important;
    }
    .st-key-hero_composer [data-testid="stHorizontalBlock"] {
        border-top: 1px solid #e8edf2 !important;
        background: rgba(248, 250, 252, 0.88) !important;
        border-radius: 0 0 18px 18px !important;
        padding: 8px 6px 0 !important;
        margin-top: 8px !important;
    }
    .st-key-hero_composer [data-testid="stPopover"] button {
        width: 42px !important;
        min-width: 42px !important;
        height: 42px !important;
        min-height: 42px !important;
        padding: 0 !important;
        border: 0 !important;
        border-radius: 8px !important;
        background: transparent !important;
        color: #475569 !important;
        font-size: 0 !important;
        position: relative !important;
    }
    .st-key-hero_composer [data-testid="stPopover"] button > * {
        opacity: 0 !important;
    }
    .st-key-hero_composer [data-testid="stPopover"] button::before {
        content: "";
        visibility: visible !important;
        display: block !important;
        position: absolute !important;
        left: 50% !important;
        top: 50% !important;
        transform: translate(-50%, -50%) !important;
        width: 23px !important;
        height: 23px !important;
        background-color: #475569 !important;
        -webkit-mask: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='%23000' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'%3E%3Cpath d='m21.44 11.05-9.19 9.19a6 6 0 0 1-8.49-8.49l9.19-9.19a4 4 0 0 1 5.66 5.66l-9.2 9.19a2 2 0 0 1-2.83-2.83l8.49-8.48'/%3E%3C/svg%3E") center / contain no-repeat !important;
        mask: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='%23000' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'%3E%3Cpath d='m21.44 11.05-9.19 9.19a6 6 0 0 1-8.49-8.49l9.19-9.19a4 4 0 0 1 5.66 5.66l-9.2 9.19a2 2 0 0 1-2.83-2.83l8.49-8.48'/%3E%3C/svg%3E") center / contain no-repeat !important;
    }
    .st-key-hero_composer [data-testid="stPopover"] button:hover {
        border: 0 !important;
        background: #e9eff2 !important;
    }
    .st-key-hero_composer [data-testid="stBaseButton-primary"] {
        width: 44px !important;
        min-width: 44px !important;
        min-height: 44px !important;
        height: 44px !important;
        padding: 0 !important;
        border-radius: 12px !important;
        font-size: 1.25rem !important;
        font-weight: 600 !important;
        background: #0b192c !important;
        color: #ffffff !important;
        border: 0 !important;
        white-space: nowrap !important;
        position: relative !important;
        letter-spacing: 0.01em !important;
        box-shadow: 0 2px 8px rgba(15, 23, 42, 0.12) !important;
    }
    .st-key-hero_composer [data-testid="stBaseButton-primary"]:hover {
        background: #0f766e !important;
        box-shadow: 0 4px 12px rgba(15, 23, 42, 0.20) !important;
    }
    .st-key-hero_composer [data-testid="stBaseButton-primary"]:disabled {
        background: #64748b !important;
        color: #ffffff !important;
        opacity: 1 !important;
        cursor: not-allowed !important;
        box-shadow: none !important;
    }
    .st-key-hero_composer [data-testid="stBaseButton-primary"] p {
        visibility: hidden !important;
    }
    .st-key-hero_composer [data-testid="stBaseButton-primary"]::before {
        content: "↑";
        position: absolute !important;
        left: 50% !important;
        top: 50% !important;
        transform: translate(-50%, -52%) !important;
        font-size: 1.35rem !important;
        line-height: 1 !important;
    }

    /* Starter Pills Container */
    .st-key-hero_pills,
    div[data-testid="stLayoutWrapper"]:has(> .st-key-hero_pills),
    div:has(> .st-key-hero_pills) {
        max-width: 900px !important;
        width: 100% !important;
        margin-left: auto !important;
        margin-right: auto !important;
    }
    .st-key-hero_pills [data-testid="column"] {
        padding: 0 3px !important;
    }
    .st-key-hero_pills button {
        border-radius: 9999px !important;
        border: 1px solid #e2e8f0 !important;
        background: #ffffff !important;
        color: #334155 !important;
        font-size: 0.86rem !important;
        font-weight: 500 !important;
        min-height: 40px !important;
        height: 40px !important;
        padding: 0 10px !important;
        white-space: nowrap !important;
        box-shadow: 0 1px 2px rgba(0, 0, 0, 0.02) !important;
        transition: all 0.15s ease !important;
    }
    .st-key-hero_pills button:hover {
        border-color: #10b981 !important;
        color: #047857 !important;
        background: #ecfdf5 !important;
        box-shadow: 0 2px 8px rgba(16, 185, 129, 0.12) !important;
        transform: translateY(-1px) !important;
    }
    .govdoc-topbar {
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 16px;
        min-height: 48px;
        margin: -0.9rem -1.8rem 0;
        padding: 8px 2rem;
        border-bottom: 1px solid #edf1f5;
        background: rgba(255, 255, 255, 0.92);
    }
    .govdoc-topbar-crumbs,
    .govdoc-topbar-status {
        display: flex;
        align-items: center;
        gap: 10px;
        font-size: 0.78rem !important;
    }
    .govdoc-topbar-crumbs { color: #94a3b8; }
    .govdoc-topbar-crumbs strong { color: #334155; font-weight: 500; }
    .govdoc-topbar-status {
        padding: 5px 10px;
        border: 1px solid #dbe5ea;
        border-radius: 8px;
        color: #64748b;
        background: #f8fafc;
        white-space: nowrap;
    }
    .govdoc-topbar-status::before {
        content: "";
        width: 8px;
        height: 8px;
        border-radius: 50%;
        background: #0d9488;
        box-shadow: 0 0 0 3px #ccfbef;
    }
    .hero-card-wrapper:focus-within {
        border-color: #10b981;
        box-shadow: 0 0 0 3px rgba(16, 185, 129, 0.12), 0 6px 28px rgba(15, 23, 42, 0.08);
    }
    .sidebar-user-card {
        display: flex;
        align-items: center;
        gap: 10px;
        padding: 10px 12px;
        background: #f8fafc;
        border: 1px solid #e2e8f0;
        border-radius: 10px;
        margin-top: 1.8rem;
    }
    .user-avatar-circle {
        width: 36px;
        height: 36px;
        border-radius: 50%;
        background: linear-gradient(135deg, #0f766e 0%, #14b8a6 100%);
        color: #ffffff;
        display: flex;
        align-items: center;
        justify-content: center;
        font-weight: 700;
        font-size: 0.85rem;
        flex-shrink: 0;
        box-shadow: 0 2px 5px rgba(15, 118, 110, 0.25);
    }
    .workspace-top-bar {
        display: flex;
        align-items: center;
        justify-content: space-between;
        background: #ffffff;
        border: 1px solid #e2e8f0;
        border-radius: 8px;
        padding: 6px 14px;
        margin-bottom: 0.7rem;
        box-shadow: 0 1px 3px rgba(0, 0, 0, 0.02);
    }
    .compact-action-bar {
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 8px;
        margin-bottom: 6px;
        padding-bottom: 6px;
        border-bottom: 1px solid #f1f5f9;
    }


    /* 10. Chat-style sidebar */
    section[data-testid="stSidebar"] {
        background: #f8fafc;
        border-right: 1px solid #e2e8f0;
    }
    section[data-testid="stSidebar"] [data-testid="stSidebarContent"] {
        padding-top: 1.0rem;
    }
    section[data-testid="stSidebar"] div[role="radiogroup"] {
        gap: 2px;
    }
    section[data-testid="stSidebar"] div[role="radiogroup"] > label {
        padding: 7px 10px;
        border-radius: 9px;
        transition: background 0.15s ease;
        cursor: pointer;
    }
    section[data-testid="stSidebar"] div[role="radiogroup"] > label:hover {
        background: #eef2f7;
    }
    section[data-testid="stSidebar"] div[role="radiogroup"] > label:has(input:checked) {
        background: #ecfdf5;
    }
    section[data-testid="stSidebar"] div[role="radiogroup"] > label > div:first-child {
        display: none;
    }
    section[data-testid="stSidebar"] div[role="radiogroup"] > label p {
        font-size: 0.90rem !important;
        font-weight: 500 !important;
        color: #334155 !important;
    }
    section[data-testid="stSidebar"] div[data-testid="stTextInput"] input {
        border-radius: 9999px !important;
        background: #ffffff !important;
        border: 1px solid #e2e8f0 !important;
        font-size: 0.82rem !important;
        padding-left: 14px !important;
    }
    section[data-testid="stSidebar"] div[data-testid="stBaseButton-secondary"] {
        justify-content: flex-start !important;
        text-align: left !important;
        background: transparent !important;
        border: none !important;
        padding: 6px 8px !important;
        font-size: 0.84rem !important;
        color: #334155 !important;
    }
    section[data-testid="stSidebar"] div[data-testid="stBaseButton-secondary"]:hover {
        background: #eef2f7 !important;
    }
    section[data-testid="stSidebar"] div[data-testid="stBaseButton-primary"] {
        border-radius: 10px !important;
        background: #0f172a !important;
    }

    /* 11. Hero polish - helper overrides */
    .st-key-hero_composer [data-testid="stBaseButton-primary"] {
        overflow: visible !important;
        text-overflow: clip !important;
    }
    button:focus-visible,
    textarea:focus-visible,
    input:focus-visible,
    select:focus-visible,
    section[data-testid="stSidebar"] label:focus-within {
        outline: 3px solid #0f766e !important;
        outline-offset: 2px !important;
    }
    @media (max-width: 768px) {
        .block-container {
            padding-left: 0.8rem !important;
            padding-right: 0.8rem !important;
        }
        .hero-title {
            font-size: 1.55rem !important;
        }
        .hero-subtitle {
            font-size: 0.9rem !important;
        }
        .st-key-hero_composer {
            padding: 10px !important;
        }
        .govdoc-topbar {
            margin-left: -0.8rem;
            margin-right: -0.8rem;
            padding-left: 0.8rem;
            padding-right: 0.8rem;
        }
        .govdoc-topbar-status {
            font-size: 0.68rem !important;
        }
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


def compact_html(html: str) -> str:
    """ตัด indent ต้นบรรทัดของ HTML เพื่อไม่ให้ Streamlit ตีความเป็น code block"""
    return "\n".join(line.lstrip() for line in html.splitlines()).strip()


def highlight_placeholders_html(text: str, clickable: bool = True, default_target: Optional[str] = None) -> str:
    """
    ตรวจจับ [ระบุ...], [✏️ ระบุ...] หรือ {{...}} แล้วครอบด้วยปุ่มหรือชิป
    เมื่อ clickable=True จะเป็นปุ่มลิงก์ที่คลิกแล้วเปิดป็อปอัป Modal Dialog ทันทีโดยไม่ต้องสลับแท็บ
    """
    if not text:
        return ""
    import urllib.parse
    def repl(m):
        raw = m.group(0)
        clean = raw.strip("[]{}").replace("✏️", "").strip()
        if not clickable:
            return f'<span class="placeholder-chip">✏️ {clean}</span>'
        target = default_target
        if not target:
            if any(k in clean for k in ("เรื่อง", "ที่", "วัน", "เรียน", "ส่วนราชการ", "ผู้บังคับบัญชา")):
                target = "header"
            elif any(k in clean for k in ("ต้นเรื่อง", "เหตุ", "ความเดิม")):
                target = "intro"
            elif any(k in clean for k in ("ข้อเท็จจริง", "โครงการ", "กิจกรรม", "รายละเอียด")):
                target = "facts"
            elif any(k in clean for k in ("กฎหมาย", "ระเบียบ", "มาตรา", "ข้อบังคับ")):
                target = "law"
            elif any(k in clean for k in ("พิจารณา", "เสนอแนะ", "โปรด", "ลงนาม")):
                target = "consideration"
            elif any(k in clean for k in ("ผู้ลงนาม", "ตำแหน่ง", "ชื่อ")):
                target = "signatory"
            elif any(k in clean for k in ("โทร", "ติดต่อ", "กลุ่มงาน", "อีเมล")):
                target = "contact"
            else:
                target = "placeholders"
        encoded_ph = urllib.parse.quote(clean)
        return f'<a href="?edit={target}&ph={encoded_ph}" target="_self" class="placeholder-chip-btn" title="คลิกเพื่อแก้ไขจุดนี้ทันที (ป็อปอัปเรียลไทม์)">✏️ {clean}</a>'
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


def audit_doc_id(doc: GovDocumentSchema) -> str:
    """ใช้เลขที่หนังสือเป็นรหัส audit; ถ้ายังเป็น placeholder ให้ใช้รหัสชั่วคราวต่อ session"""
    number = (doc.doc_number or "").strip()
    if number and not is_blank_doc_number(number):
        return number
    if "draft_uid" not in st.session_state:
        st.session_state.draft_uid = f"draft-{uuid.uuid4().hex[:8]}"
    return st.session_state.draft_uid


def get_typst_bytes(doc_schema: GovDocumentSchema) -> bytes:
    """สร้างไฟล์ Typst .typ และส่งออกเป็น bytes สำหรับดาวน์โหลดใน 1 คลิก"""
    content = generate_typst_content(doc_schema)
    return content.encode("utf-8")

# ----------------- MODAL DIALOGS สำหรับปุ่มดินสอแก้ไขด่วนตามหัวข้อ (REAL-TIME MODAL DIALOGS) -----------------

def _persist_pencil_doc(doc: GovDocumentSchema, summary: str = "แก้ไขเนื้อหาแบบเรียลไทม์") -> None:
    """บันทึก doc กลับ session, อัปเดตสถานะการแก้ไข ซิงก์ sections และบันทึก audit trail"""
    from datetime import datetime
    doc.edit_status = "saved"
    doc.last_edited_at = datetime.now()
    if doc.sections is not None:
        sync_fields_from_sections(doc)
    st.session_state.doc_data = doc
    try:
        audit_mgr.record_event(
            audit_doc_id(doc),
            "realtime_pencil_edit",
            f"{summary} เมื่อ {doc.last_edited_at.strftime('%H:%M:%S')}",
        )
    except Exception:
        pass


@st.dialog("✏️ แก้ไขข้อมูลส่วนหัวหนังสือ", width="large")
def edit_header_dialog():
    doc = st.session_state.doc_data
    st.caption("แก้ไขข้อมูลส่วนราชการ เลขที่ วันที่ ชื่อเรื่อง คำขึ้นต้น และเอกสารแนบ (อัปเดตหน้าพรีวิวเรียลไทม์)")
    
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
            _persist_pencil_doc(doc, "แก้ไขส่วนหัวหนังสือ")
            st.toast("✅ บันทึกส่วนหัวหนังสือและอัปเดตหน้าเอกสารเรียลไทม์แล้ว!", icon="💾")
            st.rerun()
    with col_cancel:
        if st.button("ปิดหน้าต่าง", key="close_dlg_hdr", use_container_width=True):
            st.rerun()


@st.dialog("✏️ แก้ไขเนื้อความ: ๑. ต้นเรื่อง", width="large")
def edit_intro_dialog():
    doc = st.session_state.doc_data
    current_val = doc.memo_intro or doc.paragraph_reason or ""
    st.caption("ระบุความเป็นมา การขอความอนุเคราะห์ คำร้อง หรือหนังสือที่ส่งเข้ามา (อัปเดตหน้าพรีวิวเรียลไทม์)")
    
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
            _persist_pencil_doc(doc, "แก้ไข ๑. ต้นเรื่อง")
            st.toast("✅ บันทึกต้นเรื่องและอัปเดตหน้าเอกสารเรียลไทม์แล้ว!", icon="💾")
            st.rerun()
    with col_cancel:
        if st.button("ปิดหน้าต่าง", key="close_dlg_intro", use_container_width=True):
            st.rerun()


@st.dialog("✏️ แก้ไขเนื้อความ: ๒. ข้อเท็จจริง", width="large")
def edit_facts_dialog():
    doc = st.session_state.doc_data
    current_val = doc.memo_facts or doc.paragraph_details or ""
    st.caption("ระบุรายละเอียดข้อเท็จจริงจากการตรวจสอบ ข้อมูลโครงการ วัน เวลา สถานที่ และผู้เข้าร่วม (อัปเดตหน้าพรีวิวเรียลไทม์)")
    
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
            _persist_pencil_doc(doc, "แก้ไข ๒. ข้อเท็จจริง")
            st.toast("✅ บันทึกข้อเท็จจริงและอัปเดตหน้าเอกสารเรียลไทม์แล้ว!", icon="💾")
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
            _persist_pencil_doc(doc, "แก้ไข ๓. ข้อกฎหมาย")
            st.toast("✅ บันทึกข้อกฎหมายและอัปเดตหน้าเอกสารเรียลไทม์แล้ว!", icon="💾")
            st.rerun()
    with col_clear:
        if st.button("🗑️ ลบ/ไม่ระบุกฎหมาย", key="clear_dlg_law", use_container_width=True):
            doc.memo_law = None
            _persist_pencil_doc(doc, "ลบข้อกฎหมาย (จัดเป็นแบบ ๓ หัวข้อ)")
            st.toast("ลบข้อกฎหมายเรียบร้อย (ระบบจะจัดเรียง ๓ หัวข้อให้อัตโนมัติ)", icon="🗑️")
            st.rerun()
    with col_cancel:
        if st.button("ปิดหน้าต่าง", key="close_dlg_law", use_container_width=True):
            st.rerun()


@st.dialog("✏️ แก้ไขเนื้อความ: ๔. ข้อพิจารณาและเสนอแนะ", width="large")
def edit_consideration_dialog():
    doc = st.session_state.doc_data
    current_val = doc.memo_consideration or doc.paragraph_purpose or ""
    st.caption("รวมข้อพิจารณาและข้อเสนอแนะไว้ในย่อหน้าเดียวกัน พร้อมประโยคลงท้ายเสนอผู้บังคับบัญชา (อัปเดตหน้าพรีวิวเรียลไทม์)")
    
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
            _persist_pencil_doc(doc, "แก้ไข ๔. ข้อพิจารณาและเสนอแนะ")
            st.toast("✅ บันทึกข้อพิจารณาและอัปเดตหน้าเอกสารเรียลไทม์แล้ว!", icon="💾")
            st.rerun()
    with col_cancel:
        if st.button("ปิดหน้าต่าง", key="close_dlg_cons", use_container_width=True):
            st.rerun()


@st.dialog("✏️ แก้ไขข้อมูลผู้ลงนามและลายมือชื่อ", width="medium")
def edit_signatory_dialog():
    doc = st.session_state.doc_data
    st.caption("แก้ไขชื่อเต็ม ตำแหน่งผู้ลงนาม และจัดการลายมือชื่อดิจิทัล (อัปเดตหน้าพรีวิวเรียลไทม์)")
    
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
            _persist_pencil_doc(doc, "แก้ไขข้อมูลผู้ลงนาม")
            st.toast("✅ บันทึกข้อมูลผู้ลงนามและอัปเดตหน้าเอกสารเรียลไทม์แล้ว!", icon="💾")
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
            _persist_pencil_doc(doc, "แก้ไขข้อมูลติดต่อ")
            st.toast("✅ บันทึกข้อมูลติดต่อและอัปเดตหน้าเอกสารเรียลไทม์แล้ว!", icon="💾")
            st.rerun()
    with col_cancel:
        if st.button("ปิดหน้าต่าง", key="close_dlg_contact", use_container_width=True):
            st.rerun()


@st.dialog("✏️ เติมข้อมูลจุดที่ต้องระบุ (Smart Placeholders)", width="medium")
def edit_placeholders_dialog(focus_ph: Optional[str] = None):
    doc = st.session_state.doc_data
    placeholders = doc.find_placeholders()
    if not placeholders:
        st.info("ไม่พบจุดที่ต้องระบุข้อมูลเพิ่มเติมในเอกสารนี้แล้วครับ")
        if st.button("ปิด"):
            st.rerun()
        return

    st.caption("กรอกข้อมูลเพื่อแทนที่เครื่องหมาย [✏️ ระบุ...] ในเอกสารทันทีแบบเรียลไทม์")
    unique_phs = list(dict.fromkeys([p[1] for p in placeholders]))
    replacements = {}
    
    for i, ph in enumerate(unique_phs):
        label = ph.replace("[✏️", "").replace("[", "").replace("]", "").strip()
        is_highlighted = focus_ph and (focus_ph in label or label in focus_ph)
        prompt_label = f"⭐ เติมข้อมูล: {label} (จุดที่คุณคลิก)" if is_highlighted else f"เติมข้อมูล: {label}"
        replacements[ph] = st.text_input(prompt_label, key=f"ph_fill_input_{i}")

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

        _persist_pencil_doc(doc, "เติมข้อมูลจุดที่ต้องระบุ")
        st.toast("✅ แทนที่ข้อมูลและอัปเดตหน้าเอกสารเรียลไทม์แล้ว!", icon="💾")
        st.rerun()


@st.dialog("✏️ แก้ไขเนื้อหาหัวข้อ", width="large")
def edit_section_dialog(section_id_or_idx: str):
    doc = st.session_state.doc_data
    if not doc.sections:
        st.error("ไม่พบรายการหัวข้อ")
        return
    sec = None
    for s in doc.sections:
        if str(s.id) == str(section_id_or_idx):
            sec = s
            break
    if not sec:
        try:
            idx = int(section_id_or_idx)
            if 0 <= idx < len(doc.sections):
                sec = doc.sections[idx]
        except ValueError:
            pass
    if not sec:
        st.error("ไม่พบหัวข้อที่ต้องการแก้ไข")
        return

    sec_title = sec.label or sec.kind.default_label()
    st.caption(f"แก้ไขหัวข้อ: {sec_title} (อัปเดตหน้าพรีวิวเรียลไทม์)")
    new_label = st.text_input("ชื่อหัวข้อ", value=sec_title, key=f"dlg_sec_label_{sec.id}")
    new_content = st.text_area("เนื้อความ", value=sec.content or "", height=160, key=f"dlg_sec_content_{sec.id}")
    new_sec = None
    if sec.kind in (SectionKind.NUMBER_DATE, SectionKind.SIGNATURE):
        new_sec = st.text_input("ข้อมูลประกอบ (เช่น วันที่ หรือ ตำแหน่ง)", value=sec.secondary or "", key=f"dlg_sec_sec_{sec.id}")

    col_save, col_cancel = st.columns([2, 1])
    with col_save:
        if st.button("💾 บันทึกหัวข้อ", key=f"save_dlg_sec_{sec.id}", type="primary", use_container_width=True):
            sec.label = new_label.strip()
            sec.content = new_content.strip()
            if new_sec is not None:
                sec.secondary = new_sec.strip()
            _persist_pencil_doc(doc, f"แก้ไขหัวข้อ {sec.label}")
            st.toast("✅ บันทึกหัวข้อและอัปเดตหน้าเอกสารเรียลไทม์แล้ว!", icon="💾")
            st.rerun()
    with col_cancel:
        if st.button("ปิดหน้าต่าง", key=f"close_dlg_sec_{sec.id}", use_container_width=True):
            st.rerun()


def render_memo_pencils(doc: GovDocumentSchema) -> None:
    """แถบปุ่มดินสอแก้ไขด่วนด้านบนหน้ากระดาษ — กดแล้วเปิดป็อปอัป Modal Dialog กลางจอทันที"""
    cols = st.columns(6, gap="small")
    with cols[0]:
        if st.button("✏️ หัวหนังสือ", key="btn_dlg_header", use_container_width=True, help="คลิกเพื่อเปิดป็อปอัปแก้ไข ส่วนราชการ, ที่, วันที่, เรื่อง, เรียน"):
            edit_header_dialog()
    with cols[1]:
        if st.button("✏️ ๑. ต้นเรื่อง", key="btn_dlg_intro", use_container_width=True, help="คลิกเพื่อเปิดป็อปอัปแก้ไข ๑. ต้นเรื่อง พร้อม AI เกลาสำนวน"):
            edit_intro_dialog()
    with cols[2]:
        if st.button("✏️ ๒. ข้อเท็จจริง", key="btn_dlg_facts", use_container_width=True, help="คลิกเพื่อเปิดป็อปอัปแก้ไข ๒. ข้อเท็จจริง พร้อม AI เกลาสำนวน"):
            edit_facts_dialog()
    with cols[3]:
        has_law = bool(doc.memo_law and doc.memo_law.strip())
        law_label = "✏️ ๓. ข้อกฎหมาย" if has_law else "➕ ๓. ข้อกฎหมาย"
        if st.button(law_label, key="btn_dlg_law", use_container_width=True, help="คลิกเพื่อเปิดป็อปอัปแทรกหรือแก้ไขข้อกฎหมาย/ระเบียบ"):
            edit_law_dialog()
    with cols[4]:
        if st.button("✏️ ๔. ข้อพิจารณา", key="btn_dlg_consideration", use_container_width=True, help="คลิกเพื่อเปิดป็อปอัปแก้ไข ข้อพิจารณาและประโยคลงท้ายตามระดับชั้น"):
            edit_consideration_dialog()
    with cols[5]:
        if st.button("✏️ ผู้ลงนาม", key="btn_dlg_signatory", use_container_width=True, help="คลิกเพื่อเปิดป็อปอัปแก้ไข ชื่อ ตำแหน่ง และลายมือชื่อดิจิทัล"):
            edit_signatory_dialog()


def render_external_pencils(doc: GovDocumentSchema) -> None:
    """แถบปุ่มดินสอด้านบนหน้ากระดาษสำหรับหนังสือภายนอก — กดแล้วเปิด Modal Dialog กลางจอ"""
    cols = st.columns(6, gap="small")
    with cols[0]:
        if st.button("✏️ หัวหนังสือ", key="btn_dlg_ext_header", use_container_width=True):
            edit_header_dialog()
    with cols[1]:
        if st.button("✏️ ภาคเหตุ", key="btn_dlg_ext_reason", use_container_width=True):
            edit_intro_dialog()
    with cols[2]:
        if st.button("✏️ ภาคข้อเท็จจริง", key="btn_dlg_ext_details", use_container_width=True):
            edit_facts_dialog()
    with cols[3]:
        if st.button("✏️ ภาคความประสงค์", key="btn_dlg_ext_purpose", use_container_width=True):
            edit_consideration_dialog()
    with cols[4]:
        if st.button("✏️ ผู้ลงนาม", key="btn_dlg_ext_sig", use_container_width=True):
            edit_signatory_dialog()
    with cols[5]:
        if st.button("✏️ ข้อมูลติดต่อ", key="btn_dlg_ext_contact", use_container_width=True):
            edit_contact_dialog()



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
        doc_number=blank_doc_number(use_thai_numerals=False),
        dept_name=current_profile.department_full,
        doc_date=format_thai_date(use_thai_numerals=False),
        subject="[✏️ ระบุเรื่อง]",
        salutation="เรียน  ผู้อำนวยการสำนักวัฒนธรรม กีฬา และการท่องเที่ยว",
        references=None,
        attachments=None,
        paragraph_reason="[✏️ ระบุต้นเรื่อง/ภาคเหตุ]",
        paragraph_details="[✏️ ระบุข้อเท็จจริงและข้อพิจารณา]",
        paragraph_purpose="[✏️ ระบุภาคความประสงค์]",
        memo_intro="[✏️ ระบุต้นเรื่อง]",
        memo_facts="[✏️ ระบุข้อเท็จจริง]",
        memo_law=None,
        memo_consideration="[✏️ ระบุข้อพิจารณาและเสนอแนะ]",
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

if "doc_secret_level" not in st.session_state:
    st.session_state.doc_secret_level = SecretLevel.NORMAL

if "include_law" not in st.session_state:
    st.session_state.include_law = False
if "include_references" not in st.session_state:
    st.session_state.include_references = False
if "include_attachments" not in st.session_state:
    st.session_state.include_attachments = False
if "intake_answers" not in st.session_state:
    st.session_state.intake_answers = {}
if "intake_ready" not in st.session_state:
    st.session_state.intake_ready = True
if "selected_law_id" not in st.session_state:
    st.session_state.selected_law_id = None


# ส่วนหัวหน้าเว็บแบบ Compact Modern Top Bar


def create_blank_memo(profile: UserProfileSchema) -> GovDocumentSchema:
    return GovDocumentSchema(
        doc_type=DocType.INTERNAL,
        urgency=UrgencyLevel.NORMAL,
        secret=SecretLevel.NORMAL,
        use_thai_numerals=False,
        doc_number=blank_doc_number(use_thai_numerals=False),
        dept_name=profile.department_full,
        doc_date=format_thai_date(use_thai_numerals=False),
        subject="[✏️ ระบุเรื่อง]",
        salutation=f"เรียน  {profile.dept_name or 'ผู้อำนวยการสำนักวัฒนธรรม กีฬา และการท่องเที่ยว'}",
        references=None,
        attachments=None,
        paragraph_reason="[✏️ ระบุต้นเรื่อง]",
        paragraph_details="[✏️ ระบุข้อเท็จจริง]",
        paragraph_purpose="[✏️ ระบุข้อพิจารณาและเสนอแนะ]",
        memo_intro="[✏️ ระบุต้นเรื่อง]",
        memo_facts="[✏️ ระบุข้อเท็จจริง]",
        memo_law=None,
        memo_consideration="[✏️ ระบุข้อพิจารณาและเสนอแนะ]",
        memo_request="จึงเรียนมาเพื่อโปรดพิจารณาลงนามหนังสือเรียนปลัดกรุงเทพมหานครที่แนบ",
        memo_hierarchy_level=MemoHierarchyLevel.DIV_TO_DEPT,
        closing="",
        signatory_name=profile.signatory_name,
        signatory_position=profile.signatory_position,
        contact_dept=profile.contact_dept,
        contact_tel=profile.contact_tel,
        contact_fax=profile.contact_fax,
        contact_email=profile.contact_email
    )


def create_blank_external(profile: UserProfileSchema) -> GovDocumentSchema:
    return GovDocumentSchema(
        doc_type=DocType.EXTERNAL,
        urgency=UrgencyLevel.NORMAL,
        secret=SecretLevel.NORMAL,
        use_thai_numerals=False,
        doc_number=blank_doc_number(use_thai_numerals=False),
        dept_name=profile.department_full,
        doc_date=format_thai_date(use_thai_numerals=False),
        subject="[✏️ ระบุเรื่อง]",
        salutation="เรียน  [✏️ ระบุชื่อผู้รับหนังสือภายนอก]",
        references=None,
        attachments=None,
        paragraph_reason="[✏️ ระบุภาคเหตุ]",
        paragraph_details="[✏️ ระบุภาคข้อเท็จจริง]",
        paragraph_purpose="[✏️ ระบุภาคความประสงค์]",
        memo_intro="[✏️ ระบุภาคเหตุ]",
        memo_facts="[✏️ ระบุภาคข้อเท็จจริง]",
        memo_law=None,
        memo_consideration="[✏️ ระบุภาคความประสงค์]",
        memo_request="",
        closing="ขอแสดงความนับถือ",
        signatory_name=profile.signatory_name,
        signatory_position=profile.signatory_position,
        contact_dept=profile.contact_dept,
        contact_tel=profile.contact_tel,
        contact_fax=profile.contact_fax,
        contact_email=profile.contact_email
    )

if "has_active_draft" not in st.session_state:
    st.session_state.has_active_draft = False

if "nav_selection" not in st.session_state:
    st.session_state.nav_selection = "📝 ห้องร่างหนังสือ"

if "export_options" not in st.session_state or not hasattr(st.session_state.export_options, "layout_profile"):
    st.session_state.export_options = ExportOptions()




def render_templates_view():
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
            doc_id=audit_doc_id(curr_tmpl.schema),
            doc=curr_tmpl.schema,
            author="Preset Template",
            note=f"โหลดจากแบบฟอร์มมาตรฐาน: {curr_tmpl.title}"
        )
        st.session_state.has_active_draft = True
        st.session_state.nav_selection = "📝 ห้องร่างหนังสือ"
        st.success(f"โหลดแบบฟอร์ม '{curr_tmpl.title}' เรียบร้อยแล้ว!")
        st.rerun()



def render_registry_view():
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




def render_profile_view():
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

    st.markdown("---")
    st.markdown("##### 📚 คลังข้อกฎหมาย/ระเบียบ (เพิ่ม/แก้ไข + สถานะตรวจยืนยัน)")
    st.caption("รายการที่ยืนยันแล้วเท่านั้นจึงจะเลือกใช้ในการร่างได้ — ระบบจะไม่ใส่ข้อกฎหมายที่ไม่มีแหล่งยืนยัน")
    _law_lib = LegalLibrary()
    _law_items = _law_lib.list()
    if _law_items:
        for _r in _law_items:
            _law_status = "✅ ยืนยันแล้ว" if _r.verified else "🕓 ยังไม่ยืนยัน"
            with st.expander(f"{_r.title} {_r.section or ''} — {_law_status}", expanded=False):
                st.caption(f"ข้อความ: {_r.quote or '-'}")
                st.caption(f"แหล่ง: {_r.url or '-'} · วันที่มีผล: {_r.effective_date or '-'}")
                st.caption(f"บันทึกโดย {_r.recorded_by or '-'} เมื่อ {_r.recorded_at or '-'}")
                _c_verify, _c_del = st.columns(2)
                with _c_verify:
                    if st.button("✅/❌ สลับสถานะตรวจยืนยัน", key=f"law_verify_{_r.id}"):
                        _law_lib.update(_r.id, verified=not _r.verified)
                        st.rerun()
                with _c_del:
                    if st.button("🗑 ลบ", key=f"law_del_{_r.id}"):
                        _law_lib.delete(_r.id)
                        st.rerun()
    else:
        st.info("ยังไม่มีรายการข้อกฎหมายในคลัง")

    with st.form("legal_ref_form"):
        st.markdown("**➕ เพิ่มข้อกฎหมาย/ระเบียบใหม่**")
        _lr_title = st.text_input("ชื่อกฎหมาย/ระเบียบ", key="lr_title")
        _lr_section = st.text_input("มาตรา/ข้อ (ถ้ามี)", key="lr_section")
        _lr_quote = st.text_area("ข้อความอ้างอิง (excerpt)", key="lr_quote", height=80)
        _lr_url = st.text_input("URL/แหล่ง", key="lr_url")
        _lr_eff = st.text_input("วันที่มีผล", key="lr_eff")
        _lr_by = st.text_input("ผู้บันทึก", key="lr_by")
        _lr_verified = st.checkbox("ยืนยันแหล่งแล้ว (verified)", key="lr_verified")
        if st.form_submit_button("➕ บันทึกรายการข้อกฎหมาย"):
            if _lr_title.strip():
                _law_lib.add(LegalReference(
                    title=_lr_title.strip(),
                    section=_lr_section.strip() or None,
                    quote=_lr_quote.strip(),
                    url=_lr_url.strip() or None,
                    effective_date=_lr_eff.strip() or None,
                    verified=_lr_verified,
                    recorded_by=_lr_by.strip(),
                ))
                st.success("บันทึกข้อกฎหมายเรียบร้อย")
                st.rerun()
            else:
                st.warning("กรุณาระบุชื่อกฎหมาย/ระเบียบ")

    if st.button("🔄 รีเซ็ตเป็นค่าเริ่มต้นของกรุงเทพมหานคร (BMA Default)", use_container_width=True):
        res_prof = reset_to_default_profile()
        st.session_state.user_profile = res_prof
        st.success("รีเซ็ตเป็นค่าเริ่มต้น กทม. เรียบร้อยแล้ว!")
        st.rerun()




def render_form_editor_view():
    doc = st.session_state.doc_data

    def _mark_section_editing():
        _d = st.session_state.doc_data
        _d.edit_status = "editing"
        st.session_state.doc_data = _d

    def _save_sections(note: str = "บันทึกหัวข้ออิสระ"):
        _d = st.session_state.doc_data
        for _s in _d.sections or []:
            if f"sec_label_{_s.id}" in st.session_state:
                _s.label = st.session_state[f"sec_label_{_s.id}"].strip() or _s.kind.default_label()
            if f"sec_content_{_s.id}" in st.session_state:
                _s.content = st.session_state[f"sec_content_{_s.id}"].strip()
            if f"sec_secondary_{_s.id}" in st.session_state:
                _s.secondary = st.session_state[f"sec_secondary_{_s.id}"].strip()
            if f"sec_enabled_{_s.id}" in st.session_state:
                _s.enabled = bool(st.session_state[f"sec_enabled_{_s.id}"])
        sync_fields_from_sections(_d)
        _d.edit_status = "saved"
        _d.last_edited_at = datetime.now().strftime("%Y-%m-%d %H:%M")
        st.session_state.doc_data = _d
        audit_mgr.save_version(
            doc_id=audit_doc_id(_d),
            doc=_d,
            author="ผู้ใช้แก้ไข",
            note=note,
        )

    if doc.edit_status == "saved":
        st.success(
            "สถานะเอกสาร: ✅ แก้ไขและบันทึกแล้ว"
            + (f" (ล่าสุด {doc.last_edited_at})" if doc.last_edited_at else "")
        )
    elif doc.edit_status == "editing":
        st.warning("สถานะเอกสาร: ✏️ กำลังแก้ไข — ยังไม่บันทึก")
    else:
        st.info("สถานะเอกสาร: 📄 ฉบับร่าง")

    # ----------------- ตัวจัดการหัวข้ออิสระ (เพิ่ม/ลบ/สลับ/แก้ไข) -----------------
    if doc.kind in (DocumentKind.EXTERNAL_LETTER, DocumentKind.INTERNAL_MEMO):
        if doc.sections is None:
            st.info(
                "ต้องการเพิ่ม/ลบ/สลับหัวข้อเอง หรือเลือกว่าจะมีหัวข้อใดบ้าง "
                "ให้เปิดโหมดแก้ไขหัวข้ออิสระด้านล่าง"
            )
            if st.button("🧩 เปิดโหมดแก้ไขหัวข้ออิสระ (เพิ่ม/ลบ/สลับหัวข้อ)", type="primary"):
                new_doc = ensure_sections(doc)
                new_doc.edit_status = "editing"
                st.session_state.doc_data = new_doc
                st.rerun()
        else:
            st.markdown("### 🧩 หัวข้อเอกสาร (โหมดอิสระ)")
            st.caption(
                "แก้ไขชื่อ/เนื้อหา เพิ่ม ลบ สลับลำดับ หรือเอาติ๊กออกเพื่อซ่อนหัวข้อ "
                "แล้วกดบันทึก ระบบจะบันทึกเวอร์ชันลง Audit Trail และสถานะลงproperties ของ Word"
            )
            if st.button("💾 บันทึกการแก้ไขทั้งหมด", type="primary", use_container_width=True):
                _save_sections("บันทึกการแก้ไขหัวข้ออิสระทั้งหมด")
                st.rerun()

            for idx, sec in enumerate(list(doc.sections)):
                _label = sec.label or sec.kind.default_label()
                if not sec.enabled:
                    _label += " (ซ่อนอยู่)"
                with st.expander(f"{idx + 1}. {_label}", expanded=False):
                    new_label = st.text_input(
                        "ชื่อหัวข้อ",
                        value=sec.label,
                        key=f"sec_label_{sec.id}",
                        on_change=_mark_section_editing,
                    )
                    new_content = st.text_area(
                        "เนื้อหา",
                        value=sec.content,
                        height=90,
                        key=f"sec_content_{sec.id}",
                        on_change=_mark_section_editing,
                    )
                    new_secondary = ""
                    if sec.kind in (SectionKind.NUMBER_DATE, SectionKind.SIGNATURE):
                        new_secondary = st.text_input(
                            "วันที่ / ตำแหน่ง",
                            value=sec.secondary,
                            key=f"sec_secondary_{sec.id}",
                            on_change=_mark_section_editing,
                        )
                    new_enabled = st.checkbox(
                        "แสดงหัวข้อนี้ในเอกสาร",
                        value=bool(sec.enabled),
                        key=f"sec_enabled_{sec.id}",
                        help="ยกเลิกเพื่อซ่อนหัวข้อนี้ออกจากเอกสาร โดยไม่ต้องลบเนื้อหา",
                    )
                    if new_enabled != sec.enabled:
                        sec.enabled = new_enabled
                        doc.sections[idx] = sec
                        sync_fields_from_sections(doc)
                        doc.edit_status = "saved"
                        doc.last_edited_at = datetime.now().strftime("%Y-%m-%d %H:%M")
                        st.session_state.doc_data = doc
                        st.rerun()
                    c_save, c_up, c_down, c_del = st.columns([1.2, 0.5, 0.5, 0.6])
                    with c_save:
                        if st.button("💾 บันทึก", key=f"sec_save_{sec.id}", type="primary"):
                            _save_sections(f"บันทึกหัวข้อ: {_label}")
                            st.rerun()
                    with c_up:
                        if idx > 0 and st.button("↑", key=f"sec_up_{sec.id}"):
                            doc.sections[idx - 1], doc.sections[idx] = doc.sections[idx], doc.sections[idx - 1]
                            _save_sections("สลับลำดับหัวข้อขึ้น")
                            st.rerun()
                    with c_down:
                        if idx < len(doc.sections) - 1 and st.button("↓", key=f"sec_down_{sec.id}"):
                            doc.sections[idx + 1], doc.sections[idx] = doc.sections[idx], doc.sections[idx + 1]
                            _save_sections("สลับลำดับหัวข้อลง")
                            st.rerun()
                    with c_del:
                        if st.button("🗑 ลบ", key=f"sec_del_{sec.id}"):
                            removed = doc.sections.pop(idx)
                            _save_sections(f"ลบหัวข้อ: {removed.label}")
                            st.rerun()

            ac1, ac2, ac3 = st.columns([1.3, 1.3, 1])
            with ac1:
                _new_kind = st.selectbox(
                    "เพิ่มหัวข้อ",
                    options=list(SectionKind),
                    format_func=lambda k: k.default_label(),
                    key="new_section_kind",
                )
            with ac2:
                _new_label = st.text_input(
                    "ชื่อหัวข้อใหม่ (เว้นว่าง = ค่าเริ่มต้น)",
                    value="",
                    key="new_section_label",
                )
            with ac3:
                st.write("")
                st.write("")
                if st.button("➕ เพิ่มหัวข้อ"):
                    doc.sections.append(
                        DocumentSection(
                            kind=_new_kind,
                            label=_new_label.strip() or _new_kind.default_label(),
                        )
                    )
                    _save_sections(f"เพิ่มหัวข้อ: {_new_kind.default_label()}")
                    st.rerun()

            if st.button("ปิดโหมดอิสระ (กลับไปใช้ฟิลด์มาตรฐาน)"):
                doc.sections = None
                doc.edit_status = "draft"
                st.session_state.doc_data = doc
                st.rerun()

    if doc.sections is None:
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






def render_diff_view():
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
                doc_id=audit_doc_id(st.session_state.doc_data),
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





def render_left_pane():
    source_mode = st.radio(
        "โหมดการสร้างร่างหนังสือ:",
        options=["📂 แนบไฟล์ต้นเรื่อง (Source Document)", "📋 เลือกจากแบบฟอร์มมาตรฐาน (Preset Templates)"],
        horizontal=True,
        label_visibility="collapsed"
    )

    if source_mode == "📂 แนบไฟล์ต้นเรื่อง (Source Document)":
        st.subheader("📂 แนบไฟล์ต้นเรื่อง (Source Document)")
        st.session_state.doc_secret_level = st.selectbox(
            "ชั้นความลับของเอกสารนี้ (ชั้นลับจะไม่ส่งให้ AI ภายนอก)",
            options=[SecretLevel.NORMAL, SecretLevel.SECRET, SecretLevel.VERY_SECRET, SecretLevel.TOP_SECRET],
            format_func=lambda x: x.to_thai(),
        )
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
                    ctx = extract_source_document(str(saved_path), api_key=st.session_state.get("ai_api_key"), allow_cloud=st.session_state.get("allow_cloud_ai", True), secret=st.session_state.doc_secret_level)
                    st.session_state.source_context = ctx
                    st.session_state.last_uploaded_file = uploaded_file.name
                    if not ctx.extraction_failed:
                        st.session_state.classification = classify_source_document(ctx)
                        st.session_state.pop("classified_kind", None)
                        st.session_state.classification_confirmed = False

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
                    st.session_state.classification = classify_source_document(new_ctx)
                    st.session_state.pop("classified_kind", None)
                    st.session_state.classification_confirmed = False
                    st.success("บันทึกข้อความต้นเรื่องเรียบร้อยแล้ว!")
                    st.rerun()
            else:
                eng_badge = f" (สกัดผ่าน {st.session_state.source_context.ocr_engine_used})" if (st.session_state.source_context and st.session_state.source_context.ocr_engine_used) else ""
                st.success(f"แนบและสกัดข้อมูลสำเร็จ: {uploaded_file.name}{eng_badge}")

            # Step 1: เลือกองค์ประกอบเอกสาร + ตรวจข้อมูลขาด + ถามกลับ
            _intake_ctx = st.session_state.source_context
            if _intake_ctx and not _intake_ctx.extraction_failed:
                st.markdown("##### 🧩 เลือกองค์ประกอบเอกสารและเติมข้อมูลที่ขาด")
                st.session_state.include_law = st.checkbox(
                    "มีข้อกฎหมาย/ระเบียบที่ต้องอ้างอิง",
                    value=st.session_state.include_law,
                    key="include_law_toggle",
                )
                st.session_state.include_references = st.checkbox(
                    "มีหนังสือ/เรื่องที่อ้างถึง",
                    value=st.session_state.include_references,
                    key="include_references_toggle",
                )
                st.session_state.include_attachments = st.checkbox(
                    "มีสิ่งที่ส่งมาด้วย",
                    value=st.session_state.include_attachments,
                    key="include_attachments_toggle",
                )

                _intake_kind = (
                    st.session_state.get("classification").kind
                    if st.session_state.get("classification")
                    else DocumentKind.EXTERNAL_LETTER
                )
                _assessment = assess_intake(
                    _intake_ctx,
                    _intake_kind,
                    include_law=st.session_state.include_law,
                    include_references=st.session_state.include_references,
                    include_attachments=st.session_state.include_attachments,
                )
                st.session_state.intake_assessment = _assessment
                st.session_state.intake_ready = _assessment.ready

                if getattr(_intake_ctx, "entities", None):
                    with st.expander("🔍 ข้อมูลที่สกัดได้จากต้นเรื่อง", expanded=False):
                        for _e in _intake_ctx.entities[:14]:
                            _flag = " ⚠️ ควรตรวจ" if (_e.evidence and _e.evidence.needs_review) else ""
                            st.caption(f"• {_e.kind}: {_e.value}{_flag}")
                if getattr(_intake_ctx, "unclear_spans", None):
                    st.warning(
                        f"⚠️ พบจุดที่อ่านไม่ชัดเจน {len(_intake_ctx.unclear_spans)} จุด "
                        "— กรุณาตรวจในข้อความต้นเรื่อง"
                    )

                _field_map = {
                    "source_subject": "source_subject",
                    "source_dept": "source_dept",
                    "source_doc_no": "source_doc_no",
                    "source_date": "source_date",
                    "requested_action": "requested_action",
                }
                for _q in _assessment.questions:
                    if _q.kind != "text":
                        continue
                    _val = st.text_input(
                        _q.question,
                        value=st.session_state.intake_answers.get(_q.field, ""),
                        key=f"intake_{_q.field}",
                        placeholder=_q.placeholder,
                    )
                    if _val.strip():
                        st.session_state.intake_answers[_q.field] = _val
                        if _q.field in _field_map:
                            setattr(_intake_ctx, _field_map[_q.field], _val.strip())
                        st.session_state.source_context = _intake_ctx

                if st.session_state.include_law:
                    _law_lib = LegalLibrary()
                    _law_list = _law_lib.list(verified_only=True)
                    if not _law_list:
                        st.warning(
                            "ยังไม่มีข้อกฎหมายที่ยืนยันแล้วในคลัง — เพิ่มได้ที่แท็บ "
                            "'⚙️ ตั้งค่าหน่วยงานของฉัน'"
                        )
                        st.session_state.selected_law_id = None
                    else:
                        _law_labels = {
                            f"{r.title} {r.section or ''}".strip(): r.id for r in _law_list
                        }
                        _law_choice = st.selectbox(
                            "เลือกข้อกฎหมายที่ยืนยันแล้ว",
                            options=list(_law_labels.keys()),
                            key="law_select",
                        )
                        st.session_state.selected_law_id = _law_labels[_law_choice]
                else:
                    st.session_state.selected_law_id = None

                if not _assessment.ready:
                    st.info("กรุณาตอบข้อมูลที่จำเป็น (เครื่องหมาย *) หรือพิมพ์ข้อความต้นเรื่องให้ครบก่อนยกร่าง")
                else:
                    st.success("ข้อมูลครบถ้วน พร้อมยกร่าง")

            # ชนิดหนังสือที่ตรวจพบ + ยืนยันก่อนร่าง
            _cls = st.session_state.get("classification")
            if _cls:
                st.markdown("##### 🔎 ชนิดหนังสือที่ตรวจพบ")
                _kinds = list(DocumentKind)
                _kind = st.selectbox(
                    "ชนิดหนังสือ (เลือกแก้ได้)",
                    options=_kinds,
                    index=_kinds.index(_cls.kind),
                    format_func=lambda k: k.thai_label(),
                    key="classified_kind",
                )
                if _kind != _cls.kind:
                    _cls = classify_source_document(
                        st.session_state.source_context, forced_kind=_kind
                    )
                    st.session_state.classification = _cls
                    st.session_state.classification_confirmed = False
                    st.rerun()

                st.caption(
                    f"ความมั่นใจ {_cls.confidence:.0%} · แบบที่ {_cls.form_no} · "
                    f"{'รองรับการร่างอัตโนมัติ' if _cls.supported else 'ยังไม่รองรับการร่างอัตโนมัติ'}"
                )
                for _reason in _cls.reasons[:3]:
                    st.caption(f"• {_reason}")
                if not _cls.supported:
                    st.warning(
                        "ชนิดนี้ยังไม่เปิดให้ร่างอัตโนมัติใน P1 — ใช้แม่แบบเอกสารหรือแก้ข้อความเองก่อนส่งออก"
                    )
                if st.button("✅ ยืนยันชนิดนี้", type="primary"):
                    st.session_state.classification_confirmed = True
                    st.rerun()
                if st.session_state.get("classification_confirmed"):
                    st.success("ยืนยันชนิดหนังสือแล้ว พร้อมยกร่าง")

            # เลือกเจตนาการร่างหนังสือ (Drafting Intent)
            st.markdown("##### 🎯 วัตถุประสงค์ในการร่างหนังสือ:")
            _intent_options = [
                (DraftingIntent.MEMO_REVIEW, "📑 บันทึกข้อความรายงานการพิจารณา / เกษียนเรื่องเดิม"),
                (DraftingIntent.ACCEPT, "🤝 หนังสือตอบรับ / ยินดีให้ความอนุเคราะห์"),
                (DraftingIntent.DECLINE, "❌ หนังสือแจ้งข้อขัดข้อง / ปฏิเสธอย่างสุภาพ"),
                (DraftingIntent.FORWARD, "📨 หนังสือส่งต่อเรื่อง / แจ้งเวียน"),
                (DraftingIntent.PROPOSAL, "📝 บันทึกข้อความเสนอผู้บังคับบัญชาเพื่อพิจารณาอนุมัติ"),
            ]
            _suggested_intent = (
                st.session_state.get("classification").intent
                if st.session_state.get("classification")
                else DraftingIntent.MEMO_REVIEW
            )
            _intent_index = next(
                (i for i, (value, _) in enumerate(_intent_options) if value == _suggested_intent),
                0,
            )
            intent_choice = st.radio(
                "เจตนาการตอบ/ยกร่าง:",
                options=_intent_options,
                format_func=lambda x: x[1],
                index=_intent_index,
                key=f"intent_{_suggested_intent.value}",
                label_visibility="collapsed",
            )

            is_internal_intent = intent_choice[0] in [DraftingIntent.PROPOSAL, DraftingIntent.MEMO_REVIEW]
            target_doc_type = DocType.INTERNAL if is_internal_intent else DocType.EXTERNAL
            _cls_now = st.session_state.get("classification")
            if (
                _cls_now
                and st.session_state.get("classification_confirmed")
                and _cls_now.supported
            ):
                target_doc_type = _cls_now.doc_type

            with st.expander("⚙️ ตั้งค่าโมเดล AI ยกร่าง และ OCR (Gemini / OpenAI)", expanded=False):
                allow_cloud = st.checkbox(
                    "อนุญาตส่งข้อมูลไป AI ภายนอก (Gemini/OpenAI)",
                    value=bool(st.session_state.get("allow_cloud_ai", True)),
                    key="allow_cloud_ai",
                    help="หากเป็นเอกสารชั้นลับ/ข้อมูลอ่อนไหว ให้ปิดเพื่อใช้ Rule-based และ OCR ภายในเครื่องเท่านั้น",
                )
                if not allow_cloud:
                    st.warning("โหมดข้อมูลอ่อนไหว: ระบบจะไม่ส่งเนื้อหาไปยัง AI ภายนอก และจะใช้ Rule-based/local OCR")
                ai_prov = st.selectbox("AI Engine:", ["Gemini 3.8 Flash (Google)", "OpenAI GPT-4o-mini"], index=0)
                ai_key_input = st.text_input("API Key (เว้นว่างเพื่อใช้ Local OCR / Rule-based)", value=st.session_state.get("ai_api_key", ""), type="password")
                if ai_key_input:
                    st.session_state["ai_api_key"] = ai_key_input
                st.caption("💡 ใส่ Gemini API Key เพื่อให้ระบบอ่านลายมือเกษียนสั่งการและตรายางได้แม่นยำ 100%")
                if st.button("🔄 รัน OCR ถอดข้อความใหม่อีกครั้ง", use_container_width=True):
                    with st.spinner("กำลังประมวลผล OCR อีกครั้งด้วย API Key/เครื่องมือที่ระบุ..."):
                        re_ctx = extract_source_document(str(saved_path), api_key=st.session_state.get("ai_api_key"), allow_cloud=st.session_state.get("allow_cloud_ai", True), secret=st.session_state.doc_secret_level)
                        st.session_state.source_context = re_ctx
                        if not re_ctx.extraction_failed:
                            st.session_state.classification = classify_source_document(re_ctx)
                            st.session_state.pop("classified_kind", None)
                            st.session_state.classification_confirmed = False
                        st.rerun()

            _can_draft = bool(
                _cls_now
                and st.session_state.get("classification_confirmed")
                and _cls_now.supported
                and st.session_state.get("intake_ready", True)
            )
            if not _can_draft:
                if not st.session_state.get("intake_ready", True):
                    st.warning("กรุณาตอบข้อมูลที่จำเป็นด้านบนให้ครบก่อนยกร่าง")
                else:
                    st.caption("กรุณาตรวจและยืนยันชนิดหนังสือด้านบนก่อนยกร่าง")
            if st.button(
                "🚀 ให้ AI ยกร่างหนังสือตามต้นเรื่องนี้",
                type="primary",
                use_container_width=True,
                disabled=not _can_draft,
            ):
                ctx = st.session_state.source_context
                if not ctx or ctx.extraction_failed or not (ctx.raw_text or "").strip():
                    st.error("⚠️ ไม่สามารถยกร่างหนังสือได้ เนื่องจากไม่มีข้อความต้นเรื่องที่อ่านได้ กรุณาใส่ API Key หรือกรอกข้อความด้วยตนเองก่อน")
                else:
                    with st.spinner("AI กำลังวิเคราะห์และยกร่างโครงสร้างตามระเบียบ..."):
                        prov = "openai" if "OpenAI" in ai_prov else "gemini"
                        key = st.session_state.get("ai_api_key")
                        allow_cloud_now = st.session_state.get("allow_cloud_ai", True)
                        secret_value = st.session_state.doc_secret_level
                        use_cloud = bool(key) and bool(allow_cloud_now) and cloud_ai_allowed(secret_value)
                        if _cls_now and _cls_now.kind not in (
                            DocumentKind.EXTERNAL_LETTER,
                            DocumentKind.INTERNAL_MEMO,
                        ):
                            draft = draft_special_from_context(
                                ctx,
                                _cls_now.kind,
                                _cls_now.form_no,
                                get_user_profile(),
                            )
                            draft_author = "Special template (local)"
                        elif use_cloud:
                            m_name = os.getenv("GEMINI_MODEL") or "gemini-3.8-flash" if prov == "gemini" else None
                            draft = draft_from_context_llm(ctx, doc_type=target_doc_type, intent=intent_choice[0], provider=prov, model_name=m_name, api_key=key, secret=secret_value, allow_cloud=allow_cloud_now)
                            draft_author = f"AI Studio ({prov.upper()})"
                        else:
                            draft = draft_from_context_rule_based(ctx, doc_type=target_doc_type, intent=intent_choice[0])
                            draft_author = "Rule-based (local)"
                            if not allow_cloud_now or not cloud_ai_allowed(secret_value):
                                st.info("โหมดข้อมูลอ่อนไหว: ระบบใช้ Rule-based ภายในเครื่อง โดยไม่ส่งข้อมูลไป AI ภายนอก")
                        draft.secret = secret_value

                        # Step 1: ใส่ข้อกฎหมายที่ผู้ใช้เลือกจากคลังที่ยืนยันแล้ว
                        if st.session_state.get("selected_law_id"):
                            _law_lib = LegalLibrary()
                            _law_ref = next(
                                (r for r in _law_lib.list() if r.id == st.session_state.selected_law_id),
                                None,
                            )
                            if _law_ref:
                                draft.memo_law = format_legal_citation(_law_ref)

                        # Step 1: ใส่สิ่งที่ส่งมาด้วยจากคำตอบของผู้ใช้
                        _att_text = st.session_state.intake_answers.get("attachments", "")
                        if st.session_state.include_attachments and _att_text.strip():
                            draft.attachments = [
                                line.strip() for line in _att_text.splitlines() if line.strip()
                            ]

                        if draft.kind in (DocumentKind.EXTERNAL_LETTER, DocumentKind.INTERNAL_MEMO):
                            draft = ensure_sections(draft)
                        st.session_state.draft_uid = f"draft-{uuid.uuid4().hex[:8]}"
                        st.session_state.doc_data = draft
                        st.session_state.initial_ai_draft = draft.model_copy(deep=True)
                        audit_mgr.save_version(
                            doc_id=audit_doc_id(draft),
                            doc=draft,
                            author=draft_author,
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
                doc_id=audit_doc_id(curr_tmpl.schema),
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
        elif "พัสดุ" in c_prompt or "ระเบียบ" in c_prompt or "กฎหมาย" in c_prompt:
            st.info("ยังไม่มีแหล่งยืนยันข้อกฎหมาย — ระบบจะเพิ่มคลังให้เลือกใน Step 1 (ตอนนี้ยังไม่ใส่ข้อกฎหมายอัตโนมัติ)")
        else:
            st.info("AI ได้รับคำสั่งแล้ว: สามารถใช้ปุ่มลัดด้านล่างหรือเกลาข้อความในแบบฟอร์มได้ทันที")





def render_a4_paper_canvas():
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
        include_pencils=True, # ปักหมุดปุ่มดินสอแก้ไขเรียลไทม์บนหน้าหนังสือ
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
    if doc.sections is not None and doc.kind in (
        DocumentKind.EXTERNAL_LETTER,
        DocumentKind.INTERNAL_MEMO,
    ):
        _sec_html = []
        for _section in doc.sections:
            if not _section.enabled:
                continue
            _label = _section.label or _section.kind.default_label()
            _content = _section.content or ""
            _secondary = _section.secondary or ""
            if doc.use_thai_numerals:
                _content = to_thai_numerals(_content)
                _secondary = to_thai_numerals(_secondary)
            _safe = highlight_placeholders_html(_content).replace("\n", "<br/>")
            _safe_secondary = highlight_placeholders_html(_secondary).replace("\n", "<br/>")
            _sec_p_link = f'&nbsp;<a href="?edit=sec_{_section.id}" target="_self" class="doc-pencil-btn" title="คลิกแก้ไขหัวข้อ {_label} (ป็อปอัปเรียลไทม์)">✏️</a>'

            if _section.kind == SectionKind.NUMBER_DATE:
                _sec_html.append(
                    f'<div style="display:flex;justify-content:space-between;margin:2px 0;"><span><strong>ที่</strong> {_safe}</span><span><strong>วันที่</strong> {_safe_secondary}</span>{_sec_p_link}</div>'
                )
            elif _section.kind == SectionKind.SIGNATURE:
                _sec_html.append(
                    f'<div style="text-align:center;margin-left:45%;margin-top:24px;"><p>{_safe} {_sec_p_link}</p><p>{_safe_secondary}</p></div>'
                )
            elif _section.kind == SectionKind.CLOSING:
                _sec_html.append(
                    f'<div style="text-align:center;margin-left:45%;margin-top:18px;"><p>{_safe} {_sec_p_link}</p></div>'
                )
            elif _section.kind in (SectionKind.REFERENCES, SectionKind.ATTACHMENTS):
                _sec_html.append(f'<p><strong>{_label}</strong>  {_safe} {_sec_p_link}</p>')
            elif _section.kind in (
                SectionKind.INTRO,
                SectionKind.LAW,
                SectionKind.FACTS,
                SectionKind.CONSIDERATION,
                SectionKind.DETAILS,
                SectionKind.PURPOSE,
                SectionKind.CUSTOM,
            ):
                _sec_html.append(f'<p class="a4-indent"><u>{_label}</u>{_sec_p_link}  {_safe}</p>')
            else:
                _sec_html.append(f'<p><strong>{_label}</strong>  {_safe} {_sec_p_link}</p>')
        _is_internal_preview = doc.kind == DocumentKind.INTERNAL_MEMO
        _header_html = (
            f'<div style="display:flex;align-items:flex-start;margin-bottom:12px;"><img src="data:{garuda_mime};base64,{garuda_b64}" style="height:1.5cm;margin-right:18px;" /><div style="font-size:26px;font-weight:bold;text-align:center;width:85%;">บันทึกข้อความ</div></div>'
            if _is_internal_preview
            else f'<div style="text-align:center;margin-bottom:12px;"><img src="data:{garuda_mime};base64,{garuda_b64}" style="height:3.0cm;" /></div>'
        )
        st.markdown(compact_html(f"""
        <div class="a4-paper">
            {_header_html}
            {''.join(_sec_html)}
        </div>
        """), unsafe_allow_html=True)
    elif doc.kind not in (DocumentKind.EXTERNAL_LETTER, DocumentKind.INTERNAL_MEMO):
        _special_items = "".join(
            f'<p class="a4-indent">{highlight_placeholders_html((to_thai_numerals(str(i)) if doc.use_thai_numerals else str(i)) + ".  " + item)}</p>'
            for i, item in enumerate(doc.special_items or [], 1)
        )
        st.markdown(compact_html(f"""
        <div class="a4-paper">
            <div style="text-align: center; margin-bottom: 12px;">
                <img src="data:{garuda_mime};base64,{garuda_b64}" style="height: 3.0cm; width: auto;" alt="ตราครุฑ 3 ซม." />
            </div>
            <h2 style="text-align: center; font-size: 24px; margin: 4px 0 14px;">{highlight_placeholders_html(doc.special_title or doc.subject)}</h2>
            <div style="display: flex; justify-content: space-between; margin-bottom: 6px; font-size: 14.5px;">
                <div>ที่  {disp_no} <a href="?edit=header" target="_self" class="doc-pencil-btn" title="คลิกแก้ไขเลขที่ (ป็อปอัปเรียลไทม์)">✏️</a></div>
                <div>วันที่  {disp_date} <a href="?edit=header" target="_self" class="doc-pencil-btn" title="คลิกแก้ไขวันที่ (ป็อปอัปเรียลไทม์)">✏️</a></div>
            </div>
            <p style="font-size: 14.5px;"><strong>เรื่อง</strong>  {disp_subject} <a href="?edit=header" target="_self" class="doc-pencil-btn" title="คลิกแก้ไขชื่อเรื่อง (ป็อปอัปเรียลไทม์)">✏️</a></p>
            <p class="a4-indent">{highlight_placeholders_html(doc.special_preamble or "")}</p>
            {_special_items}
            <p class="a4-indent">{highlight_placeholders_html(doc.special_note or "")}</p>
            <div style="text-align: center; margin-left: 45%; margin-top: 28px; margin-bottom: 20px; font-size: 14.5px;">
                {sig_preview_html}
                <p>{disp_sig_name} <a href="?edit=signatory" target="_self" class="doc-pencil-btn" title="คลิกแก้ไขผู้ลงนาม (ป็อปอัปเรียลไทม์)">✏️</a></p>
                <p>{disp_sig_pos}</p>
            </div>
            <div style="font-size: 12.5px !important; color: #334155;">
                <p style="margin: 0;">{highlight_placeholders_html(doc.contact_dept or '')} <a href="?edit=contact" target="_self" class="doc-pencil-btn" title="คลิกแก้ไขข้อมูลติดต่อ">✏️</a></p>
                <p style="margin: 0;">โทรศัพท์  {highlight_placeholders_html(doc.contact_tel or '')}</p>
            </div>
        </div>
        """), unsafe_allow_html=True)
    elif doc.doc_type == DocType.EXTERNAL:
        st.markdown(compact_html(f"""
        <div class="a4-paper">
            <div style="text-align: center; margin-bottom: 12px;">
                <img src="data:{garuda_mime};base64,{garuda_b64}" style="height: 3.0cm; width: auto; display: inline-block;" alt="ตราครุฑ 3 ซม." />
            </div>
            <div style="display: flex; justify-content: space-between; margin-bottom: 6px; font-size: 14.5px;">
                <div style="width: 48%;"><strong>ที่</strong>  {disp_no} <a href="?edit=header" target="_self" class="doc-pencil-btn" title="คลิกแก้ไขเลขที่ (ป็อปอัปเรียลไทม์)">✏️</a></div>
                <div style="width: 48%; text-align: left;">{disp_dept} <a href="?edit=header" target="_self" class="doc-pencil-btn" title="คลิกแก้ไขส่วนราชการ (ป็อปอัปเรียลไทม์)">✏️</a></div>
            </div>
            <div style="text-align: center; margin-left: 20%; margin-bottom: 12px; font-size: 14.5px;">
                {disp_date} <a href="?edit=header" target="_self" class="doc-pencil-btn" title="คลิกแก้ไขวันที่ (ป็อปอัปเรียลไทม์)">✏️</a>
            </div>
            <div style="margin-bottom: 12px; font-size: 14.5px;">
                <p><strong>เรื่อง</strong>  {disp_subject} <a href="?edit=header" target="_self" class="doc-pencil-btn" title="คลิกแก้ไขชื่อเรื่อง (ป็อปอัปเรียลไทม์)">✏️</a></p>
                <p><strong>{sal_label}</strong>  {disp_sal_body} <a href="?edit=header" target="_self" class="doc-pencil-btn" title="คลิกแก้ไขคำขึ้นต้น (ป็อปอัปเรียลไทม์)">✏️</a></p>
                {refs_html}
                {atts_html}
            </div>
            <p class="a4-indent">{disp_reason} <a href="?edit=intro" target="_self" class="doc-pencil-btn" title="คลิกแก้ไขภาคเหตุ (ป็อปอัปเรียลไทม์)">✏️</a></p>
            {f'<p class="a4-indent">{disp_details} <a href="?edit=facts" target="_self" class="doc-pencil-btn" title="คลิกแก้ไขภาคข้อเท็จจริง (ป็อปอัปเรียลไทม์)">✏️</a></p>' if disp_details else ''}
            <p class="a4-indent">{disp_purpose} <a href="?edit=consideration" target="_self" class="doc-pencil-btn" title="คลิกแก้ไขภาคความประสงค์ (ป็อปอัปเรียลไทม์)">✏️</a></p>
            <div style="text-align: center; margin-left: 45%; margin-top: 28px; margin-bottom: 24px; font-size: 14.5px;">
                <p>{disp_closing}</p>
                {sig_preview_html}
                <p>{disp_sig_name} <a href="?edit=signatory" target="_self" class="doc-pencil-btn" title="คลิกแก้ไขข้อมูลผู้ลงนาม (ป็อปอัปเรียลไทม์)">✏️</a></p>
                <p>{disp_sig_pos}</p>
            </div>
            <div style="font-size: 12.5px !important; margin-top: 24px; color: #334155; line-height: 1.4;">
                <p style="margin: 0; font-size: 12.5px !important;">{highlight_placeholders_html(doc.contact_dept or '')} <a href="?edit=contact" target="_self" class="doc-pencil-btn" title="คลิกแก้ไขข้อมูลติดต่อ (ป็อปอัปเรียลไทม์)">✏️</a></p>
                <p style="margin: 0; font-size: 12.5px !important;">โทรศัพท์  {highlight_placeholders_html(doc.contact_tel or '')}</p>
                <p style="margin: 0; font-size: 12.5px !important;">ไปรษณีย์อิเล็กทรอนิกส์  {highlight_placeholders_html(doc.contact_email or '')}</p>
            </div>
        </div>
        """), unsafe_allow_html=True)
    else:
        dept_tel_str = f"  โทร. {highlight_placeholders_html(doc.contact_tel)}" if (doc.contact_tel and doc.contact_tel not in doc.dept_name) else ""
        st.markdown(compact_html(f"""
        <div class="a4-paper">
            <div style="display: flex; align-items: flex-start; margin-bottom: 12px;">
                <img src="data:{garuda_mime};base64,{garuda_b64}" style="height: 1.5cm; width: auto; margin-right: 18px;" alt="ตราครุฑ 1.5 ซม." />
                <div style="font-size: 26px; font-weight: bold; text-align: center; width: 85%; font-family: 'TH Sarabun New', 'TH SarabunIT๙', 'Sarabun', sans-serif;">บันทึกข้อความ</div>
            </div>
            <div style="margin-bottom: 10px; font-size: 14.5px;">
                <div class="memo-field">
                    <span class="memo-label">ส่วนราชการ</span>
                    <span class="memo-value">{disp_dept}{dept_tel_str}</span>
                    <a href="?edit=header" target="_self" class="doc-pencil-btn" title="คลิกแก้ไขส่วนราชการ (ป็อปอัปเรียลไทม์)">✏️</a>
                </div>
                <div class="memo-field">
                    <span class="memo-label">ที่</span><span class="memo-value" style="flex: 0 0 42%;">{disp_no}</span>
                    <span class="memo-label" style="margin-left: 8px;">วันที่</span><span class="memo-value">{disp_date}</span>
                    <a href="?edit=header" target="_self" class="doc-pencil-btn" title="คลิกแก้ไขเลขที่และวันที่ (ป็อปอัปเรียลไทม์)">✏️</a>
                </div>
                <div class="memo-field">
                    <span class="memo-label">เรื่อง</span><span class="memo-value">{disp_subject}</span>
                    <a href="?edit=header" target="_self" class="doc-pencil-btn" title="คลิกแก้ไขชื่อเรื่อง (ป็อปอัปเรียลไทม์)">✏️</a>
                </div>
                <p style="margin-top: 6px;">
                    {sal_label}  {disp_sal_body}
                    <a href="?edit=header" target="_self" class="doc-pencil-btn" title="คลิกแก้ไขคำขึ้นต้น (ป็อปอัปเรียลไทม์)">✏️</a>
                </p>
                {refs_html}
                {atts_html}
            </div>
            {rendered_memo_body}
            <div style="text-align: center; margin-left: 45%; margin-top: 35px; font-size: 14.5px;">
                {sig_preview_html}
                <p>{disp_sig_name} <a href="?edit=signatory" target="_self" class="doc-pencil-btn" title="คลิกแก้ไขข้อมูลผู้ลงนาม (ป็อปอัปเรียลไทม์)">✏️</a></p>
                <p>{disp_sig_pos}</p>
            </div>
        </div>
        """), unsafe_allow_html=True)


    with st.expander("✏️ ดูและเกลาเนื้อหาข้อความแบบฟิลด์ด้านล่าง", expanded=False):
        # ----------------- กล่องแก้ไขเนื้อหาและเกลาภาษาตามหัวข้อโดยตรง -----------------
        st.markdown("##### ✏️ แก้ไขเนื้อหาและเกลาภาษาตามหัวข้อโดยตรง")
        if doc.sections is not None:
            st.caption("โหมดหัวข้ออิสระเปิดอยู่: ใช้ตัวจัดการหัวข้อด้านบนเพื่อแก้ไข/เพิ่ม/ลบ/สลับหัวข้อ")
        elif doc.kind not in (DocumentKind.EXTERNAL_LETTER, DocumentKind.INTERNAL_MEMO):
            st.info("เอกสารชนิดพิเศษ: แก้ชื่อเอกสาร ความนำ ข้อความแยกข้อ และผู้ลงนามได้ด้านล่าง")
            sp1, sp2 = st.columns(2)
            with sp1:
                sp_title = st.text_input("ชื่อเอกสาร", value=doc.special_title or "", key="sp_title")
            with sp2:
                sp_subject = st.text_input("เรื่อง", value=doc.subject or "", key="sp_subject")
            sp_preamble = st.text_area(
                "ความนำ / อาศัยอำนาจ",
                value=doc.special_preamble or "",
                height=100,
                key="sp_preamble",
            )
            sp_items = st.text_area(
                "ข้อความแยกข้อ (หนึ่งบรรทัดต่อหนึ่งข้อ)",
                value="\n".join(doc.special_items or []),
                height=180,
                key="sp_items",
            )
            sp_note = st.text_area(
                "หมายเหตุ / บทบังคับใช้",
                value=doc.special_note or "",
                height=90,
                key="sp_note",
            )
            sp_sign_name = st.text_input(
                "ชื่อผู้ลงนาม", value=doc.signatory_name or "", key="sp_sign_name"
            )
            sp_sign_pos = st.text_input(
                "ตำแหน่งผู้ลงนาม", value=doc.signatory_position or "", key="sp_sign_pos"
            )
            if st.button("💾 บันทึกเอกสารชนิดพิเศษ", type="primary"):
                doc.special_title = sp_title.strip()
                doc.subject = sp_subject.strip()
                doc.special_preamble = sp_preamble.strip()
                doc.special_items = [line.strip() for line in sp_items.splitlines() if line.strip()]
                doc.special_note = sp_note.strip()
                doc.signatory_name = sp_sign_name.strip()
                doc.signatory_position = sp_sign_pos.strip()
                st.session_state.doc_data = doc
                st.rerun()
        elif doc.doc_type == DocType.INTERNAL:
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




def render_verification_view():
    """Step 2/3: แสดงผลตรวจร่างเทียบต้นเรื่องและข้อตรวจภาษา/ความสอดคล้อง"""
    doc = st.session_state.doc_data
    ctx = st.session_state.source_context

    st.markdown("##### 🔍 ตรวจร่างเทียบต้นเรื่อง และภาษา")
    if not ctx or ctx.extraction_failed:
        st.info("ยังไม่มีเอกสารต้นเรื่อง — แนบไฟล์หรือกรอกข้อความก่อนตรวจ")
        return

    vres = verify_draft_against_source(doc, ctx)
    tires = check_document_text(doc, ctx)

    critical = [f for f in vres.findings if f.severity == "critical"]
    warn = [f for f in vres.findings if f.severity == "warning"]
    info = [f for f in vres.findings if f.severity == "info"]

    st.markdown(
        f'<div style="display:flex; gap:6px; margin-bottom:10px;">'
        f'<span class="status-pill status-pill-warning">🔴 {len(critical)} ต้องแก้</span>'
        f'<span class="status-pill status-pill-info">🟠 {len(warn)} ควรตรวจ</span>'
        f'<span class="status-pill status-pill-info">🔵 {len(info)} ข้อมูล</span>'
        f'<span class="status-pill status-pill-info">🖋 {len(tires)} ภาษา</span>'
        f'</div>',
        unsafe_allow_html=True,
    )

    if not vres.findings and not tires:
        st.success("✅ ไม่พบข้อควรตรวจ — ร่างสอดคล้องกับต้นเรื่องเท่าที่ตรวจได้")

    _status_icon = {"found": "✅", "not_found": "❌", "confirm": "🟡"}
    _status_label = {"found": "พบหลักฐาน", "not_found": "ไม่พบหลักฐาน", "confirm": "ต้องยืนยัน"}
    for f in vres.findings:
        _sev = {"critical": "🔴", "warning": "🟠", "info": "🔵"}[f.severity]
        st.markdown(f"{_sev} **{f.message}** — {_status_icon[f.evidence_status]} {_status_label[f.evidence_status]}")
        if f.source_quote:
            st.caption(f"หลักฐาน: “{f.source_quote}”")
        if f.suggestion:
            st.caption(f"แนะนำ: {f.suggestion}")

    for t in tires:
        st.markdown(f"🖋 **{t.message}**" + (f" — {t.suggestion}" if t.suggestion else ""))

    if st.button("💾 บันทึกผลตรวจลง Audit", key="btn_save_verification", type="primary"):
        audit_mgr.save_version(
            doc_id=audit_doc_id(doc),
            doc=doc,
            author="ผู้ใช้ตรวจสอบ",
            note=f"ผลตรวจร่าง: critical {len(critical)} / warning {len(warn)} / ภาษา {len(tires)}",
        )
        st.success("บันทึกผลตรวจเรียบร้อย")
        st.rerun()


def render_right_pane():
    if "export_options" not in st.session_state or not hasattr(st.session_state.export_options, "layout_profile"):
        st.session_state.export_options = ExportOptions()

    doc = st.session_state.doc_data
    placeholder_count = doc.count_placeholders()

    _edit_param = st.query_params.get("edit")
    _ph_param = st.query_params.get("ph")
    if _edit_param:
        try:
            del st.query_params["edit"]
        except KeyError:
            pass
        if _ph_param:
            try:
                del st.query_params["ph"]
            except KeyError:
                pass
        if _edit_param == "header":
            edit_header_dialog()
        elif _edit_param in ("intro", "reason"):
            edit_intro_dialog()
        elif _edit_param in ("facts", "details"):
            edit_facts_dialog()
        elif _edit_param == "law":
            edit_law_dialog()
        elif _edit_param in ("consideration", "purpose", "request", "closing"):
            edit_consideration_dialog()
        elif _edit_param in ("signatory", "sig"):
            edit_signatory_dialog()
        elif _edit_param in ("contact", "dept"):
            edit_contact_dialog()
        elif _edit_param == "placeholders":
            edit_placeholders_dialog(focus_ph=_ph_param)
        elif _edit_param.startswith("sec_"):
            edit_section_dialog(_edit_param.replace("sec_", ""))

    # Row 1: Single-Row Compact Action Bar + View Selector
    r_act_col, r_view_col = st.columns([1.55, 1.15], gap="small")
    with r_act_col:
        btn_w, btn_p, btn_more = st.columns([1.25, 0.95, 1.25], gap="small")
        with btn_w:
            docx_bytes = get_docx_bytes(st.session_state.doc_data, st.session_state.export_options)
            st.download_button(
                label="📥 ดาวน์โหลด Word",
                data=docx_bytes,
                file_name=f"{st.session_state.doc_data.subject[:30].replace('/', '_')}.docx",
                mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                use_container_width=True,
                type="primary"
            )
        with btn_p:
            try:
                pdf_bytes = get_pdf_bytes(st.session_state.doc_data)
                st.download_button(
                    label="📥 PDF",
                    data=pdf_bytes,
                    file_name=f"{st.session_state.doc_data.subject[:30].replace('/', '_')}.pdf",
                    mime="application/pdf",
                    use_container_width=True
                )
            except Exception as _pdf_err:
                st.button(f"⚠️ PDF ({str(_pdf_err)[:8]})", disabled=True, use_container_width=True)
        with btn_more:
            with st.popover("⚙️ ตัวเลือก ▾", use_container_width=True):
                st.markdown("###### ⚙️ ตัวเลือกการส่งออกและการจัดหน้า")
                if st.button("🔢 สลับเลขไทย/อารบิก", use_container_width=True):
                    new_val = not st.session_state.doc_data.use_thai_numerals
                    st.session_state.doc_data = toggle_doc_numerals(st.session_state.doc_data, use_thai=new_val)
                    st.rerun()

                typst_bytes = get_typst_bytes(st.session_state.doc_data)
                st.download_button(
                    label="📄 ดาวน์โหลด Typst (.typ)",
                    data=typst_bytes,
                    file_name=f"{st.session_state.doc_data.subject[:30].replace('/', '_')}.typ",
                    mime="text/plain",
                    use_container_width=True
                )

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

                if st.button("🏛️ สร้างชุด 3 ฉบับตามลำดับชั้น", use_container_width=True):
                    _chain = build_hierarchy_chain(st.session_state.doc_data, get_user_profile())
                    st.session_state.hierarchy_chain = _chain
                    st.session_state.doc_data = _chain[0].document
                    st.rerun()

                st.markdown("---")
                _roles = roles_from_profile(get_user_profile())
                _current_recipient = st.session_state.doc_data.salutation.replace("เรียน", "").strip()
                _role_match = next((i for i, r in enumerate(_roles) if r.recipient == _current_recipient), -1)
                def _on_recipient_change_pop():
                    idx = st.session_state.get("pop_recipient_role_idx", -1)
                    if idx is not None and idx >= 0:
                        st.session_state.doc_data = apply_hierarchy_role(st.session_state.doc_data, _roles[idx])

                st.selectbox(
                    "ส่งถึง (ระดับชั้นการเสนอ)",
                    options=list(range(len(_roles))) + [-1],
                    index=_role_match if _role_match >= 0 else len(_roles),
                    format_func=lambda i: "✏️ กำหนดเอง" if i == -1 else _roles[i].label,
                    key="pop_recipient_role_idx",
                    on_change=_on_recipient_change_pop,
                )

                if "export_options" not in st.session_state or not hasattr(st.session_state.export_options, "layout_profile"):
                    st.session_state.export_options = ExportOptions()
                _eo = st.session_state.export_options
                _profile_choice = st.selectbox(
                    "แม่แบบการจัดหน้า Word",
                    options=["auto", "standard_memo", "standard_external", "form_it9_2026"],
                    index=["auto", "standard_memo", "standard_external", "form_it9_2026"].index(_eo.layout_profile or "auto"),
                    format_func=lambda v: {
                        "auto": "อัตโนมัติตามชนิดหนังสือ",
                        "standard_memo": "บันทึกข้อความมาตรฐาน",
                        "standard_external": "หนังสือภายนอกมาตรฐาน",
                        "form_it9_2026": "ฟอร์มราชการ IT9 (จากไฟล์จริง)",
                    }[v],
                    key="pop_exp_profile",
                )
                _profile = get_layout_profile(None if _profile_choice == "auto" else _profile_choice, st.session_state.doc_data.doc_type)
                _font = st.selectbox(
                    "ฟอนต์ Word",
                    options=["sarabun_new", "psk", "it9"],
                    index=["sarabun_new", "psk", "it9"].index(_profile.font_key),
                    format_func=lambda v: {"sarabun_new": "TH Sarabun New", "psk": "TH Sarabun PSK", "it9": "TH Sarabun IT9"}.get(v, v),
                    key="pop_exp_font",
                )
                _letterhead = st.selectbox(
                    "ตราครุฑ",
                    options=["garuda", "none"],
                    index=0 if _eo.letterhead == "garuda" else 1,
                    format_func=lambda v: "แสดงตราครุฑ" if v == "garuda" else "ไม่แสดงตราครุฑ",
                    key="pop_exp_letterhead",
                )
                _embed = st.checkbox(
                    "ฝังฟอนต์ในไฟล์ Word",
                    value=bool(_eo.embed_fonts),
                    key="pop_exp_embed",
                )
                st.session_state.export_options = ExportOptions(
                    layout_profile=None if _profile_choice == "auto" else _profile_choice,
                    export_font=_font,
                    letterhead=_letterhead,
                    divider=_eo.divider,
                    letter_spacing_pt=float(_profile.letter_spacing_pt),
                    embed_fonts=_embed,
                )

    with r_view_col:
        view_mode = st.radio(
            "มุมมองการทำงาน",
            options=["👁️ A4 พรีวิว", "✏️ ฟอร์มแก้ไข", "🔍 ตรวจ", "📊 Diff"],
            horizontal=True,
            label_visibility="collapsed",
            key="workspace_right_view"
        )

    if view_mode == "👁️ A4 พรีวิว":
        if doc.sections is None and doc.doc_type == DocType.INTERNAL:
            render_memo_pencils(doc)
        elif doc.sections is None:
            render_external_pencils(doc)

        active_placeholders = doc.find_placeholders()
        if active_placeholders:
            c_ph_warn, c_ph_btn = st.columns([2.6, 1.2], gap="small")
            with c_ph_warn:
                st.warning(f"⚠️ พบ {len(active_placeholders)} จุดที่ต้องระบุข้อมูล (คลิกชิปสีเหลืองบนหน้าหนังสือ หรือกดปุ่มเติมข้อมูล)")
            with c_ph_btn:
                if st.button("✏️ เติมข้อมูลจุดนี้ทันที", key="btn_quick_fill_phs", type="primary", use_container_width=True):
                    edit_placeholders_dialog()

        render_a4_paper_canvas()

    elif view_mode == "✏️ ฟอร์มแก้ไข":
        render_form_editor_view()

    elif view_mode == "🔍 ตรวจ":
        render_verification_view()

    elif view_mode == "📊 Diff":
        render_diff_view()



def render_welcome_hero():
    current_profile = st.session_state.user_profile
    raw_name = current_profile.signatory_name or "Jack_Sport"
    clean_name = raw_name.replace("(", "").replace(")", "").replace("นาย", "").replace("นางสาว", "").replace("นาง", "").strip()
    first_name = clean_name.split()[0] if clean_name else "Jack_Sport"

    st.markdown("""
    <div class="govdoc-topbar">
        <div class="govdoc-topbar-crumbs"><span>ร่างหนังสือราชการ</span><span>›</span><strong>เอกสารใหม่</strong></div>
        <div class="govdoc-topbar-status">พร้อมใช้งาน · ระเบียบสารบรรณ พ.ศ. ๒๕๒๖</div>
    </div>
    """, unsafe_allow_html=True)

    st.markdown(f"""
    <div class="hero-wrapper">
        <div class="hero-sparkle-icon">
            <svg width="34" height="34" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
                <path d="M14 2H6C4.89543 2 4 2.89543 4 4V20C4 21.1046 4.89543 22 6 22H18C19.1046 22 20 21.1046 20 20V8L14 2Z" fill="#10b981" fill-opacity="0.16" stroke="#059669" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
                <path d="M14 2V8H20" stroke="#059669" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
                <path d="M9 13H15" stroke="#059669" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
                <path d="M9 17H13" stroke="#059669" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
                <path d="M19 11L20 9L22 8L20 7L19 5L18 7L16 8L18 9L19 11Z" fill="#10b981"/>
            </svg>
        </div>
        <div class="hero-title">สวัสดี คุณ{html.escape(first_name)}</div>
        <div class="hero-subtitle">วันนี้มีอะไรให้ช่วยร่างครับ? พิมพ์คำสั่งหรือแนบไฟล์ต้นเรื่องได้เลย</div>
    </div>
    """, unsafe_allow_html=True)

    # หน้าเริ่มต้นไม่ให้ตั้งค่าชนิดหนังสือหรือชั้นความลับ ระบบจำแนกชนิดจากต้นเรื่อง
    hero_secret = SecretLevel.NORMAL

    with st.container(border=True, key="hero_composer"):
        hero_prompt = st.text_area(
            "คำสั่งหรือเนื้อหาต้นเรื่อง",
            value="",
            placeholder="พิมพ์คำสั่งหรือวางเนื้อหาต้นเรื่อง เช่น เขียนหนังสือขอความอนุเคราะห์ใช้อาคารกีฬาเวสน์ ๑ หรือแนบไฟล์ต้นเรื่อง...",
            height=75,
            label_visibility="collapsed",
            key="hero_prompt_input",
        )

        hc1, hc_spacer, hc3 = st.columns([0.7, 6.0, 1.8], gap="small")
        with hc1:
            with st.popover("📎", use_container_width=True, help="แนบไฟล์ PDF, DOCX, TXT หรือรูปภาพ"):
                hero_file = st.file_uploader(
                    "แนบไฟล์",
                    type=["pdf", "docx", "txt", "png", "jpg", "jpeg"],
                    label_visibility="collapsed",
                    key="hero_file_upload",
                )
        with hc3:
            btn_hero_submit = st.button(
                "↑",
                type="primary",
                use_container_width=True,
                key="hero_submit_btn",
                disabled=(hero_file is None and not hero_prompt.strip()),
                help="วิเคราะห์ข้อความหรือไฟล์ และเตรียมร่างเอกสาร",
            )

        if hero_file is not None:
            st.markdown(f'<div style="margin-top: 8px; display: inline-flex; align-items: center; background: #ecfdf5; border: 1px solid #a7f3d0; border-radius: 8px; padding: 4px 10px; color: #065f46;">📄 {html.escape(hero_file.name)}</div>', unsafe_allow_html=True)

    if btn_hero_submit and hero_file is not None:
        saved_path = uploads_dir / hero_file.name
        with open(saved_path, "wb") as f:
            f.write(hero_file.getbuffer())
        with st.status("กำลังอ่านต้นเรื่อง...", expanded=True) as progress:
            st.write("กำลังสกัดข้อความจากไฟล์")
            ctx = extract_source_document(
                str(saved_path),
                api_key=st.session_state.get("ai_api_key"),
                allow_cloud=st.session_state.get("allow_cloud_ai", True),
                secret=hero_secret,
            )
            st.session_state.source_context = ctx
            st.session_state.last_uploaded_file = hero_file.name
            progress.update(label="กำลังจำแนกเนื้อหาและชนิดหนังสือ...", state="running")
            cls = classify_source_document(ctx)
            st.session_state.classification = cls
            st.session_state.classification_confirmed = True
            if not ctx.extraction_failed:
                progress.update(label="กำลังเตรียมร่างให้ตรวจทาน...", state="running")
                target_type = cls.doc_type
                key = st.session_state.get("ai_api_key") or os.getenv("GEMINI_API_KEY")
                allow_cloud_now = st.session_state.get("allow_cloud_ai", True)
                use_cloud = bool(key) and bool(allow_cloud_now) and cloud_ai_allowed(hero_secret)
                if use_cloud:
                    m_name = os.getenv("GEMINI_MODEL") or "gemini-3.8-flash"
                    draft = draft_from_context_llm(
                        ctx,
                        doc_type=target_type,
                        intent=cls.intent,
                        provider="gemini",
                        model_name=m_name,
                        api_key=key,
                        secret=hero_secret,
                        allow_cloud=allow_cloud_now,
                    )
                else:
                    draft = draft_from_context_rule_based(ctx, doc_type=target_type, intent=cls.intent)
                draft.secret = hero_secret
                st.session_state.doc_data = draft
                st.session_state.initial_ai_draft = draft.model_copy(deep=True)
                progress.update(label="ร่างพร้อมตรวจทาน", state="complete")
                st.session_state.has_active_draft = True
            else:
                progress.update(label="อ่านต้นเรื่องไม่สำเร็จ กรุณาตรวจไฟล์หรือป้อนข้อความด้วยตนเอง", state="error")
        if not ctx.extraction_failed:
            st.rerun()
        else:
            st.error("ยังไม่สร้างร่าง เพราะอ่านเนื้อหาจากไฟล์ไม่ได้ กรุณาลองไฟล์อื่นหรือกรอกข้อความต้นเรื่อง")

    elif btn_hero_submit and hero_prompt.strip():
        with st.spinner("กำลังวิเคราะห์คำสั่งและเตรียมร่างให้ตรวจทาน..."):
            ctx = extract_from_raw_text(hero_prompt.strip(), filename="คำสั่งผู้ใช้.txt")
            st.session_state.source_context = ctx
            cls = classify_source_document(ctx)
            st.session_state.classification = cls
            st.session_state.classification_confirmed = True
            key = st.session_state.get("ai_api_key") or os.getenv("GEMINI_API_KEY")
            allow_cloud_now = st.session_state.get("allow_cloud_ai", True)
            use_cloud = bool(key) and bool(allow_cloud_now) and cloud_ai_allowed(hero_secret)
            if use_cloud:
                m_name = os.getenv("GEMINI_MODEL") or "gemini-3.8-flash"
                draft = draft_from_context_llm(
                    ctx,
                    doc_type=cls.doc_type,
                    intent=cls.intent,
                    provider="gemini",
                    model_name=m_name,
                    api_key=key,
                    secret=hero_secret,
                    allow_cloud=allow_cloud_now,
                )
            else:
                draft = draft_from_context_rule_based(ctx, doc_type=cls.doc_type, intent=cls.intent)
            draft.secret = hero_secret
            clean_p = hero_prompt.strip().replace("\n", " ")
            draft.subject = clean_p[:60] if len(clean_p) <= 60 else clean_p[:60] + "..."
            st.session_state.doc_data = draft
            st.session_state.initial_ai_draft = draft.model_copy(deep=True)
            st.session_state.has_active_draft = True
            st.rerun()

    with st.container(key="hero_pills"):
        p1, p2, p3, p4, p5 = st.columns(5, gap="small")
        with p1:
            if st.button("📄 บันทึกข้อความ", key="pill_memo", use_container_width=True):
                st.session_state.doc_data = create_blank_memo(current_profile)
                st.session_state.initial_ai_draft = st.session_state.doc_data.model_copy(deep=True)
                st.session_state.source_context = None
                st.session_state.has_active_draft = True
                st.rerun()
        with p2:
            if st.button("🏛️ หนังสือภายนอก", key="pill_ext", use_container_width=True):
                st.session_state.doc_data = create_blank_external(current_profile)
                st.session_state.initial_ai_draft = st.session_state.doc_data.model_copy(deep=True)
                st.session_state.source_context = None
                st.session_state.has_active_draft = True
                st.rerun()
        with p3:
            if st.button("📋 คลังแม่แบบ", key="pill_tmpl", use_container_width=True):
                st.session_state.nav_selection = "📋 คลังแบบฟอร์มมาตรฐาน"
                st.rerun()
        with p4:
            if st.button("⚖️ คลังกฎหมาย", key="pill_law", use_container_width=True):
                st.session_state.nav_selection = "⚖️ คลังระเบียบ & กฎหมาย"
                st.rerun()
        with p5:
            if st.button("📂 ตัวอย่างเอกสาร", key="pill_kick", use_container_width=True):
                t = PRESET_TEMPLATES["bma_memo_kickboxing_division"]
                st.session_state.doc_data = t.schema.model_copy(deep=True)
                st.session_state.initial_ai_draft = t.schema.model_copy(deep=True)
                st.session_state.source_context = None
                st.session_state.has_active_draft = True
                st.rerun()

    st.markdown("""
    <div style="text-align: center; margin-top: 10px; margin-bottom: 6px; color: #94a3b8; font-size: 0.78rem;">
        ลองเลือกเครื่องมือเพื่อดูตัวอย่างร่างเอกสารจริงได้ทันที
    </div>
    """, unsafe_allow_html=True)

def render_split_workspace():
    doc = st.session_state.doc_data
    placeholder_count = doc.count_placeholders()

    top_c1, top_c2 = st.columns([1.1, 2.8], gap="medium")
    with top_c1:
        if st.button("← เริ่มร่างฉบับใหม่", key="btn_workspace_back", use_container_width=True, help="กลับสู่หน้าเริ่มต้นเพื่อร่างหนังสือฉบับใหม่"):
            st.session_state.has_active_draft = False
            st.session_state.source_context = None
            st.session_state.last_uploaded_file = None
            st.rerun()
    with top_c2:
        doc_type_name = "หนังสือภายนอก" if doc.doc_type == DocType.EXTERNAL else "บันทึกข้อความ (หนังสือภายใน)"
        status_edit_pill = ""
        if doc.edit_status == "saved":
            time_str = f" {doc.last_edited_at.strftime('%H:%M:%S')}" if doc.last_edited_at else ""
            status_edit_pill = f'<span class="status-pill status-pill-ready">💾 บันทึกแล้ว{time_str}</span>'
        elif doc.edit_status == "editing":
            status_edit_pill = '<span class="status-pill status-pill-warning">✏️ กำลังแก้ไข</span>'
        else:
            status_edit_pill = '<span class="status-pill status-pill-info">📄 ฉบับร่าง</span>'

        ph_pill = f'<span class="status-pill status-pill-warning">⚠️ มี {placeholder_count} จุดที่ต้องระบุ</span>' if placeholder_count > 0 else '<span class="status-pill status-pill-ready">✅ พร้อมตรวจและส่งออก</span>'

        st.markdown(
            f'<div style="display:flex; align-items:center; gap:6px; height:34px;">'
            f'<span class="status-pill status-pill-info">📄 {doc_type_name}</span>'
            f'<span class="status-pill status-pill-info">{doc.urgency.to_thai()}</span>'
            f'{status_edit_pill}'
            f'{ph_pill}'
            f'</div>',
            unsafe_allow_html=True
        )

    col_left, col_right = st.columns([0.92, 1.48], gap="medium")
    with col_left:
        render_left_pane()
    with col_right:
        render_right_pane()



# ----------------- SIDEBAR NAVIGATION & PROFILE -----------------
with st.sidebar:
    st.markdown("""
    <div style="display:flex; align-items:center; gap:10px; margin-bottom:12px; padding: 4px 0;">
        <div style="width:38px; height:38px; background:linear-gradient(135deg, #0f766e 0%, #0d9488 100%); border-radius:10px; display:flex; align-items:center; justify-content:center; color:#fff; font-size:1.3rem; box-shadow:0 2px 6px rgba(15,118,110,0.25);">🏛️</div>
        <div>
            <div style="font-weight:700; font-size:1.05rem; color:#0f172a; line-height:1.2;">GovDoc Studio</div>
            <div style="font-size:0.72rem; color:#64748b;">ระเบียบสารบรรณ พ.ศ. ๒๕๒๖</div>
        </div>
    </div>
    """, unsafe_allow_html=True)
    
    if st.button("➕ แชทใหม่", key="btn_side_new_draft", type="primary", use_container_width=True, help="สร้างร่างฉบับใหม่ และกลับสู่หน้าเริ่มต้น"):
        st.session_state.has_active_draft = False
        st.session_state.source_context = None
        st.session_state.last_uploaded_file = None
        st.session_state.nav_selection = "📝 ห้องร่างหนังสือ"
        st.rerun()

    menu_options = [
        "📝 ห้องร่างหนังสือ",
        "📋 คลังแบบฟอร์มมาตรฐาน",
        "⚖️ คลังระเบียบ & กฎหมาย",
        "📖 สมุดทะเบียนคุมสารบรรณ",
        "⚙️ ตั้งค่าหน่วยงานของฉัน"
    ]
    nav_labels = {
        "📝 ห้องร่างหนังสือ": "📝 ร่างหนังสือ",
        "📋 คลังแบบฟอร์มมาตรฐาน": "📋 คลังแม่แบบ",
        "⚖️ คลังระเบียบ & กฎหมาย": "⚖️ คลังกฎหมาย",
        "📖 สมุดทะเบียนคุมสารบรรณ": "📖 สมุดทะเบียน",
        "⚙️ ตั้งค่าหน่วยงานของฉัน": "⚙️ ตั้งค่า",
    }
    current_nav_idx = menu_options.index(st.session_state.nav_selection) if st.session_state.nav_selection in menu_options else 0
    selected_nav = st.radio(
        "เมนูหลัก",
        menu_options,
        index=current_nav_idx,
        format_func=lambda x: nav_labels.get(x, x),
        label_visibility="collapsed",
        key="main_nav_radio"
    )
    if selected_nav != st.session_state.nav_selection:
        st.session_state.nav_selection = selected_nav
        st.rerun()

    sidebar_search = st.text_input(
        "ค้นหาตัวอย่างงาน",
        placeholder="ค้นหาตัวอย่างเอกสาร...",
        label_visibility="collapsed",
        key="sidebar_search",
    )
    search_q = sidebar_search.strip().lower()

    st.markdown("""
    <div style="margin-top: 16px; margin-bottom: 6px; font-size: 0.72rem; font-weight: 700; color: #94a3b8; text-transform: uppercase; letter-spacing: 0.04em;">
        ตัวอย่างงาน
    </div>
    """, unsafe_allow_html=True)

    if (not search_q or search_q in "ขอสถานที่ เวสน์ ๑".lower()) and st.button("🥊 ขอสถานที่ เวสน์ ๑", key="side_rec_kick", use_container_width=True, help="โหลดตัวอย่างขอความอนุเคราะห์สถานที่อาคารกีฬาเวสน์ ๑"):
        if "bma_memo_kickboxing_division" in PRESET_TEMPLATES:
            t = PRESET_TEMPLATES["bma_memo_kickboxing_division"]
            st.session_state.doc_data = t.schema.model_copy(deep=True)
            st.session_state.initial_ai_draft = t.schema.model_copy(deep=True)
            st.session_state.source_context = None
            st.session_state.has_active_draft = True
            st.session_state.nav_selection = "📝 ห้องร่างหนังสือ"
            st.rerun()

    if (not search_q or search_q in "งานวิ่งเปี้ยว-2569 วิ่ง".lower()) and st.button("🏃 งานวิ่งเปี้ยว-2569", key="side_rec_wing", use_container_width=True, help="โหลดตัวอย่างสแกนงานวิ่งเปี้ยว-2569"):
        wing_path = root_dir / "uploads" / "งานวิ่งเปี้ยว-2569.pdf"
        if wing_path.exists():
            with st.spinner("กำลังอ่านและสกัดข้อความ..."):
                ctx = extract_source_document(str(wing_path), api_key=st.session_state.get("ai_api_key"), allow_cloud=st.session_state.get("allow_cloud_ai", True))
                st.session_state.source_context = ctx
                st.session_state.last_uploaded_file = "งานวิ่งเปี้ยว-2569.pdf"
                st.session_state.classification = classify_source_document(ctx)
                draft = draft_from_context_rule_based(ctx, doc_type=DocType.INTERNAL, intent=DraftingIntent.MEMO_REVIEW)
                st.session_state.doc_data = draft
                st.session_state.initial_ai_draft = draft.model_copy(deep=True)
                st.session_state.has_active_draft = True
                st.session_state.nav_selection = "📝 ห้องร่างหนังสือ"
                st.rerun()

    if (not search_q or search_q in "ทวงถามเงินยืมทดรอง เงินยืม".lower()) and st.button("📑 ทวงถามเงินยืมทดรอง", key="side_rec_memo", use_container_width=True, help="โหลดตัวอย่างบันทึกทวงถามหลักฐานเงินยืม"):
        if "bma_general_memo" in PRESET_TEMPLATES:
            t = PRESET_TEMPLATES["bma_general_memo"]
            st.session_state.doc_data = t.schema.model_copy(deep=True)
            st.session_state.initial_ai_draft = t.schema.model_copy(deep=True)
            st.session_state.source_context = None
            st.session_state.has_active_draft = True
            st.session_state.nav_selection = "📝 ห้องร่างหนังสือ"
            st.rerun()

    st.markdown("<div style='height: 30px;'></div>", unsafe_allow_html=True)
    raw_name = current_profile.signatory_name or "ยังไม่ได้ตั้งชื่อผู้ลงนาม"
    clean_name = raw_name.replace("(", "").replace(")", "").replace("นาย", "").replace("นางสาว", "").replace("นาง", "").strip()
    parts = clean_name.split()
    if len(parts) >= 2:
        user_initials = (parts[0][:1] + parts[1][:1]).strip() or "สล"
    elif parts:
        user_initials = parts[0][:2]
    else:
        user_initials = "สล"
    profile_name = html.escape(raw_name.replace("(", "").replace(")", "").strip())
    profile_position = html.escape(current_profile.signatory_position or "เพิ่มตำแหน่งในตั้งค่า")
    st.markdown(f"""
    <div class="sidebar-user-card">
        <div class="user-avatar-circle">{user_initials}</div>
        <div style="flex: 1; min-width: 0;">
            <div style="font-weight: 600; font-size: 0.82rem; color: #0f172a; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;">{profile_name}</div>
            <div style="font-size: 0.72rem; color: #64748b; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;">{profile_position}</div>
        </div>
        <span style="font-size: 0.68rem; background: #ecfdf5; color: #047857; padding: 2px 6px; border-radius: 9999px; font-weight: 600;">Free</span>
    </div>
    """, unsafe_allow_html=True)

# ----------------- MAIN CONTENT ROUTER -----------------
nav = st.session_state.nav_selection

if nav == "📝 ห้องร่างหนังสือ":
    if not st.session_state.has_active_draft:
        render_welcome_hero()
    else:
        render_split_workspace()

elif nav == "📋 คลังแบบฟอร์มมาตรฐาน":
    render_templates_view()

elif nav == "⚖️ คลังระเบียบ & กฎหมาย":
    st.subheader("⚖️ คลังระเบียบและข้อกฎหมายที่ตรวจยืนยันแล้ว")
    render_profile_view()

elif nav == "📖 สมุดทะเบียนคุมสารบรรณ":
    render_registry_view()

elif nav == "⚙️ ตั้งค่าหน่วยงานของฉัน":
    render_profile_view()
