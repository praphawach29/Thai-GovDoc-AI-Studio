-- =============================================================================
-- ที่เก็บไฟล์ต้นเรื่อง (Supabase Storage)
--   bucket "sources" เป็น private: ต้องล็อกอินและอยู่ในหน่วยงานเดียวกันจึงอ่าน/อัปโหลดได้
--   path ต้องขึ้นต้นด้วย org_id/ เช่น "<org_id>/<uuid>.pdf"
--   เบราว์เซอร์อัปโหลดตรงมาที่ Storage (ไม่ผ่าน Vercel ซึ่งรับ request ได้ราว 4.5 MB)
-- =============================================================================

insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
values (
    'sources', 'sources', false, 52428800,   -- 50 MB
    array[
        'application/pdf',
        'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
        'text/plain',
        'image/png', 'image/jpeg', 'image/tiff'
    ]
)
on conflict (id) do nothing;

create policy sources_select on storage.objects
    for select to authenticated
    using (bucket_id = 'sources'
           and (storage.foldername(name))[1] = (select public.current_org_id())::text);

create policy sources_insert on storage.objects
    for insert to authenticated
    with check (bucket_id = 'sources'
                and (storage.foldername(name))[1] = (select public.current_org_id())::text);

-- ลบได้เฉพาะไฟล์ที่ตัวเองอัปโหลด (เช่น อัปโหลดผิดไฟล์) — การลบตามอายุทำโดยงานหลังบ้าน
create policy sources_delete_own on storage.objects
    for delete to authenticated
    using (bucket_id = 'sources'
           and owner_id = (select auth.uid())::text
           and (storage.foldername(name))[1] = (select public.current_org_id())::text);
