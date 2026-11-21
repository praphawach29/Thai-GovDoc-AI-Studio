"""
doc_forms.py — หนังสือราชการชนิดอื่นนอกจากหนังสือภายนอก/บันทึกข้อความ (ระเบียบงานสารบรรณ พ.ศ. ๒๕๒๖)

- หนังสือประทับตรา (แบบที่ ๓): ที่ · ถึง · ข้อความ · ส่วนราชการที่ส่งหนังสือออก · ตราชื่อส่วนราชการ
  (หมึกแดง + ลงชื่อย่อกำกับตรา) · วัน เดือน ปี · ส่วนราชการเจ้าของเรื่อง · โทร. โทรสาร ไปรษณีย์อิเล็กทรอนิกส์
  ไม่มี "เรื่อง" บนหนังสือ (เก็บ subject ไว้ลงทะเบียน), ไม่มีคำขึ้นต้น/คำลงท้าย/ผู้ลงนาม

ใช้ร่วมกันทั้งหน้าเว็บ Word และ PDF: เนื้อความทุกบรรทัดคือย่อหน้า (body_lines)
"""

from __future__ import annotations

import re
from typing import List, Optional, Tuple

from core.models import DocType, DocumentKind, GovDocumentSchema

# ระยะย่อหน้า: ทุกบรรทัด 2.5 ซม., ๑.๑ = 3.5 ซม., ๑.๑.๑ = 4.5 ซม.; แท็บนำหน้า N ตัว = ระดับ N (ผู้ใช้กำหนดเอง)
# ต่างจากบันทึกข้อความตรงที่ "ข้อ ๑" อยู่ระดับ ๑ (ข้อของคำสั่ง/ระเบียบเริ่มที่ย่อหน้าปกติ)
BODY_INDENT_CM = 2.5
LEVEL_STEP_CM = 1.0
_MAX_LEVEL = 6
_RE_L3 = re.compile(r"^[0-9๐-๙]+\.[0-9๐-๙]+\.[0-9๐-๙]+")
_RE_L2 = re.compile(r"^[0-9๐-๙]+\.[0-9๐-๙]+")

STAMP_GAP_CM = 2.2          # ที่ว่างสำหรับประทับตราชื่อส่วนราชการ + ลงชื่อย่อกำกับตรา (ระหว่างชื่อส่วนราชการกับวันที่)
SENDER_INDENT_CM = 8.0      # ส่วนราชการที่ส่ง/วันที่ ของหนังสือประทับตรา เริ่มที่แนวกึ่งกลางพื้นที่พิมพ์


def line_level(line: str) -> int:
    tabs = len(line) - len(line.lstrip("\t"))
    if tabs:
        return min(tabs, _MAX_LEVEL)
    s = line.strip()
    if _RE_L3.match(s):
        return 3
    if _RE_L2.match(s):
        return 2
    return 1


def body_lines(*texts: Optional[str]) -> List[Tuple[float, str]]:
    """ย่อหน้าเนื้อความ [(ระยะย่อหน้า ซม., ข้อความ)] จากหลายช่องต่อกัน — บรรทัดว่างถูกข้าม"""
    out: List[Tuple[float, str]] = []
    for text in texts:
        for raw in (text or "").splitlines():
            if not raw.strip():
                continue
            indent = BODY_INDENT_CM + (line_level(raw) - 1) * LEVEL_STEP_CM
            out.append((indent, raw.lstrip("\t").strip()))
    return out


_SAL_RE = re.compile(r"^(กราบเรียน|เรียน|ถึง)\s*")


def recipient_of(salutation: str) -> str:
    return _SAL_RE.sub("", (salutation or "").strip()).strip()


def sender_name(dept: str) -> str:
    """ชื่อส่วนราชการอย่างเดียว: บรรทัดแรก ตัดวงเล็บท้ายที่มีโทรศัพท์ (แบบช่องส่วนราชการของบันทึกข้อความ)"""
    first = (dept or "").split("\n")[0].strip()
    return re.sub(r"\s*\([^()]*โทร[^()]*\)\s*$", "", first).strip()


def to_stamp_letter(doc: GovDocumentSchema, sender: Optional[str] = None) -> GovDocumentSchema:
    """แปลงร่างหนังสือภายนอก (ร่างตามกฎ) เป็นหนังสือประทับตรา: "ถึง" แทน "เรียน", ไม่มีคำลงท้าย/อ้างถึง/สิ่งที่ส่งมาด้วย
    ส่วนราชการที่ส่ง = ชื่อส่วนราชการบรรทัดแรก (ไม่มีที่อยู่)"""
    d = doc.model_copy(deep=True)
    d.kind = DocumentKind.STAMP_LETTER
    d.doc_type = DocType.EXTERNAL
    d.salutation = f"ถึง  {recipient_of(d.salutation) or '[✏️ ระบุผู้รับ]'}"
    d.closing = ""
    d.references = None
    d.attachments = None
    d.signatory_stamp = False
    d.co_signers = None
    d.dept_name = sender_name(sender or d.dept_name) or "[✏️ ระบุส่วนราชการที่ส่งหนังสือออก]"
    return d


class FormalSpec:
    """แบบหัวกลาง (คำสั่ง แบบที่ ๔ / ระเบียบ ๕ / ข้อบังคับ ๖ / ประกาศ ๗)
    ครุฑ 3 ซม. · ชื่อเอกสาร (เช่น "คำสั่งกองการกีฬา") · ที่ (เฉพาะคำสั่ง) · เรื่อง/ว่าด้วย · เส้นคั่น
    · ข้อความ · "<สั่ง/ประกาศ> ณ วันที่ ..." · ลายมือชื่อ ชื่อเต็ม ตำแหน่ง"""

    def __init__(self, prefix: str, subject_label: str, date_label: str, number: bool, blank: Tuple[str, str, str]):
        self.prefix = prefix
        self.subject_label = subject_label
        self.date_label = date_label
        self.number = number
        self.blank = blank


FORMAL = {
    DocumentKind.ORDER: FormalSpec(
        "คำสั่ง", "เรื่อง", "สั่ง ณ วันที่", True,
        ("[✏️ ระบุเหตุผลที่ออกคำสั่ง] และอาศัยอำนาจตาม[✏️ ระบุกฎหมาย/ระเบียบที่ให้อำนาจ] จึง[✏️ ระบุสิ่งที่สั่ง] ดังนี้",
         "๑. [✏️ ระบุรายการที่สั่ง]",
         "ทั้งนี้ ตั้งแต่บัดนี้เป็นต้นไป"),
    ),
    DocumentKind.ANNOUNCEMENT: FormalSpec(
        "ประกาศ", "เรื่อง", "ประกาศ ณ วันที่", False,
        ("ด้วย[✏️ ระบุเหตุผล/ความเป็นมาของเรื่องที่ประกาศ]",
         "[✏️ ระบุรายละเอียดที่ประกาศ เช่น คุณสมบัติ กำหนดการ สถานที่]",
         "จึงประกาศให้ทราบโดยทั่วกัน"),
    ),
    DocumentKind.REGULATION: FormalSpec(
        "ระเบียบ", "ว่าด้วย", "ประกาศ ณ วันที่", False,
        ("โดยที่เป็นการสมควร[✏️ ระบุเหตุผลที่วางระเบียบ] อาศัยอำนาจตาม[✏️ ระบุกฎหมายที่ให้อำนาจ] จึงวางระเบียบไว้ ดังต่อไปนี้",
         "ข้อ ๑ ระเบียบนี้เรียกว่า \"[✏️ ระบุชื่อระเบียบ]\"\n"
         "ข้อ ๒ ระเบียบนี้ให้ใช้บังคับตั้งแต่[✏️ ระบุวันที่ใช้บังคับ]เป็นต้นไป\n"
         "ข้อ ๓ [✏️ ระบุสาระของระเบียบ]\n"
         "ข้อ ๔ ให้[✏️ ระบุตำแหน่ง]รักษาการตามระเบียบนี้",
         ""),
    ),
    DocumentKind.BYLAW: FormalSpec(
        "ข้อบังคับ", "ว่าด้วย", "ประกาศ ณ วันที่", False,
        ("โดยที่เป็นการสมควร[✏️ ระบุเหตุผลที่วางข้อบังคับ] อาศัยอำนาจตาม[✏️ ระบุกฎหมายที่ให้อำนาจ] จึงวางข้อบังคับไว้ ดังต่อไปนี้",
         "ข้อ ๑ ข้อบังคับนี้เรียกว่า \"[✏️ ระบุชื่อข้อบังคับ]\"\n"
         "ข้อ ๒ ข้อบังคับนี้ให้ใช้บังคับตั้งแต่[✏️ ระบุวันที่ใช้บังคับ]เป็นต้นไป\n"
         "ข้อ ๓ [✏️ ระบุสาระของข้อบังคับ]",
         ""),
    ),
}
# ระเบียบ/ข้อบังคับ: มีบรรทัด (ฉบับที่ ...) และ พ.ศ. ใต้ "ว่าด้วย"; ภาคท้าย (paragraph_purpose) ว่างได้
WITH_YEAR_LINE = frozenset({DocumentKind.REGULATION, DocumentKind.BYLAW})

# ระยะของแบบหัวกลาง (Word = PDF = หน้าแก้ไข)
FORMAL_RULE_CM = 4.0            # เส้นคั่นใต้เรื่อง ยาว 4 ซม. กึ่งกลาง
FORMAL_DATE_INDENT_CM = 5.0     # "สั่ง ณ วันที่ ..." เริ่ม 5 ซม. จากขอบซ้ายพื้นที่พิมพ์
FORMAL_SIGN_LEFT_CM = 6.0       # ผู้ลงนามกึ่งกลางในช่วง 6 ซม. ถึงขอบขวา (เหมือนบันทึกข้อความ)

def formal_extra_lines(doc: GovDocumentSchema) -> List[str]:
    """บรรทัดใต้ "ว่าด้วย" ของระเบียบ/ข้อบังคับ (ฉบับที่ ..., พ.ศ. ...) — คำสั่ง/ประกาศไม่มี"""
    if doc.kind not in WITH_YEAR_LINE:
        return []
    out = []
    edition = (doc.special_edition or "").strip()
    if edition:
        edition = re.sub(r"^\(?\s*ฉบับที่\s*", "", edition).rstrip(")").strip()
        out.append(f"(ฉบับที่ {edition})")
    out.append((doc.special_year or "").strip() or year_line(doc.doc_date))
    return [x for x in out if x]


def year_line(date: str) -> str:
    """'๑๗ พฤศจิกายน พ.ศ. ๒๕๖๙' → 'พ.ศ. ๒๕๖๙' (บรรทัดปีของระเบียบ/ข้อบังคับ)"""
    m = _YEAR_RE.match((date or "").strip())
    return f"พ.ศ. {m.group(2)}" if m and "[" not in date else ""


_YEAR_RE = re.compile(r"^(.*?)\s*(?:พ\.ศ\.\s*)?([0-9๐-๙]{4})\s*$")


def with_buddhist_era(date: str) -> str:
    """'๑๗ พฤศจิกายน ๒๕๖๙' → '๑๗ พฤศจิกายน พ.ศ. ๒๕๖๙' (แบบคำสั่ง/ประกาศ ระบุ พ.ศ.)"""
    m = _YEAR_RE.match((date or "").strip())
    if not m or "[" in date:
        return date
    return f"{m.group(1).strip()} พ.ศ. {m.group(2)}".strip()


def to_formal(doc: GovDocumentSchema, kind: DocumentKind, issuer: Optional[str] = None) -> GovDocumentSchema:
    """แปลงร่างหนังสือภายนอกเป็นแบบหัวกลาง: ชื่อเอกสาร = คำนำหน้า + ชื่อส่วนราชการ, ไม่มีคำขึ้นต้น/ลงท้าย/อ้างถึง"""
    spec = FORMAL[kind]
    d = doc.model_copy(deep=True)
    d.kind = kind
    d.doc_type = DocType.EXTERNAL
    name = sender_name(issuer or d.dept_name) or "[✏️ ระบุชื่อส่วนราชการ]"
    d.special_title = f"{spec.prefix}{name}"
    d.dept_name = name
    d.salutation = ""
    d.closing = ""
    d.references = None
    d.attachments = None
    d.co_signers = None
    d.doc_date = with_buddhist_era(d.doc_date)
    if kind in WITH_YEAR_LINE and not d.special_year:
        d.special_year = year_line(d.doc_date) or None
    return d


def to_project(doc: GovDocumentSchema, agency: Optional[str] = None) -> GovDocumentSchema:
    """แบบเสนอโครงการ กทม.: ชื่อโครงการ = subject, ส่วนอื่นเป็นโครงเปล่าใน doc.project
    ไม่มีส่วนหัว/ท้ายของหนังสือ (ที่ วันที่ เรียน คำลงท้าย) — ช่องเหล่านั้นว่างไว้"""
    from core.project import blank_project

    d = doc.model_copy(deep=True)
    d.kind = DocumentKind.PROJECT
    d.doc_type = DocType.EXTERNAL
    d.project = blank_project(agency=(agency or "").strip())
    d.subject = "โครงการ[✏️ ระบุชื่อโครงการ]"
    d.salutation = ""
    d.closing = ""
    d.references = None
    d.attachments = None
    d.co_signers = None
    d.paragraph_reason = d.paragraph_details = d.paragraph_purpose = ""
    d.memo_intro = d.memo_facts = d.memo_law = d.memo_consideration = d.memo_request = None
    return d


def apply_form(doc: GovDocumentSchema, kind: DocumentKind, issuer: Optional[str] = None) -> GovDocumentSchema:
    """แปลงร่างตามกฎ (หนังสือภายนอก) เป็นชนิดที่เลือก — ชนิดเดิม (ภายนอก/บันทึก) คืนค่าเดิม
    issuer = ชื่อส่วนราชการ (ไม่มีที่อยู่/โทรศัพท์) จากโปรไฟล์หน่วยงาน
    เนื้อความเป็นโครงของชนิดนั้น (ร่างตามกฎของหนังสือภายนอกใช้กับแบบอื่นไม่ได้) — AI เขียนทับเมื่อร่างสำเร็จ"""
    if kind == DocumentKind.PROJECT:
        return to_project(doc, agency=issuer)
    if kind == DocumentKind.STAMP_LETTER:
        d = to_stamp_letter(doc, sender=issuer)
    elif kind in FORMAL:
        d = to_formal(doc, kind, issuer)
    else:
        return doc
    d.paragraph_reason, d.paragraph_details, d.paragraph_purpose = blank_body(kind)
    if "[✏️" in (d.subject or ""):
        d.subject = "[✏️ ระบุเรื่อง]"          # เรื่องที่ร่างตามกฎเดาจากหนังสือภายนอก (เช่น "การให้ความอนุเคราะห์...")
    return d


def blank_body(kind: DocumentKind) -> Tuple[str, str, str]:
    """(ภาคเหตุ, ภาคข้อเท็จจริง, ภาคความประสงค์) ของเอกสารเปล่า"""
    if kind == DocumentKind.STAMP_LETTER:
        return ("[✏️ ระบุที่มาของเรื่อง เช่น ตามที่... นั้น]", "[✏️ ระบุสิ่งที่ขอ/แจ้ง]", "จึงเรียนมาเพื่อโปรดทราบ")
    if kind in FORMAL:
        return FORMAL[kind].blank
    return ("[✏️ ระบุภาคเหตุ]", "[✏️ ระบุภาคข้อเท็จจริง]", "[✏️ ระบุภาคความประสงค์]")
