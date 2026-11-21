"""
Step 24: ใช้ไฟล์ Word ที่แนบเป็นแม่แบบ — แก้เฉพาะข้อความ คงรูปแบบเดิม (core/docx_template, core/template_ai, API)
"""

import io
import json

from docx import Document
from fastapi.testclient import TestClient

from core.docx_template import apply_edits, replace_paragraph_text, segments
from core.template_ai import TemplateEdit, TemplateEdits, build_prompt, propose_edits
from server.main import app
from server.routers import word_template

client = TestClient(app)


def _template() -> bytes:
    d = Document()
    p = d.add_paragraph()
    label = p.add_run("ปีงบประมาณ")
    label.bold = True
    p.add_run("\t2571")
    d.add_paragraph("")                                   # ย่อหน้าว่างในเนื้อความ: ไม่ส่งให้ AI แต่ยังนับรหัส
    d.add_paragraph("ระหว่างเดือน พ.ย. 70 – พ.ค. 71")
    t = d.add_table(rows=1, cols=2)
    t.cell(0, 0).text = "1.1 ผู้ตัดสิน"
    t.cell(0, 1).text = "12,000.-"
    t.cell(0, 1).add_paragraph("")                        # ย่อหน้าว่างในตาราง: ส่งให้ AI (ใช้จัดบรรทัด)
    buf = io.BytesIO()
    d.save(buf)
    return buf.getvalue()


def test_segments_ids_and_locations():
    segs = segments(_template())
    assert [(s.id, s.where, s.text) for s in segs] == [
        ("p1", "เนื้อความ", "ปีงบประมาณ\t2571"),
        ("p3", "เนื้อความ", "ระหว่างเดือน พ.ย. 70 – พ.ค. 71"),
        ("p4", "ตาราง 1 แถว 1 ช่อง 1", "1.1 ผู้ตัดสิน"),
        ("p5", "ตาราง 1 แถว 1 ช่อง 2", "12,000.-"),
        ("p6", "ตาราง 1 แถว 1 ช่อง 2", ""),
    ]


def test_replace_keeps_formatting_of_unchanged_parts():
    d = Document()
    p = d.add_paragraph()
    r = p.add_run("ชื่อโครงการ")
    r.bold = True
    p.add_run("  โครงการเดิม ปี 2570")
    assert replace_paragraph_text(p, "ชื่อโครงการ  โครงการเดิม ปี 2572")
    assert [x.text for x in p.runs] == ["ชื่อโครงการ", "  โครงการเดิม ปี 2572"] and p.runs[0].bold
    assert not replace_paragraph_text(p, "ชื่อโครงการ  โครงการเดิม ปี 2572")       # ไม่เปลี่ยน = ไม่แตะ
    assert replace_paragraph_text(p, "ชื่อโครงการ")
    assert p.text == "ชื่อโครงการ" and p.runs[0].bold


def test_apply_edits_changes_only_listed_paragraphs():
    data = _template()
    out, changed = apply_edits(data, {"p1": "ปีงบประมาณ\t2572", "p6": "9,600.-", "p99": "ไม่มีรหัสนี้"})
    assert changed == 2
    after = {s.id: s.text for s in segments(out)}
    assert after["p1"] == "ปีงบประมาณ\t2572" and after["p6"] == "9,600.-" and after["p3"].endswith("พ.ค. 71")
    assert Document(io.BytesIO(out)).paragraphs[0].runs[0].bold                      # ป้ายตัวหนาคงเดิม


def test_propose_filters_unknown_and_unchanged():
    segs = segments(_template())
    seen = {}

    def ai(system, prompt):
        seen["prompt"] = prompt
        return TemplateEdits(edits=[TemplateEdit(id="p1", text="ปีงบประมาณ\t2572"),
                                    TemplateEdit(id="p4", text="1.1 ผู้ตัดสิน"),          # ไม่เปลี่ยน → ตัด
                                    TemplateEdit(id="p77", text="x")],                   # รหัสไม่มี → ตัด
                             summary="เปลี่ยนปี", notes="")

    res = propose_edits(segs, "ปรับเป็นปี 2572", "", ai)
    assert res.changes == [{"id": "p1", "where": "เนื้อความ", "before": "ปีงบประมาณ\t2571", "after": "ปีงบประมาณ\t2572"}]
    assert "p6 [ตาราง 1 แถว 1 ช่อง 2] (ว่าง)" in seen["prompt"] and "<instruction>" in seen["prompt"]
    assert "ต้นเรื่องใหม่" in build_prompt(segs, "x", "ข้อมูลใหม่")


def test_api_propose_and_build(monkeypatch):
    def fake_structured_call(system, prompt, schema, config, timeout_s=25.0, max_tokens=2000):
        return TemplateEdits(edits=[TemplateEdit(id="p3", text="ระหว่างเดือน พ.ย. 71 – พ.ค. 72")], summary="ok", notes="")

    monkeypatch.setattr(word_template, "structured_call", fake_structured_call)
    monkeypatch.setattr(word_template, "llm_config",
                        lambda s: type("C", (), {"any_provider": True})())
    files = {"file": ("แม่แบบ.docx", _template(), "application/octet-stream")}
    res = client.post("/api/v1/studio/word-template/propose", data={"prompt": "ปี 2572"}, files=files)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["segment_count"] == 5 and body["changes"][0]["id"] == "p3"

    edits = {c["id"]: c["after"] for c in body["changes"]}
    res = client.post("/api/v1/studio/word-template/build", data={"edits": json.dumps(edits)}, files=files)
    assert res.status_code == 200 and res.headers["x-govdoc-changed"] == "1"
    assert "attachment" in res.headers["content-disposition"]
    assert segments(res.content)[1].text == "ระหว่างเดือน พ.ย. 71 – พ.ค. 72"


def test_api_rejects_bad_input():
    files = {"file": ("a.pdf", b"%PDF", "application/pdf")}
    assert client.post("/api/v1/studio/word-template/propose", data={"prompt": "x"}, files=files).status_code == 400
    files = {"file": ("a.docx", _template(), "application/octet-stream")}
    assert client.post("/api/v1/studio/word-template/propose", data={"prompt": ""}, files=files).status_code == 400
    assert client.post("/api/v1/studio/word-template/propose",
                       data={"prompt": "x", "secret": "secret"}, files=files).status_code == 400     # ชั้นความลับไม่ส่ง AI
    assert client.post("/api/v1/studio/word-template/build", data={"edits": "[1]"}, files=files).status_code == 400
