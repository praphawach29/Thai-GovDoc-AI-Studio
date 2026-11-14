-- ทดสอบ migration บน PostgreSQL ธรรมดา (ดู run_local.sh)
-- แต่ละข้อ: สลับเป็นผู้ใช้ด้วย set role + request.jwt.claims แล้วตรวจผล
\set ON_ERROR_STOP on
\set QUIET on

-- ---------------------------------------------------------------- เตรียมข้อมูล (สิทธิ์ผู้ดูแลระบบ)
insert into auth.users (id, email) values
    ('00000000-0000-0000-0000-00000000000a', 'a@test.local'),
    ('00000000-0000-0000-0000-00000000000b', 'b@test.local'),
    ('00000000-0000-0000-0000-00000000000c', 'c@test.local');   -- ยังไม่มีโปรไฟล์/หน่วยงาน
insert into public.organizations (id, name, doc_prefix) values
    ('11111111-1111-1111-1111-111111111111', 'หน่วยงาน ก', 'กท ๐๐๐๑/'),
    ('22222222-2222-2222-2222-222222222222', 'หน่วยงาน ข', 'ABC/');
insert into public.profiles (user_id, org_id, full_name, role) values
    ('00000000-0000-0000-0000-00000000000a', '11111111-1111-1111-1111-111111111111', 'ผู้ใช้ ก', 'drafter'),
    ('00000000-0000-0000-0000-00000000000b', '22222222-2222-2222-2222-222222222222', 'ผู้ใช้ ข', 'drafter');

create function pg_temp.expect_error(sql text, label text) returns void language plpgsql as $$
begin
    execute sql;
    raise exception 'FAIL (ควร error แต่ผ่าน): %', label;
exception when others then
    if sqlerrm like 'FAIL%' then raise; end if;
    -- แสดงสาเหตุไว้ตรวจว่า error ด้วยเหตุผลที่ตั้งใจ ไม่ใช่พิมพ์ SQL ผิด
    if sqlstate in ('42601', '42P01', '42703', '42883') then
        raise exception 'FAIL (SQL ในเทสต์ผิด %): % — %', sqlstate, label, sqlerrm;
    end if;
    raise notice 'ok  % → [%] %', label, sqlstate, sqlerrm;
end $$;
create function pg_temp.check(cond boolean, label text) returns void language plpgsql as $$
begin
    if not coalesce(cond, false) then raise exception 'FAIL: %', label; end if;
end $$;
grant execute on function pg_temp.expect_error(text, text) to public;
grant execute on function pg_temp.check(boolean, text) to public;

-- ---------------------------------------------------------------- ผู้ใช้ A
begin;
set local role authenticated;
set local request.jwt.claims = '{"sub":"00000000-0000-0000-0000-00000000000a"}';

-- ออกเลข: เลขไทยตามรหัสหน่วยงาน, เพิ่มทีละ ๑, หนังสือเวียนมีชุดของตัวเอง
select pg_temp.check((public.reserve_outgoing_number('กท ๐๐๐๑/', 'เรื่องที่ ๑')).doc_number = 'กท ๐๐๐๑/๑', 'เลขแรก ๑');
select pg_temp.check((public.reserve_outgoing_number('กท ๐๐๐๑/', 'เรื่องที่ ๒')).doc_number = 'กท ๐๐๐๑/๒', 'เลขถัดไป ๒');
select pg_temp.check((public.reserve_outgoing_number('กท ๐๐๐๑/', 'เวียน', true)).doc_number = 'กท ๐๐๐๑/ว ๑', 'หนังสือเวียนเริ่ม ว ๑');
select pg_temp.check((public.reserve_outgoing_number('XY/', 'อารบิก')).doc_number = 'XY/1', 'รหัสอารบิกได้เลขอารบิก');

-- เอกสาร + เวอร์ชัน
insert into public.documents (id, org_id, owner_id, subject)
values ('33333333-3333-3333-3333-333333333333', '11111111-1111-1111-1111-111111111111',
        '00000000-0000-0000-0000-00000000000a', 'ร่างแรก');
select pg_temp.check(public.save_document_version('33333333-3333-3333-3333-333333333333', '{"subject":"ร่าง ๑"}') = 1, 'เวอร์ชัน 1');
select pg_temp.check(public.save_document_version('33333333-3333-3333-3333-333333333333', '{"subject":"ร่าง ๒"}', 'ขัดเกลา') = 2, 'เวอร์ชัน 2');
select pg_temp.check((select subject from public.documents where id = '33333333-3333-3333-3333-333333333333') = 'ร่าง ๒', 'เรื่องตามเวอร์ชันล่าสุด');

-- บันทึกอัตโนมัติ (working copy) ได้ โดยไม่สร้างเวอร์ชันใหม่
update public.documents set workspace = '{"doc":{"subject":"กำลังแก้"}}' where id = '33333333-3333-3333-3333-333333333333';
select pg_temp.check((select workspace->'doc'->>'subject' = 'กำลังแก้' and current_version = 2 from public.documents
                      where id = '33333333-3333-3333-3333-333333333333'), 'autosave workspace ไม่เพิ่มเวอร์ชัน');

-- ออกเลขผูกกับเอกสาร → เอกสารได้เลขที่และสถานะ numbered
select pg_temp.check((public.reserve_outgoing_number('กท ๐๐๐๑/', 'ผูกเอกสาร', false, 'กรม ข',
        '33333333-3333-3333-3333-333333333333')).doc_number = 'กท ๐๐๐๑/๓', 'เลขที่ผูกเอกสาร');
select pg_temp.check((select doc_number = 'กท ๐๐๐๑/๓' and status = 'numbered' from public.documents
                      where id = '33333333-3333-3333-3333-333333333333'), 'เอกสารได้เลขที่');

-- สิ่งที่ต้องทำไม่ได้
select pg_temp.expect_error($$insert into public.documents (org_id, owner_id) values
    ('22222222-2222-2222-2222-222222222222', '00000000-0000-0000-0000-00000000000a')$$, 'สร้างเอกสารในหน่วยงานอื่น');
select pg_temp.expect_error($$insert into public.outgoing_register (org_id, book, year_be, reg_no, doc_number, created_by)
    values ('11111111-1111-1111-1111-111111111111', 'x', 2569, 99, 'ปลอม/99', '00000000-0000-0000-0000-00000000000a')$$,
    'เขียนทะเบียนส่งตรงโดยไม่ผ่านฟังก์ชัน');
select pg_temp.expect_error($$update public.documents set doc_number = 'ปลอม/1'$$, 'แก้เลขที่หนังสือเอง');
select pg_temp.expect_error($$update public.profiles set role = 'admin' where user_id = auth.uid()$$, 'ยกบทบาทตัวเองเป็น admin');
select pg_temp.expect_error($$update public.profiles set org_id = '22222222-2222-2222-2222-222222222222' where user_id = auth.uid()$$, 'ย้ายหน่วยงานตัวเอง');
select pg_temp.expect_error($$select public.issue_reg_no('11111111-1111-1111-1111-111111111111', 'x', 2569)$$, 'เรียกตัวนับเลขตรง');
select pg_temp.expect_error($$select public.cancel_outgoing_number(1, '  ')$$, 'ยกเลิกเลขโดยไม่มีเหตุผล');
update public.profiles set full_name = 'ชื่อใหม่' where user_id = auth.uid();
select pg_temp.check((select full_name from public.profiles where user_id = auth.uid()) = 'ชื่อใหม่', 'แก้ชื่อตัวเองได้');

-- ยืนยันการใช้เลข / ยกเลิกเลข
select pg_temp.check((public.mark_outgoing_issued(1, '๑๔ พฤศจิกายน ๒๕๖๙')).status = 'issued', 'ยืนยันเลข');
select pg_temp.check((public.cancel_outgoing_number(2, 'จองผิดเรื่อง')).status = 'cancelled', 'ยกเลิกเลขพร้อมเหตุผล');
select pg_temp.expect_error($$select public.mark_outgoing_issued(2)$$, 'ใช้เลขที่ยกเลิกแล้ว');

-- ทะเบียนรับ
select pg_temp.check((public.register_incoming('สธ ๐๑/๑', '๑ พ.ย. ๒๕๖๙', 'กระทรวง ก', 'ขอเชิญประชุม')).reg_no = 1, 'ทะเบียนรับเลข 1');
select pg_temp.check((public.register_incoming('สธ ๐๑/๒', '๒ พ.ย. ๒๕๖๙', 'กระทรวง ก', 'ขอข้อมูล')).reg_no = 2, 'ทะเบียนรับเลข 2');

-- Storage: อัปโหลดได้เฉพาะโฟลเดอร์หน่วยงานตัวเอง
insert into storage.objects (bucket_id, name) values ('sources', '11111111-1111-1111-1111-111111111111/a.pdf');
select pg_temp.expect_error($$insert into storage.objects (bucket_id, name)
    values ('sources', '22222222-2222-2222-2222-222222222222/x.pdf')$$, 'อัปโหลดเข้าโฟลเดอร์หน่วยงานอื่น');

select pg_temp.check((select ok from public.verify_audit_chain()), 'audit chain ถูกต้อง');
select pg_temp.check((select count(*) from public.audit_log) >= 10, 'มี audit อัตโนมัติ');
commit;

-- ---------------------------------------------------------------- ผู้ใช้ B (หน่วยงานอื่น)
begin;
set local role authenticated;
set local request.jwt.claims = '{"sub":"00000000-0000-0000-0000-00000000000b"}';
select pg_temp.check((select count(*) from public.documents) = 0, 'B มองไม่เห็นเอกสารของ ก');
select pg_temp.check((select count(*) from public.outgoing_register) = 0, 'B มองไม่เห็นทะเบียนของ ก');
select pg_temp.check((select count(*) from public.audit_log) = 0, 'B มองไม่เห็น audit ของ ก');
select pg_temp.check((select count(*) from storage.objects) = 0, 'B มองไม่เห็นไฟล์ของ ก');
select pg_temp.check((public.reserve_outgoing_number('ABC/', 'ของ ข')).doc_number = 'ABC/1', 'B มีตัวนับของตัวเอง');
select pg_temp.expect_error($$select public.save_document_version('33333333-3333-3333-3333-333333333333', '{}')$$,
    'B บันทึกเวอร์ชันเอกสารของ ก');
commit;

-- ---------------------------------------------------------------- ผู้ใช้ที่ยังไม่มีหน่วยงาน / ไม่ได้ล็อกอิน
begin;
set local role authenticated;
set local request.jwt.claims = '{"sub":"00000000-0000-0000-0000-00000000000c"}';
select pg_temp.expect_error($$select public.reserve_outgoing_number('X/', 'y')$$, 'ผู้ใช้ไม่มีหน่วยงานออกเลข');
commit;
begin;
set local role anon;
select pg_temp.expect_error($$select count(*) from public.documents$$, 'anon อ่านเอกสาร');
select pg_temp.expect_error($$select public.reserve_outgoing_number('X/', 'y')$$, 'anon ออกเลข');
commit;

-- ---------------------------------------------------------------- ห้ามลบ/แก้ แม้เป็นผู้ดูแลระบบ
select pg_temp.expect_error($$delete from public.outgoing_register$$, 'ลบทะเบียนส่ง');
select pg_temp.expect_error($$delete from public.incoming_register$$, 'ลบทะเบียนรับ');
select pg_temp.expect_error($$update public.document_versions set content = '{}'$$, 'แก้เวอร์ชันเก่า');
select pg_temp.expect_error($$delete from public.audit_log$$, 'ลบ audit');
select pg_temp.expect_error($$delete from public.documents$$, 'ลบเอกสาร');

-- ตรวจจับการแก้ audit ย้อนหลัง (จำลองผู้ไม่หวังดีที่ปิด trigger ได้)
set session_replication_role = replica;
update public.audit_log set details = '{"แก้":"ย้อนหลัง"}' where id = (select min(id) from public.audit_log);
set session_replication_role = origin;
begin;
set local role authenticated;
set local request.jwt.claims = '{"sub":"00000000-0000-0000-0000-00000000000a"}';
select pg_temp.check((select not ok from public.verify_audit_chain()), 'ตรวจพบการแก้ audit ย้อนหลัง');
commit;

\echo 'db_test: ผ่านทุกข้อ'
