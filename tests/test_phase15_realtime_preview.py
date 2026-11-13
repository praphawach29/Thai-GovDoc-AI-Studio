"""
test_phase15_realtime_preview.py — ชุดทดสอบระบบคลิกปุ่มดินสอบนหน้าหนังสือ A4 และป็อปอัป Modal Dialog เรียลไทม์
"""

import pytest
from core.models import GovDocumentSchema, DocType, UrgencyLevel, SecretLevel
from core.memo_layout import render_memo_blocks_html, MemoBlock, build_memo_sections, build_memo_blocks
from web.app import highlight_placeholders_html, _persist_pencil_doc
import streamlit as st
from datetime import datetime


def test_highlight_placeholders_html_clickable_chips():
    """ทดสอบว่า Smart Placeholder บนหน้าหนังสือถูกครอบด้วยแท็ก <a> ลิงก์ไปยัง Modal Dialog"""
    text = "เรียน [✏️ ระบุตำแหน่งผู้บังคับบัญชา] เรื่อง [ระบุเรื่อง]"
    html = highlight_placeholders_html(text, clickable=True)
    assert 'class="placeholder-chip-btn"' in html
    assert 'href="?edit=header' in html
    assert "✏️ ระบุตำแหน่งผู้บังคับบัญชา" in html
    assert "✏️ ระบุเรื่อง" in html


def test_highlight_placeholders_html_non_clickable_for_exports():
    """ทดสอบว่าเมื่อ clickable=False จะได้เฉพาะ <span> ธรรมดาไม่มี <a> ลิงก์"""
    text = "เรียน [✏️ ระบุตำแหน่งผู้บังคับบัญชา]"
    html = highlight_placeholders_html(text, clickable=False)
    assert '<a ' not in html
    assert '<span class="placeholder-chip">✏️ ระบุตำแหน่งผู้บังคับบัญชา</span>' in html


def test_render_memo_blocks_html_include_pencils():
    """ทดสอบว่าเมื่อ include_pencils=True จะมีปุ่มดินสอ <a href='?edit=...'> บนหน้าพรีวิว"""
    sections = [
        ("intro", "ต้นเรื่อง", "ตามที่ หน่วยงานมีหนังสือ"),
        ("facts", "ข้อเท็จจริง", "จากการตรวจสอบข้อเท็จจริง"),
        ("consideration", "ข้อพิจารณาและเสนอแนะ", "เห็นควรดำเนินการ"),
    ]
    blocks = build_memo_blocks(sections, request="จึงเรียนมาเพื่อโปรดพิจารณา", style="bma")
    html_preview = render_memo_blocks_html(blocks, include_pencils=True)
    
    assert 'href="?edit=intro"' in html_preview
    assert 'href="?edit=facts"' in html_preview
    assert 'href="?edit=consideration"' in html_preview
    assert 'class="doc-pencil-btn"' in html_preview


def test_render_memo_blocks_html_clean_for_pdf_export():
    """ทดสอบว่าเมื่อ include_pencils=False (ค่าเริ่มต้นสำหรับ PDF/Word) จะไม่มีปุ่มดินสอหรือแท็ก <a> หลุดไป"""
    sections = [
        ("intro", "ต้นเรื่อง", "ตามที่ หน่วยงานมีหนังสือ"),
        ("facts", "ข้อเท็จจริง", "จากการตรวจสอบข้อเท็จจริง"),
        ("consideration", "ข้อพิจารณาและเสนอแนะ", "เห็นควรดำเนินการ"),
    ]
    blocks = build_memo_blocks(sections, request="จึงเรียนมาเพื่อโปรดพิจารณา", style="bma")
    html_export = render_memo_blocks_html(blocks, include_pencils=False)
    
    assert 'href="?edit=' not in html_export
    assert 'doc-pencil-btn' not in html_export


def test_persist_pencil_doc_updates_status_and_timestamp():
    """ทดสอบว่าฟังก์ชัน _persist_pencil_doc อัปเดต edit_status และ last_edited_at"""
    doc = GovDocumentSchema(
        dept_name="สำนักวัฒนธรรม กีฬา และการท่องเที่ยว",
        contact_dept="กองการกีฬา",
        doc_number="กท 0123/2569",
        doc_date="13 พฤศจิกายน 2569",
        subject="รายงานการพิจารณา",
        salutation="เรียน ผู้อำนวยการ",
        paragraph_reason="เหตุผล",
        paragraph_purpose="ความประสงค์",
        signatory_name="(นายสิงห์ ลิ้มพิรัตน์)",
        signatory_position="ผู้อำนวยการสำนัก",
        memo_intro="ต้นเรื่องเดิม",
        memo_facts="ข้อเท็จจริงเดิม",
        memo_consideration="ข้อพิจารณาเดิม",
    )
    assert doc.edit_status == "draft"
    assert doc.last_edited_at is None

    _persist_pencil_doc(doc, summary="ทดสอบการแก้ไขเรียลไทม์")
    assert doc.edit_status == "saved"
    assert isinstance(doc.last_edited_at, datetime)
    assert st.session_state.doc_data == doc
