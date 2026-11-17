-- รันครั้งเดียวหลังสร้างบัญชีผู้ใช้คนแรก (Authentication → Users → Add user)
-- ใน Supabase SQL Editor: แก้ 3 ค่าใน "params" แล้วกด Run
-- ผล: สร้างหน่วยงาน 1 แห่ง และผูกบัญชีนั้นเป็น admin ของหน่วยงาน
with params as (
    select
        'อีเมลบัญชีของคุณ'::text as email,         -- เช่น ที่ใช้ล็อกอิน
        'ชื่อหน่วยงาน'::text      as org_name,      -- เช่น กลุ่มงานส่งเสริมกีฬา กองการกีฬา
        'กท ๐๐๐๐/'::text           as doc_prefix     -- รหัสหนังสือของหน่วยงาน (มี / ท้าย)
), new_org as (
    insert into public.organizations (name, doc_prefix)
    select org_name, doc_prefix from params
    returning id
)
insert into public.profiles (user_id, org_id, full_name, role)
select u.id, o.id, '', 'admin'
from auth.users u, new_org o, params p
where lower(u.email) = lower(p.email)
returning user_id, org_id, role;
-- ถ้าไม่มีแถวคืนมา = ไม่พบอีเมลนี้ใน auth.users (ตรวจว่าสร้างผู้ใช้แล้ว และพิมพ์อีเมลถูก)
