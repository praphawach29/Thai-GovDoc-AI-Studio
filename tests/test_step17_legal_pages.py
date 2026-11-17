"""
Step 17: แนบหน้าของข้อกฎหมายที่เลือก (ไฟล์สแกนต้นฉบับในคลัง) ต่อท้าย PDF
"""

import io

import pytest
from fastapi.testclient import TestClient
from pypdf import PdfReader, PdfWriter

from core.legal_pages import append_pages, plan_pages
from core.models import LegalCitation
from core.templates_library import PRESET_TEMPLATES


def C(source, p1, p2=None, id="x"):
    return LegalCitation(id=id, title="t", section="ข้อ ๑", source_id=source, page_from=p1, page_to=p2)


def _source_pdf(pages=6):
    """หน้าที่ n กว้าง 300+n จุด — ดูจากความกว้างได้ว่าแนบหน้าไหน"""
    from PIL import Image
    imgs = [Image.new("RGB", (300 + n, 420), "white") for n in range(1, pages + 1)]
    buf = io.BytesIO()
    imgs[0].save(buf, format="PDF", save_all=True, append_images=imgs[1:], resolution=72)
    return buf.getvalue()


def _widths(pdf_bytes, skip=0):
    return [round(float(p.mediabox.width)) for p in PdfReader(io.BytesIO(pdf_bytes)).pages[skip:]]


def test_plan_merges_overlaps_keeps_file_order_and_skips_manual():
    plan = plan_pages([C("s2", 3, 4), C("s1", 2), C("s2", 4, 5), C(None, 1), C("s1", None), C("s2", 1)])
    assert plan == [("s2", [1, 3, 4, 5]), ("s1", [2])]
    assert plan_pages([]) == [] and plan_pages(None) == []


def test_append_pages_skips_out_of_range():
    w = PdfWriter()
    assert append_pages(w, _source_pdf(3), [2, 3, 9]) == 2
    out = io.BytesIO(); w.write(out)
    assert _widths(out.getvalue()) == [302, 303]


# ---------------------------------------------------------------- API (Supabase)
@pytest.fixture
def fake(tmp_path, monkeypatch):
    from server import auth as server_auth
    from server import supabase as server_supabase
    from server.main import app
    from server.settings import Settings, get_settings
    from tests.fake_supabase import ORG_ID, PUBLISHABLE_KEY, URL, FakeSupabase

    fake = FakeSupabase()
    for sid, pages in (("s1", 6), ("s2", 3)):
        path = f"{ORG_ID}/legal/{sid * 16}.pdf"
        fake.tables["legal_sources"].append({"id": sid, "org_id": ORG_ID, "storage_path": path, "page_count": pages})
        fake.storage[f"sources/{path}"] = _source_pdf(pages)
    monkeypatch.setattr(server_supabase, "transport_factory", fake.transport)
    server_auth._jwks_cache.clear()
    app.dependency_overrides[get_settings] = lambda: Settings(
        upload_dir=tmp_path / "u", registry_db_path=tmp_path / "r.db", supabase_url=URL, supabase_publishable_key=PUBLISHABLE_KEY)
    yield fake
    app.dependency_overrides.clear()


def _doc(refs, attach=True):
    d = PRESET_TEMPLATES["bma_cohost_request"].schema.model_copy(deep=True)
    d.legal_refs, d.attach_legal_pages = refs, attach
    return d.model_dump(mode="json")


def _memo_pages(h=None):
    from server.main import app
    r = TestClient(app).post("/api/v1/export/pdf", json=_doc(None), headers=h or {})
    return len(PdfReader(io.BytesIO(r.content)).pages)


def test_pdf_appends_selected_pages(fake):
    from server.main import app
    h = {"Authorization": f"Bearer {fake.token()}"}
    base = _memo_pages(h)
    r = TestClient(app).post("/api/v1/export/pdf", json=_doc([C("s1", 3, 4), C("s2", 2), C("s1", 4)]), headers=h)
    assert r.status_code == 200 and r.headers["X-GovDoc-Legal-Pages"] == "3"
    assert _widths(r.content, skip=base) == [303, 304, 302]          # s1 หน้า ๓–๔ แล้ว s2 หน้า ๒ (ไม่ซ้ำ)


def test_pdf_attach_off_and_missing_source(fake):
    from server.main import app
    h = {"Authorization": f"Bearer {fake.token()}"}
    base = _memo_pages(h)
    off = TestClient(app).post("/api/v1/export/pdf", json=_doc([C("s1", 3)], attach=False), headers=h)
    assert len(PdfReader(io.BytesIO(off.content)).pages) == base
    missing = TestClient(app).post("/api/v1/export/pdf", json=_doc([C("gone", 1), C("s2", 3)]), headers=h)
    assert missing.status_code == 200 and missing.headers["X-GovDoc-Legal-Pages"] == "1"


def test_bundle_attaches_once_at_end(fake):
    from server.main import app
    h = {"Authorization": f"Bearer {fake.token()}"}
    base = _memo_pages(h)
    r = TestClient(app).post("/api/v1/export/pdf-bundle",
                             json={"documents": [_doc([C("s1", 2)]), _doc([C("s1", 2), C("s1", 5)])]}, headers=h)
    assert r.headers["X-GovDoc-Legal-Pages"] == "2"
    assert _widths(r.content, skip=2 * base) == [302, 305]


def test_local_mode_exports_without_attaching():
    from server.main import app
    r = TestClient(app).post("/api/v1/export/pdf", json=_doc([C("s1", 3)]))
    assert r.status_code == 200 and r.headers["X-GovDoc-Legal-Pages"] == "0"
