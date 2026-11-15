-- =============================================================================
-- หน่วยออกหนังสือของแต่ละหน่วยงาน (เลือกได้ทุกครั้งที่ร่าง)
--   แต่ละหน่วยมีบรรทัด "ส่วนราชการ" รูปแบบเลขที่ และผู้ประสานของตัวเอง
--   doc_number_format: {gap} = เว้นที่ให้เขียนเลขด้วยมือ, {year} = ปี พ.ศ. ปัจจุบัน
--     เช่น '{gap}/{year}' (กลุ่มงาน) หรือ 'กท 1205/{gap}' (กอง)
-- =============================================================================
create table public.org_units (
    id                uuid primary key default gen_random_uuid(),
    org_id            uuid not null references public.organizations (id),
    key               text not null check (key ~ '^[a-z0-9-]{2,40}$'),
    label             text not null check (length(trim(label)) > 0),
    dept_name         text not null,
    doc_number_format text not null default '{gap}/{year}',
    contact_dept      text not null default '',
    contact_tel       text not null default '',
    contact_fax       text not null default '',
    blank_day         boolean not null default true,
    is_default        boolean not null default false,
    sort_order        integer not null default 0,
    created_at        timestamptz not null default now(),
    unique (org_id, key)
);
create index org_units_org_idx on public.org_units (org_id, sort_order);
-- หน่วยตั้งต้นได้ไม่เกิน 1 หน่วยต่อหน่วยงาน
create unique index org_units_one_default on public.org_units (org_id) where is_default;

alter table public.org_units enable row level security;
create policy org_units_select on public.org_units
    for select to authenticated using (org_id = (select public.current_org_id()));
create policy org_units_admin_insert on public.org_units
    for insert to authenticated
    with check (org_id = (select public.current_org_id()) and (select public.current_role_is('admin')));
create policy org_units_admin_update on public.org_units
    for update to authenticated
    using (org_id = (select public.current_org_id()) and (select public.current_role_is('admin')))
    with check (org_id = (select public.current_org_id()));
revoke all on public.org_units from anon;
