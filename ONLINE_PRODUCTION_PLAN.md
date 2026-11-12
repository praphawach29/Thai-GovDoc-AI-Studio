# แผนนำระบบขึ้นใช้งานจริงแบบออนไลน์
## Thai GovDoc AI Studio — Production & Online Deployment Plan

**เวอร์ชัน:** 1.0  
**วันที่:** 13 พฤศจิกายน 2569  
**สถานะ:** แผนแนะนำสำหรับนำร่องและขึ้นProduction  
**เจ้าของระบบ:** สำนักวัฒนธรรม กีฬา และการท่องเที่ยว กรุงเทพมหานคร

---

## 1. บทสรุปผู้บริหาร

ระบบปัจจุบันเป็น **prototype ที่ทำงานได้จริงในเครื่องเดียว** (Streamlit + FastAPI core + Word/Typst exporter) มีจุดแข็งคือกฎราชการไทย, การจำแนกหนังสือ 6 ชนิด, หัวข้อเอกสารอิสระ, การตรวจ Linter และการบล็อก AI ภายนอกสำหรับเอกสารชั้นลับ

การนำขึ้นใช้ออนไลน์จริงไม่ควรเปิด Streamlit โล่ง ๆ สู่ الإنترنت เพราะยังขาด:
- ระบบยืนยันตัวตนและสิทธิ์ (Authentication / RBAC)
- ฐานข้อมูลกลางและ audit trail ที่แก้ไขไม่ได้
- พื้นที่จัดเก็บไฟล์ที่ปลอดภัย
- คิวงาน OCR/PDF ที่รองรับผู้ใช้พร้อมกัน
- การเชื่อมทะเบียนสารบรรณและเลขที่หนังสือ
- นโยบายข้อมูลชั้นความลับ/PDPA

**ข้อแนะนำ:** แยกเป็น 2 ระยะ
1. **Pilot ภายใน (4–6 สัปดาห์):** Streamlit + Reverse Proxy + SSO + PostgreSQL + MinIO + Audit ในเครื่องแม่ข่ายของหน่วยงาน
2. **Production (3–5 เดือน):** FastAPI + Next.js + Worker Queue + PostgreSQL + Object Storage + AI Gateway + e-Saraban integration

---

## 2. สถานะปัจจุบันและช่องว่าง

| ด้าน | ปัจจุบัน | ต้องมีก่อนใช้จริง |
|---|---|---|
| Frontend | Streamlit `web/app.py` | Next.js/React หรือ Streamlit หลัง SSO (pilot) |
| Backend | FastAPI `core/api.py` + core modules | API Gateway, rate limit, versioning |
| ฐานข้อมูล | SQLite ไฟล์ lokal (`data/`) | PostgreSQL + backup + PITR |
| ไฟล์แนบ | `uploads/` บนเครื่อง | Object Storage (MinIO/S3) + encryption |
| ประมวลผล OCR | ทำใน request | Worker queue + progress + retry |
| AI | เรียก Gemini/OpenAI ตรง | AI Gateway + redaction + policy |
| Auth | ไม่มี | OIDC/SSO + MFA + RBAC |
| Audit | ตาราง audit lokal | Audit log กลาง + hash chain/WORM |
| เลขหนังสือ | กรอกเอง/ทะเบียน lokal | เชื่อมทะเบียนสารบรรณ + reserve number |
| PDF/DOCX | Typst/Word exporter | Worker + PDF/A + digital signature |
| Observability | print/log | Metrics, tracing, alerting |

---

## 3. เป้าหมายการให้บริการ (SLA)

| รายการ | เป้าหมาย |
|---|---|
| Availability | 99.5% (pilot) → 99.9% (production) |
| เวลาสร้างร่างจากเอกสาร 1 หน้า | < 30 วินาที (ไม่รวม OCR นาน) |
| OCR เอกสารสแกน 1 หน้า | < 60 วินาที/หน้า |
| Export Word/PDF | < 10 วินาที/ฉบับ |
| RPO (ข้อมูลสูญหายได้ไม่เกิน) | 15 นาที |
| RTO (กลับมาใช้งานได้ภายใน) | 4 ชั่วโมง |
| Audit retention | 5–10 ปี ตามนโยบายหน่วยงาน |
| จำนวนผู้ใช้พร้อมกัน | 50 (pilot) → 500 (production) |

---

## 4. สถาปัตยกรรมแนะนำ (Production)

```text
[ผู้ใช้ราชการ]
      │ HTTPS / OIDC
      ▼
[Reverse Proxy / WAF / Load Balancer]
      │
      ├── [Next.js Web App]  ── SSO (ThaiD / Entra ID / Keycloak)
      │
      └── [FastAPI API Gateway]
              │
              ├── [Auth & RBAC Service]
              ├── [Document Service] ── PostgreSQL
              ├── [Registry Service] ── PostgreSQL (reserve/outbound numbers)
              ├── [File Service] ───── MinIO / S3 (encrypted)
              ├── [AI Gateway] ─────── Gemini/OpenAI (normal only)
              │                       └─ Local OCR/AI (secret only)
              ├── [Job Queue] ──────── Redis
              │        │
              │        ├── [OCR Worker] (PaddleOCR/Tesseract Thai)
              │        ├── [DOCX/PDF Worker] (python-docx, Typst, LibreOffice)
              │        └── [AI Draft Worker] (LLM, template, Linter)
              │
              └── [Audit & Observability] ── OpenTelemetry, Loki, Grafana
```

### 4.1 Frontend
- **Production:** Next.js + React + TypeScript; split-screen ตาม AGENTS.md (ซ้าย source viewer, ขวา A4 editor)
- **Pilot:** คง Streamlit ได้ แต่ต้องอยู่หลัง reverse proxy + SSO และจำกัด IP/VP
- หน้าสำคัญ: Workspace, คลังเอกสาร, ทะเบียน, ผู้ใช้/สิทธิ์, Audit, ตั้งค่าหน่วยงาน

### 4.2 Backend
- คง `core/` เดิมเป็น domain layer (models, classifier, linter, sections, exporters)
- ห่อด้วย FastAPI endpoints:
  - `POST /documents/upload`
  - `POST /documents/{id}/classify`
  - `POST /documents/{id}/draft`
  - `PATCH /documents/{id}/sections`
  - `POST /documents/{id}/export`
  - `POST /documents/{id}/reserve-number`
  - `GET /audit/{id}`
- ใช้ idempotency key สำหรับ upload/export
- จำกัดขนาดไฟล์และชนิดไฟล์, scan malware

### 4.3 ฐานข้อมูล (PostgreSQL)
ตารางหลัก:
- `organizations`, `users`, `roles`, `user_roles`
- `documents` (id, org_id, kind, doc_type, status, current_version)
- `document_versions` (sections JSONB, schema JSONB, edited_by, edit_status, created_at)
- `files` (object_key, mime, size, sha256, virus_scan_status)
- `registry_numbers` (prefix, year, running_no, reserved_by, reserved_at, status)
- `audit_events` (actor, action, before/after hash, ip, user_agent, created_at)
- `ai_jobs` (provider, model, prompt_hash, source_redacted, status)
- `signatures` (document_id, signer, cert_serial, signed_at, hash)

ใช้ `JSONB` เก็บ `sections` เพื่อรองรับหัวข้ออิสระโดยไม่ต้อง migrate schema ทุกครั้ง

### 4.4 Object Storage
- MinIO (on-prem) หรือ S3-compatible
- เข้ารหัส AES-256 at rest, TLS 1.2+
- แยก bucket: `uploads`, `exports`, `audit-exports`
- ตั้ง lifecycle: ไฟล์ต้นเรื่อง 1–5 ปีตามนโยบาย; export 10 ปี
- ห้าม public bucket

### 4.5 Queue/Worker
- Redis + Celery/RQ/Arq
- งาน OCR, AI draft, PDF/DOCX export เป็น async job
- UI แสดง progress และ retry
- จำกัด concurrent ต่อผู้ใช้/หน่วยงาน

### 4.6 AI Gateway
- รวม Gemini/OpenAI ไว้หลัง gateway เดียว
- **Block** เอกสาร `secret`/`classified` ไม่ให้ออกภายนอก (ใช้ `core/security.py`)
- Redact ชื่อบุคคล/เลขบัตร/เบอร์โทร ก่อนส่ง (ถ้าเปิดใช้)
- บันทึก prompt hash + model + ผู้ใช้ โดยไม่เก็บเนื้อหาลับ
- Local fallback: rule-based/template + OCR ภายในเครื่อง

---

## 5. ความปลอดภัยและกฎหมาย

### 5.1 ชั้นข้อมูล
| ชั้น | การประมวลผล | AI ภายนอก |
|---|---|---|
| ปกติ | Cloud ได้ | ได้ |
| ลับ | On-prem/local เท่านั้น | ห้าม |
| ลับมาก | On-prem + เข้ารหัส | ห้าม |

### 5.2 มาตรการขั้นต่ำ
- SSO + MFA, session timeout 15–30 นาที
- RBAC: ผู้ใช้, ผู้ตรวจ, ผู้ลงนาม, ผู้ดูแลระบบ, ผู้ตรวจสอบ
- Least privilege; แยกสิทธิ์ตามหน่วยงาน
- Audit log ทุกการเปิด/แก้/ส่งออก/ลบ; hash chain หรือ WORM
- Encryption at rest/in transit; secret manager (Vault/KMS)
- Backup เข้ารหัส + ทดสอบ restore รายไตรมาส
- PDPA: consent, data minimization, retention, data subject request
- PDPA + พ.ร.บ.ธุรกรรมทางอิเล็กทรอนิกส์ สำหรับลายมือชื่ออิเล็กทรอนิกส์
- OWASP ASVS, dependency scan, SAST/DAST, pen test ก่อน production
- DLP: บล็อกการ export เอกสารลับออกนอกระบบตามนโยบาย

---

## 6. การเชื่อมระบบสารบรรณ (e-Saraban)

### 6.1 ทะเบียนเลขที่หนังสือ
- ใช้ transaction `SELECT ... FOR UPDATE` เพื่อกันเลขซ้ำ
- Flow:
  1. ผู้ใช้กด "ขอเลขที่"
  2. ระบบ reserve เลข (`......../2569` → running number)
  3. บันทึก `registry_numbers` สถานะ `reserved`
  4. เมื่อส่งออก/ลงนาม → `used`
  5. ยกเลิก → `cancelled` พร้อมเหตุผล
- ถ้ายังไม่เชื่อมระบบกลาง ใช้เลขแบบเว้นช่อง `......../2569` และให้เจ้าหน้าที่กรอกเอง

### 6.2 e-Saraban Integration
- Inbound: รับหนังสือเข้า через API/email gateway
- Outbound: ส่งหนังสือออกพร้อม PDF/A-3 + metadata XML
- Digital signature: XAdES/PAdES ตามนโยบาย; ใช้ HSM/USB token
- Timestamp: TSA ตามมาตรฐาน
- ถ้าไม่มี API: export ชุดไฟล์ + CSV สำหรับนำเข้า manual

---

## 7. รูปแบบการติดตั้ง

### Option A: On-Prem / Government Data Center (แนะนำ)
- เหมาะกับเอกสารลับและข้อกำหนด data residency
- Kubernetes หรือ Docker Compose
- ข้อดี: ควบคุมข้อมูล, เชื่อม AD/SSO ภายใน, ไม่มีค่า egress
- ข้อเสีย: ต้องมีทีม ops, ลงทุนเครื่อง/สำรอง

### Option B: Hybrid
- Web/API/DB บน cloud ภาครัฐ (G-Cloud) หรือ private cloud
- OCR/AI/เอกสารลับอยู่ on-prem
- เหมาะกับหน่วยงานที่มีข้อมูลลับและต้องการ scalability
- ต้องมี VPN/Private Link

### Option C: SaaS Multi-tenant
- เหมาะกับ pilot หลายหน่วยงาน
- ต้องมี tenant isolation, encryption ต่อ tenant, สัญญา DPA
- ไม่แนะนำสำหรับเอกสารลับระยะแรก

**คำแนะนำ:** เริ่ม Option A (pilot) → Hybrid (production) หากต้องการขยาย

---

## 8. ขนาดเครื่องและต้นทุนเบื้องต้น (indicative)

### Pilot (50 ผู้ใช้)
| ทรัพยากร | สเปก |
|---|---|
| App VM | 8 vCPU / 32 GB RAM / 500 GB SSD |
| DB | 4 vCPU / 16 GB / 500 GB |
| Object Storage | 2 TB |
| Backup | 2 TB |
| GPU | ไม่จำเป็น (ใช้ cloud AI เฉพาะปกติ) |

### Production (500 ผู้ใช้)
| ทรัพยากร | สเปก |
|---|---|
| Web/API | 3 × (4 vCPU / 8 GB) |
| Worker OCR/Export | 2 × (8 vCPU / 32 GB) |
| PostgreSQL | 8 vCPU / 32 GB + replica |
| Redis | 4 GB |
| Object Storage | 10–20 TB |
| GPU (ถ้าใช้ local OCR/VLM) | 1 × L4/A10 หรือมากกว่า |

**ต้นทุนคร่าว ๆ**
- On-prem pilot: 300,000–600,000 บาท (เครื่อง + ติดตั้ง)
- Cloud hybrid: 40,000–120,000 บาท/เดือน (ขึ้นกับ storage/AI)
- Production on-prem: 1.5–3 ล้านบาท (HA + backup + GPU ถ้ามี)
- ค่าพัฒนา production: 1.5–3 ล้านบาท (ขึ้นกับขอบเขต e-Saraban/signature)

> ตัวเลขเป็นเพียงประมาณการ ต้องประเมินจากจำนวนผู้ใช้ ปริมาณเอกสาร และข้อกำหนดจัดซื้อจริง

---

## 9. CI/CD และสภาพแวดล้อม

- **Dev:** เครื่องนักพัฒนา + SQLite/MinIO local
- **Staging:** เหมือน production ขนาดย่อ, ข้อมูล anonymize
- **Production:** HA, backup, monitoring
- Pipeline:
  1. Lint + unit tests (135 tests)
  2. Build Docker image (API, worker, web)
  3. Scan dependency/image (Trivy)
  4. Deploy staging + smoke test
  5. Manual approval
  6. Blue-green/rolling deploy production
- Database migration: Alembic, backward compatible
- Feature flags สำหรับ AI/exports

---

## 10. Observability และ Backup

- Metrics: request latency, error rate, queue depth, OCR duration, export failures
- Logs: structured JSON, ไม่ log เนื้อหาลับ
- Tracing: OpenTelemetry
- Alert: PagerDuty/LINE Notify/อีเมล
- Backup:
  - DB: daily full + WAL 15 นาที
  - Object storage: versioning + cross-region/offsite
  - ทดสอบ restore ทุกไตรมาส
- DR runbook: RTO 4 ชม., RPO 15 นาที

---

## 11. แผนนำร่องและขึ้นProduction

### Phase 0: เตรียมความพร้อม (1–2 สัปดาห์)
- ยืนยันขอบเขต, ผู้ใช้ pilot, นโยบายข้อมูล
- ตั้ง domain/SSL, SSO test
- สร้าง staging

### Phase 1: Pilot ภายใน (4–6 สัปดาห์)
- Streamlit + FastAPI หลัง reverse proxy + SSO
- PostgreSQL + MinIO + audit
- ฝึกผู้ใช้ 10–20 คน
- เก็บ KPI: เวลาร่าง, จำนวนแก้ไข, error rate
- **Gate:** ผู้ใช้ยอมรับ >80%, ไม่มีข้อมูลลับออกนอก

### Phase 2: Production MVP (8–12 สัปดาห์)
- Next.js workspace + FastAPI endpoints
- Worker queue + progress
- Registry reserve number
- RBAC + audit + backup
- PDF/A + Word template ราชการ
- **Gate:** UAT ผ่าน, pen test ไม่มี critical

### Phase 3: e-Saraban & Signatures (8–12 สัปดาห์)
- เชื่อมทะเบียนกลาง/ส่งออก e-Saraban
- Digital signature/HSM
- SSO หน่วยงาน, multi-tenant (ถ้าต้องการ)
- **Gate:** ส่งออก/รับเข้าจริงได้, audit ครบ

### Phase 4: ขยายผล (ต่อเนื่อง)
- OCR local/GPU, fine-tune
- Dashboard ผู้บริหาร
- Mobile/tablet view
- วิเคราะห์คุณภาพร่างและต้นทุน AI

---

## 12. ความเสี่ยงและมาตรการลด

| ความเสี่ยง | ผลกระทบ | มาตรการ |
|---|---|---|
| ข้อมูลลับรั่วไป AI | สูงมาก | Block ที่ backend, DLP, audit, training |
| เลขหนังสือซ้ำ | สูง | DB transaction/reserve, unique constraint |
| Streamlit รองรับผู้ใช้มากไม่ได้ | กลาง | Pilot จำกัดคน, production ย้าย Next.js |
| OCR ไทยผิดพลาด | กลาง | Local OCR + human review + confidence |
| AI สร้างเลข/วันที่เอง | สูง | P0 guard + linter + placeholder |
| PDF ไทยตัดบรรทัดผิด | กลาง | ZWSP + Typst fallback + visual check |
| ต้นทุน AI บานปลาย | กลาง | Quota, cache, rule-based fallback |
| ขาดทีม ops | กลาง | Managed service หรือสัญญา support |

---

## 13. Checklist ก่อนเปิดใช้จริง

- [ ] SSO + MFA ใช้งานได้
- [ ] RBAC ครบ 5 บทบาท
- [ ] เอกสารลับไม่ออกนอกเครือข่าย (ทดสอบ)
- [ ] Audit log เปิดและตรวจย้อนหลังได้
- [ ] Backup/restore ผ่านการทดสอบ
- [ ] เลขหนังสือ reserve ไม่ซ้ำ
- [ ] Word/PDF ผ่านตรวจ formatting ราชการ
- [ ] Linter ทำงานกับเอกสารจริง
- [ ] PDPA notice + retention policy
- [ ] Pen test ไม่มี critical/high
- [ ] Runbook + ผู้รับผิดชอบ on-call
- [ ] UAT sign-off

---

## 14. สิ่งที่ต้องตัดสินใจจากผู้บริหาร

1. **ติดตั้งที่ไหน:** on-prem / G-Cloud / hybrid
2. **ขอบเขต Phase 1:** ใช้ Streamlit pilot หรือไป Next.js เลย
3. **e-Saraban:** เชื่อม API กลางหรือ export manual ก่อน
4. **ลายมือชื่ออิเล็กทรอนิกส์:** ใช้หรือไม่ และใช้ CA ใด
5. **งบประมาณและทีม ops:** ภายในหรือ outsourced
6. **นโยบาย AI:** อนุญาต cloud AI เฉพาะชั้นปกติหรือไม่
7. **ระยะเวลา:** pilot 4–6 สัปดาห์ หรือเร่ง production

---

## 15. สองสัปดาห์ถัดไป (Action Items)

1. ยืนยันผู้ใช้ pilot 10–20 คน และเอกสารตัวอย่าง 20 ฉบับ
2. ตั้ง PostgreSQL + MinIO + reverse proxy ใน staging
3. ทำ SSO (Keycloak/Entra ID) ทดสอบ
4. ย้าย audit จาก SQLite → PostgreSQL
5. ทำ Docker image สำหรับ API/worker
6. ทดสอบเอกสารลับไม่ถูกส่งออก AI
7. วัดเวลาร่าง/แก้ไข/export จริง
8. สรุปผล pilot เพื่อตัดสินใจ Phase 2

---

## ภาคผนวก: Mapping กับโค้ดปัจจุบัน

| องค์ประกอบ | โค้ดปัจจุบัน | ต้องทำเพิ่ม |
|---|---|---|
| Domain models | `core/models.py` | คงไว้ |
| Classifier | `core/classifier.py` | เพิ่ม confidence/feedback |
| Sections | `core/sections.py` | เก็บ JSONB |
| Linter | `core/linter.py` | เพิ่มกฎตามหน่วยงาน |
| Word export | `core/word_exporter.py` | Worker + template ราชการ |
| Typst export | `core/typst_exporter.py` | ZWSP + PDF/A |
| Security | `core/security.py` | AI Gateway + DLP |
| Audit | `core/audit.py` | PostgreSQL + hash chain |
| Registry | `core/registry.py` | Transaction + API |
| UI | `web/app.py` | Next.js production |
| API | `core/api.py` | Auth, rate limit, idempotency |
