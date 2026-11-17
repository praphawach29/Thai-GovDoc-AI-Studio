-- =============================================================================
-- แก้ลบถาวรไม่ได้: "record \"old\" has no field \"document_id\""
--   forbid_change() ใช้กับหลายตาราง จึงอ่านค่าแถวผ่าน jsonb แทน old.<คอลัมน์>
--   (สำหรับฐานข้อมูลที่รัน 20261116000009 ฉบับแรกไปแล้ว — รันซ้ำได้)
-- =============================================================================
create or replace function public.forbid_change()
returns trigger
language plpgsql
set search_path = ''
as $$
declare
    v_purge text := current_setting('govdoc.purge_document', true);
    v_old   jsonb;
begin
    -- อ่านค่าผ่าน jsonb: trigger ตัวนี้ใช้หลายตาราง ห้ามอ้าง old.<คอลัมน์> ที่บางตารางไม่มี
    if tg_op = 'DELETE' and coalesce(v_purge, '') <> '' then
        v_old := to_jsonb(old);
        if (tg_table_name = 'documents' and v_old ->> 'id' = v_purge)
           or (tg_table_name = 'document_versions' and v_old ->> 'document_id' = v_purge) then
            return old;
        end if;
    end if;
    raise exception '% ห้าม% (บันทึกนี้แก้ไขหรือลบไม่ได้)', tg_table_name,
        case tg_op when 'DELETE' then 'ลบ' else 'แก้ไข' end
        using errcode = '42501';
end
$$;

notify pgrst, 'reload schema';
