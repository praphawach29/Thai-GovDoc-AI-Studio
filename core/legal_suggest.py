"""legal_suggest.py — เสนอข้อกฎหมายที่เกี่ยวข้องกับเรื่องที่กำลังร่าง จากคลังที่ "ยืนยันแล้ว" เท่านั้น

๑. คัดผู้สมัครด้วยคำที่ตรงกัน (ไม่ใช้ AI) ให้เหลือไม่เกิน ~๓๐ รายการ — คำขอเล็ก ไม่ส่งทั้งคลัง
๒. ให้ AI เลือกไม่เกิน ๕ ข้อ พร้อมเหตุผลสั้น ๆ ตอบเป็นรหัสรายการเท่านั้น (รหัสที่ไม่อยู่ในรายการถูกตัดทิ้ง จึงแต่งกฎหมายเองไม่ได้)
๓. ไม่มี AI / AI ล้มเหลว → ใช้ลำดับจากคำที่ตรงกัน
"""

from __future__ import annotations

import logging
import re
from typing import Callable, Dict, List, Optional, Sequence, Tuple

from pydantic import BaseModel

logger = logging.getLogger("govdoc.ai")

# คำที่พบบ่อยในหนังสือราชการ ไม่ช่วยแยกว่าข้อไหนเกี่ยวข้อง
_STOP = set("""ที่ และ หรือ ของ ใน ให้ ได้ เป็น การ ความ ตาม โดย ซึ่ง จาก กับ แก่ แห่ง นี้ นั้น ไว้ ไป มา จะ ต้อง มี ไม่ แล้ว
เพื่อ ว่า ราย กรณี ดังนี้ ดังกล่าว เรื่อง เรียน กรุงเทพมหานคร สำนัก กอง กลุ่มงาน ระเบียบ ข้อ มาตรา พ.ศ. ปี วันที่ หนังสือ
ผู้ ท่าน ทั้ง ทุก แต่ละ อื่น ใด ใดๆ คน จำนวน บาท ครั้ง ประกอบ อาศัย อำนาจ ฉบับ ใช้ บังคับ""".split())


class LegalPick(BaseModel):
    id: str
    reason: str


class LegalPicks(BaseModel):
    picks: List[LegalPick]


class Suggestion(BaseModel):
    id: str
    reason: str
    by: str            # "ai" | "keyword"


def _words(text: str) -> List[str]:
    from core.thai_segmenter import segment_thai_words   # ตั้งที่เก็บข้อมูล PyThaiNLP ให้ + มีตัวตัดคำสำรอง

    text = re.sub(r"[​“”\"'()\[\]{}:;,.!?…\-–/]", " ", text or "")
    toks = segment_thai_words(text)
    return [t.strip() for t in toks if len(t.strip()) >= 2 and t.strip() not in _STOP and not t.strip().isdigit()]


def _ref_text(ref: dict) -> str:
    return " ".join(str(ref.get(k) or "") for k in ("title", "chapter", "section", "quote"))


def keyword_rank(context: str, refs: Sequence[dict], limit: int = 30) -> List[Tuple[dict, float, List[str]]]:
    """เรียงรายการตามคำที่ตรงกับเรื่อง (คำหายากในคลังได้น้ำหนักมากกว่า)"""
    ctx = set(_words(context))
    if not ctx:
        return []
    ref_words = [set(_words(_ref_text(r))) for r in refs]
    df: Dict[str, int] = {}
    for ws in ref_words:
        for w in ws:
            df[w] = df.get(w, 0) + 1
    n = max(1, len(refs))
    scored = []
    for ref, ws in zip(refs, ref_words):
        common = ctx & ws
        if not common:
            continue
        score = sum(1.0 + (n / df[w]) ** 0.5 for w in common)
        scored.append((ref, score, sorted(common, key=lambda w: -len(w))[:4]))
    scored.sort(key=lambda x: -x[1])
    return scored[:limit]


PICK_SYSTEM = (
    "คุณเป็นนิติกรของหน่วยงานกรุงเทพมหานคร ช่วยเลือกข้อกฎหมาย/ระเบียบที่ต้องอ้างในบันทึกข้อความเสนอผู้บังคับบัญชา "
    "เลือกได้เฉพาะจากรายการที่ให้ (ตอบเป็น id ตามรายการเท่านั้น) ไม่เกิน 5 ข้อ เรียงจากเกี่ยวข้องมากที่สุด "
    "เลือกเฉพาะข้อที่เป็นฐานอำนาจหรือหลักเกณฑ์ของเรื่องนี้จริง ถ้าไม่มีข้อใดเกี่ยวข้องให้ตอบรายการว่าง "
    "reason เขียนภาษาไทยสั้น ๆ ไม่เกิน 1 ประโยค ว่าข้อนั้นเกี่ยวกับเรื่องอย่างไร"
)


def build_pick_prompt(context: str, candidates: Sequence[dict]) -> str:
    lines = []
    for r in candidates:
        quote = re.sub(r"\s+", " ", str(r.get("quote") or ""))[:350]
        head = " · ".join(x for x in (r.get("title"), r.get("chapter"), r.get("section")) if x)
        lines.append(f"[{r['id']}] {head}\n    {quote}")
    return f"เรื่องที่กำลังร่าง:\n{context.strip()[:3000]}\n\nรายการข้อกฎหมายในคลัง (ยืนยันแล้ว):\n" + "\n".join(lines)


PickCall = Callable[[str, str], LegalPicks]


def suggest(context: str, refs: Sequence[dict], *, ai: Optional[PickCall] = None, limit: int = 5) -> List[Suggestion]:
    """ข้อที่เกี่ยวข้อง (ไม่เกิน limit) จากรายการที่ยืนยันแล้ว"""
    verified = [r for r in refs if r.get("verified") and r.get("id")]
    ranked = keyword_rank(context, verified)
    if not ranked:
        return []
    candidates = [r for r, _, _ in ranked]
    if ai is not None:
        try:
            picks = ai(PICK_SYSTEM, build_pick_prompt(context, candidates))
            allowed = {str(r["id"]) for r in candidates}
            out, seen = [], set()
            for p in picks.picks:
                if p.id in allowed and p.id not in seen:
                    seen.add(p.id)
                    out.append(Suggestion(id=p.id, reason=p.reason.strip()[:200] or "AI เห็นว่าเกี่ยวข้อง", by="ai"))
            return out[:limit]
        except Exception as exc:          # AI ล้มเหลว: ใช้ลำดับจากคำที่ตรงกัน
            logger.warning("legal suggest AI failed, using keyword ranking: %s", exc)
    return [Suggestion(id=str(r["id"]), reason="คำที่ตรงกับเรื่อง: " + " ".join(words), by="keyword")
            for r, _, words in ranked[:limit]]
