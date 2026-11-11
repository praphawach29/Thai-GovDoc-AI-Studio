"""
generate_samples.py — สร้างไฟล์ตัวอย่างหนังสือภายนอกและบันทึกข้อความ (DOCX และ Typst)
"""

import sys
from pathlib import Path

# Add project root to path
root_dir = Path(__file__).resolve().parent.parent
if str(root_dir) not in sys.path:
    sys.path.insert(0, str(root_dir))

from core.models import GovDocumentSchema, DocType, UrgencyLevel, SecretLevel
from core.word_exporter import export_govdoc_to_docx
from core.typst_exporter import export_govdoc_to_typst


def main():
    examples_dir = Path(__file__).resolve().parent.parent / "examples"
    examples_dir.mkdir(exist_ok=True)

    # 1. ตัวอย่างหนังสือภายนอก
    ext_doc = GovDocumentSchema(
        doc_type=DocType.EXTERNAL,
        urgency=UrgencyLevel.URGENT,
        secret=SecretLevel.NORMAL,
        use_thai_numerals=True,
        doc_number="ดพร ๐๑๐๒/ว ๑๒๓",
        dept_name="สำนักงานพัฒนารัฐบาลดิจิทัล (องค์การมหาชน) ถนนวิภาวดีรังสิต กรุงเทพฯ ๑๐๔๐๐",
        doc_date="๑๕ มีนาคม ๒๕๖๙",
        subject="การให้ความอนุเคราะห์วิทยากรบรรยายการประยุกต์ใช้ AI ในภาครัฐ",
        salutation="เรียน  อธิการบดีมหาวิทยาลัยเชียงใหม่",
        references=["หนังสือมหาวิทยาลัยเชียงใหม่ ที่ อว ๘๓๙๒/๑๐๒ ลงวันที่ ๕ มีนาคม ๒๕๖๙"],
        attachments=["แบบตอบรับวิทยากร จำนวน ๑ ฉบับ"],
        paragraph_reason="ตามที่ มหาวิทยาลัยเชียงใหม่ ได้มีหนังสือที่อ้างถึง แจ้งความประสงค์ขอความอนุเคราะห์วิทยากรบรรยายในหัวข้อ การประยุกต์ใช้ AI ในภาครัฐเพื่อยกระดับงานบริการประชาชน ในวันที่ ๒๕ มีนาคม ๒๕๖๙ ความละเอียดแจ้งแล้ว นั้น",
        paragraph_details="สำนักงานพัฒนารัฐบาลดิจิทัล (องค์การมหาชน) ได้พิจารณาแล้ว มีความยินดีและไม่ขัดข้องในการให้ความอนุเคราะห์วิทยากรดังกล่าว โดยได้มอบหมายให้ นายสมชาย ดิจิทัล ตำแหน่งผู้เชี่ยวชาญด้านปัญญาประดิษฐ์ เข้าร่วมบรรยายตามวัน เวลา และสถานที่ดังกล่าว",
        paragraph_purpose="จึงเรียนมาเพื่อโปรดทราบ และได้มอบหมายให้ผู้ประสานงานดำเนินการในส่วนที่เกี่ยวข้องต่อไป",
        closing="ขอแสดงความนับถือ",
        signatory_name="(นางสาวสุดา พัฒนารัฐ)",
        signatory_position="ผู้อำนวยการสำนักงานพัฒนารัฐบาลดิจิทัล",
        contact_dept="ฝ่ายพัฒนาศักยภาพภาครัฐ",
        contact_tel="๐ ๒๖๑๒ ๖๐๐๐ ต่อ ๑๒๓๔",
        contact_fax="๐ ๒๖๑๒ ๖๐๐๑",
        contact_email="contact@dga.or.th"
    )

    # 2. ตัวอย่างหนังสือภายใน (บันทึกข้อความ)
    int_doc = GovDocumentSchema(
        doc_type=DocType.INTERNAL,
        urgency=UrgencyLevel.NORMAL,
        secret=SecretLevel.NORMAL,
        use_thai_numerals=False,
        doc_number="๑๒๓/๒๕๖๙",
        dept_name="ฝ่ายพัฒนาเทคโนโลยี สำนักงานพัฒนารัฐบาลดิจิทัล (องค์การมหาชน)",
        doc_date="๑๕ มีนาคม ๒๕๖๙",
        subject="ขออนุมัติจัดโครงการสัมมนาเชิงปฏิบัติการการใช้ AI สารบรรณภาครัฐ",
        salutation="เรียน  ผู้อำนวยการสำนักงานพัฒนารัฐบาลดิจิทัล",
        paragraph_reason="ด้วย ฝ่ายพัฒนาเทคโนโลยี มีความประสงค์จะจัดโครงการสัมมนาเชิงปฏิบัติการการใช้ AI สารบรรณภาครัฐ สำหรับบุคลากรในสังกัด",
        paragraph_details="การจัดโครงการดังกล่าวมีวัตถุประสงค์เพื่อเพิ่มประสิทธิภาพในการร่างและบริหารจัดการเอกสารราชการอิเล็กทรอนิกส์ ให้เป็นไปตามระเบียบงานสารบรรณ พ.ศ. ๒๕๒๖ และประหยัดเวลาการทำงานของเจ้าหน้าที่",
        paragraph_purpose="จึงเรียนมาเพื่อโปรดพิจารณาอนุมัติการจัดโครงการและงบประมาณดำเนินงานดังกล่าว",
        closing="",
        signatory_name="(นายวิชาการ มุ่งมั่น)",
        signatory_position="หัวหน้าฝ่ายพัฒนาเทคโนโลยี",
        contact_dept="ฝ่ายพัฒนาเทคโนโลยี",
        contact_tel="0 2612 6000"
    )

    p1 = export_govdoc_to_docx(ext_doc, str(examples_dir / "หนังสือภายนอก_ตัวอย่าง.docx"))
    p2 = export_govdoc_to_typst(ext_doc, str(examples_dir / "หนังสือภายนอก_ตัวอย่าง.typ"))
    p3 = export_govdoc_to_docx(int_doc, str(examples_dir / "บันทึกข้อความ_ตัวอย่าง.docx"))
    p4 = export_govdoc_to_typst(int_doc, str(examples_dir / "บันทึกข้อความ_ตัวอย่าง.typ"))

    print(f"Generated: {p1}")
    print(f"Generated: {p2}")
    print(f"Generated: {p3}")
    print(f"Generated: {p4}")


if __name__ == "__main__":
    main()
