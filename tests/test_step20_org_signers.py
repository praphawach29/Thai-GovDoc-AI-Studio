"""
Step 20: รายชื่อผู้ลงนามประจำหน่วยงาน (org_signers) — เติมชื่อผู้ลงนามในร่างใหม่ + API ตั้งค่า
"""

import httpx
import pytest
from fastapi.testclient import TestClient

from core.issuing_units import SIGNER_NAME_PLACEHOLDER, apply_issuing_unit
from core.models import Signer, default_issuing_units
from core.signers import (OrgSigner, clean_name, clean_position, fill_document_signers, fill_from_roster,
                          is_blank_name, match_position)
from core.studio import create_blank_document
from core.models import DocType
from server import auth as server_auth
from server import supabase as server_supabase
from server.main import app
from server.settings import Settings, get_settings
from tests.fake_supabase import ORG_ID, PUBLISHABLE_KEY, URL, FakeSupabase

HEAD = OrgSigner(id="1", full_name="นายหัวหน้า กลุ่มงาน", position="หัวหน้ากลุ่มงานส่งเสริมกีฬา")
DIRECTOR = OrgSigner(id="2", full_name="นางผู้อำนวยการ กองกีฬา", position="ผู้อำนวยการกองการกีฬา", stamp=True)
DEFAULT = OrgSigner(id="3", full_name="นายเริ่มต้น ลงนาม", position="ผู้อำนวยการสำนักวัฒนธรรม กีฬา และการท่องเที่ยว\nกรุงเทพมหานคร",
                    is_default=True)


# ---------------------------------------------------------------- core
def test_clean_name_and_position():
    assert clean_name("  (นายสมชาย   ใจดี) ") == "นายสมชาย ใจดี"
    assert clean_position(" ผู้อำนวยการกอง \r\n\n  กรุงเทพมหานคร ") == "ผู้อำนวยการกอง\nกรุงเทพมหานคร"
    assert DEFAULT.display_name() == "(นายเริ่มต้น ลงนาม)"


def test_blank_name_detection():
    assert is_blank_name("") and is_blank_name("()") and is_blank_name(SIGNER_NAME_PLACEHOLDER)
    assert not is_blank_name("(นายสมชาย ใจดี)")


def test_match_position_whole_then_first_line():
    roster = [HEAD, DIRECTOR, DEFAULT]
    assert match_position(roster, "ผู้อำนวยการกองการกีฬา") is DIRECTOR
    assert match_position(roster, "หัวหน้ากลุ่มงาน ส่งเสริมกีฬา") is HEAD          # ช่องว่างไม่มีผล
    assert match_position(roster, "ผู้อำนวยการสำนักวัฒนธรรม กีฬา และการท่องเที่ยว") is DEFAULT   # บรรทัดแรก
    assert match_position(roster, "[✏️ ระบุตำแหน่ง]") is None
    assert match_position(roster, "ปลัดกรุงเทพมหานคร") is None


def test_fill_matches_position_and_keeps_author_and_typed_names():
    slots = [Signer(name="(ผู้ใช้)", position="นักวิชาการ", is_author=True),
             Signer(name=SIGNER_NAME_PLACEHOLDER, position="หัวหน้ากลุ่มงานส่งเสริมกีฬา"),
             Signer(name="(คนที่พิมพ์เอง)", position="ผู้อำนวยการกองการกีฬา")]
    fill_from_roster(slots, [HEAD, DIRECTOR, DEFAULT], use_default=True)
    assert slots[0].name == "(ผู้ใช้)"
    assert slots[1].name == "(นายหัวหน้า กลุ่มงาน)"
    assert slots[2].name == "(คนที่พิมพ์เอง)"           # ไม่ทับชื่อที่มีอยู่


def test_default_fills_last_open_non_author_slot_only_when_fresh():
    def slots():
        return [Signer(name="", position="ผู้เสนอเรื่อง", is_author=True),
                Signer(name=SIGNER_NAME_PLACEHOLDER, position="ปลัดกรุงเทพมหานคร")]
    s = fill_from_roster(slots(), [HEAD, DEFAULT], use_default=False)
    assert s[1].name == SIGNER_NAME_PLACEHOLDER              # ไม่ใช่ร่างใหม่: ตำแหน่งไม่ตรง = ไม่เดา
    s = fill_from_roster(slots(), [HEAD, DEFAULT], use_default=True)
    assert s[0].name == ""                                   # ผู้เสนอเรื่องไม่ถูกเติมจากรายชื่อ
    assert s[1].name == "(นายเริ่มต้น ลงนาม)" and s[1].position.startswith("ผู้อำนวยการสำนัก")


def test_default_not_used_twice():
    slots = [Signer(name="", position=DEFAULT.position), Signer(name="", position="ตำแหน่งอื่น")]
    fill_from_roster(slots, [DEFAULT], use_default=True)
    assert slots[0].name == "(นายเริ่มต้น ลงนาม)" and slots[1].name == ""


def test_roster_stamp_carries_over():
    slots = [Signer(name="", position="ผู้อำนวยการกองการกีฬา")]
    fill_from_roster(slots, [DIRECTOR])
    assert slots[0].stamp is True


def test_apply_issuing_unit_fills_whole_chain_by_position():
    units = default_issuing_units()
    doc = create_blank_document(DocType.INTERNAL)
    author = Signer(name="(ผู้เสนอ)", position="นักวิชาการ", is_author=True)
    roster = [HEAD, DIRECTOR]
    first = apply_issuing_unit(doc, units[0], author=author, units=units, roster=roster)
    assert first.signatory_name == "(ผู้เสนอ)"
    assert first.co_signers[0].name == "(นายหัวหน้า กลุ่มงาน)"
    second = apply_issuing_unit(first, units[1], units=units, roster=roster)
    assert second.signatory_name == "(นางผู้อำนวยการ กองกีฬา)" and second.signatory_stamp is True
    third = apply_issuing_unit(first, units[2], units=units, roster=roster)
    assert third.signatory_name == SIGNER_NAME_PLACEHOLDER        # ไม่มีในรายชื่อ = เว้นให้กรอกเหมือนเดิม
    # ไม่มีรายชื่อ = พฤติกรรมเดิม
    plain = apply_issuing_unit(doc, units[1], units=units)
    assert plain.signatory_name == SIGNER_NAME_PLACEHOLDER


def test_fill_document_signers_external():
    doc = create_blank_document(DocType.EXTERNAL)
    doc.signatory_name, doc.signatory_position = "(ชื่อในโปรไฟล์เครื่อง)", "ตำแหน่งในโปรไฟล์"
    out = fill_document_signers(doc, [HEAD, DEFAULT], use_default=True)
    assert out.signatory_name == "(นายเริ่มต้น ลงนาม)"
    assert out.signatory_position == DEFAULT.position
    assert fill_document_signers(doc, [], use_default=True).signatory_name == "(ชื่อในโปรไฟล์เครื่อง)"
    # ไม่ใช่ร่างใหม่ + ตำแหน่งไม่ตรง → ไม่เปลี่ยน
    assert fill_document_signers(doc, [HEAD], use_default=False).signatory_name == "(ชื่อในโปรไฟล์เครื่อง)"


def test_multiline_position_reaches_export_lines():
    doc = create_blank_document(DocType.EXTERNAL)
    out = fill_document_signers(doc, [DEFAULT], use_default=True)
    assert out.signer_lines()[0] == ("(นายเริ่มต้น ลงนาม)", DEFAULT.position)


# ---------------------------------------------------------------- API
class SignersFake(FakeSupabase):
    def __init__(self):
        super().__init__()
        self.tables["org_signers"] = []
        self.tables["org_units"] = [{**u.model_dump(), "sort_order": i} for i, u in enumerate(default_issuing_units())]
        self.missing = set()

    def _table(self, request, table, query):
        if table in self.missing:
            return httpx.Response(404, json={"code": "PGRST205", "message": f"Could not find the table 'public.{table}'"})
        if request.method == "DELETE":
            target = {k: v[3:] for k, v in query.items() if v.startswith("eq.")}
            self.tables[table] = [r for r in self.tables[table] if not all(str(r.get(k)) == v for k, v in target.items())]
            return httpx.Response(204)
        return super()._table(request, table, query)


@pytest.fixture
def fake(tmp_path, monkeypatch):
    fake = SignersFake()
    monkeypatch.setattr(server_supabase, "transport_factory", fake.transport)
    server_auth._jwks_cache.clear()
    app.dependency_overrides[get_settings] = lambda: Settings(
        upload_dir=tmp_path / "uploads", registry_db_path=tmp_path / "r.db",
        supabase_url=URL, supabase_publishable_key=PUBLISHABLE_KEY,
    )
    yield fake
    app.dependency_overrides.clear()


@pytest.fixture
def client():
    return TestClient(app)


def _h(fake):
    return {"Authorization": f"Bearer {fake.token()}"}


def test_signers_crud_and_single_default(fake, client):
    h = _h(fake)
    r = client.post("/api/v1/signers", json={"full_name": "(นายหัวหน้า กลุ่มงาน)", "position": "หัวหน้ากลุ่มงานส่งเสริมกีฬา"}, headers=h)
    assert r.status_code == 201, r.text
    first = r.json()
    assert first["full_name"] == "นายหัวหน้า กลุ่มงาน"           # ตัดวงเล็บ
    assert first["is_default"] is True                           # คนแรก = เริ่มต้น
    assert fake.tables["org_signers"][0]["org_id"] == ORG_ID
    r = client.post("/api/v1/signers", json={"full_name": "นางผู้อำนวยการ กองกีฬา", "position": "ผู้อำนวยการกองการกีฬา\n กรุงเทพมหานคร ",
                                             "stamp": True}, headers=h)
    second = r.json()
    assert second["is_default"] is False and second["position"] == "ผู้อำนวยการกองการกีฬา\nกรุงเทพมหานคร"

    r = client.patch(f"/api/v1/signers/{second['id']}", json={"is_default": True}, headers=h)
    assert r.status_code == 200 and r.json()["is_default"] is True
    rows = client.get("/api/v1/signers", headers=h).json()
    assert [x["is_default"] for x in rows] == [True, False]      # คนเริ่มต้นอยู่บนสุด และมีคนเดียว
    assert rows[0]["id"] == second["id"]

    r = client.patch(f"/api/v1/signers/{first['id']}", json={"position": "หัวหน้ากลุ่มงาน\nส่งเสริมกีฬา"}, headers=h)
    assert r.json()["position"] == "หัวหน้ากลุ่มงาน\nส่งเสริมกีฬา"
    assert client.delete(f"/api/v1/signers/{first['id']}", headers=h).json()["deleted"] is True
    assert len(client.get("/api/v1/signers", headers=h).json()) == 1
    assert client.delete(f"/api/v1/signers/{first['id']}", headers=h).status_code == 404


def test_signers_validation(fake, client):
    h = _h(fake)
    assert client.post("/api/v1/signers", json={"full_name": "  "}, headers=h).status_code == 422
    assert client.post("/api/v1/signers", json={"full_name": "[✏️ ระบุชื่อผู้ลงนาม]"}, headers=h).status_code == 422
    assert client.post("/api/v1/signers", json={"full_name": "ก", "position": "\n".join("abcdef")}, headers=h).status_code == 422
    assert client.patch("/api/v1/signers/00000000-0000-0000-0000-000000000000", json={}, headers=h).status_code == 400


def test_signers_require_login(fake, client):
    assert client.get("/api/v1/signers").status_code == 401


def test_missing_table_hint_and_drafting_still_works(fake, client):
    fake.missing.add("org_signers")
    h = _h(fake)
    r = client.get("/api/v1/signers", headers=h)
    assert r.status_code == 503 and "20261116000012_org_signers.sql" in r.json()["detail"]
    r = client.post("/api/v1/studio/blank", json={"doc_type": "internal"}, headers=h)
    assert r.status_code == 200, r.text
    assert r.json()["co_signers"][0]["name"] == SIGNER_NAME_PLACEHOLDER


def test_new_memo_gets_roster_names(fake, client):
    h = _h(fake)
    client.post("/api/v1/signers", json={"full_name": "นายหัวหน้า กลุ่มงาน", "position": "หัวหน้ากลุ่มงานส่งเสริมกีฬา",
                                         "is_default": True}, headers=h)
    client.post("/api/v1/signers", json={"full_name": "นางผู้อำนวยการ กองกีฬา", "position": "ผู้อำนวยการกองการกีฬา"}, headers=h)
    doc = client.post("/api/v1/studio/blank", json={"doc_type": "internal"}, headers=h).json()
    assert doc["signatory_name"] == "(ผู้ทดสอบ)"                     # ผู้เสนอเรื่อง = ผู้ใช้ที่ล็อกอิน
    assert doc["co_signers"][0]["name"] == "(นายหัวหน้า กลุ่มงาน)"
    # เสนอขั้นถัดไป (apply-unit): ตำแหน่งตรงกับรายชื่อ → ได้ชื่อทันที
    up = client.post("/api/v1/studio/apply-unit", json={"doc": doc, "unit_key": "sports-division"}, headers=h).json()
    assert up["signatory_name"] == "(นางผู้อำนวยการ กองกีฬา)"
    check = client.post("/api/v1/studio/check", json=up, headers=h).json()
    assert not any("ผู้ลงนาม" in str(p) for p in check.get("placeholders", []))


def test_new_external_letter_uses_default_signer(fake, client):
    h = _h(fake)
    client.post("/api/v1/signers", json={"full_name": "นายเริ่มต้น ลงนาม", "position": "ผู้อำนวยการสำนัก\nกรุงเทพมหานคร"}, headers=h)
    doc = client.post("/api/v1/studio/blank", json={"doc_type": "external"}, headers=h).json()
    assert doc["signatory_name"] == "(นายเริ่มต้น ลงนาม)"
    assert doc["signatory_position"] == "ผู้อำนวยการสำนัก\nกรุงเทพมหานคร"
