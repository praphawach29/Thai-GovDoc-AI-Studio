"""supabase.py — ตัวเรียก Supabase (PostgREST / Storage / Auth) ผ่าน HTTP

เรียกด้วย access token ของผู้ใช้เสมอ (ไม่ใช้ service_role) เพื่อให้ Row Level Security
ในฐานข้อมูลเป็นผู้ตัดสินสิทธิ์จริง — โค้ดฝั่งเซิร์ฟเวอร์พลาดก็ข้ามหน่วยงานไม่ได้
"""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional
from urllib.parse import quote

import httpx

# เทสต์แทนที่ด้วย httpx.MockTransport ได้ (server.supabase.transport_factory = ...)
transport_factory: Optional[Callable[[], httpx.BaseTransport]] = None

# รหัส error ของ Postgres/PostgREST → HTTP status ที่ส่งต่อให้หน้าเว็บ
_PG_STATUS = {
    "42501": 403,   # ไม่มีสิทธิ์ / RLS
    "P0002": 404,   # ไม่พบ
    "22023": 400,   # ค่าที่ส่งมาไม่ถูกต้อง
    "23505": 409,   # ซ้ำ
    "23514": 400,   # ผิดเงื่อนไข check
    "PGRST116": 404,
}


class SupabaseError(Exception):
    def __init__(self, status: int, message: str, code: str = ""):
        super().__init__(message)
        self.status = status
        self.message = message
        self.code = code


def _client(timeout: float = 20.0) -> httpx.Client:
    transport = transport_factory() if transport_factory else None
    return httpx.Client(timeout=timeout, transport=transport)


class SupabaseClient:
    def __init__(self, url: str, publishable_key: str, access_token: str):
        self.url = url.rstrip("/")
        self.key = publishable_key
        self.token = access_token

    # ---------------------------------------------------------------- พื้นฐาน
    def _headers(self, extra: Optional[Dict[str, str]] = None) -> Dict[str, str]:
        headers = {"apikey": self.key, "Authorization": f"Bearer {self.token}"}
        if extra:
            headers.update(extra)
        return headers

    def _request(self, method: str, path: str, **kwargs) -> httpx.Response:
        headers = self._headers(kwargs.pop("headers", None))
        try:
            with _client() as http:
                res = http.request(method, self.url + path, headers=headers, **kwargs)
        except httpx.HTTPError as exc:
            raise SupabaseError(502, "เชื่อมต่อฐานข้อมูลไม่สำเร็จ") from exc
        if res.status_code >= 400:
            raise self._error(res)
        return res

    @staticmethod
    def _error(res: httpx.Response) -> SupabaseError:
        code, message = "", ""
        try:
            body = res.json()
            code = str(body.get("code") or body.get("error") or "")
            message = str(body.get("message") or body.get("msg") or body.get("error_description") or "")
        except ValueError:
            pass
        status = _PG_STATUS.get(code)
        if status is None:
            status = res.status_code if res.status_code in (400, 401, 403, 404, 409, 413) else 502
        if status >= 500 or not message:
            message = "ฐานข้อมูลตอบกลับผิดพลาด"
        return SupabaseError(status, message, code)

    # ---------------------------------------------------------------- PostgREST
    def select(self, table: str, params: Dict[str, str]) -> List[Dict[str, Any]]:
        return self._request("GET", f"/rest/v1/{table}", params=params).json()

    def insert(self, table: str, row: Dict[str, Any]) -> Dict[str, Any]:
        res = self._request(
            "POST", f"/rest/v1/{table}", json=row, headers={"Prefer": "return=representation"}
        )
        return res.json()[0]

    def insert_many(self, table: str, rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """เพิ่มหลายแถวในคำขอเดียว"""
        res = self._request("POST", f"/rest/v1/{table}", json=rows, headers={"Prefer": "return=representation"})
        return res.json()

    def update(self, table: str, filters: Dict[str, str], values: Dict[str, Any]) -> List[Dict[str, Any]]:
        res = self._request(
            "PATCH", f"/rest/v1/{table}", params=filters, json=values,
            headers={"Prefer": "return=representation"},
        )
        return res.json()

    def rpc(self, function: str, params: Dict[str, Any]) -> Any:
        return self._request("POST", f"/rest/v1/rpc/{function}", json=params).json()

    # ---------------------------------------------------------------- Storage
    def signed_upload_url(self, bucket: str, path: str) -> str:
        """URL สำหรับให้เบราว์เซอร์ PUT ไฟล์ตรงเข้า Storage (ไม่ผ่าน Vercel)"""
        res = self._request("POST", f"/storage/v1/object/upload/sign/{bucket}/{quote(path)}")
        signed = res.json().get("url", "")
        if not signed:
            raise SupabaseError(502, "ขอ URL อัปโหลดไม่สำเร็จ")
        return f"{self.url}/storage/v1{signed}"

    def upload(self, bucket: str, path: str, data: bytes, content_type: str) -> None:
        """อัปโหลดจากเซิร์ฟเวอร์ (ใช้กับไฟล์เล็กที่ส่งมาแบบ multipart)"""
        self._request(
            "POST", f"/storage/v1/object/{bucket}/{quote(path)}", content=data,
            headers={"Content-Type": content_type or "application/octet-stream", "x-upsert": "false"},
        )

    def signed_download_url(self, bucket: str, path: str, filename: str = "", expires_in: int = 300) -> str:
        """URL ชั่วคราวให้เบราว์เซอร์ดาวน์โหลดตรงจาก Storage (ไฟล์ใหญ่ได้ ไม่ผ่าน Vercel)"""
        res = self._request("POST", f"/storage/v1/object/sign/{bucket}/{quote(path)}", json={"expiresIn": expires_in})
        signed = res.json().get("signedURL", "")
        if not signed:
            raise SupabaseError(502, "ขอ URL ดาวน์โหลดไม่สำเร็จ")
        url = f"{self.url}/storage/v1{signed}"
        if filename:
            url += ("&" if "?" in url else "?") + "download=" + quote(filename)
        return url

    def remove(self, bucket: str, path: str) -> None:
        self._request("DELETE", f"/storage/v1/object/{bucket}/{quote(path)}")

    def download(self, bucket: str, path: str) -> bytes:
        return self._request("GET", f"/storage/v1/object/authenticated/{bucket}/{quote(path)}").content

    # ---------------------------------------------------------------- Auth
    def get_user(self) -> Dict[str, Any]:
        return self._request("GET", "/auth/v1/user").json()
