"""main.py — ประกอบแอป FastAPI ของ Thai GovDoc AI Studio

รันบนเครื่อง:  uvicorn server.main:app --port 8600
"""

from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from server.auth import get_current_user
from server.routers import (account, documents, drafting, examples, export, finals, health, legal, legal_import, registry,
                            signers, sources, studio)
from server.settings import get_settings
from server.supabase import SupabaseError


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="Thai GovDoc AI Studio API",
        description="สกัด ยกร่าง ตรวจสอบ และผลิตหนังสือราชการไทยตามระเบียบงานสารบรรณ พ.ศ. ๒๕๒๖",
        version="2.0.0",
    )
    # อนุญาตเฉพาะโดเมนที่กำหนดใน GOVDOC_ALLOWED_ORIGINS — ห้ามใช้ "*" คู่กับ credentials
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.allowed_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "PUT", "PATCH"],
        allow_headers=["Content-Type", "Authorization"],
    )
    # ไม่ต้องล็อกอิน: สถานะระบบ และค่าตั้งที่หน้า login ต้องใช้
    for module in (health, account):
        app.include_router(module.router)
    # ต้องล็อกอินเมื่อเปิดโหมด Supabase (โหมดเครื่องเดียว get_current_user คืน None)
    protected = [Depends(get_current_user)]
    # legal_import ก่อน legal: PATCH /legal/references/verify ต้องไม่ถูกจับเป็น /legal/references/{ref_id}
    for module in (sources, drafting, legal_import, legal, export, registry, studio, documents, finals, examples, signers):
        app.include_router(module.router, dependencies=protected)

    @app.exception_handler(SupabaseError)
    async def _supabase_error(_: Request, exc: SupabaseError):
        return JSONResponse(status_code=exc.status, content={"detail": exc.message})

    app.mount("/studio", StaticFiles(directory=settings.web_dir, html=True), name="studio")
    app.mount("/assets", StaticFiles(directory=settings.assets_dir), name="assets")

    @app.get("/", include_in_schema=False)
    def root_redirect():
        return RedirectResponse(url="/studio/")

    return app


app = create_app()
