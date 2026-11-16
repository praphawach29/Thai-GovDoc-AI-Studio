-- =============================================================================
-- คลังตัวอย่างของหน่วย: หนังสือฉบับจริงที่ลงนาม/ส่งออกแล้ว ใช้สอน "สำนวน" ให้ AI ตอนร่าง (few-shot)
--   - origin 'upload'   : ผู้ใช้อัปโหลด PDF สแกน/DOCX จากหน้าแรก (ไฟล์อยู่ใน bucket sources โฟลเดอร์ <org_id>/examples/)
--   - origin 'document' : ร่างในระบบที่ผู้ใช้กด "นี่คือฉบับจริง" (หนึ่งเอกสาร = หนึ่งตัวอย่าง กดซ้ำ = อัปเดต)
--   - เก็บข้อความแยกเป็น เรื่อง / ภาคเหตุ / ภาคข้อเท็จจริง / ภาคความประสงค์ + คำสำคัญ (ใช้คัดเลือกตอนร่าง)
--   - ลบได้ (ตัวอย่างไม่ใช่หลักฐานทางราชการ — ฉบับจริงที่เป็นหลักฐานอยู่ที่ final_files ซึ่งลบไม่ได้)
-- ไม่แก้ตารางเดิม และรันซ้ำได้
-- =============================================================================
create table if not exists public.style_examples (
    id           uuid primary key default gen_random_uuid(),
    org_id       uuid not null references public.organizations (id),
    created_by   uuid not null references auth.users (id),
    origin       text not null check (origin in ('upload', 'document')),
    document_id  uuid references public.documents (id) on delete set null,
    storage_path text unique,
    filename     text,
    doc_type     text not null check (doc_type in ('internal', 'external')),
    subject      text not null default '',
    doc_number   text not null default '',
    doc_date     text not null default '',
    part_reason  text not null default '',
    part_details text not null default '',
    part_purpose text not null default '',
    keywords     text not null default '',
    page_count   integer not null default 0 check (page_count >= 0),
    created_at   timestamptz not null default now(),
    updated_at   timestamptz not null default now(),
    check (storage_path is null or storage_path like org_id::text || '/examples/%'),
    check (length(part_reason) + length(part_details) + length(part_purpose) <= 60000)
);
create index if not exists style_examples_org_idx on public.style_examples (org_id, doc_type, created_at desc);
create index if not exists style_examples_created_by_idx on public.style_examples (created_by);
create unique index if not exists style_examples_document_uidx on public.style_examples (document_id)
    where document_id is not null;

alter table public.style_examples enable row level security;
drop policy if exists style_examples_select on public.style_examples;
create policy style_examples_select on public.style_examples
    for select to authenticated using (org_id = (select public.current_org_id()));
drop policy if exists style_examples_insert on public.style_examples;
create policy style_examples_insert on public.style_examples
    for insert to authenticated
    with check (org_id = (select public.current_org_id()) and created_by = (select auth.uid()));
drop policy if exists style_examples_update on public.style_examples;
create policy style_examples_update on public.style_examples
    for update to authenticated
    using (org_id = (select public.current_org_id()))
    with check (org_id = (select public.current_org_id()));
drop policy if exists style_examples_delete on public.style_examples;
create policy style_examples_delete on public.style_examples
    for delete to authenticated using (org_id = (select public.current_org_id()));

revoke all on public.style_examples from anon;
revoke update on public.style_examples from authenticated;
grant select, insert, delete on public.style_examples to authenticated;
grant update (doc_type, subject, doc_number, doc_date, part_reason, part_details, part_purpose, keywords, updated_at)
    on public.style_examples to authenticated;

-- ให้ API (PostgREST) เห็นตารางใหม่ทันที
notify pgrst, 'reload schema';

-- ตรวจผลหลังรัน:
--   select relrowsecurity from pg_class where relname = 'style_examples';            → true
--   select count(*) from pg_policies where tablename = 'style_examples';              → 4
--   select count(*) from public.style_examples;                                       → 0 (ตารางใหม่)
