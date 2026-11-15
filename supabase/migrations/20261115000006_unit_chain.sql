-- =============================================================================
-- สายการเสนอของหน่วยออกหนังสือ (กลุ่มงาน -> กอง -> สำนัก)
--   แต่ละหน่วย = หนึ่งขั้น: ผู้รับ (เรียน), ผู้ลงนาม, ชื่อผู้พิจารณาใน "ข้อพิจารณาและเสนอแนะ"
--   และภาคความประสงค์มาตรฐาน; ลำดับขั้น = sort_order
-- signers: [{"name": "(นาย...)", "position": "...", "is_author": false}, ...]
--   คนแรก = ผู้ลงนามหลัก, is_author = ใช้ชื่อ/ตำแหน่งของผู้ใช้ที่ล็อกอิน (ผู้เสนอเรื่อง)
-- =============================================================================
alter table public.org_units
    add column if not exists recipient    text  not null default '',
    add column if not exists signers      jsonb not null default '[]'::jsonb
        check (jsonb_typeof(signers) = 'array' and jsonb_array_length(signers) <= 4),
    add column if not exists review_party text  not null default '',
    add column if not exists request_text text  not null default '';
