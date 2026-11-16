-- =============================================================================
-- ลบเอกสารถาวรจากถังขยะ (คืนพื้นที่จัดเก็บ)
--   - ลบได้เฉพาะ "ร่าง" ที่อยู่ในถังขยะ (status archived) และยังไม่เป็นหนังสือจริง:
--       ยังไม่ออกเลข / ไม่อยู่ในทะเบียนส่ง / ไม่มีฉบับจริงที่อัปโหลด (final_files)
--   - ผู้ลบต้องเป็นเจ้าของเอกสารหรือผู้ดูแล (admin) ของหน่วยงาน
--   - ลบ: เอกสาร, ประวัติเวอร์ชัน, แชต, แถวไฟล์ต้นเรื่อง — ตัวไฟล์ใน Storage ลบผ่าน Storage API
--     (Supabase ไม่ให้ลบไฟล์ด้วย SQL) จึงเข้าคิว storage_purge_queue ให้เซิร์ฟเวอร์ลบต่อ
--   - บันทึกการลบไว้ใน audit_log (ใคร เมื่อไร เรื่องอะไร) — audit ยังแก้/ลบไม่ได้เหมือนเดิม
-- รันซ้ำได้
-- =============================================================================

-- ---------------------------------------------------------------- ปลดล็อกเฉพาะตอนลบถาวร
-- เอกสาร/เวอร์ชันยังห้ามลบเสมอ ยกเว้นภายใน purge_document ของเอกสารฉบับนั้น (ตั้งค่าเฉพาะ transaction)
create or replace function public.forbid_change()
returns trigger
language plpgsql
set search_path = ''
as $$
declare
    v_purge text := current_setting('govdoc.purge_document', true);
begin
    if tg_op = 'DELETE' and coalesce(v_purge, '') <> '' and (
        (tg_table_name = 'documents' and old.id::text = v_purge)
        or (tg_table_name = 'document_versions' and old.document_id::text = v_purge)
    ) then
        return old;
    end if;
    raise exception '% ห้าม% (บันทึกนี้แก้ไขหรือลบไม่ได้)', tg_table_name,
        case tg_op when 'DELETE' then 'ลบ' else 'แก้ไข' end
        using errcode = '42501';
end
$$;

-- ---------------------------------------------------------------- คิวไฟล์ที่รอลบจาก Storage
create table if not exists public.storage_purge_queue (
    id           bigint generated always as identity primary key,
    org_id       uuid not null references public.organizations (id),
    bucket       text not null default 'sources',
    storage_path text not null,
    queued_at    timestamptz not null default now(),
    unique (bucket, storage_path),
    check (storage_path like org_id::text || '/%')
);
alter table public.storage_purge_queue enable row level security;
drop policy if exists storage_purge_queue_select on public.storage_purge_queue;
create policy storage_purge_queue_select on public.storage_purge_queue
    for select to authenticated using (org_id = (select public.current_org_id()));
revoke all on public.storage_purge_queue from anon;
revoke insert, update, delete on public.storage_purge_queue from authenticated;

-- ไฟล์ที่อยู่ในคิวลบ: ทุกคนในหน่วยงานลบผ่าน Storage API ได้ (ปกติลบได้เฉพาะไฟล์ที่ตัวเองอัปโหลด)
drop policy if exists sources_delete_purged on storage.objects;
create policy sources_delete_purged on storage.objects
    for delete to authenticated
    using (bucket_id = 'sources'
           and (storage.foldername(name))[1] = (select public.current_org_id())::text
           and exists (select 1 from public.storage_purge_queue q
                       where q.bucket = 'sources' and q.storage_path = name
                         and q.org_id = (select public.current_org_id())));

-- ---------------------------------------------------------------- ลบถาวร
create or replace function public.purge_document(p_document_id uuid)
returns setof text            -- path ไฟล์ใน Storage ที่ต้องลบต่อ
language plpgsql
volatile
security definer
set search_path = ''
as $$
declare
    v_org   uuid := public._require_org();
    v_doc   public.documents;
    v_src   uuid;
    v_paths text[];
    v_versions integer;
begin
    select * into v_doc from public.documents
     where id = p_document_id and org_id = v_org for update;
    if not found then
        raise exception 'ไม่พบเอกสาร' using errcode = 'P0002';
    end if;
    if v_doc.owner_id <> auth.uid() and not public.current_role_is('admin') then
        raise exception 'ลบถาวรได้เฉพาะเจ้าของเอกสารหรือผู้ดูแลหน่วยงาน' using errcode = '42501';
    end if;
    if v_doc.status <> 'archived' then
        raise exception 'ต้องย้ายเอกสารไปถังขยะก่อนจึงลบถาวรได้' using errcode = '22023';
    end if;
    if v_doc.doc_number is not null
       or exists (select 1 from public.outgoing_register r where r.document_id = p_document_id) then
        raise exception 'เอกสารนี้ออกเลขที่หนังสือแล้ว เป็นหนังสือราชการจริง ลบถาวรไม่ได้' using errcode = '42501';
    end if;
    if exists (select 1 from public.final_files f where f.document_id = p_document_id) then
        raise exception 'เอกสารนี้มีฉบับจริงที่อัปโหลดแล้ว ลบถาวรไม่ได้' using errcode = '42501';
    end if;

    -- ไฟล์ต้นเรื่อง: ผูกด้วย document_id หรืออ้างจาก workspace (อัปโหลดก่อนสร้างเอกสาร)
    begin
        v_src := nullif(v_doc.workspace ->> 'sourceFileId', '')::uuid;
    exception when invalid_text_representation then
        v_src := null;
    end;
    select coalesce(array_agg(s.storage_path), '{}') into v_paths
      from public.source_files s
     where s.org_id = v_org
       and (s.document_id = p_document_id
            or (s.id = v_src and not exists (
                    select 1 from public.documents d
                     where d.id <> p_document_id and d.org_id = v_org
                       and d.workspace ->> 'sourceFileId' = s.id::text)));

    insert into public.storage_purge_queue (org_id, bucket, storage_path)
    select v_org, 'sources', p from unnest(v_paths) p
    on conflict (bucket, storage_path) do nothing;
    delete from public.source_files where org_id = v_org and storage_path = any (v_paths);

    delete from public.conversations where document_id = p_document_id;   -- ข้อความลบตาม (cascade)

    select count(*) into v_versions from public.document_versions where document_id = p_document_id;
    perform set_config('govdoc.purge_document', p_document_id::text, true);
    delete from public.document_versions where document_id = p_document_id;
    delete from public.documents where id = p_document_id;
    perform set_config('govdoc.purge_document', '', true);

    perform public.write_audit(v_org, 'purge', 'documents', p_document_id::text, jsonb_build_object(
        'subject', v_doc.subject, 'owner_id', v_doc.owner_id, 'created_at', v_doc.created_at,
        'versions', v_versions, 'files', coalesce(array_length(v_paths, 1), 0)));

    return query select unnest(v_paths);
end
$$;
revoke execute on function public.purge_document(uuid) from public, anon;
grant execute on function public.purge_document(uuid) to authenticated;

-- เซิร์ฟเวอร์ลบไฟล์ใน Storage สำเร็จแล้ว → เอาออกจากคิว
create or replace function public.storage_purge_done(p_paths text[])
returns integer
language sql
volatile
security definer
set search_path = ''
as $$
    with d as (
        delete from public.storage_purge_queue
         where org_id = public._require_org() and storage_path = any (p_paths)
        returning 1
    )
    select count(*)::integer from d
$$;
revoke execute on function public.storage_purge_done(text[]) from public, anon;
grant execute on function public.storage_purge_done(text[]) to authenticated;

notify pgrst, 'reload schema';
