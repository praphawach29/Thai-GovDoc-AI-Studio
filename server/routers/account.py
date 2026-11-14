"""ค่าตั้งสำหรับหน้าเว็บ และข้อมูลผู้ใช้ที่ล็อกอิน"""

from fastapi import APIRouter, Depends

from server.auth import Profile, get_profile
from server.settings import Settings, get_settings, supabase_enabled

router = APIRouter(tags=["account"])


@router.get("/api/v1/config")
def public_config(settings: Settings = Depends(get_settings)):
    """ค่าที่หน้าเว็บต้องใช้ก่อนล็อกอิน (เปิดเผยได้: publishable key ถูกคุมด้วย RLS)"""
    enabled = supabase_enabled(settings)
    return {
        "auth_required": enabled,
        "supabase_url": settings.supabase_url if enabled else None,
        "supabase_publishable_key": settings.supabase_publishable_key if enabled else None,
        "source_bucket": settings.source_bucket,
        "max_upload_mb": settings.max_upload_bytes // (1024 * 1024),
    }


@router.get("/api/v1/me")
def me(profile: Profile = Depends(get_profile)):
    """ผู้ใช้ที่ล็อกอิน + หน่วยงาน (โหมด Supabase)"""
    return {
        "user_id": profile.user_id,
        "full_name": profile.full_name,
        "position": profile.position,
        "role": profile.role,
        "organization": profile.org,
    }
