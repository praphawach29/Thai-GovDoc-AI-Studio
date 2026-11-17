"""
Step 16: เสนอข้อกฎหมายที่เกี่ยวข้องจากคลังที่ยืนยันแล้ว — AI เลือกได้เฉพาะรหัสในรายการ (แต่งกฎหมายเองไม่ได้)
"""

import pytest
from fastapi.testclient import TestClient

from core.legal_suggest import LegalPick, LegalPicks, keyword_rank, suggest
from core.models import GovDocumentSchema
from core.templates_library import PRESET_TEMPLATES

REFS = [
    {"id": "a14", "title": "ระเบียบกรุงเทพมหานคร ว่าด้วยเงินบำรุงและค่าใช้จ่ายของศูนย์บริการ", "section": "ข้อ ๑๔",
     "chapter": "หมวด ๒ ค่าสมาชิก ค่าบริการ ค่าใช้สถานที่ และค่าปรับ",
     "quote": "ข้อ ๑๔ อัตราค่าสมาชิก ค่าบริการ ค่าใช้สถานที่ และค่าปรับ ของศูนย์บริการ ให้เป็นไปตามบัญชีท้ายระเบียบนี้",
     "verified": True, "source_id": "s1", "page_from": 3, "page_to": 3},
    {"id": "a10", "title": "ระเบียบกรุงเทพมหานคร ว่าด้วยเงินบำรุงและค่าใช้จ่ายของศูนย์บริการ", "section": "ข้อ ๑๐",
     "quote": "ข้อ ๑๐ ให้สำนักวัฒนธรรม กีฬา และการท่องเที่ยว ฝากเงินบำรุงศูนย์บริการกับธนาคารของรัฐ",
     "verified": True, "source_id": "s1", "page_from": 3, "page_to": 3},
    {"id": "m6", "title": "พระราชบัญญัติเครื่องหมายราชการ พุทธศักราช ๒๔๘๒", "section": "มาตรา ๖",
     "quote": "มาตรา ๖ ห้ามมิให้บุคคลใดใช้เครื่องหมายราชการ เว้นแต่หน่วยราชการที่กำหนดเครื่องหมายนั้นจะได้อนุญาต",
     "verified": True, "source_id": "s2", "page_from": 1, "page_to": 1},
    {"id": "x1", "title": "ระเบียบที่ยังไม่ตรวจ", "section": "ข้อ ๑", "quote": "เครื่องหมายราชการ สถานที่ ค่าบริการ",
     "verified": False},
]
CONTEXT = "ขออนุญาตใช้ตราสัญลักษณ์กรุงเทพมหานคร (เครื่องหมายราชการ) บนถ้วยรางวัล และขอใช้สถานที่ลานกีฬา"


def test_keyword_rank_finds_related_sections():
    ranked = [r["id"] for r, _, _ in keyword_rank(CONTEXT, [r for r in REFS if r["verified"]])]
    assert ranked[0] in ("m6", "a14") and set(ranked[:2]) == {"m6", "a14"}
    assert keyword_rank("", REFS) == []


def test_ai_can_only_pick_from_the_list_and_never_unverified():
    seen = {}

    def ai(system, prompt):
        seen["prompt"] = prompt
        return LegalPicks(picks=[LegalPick(id="m6", reason="ใช้เครื่องหมายราชการต้องได้รับอนุญาต"),
                                 LegalPick(id="invented-law", reason="แต่งขึ้น"),
                                 LegalPick(id="x1", reason="ยังไม่ยืนยัน"),
                                 LegalPick(id="m6", reason="ซ้ำ")])
    got = suggest(CONTEXT, REFS, ai=ai)
    assert [(s.id, s.by) for s in got] == [("m6", "ai")]
    assert "[m6]" in seen["prompt"] and "[x1]" not in seen["prompt"]       # ไม่ส่งรายการที่ยังไม่ยืนยัน


def test_ai_failure_falls_back_to_keywords():
    def broken(system, prompt):
        raise RuntimeError("timeout")
    got = suggest(CONTEXT, REFS, ai=broken, limit=2)
    assert len(got) == 2 and all(s.by == "keyword" and s.reason.startswith("คำที่ตรงกับเรื่อง") for s in got)


def test_no_match_and_empty_library():
    assert suggest("งานเลี้ยงปีใหม่", REFS) == [] or all(s.by == "keyword" for s in suggest("งานเลี้ยงปีใหม่", REFS))
    assert suggest(CONTEXT, []) == []


def test_document_keeps_legal_refs():
    doc = PRESET_TEMPLATES["bma_cohost_request"].schema.model_copy(deep=True)
    data = doc.model_dump(mode="json")
    data["legal_refs"] = [{"id": "m6", "title": "พ.ร.บ.", "section": "มาตรา ๖", "source_id": "s2", "page_from": 1, "page_to": 1}]
    again = GovDocumentSchema.model_validate(data)
    assert again.legal_refs[0].page_from == 1
    assert PRESET_TEMPLATES["bma_cohost_request"].schema.legal_refs is None


# ---------------------------------------------------------------- API
@pytest.fixture
def fake(tmp_path, monkeypatch):
    from server import auth as server_auth
    from server import supabase as server_supabase
    from server.main import app
    from server.settings import Settings, get_settings
    from tests.fake_supabase import ORG_ID, PUBLISHABLE_KEY, URL, FakeSupabase

    fake = FakeSupabase()
    fake.tables["legal_references"] = [dict(r, org_id=ORG_ID) for r in REFS]
    monkeypatch.setattr(server_supabase, "transport_factory", fake.transport)
    server_auth._jwks_cache.clear()
    app.dependency_overrides[get_settings] = lambda: Settings(
        upload_dir=tmp_path / "u", registry_db_path=tmp_path / "r.db",
        supabase_url=URL, supabase_publishable_key=PUBLISHABLE_KEY, gemini_api_key="k")
    yield fake
    app.dependency_overrides.clear()


def test_suggest_api_with_ai(fake, monkeypatch):
    from server.main import app
    from server.routers import legal as legal_router

    monkeypatch.setattr(legal_router, "structured_call",
                        lambda system, prompt, schema, config, timeout_s: LegalPicks(picks=[LegalPick(id="a14", reason="ค่าใช้สถานที่")]))
    res = TestClient(app).post("/api/v1/legal/suggest", json={"text": CONTEXT},
                               headers={"Authorization": f"Bearer {fake.token()}"})
    assert res.status_code == 200, res.text
    got = res.json()["suggestions"]
    assert [(s["reference"]["id"], s["by"], s["reason"]) for s in got] == [("a14", "ai", "ค่าใช้สถานที่")]
    assert got[0]["reference"]["page_from"] == 3
    sent = [r for r in fake.requests if r.url.path == "/rest/v1/legal_references"][-1]
    assert sent.url.params["verified"] == "eq.true"


def test_suggest_api_without_ai_uses_keywords(fake):
    from server.main import app
    from server.settings import Settings, get_settings
    from tests.fake_supabase import PUBLISHABLE_KEY, URL

    app.dependency_overrides[get_settings] = lambda: Settings(supabase_url=URL, supabase_publishable_key=PUBLISHABLE_KEY)
    got = TestClient(app).post("/api/v1/legal/suggest", json={"text": CONTEXT, "limit": 2},
                               headers={"Authorization": f"Bearer {fake.token()}"}).json()["suggestions"]
    assert {s["reference"]["id"] for s in got} == {"m6", "a14"} and all(s["by"] == "keyword" for s in got)
