---
name: thai-govdoc-ux-frontend
description: UX/UI และ frontend architecture สำหรับ Thai GovDoc AI Studio — ระบบร่างหนังสือราชการไทย (Streamlit prototype + FastAPI core + A4 preview + Word/PDF export) ใช้เมื่อออกแบบหรือตรวจหน้าจอ เขียน microcopy ไทย จัดลำดับ workflow ตรวจ accessibility หรือปรับ frontend ก่อนย้ายไป Next.js
---

# Thai GovDoc UX/UI + Frontend

## 1. ใช้ skill นี้เมื่อไหร่

ใช้เมื่อทำงานเกี่ยวกับ:

- ออกแบบ/ตรวจหน้าจอ Workspace, ฟอร์ม, ป็อปอัป, แถบสถานะ, ตารางตรวจร่าง
- เขียนหรือตรวจ microcopy ภาษาไทยใน UI
- ปรับ `web/app.py` (Streamlit) โดยไม่ทำ logic ใน `core/` เสียหาย
- วางโครง frontend สำหรับ production (Next.js/FastAPI)
- ตรวจ UX ของ workflow รับมอบหมาย → OCR → ถามข้อมูล → ยืนยันชนิด → ร่าง → ตรวจ → บันทึก → ส่งออก
- ตรวจ accessibility, responsive layout, typography ไทย, A4 fidelity

ไม่ใช้ skill นี้แทนกฎธุรกิจใน `AGENTS.md`, `SARABAN_RULES.md` หรือ `DEVELOPMENT_PLAN.md` — skill นี้เสริมด้าน UX/UI และ frontend เท่านั้น

---

## 2. หลักเหล็กของผลิตภัณฑ์ (ห้ามละเมิด)

1. **Human-in-the-loop:** AI ช่วยอ่าน/ร่าง/ตรวจ แต่ผู้ใช้เป็นผู้ยืนยันและส่งออก
2. **ห้ามแต่งข้อเท็จจริง:** ชื่อ หน่วยงาน เลขที่ วันที่ จำนวนเงิน กำหนดการ กฎหมาย และสิ่งที่ส่งมาด้วย ต้องมาจากต้นเรื่อง ผู้ใช้ หรือโปรไฟล์
3. **ข้อมูลขาด = ถามหรือ placeholder:** ใช้ `[✏️ ระบุ...]` หรือคำถาม intake ห้ามเติมข้อความที่ดูสมเหตุสมผลเอง
4. **กฎหมายต้องมีแหล่ง:** ใช้เฉพาะรายการที่ผู้ใช้ยืนยันในคลังข้อกฎหมาย; ไม่พบแหล่ง → แจ้ง “ไม่พบแหล่งยืนยัน” และไม่ใส่
5. **ความปลอดภัยอยู่ที่ backend:** `secret` / `allow_cloud` ต้องถูกบังคับใน `core/extractor.py`, `core/ai_drafter.py`, `core/security.py`, `core/api.py` — UI เป็นเพียงตัวส่งค่า
6. **ห้ามเพิ่มปุ่ม/เมนูที่ยังไม่มี backend รองรับ**
7. **รักษารูปแบบราชการ:** ฟอนต์ TH Sarabun New/PSK, ขนาด 16 pt, ครุฑ 3/1.5 ซม., เลขไทย/อารบิก, A4 preview, Word/PDF เดิม
8. **ไม่ auto-approve / ไม่ auto-send:** ทุกการส่งออกต้องมีการยืนยันของผู้ใช้

---

## 3. Workflow UX ที่ต้องสะท้อนบนหน้าจอ

```text
1. รับมอบหมาย
   ├─ พิมพ์สรุปงาน
   └─ แนบไฟล์ต้นเรื่อง
2. OCR / สกัดข้อความ
   ├─ แสดงสถานะกำลังอ่าน
   ├─ แสดง engine ที่ใช้
   └─ แสดงจุดที่อ่านไม่ชัด
3. ตรวจข้อมูลที่ขาด
   ├─ ถามเฉพาะที่จำเป็น
   ├─ ผู้ใช้ตอบ หรือเลือกใช้ placeholder
   └─ ยังไม่ครบ → ปิดปุ่มร่าง
4. จำแนกชนิดหนังสือ + ผู้ใช้ยืนยัน
5. ร่างหนังสือ
6. ตรวจร่างเทียบต้นเรื่อง
   ├─ พบหลักฐาน
   ├─ ไม่พบหลักฐาน
   └─ ต้องยืนยัน
7. ตรวจภาษา/ระเบียบ
8. แก้ไข + เปรียบเทียบเวอร์ชัน + บันทึก
9. ส่งออก Word/PDF (เมื่อผู้ใช้ยืนยัน)
```

### สถานะที่ผู้ใช้ต้องเห็นตลอดเวลา

- เอกสารชนิดอะไร
- ชั้นความลับ / ชั้นความเร็ว
- จำนวน placeholder ที่ยังค้าง
- สถานะบันทึก: ฉบับร่าง / กำลังแก้ไข / บันทึกแล้ว
- จำนวนข้อตรวจที่ยัง pending (ถ้ามี Step 2)
- AI ภายนอกถูกใช้หรือถูกบล็อก

---

## 4. Layout หลัก

### 4.1 Desktop

```text
┌──────────────────────────────────────────────────────────────┐
│ Top bar: ชื่อระบบ + สถานะ privacy + หน่วยงาน                  │
├───────────────────────────┬──────────────────────────────────┤
│ ซ้าย: ต้นเรื่อง            │ ขวา: ร่าง / A4 preview / editor   │
│ - อัปโหลด/วางข้อความ       │ - tabs: Preview | ฟอร์ม | ประวัติ  │
│ - สถานะ OCR               │ - status pills                    │
│ - entity + หลักฐาน        │ - A4 paper                        │
│ - คำถามข้อมูลที่ขาด        │ - ปุ่มดินสอ/popover               │
│ - องค์ประกอบเอกสาร         │ - Linter / ข้อตรวจ                │
├───────────────────────────┴──────────────────────────────────┤
│ Action bar: บันทึก | ตรวจระเบียบ | ส่งออก Word/PDF            │
└──────────────────────────────────────────────────────────────┘
```

### 4.2 Mobile / จอแคบ

- เรียงซ้ายบน ขวาล่าง
- ใช้ segmented control หรือ tabs ในการสลับ “ต้นเรื่อง / ร่าง”
- ห้ามซ่อนปุ่มหลัก (บันทึก/ส่งออก)
- ตารางตรวจร่างเปลี่ยนเป็นการ์ดแนวตั้ง

### 4.3 หลักการจัดวาง

- ใช้พื้นที่ว่างและเส้นแบ่งแทนการ์ดซ้อนกันหลายชั้น
- หนึ่งหน้าจอมี action หลักได้ไม่เกิน 2–3 ปุ่ม
- ปุ่มทำลายข้อมูล (ลบ/รีเซ็ต) ต้องมี confirm หรือแยกสี
- สถานะไม่ควรสื่อด้วยสีเพียงอย่างเดียว ต้องมีข้อความ/ไอคอน

---

## 5. Microcopy ภาษาไทย

### หลัก

- กระชับ ตรงการกระทำ ใช้คำที่เจ้าหน้าที่ราชการใช้จริง
- ปุ่มขึ้นต้นด้วยคำกริยา: “บันทึก”, “ตรวจระเบียบ”, “ส่งออก Word”
- หลีกเลี่ยงคำเทคนิคที่ไม่จำเป็น: “payload”, “endpoint”, “token”
- บอกผลลัพธ์และสิ่งที่ต้องทำต่อ
- ข้อผิดพลาดต้องบอกสาเหตุ + ทางแก้

### ตัวอย่าง

| บริบท | ควรใช้ | ไม่ควรใช้ |
|---|---|---|
| ปุ่มร่าง | “ยกร่างหนังสือ” | “Generate” |
| ข้อมูลขาด | “กรุณาระบุเรื่องก่อนยกร่าง” | “Validation failed” |
| ชั้นลับ | “เอกสารชั้นลับจะไม่ส่งให้ AI ภายนอก” | “Secret policy enforced” |
| OCR ไม่ชัด | “อ่านบางส่วนไม่ชัด กรุณาตรวจสอบ” | “OCR confidence 0.42” |
| กฎหมาย | “ไม่พบแหล่งยืนยัน จึงยังไม่ใส่ข้อกฎหมาย” | “Law not found” |
| บันทึก | “บันทึกแล้ว” | “Saved successfully!!!” |

### โทน

- สุภาพแต่ไม่เยิ่นเย้อ
- ใช้ “กรุณา” เฉพาะเมื่อจำเป็น
- ไม่ใช้คำขู่หรือคำเกินจริง
- ไม่ใช้ “AI ฉลาด/แม่นยำ 100%” หากไม่มีหลักฐาน

---

## 6. Component Patterns

### 6.1 Placeholder

- แสดงเป็น chip สีอ่อน อ่านออก มีไอคอน ✏️
- คลิกเพื่อเปิดป็อปอัปเติมข้อมูล
- หลังเติมแล้ว chip ต้องหาย
- ห้ามแสดง placeholder เป็นข้อความธรรมดาที่แยกไม่ออก

### 6.2 ข้อมูลที่สกัดได้ + หลักฐาน

- แสดง `field`, `value`, `source_quote` และสถานะ
- ถ้าเป็นค่าที่ควรตรวจ: ป้าย “ควรตรวจ”
- ถ้าไม่มีหลักฐาน: แสดง “ไม่พบหลักฐาน” ไม่เดา
- ห้ามแสดงเปอร์เซ็นต์ OCR confidence เว้นแต่ได้จาก engine จริง

### 6.3 ข้อตรวจร่าง

ใช้สถานะ 3 ค่า:

- ✅ พบหลักฐาน
- ⚠️ ต้องยืนยัน
- ❌ ไม่พบหลักฐาน

แต่ละข้อมี:
- ข้อความในร่าง
- หลักฐาน/ตำแหน่ง (ถ้ามี)
- คำแนะนำ
- ปุ่ม “ยอมรับ” / “ปฏิเสธ”
- เมื่อตัดสินใจแล้วบันทึกใน Audit Trail

### 6.4 คลังข้อกฎหมาย

- แยกสถานะ “ยืนยันแล้ว” / “ยังไม่ยืนยัน”
- เลือกใช้ได้เฉพาะรายการที่ยืนยันแล้ว
- แสดงชื่อ, มาตรา/ข้อ, แหล่ง, วันที่มีผล
- ถ้าไม่มีรายการ → แจ้ง “ยังไม่มีข้อกฎหมายที่ยืนยันแล้ว” พร้อมลิงก์ไปหน้าตั้งค่า

### 6.5 ปุ่มดินสอ / แก้ไขด่วน

- ใช้ `st.popover` สำหรับแก้ไขในบริบท
- อย่าบังคับผู้ใช้สลับแท็บเพียงเพื่อแก้ช่องเดียว
- ภายในป็อปอัปมีช่องข้อความ + ปุ่มบันทึก + คำอธิบายสั้น
- หลังบันทึก rerun และป็อปอัปปิด

---

## 7. Frontend Architecture — Streamlit (ปัจจุบัน)

### 7.1 ขอบเขต

- `web/app.py` = UI orchestration เท่านั้น
- `core/` = domain logic (models, extractor, intake, classifier, drafter, linter, sections, exporters, audit)
- ห้ามคัดลอก logic จาก `core/` ไปไว้ใน UI
- เรียกใช้ฟังก์ชันเดิมก่อนสร้างใหม่: `extract_source_document`, `assess_intake`, `classify_source_document`, `draft_from_context_*`, `lint_gov_document`, `export_govdoc_to_docx`

### 7.2 Session state

- ใช้ `st.session_state.doc_data` เป็นแหล่งความจริงของเอกสาร
- เก็บสถานะ workflow แยก: `source_context`, `classification`, `intake_ready`, `intake_answers`, `selected_law_id`, `doc_secret_level`
- ตั้งค่า default ทุก key ก่อนใช้
- ระวัง key ซ้ำเมื่อมีหลาย branch (internal/external) — ใช้ suffix หรือ render branch เดียว

### 7.3 Rerun discipline

- `st.rerun()` หลังแก้ข้อมูลที่ต้องให้ UI อัปเดต
- อย่า rerun ในลูปโดยไม่มีเงื่อนไข
- callback `on_change` ใช้เมื่อต้องบันทึกทันที
- หลีกเลี่ยงการแก้ `session_state` หลัง widget ถูกสร้างในรอบเดียวกัน

### 7.4 HTML / A4 preview

- ใช้ `compact_html()` ตัด indentation ก่อน `st.markdown(..., unsafe_allow_html=True)` เพื่อไม่ให้ HTML กลายเป็น code block
- ห้ามใส่ HTML ที่เยื้อง 4+ ช่องใน markdown
- ระวัง tag ไม่สมดุล (`<div>`/`</div>`) โดยเฉพาะเมื่อผู้ใช้ลบหัวข้อ
- ใช้ CSS class กลาง: `a4-paper`, `a4-indent`, `memo-body`, `memo-heading`, `memo-request`

### 7.5 Dialog vs Popover

- งานแก้ไขสั้นในบริบท → `st.popover`
- งานหลายขั้นตอน/ต้องโฟกัส → `st.dialog` (ถ้าทดสอบแล้วว่าเปิดได้)
- อย่าใช้ dialog ซ้อน dialog
- ทดสอบจริงในเบราว์เซอร์ เพราะ `AppTest` ไม่ render dialog

### 7.6 ข้อจำกัดที่ต้องรู้

- Streamlit rerun ทั้งสคริปต์ทุก interaction
- ไม่มี client-side routing ที่แท้จริง
- ไม่เหมาะกับผู้ใช้พร้อมกันมากใน production
- ถ้าต้อง multi-user/auth/queue → วางแผนย้ายเป็น Next.js + FastAPI ตาม `ONLINE_PRODUCTION_PLAN.md`

---

## 8. Frontend Architecture — Next.js (อนาคต)

### 8.1 โครง

```text
apps/web (Next.js)
  ├─ app/workspace
  ├─ components/document/
  │   ├─ SourcePanel
  │   ├─ IntakeQuestions
  │   ├─ ClassificationCard
  │   ├─ A4Preview
  │   ├─ SectionEditor
  │   ├─ VerificationPanel
  │   └─ ExportBar
  ├─ lib/api-client
  └─ lib/session
```

### 8.2 หลัก

- UI ไม่ถือ business rules; เรียก API
- ใช้ TypeScript types ที่ generate จาก Pydantic/OpenAPI
- แยก state: server state (documents) vs UI state (tabs, popovers)
- ใช้ optimistic update เฉพาะฟิลด์ที่ปลอดภัย
- ห้าม cache เอกสารลับใน browser storage
- A4 preview ต้องใช้ฟอนต์และ layout เดียวกับ exporter

### 8.3 API contract ที่ควรมี

- `POST /documents/upload`
- `POST /documents/{id}/intake/questions`
- `POST /documents/{id}/classify`
- `POST /documents/{id}/draft`
- `PUT /documents/{id}/sections`
- `POST /documents/{id}/verify`
- `POST /documents/{id}/legal-references`
- `POST /documents/{id}/export`

---

## 9. Accessibility & Typography

- ตัวอักษรเนื้อหาขั้นต่ำ 14–16 px บนเว็บ; เอกสารจริง 16 pt
- Contrast อย่างน้อย 4.5:1 สำหรับข้อความปกติ
- ห้ามใช้สีอย่างเดียวบอกสถานะ
- ปุ่มต้องมี label ที่อ่านด้วย screen reader ได้
- Target size อย่างน้อย 40×40 px
- รองรับการซูม 200% โดยไม่ทับกัน
- ใช้ภาษาไทยเป็นหลัก; English เฉพาะคำเทคนิคที่จำเป็น

---

## 10. Design Tokens (แนะนำ)

```text
Font: TH Sarabun New / TH Sarabun PSK
Body: 16px (web), 16pt (document)
Heading: 20–29pt ตามประเภท
Spacing: 4 / 8 / 12 / 16 / 24 / 32
Radius: 8–12px
Primary: น้ำเงินราชการหรือโทนหน่วยงาน
Warning: amber
Danger: red
Success: green
Muted: slate
Paper: #FFFFFF
Background: #F8FAFC
```

---

## 11. Checklist ตรวจ UI ก่อนส่งงาน

- [ ] ผู้ใช้เริ่มงานได้จากหน้าแรกโดยไม่ต้องเดา
- [ ] ทุกปุ่มมี backend รองรับจริง
- [ ] สถานะ OCR / ขาดข้อมูล / ชนิด / ร่าง / ตรวจ / บันทึก / ส่งออก มองเห็น
- [ ] ข้อมูลขาดถูกถามหรือเป็น placeholder ไม่ถูกเดา
- [ ] ข้อความสำคัญ (ชื่อ/วันที่/เลขที่/จำนวนเงิน) มีหลักฐานหรือแจ้ง “ไม่พบ”
- [ ] ไม่มีการแก้ข้อความสำคัญอัตโนมัติโดยไม่ยืนยัน
- [ ] เอกสารชั้นลับไม่ถูกส่งออก AI ภายนอก (ทดสอบ backend)
- [ ] A4 preview ไม่เป็น code block และ indentation ถูก
- [ ] ฟอนต์/เลขไทย/อารบิก/ครุฑ/ขอบกระดาษยังถูกต้อง
- [ ] Word/PDF ยังดาวน์โหลดได้
- [ ] Audit Trail ถูกบันทึก
- [ ] จอแคบใช้งานได้ ไม่มีปุ่มถูกซ่อน
- [ ] ข้อความไทยอ่านง่าย ไม่ใช่คำแปลตรงตัว

---

## 12. Anti-patterns

- เพิ่มปุ่ม “AI ทำทั้งหมด” โดยไม่มีขั้นยืนยัน
- แสดงเปอร์เซ็นต์ความมั่นใจปลอม
- ใช้สีแดง/เขียวอย่างเดียวบอกผลตรวจ
- ให้ AI เติมชื่อ/เลขที่/วันที่/จำนวนเงินเอง
- ใส่ HTML เยื้องใน `st.markdown`
- ใช้ dialog ซ้อน dialog หรือ popover ที่มีปุ่มซ้อนหลายชั้น
- สร้าง state ซ้ำระหว่าง `sections` กับฟิลด์เดิมโดยไม่ sync
- แสดง error แบบ `Exception: ...` ให้ผู้ใช้เห็น
- ซ่อนข้อจำกัดของระบบเพื่อให้ดูดี

---

## 13. ไฟล์อ้างอิงในโปรเจกต์

| ไฟล์ | หน้าที่ |
|---|---|
| `web/app.py` | UI หลัก (Streamlit) |
| `core/models.py` | Pydantic schemas |
| `core/intake.py` | คำถามข้อมูลที่ขาด |
| `core/entity_extractor.py` | สกัด entity + หลักฐาน |
| `core/legal_sources.py` | คลังข้อกฎหมาย |
| `core/linter.py` | ตรวจระเบียบ |
| `core/sections.py` | หัวข้ออิสระ |
| `core/word_exporter.py` | Word export |
| `core/typst_exporter.py` / `core/pdf_exporter.py` | PDF export |
| `AGENTS.md` | กฎโครงการ |
| `SARABAN_RULES.md` | กฎหมายสารบรรณ |
| `ONLINE_PRODUCTION_PLAN.md` | แผน production |

---

## 14. วิธีตรวจงาน UI

1. รัน `pytest -q` — ต้องไม่ถดถอย
2. เปิด Streamlit และทดสอบ flow จริง
3. ตรวจ A4 preview ด้วยตาทุกครั้งหลังแก้ HTML/CSS
4. ทดสอบกรณีลบหัวข้อ/อ้างถึง/สิ่งที่ส่งมาด้วย
5. ทดสอบเอกสารชั้นลับ + ปิด cloud
6. ทดสอบ Word/PDF ว่าเปิดได้และหน้าตาไม่เพี้ยน
7. ตรวจ mobile width ถ้ามีเวลา
8. บันทึกข้อจำกัดที่ยังเหลือในรายงาน
