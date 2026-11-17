-- =============================================================================
-- ทะเบียน/เลขที่หนังสือ, เวอร์ชันเอกสาร และ audit แบบต่อ hash
--
-- ฟังก์ชันที่ผู้ใช้เรียกได้ (ผ่าน supabase.rpc / PostgREST):
--   reserve_outgoing_number   ออกเลขหนังสือส่ง (จอง) — atomic ไม่ซ้ำแม้กดพร้อมกัน
--   mark_outgoing_issued      ยืนยันว่าเลขที่จองถูกใช้ส่งจริง
--   cancel_outgoing_number    ยกเลิกเลข (ต้องมีเหตุผล) — ไม่ลบ ไม่นำเลขกลับมาใช้
--   register_incoming         ลงทะเบียนรับ
--   save_document_version     บันทึกเวอร์ชันเอกสาร (เลขเวอร์ชันต่อเนื่อง)
--   verify_audit_chain        ตรวจว่า audit_log ถูกแก้ย้อนหลังหรือไม่
-- =============================================================================

-- ---------------------------------------------------------------- ตัวช่วย
create function public.bangkok_year_be()
returns integer
language sql
stable
set search_path = ''
as $$
    select extract(year from (now() at time zone 'Asia/Bangkok'))::integer + 543
$$;

create function public.to_thai_digits(value text)
returns text
language sql
immutable
set search_path = ''
as $$
    select translate(value, '0123456789', '๐๑๒๓๔๕๖๗๘๙')
$$;

-- ออกเลขลำดับถัดไปของเล่มทะเบียน (ภายในเท่านั้น — ผู้ใช้เรียกผ่านฟังก์ชันระดับบน)
-- INSERT ... ON CONFLICT DO UPDATE ล็อกแถวให้เอง จึงไม่มีเลขซ้ำ; เริ่ม ๑ ใหม่ทุกปีปฏิทิน
create function public.issue_reg_no(p_org uuid, p_book text, p_year_be integer)
returns integer
language sql
volatile
security definer
set search_path = ''
as $$
    insert into public.number_sequences as s (org_id, book, year_be, last_value)
    values (p_org, p_book, p_year_be, 1)
    on conflict (org_id, book, year_be)
    do update set last_value = s.last_value + 1
    returning last_value
$$;
revoke execute on function public.issue_reg_no(uuid, text, integer) from public, anon, authenticated;

create function public._require_org()
returns uuid
language plpgsql
stable
security definer
set search_path = ''
as $$
declare
    v_org uuid := public.current_org_id();
begin
    if v_org is null then
        raise exception 'ผู้ใช้ยังไม่ได้ผูกกับหน่วยงาน' using errcode = '42501';
    end if;
    return v_org;
end
$$;
revoke execute on function public._require_org() from public, anon, authenticated;

-- ---------------------------------------------------------------- audit (ต่อ hash)
-- เขียนบันทึกได้จาก trigger/ฟังก์ชันเท่านั้น (ไม่มี policy insert ให้ผู้ใช้)
create function public.write_audit(
    p_org uuid, p_action text, p_entity text, p_entity_id text, p_details jsonb default '{}'::jsonb
)
returns void
language sql
volatile
security definer
set search_path = ''
as $$
    insert into public.audit_log (org_id, actor_id, action, entity, entity_id, details)
    values (p_org, (select auth.uid()), p_action, p_entity, p_entity_id, coalesce(p_details, '{}'::jsonb))
$$;
revoke execute on function public.write_audit(uuid, text, text, text, jsonb) from public, anon, authenticated;

-- เนื้อหาที่ใช้คำนวณ hash (เวลาแปลงเป็น UTC เพื่อไม่ขึ้นกับ TimeZone ของ session)
create function public.audit_payload(r public.audit_log)
returns text
language sql
stable
set search_path = ''
as $$
    select jsonb_build_object(
        'org_id', r.org_id, 'actor_id', r.actor_id, 'action', r.action, 'entity', r.entity,
        'entity_id', r.entity_id, 'details', r.details,
        'at', to_char(r.at at time zone 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"')
    )::text
$$;

create function public.audit_chain_hash()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
begin
    -- ล็อกต่อหน่วยงาน กัน 2 transaction อ่าน prev_hash ตัวเดียวกันพร้อมกัน
    perform pg_advisory_xact_lock(hashtextextended('audit:' || new.org_id::text, 0));
    select a.hash into new.prev_hash
      from public.audit_log a where a.org_id = new.org_id order by a.id desc limit 1;
    new.hash := encode(sha256(convert_to(coalesce(new.prev_hash, '') || public.audit_payload(new), 'UTF8')), 'hex');
    return new;
end
$$;
create trigger audit_log_chain before insert on public.audit_log
    for each row execute function public.audit_chain_hash();

-- ห้ามแก้/ลบ บันทึกที่ต้องคงไว้ (มีผลกับทุก role รวมถึง service_role)
create function public.forbid_change()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
    raise exception '% ห้าม% (บันทึกนี้แก้ไขหรือลบไม่ได้)', tg_table_name,
        case tg_op when 'DELETE' then 'ลบ' else 'แก้ไข' end
        using errcode = '42501';
end
$$;
create trigger audit_log_immutable before update or delete on public.audit_log
    for each row execute function public.forbid_change();
create trigger document_versions_immutable before update or delete on public.document_versions
    for each row execute function public.forbid_change();
create trigger outgoing_register_no_delete before delete on public.outgoing_register
    for each row execute function public.forbid_change();
create trigger incoming_register_no_delete before delete on public.incoming_register
    for each row execute function public.forbid_change();
create trigger documents_no_delete before delete on public.documents
    for each row execute function public.forbid_change();

create function public.verify_audit_chain()
returns table (ok boolean, checked bigint, first_bad_id bigint)
language plpgsql
stable
security definer
set search_path = ''
as $$
declare
    v_org uuid := public._require_org();
    v_prev text := null;
    v_count bigint := 0;
    r public.audit_log;
begin
    for r in select * from public.audit_log a where a.org_id = v_org order by a.id loop
        v_count := v_count + 1;
        if r.prev_hash is distinct from v_prev
           or r.hash is distinct from encode(sha256(convert_to(coalesce(v_prev, '') || public.audit_payload(r), 'UTF8')), 'hex') then
            return query select false, v_count, r.id;
            return;
        end if;
        v_prev := r.hash;
    end loop;
    return query select true, v_count, null::bigint;
end
$$;

-- ---------------------------------------------------------------- ทะเบียนหนังสือส่ง
create function public.reserve_outgoing_number(
    p_prefix       text,
    p_subject      text,
    p_is_circular  boolean default false,
    p_to_recipient text default '',
    p_document_id  uuid default null
)
returns public.outgoing_register
language plpgsql
volatile
security definer
set search_path = ''
as $$
declare
    v_org  uuid := public._require_org();
    v_year integer := public.bangkok_year_be();
    -- หนังสือเวียนมีเลขชุดของตัวเอง (ระเบียบงานสารบรรณ: เพิ่ม ว หน้าเลข เริ่ม ๑ ทุกปีปฏิทิน)
    v_book text := 'outgoing:' || p_prefix || case when p_is_circular then 'ว' else '' end;
    v_no   integer;
    v_num  text;
    v_row  public.outgoing_register;
begin
    if length(trim(coalesce(p_prefix, ''))) = 0 then
        raise exception 'ต้องระบุรหัสหนังสือ (เช่น กท ๑๒๓๔/)' using errcode = '22023';
    end if;
    if p_document_id is not null and not exists (
        select 1 from public.documents d where d.id = p_document_id and d.org_id = v_org
    ) then
        raise exception 'ไม่พบเอกสารนี้ในหน่วยงาน' using errcode = '42501';
    end if;

    v_no := public.issue_reg_no(v_org, v_book, v_year);
    v_num := v_no::text;
    -- ตัวเลขชุดเดียวกันทั้งเลขที่: รหัสหน่วยงานเป็นเลขไทย → เลขลำดับเป็นเลขไทย
    if p_prefix ~ '[๐-๙]' then
        v_num := public.to_thai_digits(v_num);
    end if;

    insert into public.outgoing_register
        (org_id, book, year_be, reg_no, doc_number, subject, to_recipient, status, document_id, created_by)
    values
        (v_org, v_book, v_year, v_no,
         p_prefix || case when p_is_circular then 'ว ' else '' end || v_num,
         coalesce(p_subject, ''), coalesce(p_to_recipient, ''), 'reserved', p_document_id, auth.uid())
    returning * into v_row;

    if p_document_id is not null then
        update public.documents
           set doc_number = v_row.doc_number, status = 'numbered', updated_at = now()
         where id = p_document_id;
    end if;
    return v_row;
end
$$;

create function public.mark_outgoing_issued(p_id bigint, p_doc_date text default null)
returns public.outgoing_register
language plpgsql
volatile
security definer
set search_path = ''
as $$
declare
    v_row public.outgoing_register;
begin
    update public.outgoing_register o
       set status = 'issued', doc_date = coalesce(p_doc_date, o.doc_date)
     where o.id = p_id and o.org_id = public._require_org() and o.status = 'reserved'
    returning * into v_row;
    if v_row.id is null then
        raise exception 'ไม่พบเลขที่จองไว้ หรือเลขนี้ถูกใช้/ยกเลิกไปแล้ว' using errcode = 'P0002';
    end if;
    return v_row;
end
$$;

create function public.cancel_outgoing_number(p_id bigint, p_reason text)
returns public.outgoing_register
language plpgsql
volatile
security definer
set search_path = ''
as $$
declare
    v_row public.outgoing_register;
begin
    if length(trim(coalesce(p_reason, ''))) = 0 then
        raise exception 'ต้องระบุเหตุผลการยกเลิกเลข' using errcode = '22023';
    end if;
    update public.outgoing_register o
       set status = 'cancelled', cancel_reason = p_reason
     where o.id = p_id and o.org_id = public._require_org() and o.status <> 'cancelled'
    returning * into v_row;
    if v_row.id is null then
        raise exception 'ไม่พบเลขนี้ หรือถูกยกเลิกไปแล้ว' using errcode = 'P0002';
    end if;
    return v_row;
end
$$;

-- ---------------------------------------------------------------- ทะเบียนหนังสือรับ
create function public.register_incoming(
    p_source_doc_number text,
    p_source_doc_date   text,
    p_from_org          text,
    p_subject           text,
    p_to_unit           text default '',
    p_source_file_id    uuid default null,
    p_remark            text default ''
)
returns public.incoming_register
language plpgsql
volatile
security definer
set search_path = ''
as $$
declare
    v_org  uuid := public._require_org();
    v_year integer := public.bangkok_year_be();
    v_row  public.incoming_register;
begin
    if p_source_file_id is not null and not exists (
        select 1 from public.source_files f where f.id = p_source_file_id and f.org_id = v_org
    ) then
        raise exception 'ไม่พบไฟล์ต้นเรื่องนี้ในหน่วยงาน' using errcode = '42501';
    end if;
    insert into public.incoming_register
        (org_id, year_be, reg_no, source_doc_number, source_doc_date, from_org, to_unit,
         subject, remark, source_file_id, created_by)
    values
        (v_org, v_year, public.issue_reg_no(v_org, 'incoming', v_year),
         coalesce(p_source_doc_number, ''), coalesce(p_source_doc_date, ''), coalesce(p_from_org, ''),
         coalesce(p_to_unit, ''), coalesce(p_subject, ''), coalesce(p_remark, ''), p_source_file_id, auth.uid())
    returning * into v_row;
    return v_row;
end
$$;

-- ---------------------------------------------------------------- เวอร์ชันเอกสาร
create function public.save_document_version(
    p_document_id      uuid,
    p_content          jsonb,
    p_edit_instruction text default null,
    p_note             text default null
)
returns integer
language plpgsql
volatile
security definer
set search_path = ''
as $$
declare
    v_org uuid := public._require_org();
    v_version integer;
begin
    -- ล็อกแถวเอกสาร: บันทึกพร้อมกันได้เลขเวอร์ชันต่อเนื่อง ไม่ชนกัน
    update public.documents d
       set current_version = d.current_version + 1,
           subject = coalesce(p_content ->> 'subject', d.subject),
           updated_at = now()
     where d.id = p_document_id and d.org_id = v_org
    returning d.current_version into v_version;
    if v_version is null then
        raise exception 'ไม่พบเอกสารนี้ในหน่วยงาน' using errcode = '42501';
    end if;
    insert into public.document_versions
        (document_id, org_id, version_no, content, edit_instruction, note, created_by)
    values (p_document_id, v_org, v_version, p_content, p_edit_instruction, p_note, auth.uid());
    return v_version;
end
$$;

-- ---------------------------------------------------------------- เก็บ audit อัตโนมัติ
create function public.audit_row_change()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
declare
    v_details jsonb;
begin
    if tg_table_name = 'documents' then
        if tg_op = 'UPDATE' and new.status is not distinct from old.status
           and new.doc_number is not distinct from old.doc_number
           and new.secret_level is not distinct from old.secret_level then
            return new;   -- แก้เนื้อหา/เวลาเฉย ๆ ถูกบันทึกผ่าน document_versions แล้ว
        end if;
        v_details := jsonb_build_object('status', new.status, 'doc_number', new.doc_number,
                                        'secret_level', new.secret_level, 'subject', new.subject);
    elsif tg_table_name = 'document_versions' then
        v_details := jsonb_build_object('document_id', new.document_id, 'version_no', new.version_no,
                                        'edit_instruction', new.edit_instruction);
    elsif tg_table_name = 'outgoing_register' then
        v_details := jsonb_build_object('doc_number', new.doc_number, 'status', new.status,
                                        'subject', new.subject, 'cancel_reason', new.cancel_reason);
    elsif tg_table_name = 'incoming_register' then
        v_details := jsonb_build_object('reg_no', new.reg_no, 'year_be', new.year_be,
                                        'source_doc_number', new.source_doc_number, 'subject', new.subject);
    elsif tg_table_name = 'source_files' then
        v_details := jsonb_build_object('filename', new.filename, 'size_bytes', new.size_bytes,
                                        'secret_level', new.secret_level);
    else
        v_details := '{}'::jsonb;
    end if;
    perform public.write_audit(new.org_id, lower(tg_op), tg_table_name, new.id::text, v_details);
    return new;
end
$$;

create trigger documents_audit after insert or update on public.documents
    for each row execute function public.audit_row_change();
create trigger document_versions_audit after insert on public.document_versions
    for each row execute function public.audit_row_change();
create trigger outgoing_register_audit after insert or update on public.outgoing_register
    for each row execute function public.audit_row_change();
create trigger incoming_register_audit after insert or update on public.incoming_register
    for each row execute function public.audit_row_change();
create trigger source_files_audit after insert on public.source_files
    for each row execute function public.audit_row_change();

-- updated_at ของเอกสาร
create function public.touch_updated_at()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
    new.updated_at := now();
    return new;
end
$$;
create trigger documents_touch before update on public.documents
    for each row execute function public.touch_updated_at();

-- ---------------------------------------------------------------- สิทธิ์เรียกฟังก์ชัน
revoke execute on function public.reserve_outgoing_number(text, text, boolean, text, uuid) from public, anon;
revoke execute on function public.mark_outgoing_issued(bigint, text) from public, anon;
revoke execute on function public.cancel_outgoing_number(bigint, text) from public, anon;
revoke execute on function public.register_incoming(text, text, text, text, text, uuid, text) from public, anon;
revoke execute on function public.save_document_version(uuid, jsonb, text, text) from public, anon;
revoke execute on function public.verify_audit_chain() from public, anon;
revoke execute on function public.audit_chain_hash() from public, anon, authenticated;
revoke execute on function public.audit_row_change() from public, anon, authenticated;
grant execute on function public.reserve_outgoing_number(text, text, boolean, text, uuid) to authenticated;
grant execute on function public.mark_outgoing_issued(bigint, text) to authenticated;
grant execute on function public.cancel_outgoing_number(bigint, text) to authenticated;
grant execute on function public.register_incoming(text, text, text, text, text, uuid, text) to authenticated;
grant execute on function public.save_document_version(uuid, jsonb, text, text) to authenticated;
grant execute on function public.verify_audit_chain() to authenticated;
