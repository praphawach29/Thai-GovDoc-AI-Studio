"""
extractor.py — ตัวสกัดข้อความและวิเคราะห์บริบทจากไฟล์ต้นเรื่อง (PDF, Scan, Image, DOCX)
รองรับ Multi-Engine OCR (Gemini Vision, Docker Tesseract, Local Pytesseract)
และมีระบบ Fail-Safe หยุดการยกร่างทันทีหากไม่สามารถถอดข้อความได้ พร้อมตัดชื่อไฟล์ออกจาก Metadata
"""

import os
import re
import io
import subprocess
from pathlib import Path
from typing import Optional, List, Tuple
from PIL import Image

from core.models import SourceDocumentContext
from core.ocr_preprocessor import (
    render_pdf_to_images,
    deskew_image,
    enhance_document_contrast
)


THAI_MONTHS_REGEX = r'(?:มกราคม|กุมภาพันธ์|มีนาคม|เมษายน|พฤษภาคม|มิถุนายน|กรกฎาคม|สิงหาคม|กันยายน|ตุลาคม|พฤศจิกายน|ธันวาคม)'


def clean_thai_intra_word_spaces(text: str) -> str:
    """
    ทำความสะอาดช่องว่างเดี่ยวระหว่างพยัญชนะไทยที่เกิดจากการ OCR (เช่น 'ส ม า ค ม' -> 'สมาคม')
    """
    lines = []
    for line in text.split("\n"):
        # ยุบช่องว่างระหว่างตัวอักษรภาษาไทย/สระ/วรรณยุกต์
        cleaned = re.sub(r'(?<=[\u0e01-\u0e5b]) (?=[\u0e01-\u0e5b])', '', line)
        lines.append(cleaned)
    return "\n".join(lines)


def extract_ocr_docker_tesseract(image_bytes: bytes) -> str:
    """
    ถอดข้อความภาษาไทยด้วย Tesseract ผ่าน Docker (tha-tesseract:latest หรือ container ชั่วคราว)
    ทำงานแบบ Offline 100% ไม่ต้องใช้อินเทอร์เน็ต
    """
    try:
        proc = subprocess.run(
            ['docker', 'run', '--rm', '-i', 'tha-tesseract:latest', 'stdin', 'stdout', '-l', 'tha+eng'],
            input=image_bytes,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=30
        )
        if proc.returncode == 0:
            raw = proc.stdout.decode('utf-8', errors='ignore')
            return clean_thai_intra_word_spaces(raw).strip()
    except Exception as e:
        print(f"Docker OCR error: {e}")
    return ""


def extract_ocr_gemini(pil_img: Image.Image, api_key: Optional[str] = None) -> str:
    """
    ถอดข้อความด้วย Gemini Vision API (Multimodal AI)
    รองรับการอ่านลายมือเกษียนสั่งการ ตรายางรับหนังสือ และตารางที่มีความซับซ้อนสูง
    """
    key = api_key or os.getenv("GEMINI_API_KEY")
    if not key:
        return ""
    try:
        from google import genai
        client = genai.Client(api_key=key)
        prompt = (
            "กรุณาถอดข้อความภาษาไทยทั้งหมดจากภาพเอกสารราชการฉบับนี้อย่างละเอียด ครบถ้วน 100% "
            "โดยคงโครงสร้างข้อความ ส่วนราชการ, ที่, วันที่, เรื่อง, เรียน, อ้างถึง, สิ่งที่ส่งมาด้วย, "
            "เนื้อหาทุกย่อหน้า, รายการข้อขอความอนุเคราะห์, และบันทึกข้อความสั่งการ/เกษียนหนังสือ/ตรายางรับหนังสือทั้งหมด"
        )
        res = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=[pil_img, prompt]
        )
        if res and res.text:
            return res.text.strip()
    except Exception as e:
        print(f"Gemini Vision error: {e}")
    return ""


def extract_ocr_pytesseract(pil_img: Image.Image) -> str:
    """ถอดข้อความด้วย pytesseract ในเครื่อง (ถ้ามีการติดตั้งไว้)"""
    try:
        import pytesseract
        raw = pytesseract.image_to_string(pil_img, lang="tha+eng")
        return clean_thai_intra_word_spaces(raw).strip()
    except Exception:
        return ""


def try_extract_ocr_multi_engine(
    pil_img: Image.Image, api_key: Optional[str] = None, allow_cloud: bool = True
) -> Tuple[str, Optional[str]]:
    """
    พยายามถอดข้อความจากภาพผ่านลำดับความสำคัญของ OCR Engines:
    1. Gemini Vision (ถ้ามี API Key) -> แม่นยำที่สุดทั้งตัวพิมพ์ ลายมือ และตรายาง
    2. Local Docker Tesseract -> เร็ว ออฟไลน์ รองรับไทย+อังกฤษ
    3. System pytesseract (ถ้าติดตั้งในระบบ)
    คืนค่า (ข้อความที่ถอดได้, ชื่อ Engine ที่ใช้)
    """
    # แปลง PIL เป็น PNG Bytes สำหรับ Docker
    buf = io.BytesIO()
    pil_img.save(buf, format='PNG')
    png_bytes = buf.getvalue()

    # 1. ลอง Gemini Vision ก่อน
    if allow_cloud and (api_key or os.getenv("GEMINI_API_KEY")):
        gemini_txt = extract_ocr_gemini(pil_img, api_key=api_key)
        if len(gemini_txt.strip()) >= 20:
            return gemini_txt, "Gemini Vision"

    # 2. ลอง Local Docker Tesseract
    docker_txt = extract_ocr_docker_tesseract(png_bytes)
    if len(docker_txt.strip()) >= 20:
        return docker_txt, "Local Docker Tesseract (tha+eng)"

    # 3. ลอง Local pytesseract
    pytess_txt = extract_ocr_pytesseract(pil_img)
    if len(pytess_txt.strip()) >= 20:
        return pytess_txt, "Local Tesseract (pytesseract)"

    return "", None


def extract_text_from_pdf(
    pdf_path: str, api_key: Optional[str] = None, allow_cloud: bool = True
) -> Tuple[str, bool, int, Optional[str], bool, Optional[str], Optional[str]]:
    """
    สกัดข้อความจากไฟล์ PDF:
    - ถ้าเป็น Digital PDF -> สกัดข้อความโดยตรง
    - ถ้าเป็น Scanned PDF -> สกัดด้วย Multi-Engine OCR ทีละหน้า
    คืนค่า (raw_text, is_scanned, page_count, preview_path, extraction_failed, extraction_error, ocr_engine_used)
    """
    text_chunks = []
    page_count = 1
    preview_path = None
    extraction_failed = False
    extraction_error = None
    ocr_engine_used = None

    # 1. พยายามสกัดข้อความดิจิทัลผ่าน pdfplumber
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

    # 2. Fallback สกัดข้อความด้วย pypdfium2 หาก pdfplumber ไม่ได้ผล
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

    digital_text = "\n\n".join(text_chunks).strip()
    is_scanned = len(digital_text) < 50

    # 3. สร้างรูปภาพสำหรับพรีวิวและเตรียม OCR
    images = []
    try:
        # สแกนหน้าสูงสุด 6 หน้าสำหรับเอกสารราชการ
        images = render_pdf_to_images(pdf_path, max_pages=6, scale=2.0)
        if images:
            preview_dir = Path(pdf_path).parent / "previews"
            preview_dir.mkdir(parents=True, exist_ok=True)
            preview_path = str(preview_dir / f"{Path(pdf_path).stem}_preview.png")
            images[0].save(preview_path)
    except Exception as e:
        print(f"Error creating preview/rendering PDF: {e}")

    # 4. หากเป็นเอกสารสแกน ทำการประมวลผล OCR
    if is_scanned:
        if not images:
            extraction_failed = True
            extraction_error = "ไม่สามารถแปลงไฟล์ PDF เป็นภาพเพื่อประมวลผล OCR ได้"
            return "", True, page_count, preview_path, extraction_failed, extraction_error, None

        ocr_pages = []
        for idx, img in enumerate(images):
            txt, eng_name = try_extract_ocr_multi_engine(img, api_key=api_key, allow_cloud=allow_cloud)
            if txt:
                ocr_pages.append(f"--- หน้าที่ {idx + 1} ---\n{txt}")
                if not ocr_engine_used and eng_name:
                    ocr_engine_used = eng_name

        if ocr_pages:
            raw_text = "\n\n".join(ocr_pages)
            extraction_failed = False
        else:
            # FAIL-SAFE: ไม่พบข้อความใดๆ จาก OCR
            raw_text = ""
            extraction_failed = True
            extraction_error = (
                "เอกสารนี้เป็นไฟล์สแกน/ภาพถ่าย แต่ระบบไม่สามารถถอดข้อความได้ "
                "(กรุณาระบุ GEMINI_API_KEY หรือเปิดใช้งาน Local Docker OCR หรือกรอกข้อความด้วยตนเอง)"
            )
    else:
        raw_text = digital_text

    return raw_text, is_scanned, page_count, preview_path, extraction_failed, extraction_error, ocr_engine_used


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


def extract_text_from_image_file(
    image_path: str, api_key: Optional[str] = None, allow_cloud: bool = True
) -> Tuple[str, Optional[str], bool, Optional[str], Optional[str]]:
    """
    ประมวลผลรูปภาพเอกสารสแกน:
    1. ปรับมุมเอียง (Deskew) และปรับ Contrast ด้วย OpenCV
    2. บันทึกภาพที่ปรับแต่งแล้ว
    3. ส่งเข้า OCR Multi-Engine
    """
    import cv2
    img_cv = cv2.imread(image_path)
    preview_path = image_path

    if img_cv is not None:
        deskewed, _ = deskew_image(img_cv)
        enhanced = enhance_document_contrast(deskewed)
        preview_dir = Path(image_path).parent / "previews"
        preview_dir.mkdir(parents=True, exist_ok=True)
        preview_path = str(preview_dir / f"{Path(image_path).stem}_enhanced.png")
        cv2.imwrite(preview_path, enhanced)

    pil_img = Image.open(preview_path)
    text, eng_name = try_extract_ocr_multi_engine(pil_img, api_key=api_key, allow_cloud=allow_cloud)

    if len(text.strip()) >= 20:
        return text, preview_path, False, None, eng_name
    else:
        return "", preview_path, True, "ไม่สามารถถอดข้อความจากไฟล์รูปภาพได้ (กรุณาระบุ GEMINI_API_KEY หรือเปิด Local OCR)", None


def parse_govdoc_metadata(raw_text: str) -> dict:
    """
    วิเคราะห์และสกัด Metadata ของหนังสือราชการอย่างแม่นยำ (Pattern Matcher)
    ปรับปรุงให้รองรับเอกสารจากสมาคม/ชมรม/เอกชน และฟอร์แมตวันที่ที่ไม่มีช่องว่างจากการ OCR
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

    # 1. ค้นหาเลขที่หนังสือ "ที่ ..."
    for line in lines[:25]:
        match_no = re.search(r'^(?:ที่|เลขที่)\s*([^\n\r]+)', line)
        if match_no:
            candidate = match_no.group(1).strip()
            # ป้องกันกรณีเป็น "ที่อ้างถึง" หรือ "ที่ประชุม"
            if not any(candidate.startswith(x) for x in ["อ้างถึง", "ประชุม", "ตั้ง", "ทำการ", "ปรึกษา"]):
                # ทำความสะอาดช่องว่างรอบจุดหรือสแลช เช่น 'สวปท . ๑๕ / ๒๕๒๑' -> 'สวปท. ๑๕/๒๕๒๑'
                doc_no = re.sub(r'\s*([./])\s*', r'\1', candidate)
                break

    # 2. ค้นหาวันที่ พ.ศ. (รองรับทั้งแบบมีเว้นวรรคและไม่มีเว้นวรรค)
    date_pattern = rf'([๐-๙0-9]{{1,2}})\s*({THAI_MONTHS_REGEX})\s*(?:พ\.ศ\.\s*)?([๐-๙0-9]{{2,4}})'
    for line in lines[:30]:
        match_date = re.search(date_pattern, line)
        if match_date:
            day = match_date.group(1)
            month = match_date.group(2)
            year = match_date.group(3)
            doc_date = f"{day} {month} {year}"
            break

    # 3. ค้นหาเรื่อง
    for line in lines[:30]:
        match_sub = re.search(r'^เรื่อง\s*([^\n\r]+)', line)
        if match_sub:
            subject = match_sub.group(1).strip()
            # ตัดชื่อไฟล์หลุด
            if any(subject.lower().endswith(ext) for ext in ['.pdf', '.docx', '.png', '.jpg']):
                subject = None
            break

    # หากยังไม่พบเรื่อง ให้สแกนหาข้อความวัตถุประสงค์จากเนื้อหาตอนต้น
    if not subject:
        for line in lines[:35]:
            match_plan = re.search(r'(?:มีแผนดำเนินการ|ประสงค์จะ|เพื่อ)(?:การ)?(จัดการแข่งขัน[^\n\r]{10,80})', line)
            if match_plan:
                subject = "การ" + match_plan.group(1).strip()
                break
            match_req = re.search(r'(ขอความอนุเคราะห์[^\n\r]{10,80})', line)
            if match_req:
                subject = match_req.group(1).strip()
                break

    # 4. ค้นหาเรียน / กราบเรียน
    for line in lines[:30]:
        match_sal = re.search(r'^(?:กราบเรียน|เรียน)\s*([^\n\r]+)', line)
        if match_sal:
            salutation = match_sal.group(1).strip()
            break

    # 5. ค้นหาหน่วยงานผู้ส่ง (รองรับกระทรวง กรม สำนักงาน เทศบาล รวมทั้ง สมาคม มูลนิธิ สโมสร บริษัท)
    dept_keywords = [
        "กระทรวง", "กรม", "สำนักงาน", "มหาวิทยาลัย", "จังหวัด", "เทศบาล",
        "องค์การ", "ฝ่าย", "กอง", "คณะ", "สมาคม", "มูลนิธิ", "สโมสร", "ชมรม", "บริษัท"
    ]
    for line in lines[:20]:
        if line.startswith("ที่") or line.startswith("เรื่อง") or line.startswith("เรียน") or "บันทึกข้อความ" in line:
            continue
        if any(kw in line for kw in dept_keywords):
            if len(line) < 160 and not line.startswith("ตามที่") and not line.startswith("ในวันที่") and not line.startswith("สิ่งที่"):
                # ตัดส่วนที่อยู่ด้านหลัง เช่น ถนน... ตำบล... ออก เพื่อให้ได้ชื่อหน่วยงานชัดเจน
                dept_clean = re.split(r'\s+(?:ถนน|ต\.|ตำบล|อ\.|อำเภอ|จ\.|จังหวัด|\d{5}|เลขที่)', line)[0].strip()
                dept_clean = re.sub(r'[\s๐-๙0-9]+$', '', dept_clean).strip()
                dept = dept_clean if dept_clean else line.strip()
                break

    # 6. ค้นหาอ้างถึง และ สิ่งที่ส่งมาด้วย
    for line in lines[:35]:
        match_ref = re.search(r'^อ้างถึง\s*([^\n\r]+)', line)
        if match_ref:
            ref_val = match_ref.group(1).strip()
            if not any(ref_val.lower().endswith(ext) for ext in ['.pdf', '.docx', '.png', '.jpg']):
                references.append(ref_val)
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


def extract_source_document(file_path: str, api_key: Optional[str] = None, allow_cloud: bool = True) -> SourceDocumentContext:
    """
    ฟังก์ชันหลักสำหรับวิเคราะห์และสกัดข้อมูลจากไฟล์ต้นเรื่องทุกชนิด
    รองรับ Multi-Engine OCR และ Fail-Safe ป้องกันการนำชื่อไฟล์มาใช้เป็นเนื้อหา
    """
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"File not found: {file_path}")

    ext = path.suffix.lower()
    raw_text = ""
    is_scanned = False
    page_count = 1
    preview_path = None
    extraction_failed = False
    extraction_error = None
    ocr_engine_used = None

    if ext == ".pdf":
        raw_text, is_scanned, page_count, preview_path, extraction_failed, extraction_error, ocr_engine_used = extract_text_from_pdf(str(path), api_key=api_key, allow_cloud=allow_cloud)
    elif ext in [".docx", ".doc"]:
        raw_text = extract_text_from_docx(str(path))
        is_scanned = False
        extraction_failed = len(raw_text.strip()) == 0
        if extraction_failed:
            extraction_error = "ไม่สามารถอ่านข้อความจากไฟล์ Word ได้ หรือไฟล์ไม่มีเนื้อความ"
    elif ext in [".png", ".jpg", ".jpeg", ".tiff", ".bmp"]:
        raw_text, preview_path, extraction_failed, extraction_error, ocr_engine_used = extract_text_from_image_file(str(path), api_key=api_key, allow_cloud=allow_cloud)
        is_scanned = True
    elif ext in [".txt", ".md", ".json"]:
        raw_text = path.read_text(encoding="utf-8")
        is_scanned = False
        extraction_failed = len(raw_text.strip()) == 0
        if extraction_failed:
            extraction_error = "ไฟล์ข้อความว่างเปล่า"
    else:
        raise ValueError(f"Unsupported file type: {ext}")

    meta = parse_govdoc_metadata(raw_text) if raw_text else {
        "doc_no": None, "doc_date": None, "subject": None,
        "salutation": None, "dept": None, "references": [], "attachments": []
    }

    # สรุปประเด็นปัญหาและใจความสำคัญ
    lines = [l.strip() for l in raw_text.split("\n") if l.strip()]
    summary_text = " ".join(lines[2:6]) if len(lines) >= 3 else (" ".join(lines) if lines else (extraction_error or "ไม่พบข้อความ"))

    source_case = None
    if not extraction_failed and raw_text.strip():
        try:
            from core.case_dossier import parse_case_dossier
            source_case = parse_case_dossier(raw_text, filename=path.name)
        except Exception:
            source_case = None

    return SourceDocumentContext(
        source_filename=path.name,
        source_dept=meta["dept"] or ("หน่วยงานต้นเรื่อง" if not extraction_failed else None),
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
        requested_action=f"พิจารณาดำเนินการเกี่ยวกับ{meta['subject'] or 'ข้อเสนอในเอกสารต้นเรื่อง'}" if meta["subject"] else None,
        extraction_failed=extraction_failed,
        extraction_error=extraction_error,
        ocr_engine_used=ocr_engine_used,
        source_case=source_case
    )


def extract_from_raw_text(text: str, filename: str = "manual_input.txt") -> SourceDocumentContext:
    """
    สร้าง SourceDocumentContext จากข้อความที่ผู้ใช้กรอกหรือวางเอง (Manual Entry)
    """
    clean_text = clean_thai_intra_word_spaces(text.strip())
    meta = parse_govdoc_metadata(clean_text)
    lines = [l.strip() for l in clean_text.split("\n") if l.strip()]
    summary_text = " ".join(lines[:4]) if lines else "ข้อความต้นเรื่องที่ผู้ใช้ป้อนด้วยตนเอง"

    source_case = None
    if clean_text:
        try:
            from core.case_dossier import parse_case_dossier
            source_case = parse_case_dossier(clean_text, filename=filename)
        except Exception:
            source_case = None

    return SourceDocumentContext(
        source_filename=filename,
        source_dept=meta["dept"] or "หน่วยงานต้นเรื่อง",
        source_doc_no=meta["doc_no"],
        source_date=meta["doc_date"],
        source_subject=meta["subject"],
        source_salutation=meta["salutation"],
        is_scanned=False,
        page_count=1,
        preview_image_path=None,
        raw_text=clean_text,
        summary=summary_text,
        core_issues=lines[:6] if lines else [],
        requested_action=f"พิจารณาดำเนินการเกี่ยวกับ{meta['subject'] or 'ข้อเสนอในเอกสารต้นเรื่อง'}" if meta["subject"] else None,
        extraction_failed=len(clean_text) == 0,
        extraction_error="ข้อความว่างเปล่า" if len(clean_text) == 0 else None,
        ocr_engine_used="Manual Input",
        source_case=source_case
    )
