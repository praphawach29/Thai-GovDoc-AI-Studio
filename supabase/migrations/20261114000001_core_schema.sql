-- =============================================================================
-- Thai GovDoc AI Studio — โครงสร้างฐานข้อมูลหลัก (Supabase Postgres)
--
-- หลักการ:
--   * ทุกตารางมี org_id ตั้งแต่วันแรก แม้ช่วงทดสอบมีหน่วยงานเดียว/ผู้ใช้คนเดียว
--   * RLS เปิดทุกตาราง: เห็นและเขียนได้เฉพาะแถวของหน่วยงานตัวเอง
--   * ทะเบียนรับ-ส่ง, ประวัติเวอร์ชัน, audit_log: ห้ามลบ/ห้ามเขียนทับ
--     (เปลี่ยนสถานะผ่านฟังก์ชันใน migration ถัดไปเท่านั้น)
--   * วัน/ปี พ.ศ. นับตามเวลาประเทศไทย (Asia/Bangkok) ไม่ใช่เวลาเซิร์ฟเวอร์
-- =============================================================================

-- ---------------------------------------------------------------- หน่วยงาน/ผู้ใช้
create table public.organizations (
    id                uuid primary key default gen_random_uuid(),
    name              text not null check (length(trim(name)) > 0),
    doc_prefix        text not null,                 -- รหัสหนังสือ เช่น 'กท ๑๒๓๔/'
    address           text,
    use_thai_numerals boolean not null default true,
    created_at        timestamptz not null default now()
);
comment on table public.organizations is 'หน่วยงาน (ส่วนราชการ) — ขอบเขตข้อมูลของ RLS';

create table public.profiles (
    user_id    uuid primary key references auth.users (id) on delete cascade,
    org_id     uuid not null references public.organizations (id),
    full_name  text not null default '',
    position   text not null default '',
    role       text not null default 'drafter'
               check (role in ('admin', 'clerk', 'drafter', 'approver')),
    created_at timestamptz not null default now()
);
comment on table public.profiles is 'ผู้ใช้ 1 คนต่อ 1 แถว (คู่กับ auth.users) และสังกัดหน่วยงาน';
create index profiles_org_idx on public.profiles (org_id);

-- หน่วยงานของผู้ใช้ปัจจุบัน — ใช้ใน RLS ทุกตาราง
-- security definer เพื่อให้อ่าน profiles ได้โดยไม่วน RLS ของ profiles เอง
create function public.current_org_id()
returns uuid
language sql
stable
security definer
set search_path = ''
as $$
    select p.org_id from public.profiles p where p.user_id = (select auth.uid())
$$;

create function public.current_role_is(variadic roles text[])
returns boolean
language sql
stable
security definer
set search_path = ''
as $$
    select exists (
        select 1 from public.profiles p
        where p.user_id = (select auth.uid()) and p.role = any (roles)
    )
$$;

-- ---------------------------------------------------------------- เอกสาร
create table public.documents (
    id              uuid primary key default gen_random_uuid(),
    org_id          uuid not null references public.organizations (id),
    owner_id        uuid not null references auth.users (id),
    kind            text not null default 'internal_memo',   -- core.models.DocumentKind
    doc_type        text not null default 'internal' check (doc_type in ('external', 'internal')),
    status          text not null default 'draft'
                    check (status in ('draft', 'review', 'approved', 'numbered', 'sent', 'archived')),
    secret_level    text not null default 'normal'
                    check (secret_level in ('normal', 'secret', 'very_secret', 'top_secret')),
    urgency         text not null default 'normal'
                    check (urgency in ('normal', 'urgent', 'very_urgent', 'most_urgent')),
    subject         text not null default '',
    doc_number      text,
    current_version integer not null default 0,
    created_at      timestamptz not null default now(),
    updated_at      timestamptz not null default now()
);
create index documents_org_updated_idx on public.documents (org_id, updated_at desc);
create index documents_owner_idx on public.documents (owner_id);

-- ทุกครั้งที่บันทึก = 1 แถว (เขียนเพิ่มอย่างเดียว) เนื้อหาคือ core.models.GovDocumentSchema
create table public.document_versions (
    id               bigint generated always as identity primary key,
    document_id      uuid not null references public.documents (id) on delete restrict,
    org_id           uuid not null references public.organizations (id),
    version_no       integer not null,
    content          jsonb not null,
    edit_instruction text,              -- คำสั่งที่ทำให้เกิดเวอร์ชันนี้ (ถ้ามาจาก AI/ผู้ใช้สั่ง)
    note             text,
    created_by       uuid not null references auth.users (id),
    created_at       timestamptz not null default now(),
    unique (document_id, version_no)
);
create index document_versions_org_idx on public.document_versions (org_id);
create index document_versions_created_by_idx on public.document_versions (created_by);

-- ---------------------------------------------------------------- แชตกับผู้ช่วยร่าง
create table public.conversations (
    id          uuid primary key default gen_random_uuid(),
    org_id      uuid not null references public.organizations (id),
    owner_id    uuid not null references auth.users (id),
    document_id uuid references public.documents (id) on delete set null,
    title       text not null default '',
    created_at  timestamptz not null default now()
);
create index conversations_org_idx on public.conversations (org_id, created_at desc);
create index conversations_owner_idx on public.conversations (owner_id);
create index conversations_document_idx on public.conversations (document_id);

create table public.messages (
    id              bigint generated always as identity primary key,
    conversation_id uuid not null references public.conversations (id) on delete cascade,
    org_id          uuid not null references public.organizations (id),
    role            text not null check (role in ('user', 'assistant', 'system')),
    content         text not null,
    created_at      timestamptz not null default now()
);
create index messages_conversation_idx on public.messages (conversation_id, id);
create index messages_org_idx on public.messages (org_id);

-- ---------------------------------------------------------------- ไฟล์ต้นเรื่อง
create table public.source_files (
    id             uuid primary key default gen_random_uuid(),
    org_id         uuid not null references public.organizations (id),
    document_id    uuid references public.documents (id) on delete set null,
    uploaded_by    uuid not null references auth.users (id),
    storage_path   text not null unique,          -- path ใน bucket "sources" (ขึ้นต้นด้วย org_id/)
    filename       text not null,                 -- ชื่อไฟล์เดิมของผู้ใช้ (แสดงผลเท่านั้น)
    mime           text not null default '',
    size_bytes     bigint not null default 0 check (size_bytes >= 0),
    sha256         text,
    extracted_text text,
    ocr_engine     text,
    secret_level   text not null default 'normal'
                   check (secret_level in ('normal', 'secret', 'very_secret', 'top_secret')),
    delete_after   timestamptz not null default (now() + interval '30 days'),
    created_at     timestamptz not null default now()
);
create index source_files_org_idx on public.source_files (org_id, created_at desc);
create index source_files_document_idx on public.source_files (document_id);
create index source_files_uploaded_by_idx on public.source_files (uploaded_by);
create index source_files_delete_after_idx on public.source_files (delete_after);

-- ---------------------------------------------------------------- ทะเบียนรับ-ส่ง
-- ตัวนับเลขทะเบียน: 1 แถวต่อ (หน่วยงาน, เล่มทะเบียน, ปี พ.ศ.) — ออกเลขผ่าน issue_reg_no() เท่านั้น
create table public.number_sequences (
    org_id     uuid not null references public.organizations (id),
    book       text not null,                -- เช่น 'outgoing:กท ๑๒๓๔/' / 'outgoing:กท ๑๒๓๔/ว' / 'incoming'
    year_be    integer not null,
    last_value integer not null default 0 check (last_value >= 0),
    primary key (org_id, book, year_be)
);

-- ทะเบียนหนังสือส่ง (เลขทะเบียน, ที่, ลงวันที่, จาก, ถึง, เรื่อง, การปฏิบัติ, หมายเหตุ)
create table public.outgoing_register (
    id            bigint generated always as identity primary key,
    org_id        uuid not null references public.organizations (id),
    book          text not null,
    year_be       integer not null,
    reg_no        integer not null,
    doc_number    text not null,                 -- "ที่" เช่น 'กท ๑๒๓๔/๕๖'
    doc_date      text,                          -- ลงวันที่ (ข้อความไทย)
    from_unit     text not null default '',
    to_recipient  text not null default '',
    subject       text not null default '',
    action_taken  text not null default '',
    remark        text not null default '',
    status        text not null default 'reserved' check (status in ('reserved', 'issued', 'cancelled')),
    cancel_reason text,
    document_id   uuid references public.documents (id) on delete set null,
    created_by    uuid not null references auth.users (id),
    created_at    timestamptz not null default now(),
    unique (org_id, book, year_be, reg_no),
    unique (org_id, doc_number),
    check (status <> 'cancelled' or length(trim(coalesce(cancel_reason, ''))) > 0)
);
create index outgoing_register_org_idx on public.outgoing_register (org_id, created_at desc);
create index outgoing_register_document_idx on public.outgoing_register (document_id);
create index outgoing_register_created_by_idx on public.outgoing_register (created_by);

-- ทะเบียนหนังสือรับ
create table public.incoming_register (
    id                bigint generated always as identity primary key,
    org_id            uuid not null references public.organizations (id),
    year_be           integer not null,
    reg_no            integer not null,
    received_at       timestamptz not null default now(),
    source_doc_number text not null default '',     -- "ที่" ของหนังสือที่รับ
    source_doc_date   text not null default '',
    from_org          text not null default '',
    to_unit           text not null default '',
    subject           text not null default '',
    action_taken      text not null default '',
    remark            text not null default '',
    source_file_id    uuid references public.source_files (id) on delete set null,
    created_by        uuid not null references auth.users (id),
    created_at        timestamptz not null default now(),
    unique (org_id, year_be, reg_no)
);
create index incoming_register_org_idx on public.incoming_register (org_id, created_at desc);
create index incoming_register_source_file_idx on public.incoming_register (source_file_id);
create index incoming_register_created_by_idx on public.incoming_register (created_by);

-- ---------------------------------------------------------------- audit / คลังกฎหมาย / AI
create table public.audit_log (
    id        bigint generated always as identity primary key,
    org_id    uuid not null references public.organizations (id),
    actor_id  uuid references auth.users (id),
    action    text not null,
    entity    text not null,
    entity_id text,
    details   jsonb not null default '{}'::jsonb,
    prev_hash text,
    hash      text,
    at        timestamptz not null default now()
);
create index audit_log_org_idx on public.audit_log (org_id, id);
create index audit_log_actor_idx on public.audit_log (actor_id);

create table public.legal_references (
    id             uuid primary key default gen_random_uuid(),
    org_id         uuid not null references public.organizations (id),
    title          text not null default '',
    section        text,                         -- มาตรา/ข้อ
    quote          text not null default '',
    url            text,
    effective_date text,
    verified       boolean not null default false,
    recorded_by    uuid references auth.users (id),
    recorded_at    timestamptz not null default now()
);
create index legal_references_org_idx on public.legal_references (org_id);
create index legal_references_recorded_by_idx on public.legal_references (recorded_by);

create table public.ai_usage (
    id           bigint generated always as identity primary key,
    org_id       uuid not null references public.organizations (id),
    user_id      uuid references auth.users (id),
    document_id  uuid references public.documents (id) on delete set null,
    model        text not null,
    purpose      text not null,                  -- ocr / draft / refine / classify
    secret_level text not null default 'normal',
    tokens_in    integer not null default 0,
    tokens_out   integer not null default 0,
    created_at   timestamptz not null default now()
);
create index ai_usage_org_idx on public.ai_usage (org_id, created_at desc);
create index ai_usage_user_idx on public.ai_usage (user_id);
create index ai_usage_document_idx on public.ai_usage (document_id);

-- =============================================================================
-- Row Level Security
-- =============================================================================
alter table public.organizations     enable row level security;
alter table public.profiles          enable row level security;
alter table public.documents         enable row level security;
alter table public.document_versions enable row level security;
alter table public.conversations     enable row level security;
alter table public.messages          enable row level security;
alter table public.source_files      enable row level security;
alter table public.number_sequences  enable row level security;
alter table public.outgoing_register enable row level security;
alter table public.incoming_register enable row level security;
alter table public.audit_log         enable row level security;
alter table public.legal_references  enable row level security;
alter table public.ai_usage          enable row level security;

-- หน่วยงาน/ผู้ใช้: อ่านได้เฉพาะหน่วยงานตัวเอง; แก้โปรไฟล์ตัวเองได้ (ยกเว้นหน่วยงาน/บทบาท ดู trigger)
create policy organizations_select on public.organizations
    for select to authenticated using (id = (select public.current_org_id()));
create policy organizations_update_admin on public.organizations
    for update to authenticated
    using (id = (select public.current_org_id()) and (select public.current_role_is('admin')))
    with check (id = (select public.current_org_id()));

create policy profiles_select on public.profiles
    for select to authenticated using (org_id = (select public.current_org_id()));
create policy profiles_update_self on public.profiles
    for update to authenticated
    using (user_id = (select auth.uid()))
    with check (user_id = (select auth.uid()));

-- เอกสาร: ทุกคนในหน่วยงานอ่าน/สร้าง/แก้ได้ (ช่วงทดสอบ) — ไม่มีสิทธิ์ลบ ใช้สถานะ archived แทน
create policy documents_select on public.documents
    for select to authenticated using (org_id = (select public.current_org_id()));
create policy documents_insert on public.documents
    for insert to authenticated
    with check (org_id = (select public.current_org_id()) and owner_id = (select auth.uid()));
create policy documents_update on public.documents
    for update to authenticated
    using (org_id = (select public.current_org_id()))
    with check (org_id = (select public.current_org_id()));

create policy document_versions_select on public.document_versions
    for select to authenticated using (org_id = (select public.current_org_id()));
-- เพิ่มเวอร์ชันผ่าน save_document_version() เท่านั้น (ออกเลขเวอร์ชันแบบ atomic)

create policy conversations_select on public.conversations
    for select to authenticated using (org_id = (select public.current_org_id()));
create policy conversations_insert on public.conversations
    for insert to authenticated
    with check (org_id = (select public.current_org_id()) and owner_id = (select auth.uid()));
create policy conversations_update_owner on public.conversations
    for update to authenticated
    using (owner_id = (select auth.uid()))
    with check (org_id = (select public.current_org_id()));

create policy messages_select on public.messages
    for select to authenticated using (org_id = (select public.current_org_id()));
create policy messages_insert on public.messages
    for insert to authenticated
    with check (
        org_id = (select public.current_org_id())
        and exists (select 1 from public.conversations c
                    where c.id = conversation_id and c.org_id = (select public.current_org_id()))
    );

create policy source_files_select on public.source_files
    for select to authenticated using (org_id = (select public.current_org_id()));
create policy source_files_insert on public.source_files
    for insert to authenticated
    with check (
        org_id = (select public.current_org_id())
        and uploaded_by = (select auth.uid())
        and storage_path like (select public.current_org_id())::text || '/%'
    );
create policy source_files_update on public.source_files
    for update to authenticated
    using (org_id = (select public.current_org_id()))
    with check (org_id = (select public.current_org_id()));

-- ทะเบียนและตัวนับ: อ่านได้ในหน่วยงาน; เขียนผ่านฟังก์ชัน security definer เท่านั้น (ไม่มี policy insert/update/delete)
create policy number_sequences_select on public.number_sequences
    for select to authenticated using (org_id = (select public.current_org_id()));
create policy outgoing_register_select on public.outgoing_register
    for select to authenticated using (org_id = (select public.current_org_id()));
create policy incoming_register_select on public.incoming_register
    for select to authenticated using (org_id = (select public.current_org_id()));

-- audit: อ่านได้ในหน่วยงาน; เขียนโดย trigger/ฟังก์ชันเท่านั้น
create policy audit_log_select on public.audit_log
    for select to authenticated using (org_id = (select public.current_org_id()));

create policy legal_references_select on public.legal_references
    for select to authenticated using (org_id = (select public.current_org_id()));
create policy legal_references_insert on public.legal_references
    for insert to authenticated
    with check (org_id = (select public.current_org_id()) and recorded_by = (select auth.uid()));
create policy legal_references_update on public.legal_references
    for update to authenticated
    using (org_id = (select public.current_org_id()))
    with check (org_id = (select public.current_org_id()));

create policy ai_usage_select on public.ai_usage
    for select to authenticated using (org_id = (select public.current_org_id()));
create policy ai_usage_insert on public.ai_usage
    for insert to authenticated
    with check (org_id = (select public.current_org_id()) and user_id = (select auth.uid()));

-- ผู้ใช้ที่ไม่ได้ล็อกอิน (anon) ไม่มีสิทธิ์ใด ๆ กับตารางของระบบ
revoke all on all tables in schema public from anon;

-- จำกัดคอลัมน์ที่แก้ได้ (RLS คุมแถว, GRANT คุมคอลัมน์)
--   profiles: แก้ชื่อ/ตำแหน่งตัวเองได้ แต่ห้ามเปลี่ยนหน่วยงานหรือบทบาท
--   documents: เลขที่หนังสือ/เลขเวอร์ชัน/เจ้าของ เปลี่ยนผ่านฟังก์ชันเท่านั้น
revoke update on public.organizations from authenticated;
grant update (name, doc_prefix, address, use_thai_numerals) on public.organizations to authenticated;
revoke update on public.profiles from authenticated;
grant update (full_name, position) on public.profiles to authenticated;
revoke update on public.documents from authenticated;
grant update (kind, doc_type, status, secret_level, urgency, subject) on public.documents to authenticated;
revoke update on public.conversations from authenticated;
grant update (title, document_id) on public.conversations to authenticated;
revoke update on public.source_files from authenticated;
grant update (document_id, extracted_text, ocr_engine) on public.source_files to authenticated;
revoke update on public.legal_references from authenticated;
grant update (title, section, quote, url, effective_date, verified) on public.legal_references to authenticated;
revoke execute on function public.current_org_id() from public, anon;
revoke execute on function public.current_role_is(text[]) from public, anon;
grant execute on function public.current_org_id() to authenticated;
grant execute on function public.current_role_is(text[]) to authenticated;
