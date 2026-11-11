"""
registry.py — ระบบทะเบียนคุมและออกเลขที่หนังสือราชการ (E-Document Registry Engine)
อ้างอิงแนวทางและสถาปัตยกรรมจาก goragodwiriya/edocument & eoffice
"""

import sqlite3
import datetime
from pathlib import Path
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field

from core.models import DocType


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
            db_dir = Path(__file__).resolve().parent.parent / "data"
            db_dir.mkdir(exist_ok=True)
            db_path = str(db_dir / "edocument.db")
        self.db_path = db_path
        self._init_db()

    def _get_connection(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

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
        """คืนค่าปี พ.ศ. ปัจจุบัน"""
        return datetime.datetime.now().year + 543

    def get_next_doc_number(self, prefix: str = "ดพร ๐๑๐๒/", is_circular: bool = False) -> str:
        """
        ออกเลขที่หนังสือราชการอัตโนมัติ (Auto-increment Numbering)
        เช่น: ดพร ๐๑๐๒/๑, ดพร ๐๑๐๒/ว ๑๒
        """
        year_be = self.get_current_be_year()
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT current_seq FROM doc_sequences WHERE prefix = ? AND year_be = ?",
                (prefix, year_be)
            )
            row = cursor.fetchone()
            if row:
                next_seq = row["current_seq"] + 1
                cursor.execute(
                    "UPDATE doc_sequences SET current_seq = ? WHERE prefix = ? AND year_be = ?",
                    (next_seq, prefix, year_be)
                )
            else:
                next_seq = 1
                cursor.execute(
                    "INSERT INTO doc_sequences (prefix, year_be, current_seq) VALUES (?, ?, ?)",
                    (prefix, year_be, next_seq)
                )
            conn.commit()

        # จัดรูปแบบเลข
        seq_str = str(next_seq)
        if is_circular:
            return f"{prefix}ว {seq_str}"
        return f"{prefix}{seq_str}"

    def reserve_doc_number(self, prefix: str, subject: str, reserved_by: str, doc_type: str = "external") -> str:
        """
        จองเลขที่หนังสือล่วงหน้า (Number Reservation)
        """
        doc_no = self.get_next_doc_number(prefix)
        today_thai = f"{datetime.datetime.now().day} {self._get_thai_month(datetime.datetime.now().month)} {self.get_current_be_year()}"
        
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
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
            INSERT OR REPLACE INTO outgoing_register (doc_number, doc_type, subject, recipient, doc_date, created_by, status, file_path)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                record.doc_number, record.doc_type, record.subject,
                record.recipient, record.doc_date, record.created_by,
                record.status, record.file_path
            ))
            conn.commit()
            return cursor.lastrowid

    def register_incoming(self, record: IncomingRecord) -> int:
        """บันทึกลงสมุดทะเบียนรับหนังสือ"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
            INSERT OR REPLACE INTO incoming_register (receive_number, source_doc_no, source_dept, subject, receive_date, receiver, status, attachment_path)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                record.receive_number, record.source_doc_no, record.source_dept,
                record.subject, record.receive_date, record.receiver,
                record.status, record.attachment_path
            ))
            conn.commit()
            return cursor.lastrowid

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

