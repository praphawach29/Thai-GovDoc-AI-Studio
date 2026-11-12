"""security.py — นโยบายความปลอดภัยข้อมูลสำหรับ AI ภายนอก"""

from core.models import SecretLevel


class CloudAIBlocked(RuntimeError):
    """ข้อมูลชั้นลับ/ข้อมูลอ่อนไหวถูกบล็อกไม่ให้ส่งไป AI ภายนอก"""


def cloud_ai_allowed(secret: SecretLevel | str = SecretLevel.NORMAL) -> bool:
    """อนุญาตเฉพาะเอกสารชั้นปกติเท่านั้น"""
    value = getattr(secret, "value", secret)
    return str(value).lower() in {"normal", "ปกติ", ""}


def assert_cloud_ai_allowed(secret: SecretLevel | str = SecretLevel.NORMAL) -> None:
    if not cloud_ai_allowed(secret):
        raise CloudAIBlocked(
            "เอกสารนี้เป็นชั้นความลับ/ข้อมูลอ่อนไหว ระบบจึงไม่อนุญาตให้ส่งเนื้อหาไปยัง "
            "Gemini/OpenAI ภายนอก กรุณาใช้โหมด Local (Rule-based/Template) หรือ Docker OCR"
        )
