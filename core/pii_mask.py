"""pii_mask.py — ปิดข้อมูลส่วนบุคคลก่อนส่งข้อความให้ AI ภายนอก แล้วใส่ค่าจริงกลับในคำตอบ

ชื่อบุคคล เลขประจำตัวประชาชน โทรศัพท์ อีเมล เลขบัญชี และบ้านเลขที่ ถูกแทนด้วยรหัส เช่น [ชื่อ_1]
ค่าเดียวกันได้รหัสเดิมตลอดเอกสาร AI จึงยังร่างได้ถูกว่าใครทำอะไร แต่ไม่เห็นค่าจริง
ไม่ปิดชื่อหน่วยงาน ตำแหน่ง วันที่ จำนวนเงิน เลขที่หนังสือ (AI ต้องใช้ร่าง และ fact_check ใช้ตรวจกับต้นเรื่อง)

ดู skills/thai-govdoc-pdpa/SKILL.md
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Dict, Tuple

_D = "[0-9๐-๙]"
_THAI_DIGITS = str.maketrans("๐๑๒๓๔๕๖๗๘๙", "0123456789")

# ชนิด → (ป้ายในรหัส, ชื่อที่แสดงผู้ใช้, placeholder เมื่อ AI แต่งรหัสที่ไม่มีจริง)
KINDS: Dict[str, Tuple[str, str]] = {
    "ชื่อ": ("ชื่อ", "[✏️ ระบุชื่อ]"),
    "เลขบัตร": ("เลขประจำตัวประชาชน", "[✏️ ระบุเลขประจำตัวประชาชน]"),
    "โทร": ("โทรศัพท์", "[✏️ ระบุหมายเลขโทรศัพท์]"),
    "อีเมล": ("อีเมล", "[✏️ ระบุอีเมล]"),
    "บัญชี": ("เลขบัญชี", "[✏️ ระบุเลขบัญชี]"),
    "ที่อยู่": ("ที่อยู่", "[✏️ ระบุที่อยู่]"),
}

# คำนำหน้าชื่อ — ยาวก่อนสั้น (นางสาว ก่อน นาง)
_TITLES = (
    "นางสาว", "เด็กชาย", "เด็กหญิง", "ว่าที่ร้อยตรี", "ว่าที่ร้อยโท", "ว่าที่ร้อยเอก", "ว่าที่ร.ต.", "ว่าที่ ร.ต.",
    "พลตำรวจเอก", "พลตำรวจโท", "พลตำรวจตรี", "พันตำรวจเอก", "พันตำรวจโท", "พันตำรวจตรี",
    "ร้อยตำรวจเอก", "ร้อยตำรวจโท", "ร้อยตำรวจตรี", "พลเอก", "พลโท", "พลตรี", "พันเอก", "พันโท", "พันตรี",
    "ร้อยเอก", "ร้อยโท", "ร้อยตรี", "จ่าสิบเอก", "จ่าสิบโท", "จ่าสิบตรี", "สิบเอก", "สิบโท", "สิบตรี",
    "พล.ต.อ.", "พล.ต.ท.", "พล.ต.ต.", "พ.ต.อ.", "พ.ต.ท.", "พ.ต.ต.", "ร.ต.อ.", "ร.ต.ท.", "ร.ต.ต.",
    "พล.อ.", "พล.ท.", "พล.ต.", "พ.อ.", "พ.ท.", "พ.ต.", "ร.อ.", "ร.ท.", "ร.ต.", "จ.ส.อ.", "จ.ส.ท.", "จ.ส.ต.",
    "ส.อ.", "ส.ท.", "ส.ต.", "ด.ช.", "ด.ญ.", "น.ส.", "ศ.ดร.", "รศ.ดร.", "ผศ.ดร.", "ดร.", "ศ.", "รศ.", "ผศ.",
    "นพ.", "พญ.", "ทพ.", "ทพญ.", "นายแพทย์", "แพทย์หญิง", "ทันตแพทย์หญิง", "ทันตแพทย์",
    "นาง", "นาย",
)
# คำที่ขึ้นต้นด้วย นาย/นาง แต่ไม่ใช่ชื่อคน
_NOT_AFTER_NAI = ("ก", "ทะเบียน", "อำเภอ", "ช่าง", "ตำรวจ", "ทหาร", "งาน", "จ้าง", "หน้า", "ด่าน", "ประตู",
                  "สนาม", "ท้าย", "ร้อย", "พัน", "พล", "เรือ", "สิบ", "ตรวจ", "สัตวแพทย์", "ประกัน", "ทุน", "ห้าง")
_NOT_AFTER_NANG = ("พยาบาล", "งาม", "ฟ้า", "สนม", "กำนัล", "ใน", "เอก")
# คำที่ไม่ใช่นามสกุล (ชื่อตามด้วยกริยา/ตำแหน่ง)
_NOT_SURNAME = ("ได้", "ขอ", "จะ", "เป็น", "มี", "ซึ่ง", "และ", "หรือ", "ที่", "ตำแหน่ง", "ผู้", "ไป", "มา", "เพื่อ",
                "ยื่น", "แจ้ง", "กับ", "โดย", "ใน", "จาก", "ถึง", "เรียน", "ให้", "ไม่", "ยัง", "ก็",
                "อายุ", "สังกัด", "เลข", "โทร", "อยู่", "หัวหน้า", "เจ้าหน้าที่", "ข้าราชการ",
                "พนักงาน", "ลูกจ้าง", "ปลัด", "รอง", "อธิบดี", "ประธาน", "กรรมการ", "เลขานุการ", "ประสงค์")
# คำที่สั้นมาก (มี มา ไป ทำ ฯลฯ) ไม่อยู่ในรายการ เพราะเป็นต้นนามสกุลได้ — ยอมให้กินคำถัดไปดีกว่าปล่อยนามสกุลรั่ว


def _title_rx() -> str:
    parts = []
    for t in _TITLES:
        esc = re.escape(t).replace(r"\ ", r"\s*")
        if "." in t:                      # ตัวย่อ เช่น ร.ต. ต้องไม่อยู่กลางตัวย่ออื่น
            esc = r"(?<![ก-ฮ.])" + esc
        if t == "นาย":
            esc += "(?!" + "|".join(_NOT_AFTER_NAI) + ")"
        elif t == "นาง":
            esc += "(?!" + "|".join(_NOT_AFTER_NANG) + ")"
        parts.append(esc)
    return "|".join(parts)


_WORD = r"[ก-ฮเ-ไ][ก-ฺเ-ํ]*"         # คำไทย ขึ้นต้นด้วยพยัญชนะหรือสระหน้า (เ แ โ ใ ไ) ไม่รวมเลขไทย
_SP = r"[ \t]"                      # ช่องว่างในบรรทัดเดียว (ชื่อไม่ข้ามบรรทัด)
_NAME_RX = re.compile(
    rf"(?P<title>{_title_rx()}){_SP}*(?P<first>{_WORD})(?:{_SP}+(?!(?:{'|'.join(_NOT_SURNAME)}))(?P<last>{_WORD}))?"
)
# ชื่อในวงเล็บใต้ลายมือชื่อ ไม่มีคำนำหน้า เช่น "(สมชาย ใจดี)"
_SIGNED_RX = re.compile(rf"\({_SP}*(?P<name>{_WORD}{_SP}+{_WORD}){_SP}*\)")
_SEP = r"[-\x20]?"                  # ขีดหรือเว้นวรรค (ไม่ข้ามบรรทัด)
_ID_RX = re.compile(rf"(?<![0-9๐-๙]){_D}(?:{_SEP}{_D}){{12}}(?![0-9๐-๙])")
_PHONE_RX = re.compile(rf"(?<![0-9๐-๙+])(?:\+66|[0๐])(?:{_SEP}{_D}){{8,9}}(?![0-9๐-๙])")
_EMAIL_RX = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_ACCOUNT_RX = re.compile(rf"(?P<label>บัญชี(?:\s*เลขที่)?{_SP}*:?{_SP}*)(?P<num>{_D}(?:{_SEP}{_D}){{8,13}})")
_ADDRESS_RX = re.compile(
    rf"บ้านเลขที่\s*{_D}+(?:/{_D}+)?(?:\s*(?:หมู่(?:ที่)?|ม\.)\s*{_D}+)?"
)

# รหัสที่ AI ส่งกลับ: ทนต่อเลขไทย ช่องว่าง ขีด — "[ชื่อ_1]" "[ชื่อ ๑]" "[ ชื่อ-1 ]"
_TOKEN_RX = re.compile(r"\[\s*(" + "|".join(KINDS) + r")\s*[_\-\s]?\s*([0-9๐-๙]+)\s*\]")


def _norm(text: str) -> str:
    return re.sub(r"[-\s]", "", text.translate(_THAI_DIGITS))


def _name_key(name: str) -> str:
    """ชื่อเดียวกันไม่ว่าจะมีคำนำหน้าหรือไม่ → รหัสเดียวกัน"""
    m = re.match(rf"(?:{_title_rx()})\s*", name)
    return re.sub(r"\s+", " ", name[m.end():] if m else name).strip()


@dataclass
class PiiVault:
    """ตารางรหัส ↔ ค่าจริงของเอกสารหนึ่งฉบับ (อยู่ในหน่วยความจำของคำขอเท่านั้น ไม่บันทึก)"""
    values: Dict[str, str] = field(default_factory=dict)           # "[ชื่อ_1]" → "นายสมชาย ใจดี"
    _keys: Dict[Tuple[str, str], str] = field(default_factory=dict)
    counts: Counter = field(default_factory=Counter)

    def _token(self, kind: str, value: str, key: str) -> str:
        found = self._keys.get((kind, key))
        if found:
            # เก็บรูปที่ยาวที่สุด (มีคำนำหน้า/นามสกุล) เป็นค่าที่ใส่กลับ
            if len(value) > len(self.values[found]):
                self.values[found] = value
            return found
        self.counts[kind] += 1
        token = f"[{kind}_{self.counts[kind]}]"
        self._keys[(kind, key)] = token
        self.values[token] = value
        return token

    def mask(self, text: str) -> str:
        if not text:
            return text or ""
        text = _EMAIL_RX.sub(lambda m: self._token("อีเมล", m.group(), m.group().lower()), text)
        text = _ID_RX.sub(lambda m: self._token("เลขบัตร", m.group(), _norm(m.group())), text)
        text = _ACCOUNT_RX.sub(
            lambda m: m.group("label") + self._token("บัญชี", m.group("num"), _norm(m.group("num"))), text)
        text = _PHONE_RX.sub(lambda m: self._token("โทร", m.group(), _norm(m.group())), text)
        text = _ADDRESS_RX.sub(lambda m: self._token("ที่อยู่", m.group(), _norm(m.group())), text)

        def name(m: re.Match) -> str:
            value = m.group().strip()
            return self._token("ชื่อ", value, _name_key(value))

        text = _NAME_RX.sub(name, text)
        text = _SIGNED_RX.sub(lambda m: "(" + self._token("ชื่อ", m.group("name"), _name_key(m.group("name"))) + ")",
                              text)
        return text

    def unmask(self, text: str) -> str:
        """ใส่ค่าจริงกลับ; รหัสที่ไม่มีในตาราง (AI แต่งขึ้น) กลายเป็นช่องให้ผู้ใช้กรอก"""
        if not text or "[" not in text:
            return text or ""
        out, pos = [], 0
        for m in _TOKEN_RX.finditer(text):
            kind, num = m.group(1), m.group(2).translate(_THAI_DIGITS)
            value = self.values.get(f"[{kind}_{int(num)}]")
            before = text[pos:m.start()]
            if value is None:
                value = KINDS[kind][1]
            elif kind == "ชื่อ":
                # AI เขียน "นาย[ชื่อ_1]" ทั้งที่ค่าจริงมีคำนำหน้าแล้ว → ตัดคำนำหน้าที่ซ้ำ
                for title in _TITLES:
                    t = title.replace(" ", "")
                    if value.replace(" ", "").startswith(t) and before.rstrip().endswith(t):
                        before = before.rstrip()[: -len(t)]
                        break
            out.append(before)
            out.append(value)
            pos = m.end()
        out.append(text[pos:])
        return "".join(out)

    @property
    def total(self) -> int:
        return sum(self.counts.values())

    def summary(self) -> str:
        """เช่น 'ชื่อ 2 · โทรศัพท์ 1' (ว่าง = ไม่พบข้อมูลที่ต้องปิด)"""
        return " · ".join(f"{KINDS[k][0]} {n}" for k, n in self.counts.items() if n)
