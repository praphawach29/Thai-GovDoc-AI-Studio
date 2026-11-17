"""จุดเข้าสำหรับ Vercel (FastAPI preset หาตัวแปร `app` จากไฟล์นี้)

บนเครื่องตัวเองใช้:  uvicorn server.main:app --port 8600
"""

from server.main import app  # noqa: F401
