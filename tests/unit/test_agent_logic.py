"""Unit tests for core AI agent logic without calling real LLMs.

Tests cover:
- Question classification (keyword pre-check & LLM classification with retry)
- GraphRAG document reranking (logic, deduplication, retry)
- Self-reflection response evaluation
- Multi-agent coordinator orchestration
"""

from unittest.mock import MagicMock, call, patch
import pytest

from src.rag.agent import classify_question, AgentState
from src.rag.graph_rag import _rerank, settings as graph_settings
from src.rag.reflection import evaluate_response
from src.agents import coordinator
from src.core.llm import get_model_name


def _make_state(question: str) -> AgentState:
    """Helper creating a fresh AgentState dictionary for testing."""
    return AgentState(
        question=question,
        messages=[],
        intent="",
        tools_to_use=[],
        tool_results={},
        retrieved_docs=[],
        entities={},
        response="",
    )


class TestClassifierKeywordPrecheck:
    """Test fast keyword-based precheck for building and bridge design."""

    @pytest.fixture(autouse=True)
    def setup_mock_client(self):
        with patch("src.rag.agent.get_llm_client") as mock_get:
            self.mock_client = MagicMock()
            mock_get.return_value = self.mock_client
            yield

    def test_precheck_building_design(self):
        """'Thiết kế nhà 5 tầng văn phòng' triggers design_building without LLM."""
        state = _make_state("Thiết kế nhà 5 tầng văn phòng")
        res = classify_question(state)

        self.mock_client.models.generate_content.assert_not_called()
        assert res["tools_to_use"] == ["design_building"]
        assert res["intent"] == "design_building"
        assert res["entities"]["building_type"] == ""

    def test_precheck_bridge_design(self):
        """'Thiết kế cầu dầm 30m 3 nhịp 2 làn xe' detects bridge entity without LLM."""
        state = _make_state("Thiết kế cầu dầm 30m 3 nhịp 2 làn xe")
        res = classify_question(state)

        self.mock_client.models.generate_content.assert_not_called()
        assert res["tools_to_use"] == ["design_building"]
        assert res["intent"] == "design_building"
        assert res["entities"]["building_type"] == "bridge"

    def test_precheck_stairs_not_bridge(self):
        """'Thiết kế cầu thang cho nhà 3 tầng' treats 'cầu thang' as building, not bridge."""
        state = _make_state("Thiết kế cầu thang cho nhà 3 tầng")
        res = classify_question(state)

        self.mock_client.models.generate_content.assert_not_called()
        assert res["tools_to_use"] == ["design_building"]
        assert res["intent"] == "design_building"
        assert res["entities"]["building_type"] == ""

    def test_precheck_english_bridge(self):
        """'design a bridge 40m' detects bridge in English without LLM."""
        state = _make_state("design a bridge 40m")
        res = classify_question(state)

        self.mock_client.models.generate_content.assert_not_called()
        assert res["tools_to_use"] == ["design_building"]
        assert res["intent"] == "design_building"
        assert res["entities"]["building_type"] == "bridge"


class TestClassifierLLM:
    """Test LLM-based classification, JSON parsing, and retry/fallback logic."""

    def test_classify_markdown_wrapped_json(self):
        """LLM returns markdown JSON block with tools and entities."""
        mock_client = MagicMock()
        mock_client.models.generate_content.return_value.text = (
            '```json\n{"tools": ["qcvn_search"], "entities": {"building_type": "F1", "topic": "PCCC"}}\n```'
        )
        with patch("src.rag.agent.get_llm_client", return_value=mock_client):
            state = _make_state("Yêu cầu PCCC nhà F1?")
            res = classify_question(state)

            assert res["tools_to_use"] == ["qcvn_search"]
            assert res["intent"] == "qcvn_search"
            assert res["entities"]["building_type"] == "F1"

    def test_classify_multiple_tools(self):
        """LLM returns multiple tools; intent is comma-separated list."""
        mock_client = MagicMock()
        mock_client.models.generate_content.return_value.text = (
            '{"tools": ["graph_reasoning", "qcvn_search"], "entities": {}}'
        )
        with patch("src.rag.agent.get_llm_client", return_value=mock_client):
            state = _make_state("So sánh quy chuẩn giữa F1 và F2")
            res = classify_question(state)

            assert res["tools_to_use"] == ["graph_reasoning", "qcvn_search"]
            assert res["intent"] == "graph_reasoning, qcvn_search"

    def test_classify_invalid_json_fallback_no_sleep(self):
        """Non-JSON response falls back to qcvn_search immediately without sleep."""
        mock_client = MagicMock()
        mock_client.models.generate_content.return_value.text = "xin lỗi, tôi không hiểu"
        with patch("src.rag.agent.get_llm_client", return_value=mock_client), \
             patch("src.rag.agent.time.sleep") as mock_sleep:
            state = _make_state("Câu hỏi chung")
            res = classify_question(state)

            assert res["tools_to_use"] == ["qcvn_search"]
            assert res["intent"] == "fallback_qcvn"
            assert res["entities"] == {}
            mock_sleep.assert_not_called()

    def test_classify_rate_limit_retry_and_fallback_model(self):
        """Two 429 errors followed by valid JSON retries with exponential backoff and fallback model."""
        mock_client = MagicMock()
        valid_resp = MagicMock()
        valid_resp.text = '{"tools": ["material_check"], "entities": {}}'
        mock_client.models.generate_content.side_effect = [
            Exception("429 RESOURCE_EXHAUSTED"),
            Exception("429 RESOURCE_EXHAUSTED"),
            valid_resp,
        ]
        with patch("src.rag.agent.get_llm_client", return_value=mock_client), \
             patch("src.rag.agent.time.sleep") as mock_sleep:
            state = _make_state("Kiểm tra bê tông")
            res = classify_question(state)

            assert res["tools_to_use"] == ["material_check"]
            assert mock_sleep.call_count == 2
            assert mock_sleep.call_args_list == [call(2), call(4)]

            calls = mock_client.models.generate_content.call_args_list
            assert len(calls) == 3
            assert calls[0].kwargs["model"] == get_model_name(fallback=False)
            assert calls[1].kwargs["model"] == get_model_name(fallback=False)
            assert calls[2].kwargs["model"] == get_model_name(fallback=True)

    def test_classify_unavailable_max_retries(self):
        """Three consecutive 503 errors exhaust retries and return fallback_qcvn."""
        mock_client = MagicMock()
        mock_client.models.generate_content.side_effect = [
            Exception("503 UNAVAILABLE"),
            Exception("503 UNAVAILABLE"),
            Exception("503 UNAVAILABLE"),
        ]
        with patch("src.rag.agent.get_llm_client", return_value=mock_client), \
             patch("src.rag.agent.time.sleep") as mock_sleep:
            state = _make_state("Quy chuẩn PCCC")
            res = classify_question(state)

            assert res["intent"] == "fallback_qcvn"
            assert mock_client.models.generate_content.call_count == 3
            assert mock_sleep.call_count == 2
            assert mock_sleep.call_args_list == [call(2), call(4)]

    def test_classify_client_error_no_retry(self):
        """400 INVALID_ARGUMENT error triggers fallback immediately without retry."""
        mock_client = MagicMock()
        mock_client.models.generate_content.side_effect = Exception("400 INVALID_ARGUMENT")
        with patch("src.rag.agent.get_llm_client", return_value=mock_client), \
             patch("src.rag.agent.time.sleep") as mock_sleep:
            state = _make_state("Lỗi tham số")
            res = classify_question(state)

            assert res["intent"] == "fallback_qcvn"
            assert mock_client.models.generate_content.call_count == 1
            mock_sleep.assert_not_called()


class TestRerank:
    """Test document reranking logic, deduplication, error handling, and backoff."""

    @pytest.fixture
    def sample_docs(self):
        return [{"text": f"doc {i} " + "x" * 10, "metadata": {}} for i in range(8)]

    def test_rerank_docs_count_less_than_or_equal_top_k(self, sample_docs):
        """When doc count <= top_k, return original docs without calling LLM."""
        with patch("src.rag.graph_rag._get_client") as mock_get_client:
            res = _rerank("q", sample_docs[:3], top_k=5)
            assert res == sample_docs[:3]
            mock_get_client.assert_not_called()

    def test_rerank_valid_indices(self, sample_docs):
        """LLM returns valid ordered indices '2, 0, 5'."""
        mock_client = MagicMock()
        mock_client.models.generate_content.return_value.text = "2, 0, 5"
        with patch("src.rag.graph_rag._get_client", return_value=mock_client):
            res = _rerank("q", sample_docs, top_k=3)
            assert res == [sample_docs[2], sample_docs[0], sample_docs[5]]

    def test_rerank_duplicate_indices_no_truncation(self, sample_docs):
        """LLM returns '6,1,6,1,0,7'.

        Current implementation deduplicates indices into [6, 1, 0, 7] but does
        not slice by top_k when multiple indices are returned.
        """
        mock_client = MagicMock()
        mock_client.models.generate_content.return_value.text = "6,1,6,1,0,7"
        with patch("src.rag.graph_rag._get_client", return_value=mock_client):
            res = _rerank("q", sample_docs, top_k=3)
            assert res == [sample_docs[6], sample_docs[1], sample_docs[0], sample_docs[7]]

    def test_rerank_invalid_and_out_of_range_indices(self, sample_docs):
        """LLM returns '1, 1, 99, abc, 3' filter out non-numbers, out-of-range, and duplicates."""
        mock_client = MagicMock()
        mock_client.models.generate_content.return_value.text = "1, 1, 99, abc, 3"
        with patch("src.rag.graph_rag._get_client", return_value=mock_client):
            res = _rerank("q", sample_docs, top_k=3)
            assert res == [sample_docs[1], sample_docs[3]]

    def test_rerank_no_valid_indices_fallback(self, sample_docs):
        """LLM returns text without numeric indices, falls back to docs[:top_k]."""
        mock_client = MagicMock()
        mock_client.models.generate_content.return_value.text = "không có đoạn nào"
        with patch("src.rag.graph_rag._get_client", return_value=mock_client):
            res = _rerank("q", sample_docs, top_k=3)
            assert res == sample_docs[:3]

    def test_rerank_max_retries_and_fallback_model(self, sample_docs):
        """Five consecutive 503 errors trigger 4 sleeps and final attempt uses llm_fallback_model."""
        mock_client = MagicMock()
        mock_client.models.generate_content.side_effect = [
            Exception("503 UNAVAILABLE"),
            Exception("503 UNAVAILABLE"),
            Exception("503 UNAVAILABLE"),
            Exception("503 UNAVAILABLE"),
            Exception("503 UNAVAILABLE"),
        ]
        with patch("src.rag.graph_rag._get_client", return_value=mock_client), \
             patch("src.rag.graph_rag.time.sleep") as mock_sleep:
            res = _rerank("q", sample_docs, top_k=3)

            assert res == sample_docs[:3]
            assert mock_sleep.call_count == 4
            assert mock_sleep.call_args_list == [call(2), call(4), call(8), call(16)]

            calls = mock_client.models.generate_content.call_args_list
            assert len(calls) == 5
            assert calls[-1].kwargs["model"] == graph_settings.llm_fallback_model


class TestReflection:
    """Test response quality evaluation and confidence calculation."""

    @pytest.fixture
    def long_response(self):
        return "Theo QCVN 06:2022/BXD Điều 3.4.2, " + "nội dung " * 10

    def test_reflection_skip_general_chat(self, long_response):
        """intent='general_chat' returns confidence 0.85 without calling LLM."""
        mock_client = MagicMock()
        with patch("src.rag.reflection.get_llm_client", return_value=mock_client):
            res = evaluate_response("Chào bạn", long_response, intent="general_chat")
            assert res["confidence"] == pytest.approx(0.85, abs=0.01)
            assert res["should_retry"] is False
            mock_client.models.generate_content.assert_not_called()

    def test_reflection_skip_short_response(self):
        """response < 50 chars returns confidence 0.85 without calling LLM."""
        mock_client = MagicMock()
        with patch("src.rag.reflection.get_llm_client", return_value=mock_client):
            res = evaluate_response("Câu hỏi", "Ngắn", intent="qcvn_search")
            assert res["confidence"] == pytest.approx(0.85, abs=0.01)
            assert res["should_retry"] is False
            mock_client.models.generate_content.assert_not_called()

    def test_reflection_perfect_score_markdown_json(self, long_response):
        """Perfect scores in markdown JSON result in confidence 1.0, feedback separated."""
        mock_client = MagicMock()
        mock_client.models.generate_content.return_value.text = (
            '```json\n{"relevance": 1.0, "citations": 1.0, "completeness": 1.0, "accuracy": 1.0, "feedback": "tốt"}\n```'
        )
        with patch("src.rag.reflection.get_llm_client", return_value=mock_client):
            res = evaluate_response("Câu hỏi", long_response, intent="qcvn_search")
            assert res["confidence"] == pytest.approx(1.0, abs=0.01)
            assert res["feedback"] == "tốt"
            assert "feedback" not in res["scores"]
            assert res["should_retry"] is False

    def test_reflection_weighted_confidence_standard(self, long_response):
        """Standard valid scores compute weighted confidence ~0.73, should_retry=False."""
        mock_client = MagicMock()
        mock_client.models.generate_content.return_value.text = (
            '{"relevance": 0.8, "citations": 0.5, "completeness": 0.6, "accuracy": 1.0, "feedback": ""}'
        )
        with patch("src.rag.reflection.get_llm_client", return_value=mock_client):
            res = evaluate_response("Câu hỏi", long_response, intent="qcvn_search")
            assert res["confidence"] == pytest.approx(0.73, abs=0.01)
            assert res["should_retry"] is False

    def test_reflection_low_confidence_should_retry(self, long_response):
        """Scores 0.2 give confidence 0.2 (< 0.4) triggering should_retry=True."""
        mock_client = MagicMock()
        mock_client.models.generate_content.return_value.text = (
            '{"relevance": 0.2, "citations": 0.2, "completeness": 0.2, "accuracy": 0.2, "feedback": ""}'
        )
        with patch("src.rag.reflection.get_llm_client", return_value=mock_client):
            res = evaluate_response("Câu hỏi", long_response, intent="qcvn_search")
            assert res["confidence"] == pytest.approx(0.2, abs=0.01)
            assert res["should_retry"] is True

    def test_reflection_missing_keys_default_half(self, long_response):
        """Missing keys default to 0.5; relevance 1.0 yields confidence ~0.675."""
        mock_client = MagicMock()
        mock_client.models.generate_content.return_value.text = '{"relevance": 1.0, "feedback": "x"}'
        with patch("src.rag.reflection.get_llm_client", return_value=mock_client):
            res = evaluate_response("Câu hỏi", long_response, intent="qcvn_search")
            assert res["confidence"] == pytest.approx(0.675, abs=0.01)

    def test_reflection_non_json_fallback(self, long_response):
        """Non-JSON response falls back to confidence 0.7."""
        mock_client = MagicMock()
        mock_client.models.generate_content.return_value.text = "không phải json"
        with patch("src.rag.reflection.get_llm_client", return_value=mock_client):
            res = evaluate_response("Câu hỏi", long_response, intent="qcvn_search")
            assert res["confidence"] == pytest.approx(0.7, abs=0.01)
            assert res["should_retry"] is False

    def test_reflection_exception_fallback(self, long_response):
        """LLM exception falls back to neutral confidence 0.7 without raising."""
        mock_client = MagicMock()
        mock_client.models.generate_content.side_effect = Exception("boom")
        with patch("src.rag.reflection.get_llm_client", return_value=mock_client):
            res = evaluate_response("Câu hỏi", long_response, intent="qcvn_search")
            assert res["confidence"] == pytest.approx(0.7, abs=0.01)


class TestCoordinator:
    """Test multi-agent coordinator orchestration, dispatching, deduplication, and streaming."""

    def test_coordinator_mode_design(self):
        """mode='design' skips classify_question and dispatches _design_agent.run only."""
        with patch("src.agents.coordinator.classify_question") as mock_classify, \
             patch("src.agents.coordinator._rerank", side_effect=lambda q, docs: docs), \
             patch("src.agents.coordinator._generate_stream", side_effect=lambda q, docs, msgs, intent: iter(["Trả ", "lời"])), \
             patch.object(coordinator._design_agent, "run", return_value={"documents": [], "tool_results": {}, "metadata": {}}) as mock_design_run, \
             patch.object(coordinator._qcvn_agent, "run") as mock_qcvn_run:

            coordinator.ask("Thiết kế nhà", messages=[], stream=False, mode="design")

            mock_classify.assert_not_called()
            mock_design_run.assert_called_once_with("Thiết kế nhà", {})
            mock_qcvn_run.assert_not_called()

    def test_coordinator_mode_analyze(self):
        """mode='analyze' skips classify_question and dispatches _bim_agent.run only."""
        with patch("src.agents.coordinator.classify_question") as mock_classify, \
             patch("src.agents.coordinator._rerank", side_effect=lambda q, docs: docs), \
             patch("src.agents.coordinator._generate_stream", side_effect=lambda q, docs, msgs, intent: iter(["Trả ", "lời"])), \
             patch.object(coordinator._bim_agent, "run", return_value={"documents": [], "tool_results": {}, "metadata": {}}) as mock_bim_run:

            coordinator.ask("Kiểm tra mô hình", messages=[], stream=False, mode="analyze")

            mock_classify.assert_not_called()
            mock_bim_run.assert_called_once_with("Kiểm tra mô hình", {})

    def test_coordinator_qcvn_tools_dispatches_agent_once(self):
        """Multiple tools mapping to QCVNAgent dispatches _qcvn_agent.run exactly once."""
        mock_state = _make_state("PCCC và vật liệu")
        mock_state["tools_to_use"] = ["qcvn_search", "graph_reasoning", "material_check"]
        mock_state["intent"] = "qcvn_search, graph_reasoning, material_check"

        with patch("src.agents.coordinator.classify_question", return_value=mock_state), \
             patch("src.agents.coordinator._rerank", side_effect=lambda q, docs: docs), \
             patch("src.agents.coordinator._generate_stream", side_effect=lambda q, docs, msgs, intent: iter(["Trả ", "lời"])), \
             patch.object(coordinator._qcvn_agent, "run", return_value={"documents": [], "tool_results": {}, "metadata": {}}) as mock_qcvn_run:

            coordinator.ask("PCCC và vật liệu", messages=[], stream=False)

            assert mock_qcvn_run.call_count == 1

    def test_coordinator_deduplicates_docs_before_rerank(self):
        """Docs with identical first 200 chars are deduplicated before passing to _rerank."""
        text_common = "Nội dung chuẩn hóa quy chuẩn " * 10  # > 200 chars
        doc1 = {"text": text_common + "đuôi 1", "metadata": {}}
        doc2 = {"text": text_common + "đuôi 2", "metadata": {}}
        doc3 = {"text": "Tài liệu khác hoàn toàn " * 10, "metadata": {}}

        mock_state = _make_state("q")
        mock_state["tools_to_use"] = ["qcvn_search"]
        mock_state["intent"] = "qcvn_search"

        with patch("src.agents.coordinator.classify_question", return_value=mock_state), \
             patch("src.agents.coordinator._rerank", side_effect=lambda q, docs: docs) as mock_rerank, \
             patch("src.agents.coordinator._generate_stream", side_effect=lambda q, docs, msgs, intent: iter(["Trả ", "lời"])), \
             patch.object(coordinator._qcvn_agent, "run", return_value={"documents": [doc1, doc2, doc3], "tool_results": {}, "metadata": {}}):

            coordinator.ask("q", messages=[], stream=False)

            mock_rerank.assert_called_once()
            passed_docs = mock_rerank.call_args[0][1]
            assert len(passed_docs) == 2
            assert passed_docs == [doc1, doc3]

    def test_coordinator_general_chat_no_rerank(self):
        """tools_to_use=['general_chat'] does not invoke _rerank and returns empty documents."""
        mock_state = _make_state("Xin chào")
        mock_state["tools_to_use"] = ["general_chat"]
        mock_state["intent"] = "general_chat"

        with patch("src.agents.coordinator.classify_question", return_value=mock_state), \
             patch("src.agents.coordinator._rerank") as mock_rerank, \
             patch("src.agents.coordinator._generate_stream", side_effect=lambda q, docs, msgs, intent: iter(["Trả ", "lời"])):

            res = coordinator.ask("Xin chào", messages=[], stream=False)

            mock_rerank.assert_not_called()
            assert res[1] == []

    def test_coordinator_stream_false_and_tool_results(self):
        """stream=False joins chunks into string; returns 4-tuple containing agent tool_results."""
        mock_state = _make_state("Thiết kế")
        mock_state["tools_to_use"] = ["design_building"]
        mock_state["intent"] = "design_building"
        expected_tool_results = {"design": {"filename": "a.ifc"}}

        with patch("src.agents.coordinator.classify_question", return_value=mock_state), \
             patch("src.agents.coordinator._rerank", side_effect=lambda q, docs: docs), \
             patch("src.agents.coordinator._generate_stream", side_effect=lambda q, docs, msgs, intent: iter(["Trả ", "lời"])), \
             patch.object(coordinator._design_agent, "run", return_value={"documents": [], "tool_results": expected_tool_results, "metadata": {}}):

            res = coordinator.ask("Thiết kế", messages=[], stream=False)

            assert isinstance(res, tuple)
            assert len(res) == 4
            assert res[0] == "Trả lời"
            assert res[3] == expected_tool_results
