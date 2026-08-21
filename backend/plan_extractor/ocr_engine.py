# backend/plan_extractor/ocr_engine.py
# OCR engine abstraction (scope §8).
#
# Pipeline code calls OCREngine.process_page() only — nothing outside this
# module depends on Tesseract-specific classes, so a future PaddleOCR or
# Azure Document Intelligence engine can be added without touching the rest
# of the pipeline (definition of done: "the OCR engine can be replaced
# without changing the rest of the pipeline").
#
# Gemini's vision call (scanned_pdf_extractor.py) is NOT wrapped behind
# this interface: it returns a richer structured-JSON read (height, floors,
# room labels...) that would lose real value if flattened into plain
# OCRResult text+bboxes. It stays as its own specialized fallback path,
# tried before Tesseract, unchanged. TesseractEngine is what actually
# exercises this abstraction for V1.

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Protocol


@dataclass
class OCRWord:
    text: str
    confidence: float  # 0-100, pytesseract convention (-1 for non-word structural rows, normalized to 0 here)
    bbox: tuple[float, float, float, float]  # (x0, top, x1, bottom), image pixel space


@dataclass
class OCRResult:
    raw_text: str
    words: list[OCRWord] = field(default_factory=list)
    mean_confidence: float = 0.0
    engine_name: str = ""
    config: str = ""
    error: Optional[str] = None

    @property
    def success(self) -> bool:
        return self.error is None


class OCREngine(Protocol):
    name: str

    def process_page(self, image, config: str = "") -> OCRResult:
        ...


class TesseractEngine:
    """
    Wraps pytesseract. Uses image_to_data (not just image_to_string) to
    capture word-level confidence and bounding boxes — the previous code
    only ever captured raw concatenated text, which the ingestion scope's
    definition of done explicitly calls out as required ("OCR output
    contains text, confidence, and bounding boxes").
    """

    name = "tesseract"

    def process_page(self, image, config: str = "") -> OCRResult:
        try:
            import pytesseract
        except ImportError as e:
            return OCRResult(
                raw_text="", engine_name=self.name, config=config,
                error=f"pytesseract not installed: {e}",
            )

        try:
            data = pytesseract.image_to_data(image, config=config, output_type=pytesseract.Output.DICT)
        except Exception as e:
            return OCRResult(
                raw_text="", engine_name=self.name, config=config,
                error=f"Tesseract OCR failed: {e}. Ensure tesseract is installed on the system.",
            )

        words: list[OCRWord] = []
        text_parts: list[str] = []
        confidences: list[float] = []
        n = len(data.get("text", []))

        for i in range(n):
            text = (data["text"][i] or "").strip()
            if not text:
                continue
            try:
                conf = float(data["conf"][i])
            except (TypeError, ValueError):
                conf = -1.0
            conf = max(conf, 0.0)

            x, y, w, h = data["left"][i], data["top"][i], data["width"][i], data["height"][i]
            words.append(OCRWord(text=text, confidence=conf, bbox=(x, y, x + w, y + h)))
            text_parts.append(text)
            if conf > 0:
                confidences.append(conf)

        mean_conf = sum(confidences) / len(confidences) if confidences else 0.0

        return OCRResult(
            raw_text=" ".join(text_parts),
            words=words,
            mean_confidence=mean_conf,
            engine_name=self.name,
            config=config,
        )
