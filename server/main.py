"""main.py — ประกอบแอป FastAPI ของ Thai GovDoc AI Studio

รันบนเครื่อง:  uvicorn server.main:app --port 8600
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from server.routers import drafting, export, health, legal, registry, sources, studio
from server.settings import get_settings


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
        allow_methods=["GET", "POST", "PUT"],
        allow_headers=["Content-Type", "Authorization"],
    )
    for module in (health, sources, drafting, legal, export, registry, studio):
        app.include_router(module.router)

    app.mount("/studio", StaticFiles(directory=settings.web_dir, html=True), name="studio")
    app.mount("/assets", StaticFiles(directory=settings.assets_dir), name="assets")

    @app.get("/", include_in_schema=False)
    def root_redirect():
        return RedirectResponse(url="/studio/")

    return app


app = create_app()
