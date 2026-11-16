-- =============================================================================
-- ทะเบียนรับ-ส่ง: ออกเลขจากหน้าแก้ไข, ใช้เลขที่จองไว้, เชื่อมหนังสือรับกับหนังสือตอบ
--
-- ต่อยอด migration 2 (reserve_outgoing_number / cancel_outgoing_number / register_incoming)
--   issue_outgoing_number   ออกเลข (หรือจองล่วงหน้า) ต่อหน่วยงาน ต่อรหัส ต่อปี พ.ศ.
--                           รองรับรูปแบบที่เลขอยู่หน้า เช่น "๑๒/๒๕๖๙" (p_suffix = '/๒๕๖๙')
--                           ผูกเอกสาร: ล็อกแถวเอกสาร กดซ้ำ/สองคนพร้อมกันไม่ได้สองเลข
--   use_reserved_number     นำเลขที่จองไว้มาใช้กับเอกสาร (reserved → issued)
--   cancel_outgoing_number  (แทนของเดิม) บันทึกผู้ยกเลิก/เวลา และถอดเลขออกจากเอกสาร
--   register_incoming       (แทนของเดิม) ผูกเอกสารที่ร่างจากต้นเรื่อง; ต้นเรื่องเดียวลงรับได้ครั้งเดียว
--   audit_row_change        (แทนของเดิม) ชื่อการกระทำ reserve / issue / cancel / receive
-- เลขที่ออกแล้วไม่ถูกนำกลับมาใช้ (ตัวนับเดินหน้าอย่างเดียว) และทะเบียนห้ามลบ (trigger เดิม)
-- =============================================================================

-- ---------------------------------------------------------------- คอลัมน์ใหม่
alter table public.outgoing_register
    add column if not exists incoming_id  bigint references public.incoming_register (id) on delete set null,
    add column if not exists issued_at    timestamptz,
    add column if not exists issued_by    uuid references auth.users (id),
    add column if not exists cancelled_at timestamptz,
    add column if not exists cancelled_by uuid references auth.users (id);
create index if not exists outgoing_register_incoming_idx on public.outgoing_register (incoming_id);
create index if not exists outgoing_register_year_idx on public.outgoing_register (org_id, year_be, reg_no);
create index if not exists outgoing_register_issued_by_idx on public.outgoing_register (issued_by);
create index if not exists outgoing_register_cancelled_by_idx on public.outgoing_register (cancelled_by);

-- เอกสารที่ร่างจากหนังสือรับฉบับนี้ (หนังสือตอบ/บันทึกเสนอ)
alter table public.incoming_register
    add column if not exists document_id uuid references public.documents (id) on delete set null;
create index if not exists incoming_register_document_idx on public.incoming_register (document_id);
create index if not exists incoming_register_year_idx on public.incoming_register (org_id, year_be, reg_no);
-- ต้นเรื่องไฟล์เดียวลงรับได้ครั้งเดียว (กดซ้ำ/สองคนพร้อมกันไม่ได้เลขรับสองเลข)
create unique index if not exists incoming_register_source_file_uidx
    on public.incoming_register (org_id, source_file_id) where source_file_id is not null;

-- ---------------------------------------------------------------- ตัวช่วย
-- เล่มทะเบียนส่ง: แยกตามรหัส (และส่วนท้าย) — หนังสือเวียนมีเล่มของตัวเอง; ไม่มีส่วนท้าย = ชื่อเล่มเดิมของ migration 2
create or replace function public.outgoing_book(p_prefix text, p_suffix text, p_is_circular boolean)
returns text
language sql
immutable
set search_path = ''
as $$
    select 'outgoing:' || coalesce(p_prefix, '') || case when p_is_circular then 'ว' else '' end
           || case when coalesce(p_suffix, '') <> '' then '|' || p_suffix else '' end
$$;

-- ห้ามออกเลขซ้ำให้เอกสารเดียว: ล็อกแถวเอกสาร แล้วดูว่ามีเลขที่ยังไม่ยกเลิกอยู่หรือไม่ (ภายในเท่านั้น)
create or replace function public._lock_document_for_number(p_org uuid, p_document_id uuid, p_except bigint)
returns void
language plpgsql
volatile
security definer
set search_path = ''
as $$
declare
    v_existing text;
begin
    perform 1 from public.documents d where d.id = p_document_id and d.org_id = p_org for update;
    if not found then
        raise exception 'ไม่พบเอกสารนี้ในหน่วยงาน' using errcode = '42501';
    end if;
    select o.doc_number into v_existing
      from public.outgoing_register o
     where o.org_id = p_org and o.document_id = p_document_id and o.status <> 'cancelled'
       and o.id is distinct from p_except
     order by o.id desc limit 1;
    if v_existing is not null then
        raise exception 'เอกสารนี้ออกเลขแล้ว: % (ยกเลิกเลขเดิมก่อนจึงออกใหม่ได้)', v_existing using errcode = '23505';
    end if;
end
$$;
revoke execute on function public._lock_document_for_number(uuid, uuid, bigint) from public, anon, authenticated;

create or replace function public._check_incoming(p_org uuid, p_incoming_id bigint)
returns void
language plpgsql
stable
security definer
set search_path = ''
as $$
begin
    if p_incoming_id is not null and not exists (
        select 1 from public.incoming_register i where i.id = p_incoming_id and i.org_id = p_org
    ) then
        raise exception 'ไม่พบหนังสือรับนี้ในหน่วยงาน' using errcode = '42501';
    end if;
end
$$;
revoke execute on function public._check_incoming(uuid, bigint) from public, anon, authenticated;

-- ---------------------------------------------------------------- ออกเลข / จองเลข
create or replace function public.issue_outgoing_number(
    p_prefix       text,
    p_subject      text,
    p_to_recipient text default '',
    p_doc_date     text default null,
    p_document_id  uuid default null,
    p_suffix       text default '',
    p_from_unit    text default '',
    p_is_circular  boolean default false,
    p_reserve_only boolean default false,
    p_incoming_id  bigint default null
)
returns public.outgoing_register
language plpgsql
volatile
security definer
set search_path = ''
as $$
declare
    v_org    uuid := public._require_org();
    v_year   integer := public.bangkok_year_be();
    v_prefix text := coalesce(p_prefix, '');
    v_suffix text := coalesce(p_suffix, '');
    v_book   text;
    v_no     integer;
    v_num    text;
    v_row    public.outgoing_register;
begin
    if length(trim(v_prefix || v_suffix)) = 0 then
        raise exception 'ต้องระบุรหัสหนังสือ (เช่น กท ๑๒๓๔/)' using errcode = '22023';
    end if;
    if p_document_id is not null then
        perform public._lock_document_for_number(v_org, p_document_id, null);
    end if;
    perform public._check_incoming(v_org, p_incoming_id);

    -- เลขลำดับจากตัวนับในฐานข้อมูล (INSERT ... ON CONFLICT ล็อกแถว) — ไม่ซ้ำแม้กดพร้อมกัน, เริ่ม ๑ ทุกปี พ.ศ.
    v_book := public.outgoing_book(v_prefix, v_suffix, p_is_circular);
    v_no := public.issue_reg_no(v_org, v_book, v_year);
    v_num := v_no::text;
    -- ตัวเลขชุดเดียวกันทั้งเลขที่: รหัส/ปีเป็นเลขไทย → เลขลำดับเป็นเลขไทย
    if (v_prefix || v_suffix) ~ '[๐-๙]' then
        v_num := public.to_thai_digits(v_num);
    end if;

    insert into public.outgoing_register
        (org_id, book, year_be, reg_no, doc_number, doc_date, from_unit, to_recipient, subject,
         status, document_id, incoming_id, created_by, issued_at, issued_by)
    values
        (v_org, v_book, v_year, v_no,
         v_prefix || case when p_is_circular then 'ว ' else '' end || v_num || v_suffix,
         nullif(trim(coalesce(p_doc_date, '')), ''), coalesce(p_from_unit, ''), coalesce(p_to_recipient, ''),
         coalesce(p_subject, ''),
         case when p_reserve_only then 'reserved' else 'issued' end,
         p_document_id, p_incoming_id, auth.uid(),
         case when p_reserve_only then null else now() end,
         case when p_reserve_only then null else auth.uid() end)
    returning * into v_row;

    if p_document_id is not null then
        update public.documents d
           set doc_number = v_row.doc_number,
               status = case when d.status in ('draft', 'review', 'approved') then 'numbered' else d.status end
         where d.id = p_document_id;
    end if;
    return v_row;
end
$$;

-- นำเลขที่จองไว้มาใช้ (reserved → issued) พร้อมเติม เรื่อง/ถึง/ลงวันที่ ที่ยังว่าง
create or replace function public.use_reserved_number(
    p_id           bigint,
    p_document_id  uuid default null,
    p_subject      text default null,
    p_to_recipient text default null,
    p_doc_date     text default null,
    p_incoming_id  bigint default null
)
returns public.outgoing_register
language plpgsql
volatile
security definer
set search_path = ''
as $$
declare
    v_org uuid := public._require_org();
    v_row public.outgoing_register;
begin
    if p_document_id is not null then
        perform public._lock_document_for_number(v_org, p_document_id, p_id);
    end if;
    perform public._check_incoming(v_org, p_incoming_id);

    update public.outgoing_register o
       set status       = 'issued',
           document_id  = coalesce(p_document_id, o.document_id),
           subject      = coalesce(nullif(trim(coalesce(p_subject, '')), ''), o.subject),
           to_recipient = coalesce(nullif(trim(coalesce(p_to_recipient, '')), ''), o.to_recipient),
           doc_date     = coalesce(nullif(trim(coalesce(p_doc_date, '')), ''), o.doc_date),
           incoming_id  = coalesce(p_incoming_id, o.incoming_id),
           issued_at    = now(),
           issued_by    = auth.uid()
     where o.id = p_id and o.org_id = v_org and o.status = 'reserved'
    returning * into v_row;
    if v_row.id is null then
        raise exception 'ไม่พบเลขที่จองไว้ หรือเลขนี้ถูกใช้/ยกเลิกไปแล้ว' using errcode = 'P0002';
    end if;

    if v_row.document_id is not null then
        update public.documents d
           set doc_number = v_row.doc_number,
               status = case when d.status in ('draft', 'review', 'approved') then 'numbered' else d.status end
         where d.id = v_row.document_id;
    end if;
    return v_row;
end
$$;

-- ยกเลิกเลข: รายการยังอยู่ในทะเบียนพร้อมเหตุผล ผู้ยกเลิก เวลา — ตัวนับไม่ย้อน เลขนี้จึงไม่ถูกออกซ้ำ
create or replace function public.cancel_outgoing_number(p_id bigint, p_reason text)
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
       set status = 'cancelled', cancel_reason = trim(p_reason),
           cancelled_at = now(), cancelled_by = auth.uid()
     where o.id = p_id and o.org_id = public._require_org() and o.status <> 'cancelled'
    returning * into v_row;
    if v_row.id is null then
        raise exception 'ไม่พบเลขนี้ หรือถูกยกเลิกไปแล้ว' using errcode = 'P0002';
    end if;
    -- ถอดเลขออกจากเอกสาร (ถ้ายังเป็นเลขนี้) ให้ออกเลขใหม่ได้
    if v_row.document_id is not null then
        update public.documents d
           set doc_number = null,
               status = case when d.status = 'numbered' then 'draft' else d.status end
         where d.id = v_row.document_id and d.doc_number = v_row.doc_number;
    end if;
    return v_row;
end
$$;

-- ---------------------------------------------------------------- ทะเบียนรับ
drop function if exists public.register_incoming(text, text, text, text, text, uuid, text);
create function public.register_incoming(
    p_source_doc_number text,
    p_source_doc_date   text,
    p_from_org          text,
    p_subject           text,
    p_to_unit           text default '',
    p_source_file_id    uuid default null,
    p_remark            text default '',
    p_document_id       uuid default null
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
    v_prev public.incoming_register;
    v_row  public.incoming_register;
begin
    if p_source_file_id is not null then
        if not exists (select 1 from public.source_files f where f.id = p_source_file_id and f.org_id = v_org) then
            raise exception 'ไม่พบไฟล์ต้นเรื่องนี้ในหน่วยงาน' using errcode = '42501';
        end if;
        select * into v_prev from public.incoming_register i
         where i.org_id = v_org and i.source_file_id = p_source_file_id limit 1;
        if v_prev.id is not null then
            raise exception 'ต้นเรื่องนี้ลงรับแล้ว เลขรับ %/%', v_prev.reg_no, v_prev.year_be using errcode = '23505';
        end if;
    end if;
    if p_document_id is not null and not exists (
        select 1 from public.documents d where d.id = p_document_id and d.org_id = v_org
    ) then
        raise exception 'ไม่พบเอกสารนี้ในหน่วยงาน' using errcode = '42501';
    end if;

    insert into public.incoming_register
        (org_id, year_be, reg_no, source_doc_number, source_doc_date, from_org, to_unit,
         subject, remark, source_file_id, document_id, created_by)
    values
        (v_org, v_year, public.issue_reg_no(v_org, 'incoming', v_year),
         coalesce(p_source_doc_number, ''), coalesce(p_source_doc_date, ''), coalesce(p_from_org, ''),
         coalesce(p_to_unit, ''), coalesce(p_subject, ''), coalesce(p_remark, ''),
         p_source_file_id, p_document_id, auth.uid())
    returning * into v_row;
    return v_row;
end
$$;

-- ---------------------------------------------------------------- audit (ชื่อการกระทำชัดเจน)
create or replace function public.audit_row_change()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
declare
    v_details jsonb;
    v_action  text := lower(tg_op);
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
        if tg_op = 'INSERT' then
            v_action := case when new.status = 'reserved' then 'reserve' else 'issue' end;
        elsif new.status = 'cancelled' and old.status <> 'cancelled' then
            v_action := 'cancel';
        elsif new.status = 'issued' and old.status = 'reserved' then
            v_action := 'issue';
        end if;
        v_details := jsonb_build_object('doc_number', new.doc_number, 'status', new.status,
                                        'reg_no', new.reg_no, 'year_be', new.year_be,
                                        'subject', new.subject, 'to_recipient', new.to_recipient,
                                        'document_id', new.document_id, 'cancel_reason', new.cancel_reason);
    elsif tg_table_name = 'incoming_register' then
        if tg_op = 'INSERT' then
            v_action := 'receive';
        end if;
        v_details := jsonb_build_object('reg_no', new.reg_no, 'year_be', new.year_be,
                                        'source_doc_number', new.source_doc_number, 'subject', new.subject,
                                        'document_id', new.document_id);
    elsif tg_table_name = 'source_files' then
        v_details := jsonb_build_object('filename', new.filename, 'size_bytes', new.size_bytes,
                                        'secret_level', new.secret_level);
    else
        v_details := '{}'::jsonb;
    end if;
    perform public.write_audit(new.org_id, v_action, tg_table_name, new.id::text, v_details);
    return new;
end
$$;

-- ---------------------------------------------------------------- สิทธิ์เรียกฟังก์ชัน
revoke execute on function public.issue_outgoing_number(text, text, text, text, uuid, text, text, boolean, boolean, bigint) from public, anon;
revoke execute on function public.use_reserved_number(bigint, uuid, text, text, text, bigint) from public, anon;
revoke execute on function public.register_incoming(text, text, text, text, text, uuid, text, uuid) from public, anon;
revoke execute on function public.cancel_outgoing_number(bigint, text) from public, anon;
grant execute on function public.issue_outgoing_number(text, text, text, text, uuid, text, text, boolean, boolean, bigint) to authenticated;
grant execute on function public.use_reserved_number(bigint, uuid, text, text, text, bigint) to authenticated;
grant execute on function public.register_incoming(text, text, text, text, text, uuid, text, uuid) to authenticated;
grant execute on function public.cancel_outgoing_number(bigint, text) to authenticated;
grant execute on function public.outgoing_book(text, text, boolean) to authenticated;

-- ให้ API (PostgREST) เห็นคอลัมน์/ฟังก์ชันใหม่ทันที
notify pgrst, 'reload schema';

-- ตรวจผลหลังรัน:
--   select count(*) from information_schema.columns
--    where table_name = 'outgoing_register' and column_name in ('incoming_id','issued_at','issued_by','cancelled_at','cancelled_by');  → 5
--   select count(*) from information_schema.columns where table_name = 'incoming_register' and column_name = 'document_id';         → 1
--   select proname, pronargs from pg_proc
--    where proname in ('issue_outgoing_number','use_reserved_number','register_incoming','cancel_outgoing_number') order by 1;
--     → cancel_outgoing_number 2 · issue_outgoing_number 10 · register_incoming 8 · use_reserved_number 6  (register_incoming ต้องเหลือแถวเดียว)
--   select indexname from pg_indexes where indexname = 'incoming_register_source_file_uidx';                                         → 1 แถว
