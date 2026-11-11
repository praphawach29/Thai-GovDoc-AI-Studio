"""
extractor.py — ตัวสกัดข้อความและวิเคราะห์บริบทจากไฟล์ต้นเรื่อง (PDF, Scan, Image, DOCX)
ปรับปรุงสำหรับ Phase 2: รองรับทั้ง Digital PDF, Scanned PDF, Word Tables และ OCR Preprocessing
"""

import os
import re
from pathlib import Path
from typing import Optional, List, Tuple

from core.models import SourceDocumentContext
from core.ocr_preprocessor import (
    render_pdf_to_images,
    check_is_scanned_pdf,
    deskew_image,
    enhance_document_contrast
)


THAI_MONTHS_REGEX = r'(?:มกราคม|กุมภาพันธ์|มีนาคม|เมษายน|พฤษภาคม|มิถุนายน|กรกฎาคม|สิงหาคม|กันยายน|ตุลาคม|พฤศจิกายน|ธันวาคม)'


def extract_text_from_pdf(pdf_path: str) -> Tuple[str, bool, int, Optional[str]]:
    """
    สกัดข้อความจากไฟล์ PDF
    คืนค่า (raw_text, is_scanned, page_count, preview_image_path)
    """
    text_chunks = []
    page_count = 1
    preview_path = None

    # ตรวจสอบจำนวนหน้าและสกัดข้อความด้วย pdfplumber
    try:
        import pdfplumber
        with pdfplumber.open(pdf_path) as pdf:
            page_count = len(pdf.pages)
            for page in pdf.pages:
                page_text = page.extract_text()
                if page_text:
                    text_chunks.append(page_text.strip())
    except Exception:
        pass

    # Fallback สกัดข้อความด้วย pypdfium2 หาก pdfplumber ไม่ได้ผล
    if not text_chunks:
        try:
            import pypdfium2 as pdfium
            pdf = pdfium.PdfDocument(pdf_path)
            try:
                page_count = len(pdf)
                for page in pdf:
                    textpage = page.get_textpage()
                    page_text = textpage.get_text_range()
                    textpage.close()
                    page.close()
                    if page_text:
                        text_chunks.append(page_text.strip())
            finally:
                pdf.close()
        except Exception:
            pass

    raw_text = "\n\n".join(text_chunks)
    is_scanned = len(raw_text.strip()) < 50

    # สร้างรูปภาพพรีวิวหน้าแรก (สำหรับแสดงใน UI)
    try:
        images = render_pdf_to_images(pdf_path, max_pages=1, scale=1.5)
        if images:
            preview_dir = Path(pdf_path).parent / "previews"
            preview_dir.mkdir(parents=True, exist_ok=True)
            preview_path = str(preview_dir / f"{Path(pdf_path).stem}_preview.png")
            images[0].save(preview_path)
    except Exception as e:
        print(f"Error creating preview: {e}")

    # หากเป็นเอกสารสแกน และยังไม่มีข้อความ ลองสกัดผ่าน OCR หรือ Multimodal
    if is_scanned and preview_path:
        ocr_text = try_extract_ocr_or_vlm(preview_path)
        if ocr_text:
            raw_text = ocr_text

    return raw_text, is_scanned, page_count, preview_path


def extract_text_from_docx(docx_path: str) -> str:
    """
    สกัดข้อความจากไฟล์ Word (.docx) อย่างสมบูรณ์
    ครอบคลุมทั้งย่อหน้าปกติ (Paragraphs) และตารางส่วนหัว (Tables)
    """
    try:
        from docx import Document
        doc = Document(docx_path)
        chunks = []
        
        # 1. อ่านตารางก่อน (มักเป็นที่ตั้งของ ที่, วันที่, ส่วนราชการ)
        for table in doc.tables:
            for row in table.rows:
                for cell in row.cells:
                    for p in cell.paragraphs:
                        text = p.text.strip()
                        if text and text not in chunks:
                            chunks.append(text)

        # 2. อ่านย่อหน้าในเนื้อความ
        for p in doc.paragraphs:
            text = p.text.strip()
            if text and text not in chunks:
                chunks.append(text)

        raw = "\n\n".join(chunks)
        # ล้างอักขระ ZWSP เพื่อให้การค้นหา Regex ทำงานได้อย่างแม่นยำ
        return raw.replace("\u200b", "")
    except Exception as e:
        return f"Error extracting DOCX: {str(e)}"


def extract_text_from_image_file(image_path: str) -> Tuple[str, Optional[str]]:
    """
    ประมวลผลรูปภาพเอกสารสแกน:
    1. ปรับมุมเอียง (Deskew) และปรับ Contrast ด้วย OpenCV
    2. บันทึกภาพที่ปรับแต่งแล้ว
    3. ส่งเข้า OCR หรือ Multimodal Engine
    """
    import cv2
    img_cv = cv2.imread(image_path)
    preview_path = image_path

    if img_cv is not None:
        # ปรับภาพให้ตรง
        deskewed, _ = deskew_image(img_cv)
        enhanced = enhance_document_contrast(deskewed)
        preview_dir = Path(image_path).parent / "previews"
        preview_dir.mkdir(parents=True, exist_ok=True)
        preview_path = str(preview_dir / f"{Path(image_path).stem}_enhanced.png")
        cv2.imwrite(preview_path, enhanced)

    text = try_extract_ocr_or_vlm(preview_path)
    return text, preview_path


def try_extract_ocr_or_vlm(image_path: str) -> str:
    """
    พยายามถอดข้อความจากภาพ:
    1. หากมี Gemini API Key -> ใช้ Gemini Vision
    2. หากมี Tesseract -> ใช้ Tesseract
    3. ถ้าไม่มี -> ส่งคืนข้อความแนะนำ
    """
    api_key = os.getenv("GEMINI_API_KEY")
    if api_key:
        try:
            from google import genai
            from PIL import Image
            client = genai.Client(api_key=api_key)
            pil_img = Image.open(image_path)
            res = client.models.generate_content(
                model='gemini-2.5-flash',
                contents=[
                    pil_img,
                    "กรุณาถอดข้อความทั้งหมดจากเอกสารราชการไทยฉบับนี้อย่างละเอียด 100% คงโครงสร้าง ที่, วันที่, เรื่อง, เรียน, และเนื้อหาครบถ้วน"
                ]
            )
            if res and res.text:
                return res.text.strip()
        except Exception as e:
            print(f"Gemini Vision error: {e}")

    # Fallback to Tesseract ถ้ามี
    try:
        import pytesseract
        from PIL import Image
        pil_img = Image.open(image_path)
        return pytesseract.image_to_string(pil_img, lang="tha+eng")
    except Exception:
        pass

    return "(เอกสารนี้เป็นไฟล์ภาพ/สแกน กรุณาระบุ GEMINI_API_KEY หรือติดตั้ง Tesseract OCR เพื่อถอดข้อความอัตโนมัติ)"


def parse_govdoc_metadata(raw_text: str) -> dict:
    """
    วิเคราะห์และสกัด Metadata ของหนังสือราชการอย่างแม่นยำ (Pattern Matcher)
    """
    clean_text = raw_text.replace("\u200b", "")
    lines = [line.strip() for line in clean_text.split("\n") if line.strip()]

    doc_no = None
    doc_date = None
    subject = None
    salutation = None
    dept = None
    references = []
    attachments = []

    # 1. ค้นหาเลขที่หนังสือ "ที่ ..." (ต้องไม่ตรงกับ "ตามที่" หรือ "ในวันที่")
    for line in lines[:20]:
        # ตรวจสอบบรรทัดที่ขึ้นต้นด้วย "ที่ "
        match_no = re.search(r'^(?:ที่|เลขที่)\s*([^\n\r]+)', line)
        if match_no:
            candidate = match_no.group(1).strip()
            # ป้องกันกรณีเป็น "ที่อ้างถึง" หรือ "ที่ประชุม"
            if not any(candidate.startswith(x) for x in ["อ้างถึง", "ประชุม", "ตั้ง", "ทำการ", "ปรึกษา"]):
                doc_no = candidate
                break

    # 2. ค้นหาวันที่ พ.ศ.
    date_pattern = rf'([๐-๙0-9]{{1,2}}\s+{THAI_MONTHS_REGEX}\s+(?:พ\.ศ\.\s*)?[๐-๙0-9]{{4}})'
    for line in lines[:25]:
        match_date = re.search(date_pattern, line)
        if match_date:
            doc_date = match_date.group(1).strip()
            break

    # 3. ค้นหาเรื่อง
    for line in lines[:25]:
        match_sub = re.search(r'^เรื่อง\s*([^\n\r]+)', line)
        if match_sub:
            subject = match_sub.group(1).strip()
            break

    # 4. ค้นหาเรียน / กราบเรียน
    for line in lines[:25]:
        match_sal = re.search(r'^(?:กราบเรียน|เรียน)\s*([^\n\r]+)', line)
        if match_sal:
            salutation = match_sal.group(1).strip()
            break

    # 5. ค้นหาหน่วยงานผู้ส่ง (สแกนบรรทัดช่วงแรกที่ระบุชื่อกระทรวง กรม สำนักงาน มหาวิทยาลัย)
    for line in lines[:15]:
        if line.startswith("ที่") or line.startswith("เรื่อง") or line.startswith("เรียน") or "บันทึกข้อความ" in line:
            continue
        if any(kw in line for kw in ["กระทรวง", "กรม", "สำนักงาน", "มหาวิทยาลัย", "จังหวัด", "เทศบาล", "องค์การ", "ฝ่าย", "กอง", "คณะ"]):
            if len(line) < 160 and not line.startswith("ตามที่") and not line.startswith("ในวันที่"):
                # ตัดส่วนที่อยู่ด้านหลัง เช่น ถนน... ตำบล... ออก เพื่อให้ได้ชื่อหน่วยงานชัดเจน
                dept_clean = re.split(r'\s+(?:ถนน|ต\.|ตำบล|อ\.|อำเภอ|จ\.|จังหวัด|\d{5}|เลขที่)', line)[0].strip()
                dept_clean = re.sub(r'[\s๐-๙0-9]+$', '', dept_clean).strip()
                dept = dept_clean if dept_clean else line.strip()
                break

    # 6. ค้นหาอ้างถึง และ สิ่งที่ส่งมาด้วย
    for line in lines[:30]:
        match_ref = re.search(r'^อ้างถึง\s*([^\n\r]+)', line)
        if match_ref:
            references.append(match_ref.group(1).strip())
        match_att = re.search(r'^สิ่งที่ส่งมาด้วย\s*([^\n\r]+)', line)
        if match_att:
            attachments.append(match_att.group(1).strip())

    return {
        "doc_no": doc_no,
        "doc_date": doc_date,
        "subject": subject,
        "salutation": salutation,
        "dept": dept,
        "references": references,
        "attachments": attachments
    }


def extract_source_document(file_path: str) -> SourceDocumentContext:
    """
    ฟังก์ชันหลักสำหรับวิเคราะห์และสกัดข้อมูลจากไฟล์ต้นเรื่องทุกชนิด
    """
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"File not found: {file_path}")

    ext = path.suffix.lower()
    raw_text = ""
    is_scanned = False
    page_count = 1
    preview_path = None

    if ext == ".pdf":
        raw_text, is_scanned, page_count, preview_path = extract_text_from_pdf(str(path))
    elif ext in [".docx", ".doc"]:
        raw_text = extract_text_from_docx(str(path))
        is_scanned = False
    elif ext in [".png", ".jpg", ".jpeg", ".tiff", ".bmp"]:
        raw_text, preview_path = extract_text_from_image_file(str(path))
        is_scanned = True
    elif ext in [".txt", ".md", ".json"]:
        raw_text = path.read_text(encoding="utf-8")
        is_scanned = False
    else:
        raise ValueError(f"Unsupported file type: {ext}")

    meta = parse_govdoc_metadata(raw_text)

    # สรุปประเด็นปัญหาและใจความสำคัญ
    lines = [l.strip() for l in raw_text.split("\n") if l.strip()]
    summary_text = " ".join(lines[2:6]) if len(lines) >= 3 else (" ".join(lines) if lines else "ไม่พบข้อความ")

    return SourceDocumentContext(
        source_filename=path.name,
        source_dept=meta["dept"] or "หน่วยงานต้นเรื่อง",
        source_doc_no=meta["doc_no"],
        source_date=meta["doc_date"],
        source_subject=meta["subject"],
        source_salutation=meta["salutation"],
        is_scanned=is_scanned,
        page_count=page_count,
        preview_image_path=preview_path,
        raw_text=raw_text,
        summary=summary_text,
        core_issues=lines[:6] if lines else [],
        requested_action=f"พิจารณาดำเนินการเกี่ยวกับ{meta['subject'] or 'ข้อเสนอในเอกสารต้นเรื่อง'}"
    )
