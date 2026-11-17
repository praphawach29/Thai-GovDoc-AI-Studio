-- =============================================================================
-- รายชื่อผู้ลงนามประจำหน่วยงาน (ใช้ร่วมกันทุกคนในหน่วยงานเดียวกัน)
--   - ชื่อเต็ม (ไม่มีวงเล็บ — ระบบใส่วงเล็บตอนเติมลงเอกสาร), ตำแหน่ง (หลายบรรทัดได้), ใช้ตราประทับชื่อ-ตำแหน่ง
--   - ผู้ลงนามเริ่มต้นได้หนึ่งคนต่อหน่วยงาน (unique index บางส่วน)
--   - ตอนร่าง: ช่องผู้ลงนามที่ตำแหน่งตรงกับรายชื่อ เติมชื่อให้อัตโนมัติ; ช่องผู้ลงนามหลักที่ยังว่างใช้ผู้ลงนามเริ่มต้น
-- ไม่แก้ตารางเดิม และรันซ้ำได้
-- =============================================================================
create table if not exists public.org_signers (
    id          uuid primary key default gen_random_uuid(),
    org_id      uuid not null references public.organizations (id),
    created_by  uuid not null references auth.users (id),
    full_name   text not null check (length(btrim(full_name)) between 1 and 200),
    position    text not null default '' check (length(position) <= 600),
    stamp       boolean not null default false,
    is_default  boolean not null default false,
    sort_order  integer not null default 0,
    created_at  timestamptz not null default now(),
    updated_at  timestamptz not null default now()
);
create index if not exists org_signers_org_idx on public.org_signers (org_id, sort_order, created_at);
create index if not exists org_signers_created_by_idx on public.org_signers (created_by);
create unique index if not exists org_signers_one_default_uidx on public.org_signers (org_id) where is_default;

alter table public.org_signers enable row level security;
drop policy if exists org_signers_select on public.org_signers;
create policy org_signers_select on public.org_signers
    for select to authenticated using (org_id = (select public.current_org_id()));
drop policy if exists org_signers_insert on public.org_signers;
create policy org_signers_insert on public.org_signers
    for insert to authenticated
    with check (org_id = (select public.current_org_id()) and created_by = (select auth.uid()));
drop policy if exists org_signers_update on public.org_signers;
create policy org_signers_update on public.org_signers
    for update to authenticated
    using (org_id = (select public.current_org_id()))
    with check (org_id = (select public.current_org_id()));
drop policy if exists org_signers_delete on public.org_signers;
create policy org_signers_delete on public.org_signers
    for delete to authenticated using (org_id = (select public.current_org_id()));

revoke all on public.org_signers from anon;
revoke update on public.org_signers from authenticated;
grant select, insert, delete on public.org_signers to authenticated;
grant update (full_name, position, stamp, is_default, sort_order, updated_at) on public.org_signers to authenticated;

-- ให้ API (PostgREST) เห็นตารางใหม่ทันที
notify pgrst, 'reload schema';

-- ตรวจผลหลังรัน:
--   select relrowsecurity from pg_class where relname = 'org_signers';                → true
--   select count(*) from pg_policies where tablename = 'org_signers';                  → 4
--   select indexname from pg_indexes where tablename = 'org_signers' and indexname = 'org_signers_one_default_uidx';  → 1 แถว
--   select count(*) from public.org_signers;                                           → 0 (ตารางใหม่)
