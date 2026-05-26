"""Tests for the hybrid (regex + LLM) query classifier router."""
from __future__ import annotations

from unittest.mock import patch

from django.test import TestCase, override_settings

from apps.chat.services.query_analysis import (
    CLASSIFIER_CONFIDENCE_HIGH,
    CLASSIFIER_CONFIDENCE_LOW,
    CLASSIFIER_SOURCE_LLM,
    CLASSIFIER_SOURCE_OVERRIDE,
    CLASSIFIER_SOURCE_REGEX,
    COVERAGE_MODE_ALL,
    COVERAGE_MODE_FOCUSED,
    QUERY_TYPE_COMPARATIVE,
    QUERY_TYPE_PANORAMA,
    apply_response_mode_override,
    classify_query,
    classify_query_hybrid,
    classify_query_llm,
)


class RegexClassifierConfidenceTests(TestCase):
    """The regex classifier tags its output with a confidence level so the
    hybrid router can decide whether to escalate to the LLM."""

    def test_strong_comparative_signal_is_high_confidence(self):
        analysis = classify_query(
            "Compará el documento A con el documento B y resaltame diferencias"
        )
        self.assertEqual(analysis.query_type, QUERY_TYPE_COMPARATIVE)
        self.assertEqual(analysis.classifier_source, CLASSIFIER_SOURCE_REGEX)
        self.assertEqual(analysis.classifier_confidence, CLASSIFIER_CONFIDENCE_HIGH)

    def test_short_factual_lookup_is_high_confidence(self):
        analysis = classify_query("autor de informe anual")
        self.assertEqual(analysis.classifier_confidence, CLASSIFIER_CONFIDENCE_HIGH)

    def test_long_prose_with_no_topical_signal_is_low_confidence(self):
        # Long prose question, no panorama / comparative / numeric cue.
        # This is precisely the bucket the LLM router should pick up.
        text = (
            "Quisiera entender cómo se vincula la estrategia descrita en el "
            "documento con los procesos del equipo de operaciones y qué "
            "implicaciones podría tener en próximos trimestres"
        )
        analysis = classify_query(text)
        self.assertEqual(analysis.classifier_confidence, CLASSIFIER_CONFIDENCE_LOW)


class HybridRouterTests(TestCase):
    """The hybrid router escalates to the LLM only when the regex is unsure."""

    @patch("apps.chat.services.query_analysis.classify_query_llm")
    def test_high_confidence_regex_skips_llm(self, mock_llm):
        result = classify_query_hybrid(
            "Compará el documento A con el documento B"
        )
        mock_llm.assert_not_called()
        self.assertEqual(result.classifier_source, CLASSIFIER_SOURCE_REGEX)

    @patch("apps.chat.services.query_analysis.classify_query_llm")
    def test_low_confidence_calls_llm(self, mock_llm):
        mock_llm.return_value = self._fake_llm_analysis(
            query_type=QUERY_TYPE_PANORAMA,
            coverage_mode=COVERAGE_MODE_ALL,
            is_general=True,
        )
        text = (
            "Quisiera entender cómo se vincula la estrategia descrita en el "
            "documento con los procesos del equipo de operaciones y qué "
            "implicaciones podría tener en próximos trimestres"
        )
        result = classify_query_hybrid(text)
        mock_llm.assert_called_once()
        self.assertEqual(result.classifier_source, CLASSIFIER_SOURCE_LLM)
        self.assertEqual(result.query_type, QUERY_TYPE_PANORAMA)
        self.assertEqual(result.coverage_mode, COVERAGE_MODE_ALL)

    @patch("apps.chat.services.query_analysis.classify_query_llm")
    def test_llm_failure_falls_back_to_regex(self, mock_llm):
        mock_llm.return_value = None
        text = (
            "Quisiera entender cómo se vincula la estrategia descrita en el "
            "documento con los procesos del equipo de operaciones y qué "
            "implicaciones podría tener en próximos trimestres"
        )
        result = classify_query_hybrid(text)
        mock_llm.assert_called_once()
        # Falls back: source stays "regex" (the regex analysis is returned).
        self.assertEqual(result.classifier_source, CLASSIFIER_SOURCE_REGEX)

    @patch("apps.chat.services.query_analysis.classify_query_llm")
    @override_settings()
    def test_feature_flag_disabled_skips_llm(self, mock_llm):
        text = (
            "Quisiera entender cómo se vincula la estrategia descrita en el "
            "documento con los procesos del equipo de operaciones y qué "
            "implicaciones podría tener en próximos trimestres"
        )
        import os

        os.environ["RAG_LLM_ROUTER_ENABLED"] = "0"
        try:
            result = classify_query_hybrid(text)
        finally:
            os.environ.pop("RAG_LLM_ROUTER_ENABLED", None)
        mock_llm.assert_not_called()
        self.assertEqual(result.classifier_source, CLASSIFIER_SOURCE_REGEX)

    def test_override_takes_precedence(self):
        analysis = classify_query("autor de informe anual")
        analysis = apply_response_mode_override(analysis, "panorama")
        self.assertEqual(analysis.classifier_source, CLASSIFIER_SOURCE_OVERRIDE)
        self.assertEqual(analysis.query_type, QUERY_TYPE_PANORAMA)
        self.assertEqual(analysis.coverage_mode, COVERAGE_MODE_ALL)

    @staticmethod
    def _fake_llm_analysis(*, query_type, coverage_mode, is_general):
        # Mirror the structure classify_query_llm would produce.
        from apps.chat.services.query_analysis import QueryAnalysis

        analysis = QueryAnalysis(
            raw_text="x",
            normalized="x",
            query_type=query_type,
            coverage_mode=coverage_mode,
            is_general=is_general,
        )
        analysis.classifier_source = CLASSIFIER_SOURCE_LLM
        analysis.classifier_confidence = CLASSIFIER_CONFIDENCE_HIGH
        return analysis


class LLMRouterParsingTests(TestCase):
    """`classify_query_llm` is defensive about LLM output formats."""

    @patch("apps.document.utils.client_openia.generate_chat_completion")
    def test_parses_well_formed_json(self, mock_chat):
        mock_chat.return_value = (
            '{"query_type": "comparative", "coverage_mode": "balanced", '
            '"is_general": true, "confidence": "high"}',
            {"total_tokens": 5},
        )
        result = classify_query_llm("¿En qué difieren los dos planes?")
        self.assertIsNotNone(result)
        self.assertEqual(result.query_type, "comparative")
        self.assertEqual(result.coverage_mode, "balanced")
        self.assertTrue(result.is_general)

    @patch("apps.document.utils.client_openia.generate_chat_completion")
    def test_invalid_query_type_returns_none(self, mock_chat):
        mock_chat.return_value = (
            '{"query_type": "bogus", "coverage_mode": "focused"}',
            {},
        )
        self.assertIsNone(classify_query_llm("foo"))

    @patch("apps.document.utils.client_openia.generate_chat_completion")
    def test_malformed_json_returns_none(self, mock_chat):
        mock_chat.return_value = ("not even close to json", {})
        self.assertIsNone(classify_query_llm("foo"))

    @patch("apps.document.utils.client_openia.generate_chat_completion")
    def test_backfills_missing_coverage_mode(self, mock_chat):
        mock_chat.return_value = (
            '{"query_type": "factual", "confidence": "high"}',
            {},
        )
        result = classify_query_llm("autor del informe")
        self.assertIsNotNone(result)
        self.assertEqual(result.coverage_mode, COVERAGE_MODE_FOCUSED)
