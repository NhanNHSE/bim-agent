"""Tests for Self-Reflection module."""

import pytest


from src.rag.reflection import format_confidence_label


class TestConfidenceLabel:
    """Test confidence score to label mapping."""

    def test_very_high(self):
        assert format_confidence_label(0.95) == "Rất tin cậy"
        assert format_confidence_label(0.85) == "Rất tin cậy"

    def test_high(self):
        assert format_confidence_label(0.7) == "Tin cậy"
        assert format_confidence_label(0.84) == "Tin cậy"

    def test_medium(self):
        assert format_confidence_label(0.5) == "Trung bình"
        assert format_confidence_label(0.69) == "Trung bình"

    def test_needs_review(self):
        assert format_confidence_label(0.3) == "Cần xem xét"
        assert format_confidence_label(0.49) == "Cần xem xét"

    def test_low(self):
        assert format_confidence_label(0.0) == "Độ tin cậy thấp"
        assert format_confidence_label(0.29) == "Độ tin cậy thấp"

    def test_boundary_values(self):
        assert format_confidence_label(1.0) == "Rất tin cậy"
        assert format_confidence_label(0.0) == "Độ tin cậy thấp"
