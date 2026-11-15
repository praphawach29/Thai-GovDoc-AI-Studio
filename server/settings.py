"""settings.py — ค่าตั้งของเซิร์ฟเวอร์ อ่านจากตัวแปรสภาพแวดล้อมที่เดียว"""

import os
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import List

ROOT_DIR = Path(__file__).resolve().parent.parent

# Vercel (และ serverless ส่วนใหญ่) เขียนไฟล์ได้เฉพาะ /tmp
_ON_SERVERLESS = bool(os.environ.get("VERCEL") or os.environ.get("AWS_LAMBDA_FUNCTION_NAME"))
_WRITABLE_ROOT = Path("/tmp/govdoc") if _ON_SERVERLESS else ROOT_DIR


# ชื่อที่ยอมรับ (ตัวแรกคือชื่อหลัก) — หน้า "Connect" ของ Supabase และ Vercel Integration
# มักให้ชื่อแบบ NEXT_PUBLIC_* จึงรับไว้ด้วย กันตั้งค่าผิดชื่อแล้วระบบปิดตัวเองโดยไม่รู้สาเหตุ
SUPABASE_URL_ENV = ("SUPABASE_URL", "NEXT_PUBLIC_SUPABASE_URL")
SUPABASE_KEY_ENV = (
    "SUPABASE_PUBLISHABLE_KEY",
    "SUPABASE_ANON_KEY",
    "NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY",
    "NEXT_PUBLIC_SUPABASE_PUBLISHABLE_DEFAULT_KEY",
    "NEXT_PUBLIC_SUPABASE_ANON_KEY",
)


def _first_env(names) -> str:
    for name in names:
        value = os.environ.get(name, "").strip()
        if value:
            return value
    return ""


def _split_csv(value: str) -> List[str]:
    return [v.strip() for v in value.split(",") if v.strip()]


@dataclass(frozen=True)
class Settings:
    # โดเมนที่เรียก API ข้ามโดเมนได้ (คั่นด้วยจุลภาค) — ห้ามใช้ "*"
    allowed_origins: List[str] = field(
        default_factory=lambda: _split_csv(
            os.environ.get("GOVDOC_ALLOWED_ORIGINS", "http://localhost:8600,http://127.0.0.1:8600")
        )
    )
    upload_dir: Path = field(
        default_factory=lambda: Path(os.environ.get("GOVDOC_UPLOAD_DIR", _WRITABLE_ROOT / "uploads"))
    )
    # ทะเบียน SQLite ชั่วคราว — ขั้นถัดไปย้ายไป Supabase Postgres
    registry_db_path: Path = field(
        default_factory=lambda: Path(os.environ.get("GOVDOC_REGISTRY_DB", _WRITABLE_ROOT / "data" / "edocument.db"))
    )
    max_upload_bytes: int = field(
        default_factory=lambda: int(os.environ.get("GOVDOC_MAX_UPLOAD_MB", "50")) * 1024 * 1024
    )
    # Supabase: ตั้ง SUPABASE_URL + SUPABASE_PUBLISHABLE_KEY แล้วระบบจะบังคับล็อกอินทุก API
    # และเก็บข้อมูลใน Supabase; ไม่ตั้ง = โหมดเครื่องเดียว (SQLite + localStorage, ไม่มีล็อกอิน)
    # publishable key (เดิมเรียก anon key) เปิดเผยในหน้าเว็บได้ สิทธิ์ถูกคุมด้วย RLS
    # ห้ามใส่ service_role / secret key ที่นี่ — API เรียก Supabase ด้วย token ของผู้ใช้เท่านั้น
    supabase_url: str = field(default_factory=lambda: _first_env(SUPABASE_URL_ENV).rstrip("/"))
    supabase_publishable_key: str = field(default_factory=lambda: _first_env(SUPABASE_KEY_ENV))
    source_bucket: str = "sources"
    # บนคลาวด์ต้องมีล็อกอินเสมอ: ถ้าลืมตั้ง Supabase ระบบจะปฏิเสธ API แทนการเปิดใช้แบบไม่มีล็อกอิน
    # (บนเครื่องตัวเองไม่บังคับ; ตั้ง GOVDOC_REQUIRE_AUTH=1 เพื่อบังคับเองได้)
    require_auth: bool = field(
        default_factory=lambda: os.environ.get("GOVDOC_REQUIRE_AUTH", "1" if _ON_SERVERLESS else "0") == "1"
    )
    # AI ร่างหนังสือ: ลอง Claude ก่อน แล้ว Gemini; ไม่ตั้งคีย์เลย = ร่างตามกฎอย่างเดียว
    # คีย์เป็นความลับ ตั้งใน Vercel → Settings → Environment Variables เท่านั้น
    anthropic_api_key: str = field(default_factory=lambda: os.environ.get("ANTHROPIC_API_KEY", "").strip())
    anthropic_workspace_id: str = field(default_factory=lambda: os.environ.get("ANTHROPIC_WORKSPACE_ID", "").strip())
    gemini_api_key: str = field(default_factory=lambda: _first_env(("GEMINI_API_KEY", "GOOGLE_API_KEY")))
    claude_model: str = field(default_factory=lambda: os.environ.get("GOVDOC_CLAUDE_MODEL", "claude-opus-5-5").strip())
    claude_effort: str = field(default_factory=lambda: os.environ.get("GOVDOC_CLAUDE_EFFORT", "medium").strip())
    gemini_model: str = field(default_factory=lambda: os.environ.get("GOVDOC_GEMINI_MODEL", "gemini-2.5-flash").strip())
    web_dir: Path = ROOT_DIR / "web" / "studio"
    assets_dir: Path = ROOT_DIR / "assets"
    typst_templates_dir: Path = ROOT_DIR / "templates" / "typst"


def llm_config(settings: "Settings"):
    """ค่าตั้ง AI สำหรับ core (core ไม่อ่านตัวแปรสภาพแวดล้อมเอง)"""
    from core.llm_drafter import LLMConfig

    return LLMConfig(
        anthropic_api_key=settings.anthropic_api_key, gemini_api_key=settings.gemini_api_key,
        anthropic_workspace_id=settings.anthropic_workspace_id,
        claude_model=settings.claude_model, claude_effort=settings.claude_effort,
        gemini_model=settings.gemini_model,
    )


def supabase_enabled(settings: "Settings") -> bool:
    return bool(settings.supabase_url and settings.supabase_publishable_key)


@lru_cache
def get_settings() -> Settings:
    return Settings()
