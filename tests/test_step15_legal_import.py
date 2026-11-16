"""
Step 15: คลังกฎหมาย — แยกไฟล์ระเบียบที่ AI อ่านแล้วเป็นข้อ/มาตรา พร้อมเลขหน้า (รูปแบบจากไฟล์จริงของหน่วยงาน)
"""

from core.legal_import import guess_title, split_sections

# ระเบียบกรุงเทพมหานคร (ราชกิจจานุเบกษา): หัวกระดาษ "หน้า N / เล่ม ... ราชกิจจานุเบกษา", หมวด, ข้อยาวข้ามหน้า, บัญชีท้าย
REG = [
    """หน้า ๑
เล่ม ๑๓๗ ตอนพิเศษ ๒๙๗ ง ราชกิจจานุเบกษา ๒๑ ธันวาคม ๒๕๖๓
ระเบียบกรุงเทพมหานคร
ว่าด้วยเงินบำรุงและค่าใช้จ่ายของศูนย์บริการและกิจกรรมส่งเสริมการกีฬา การดนตรี
สำนักวัฒนธรรม กีฬา และการท่องเที่ยว
พ.ศ. ๒๕๖๓
โดยที่เป็นการสมควรกำหนดระเบียบ
อาศัยอำนาจตามความในมาตรา ๔๙ ประกอบกับข้อ ๕ ข้อ ๖
ข้อ ๑ ระเบียบนี้เรียกว่า “ระเบียบกรุงเทพมหานคร ...”
ข้อ ๒ ระเบียบนี้ใช้บังคับตั้งแต่วันถัดจากวันประกาศ
ข้อ ๓ ให้ยกเลิก
(๑) ระเบียบกรุงเทพมหานครว่าด้วยการรับเงิน""",
    """หน้า ๒
เล่ม ๑๓๗ ตอนพิเศษ ๒๙๗ ง ราชกิจจานุเบกษา ๒๑ ธันวาคม ๒๕๖๓
(๒) ระเบียบกรุงเทพมหานครว่าด้วยอัตราค่าตอบแทน
ข้อ ๑๓ ให้ศูนย์บริการที่มีการรับจ่ายเงินจัดทำบัญชี
หมวด ๒
ค่าสมาชิก ค่าบริการ ค่าใช้สถานที่ และค่าปรับ ของศูนย์บริการ
ข้อ ๑๔ อัตราค่าสมาชิก ค่าบริการ ค่าใช้สถานที่ และค่าปรับ ให้เป็นไปตามบัญชีท้ายระเบียบนี้
ข้อ ๑๕ ผู้ขอใช้บริการหรือสถานที่ของศูนย์บริการ ต้องเสียค่าบริการ""",
    """หน้า ๓
ในกรณีผู้ขอใช้บริการมีการจำหน่ายบัตรผ่านประตู ให้คิดค่าบริการเพิ่มร้อยละยี่สิบ
ข้อ ๑๖ การยกเว้นค่าบริการ
ประกาศ ณ วันที่ ๑๖ ธันวาคม พ.ศ. ๒๕๖๓""",
    """-๑๖-
บัญชีท้ายระเบียบกรุงเทพมหานคร
ลำดับ รายการ อัตรา (บาท)
ข้อ ๑ ค่าตอบแทนผู้ตัดสิน ๕๐๐.-""",
    """-๑๗-
(๑๕) ซอฟท์บอล (ต่อคู่) ผู้ตัดสิน ๔ คน คนละ ๕๐๐.-""",
]


def _labels(sections):
    return [(s.label, s.page_from, s.page_to) for s in sections]


def test_regulation_sections_pages_and_chapter():
    got = split_sections(REG)
    assert _labels(got) == [
        ("ข้อ ๑", 1, 1), ("ข้อ ๒", 1, 1), ("ข้อ ๓", 1, 2), ("ข้อ ๑๓", 2, 2),
        ("ข้อ ๑๔", 2, 2), ("ข้อ ๑๕", 2, 3), ("ข้อ ๑๖", 3, 3),
        ("บัญชีท้ายระเบียบกรุงเทพมหานคร", 4, 5),
    ]
    by = {s.label: s for s in got}
    assert by["ข้อ ๑๔"].chapter == "หมวด ๒ ค่าสมาชิก ค่าบริการ ค่าใช้สถานที่ และค่าปรับ ของศูนย์บริการ"
    assert by["ข้อ ๑๓"].chapter is None
    assert by["ข้อ ๑๔"].number == "14"
    assert "ร้อยละยี่สิบ" in by["ข้อ ๑๕"].text                  # ข้อยาวข้ามหน้า
    assert "ราชกิจจานุเบกษา" not in by["ข้อ ๓"].text and "หน้า ๒" not in by["ข้อ ๓"].text   # หัวกระดาษไม่ปน
    assert "ซอฟท์บอล" in by["บัญชีท้ายระเบียบกรุงเทพมหานคร"].text
    assert "ข้อ ๑ ค่าตอบแทน" in by["บัญชีท้ายระเบียบกรุงเทพมหานคร"].text   # "ข้อ ๑" ในตารางไม่แยกเป็นข้อใหม่


def test_chapter_title_on_next_line_is_kept_with_section_text():
    got = {s.label: s for s in split_sections(REG)}
    # ชื่อหมวดอยู่บรรทัดถัดไป: ไม่หลุดไปเป็นเนื้อหาของข้อ ๑๓
    assert "ค่าสมาชิก ค่าบริการ" not in got["ข้อ ๑๓"].text


def test_act_with_arabic_section_numbers():
    act = ["""สำเนา
พระราชบัญญัติ
เครื่องหมายราชการ พุทธศักราช 2482
มาตรา 1 พระราชบัญญัตินี้ให้เรียกว่า "พระราชบัญญัติเครื่องหมายราชการ พุทธศักราช
2482"
มาตรา 2 ให้ใช้พระราชบัญญัตินี้ตั้งแต่วันประกาศในราชกิจจานุเบกษาเป็นต้นไป""",
           """มาตรา 8 ผู้ใดฝ่าฝืนบทบัญญัติแห่งมาตรา 6 หรือมาตรา 7 มีความผิดต้องระวางโทษ
มาตรา 9 เครื่องหมาย"""]
    got = split_sections(act)
    assert _labels(got) == [("มาตรา ๑", 1, 1), ("มาตรา ๒", 1, 1), ("มาตรา ๘", 2, 2), ("มาตรา ๙", 2, 2)]
    assert "2482\"" in got[0].text                       # บรรทัดที่เป็นเลขปีล้วนไม่ถูกตัดเป็นเลขหน้า? (ตัดได้ — ดูข้อความหลัก)
    assert split_sections(act, thai_digits=False)[0].label == "มาตรา 1"


def test_mention_of_section_inside_text_is_not_a_heading():
    got = split_sections(["มาตรา 8 ผู้ใดฝ่าฝืนบทบัญญัติแห่งมาตรา 6 หรือมาตรา 7\nมาตรา 6 ห้ามมิให้บุคคลใด"])
    assert [s.label for s in got] == ["มาตรา ๘", "มาตรา ๖"]


def test_announcement_without_sections_is_whole_document():
    pages = ["ประกาศสำนักนายกรัฐมนตรี\nเรื่อง กำหนดภาพเครื่องหมายราชการ\nอาศัยอำนาจตามความในมาตรา ๕ แห่งพระราชบัญญัติ",
             "ภาพเครื่องหมายราชการของกรุงเทพมหานคร"]
    got = split_sections(pages)
    assert _labels(got) == [("ทั้งฉบับ", 1, 2)]
    assert "ภาพเครื่องหมาย" in got[0].text


def test_guess_title():
    assert guess_title(REG).startswith("ระเบียบกรุงเทพมหานคร ว่าด้วยเงินบำรุงและค่าใช้จ่าย")
    assert guess_title(["ประกาศสำนักนายกรัฐมนตรี\nเรื่อง กำหนดภาพเครื่องหมายราชการ\nอาศัยอำนาจ"]) == \
        "ประกาศสำนักนายกรัฐมนตรี เรื่อง กำหนดภาพเครื่องหมายราชการ"
    assert guess_title(["ข้อความทั่วไป"]) == ""


def test_empty():
    assert split_sections([]) == [] and split_sections(["", "  "]) == []


# ---------------------------------------------------------------- API (Supabase)
import io

import pytest
from fastapi.testclient import TestClient

from core import llm_drafter
from server import auth as server_auth
from server import supabase as server_supabase
from server.main import app
from server.settings import Settings, get_settings
from tests.fake_supabase import ORG_ID, PUBLISHABLE_KEY, URL, FakeSupabase


def _pdf_bytes(pages=3):
    from PIL import Image
    imgs = [Image.new("RGB", (300, 420), "white") for _ in range(pages)]
    buf = io.BytesIO()
    imgs[0].save(buf, format="PDF", save_all=True, append_images=imgs[1:])
    return buf.getvalue()


@pytest.fixture
def fake(tmp_path, monkeypatch):
    fake = FakeSupabase()
    monkeypatch.setattr(server_supabase, "transport_factory", fake.transport)
    server_auth._jwks_cache.clear()
    app.dependency_overrides[get_settings] = lambda: Settings(
        upload_dir=tmp_path / "uploads", registry_db_path=tmp_path / "r.db",
        supabase_url=URL, supabase_publishable_key=PUBLISHABLE_KEY, gemini_api_key="k",
    )
    yield fake
    app.dependency_overrides.clear()


@pytest.fixture
def client():
    return TestClient(app)


def _register(fake, client, h, pages=3):
    res = client.post("/api/v1/legal/sources/upload-url", json={"filename": "ระเบียบ.pdf", "size_bytes": 100}, headers=h)
    assert res.status_code == 200, res.text
    path = res.json()["path"]
    assert path.startswith(f"{ORG_ID}/legal/") and path.endswith(".pdf")
    fake.storage[f"sources/{path}"] = _pdf_bytes(pages)
    return client.post("/api/v1/legal/sources", json={"path": path, "filename": "ระเบียบ.pdf"}, headers=h)


def test_import_flow(fake, client, monkeypatch):
    h = {"Authorization": f"Bearer {fake.token()}"}
    res = _register(fake, client, h)
    assert res.status_code == 201, res.text
    src = res.json()
    assert src["page_count"] == 3 and fake.tables["legal_sources"][0]["sha256"]

    seen = []
    monkeypatch.setattr(llm_drafter, "_ocr_gemini", lambda images, config, timeout: seen.append(len(images)) or REG[len(seen) - 1])
    png = io.BytesIO()
    from PIL import Image
    Image.new("RGB", (200, 280), "white").save(png, format="JPEG")
    texts = []
    for page in (1, 2, 3):
        r = client.post("/api/v1/legal/ocr-page", data={"page": str(page)},
                        files={"image": ("p.jpg", png.getvalue(), "image/jpeg")}, headers=h)
        assert r.status_code == 200, r.text
        texts.append(r.json()["text"])
    assert seen == [1, 1, 1]                                   # หน้าละหนึ่งคำขอ

    r = client.post(f"/api/v1/legal/sources/{src['id']}/sections", json={"page_texts": texts}, headers=h)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["title"].startswith("ระเบียบกรุงเทพมหานคร ว่าด้วยเงินบำรุง")
    refs = body["references"]
    assert [x["section"] for x in refs][:3] == ["ข้อ ๑", "ข้อ ๒", "ข้อ ๓"]
    assert all(x["verified"] is False and x["source_id"] == src["id"] for x in refs)
    r14 = next(x for x in refs if x["section"] == "ข้อ ๑๔")
    assert (r14["page_from"], r14["page_to"]) == (2, 2) and r14["chapter"].startswith("หมวด ๒")
    # แยกซ้ำไม่ได้
    assert client.post(f"/api/v1/legal/sources/{src['id']}/sections", json={"page_texts": texts}, headers=h).status_code == 409

    ids = [x["id"] for x in refs if x["section"] in ("ข้อ ๑๔", "ข้อ ๑๕")]
    r = client.patch("/api/v1/legal/references/verify", json={"ids": ids}, headers=h)
    assert r.json() == {"updated": 2}
    verified = client.get("/api/v1/legal/references?verified_only=true", headers=h).json()["references"]
    assert {x["section"] for x in verified} == {"ข้อ ๑๔", "ข้อ ๑๕"}
    assert verified[0]["page_from"] == 2

    listed = client.get("/api/v1/legal/sources", headers=h).json()
    assert listed[0]["title"] == body["title"] and "page_texts" not in listed[0]
    url = client.get(f"/api/v1/legal/sources/{src['id']}/file-url", headers=h).json()["url"]
    assert url.startswith(f"{URL}/storage/v1/object/sign/sources/{ORG_ID}/legal/")


def test_wrong_page_count_and_bad_files(fake, client):
    h = {"Authorization": f"Bearer {fake.token()}"}
    src = _register(fake, client, h).json()
    assert client.post(f"/api/v1/legal/sources/{src['id']}/sections", json={"page_texts": ["a"]}, headers=h).status_code == 400
    assert client.post("/api/v1/legal/sources/upload-url", json={"filename": "x.docx", "size_bytes": 5}, headers=h).status_code == 400
    bad = client.post("/api/v1/legal/sources", json={"path": f"{ORG_ID}/finals/{'a' * 32}.pdf", "filename": "x.pdf"}, headers=h)
    assert bad.status_code == 400
    path = f"{ORG_ID}/legal/{'b' * 32}.pdf"
    fake.storage[f"sources/{path}"] = b"not a pdf"
    assert client.post("/api/v1/legal/sources", json={"path": path, "filename": "x.pdf"}, headers=h).status_code == 422
    assert f"sources/{path}" not in fake.storage              # ไฟล์เสียถูกลบทิ้ง


def test_ocr_page_failure_and_missing_ai(fake, client, monkeypatch):
    h = {"Authorization": f"Bearer {fake.token()}"}
    from PIL import Image
    jpg = io.BytesIO(); Image.new("RGB", (50, 50)).save(jpg, format="JPEG")
    monkeypatch.setattr(llm_drafter, "_ocr_gemini", lambda *a: "")
    r = client.post("/api/v1/legal/ocr-page", data={"page": "4"}, files={"image": ("p.jpg", jpg.getvalue(), "image/jpeg")}, headers=h)
    assert r.status_code == 502 and "หน้า 4" in r.json()["detail"]
    r = client.post("/api/v1/legal/ocr-page", data={"page": "1"}, files={"image": ("p.jpg", b"xx", "image/jpeg")}, headers=h)
    assert r.status_code == 400


def test_local_mode_has_no_import():
    assert TestClient(app).get("/api/v1/legal/sources").status_code == 404
