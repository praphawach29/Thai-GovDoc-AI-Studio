-- =============================================================================
-- ตั้งต้นหน่วยงานทดสอบ: กองการกีฬา สำนักวัฒนธรรม กีฬา และการท่องเที่ยว
--   - สร้างหน่วยงาน 1 แห่ง และผูกบัญชี (ตาม email ด้านล่าง) เป็น admin
--   - เพิ่มสายการเสนอ 3 ขั้น (กลุ่มงาน -> กอง -> สำนัก) ตามตัวอย่างบันทึกข้อความจริง
-- รันใน Supabase SQL Editor หลังติดตั้ง migration 1–6 และสร้างผู้ใช้ใน Authentication แล้ว
-- รันซ้ำได้: ถ้าบัญชีผูกกับหน่วยงานแล้วจะไม่สร้างซ้ำ (หน่วยออกหนังสือถูกปรับเป็นค่าตามตัวอย่าง)
-- =============================================================================
do $$
declare
    v_email  text := 'bkk.sportsdev@gmail.com';
    v_user   uuid;
    v_org    uuid;
    v_tel    text := '๐ ๒๒๔๖ ๘๐๗๙';
    v_fax    text := '๐ ๒๒๔๖ ๐๒๘๒';
    v_bureau text := 'สำนักวัฒนธรรม กีฬา และการท่องเที่ยว';
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
    -- ลำดับขั้น (sort_order): กลุ่มงาน -> กอง -> สำนัก ตามตัวอย่างบันทึกเสนอจริง
    insert into public.org_units
        (org_id, key, label, dept_name, doc_number_format, contact_dept, contact_tel, contact_fax,
         blank_day, is_default, sort_order, recipient, signers, review_party, request_text)
    values
        (v_org, 'sport-promotion', 'กลุ่มงานส่งเสริมกีฬา',
         'กลุ่มงานส่งเสริมกีฬา โทร.' || v_tel || ' โทรสาร ' || v_fax,
         '{gap}/{year}', 'กลุ่มงานส่งเสริมกีฬา', v_tel, v_fax, true, true, 1,
         'หัวหน้ากลุ่มงานส่งเสริมกีฬา',
         jsonb_build_array(
             jsonb_build_object('name', '', 'position', 'ผู้เสนอเรื่อง', 'is_author', true),
             jsonb_build_object('name', '', 'position', 'หัวหน้ากลุ่มงานส่งเสริมกีฬา', 'is_author', false)),
         'กลุ่มงานส่งเสริมกีฬา',
         'จึงเรียนมาเพื่อโปรดพิจารณานำเรียนผู้อำนวยการกองการกีฬาลงนามในหนังสือที่แนบ'),
        (v_org, 'sports-division', 'กองการกีฬา',
         'กองการกีฬา (กลุ่มงานส่งเสริมกีฬา โทร.' || v_tel || ' โทรสาร ' || v_fax || ')',
         'กท 1205/{gap}', 'กองการกีฬา', v_tel, v_fax, true, false, 2,
         'ผู้อำนวยการ' || v_bureau,
         jsonb_build_array(jsonb_build_object('name', '', 'position', 'ผู้อำนวยการกองการกีฬา', 'is_author', false)),
         'กองการกีฬา',
         'จึงเรียนมาเพื่อโปรดพิจารณาลงนามหนังสือเรียนปลัดกรุงเทพมหานครที่แนบ'),
        (v_org, 'culture-sports-bureau', v_bureau,
         v_bureau || ' (กองการกีฬา โทร.' || v_tel || ' โทรสาร ' || v_fax || ')',
         'กท 1205/{gap}', 'กองการกีฬา', v_tel, v_fax, true, false, 3,
         'ปลัดกรุงเทพมหานคร',
         jsonb_build_array(jsonb_build_object('name', '', 'position', 'ผู้อำนวยการ' || v_bureau, 'is_author', false)),
         v_bureau,
         'จึงเรียนมาเพื่อโปรดพิจารณา หากเห็นชอบโปรดนำเรียนผู้ว่าราชการกรุงเทพมหานคร'
             || 'เพื่อโปรดพิจารณาตามข้อพิจารณาและเสนอแนะข้างต้น')
    -- รันซ้ำ = ปรับกลับเป็นค่าตามตัวอย่าง (แก้ค่าเองภายหลังได้ในตาราง org_units)
    on conflict (org_id, key) do update set
        label = excluded.label, dept_name = excluded.dept_name,
        doc_number_format = excluded.doc_number_format, contact_dept = excluded.contact_dept,
        contact_tel = excluded.contact_tel, contact_fax = excluded.contact_fax,
        blank_day = excluded.blank_day, is_default = excluded.is_default, sort_order = excluded.sort_order,
        recipient = excluded.recipient, signers = excluded.signers,
        review_party = excluded.review_party, request_text = excluded.request_text;

    raise notice 'เรียบร้อย: ผู้ใช้ % เป็น admin ของหน่วยงาน % (หน่วยออกหนังสือ % หน่วย)',
        v_email, v_org, (select count(*) from public.org_units where org_id = v_org);
end $$;

-- ตรวจผล: ควรได้ 3 แถว เรียงกลุ่มงาน -> กอง -> สำนัก (กลุ่มงานส่งเสริมกีฬา เป็นค่าตั้งต้น)
select u.sort_order, u.label, u.doc_number_format, u.recipient, u.is_default, p.role
from public.profiles p
join auth.users a on a.id = p.user_id
join public.organizations o on o.id = p.org_id
join public.org_units u on u.org_id = o.id
where lower(a.email) = 'bkk.sportsdev@gmail.com'
order by u.sort_order;
