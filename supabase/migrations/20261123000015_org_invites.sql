-- =============================================================================
-- ผู้ใช้ของหน่วยงาน: เชิญด้วยอีเมล → ลงทะเบียนเอง → ได้โปรไฟล์ในหน่วยงานอัตโนมัติ
--   - ผู้ดูแล (role = admin) เพิ่มคำเชิญ: อีเมล ชื่อ ตำแหน่ง บทบาท (หมดอายุ ๑๔ วัน)
--   - ผู้ถูกเชิญลงทะเบียนที่หน้าเข้าสู่ระบบด้วยอีเมลนั้น → trigger บน auth.users สร้างแถว profiles ให้
--   - อีเมลที่ไม่มีคำเชิญ: มีบัญชีแต่ไม่มีโปรไฟล์ = เข้าข้อมูลใดไม่ได้ (RLS) — ไม่ปฏิเสธการสร้างบัญชี
--     เพราะผู้ดูแลคนแรกของหน่วยงานใหม่สร้างจาก Dashboard ก่อนมีคำเชิญ (supabase/seed/bootstrap_admin.sql)
--   - ผู้ดูแลเปลี่ยนบทบาท/ระงับผู้ใช้ได้ผ่านฟังก์ชัน (ระงับ = role 'disabled' → current_org_id() คืน null → RLS ปิดทุกตาราง)
--   - ไม่ต้องใช้ service role key บนเซิร์ฟเวอร์
-- รันซ้ำได้ — รันทั้งไฟล์ใน SQL Editor ของ Supabase
-- =============================================================================

-- ---------------------------------------------------------------- profiles: อีเมล + บทบาท "ระงับ"
alter table public.profiles add column if not exists email text not null default '';
update public.profiles p set email = lower(u.email)
  from auth.users u where u.id = p.user_id and p.email = '' and u.email is not null;

alter table public.profiles drop constraint if exists profiles_role_check;
alter table public.profiles add constraint profiles_role_check
    check (role in ('admin', 'clerk', 'drafter', 'approver', 'disabled'));

-- อ่านโปรไฟล์ของตัวเองได้เสมอ (ผู้ใช้ที่ถูกระงับเห็นว่าตัวเองถูกระงับ ไม่ใช่ "ยังไม่ผูกหน่วยงาน")
drop policy if exists profiles_select_self on public.profiles;
create policy profiles_select_self on public.profiles
    for select to authenticated using (user_id = (select auth.uid()));

-- ผู้ใช้ที่ถูกระงับ = ไม่มีหน่วยงาน (ทุก policy ใช้ current_org_id())
create or replace function public.current_org_id()
returns uuid
language sql
stable
security definer
set search_path = ''
as $$
    select p.org_id from public.profiles p
    where p.user_id = (select auth.uid()) and p.role <> 'disabled'
$$;

-- ---------------------------------------------------------------- คำเชิญ
create table if not exists public.org_invites (
    id          uuid primary key default gen_random_uuid(),
    org_id      uuid not null references public.organizations (id),
    email       text not null check (email = lower(btrim(email)) and email like '%_@_%.__%' and length(email) <= 254),
    full_name   text not null default '' check (length(full_name) <= 200),
    position    text not null default '' check (length(position) <= 300),
    role        text not null default 'drafter' check (role in ('admin', 'clerk', 'drafter', 'approver')),
    created_by  uuid not null references auth.users (id),
    created_at  timestamptz not null default now(),
    expires_at  timestamptz not null default now() + interval '14 days',
    used_by     uuid references auth.users (id),
    used_at     timestamptz,
    revoked_at  timestamptz
);
-- คำเชิญที่ยังใช้ได้มีได้ใบเดียวต่ออีเมล (ทั้งระบบ — อีเมลหนึ่งอยู่ได้หน่วยงานเดียว)
create unique index if not exists org_invites_open_email_uidx on public.org_invites (email)
    where used_at is null and revoked_at is null;
create index if not exists org_invites_org_idx on public.org_invites (org_id, created_at desc);
create index if not exists org_invites_created_by_idx on public.org_invites (created_by);
create index if not exists org_invites_used_by_idx on public.org_invites (used_by);

alter table public.org_invites enable row level security;
drop policy if exists org_invites_select_admin on public.org_invites;
create policy org_invites_select_admin on public.org_invites
    for select to authenticated
    using (org_id = (select public.current_org_id()) and (select public.current_role_is('admin')));
drop policy if exists org_invites_insert_admin on public.org_invites;
create policy org_invites_insert_admin on public.org_invites
    for insert to authenticated
    with check (org_id = (select public.current_org_id()) and (select public.current_role_is('admin'))
                and created_by = (select auth.uid()) and used_at is null and revoked_at is null);
drop policy if exists org_invites_update_admin on public.org_invites;
create policy org_invites_update_admin on public.org_invites
    for update to authenticated
    using (org_id = (select public.current_org_id()) and (select public.current_role_is('admin')))
    with check (org_id = (select public.current_org_id()));

revoke all on public.org_invites from anon;
revoke all on public.org_invites from authenticated;
grant select, insert on public.org_invites to authenticated;
grant update (revoked_at) on public.org_invites to authenticated;   -- ผู้ดูแลยกเลิกคำเชิญได้อย่างเดียว

-- ---------------------------------------------------------------- ลงทะเบียน = ใช้คำเชิญ
create or replace function public.handle_invited_signup()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
declare
    inv public.org_invites%rowtype;
begin
    if exists (select 1 from public.profiles where user_id = new.id) then
        return new;                                      -- ผู้ดูแลสร้างโปรไฟล์ให้เองแล้ว
    end if;
    select * into inv from public.org_invites
     where email = lower(new.email) and used_at is null and revoked_at is null and expires_at > now()
     order by created_at desc limit 1
     for update;
    if not found then
        return new;                                      -- ไม่มีคำเชิญ: ไม่มีโปรไฟล์ = ไม่เห็นข้อมูลใด
    end if;
    insert into public.profiles (user_id, org_id, full_name, position, role, email)
    values (new.id, inv.org_id, inv.full_name, inv.position, inv.role, lower(new.email));
    update public.org_invites set used_by = new.id, used_at = now() where id = inv.id;
    return new;
end
$$;
revoke all on function public.handle_invited_signup() from public, anon, authenticated;

drop trigger if exists on_auth_user_invited on auth.users;
create trigger on_auth_user_invited
    after insert on auth.users
    for each row execute function public.handle_invited_signup();

-- สมัครไว้ก่อนแล้วค่อยได้รับเชิญ: เซิร์ฟเวอร์เรียกตอนผู้ใช้ที่ล็อกอินยังไม่มีโปรไฟล์ (server/auth.get_profile)
create or replace function public.claim_my_invite()
returns boolean
language plpgsql
security definer
set search_path = ''
as $$
declare
    me uuid := auth.uid();
    my_email text;
    inv public.org_invites%rowtype;
begin
    if me is null or exists (select 1 from public.profiles where user_id = me) then
        return false;
    end if;
    select lower(email) into my_email from auth.users where id = me;
    select * into inv from public.org_invites
     where email = my_email and used_at is null and revoked_at is null and expires_at > now()
     order by created_at desc limit 1
     for update;
    if not found then
        return false;
    end if;
    insert into public.profiles (user_id, org_id, full_name, position, role, email)
    values (me, inv.org_id, inv.full_name, inv.position, inv.role, my_email);
    update public.org_invites set used_by = me, used_at = now() where id = inv.id;
    return true;
end
$$;
revoke all on function public.claim_my_invite() from public, anon;
grant execute on function public.claim_my_invite() to authenticated;

-- ---------------------------------------------------------------- ผู้ดูแลจัดการผู้ใช้ในหน่วยงาน
-- เปลี่ยนบทบาท / ระงับ ('disabled') / เปิดใช้คืน — ห้ามทำให้หน่วยงานไม่เหลือผู้ดูแล
create or replace function public.admin_set_role(target uuid, new_role text)
returns text                                             -- คืนบทบาทใหม่ (void ทำให้ PostgREST ตอบเนื้อความว่าง)
language plpgsql
security definer
set search_path = ''
as $$
declare
    my_org uuid := public.current_org_id();
    old_role text;
begin
    if my_org is null or not public.current_role_is('admin') then
        raise exception 'เฉพาะผู้ดูแลของหน่วยงาน' using errcode = '42501';
    end if;
    if new_role not in ('admin', 'clerk', 'drafter', 'approver', 'disabled') then
        raise exception 'บทบาทไม่ถูกต้อง' using errcode = '22023';
    end if;
    select role into old_role from public.profiles where user_id = target and org_id = my_org for update;
    if not found then
        raise exception 'ไม่พบผู้ใช้นี้ในหน่วยงาน' using errcode = 'P0002';
    end if;
    if old_role = 'admin' and new_role <> 'admin'
       and (select count(*) from public.profiles where org_id = my_org and role = 'admin') <= 1 then
        raise exception 'หน่วยงานต้องมีผู้ดูแลอย่างน้อย ๑ คน' using errcode = 'P0001';
    end if;
    update public.profiles set role = new_role where user_id = target and org_id = my_org;
    return new_role;
end
$$;
revoke all on function public.admin_set_role(uuid, text) from public, anon;
grant execute on function public.admin_set_role(uuid, text) to authenticated;

-- ให้ API (PostgREST) เห็นตาราง/ฟังก์ชันใหม่ทันที
notify pgrst, 'reload schema';

-- ตรวจผลหลังรัน:
--   select count(*) from pg_policies where tablename = 'org_invites';                        → 3
--   select tgname from pg_trigger where tgname = 'on_auth_user_invited';                       → 1 แถว
--   select count(*) from public.profiles where email = '';                                     → 0
--   select user_id, email, role from public.profiles;   -- ต้องมีอย่างน้อย ๑ คนเป็น admin ไม่งั้นเชิญใครไม่ได้
--     ถ้ายังไม่มี: update public.profiles set role = 'admin' where email = '<อีเมลผู้ดูแล>';
-- ตั้งค่าใน Supabase Dashboard → Authentication:
--   - Sign In / Providers → Email: เปิด "Allow new users to sign up" (คนที่ไม่มีคำเชิญสร้างบัญชีได้แต่ไม่เห็นข้อมูลใด)
--   - URL Configuration → Site URL / Redirect URLs: ใส่ https://<โดเมนเว็บ>/studio/login.html (ลิงก์ยืนยันอีเมล)
