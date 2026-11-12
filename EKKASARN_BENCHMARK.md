# Ekkasarn AI: product benchmark for Thai GovDoc AI Studio

**Reviewed:** 12 November 2026  
**Evidence level:** Public product pages, one user-supplied HAR capture of a signed-in workflow, the existing Thai GovDoc AI Studio source, and a local parse of that HAR. This is a single-session observation, not a full product audit.

## Evidence and method

REA 6.8.0 is installed locally at `tools/rea` and can inspect a HAR offline with `rea inspect-web-network-capture <file> har`. REA's browser mode is passive CDP and requires a Chrome-family browser already signed in to the target, so the authenticated Ekkasarn workflow in this review was reconstructed from the supplied HAR rather than from a live attach.

The HAR was parsed locally. Credentials (cookies, bearer/refresh tokens, signed URLs) were removed with `scripts/sanitize_har.py` before analysis; only aggregate request shapes and layout facts are reported here. The capture supports observations about one recorded workflow, not complete product behaviour or internal architecture. See [REA browser observation guide](https://github.com/morluto/rea/blob/main/docs/guides/web/browser-observation.md).

> The original HAR contains live session material. Do not commit or redistribute it; revoke the Ekkasarn session if the captured refresh token may still be valid.

## Publicly evidenced capabilities

Ekkasarn presents a workflow spanning document drafting, checking several documents together and preparing annotation text, reusable official templates, asking questions over multiple PDF/image/Word files, legal and circular search, and audio-to-meeting-minutes/transcription. It advertises six official document types, Word export with embedded fonts, and a library of 300+ government forms. The site states that AI-generated documents should be reviewed before real use. These are vendor descriptions, not independently verified performance claims. See [Ekkasarn AI](https://www.ekkasarn.com/).

## Observed workflow in the supplied HAR

The capture records one complete path: create a memo conversation, upload a PDF attachment, send a prompt to the assistant, retrieve one saved draft version, then export a DOCX and finalize the session.

| Step | Request | Observed shape |
|---|---|---|
| 1. Create workspace | `POST /api/conversations` | `{docType, title, isIncognito}` → `{id, caseId}` |
| 2. Read case | `GET /api/cases/{caseId}` | case carries `state`, `version`, `docType`, `origin`, timestamps |
| 3. Upload source | `POST auth.../storage/v1/object/document-attachments/...` | attachment stored first; assistant later receives `{storagePath, name, mime, size}` |
| 4. Draft | `POST /api/assistant` | request `{conversationId, text, attachments[], turnId, isIncognito}`; response is **NDJSON** |
| 5. Version history | `GET /api/versions` | `{versions:[{versionNum, content, editInstruction, createdAt}], retentionDays}` |
| 6. Export | `POST /api/export` | `{content, docType, format:"docx", letterhead, divider, letterSpacingPt, exportFont, ...}` → DOCX binary |
| 7. Finalize | `PATCH /api/sessions/finalize` | `{sessionId, finalContent}` → `{success:true}` |
| 8. Download feedback | `POST /api/feedback/first-download` | `{step:"check"}` → `{eligible:true}` |

The assistant stream contained 44 frames: `step(draft_document,start)` → `draft_meta(mode:"create", docType:"memo", documentId)` → 34 `delta` chunks of plain document text → `produced` → `final` → `step(end)` → four `text` summary frames → `done`. The `done` frame reported provider `vertex`, model `gemini-3.8-flash`, 25,092 input tokens and 427 output tokens. Client telemetry recorded `assistant-read-file` at ~35 s, `classify` at ~17 s, and first draft text at ~63 s, with a progressive preview revealing five paragraphs.

Key observations:

- The document is stored as **plain text**, not as structured JSON sections. Placeholders are literal `[ระบุ...]` strings.
- **Classification is a separate flow** (`flow:"classify"`) before drafting, matching the vendor's "confirm the document type" step.
- `documentId`, `conversationId`, and `caseId` are distinct; case state `S1` and `version` suggest a lifecycle state machine.
- Attachment bytes go directly to object storage; the assistant references only the storage path.
- The draft was 2,389 characters with four placeholders. It contained `"จึงเรียนมาเพื่อโปรดพิจารณา"` (a standard memo closing) but no BMA four-section labels (`ต้นเรื่อง`, `ข้อเท็จจริง`, `ข้อพิจารณา`, `ข้อกฎหมาย`) — a review signal, not a defect, because not every memo uses that template.
- The API reported seven-day version retention with enforcement enabled.

## Document and layout evidence (exported DOCX)

The exported file was inspected at the OpenXML level:

| Item | Observed value |
|---|---|
| Page | A4 (11,906 × 16,838 twips) |
| Margins | left 3.0 cm, right 2.0 cm, top **1.5 cm**, bottom 2.0 cm, header 1.2 cm |
| Garuda | 1.5 cm (542,925 EMU), placed in the document body |
| Title "บันทึกข้อความ" | 32 pt (`w:sz=64`), exact line 35 pt |
| Body | 16 pt (`w:sz=32`), `w:jc="thaiDistribute"` |
| First-line indent | 2.5 cm (1,418 twips), 6 pt before |
| Character spacing | `w:spacing w:val="8"` in `styles.xml` = 0.4 pt (from `letterSpacingPt`) |
| Page numbers | `w:pgNumType w:fmt="thaiNumbers"` + `w:titlePg` (no number on first page) |
| Fonts | TH SarabunPSK regular + bold, **embedded** via `fontTable → embedRegular/embedBold → word/fonts/*.odttf` |
| Grid | `docGrid linePitch=360` |

This confirms the practical recipe for Word fidelity: embed the font, use `thaiDistribute`, set character spacing at style level, and control first-line indent/page numbering explicitly. It does **not** perform per-line glyph scaling; "compress/expand" in Word is justification plus character spacing.

## Comparison with this codebase

| Capability | Thai GovDoc AI Studio today | Adaptation |
|---|---|---|
| Drafting and export | Drafting intents, rule-based and model-backed drafting, DOCX/Typst/PDF, profile settings, and placeholders are implemented. DOCX export now supports ExportOptions, embedded New/IT9/PSK fonts, 0.4 pt spacing, Thai page numbers, and 1.5 cm memo top margin. | Keep the domain-specific format, BMA hierarchy, and export fidelity as the differentiator; validate required sections and make placeholders and review status visible before export. |
| Review and annotation | `MEMO_REVIEW`, source dossier, references/attachments, paragraph copilot, linter, and audit/diff are implemented. | Add side-by-side comparison of multiple source versions and explicit evidence links from draft claims to source passages. Never promote inferred content to verified fact. |
| Forms/templates | `PRESET_TEMPLATES` already supplies reusable templates. | Curate and tag by document type, work mission, authority, and last-reviewed date; distinguish verified official templates from editable examples. |
| Multi-document reading and OCR | Multi-engine OCR, preprocessing, dossier extraction, and fail-safe behavior are implemented. | Preserve the no-invention fail-safe; expose per-file extraction confidence and let users ask questions over the dossier with page-level citations. |
| Legal and circular lookup | Legal insertion helpers exist; a curated legal knowledge base is on the roadmap. | Make this the next priority: retrieve only from maintained primary texts, show instrument/version/effective date and exact provision, and require human confirmation. |
| Meeting audio | No audio transcription/minutes pipeline was found in the current source inventory. | Defer until core review and legal-source traceability are delivered; if added, keep transcript, agenda, decisions, and action items linked to timestamps and human review. |
| Organization/security | Profile and local workflow exist; enterprise account controls are not evidenced in this codebase review. | Before multi-user deployment, define access roles, retention/deletion, secret handling, and audit boundaries; do not infer Ekkasarn's controls beyond its public statements. |
| Document model | Structured fields (`memo_intro`, `memo_facts`, ...) with validation. | Add a full-text projection and parser for Word round-trip while retaining the structured model for linting and rules. |

## Applied from this benchmark (Sprint 1–8)

- `core/models.py`: `ExportOptions` (layout profile, font: New/PSK/IT9, letterhead, divider, letter spacing, embed flag, private flag).
- `core/layout_profile.py`: `LayoutProfile` + `standard_memo`, `standard_external`, `form_it9_2026` (margins/fonts/spacing/indent/header style/page numbers from the real memo).
- `core/hierarchy.py`: three-level memo chain (section → division → department → permanent secretary) with recipient/signatory/closing updates and a UI recipient dropdown.
- `core/classifier.py`: six official document kinds / forms 1–11 with keywords, confidence, reasons, and a confirmation card before drafting.
- `core/special_drafter.py`: rule-based generators for stamp letters, directives, public-relations documents, and evidence/meeting minutes, exported with a dedicated Word layout.
- `core/sections.py`: editable document-section list (12 section types, add/delete/reorder/visibility) synced back to legacy fields, with a Word renderer and A4 preview that follow the user's order.
- `core/word_exporter.py`: automatic character compression (`w:w`) for long department headers, and blank document-number format `......../พ.ศ.` for manual numbering.
- `core/docx_fonts.py`: OOXML font embedding (`fontTable` + `odttf` + relationships + content types + settings).
- `core/word_exporter.py`: profile-driven margins, style-level character spacing, segmented/dotted header, Thai/Arabic page numbers, optional garuda/divider, font selection.
- `web/app.py`: export-options panel (layout profile, font, garuda, divider, spacing, embedding) wired to the Word download; recipient dropdown and hierarchy chain UI; cloud-AI opt-out for sensitive documents.
- `core/security.py` + `core/thai_date.py`: block Gemini/OpenAI for classified documents, and never let AI invent document numbers/dates.
- `tests/test_phase9_export_options.py`: nine tests covering embedding, obfuscation, spacing, margins, page numbers, letterhead, divider, font selection, and the `form_it9_2026` profile.
- `tests/test_phase11_p0_safety.py`: eight tests covering placeholder document numbers, today's Thai date, cloud-AI blocking, and new linter rules.
- `tests/test_phase12_classifier.py`: six tests covering all six document kinds, form inference, forced selection, and low-confidence defaults.

Test suite after Sprint 1–8: **135 tests collected — 130 passed, 5 skipped, 0 failed** (five environment-dependent browser/OCR tests skip under the current sandbox).

## Recommended application sequence

1. **Source-grounded legal lookup (Phase 9):** create a curated, versioned legal corpus; return source title, issuing authority, provision, effective dates, URL, and retrieved excerpt; block unsupported legal citations; record which source informed each draft field.
2. **Document-type classifier and confirmation card (Sprint 2):** separate classification from drafting, show detected type with confidence and reasons, and require confirmation before generation.
3. **Full-text projection and Word round-trip (Sprint 3):** `to_document_text()` / `from_document_text()`, content-control tags on export, importer with diff/merge.
4. **Multi-document review (Phase 10):** compare incoming/replacement documents and prior drafts, show changed passages and their source/page, then generate a review memo from confirmed facts only. Reuse the existing dossier, audit, and `MEMO_REVIEW` components.
5. **Template governance:** expand the existing template library through a reviewed catalog with ownership, scope, and review date, rather than importing a large unverified form set.
6. **Audio minutes later:** implement only as a separate optional ingestion path with timestamped transcript provenance and the same approval-before-export gate.

## Guardrails carried forward

- AI output remains a draft; a responsible officer reviews it before official use.
- Never fabricate laws, source metadata, or facts missing from the input. Mark unknown values as placeholders.
- Citations must resolve to a source document and page/section where available.
- Keep Thai GovDoc-specific rules intact: Thai official document structure, hierarchy-aware language, TH Sarabun export, and DOCX/PDF layout requirements.
- Treat Ekkasarn's feature claims as a product benchmark, not evidence that its internal implementation or outcomes are reproducible.
- Treat captured HAR files as sensitive session data: sanitize before analysis, never commit them, and revoke credentials that may still be valid.
