# --------------------------------------------------------------------------
# Horizon Capital - proprietary source. Do not remove this notice.
# Author: Aaryan Baadkar <aaryanbaadkar71@gmail.com> (github.com/Aaryanxvi)
# Copyright (c) 2026 Aaryan Baadkar. All rights reserved.
# HC-AUTH-AARYAN-BAADKAR-BB1327442273
# ⁠​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​​‌​​​​​​‌​​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌​​​​​​​‌‌‌‌​​​‌‌​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌‌​‌‌‌​​‌‌​​​‌​‌​​​​​​​‌‌​​‌‌‌​‌‌​‌‌​‌​‌‌​​​​‌​‌‌​‌​​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌‌‌‌‌​​​‌​​​​​​‌‌​​‌‌‌​‌‌​‌​​‌​‌‌‌​‌​​​‌‌​‌​​​​‌‌‌​‌​‌​‌‌​​​‌​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌​‌‌‌‌​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌‌‌​​​​‌‌‌​‌‌​​‌‌​‌​​‌⁠
# --------------------------------------------------------------------------
"""LLM-extracted news sentiment scoring (Li, Mei, Zhu 2023; Loughran-McDonald 2011).

Two backends:
  1. Anthropic Claude (preferred) — calls API, uses prompt cache for cost control
  2. Loughran-McDonald dict fallback — deterministic, no API key needed

Returns sentiment in [-1, +1] per (symbol, date) tuple.

Usage:
    scorer = LLMSentimentScorer(api_key=os.getenv("ANTHROPIC_API_KEY"))
    score = scorer.score("NVDA", news_items=["NVDA earnings beat ...", ...])

For backtests where no historical news is on hand, this module also exposes a
deterministic mock that produces *correlated noise* so the v4 pipeline can
demo end-to-end without paying for news API. Real usage: plug in a news feed
(NewsAPI, Polygon, Tiingo).
"""
from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass

# Loughran-McDonald simplified dict (canonical version is ~3500 words; this is
# a high-frequency subset — enough for baseline. Full dict at
# https://sraf.nd.edu/loughranmcdonald-master-dictionary/)
_LM_POS = {
    "advances", "achieve", "achieved", "achievement", "advanced", "advancing",
    "beat", "beats", "beneficial", "benefit", "benefiting", "best", "better",
    "boost", "boosted", "boosts", "breakthrough", "constructive", "creative",
    "delight", "delighted", "deliver", "delivered", "delivers", "discover",
    "discovered", "effective", "efficient", "enabled", "enhance", "enhanced",
    "enhances", "enhancing", "exceed", "exceeded", "exceeding", "exceeds",
    "exceptional", "excited", "expansion", "expand", "expanded", "expanding",
    "expands", "favorable", "favourably", "gain", "gained", "gaining", "gains",
    "good", "great", "greatest", "growth", "growing", "happily", "happy",
    "highest", "improve", "improved", "improvement", "improves", "improving",
    "innovate", "innovated", "innovation", "innovative", "lead", "leadership",
    "leader", "leading", "leads", "outperform", "outperforming",
    "outperforms", "outperformed", "positive", "profit", "profited", "profits",
    "profitable", "progress", "progressed", "progressing", "rebound", "record",
    "stronger", "strongest", "succeed", "succeeded", "success", "successful",
    "successfully", "surge", "surged", "surges", "surging", "transformative",
    "upgrade", "upgraded", "upgrades", "upside", "win", "winning", "wins",
}
_LM_NEG = {
    "abandon", "abandoned", "abandoning", "adverse", "adversely", "alert",
    "allegation", "allegations", "alleged", "bad", "badly", "bankrupt",
    "bankruptcy", "below", "breach", "breached", "breaches", "breaching",
    "breakdown", "burden", "burdened", "burdens", "challenge", "challenged",
    "challenges", "challenging", "claim", "claims", "collapse", "collapsed",
    "collapses", "collapsing", "concern", "concerned", "concerns", "crisis",
    "crash", "crashed", "crashes", "crashing", "criticism", "decline",
    "declined", "declines", "declining", "decreased", "decreases",
    "decreasing", "default", "defaulted", "defaults", "delay", "delayed",
    "delays", "deteriorate", "deteriorated", "deteriorating", "difficult",
    "difficulty", "disappoint", "disappointed", "disappointing", "disaster",
    "downgrade", "downgraded", "downgrades", "downturn", "drag", "drop",
    "dropped", "drops", "exposure", "fail", "failed", "failing", "fails",
    "failure", "failures", "fall", "fallen", "falling", "falls", "fell",
    "fraud", "guilty", "harm", "harmful", "hurt", "hurts", "impair",
    "impaired", "impairment", "impairments", "investigate", "investigation",
    "lag", "lagged", "lagging", "lawsuit", "layoff", "layoffs", "loss",
    "losses", "lost", "miss", "missed", "misses", "missing", "negative",
    "negatively", "panic", "plunge", "plunged", "plunges", "plunging",
    "poor", "problem", "problems", "recession", "reduce", "reduced",
    "reduces", "reducing", "reduction", "regret", "rejected", "risk", "risks",
    "risky", "scrutiny", "setback", "shortage", "shrink", "shrinking", "slow",
    "slowdown", "slowed", "slumping", "struggle", "struggled", "struggling",
    "suffer", "suffered", "suffering", "tumble", "tumbled", "tumbles",
    "underperform", "underperforming", "violate", "violated", "violates",
    "warning", "weak", "weaker", "weakness", "worry", "worried", "worse",
    "worst",
}


def lm_dict_score(text: str) -> float:
    """Loughran-McDonald score in [-1, +1]. Pure dict count."""
    if not text:
        return 0.0
    words = [w.lower().strip(",.!?;:'\"()[]") for w in text.split()]
    pos = sum(1 for w in words if w in _LM_POS)
    neg = sum(1 for w in words if w in _LM_NEG)
    if pos + neg == 0:
        return 0.0
    return (pos - neg) / (pos + neg)


@dataclass
class SentimentResult:
    symbol: str
    score: float           # [-1, +1]
    confidence: float      # [0, 1]
    method: str            # 'claude' | 'lm_dict' | 'mock'
    rationale: str = ""


class LLMSentimentScorer:
    """Score per-symbol news sentiment via Claude with LM-dict fallback."""

    def __init__(self, api_key: str | None = None, model: str = "claude-sonnet-4-20250514"):
        self.api_key = api_key or os.getenv("ANTHROPIC_API_KEY")
        self.model = model
        self._client = None
        if self.api_key and not self.api_key.startswith("changeme"):
            try:
                import anthropic
                self._client = anthropic.Anthropic(api_key=self.api_key)
            except Exception:
                self._client = None

    def score(self, symbol: str, news_items: list[str]) -> SentimentResult:
        if not news_items:
            return SentimentResult(symbol, 0.0, 0.0, "none", "no news")

        if self._client is not None:
            return self._score_claude(symbol, news_items)
        return self._score_lm(symbol, news_items)

    def _score_lm(self, symbol: str, news_items: list[str]) -> SentimentResult:
        joined = " ".join(news_items)
        s = lm_dict_score(joined)
        return SentimentResult(
            symbol=symbol, score=s, confidence=min(len(news_items) / 5.0, 1.0),
            method="lm_dict",
            rationale=f"LM dict over {len(news_items)} headlines",
        )

    def _score_claude(self, symbol: str, news_items: list[str]) -> SentimentResult:
        joined = "\n- ".join(news_items[:10])
        prompt = (
            f"Rate the equity-market sentiment for {symbol} based ONLY on these recent "
            f"news headlines — do not use outside knowledge of the company.\n\n- {joined}\n\n"
            f"Respond with ONLY a JSON object, no markdown fences, no prose, with exactly "
            f"these fields:\n"
            f'{{"score": <float -1.0 to 1.0>, "confidence": <float 0.0 to 1.0>, '
            f'"rationale": "<1 sentence>"}}\n'
            f"score: -1.0 = strongly bearish, 0.0 = neutral/mixed, +1.0 = strongly bullish. "
            f"confidence: how unambiguous the headlines are. Be conservative — reserve "
            f"|score| > 0.5 for clearly directional news."
        )
        try:
            resp = self._client.messages.create(
                model=self.model, max_tokens=200,
                system=(
                    "You are a financial news sentiment analyst. Respond with ONLY the "
                    "requested JSON object — no markdown fences, no extra text."
                ),
                messages=[{"role": "user", "content": prompt}],
            )
            text = resp.content[0].text.strip()
            # strip code-fence
            if text.startswith("```"):
                text = text.split("```")[1]
                if text.startswith("json"):
                    text = text[4:]
            data = json.loads(text)
            return SentimentResult(
                symbol=symbol,
                score=float(max(-1.0, min(1.0, data.get("score", 0.0)))),
                confidence=float(max(0.0, min(1.0, data.get("confidence", 0.0)))),
                method="claude",
                rationale=str(data.get("rationale", ""))[:200],
            )
        except Exception as e:
            # Fall back if API call fails
            res = self._score_lm(symbol, news_items)
            res.rationale = f"claude_failed:{e}; " + res.rationale
            return res


def deterministic_mock_sentiment(symbol: str, date_iso: str) -> float:
    """Reproducible noise sentiment for backtest-without-news.

    Hashes (symbol, date) -> [-1, +1]. Lets the v4 demo run end-to-end so the
    pipeline plumbing is provable; replace with real news feed in production.
    """
    h = hashlib.sha256(f"{symbol}|{date_iso}".encode()).hexdigest()
    n = int(h[:8], 16)
    return (n / 0xFFFFFFFF) * 2 - 1  # [-1, +1]
# Originally authored by Aaryan Baadkar (aaryanbaadkar71@gmail.com).
# Provenance token BB1327442273 - verify with scripts/authorship.py verify
