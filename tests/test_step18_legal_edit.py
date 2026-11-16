"""
Step 18: แก้รายการในคลังกฎหมาย — หัวข้อที่ใช้เรียก + เนื้อหา (แก้คำที่ AI อ่านผิด) และเปลี่ยนชื่อฉบับ
"""

import pytest
from fastapi.testclient import TestClient

from core.legal_import import guess_title


def test_title_of_act_with_name_on_next_line():
    assert guess_title(["สำเนา\nพระราชบัญญัติ\nเครื่องหมายราชการ พุทธศักราช 2482\nในพระปรมาภิไธย\nมาตรา 1 ..."]) == \
        "พระราชบัญญัติ เครื่องหมายราชการ พุทธศักราช 2482"
    # ชื่อที่อยู่บรรทัดเดียวกันอยู่แล้ว ไม่ต่อบรรทัดอื่นมั่ว
    assert guess_title(["ระเบียบกรุงเทพมหานคร\nว่าด้วยเงินบำรุง\nพ.ศ. ๒๕๖๓\nโดยที่เป็นการสมควร"]) == \
        "ระเบียบกรุงเทพมหานคร ว่าด้วยเงินบำรุง พ.ศ. ๒๕๖๓"


@pytest.fixture
def fake(tmp_path, monkeypatch):
    from server import auth as server_auth
    from server import supabase as server_supabase
    from server.main import app
    from server.settings import Settings, get_settings
    from tests.fake_supabase import ORG_ID, PUBLISHABLE_KEY, URL, FakeSupabase

    fake = FakeSupabase()
    sid = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    fake.tables["legal_sources"].append({"id": sid, "org_id": ORG_ID, "title": "พระราชบัญญัติ", "storage_path": "x"})
    fake.tables["legal_references"] = [
        {"id": "11111111-1111-1111-1111-111111111111", "org_id": ORG_ID, "title": "พระราชบัญญัติ", "section": "มาตรา ๖",
         "quote": "มาตรา 6 ห้ามมิให้บุคคลใดใช้เครื่องหมายราชกาน", "verified": False, "source_id": sid, "page_from": 1, "page_to": 1},
        {"id": "22222222-2222-2222-2222-222222222222", "org_id": ORG_ID, "title": "พระราชบัญญัติ", "section": "มาตรา ๗",
         "quote": "มาตรา 7 ห้ามมิให้ผู้ใดปลอม", "verified": True, "source_id": sid, "page_from": 2, "page_to": 2},
    ]
    monkeypatch.setattr(server_supabase, "transport_factory", fake.transport)
    server_auth._jwks_cache.clear()
    app.dependency_overrides[get_settings] = lambda: Settings(
        upload_dir=tmp_path / "u", registry_db_path=tmp_path / "r.db", supabase_url=URL, supabase_publishable_key=PUBLISHABLE_KEY)
    fake.sid = sid
    yield fake
    app.dependency_overrides.clear()


def _c():
    from server.main import app
    return TestClient(app)


def test_edit_heading_and_content_keeps_pages(fake):
    h = {"Authorization": f"Bearer {fake.token()}"}
    rid = "11111111-1111-1111-1111-111111111111"
    r = _c().patch(f"/api/v1/legal/references/{rid}", json={
        "section": "  การใช้เครื่องหมายราชการ (มาตรา ๖) ", "quote": "มาตรา ๖ ห้ามมิให้บุคคลใดใช้เครื่องหมายราชการ\n"}, headers=h)
    assert r.status_code == 200, r.text
    row = fake.tables["legal_references"][0]
    assert row["section"] == "การใช้เครื่องหมายราชการ (มาตรา ๖)" and row["quote"].endswith("เครื่องหมายราชการ")
    assert (row["page_from"], row["source_id"], row["verified"]) == (1, fake.sid, False)     # ช่องอื่นคงเดิม
    sent = [q for q in fake.requests if q.method == "PATCH" and q.url.path == "/rest/v1/legal_references"][-1]
    assert set(__import__("json").loads(sent.content)) == {"section", "quote"}            # ส่งเฉพาะช่องที่แก้ (ตามสิทธิ์ที่ให้ไว้)
    r = _c().patch(f"/api/v1/legal/references/{rid}", json={"quote": "แก้อีกรอบ", "verified": True}, headers=h)
    assert fake.tables["legal_references"][0]["verified"] is True


@pytest.mark.parametrize("body", [{}, {"section": "  "}, {"quote": ""}])
def test_edit_rejects_empty(fake, body):
    h = {"Authorization": f"Bearer {fake.token()}"}
    assert _c().patch("/api/v1/legal/references/11111111-1111-1111-1111-111111111111", json=body, headers=h).status_code == 422


def test_edit_missing_is_404_and_verify_route_still_works(fake):
    h = {"Authorization": f"Bearer {fake.token()}"}
    assert _c().patch("/api/v1/legal/references/99999999-9999-9999-9999-999999999999", json={"quote": "x"}, headers=h).status_code == 404
    r = _c().patch("/api/v1/legal/references/verify", json={"ids": ["11111111-1111-1111-1111-111111111111"]}, headers=h)
    assert r.status_code == 200 and r.json() == {"updated": 1}


def test_rename_source_updates_all_sections(fake):
    h = {"Authorization": f"Bearer {fake.token()}"}
    r = _c().patch(f"/api/v1/legal/sources/{fake.sid}", json={"title": " พระราชบัญญัติเครื่องหมายราชการ พุทธศักราช ๒๔๘๒ "}, headers=h)
    assert r.status_code == 200 and r.json()["updated"] == 2
    assert fake.tables["legal_sources"][0]["title"] == "พระราชบัญญัติเครื่องหมายราชการ พุทธศักราช ๒๔๘๒"
    assert {x["title"] for x in fake.tables["legal_references"]} == {"พระราชบัญญัติเครื่องหมายราชการ พุทธศักราช ๒๔๘๒"}
    assert _c().patch(f"/api/v1/legal/sources/{fake.sid}", json={"title": "   "}, headers=h).status_code == 422


def test_local_mode_edit(tmp_path, monkeypatch):
    from core import legal_sources
    from core.legal_sources import LegalLibrary, LegalReference

    monkeypatch.setattr(legal_sources, "LEGAL_LIBRARY_PATH", tmp_path / "legal.json")
    ref = LegalLibrary().add(LegalReference(title="ระเบียบ", section="ข้อ ๑", quote="เดิม"))
    r = _c().patch(f"/api/v1/legal/references/{ref.id}", json={"section": "ข้อ ๑ (แก้)", "quote": "ใหม่"})
    assert r.status_code == 200
    got = LegalLibrary().list()[0]
    assert (got.section, got.quote) == ("ข้อ ๑ (แก้)", "ใหม่")
