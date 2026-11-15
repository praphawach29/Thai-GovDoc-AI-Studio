-- =============================================================================
-- ตั้งต้นหน่วยงานทดสอบ: กองการกีฬา สำนักวัฒนธรรม กีฬา และการท่องเที่ยว
--   - สร้างหน่วยงาน 1 แห่ง และผูกบัญชี (ตาม email ด้านล่าง) เป็น admin
--   - เพิ่มหน่วยออกหนังสือ 2 หน่วยตามตัวอย่างบันทึกข้อความจริง
-- รันใน Supabase SQL Editor หลังติดตั้ง migration 1–5 และสร้างผู้ใช้ใน Authentication แล้ว
-- รันซ้ำได้: ถ้าบัญชีผูกกับหน่วยงานแล้วจะไม่สร้างซ้ำ
-- =============================================================================
do $$
declare
    v_email  text := 'bkk.sportsdev@gmail.com';
    v_user   uuid;
    v_org    uuid;
    v_tel    text := '๐ ๒๒๔๖ ๘๐๗๙';
    v_fax    text := '๐ ๒๒๔๖ ๐๒๘๒';
begin
    select id into v_user from auth.users where lower(email) = lower(v_email);
    if v_user is null then
        raise exception 'ไม่พบผู้ใช้ % ใน Authentication → Users (สร้างผู้ใช้ก่อน)', v_email;
    end if;

    select org_id into v_org from public.profiles where user_id = v_user;
    if v_org is null then
        insert into public.organizations (name, doc_prefix, use_thai_numerals)
        values ('กองการกีฬา สำนักวัฒนธรรม กีฬา และการท่องเที่ยว', 'กท 1205/', true)
        returning id into v_org;
        insert into public.profiles (user_id, org_id, full_name, position, role)
        values (v_user, v_org, '', 'เจ้าหน้าที่กลุ่มงานส่งเสริมกีฬา', 'admin');
    end if;

    -- เลขที่: {gap} = เว้นที่ให้เขียนเลขด้วยมือ (ไม่มีจุด), {year} = ปี พ.ศ. ปัจจุบัน
    insert into public.org_units
        (org_id, key, label, dept_name, doc_number_format, contact_dept, contact_tel, contact_fax,
         blank_day, is_default, sort_order)
    values
        (v_org, 'sport-promotion', 'กลุ่มงานส่งเสริมกีฬา',
         'กองการกีฬา (กลุ่มงานส่งเสริมกีฬา โทร.' || v_tel || ' โทรสาร ' || v_fax || ')',
         '{gap}/{year}', 'กองการกีฬา (กลุ่มงานส่งเสริมกีฬา)', v_tel, v_fax, true, true, 1),
        (v_org, 'sports-division', 'กองการกีฬา',
         'สำนักวัฒนธรรม กีฬา และการท่องเที่ยว (กองการกีฬา โทร.' || v_tel || ' โทรสาร ' || v_fax || ')',
         'กท 1205/{gap}', 'กองการกีฬา', v_tel, v_fax, true, false, 2)
    on conflict (org_id, key) do nothing;

    raise notice 'เรียบร้อย: ผู้ใช้ % เป็น admin ของหน่วยงาน % (หน่วยออกหนังสือ % หน่วย)',
        v_email, v_org, (select count(*) from public.org_units where org_id = v_org);
end $$;

-- ตรวจผล: ควรได้ 2 แถว (กลุ่มงานส่งเสริมกีฬา เป็นค่าตั้งต้น)
select u.label, u.doc_number_format, u.is_default, o.name as organization, p.role
from public.profiles p
join auth.users a on a.id = p.user_id
join public.organizations o on o.id = p.org_id
join public.org_units u on u.org_id = o.id
where lower(a.email) = 'bkk.sportsdev@gmail.com'
order by u.sort_order;
