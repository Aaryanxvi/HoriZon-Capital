"""Unit tests for LFRDriftDetector."""

import pytest

from app.agents.front_office.research.drift_detector import LFRDriftDetector


@pytest.fixture()
def detector() -> LFRDriftDetector:
    """Create a drift detector with default parameters."""
    return LFRDriftDetector(beta=0.9, alpha_warn=0.05, alpha_detect=0.01)


class TestNoDrift:
    """When the model is always correct, no drift should be detected."""

    def test_no_drift_perfect_predictions(self, detector: LFRDriftDetector) -> None:
        # Feed 100 perfect predictions (50 positive, 50 negative)
        for i in range(100):
            actual_positive = i % 2 == 0
            detector.update(
                prediction_correct=True,
                predicted_positive=actual_positive,
                actual_positive=actual_positive,
            )

        level, details = detector.check_drift()
        assert level == "NONE"

    def test_no_drift_mostly_correct(self, detector: LFRDriftDetector) -> None:
        """Mostly correct predictions with occasional errors should not trigger."""
        for i in range(200):
            actual_positive = i % 2 == 0
            # 5% error rate
            correct = i % 20 != 0
            if correct:
                predicted = actual_positive
            else:
                predicted = not actual_positive

            detector.update(
                prediction_correct=correct,
                predicted_positive=predicted,
                actual_positive=actual_positive,
            )

        level, details = detector.check_drift()
        # With only 5% errors, should be NONE or at most WARNING
        assert level in ("NONE", "WARNING")


class TestWarning:
    """Feed degrading predictions to trigger a WARNING level."""

    def test_warning_on_moderate_degradation(self) -> None:
        detector = LFRDriftDetector(beta=0.9, alpha_warn=0.05, alpha_detect=0.005)

        # Phase 1: good predictions to establish baseline
        for i in range(100):
            actual_positive = i % 2 == 0
            detector.update(
                prediction_correct=True,
                predicted_positive=actual_positive,
                actual_positive=actual_positive,
            )

        # Phase 2: degrade predictions (30% error rate)
        for i in range(100):
            actual_positive = i % 2 == 0
            correct = i % 3 != 0  # ~33% errors
            if correct:
                predicted = actual_positive
            else:
                predicted = not actual_positive

            detector.update(
                prediction_correct=correct,
                predicted_positive=predicted,
                actual_positive=actual_positive,
            )

        level, details = detector.check_drift()
        # Should at least trigger WARNING with this level of degradation
        assert level in ("WARNING", "DRIFT")


class TestDriftDetected:
    """Feed heavily degraded predictions to trigger DRIFT."""

    def test_drift_on_severe_degradation(self) -> None:
        detector = LFRDriftDetector(beta=0.8, alpha_warn=0.10, alpha_detect=0.05)

        # Phase 1: good predictions
        for i in range(50):
            actual_positive = i % 2 == 0
            detector.update(
                prediction_correct=True,
                predicted_positive=actual_positive,
                actual_positive=actual_positive,
            )

        # Phase 2: very bad predictions (70% wrong)
        for i in range(200):
            actual_positive = i % 2 == 0
            # 70% of predictions are wrong
            correct = i % 10 < 3
            if correct:
                predicted = actual_positive
            else:
                predicted = not actual_positive

            detector.update(
                prediction_correct=correct,
                predicted_positive=predicted,
                actual_positive=actual_positive,
            )

        level, details = detector.check_drift()
        assert level == "DRIFT"
        assert "triggered_rates" in details
        assert len(details["triggered_rates"]) > 0

    def test_drift_random_predictions(self) -> None:
        """Completely random predictions should eventually trigger drift."""
        import random

        random.seed(42)
        detector = LFRDriftDetector(beta=0.8, alpha_warn=0.10, alpha_detect=0.05)

        # Phase 1: good predictions
        for i in range(50):
            actual_positive = i % 2 == 0
            detector.update(
                prediction_correct=True,
                predicted_positive=actual_positive,
                actual_positive=actual_positive,
            )

        # Phase 2: random predictions
        for i in range(300):
            actual_positive = random.choice([True, False])
            predicted_positive = random.choice([True, False])
            detector.update(
                prediction_correct=(predicted_positive == actual_positive),
                predicted_positive=predicted_positive,
                actual_positive=actual_positive,
            )

        level, details = detector.check_drift()
        assert level in ("WARNING", "DRIFT")


class TestReset:
    """Test that reset clears all internal state."""

    def test_reset_clears_state(self, detector: LFRDriftDetector) -> None:
        # Feed some data
        for i in range(50):
            detector.update(
                prediction_correct=True,
                predicted_positive=True,
                actual_positive=True,
            )

        detector.reset()

        # After reset, internal counters should be zeroed
        assert detector._tp == 0
        assert detector._tn == 0
        assert detector._fp == 0
        assert detector._fn == 0

    def test_reset_returns_to_none(self, detector: LFRDriftDetector) -> None:
        """After reset, check_drift should return NONE (no data)."""
        for i in range(50):
            detector.update(
                prediction_correct=False,
                predicted_positive=True,
                actual_positive=False,
            )

        detector.reset()
        level, _ = detector.check_drift()
        assert level == "NONE"

    def test_reset_allows_fresh_detection(self) -> None:
        """After reset, the detector should work correctly on new data."""
        detector = LFRDriftDetector(beta=0.9, alpha_warn=0.05, alpha_detect=0.01)

        # Trigger some bad data
        for i in range(100):
            detector.update(
                prediction_correct=False,
                predicted_positive=True,
                actual_positive=False,
            )

        detector.reset()

        # Feed good data
        for i in range(100):
            actual_positive = i % 2 == 0
            detector.update(
                prediction_correct=True,
                predicted_positive=actual_positive,
                actual_positive=actual_positive,
            )

        level, _ = detector.check_drift()
        assert level == "NONE"
