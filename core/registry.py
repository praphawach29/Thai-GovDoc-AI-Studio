"""
registry.py — ระบบทะเบียนคุมและออกเลขที่หนังสือราชการ (E-Document Registry Engine)
อ้างอิงแนวทางและสถาปัตยกรรมจาก goragodwiriya/edocument & eoffice
"""

import os
import re
import tempfile
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field

from core.models import DocType, GovDocumentSchema
from core.thai_date import current_be_year, format_thai_date
from core.thai_segmenter import to_arabic_numerals, to_thai_numerals


# ---------------------------------------------------------------- รูปแบบเลขที่ (ใช้ทั้งโหมด Supabase และเครื่องเดียว)
# ช่องที่เว้นไว้ให้เติมเลข: placeholder ของ AI, ขีดล่าง, ช่องว่างเขียนมือ (NBSP), จุดไข่ปลา
_GAP_RE = re.compile(r"\[✏️[^\]]*\]|_{2,}|[\u00a0 ]{2,}|\.{3,}|…+")
_CIRCULAR_RE = re.compile(r"\s*ว\s*$")


class NumberTemplate(BaseModel):
    """รูปแบบเลขที่ของหน่วย: เลขลำดับอยู่ระหว่าง prefix กับ suffix

    'กท 1205/[ช่องว่าง]' -> prefix 'กท 1205/'; '[ช่องว่าง]/2569' -> suffix '/2569' (เลขอยู่หน้า);
    'กท ๑๒๓๔/ว [ช่องว่าง]' -> หนังสือเวียน (เล่มเลขของตัวเอง)
    """
    prefix: str = ""
    suffix: str = ""
    is_circular: bool = False

    def format(self, seq: int) -> str:
        num = str(seq)
        if re.search(r"[๐-๙]", self.prefix + self.suffix):
            num = to_thai_numerals(num)
        return self.prefix + ("ว " if self.is_circular else "") + num + self.suffix


def _clean_number_text(doc_number: Optional[str]) -> str:
    text = (doc_number or "").replace("\u200b", "")
    return re.sub(r"^\s*ที่\s+", "", text).strip(" \t\r\n")


def split_number_template(doc_number: Optional[str], fallback_prefix: str = "") -> Optional[NumberTemplate]:
    """แยกรหัสหนังสือจากช่อง "ที่" ของเอกสาร — คืน None ถ้าออกเลขแล้ว (มีเลขลำดับครบ) หรือไม่มีรหัสเลย

    เลขลำดับต้องมาจากฐานข้อมูลเท่านั้น ฟังก์ชันนี้ไม่เดาเลข แค่บอกว่าเลขจะไปอยู่ตรงไหน
    """
    text = _clean_number_text(doc_number)
    match = _GAP_RE.search(text)
    if match:
        prefix = text[:match.start()].rstrip(" \u00a0")
        suffix = text[match.end():].strip(" \u00a0")
    elif not text:
        prefix, suffix = fallback_prefix.strip(), ""
    elif text.endswith("/"):
        prefix, suffix = text, ""
    else:
        return None   # มีเลขครบแล้ว เช่น 'กท 1205/45'
    is_circular = bool(_CIRCULAR_RE.search(prefix)) and "/" in prefix
    if is_circular:
        prefix = _CIRCULAR_RE.sub("", prefix)
    if _GAP_RE.search(prefix + suffix) or not (prefix + suffix).strip():
        return None
    return NumberTemplate(prefix=prefix, suffix=suffix, is_circular=is_circular)


def _is_placeholder(value: Optional[str]) -> bool:
    text = (value or "").strip()
    return not text or "[✏️" in text or bool(_GAP_RE.search(text))


def recipient_from_salutation(salutation: Optional[str]) -> str:
    """'เรียน ผู้อำนวยการสำนัก...' -> 'ผู้อำนวยการสำนัก...' (คอลัมน์ "ถึง" ในทะเบียน)"""
    text = (salutation or "").replace("\u200b", "").strip()
    text = re.sub(r"^(กราบเรียน|เรียน|ถึง)\s*", "", text)
    return "" if _is_placeholder(text) else text


class IssueDraft(BaseModel):
    """ข้อมูลที่จะลงทะเบียนส่งเมื่อกด "ออกเลข" (ผู้ใช้แก้ได้ก่อนยืนยัน)"""
    template: Optional[NumberTemplate] = None
    current_number: str = ""          # เลขที่มีอยู่แล้วในเอกสาร (ถ้าออกแล้ว)
    subject: str = ""
    to_recipient: str = ""
    doc_date: str = ""
    from_unit: str = ""


def issue_draft_for(doc: GovDocumentSchema, fallback_prefix: str = "", today: Optional[str] = None) -> IssueDraft:
    """เตรียม เรื่อง/ถึง/ลงวันที่/จาก จากเอกสาร — วันที่ในเอกสารยังเว้นไว้ = ใช้วันนี้ในทะเบียน"""
    template = split_number_template(doc.doc_number, fallback_prefix)
    date = (doc.doc_date or "").strip()
    # วันที่ครบต้องขึ้นต้นด้วยเลขวัน — บันทึกแบบ กทม. เว้นเลขวันไว้เขียนมือ ("          พฤศจิกายน 2569")
    if not re.match(r"^[0-9๐-๙]{1,2}\s", date):
        date = ""
    return IssueDraft(
        template=template,
        current_number="" if template else _clean_number_text(doc.doc_number),
        subject="" if _is_placeholder(doc.subject) else doc.subject.strip(),
        to_recipient=recipient_from_salutation(doc.salutation),
        doc_date=date if not _is_placeholder(date) else (today or format_thai_date()),
        from_unit="" if _is_placeholder(doc.dept_name) else re.sub(r"\s+", " ", doc.dept_name).strip(),
    )


def normalize_search(text: Optional[str]) -> str:
    """เทียบคำค้นแบบไม่สนเลขไทย/อารบิก ตัวพิมพ์ และช่องว่าง"""
    return re.sub(r"\s+", "", to_arabic_numerals(str(text or "")).lower())


def search_rows(rows: List[Dict[str, Any]], query: str, fields: List[str]) -> List[Dict[str, Any]]:
    """ค้นในทะเบียน: ทุกคำในคำค้นต้องพบในคอลัมน์ใดคอลัมน์หนึ่ง"""
    words = [normalize_search(w) for w in (query or "").split() if w.strip()]
    if not words:
        return list(rows)
    out = []
    for row in rows:
        hay = " ".join(normalize_search(row.get(f)) for f in fields)
        if all(w in hay for w in words):
            out.append(row)
    return out


class DuplicateRegistryEntry(ValueError):
    """เลขที่นี้มีในทะเบียนแล้ว — ทะเบียนห้ามเขียนทับรายการเดิม"""


class OutgoingRecord(BaseModel):
    id: Optional[int] = None
    doc_number: str
    doc_type: str
    subject: str
    recipient: str
    doc_date: str
    created_by: str = "เจ้าหน้าที่สารบรรณ"
    status: str = "sent"  # draft, reserved, sent, archived
    file_path: Optional[str] = None
    created_at: Optional[str] = None


class IncomingRecord(BaseModel):
    id: Optional[int] = None
    receive_number: str
    source_doc_no: str
    source_dept: str
    subject: str
    receive_date: str
    receiver: str = "งานสารบรรณกลาง"
    status: str = "received"
    attachment_path: Optional[str] = None
    created_at: Optional[str] = None


class DocumentRegistry:
    """
    ระบบทะเบียนคุมสารบรรณอิเล็กทรอนิกส์ จัดเก็บข้อมูลด้วย SQLite
    รองรับ: ออกเลขอัตโนมัติ, จองเลขหนังสือ, ทะเบียนส่ง, และทะเบียนรับ
    """
    def __init__(self, db_path: Optional[str] = None):
        if not db_path:
            root_dir = Path(__file__).resolve().parent.parent
            if os.environ.get("VERCEL") or not os.access(root_dir, os.W_OK):
                db_dir = Path(tempfile.gettempdir()) / "data"
            else:
                db_dir = root_dir / "data"

            try:
                db_dir.mkdir(parents=True, exist_ok=True)
                db_path = str(db_dir / "edocument.db")
                test_conn = sqlite3.connect(db_path)
                test_conn.execute("CREATE TABLE IF NOT EXISTS _health (id INT)")
                test_conn.close()
            except (OSError, sqlite3.OperationalError):
                db_dir = Path(tempfile.gettempdir()) / "data"
                db_dir.mkdir(parents=True, exist_ok=True)
                db_path = str(db_dir / "edocument.db")
        self.db_path = db_path
        self._init_db()

    @contextmanager
    def _get_connection(self):
        # sqlite3 ใช้ "with conn" คุมแค่ transaction ไม่ได้ปิดการเชื่อมต่อ จึงปิดเองที่นี่
        # timeout รอ lock เมื่อมีผู้เขียนพร้อมกัน แทนการล้มทันทีด้วย "database is locked"
        conn = sqlite3.connect(self.db_path, timeout=30)
        conn.row_factory = sqlite3.Row
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def _init_db(self):
        with self._get_connection() as conn:
            cursor = conn.cursor()
            # 1. ตารางทะเบียนส่ง (Outgoing Register)
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS outgoing_register (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                doc_number TEXT NOT NULL UNIQUE,
                doc_type TEXT NOT NULL,
                subject TEXT NOT NULL,
                recipient TEXT NOT NULL,
                doc_date TEXT NOT NULL,
                created_by TEXT DEFAULT 'เจ้าหน้าที่สารบรรณ',
                status TEXT DEFAULT 'sent',
                file_path TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """)

            # 2. ตารางทะเบียนรับ (Incoming Register)
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS incoming_register (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                receive_number TEXT NOT NULL UNIQUE,
                source_doc_no TEXT,
                source_dept TEXT NOT NULL,
                subject TEXT NOT NULL,
                receive_date TEXT NOT NULL,
                receiver TEXT DEFAULT 'งานสารบรรณกลาง',
                status TEXT DEFAULT 'received',
                attachment_path TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """)

            # 3. ตารางรันลำดับเลขที่หนังสือ (Sequences)
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS doc_sequences (
                prefix TEXT PRIMARY KEY,
                year_be INTEGER NOT NULL,
                current_seq INTEGER NOT NULL DEFAULT 0
            )
            """)
            conn.commit()

    @staticmethod
    def get_current_be_year() -> int:
        """คืนค่าปี พ.ศ. ปัจจุบัน (ตามเวลาประเทศไทย ไม่ใช่เวลาเครื่องเซิร์ฟเวอร์)"""
        return current_be_year()

    @staticmethod
    def _sequence_key(prefix: str, is_circular: bool) -> str:
        # หนังสือเวียนมีเลขทะเบียนชุดของตัวเอง (เริ่ม ๑ ใหม่ทุกปีปฏิทิน) แยกจากหนังสือส่งปกติ
        return f"{prefix}\u0e27" if is_circular else prefix

    @staticmethod
    def _format_doc_number(prefix: str, seq: int, is_circular: bool) -> str:
        seq_str = str(seq)
        # ให้ตัวเลขชุดเดียวกันทั้งเลขที่: ถ้ารหัสหน่วยงานใช้เลขไทย เลขลำดับก็ใช้เลขไทย
        if any("\u0e50" <= ch <= "\u0e59" for ch in prefix):
            seq_str = to_thai_numerals(seq_str)
        return f"{prefix}ว {seq_str}" if is_circular else f"{prefix}{seq_str}"

    def peek_next_doc_number(self, prefix: str = "ดพร ๐๑๐๒/", is_circular: bool = False) -> str:
        """ดูเลขที่หนังสือลำดับถัดไปโดยไม่ออกเลขจริง (ไม่กินเลขในทะเบียน)"""
        key = self._sequence_key(prefix, is_circular)
        with self._get_connection() as conn:
            row = conn.execute(
                "SELECT current_seq FROM doc_sequences WHERE prefix = ? AND year_be = ?",
                (key, self.get_current_be_year()),
            ).fetchone()
        return self._format_doc_number(prefix, (row["current_seq"] if row else 0) + 1, is_circular)

    def get_next_doc_number(self, prefix: str = "ดพร ๐๑๐๒/", is_circular: bool = False) -> str:
        """
        ออกเลขที่หนังสือราชการ (กินเลขจริง) เช่น ดพร ๐๑๐๒/๑, ดพร ๐๑๐๒/ว ๑๒

        ใช้คำสั่ง UPSERT ... RETURNING คำสั่งเดียว ฐานข้อมูลจึงล็อกแถวให้เอง
        ผู้ใช้หลายคนกดพร้อมกันก็ไม่ได้เลขซ้ำ และเริ่มนับ ๑ ใหม่ทุกปีปฏิทิน
        """
        key = self._sequence_key(prefix, is_circular)
        with self._get_connection() as conn:
            row = conn.execute(
                """
                INSERT INTO doc_sequences (prefix, year_be, current_seq) VALUES (?, ?, 1)
                ON CONFLICT(prefix) DO UPDATE SET
                    current_seq = CASE WHEN doc_sequences.year_be = excluded.year_be
                                       THEN doc_sequences.current_seq + 1 ELSE 1 END,
                    year_be = excluded.year_be
                RETURNING current_seq
                """,
                (key, self.get_current_be_year()),
            ).fetchone()
            conn.commit()
        return self._format_doc_number(prefix, row["current_seq"], is_circular)

    def reserve_doc_number(self, prefix: str, subject: str, reserved_by: str, doc_type: str = "external") -> str:
        """
        จองเลขที่หนังสือราชการล่วงหน้า (Number Reservation)
        """
        doc_no = self.get_next_doc_number(prefix)
        today_thai = format_thai_date()

        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
            INSERT INTO outgoing_register (doc_number, doc_type, subject, recipient, doc_date, created_by, status)
            VALUES (?, ?, ?, ?, ?, ?, 'reserved')
            """, (doc_no, doc_type, subject, "ยังไม่ระบุ (จองเลข)", today_thai, reserved_by))
            conn.commit()
        return doc_no

    def register_outgoing(self, record: OutgoingRecord) -> int:
        """บันทึกลงสมุดทะเบียนส่งหนังสือ"""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                INSERT INTO outgoing_register (doc_number, doc_type, subject, recipient, doc_date, created_by, status, file_path)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    record.doc_number, record.doc_type, record.subject,
                    record.recipient, record.doc_date, record.created_by,
                    record.status, record.file_path
                ))
                conn.commit()
                return cursor.lastrowid
        except sqlite3.IntegrityError as exc:
            raise DuplicateRegistryEntry(f"เลข {record.doc_number} มีในทะเบียนแล้ว") from exc

    def register_incoming(self, record: IncomingRecord) -> int:
        """บันทึกลงสมุดทะเบียนรับหนังสือ"""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                INSERT INTO incoming_register (receive_number, source_doc_no, source_dept, subject, receive_date, receiver, status, attachment_path)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    record.receive_number, record.source_doc_no, record.source_dept,
                    record.subject, record.receive_date, record.receiver,
                    record.status, record.attachment_path
                ))
                conn.commit()
                return cursor.lastrowid
        except sqlite3.IntegrityError as exc:
            raise DuplicateRegistryEntry(f"เลข {record.receive_number} มีในทะเบียนแล้ว") from exc

    def list_outgoing(self, limit: int = 50) -> List[Dict[str, Any]]:
        """ดึงรายการทะเบียนส่งล่าสุด"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM outgoing_register ORDER BY id DESC LIMIT ?", (limit,))
            return [dict(row) for row in cursor.fetchall()]

    def list_incoming(self, limit: int = 50) -> List[Dict[str, Any]]:
        """ดึงรายการทะเบียนรับล่าสุด"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM incoming_register ORDER BY id DESC LIMIT ?", (limit,))
            return [dict(row) for row in cursor.fetchall()]

    @staticmethod
    def _get_thai_month(month: int) -> str:
        months = [
            "", "มกราคม", "กุมภาพันธ์", "มีนาคม", "เมษายน", "พฤษภาคม", "มิถุนายน",
            "กรกฎาคม", "สิงหาคม", "กันยายน", "ตุลาคม", "พฤศจิกายน", "ธันวาคม"
        ]
        return months[month] if 1 <= month <= 12 else ""

