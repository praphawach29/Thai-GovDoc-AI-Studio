-- =============================================================================
-- คลังกฎหมาย: ไฟล์กฎหมาย/ระเบียบต้นฉบับ (สแกน) + แยกเป็นข้อ/มาตรา พร้อมเลขหน้า
--   - ไฟล์เก็บใน bucket "sources" โฟลเดอร์ <org_id>/legal/ (ใช้สิทธิ์ Storage เดิมของหน่วยงาน)
--   - legal_sources: หนึ่งแถวต่อไฟล์ เก็บข้อความที่ AI อ่านทีละหน้า (ไม่ต้องอ่านซ้ำ)
--   - legal_references (เดิม): เพิ่ม source_id / page_from / page_to / chapter
--     ใช้ดึงเฉพาะหน้าของข้อที่เลือกจากไฟล์สแกนจริงไปแนบท้าย PDF
-- ไม่มีการลบข้อมูลเดิม และรันซ้ำได้
-- =============================================================================
create table if not exists public.legal_sources (
    id           uuid primary key default gen_random_uuid(),
    org_id       uuid not null references public.organizations (id),
    title        text not null default '',
    storage_path text not null unique,
    filename     text not null check (length(trim(filename)) > 0),
    page_count   integer not null default 0 check (page_count >= 0),
    size_bytes   bigint not null default 0 check (size_bytes >= 0),
    sha256       text,
    page_texts   jsonb not null default '[]'::jsonb,   -- ข้อความที่ AI อ่าน หน้าละหนึ่งสตริง
    created_by   uuid not null references auth.users (id),
    created_at   timestamptz not null default now(),
    check (storage_path like org_id::text || '/legal/%')
);
create index if not exists legal_sources_org_idx on public.legal_sources (org_id, created_at desc);
create index if not exists legal_sources_created_by_idx on public.legal_sources (created_by);

alter table public.legal_sources enable row level security;
drop policy if exists legal_sources_select on public.legal_sources;
create policy legal_sources_select on public.legal_sources
    for select to authenticated using (org_id = (select public.current_org_id()));
drop policy if exists legal_sources_insert on public.legal_sources;
create policy legal_sources_insert on public.legal_sources
    for insert to authenticated
    with check (org_id = (select public.current_org_id()) and created_by = (select auth.uid()));
drop policy if exists legal_sources_update on public.legal_sources;
create policy legal_sources_update on public.legal_sources
    for update to authenticated
    using (org_id = (select public.current_org_id()))
    with check (org_id = (select public.current_org_id()));
revoke all on public.legal_sources from anon;
revoke update, delete on public.legal_sources from authenticated;
grant select, insert on public.legal_sources to authenticated;
grant update (title, page_texts) on public.legal_sources to authenticated;

alter table public.legal_references
    add column if not exists source_id uuid references public.legal_sources (id) on delete set null,
    add column if not exists page_from integer check (page_from is null or page_from > 0),
    add column if not exists page_to   integer check (page_to is null or page_to > 0),
    add column if not exists chapter   text;
create index if not exists legal_references_source_idx on public.legal_references (source_id);

-- ตรวจผลหลังรัน:
--   select column_name from information_schema.columns
--    where table_schema = 'public' and table_name = 'legal_references' and column_name in ('source_id','page_from','page_to','chapter');
--   → ต้องได้ 4 แถว
--   select count(*) from public.legal_sources;   → 0 (ตารางใหม่)
