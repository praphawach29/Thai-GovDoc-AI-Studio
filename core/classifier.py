"""
classifier.py — จำแนกชนิดหนังสือราชการ 6 ชนิด (แบบที่ 1–11)

อ้างอิงระเบียบสำนักนายกรัฐมนตรีว่าด้วยงานสารบรรณ พ.ศ. ๒๕๒๖ และที่แก้ไขเพิ่มเติม
ใช้กฎคำสำคัญจากต้นเรื่อง + metadata เพื่อเสนอชนิด/แบบ และให้ผู้ใช้ยืนยันก่อนร่าง
"""

from typing import Dict, List, Optional

from pydantic import BaseModel, Field

from core.ai_drafter import DraftingIntent
from core.models import DocType, DocumentKind, SourceDocumentContext


class ClassificationResult(BaseModel):
    kind: DocumentKind
    form_no: int = Field(..., ge=1, le=11)
    confidence: float = Field(..., ge=0.0, le=1.0)
    reasons: List[str] = Field(default_factory=list)
    doc_type: DocType
    intent: DraftingIntent
    supported: bool


KEYWORDS: Dict[DocumentKind, List[str]] = {
    DocumentKind.INTERNAL_MEMO: ["บันทึกข้อความ", "บันทึกภายใน", "เรียน ผู้อำนวยการ", "เรียน ปลัด"],
    DocumentKind.EXTERNAL_LETTER: [
        "หนังสือภายนอก", "ขอความอนุเคราะห์", "ขอเชิญ", "ด้วย", "ตามที่",
        "จึงเรียนมาเพื่อ", "ขอแสดงความนับถือ",
    ],
    DocumentKind.STAMP_LETTER: ["หนังสือประทับตรา", "ประทับตรา", "ตราประทับแทนการลงชื่อ"],
    DocumentKind.DIRECTIVE: ["คำสั่ง", "ระเบียบ", "ข้อบังคับ", "อาศัยอำนาจตาม", "ประกาศใช้"],
    DocumentKind.PUBLIC_RELATIONS: ["ประกาศ", "แถลงการณ์", "ข่าว", "ประชาสัมพันธ์", "แจ้งให้ทราบ"],
    DocumentKind.EVIDENCE: ["หนังสือรับรอง", "รายงานการประชุม", "บันทึกการประชุม", "รับรองว่า", "ผู้จดบันทึก"],
}


def _infer_form(kind: DocumentKind, text: str) -> int:
    if kind == DocumentKind.EXTERNAL_LETTER:
        return 1
    if kind == DocumentKind.INTERNAL_MEMO:
        return 2
    if kind == DocumentKind.STAMP_LETTER:
        return 3
    if kind == DocumentKind.DIRECTIVE:
        if "ระเบียบ" in text:
            return 5
        if "ข้อบังคับ" in text:
            return 6
        return 4
    if kind == DocumentKind.PUBLIC_RELATIONS:
        if "แถลงการณ์" in text:
            return 8
        if "ข่าว" in text:
            return 9
        return 7
    if "รายงานการประชุม" in text or "บันทึกการประชุม" in text:
        return 11
    return 10


def _suggest_intent(kind: DocumentKind) -> DraftingIntent:
    if kind == DocumentKind.INTERNAL_MEMO:
        return DraftingIntent.MEMO_REVIEW
    if kind in {DocumentKind.DIRECTIVE, DocumentKind.PUBLIC_RELATIONS, DocumentKind.EVIDENCE}:
        return DraftingIntent.PROPOSAL
    return DraftingIntent.ACCEPT


def classify_source_document(
    ctx: SourceDocumentContext, forced_kind: Optional[DocumentKind] = None
) -> ClassificationResult:
    """
    จำแนกชนิดหนังสือจากข้อความ/metadata
    forced_kind: ใช้เมื่อผู้ใช้เลือกชนิดเองจาก dropdown (confidence = 1.0)
    """
    text = "\n".join(
        part for part in (ctx.source_subject or "", ctx.raw_text or "") if part
    )

    scores: Dict[DocumentKind, float] = {kind: 0.0 for kind in DocumentKind}
    matches: Dict[DocumentKind, List[str]] = {kind: [] for kind in DocumentKind}
    for kind, keywords in KEYWORDS.items():
        for keyword in keywords:
            if keyword and keyword in text:
                scores[kind] += 1.0
                matches[kind].append(keyword)

    if forced_kind is not None:
        kind = forced_kind
        reasons = ["เลือกชนิดโดยผู้ใช้"]
        confidence = 1.0
    else:
        best_kind = max(scores, key=lambda k: scores[k])
        best_score = scores[best_kind]
        total = sum(scores.values())
        if best_score == 0:
            # ไม่พบคำสำคัญ: ใช้หนังสือภายนอกเป็นค่าตั้งต้นที่ปลอดภัยที่สุด
            kind = DocumentKind.EXTERNAL_LETTER
            confidence = 0.35
            reasons = ["ไม่พบคำสำคัญเฉพาะ จึงตั้งต้นเป็นหนังสือภายนอกให้ผู้ใช้ยืนยัน"]
        else:
            kind = best_kind
            confidence = max(0.4, min(0.95, best_score / max(total, 1.0)))
            reasons = [f"พบคำสำคัญ: {', '.join(matches[kind][:4])}"]
            runner_up = sorted(
                ((k, s) for k, s in scores.items() if k != kind and s > 0),
                key=lambda item: item[1],
                reverse=True,
            )
            if runner_up and runner_up[0][1] == best_score:
                confidence = min(confidence, 0.55)
                reasons.append(f"พบคำสำคัญใกล้เคียงกับ {runner_up[0][0].thai_label()}")

    doc_type = DocType.INTERNAL if kind == DocumentKind.INTERNAL_MEMO else DocType.EXTERNAL
    return ClassificationResult(
        kind=kind,
        form_no=_infer_form(kind, text),
        confidence=confidence,
        reasons=reasons,
        doc_type=doc_type,
        intent=_suggest_intent(kind),
        supported=kind.is_generation_supported(),
    )
