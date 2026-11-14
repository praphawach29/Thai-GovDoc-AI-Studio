# ARCHITECTURE.md — สถาปัตยกรรมเป้าหมาย (Vercel + Supabase)

**สถานะ:** ร่างออกแบบ รอยืนยันก่อนลงมือ (14 พ.ย. 2569)
**ขอบเขตรอบนี้:** ทดสอบใช้งานจริงคนเดียวบนคลาวด์ (GitHub → Vercel, ฐานข้อมูล Supabase) โดยออกแบบให้ขยายเป็นหลายผู้ใช้/หลายหน่วยงานได้โดยไม่ต้องย้ายข้อมูล

> ข้อจำกัดสำคัญ: Vercel และ Supabase เป็นคลาวด์สาธารณะ ระหว่างทดสอบใช้เฉพาะเอกสารตัวอย่างหรือเอกสารชั้นปกติที่ไม่มีข้อมูลส่วนบุคคล เอกสารชั้นลับต้องใช้งานบนเครื่อง/ศูนย์ข้อมูลของหน่วยงานตาม `ONLINE_PRODUCTION_PLAN.md`

---

## 1. ภาพรวม

```
เบราว์เซอร์ (web/ — HTML/JS ล้วน, เสิร์ฟจาก Vercel CDN)
   │  1) login ด้วย Supabase Auth → ได้ JWT
   │  2) อัปโหลดไฟล์ต้นเรื่องตรงไป Supabase Storage (signed upload URL, ไม่ผ่าน Vercel)
   │  3) เรียก /api/* พร้อม Authorization: Bearer <JWT>
   ▼
Vercel Python Function: api/index.py → FastAPI (server/)
   ├─ ตรวจ JWT ทุก request (ยกเว้น /api/health)
   ├─ เรียก core/ (ตรรกะหนังสือราชการ — ฟังก์ชันล้วน ไม่มี I/O)
   ├─ อ่าน/เขียน Postgres ผ่าน Supabase (ส่ง JWT ของผู้ใช้ → RLS มีผล)
   ├─ ออกเลขหนังสือผ่านฟังก์ชัน SQL (atomic)
   └─ เรียก Gemini เฉพาะเอกสารชั้นปกติ (fail-closed)
   ▼
Supabase (ภูมิภาค Singapore): Postgres + Auth + Storage
```

ตั้ง Vercel function region เป็น `sin1` ให้อยู่ใกล้ Supabase Singapore

## 2. อะไรเก็บ อะไรรื้อ

| ส่วน | การตัดสินใจ | เหตุผล |
|---|---|---|
| `core/models.py`, `templates_library.py`, `linter.py`, `text_checks.py`, `verification.py`, `intake.py`, `sections.py`, `memo_layout.py`, `hierarchy.py`, `case_dossier.py`, `classifier.py`, `entity_extractor.py`, `copilot.py`, `special_drafter.py`, `thai_date.py`, `thai_segmenter.py` | **เก็บ** | ตรรกะสารบรรณ มีเทสต์คุม ไม่ผูกกับที่เก็บข้อมูล |
| `core/word_exporter.py`, `docx_fonts.py` | **เก็บ + ปรับ** | เพิ่ม `w:lang w:bidi="th-TH"`, ให้เลือกการจัดแนว (ดูข้อ 7) |
| `core/typst_exporter.py`, `templates/typst/*` | **เก็บ + ปรับ** | เป็นช่องทาง PDF เดียวบนคลาวด์; แก้ขนาดชั้นความเร็ว (ข้อ 7) |
| `core/ai_drafter.py`, `extractor.py` | **เก็บ + ปรับ** | อ่าน API key จาก env เท่านั้น (เลิกรับจาก request), OCR บนคลาวด์ใช้ pdfplumber + Gemini |
| `core/registry.py` (SQLite) | **รื้อ** | ออกเลขซ้ำเมื่อเรียกพร้อมกัน, `INSERT OR REPLACE` ลบประวัติ → ย้ายเป็นตาราง + ฟังก์ชัน SQL |
| `core/audit.py` (SQLite) | **รื้อส่วนเก็บข้อมูล** | เก็บ `compute_*_diff` ไว้, ย้ายบันทึกไป Postgres แบบเขียนเพิ่มอย่างเดียว |
| `core/legal_sources.py` + `data/legal_references.json` | **ย้ายไปตาราง** | ไฟล์บน Vercel เขียนไม่ได้ |
| `core/profile_manager.py` + `data/user_profile.json` | **ย้ายไปตาราง** | ผูกกับผู้ใช้/หน่วยงาน |
| `core/api.py` | **แยกใหม่** เป็น `server/` | แยก router, ใส่ auth, เลิกเขียน `uploads/` |
| `core/pdf_exporter.py` (HTML→Chrome) | **ใช้เฉพาะเครื่อง local** | Vercel ไม่มี Chrome; ซ้ำซ้อนกับ Typst; ยังไม่ escape HTML |
| `core/ocr_preprocessor.py` + Docker Tesseract | **ใช้เฉพาะเครื่อง local** | Vercel รัน Docker ไม่ได้, OpenCV ใหญ่เกินขนาด function |
| `web/app.py` (Streamlit 3,500 บรรทัด) | **ปลดระวาง** → `legacy/` | Vercel รัน Streamlit ไม่ได้; หน้าเว็บหลักคือ `web/studio` |
| `web/studio/*` | **เก็บ + ต่อยอด** | เพิ่มหน้า login, เปลี่ยนจาก localStorage เป็น API |

กติกาใหม่: **`core/` ห้ามทำ I/O** (ไม่เปิด DB, ไม่เขียนไฟล์นอก temp, ไม่อ่าน env) ทุกอย่างที่แตะโลกภายนอกอยู่ใน `server/`

## 3. โครงสร้างโฟลเดอร์ใหม่

```
api/index.py                 # จุดเข้า Vercel: from server.main import app
server/
  main.py                    # สร้าง FastAPI, CORS เฉพาะโดเมนตัวเอง, error handler ไม่เผยข้อความภายใน
  settings.py                # อ่าน env (SUPABASE_URL, SUPABASE_ANON_KEY, GEMINI_API_KEY, APP_ENV)
  auth.py                    # ตรวจ JWT ของ Supabase → CurrentUser(user_id, org_id, role)
  db.py                      # Supabase client ต่อ request (ใช้ JWT ผู้ใช้)
  storage.py                 # ออก signed upload/download URL, ดึงไฟล์มาประมวลผล
  routers/
    documents.py             # CRUD ร่าง + เวอร์ชัน
    drafting.py              # สกัด/ร่าง/ตรวจ/copilot
    export.py                # DOCX, PDF (Typst)
    registry.py              # ออกเลข/จอง/ยกเลิก, ทะเบียนรับ-ส่ง
    legal.py, profile.py
core/                        # ตรรกะล้วน (ตามข้อ 2)
templates/typst/
assets/                      # ฟอนต์ TH Sarabun New, ตราครุฑ
web/                         # หน้าเว็บ static (ย้ายจาก web/studio)
  index.html, editor.html, login.html, registry.html, js/, css/
supabase/migrations/         # SQL ทุกตาราง ฟังก์ชัน และ RLS (เก็บใน git)
legacy/                      # Streamlit + HTML→PDF สำหรับใช้บนเครื่อง
tests/
vercel.json
requirements.txt             # เฉพาะที่ deploy (ไม่มี streamlit/opencv)
requirements-dev.txt         # -r requirements.txt + pytest + streamlit + opencv
```

## 4. ฐานข้อมูล (Supabase Postgres)

ทุกตารางมี `org_id` ตั้งแต่วันแรก แม้ตอนนี้มีหน่วยงานเดียวและผู้ใช้คนเดียว

| ตาราง | หน้าที่ | คอลัมน์หลัก |
|---|---|---|
| `organizations` | หน่วยงาน | `name`, `doc_prefix` (เช่น `ดพร ๐๑๐๒`), `address`, `use_thai_numerals` |
| `profiles` | ผู้ใช้ (1:1 กับ `auth.users`) | `user_id`, `org_id`, `full_name`, `position`, `role` (`admin`/`clerk`/`drafter`/`approver`) |
| `documents` | แฟ้มเอกสาร 1 เรื่อง | `kind`, `status` (`draft`→`review`→`approved`→`numbered`→`sent`→`archived`), `secret_level`, `urgency`, `subject`, `doc_number`, `current_version` |
| `document_versions` | ทุกครั้งที่บันทึก (เขียนเพิ่มอย่างเดียว) | `document_id`, `version_no`, `content jsonb` (= `GovDocumentSchema`), `created_by`, `note` |
| `source_files` | ไฟล์ต้นเรื่อง | `storage_path`, `filename`, `mime`, `size`, `sha256`, `extracted_text`, `ocr_engine`, `delete_after` |
| `number_sequences` | ตัวนับเลขทะเบียน | PK (`org_id`, `book`, `year_be`), `last_value` |
| `outgoing_register` | ทะเบียนหนังสือส่ง | `reg_no`, `doc_number`, `doc_date`, `from_unit`, `to_recipient`, `subject`, `action_taken`, `remark`, `status` (`reserved`/`issued`/`cancelled`), `cancel_reason`, `document_id` |
| `incoming_register` | ทะเบียนหนังสือรับ | `reg_no`, `received_at`, `source_doc_number`, `source_doc_date`, `from_org`, `to_unit`, `subject`, `action_taken`, `remark`, `source_file_id` |
| `audit_log` | บันทึกการกระทำ | `actor_id`, `action`, `entity`, `entity_id`, `details jsonb`, `prev_hash`, `hash`, `at` |
| `legal_references` | คลังข้อกฎหมาย | ย้ายจาก JSON เดิม |
| `ai_usage` | การเรียก AI | `model`, `purpose`, `secret_level`, `tokens_in/out`, `document_id` |

### 4.1 การออกเลขหนังสือ (แก้บั๊กเลขซ้ำ)

ออกเลขด้วยคำสั่ง SQL คำสั่งเดียวที่ล็อกแถวในตัว แทนการอ่านแล้วค่อยบวกหนึ่ง:

```sql
create function issue_reg_no(p_org uuid, p_book text) returns int
language sql as $$
  insert into number_sequences (org_id, book, year_be, last_value)
  values (p_org, p_book, extract(year from now() at time zone 'Asia/Bangkok')::int + 543, 1)
  on conflict (org_id, book, year_be)
  do update set last_value = number_sequences.last_value + 1
  returning last_value;
$$;
```

- เลขทะเบียนเริ่มที่ ๑ ใหม่ทุกปีปฏิทิน โดยนับปีตามเวลาประเทศไทย
- ห้ามลบหรือเขียนทับรายการในทะเบียน: เลขที่จองแล้วไม่ใช้ให้เปลี่ยนสถานะเป็น `cancelled` พร้อมเหตุผล
- ขอดูเลขถัดไปต้องไม่กินเลข (ออกเลขจริงเฉพาะ `POST`)

### 4.2 สิทธิ์ (Row Level Security)

- ทุกตารางเปิด RLS: อ่าน/เขียนได้เฉพาะแถวที่ `org_id` ตรงกับ `profiles.org_id` ของผู้ใช้
- `audit_log`, `document_versions`: อนุญาต `insert` อย่างเดียว ไม่มีสิทธิ์ `update`/`delete`
- `outgoing_register`/`incoming_register`: ไม่มีสิทธิ์ `delete`
- Storage bucket `sources` เป็น private, path ขึ้นต้นด้วย `org_id/`

### 4.3 Audit chain

ทริกเกอร์คำนวณ `hash = sha256(prev_hash || row)` ทุกครั้งที่ insert ทำให้ตรวจได้ว่ามีการแก้ไขย้อนหลังหรือไม่

## 5. การล็อกอิน

ใช้ **Supabase Auth (อีเมล + รหัสผ่าน)** แทนรหัสผ่านเดียวใน env ที่เสนอไว้ก่อนหน้า เพราะใช้ Supabase อยู่แล้ว ได้ JWT มาตรฐาน และ RLS ใช้ตัวตนเดียวกัน

- ช่วงทดสอบ: ปิดการสมัครเอง (disable signups) แล้วสร้างบัญชีให้ตัวเองบัญชีเดียวในหน้า Supabase
- ภายหลังเพิ่ม SSO (SAML/OIDC) ของหน่วยงานได้โดยตารางเดิมไม่ต้องเปลี่ยน
- หน้าเว็บใช้ `@supabase/supabase-js` ระบุเวอร์ชันแน่นอน, FastAPI ตรวจลายเซ็น JWT ทุก request

## 6. ขั้นตอนหลักบนคลาวด์

1. **แนบต้นเรื่อง:** เบราว์เซอร์ขอ signed URL → อัปโหลดตรงไป Storage (เลี่ยงเพดาน request ~4.5 MB ของ Vercel) → แจ้ง API ด้วย path
2. **สกัดข้อความ:** PDF ดิจิทัลใช้ pdfplumber; สแกน/รูปใช้ Gemini เฉพาะชั้นปกติ; ชั้นลับปฏิเสธบนคลาวด์
3. **ร่าง:** rule-based เป็นค่าเริ่มต้น, LLM เมื่อเลือกและผ่านเงื่อนไขชั้นความลับ, บันทึกเป็น `document_versions`
4. **ตรวจ:** linter + text checks + placeholder (โค้ดเดิม)
5. **ออกเลข:** `issue_reg_no` → อัปเดต `documents.doc_number` + `outgoing_register`
6. **ส่งออก:** DOCX (python-docx) / PDF (Typst) สร้างในหน่วยความจำ ส่งกลับตรง ไม่เก็บไฟล์บนเซิร์ฟเวอร์
7. **ลบไฟล์ต้นเรื่องอัตโนมัติ** ตาม `delete_after` (เริ่มที่ 30 วัน) ด้วย Supabase cron

## 7. แก้ให้ตรงระเบียบและแหล่งอ้างอิง

| เรื่อง | ปัจจุบัน | แก้เป็น |
|---|---|---|
| ขนาดชั้นความเร็ว (ด่วน/ด่วนมาก/ด่วนที่สุด) | Typst 18 pt, `SARABAN_RULES.md` เขียน 20–24 pt | ไม่เล็กกว่า **32 pt** สีแดง ตามระเบียบงานสารบรรณ ข้อ 16 (typst-govdoc ใช้ 36 pt) |
| ตัดคำไทยใน Typst | เอกสารเดิมอ้าง typst-govdoc ว่า Typst ตัดคำไทยไม่ได้ | Typst 0.15 ตัดคำไทยตามขอบเขตคำเองแล้ว (ทดสอบแล้ว) ไม่ต้องแทรก ZWSP ใน PDF |
| การจัดแนวย่อหน้าใน DOCX | บังคับ `thaiDistribute` | ทำเป็นตัวเลือก: ค่าเริ่มต้น `thaiDistribute` ตามที่สำนักงานใช้จริง, มีตัวเลือก `left` ตามคำแนะนำของ thai-doc-skills ที่เตือนว่ากระจายแบบไทยยืดตัวอักษร |
| ภาษาใน DOCX | ยังไม่ระบุ | ใส่ `w:lang w:bidi="th-TH"` ให้ Word ตัดคำ/ตรวจตัวสะกดไทยได้เอง |
| คำว่า "วันที่" | AGENTS.md ห้ามทุกกรณี | ห้ามเฉพาะบรรทัดวันที่ของ**หนังสือภายนอก**; บันทึกข้อความมีหัวข้อ "วันที่" เป็นป้ายกำกับตามแบบฟอร์ม |
| ระเบียบฉบับแก้ไข | อ้างแค่ พ.ศ. ๒๕๒๖ | ระบุฉบับแก้ไขเพิ่มเติม (ฉบับที่ ๒ พ.ศ. ๒๕๔๘, ฉบับที่ ๓ พ.ศ. ๒๕๖๐, ฉบับที่ ๔ พ.ศ. ๒๕๖๔ ซึ่งว่าด้วยหนังสืออิเล็กทรอนิกส์) — ตรวจข้อความจากราชกิจจานุเบกษาก่อนใส่รายละเอียด |
| ทะเบียนรับ-ส่ง | คอลัมน์ไม่ครบตามแบบทะเบียนในระเบียบ | ใช้คอลัมน์ตามข้อ 4 (เลขทะเบียน, ที่, ลงวันที่, จาก, ถึง, เรื่อง, การปฏิบัติ, หมายเหตุ) |

## 8. ข้อสังเกตต่อ repo อ้างอิง

| Repo | ใช้ได้จริงแค่ไหน | ใบอนุญาต | ข้อควรระวัง |
|---|---|---|---|
| `whs/typst-govdoc` | ต้นแบบ layout ใช้ได้ (ขอบ 3/2/2.5/2, ครุฑ 3 ซม., ย่อหน้า 2.5 ซม., ชั้นความเร็ว 36 pt) | ไม่มีไฟล์ LICENSE ใน repo | ใช้เป็นแนวคิด อย่าคัดลอกโค้ดตรง; ข้อจำกัดเรื่องตัดคำไทยใน README ล้าสมัยแล้ว |
| `copninixh/TH-National-Document-OCR` | มีแต่ README; โมเดลอยู่ใน Google Drive, Tesseract v4 (2564) | ไม่มีไฟล์ LICENSE | ใช้บน Vercel ไม่ได้; ถ้าจะใช้บนเครื่อง local ต้องวัดความแม่นเทียบ Gemini ก่อน |
| `Boom-Vitt/claude-thai-skills` | `thai-government-form` ใช้อ้างอิงคำขึ้นต้น/ลงท้ายได้, `thai-date-format`, `thai-pdpa` มีประโยชน์ | MIT | ตัวอย่างหนังสือภายนอกใส่ "วันที่" หน้าวันที่ และบอกว่าบันทึกข้อความไม่มีบรรทัด "เรียน" แยก — ขัดกับแบบฟอร์มที่ใช้จริง ให้ยึด `SARABAN_RULES.md` |
| `thaigqsoft/thai-doc-skills` | เทคนิค ZWSP + ตั้งฟอนต์ฝั่ง cs + ฝังฟอนต์ ตรงกับที่ทำอยู่แล้ว | MIT | แนะนำจัดชิดซ้าย ไม่ใช้ thaiDistribute (ดูข้อ 7) |
| `goragodwiriya/edocument` | ระบบเวียนเอกสาร + ติดตามการลงชื่อรับ (ใครดาวน์โหลดแล้ว) | MIT | ไม่ใช่ทะเบียนรับ-ส่งตามระเบียบ; ระบบออกเลขก็ไม่ล็อกแบบเดียวกับเรา |
| `goragodwiriya/eoffice` | แนวคิดสิทธิ์รายความสามารถ, อนุมัติหลายขั้น, แจ้งเตือน | ไม่ใช่โอเพนซอร์ส: ใช้งานจริงต้องจ่าย 1,000 บาท, ห้ามขาย | ศึกษาแนวคิดได้ **ห้ามคัดลอกโค้ด** |

## 9. ค่าจัดหน้าจากคู่มือ "การพิมพ์หนังสือราชการด้วย Microsoft Word" (อบต.ดูน จ.ศรีสะเกษ)

คู่มือนี้เป็นแนวปฏิบัติของหน่วยงาน (อ้างแบบที่ ๒๘ กระดาษตราครุฑ และแบบที่ ๒๙ กระดาษบันทึกข้อความ ท้ายระเบียบงานสารบรรณ) ไม่ใช่ตัวระเบียบเอง แต่ให้ค่าที่วัดได้ชัด จึงใช้เป็น **โปรไฟล์มาตรฐาน (`standard`)** ส่วนแบบ กทม. ที่ Ekkasarn ใช้ (ขอบบน 1.5 ซม., หัว 32 pt) แยกเป็นโปรไฟล์ `bma` (`form_it9_2026` เดิม)

**ร่วมทุกชนิด:** A4, ขอบ ซ้าย 3 / ขวา 2 / บน 2.5 / ล่าง 2 ซม. (พื้นที่พิมพ์กว้าง 16 ซม.), TH Sarabun 16 pt, ระยะบรรทัด single (ปรับได้ 1.05–1.1), ย่อหน้า 2.5 ซม., "1 Enter" = 1 บรรทัด, ยอดครุฑห่างขอบบน 2.5 ซม.

| ส่วน | หนังสือภายนอก (รูปที่ 11) | บันทึกข้อความ (รูปที่ 12) | คำสั่ง/ประกาศ (รูปที่ 13–14) |
|---|---|---|---|
| ครุฑ | สูง 3 ซม. กึ่งกลาง | สูง 1.5 ซม. มุมซ้าย | สูง 3 ซม. กึ่งกลาง |
| หัว | "ที่" และส่วนราชการเจ้าของหนังสืออยู่แนวเท้าครุฑ | "บันทึกข้อความ" หนา 29 pt บรรทัด Exactly 35 pt; "ส่วนราชการ ที่ วันที่ เรื่อง" หนา 20 pt + จุดไข่ปลา; "วันที่" ตรงตัว "ข" | ชื่อคำสั่ง/ประกาศ, ที่ .../ปี, เรื่อง กึ่งกลาง + เส้นขีดคั่น |
| วันที่ | ตัวแรกของ**ชื่อเดือน**ตรงแนวเท้าขวาของครุฑ (1 Enter + 6 pt) | ตัวแรกของชื่อเดือนตรงหลังตัว "ม" ของ "บันทึกข้อความ" | ท้ายเรื่อง: "สั่ง ณ วันที่ ..." / "ประกาศ ณ วันที่ ..." ย่อหน้า 4 ซม. + 12 pt |
| เรื่อง/เรียน/อ้างถึง/สิ่งที่ส่งมาด้วย | แต่ละบรรทัด 1 Enter + 6 pt | เรียน อยู่บรรทัดแยก 1 Enter + 6 pt | — |
| ระหว่างย่อหน้า | 1 Enter + 6 pt | 1 Enter + 6 pt | เส้นขีด→ภาคเหตุ 12 pt; ย่อหน้า 6 pt |
| คำลงท้าย | ตัวแรกตรง**แนวกึ่งกลางครุฑ**, 12 pt จากย่อหน้าสุดท้าย | ไม่มี | เหมือนหนังสือภายนอก |
| ชื่อ (ในวงเล็บ) + ตำแหน่ง | ใต้คำลงท้าย 4 Enter, กึ่งกลางเทียบคำลงท้าย | 4 Enter จากบรรทัดสุดท้าย | 4 Enter |
| ส่วนราชการเจ้าของเรื่อง | 4 Enter จากตำแหน่ง, 16 pt, โทร./โทรสาร/อีเมล | — | — |
| ชั้นความลับ | — | กลางหน้า **ทั้งบนและล่าง** | — |

ข้อผิดพลาดในตัวคู่มือที่ไม่ควรลอก: คำบรรยายรูปที่ 1 เขียน "แบบที่8" (ที่ถูกคือแบบที่ ๒๘), และตัวอย่างประกาศ (รูปที่ 14) ใช้ "สั่ง ณ วันที่" ซึ่งต้องเป็น "ประกาศ ณ วันที่"

### 9.1 ส่วนที่เทมเพลต Typst ของเรายังไม่ตรง (ตรวจจาก PDF ที่ render จริง)

| จุด | ปัจจุบัน (`templates/typst/external.typ`) | ต้องเป็น |
|---|---|---|
| วันที่ | เริ่มที่ 6.5 ซม. จากขอบข้อความ (ซ้ายของกึ่งกลาง) | ชื่อเดือนเริ่มที่แนวเท้าขวาครุฑ (≈ 8.7 ซม.) |
| คำลงท้าย | จัดกึ่งกลางในกรอบที่เริ่ม 6 ซม. → ตัวแรกอยู่ราว 9.5 ซม. | ตัวแรกที่ 8 ซม. (กึ่งกลางพื้นที่พิมพ์) |
| ช่องลงนาม | เว้น 1.5 ซม. (~2 บรรทัด) | 4 Enter (เว้น 3 บรรทัด) |
| ระยะ 6/12 pt | ใช้ระยะบรรทัดค่าเดียวทั้งฉบับ | 6 pt ก่อนหัวข้อและย่อหน้า, 12 pt ก่อนคำลงท้าย |
| ส่วนราชการเจ้าของเรื่อง | 14 pt, ห่าง 0.8 ซม. | 16 pt, ห่าง 4 Enter |
| ชั้นความลับ | หัวกระดาษอย่างเดียว | หัวและท้ายกระดาษ |
| คำสั่ง/ประกาศ | ไม่มีเทมเพลต Typst (มีเฉพาะ Word), คำสั่งไม่มี "สั่ง ณ วันที่" | เพิ่ม `templates/typst/order.typ` ตามรูปที่ 13–14 |

ต้องเขียนเทสต์ที่วัดตำแหน่งจริงจาก PDF (พิกัดจาก pdfplumber) ไม่ใช่แค่ตรวจว่าไฟล์สร้างได้

## 10. บทเรียนจาก Ekkasarn (จาก HAR ใน `EKKASARN_BENCHMARK.md` และภาพหน้าจอ)

| สิ่งที่เห็น | ผลต่อการออกแบบของเรา |
|---|---|
| อัปโหลดไฟล์ไปที่ path แบบ `/storage/v1/object/document-attachments/...` (รูปแบบเดียวกับ Supabase Storage) แล้วส่งแค่ path ให้ AI | ยืนยันแนวทาง signed upload ในข้อ 6 |
| ร่างตอบกลับเป็น NDJSON stream; ข้อความแรกโผล่ราว 63 วินาที | API ร่างต้องเป็น streaming (`StreamingResponse`) และหน้าเว็บแสดงสถานะทีละขั้น (อ่านไฟล์ → จำแนก → ร่าง) |
| จำแนกชนิดหนังสือเป็นขั้นแยกก่อนร่าง | มี `core/classifier.py` แล้ว ให้เป็น endpoint แยก |
| แยก `conversationId` / `caseId` / `documentId`, เก็บเวอร์ชันพร้อมคำสั่งแก้ (`editInstruction`) 7 วัน | เพิ่มตาราง `conversations` + `messages`; `document_versions` เก็บ `edit_instruction` |
| เก็บเนื้อหาเป็นข้อความล้วน มี `[ระบุ...]` | เราเก็บแบบโครงสร้าง (ตรวจระเบียบได้) — เป็นจุดแข็ง ให้คงไว้ |
| หน้าจอ: แชตซ้าย เอกสารขวา, ปุ่มไปยังช่องที่ต้องกรอกพร้อมตัวนับ, ดินสอแก้รายย่อหน้า, สถานะ "เอกสารพร้อมตรวจ", โหมด "ไม่ระบุตัวตน" | นำแนวคิดมาใช้ใน `web/` (ไม่คัดลอกหน้าตา/โค้ด) |
| วันที่ในร่างเว้นเลขวัน ("พฤศจิกายน ๒๕๖๙") | เพิ่มตัวเลือก "เว้นวันไว้ลงตอนลงนาม" |
| ข้อความ `thaiDistribute` ในภาพมีช่องว่างถ่างกว้างเป็นช่วง ๆ | ยืนยันว่าต้องมีตัวเลือกการจัดแนวตามข้อ 7 |
| หน้าแบบ กทม.: ขอบบน 1.5 ซม., "บันทึกข้อความ" 32 pt | ต่างจากคู่มือมาตรฐาน → เป็นโปรไฟล์ `bma` ไม่ใช่ค่าเริ่มต้น |
| ใช้ Next.js บน Vercel + Supabase (Auth, PostgREST, Storage) | ยืนยันว่าสแตกที่เลือกรองรับงานแบบนี้ได้จริง |
| AI เรียก "เครื่องมือร่างเอกสาร" เป็นรอบ ๆ แล้วเซิร์ฟเวอร์ปรับผลก่อนบันทึก (เช่น ลบเลขวันที่ AI ใส่มา) | ผลจาก AI ต้องผ่าน `core/` (linter, กฎวันที่/เลขที่) ทุกครั้งก่อนบันทึก ไม่เชื่อข้อความที่ stream มา |
| นับโควตา: จำนวนเอกสาร, รอบแชต, หน้า OCR, พื้นที่เก็บไฟล์ | ตาราง `ai_usage` + จำกัดโควตาต่อวัน กันค่า AI บานปลาย |
| หน้าร่างเอกสารฝัง Clarity (บันทึกหน้าจอ), TikTok pixel, Google Analytics | **ระบบเราห้ามใส่ตัวติดตามแบบนี้** เพราะเนื้อหาเป็นเอกสารราชการ |

## 11. ลำดับการทำงาน

1. **แก้บั๊กกลุ่มเร่งด่วน** ในโค้ดเดิม พร้อมเทสต์ (path traversal ของ `/extract`, escape HTML, เวลา Asia/Bangkok, ชั้นความเร็ว 32 pt) และ**แก้ตำแหน่งในเทมเพลต Typst ตามข้อ 9.1** พร้อมเทสต์วัดพิกัด
2. **ปรับโครงสร้าง:** แยก `server/` ออกจาก `core/`, ย้าย Streamlit ไป `legacy/`, แยก requirements, ทำให้ `core/` ไม่มี I/O
3. **Supabase:** สร้างโปรเจกต์ (Singapore), เขียน migrations (ตาราง + `issue_reg_no` + RLS + audit trigger), ปิด signup, สร้างบัญชีทดสอบ
4. **Auth + API:** ตรวจ JWT, router ใหม่ต่อ Supabase, signed upload
5. **หน้าเว็บ:** หน้า login, เปลี่ยน localStorage เป็น API, หน้าทะเบียนรับ-ส่ง
6. **Deploy:** `vercel.json`, ตั้ง env ใน Vercel, deploy preview จาก branch, วัดขนาด function
7. **อัปเดตเอกสาร:** AGENTS.md, SARABAN_RULES.md, README.md, DESIGN.md, EXPORT_ENGINE.md ให้ตรงกับข้อ 7–8 และรวมเอกสารที่ซ้ำกัน
