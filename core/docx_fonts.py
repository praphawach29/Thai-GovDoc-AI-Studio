"""
docx_fonts.py — ฝังฟอนต์ TrueType ลงในไฟล์ .docx ตามมาตรฐาน OOXML (obfuscated font)

Word จะแสดงฟอนต์ถูกต้องบนเครื่องที่ไม่ได้ติดตั้งฟอนต์ เมื่อไฟล์มี:
- word/fontTable.xml ระบุ <w:embedRegular>/<w:embedBold>
- word/fonts/*.odttf (ฟอนต์ที่ obfuscate ด้วย fontKey)
- word/_rels/fontTable.xml.rels เชื่อม part
- [Content_Types].xml ประกาศนามสกุล odttf
- word/settings.xml เปิด <w:embedTrueTypeFonts/>

อ้างอิงรูปแบบจาก ECMA-376 (obfuscated font) — ไฟล์ฟอนต์ไทย TH Sarabun อนุญาตให้ฝังได้
"""

from __future__ import annotations

import re
import uuid
import zipfile
from pathlib import Path
from typing import Optional

FONT_FILES = {
    "psk": {
        "family": "TH SarabunPSK",
        "regular": "THSarabunPSK.ttf",
        "bold": "THSarabunPSK-Bold.ttf",
    },
    "sarabun_new": {
        "family": "TH Sarabun New",
        "regular": "THSarabunNew.ttf",
        "bold": "THSarabunNew-Bold.ttf",
    },
}

ODTTF_CONTENT_TYPE = "application/vnd.openxmlformats-officedocument.obfuscatedFont"
FONT_REL_TYPE = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/font"


def _obfuscate(data: bytes, guid: str) -> bytes:
    """XOR 32 ไบต์แรกด้วย GUID 16 ไบต์ (กลับลำดับ) ตามสเปก OOXML"""
    key = bytes.fromhex(guid.strip("{}").replace("-", ""))[::-1]
    buf = bytearray(data)
    for i in range(min(32, len(buf))):
        buf[i] ^= key[i % len(key)]
    return bytes(buf)


def _font_entry(family: str, regular_guid: str, bold_guid: Optional[str]) -> str:
    embeds = f'<w:embedRegular r:id="rIdFont1" w:fontKey="{regular_guid}"/>'
    if bold_guid:
        embeds += f'<w:embedBold r:id="rIdFont2" w:fontKey="{bold_guid}"/>'
    return (
        f'<w:font w:name="{family}">'
        '<w:charset w:val="DE"/>'
        '<w:family w:val="auto"/>'
        '<w:pitch w:val="variable"/>'
        f"{embeds}"
        "</w:font>"
    )


def _update_font_table(xml: str, family: str, entry: str) -> str:
    pattern = re.compile(
        rf'<w:font w:name="{re.escape(family)}">.*?</w:font>', re.DOTALL
    )
    if pattern.search(xml):
        return pattern.sub(entry, xml, count=1)
    return xml.replace("</w:fonts>", entry + "</w:fonts>", 1)


def _update_relationships(xml: str, has_bold: bool) -> str:
    rels = (
        f'<Relationship Id="rIdFont1" Type="{FONT_REL_TYPE}" Target="fonts/font1.odttf"/>'
    )
    if has_bold:
        rels += (
            f'<Relationship Id="rIdFont2" Type="{FONT_REL_TYPE}" Target="fonts/font2.odttf"/>'
        )
    if "<Relationships" not in xml:
        return (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            f"{rels}</Relationships>"
        )
    return xml.replace("</Relationships>", rels + "</Relationships>", 1)


def _update_content_types(xml: str) -> str:
    if 'Extension="odttf"' in xml:
        return xml
    return xml.replace(
        "</Types>",
        f'<Default Extension="odttf" ContentType="{ODTTF_CONTENT_TYPE}"/></Types>',
        1,
    )


def _update_settings(xml: str) -> str:
    if "embedTrueTypeFonts" in xml:
        return xml
    match = re.search(r"<w:settings\b[^>]*>", xml)
    if not match:
        return xml
    insert_at = match.end()
    tags = "<w:embedTrueTypeFonts/><w:saveSubsetFonts/>"
    return xml[:insert_at] + tags + xml[insert_at:]


def resolve_font_paths(font_key: str) -> tuple:
    """คืน (family, regular_path, bold_path) โดย bold เป็น None ได้"""
    spec = FONT_FILES.get(font_key, FONT_FILES["psk"])
    font_dir = Path(__file__).resolve().parent.parent / "assets" / "fonts"
    regular = font_dir / spec["regular"]
    bold = font_dir / spec["bold"]
    return spec["family"], regular, bold if bold.exists() else None


def embed_fonts(docx_path: str | Path, font_key: str = "psk") -> bool:
    """
    ฝังฟอนต์ลงในไฟล์ .docx (แก้ไฟล์เดิม)
    คืน True เมื่อฝังสำเร็จ, False เมื่อไม่พบไฟล์ฟอนต์
    """
    docx_path = Path(docx_path)
    family, regular_path, bold_path = resolve_font_paths(font_key)
    if not regular_path.exists():
        return False

    regular_guid = "{" + str(uuid.uuid4()).upper() + "}"
    bold_guid = "{" + str(uuid.uuid4()).upper() + "}" if bold_path else None

    with zipfile.ZipFile(docx_path, "r") as zin:
        items = [(info, zin.read(info.filename)) for info in zin.infolist()]

    output = {}
    for info, data in items:
        name = info.filename
        if name == "[Content_Types].xml":
            data = _update_content_types(data.decode("utf-8")).encode("utf-8")
        elif name == "word/fontTable.xml":
            entry = _font_entry(family, regular_guid, bold_guid)
            data = _update_font_table(data.decode("utf-8"), family, entry).encode("utf-8")
        elif name == "word/settings.xml":
            data = _update_settings(data.decode("utf-8")).encode("utf-8")
        output[name] = data

    rels_name = "word/_rels/fontTable.xml.rels"
    rels_xml = output.get(rels_name, "").decode("utf-8") if rels_name in output else ""
    output[rels_name] = _update_relationships(rels_xml, bool(bold_path)).encode("utf-8")

    output["word/fonts/font1.odttf"] = _obfuscate(regular_path.read_bytes(), regular_guid)
    if bold_path:
        output["word/fonts/font2.odttf"] = _obfuscate(
            bold_path.read_bytes(), bold_guid
        )

    with zipfile.ZipFile(docx_path, "w", zipfile.ZIP_DEFLATED) as zout:
        for name, data in output.items():
            zout.writestr(name, data)
    return True
