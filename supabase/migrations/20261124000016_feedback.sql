-- =============================================================================
-- แจ้งปัญหา / ความเห็นของผู้ใช้ (ช่วงทดสอบ) — ปุ่ม "แจ้งปัญหา" ในหน้าแก้ไขและหน้าแรก
--   - ทุกคนในหน่วยงานส่งได้ (เป็นชื่อตัวเองเท่านั้น) ผูกกับร่างที่เปิดอยู่ (ถ้ามี) พร้อมข้อมูลประกอบอัตโนมัติ
--     (ประเภท หน่วยออกหนังสือ ขั้นตอนที่ระบบทำ เวลา เบราว์เซอร์) — ไม่ต้องให้ผู้ทดสอบจดเอง
--   - ผู้ส่งเห็นเรื่องของตัวเอง; ผู้ดูแล (admin) เห็นทั้งหน่วยงาน และเปลี่ยนสถานะได้ (ใหม่ / รับทราบ / แก้แล้ว)
--   - ไม่มีสิทธิ์ลบ (เก็บเป็นหลักฐานการทดสอบ)
-- รันซ้ำได้ — รันทั้งไฟล์ใน SQL Editor ของ Supabase
-- =============================================================================

create table if not exists public.feedback (
    id           uuid primary key default gen_random_uuid(),
    org_id       uuid not null references public.organizations (id),
    user_id      uuid not null references auth.users (id),
    document_id  uuid references public.documents (id) on delete set null,
    rating       text not null check (rating in ('ok', 'minor', 'major', 'broken', 'idea')),
    category     text not null default 'other'
                 check (category in ('content', 'layout', 'export', 'source', 'speed', 'ui', 'other')),
    message      text not null default '' check (length(message) <= 4000),
    page         text not null default '' check (length(page) <= 300),
    context      jsonb not null default '{}'::jsonb check (pg_column_size(context) <= 16384),
    status       text not null default 'new' check (status in ('new', 'seen', 'done')),
    created_at   timestamptz not null default now(),
    updated_at   timestamptz not null default now()
);
create index if not exists feedback_org_created_idx on public.feedback (org_id, created_at desc);
create index if not exists feedback_user_idx on public.feedback (user_id);
create index if not exists feedback_document_idx on public.feedback (document_id);

alter table public.feedback enable row level security;

drop policy if exists feedback_select on public.feedback;
create policy feedback_select on public.feedback
    for select to authenticated
    using (org_id = (select public.current_org_id())
           and (user_id = (select auth.uid()) or (select public.current_role_is('admin'))));

drop policy if exists feedback_insert_self on public.feedback;
create policy feedback_insert_self on public.feedback
    for insert to authenticated
    with check (org_id = (select public.current_org_id()) and user_id = (select auth.uid()) and status = 'new');

drop policy if exists feedback_update_admin on public.feedback;
create policy feedback_update_admin on public.feedback
    for update to authenticated
    using (org_id = (select public.current_org_id()) and (select public.current_role_is('admin')))
    with check (org_id = (select public.current_org_id()));

revoke all on public.feedback from anon;
revoke all on public.feedback from authenticated;
grant select, insert on public.feedback to authenticated;
grant update (status, updated_at) on public.feedback to authenticated;   -- ผู้ดูแลเปลี่ยนได้เฉพาะสถานะ

notify pgrst, 'reload schema';

-- ตรวจผล (ควรได้ policies 3 · คอลัมน์ 12):
-- select count(*) as policies from pg_policies where schemaname = 'public' and tablename = 'feedback';
-- select count(*) as columns from information_schema.columns where table_schema = 'public' and table_name = 'feedback';
