"""
main.py — Default entrypoint for Vercel, Uvicorn, and ASGI servers
"""
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from core.api import app

__all__ = ["app"]
