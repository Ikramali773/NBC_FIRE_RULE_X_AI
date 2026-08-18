# backend/plan_extractor/ocr_preprocessor.py
# OCR preprocessing (scope §7): grayscale, deskew, denoise, contrast, and
# optional thresholding — applied to a DERIVED copy of the rasterized page
# image. The original page image is never modified; only the OCR-bound
# copy is touched, so the raw rasterized page stays available untouched
# for anything else (display, re-processing with a different profile).

from __future__ import annotations

import numpy as np
from PIL import Image, ImageOps


def _to_gray_array(image: Image.Image) -> np.ndarray:
    return np.array(image.convert("L"))


def deskew(gray_arr: np.ndarray) -> np.ndarray:
    """
    Correct small rotation (a few degrees) using minAreaRect over
    thresholded ink content. Deliberately conservative: only corrects
    small skews typical of a scanned/photographed sheet — a drawing that's
    genuinely rotated 45-90 degrees should not be "corrected" into
    something worse by this heuristic.
    """
    import cv2

    _, thresh = cv2.threshold(gray_arr, 0, 255, cv2.THRESH_BINARY_INV | cv2.THRESH_OTSU)
    coords = cv2.findNonZero(thresh)
    if coords is None or len(coords) < 50:
        return gray_arr  # not enough content to reliably deskew

    angle = cv2.minAreaRect(coords)[-1]
    if angle < -45:
        angle = -(90 + angle)
    else:
        angle = -angle

    if abs(angle) < 0.5 or abs(angle) > 15:
        return gray_arr  # negligible skew, or too large to trust this heuristic

    h, w = gray_arr.shape
    matrix = cv2.getRotationMatrix2D((w // 2, h // 2), angle, 1.0)
    return cv2.warpAffine(gray_arr, matrix, (w, h), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE)


def denoise(gray_arr: np.ndarray) -> np.ndarray:
    import cv2
    return cv2.fastNlMeansDenoising(gray_arr, h=10)


def adaptive_threshold(gray_arr: np.ndarray) -> np.ndarray:
    import cv2
    return cv2.adaptiveThreshold(
        gray_arr, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 31, 15,
    )


# Named profiles the OCR retry ladder can try in combination with different
# Tesseract PSM modes — not every profile helps every page, which is why
# this is a menu rather than one fixed pipeline.
PROFILES = {
    "default": {"deskew": True, "denoise": False, "threshold": False},
    "denoised": {"deskew": True, "denoise": True, "threshold": False},
    "thresholded": {"deskew": True, "denoise": True, "threshold": True},
}


def preprocess_for_ocr(image: Image.Image, profile: str = "default") -> Image.Image:
    """Produce a derived image for OCR. Always returns a new PIL Image —
    the caller's original `image` is never mutated."""
    steps = PROFILES.get(profile, PROFILES["default"])

    gray = _to_gray_array(image)
    gray = np.array(ImageOps.autocontrast(Image.fromarray(gray)))

    if steps["deskew"]:
        gray = deskew(gray)
    if steps["denoise"]:
        gray = denoise(gray)
    if steps["threshold"]:
        gray = adaptive_threshold(gray)

    return Image.fromarray(gray)
