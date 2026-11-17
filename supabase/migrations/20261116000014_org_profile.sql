-- =============================================================================
-- ข้อมูลหน่วยงานที่แก้ได้จากหน้าเว็บ (หน้าแรก → ข้อมูลหน่วยงาน) — หนึ่งแถวต่อหน่วยงาน ใช้ร่วมกันทุกคนในหน่วย
--   ใช้เติมหัวหนังสือภายนอก/เอกสารเปล่า: ส่วนราชการ, รหัสหนังสือออก, ส่วนราชการเจ้าของเรื่อง, โทร, โทรสาร, อีเมล
--   (บันทึกข้อความใช้ส่วนราชการตามหน่วยออกหนังสือใน org_units; ผู้ลงนามอยู่ที่ org_signers)
--   ช่องที่เว้นว่าง = ใช้ค่าตั้งต้นของระบบ
-- ไม่แก้ตารางเดิม และรันซ้ำได้
-- =============================================================================
create table if not exists public.org_profile (
    org_id          uuid primary key references public.organizations (id),
    dept_name       text not null default '' check (length(dept_name) <= 300),
    department_full text not null default '' check (length(department_full) <= 500),
    doc_origin_code text not null default '' check (length(doc_origin_code) <= 50),
    contact_dept    text not null default '' check (length(contact_dept) <= 300),
    contact_tel     text not null default '' check (length(contact_tel) <= 100),
    contact_fax     text not null default '' check (length(contact_fax) <= 100),
    contact_email   text not null default '' check (length(contact_email) <= 200),
    updated_by      uuid references auth.users (id),
    updated_at      timestamptz not null default now()
);
create index if not exists org_profile_updated_by_idx on public.org_profile (updated_by);

alter table public.org_profile enable row level security;
drop policy if exists org_profile_select on public.org_profile;
create policy org_profile_select on public.org_profile
    for select to authenticated using (org_id = (select public.current_org_id()));
drop policy if exists org_profile_insert on public.org_profile;
create policy org_profile_insert on public.org_profile
    for insert to authenticated
    with check (org_id = (select public.current_org_id()) and updated_by = (select auth.uid()));
drop policy if exists org_profile_update on public.org_profile;
create policy org_profile_update on public.org_profile
    for update to authenticated
    using (org_id = (select public.current_org_id()))
    with check (org_id = (select public.current_org_id()) and updated_by = (select auth.uid()));

revoke all on public.org_profile from anon;
revoke update, delete on public.org_profile from authenticated;
grant select, insert on public.org_profile to authenticated;
grant update (dept_name, department_full, doc_origin_code, contact_dept, contact_tel, contact_fax, contact_email,
              updated_by, updated_at) on public.org_profile to authenticated;

-- ให้ API (PostgREST) เห็นตารางใหม่ทันที
notify pgrst, 'reload schema';

-- ตรวจผลหลังรัน:
--   select relrowsecurity from pg_class where relname = 'org_profile';     → true
--   select count(*) from pg_policies where tablename = 'org_profile';       → 3
--   select count(*) from public.org_profile;                                → 0 (ตารางใหม่ — แถวแรกเกิดเมื่อกดบันทึกในหน้าเว็บ)
