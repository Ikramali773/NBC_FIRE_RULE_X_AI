# backend/plan_extractor/ingestion_log.py
# Structured per-page ingestion logging (scope §14 observability list):
# document id, page, extraction method, OCR engine/config, confidence,
# quality score, retry count, warnings. Plain stdlib logging — no new infra.

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from typing import Optional

logger = logging.getLogger("plan_extractor.ingestion")


@dataclass
class PageIngestionLog:
    document_id: str
    page_index: int
    page_class: str
    extraction_method: str  # "vector" | "ocr" | "mixed"
    ocr_engine: Optional[str] = None
    ocr_config: Optional[str] = None
    ocr_confidence: Optional[float] = None
    ocr_retry_count: int = 0
    table_count: int = 0
    quality_score: Optional[float] = None
    quality_label: Optional[str] = None
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)

    def emit(self) -> None:
        """Log at WARNING when the page's quality is BAD or a warning was
        recorded, INFO otherwise — so BAD/REVIEW pages are greppable
        without every routine GOOD page also showing up at that level."""
        level = logging.WARNING if (self.quality_label == "BAD" or self.warnings) else logging.INFO
        logger.log(level, json.dumps(self.to_dict()))
