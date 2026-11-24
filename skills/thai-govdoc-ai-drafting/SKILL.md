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
| ตรวจข้อเท็จจริง | `core/fact_check.py`, `/api/v1/studio/fact-check` | วันที่/เวลา/ตัวเลขในเนื้อความเทียบต้นเรื่อง (ไม่ใช้ AI) → `check.facts`; ผู้ใช้ยืนยันเก็บใน `workspace.factOk` |
| คลังกฎหมาย (นำเข้า) | `core/legal_import.py`, `server/routers/legal_import.py`, migration 8 | ไฟล์สแกน → AI อ่านทีละหน้า (`/legal/ocr-page`, เบราว์เซอร์เรนเดอร์ภาพด้วย pdf.js) → `split_sections` (ข้อ/มาตรา, หมวด, บัญชีท้าย, ตัดหัวกระดาษราชกิจจาฯ) → `legal_references` (source_id, page_from/to) ยังไม่ยืนยัน |
| เสนอ/แนบข้อกฎหมาย | `core/legal_suggest.py` (`/legal/suggest`), `core/legal_pages.py`, `server/routers/export.py` | คัดด้วยคำ → AI เลือกจากรหัสในรายการที่ยืนยันแล้วเท่านั้น; PDF ต่อหน้าจริงจากไฟล์ใน Storage (header `X-GovDoc-Legal-Pages`) |
| ฉบับจริง | `core/final_file.py`, `server/routers/finals.py` | อัปโหลด Word/PDF ที่แก้เสร็จกลับเข้าระบบ (sha256, append-only) |
| ตัวอย่างของหน่วย (สำนวน) | `core/style_examples.py`, `server/routers/examples.py`, migration 10 | หนังสือฉบับจริง (อัปโหลดหลายไฟล์จากหน้าแรก / ปุ่ม "นี่คือฉบับจริง" ในแท็บ ฉบับจริง) → `parse_example`/`from_document` แยก เรื่อง/ภาคเหตุ/ข้อเท็จจริง/ความประสงค์ + `keywords` → ตอนร่าง `example_finder` → `rank_examples` (คำที่ตรงกัน ประเภทเดียวกัน ≤ ๓) → `few_shot_block` (ปิดเลข/วันที่/ชื่อ, งบ ~4,800 ตัวอักษร) → `result.style_examples` แสดงในแชท/แท็บต้นเรื่อง |
| ผู้ลงนามของหน่วย | `core/signers.py`, `server/routers/signers.py`, migration 12 | `org_signers` (ใช้ร่วมทั้งหน่วย) → `apply_issuing_unit(roster, use_default)` / `fill_document_signers`: ตำแหน่งตรง = เติมชื่อ, ร่างใหม่ = ผู้ลงนามเริ่มต้นในช่องหลักที่ว่าง (ไม่แตะผู้เสนอเรื่อง/ชื่อที่มีอยู่); หน้าแก้ไขปุ่ม `[data-pick-signer]` |
| ทะเบียนรับ-ส่ง / ออกเลข | `core/registry.py` (`split_number_template`, `issue_draft_for`, `search_rows`), `core/register_export.py` (แบบทะเบียน ข้อ ๓๘/๕๐ → xlsx เขียนเอง + Typst PDF), `server/routers/registry.py`, migration 2 + 13, `web/studio/registry*.{html,js}` | ปุ่ม "ออกเลข" (`#btn-issue`) อ่านเอกสารจากเซิร์ฟเวอร์ → `issue_outgoing_number`/`use_reserved_number` (ล็อกแถวเอกสาร กดซ้ำไม่ได้สองเลข) → เติมช่อง "ที่"; ยกเลิก = เลขอยู่ในทะเบียนพร้อมเหตุผล ช่อง "ที่" กลับเป็นรหัส+ช่องว่าง (จาก `book`); แท็บต้นเรื่อง `#receive-box` ลงรับ (ไฟล์ละครั้ง) → หนังสือตอบเชื่อมเลขรับเองผ่าน `sourceFileId` |
| หน้าเว็บ | `web/studio/index.html`/`home.js` (หน้าแรก), `editor.html`/`editor.js`/`studio.css` (หน้าแก้ไข) | |
| ฐานข้อมูล | `supabase/migrations/2026111*` (12 ไฟล์) | RLS ตาม org, RPC security definer, audit |

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
- หัวข้อ (ต้นเรื่อง/ข้อกฎหมาย/ข้อเท็จจริง/ข้อพิจารณาและเสนอแนะ) เริ่ม 2.5 ซม. ขีดเส้นใต้; เนื้อความเป็นข้อ ๆ (บรรทัดแรก ๑. / มาตรา / แท็บ) = หัวข้อบรรทัดเดี่ยว, ความเรียง = หัวข้อนำหน้าข้อความ (`starts_with_item`); AI ใส่เลขข้อเฉพาะเมื่อมี ๒ ข้อขึ้นไป (`drop_lone_number` ตัด "๑." เดี่ยว); เปลี่ยนชื่อได้ `memo_headings` (ว่าง = ไม่แสดง)
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
- `DraftContent` = subject, memo_intro, memo_facts, memo_consideration, paragraph_reason/details/purpose, **reference**, **source_summary**
  - **ห้ามใส่ `default=` ใน field** — Gemini response_schema ไม่รับ default
  - `source_summary` = สรุปต้นเรื่อง ๓–๔ บรรทัด (ใคร/ขออะไร/เมื่อไร-ที่ไหน/ต้องทำอะไร) → `ctx.summary` + `summary_by_ai=True` (`core/studio._clean_summary` ตัด placeholder/สัญลักษณ์, ไม่เกิน ๔ บรรทัด); หน้าแก้ไขแสดงเฉพาะสรุปจาก AI
  - `reference` (อ้างถึง) = "หนังสือ<องค์กรผู้ส่งบนหัวกระดาษ> ที่ <เลข> ลงวันที่ <วันลงหนังสือ>" ใช้แทนค่าที่ `parse_govdoc_metadata` เดา (เคยได้ตำแหน่งผู้ลงนาม + วันจัดงาน)
- กฎใน `SYSTEM_PROMPT`: ใช้เฉพาะข้อเท็จจริงในต้นเรื่อง, ขาดให้ `[✏️ ระบุ...]`, ห้ามแต่งกฎหมาย, ไม่เขียนส่วนหัว/ผู้ลงนาม, เลขข้อ ๑. ๑.๑ ไม่ใช้ markdown, บันทึกไม่ต้องเขียน "จึงเรียนมาเพื่อ..." (ระบบเติมตามขั้นเสนอ)
- AI OCR อธิบายภาพในวงเล็บ เช่น `[ตราสัญลักษณ์: ...]`, `[ตรายางมุมบนซ้าย:] ... เลขรับ` — ตัวสกัดผู้ส่งต้องใช้ชื่อไทยข้างใน และข้ามตรายางรับ
- วันที่ลงหนังสือ: เลือกบรรทัดที่มีแต่วันที่ก่อน วันที่ในประโยค (วันจัดงาน)
- **ตัวอย่างสำนวนของหน่วย (few-shot)** — กฎ 9 ใน `SYSTEM_PROMPT` + ส่วน `<example>` ใน `build_user_prompt(examples=...)`
  - ตัวอย่างอยู่ **ก่อน** `<instruction>`/`<source>` เสมอ (เรื่องใหม่อยู่ท้าย) และมีคำสั่งห้ามใช้ข้อเท็จจริงในตัวอย่าง
  - `mask_facts` ปิด วันที่ → `[วันที่]`, ตัวเลข → `[เลข]`, คำนำหน้า+ชื่อ → `[ชื่อบุคคล]` (ยกเว้น นายก/นายทะเบียน/นายอำเภอ ฯลฯ) — เลขข้อ ๑. คงรูปแบบ
  - AI คัดลอกส่วนที่ปิดมา → `_clean` → `unmask_leftovers` เปลี่ยนเป็น `[✏️ ระบุ...]` (ผู้ใช้เห็นเป็นจุดต้องแก้)
  - เลือกด้วยคำ (`core/legal_suggest._words` + IDF, คำในชื่อเรื่อง ×๒, หารรากความยาว) ต้องตรง ≥ ๒ คำ; ไม่ใช้ embedding — คำสำคัญคำนวณตอนเก็บ (คอลัมน์ `keywords`) ตอนร่างดึงแค่ id/subject/keywords แล้วค่อยดึงเนื้อความ ≤ ๓ ฉบับ
  - ตารางยังไม่มี/ฐานข้อมูลขัดข้อง/ชั้นลับ/ไม่มีคีย์ AI → ร่างต่อโดยไม่มีตัวอย่าง (ห้ามทำให้การร่างล้ม)
- คีย์ตั้งใน Vercel เท่านั้น (`GEMINI_API_KEY`, `ANTHROPIC_API_KEY`, `ANTHROPIC_WORKSPACE_ID` ถ้าเป็นคีย์ระดับองค์กร) ห้ามให้ผู้ใช้วางคีย์ในแชท; แนะนำโปรเจกต์ Gemini แบบเสียเงิน (free tier อาจนำข้อมูลไปฝึก)

## 6. หน้าแก้ไข (web/studio/editor.js)

- ช่องเนื้อความเป็น `div.lines` แต่ละบรรทัด `div.ln` คำนวณ text-indent จากเลขข้อ/แท็บ (`tab-size: 0` ซ่อนแท็บ)
- ช่องที่ทั้งช่องเป็น placeholder เท่านั้นที่เลือกให้อัตโนมัติเมื่อคลิก (ไม่งั้นกดปุ่มแล้ว placeholder กลางย่อหน้าหาย)
- เปลี่ยนประเภทหนังสือหลังร่างได้ (ร่างใหม่จากต้นเรื่องเดิม เก็บฉบับเก่าในประวัติ)
- `fitOneLine` บีบส่วนราชการให้บรรทัดเดียวเหมือนไฟล์ส่งออก
- ตัวอย่างที่ร่างนี้อ้างสำนวน: `entry.styleExamples` (เก็บใน workspace, อัปเดตตอนร่างใหม่) → `#chat-style` ในแชท + `#style-refs` ใต้สรุปต้นเรื่อง
- "นี่คือฉบับจริง" (`#mark-example` แท็บ ฉบับจริง): `persist()` ก่อน แล้ว `/examples/from-document` — เซิร์ฟเวอร์อ่าน `documents.workspace.doc` เอง (ไม่เชื่อ doc จากเบราว์เซอร์), กดซ้ำ = อัปเดต (unique index ต่อ document_id), ปฏิเสธถ้าเรื่อง/เนื้อความยังมี `[✏️`

## 7. ทดสอบก่อน push ทุกครั้ง

```bash
.venv/bin/python -m pytest -q          # ปัจจุบัน 403 รายการ 1 ข้าม (Windows: test_width_measure_counts_letter_spacing ไม่ผ่าน — PyThaiNLP)
```
- ทดสอบที่เกี่ยวข้อง: `test_step7_unit_chain`, `test_step8_font_spacing` (ระยะ/เส้นประ/ไอคอน), `test_step9_final_files`, `test_step10_llm_drafting`, `test_phase6_memo_template`
- ผู้ลงนามของหน่วย: `test_step20_org_signers.py` (เติมชื่อ/เริ่มต้น/API/ตารางยังไม่มี)
- ทะเบียนรับ-ส่ง: `test_step21_registry.py` (รูปแบบเลขที่, แบบทะเบียน, xlsx/PDF, API ออกเลข/ยกเลิก/จอง/ลงรับ/ส่งออก); ฐานข้อมูลจริง `bash supabase/tests/run_local.sh` — บน Windows รันใน Docker: `docker run --rm -v "<repo>/supabase:/src:ro" postgres:16 bash -c 'cp -r /src /w && find /w -type f -exec sed -i "s/\r$//" {} + && chown -R postgres /w && PGBIN=/usr/lib/postgresql/16/bin bash /w/tests/run_local.sh'` (รวมออกเลขพร้อมกัน 200 ครั้ง)
- คลังตัวอย่าง: `test_step18_style_examples.py` (แยกส่วน/ปิดข้อเท็จจริง/เลือก), `test_step18_style_examples_api.py` (API + few-shot ใน prompt ตอนร่าง)
- หน้าเว็บโหมด Supabase บนเครื่อง: รันแอปจริงกับ `FakeSupabase` แล้ว mount proxy `/fake-sb/{path}` → `fake.handle` ให้ supabase-js ในเบราว์เซอร์ล็อกอินได้ (รหัสผ่าน `correct-password`) — ต้อง (๑) ตั้ง `supabase_url` = URL proxy และออก token ด้วย `iss` = `<proxy>/auth/v1` (๒) `transport_factory` ตัด `/fake-sb` ออกก่อนส่งให้ fake ไม่งั้น JWKS 404 → API ตอบ 503 "ตรวจสอบการเข้าสู่ระบบไม่ได้ชั่วคราว"; fake เก็บข้อมูลในหน่วยความจำ — รีสตาร์ทก่อนรันชุดทดสอบใหม่
- Playwright: `chromium.launch({ channel: 'chrome' })` ใช้ Chrome ในเครื่อง (ติดตั้งแพ็กเกจด้วย `PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1`); ไฟล์อัปโหลดส่งเป็น buffer ผ่าน `setInputFiles([{name, mimeType, buffer}])` ได้
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

- `master` = production branch ของ Vercel (ตั้งแต่ ๒๔ พ.ย. ๒๕๖๙ — merge แล้วขึ้นเว็บเองใน ~2–3 นาที) — ทำงานบน branch แยก แล้วเปิด PR เข้า `master` เมื่อผู้ใช้ขอ; ห้าม push `master` ตรง
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
| ร่างลอกชื่อ/เลข/วันที่จากหนังสือเก่า (เสี่ยงเมื่อใส่ตัวอย่าง) | few-shot ส่งข้อความดิบ | `mask_facts` ก่อนใส่ prompt + `unmask_leftovers` หลังได้คำตอบ + `fact_check` ตามเดิม |
| ข้อความ OCR ต่อกันเป็นก้อน "...เยาวชนจึงเห็นควร..." | รวมบรรทัดที่ OCR ตัดกลางประโยคโดยไม่ดูคำขึ้นต้น | `_join`: บรรทัดที่ขึ้นต้น เลขข้อ หรือ "จึง..." ขึ้นย่อหน้าใหม่ |
| ข้อความ sr-only ในตารางทำหน้าล้นแนวนอนบนมือถือ | `position:absolute` หลุดจากกล่อง `overflow-x-auto` ที่ไม่ใช่ positioned | ใส่ `relative` ที่กล่องเลื่อนของตาราง |
| หลาย session แก้โฟลเดอร์เดียวกันบน branch เดียว แล้ว commit ไฟล์ของกันและกัน | `git add` ทั้งไฟล์/ทั้งโฟลเดอร์ | ดู `git status` ก่อน commit, `git add` เฉพาะไฟล์ของงานตัวเอง, เลข migration ไม่ซ้ำ (ดูไฟล์ล่าสุดใน `supabase/migrations/` ก่อนตั้งชื่อ) |
