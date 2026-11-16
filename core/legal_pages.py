"""legal_pages.py — แนบหน้าของข้อกฎหมายที่เลือก (จากไฟล์สแกนต้นฉบับในคลัง) ต่อท้าย PDF

ไม่พิมพ์ข้อความใหม่ — ดึงหน้าจริงจากไฟล์ที่นำเข้า หน้าตาเหมือนที่หน่วยงานพิมพ์แนบอยู่เดิม
"""

from __future__ import annotations

from io import BytesIO
from typing import Dict, Iterable, List, Tuple

from core.models import LegalCitation


def plan_pages(citations: Iterable[LegalCitation]) -> List[Tuple[str, List[int]]]:
    """[(source_id, [หน้า...])] ตามลำดับที่ผู้ใช้เลือกไฟล์ — หน้าที่ซ้ำ/ทับกันแนบครั้งเดียว เรียงตามหน้าในไฟล์"""
    order: List[str] = []
    pages: Dict[str, set] = {}
    for c in citations or []:
        if not c.source_id or not c.page_from:
            continue                      # รายการที่เพิ่มเอง (ไม่มีไฟล์ต้นฉบับ) ไม่มีหน้าให้แนบ
        first = max(1, int(c.page_from))
        last = max(first, int(c.page_to or first))
        if c.source_id not in pages:
            order.append(c.source_id)
            pages[c.source_id] = set()
        pages[c.source_id].update(range(first, min(last, first + 200) + 1))
    return [(sid, sorted(pages[sid])) for sid in order]


def append_pages(writer, pdf_bytes: bytes, page_numbers: List[int]) -> int:
    """ต่อหน้าที่กำหนด (เริ่ม 1) จากไฟล์ต้นฉบับท้าย writer — หน้าที่เกินจำนวนในไฟล์ข้ามไป คืนจำนวนหน้าที่แนบ"""
    from pypdf import PdfReader

    reader = PdfReader(BytesIO(pdf_bytes))
    added = 0
    for n in page_numbers:
        if 1 <= n <= len(reader.pages):
            writer.add_page(reader.pages[n - 1])
            added += 1
    return added
