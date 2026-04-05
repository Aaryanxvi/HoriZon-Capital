"""Tests for sentiment analysis."""
from app.agents.front_office.research.sentiment_agent import score_headline


class TestScoreHeadline:
    def test_positive(self):
        sentiment, score = score_headline("Stock prices surge on strong growth")
        assert sentiment == "positive"
        assert score > 0

    def test_negative(self):
        sentiment, score = score_headline("Markets crash amid recession fear")
        assert sentiment == "negative"
        assert score > 0

    def test_neutral(self):
        sentiment, score = score_headline("Company announces quarterly results")
        assert sentiment == "neutral"
        assert score == 0.0

    def test_empty(self):
        sentiment, score = score_headline("")
        assert sentiment == "neutral"
