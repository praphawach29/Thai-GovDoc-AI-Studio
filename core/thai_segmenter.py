"""
thai_segmenter.py — เครื่องมือตัดคำภาษาไทยและแทรก Zero-Width Space (U+200B)
รองรับทั้ง PyThaiNLP (ถ้ามีติดตั้ง) และ Built-in Dictionary-based Longest Matching
สำหรับใช้งานในเอกสารราชการไทยโดยเฉพาะ
"""

import os
import tempfile
import re
from pathlib import Path
from typing import List

# พจนานุกรมคำภาษาไทยพื้นฐานและคำศัพท์เฉพาะในระเบียบงานสารบรรณ
GOV_THAI_WORDS = {
    # คำทางการและคำสารบรรณ
    "หนังสือ", "ราชการ", "บันทึก", "ข้อความ", "ระเบียบ", "สำนักนายกรัฐมนตรี",
    "งานสารบรรณ", "กระทรวง", "ทบวง", "กรม", "กอง", "ฝ่าย", "กลุ่มงาน", "สำนักงาน",
    "ปลัดกระทรวง", "อธิบดี", "ผู้อำนวยการ", "ผู้ว่าราชการจังหวัด", "นายอำเภอ",
    "ข้าราชการ", "พนักงานราชการ", "เจ้าหน้าที่", "รัฐวิสาหกิจ", "องค์การมหาชน",
    "ด่วนที่สุด", "ด่วนมาก", "ด่วน", "ลับที่สุด", "ลับมาก", "ลับ",
    "เรื่อง", "เรียน", "กราบเรียน", "อ้างถึง", "สิ่งที่ส่งมาด้วย", "เอกสารแนบ",
    "ขอแสดงความนับถือ", "ขอแสดงความนับถืออย่างยิ่ง", "ลงชื่อ", "ตำแหน่ง",
    "โทรศัพท์", "โทรสาร", "ไปรษณีย์อิเล็กทรอนิกส์", "ต่อ", "หมายเลข",
    # ภาคเหตุ / ภาคประสงค์
    "ด้วย", "เนื่องจาก", "ตามที่", "สืบเนื่องจาก", "ความละเอียดแจ้งแล้ว", "นั้น",
    "ในการนี้", "ในการดังกล่าว", "ข้อเท็จจริง", "ข้อพิจารณา", "ข้อกฎหมาย",
    "จึงเรียนมาเพื่อโปรด", "พิจารณา", "อนุมัติ", "อนุเคราะห์", "ทราบ",
    "ดำเนินการ", "ประสานงาน", "ตรวจสอบ", "ให้ความอนุเคราะห์", "เห็นชอบ",
    "เข้าร่วม", "จัดประชุม", "การประชุม", "สัมมนา", "เชิงปฏิบัติการ",
    "โครงการ", "กิจกรรม", "รายงาน", "มติคณะรัฐมนตรี", "งบประมาณ", "จัดซื้อจัดจ้าง",
    # วันเดือนปี
    "มกราคม", "กุมภาพันธ์", "มีนาคม", "เมษายน", "พฤษภาคม", "มิถุนายน",
    "กรกฎาคม", "สิงหาคม", "กันยายน", "ตุลาคม", "พฤศจิกายน", "ธันวาคม",
    "พุทธศักราช", "พ.ศ.", "วัน", "เดือน", "ปี", "เวลา", "นาฬิกา",
    # คำทั่วไป
    "และ", "หรือ", "ของ", "แห่ง", "ใน", "บน", "จาก", "ถึง", "โดย", "เพื่อ",
    "การ", "ความ", "ผู้", "ที่", "ซึ่ง", "อัน", "เป็น", "มี", "ได้", "ให้",
    "ไป", "มา", "อยู่", "จะ", "ต้อง", "ควร", "สามารถ", "พร้อมนี้", "ต่อไป",
    "ดังกล่าว", "ข้างต้น", "นี้", "นั้น", "โน้น", "ทั้งนี้", "อย่างไรก็ตาม",
    "ฉบับ", "ชุด", "ราย", "แห่ง", "คน", "ท่าน", "คณะ", "ทีม", "ส่วน",
    "หนึ่ง", "สอง", "สาม", "สี่", "ห้า", "หก", "เจ็ด", "แปด", "เก้า", "สิบ",
    "ร้อย", "พัน", "หมื่น", "แสน", "ล้าน", "บาท", "สตางค์", "บาทถ้วน"
}

# สระและวรรณยุกต์ภาษาไทยที่ไม่สามารถขึ้นต้นคำเดี่ยวๆ ได้
THAI_LEADING_VOWELS = set("เแโใไ")
THAI_FOLLOWING_CHARS = set("ะัาำิีึืฺุูเแโใไ็่้๊๋์ํ๎")
THAI_VOWELS_TONES = set("ะัาำิีึืฺุู็่้๊๋์ํ๎")


def _is_thai_char(ch: str) -> bool:
    """ตรวจสอบว่าเป็นตัวอักษรไทยหรือไม่ (U+0E00 - U+0E7F)"""
    return '\u0e01' <= ch <= '\u0e5b'


def _configure_pythainlp_data_dir() -> None:
    """
    กำหนดที่เก็บข้อมูล PyThaiNLP ให้อยู่ภายในโปรเจกต์ (data/pythainlp)
    เพื่อไม่ให้พยายามเขียนไปที่ ~/pythainlp-data ซึ่งอาจถูก sandbox/สิทธิ์บล็อก
    """
    if os.environ.get("PYTHAINLP_DATA") or os.environ.get("PYTHAINLP_DATA_DIR"):
        return
    # บนคลาวด์ (Vercel) โฟลเดอร์โปรเจกต์อ่านได้อย่างเดียว จึงถอยไปใช้โฟลเดอร์ชั่วคราว
    # ถ้าสร้างไม่ได้ทั้งคู่ PyThaiNLP จะ import ไม่ผ่านและตกไปใช้ตัวตัดคำสำรองที่แม่นน้อยกว่า
    candidates = (
        Path(__file__).resolve().parent.parent / "data" / "pythainlp",
        Path(tempfile.gettempdir()) / "pythainlp-data",
    )
    for data_dir in candidates:
        try:
            data_dir.mkdir(parents=True, exist_ok=True)
        except OSError:
            continue
        if os.access(data_dir, os.W_OK):
            os.environ["PYTHAINLP_DATA"] = str(data_dir)
            return


def segment_thai_words(text: str) -> List[str]:
    """
    ตัดคำภาษาไทย:
    1. พยายามใช้ PyThaiNLP ถ้ามี
    2. ถ้าไม่มี ให้ใช้ Built-in Longest Matching กับ Government Vocabulary
    """
    if not text:
        return []

    try:
        _configure_pythainlp_data_dir()
        import pythainlp
        return pythainlp.tokenize.word_tokenize(text, engine="newmm")
    except Exception:
        # ไม่มีไลบรารี/ไม่มี corpus/ออฟไลน์ -> ใช้ fallback ด้านล่างเสมอ
        pass

    # Fallback: Rule-based / Longest matching tokenizer
    tokens = []
    i = 0
    n = len(text)

    while i < n:
        # หากไม่ใช่ตัวอักษรไทย เช่น ช่องว่าง, ตัวเลข, สัญลักษณ์, อังกฤษ
        if not _is_thai_char(text[i]):
            # รวบคำที่ไม่ใช่ไทยติดกันไว้ด้วยกัน
            j = i
            while j < n and not _is_thai_char(text[j]):
                j += 1
            tokens.append(text[i:j])
            i = j
            continue

        # หากเป็นตัวอักษรไทย: ค้นหาคำที่ยาวที่สุดในคลังคำศัพท์
        matched_word = None
        max_len = 0

        # ลองค้นหาความยาวตั้งแต่ 25 ตัวอักษรลงมาจนถึง 2 ตัวอักษร
        for length in range(min(25, n - i), 1, -1):
            sub = text[i:i + length]
            if sub in GOV_THAI_WORDS:
                matched_word = sub
                max_len = length
                break

        if matched_word:
            tokens.append(matched_word)
            i += max_len
        else:
            # ตรวจจับพยางค์ภาษาไทยเบื้องต้น
            # รวบพยัญชนะต้น + สระ/วรรณยุกต์ที่ตามมา
            j = i + 1
            while j < n and text[j] in THAI_FOLLOWING_CHARS:
                j += 1
            # ตรวจสอบว่าตัวถัดไปเป็นตัวสะกดหรือไม่
            if j < n and _is_thai_char(text[j]) and text[j] not in THAI_LEADING_VOWELS:
                # อาจเป็นตัวสะกด
                if j + 1 < n and text[j + 1] in THAI_VOWELS_TONES:
                    # ตัวถัดไปมีสระบน/ล่าง แปลว่าเป็นพยัญชนะต้นของคำใหม่
                    pass
                else:
                    j += 1
                    # รวบวรรณยุกต์/การันต์ที่อาจอยู่บนตัวสะกด
                    while j < n and text[j] in THAI_FOLLOWING_CHARS:
                        j += 1

            token = text[i:j]
            tokens.append(token)
            i = j

    return tokens


def insert_zwsp(text: str) -> str:
    """
    แทรก Zero-Width Space (U+200B) ระหว่างคำภาษาไทย
    เพื่อช่วยให้ Microsoft Word ตัดบรรทัดและกระจายข้อความแบบชิดขอบ (Thai Distributed) ได้อย่างถูกต้อง
    """
    if not text:
        return ""

    # แยกบรรทัดออกมาก่อน เพื่อไม่ให้แทรก \u200b ทับ \n
    lines = text.split("\n")
    processed_lines = []

    for line in lines:
        if not line:
            processed_lines.append("")
            continue

        tokens = segment_thai_words(line)
        # เชื่อมคำด้วย Zero-Width Space (\u200b)
        # หากระหว่างคำมีช่องว่างปกติอยู่แล้ว จะไม่แทรก \u200b ซ้ำ
        result = []
        for idx, token in enumerate(tokens):
            result.append(token)
            if idx < len(tokens) - 1:
                next_token = tokens[idx + 1]
                # ไม่แทรก ZWSP หากตัวปัจจุบันลงท้ายด้วยช่องว่าง หรือตัวถัดไปขึ้นต้นด้วยช่องว่าง
                if not token.endswith(" ") and not next_token.startswith(" "):
                    result.append("\u200b")

        processed_lines.append("".join(result))

    return "\n".join(processed_lines)


def to_thai_numerals(text: str) -> str:
    """แปลงตัวเลขอารบิก (0-9) เป็นเลขไทย (๐-๙)"""
    if not text:
        return ""
    mapping = str.maketrans("0123456789", "๐๑๒๓๔๕๖๗๘๙")
    return text.translate(mapping)


def to_arabic_numerals(text: str) -> str:
    """แปลงเลขไทย (๐-๙) เป็นเลขอารบิก (0-9)"""
    if not text:
        return ""
    mapping = str.maketrans("๐๑๒๓๔๕๖๗๘๙", "0123456789")
    return text.translate(mapping)

