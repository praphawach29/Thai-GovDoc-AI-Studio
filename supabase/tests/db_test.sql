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

insert into public.org_units (org_id, key, label, dept_name, doc_number_format, is_default) values
    ('11111111-1111-1111-1111-111111111111', 'sport-promotion', 'กลุ่มงานส่งเสริมกีฬา', 'กองการกีฬา (กลุ่มงานส่งเสริมกีฬา)', '{gap}/{year}', true);
update public.org_units set recipient = 'หัวหน้ากลุ่มงานส่งเสริมกีฬา',
    signers = '[{"name": "", "position": "ผู้เสนอเรื่อง", "is_author": true}]' where key = 'sport-promotion';
select pg_temp.check((select signers->0->>'position' from public.org_units where key = 'sport-promotion') = 'ผู้เสนอเรื่อง',
    'เก็บผู้ลงนามของหน่วยเป็น JSON');
select pg_temp.expect_error($$update public.org_units set signers = '{"name": "x"}' where key = 'sport-promotion'$$,
    'ผู้ลงนามต้องเป็นรายการ (array)');

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

-- ฉบับจริง (ไฟล์ Word ที่แก้เสร็จ): เลขฉบับต่อเนื่อง, path ต้องอยู่ใน <org>/finals/
select pg_temp.check((public.register_final_file('33333333-3333-3333-3333-333333333333',
    '11111111-1111-1111-1111-111111111111/finals/11111111111111111111111111111111.docx', 'ฉบับจริง.docx', 'application/x', 100, 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa')).revision = 1,
    'ฉบับจริงฉบับที่ 1');
select pg_temp.check((public.register_final_file('33333333-3333-3333-3333-333333333333',
    '11111111-1111-1111-1111-111111111111/finals/22222222222222222222222222222222.docx', 'แก้ครั้งที่ 2.docx', 'application/x', 120, 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa',
    'ข้อความ', 'กท 1205/45', null, 'เรื่องทดสอบ', 'แก้คำผิด')).revision = 2, 'อัปโหลดใหม่ = ฉบับที่ 2');
select pg_temp.expect_error($$select public.register_final_file('33333333-3333-3333-3333-333333333333',
    '11111111-1111-1111-1111-111111111111/33333333333333333333333333333333.docx', 'x.docx', 'm', 1, 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa')$$,
    'ฉบับจริงนอกโฟลเดอร์ finals');
select pg_temp.expect_error($$insert into public.final_files (org_id, document_id, revision, storage_path, filename, mime,
    size_bytes, sha256, uploaded_by) values ('11111111-1111-1111-1111-111111111111', '33333333-3333-3333-3333-333333333333',
    9, '11111111-1111-1111-1111-111111111111/finals/x.docx', 'x', 'm', 1, 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa', auth.uid())$$,
    'เพิ่มฉบับจริงตรงโดยไม่ผ่านฟังก์ชัน');
select pg_temp.expect_error($$update public.final_files set filename = 'แก้ชื่อ'$$, 'แก้ข้อมูลฉบับจริง');
select pg_temp.check((select count(*) from public.audit_log where entity = 'final_files') = 2, 'audit ฉบับจริง');
-- ไฟล์ฉบับจริงใน Storage ลบไม่ได้แม้เป็นคนอัปโหลด (ไฟล์ต้นเรื่องยังลบของตัวเองได้)
insert into storage.objects (bucket_id, name) values ('sources', '11111111-1111-1111-1111-111111111111/finals/11111111111111111111111111111111.docx');
insert into storage.objects (bucket_id, name) values ('sources', '11111111-1111-1111-1111-111111111111/finals/rejected.docx');
insert into storage.objects (bucket_id, name) values ('sources', '11111111-1111-1111-1111-111111111111/tmp.pdf');
delete from storage.objects where name like '%/finals/%';
select pg_temp.check((select count(*) from storage.objects where name like '%/finals/1111%') = 1, 'ลบไฟล์ฉบับจริงที่บันทึกแล้วไม่ได้');
select pg_temp.check((select count(*) from storage.objects where name like '%/finals/rejected.docx') = 0, 'ลบไฟล์ที่ตรวจไม่ผ่านได้');
delete from storage.objects where name like '%/tmp.pdf';
select pg_temp.check((select count(*) from storage.objects where name like '%/tmp.pdf') = 0, 'ลบไฟล์ต้นเรื่องของตัวเองได้');

-- Storage: อัปโหลดได้เฉพาะโฟลเดอร์หน่วยงานตัวเอง
insert into storage.objects (bucket_id, name) values ('sources', '11111111-1111-1111-1111-111111111111/a.pdf');
select pg_temp.expect_error($$insert into storage.objects (bucket_id, name)
    values ('sources', '22222222-2222-2222-2222-222222222222/x.pdf')$$, 'อัปโหลดเข้าโฟลเดอร์หน่วยงานอื่น');

-- หน่วยออกหนังสือ: drafter อ่านได้แต่เพิ่มไม่ได้ (admin เท่านั้น)
select pg_temp.expect_error($$insert into public.org_units (org_id, key, label, dept_name)
    values ('11111111-1111-1111-1111-111111111111', 'x-unit', 'X', 'X')$$, 'drafter เพิ่มหน่วยออกหนังสือ');

select pg_temp.check((select ok from public.verify_audit_chain()), 'audit chain ถูกต้อง');
select pg_temp.check((select count(*) from public.audit_log) >= 10, 'มี audit อัตโนมัติ');
commit;

-- ---------------------------------------------------------------- ทะเบียนรับ-ส่ง (migration 13)
begin;
set local role authenticated;
set local request.jwt.claims = '{"sub":"00000000-0000-0000-0000-00000000000a"}';
insert into public.documents (id, org_id, owner_id, subject) values
    ('44444444-4444-4444-4444-444444444444', '11111111-1111-1111-1111-111111111111', '00000000-0000-0000-0000-00000000000a', 'ตอบหนังสือ'),
    ('66666666-6666-6666-6666-666666666666', '11111111-1111-1111-1111-111111111111', '00000000-0000-0000-0000-00000000000a', 'ใช้เลขที่จอง');
insert into public.source_files (id, org_id, uploaded_by, storage_path, filename) values
    ('55555555-5555-5555-5555-555555555555', '11111111-1111-1111-1111-111111111111', '00000000-0000-0000-0000-00000000000a',
     '11111111-1111-1111-1111-111111111111/src.pdf', 'src.pdf');

-- ลงรับต้นเรื่อง ผูกไฟล์และเอกสารที่ร่างจากต้นเรื่อง; ไฟล์เดิมลงรับซ้ำไม่ได้
select pg_temp.check((select reg_no = 3 and document_id = '44444444-4444-4444-4444-444444444444'
    from public.register_incoming('ศธ ๐๔/๗', '๑ พฤศจิกายน ๒๕๖๙', 'กรม ค', 'ขอความอนุเคราะห์', '',
         '55555555-5555-5555-5555-555555555555', '', '44444444-4444-4444-4444-444444444444')), 'ลงรับผูกต้นเรื่องและเอกสาร');
select pg_temp.expect_error($$select public.register_incoming('x', 'y', 'z', 'w', '', '55555555-5555-5555-5555-555555555555')$$,
    'ต้นเรื่องเดิมลงรับซ้ำ');
select pg_temp.check((select action from public.audit_log where entity = 'incoming_register' order by id desc limit 1) = 'receive',
    'audit ลงรับ');

-- รูปแบบเลขอยู่หน้า (กลุ่มงาน ___/๒๕๖๙): เล่มของตัวเอง เลขไทยตามปี
select pg_temp.check((public.issue_outgoing_number('', 'บันทึก', 'หัวหน้ากลุ่มงาน', '๑๖ พฤศจิกายน ๒๕๖๙', null, '/๒๕๖๙')).doc_number = '๑/๒๕๖๙', 'เลขหน้า/ปี');
select pg_temp.check((public.issue_outgoing_number('', 'บันทึก ๒', '', null, null, '/๒๕๖๙')).doc_number = '๒/๒๕๖๙', 'เลขหน้า/ปี ถัดไป');
select pg_temp.expect_error($$select public.issue_outgoing_number(' ', 'ไม่มีรหัส')$$, 'ออกเลขโดยไม่มีรหัส');

-- ออกเลขผูกเอกสาร + หนังสือรับ → ออกแล้ว (issued) พร้อมผู้ออกเลข
select pg_temp.check((public.issue_outgoing_number('กท 1205/', 'ตอบ', 'กรม ค', '๑๖ พฤศจิกายน ๒๕๖๙',
    '44444444-4444-4444-4444-444444444444', '', 'กองการกีฬา', false, false,
    (select id from public.incoming_register where source_file_id = '55555555-5555-5555-5555-555555555555'))).doc_number = 'กท 1205/1',
    'ออกเลขจากหน้าแก้ไข');
select pg_temp.check((select status = 'issued' and issued_by = auth.uid() and issued_at is not null and incoming_id is not null
    and to_recipient = 'กรม ค' and doc_date = '๑๖ พฤศจิกายน ๒๕๖๙' from public.outgoing_register where doc_number = 'กท 1205/1'),
    'ทะเบียนส่งมี วันที่ เรื่อง ผู้รับ ผู้ออกเลข');
select pg_temp.check((select doc_number = 'กท 1205/1' and status = 'numbered' from public.documents
    where id = '44444444-4444-4444-4444-444444444444'), 'เอกสารได้เลขที่');
select pg_temp.expect_error($$select public.issue_outgoing_number('กท 1205/', 'ซ้ำ', '', null, '44444444-4444-4444-4444-444444444444')$$,
    'ออกเลขซ้ำให้เอกสารเดิม');
select pg_temp.expect_error($$select public.issue_outgoing_number('กท 1205/', 'x', '', null, null, '', '', false, false, 999999)$$,
    'ผูกหนังสือรับที่ไม่มี');

-- ยกเลิก → เลขยังอยู่ในทะเบียนพร้อมเหตุผล ถอดจากเอกสาร ออกใหม่ได้เลขถัดไป (ไม่นำเลขเดิมกลับมา)
select pg_temp.check((select cancelled_by = auth.uid() and cancelled_at is not null and cancel_reason = 'พิมพ์ผู้รับผิด'
    from public.cancel_outgoing_number((select id from public.outgoing_register where doc_number = 'กท 1205/1'), ' พิมพ์ผู้รับผิด ')),
    'ยกเลิกเลขบันทึกผู้ยกเลิก');
select pg_temp.check((select doc_number is null and status = 'draft' from public.documents
    where id = '44444444-4444-4444-4444-444444444444'), 'ยกเลิกแล้วเอกสารไม่มีเลข');
select pg_temp.check((public.issue_outgoing_number('กท 1205/', 'ตอบ', 'กรม ค', null, '44444444-4444-4444-4444-444444444444')).doc_number = 'กท 1205/2',
    'เลขที่ยกเลิกไม่ถูกนำกลับมาใช้');
select pg_temp.check((select count(*) from public.outgoing_register where doc_number = 'กท 1205/1' and status = 'cancelled') = 1,
    'เลขที่ยกเลิกยังอยู่ในทะเบียน');

-- จองล่วงหน้า แล้วนำมาใช้กับเอกสาร
select pg_temp.check((public.issue_outgoing_number('กท 1205/', 'จองไว้', '', null, null, '', '', false, true)).status = 'reserved', 'จองเลข');
select pg_temp.check((select status = 'issued' and subject = 'เรื่องจริง' and to_recipient = 'ผู้รับ' and document_id = '66666666-6666-6666-6666-666666666666'
    from public.use_reserved_number((select id from public.outgoing_register where doc_number = 'กท 1205/3'),
         '66666666-6666-6666-6666-666666666666', 'เรื่องจริง', 'ผู้รับ', '๑๗ พฤศจิกายน ๒๕๖๙')), 'ใช้เลขที่จองไว้');
select pg_temp.check((select doc_number from public.documents where id = '66666666-6666-6666-6666-666666666666') = 'กท 1205/3',
    'เอกสารได้เลขที่จองไว้');
select pg_temp.expect_error($$select public.use_reserved_number((select id from public.outgoing_register where doc_number = 'กท 1205/3'))$$,
    'ใช้เลขที่จองซ้ำ');
select pg_temp.expect_error($$select public.use_reserved_number((select id from public.outgoing_register where doc_number = 'กท 1205/2'),
    '66666666-6666-6666-6666-666666666666')$$, 'ใช้เลขที่ออกแล้ว');

-- audit: ใคร ทำอะไร กับเลขไหน
select pg_temp.check((select array_agg(action order by id) from public.audit_log
    where entity = 'outgoing_register' and details->>'doc_number' like 'กท 1205/%') = array['issue', 'cancel', 'issue', 'reserve', 'issue'],
    'ชื่อการกระทำใน audit');
select pg_temp.check((select bool_and(actor_id = auth.uid()) from public.audit_log where entity = 'outgoing_register'), 'audit มีผู้กระทำ');
select pg_temp.check((select ok from public.verify_audit_chain()), 'audit chain ถูกต้องหลังออก/ยกเลิกเลข');
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
select pg_temp.check((select count(*) from public.org_units) = 0, 'B มองไม่เห็นหน่วยของ ก');
select pg_temp.check((select count(*) from public.final_files) = 0, 'B มองไม่เห็นฉบับจริงของ ก');
select pg_temp.expect_error($$select public.register_final_file('33333333-3333-3333-3333-333333333333',
    '22222222-2222-2222-2222-222222222222/finals/44444444444444444444444444444444.docx', 'x.docx', 'm', 1, 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa')$$,
    'B เพิ่มฉบับจริงให้เอกสารของ ก');
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
select pg_temp.expect_error($$delete from public.final_files$$, 'ลบฉบับจริง');

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
