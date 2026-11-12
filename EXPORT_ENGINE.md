# EXPORT_ENGINE.md — สถาปัตยกรรมการเรนเดอร์เอกสาร (Typst PDF & Word DOCX)

เอกสารนี้อธิบายกลไกเชิงลึกของการส่งออกหนังสือราชการให้ได้คุณภาพตามระเบียบงานสารบรรณ ๑๐๐% โดยผสมผสานจุดแข็งจาก ๒ โปรเจกต์สำคัญ:
1. **`whs/typst-govdoc`:** การเรนเดอร์ PDF เวกเตอร์คุณภาพสูงสุดด้วย Typst
2. **`thaigqsoft/thai-doc-skills`:** การสร้างไฟล์ Microsoft Word (`.docx`) ที่แก้ปัญหาการตัดบรรทัดและฟอนต์เพี้ยน

---

## 1. Pipeline A: การสร้าง PDF เวกเตอร์ด้วย Typst

### 1.1 ทำไมต้องเป็น Typst?
ในอดีต การสร้าง PDF สารบรรณมักใช้ LaTeX (ซึ่งจัดการภาษาไทยและฟอนต์ยาก) หรือ LibreOffice headless (ซึ่งทำงานช้า เปลือง RAM สูง และมักมีปัญหาฟอนต์เพี้ยนบน Server) 
**Typst** เป็นระบบ Typesetting ยุคใหม่ที่เขียนด้วยภาษา Rust:
- คอมไพล์เร็วมาก (ระดับ 30-100 มิลลิวินาทีต่อหน้า)
- รองรับไฟล์เวกเตอร์ SVG (ตราครุฑ) อย่างสมบูรณ์
- สามารถกำหนดระยะขอบและตำแหน่งอ็อบเจกต์ระดับมิลลิเมตร (เช่น ตราครุฑสูง 3.0 ซม., ระยะย่อหน้า 2.5 ซม.) ได้อย่างแม่นยำ

### 1.2 โครงสร้างเทมเพลต Typst สำหรับหนังสือภายนอก (`templates/typst/external.typ`)
```typst
#set page(
  paper: "a4",
  margin: (top: 2.5cm, bottom: 2.0cm, left: 3.0cm, right: 2.0cm),
  header: locate(loc => {
    // แสดงชั้นความลับกึ่งกลางหัวกระดาษ (ถ้ามี)
    if secret != "normal" {
      align(center)[#text(size: 16pt, weight: "bold", fill: red)[#secret_text]]
    }
  })
)

#set text(
  font: "TH Sarabun New",
  size: 16pt,
  lang: "th"
)

#set par(
  leading: 0.65em,
  first-line-indent: 2.5cm,
  justify: true
)

// แสดงชั้นความเร็ว (ถ้ามี)
#if urgency != "normal" [
  #place(top + left, dx: 0cm, dy: -0.5cm)[
    #text(size: 16pt, weight: "bold", fill: red)[#urgency_text]
  ]
]

// ตราครุฑ 3 ซม. กึ่งกลางหน้า
#align(center)[
  #image("../../assets/garuda.svg", height: 3.0cm)
]

#v(0.5cm)

// ส่วนหัวหนังสือ: เลขที่ และ ส่วนราชการ
#grid(
  columns: (1fr, 1fr),
  align: (left, left),
  [ที่ #doc_number],
  [#dept_name]
)

#v(0.3cm)

// วันที่ (เยื้องจากกึ่งกลางหน้าไปทางขวา)
#align(center)[
  #h(4.0cm) #doc_date
]

#v(0.3cm)

// เรื่อง, เรียน, อ้างถึง, สิ่งที่ส่งมาด้วย
#block[
  #text(weight: "bold")[เรื่อง] #h(0.5cm) #subject \
  #text(weight: "bold")[เรียน] #h(0.5cm) #salutation \
  #if references != none [
    #text(weight: "bold")[อ้างถึง] #h(0.3cm) #references.join("\n" + h(1.5cm)) \
  ]
  #if attachments != none [
    #text(weight: "bold")[สิ่งที่ส่งมาด้วย] #h(0.2cm) #attachments.join("\n" + h(2.8cm)) \
  ]
]

#v(0.5cm)

// เนื้อหา 3 ย่อหน้า
#par[#paragraph_reason]

#if paragraph_details != none [
  #par[#paragraph_details]
]

#par[#paragraph_purpose]

#v(1.0cm)

// คำลงท้าย และ ลายมือชื่อ
#align(center)[
  #h(4.0cm) #closing \
  #v(1.5cm)
  #h(4.0cm) #signatory_name \
  #h(4.0cm) #signatory_position
]

#v(1.0cm)

// ส่วนราชการเจ้าของเรื่อง (ชิดมุมล่างซ้าย)
#align(left)[
  #text(size: 14pt)[
    #contact_dept \
    โทรศัพท์ #contact_tel \
    #if contact_email != none [อีเมล #contact_email]
  ]
]
```

### 1.3 การคอมไพล์ Typst ผ่าน Python
```python
import subprocess
from pathlib import Path

def compile_typst_to_pdf(typ_path: Path, output_pdf_path: Path) -> bool:
    """คอมไพล์ไฟล์ .typ เป็น PDF ผ่าน Typst CLI"""
    cmd = [
        "typst", "compile",
        str(typ_path),
        str(output_pdf_path),
        "--font-path", "assets/fonts"
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"Typst compilation failed: {result.stderr}")
    return True
```

---

## 2. Pipeline B: การสร้าง Word (`.docx`) ด้วย Python

### 2.1 ปัญหาการจัดหน้าภาษาไทยใน Microsoft Word
เมื่อสร้างไฟล์ `.docx` ผ่านโปรแกรม เช่น `python-docx`:
1. **Word ไม่รู้ตำแหน่งตัดคำ:** ภาษาไทยไม่มีการเว้นวรรคระหว่างคำ ทำให้เมื่อข้อความขึ้นบรรทัดใหม่ Word มักจะตัดคำผิดตำแหน่ง เช่น ตัดคำว่า "ประ- / ชุม" หรือ "โครง- / การ"
2. **การจัดขอบกระดาษเป็นช่องว่างโบ๋:** เมื่อเลือก Paragraph Alignment เป็น `JUSTIFY` หรือ `THAI_DISTRIBUTE` หากไม่มีการตัดคำที่ถูกต้อง Word จะถ่างช่องว่างระหว่างคำจนตัวอักษรห่างผิดปกติ
3. **ฟอนต์เด้ง (Font Fallback):** หากไม่ได้ตั้งค่า XML สำหรับตัวอักษรแบบ Complex Script (`w:cs`) เมื่อเปิดไฟล์ Word จะแสดงผลด้วย Angsana New หรือ Calibri แทน TH Sarabun New

### 2.2 วิธีแก้ปัญหาแบบ `thaigqsoft/thai-doc-skills` (ZWSP & OpenXML)

#### ก. การแทรก Zero-Width Space (U+200B)
นำข้อความภาษาไทยมาตัดคำ (Word Segmentation) ด้วยอัลกอริทึม dictionary-based (เช่น PyThaiNLP หรือพจนานุกรมสารบรรณ) แล้วเชื่อมรอยต่อของคำด้วยอักขระ `\u200b` (Zero-Width Space):
```python
import re

def insert_zwsp_thai(text: str) -> str:
    """แทรก Zero-Width Space เพื่อให้ Microsoft Word ตัดบรรทัดได้อย่างถูกต้อง"""
    try:
        import pythainlp
        # ตัดคำภาษาไทย
        words = pythainlp.tokenize.word_tokenize(text, engine="newmm")
        # เชื่อมคำด้วย \u200b
        return "\u200b".join(words)
    except ImportError:
        # Fallback กรณีไม่มี pythainlp: ใช้ Regex พื้นฐาน
        return text
```

#### ข. การตั้งค่า XML เพื่อบังคับใช้ Thai Distributed และ Font TH Sarabun New
ใช้ `python-docx` ปรับแต่ง OpenXML elements โดยตรง:
```python
from docx import Document
from docx.shared import Cm, Pt
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.enum.text import WD_ALIGN_PARAGRAPH

def set_thai_font_and_justify(paragraph, font_name="TH Sarabun New", size_pt=16):
    """ปรับแต่ง Paragraph ให้ตัดคำสวยงามและฟอนต์ไม่เด้ง"""
    # 1. กำหนดการจัดแนวเป็น Thai Distributed
    pPr = paragraph._p.get_or_add_pPr()
    jc = OxmlElement('w:jc')
    jc.set(qn('w:val'), 'thaiDistribute')
    pPr.append(jc)
    
    # 2. ปรับแต่งทุก Run ใน Paragraph ให้ใช้ Complex Script Font
    for run in paragraph.runs:
        run.font.name = font_name
        run.font.size = Pt(size_pt)
        rPr = run._r.get_or_add_rPr()
        
        # กำหนด w:rFonts ทั้งสำหรับภาษาไทยและภาษาอังกฤษ
        rFonts = OxmlElement('w:rFonts')
        rFonts.set(qn('w:ascii'), font_name)
        rFonts.set(qn('w:hAnsi'), font_name)
        rFonts.set(qn('w:cs'), font_name)
        rPr.append(rFonts)

def setup_govdoc_margins(doc: Document):
    """กำหนดขอบกระดาษตามระเบียบงานสารบรรณ (ซ้าย 3cm, ขวา 2cm, บน 2.5cm, ล่าง 2cm)"""
    sections = doc.sections
    for section in sections:
        section.top_margin = Cm(2.5)
        section.bottom_margin = Cm(2.0)
        section.left_margin = Cm(3.0)
        section.right_margin = Cm(2.0)
```

---

### 2.3 ตัวเลือกการส่งออก Word และการฝังฟอนต์ (Sprint 1)

`export_govdoc_to_docx(data, path, options=ExportOptions(...))` รองรับตัวเลือกต่อไปนี้:

| ตัวเลือก | ค่าเริ่มต้น | ผลในไฟล์ DOCX |
|---|---|---|
| `export_font` | `"sarabun_new"` | ใช้ TH Sarabun New (หรือ `"psk"` / `"it9"`) |
| `letter_spacing_pt` | `0.4` | `<w:spacing w:val="8"/>` ใน style Normal (8 twips = 0.4 pt) |
| `letterhead` | `"garuda"` | แสดง/ซ่อนตราครุฑ (บันทึกข้อความ 1.5 ซม., ภายนอก 3 ซม.) |
| `divider` | `"none"` | `"line"` เพิ่มเส้นคั่นใต้ส่วนหัว (`w:pBdr`) |
| `embed_fonts` | `True` | ฝังฟอนต์ TrueType เป็น `word/fonts/*.odttf` |
| `is_private` | `False` | ทำเครื่องหมายเอกสารส่วนตัวสำหรับ flow ภายนอก |

การฝังฟอนต์ทำใน `core/docx_fonts.py` หลัง `doc.save()`:

1. เพิ่ม `<w:embedRegular>` / `<w:embedBold>` ใน `word/fontTable.xml` พร้อม `fontKey` (GUID)
2. Obfuscate ไฟล์ฟอนต์ 32 ไบต์แรกด้วย GUID ตามสเปก OOXML แล้วเก็บเป็น `font1.odttf`, `font2.odttf`
3. เพิ่ม relationship ใน `word/_rels/fontTable.xml.rels`
4. ประกาศ `Default Extension="odttf"` ใน `[Content_Types].xml`
5. เปิด `<w:embedTrueTypeFonts/>` และ `<w:saveSubsetFonts/>` ใน `word/settings.xml`

ผลลัพธ์: เปิดไฟล์บนเครื่องที่ไม่มีฟอนต์ TH Sarabun ก็ยังเห็นหน้าตาเดิม และขอบบนของบันทึกข้อความใช้ 1.5 ซม. พร้อมเลขหน้าไทย (`w:pgNumType w:fmt="thaiNumbers"`)

---

## 3. สรุปเปรียบเทียบการเลือกใช้ (When to use which?)

| ปัจจัย | Typst Engine (PDF) | Word Engine (DOCX) |
| :--- | :--- | :--- |
| **ผลลัพธ์** | เอกสาร PDF เวกเตอร์ 100% | ไฟล์ `.docx` สำหรับแก้ไขต่อ |
| **ความแม่นยำของระยะ** | แม่นยำระดับมิลลิเมตร (ตราครุฑ 3 ซม. ขอบ 3-2-2.5 ซม.) | ขึ้นอยู่กับโปรแกรมและเวอร์ชัน Word ของผู้เปิด |
| **ความเร็วในการสร้าง** | สูงมาก (< 100 ms) | ปานกลาง (~ 200-500 ms) |
| **เหมาะสำหรับ** | • พิมพ์ออกกระดาษเพื่อเสนอเซ็น<br/>• ส่งออกเพื่อลงนาม E-Signature ดิจิทัล<br/>• การแนบไฟล์เข้าสู่ระบบ e-Document ทันที | • ให้เจ้าหน้าที่นำไปเพิ่มเติมเนื้อหาใน MS Word<br/>• หน่วยงานที่ต้องการแม่แบบ `.docx` ไปใช้งานต่อ |

