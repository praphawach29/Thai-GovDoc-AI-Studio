---
name: thai-govdoc-ai-drafting
description: ระบบร่างหนังสือราชการไทยด้วย AI ของ Thai GovDoc AI Studio ตั้งแต่แนบไฟล์ต้นเรื่อง → AI อ่าน (OCR) → ร่างบันทึกข้อความ/หนังสือภายนอก → แก้บนกระดาษ A4 → เสนอตามสายบังคับบัญชา → ส่งออก Word/PDF → อัปโหลดฉบับจริงกลับ ใช้เมื่อแก้หรือต่อยอดส่วนใดของ pipeline นี้ ตรวจไฟล์ Word/PDF ที่ผู้ใช้ส่งมา ไล่ปัญหา AI ร่างผิด หรือ deploy ขึ้น Vercel + Supabase
---

# Thai GovDoc AI Drafting — ระบบร่างหนังสือราชการด้วย AI

skill นี้สรุปสิ่งที่ระบบทำได้จริงและ "บทเรียนที่ได้จากการใช้งานจริง" ของกลุ่มงานส่งเสริมกีฬา กองการกีฬา
สำนักวัฒนธรรม กีฬา และการท่องเที่ยว กรุงเทพมหานคร ใช้คู่กับ `AGENTS.md` (กฎเหล็ก) — ถ้าขัดกัน `AGENTS.md` ชนะ

## 1. ใช้ skill นี้เมื่อไหร่

- แก้/เพิ่มขั้นใด ๆ ใน pipeline: อ่านไฟล์, เลือกประเภทหนังสือ, AI ร่าง, หน่วยออกหนังสือ, แก้ไข, ส่งออก, ฉบับจริง
- ผู้ใช้ส่งไฟล์ `.docx` / ภาพหน้าจอมาให้ "ช่วยเช็ค" (ดูหัวข้อ 8)
- AI ร่างผิดประเภท ผิดข้อเท็จจริง ช้า หรือ error
- ปรับรูปแบบหน้ากระดาษให้ตรงแบบฟอร์มจริงของหน่วยงาน (Word, PDF, หน้าแก้ไข ต้องตรงกันทั้ง 3 ช่องทาง)
- deploy / ตรวจ production

ไม่ใช้แทน: `skills/thai-govdoc-ux-frontend` (งานออกแบบ UX), `SARABAN_RULES.md` (ระเบียบงานสารบรรณ)

## 2. แผนที่โค้ด

| ขั้น | ไฟล์หลัก | หน้าที่ |
|---|---|---|
| อัปโหลด | `server/routers/sources.py`, `server/supabase.py` | signed upload URL ตรงไป Supabase Storage bucket `sources` |
| อ่านไฟล์ | `core/extractor.py`, `core/llm_drafter.ocr_images_with_llm` | ข้อความฝังใน PDF ก่อน ไม่มีค่อย OCR ด้วย AI (ภาพ JPEG) แล้วจึง OCR เครื่อง |
| สกัดหัวหนังสือ | `core/extractor.parse_govdoc_metadata` | เลขที่ วันที่ เรื่อง เรียน ผู้ส่ง (สำรองเมื่อ AI ไม่ตอบ) |
| เลือกประเภท | `core/studio.choose_output_type` | ผู้ใช้เลือก > คำในคำสั่ง > มีไฟล์ต้นเรื่อง = บันทึกข้อความ > classifier |
| AI ร่าง | `core/llm_drafter.py` (`draft_content_with_llm`, `apply_draft_content`, `SYSTEM_PROMPT`) | Gemini ก่อน สำรองด้วย Claude, JSON schema `DraftContent` |
| โครงหนังสือ | `core/ai_drafter.py`, `core/studio.start_draft` | หัวหนังสือ placeholder `[✏️ ระบุ...]` และประกอบผล AI |
| หน่วยออกหนังสือ | `core/issuing_units.py`, `core/models.default_issuing_units` | ๓ ระดับ: กลุ่มงาน → กอง → สำนัก (เลขที่ ผู้รับ ผู้ลงนาม ประโยคท้าย) |
| จัดย่อหน้าบันทึก | `core/memo_layout.py` | หัวข้อ ระยะ 6 pt ระดับย่อหน้า (แท็บ = ระดับที่ผู้ใช้กำหนด) |
| Word | `core/word_exporter.py`, `core/layout_profile.py`, `core/docx_fonts.py` | ZWSP, thaiDistribute, เส้นประหัวฟอร์มแบบรูปร่างเส้น |
| PDF | `core/typst_exporter.py`, `templates/typst/internal.typ`, `external.typ` | Typst + ฟอนต์ที่เลือกเท่านั้น |
| ชุดเสนอ PDF | `server/routers/export.py` (`/export/pdf-bundle`) | รวมทุกขั้น ขั้นสูงสุดอยู่หน้าแรก |
| ฉบับจริง | `core/final_file.py`, `server/routers/finals.py` | อัปโหลด Word/PDF ที่แก้เสร็จกลับเข้าระบบ (sha256, append-only) |
| หน้าเว็บ | `web/studio/index.html`/`home.js` (หน้าแรก), `editor.html`/`editor.js`/`studio.css` (หน้าแก้ไข) | |
| ฐานข้อมูล | `supabase/migrations/2026111*` (7 ไฟล์) | RLS ตาม org, RPC security definer, audit |

## 3. กฎรูปแบบที่ตกลงกับผู้ใช้แล้ว (ห้ามเปลี่ยนโดยไม่ถาม)

**บันทึกข้อความแบบกรุงเทพมหานคร (ค่าเริ่มต้น)**
- ขอบ บน 1.5 / ล่าง 2 / ซ้าย 3 / ขวา 2 ซม. — หน้าแก้ไขก็ต้อง 1.5 ซม. (`.a4-sheet[data-type="internal"]`)
- ครุฑ `assets/garuda_krut.png` (ครุฑทึบจากไฟล์ต้นแบบของหน่วยงาน) สูง 1.5 ซม. ลอยชิดซ้าย; "บันทึกข้อความ" 32 pt กึ่งกลางความกว้างข้อความ (ห้ามใช้ตาราง 2 ช่อง — หัวเรื่องจะเยื้องขวา)
- ฟอนต์ TH SarabunIT๙ 16 pt (เลือก PSK/New รายฉบับได้) — ไฟล์ IT๙ ชื่อภายใน "TH SarabunPSK" ต้องส่งเฉพาะไฟล์ฟอนต์ที่เลือกให้ Typst
- ส่วนราชการบรรทัดเดียวเสมอ (บีบแนวนอนถ้ายาว)
- **เส้นประหัวฟอร์ม (Word):** เป็นรูปร่างเส้นตรง VML ล็อกกับบรรทัด อยู่หลังข้อความ (`_add_fixed_dotted_line`) — ส่วนราชการ, ที่ (ถึงก่อน "วันที่" ที่ 7.5 ซม.), วันที่, บรรทัดแรกของเรื่อง; บรรทัดที่ ๒ ของเรื่องไม่มีเส้น
  - ลองมาแล้วไม่ผ่าน: ขีดเส้นใต้ข้อความ (ย้ายคำแล้วเส้นหาย), เส้นขอบย่อหน้าแบบเยื้องลอย (Word ลากเส้นใต้คำว่า "เรื่อง" ด้วย), ตาราง 2 ช่อง (แก้ใน Word ไม่เป็นธรรมชาติ)
  - ผู้ใช้ทำแบบนี้ใน Word จริง: "แทรกรูปร่างเส้นตรงแล้วพิมพ์ข้อความบนเส้น"
- หน้าแก้ไข: `.first-line-fill` เส้นประเฉพาะบรรทัดแรกของเรื่อง; PDF: `_field_first_line` ใน `internal.typ`
- ระยะ: "เรียน" 6 pt, ทุกหัวข้อรวมต้นเรื่อง 6 pt, ภาคความประสงค์ 6 pt, ย่อหน้าในหัวข้อเดียวกัน 0 pt
- หัวข้อ (ต้นเรื่อง/ข้อกฎหมาย/ข้อเท็จจริง/ข้อพิจารณาและเสนอแนะ) บรรทัดเดี่ยว เริ่ม 2.5 ซม. ขีดเส้นใต้; เปลี่ยนชื่อได้ `memo_headings` (ว่าง = ไม่แสดง)
- ทุกบรรทัดคือย่อหน้า: ข้อ ๑. 2.5 ซม., ๑.๑ 3.5 ซม., ๑.๑.๑ 4.5 ซม.; แท็บนำหน้า N ตัว = ระดับ N (Tab/Shift+Tab ในหน้าแก้ไข)
- ผู้ลงนามบันทึก: กึ่งกลางในช่วง 6 ซม. ถึงขอบขวา (Word = PDF)

**การวัดความกว้างใน Word ต้องรวมระยะห่างตัวอักษร 0.4 pt ทุกตัวอักษร (รวม ZWSP)** — `_LETTER_SPACING` ไม่งั้นบรรทัดยาวกว่าที่คำนวณ ~1 ซม.
**ไฟล์ Word ต้องไม่มี `docProps/thumbnail.jpeg`** (ภาพว่างจากแม่แบบ python-docx ทำให้ Explorer แสดงหน้าเปล่าแทนไอคอน Word)

## 4. สายเสนอ ๓ ระดับ (BMA sports)

| หน่วย | เลขที่ | เรียน | ผู้ลงนาม |
|---|---|---|---|
| กลุ่มงานส่งเสริมกีฬา | `___/2569` | หัวหน้ากลุ่มงานส่งเสริมกีฬา | ผู้เสนอ (ผู้ใช้) + หัวหน้ากลุ่มงาน |
| กองการกีฬา | `กท 1205/___` | ผู้อำนวยการสำนักฯ | ผู้อำนวยการกอง |
| สำนักวัฒนธรรม กีฬา และการท่องเที่ยว | `กท 1205/___` | ปลัดกรุงเทพมหานคร | ผู้อำนวยการสำนัก |

- ปุ่ม "เสนอขั้นถัดไป" สร้างฉบับขั้นบนจากฉบับปัจจุบัน; "ชุดเสนอ PDF" รวมทุกขั้น ขั้นสูงสุดหน้าแรก
- ข้อมูลหน่วยอยู่ตาราง `org_units` (seed `supabase/seed/bootstrap_bma_sports.sql`) — ชื่อผู้ลงนามที่ยังไม่รู้ใช้ `([✏️ ระบุชื่อผู้ลงนาม])`

## 5. AI: ผู้ให้บริการ เวลา และ prompt

- ลำดับ `GOVDOC_AI_ORDER` (ค่าเริ่มต้น `gemini,claude`) — **ตัวที่อ่านไฟล์ได้ ร่างต่อจนจบ** ตัวที่ล้มเหลวย้ายไปท้าย (ประหยัดค่าใช้จ่าย)
- โมเดล: `gemini-3.8-flash` (thinking LOW, ถ้าถูกปฏิเสธลองใหม่โดยไม่ตั้ง), `claude-opus-5-5` effort medium (server-side fallback beta; ถูกปฏิเสธลองใหม่โดยไม่ใส่)
- เวลา: request 105 วิ (Vercel maxDuration 120), OCR 60 วิ (ตัวแรก 70%), ร่าง ≤ 75 วิ, ตัวแรก ≤ 50 วิ
- error แปลจาก status code + ข้อความผู้ให้บริการ, log ชื่อ `govdoc.ai` — อย่าเดาว่า "คีย์ผิด" จาก 400/504
- `DraftContent` = subject, memo_intro, memo_facts, memo_consideration, paragraph_reason/details/purpose, **reference**
  - **ห้ามใส่ `default=` ใน field** — Gemini response_schema ไม่รับ default
  - `reference` (อ้างถึง) = "หนังสือ<องค์กรผู้ส่งบนหัวกระดาษ> ที่ <เลข> ลงวันที่ <วันลงหนังสือ>" ใช้แทนค่าที่ `parse_govdoc_metadata` เดา (เคยได้ตำแหน่งผู้ลงนาม + วันจัดงาน)
- กฎใน `SYSTEM_PROMPT`: ใช้เฉพาะข้อเท็จจริงในต้นเรื่อง, ขาดให้ `[✏️ ระบุ...]`, ห้ามแต่งกฎหมาย, ไม่เขียนส่วนหัว/ผู้ลงนาม, เลขข้อ ๑. ๑.๑ ไม่ใช้ markdown, บันทึกไม่ต้องเขียน "จึงเรียนมาเพื่อ..." (ระบบเติมตามขั้นเสนอ)
- AI OCR อธิบายภาพในวงเล็บ เช่น `[ตราสัญลักษณ์: ...]`, `[ตรายางมุมบนซ้าย:] ... เลขรับ` — ตัวสกัดผู้ส่งต้องใช้ชื่อไทยข้างใน และข้ามตรายางรับ
- วันที่ลงหนังสือ: เลือกบรรทัดที่มีแต่วันที่ก่อน วันที่ในประโยค (วันจัดงาน)
- คีย์ตั้งใน Vercel เท่านั้น (`GEMINI_API_KEY`, `ANTHROPIC_API_KEY`, `ANTHROPIC_WORKSPACE_ID` ถ้าเป็นคีย์ระดับองค์กร) ห้ามให้ผู้ใช้วางคีย์ในแชท; แนะนำโปรเจกต์ Gemini แบบเสียเงิน (free tier อาจนำข้อมูลไปฝึก)

## 6. หน้าแก้ไข (web/studio/editor.js)

- ช่องเนื้อความเป็น `div.lines` แต่ละบรรทัด `div.ln` คำนวณ text-indent จากเลขข้อ/แท็บ (`tab-size: 0` ซ่อนแท็บ)
- ช่องที่ทั้งช่องเป็น placeholder เท่านั้นที่เลือกให้อัตโนมัติเมื่อคลิก (ไม่งั้นกดปุ่มแล้ว placeholder กลางย่อหน้าหาย)
- เปลี่ยนประเภทหนังสือหลังร่างได้ (ร่างใหม่จากต้นเรื่องเดิม เก็บฉบับเก่าในประวัติ)
- `fitOneLine` บีบส่วนราชการให้บรรทัดเดียวเหมือนไฟล์ส่งออก

## 7. ทดสอบก่อน push ทุกครั้ง

```bash
.venv/bin/python -m pytest -q          # ปัจจุบัน 292 ผ่าน 1 ข้าม
```
- ทดสอบที่เกี่ยวข้อง: `test_step7_unit_chain`, `test_step8_font_spacing` (ระยะ/เส้นประ/ไอคอน), `test_step9_final_files`, `test_step10_llm_drafting`, `test_phase6_memo_template`
- `tests/conftest.py` ล้างคีย์ AI อัตโนมัติ — เทส AI ใช้ fake/mock เท่านั้น
- หน้าเว็บ: รัน `uvicorn server.main:app --port 8614` แล้วใช้ Playwright (`require('playwright')`) — Tailwind CDN โหลดไม่ได้ในเครื่อง cloud จึงตรวจตำแหน่งด้วย `getBoundingClientRect` ไม่ใช่หน้าตาโดยรวม
- Word: แปลงด้วย `soffice --headless --convert-to pdf` + `pdftoppm` ดูตำแหน่งได้ แต่ LibreOffice ไม่มี TH SarabunIT๙ ตัวอักษรจึงเล็กกว่าจริง — บอกผู้ใช้ตรง ๆ ว่ายังไม่ได้เปิดใน MS Word

## 8. ตรวจไฟล์/ภาพที่ผู้ใช้ส่งมา

```python
from docx import Document
d = Document(path)
for p in d.paragraphs:
    pf = p.paragraph_format
    print(pf.first_line_indent, pf.space_before, p.text.replace("​", "")[:60])
```
- เช็ค: ขอบกระดาษ, ฟอนต์ทุก run, ระยะก่อนย่อหน้า, เส้น `<v:line` ในหัวฟอร์ม, ไม่มี `w:u` ในหัวฟอร์ม, placeholder ที่เหลือ
- ไฟล์ `.dot/.doc` แปลงเป็น docx ด้วย soffice ก่อนอ่าน XML (ดูแท็บ ระยะ และรูปที่ฝังในแม่แบบ)
- ปัญหา "แก้แล้วไม่เห็นผล": เทียบเวลาที่ผู้ใช้ดาวน์โหลดกับเวลา deploy (`list_deployments` → created) — build ใช้ ~2–3 นาที
- log production: Vercel `get_runtime_logs` (Hobby เก็บแค่ 1 ชั่วโมง ใช้ `since: "50m"`) ดูว่าเรียก Gemini/Claude กี่ครั้ง ใช้เวลาเท่าไร
- เนื้อหาเอกสารในฐานข้อมูล agent อ่านไม่ได้ (RLS) — ขอภาพหน้าจอหรือไฟล์ Word จากผู้ใช้

## 9. Deploy

- branch งาน `claude/awesome-hopper-wi1sv4` = production branch ของ Vercel (push แล้วขึ้นเอง) — ห้าม push `master`, ไม่เปิด PR ถ้าไม่ได้ขอ
- Vercel project `prj_3XIFAg4IFlfIq7UW3fIucKFvQOt9`, region sin1, function ~249 MB (ใกล้เพดาน 250 MB — ไลบรารีใหม่ต้องเช็คขนาด)
- Supabase project `fjnmptcnaehbyidsgphc`: migration ใหม่ให้ผู้ใช้รันใน SQL Editor เอง (agent ไม่มีสิทธิ์เขียน) — ส่งไฟล์ SQL + คำสั่งตรวจผลให้
- ห้ามขอ service_role key / รหัสผ่าน; รหัสผ่านพิมพ์ใน SQL Editor แล้วลบทิ้ง

## 10. ข้อผิดพลาดที่เคยเกิด (อย่าทำซ้ำ)

| อาการ | สาเหตุ | ที่แก้ |
|---|---|---|
| PDF ใช้ PSK ทั้งที่เลือก IT๙ | ชื่อตระกูลภายในซ้ำ | `_font_dir_for` ส่งเฉพาะไฟล์ฟอนต์ที่เลือก |
| ข้อ ๒. ชิดซ้ายในหน้าแก้ไข | text-indent มีผลแค่บรรทัดแรกของ span | ทุกบรรทัดเป็น div ของตัวเอง |
| อ้างถึงมี `[ตราสัญลักษณ์: ...]` | ตัวสกัดผู้ส่งหยิบคำอธิบายภาพของ AI OCR | แกะชื่อไทยข้างใน, ข้ามตรายาง |
| อ้างถึง = ตำแหน่งผู้ลงนาม + วันจัดงาน | เดาจากรูปแบบข้อความ | `DraftContent.reference` |
| เส้นประบรรทัดเรื่องล้น/หาย | วัดความกว้างไม่รวม letter spacing / ใช้ขีดเส้นใต้ | `_LETTER_SPACING` + เส้นรูปร่างล็อก |
| ไอคอนไฟล์เป็นหน้าว่าง | thumbnail ว่างจากแม่แบบ | `_drop_blank_thumbnail` |
| AI ร่างหนังสือภายนอกทั้งที่เป็นเรื่องรับเข้า | classifier เดา | `choose_output_type`: มีต้นเรื่อง = บันทึกข้อความ + ปุ่มเปลี่ยนประเภท |
| production ถูกทับด้วย commit จาก master | production ติดตาม branch อื่น | ตั้ง Branch Tracking เป็น branch งาน |
