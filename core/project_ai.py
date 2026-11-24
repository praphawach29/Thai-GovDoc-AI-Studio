"""
project_ai.py — ให้ AI เขียนแบบเสนอโครงการ กทม. (schema คำตอบ + prompt + ใส่ผลลงเอกสาร)

ใช้ผู้ให้บริการชุดเดียวกับการร่างหนังสือ (core.llm_drafter) แต่ตอบเป็น ProjectContent ซึ่งมีตาราง
กฎเดียวกับการร่างหนังสือ: ใช้เฉพาะข้อเท็จจริงในต้นเรื่อง จำนวนเงิน/ตัวเลขที่ไม่มีให้เว้น [✏️ ระบุ...]
"""

from __future__ import annotations

from typing import List

from pydantic import BaseModel, Field

from core.models import GovDocumentSchema
from core.project import (BudgetRow, KpiRow, PlanStep, ProjectData, RiskRow, parse_amount)


# Gemini response_schema ไม่รับค่าเริ่มต้นและ Optional — ทุกช่องต้องมี, จำนวนเงินเป็นข้อความ ("" = ไม่มี)
class PlanStepContent(BaseModel):
    step: str = Field(description="ขั้นตอนการดำเนินงาน ขึ้นต้นด้วยเลขข้อ เช่น '1. ขออนุมัติโครงการ'")
    months: List[int] = Field(description="เดือนที่ดำเนินการ เป็นดัชนี 0=ต.ค. 1=พ.ย. 2=ธ.ค. 3=ม.ค. 4=ก.พ. 5=มี.ค. "
                                          "6=เม.ย. 7=พ.ค. 8=มิ.ย. 9=ก.ค. 10=ส.ค. 11=ก.ย.")


class BudgetRowContent(BaseModel):
    activity: str = Field(description="ชื่อกิจกรรม (เฉพาะแถวแรกของกิจกรรม แถวถัดไปในกิจกรรมเดียวกันให้เป็น \"\")")
    item: str = Field(description="รายการค่าใช้จ่ายหนึ่งบรรทัด ขึ้นต้นด้วยเลขข้อ '1.' (หมวด) '1.1' '1.1.1' "
                                  "พร้อมสูตร เช่น 'ผู้ตัดสิน คู่ละ 2 คน ๆ ละ 500 บาท'")
    amount: str = Field(description="จำนวนเงินของบรรทัดนี้เป็นตัวเลข เช่น '96000' — ว่าง \"\" ถ้าบรรทัดนี้ไม่มีจำนวนเงิน")
    law: str = Field(description="กฎหมาย/ระเบียบที่ใช้เบิกรายการนี้ (เฉพาะที่มีในต้นเรื่อง) ว่างได้")


class RiskRowContent(BaseModel):
    risk: str = Field(description="ความเสี่ยง: ข้อจำกัดหรือปัจจัยที่อาจทำให้โครงการไม่บรรลุวัตถุประสงค์")
    likelihood: int = Field(description="โอกาสที่จะเกิด 1–5 (1 น้อยมาก … 5 สูงมาก)")
    impact: int = Field(description="ผลกระทบ 1–5 (1 น้อยมาก … 5 สูงมาก)")
    mitigation: str = Field(description="แนวทางการบริหารความเสี่ยง")


class KpiRowContent(BaseModel):
    indicator: str = Field(description="ตัวชี้วัด ขึ้นต้นด้วยเลขข้อ")
    target: str = Field(description="ค่าเป้าหมาย เช่น 'ร้อยละ 80'")
    kind: str = Field(description="ประเภทตัวชี้วัด: ผลผลิต / ผลลัพธ์ / ผลกระทบ")
    method: str = Field(description="วิธีการคำนวณ/เครื่องมือในการใช้วัด")
    period: str = Field(description="ระยะเวลาที่วัด")


class ProjectContent(BaseModel):
    """แบบเสนอโครงการที่ AI เขียน — ย่อหน้า/ข้อแยกด้วยการขึ้นบรรทัดใหม่"""
    subject: str = Field(description="ชื่อโครงการ ขึ้นต้นด้วยคำว่า 'โครงการ'")
    agency: str = Field(description="หน่วยงาน: ส่วนราชการและหน่วยงานที่รับผิดชอบ")
    fiscal_year: str = Field(description="ปีงบประมาณ พ.ศ. เช่น '2571'")
    rationale: str = Field(description="1. หลักการและเหตุผล หลายย่อหน้า")
    objectives: str = Field(description="2. วัตถุประสงค์ ข้อละบรรทัด '2.1 เพื่อ...' ไม่เกิน 3 ข้อ")
    targets: str = Field(description="3. เป้าหมาย")
    project_type: str = Field(description="4. ประเภทโครงการ")
    alignment: str = Field(description="4. ความสอดคล้องหรือเชื่อมโยงกับยุทธศาสตร์/แผน ข้อละบรรทัด")
    project_format: str = Field(description="4. รูปแบบโครงการ")
    schedule: str = Field(description="5. ระยะเวลาและสถานที่ดำเนินการ")
    plan: List[PlanStepContent] = Field(description="6. แผนปฏิบัติการ")
    budget_title: str = Field(description="หัวตารางงบประมาณ เช่น 'รายการค่าใช้จ่ายในการ...' ว่างได้")
    budget: List[BudgetRowContent] = Field(description="7. ตารางงบประมาณ ทีละบรรทัดตามลำดับ")
    budget_note: str = Field(description="ย่อหน้าใต้ตาราง 'โดยเบิกจ่ายจากงบประมาณรายจ่ายประจำปี...' "
                                         "(ไม่ต้องเขียนยอดรวมเป็นตัวอักษร ระบบคำนวณให้)")
    risks: List[RiskRowContent] = Field(description="8. ความเสี่ยงและแนวทางการบริหารความเสี่ยง")
    benefits: str = Field(description="9. ประโยชน์ที่คาดว่าจะได้รับ ข้อละบรรทัด")
    kpis: List[KpiRowContent] = Field(description="10.1 ตัวชี้วัดความสำเร็จ")
    monitoring: str = Field(description="10.2 การติดตามความก้าวหน้า")
    assessment: str = Field(description="10.3 การประเมินผลโครงการ")
    source_summary: str = Field(description="สรุปต้นเรื่อง ๓–๔ บรรทัด (ใช้เฉพาะข้อเท็จจริงในต้นเรื่อง) ว่างได้")


PROJECT_PROMPT = """ชนิดเอกสาร: แบบเสนอโครงการของกรุงเทพมหานคร (ตามรูปแบบการเขียนโครงการ และคู่มือการเขียนโครงการ กทม.)
เขียนทุกช่องตาม schema โดยยึดหลักของคู่มือ:
- subject: ชื่อโครงการชัดเจน เฉพาะเจาะจง บอกว่าจะทำอะไร (ขึ้นต้น "โครงการ")
- agency: ส่วนราชการและหน่วยงานที่รับผิดชอบ เช่น "กองการกีฬา สำนักวัฒนธรรม กีฬา และการท่องเที่ยว"
- fiscal_year: ปีงบประมาณ พ.ศ. ที่ดำเนินการ (ตัวเลขสี่หลัก)
- rationale (๑. หลักการและเหตุผล): ๒–๔ ย่อหน้า ย่อหน้าละบรรทัด — ความเป็นมา สภาพปัญหาและผลกระทบ (มีข้อมูลสนับสนุน)
  วิธีแก้ไข/พัฒนาและเหตุผลที่เลือก แล้วย่อหน้าสุดท้ายขึ้นต้น "ดังนั้น/ในการนี้ <หน่วยงาน> จึงจัดทำโครงการ..." พร้อมผลที่คาดว่าจะได้รับ
- objectives (๒. วัตถุประสงค์): ขึ้นต้น "เพื่อ..." วัดผลได้ สอดคล้องกับหลักการและเหตุผล ไม่เกิน ๓ ข้อ เรียงตามความสำคัญ
  ข้อละบรรทัด "2.1 เพื่อ..." (โครงการฝึกอบรมเขียนเชิงพฤติกรรม)
- targets (๓. เป้าหมาย): สิ่งที่จะทำ/ผลที่จะเกิดเชิงปริมาณและคุณภาพ เช่น จำนวนผู้เข้าร่วม ร้อยละ; โครงการฝึกอบรมระบุกลุ่มเป้าหมาย/ตำแหน่ง/จำนวน
- project_type: โครงการตามยุทธศาสตร์ หรือโครงการตามภารกิจประจำของหน่วยงาน และเป็นโครงการใหม่หรือโครงการต่อเนื่อง
- alignment: ความสอดคล้องกับยุทธศาสตร์ชาติ แผนพัฒนากรุงเทพมหานคร (ระยะ/ยุทธศาสตร์/เป้าประสงค์/กลยุทธ์) แผนปฏิบัติราชการประจำปี
  ข้อละบรรทัด "1. สอดคล้องกับ..." — ใช้เฉพาะชื่อแผน/ด้าน/มิติ/เลขเป้าประสงค์ที่มีในต้นเรื่อง ไม่มีให้เว้น [✏️ ระบุ...] ห้ามแต่งเลขข้อของแผน
- project_format: รูปแบบ เช่น โครงการฝึกอบรม/สัมมนา/ศึกษาดูงาน ศึกษาวิจัย ก่อสร้าง รณรงค์/ประชาสัมพันธ์/เผยแพร่ พัฒนาระบบสารสนเทศ
  จัดงาน/กิจกรรม พร้อมรายละเอียดกิจกรรมหลัก
- schedule (๕.): ระยะเวลาเริ่มต้น–สิ้นสุด (เดือน ปี) และสถานที่ ข้อละบรรทัด; โครงการฝึกอบรมระบุแบบไป-กลับ/พักค้าง จำนวนวัน/คืน
- plan (๖. แผนปฏิบัติการ): ขั้นตอนเรียงตามลำดับตั้งแต่ขออนุมัติจนรายงานผล พร้อมเดือนที่ทำ (ดัชนีเดือนของปีงบประมาณ 0=ต.ค. … 11=ก.ย.)
  เดือนต้องอยู่ในระยะเวลาโครงการ
- budget (๗. งบประมาณ): ตารางทีละบรรทัด เรียงตามต้นเรื่อง หมวด "1. หมวดค่าตอบแทน" รายการย่อย "1.1" "1.1.1" พร้อมสูตร (จำนวน x อัตรา)
  amount = จำนวนเงินของบรรทัดนั้น (หมวด/รายการที่มีรายการย่อยให้ใส่ยอดรวมของรายการย่อย) — ใช้เฉพาะจำนวนเงินและอัตราที่มีในต้นเรื่อง
  ไม่มีให้ amount เป็น "" และเว้น [✏️ ระบุ...] ในรายการ; law = ระเบียบที่ใช้เบิก (เช่น "บัญชี ๓ ข้อ ๔.๑ (๒)") เฉพาะที่มีในต้นเรื่อง
  ห้ามเขียนแถว "รวม"/"รวมเป็นเงินทั้งสิ้น" (ระบบรวมและเขียนเป็นตัวอักษรให้)
  ตารางในต้นเรื่องอยู่ระหว่าง [ตาราง]...[/ตาราง] ช่องคั่นด้วย " | " บรรทัดเดียวกันมักเป็นแถวเดียวกัน แต่ไฟล์ Word บางฉบับ
  จำนวนเงินเหลื่อมขึ้น/ลงหนึ่งบรรทัด — ให้ตรวจทุกรายการด้วยสูตรในรายการ (เช่น 96 คู่ × 2 คน × 500 บาท = 96,000;
  10 คน × 300 บาท × 4 วัน = 12,000) และยอดของหมวด/กิจกรรมย่อยต้องเท่ากับผลรวมรายการย่อย แล้วจับคู่จำนวนเงินกับรายการที่คำนวณได้ตรง
  บรรทัดต่อของรายการเดียวกัน (เช่น "๕๐๐.- บาท" ที่ขึ้นบรรทัดใหม่) รวมเป็นรายการเดียว ไม่แยกแถว
- budget_note: "โดยเบิกจ่ายจากงบประมาณรายจ่ายประจำปีงบประมาณ พ.ศ. ... แผนงาน ... งาน/ผลผลิต ... หมวด/งบ ... รายการ ..."
  ตามด้วยข้อความถัวจ่าย/เอกสารแนบที่มีในต้นเรื่อง (ไม่ต้องเขียนยอดเงินรวม)
- risks (๘.): ความเสี่ยงที่คาดการณ์ได้ โอกาสที่จะเกิด 1–5 ผลกระทบ 1–5 (ระบบคำนวณระดับความเสี่ยงให้) และแนวทางบริหารความเสี่ยง
- benefits (๙.): ผลที่ได้รับหลังจบโครงการทั้งทางตรงและทางอ้อม (ไม่ใช่วัตถุประสงค์หรือเป้าหมาย) ข้อละบรรทัด "9.1 ..."
- kpis (๑๐.๑): ตัวชี้วัดระดับผลผลิต (เป้าหมาย) ผลลัพธ์ (วัตถุประสงค์) และผลกระทบ (ประโยชน์ที่คาดว่าจะได้รับ) อย่างละ ๑ ข้อขึ้นไป
- monitoring (๑๐.๒): รอบและวิธีรายงานความก้าวหน้า (รายสัปดาห์/รายเดือน/รายไตรมาส) ข้อละบรรทัด
- assessment (๑๐.๓): วิธีเก็บข้อมูล ประมวลผล และประเมินผลตามเป้าหมาย/ตัวชี้วัด ข้อละบรรทัด

ถ้าต้นเรื่องเป็นโครงการเดิม (เช่น ปีงบประมาณก่อน) ให้คงข้อเท็จจริง ตาราง จำนวนเงิน และระเบียบเดิมไว้ครบทุกบรรทัด
แล้วปรับตามคำสั่งของผู้ใช้ (เช่น ปีงบประมาณใหม่ ช่วงเดือน) และแก้ข้อความให้ถูกตามคู่มือ — ห้ามตัดรายการงบประมาณทิ้ง
เลขข้อในข้อความใช้เลขอารบิก (ระบบแปลงเป็นเลขไทยตามการตั้งค่า) ไม่ใช้ markdown"""


def build_project_prompt(*, instruction: str, source_text: str, agency: str = "", assemble=None,
                         examples: str = "") -> str:
    """prompt ของแบบเสนอโครงการ — assemble = core.llm_drafter._assemble (ส่งเข้ามากัน import วน)
    examples = แม่แบบ Word ของหน่วยงาน (core.studio.template_block) ว่างได้"""
    head = PROJECT_PROMPT + (f"\nหน่วยงานของผู้ใช้ (ใช้ถ้าต้นเรื่องไม่ระบุ): {agency}" if agency else "")
    return assemble(head, instruction, source_text, examples)


def _tidy(text: str) -> str:
    from core.style_examples import unmask_leftovers

    lines = [ln.rstrip() for ln in (text or "").replace("**", "").splitlines()]
    return unmask_leftovers("\n".join(lines).strip())


def clean_project(content: ProjectContent) -> ProjectContent:
    """ตัดช่องว่าง/markdown ทุกช่องข้อความ (รวมในตาราง) และแถว "รวม" ที่ AI เขียนมาเอง"""
    def walk(value):
        if isinstance(value, str):
            return _tidy(value)
        if isinstance(value, list):
            return [walk(v) for v in value]
        if isinstance(value, dict):
            return {k: walk(v) for k, v in value.items()}
        return value

    data = walk(content.model_dump())
    data["budget"] = [r for r in data["budget"]
                      if not (r["item"].replace(" ", "").startswith(("รวม", "รวมเป็นเงิน", "รวมทั้งสิ้น"))
                              and not r["activity"])]
    return ProjectContent.model_validate(data)


def _scale(n: int) -> int:
    return n if 1 <= n <= 5 else 0


def apply_project_content(doc: GovDocumentSchema, content: ProjectContent) -> GovDocumentSchema:
    """ใส่โครงการจาก AI ลงเอกสาร — ช่องที่ AI เว้นว่างคงโครงเดิม (placeholder) ไว้"""
    d = doc.model_copy(deep=True)
    base = d.project or ProjectData()
    if content.subject:
        d.subject = content.subject
    text = {k: getattr(content, k) or getattr(base, k) for k in (
        "agency", "fiscal_year", "rationale", "objectives", "targets", "project_type", "alignment",
        "project_format", "schedule", "budget_title", "budget_note", "benefits", "monitoring", "assessment")}
    plan = [PlanStep(step=s.step, months=sorted({m for m in s.months if 0 <= m <= 11})) for s in content.plan if s.step]
    budget = [BudgetRow(activity=r.activity, item=r.item, amount=parse_amount(r.amount), law=r.law)
              for r in content.budget if r.item or r.amount]
    risks = [RiskRow(risk=r.risk, likelihood=_scale(r.likelihood), impact=_scale(r.impact), mitigation=r.mitigation)
             for r in content.risks if r.risk]
    kpis = [KpiRow(**k.model_dump()) for k in content.kpis if k.indicator]
    d.project = base.model_copy(update={
        **text,
        "plan": plan or base.plan, "budget": budget or base.budget,
        "risks": risks or base.risks, "kpis": kpis or base.kpis,
    })
    return d
