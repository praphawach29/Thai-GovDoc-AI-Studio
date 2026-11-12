#!/usr/bin/env python3
"""
sanitize_har.py — ลบข้อมูลรับรองและข้อมูลอ่อนไหวออกจากไฟล์ HAR ก่อนนำไปวิเคราะห์/แชร์

ใช้เมื่อจับ HAR จาก Chrome DevTools แล้วต้องการส่งให้ทีมวิเคราะห์โดยไม่หลุด
cookie, bearer token, API key หรือรหัส session

ตัวอย่าง:
    python scripts/sanitize_har.py uploads/ekkasarn.har
    python scripts/sanitize_har.py uploads/ekkasarn.har -o uploads/ekkasarn.sanitized.har
    python scripts/sanitize_har.py uploads/ekkasarn.har --redact-document
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any, Dict, List
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

SENSITIVE_HEADERS = {
    "cookie",
    "set-cookie",
    "authorization",
    "proxy-authorization",
    "x-api-key",
    "x-supabase-auth",
    "apikey",
    "x-csrf-token",
    "x-xsrf-token",
}

SENSITIVE_QUERY_KEYS = re.compile(
    r"(token|secret|password|passwd|api[_-]?key|authorization|cookie|csrf|session|"
    r"access[_-]?token|refresh[_-]?token|id[_-]?token|code|state|sig|signature)",
    re.IGNORECASE,
)

SENSITIVE_BODY_KEYS = re.compile(
    r"(token|secret|password|passwd|api[_-]?key|authorization|cookie|csrf|"
    r"access[_-]?token|refresh[_-]?token|id[_-]?token)",
    re.IGNORECASE,
)

# ค่าที่เป็นข้อมูลส่วนบุคคล — ปกปิดเมื่อใช้ --redact-document
PII_KEYS = re.compile(r"(email|phone|tel|mobile|citizen|national[_-]?id|address)", re.IGNORECASE)


def _fingerprint(value: str) -> str:
    """แทนค่าแบบคงที่ต่อค่าเดิม เพื่อให้ group request ที่ใช้ session เดียวกันได้"""
    digest = hashlib.sha256(value.encode("utf-8", "replace")).hexdigest()[:10]
    return f"[REDACTED:{digest}]"


def _sanitize_headers(headers: List[Dict[str, str]]) -> List[Dict[str, str]]:
    cleaned = []
    for header in headers or []:
        name = str(header.get("name", ""))
        if name.lower() in SENSITIVE_HEADERS:
            cleaned.append({"name": name, "value": "[REDACTED]"})
        else:
            cleaned.append(header)
    return cleaned


def _sanitize_query(query: List[Dict[str, str]]) -> List[Dict[str, str]]:
    cleaned = []
    for item in query or []:
        name = str(item.get("name", ""))
        value = str(item.get("value", ""))
        if SENSITIVE_QUERY_KEYS.search(name) and value:
            cleaned.append({"name": name, "value": _fingerprint(value)})
        else:
            cleaned.append(item)
    return cleaned


def _sanitize_url(url: str) -> str:
    if not url:
        return url
    parts = urlsplit(url)
    if not parts.query:
        return url
    pairs = parse_qsl(parts.query, keep_blank_values=True)
    redacted = [
        (key, _fingerprint(value) if SENSITIVE_QUERY_KEYS.search(key) and value else value)
        for key, value in pairs
    ]
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(redacted), parts.fragment))


def _redact_json(value: Any, redact_document: bool) -> Any:
    if isinstance(value, dict):
        result = {}
        for key, item in value.items():
            if SENSITIVE_BODY_KEYS.search(str(key)) or (redact_document and PII_KEYS.search(str(key))):
                result[key] = "[REDACTED]"
            else:
                result[key] = _redact_json(item, redact_document)
        return result
    if isinstance(value, list):
        return [_redact_json(item, redact_document) for item in value]
    if redact_document and isinstance(value, str) and len(value) > 80:
        return f"[REDACTED_TEXT:{len(value)} chars]"
    return value


def _sanitize_body(body: Dict[str, Any], redact_document: bool) -> Dict[str, Any]:
    if not body:
        return body

    mime = str(body.get("mimeType", ""))
    text = body.get("text")
    if isinstance(text, str) and "json" in mime:
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            return body
        body = dict(body)
        body["text"] = json.dumps(_redact_json(parsed, redact_document), ensure_ascii=False)

    params = body.get("params")
    if isinstance(params, list):
        body = dict(body)
        body["params"] = [
            {**item, "value": "[REDACTED]"}
            if SENSITIVE_BODY_KEYS.search(str(item.get("name", "")))
            else item
            for item in params
        ]
    return body


def sanitize(har: Dict[str, Any], redact_document: bool = False) -> Dict[str, Any]:
    entries = har.get("log", {}).get("entries", [])
    for entry in entries:
        request = entry.get("request", {})
        response = entry.get("response", {})

        request["headers"] = _sanitize_headers(request.get("headers", []))
        response["headers"] = _sanitize_headers(response.get("headers", []))
        request["url"] = _sanitize_url(str(request.get("url", "")))
        request["queryString"] = _sanitize_query(request.get("queryString", []))
        request["cookies"] = []
        response["cookies"] = []

        if "postData" in request:
            request["postData"] = _sanitize_body(request["postData"], redact_document)
        if "content" in response:
            response["content"] = _sanitize_body(response["content"], redact_document)

    return har


def main() -> None:
    parser = argparse.ArgumentParser(description="ลบข้อมูลรับรองออกจากไฟล์ HAR")
    parser.add_argument("input", type=Path, help="ไฟล์ .har ต้นฉบับ")
    parser.add_argument("-o", "--output", type=Path, help="ไฟล์ปลายทาง (ค่าเริ่มต้น: *.sanitized.har)")
    parser.add_argument(
        "--redact-document",
        action="store_true",
        help="ปิดเนื้อหาเอกสาร/ข้อมูลส่วนบุคคลด้วย (เหมาะเมื่อจะส่งออกนอกเครื่อง)",
    )
    args = parser.parse_args()

    output = args.output or args.input.with_name(args.input.stem + ".sanitized.har")
    data = json.loads(args.input.read_text(encoding="utf-8"))
    sanitized = sanitize(data, redact_document=args.redact_document)
    output.write_text(json.dumps(sanitized, ensure_ascii=False, indent=2), encoding="utf-8")

    entries = len(sanitized.get("log", {}).get("entries", []))
    print(f"sanitized {entries} requests -> {output}")


if __name__ == "__main__":
    main()
