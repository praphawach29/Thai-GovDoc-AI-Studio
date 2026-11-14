"""auth.py — ตรวจการล็อกอิน (Supabase Auth) ของทุก request

โหมด Supabase (ตั้ง SUPABASE_URL + SUPABASE_PUBLISHABLE_KEY):
  ทุก API ต้องมี  Authorization: Bearer <access token>  ที่ Supabase ออกให้
  ตรวจลายเซ็นด้วยกุญแจสาธารณะของโปรเจกต์ (JWKS); ถ้าโปรเจกต์ยังใช้กุญแจแบบ HS256
  (legacy) จะถาม Supabase ตรงว่า token ใช้ได้ไหม
โหมดเครื่องเดียว: ไม่ตรวจ (ใช้บนเครื่องตัวเอง)
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Dict, Optional

import httpx
import jwt
from fastapi import Depends, HTTPException, Request

from server import supabase as sb
from server.settings import Settings, get_settings, supabase_enabled

_JWKS_TTL_SECONDS = 600
_jwks_cache: Dict[str, tuple] = {}   # url -> (fetched_at, PyJWKSet)
_ASYMMETRIC = {"ES256", "RS256", "EdDSA"}


@dataclass(frozen=True)
class CurrentUser:
    id: str
    email: str
    token: str


@dataclass(frozen=True)
class Profile:
    user_id: str
    org_id: str
    role: str
    full_name: str
    position: str
    org: Dict[str, Any]


def _unauthorized(detail: str = "กรุณาเข้าสู่ระบบ") -> HTTPException:
    return HTTPException(status_code=401, detail=detail, headers={"WWW-Authenticate": "Bearer"})


def _jwks(settings: Settings, refresh: bool = False) -> jwt.PyJWKSet:
    url = f"{settings.supabase_url}/auth/v1/.well-known/jwks.json"
    cached = _jwks_cache.get(url)
    if cached and not refresh and time.time() - cached[0] < _JWKS_TTL_SECONDS:
        return cached[1]
    try:
        with sb._client(timeout=10) as http:
            res = http.get(url, headers={"apikey": settings.supabase_publishable_key})
        res.raise_for_status()
        keyset = jwt.PyJWKSet.from_dict(res.json())
    except (httpx.HTTPError, jwt.PyJWKSetError, ValueError) as exc:
        raise HTTPException(status_code=503, detail="ตรวจสอบการเข้าสู่ระบบไม่ได้ชั่วคราว") from exc
    _jwks_cache[url] = (time.time(), keyset)
    return keyset


def _verify_with_jwks(token: str, header: Dict[str, Any], settings: Settings) -> Dict[str, Any]:
    kid = header.get("kid")
    keyset = _jwks(settings)
    key = next((k for k in keyset.keys if k.key_id == kid), None)
    if key is None:   # หมุนกุญแจใหม่: โหลด JWKS ใหม่หนึ่งครั้ง
        keyset = _jwks(settings, refresh=True)
        key = next((k for k in keyset.keys if k.key_id == kid), None)
    if key is None:
        raise _unauthorized("token ไม่ถูกต้อง")
    try:
        return jwt.decode(
            token,
            key.key,
            algorithms=[header["alg"]],
            audience="authenticated",
            issuer=f"{settings.supabase_url}/auth/v1",
            leeway=30,
            options={"require": ["exp", "sub"]},
        )
    except jwt.ExpiredSignatureError:
        raise _unauthorized("หมดเวลาเข้าสู่ระบบ กรุณาเข้าสู่ระบบใหม่")
    except jwt.InvalidTokenError:
        raise _unauthorized("token ไม่ถูกต้อง")


def _verify_with_auth_server(token: str, settings: Settings) -> Dict[str, Any]:
    client = sb.SupabaseClient(settings.supabase_url, settings.supabase_publishable_key, token)
    try:
        user = client.get_user()
    except sb.SupabaseError as exc:
        if exc.status in (401, 403):
            raise _unauthorized("token ไม่ถูกต้องหรือหมดอายุ")
        raise HTTPException(status_code=503, detail="ตรวจสอบการเข้าสู่ระบบไม่ได้ชั่วคราว")
    return {"sub": user.get("id"), "email": user.get("email", ""), "role": user.get("role")}


def verify_token(token: str, settings: Settings) -> CurrentUser:
    try:
        header = jwt.get_unverified_header(token)
    except jwt.InvalidTokenError:
        raise _unauthorized("token ไม่ถูกต้อง")
    if header.get("alg") in _ASYMMETRIC:
        claims = _verify_with_jwks(token, header, settings)
    else:
        claims = _verify_with_auth_server(token, settings)
    if claims.get("role") not in (None, "authenticated") or not claims.get("sub"):
        raise _unauthorized("token นี้ไม่ใช่ของผู้ใช้ที่เข้าสู่ระบบ")
    return CurrentUser(id=str(claims["sub"]), email=str(claims.get("email") or ""), token=token)


def get_current_user(request: Request, settings: Settings = Depends(get_settings)) -> Optional[CurrentUser]:
    """ผู้ใช้ที่ล็อกอิน (โหมด Supabase) หรือ None (โหมดเครื่องเดียว)"""
    if not supabase_enabled(settings):
        return None
    auth = request.headers.get("authorization", "")
    scheme, _, token = auth.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise _unauthorized()
    return verify_token(token.strip(), settings)


def require_supabase_user(
    user: Optional[CurrentUser] = Depends(get_current_user),
) -> CurrentUser:
    """สำหรับ endpoint ที่มีเฉพาะในโหมด Supabase (เช่น เอกสารที่เก็บบนเซิร์ฟเวอร์)"""
    if user is None:
        raise HTTPException(status_code=404, detail="ใช้ได้เมื่อเชื่อมต่อ Supabase เท่านั้น")
    return user


def get_supabase(
    user: CurrentUser = Depends(require_supabase_user),
    settings: Settings = Depends(get_settings),
) -> sb.SupabaseClient:
    return sb.SupabaseClient(settings.supabase_url, settings.supabase_publishable_key, user.token)


def get_profile(
    user: CurrentUser = Depends(require_supabase_user),
    client: sb.SupabaseClient = Depends(get_supabase),
) -> Profile:
    """โปรไฟล์ + หน่วยงานของผู้ใช้ (อ่านผ่าน RLS)"""
    rows = client.select(
        "profiles",
        {
            "select": "user_id,org_id,role,full_name,position,"
                      "organizations(id,name,doc_prefix,address,use_thai_numerals)",
            "user_id": f"eq.{user.id}",
        },
    )
    if not rows:
        raise HTTPException(status_code=403, detail="บัญชีนี้ยังไม่ได้ผูกกับหน่วยงาน — ติดต่อผู้ดูแลระบบ")
    row = rows[0]
    return Profile(
        user_id=row["user_id"], org_id=row["org_id"], role=row["role"],
        full_name=row.get("full_name") or "", position=row.get("position") or "",
        org=row.get("organizations") or {},
    )
