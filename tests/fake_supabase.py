"""fake_supabase.py — Supabase จำลองในหน่วยความจำ สำหรับเทสต์ชั้น server/

จำลองเฉพาะส่วนที่ API เรียก: JWKS + /auth/v1/user, PostgREST (select/insert/update/rpc),
Storage (sign/upload/download) และจดทุก request ไว้ตรวจว่าใช้ token ของผู้ใช้เสมอ
RLS จริงทดสอบแยกที่ supabase/tests/run_local.sh
"""

from __future__ import annotations

import json
import time
import uuid
from typing import Any, Dict, List
from urllib.parse import parse_qs, unquote, urlsplit

import httpx
import jwt
from cryptography.hazmat.primitives.asymmetric import ec

URL = "https://fake-project.supabase.co"
PUBLISHABLE_KEY = "sb_publishable_test_key"
ORG_ID = "11111111-1111-1111-1111-111111111111"
USER_ID = "00000000-0000-0000-0000-00000000000a"
NO_PROFILE_USER = "00000000-0000-0000-0000-00000000000c"


class FakeSupabase:
    def __init__(self):
        self.private_key = ec.generate_private_key(ec.SECP256R1())
        self.kid = "test-key-1"
        self.requests: List[httpx.Request] = []
        self.tables: Dict[str, List[Dict[str, Any]]] = {
            "profiles": [{
                "user_id": USER_ID, "org_id": ORG_ID, "role": "admin", "full_name": "ผู้ทดสอบ",
                "position": "นักวิชาการ",
                "organizations": {"id": ORG_ID, "name": "หน่วยงานทดสอบ", "doc_prefix": "กท ๐๐๐๑/",
                                  "address": None, "use_thai_numerals": True},
            }],
            "documents": [], "document_versions": [], "number_sequences": [],
            "outgoing_register": [], "incoming_register": [], "source_files": [], "legal_references": [],
        }
        self.storage: Dict[str, bytes] = {}
        self.rpc_errors: Dict[str, Dict[str, str]] = {}
        self.legacy_tokens: Dict[str, Dict[str, Any]] = {}

    # ---------------------------------------------------------------- tokens
    def token(self, sub: str = USER_ID, **overrides) -> str:
        now = int(time.time())
        claims = {"sub": sub, "role": "authenticated", "aud": "authenticated",
                  "iss": f"{URL}/auth/v1", "iat": now, "exp": now + 3600, "email": "a@test.local"}
        claims.update(overrides)
        return jwt.encode(claims, self.private_key, algorithm="ES256", headers={"kid": self.kid})

    def jwks(self) -> Dict[str, Any]:
        jwk = jwt.algorithms.ECAlgorithm.to_jwk(self.private_key.public_key(), as_dict=True)
        jwk.update({"kid": self.kid, "alg": "ES256", "use": "sig"})
        return {"keys": [jwk]}

    def legacy_token(self, sub: str = USER_ID, valid: bool = True) -> str:
        tok = jwt.encode({"sub": sub, "role": "authenticated", "jti": uuid.uuid4().hex}, "legacy-secret-that-is-long-enough!", algorithm="HS256")
        if valid:
            self.legacy_tokens[tok] = {"id": sub, "email": "a@test.local", "role": "authenticated"}
        return tok

    # ---------------------------------------------------------------- transport
    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handle)

    def _caller(self, request: httpx.Request) -> str:
        auth = request.headers.get("authorization", "")
        token = auth.partition(" ")[2]
        if token in self.legacy_tokens:
            return self.legacy_tokens[token]["id"]
        return jwt.decode(token, options={"verify_signature": False}).get("sub", "")

    @staticmethod
    def _json(status: int, body: Any) -> httpx.Response:
        return httpx.Response(status, json=body)

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        parts = urlsplit(str(request.url))
        path = unquote(parts.path)
        query = {k: v[0] for k, v in parse_qs(parts.query).items()}

        if path == "/auth/v1/.well-known/jwks.json":
            return self._json(200, self.jwks())
        if path == "/auth/v1/user":
            tok = request.headers.get("authorization", "").partition(" ")[2]
            if tok in self.legacy_tokens:
                return self._json(200, self.legacy_tokens[tok])
            return self._json(401, {"msg": "invalid JWT"})

        if request.headers.get("apikey") != PUBLISHABLE_KEY:
            return self._json(401, {"message": "no apikey"})

        if path.startswith("/storage/v1/"):
            return self._storage(request, path)
        if path.startswith("/rest/v1/rpc/"):
            return self._rpc(request, path.rsplit("/", 1)[1])
        if path.startswith("/rest/v1/"):
            return self._table(request, path.split("/")[3], query)
        return self._json(404, {"message": "not found"})

    # ---------------------------------------------------------------- PostgREST
    def _table(self, request: httpx.Request, table: str, query: Dict[str, str]) -> httpx.Response:
        rows = self.tables[table]
        filters = {k: v[3:] for k, v in query.items() if v.startswith("eq.")}
        if table == "profiles":
            filters = {k: v for k, v in filters.items() if k == "user_id"}
            filters["user_id"] = self._caller(request) if filters.get("user_id") else filters.get("user_id")

        def match(r):
            return all(str(r.get(k)).lower() == v.lower() for k, v in filters.items())

        if request.method == "GET":
            out = [r for r in rows if match(r)]
            if "limit" in query:
                out = out[: int(query["limit"])]
            return self._json(200, out)
        body = json.loads(request.content or b"{}")
        if request.method == "POST":
            row = {"id": str(uuid.uuid4()), "updated_at": "2026-11-15T00:00:00Z", **body}
            rows.append(row)
            return self._json(201, [row])
        if request.method == "PATCH":
            changed = [r for r in rows if match(r)]
            for r in changed:
                r.update(body)
            return self._json(200, changed)
        return self._json(405, {"message": "method"})

    def _rpc(self, request: httpx.Request, name: str) -> httpx.Response:
        if name in self.rpc_errors:
            return self._json(400, self.rpc_errors[name])
        p = json.loads(request.content or b"{}")
        if name == "save_document_version":
            doc = next((d for d in self.tables["documents"] if d["id"] == p["p_document_id"]), None)
            if doc is None:
                return self._json(403, {"code": "42501", "message": "ไม่พบเอกสารนี้ในหน่วยงาน"})
            doc["current_version"] = doc.get("current_version", 0) + 1
            self.tables["document_versions"].append({
                "document_id": doc["id"], "version_no": doc["current_version"], "content": p["p_content"],
                "note": p.get("p_note"), "edit_instruction": p.get("p_edit_instruction"),
            })
            return self._json(200, doc["current_version"])
        if name == "reserve_outgoing_number":
            n = len([r for r in self.tables["outgoing_register"]]) + 1
            row = {"id": n, "reg_no": n, "doc_number": p["p_prefix"] + str(n), "status": "reserved",
                   "subject": p["p_subject"], "document_id": p.get("p_document_id")}
            self.tables["outgoing_register"].append(row)
            return self._json(200, row)
        if name in ("mark_outgoing_issued", "cancel_outgoing_number"):
            row = next(r for r in self.tables["outgoing_register"] if r["id"] == p["p_id"])
            row["status"] = "issued" if name == "mark_outgoing_issued" else "cancelled"
            return self._json(200, row)
        if name == "register_incoming":
            n = len(self.tables["incoming_register"]) + 1
            row = {"id": n, "reg_no": n, "subject": p["p_subject"]}
            self.tables["incoming_register"].append(row)
            return self._json(200, row)
        return self._json(404, {"message": f"no function {name}"})

    # ---------------------------------------------------------------- Storage
    def _storage(self, request: httpx.Request, path: str) -> httpx.Response:
        if path.startswith("/storage/v1/object/upload/sign/"):
            obj = path[len("/storage/v1/object/upload/sign/"):]
            return self._json(200, {"url": f"/object/upload/sign/{obj}?token=signed-token"})
        if path.startswith("/storage/v1/object/authenticated/"):
            obj = path[len("/storage/v1/object/authenticated/"):]
            if obj not in self.storage:
                return self._json(404, {"error": "not_found", "message": "Object not found"})
            return httpx.Response(200, content=self.storage[obj])
        if request.method == "POST" and path.startswith("/storage/v1/object/"):
            self.storage[path[len("/storage/v1/object/"):]] = request.content
            return self._json(200, {"Key": path})
        return self._json(404, {"message": "not found"})
