"""
test_typst_compile.py — คอมไพล์เทมเพลต Typst จริง (ไม่ใช่แค่ตรวจสตริง)

ใช้ typst CLI ในเครื่องถ้ามี มิฉะนั้นใช้ Docker image ghcr.io/typst/typst
ถ้าไม่มีทั้งสองอย่าง จะ skip
"""

import shutil
import subprocess
from pathlib import Path

import pytest

from core.models import DocType
from core.templates_library import PRESET_TEMPLATES
from core.typst_exporter import find_typst_binary, generate_typst_content

ROOT = Path(__file__).resolve().parent.parent
DOCKER_IMAGE = "ghcr.io/typst/typst:latest"


def _docker_ready() -> bool:
    if not shutil.which("docker"):
        return False
    try:
        return subprocess.run(["docker", "info"], capture_output=True, timeout=15).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def _compile_cmd(workdir: Path, main: str):
    typst_bin = find_typst_binary()
    if typst_bin:
        return [typst_bin, "compile", str(workdir / main), str(workdir / "out.pdf")], None
    if _docker_ready():
        return ["docker", "run", "--rm",
                "-v", f"{workdir}:/work",
                "-v", f"{ROOT / 'assets' / 'fonts'}:/fonts:ro",
                "-w", "/work",
                DOCKER_IMAGE, "compile", "--font-path", "/fonts", main, "out.pdf"], None
    return None, "ไม่มี typst CLI หรือ Docker"


@pytest.mark.requires_typst
@pytest.mark.parametrize("template_id, style", [
    ("bma_cohost_request", "bma"),
    ("bma_general_memo", "numbered"),
    ("meeting_invitation", None),
])
def test_typst_compiles(tmp_path, template_id, style):
    doc = PRESET_TEMPLATES[template_id].schema.model_copy(deep=True)
    if style:
        doc.memo_heading_style = style
    if doc.doc_type == DocType.INTERNAL:
        doc.use_thai_numerals = True

    # จำลองโครงสร้างโปรเจกต์: main.typ อยู่ที่ราก import templates/typst/*.typ
    (tmp_path / "templates" / "typst").mkdir(parents=True)
    (tmp_path / "assets").mkdir()
    for name in ("internal.typ", "external.typ"):
        shutil.copy(ROOT / "templates" / "typst" / name, tmp_path / "templates" / "typst" / name)
    shutil.copy(ROOT / "assets" / "garuda.svg", tmp_path / "assets" / "garuda.svg")
    (tmp_path / "main.typ").write_text(generate_typst_content(doc), encoding="utf-8")

    cmd, reason = _compile_cmd(tmp_path, "main.typ")
    if cmd is None:
        # ไม่มี CLI/Docker: ใช้ Python binding (pip install typst) ตัวเดียวกับที่ production ใช้
        from core.typst_exporter import compile_typst_to_pdf

        ok, message = compile_typst_to_pdf(
            str(tmp_path / "main.typ"), str(tmp_path / "out.pdf")
        )
        assert ok, message
    else:
        res = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", timeout=180)
        assert res.returncode == 0, res.stderr
    pdf = tmp_path / "out.pdf"
    assert pdf.exists() and pdf.read_bytes().startswith(b"%PDF-")
    # ต้องฝังฟอนต์ตระกูล Sarabun จาก assets/fonts ไม่ใช่ fallback ภาษาอังกฤษ
    assert b"Sarabun" in pdf.read_bytes()
