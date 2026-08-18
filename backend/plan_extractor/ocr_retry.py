# backend/plan_extractor/ocr_retry.py
# Quality-scored OCR retry ladder (scope §9): try PSM 3 -> PSM 6 -> PSM 11,
# score each attempt, stop early once a result clears the GOOD threshold,
# otherwise return whichever attempt scored best.
#
# Replaces the previous behavior of always using a single hardcoded
# "--psm 11" call regardless of how well it actually did on a given page.

from __future__ import annotations

import re
from dataclasses import dataclass, field

from plan_extractor.ocr_engine import OCREngine, OCRResult
from plan_extractor.ocr_preprocessor import preprocess_for_ocr
from plan_extractor.page_quality import QUALITY_GOOD_THRESHOLD, quality_label

# PSM 3 (fully automatic layout, the Tesseract default) is tried first since
# it's the cheapest signal of "does this page behave like ordinary prose."
# PSM 6 (a single uniform block) and PSM 11 (sparse text, no reading order)
# follow — PSM 11 is verified (this session) to recover far more real text
# than PSM 3 on architectural sheets, but it is not universally best, hence
# a ladder instead of hardcoding it.
PSM_LADDER: tuple[str, ...] = ("--psm 3", "--psm 6", "--psm 11")

# A "garbage" OCR word is one with no alphanumeric content at all (stray
# punctuation/line-art noise Tesseract mistook for glyphs) — a high ratio of
# these means the engine is hallucinating tokens from noise, not reading text.
_ALNUM_RE = re.compile(r"[0-9A-Za-z]")


@dataclass
class OCRAttempt:
    config: str
    score: float
    result: OCRResult


@dataclass
class OCRRetryResult:
    best: OCRResult
    quality_score: float
    quality_label: str
    winning_config: str
    attempts: list[OCRAttempt] = field(default_factory=list)

    @property
    def attempt_count(self) -> int:
        return len(self.attempts)


def _garbage_token_ratio(result: OCRResult) -> float:
    if not result.words:
        return 1.0
    garbage = sum(1 for w in result.words if not _ALNUM_RE.search(w.text))
    return garbage / len(result.words)


def score_ocr_result(result: OCRResult) -> float:
    """
    Combine mean word confidence (0-100 -> 0-1) with the garbage-token ratio
    into a single 0-1 quality score. An engine error, or a page with no
    recognized words at all, scores 0 — there is nothing to retry towards.
    """
    if not result.success or not result.words:
        return 0.0
    confidence_component = max(0.0, min(result.mean_confidence, 100.0)) / 100.0
    garbage_penalty = _garbage_token_ratio(result)
    return max(0.0, confidence_component * (1.0 - garbage_penalty))


def run_ocr_with_retry(
    image,
    engine: OCREngine,
    preprocess_profile: str = "default",
    psm_ladder: tuple[str, ...] = PSM_LADDER,
) -> OCRRetryResult:
    """
    Preprocess once, then try each PSM config in `psm_ladder` against the
    same preprocessed image, scoring every attempt. Stops as soon as an
    attempt's score clears QUALITY_GOOD_THRESHOLD; otherwise runs the full
    ladder and returns whichever attempt scored highest.
    """
    processed = preprocess_for_ocr(image, profile=preprocess_profile)

    attempts: list[OCRAttempt] = []
    for config in psm_ladder:
        result = engine.process_page(processed, config=config)
        score = score_ocr_result(result)
        attempts.append(OCRAttempt(config=config, score=score, result=result))
        if score >= QUALITY_GOOD_THRESHOLD:
            break

    best = max(attempts, key=lambda a: a.score)
    return OCRRetryResult(
        best=best.result,
        quality_score=best.score,
        quality_label=quality_label(best.score),
        winning_config=best.config,
        attempts=attempts,
    )
