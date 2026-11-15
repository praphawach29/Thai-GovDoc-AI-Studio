# 🏛️ Thai GovDoc AI Studio (ระบบร่างและผลิตหนังสือราชการไทยอัจฉริยะ)

ระบบผู้ช่วยอัจฉริยะสำหรับงานสารบรรณภาครัฐ: **"แนบไฟล์ต้นเรื่อง -> AI สกัดและร่างหนังสือ -> ผู้ใช้ตรวจ/แก้ไขเคียงข้าง -> ส่งออกเอกสารจริง (PDF / Word)"** ถูกต้องตามระเบียบสำนักนายกรัฐมนตรีว่าด้วยงานสารบรรณ พ.ศ. ๒๕๒๖ และที่แก้ไขเพิ่มเติม ๑๐๐%

---

## 🌟 จุดเด่นของระบบ (Key Highlights)

1. **แนบไฟล์ต้นเรื่องได้หลากหลาย:** รองรับทั้ง PDF ดิจิทัล, เอกสารสแกน, รูปภาพถ่ายเอกสารราชการที่มีรอยประทับ, และไฟล์ Word (`.docx`)
2. **ร่างหนังสือตามระเบียบ 3 ภาคอัตโนมัติ:** แยกภาคเหตุ (ด้วย/ตามที่...นั้น), ภาคข้อเท็จจริง/พิจารณา, และภาคความประสงค์ (จึงเรียนมาเพื่อโปรด...) พร้อมคำขึ้นต้นและคำลงท้ายตามลำดับชั้นยศ
3. **หน้าจอตรวจแก้แบบเคียงข้าง (Side-by-Side Review Workspace):** ดูเอกสารต้นเรื่องฝั่งซ้าย ตรวจและแก้ไขร่างหนังสือฝั่งขวา พร้อม AI Copilot ช่วยเกลาภาษาและย่อความเฉพาะจุด
4. **ส่งออกเอกสารจริง 2 รูปแบบมาตรฐาน:**
   - **Vector PDF (ผ่าน Typst):** จัดหน้า ขอบกระดาษ 3-2-2.5 ซม. ตราครุฑ 3 ซม./1.5 ซม. สวยคมชัดระดับเวกเตอร์ คอมไพล์เร็วในระดับเสี้ยววินาที
   - **Editable Word (`.docx`):** แก้ปัญหาการตัดคำภาษาไทยด้วย Zero-Width Space (`\u200b`) และตั้งค่า Thai Distributed เต็มขอบกระดาษ สระไม่ลอย ฝังฟอนต์ TH Sarabun New (หรือ PSK/IT9) ลงในไฟล์ เปิดเครื่องอื่นแล้วหน้าตาไม่เพี้ยน
5. **ตัวเลือกการส่งออก Word:** เลือก **แม่แบบการจัดหน้า (LayoutProfile)** 3 โปรไฟล์ (มาตรฐาน / หนังสือภายนอก / ฟอร์มราชการ IT9), ฟอนต์ (New/PSK/IT9), ระยะห่างตัวอักษร, ตราครุฑ, เส้นคั่น และการฝังฟอนต์
6. **ระบบทะเบียนคุมสารบรรณ (e-Document Ready):** รองรับระบบออกเลขที่หนังสือราชการอัตโนมัติ ทะเบียนรับ ทะเบียนส่ง และการจองเลขหนังสือ
7. **Safety gates สำหรับงานราชการ:** AI ไม่สร้างเลขที่หนังสือ/วันที่เอง, บล็อก AI ภายนอกเมื่อเอกสารเป็นชั้นความลับ, และ Linter เตือนเลขที่ยังไม่ ออก/อ้างถึงหลายฉบับก่อนส่ง
8. **จำแนกชนิดหนังสืออัตโนมัติ:** ตรวจ 6 ชนิด/แบบ 1–11 พร้อมความมั่นใจและเหตุผล ให้ผู้ใช้ยืนยันก่อนร่าง
9. **เอกสารชนิดพิเศษ 4 ชนิด:** ประทับตรา/สั่งการ/ประชาสัมพันธ์/หลักฐาน พร้อม generator และ Word layout เฉพาะ
10. **หัวข้อเอกสารอิสระ:** เปิดโหมดแก้ไขหัวข้อเพื่อเพิ่ม/ลบ/แก้ไข/สลับลำดับ 12 ส่วน (ส่วนราชการ, ที่/วันที่, เรื่อง, เรียน, อ้างถึง, สิ่งที่ส่งมาด้วย, ต้นเรื่อง, ข้อกฎหมาย, ข้อเท็จจริง, ข้อเสนอแนะ, คำลงท้าย, ลงชื่อ)
11. **เลขที่หนังสือแบบเว้นช่อง + บีบหัวฟอร์ม:** ใช้รูปแบบ `......../2569` ให้เจ้าหน้าที่เขียนเลขเอง และบีบตัวอักษรอัตโนมัติให้ส่วนราชการอยู่บรรทัดเดียว

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
- 🚀 [ONLINE_PRODUCTION_PLAN.md](ONLINE_PRODUCTION_PLAN.md) — **แผนนำระบบขึ้นใช้งานจริงออนไลน์ (Pilot → Production, Security, e-Saraban, Cost)**
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
├── ONLINE_PRODUCTION_PLAN.md # แผนขึ้นใช้งานออนไลน์ (Pilot/Production/Security)
├── README.md               # เอกสารภาพรวม (ไฟล์นี้)
├── DESIGN.md               # สถาปัตยกรรมระบบและ Data Schemas
├── SARABAN_RULES.md        # ระเบียบงานสารบรรณฉบับสรุป
├── PROMPT_ENGINEERING.md   # Prompts & AI Drafting Schemas
├── EXPORT_ENGINE.md        # รายละเอียด Export (Typst + Word)
├── Dockerfile.tesseract    # Docker Container สำหรับ Local Thai OCR
├── ARCHITECTURE.md         # สถาปัตยกรรมเป้าหมาย (Vercel + Supabase) และลำดับงาน
├── requirements.txt        # dependencies ตอนรันเซิร์ฟเวอร์ (สิ่งที่ deploy ขึ้นคลาวด์)
├── requirements-dev.txt    # + uvicorn, Streamlit, OpenCV, pytest สำหรับเครื่องพัฒนา
│
├── server/                 # ชั้นบริการ HTTP (FastAPI) — งานที่แตะไฟล์/ฐานข้อมูล/env อยู่ที่นี่
│   ├── main.py             # ประกอบแอป: CORS, router, เสิร์ฟหน้าเว็บ  (uvicorn server.main:app)
│   ├── settings.py         # ค่าตั้งจากตัวแปรสภาพแวดล้อม (โดเมนที่อนุญาต, โฟลเดอร์อัปโหลด, ขนาดไฟล์)
│   ├── deps.py             # ทะเบียน, การรับไฟล์อัปโหลด, การกรอง path จากผู้เรียก
│   └── routers/            # health, sources, drafting, legal, export, registry, studio
│
├── core/                   # ระบบแกนหลัก (Core Business Logic)
│   ├── models.py           # Data Models (GovDoc, UserProfile, SourceContext, SourceCase)
│   ├── case_dossier.py     # ตัวประมวลผลแฟ้มเรื่องและสายเกษียนสั่งการ (Phase 8)
│   ├── profile_manager.py  # ระบบจัดการโปรไฟล์หน่วยงานของผู้ใช้
│   ├── extractor.py        # Multi-Engine OCR (Gemini + Docker) & Fail-Safe Ingestion
│   ├── ocr_preprocessor.py # ตัวประมวลผลภาพ (Deskew, CLAHE, Binarize)
│   ├── ai_drafter.py       # สมองกลยกร่างหนังสือตามระเบียบ 3 ภาค และบันทึก กทม.
│   ├── linter.py           # Automated Sarabun Linter (ตรวจระเบียบและชื่อไฟล์ดิบ)
│   ├── memo_layout.py      # ตัวจัดหน้าบันทึกข้อความ กทม. (Indentation 2.5/3.5/4.5 ซม.)
│   ├── layout_profile.py     # โปรไฟล์การจัดหน้าต่อแม่แบบ (ขอบ/ฟอนต์/เลขหน้า)
│   ├── hierarchy.py         # สร้างชุดบันทึกตามลำดับชั้น (P3)
│   ├── security.py          # นโยบายบล็อก AI ภายนอกสำหรับข้อมูลชั้นลับ (fail-closed)
│   ├── verification.py     # ตรวจร่างเทียบต้นเรื่อง (พบ/ไม่พบ/ต้องยืนยัน)
│   ├── text_checks.py      # ตรวจคำสะกดและความสอดคล้อง
│   ├── entity_extractor.py  # สกัดชื่อ/หน่วยงาน/วันที่/เลขที่/จำนวนเงิน/กำหนดการ + หลักฐาน
│   ├── intake.py            # ตรวจข้อมูลขาด + สร้างคำถามก่อนร่าง (deterministic)
│   ├── legal_sources.py     # คลังข้อกฎหมาย JSON + สถานะตรวจยืนยัน
│   ├── classifier.py        # จำแนกหนังสือ 6 ชนิด/แบบ 1–11 + การ์ดยืนยัน
│   ├── special_drafter.py   # generator เอกสารชนิดพิเศษ 4 ชนิด
│   ├── sections.py          # หัวข้อเอกสารอิสระ (เพิ่ม/ลบ/สลับ/ซิงก์ฟิลด์)
│   ├── thai_date.py         # วันที่ไทย พ.ศ. (ไม่สร้างเลขที่/วันที่เอง)
│   ├── word_exporter.py    # ตัวสร้างไฟล์ Word (.docx) พร้อมตัดคำ ZWSP ชิดขอบ
│   ├── typst_exporter.py   # ตัวคอมไพล์ PDF เวกเตอร์ด้วย Typst (CLI หรือ Python binding)
│   ├── audit.py            # ประวัติเวอร์ชันและระบบ Diff Engine
│   ├── copilot.py          # AI Copilot ขัดเกลาภาษาเฉพาะจุด
│   ├── registry.py         # ทะเบียนคุมสารบรรณและออกเลขที่หนังสือ
│   └── templates_library.py# คลังแม่แบบมาตรฐานและแม่แบบ กทม.
│
├── data/                   # ฐานข้อมูลและโปรไฟล์ผู้ใช้
│   ├── user_profile.json   # การตั้งค่าหน่วยงานและผู้ลงนาม
│   ├── audit.db            # บันทึกประวัติการแก้ไขและเวอร์ชัน
│   ├── edocument.db        # สมุดทะเบียนรับ-ส่ง และเลขจอง
│   └── legal_references.json # คลังข้อกฎหมาย/ระเบียบที่ผู้ใช้เพิ่มและยืนยันแหล่ง
│
├── templates/              # แม่แบบเอกสาร
│   ├── typst/              # external.typ, internal.typ (Word สร้างจากโค้ดใน core/word_exporter.py + layout_profile.py)
│
├── assets/                 # ทรัพยากรภาพและฟอนต์
│   ├── garuda.svg          # ตราครุฑเวกเตอร์มาตรฐาน
│   └── fonts/              # TH Sarabun New / IT9 / PSK (ครบ 4 น้ำหนัก)
│
├── tests/                  # ชุดทดสอบ 192 รายการ (ข้ามเทสที่ต้องใช้ OCR key/OpenCV/Streamlit ตามสภาพแวดล้อม)
├── web/studio/             # หน้าเว็บหลัก GovDoc Studio (HTML + Tailwind) เสิร์ฟจาก FastAPI
└── legacy/                 # ใช้บนเครื่อง local เท่านั้น ไม่ deploy
    ├── streamlit_app.py    # หน้าจอ Streamlit เดิม (ร่างหนังสือ, สมุดทะเบียน, ตั้งค่าหน่วยงาน)
    └── pdf_exporter.py     # PDF ผ่าน HTML + Edge/Chrome (บนคลาวด์ใช้ Typst)
```

---

## 🚀 แผนการเริ่มต้นและพัฒนาต่อ (Getting Started)

### 1. ความต้องการของระบบ (Prerequisites)
- **Python 3.10+** — บนเครื่องพัฒนาติดตั้งด้วย `python -m pip install -r requirements-dev.txt` (`requirements.txt` เป็นชุดเล็กสำหรับ deploy ไม่มี Streamlit/OpenCV)
- **Typst** — ใช้ได้ทั้ง Typst CLI หรือ Python binding `typst` (ติดตั้งจาก `requirements.txt` และฝัง compiler ไว้ในตัว)
- **ฟอนต์** — โปรเจกต์แนบ **TH Sarabun New, IT9 และ PSK** ครบ 4 น้ำหนัก (Regular/Bold/Italic/BoldItalic) ไว้ใน `assets/fonts` สำหรับเรนเดอร์ PDF (ระเบียบงานสารบรรณอนุญาตให้ใช้ TH Sarabun New หรือ TH Sarabun PSK)
- **Headless browser (เฉพาะ `legacy/pdf_exporter.py`)** — Edge/Chrome หรือ `chrome-headless-shell` (Playwright) ซึ่งแนะนำบนเซิร์ฟเวอร์/คลาวด์ เพราะ Chrome ตัวเต็มอาจค้างเมื่อสร้าง profile ใหม่ในเครื่องที่ไม่มี dbus/อินเทอร์เน็ต; กำหนดเองได้ด้วยตัวแปร `GOVDOC_PDF_BROWSER`
- **Docker (ทางเลือก)** — สำหรับ OCR ออฟไลน์ด้วย image `tha-tesseract:latest` (ดู `Dockerfile.tesseract`)

### 2. ขั้นตอนการทำงานแบบย่อ
1. **แนบไฟล์:** ผู้ใช้อัปโหลดไฟล์ต้นเรื่องผ่านหน้าเว็บ (รองรับ PDF ดิจิทัล, สแกน, รูปภาพ, Word)
2. **AI สกัดและร่าง:** Multi-Engine OCR ถอดข้อความ และ AI แปลงเป็นร่างหนังสือราชการตามระเบียบ
3. **ตรวจทานเคียงข้าง:** ผู้ใช้ตรวจสอบผ่านหน้าจอเทียบต้นฉบับ ปรับแต่งข้อความ และใช้ AI Copilot ช่วยเกลา
4. **ส่งออกจริง:** กดดาวน์โหลดเป็นไฟล์ Vector PDF (Typst) หรือ Editable Word (.docx) พร้อมลงทะเบียนคุมสารบรรณ

### 3. หน้าเว็บ GovDoc Studio (หน้าแรก + หน้าแก้ไขเอกสาร)
หน้าเว็บใหม่ตามดีไซน์ใน `stitch_official_document_generator_homepage_2/` อยู่ที่ `web/studio/` (HTML + Tailwind) เสิร์ฟจาก FastAPI ตัวเดียวกับ API:

```bash
.venv\Scripts\python -m uvicorn server.main:app --port 8600
```

เปิด `http://localhost:8600/` → หน้าแรก (พิมพ์คำสั่ง/แนบไฟล์) → หน้าแก้ไขเอกสาร (`/studio/editor.html`) ร่างที่แก้ไขจะเก็บใน localStorage ของเบราว์เซอร์ (ยังไม่มีฐานข้อมูลกลาง) ส่วนหน้าจอ Streamlit เดิมย้ายไปที่ `legacy/` รันด้วย:

```bash
.venv\Scripts\python -m streamlit run legacy/streamlit_app.py
```

ตัวแปรสภาพแวดล้อมของเซิร์ฟเวอร์ (ไม่ตั้งก็ได้ค่าเริ่มต้น): `GOVDOC_ALLOWED_ORIGINS` (โดเมนที่เรียก API ได้, คั่นด้วยจุลภาค), `GOVDOC_UPLOAD_DIR`, `GOVDOC_REGISTRY_DB`, `GOVDOC_MAX_UPLOAD_MB` (ค่าเริ่มต้น 50)

### 4. โหมด Supabase (ล็อกอิน + เก็บข้อมูลบนเซิร์ฟเวอร์)
ตั้ง 2 ตัวแปรนี้แล้วระบบจะบังคับล็อกอินทุก API และเก็บเอกสาร/ทะเบียน/ไฟล์ต้นเรื่องใน Supabase (ไม่ตั้ง = โหมดเครื่องเดียวแบบเดิม):

| ตัวแปร | ค่า |
|---|---|
| `SUPABASE_URL` | เช่น `https://<project-ref>.supabase.co` |
| `SUPABASE_PUBLISHABLE_KEY` | Publishable key (เดิมชื่อ anon key) จาก Settings → API Keys — เปิดเผยในหน้าเว็บได้ |

ห้ามตั้ง service_role / secret key: เซิร์ฟเวอร์เรียก Supabase ด้วย token ของผู้ใช้ที่ล็อกอิน สิทธิ์จึงถูกคุมด้วย RLS ในฐานข้อมูล
ฐานข้อมูลติดตั้งจาก `supabase/migrations/` ตามลำดับ (ทดสอบบนเครื่องด้วย `bash supabase/tests/run_local.sh`)

### 5. Deploy บน Vercel
1. vercel.com → Add New → Project → Import repo นี้ (Framework Preset: **FastAPI** ตรวจเจอเองจาก `app.py`)
2. Environment Variables (เลือกทั้ง Production และ Preview): `SUPABASE_URL`, `SUPABASE_PUBLISHABLE_KEY`
3. Deploy — ค่าตั้งอยู่ใน `vercel.json` (ภูมิภาค `sin1`, 60 วินาที) และ `.vercelignore`

บน Vercel ถ้าไม่ได้ตั้ง 2 ตัวแปรนี้ API จะปฏิเสธทุกคำขอ (ไม่เปิดใช้แบบไม่มีล็อกอิน)

---

## 🏆 สถานะการพัฒนาและการทดสอบ (Development & Testing Status)

- **สถานะชุดทดสอบ:** **172 tests — ผ่าน 167 / ข้าม 5 / ล้มเหลว 0** (รันล่าสุด ๑๕ พ.ย. ๒๕๖๙)
  - เทส PDF (headless browser) และ OCR จะ **ข้ามอัตโนมัติ** เมื่อเครื่องไม่มี browser/API key/Docker โดยใช้ marker กลางใน `tests/conftest.py` (ไม่ถูกนับเป็น fail)
- **ระยะการพัฒนาที่แล้วเสร็จ:**
  - ✅ **Phase 1:** Core Foundation, ZWSP Word Exporter & Typst Exporter
  - ✅ **Phase 2:** OpenCV Ingestion, Contrast, Deskew, DOCX & PDF Plumber Parser
  - ✅ **Phase 3:** Diff Engine, SQLite Audit Trail & AI Copilot Inline Tools
  - ✅ **Phase 4:** Ekkasarn Alignment, Smart Placeholders `[✏️ ...]` & Memo Review Intent
  - ✅ **Phase 5:** Digital Signature Embedding, 8 Preset Categories & AI Fallback
  - ✅ **Phase 6:** Standard BMA Memo Structure (4 ส่วนตามแบบ กทม.) & Hierarchy Routing
  - ✅ **Phase 7:** Multi-Engine OCR (Docker Tesseract + Gemini Vision), Fail-Safe Ingestion, `RULE_FILENAME_IN_METADATA` & Persistent User Organization Profile
  - ✅ **Phase 8:** Multi-Document Case Dossier Modeling (แฟ้มเรื่อง, สายเกษียนสั่งการ และการสังเคราะห์ย่อหน้า "ต้นเรื่อง")
  - ✅ **Phase 8.1:** Export fidelity — ตัวเลือกฟอนต์/ครุฑ/ระยะตัวอักษร, ฝังฟอนต์ New/IT9 ใน Word, เลขหน้าไทย
- ✅ **Phase 8.2:** LayoutProfile 3 โปรไฟล์, หัวฟอร์มเส้นทึบแบบแบ่งช่วง, ขอบ/ระยะย่อหน้า/เลขหน้าตามแม่แบบ
- ✅ **Phase 8.3:** Hierarchy Chain — สร้างชุด 3 ฉบับตามลำดับชั้น + dropdown เลือกผู้รับภายหลัง
- ✅ **Phase 8.4:** Safety gates — AI ไม่สร้างเลขที่/วันที่, บล็อก AI ภายนอกเมื่อเอกสารชั้นลับ, Linter เลขที่/อ้างถึง
- ✅ **Phase 8.5:** Document Classifier — จำแนกหนังสือ 6 ชนิด/แบบ 1–11 พร้อมการ์ดยืนยันก่อนร่าง
- ✅ **Phase 8.6:** Special document generators — ประทับตรา/สั่งการ/ประชาสัมพันธ์/หลักฐาน พร้อม Word layout และ UI แก้ไข
- ✅ **Phase 8.7:** Flexible Sections — เพิ่ม/ลบ/แก้ไข/สลับหัวข้อเอกสาร 12 ส่วนได้อิสระ
- ✅ **Phase 8.8:** บีบหัวข้อส่วนราชการให้อยู่ในบรรทัดเดียว, เลขที่หนังสือแบบ ......../พ.ศ., และ checkbox แสดง/ซ่อนหัวข้อ
- ✅ **Phase 8.9:** สถานะการแก้ไข (ร่าง/กำลังแก้ไข/บันทึกแล้ว), ปุ่มบันทึกทั้งหมด, Audit Trail และสถานะใน Word properties
- ✅ **Phase 8.10 (Step 0):** Grounding — ไม่แต่งข้อเท็จจริง/ข้อกฎหมาย, บังคับชั้นความลับที่ backend แบบ fail-closed, เลขที่หนังสือ `......../พ.ศ.`
- ✅ **Phase 8.11 (Step 1):** Intake — สกัด entity พร้อมหลักฐาน, ถามข้อมูลที่ขาด, เลือกหัวข้อ กฎหมาย/อ้างถึง/แนบ, คลังข้อกฎหมาย JSON + UI ยืนยันแหล่ง
- ✅ **Phase 8.12 (Step 2):** Source Verification — ตรวจร่างเทียบต้นเรื่อง (ชื่อ/หน่วยงาน/วันที่/เลขที่/จำนวนเงิน/กฎหมาย) พร้อมหลักฐานและสถานะ พบ/ไม่พบ/ต้องยืนยัน
- ✅ **Phase 8.13 (Step 3):** Text Checks — ตรวจคำสะกดและความสอดคล้อง แยก critical/warning/info โดยไม่แก้ข้อความอัตโนมัติ
- *หมายเหตุ:* ชื่อไฟล์เทส `tests/test_phaseN_*.py` เป็นลำดับรอบพัฒนา ไม่ตรงกับเลข Phase ใน roadmap (เช่น `test_phase9`–`test_phase15` คืองานใน Phase 8.1–8.9 ส่วน `test_step0`–`test_step3` คือ Phase 8.10–8.13)
- **แผนงานระยะถัดไป (Roadmap):**
  - 🚩 **Phase 9:** Curated Legal Knowledge Base (คลังข้อกฎหมายและระเบียบมาตรฐาน)
  - 🚩 **Phase 10:** Multi-Document Review, Hierarchical Approval & E-Office Integration

> รายละเอียดเชิงลึก สถาปัตยกรรมระดับโมดูล และข้อมูลการออกแบบทั้งหมด สามารถศึกษาได้ที่ 📑 [DEVELOPMENT_PLAN.md](DEVELOPMENT_PLAN.md)  
> ผลเทียบฟีเจอร์ Ekkasarn AI พร้อมแนวทางนำมาปรับใช้โดยยึดหลักฐานและข้อจำกัดไว้ที่ [EKKASARN_BENCHMARK.md](EKKASARN_BENCHMARK.md)

