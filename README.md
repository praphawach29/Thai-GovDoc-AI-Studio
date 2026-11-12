# 🏛️ Thai GovDoc AI Studio (ระบบร่างและผลิตหนังสือราชการไทยอัจฉริยะ)

ระบบผู้ช่วยอัจฉริยะสำหรับงานสารบรรณภาครัฐ: **"แนบไฟล์ต้นเรื่อง -> AI สกัดและร่างหนังสือ -> ผู้ใช้ตรวจ/แก้ไขเคียงข้าง -> ส่งออกเอกสารจริง (PDF / Word)"** ถูกต้องตามระเบียบสำนักนายกรัฐมนตรีว่าด้วยงานสารบรรณ พ.ศ. ๒๕๒๖ และที่แก้ไขเพิ่มเติม ๑๐๐%

---

## 🌟 จุดเด่นของระบบ (Key Highlights)

1. **แนบไฟล์ต้นเรื่องได้หลากหลาย:** รองรับทั้ง PDF ดิจิทัล, เอกสารสแกน, รูปภาพถ่ายเอกสารราชการที่มีรอยประทับ, และไฟล์ Word (`.docx`)
2. **ร่างหนังสือตามระเบียบ 3 ภาคอัตโนมัติ:** แยกภาคเหตุ (ด้วย/ตามที่...นั้น), ภาคข้อเท็จจริง/พิจารณา, และภาคความประสงค์ (จึงเรียนมาเพื่อโปรด...) พร้อมคำขึ้นต้นและคำลงท้ายตามลำดับชั้นยศ
3. **หน้าจอตรวจแก้แบบเคียงข้าง (Side-by-Side Review Workspace):** ดูเอกสารต้นเรื่องฝั่งซ้าย ตรวจและแก้ไขร่างหนังสือฝั่งขวา พร้อม AI Copilot ช่วยเกลาภาษาและย่อความเฉพาะจุด
4. **ส่งออกเอกสารจริง 2 รูปแบบมาตรฐาน:**
   - **Vector PDF (ผ่าน Typst):** จัดหน้า ขอบกระดาษ 3-2-2.5 ซม. ตราครุฑ 3 ซม./1.5 ซม. สวยคมชัดระดับเวกเตอร์ คอมไพล์เร็วในระดับเสี้ยววินาที
   - **Editable Word (`.docx`):** แก้ปัญหาการตัดคำภาษาไทยด้วย Zero-Width Space (`\u200b`) และตั้งค่า Thai Distributed เต็มขอบกระดาษ สระไม่ลอย ฟอนต์ TH Sarabun New ไม่เด้ง
5. **ระบบทะเบียนคุมสารบรรณ (e-Document Ready):** รองรับระบบออกเลขที่หนังสือราชการอัตโนมัติ ทะเบียนรับ ทะเบียนส่ง และการจองเลขหนังสือ

---

## 📚 อ้างอิงและขับเคลื่อนด้วย 6 Repositories ชั้นนำ

ระบบนี้ได้รับการออกแบบโดยหลอมรวมจุดเด่นจาก 6 คลังความรู้โอเพนซอร์สของไทย:

| Repository | บทบาทในระบบ |
| :--- | :--- |
| [copninixh/TH-National-Document-OCR](https://github.com/copninixh/TH-National-Document-OCR) | โมเดล OCR ที่ Fine-tune ด้วยฟอนต์ TH Sarabun สำหรับอ่านเอกสารสแกนราชการ |
| [Boom-Vitt/claude-thai-skills](https://github.com/Boom-Vitt/claude-thai-skills) | ชุด Prompt Engineering และกฎเกณฑ์ภาษาสำหรับร่างหนังสือราชการ |
| [whs/typst-govdoc](https://github.com/whs/typst-govdoc) | เทมเพลตและระบบเรนเดอร์หนังสือราชการเวกเตอร์คุณภาพสูงด้วย Typst |
| [thaigqsoft/thai-doc-skills](https://github.com/thaigqsoft/thai-doc-skills) | กลไกสร้างไฟล์ Word (`.docx`) ตัดบรรทัดภาษาไทยสวยงามด้วย ZWSP และฝังฟอนต์ |
| [goragodwiriya/edocument](https://github.com/goragodwiriya/edocument) & [eoffice](https://github.com/goragodwiriya/eoffice) | โครงสร้างระบบทะเบียนคุมสารบรรณ การออกเลขหนังสือ และสิทธิ์การใช้งาน |

---

## 📂 เอกสารทางเทคนิคในโฟลเดอร์นี้ (Project Documentation)

เพื่อความเข้าใจเชิงลึก โปรดศึกษาเอกสารข้อกำหนดแต่ละฉบับ:

- 📑 [DEVELOPMENT_PLAN.md](DEVELOPMENT_PLAN.md) — **แผนงานและข้อมูลสถาปัตยกรรมการพัฒนาระบบฉบับสมบูรณ์ (Roadmap Phase 1–10 & Spec)**
- 📖 [AGENTS.md](AGENTS.md) — กฎเหล็กและข้อแนะนำการทำงานสำหรับ AI Coding Agents
- 🏗️ [DESIGN.md](DESIGN.md) — รายละเอียดสถาปัตยกรรมระบบ โครงสร้างโมดูล และ Data Schema (Pydantic)
- ⚖️ [SARABAN_RULES.md](SARABAN_RULES.md) — สรุประเบียบงานสารบรรณ ตารางเทียบคำขึ้นต้น-ลงท้าย และขนาดตราครุฑ
- 🤖 [PROMPT_ENGINEERING.md](PROMPT_ENGINEERING.md) — System Prompts, Few-shot Examples, และคำสั่ง AI Copilot
- 🖨️ [EXPORT_ENGINE.md](EXPORT_ENGINE.md) — กลไกการเรนเดอร์ PDF ด้วย Typst และการแก้ปัญหาตัดคำใน DOCX

---

## 🛠️ โครงสร้างโฟลเดอร์ของระบบ (Directory Layout)

```text
หนังสือราชการ/
├── DEVELOPMENT_PLAN.md     # แผนงานและสเปกระบบฉบับเต็ม (Roadmap & Architecture)
├── README.md               # เอกสารภาพรวม (ไฟล์นี้)
├── DESIGN.md               # สถาปัตยกรรมระบบและ Data Schemas
├── SARABAN_RULES.md        # ระเบียบงานสารบรรณฉบับสรุป
├── PROMPT_ENGINEERING.md   # Prompts & AI Drafting Schemas
├── EXPORT_ENGINE.md        # รายละเอียด Export (Typst + Word)
├── Dockerfile.tesseract    # Docker Container สำหรับ Local Thai OCR
│
├── core/                   # ระบบแกนหลัก (Core Business Logic)
│   ├── models.py           # Data Models (GovDoc, UserProfile, SourceContext)
│   ├── profile_manager.py  # ระบบจัดการโปรไฟล์หน่วยงานของผู้ใช้
│   ├── extractor.py        # Multi-Engine OCR (Gemini + Docker) & Fail-Safe Ingestion
│   ├── ocr_preprocessor.py # ตัวประมวลผลภาพ (Deskew, CLAHE, Binarize)
│   ├── ai_drafter.py       # สมองกลยกร่างหนังสือตามระเบียบ 3 ภาค และบันทึก กทม.
│   ├── linter.py           # Automated Sarabun Linter (ตรวจระเบียบและชื่อไฟล์ดิบ)
│   ├── memo_layout.py      # ตัวจัดหน้าบันทึกข้อความ กทม. (Indentation 2.5/3.5/4.5 ซม.)
│   ├── word_exporter.py    # ตัวสร้างไฟล์ Word (.docx) พร้อมตัดคำ ZWSP ชิดขอบ
│   ├── typst_exporter.py   # ตัวคอมไพล์ PDF เวกเตอร์ด้วย Typst
│   ├── audit.py            # ประวัติเวอร์ชันและระบบ Diff Engine
│   ├── copilot.py          # AI Copilot ขัดเกลาภาษาเฉพาะจุด
│   ├── registry.py         # ทะเบียนคุมสารบรรณและออกเลขที่หนังสือ
│   └── templates_library.py# คลังแม่แบบมาตรฐานและแม่แบบ กทม.
│
├── data/                   # ฐานข้อมูลและโปรไฟล์ผู้ใช้
│   ├── user_profile.json   # การตั้งค่าหน่วยงานและผู้ลงนาม
│   ├── audit.db            # บันทึกประวัติการแก้ไขและเวอร์ชัน
│   └── edocument.db        # สมุดทะเบียนรับ-ส่ง และเลขจอง
│
├── templates/              # แม่แบบเอกสาร
│   ├── typst/              # external.typ, internal.typ
│   └── docx/               # default_template.docx
│
├── assets/                 # ทรัพยากรภาพและฟอนต์
│   ├── garuda.svg          # ตราครุฑเวกเตอร์มาตรฐาน
│   └── fonts/              # ฟอนต์ TH Sarabun New
│
├── tests/                  # ชุดทดสอบอัตโนมัติ (84 Passed, 100%)
└── web/                    # เว็บแอปพลิเคชัน (Streamlit UI Workspace)
    └── app.py              # หน้าจอหลัก 3 แท็บ (ร่างหนังสือ, สมุดทะเบียน, ตั้งค่าหน่วยงาน)
```

---

## 🚀 แผนการเริ่มต้นและพัฒนาต่อ (Getting Started)

### 1. ความต้องการของระบบ (Prerequisites)
- **Python 3.10+** (ติดตั้งแพ็กเกจ `fastapi`, `uvicorn`, `python-docx`, `pdfplumber`, `streamlit`, `pythainlp`)
- **Typst CLI** (สำหรับส่งออก PDF คุณภาพสูง: ดาวน์โหลดจาก [github.com/typst/typst](https://github.com/typst/typst))
- **ฟอนต์ TH Sarabun New** (ติดตั้งในเครื่อง หรือวางในโฟลเดอร์ `assets/fonts`)

### 2. ขั้นตอนการทำงานแบบย่อ
1. **แนบไฟล์:** ผู้ใช้อัปโหลดไฟล์ต้นเรื่องผ่านหน้าเว็บ (รองรับ PDF ดิจิทัล, สแกน, รูปภาพ, Word)
2. **AI สกัดและร่าง:** Multi-Engine OCR ถอดข้อความ และ AI แปลงเป็นร่างหนังสือราชการตามระเบียบ
3. **ตรวจทานเคียงข้าง:** ผู้ใช้ตรวจสอบผ่านหน้าจอเทียบต้นฉบับ ปรับแต่งข้อความ และใช้ AI Copilot ช่วยเกลา
4. **ส่งออกจริง:** กดดาวน์โหลดเป็นไฟล์ Vector PDF (Typst) หรือ Editable Word (.docx) พร้อมลงทะเบียนคุมสารบรรณ

---

## 🏆 สถานะการพัฒนาและการทดสอบ (Development & Testing Status)

- **สถานะชุดทดสอบ:** ผ่านการทดสอบทั้งหมด **84/84 Tests (100% Pass)**
- **ระยะการพัฒนาที่แล้วเสร็จ:**
  - ✅ **Phase 1:** Core Foundation, ZWSP Word Exporter & Typst Exporter
  - ✅ **Phase 2:** OpenCV Ingestion, Contrast, Deskew, DOCX & PDF Plumber Parser
  - ✅ **Phase 3:** Diff Engine, SQLite Audit Trail & AI Copilot Inline Tools
  - ✅ **Phase 4:** Ekkasarn Alignment, Smart Placeholders `[✏️ ...]` & Memo Review Intent
  - ✅ **Phase 5:** Digital Signature Embedding, 8 Preset Categories & AI Fallback
  - ✅ **Phase 6:** Standard BMA Memo Structure (4 ส่วนตามแบบ กทม.) & Hierarchy Routing
  - ✅ **Phase 7:** Multi-Engine OCR (Docker Tesseract + Gemini Vision), Fail-Safe Ingestion, `RULE_FILENAME_IN_METADATA` & Persistent User Organization Profile
- **แผนงานระยะถัดไป (Roadmap):**
  - 🚩 **Phase 8:** Multi-Document Case Dossier Modeling (แฟ้มเรื่องและสายการสั่งการ)
  - 🚩 **Phase 9:** Curated Legal Knowledge Base (คลังข้อกฎหมายและระเบียบมาตรฐาน)
  - 🚩 **Phase 10:** Hierarchical Approval Workflow & E-Office Integration

> รายละเอียดเชิงลึก สถาปัตยกรรมระดับโมดูล และข้อมูลการออกแบบทั้งหมด สามารถศึกษาได้ที่ 📑 [DEVELOPMENT_PLAN.md](DEVELOPMENT_PLAN.md)

