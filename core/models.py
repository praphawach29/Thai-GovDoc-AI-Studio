"""
models.py — Data Schemas for Thai Official Government Documents
อ้างอิงตามระเบียบสำนักนายกรัฐมนตรีว่าด้วยงานสารบรรณ พ.ศ. ๒๕๒๖ และที่แก้ไขเพิ่มเติม
"""

import re
from enum import Enum
from typing import Dict, List, Literal, Optional
from uuid import uuid4

from pydantic import BaseModel, Field, model_validator

from core.thai_segmenter import to_thai_numerals


DOC_NUMBER_PLACEHOLDER = "[✏️ เลขที่หนังสือ]"


# ช่องว่างสำหรับเขียนเลขด้วยลายมือ: ใช้ non-breaking space ซึ่ง Typst/Word/HTML ไม่ยุบรวม
# (ช่องว่างธรรมดาหลายตัวจะถูกยุบเหลือตัวเดียวเวลาจัดหน้า)
HANDWRITE_GAP = "\u00a0" * 10


def is_blank_doc_number(number: Optional[str]) -> bool:
    """ตรวจว่าเลขที่ยังเป็นช่องว่างให้เขียนด้วยมือ

    เช่น '......../2569', '          /2569' (เว้นว่างไม่มีจุด) หรือ 'กท 1205/' (เว้นเลขลำดับไว้)
    """
    text = (number or "").replace("\u00a0", " ").strip()
    if not text:
        return True
    if DOC_NUMBER_PLACEHOLDER in text:
        return True
    if text.startswith("/") or text.endswith("/"):
        return True
    return bool(re.match(r"^[.…_\-]+\s*/", text))


class DocType(str, Enum):
    EXTERNAL = "external"    # หนังสือภายนอก (ครุฑ 3 ซม. กึ่งกลาง)
    INTERNAL = "internal"    # หนังสือภายใน / บันทึกข้อความ (ครุฑ 1.5 ซม. ด้านซ้าย)


class DocumentKind(str, Enum):
    """ชนิดหนังสือราชการ 6 ชนิดตามระเบียบงานสารบรรณ (แบบที่ 1–11)"""

    EXTERNAL_LETTER = "external_letter"      # หนังสือภายนอก (แบบ 1)
    INTERNAL_MEMO = "internal_memo"          # หนังสือภายใน/บันทึกข้อความ (แบบ 2)
    STAMP_LETTER = "stamp_letter"            # หนังสือประทับตรา (แบบ 3)
    DIRECTIVE = "directive"                  # คำสั่ง/ระเบียบ/ข้อบังคับ (แบบ 4–6)
    PUBLIC_RELATIONS = "public_relations"    # ประกาศ/แถลงการณ์/ข่าว (แบบ 7–9)
    EVIDENCE = "evidence"                    # หนังสือรับรอง/รายงานการประชุม/บันทึก (แบบ 10–11)

    def thai_label(self) -> str:
        return {
            DocumentKind.EXTERNAL_LETTER: "หนังสือภายนอก (แบบ 1)",
            DocumentKind.INTERNAL_MEMO: "หนังสือภายใน / บันทึกข้อความ (แบบ 2)",
            DocumentKind.STAMP_LETTER: "หนังสือประทับตรา (แบบ 3)",
            DocumentKind.DIRECTIVE: "หนังสือสั่งการ: คำสั่ง/ระเบียบ/ข้อบังคับ (แบบ 4–6)",
            DocumentKind.PUBLIC_RELATIONS: "หนังสือประชาสัมพันธ์: ประกาศ/แถลงการณ์/ข่าว (แบบ 7–9)",
            DocumentKind.EVIDENCE: "หนังสือรับรอง/รายงานการประชุม/บันทึก (แบบ 10–11)",
        }[self]

    def is_generation_supported(self) -> bool:
        return True


class UrgencyLevel(str, Enum):
    NORMAL = "normal"              # ปกติ
    URGENT = "urgent"              # ด่วน
    VERY_URGENT = "very_urgent"    # ด่วนมาก
    MOST_URGENT = "most_urgent"    # ด่วนที่สุด

    def to_thai(self) -> str:
        mapping = {
            UrgencyLevel.NORMAL: "ปกติ",
            UrgencyLevel.URGENT: "ด่วน",
            UrgencyLevel.VERY_URGENT: "ด่วนมาก",
            UrgencyLevel.MOST_URGENT: "ด่วนที่สุด",
        }
        return mapping[self]


class SecretLevel(str, Enum):
    NORMAL = "normal"            # ปกติ
    SECRET = "secret"            # ลับ
    VERY_SECRET = "very_secret"  # ลับมาก
    TOP_SECRET = "top_secret"    # ลับที่สุด

    def to_thai(self) -> str:
        mapping = {
            SecretLevel.NORMAL: "ปกติ",
            SecretLevel.SECRET: "ลับ",
            SecretLevel.VERY_SECRET: "ลับมาก",
            SecretLevel.TOP_SECRET: "ลับที่สุด",
        }
        return mapping[self]


class ExportOptions(BaseModel):
    """ตัวเลือกการส่งออก Word/PDF (แยกจากข้อมูลเอกสาร เพราะเป็นค่าเฉพาะการเรนเดอร์)"""

    layout_profile: Optional[str] = Field(
        default=None,
        description="ชื่อ LayoutProfile เช่น standard_memo / form_it9_2026 (None = อัตโนมัติตามชนิดหนังสือ)",
    )
    letterhead: Literal["garuda", "none"] = Field(
        default="garuda", description="แสดงตราครุฑหรือไม่"
    )
    divider: Literal["none", "line"] = Field(
        default="none", description="เส้นคั่นใต้ส่วนหัว (none/line)"
    )
    letter_spacing_pt: Optional[float] = Field(
        default=None, ge=-2.0, le=20.0, description="ระยะห่างตัวอักษร (pt); None = ใช้ค่าจาก LayoutProfile"
    )
    export_font: Optional[Literal["sarabun_new", "psk", "it9"]] = Field(
        default=None, description="ฟอนต์ที่ใช้ส่งออก; None = ใช้ค่าจาก LayoutProfile"
    )
    body_alignment: Literal["thai_distribute", "left"] = Field(
        default="thai_distribute",
        description="การจัดแนวเนื้อความใน Word: กระจายแบบไทย (ค่าเริ่มต้น) หรือชิดซ้าย",
    )
    embed_fonts: bool = Field(
        default=True, description="ฝังฟอนต์ลงในไฟล์ .docx (odttf)"
    )
    is_private: bool = Field(
        default=False, description="ทำเครื่องหมายเอกสารส่วนตัว (ไม่บันทึก/ไม่เผยแพร่)"
    )


class MemoHierarchyLevel(str, Enum):
    """ระดับชั้นการเสนอหนังสือบันทึกข้อความตามลำดับบังคับบัญชา"""
    SECTION_TO_DIV = "section_to_div"          # ระดับกลุ่มงาน/ฝ่าย -> เสนอ ผอ.กอง
    DIV_TO_DEPT = "div_to_dept"                # ระดับกอง -> เสนอ ผอ.สำนัก/อธิบดี
    DEPT_TO_PERM_SEC = "dept_to_perm_sec"      # ระดับสำนัก/กรม -> เสนอ ปลัด (เพื่อนำเรียนผู้ว่าฯ/รมต.)
    FINAL_APPROVAL = "final_approval"          # เสนอผู้มีอำนาจสั่งการขั้นสุดท้าย (โปรดพิจารณาอนุมัติ/ลงนาม)
    CUSTOM = "custom"                          # กำหนดประโยคลงท้ายเอง

    def to_thai(self) -> str:
        mapping = {
            MemoHierarchyLevel.SECTION_TO_DIV: "📁 ระดับกลุ่มงาน/ฝ่าย -> เสนอ ผอ.กอง",
            MemoHierarchyLevel.DIV_TO_DEPT: "🏢 ระดับกอง -> เสนอ ผอ.สำนัก (ลงนามหนังสือเรียนปลัด)",
            MemoHierarchyLevel.DEPT_TO_PERM_SEC: "🏛️ ระดับสำนัก -> เสนอ ปลัด (นำเรียนผู้ว่าฯ สั่งการ)",
            MemoHierarchyLevel.FINAL_APPROVAL: "✍️ เสนอผู้มีอำนาจสั่งการขั้นสุดท้าย (โปรดพิจารณาอนุมัติ/ลงนาม)",
            MemoHierarchyLevel.CUSTOM: "✏️ กำหนดประโยคลงท้ายเอง",
        }
        return mapping.get(self, "ระดับสำนัก -> เสนอ ปลัด")

    def default_closing(self, target_title: str = "", final_authority: str = "ผู้ว่าราชการกรุงเทพมหานคร", action_items: str = "") -> str:
        if self == MemoHierarchyLevel.SECTION_TO_DIV:
            pos = target_title or "ผู้อำนวยการกอง"
            return f"จึงเรียนมาเพื่อโปรดพิจารณานำเรียน{pos}ลงนามในหนังสือที่แนบ"
        elif self == MemoHierarchyLevel.DIV_TO_DEPT:
            return "จึงเรียนมาเพื่อโปรดพิจารณาลงนามหนังสือเรียนปลัดกรุงเทพมหานครที่แนบ"
        elif self == MemoHierarchyLevel.DEPT_TO_PERM_SEC:
            items_str = f" เพื่อโปรดพิจารณา{action_items}" if action_items else " เพื่อโปรดพิจารณาให้ความเห็นชอบและสั่งการตามที่เสนอข้างต้น"
            return f"จึงเรียนมาเพื่อโปรดพิจารณา หากเห็นชอบโปรดนำเรียน{final_authority}{items_str}"
        elif self == MemoHierarchyLevel.FINAL_APPROVAL:
            return "จึงเรียนมาเพื่อโปรดพิจารณา หากเห็นชอบโปรดลงนามในหนังสือที่แนบมาพร้อมนี้"
        return "จึงเรียนมาเพื่อโปรดพิจารณา"


class Signer(BaseModel):
    """ผู้ลงนามหนึ่งคนในบันทึกข้อความ (ชื่อในวงเล็บ + ตำแหน่ง)"""
    name: str = Field(default="", description="ชื่อในวงเล็บ เช่น (นายสมชาย ใจดี); ว่าง = เว้นให้กรอก")
    position: str = ""
    is_author: bool = Field(default=False, description="ผู้เสนอเรื่อง: ใช้ชื่อ/ตำแหน่งของผู้ใช้ที่ล็อกอินถ้ามี")


class IssuingUnit(BaseModel):
    """หน่วยออกหนังสือ = หนึ่งขั้นในสายการเสนอ (กลุ่มงาน -> กอง -> สำนัก)

    แต่ละหน่วยมีบรรทัดส่วนราชการ รูปแบบเลขที่ ผู้รับ (เรียน) ผู้ลงนาม และชื่อผู้พิจารณา
    ในย่อหน้า "ข้อพิจารณาและเสนอแนะ" ของตัวเอง; ลำดับในรายการ = ลำดับการเสนอขึ้นไป

    รูปแบบเลขที่ (doc_number_format) ใช้ตัวแทน:
      {gap}  = ช่องว่างให้เจ้าหน้าที่เขียนเลขด้วยลายมือ (ไม่มีจุด)
      {year} = ปี พ.ศ. ปัจจุบันตามเวลาประเทศไทย
    เช่น "{gap}/{year}" -> "          /2569" และ "กท 1205/{gap}" -> "กท 1205/          "
    เขียนตัวเลขเป็นเลขอารบิก ระบบแปลงเป็นเลขไทยตอนส่งออกตามการตั้งค่าเอกสาร
    """

    key: str
    label: str = Field(description="ชื่อที่แสดงให้เลือก เช่น กลุ่มงานส่งเสริมกีฬา")
    dept_name: str = Field(description="บรรทัด 'ส่วนราชการ' ของบันทึกข้อความ (พิมพ์บรรทัดเดียวเสมอ)")
    doc_number_format: str = Field(default="{gap}/{year}")
    contact_dept: str = ""
    contact_tel: str = ""
    contact_fax: str = ""
    blank_day: bool = Field(default=True, description="เว้นเลขวันที่ไว้ให้ลงตอนลงนาม (เช่น '      สิงหาคม ๒๕๖๘')")
    is_default: bool = False
    recipient: str = Field(default="", description="ผู้รับ (ต่อจากคำว่า 'เรียน') เช่น หัวหน้ากลุ่มงานส่งเสริมกีฬา")
    signers: List[Signer] = Field(default_factory=list, description="ผู้ลงนามตามลำดับ (คนแรก = ผู้ลงนามหลัก)")
    review_party: str = Field(default="", description="ชื่อหน่วยในประโยค '...พิจารณาแล้ว' ของข้อพิจารณาและเสนอแนะ")
    request_text: str = Field(default="", description="ภาคความประสงค์มาตรฐานของขั้นนี้ (จึงเรียนมาเพื่อ...)")


def default_issuing_units() -> List["IssuingUnit"]:
    """สายการเสนอตั้งต้นของกลุ่มงานส่งเสริมกีฬา กองการกีฬา สำนักวัฒนธรรม กีฬา และการท่องเที่ยว
    (ตามตัวอย่างบันทึกข้อความจริง: กลุ่มงาน -> ผอ.กอง ลงนามถึง ผอ.สำนัก -> ผอ.สำนัก ลงนามถึงปลัดฯ)"""
    tel, fax = "๐ ๒๒๔๖ ๘๐๗๙", "๐ ๒๒๔๖ ๐๒๘๒"
    phone = f"โทร.{tel} โทรสาร {fax}"
    bureau = "สำนักวัฒนธรรม กีฬา และการท่องเที่ยว"
    return [
        IssuingUnit(
            key="sport-promotion",
            label="กลุ่มงานส่งเสริมกีฬา",
            dept_name=f"กลุ่มงานส่งเสริมกีฬา {phone}",
            doc_number_format="{gap}/{year}",
            contact_dept="กลุ่มงานส่งเสริมกีฬา", contact_tel=tel, contact_fax=fax, is_default=True,
            recipient="หัวหน้ากลุ่มงานส่งเสริมกีฬา",
            signers=[Signer(position="ผู้เสนอเรื่อง", is_author=True),
                     Signer(position="หัวหน้ากลุ่มงานส่งเสริมกีฬา")],
            review_party="กลุ่มงานส่งเสริมกีฬา",
            request_text="จึงเรียนมาเพื่อโปรดพิจารณานำเรียนผู้อำนวยการกองการกีฬาลงนามในหนังสือที่แนบ",
        ),
        IssuingUnit(
            key="sports-division",
            label="กองการกีฬา",
            dept_name=f"กองการกีฬา (กลุ่มงานส่งเสริมกีฬา {phone})",
            doc_number_format="กท 1205/{gap}",
            contact_dept="กองการกีฬา", contact_tel=tel, contact_fax=fax,
            recipient=f"ผู้อำนวยการ{bureau}",
            signers=[Signer(position="ผู้อำนวยการกองการกีฬา")],
            review_party="กองการกีฬา",
            request_text="จึงเรียนมาเพื่อโปรดพิจารณาลงนามหนังสือเรียนปลัดกรุงเทพมหานครที่แนบ",
        ),
        IssuingUnit(
            key="culture-sports-bureau",
            label=bureau,
            dept_name=f"{bureau} (กองการกีฬา {phone})",
            doc_number_format="กท 1205/{gap}",
            contact_dept="กองการกีฬา", contact_tel=tel, contact_fax=fax,
            recipient="ปลัดกรุงเทพมหานคร",
            signers=[Signer(position=f"ผู้อำนวยการ{bureau}")],
            review_party=bureau,
            request_text=("จึงเรียนมาเพื่อโปรดพิจารณา หากเห็นชอบโปรดนำเรียนผู้ว่าราชการกรุงเทพมหานคร"
                          "เพื่อโปรดพิจารณาตามข้อพิจารณาและเสนอแนะข้างต้น"),
        ),
    ]


class UserProfileSchema(BaseModel):
    """โปรไฟล์ข้อมูลหน่วยงานและผู้มีอำนาจลงนามของผู้ใช้งาน (User Organization Profile)"""
    dept_name: str = Field(
        default="สำนักวัฒนธรรม กีฬา และการท่องเที่ยว",
        description="ชื่อสำนัก/กรม/หน่วยงานระดับบน"
    )
    division_name: str = Field(
        default="กองการกีฬา",
        description="กอง/ฝ่าย"
    )
    section_name: str = Field(
        default="กลุ่มงานส่งเสริมกีฬา",
        description="กลุ่มงาน/งาน"
    )
    department_full: str = Field(
        default="สำนักวัฒนธรรม กีฬา และการท่องเที่ยว (กองการกีฬา โทร. ๐ ๒๒๔๖ ๘๐๗๙ โทรสาร ๐ ๒๒๔๖ ๐๒๘๒)",
        description="ชื่อส่วนราชการเต็มสำหรับหัวหนังสือภายใน/บันทึกข้อความ"
    )
    doc_origin_code: str = Field(
        default="กท ๐๒๐๔/",
        description="รหัสพยัญชนะนำหน้าเลขที่หนังสือ (เช่น กท ๐๒๐๔/)"
    )
    signatory_name: str = Field(
        default="(นายสิงห์ ลิ้มพิรัตน์)",
        description="ชื่อ-นามสกุล ผู้ลงนาม (ในวงเล็บ)"
    )
    signatory_position: str = Field(
        default="ผู้อำนวยการสำนักวัฒนธรรม กีฬา และการท่องเที่ยว",
        description="ตำแหน่งผู้ลงนาม"
    )
    contact_dept: str = Field(
        default="กองการกีฬา (กลุ่มงานส่งเสริมกีฬา)",
        description="หน่วยงานผู้ประสานงาน/เจ้าของเรื่อง"
    )
    contact_tel: str = Field(
        default="๐ ๒๒๔๖ ๘๐๗๙",
        description="เบอร์โทรศัพท์ติดต่อ"
    )
    issuing_units: List[IssuingUnit] = Field(
        default_factory=default_issuing_units,
        description="หน่วยออกหนังสือที่เลือกได้ (ส่วนราชการ + รูปแบบเลขที่)",
    )
    contact_fax: str = Field(
        default="๐ ๒๒๔๖ ๐๒๘๒",
        description="เบอร์โทรสาร"
    )
    contact_email: Optional[str] = Field(
        default="sports.bma@bangkok.go.th",
        description="อีเมลติดต่อราชการ"
    )
    hierarchy_default: MemoHierarchyLevel = Field(
        default=MemoHierarchyLevel.DEPT_TO_PERM_SEC,
        description="ระดับชั้นการเสนอเรื่องโดยปกติ"
    )


class RoutingNote(BaseModel):
    """บันทึกเกษียนสั่งการตามลำดับชั้นบังคับบัญชา"""
    author: str = Field(..., description="ผู้เกษียน/ลงนามสั่งการ เช่น 'ผอ.สำนักวัฒนธรรม กีฬา และการท่องเที่ยว'")
    position: Optional[str] = Field(None, description="ตำแหน่งของผู้เกษียนสั่งการ")
    target: Optional[str] = Field(None, description="ผู้รับคำสั่งหรือเสนอต่อไปยังผู้ใด เช่น 'เรียน ปลัดกรุงเทพมหานคร'")
    order_text: str = Field(..., description="ข้อความเกษียน/คำสั่งการ")
    order_date: Optional[str] = Field(None, description="วันที่เกษียนสั่งการ เช่น '๓๑ ม.ค. ๒๕๗๐'")
    signature_present: bool = Field(default=True, description="มีลายเซ็น/เกษียนจริงในเอกสาร")


class SourceItem(BaseModel):
    """เอกสารย่อยในแฟ้มเรื่อง (Case Dossier Item)"""
    item_id: str = Field(..., description="รหัสเอกสาร เช่น 'item-1', 'orig-letter'")
    title: str = Field(..., description="ชื่อเรื่องของเอกสาร")
    doc_no: Optional[str] = Field(None, description="เลขที่หนังสือ")
    doc_date: Optional[str] = Field(None, description="ลงวันที่")
    sender: Optional[str] = Field(None, description="หน่วยงานหรือผู้ส่ง")
    receiver: Optional[str] = Field(None, description="ผู้รับหนังสือ")
    page_start: int = Field(default=1, description="หน้าเริ่มต้นในไฟล์รวม")
    page_end: int = Field(default=1, description="หน้าสิ้นสุดในไฟล์รวม")
    doc_type: str = Field(default="external", description="ประเภทเอกสารย่อย: external (หนังสือภายนอก), internal (บันทึก), order (คำสั่ง), project (โครงการ/สิ่งที่ส่งมาด้วย)")
    replaces_item_id: Optional[str] = Field(None, description="รหัสเอกสารเดิมที่ฉบับนี้มายกเลิกหรือส่งมาแทน")


class SourceCase(BaseModel):
    """สำนวนแฟ้มเรื่องสารบรรณแบบหลายฉบับและสายเกษียนสั่งการ (Case Dossier)"""
    case_title: str = Field(..., description="ชื่อสำนวนเรื่อง เช่น 'ขอรับการสนับสนุนการจัดแข่งขันวิ่งเปี้ยวชิงชนะเลิศแห่งประเทศไทย'")
    items: List[SourceItem] = Field(default_factory=list, description="รายการเอกสารทั้งหมดในสำนวนเรื่อง")
    routing_notes: List[RoutingNote] = Field(default_factory=list, description="สายการเกษียนสั่งการตามลำดับชั้น")
    deadlines: List[str] = Field(default_factory=list, description="กำหนดการสำคัญหรือวันครบกำหนด")
    requested_items: List[str] = Field(default_factory=list, description="รายการคำขอที่ประมวลได้จากสำนวนเรื่อง")
    raw_text: Optional[str] = Field(None, description="ข้อความดิบทั้งหมดของสำนวนเรื่อง")

    def get_effective_incoming_item(self) -> Optional[SourceItem]:
        """คืนค่าเอกสารต้นเรื่องหลักที่มีผลบังคับใช้ (ไม่รวมฉบับที่ถูกยกเลิก/ส่งมาแทน)"""
        replaced_ids = {it.replaces_item_id for it in self.items if it.replaces_item_id}
        valid_items = [it for it in self.items if it.item_id not in replaced_ids and it.doc_type == "external"]
        return valid_items[0] if valid_items else (self.items[0] if self.items else None)

    def synthesize_memo_intro(self) -> str:
        """
        สังเคราะห์ข้อความย่อหน้า 'ต้นเรื่อง' สำหรับบันทึกข้อความ กทม.
        อ้างอิงเอกสารต้นเรื่องและสายเกษียนสั่งการตามระเบียบสารบรรณอย่างเป็นทางการ
        """
        eff = self.get_effective_incoming_item()
        intro_parts = []
        if eff:
            sender_str = eff.sender or "หน่วยงานต้นเรื่อง"
            doc_no_str = f" ที่ {eff.doc_no}" if eff.doc_no else ""
            date_str = f" ลงวันที่ {eff.doc_date}" if eff.doc_date else ""
            intro_parts.append(
                f"ตามที่ {sender_str} ได้มีหนังสือ{doc_no_str}{date_str} เรื่อง {eff.title} "
                f"แจ้งความประสงค์ขอความอนุเคราะห์จากกรุงเทพมหานคร ความละเอียดแจ้งแล้ว นั้น"
            )
        else:
            intro_parts.append(f"ตามที่ ได้มีหนังสือขอรับการสนับสนุนเรื่อง {self.case_title} นั้น")

        if self.routing_notes:
            routing_lines = []
            for idx, note in enumerate(self.routing_notes, 1):
                author_pos = f"{note.author}"
                if note.position:
                    author_pos += f" ({note.position})"
                date_str = f" เมื่อวันที่ {note.order_date}" if note.order_date else ""
                target_str = f" {note.target}" if note.target else ""
                # เลขลำดับข้อต้องเป็นเลขไทยล้วน (๑. ๒. ๓.) — ห้ามผสม "๑.1"
                ordinal = to_thai_numerals(str(idx))
                routing_lines.append(f"{ordinal}. {author_pos} ได้มีบันทึกเกษียนสั่งการ{target_str}{date_str} ว่า \"{note.order_text}\"")
            intro_parts.append("ต่อมา ได้มีบันทึกเกษียนสั่งการตามลำดับชั้น ดังนี้:\n" + "\n".join(routing_lines))

        return "\n\n".join(intro_parts)


class EvidenceRef(BaseModel):
    """หลักฐานอ้างอิงจากต้นเรื่อง (ข้อความ + ตำแหน่ง + ความมั่นใจตามวิธีที่ตรวจสอบได้)"""

    field: str
    value: str
    source_quote: str
    start: int
    end: int
    page: Optional[int] = None
    confidence: float
    method: Literal["regex", "ocr", "vlm", "manual", "profile"]
    needs_review: bool = False


class UnclearSpan(BaseModel):
    """ช่วงข้อความที่ OCR/การสกัดอ่านไม่ชัดเจน"""

    text: str
    start: int
    end: int
    page: Optional[int] = None
    reason: str


class ExtractedEntity(BaseModel):
    """ข้อมูลสำคัญที่สกัดได้จากต้นเรื่อง เช่น ชื่อ หน่วยงาน วันที่ จำนวนเงิน กำหนดการ"""

    kind: Literal["person", "agency", "date", "doc_no", "amount", "number", "deadline", "attachment"]
    value: str
    normalized: Optional[str] = None
    evidence: Optional[EvidenceRef] = None


class IntakeQuestion(BaseModel):
    """คำถามข้อมูลที่ขาด/ควรยืนยัน ก่อนเริ่มร่าง"""

    field: str
    question: str
    required: bool = True
    reason: str = ""
    placeholder: str = ""
    kind: Literal["text", "boolean", "choice"] = "text"
    options: List[str] = Field(default_factory=list)


class IntakeAssessment(BaseModel):
    """ผลประเมินความครบถ้วนของข้อมูลก่อนร่าง"""

    questions: List[IntakeQuestion] = Field(default_factory=list)
    missing_fields: List[str] = Field(default_factory=list)
    ready: bool = False


class SourceDocumentContext(BaseModel):
    """ข้อมูลที่สกัดได้จากเอกสารต้นเรื่อง (Source Document)"""
    source_filename: str = Field(..., description="ชื่อไฟล์ต้นเรื่องที่แนบ")
    source_dept: Optional[str] = Field(None, description="หน่วยงานผู้ส่งต้นเรื่อง")
    source_doc_no: Optional[str] = Field(None, description="เลขที่หนังสือต้นเรื่อง")
    source_date: Optional[str] = Field(None, description="วันที่ของหนังสือต้นเรื่อง")
    source_subject: Optional[str] = Field(None, description="เรื่องของหนังสือต้นเรื่อง")
    source_salutation: Optional[str] = Field(None, description="คำขึ้นต้น (เรียน/กราบเรียน) ในต้นเรื่อง")
    is_scanned: bool = Field(default=False, description="เป็นเอกสารสแกน/รูปภาพหรือไม่")
    page_count: int = Field(default=1, description="จำนวนหน้าของเอกสาร")
    preview_image_path: Optional[str] = Field(None, description="เส้นทางไฟล์รูปภาพพรีวิวหน้าแรก (ถ้ามี)")
    raw_text: str = Field(default="", description="ข้อความที่สกัดได้จากไฟล์ต้นเรื่อง")
    summary: str = Field(default="", description="สรุปสาระสำคัญของเรื่องเดิม")
    core_issues: List[str] = Field(default_factory=list, description="ประเด็นปัญหาหรือข้อเท็จจริง")
    requested_action: Optional[str] = Field(None, description="สิ่งที่ต้นเรื่องประสงค์หรือขอความร่วมมือ")
    extraction_failed: bool = Field(default=False, description="การสกัดข้อความล้มเหลวหรือไม่ (Fail-Safe)")
    extraction_error: Optional[str] = Field(default=None, description="ข้อความแจ้งเตือนข้อผิดพลาดในการสกัดข้อความ")
    ocr_engine_used: Optional[str] = Field(default=None, description="ชื่อ OCR Engine ที่ใช้ในการสกัด (Gemini/Docker/Local)")
    source_case: Optional[SourceCase] = Field(None, description="ข้อมูลสำนวนเรื่องแบบหลายฉบับ/สายเกษียนสั่งการ (Case Dossier)")
    entities: List[ExtractedEntity] = Field(default_factory=list, description="ข้อมูลสำคัญที่สกัดได้พร้อมหลักฐาน")
    unclear_spans: List[UnclearSpan] = Field(default_factory=list, description="ช่วงข้อความที่อ่านไม่ชัดเจน")
    field_confidence: Dict[str, float] = Field(default_factory=dict, description="ความมั่นใจรายฟิลด์ตามวิธีที่ตรวจสอบได้")
    missing_fields: List[str] = Field(default_factory=list, description="ฟิลด์สำคัญที่ยังขาด")


class SectionKind(str, Enum):
    DEPT = "dept"
    NUMBER_DATE = "number_date"
    SUBJECT = "subject"
    SALUTATION = "salutation"
    REFERENCES = "references"
    ATTACHMENTS = "attachments"
    INTRO = "intro"
    LAW = "law"
    FACTS = "facts"
    CONSIDERATION = "consideration"
    CLOSING = "closing"
    SIGNATURE = "signature"
    DETAILS = "details"
    PURPOSE = "purpose"
    CUSTOM = "custom"

    def default_label(self) -> str:
        return {
            SectionKind.DEPT: "ส่วนราชการ",
            SectionKind.NUMBER_DATE: "ที่ / วันที่",
            SectionKind.SUBJECT: "เรื่อง",
            SectionKind.SALUTATION: "เรียน",
            SectionKind.REFERENCES: "อ้างถึง",
            SectionKind.ATTACHMENTS: "สิ่งที่ส่งมาด้วย",
            SectionKind.INTRO: "ต้นเรื่อง",
            SectionKind.LAW: "ข้อกฎหมาย",
            SectionKind.FACTS: "ข้อเท็จจริง",
            SectionKind.CONSIDERATION: "ข้อพิจารณาและเสนอแนะ",
            SectionKind.CLOSING: "คำลงท้าย",
            SectionKind.SIGNATURE: "ลงชื่อ",
            SectionKind.DETAILS: "รายละเอียด",
            SectionKind.PURPOSE: "ความประสงค์",
            SectionKind.CUSTOM: "หัวข้อเพิ่มเติม",
        }[self]


class DocumentSection(BaseModel):
    """หัวข้อเอกสารที่ผู้ใช้เพิ่ม/ลบ/แก้ไข/สลับลำดับได้อย่างอิสระ"""

    id: str = Field(default_factory=lambda: uuid4().hex[:8])
    kind: SectionKind = SectionKind.CUSTOM
    label: str = ""
    content: str = ""
    secondary: str = ""  # วันที่ (NUMBER_DATE) หรือตำแหน่ง (SIGNATURE)
    enabled: bool = True


class GovDocumentSchema(BaseModel):
    """โมเดลข้อมูลหนังสือราชการฉบับร่าง/ส่งออกสมบูรณ์"""
    doc_type: DocType = Field(default=DocType.EXTERNAL, description="ประเภทหนังสือ (ภายนอก / ภายใน)")
    kind: DocumentKind = Field(default=DocumentKind.EXTERNAL_LETTER, description="ชนิดหนังสือ 6 ชนิดตามระเบียบ")
    special_title: Optional[str] = Field(None, description="ชื่อเอกสารชนิดพิเศษ เช่น 'คำสั่งกรุงเทพมหานคร'")
    special_preamble: Optional[str] = Field(None, description="ความนำ/อาศัยอำนาจของเอกสารชนิดพิเศษ")
    special_items: List[str] = Field(default_factory=list, description="ข้อความแยกข้อของเอกสารชนิดพิเศษ")
    special_note: Optional[str] = Field(None, description="หมายเหตุ/บทบังคับใช้ท้ายเอกสารชนิดพิเศษ")
    sections: Optional[List[DocumentSection]] = Field(
        None, description="ลำดับหัวข้อเอกสารแบบอิสระ (None = ใช้ฟิลด์มาตรฐานเดิม)"
    )
    edit_status: Literal["draft", "editing", "saved"] = Field(
        default="draft", description="สถานะการแก้ไข: ฉบับร่าง/กำลังแก้ไข/บันทึกแล้ว"
    )
    last_edited_at: Optional[str] = Field(None, description="เวลาที่แก้ไขล่าสุด")
    urgency: UrgencyLevel = Field(default=UrgencyLevel.NORMAL, description="ชั้นความเร็ว")
    secret: SecretLevel = Field(default=SecretLevel.NORMAL, description="ชั้นความลับ")
    use_thai_numerals: bool = Field(default=False, description="แปลงตัวเลขเป็นเลขไทยหรือไม่")
    font_family: Optional[Literal["it9", "psk", "sarabun_new"]] = Field(
        default=None,
        description="ฟอนต์ของฉบับนี้: it9 = TH SarabunIT๙ (ค่าเริ่มต้น), psk = TH SarabunPSK, sarabun_new = TH Sarabun New; None = ตามโปรไฟล์",
    )
    
    # ส่วนหัวหนังสือ
    doc_number: str = Field(..., description="ที่ (เลขที่หนังสือ) เช่น กค ๐๔๐๖/๑๒๓")
    dept_name: str = Field(..., description="ส่วนราชการเจ้าของหนังสือ เช่น สำนักงานปลัดกระทรวงการคลัง")
    doc_date: str = Field(..., description="วันที่ เช่น ๑๕ มีนาคม ๒๕๖๙ (ห้ามมีคำว่าวันที่)")
    subject: str = Field(..., description="เรื่อง (สั้น กะทัดรัด สื่อความหมาย)")
    salutation: str = Field(..., description="คำขึ้นต้น เช่น เรียน ปลัดกระทรวง...")
    references: Optional[List[str]] = Field(default=None, description="อ้างถึง (หนังสือเดิมที่เคยติดต่อกัน)")
    attachments: Optional[List[str]] = Field(default=None, description="สิ่งที่ส่งมาด้วย (ถ้ามี)")
    
    # ส่วนเนื้อความ (ตามโครงสร้าง 3 ภาค)
    paragraph_reason: str = Field(
        ..., 
        description="ภาคเหตุ (เช่น 'ด้วย...' หรือ 'ตามที่... ได้มีหนังสือ... นั้น')"
    )
    paragraph_details: Optional[str] = Field(
        None, 
        description="ภาคข้อเท็จจริงและข้อพิจารณา (รายละเอียดและเหตุผล)"
    )
    paragraph_purpose: str = Field(
        ..., 
        description="ภาคความประสงค์หรือภาคสรุป (เช่น 'จึงเรียนมาเพื่อโปรดพิจารณาอนุมัติ')"
    )

    # โครงสร้างเนื้อความเฉพาะของบันทึกข้อความ (แบบบันทึกเสนอพิจารณา)
    memo_intro: Optional[str] = Field(default=None, description="ต้นเรื่อง: ที่มาของเรื่อง หนังสือ/คำร้องที่ได้รับ และการสั่งการที่ผ่านมา (แยกข้อด้วยการขึ้นบรรทัดใหม่ เช่น '๑. ...')")
    memo_facts: Optional[str] = Field(default=None, description="ข้อเท็จจริง: ผลการตรวจสอบ/ประสานงาน รายละเอียดคำขอ วัน เวลา สถานที่")
    memo_law: Optional[str] = Field(default=None, description="ข้อกฎหมาย (ถ้ามี): กฎหมาย ระเบียบ หนังสือสั่งการ พร้อมมาตรา/ข้อที่เกี่ยวข้อง — ห้ามแต่งขึ้นเอง")
    memo_consideration: Optional[str] = Field(default=None, description="ข้อพิจารณาและเสนอแนะ: ความเห็นของหน่วยงานและข้อเสนอ (แยกข้อ ๑., ๑.๑ ได้)")
    memo_request: Optional[str] = Field(default=None, description="ภาคความประสงค์ เช่น 'จึงเรียนมาเพื่อโปรดพิจารณา หากเห็นชอบโปรดลงนามในหนังสือที่แนบ'")
    memo_heading_style: Literal["bma", "numbered"] = Field(
        default="bma",
        description="รูปแบบหัวข้อบันทึกข้อความ: 'bma' = หัวข้อขีดเส้นใต้ ลำดับ ต้นเรื่อง-ข้อกฎหมาย-ข้อเท็จจริง-ข้อพิจารณาฯ, 'numbered' = ๑. ต้นเรื่อง ๒. ข้อเท็จจริง ๓. ข้อกฎหมาย ๔. ข้อพิจารณาฯ",
    )
    memo_headings: Optional[Dict[str, str]] = Field(
        default=None,
        description="ชื่อหัวข้อบันทึกข้อความที่ผู้ใช้แก้เอง (intro/law/facts/consideration → ชื่อ); ค่าว่าง = ไม่แสดงหัวข้อ",
    )
    memo_hierarchy_level: MemoHierarchyLevel = Field(
        default=MemoHierarchyLevel.DEPT_TO_PERM_SEC,
        description="ระดับชั้นการเสนอหนังสือบันทึกข้อความสำหรับกำหนดประโยคลงท้าย",
    )

    # ส่วนท้ายหนังสือ
    closing: str = Field(default="ขอแสดงความนับถือ", description="คำลงท้าย (เช่น ขอแสดงความนับถือ)")
    signatory_name: str = Field(..., description="ชื่อเต็มผู้ลงนามในวงเล็บ เช่น (นายสมชาย ใจดี)")
    signatory_position: str = Field(..., description="ตำแหน่งผู้ลงนาม")
    co_signers: Optional[List[Signer]] = Field(
        default=None,
        description="ผู้ลงนามเพิ่มเติมของบันทึกข้อความ ต่อจากผู้ลงนามหลัก (เช่น หัวหน้ากลุ่มงานลงนามต่อจากผู้เสนอ)",
    )
    
    # ส่วนติดต่อสอบถาม (ท้ายกระดาษสำหรับหนังสือภายนอก)
    contact_dept: str = Field(..., description="กลุ่มงาน/กองเจ้าของเรื่อง")
    contact_tel: Optional[str] = Field(None, description="หมายเลขโทรศัพท์")
    contact_fax: Optional[str] = Field(None, description="หมายเลขโทรสาร")
    contact_email: Optional[str] = Field(None, description="อีเมลส่วนราชการ")

    # ลายมือชื่ออิเล็กทรอนิกส์ (Digital Signature Image)
    signature_image_path: Optional[str] = Field(default=None, description="พาธไฟล์ภาพลายมือชื่อ (PNG/JPG)")

    @model_validator(mode="after")
    def _sync_memo_to_paragraphs(self):
        """บันทึกข้อความที่กรอกเฉพาะ memo_* ให้คัดลอกลง paragraph_* ที่ว่าง เพื่อให้ส่วนอื่น (linter/copilot) ใช้งานได้"""
        if self.doc_type == DocType.INTERNAL:
            if not (self.paragraph_reason or "").strip() and self.memo_intro:
                self.paragraph_reason = self.memo_intro
            if not (self.paragraph_details or "").strip() and self.memo_facts:
                self.paragraph_details = self.memo_facts
            if not (self.paragraph_purpose or "").strip():
                tail = "\n\n".join(x for x in (self.memo_consideration, self.memo_request) if x)
                if tail:
                    self.paragraph_purpose = tail
        return self

    def _memo_parts(self) -> tuple:
        """คืนค่า (ต้นเรื่อง, ข้อเท็จจริง, ข้อกฎหมาย, ข้อพิจารณา, ภาคความประสงค์) พร้อม fallback สู่ paragraph_*"""
        from core.memo_layout import split_consideration_and_request

        intro = self.memo_intro if self.memo_intro is not None else self.paragraph_reason
        facts = self.memo_facts if self.memo_facts is not None else (self.paragraph_details or "")
        law = self.memo_law or ""
        consideration_src = self.memo_consideration if self.memo_consideration is not None else self.paragraph_purpose
        consideration, request = split_consideration_and_request(consideration_src, self.memo_request)
        return intro or "", facts or "", law, consideration or "", request or ""

    def get_memo_sections(self) -> List[tuple]:
        """
        ส่งคืนรายการหัวข้อและเนื้อหาของบันทึกข้อความ [(หัวข้อ, เนื้อหา), ...]
        ตามลำดับของ memo_heading_style (ไม่รวมภาคความประสงค์ — ดู get_memo_request)
        """
        from core.memo_layout import build_memo_sections

        intro, facts, law, consideration, _ = self._memo_parts()
        return [(title, body) for _, title, body in
                build_memo_sections(intro, facts, law, consideration, self.memo_heading_style,
                                    self.memo_headings)]

    def get_memo_request(self) -> str:
        """ภาคความประสงค์ (จึงเรียนมาเพื่อ...) ของบันทึกข้อความ"""
        return self._memo_parts()[4]

    def get_memo_blocks(self) -> list:
        """รายการย่อหน้าพร้อมระยะย่อหน้าสำหรับเรนเดอร์ (ใช้ร่วมกันทุก exporter)"""
        from core.memo_layout import build_memo_blocks, build_memo_sections

        intro, facts, law, consideration, request = self._memo_parts()
        sections = build_memo_sections(intro, facts, law, consideration, self.memo_heading_style,
                                       self.memo_headings)
        return build_memo_blocks(sections, request, self.memo_heading_style)

    def validate_memo_completeness(self) -> List[str]:
        """
        ตรวจสอบว่าบันทึกข้อความมีองค์ประกอบครบถ้วนตามหลักเกณฑ์หรือไม่
        - ต้นเรื่อง (ต้องมีทุกครั้ง)
        - ข้อเท็จจริง (ต้องมีทุกครั้ง)
        - ข้อพิจารณาและเสนอแนะ (ต้องมีทุกครั้ง)
        - ข้อกฎหมาย (ถ้ามี - optional)
        - ประโยคลงท้ายตามระดับชั้น (ต้องมีทุกครั้ง)
        คืนค่ารายการชื่อส่วนที่ยังขาดอยู่
        """
        missing = []
        intro, facts, _, consideration, request = self._memo_parts()
        if not (intro or "").strip():
            missing.append("ต้นเรื่อง")
        if not (facts or "").strip():
            missing.append("ข้อเท็จจริง")
        if not (consideration or "").strip():
            missing.append("ข้อพิจารณาและเสนอแนะ")
        if not (request or "").strip():
            missing.append("ประโยคลงท้ายตามระดับชั้น")
        return missing

    def find_placeholders(self) -> List[str]:
        """
        ค้นหาจุดที่ยังมี Smart Placeholder เช่น [ระบุ...], [✏️ ระบุ...] หรือ {{...}} ตกค้างอยู่
        คืนค่าเป็นรายการ (ชื่อฟิลด์: ข้อความ Placeholder)
        """
        import re
        pattern = re.compile(r'\[(?:✏️\s*)?ระบุ[^\]]*\]|\{\{[^\}]+\}\}')
        results = []
        text_fields = [
            ("เลขที่หนังสือ", self.doc_number),
            ("ส่วนราชการ", self.dept_name),
            ("วันที่", self.doc_date),
            ("เรื่อง", self.subject),
            ("คำขึ้นต้น", self.salutation),
            ("ภาคเหตุ", self.paragraph_reason),
            ("ภาคข้อเท็จจริง", self.paragraph_details or ""),
            ("ภาคความประสงค์", self.paragraph_purpose),
            ("ต้นเรื่อง (บันทึกข้อความ)", self.memo_intro or ""),
            ("ข้อเท็จจริง (บันทึกข้อความ)", self.memo_facts or ""),
            ("ข้อกฎหมาย (บันทึกข้อความ)", self.memo_law or ""),
            ("ข้อพิจารณาและเสนอแนะ (บันทึกข้อความ)", self.memo_consideration or ""),
            ("ภาคความประสงค์ (บันทึกข้อความ)", self.memo_request or ""),
            ("คำลงท้าย", self.closing),
            ("ชื่อผู้ลงนาม", self.signatory_name),
            ("ตำแหน่งผู้ลงนาม", self.signatory_position),
            ("กลุ่มงานเจ้าของเรื่อง", self.contact_dept or ""),
            ("โทรศัพท์", self.contact_tel or "")
        ]
        if self.references:
            for idx, ref in enumerate(self.references, 1):
                text_fields.append((f"อ้างถึง ({idx})", ref))
        if self.attachments:
            for idx, att in enumerate(self.attachments, 1):
                text_fields.append((f"สิ่งที่ส่งมาด้วย ({idx})", att))
                
        for label, val in text_fields:
            if not val:
                continue
            matches = pattern.findall(val)
            for m in matches:
                results.append(f"{label}: {m}")
        return results

    def count_placeholders(self) -> int:
        """นับจำนวนจุดที่ยังมี Smart Placeholder ค้างอยู่"""
        return len(self.find_placeholders())


