-- =============================================================================
-- ฉบับจริง: ไฟล์ Word/PDF ที่ผู้ใช้แก้เสร็จใน Word แล้วอัปโหลดกลับเข้าระบบ
--   - เก็บไฟล์ตามที่ได้รับทุกไบต์ใน bucket "sources" โฟลเดอร์ <org_id>/finals/
--   - เขียนเพิ่มอย่างเดียว (แก้/ลบไม่ได้) อัปโหลดใหม่ = ฉบับที่ 2, 3, ... ของเอกสารเดิม
--   - ไม่มีกำหนดลบอัตโนมัติ (ต่างจากไฟล์ต้นเรื่องที่ลบใน 30 วัน)
--   - เพิ่มผ่านฟังก์ชัน register_final_file เท่านั้น (ออกเลขฉบับต่อเนื่องไม่ชนกัน)
-- รันซ้ำได้
-- =============================================================================
create table if not exists public.final_files (
    id             uuid primary key default gen_random_uuid(),
    org_id         uuid not null references public.organizations (id),
    document_id    uuid not null references public.documents (id) on delete restrict,
    revision       integer not null check (revision > 0),
    storage_path   text not null unique,
    filename       text not null check (length(trim(filename)) > 0),
    mime           text not null,
    size_bytes     bigint not null check (size_bytes > 0),
    sha256         text not null check (sha256 ~ '^[0-9a-f]{64}$'),
    extracted_text text,
    doc_number     text,              -- "ที่" ที่อ่านได้จากไฟล์ (ถ้ามี)
    doc_date       text,
    subject        text,
    note           text,
    uploaded_by    uuid not null references auth.users (id),
    created_at     timestamptz not null default now(),
    unique (document_id, revision),
    check (storage_path like org_id::text || '/finals/%')
);
create index if not exists final_files_document_idx on public.final_files (document_id, revision desc);
create index if not exists final_files_org_idx on public.final_files (org_id, created_at desc);

alter table public.final_files enable row level security;
drop policy if exists final_files_select on public.final_files;
create policy final_files_select on public.final_files
    for select to authenticated using (org_id = (select public.current_org_id()));
revoke all on public.final_files from anon;
revoke insert, update, delete on public.final_files from authenticated;

drop trigger if exists final_files_immutable on public.final_files;
create trigger final_files_immutable before update or delete on public.final_files
    for each row execute function public.forbid_change();

-- ---------------------------------------------------------------- บันทึกฉบับจริง
create or replace function public.register_final_file(
    p_document_id    uuid,
    p_storage_path   text,
    p_filename       text,
    p_mime           text,
    p_size_bytes     bigint,
    p_sha256         text,
    p_extracted_text text default null,
    p_doc_number     text default null,
    p_doc_date       text default null,
    p_subject        text default null,
    p_note           text default null
)
returns public.final_files
language plpgsql
volatile
security definer
set search_path = ''
as $$
declare
    v_org uuid := public._require_org();
    v_revision integer;
    v_row public.final_files;
begin
    -- ล็อกแถวเอกสาร: อัปโหลดพร้อมกันได้เลขฉบับต่อเนื่อง
    perform 1 from public.documents d where d.id = p_document_id and d.org_id = v_org for update;
    if not found then
        raise exception 'ไม่พบเอกสารนี้ในหน่วยงาน' using errcode = '42501';
    end if;
    if p_storage_path not like v_org::text || '/finals/%' then
        raise exception 'path ของไฟล์ฉบับจริงไม่ถูกต้อง' using errcode = '42501';
    end if;
    select coalesce(max(f.revision), 0) + 1 into v_revision
      from public.final_files f where f.document_id = p_document_id;
    insert into public.final_files
        (org_id, document_id, revision, storage_path, filename, mime, size_bytes, sha256,
         extracted_text, doc_number, doc_date, subject, note, uploaded_by)
    values
        (v_org, p_document_id, v_revision, p_storage_path, left(p_filename, 255), p_mime, p_size_bytes,
         lower(p_sha256), p_extracted_text, left(p_doc_number, 200), left(p_doc_date, 200),
         left(p_subject, 500), left(p_note, 500), auth.uid())
    returning * into v_row;
    perform public.write_audit(v_org, 'insert', 'final_files', v_row.id::text,
        jsonb_build_object('document_id', p_document_id, 'revision', v_revision, 'filename', v_row.filename,
                           'size_bytes', p_size_bytes, 'sha256', v_row.sha256));
    return v_row;
end
$$;
revoke execute on function public.register_final_file(uuid, text, text, text, bigint, text, text, text, text, text, text)
    from public, anon;
grant execute on function public.register_final_file(uuid, text, text, text, bigint, text, text, text, text, text, text)
    to authenticated;

-- ---------------------------------------------------------------- Storage
-- ไฟล์ฉบับจริงที่บันทึกแล้วลบไม่ได้ แม้เป็นคนอัปโหลดเอง
-- (ไฟล์ที่อัปโหลดแต่ตรวจไม่ผ่าน ยังไม่ถูกบันทึก ผู้อัปโหลดลบได้ — เซิร์ฟเวอร์ลบทิ้งให้อัตโนมัติ)
drop policy if exists sources_delete_own on storage.objects;
create policy sources_delete_own on storage.objects
    for delete to authenticated
    using (bucket_id = 'sources'
           and owner_id = (select auth.uid())::text
           and (storage.foldername(name))[1] = (select public.current_org_id())::text
           and not exists (select 1 from public.final_files f where f.storage_path = name));
