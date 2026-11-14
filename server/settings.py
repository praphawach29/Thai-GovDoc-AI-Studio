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
    web_dir: Path = ROOT_DIR / "web" / "studio"
    assets_dir: Path = ROOT_DIR / "assets"
    typst_templates_dir: Path = ROOT_DIR / "templates" / "typst"


@lru_cache
def get_settings() -> Settings:
    return Settings()
