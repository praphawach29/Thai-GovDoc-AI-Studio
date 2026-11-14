"""
ocr_preprocessor.py — ระบบเตรียมภาพและประมวลผลเอกสารสแกนราชการ (Preprocessing & OCR)
อ้างอิงแนวทางและเทคนิคจาก copninixh/TH-National-Document-OCR
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import List, Tuple, Optional

from PIL import Image

# OpenCV/numpy ใช้เฉพาะการปรับภาพก่อน OCR บนเครื่อง local (Deskew/Contrast)
# บนคลาวด์ (Vercel) ไม่ติดตั้งเพราะขนาดใหญ่ ~190 MB จึงต้อง import ได้แม้ไม่มี
try:
    import cv2
    import numpy as np
except ImportError:  # pragma: no cover - ขึ้นกับสภาพแวดล้อม
    cv2 = None
    np = None


def opencv_available() -> bool:
    """มี OpenCV ให้ปรับภาพก่อน OCR หรือไม่ (ไม่มี = ส่งภาพต้นฉบับเข้า OCR ตรง)"""
    return cv2 is not None


def deskew_image(image_cv: np.ndarray) -> Tuple[np.ndarray, float]:
    """
    ตรวจสอบและปรับมุมเอียงของเอกสารสแกนราชการให้ตั้งตรง (Deskewing)
    ใช้วิธี Hough Line Transform และ MinAreaRect
    """
    if len(image_cv.shape) == 3:
        gray = cv2.cvtColor(image_cv, cv2.COLOR_BGR2GRAY)
    else:
        gray = image_cv.copy()

    # Invert and threshold
    thresh = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)[1]

    # หาตำแหน่งของพิกเซลข้อความทั้งหมด
    coords = np.column_stack(np.where(thresh > 0))
    if len(coords) < 100:
        return image_cv, 0.0

    # คำนวณองศาความเอียงของข้อความ
    angle = cv2.minAreaRect(coords)[-1]
    if angle < -45:
        angle = -(90 + angle)
    elif angle > 45:
        angle = 90 - angle

    # ปรับหมุนภาพเฉพาะกรณีที่เอียงระหว่าง -15 ถึง 15 องศา
    if abs(angle) > 0.3 and abs(angle) < 15.0:
        (h, w) = image_cv.shape[:2]
        center = (w // 2, h // 2)
        M = cv2.getRotationMatrix2D(center, angle, 1.0)
        rotated = cv2.warpAffine(
            image_cv, M, (w, h),
            flags=cv2.INTER_CUBIC,
            borderMode=cv2.BORDER_REPLICATE
        )
        return rotated, angle

    return image_cv, 0.0


def enhance_document_contrast(image_cv: np.ndarray) -> np.ndarray:
    """
    ปรับปรุง Contrast และลดสัญญาณรบกวนสำหรับเอกสารสแกน/ถ่ายเอกสาร (CLAHE)
    ช่วยให้อ่านตัวหนังสือไทย TH Sarabun ที่มัวหรือบางให้คมชัดขึ้น
    """
    if len(image_cv.shape) == 3:
        gray = cv2.cvtColor(image_cv, cv2.COLOR_BGR2GRAY)
    else:
        gray = image_cv.copy()

    # ปรับ Histogram ด้วย CLAHE (Contrast Limited Adaptive Histogram Equalization)
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    enhanced = clahe.apply(gray)

    # กรองสัญญาณรบกวนขนาดเล็ก (Denoise)
    denoised = cv2.fastNlMeansDenoising(enhanced, None, h=10, templateWindowSize=7, searchWindowSize=21)
    return denoised


def binarize_adaptive(image_cv: np.ndarray) -> np.ndarray:
    """แปลงภาพเป็นขาวดำแบบ Adaptive Thresholding เพื่อแยกตัวอักษรออกจากรอยประทับหรือพื้นหลัง"""
    if len(image_cv.shape) == 3:
        gray = cv2.cvtColor(image_cv, cv2.COLOR_BGR2GRAY)
    else:
        gray = image_cv

    # ใช้ Gaussian Adaptive Threshold
    binary = cv2.adaptiveThreshold(
        gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY, 15, 6
    )
    return binary


def render_pdf_to_images(pdf_path: str, max_pages: int = 3, scale: float = 2.0) -> List[Image.Image]:
    """
    แปลงหน้ากระดาษใน PDF เป็นรูปภาพ PIL Images โดยใช้ pypdfium2
    """
    images = []
    try:
        import pypdfium2 as pdfium
        pdf = pdfium.PdfDocument(pdf_path)
        try:
            num_pages = min(len(pdf), max_pages)
            for i in range(num_pages):
                page = pdf[i]
                # render with high resolution (scale 2.0 = ~150-200 DPI)
                pil_image = page.render(scale=scale).to_pil()
                page.close()
                images.append(pil_image)
        finally:
            pdf.close()
    except Exception as e:
        print(f"Error rendering PDF to images: {e}")
    return images


def check_is_scanned_pdf(pdf_path: str) -> bool:
    """
    ตรวจสอบว่าไฟล์ PDF เป็นไฟล์สแกน (ไม่มีข้อความดิจิทัล มีแต่รูปภาพ) หรือไม่
    """
    try:
        import pdfplumber
        with pdfplumber.open(pdf_path) as pdf:
            total_chars = sum(len(p.extract_text() or "") for p in pdf.pages[:3])
            # หาก 3 หน้าแรกมีตัวอักษรรวมกันน้อยกว่า 50 ตัวอักษร ให้ถือว่าเป็น PDF สแกน
            return total_chars < 50
    except Exception:
        return True
