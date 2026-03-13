"""FinBERT-based sentiment scorer for financial text.

Uses the ``ahmedrachid/FinancialBERT-Sentiment-Analysis`` model from
HuggingFace.  The model is loaded lazily on the first call to avoid slow
imports at module level.
"""

import math
import re
from typing import Any

from app.core.logging import get_logger

logger = get_logger("sentiment.finbert")

# Label-to-sign mapping produced by the FinancialBERT model
_LABEL_SIGN: dict[str, float] = {
    "positive": 1.0,
    "negative": -1.0,
    "neutral": 0.0,
}


def _preprocess(text: str) -> str:
    """Clean raw text before feeding into the model.

    Follows preprocessing recommendations from paper 9:
    * Replace URLs with the ``[URL]`` token.
    * Remove ``#`` characters (keep the tag word).
    * Collapse duplicate punctuation (e.g. ``!!!`` -> ``!``).
    * Strip leading/trailing whitespace.
    """
    # URLs -> [URL]
    text = re.sub(r"https?://\S+", "[URL]", text)
    # Remove '#' but keep the word after it
    text = text.replace("#", "")
    # Collapse repeated punctuation
    text = re.sub(r"([!?.;,])\1+", r"\1", text)
    return text.strip()


class FinBERTScorer:
    """Lazy-loaded FinancialBERT sentiment scorer."""

    MODEL_NAME = "ahmedrachid/FinancialBERT-Sentiment-Analysis"

    def __init__(self) -> None:
        self._pipeline: Any | None = None

    # ------------------------------------------------------------------
    # Lazy initialisation
    # ------------------------------------------------------------------

    def _load_model(self) -> None:
        """Download (if needed) and instantiate the HuggingFace pipeline."""
        if self._pipeline is not None:
            return

        logger.info("finbert_loading_model", model=self.MODEL_NAME)
        from transformers import pipeline  # type: ignore[import-untyped]

        self._pipeline = pipeline(
            "sentiment-analysis",
            model=self.MODEL_NAME,
            tokenizer=self.MODEL_NAME,
            truncation=True,
            max_length=512,
        )
        logger.info("finbert_model_loaded")

    # ------------------------------------------------------------------
    # Scoring
    # ------------------------------------------------------------------

    def score(self, text: str) -> dict:
        """Score a single piece of text.

        Returns
        -------
        dict
            ``sentiment`` -- ``"positive"`` / ``"negative"`` / ``"neutral"``
            ``score``     -- float in ``[-1.0, 1.0]``
            ``confidence`` -- raw model probability ``[0.0, 1.0]``
        """
        self._load_model()
        cleaned = _preprocess(text)
        if not cleaned:
            return {"sentiment": "neutral", "score": 0.0, "confidence": 0.0}

        result = self._pipeline(cleaned)[0]
        label: str = result["label"].lower()
        prob: float = float(result["score"])
        sign = _LABEL_SIGN.get(label, 0.0)

        return {
            "sentiment": label,
            "score": round(sign * prob, 4),
            "confidence": round(prob, 4),
        }

    def score_batch(self, texts: list[str]) -> list[dict]:
        """Score a batch of texts efficiently using the HuggingFace pipeline.

        Returns a list with the same ordering as *texts*.
        """
        self._load_model()
        cleaned = [_preprocess(t) for t in texts]

        # Replace empty strings with a neutral placeholder so the pipeline
        # does not choke.
        safe = [c if c else "no content" for c in cleaned]

        raw_results = self._pipeline(safe, batch_size=32)

        scored: list[dict] = []
        for idx, result in enumerate(raw_results):
            if not cleaned[idx]:
                scored.append({"sentiment": "neutral", "score": 0.0, "confidence": 0.0})
                continue

            label = result["label"].lower()
            prob = float(result["score"])
            sign = _LABEL_SIGN.get(label, 0.0)
            scored.append(
                {
                    "sentiment": label,
                    "score": round(sign * prob, 4),
                    "confidence": round(prob, 4),
                }
            )

        return scored

    # ------------------------------------------------------------------
    # Engagement-weighted scoring
    # ------------------------------------------------------------------

    @staticmethod
    def engagement_weighted_score(
        base_score: float,
        engagement_count: int,
    ) -> float:
        """Apply engagement weighting: ``score * log(1 + engagement)``.

        A Reddit post with 500 upvotes carries more weight than one with 2.
        """
        return round(base_score * math.log(1 + max(engagement_count, 0)), 4)
