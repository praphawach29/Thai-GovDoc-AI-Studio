"""
conftest.py — จุดรวม skip guard สำหรับเทสที่ต้องพึ่งสภาพแวดล้อมภายนอก

หลักการ: เทสที่ต้องใช้ browser/Typst/Docker OCR ไม่ควร "fail" เพราะเครื่องผู้พัฒนาขาดเครื่องมือ
แต่ต้อง skip อย่างมีเหตุผลเดียวกันทุกไฟล์ (ไม่ใช่ try/except กระจายรายไฟล์)

Marker ที่ใช้:
- requires_browser : ต้องมี Microsoft Edge/Chrome สำหรับเรนเดอร์ PDF
- requires_typst   : ต้องมี Typst CLI หรือ Docker image
- requires_ocr     : ต้องมี GEMINI_API_KEY หรือ Docker Tesseract (tha-tesseract)
"""

import importlib.util
import os
import shutil
import subprocess
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
OCR_DOCKER_IMAGE = "tha-tesseract:latest"


def browser_available() -> bool:
    from legacy.pdf_exporter import _find_browser_executable

    return _find_browser_executable() is not None


def docker_ready() -> bool:
    if not shutil.which("docker"):
        return False
    try:
        return subprocess.run(
            ["docker", "info"], capture_output=True, timeout=15
        ).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def typst_available() -> bool:
    from core.typst_exporter import find_typst_binary

    if find_typst_binary() is not None:
        return True
    if importlib.util.find_spec("typst") is not None:
        return True
    return docker_ready()


def ocr_available() -> bool:
    if os.getenv("GEMINI_API_KEY"):
        return True
    if not docker_ready():
        return False
    try:
        res = subprocess.run(
            ["docker", "image", "inspect", OCR_DOCKER_IMAGE],
            capture_output=True,
            timeout=15,
        )
        return res.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


_SKIP_RULES = {
    "requires_browser": (
        browser_available,
        "ต้องมี Microsoft Edge หรือ Google Chrome สำหรับเรนเดอร์ PDF",
    ),
    "requires_typst": (
        typst_available,
        "ต้องมี Typst CLI หรือ Docker สำหรับคอมไพล์ PDF",
    ),
    "requires_ocr": (
        ocr_available,
        "ต้องมี GEMINI_API_KEY หรือ Docker Tesseract (tha-tesseract) สำหรับ OCR",
    ),
}


def pytest_configure(config):
    for marker in _SKIP_RULES:
        config.addinivalue_line(
            "markers", f"{marker}: เทสที่ต้องพึ่งสภาพแวดล้อมภายนอก (จะ skip หากไม่มี)"
        )


def pytest_collection_modifyitems(config, items):
    for item in items:
        for marker, (check, reason) in _SKIP_RULES.items():
            if marker in item.keywords and not check():
                item.add_marker(pytest.mark.skip(reason=reason))


@pytest.fixture
def export_pdf():
    """
    เรียก PDF export ผ่าน headless browser และ skip อย่างสม่ำเสมอ
    เมื่อสภาพแวดล้อม (sandbox) บล็อกการทำงานของ browser
    """
    from legacy.pdf_exporter import export_govdoc_to_pdf, get_pdf_bytes

    def _export(doc, out_path=None):
        try:
            if out_path is not None:
                return export_govdoc_to_pdf(doc, str(out_path))
            return get_pdf_bytes(doc)
        except RuntimeError as exc:
            message = str(exc)
            if "Access is denied" in message or "การสร้างไฟล์ PDF ล้มเหลว" in message:
                first_line = message.strip().splitlines()[0]
                pytest.skip(f"สภาพแวดล้อมบล็อก headless browser: {first_line}")
            raise

    return _export


@pytest.fixture
def test_settings(tmp_path):
    """ค่าตั้งเซิร์ฟเวอร์สำหรับเทสต์: ไฟล์อัปโหลดและทะเบียนอยู่ในโฟลเดอร์ชั่วคราว"""
    from server.settings import Settings

    return Settings(upload_dir=tmp_path / "uploads", registry_db_path=tmp_path / "edocument.db")


@pytest.fixture
def test_registry(test_settings):
    from core.registry import DocumentRegistry

    return DocumentRegistry(db_path=str(test_settings.registry_db_path))


@pytest.fixture(autouse=True)
def _isolated_server(test_settings, test_registry):
    """ทุกเทสต์ใช้ทะเบียนและโฟลเดอร์อัปโหลดชั่วคราว ไม่เขียนลง data/ หรือ uploads/ ของจริง"""
    from server.deps import get_registry
    from server.main import app
    from server.settings import get_settings

    app.dependency_overrides[get_settings] = lambda: test_settings
    app.dependency_overrides[get_registry] = lambda: test_registry
    yield
    app.dependency_overrides.clear()
