-- =============================================================================
-- ร่างที่กำลังแก้ (working copy) ของเอกสาร
--   documents.workspace  = สถานะล่าสุดของหน้าแก้ไข (ตัวเอกสาร + ต้นเรื่อง/ผลตรวจ/คำสั่ง)
--                          บันทึกอัตโนมัติบ่อย ๆ ได้ (แก้แถวเดิม)
--   document_versions    = จุดบันทึกที่ตั้งใจเก็บ (สร้างเอกสาร, ก่อนร่างใหม่, ออกเลข, ผู้ใช้กดบันทึกเวอร์ชัน)
--                          เขียนเพิ่มอย่างเดียว
-- =============================================================================
alter table public.documents
    add column if not exists workspace jsonb not null default '{}'::jsonb;

-- กันข้อมูลบวม: working copy ไม่เกิน ~2 MB
alter table public.documents
    add constraint documents_workspace_size check (pg_column_size(workspace) < 2 * 1024 * 1024);

grant update (workspace) on public.documents to authenticated;
