"""register_export.py — พิมพ์ทะเบียนหนังสือรับ/ส่ง ตามแบบในระเบียบงานสารบรรณ (Excel / PDF)

แบบทะเบียน (ระเบียบสำนักนายกรัฐมนตรีว่าด้วยงานสารบรรณ ข้อ 38 และ ข้อ 50):
  หัวกลุ่ม "วันที่ ... เดือน ... พ.ศ. ..." (วันที่รับ / วันที่ส่ง) แล้วตามด้วยแถว
  เลขทะเบียน | ที่ | ลงวันที่ | จาก | ถึง | เรื่อง | การปฏิบัติ | หมายเหตุ

ไม่ใช้ไลบรารี Excel (เพดานขนาด function บน Vercel) — เขียนไฟล์ .xlsx (Office Open XML) เอง
PDF คอมไพล์ด้วย Typst + ฟอนต์ TH SarabunIT๙ ชุดเดียวกับหนังสือ
"""

from __future__ import annotations

import json
import re
import tempfile
import zipfile
from datetime import datetime
from io import BytesIO
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional
from xml.sax.saxutils import escape

from pydantic import BaseModel

from core.thai_date import BANGKOK_TZ, THAI_MONTHS
from core.thai_segmenter import to_thai_numerals

OUTGOING_HEADERS = ["เลขทะเบียนส่ง", "ที่", "ลงวันที่", "จาก", "ถึง", "เรื่อง", "การปฏิบัติ", "หมายเหตุ"]
INCOMING_HEADERS = ["เลขทะเบียนรับ", "ที่", "ลงวันที่", "จาก", "ถึง", "เรื่อง", "การปฏิบัติ", "หมายเหตุ"]
# ความกว้างสัมพัทธ์ของคอลัมน์ (Excel ใช้เป็นจำนวนตัวอักษร × 2, PDF ใช้เป็นสัดส่วน fr)
_WIDTHS = [9, 13, 13, 15, 15, 28, 16, 16]

STATUS_LABELS = {"reserved": "จองเลข", "issued": "ออกเลขแล้ว", "cancelled": "ยกเลิก"}


class RegisterGroup(BaseModel):
    heading: str
    rows: List[List[str]]


class RegisterSheet(BaseModel):
    title: str
    subtitle: str = ""
    headers: List[str]
    widths: List[int] = _WIDTHS
    groups: List[RegisterGroup]

    def row_count(self) -> int:
        return sum(len(g.rows) for g in self.groups)


# ---------------------------------------------------------------- วันเวลา
def parse_timestamp(value: Any) -> Optional[datetime]:
    """timestamptz จาก PostgREST (ISO 8601) → เวลาประเทศไทย"""
    if not value:
        return None
    text = str(value).strip().replace(" ", "T", 1)
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    # Python 3.10 รับเศษวินาทีได้ไม่เกิน 6 หลัก
    text = re.sub(r"(\.\d{6})\d+", r"\1", text)
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=BANGKOK_TZ)
    return dt.astimezone(BANGKOK_TZ)


def thai_date_text(dt: Optional[datetime]) -> str:
    if dt is None:
        return ""
    return f"{dt.day} {THAI_MONTHS[dt.month - 1]} {dt.year + 543}"


def thai_time_text(dt: Optional[datetime]) -> str:
    return "" if dt is None else f"{dt.hour:02d}.{dt.minute:02d} น."


def _num(text: Any, thai: bool) -> str:
    value = "" if text is None else str(text)
    return to_thai_numerals(value) if thai else value


def _join(*parts: str) -> str:
    return " · ".join(p for p in parts if p)


# ---------------------------------------------------------------- จัดแถวตามแบบทะเบียน
def _grouped(items: Iterable[tuple], thai: bool) -> List[RegisterGroup]:
    groups: List[RegisterGroup] = []
    for dt, cells in items:
        heading = "วันที่ " + (thai_date_text(dt) or "ไม่ระบุ")
        heading = _num(heading, thai)
        cells = [_num(c, thai) for c in cells]
        if groups and groups[-1].heading == heading:
            groups[-1].rows.append(cells)
        else:
            groups.append(RegisterGroup(heading=heading, rows=[cells]))
    return groups


def _sort_key(row: Dict[str, Any]):
    return (int(row.get("year_be") or 0), int(row.get("reg_no") or 0))


def outgoing_cells(row: Dict[str, Any], *, incoming_by_id: Optional[Dict[Any, Dict[str, Any]]] = None,
                   names: Optional[Dict[str, str]] = None) -> List[str]:
    """แถวทะเบียนส่ง: เลขที่ยกเลิกยังแสดงพร้อมเหตุผล ผู้ยกเลิก และเวลา"""
    names = names or {}
    status = row.get("status") or ""
    incoming = (incoming_by_id or {}).get(row.get("incoming_id")) if row.get("incoming_id") else None
    action = row.get("action_taken") or ""
    if incoming:
        action = _join(action, f"ตอบหนังสือรับเลข {incoming.get('reg_no')}/{incoming.get('year_be')}")
    if status == "reserved":
        action = _join(action, "จองเลข" + (f" โดย {names[row['created_by']]}" if names.get(row.get("created_by")) else ""))
    remark = row.get("remark") or ""
    if status == "cancelled":
        when = parse_timestamp(row.get("cancelled_at"))
        who = names.get(row.get("cancelled_by") or "", "")
        detail = " ".join(x for x in (who, thai_date_text(when), thai_time_text(when)) if x)
        remark = _join(f"ยกเลิกเลข: {row.get('cancel_reason') or ''}" + (f" ({detail})" if detail else ""), remark)
    return [str(row.get("reg_no") or ""), row.get("doc_number") or "", row.get("doc_date") or "",
            row.get("from_unit") or "", row.get("to_recipient") or "", row.get("subject") or "", action, remark]


def incoming_cells(row: Dict[str, Any], *, replies: Optional[List[Dict[str, Any]]] = None) -> List[str]:
    """แถวทะเบียนรับ: การปฏิบัติ = หนังสือตอบที่ออกเลขแล้ว, หมายเหตุ = เวลารับ"""
    action = row.get("action_taken") or ""
    for reply in replies or []:
        if reply.get("status") == "cancelled":
            continue
        text = f"ตอบแล้ว ที่ {reply.get('doc_number')}"
        if reply.get("doc_date"):
            text += f" ลว. {reply['doc_date']}"
        action = _join(action, text)
    received = parse_timestamp(row.get("received_at"))
    remark = _join(f"รับเวลา {thai_time_text(received)}" if received else "", row.get("remark") or "")
    return [str(row.get("reg_no") or ""), row.get("source_doc_number") or "", row.get("source_doc_date") or "",
            row.get("from_org") or "", row.get("to_unit") or "", row.get("subject") or "", action, remark]


def build_outgoing_sheet(rows: List[Dict[str, Any]], *, org_name: str = "", year_be: Optional[int] = None,
                         incoming_by_id: Optional[Dict[Any, Dict[str, Any]]] = None,
                         names: Optional[Dict[str, str]] = None, thai_digits: bool = True) -> RegisterSheet:
    items = []
    for row in sorted(rows, key=_sort_key):
        when = parse_timestamp(row.get("issued_at") or row.get("created_at"))
        items.append((when, outgoing_cells(row, incoming_by_id=incoming_by_id, names=names)))
    return RegisterSheet(title="ทะเบียนหนังสือส่ง", subtitle=_subtitle(org_name, year_be, thai_digits),
                         headers=OUTGOING_HEADERS, groups=_grouped(items, thai_digits))


def build_incoming_sheet(rows: List[Dict[str, Any]], *, org_name: str = "", year_be: Optional[int] = None,
                         replies_by_incoming: Optional[Dict[Any, List[Dict[str, Any]]]] = None,
                         thai_digits: bool = True) -> RegisterSheet:
    items = []
    for row in sorted(rows, key=_sort_key):
        replies = (replies_by_incoming or {}).get(row.get("id"), [])
        items.append((parse_timestamp(row.get("received_at")), incoming_cells(row, replies=replies)))
    return RegisterSheet(title="ทะเบียนหนังสือรับ", subtitle=_subtitle(org_name, year_be, thai_digits),
                         headers=INCOMING_HEADERS, groups=_grouped(items, thai_digits))


def _subtitle(org_name: str, year_be: Optional[int], thai: bool) -> str:
    text = _join(org_name.strip(), f"ปี พ.ศ. {year_be}" if year_be else "")
    return _num(text, thai)


# ---------------------------------------------------------------- Excel (.xlsx)
_ILLEGAL_XML = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")


def _x(text: Any) -> str:
    return escape(_ILLEGAL_XML.sub("", "" if text is None else str(text)))


def _col(index: int) -> str:
    name = ""
    index += 1
    while index:
        index, rem = divmod(index - 1, 26)
        name = chr(65 + rem) + name
    return name


# ตัวแทนเลขแถวในขณะประกอบ XML — \x00 ถูกตัดออกจากข้อความผู้ใช้เสมอ (_ILLEGAL_XML) จึงไม่ชนกัน
_ROW = "\x00"


def _cell(ref: str, text: str, style: int) -> str:
    if text == "":
        return f'<c r="{ref}" s="{style}"/>'
    return f'<c r="{ref}" s="{style}" t="inlineStr"><is><t xml:space="preserve">{_x(text)}</t></is></c>'


_FONT = "TH SarabunIT๙"
_STYLES = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
<fonts count="3">
<font><sz val="14"/><name val="{_FONT}"/><family val="2"/></font>
<font><b/><sz val="14"/><name val="{_FONT}"/><family val="2"/></font>
<font><b/><sz val="18"/><name val="{_FONT}"/><family val="2"/></font>
</fonts>
<fills count="4">
<fill><patternFill patternType="none"/></fill>
<fill><patternFill patternType="gray125"/></fill>
<fill><patternFill patternType="solid"><fgColor rgb="FFE5E7EB"/><bgColor indexed="64"/></patternFill></fill>
<fill><patternFill patternType="solid"><fgColor rgb="FFF3F4F6"/><bgColor indexed="64"/></patternFill></fill>
</fills>
<borders count="2">
<border><left/><right/><top/><bottom/><diagonal/></border>
<border><left style="thin"/><right style="thin"/><top style="thin"/><bottom style="thin"/><diagonal/></border>
</borders>
<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>
<cellXfs count="6">
<xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>
<xf numFmtId="0" fontId="2" fillId="0" borderId="0" xfId="0" applyFont="1" applyAlignment="1"><alignment horizontal="center"/></xf>
<xf numFmtId="0" fontId="1" fillId="2" borderId="1" xfId="0" applyFont="1" applyFill="1" applyBorder="1" applyAlignment="1"><alignment horizontal="center" vertical="center" wrapText="1"/></xf>
<xf numFmtId="0" fontId="0" fillId="0" borderId="1" xfId="0" applyBorder="1" applyAlignment="1"><alignment vertical="top" wrapText="1"/></xf>
<xf numFmtId="0" fontId="1" fillId="3" borderId="1" xfId="0" applyFont="1" applyFill="1" applyBorder="1"/>
<xf numFmtId="0" fontId="0" fillId="0" borderId="1" xfId="0" applyBorder="1" applyAlignment="1"><alignment horizontal="center" vertical="top" wrapText="1"/></xf>
</cellXfs>
</styleSheet>"""


def sheet_to_xlsx(sheet: RegisterSheet) -> bytes:
    """ไฟล์ Excel หนึ่งแผ่นงาน: ชื่อทะเบียน, หน่วยงาน/ปี, หัวตาราง (พิมพ์ซ้ำทุกหน้า), กลุ่มตามวันที่"""
    ncol = len(sheet.headers)
    last = _col(ncol - 1)
    rows: List[str] = []
    merges: List[str] = []

    def add_row(cells: List[str], heights: str = "") -> int:
        r = len(rows) + 1
        rows.append(f'<row r="{r}"{heights}>' + "".join(cells).replace(_ROW, str(r)) + "</row>")
        return r

    r = add_row([_cell("A" + _ROW, sheet.title, 1)], ' ht="27" customHeight="1"')
    merges.append(f"A{r}:{last}{r}")
    r = add_row([_cell("A" + _ROW, sheet.subtitle, 1)])
    merges.append(f"A{r}:{last}{r}")
    header_row = add_row([_cell(_col(i) + _ROW, h, 2) for i, h in enumerate(sheet.headers)])
    for group in sheet.groups:
        r = add_row([_cell("A" + _ROW, group.heading, 4)] + [_cell(_col(i) + _ROW, "", 4) for i in range(1, ncol)])
        merges.append(f"A{r}:{last}{r}")
        for cells in group.rows:
            add_row([_cell(_col(i) + _ROW, c, 5 if i == 0 else 3) for i, c in enumerate(cells)])

    cols = "".join(f'<col min="{i + 1}" max="{i + 1}" width="{w * 1.6:.1f}" customWidth="1"/>'
                   for i, w in enumerate(sheet.widths[:ncol]))
    worksheet = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        '<sheetPr><pageSetUpPr fitToPage="1"/></sheetPr>'
        f'<dimension ref="A1:{last}{len(rows)}"/>'
        f'<sheetViews><sheetView workbookViewId="0"><pane ySplit="{header_row}" topLeftCell="A{header_row + 1}" '
        'activePane="bottomLeft" state="frozen"/></sheetView></sheetViews>'
        '<sheetFormatPr defaultRowHeight="21"/>'
        f"<cols>{cols}</cols>"
        f'<sheetData>{"".join(rows)}</sheetData>'
        f'<mergeCells count="{len(merges)}">' + "".join(f'<mergeCell ref="{m}"/>' for m in merges) + "</mergeCells>"
        '<pageMargins left="0.4" right="0.4" top="0.6" bottom="0.6" header="0.3" footer="0.3"/>'
        '<pageSetup paperSize="9" orientation="landscape" fitToWidth="1" fitToHeight="0"/>'
        '<headerFooter><oddFooter>&amp;Cหน้า &amp;P / &amp;N</oddFooter></headerFooter>'
        "</worksheet>"
    )
    name = sheet.title[:31]
    workbook = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        f'<sheets><sheet name="{_x(name)}" sheetId="1" r:id="rId1"/></sheets>'
        f'<definedNames><definedName name="_xlnm.Print_Titles" localSheetId="0">\'{_x(name)}\'!${header_row}:${header_row}'
        "</definedName></definedNames></workbook>"
    )
    files = {
        "[Content_Types].xml": (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
            '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
            '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
            "</Types>"
        ),
        "_rels/.rels": (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
            "</Relationships>"
        ),
        "xl/_rels/workbook.xml.rels": (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>'
            '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>'
            "</Relationships>"
        ),
        "xl/workbook.xml": workbook,
        "xl/styles.xml": _STYLES,
        "xl/worksheets/sheet1.xml": worksheet,
    }
    buf = BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for path, content in files.items():
            zf.writestr(path, content)
    return buf.getvalue()


# ---------------------------------------------------------------- PDF (Typst)
_TYPST = r"""
#let data = json("register.json")
#let thai-digits(s) = s.clusters().map(c => ("0": "๐", "1": "๑", "2": "๒", "3": "๓", "4": "๔",
  "5": "๕", "6": "๖", "7": "๗", "8": "๘", "9": "๙").at(c, default: c)).join()
#set page(paper: "a4", flipped: true, margin: (x: 1.5cm, top: 1.5cm, bottom: 1.8cm),
  footer: context align(center, text(size: 12pt, {
    let p = str(counter(page).get().first())
    "หน้า " + if data.thai { thai-digits(p) } else { p }
  })))
#set text(font: ("TH SarabunPSK", "TH Sarabun New"), size: 14pt, lang: "th")
#set par(leading: 0.45em)
#align(center, text(size: 20pt, weight: "bold", data.title))
#if data.subtitle != "" { align(center, text(size: 16pt, data.subtitle)) }
#v(4pt)
#table(
  columns: data.widths.map(w => w * 1fr),
  stroke: 0.5pt,
  inset: (x: 4pt, y: 3pt),
  align: (col, row) => if col == 0 { center + top } else { left + top },
  table.header(..data.headers.map(h => table.cell(fill: luma(225), align: center + horizon, strong(h)))),
  ..for g in data.groups {
    (table.cell(colspan: data.headers.len(), fill: luma(243), strong(g.heading)),)
    for r in g.rows { r.map(c => [#c]) }
  },
  ..if data.groups.len() == 0 { (table.cell(colspan: data.headers.len(), align: center, "— ไม่มีรายการ —"),) } else { () },
)
"""


def sheet_to_pdf(sheet: RegisterSheet, thai_digits: bool = True) -> bytes:
    """PDF แนวนอน A4 หัวตารางพิมพ์ซ้ำทุกหน้า — คอมไพล์ด้วย Typst (ข้อมูลส่งเป็น JSON ไม่ต้อง escape markup)"""
    from core.typst_exporter import compile_typst_to_pdf

    payload = sheet.model_dump()
    payload["thai"] = thai_digits
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        (work / "register.json").write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        typ = work / "register.typ"
        typ.write_text(_TYPST, encoding="utf-8")
        out = work / "register.pdf"
        ok, message = compile_typst_to_pdf(str(typ), str(out), font_key="it9")
        if not ok:
            raise RuntimeError(message)
        return out.read_bytes()
