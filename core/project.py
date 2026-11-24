"""
project.py — แบบเสนอโครงการของกรุงเทพมหานคร (รูปแบบการเขียนโครงการ / คู่มือการเขียนโครงการ กทม.)

ชื่อโครงการ · หน่วยงาน · ปีงบประมาณ · เส้นคั่น แล้วหัวข้อ ๑–๑๐:
  ๑ หลักการและเหตุผล ๒ วัตถุประสงค์ ๓ เป้าหมาย ๔ ลักษณะโครงการ (ประเภท / ความสอดคล้องกับยุทธศาสตร์ / รูปแบบ)
  ๕ ระยะเวลาและสถานที่ดำเนินการ ๖ แผนปฏิบัติการ (ตารางรายเดือน ต.ค.–ก.ย.) ๗ งบประมาณ (ตาราง + โดยเบิกจ่ายจาก...)
  ๘ ความเสี่ยงและแนวทางบริหารความเสี่ยง (ตาราง โอกาส × ผลกระทบ = ระดับ) ๙ ประโยชน์ที่คาดว่าจะได้รับ
  ๑๐ การติดตามประเมินผล (๑๐.๑ ตัวชี้วัด ตาราง / ๑๐.๒ การติดตามความก้าวหน้า / ๑๐.๓ การประเมินผลโครงการ)
  ลงชื่อ ผู้เสนอโครงการ / ผู้อนุมัติโครงการ

ชื่อโครงการเก็บใน GovDocumentSchema.subject (ใช้ลงทะเบียน/ค้นหาเหมือนเรื่องของหนังสือ) ส่วนอื่นอยู่ใน ProjectData
ใช้ร่วมกันทั้งหน้าเว็บ Word และ PDF — ไฟล์นี้ไม่ import core.models (models import ไฟล์นี้)
"""

from __future__ import annotations

import re
from typing import List, Optional, Tuple

from pydantic import BaseModel, Field

# เดือนในปีงบประมาณ (คอลัมน์ของแผนปฏิบัติการ) — ดัชนี 0 = ต.ค.
FY_MONTHS = ("ต.ค.", "พ.ย.", "ธ.ค.", "ม.ค.", "ก.พ.", "มี.ค.", "เม.ย.", "พ.ค.", "มิ.ย.", "ก.ค.", "ส.ค.", "ก.ย.")

# ชื่อหัวข้อตามรูปแบบการเขียนโครงการของกรุงเทพมหานคร (เลขอารบิก — แปลงเป็นเลขไทยตามการตั้งค่าเอกสาร)
HEADINGS = {
    "rationale": "1. หลักการและเหตุผล",
    "objectives": "2. วัตถุประสงค์",
    "targets": "3. เป้าหมาย",
    "nature": "4. ลักษณะโครงการ",
    "schedule": "5. ระยะเวลาและสถานที่ดำเนินการ",
    "plan": "6. แผนปฏิบัติการ",
    "budget": "7. งบประมาณ",
    "risks": "8. ความเสี่ยงของโครงการและแนวทางการบริหารความเสี่ยง",
    "benefits": "9. ประโยชน์ที่คาดว่าจะได้รับ",
    "evaluation": "10. การติดตามประเมินผล",
}
SUBHEADINGS = {
    "project_type": "ประเภทโครงการ",
    "alignment": "ความสอดคล้องหรือเชื่อมโยงกับยุทธศาสตร์/แผน",
    "project_format": "รูปแบบโครงการ",
    "kpis": "10.1 ตัวชี้วัดความสำเร็จ",
    "monitoring": "10.2 การติดตามความก้าวหน้า",
    "assessment": "10.3 การประเมินผลโครงการ",
}
PLAN_HEAD = "ขั้นตอนการดำเนินงาน"
BUDGET_HEADS = ("กิจกรรม", "รายการค่าใช้จ่าย", "จำนวนเงิน (บาท)", "กฎหมาย ระเบียบที่เกี่ยวข้อง")
RISK_HEADS = ("ความเสี่ยง", "การประเมินความเสี่ยง", "โอกาสที่จะเกิด", "ผลกระทบ", "ระดับของความเสี่ยง",
              "แนวทางการบริหารความเสี่ยง")
KPI_HEADS = ("ตัวชี้วัด", "ค่าเป้าหมาย", "ประเภทตัวชี้วัด", "วิธีการคำนวณ/เครื่องมือในการใช้วัด", "ระยะเวลา")
KPI_KINDS = ("ผลผลิต", "ผลลัพธ์", "ผลกระทบ")

# ระยะของแบบเสนอโครงการ (Word = PDF = หน้าแก้ไข)
HEAD_LABEL_CM = 2.7          # ป้าย "ชื่อโครงการ" "หน่วยงาน" "ปีงบประมาณ" — ข้อความเริ่มที่ระยะนี้ (ยาวกว่าให้ต่อท้าย)
SIGN_LEFT_CM = 6.0           # ช่องลงชื่อผู้เสนอ/ผู้อนุมัติ เริ่มที่ระยะนี้
TABLE_PT = 14                # ขนาดตัวอักษรในตาราง (ตาราง ๑๒ เดือนต้องพอดีความกว้าง 16 ซม.)
PLAN_STEP_CM = 5.6           # คอลัมน์ขั้นตอน — เหลือ 16 - 5.6 = 10.4 ซม. สำหรับ ๑๒ เดือน
BUDGET_COLS_CM = (3.2, 7.0, 2.6, 3.2)
RISK_COLS_CM = (4.2, 1.9, 1.9, 2.0, 6.0)
KPI_COLS_CM = (4.0, 2.3, 2.3, 4.9, 2.5)
PLAN_FILL = "BFBFBF"         # สีช่องเดือนที่ดำเนินการ


class PlanStep(BaseModel):
    """ขั้นตอนหนึ่งในแผนปฏิบัติการ — months = ดัชนีเดือนที่ดำเนินการ (0 = ต.ค. … 11 = ก.ย.)"""
    step: str = ""
    months: List[int] = Field(default_factory=list)


class BudgetRow(BaseModel):
    """หนึ่งบรรทัดของตารางงบประมาณ — ระดับรายการดูจากเลขข้อ (๑. / ๑.๑ / ๑.๑.๑) เหมือนย่อหน้าเนื้อความ
    amount = None คือบรรทัดคำอธิบาย (ไม่มีจำนวนเงิน); activity ว่าง = อยู่ในกิจกรรมเดียวกับบรรทัดก่อน"""
    activity: str = ""
    item: str = ""
    amount: Optional[float] = None
    law: str = ""


class RiskRow(BaseModel):
    """likelihood / impact = 1–5 ตามตารางวิเคราะห์ระดับความเสี่ยง (0 = ยังไม่ประเมิน)"""
    risk: str = ""
    likelihood: int = 0
    impact: int = 0
    mitigation: str = ""


class KpiRow(BaseModel):
    indicator: str = ""
    target: str = ""
    kind: str = ""            # ผลผลิต / ผลลัพธ์ / ผลกระทบ
    method: str = ""
    period: str = ""


class ProjectData(BaseModel):
    """ส่วนของแบบเสนอโครงการที่ไม่ใช่ชื่อโครงการ (ชื่อโครงการ = GovDocumentSchema.subject)"""
    agency: str = ""
    fiscal_year: str = ""
    rationale: str = ""
    objectives: str = ""
    targets: str = ""
    project_type: str = ""
    alignment: str = ""
    project_format: str = ""
    schedule: str = ""
    plan: List[PlanStep] = Field(default_factory=list)
    budget_title: str = ""
    budget: List[BudgetRow] = Field(default_factory=list)
    budget_note: str = ""
    risks: List[RiskRow] = Field(default_factory=list)
    benefits: str = ""
    kpis: List[KpiRow] = Field(default_factory=list)
    monitoring: str = ""
    assessment: str = ""
    proposer_name: str = ""
    proposer_position: str = ""
    approver_name: str = ""
    approver_position: str = ""


# ---------------------------------------------------------------- ตัวเลขและข้อความจำนวนเงิน
_THAI_DIGITS = str.maketrans("๐๑๒๓๔๕๖๗๘๙", "0123456789")


def parse_amount(text) -> Optional[float]:
    """'1,087,200.-' / '๒,๑๗๔,๗๒๐' / 96000 → float; ไม่มีตัวเลข = None"""
    if text is None:
        return None
    if isinstance(text, (int, float)):
        return float(text)
    s = str(text).translate(_THAI_DIGITS).replace(",", "").replace(" ", "")
    m = re.search(r"\d+(?:\.\d+)?", s)
    return float(m.group(0)) if m else None


def format_amount(amount: Optional[float]) -> str:
    """96000 → '96,000' / 1234.5 → '1,234.50' / None → ''"""
    if amount is None:
        return ""
    if abs(amount - round(amount)) < 0.005:
        return f"{round(amount):,}"
    return f"{amount:,.2f}"


_DIGIT_WORDS = ("", "หนึ่ง", "สอง", "สาม", "สี่", "ห้า", "หก", "เจ็ด", "แปด", "เก้า")
_PLACE_WORDS = ("", "สิบ", "ร้อย", "พัน", "หมื่น", "แสน")


def _read_group(n: int, has_higher: bool) -> str:
    """อ่านเลข 0–999,999 (has_higher = มีหลักสูงกว่านี้ — หลักหน่วย ๑ อ่าน "เอ็ด")"""
    out = ""
    digits = str(n)
    size = len(digits)
    for i, ch in enumerate(digits):
        d, place = int(ch), size - i - 1
        if d == 0:
            continue
        if place == 1 and d == 1:
            out += "สิบ"
        elif place == 1 and d == 2:
            out += "ยี่สิบ"
        elif place == 0 and d == 1 and (has_higher or size > 1):
            out += "เอ็ด"
        else:
            out += _DIGIT_WORDS[d] + _PLACE_WORDS[place]
    return out


def _read_int(n: int) -> str:
    if n >= 1_000_000:
        high, low = divmod(n, 1_000_000)
        return _read_int(high) + "ล้าน" + (_read_group(low, True) if low else "")
    return _read_group(n, False)


def baht_text(amount: Optional[float]) -> str:
    """2174720 → 'สองล้านหนึ่งแสนเจ็ดหมื่นสี่พันเจ็ดร้อยยี่สิบบาทถ้วน'"""
    if amount is None:
        return ""
    satang_total = int(round(abs(amount) * 100))
    baht, satang = divmod(satang_total, 100)
    if baht == 0 and satang == 0:
        return "ศูนย์บาทถ้วน"
    text = (_read_int(baht) + "บาท") if baht else ""
    return text + (_read_int(satang) + "สตางค์" if satang else "ถ้วน")


# ---------------------------------------------------------------- งบประมาณ
_RE_L3 = re.compile(r"^[0-9๐-๙]+\.[0-9๐-๙]+\.[0-9๐-๙]+")
_RE_L2 = re.compile(r"^[0-9๐-๙]+\.[0-9๐-๙]+")


def item_level(item: str) -> int:
    """ระดับรายการงบประมาณ: แท็บนำหน้า N ตัว = ระดับ N; ไม่มีแท็บ = ดูเลขข้อ (๑.๑.๑ = 3, ๑.๑ = 2, อื่น ๆ = 1)"""
    tabs = len(item) - len(item.lstrip("\t"))
    if tabs:
        return min(tabs, 6)
    s = item.strip()
    if _RE_L3.match(s):
        return 3
    if _RE_L2.match(s):
        return 2
    return 1


def _children(rows: List[BudgetRow], index: int) -> List[int]:
    """ดัชนีรายการลูกที่มีจำนวนเงินของบรรทัด index (ลูกโดยตรง = ระดับลึกที่สุดถัดลงไปที่มีเงิน)"""
    level = item_level(rows[index].item)
    out = []
    for j in range(index + 1, len(rows)):
        if item_level(rows[j].item) <= level:
            break
        if rows[j].amount is not None:
            out.append(j)
    return out


def budget_total(rows: List[BudgetRow]) -> Optional[float]:
    """รวมเงินทั้งโครงการ = รวมเฉพาะรายการย่อยสุดที่มีเงิน (ยอดของหมวด/กิจกรรมย่อยที่เป็นผลรวมไม่นับซ้ำ)"""
    total, found = 0.0, False
    for i, row in enumerate(rows):
        if row.amount is not None and not _children(rows, i):
            total += row.amount
            found = True
    return total if found else None


def budget_mismatches(rows: List[BudgetRow]) -> List[Tuple[int, float, float]]:
    """[(ดัชนี, ยอดที่เขียน, ยอดรวมของรายการลูกโดยตรง)] ที่ไม่ตรงกัน — ตรวจเลขบวกในตารางงบประมาณ"""
    out = []
    for i, row in enumerate(rows):
        kids = _children(rows, i)
        if row.amount is None or not kids:
            continue
        level = min(item_level(rows[j].item) for j in kids)
        direct = [j for j in kids if item_level(rows[j].item) == level]
        subtotal = sum(rows[j].amount for j in direct)
        if abs(subtotal - row.amount) > 0.5:
            out.append((i, row.amount, subtotal))
    return out


def activity_groups(rows: List[BudgetRow]) -> List[Tuple[int, int]]:
    """[(แถวเริ่ม, จำนวนแถว)] ของช่องกิจกรรมที่รวมเซลล์แนวตั้ง — activity ว่างต่อจากกลุ่มก่อนหน้า"""
    groups: List[Tuple[int, int]] = []
    for i, row in enumerate(rows):
        if i == 0 or row.activity.strip():
            groups.append((i, 1))
        else:
            start, span = groups[-1]
            groups[-1] = (start, span + 1)
    return groups


# ---------------------------------------------------------------- ความเสี่ยง
def risk_level(likelihood: int, impact: int) -> str:
    """ตารางวิเคราะห์ระดับความเสี่ยง (คู่มือการเขียนโครงการ กทม. หน้า ๑๔): โอกาส × ผลกระทบ
    ≤ 2 น้อย · 3–6 ปานกลาง · 8–10 สูง · ≥ 12 สูงมาก"""
    if not (1 <= likelihood <= 5 and 1 <= impact <= 5):
        return ""
    score = likelihood * impact
    if score <= 2:
        return "น้อย"
    if score <= 6:
        return "ปานกลาง"
    if score <= 10:
        return "สูง"
    return "สูงมาก"


# ---------------------------------------------------------------- ปีงบประมาณ / เอกสารเปล่า
def plan_year(fiscal_year: str) -> str:
    """'ปีงบประมาณ พ.ศ. ๒๕๗๑' / '2571' → '2571' (หัวตารางแผนปฏิบัติการ) — หาไม่ได้ = '…'"""
    m = re.search(r"[0-9๐-๙]{4}", fiscal_year or "")
    return m.group(0) if m else "…"


def blank_project(agency: str = "", proposer_position: str = "", approver_position: str = "") -> ProjectData:
    """โครงเปล่าตามรูปแบบการเขียนโครงการ — ช่องที่ต้องกรอกเป็น [✏️ ระบุ...]"""
    return ProjectData(
        agency=agency or "[✏️ ระบุส่วนราชการและหน่วยงานที่รับผิดชอบ]",
        fiscal_year="[✏️ ระบุปีงบประมาณ]",
        rationale="[✏️ ระบุความเป็นมา สภาพปัญหา และความจำเป็นของโครงการ]\n"
                  "[✏️ ระบุวิธีการแก้ไขปัญหา/พัฒนา และเหตุผลที่เลือกวิธีนั้น]\n"
                  "[✏️ ระบุโครงการ/กิจกรรมที่จะดำเนินการและผลที่คาดว่าจะได้รับ]",
        objectives="1. เพื่อ[✏️ ระบุวัตถุประสงค์ ไม่เกิน ๓ ข้อ เรียงตามความสำคัญ]",
        targets="[✏️ ระบุผลที่จะเกิดขึ้นเชิงปริมาณและคุณภาพ กลุ่มเป้าหมาย จำนวน]",
        project_type="[✏️ ระบุโครงการตามยุทธศาสตร์/ภารกิจประจำ และโครงการใหม่/ต่อเนื่อง]",
        alignment="[✏️ ระบุความสอดคล้องกับยุทธศาสตร์ชาติ แผนพัฒนากรุงเทพมหานคร และแผนปฏิบัติราชการประจำปี]",
        project_format="[✏️ ระบุรูปแบบ เช่น โครงการฝึกอบรม/สัมมนา โครงการจัดงาน/กิจกรรม]",
        schedule="[✏️ ระบุระยะเวลาเริ่มต้น-สิ้นสุด และสถานที่ดำเนินการ]",
        plan=[PlanStep(step="1. ขออนุมัติโครงการ"), PlanStep(step="2. [✏️ ระบุขั้นตอนการดำเนินงาน]"),
              PlanStep(step="3. สรุปและรายงานผลการดำเนินงาน")],
        budget=[BudgetRow(activity="[✏️ ระบุกิจกรรม]", item="1. [✏️ ระบุรายการค่าใช้จ่าย]", amount=None,
                          law="[✏️ ระบุระเบียบที่ใช้เบิก]")],
        budget_note="โดยเบิกจ่ายจากงบประมาณรายจ่ายประจำปีงบประมาณ พ.ศ. [✏️ ระบุ] แผนงาน [✏️ ระบุ] "
                    "งาน [✏️ ระบุ] หมวด [✏️ ระบุ] รายการ [✏️ ระบุ]",
        risks=[RiskRow(risk="1. [✏️ ระบุข้อจำกัดหรือปัจจัยที่อาจทำให้โครงการไม่บรรลุวัตถุประสงค์]",
                       mitigation="[✏️ ระบุวิธีจัดการ/ป้องกัน]")],
        benefits="[✏️ ระบุผลที่จะได้รับหลังเสร็จสิ้นโครงการ (ไม่ใช่วัตถุประสงค์หรือเป้าหมาย)]",
        kpis=[KpiRow(indicator="1. [✏️ ระบุตัวชี้วัด]", target="[✏️ ระบุ]", kind="ผลผลิต",
                     method="[✏️ ระบุวิธีคำนวณ/เครื่องมือ]", period="[✏️ ระบุ]")],
        monitoring="[✏️ ระบุรอบการรายงานความก้าวหน้า เช่น รายเดือน รายไตรมาส]",
        assessment="[✏️ ระบุวิธีเก็บข้อมูลและประเมินผลตามเป้าหมาย/ตัวชี้วัด]",
        proposer_position=proposer_position,
        approver_position=approver_position,
    )


def project_texts(p: ProjectData) -> List[Tuple[str, str]]:
    """[(ชื่อช่อง, ข้อความ)] ทุกช่องของโครงการ — ใช้หาจุด [✏️ ระบุ...] และตรวจข้อเท็จจริง"""
    out = [("หน่วยงาน", p.agency), ("ปีงบประมาณ", p.fiscal_year), ("หลักการและเหตุผล", p.rationale),
           ("วัตถุประสงค์", p.objectives), ("เป้าหมาย", p.targets), ("ประเภทโครงการ", p.project_type),
           ("ความสอดคล้องกับยุทธศาสตร์/แผน", p.alignment), ("รูปแบบโครงการ", p.project_format),
           ("ระยะเวลาและสถานที่", p.schedule), ("งบประมาณ", p.budget_title), ("โดยเบิกจ่ายจาก", p.budget_note),
           ("ประโยชน์ที่คาดว่าจะได้รับ", p.benefits), ("การติดตามความก้าวหน้า", p.monitoring),
           ("การประเมินผลโครงการ", p.assessment)]
    out += [(f"แผนปฏิบัติการ ข้อ {i}", s.step) for i, s in enumerate(p.plan, 1)]
    for i, r in enumerate(p.budget, 1):
        out += [(f"งบประมาณ แถว {i}", r.activity), (f"งบประมาณ แถว {i}", r.item), (f"งบประมาณ แถว {i}", r.law)]
    for i, r in enumerate(p.risks, 1):
        out += [(f"ความเสี่ยง ข้อ {i}", r.risk), (f"ความเสี่ยง ข้อ {i}", r.mitigation)]
    for i, k in enumerate(p.kpis, 1):
        out += [(f"ตัวชี้วัด ข้อ {i}", x) for x in (k.indicator, k.target, k.kind, k.method, k.period)]
    return out


# ---------------------------------------------------------------- มุมมองสำหรับเรนเดอร์ (Word = PDF)
BODY_INDENT_CM = 2.5


def line_level(line: str) -> int:
    """ระดับย่อหน้าในแบบโครงการ: เลขข้อย่อยของหัวข้อ (๒.๑ / ๙.๑) อยู่ระดับ ๑ = 2.5 ซม., ๒.๑.๑ ระดับ ๒ = 3.5 ซม.
    (ต่างจากหนังสือที่ ๑.๑ อยู่ 3.5 ซม. เพราะ "๒." คือหัวข้อของแบบ) — แท็บนำหน้า N ตัว = ระดับ N"""
    tabs = len(line) - len(line.lstrip("\t"))
    if tabs:
        return min(tabs, 6)
    s = line.strip()
    if re.match(r"^[0-9๐-๙]+\.[0-9๐-๙]+\.[0-9๐-๙]+\.[0-9๐-๙]+", s):
        return 3
    if _RE_L3.match(s):
        return 2
    return 1


def _body(text: str, num) -> List[dict]:
    return [{"indent": BODY_INDENT_CM + line_level(raw) - 1, "text": num(raw.lstrip("\t").strip())}
            for raw in (text or "").splitlines() if raw.strip()]


def project_view(name: str, p: ProjectData, thai_numerals: bool = False) -> dict:
    """ข้อความพร้อมพิมพ์ทุกส่วนของแบบเสนอโครงการ (เลขไทยตามการตั้งค่า, ยอดรวม, ระดับความเสี่ยง)
    blocks = ลำดับส่วนในหน้า: heading / sub (ป้ายตัวหนา) / usub (ขีดเส้นใต้) / lines / plan / budget / risks / kpis"""
    from core.thai_segmenter import to_thai_numerals

    num = (lambda t: to_thai_numerals(t or "")) if thai_numerals else (lambda t: t or "")
    blocks: List[dict] = []

    def heading(key):
        blocks.append({"type": "heading", "text": num(HEADINGS[key])})

    def lines(text):
        blocks.append({"type": "lines", "lines": _body(text, num)})

    def sub(key, text, kind="sub"):
        blocks.append({"type": kind, "text": num(SUBHEADINGS[key])})
        lines(text)

    heading("rationale"); lines(p.rationale)
    heading("objectives"); lines(p.objectives)
    heading("targets"); lines(p.targets)
    heading("nature")
    sub("project_type", p.project_type)
    sub("alignment", p.alignment)
    sub("project_format", p.project_format)
    heading("schedule"); lines(p.schedule)

    heading("plan")
    blocks.append({"type": "plan", "year": num(plan_year(p.fiscal_year)), "months": list(FY_MONTHS),
                   "rows": [{"step": num(s.step), "months": [m in s.months for m in range(12)]} for s in p.plan]})

    heading("budget")
    if p.budget_title.strip():
        blocks.append({"type": "lines", "lines": [{"indent": 2.5, "text": num(p.budget_title.strip())}]})
    total = budget_total(p.budget)
    spans = {start: span for start, span in activity_groups(p.budget)}
    blocks.append({
        "type": "budget", "heads": list(BUDGET_HEADS),
        "rows": [{"activity": num(r.activity), "span": spans.get(i, 0), "item": num(r.item.lstrip("\t")),
                  "level": item_level(r.item), "amount": num(format_amount(r.amount)), "law": num(r.law)}
                 for i, r in enumerate(p.budget)],
        "total_label": "รวมเป็นเงินทั้งสิ้น" + (f" ({baht_text(total)})" if total is not None else ""),
        "total": num(format_amount(total)),
    })
    if p.budget_note.strip():
        lines(p.budget_note)

    heading("risks")
    blocks.append({"type": "risks", "rows": [
        {"risk": num(r.risk), "likelihood": num(str(r.likelihood)) if r.likelihood else "",
         "impact": num(str(r.impact)) if r.impact else "", "level": risk_level(r.likelihood, r.impact),
         "mitigation": num(r.mitigation)} for r in p.risks]})
    heading("benefits"); lines(p.benefits)
    heading("evaluation")
    blocks.append({"type": "usub", "text": num(SUBHEADINGS["kpis"])})
    blocks.append({"type": "kpis", "heads": list(KPI_HEADS), "rows": [
        {k: num(getattr(row, k)) for k in ("indicator", "target", "kind", "method", "period")} for row in p.kpis]})
    sub("monitoring", p.monitoring, "usub")
    sub("assessment", p.assessment, "usub")

    def signer(name_, position, role):
        return {"line": f"ลงชื่อ{'.' * 45}{role}",
                "name": f"({name_.strip().strip('()') or chr(0xA0) * 30})",
                "position": f"ตำแหน่ง {position.strip()}" if position.strip() else f"ตำแหน่ง {'.' * 45}"}

    return {
        "head": [("ชื่อโครงการ", num(name)), ("หน่วยงาน", num(p.agency)), ("ปีงบประมาณ", num(p.fiscal_year))],
        "blocks": blocks,
        "signers": [signer(p.proposer_name, p.proposer_position, "ผู้เสนอโครงการ"),
                    signer(p.approver_name, p.approver_position, "ผู้อนุมัติโครงการ")],
    }
