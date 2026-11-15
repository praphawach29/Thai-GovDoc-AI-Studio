"""
audit.py — ระบบบันทึกประวัติการแก้ไขและเปรียบเทียบความเปลี่ยนแปลง (Audit Trail & Diff Engine)
รองรับ Human-in-the-loop Review สำหรับงานสารบรรณภาครัฐ
"""

import os
import tempfile
import difflib
import sqlite3
import datetime
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple
from pydantic import BaseModel, Field

from core.models import GovDocumentSchema


class DiffBlock(BaseModel):
    op: str = Field(..., description="'equal', 'insert', 'delete', 'replace'")
    original_text: str
    modified_text: str


class FieldDiff(BaseModel):
    field_name: str
    field_label: str
    has_changes: bool
    diff_blocks: List[DiffBlock] = Field(default_factory=list)


class DocumentVersion(BaseModel):
    id: Optional[int] = None
    doc_id: str
    version_num: int
    author: str
    note: str
    doc_data: GovDocumentSchema
    created_at: Optional[str] = None


class AuditLogEntry(BaseModel):
    id: Optional[int] = None
    doc_id: str
    action: str  # draft_created, paragraph_edited, copilot_applied, exported_docx, etc.
    author: str
    details: Dict[str, Any] = Field(default_factory=dict)
    timestamp: Optional[str] = None


def compute_text_diff(original: str, modified: str) -> List[DiffBlock]:
    """
    เปรียบเทียบความแตกต่างระหว่างข้อความ ๒ ชุด
    คืนค่าเป็นรายการของ DiffBlock (equal, insert, delete, replace)
    """
    if original == modified:
        return [DiffBlock(op="equal", original_text=original, modified_text=modified)]

    # แยกคำภาษาไทยหรือวรรค
    orig_words = original.split(" ")
    mod_words = modified.split(" ")

    matcher = difflib.SequenceMatcher(None, orig_words, mod_words)
    blocks = []

    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        orig_sub = " ".join(orig_words[i1:i2])
        mod_sub = " ".join(mod_words[j1:j2])

        if tag == "equal":
            blocks.append(DiffBlock(op="equal", original_text=orig_sub, modified_text=mod_sub))
        elif tag == "insert":
            blocks.append(DiffBlock(op="insert", original_text="", modified_text=mod_sub))
        elif tag == "delete":
            blocks.append(DiffBlock(op="delete", original_text=orig_sub, modified_text=""))
        elif tag == "replace":
            blocks.append(DiffBlock(op="replace", original_text=orig_sub, modified_text=mod_sub))

    return blocks


def compute_doc_diff(original: GovDocumentSchema, modified: GovDocumentSchema) -> List[FieldDiff]:
    """
    เปรียบเทียบความแตกต่างของหนังสือราชการทั้งฉบับแบบรายฟิลด์
    """
    fields_to_check = [
        ("subject", "เรื่อง"),
        ("salutation", "คำขึ้นต้น"),
        ("paragraph_reason", "ภาคเหตุ (ย่อหน้า ๑)"),
        ("paragraph_details", "ภาคข้อเท็จจริง/พิจารณา (ย่อหน้า ๒)"),
        ("paragraph_purpose", "ภาคความประสงค์/สรุป (ย่อหน้า ๓)"),
        ("closing", "คำลงท้าย"),
        ("signatory_name", "ผู้ลงนาม")
    ]

    field_diffs = []

    for field_key, field_label in fields_to_check:
        orig_val = getattr(original, field_key) or ""
        mod_val = getattr(modified, field_key) or ""

        has_change = orig_val != mod_val
        diff_blocks = compute_text_diff(orig_val, mod_val)

        field_diffs.append(FieldDiff(
            field_name=field_key,
            field_label=field_label,
            has_changes=has_change,
            diff_blocks=diff_blocks
        ))

    return field_diffs


class AuditManager:
    """
    ระบบบริหารจัดการประวัติเอกสารและ Audit Trail ด้วย SQLite
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
                db_path = str(db_dir / "audit.db")
                test_conn = sqlite3.connect(db_path)
                test_conn.execute("CREATE TABLE IF NOT EXISTS _health (id INT)")
                test_conn.close()
            except (OSError, sqlite3.OperationalError):
                db_dir = Path(tempfile.gettempdir()) / "data"
                db_dir.mkdir(parents=True, exist_ok=True)
                db_path = str(db_dir / "audit.db")
        self.db_path = db_path
        self._init_db()

    def _get_connection(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        with self._get_connection() as conn:
            cursor = conn.cursor()
            # 1. ตารางเก็บประวัติเวอร์ชันของเอกสาร
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS doc_versions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                doc_id TEXT NOT NULL,
                version_num INTEGER NOT NULL,
                author TEXT NOT NULL,
                note TEXT,
                doc_json TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(doc_id, version_num)
            )
            """)

            # 2. ตารางเก็บบันทึกประวัติกิจกรรม (Audit Trail)
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS audit_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                doc_id TEXT NOT NULL,
                action TEXT NOT NULL,
                author TEXT NOT NULL,
                details_json TEXT,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """)
            conn.commit()

    def save_version(self, doc_id: str, doc: GovDocumentSchema, author: str = "ผู้ตรวจทาน", note: str = "") -> int:
        """บันทึกเวอร์ชันใหม่ของเอกสาร"""
        import json
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT MAX(version_num) as max_v FROM doc_versions WHERE doc_id = ?", (doc_id,))
            row = cursor.fetchone()
            next_v = (row["max_v"] or 0) + 1

            cursor.execute("""
            INSERT INTO doc_versions (doc_id, version_num, author, note, doc_json)
            VALUES (?, ?, ?, ?, ?)
            """, (doc_id, next_v, author, note, doc.model_dump_json()))
            conn.commit()

            # บันทึกลง Audit Trail ควบคู่กัน
            self.log_action(doc_id, "save_version", author, {"version": next_v, "note": note})
            return next_v

    def list_versions(self, doc_id: str) -> List[DocumentVersion]:
        """ดึงประวัติเวอร์ชันทั้งหมดของเอกสาร"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
            SELECT id, doc_id, version_num, author, note, doc_json, created_at
            FROM doc_versions WHERE doc_id = ? ORDER BY version_num ASC
            """, (doc_id,))
            rows = cursor.fetchall()

            versions = []
            for r in rows:
                doc = GovDocumentSchema.model_validate_json(r["doc_json"])
                versions.append(DocumentVersion(
                    id=r["id"],
                    doc_id=r["doc_id"],
                    version_num=r["version_num"],
                    author=r["author"],
                    note=r["note"],
                    doc_data=doc,
                    created_at=r["created_at"]
                ))
            return versions

    def log_action(self, doc_id: str, action: str, author: str, details: Dict[str, Any] = None):
        """บันทึกการกระทำลงใน Audit Trail"""
        import json
        details_str = json.dumps(details or {}, ensure_ascii=False)
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
            INSERT INTO audit_logs (doc_id, action, author, details_json)
            VALUES (?, ?, ?, ?)
            """, (doc_id, action, author, details_str))
            conn.commit()

    def list_logs(self, doc_id: str) -> List[AuditLogEntry]:
        """ดึงรายการ Audit Trail ของเอกสาร"""
        import json
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
            SELECT id, doc_id, action, author, details_json, timestamp
            FROM audit_logs WHERE doc_id = ? ORDER BY id DESC
            """, (doc_id,))
            rows = cursor.fetchall()

            logs = []
            for r in rows:
                details = json.loads(r["details_json"]) if r["details_json"] else {}
                logs.append(AuditLogEntry(
                    id=r["id"],
                    doc_id=r["doc_id"],
                    action=r["action"],
                    author=r["author"],
                    details=details,
                    timestamp=r["timestamp"]
                ))
            return logs

