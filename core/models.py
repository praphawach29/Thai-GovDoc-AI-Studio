"""
models.py — Data Schemas for Thai Official Government Documents
อ้างอิงตามระเบียบสำนักนายกรัฐมนตรีว่าด้วยงานสารบรรณ พ.ศ. ๒๕๒๖ และที่แก้ไขเพิ่มเติม
"""

from enum import Enum
from typing import List, Optional
from pydantic import BaseModel, Field


class DocType(str, Enum):
    EXTERNAL = "external"    # หนังสือภายนอก (ครุฑ 3 ซม. กึ่งกลาง)
    INTERNAL = "internal"    # หนังสือภายใน / บันทึกข้อความ (ครุฑ 1.5 ซม. ด้านซ้าย)


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
    raw_text: str = Field(..., description="ข้อความที่สกัดได้จากไฟล์ต้นเรื่อง")
    summary: str = Field(..., description="สรุปสาระสำคัญของเรื่องเดิม")
    core_issues: List[str] = Field(default_factory=list, description="ประเด็นปัญหาหรือข้อเท็จจริง")
    requested_action: Optional[str] = Field(None, description="สิ่งที่ต้นเรื่องประสงค์หรือขอความร่วมมือ")


class GovDocumentSchema(BaseModel):
    """โมเดลข้อมูลหนังสือราชการฉบับร่าง/ส่งออกสมบูรณ์"""
    doc_type: DocType = Field(default=DocType.EXTERNAL, description="ประเภทหนังสือ (ภายนอก / ภายใน)")
    urgency: UrgencyLevel = Field(default=UrgencyLevel.NORMAL, description="ชั้นความเร็ว")
    secret: SecretLevel = Field(default=SecretLevel.NORMAL, description="ชั้นความลับ")
    use_thai_numerals: bool = Field(default=False, description="แปลงตัวเลขเป็นเลขไทยหรือไม่")
    
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
    
    # ส่วนท้ายหนังสือ
    closing: str = Field(default="ขอแสดงความนับถือ", description="คำลงท้าย (เช่น ขอแสดงความนับถือ)")
    signatory_name: str = Field(..., description="ชื่อเต็มผู้ลงนามในวงเล็บ เช่น (นายสมชาย ใจดี)")
    signatory_position: str = Field(..., description="ตำแหน่งผู้ลงนาม")
    
    # ส่วนติดต่อสอบถาม (ท้ายกระดาษสำหรับหนังสือภายนอก)
    contact_dept: str = Field(..., description="กลุ่มงาน/กองเจ้าของเรื่อง")
    contact_tel: Optional[str] = Field(None, description="หมายเลขโทรศัพท์")
    contact_fax: Optional[str] = Field(None, description="หมายเลขโทรสาร")
    contact_email: Optional[str] = Field(None, description="อีเมลส่วนราชการ")

