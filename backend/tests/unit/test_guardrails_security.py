"""Unit tests for Guardrails Security (Task 013).

Covers:
- Cypher read-only execution via session.execute_read
- Chat message character limit (4,000 chars) and whitespace rejection
- IFC design parameter validation (SPEC_BOUNDS) and bounds enforcement in design_tool
"""

from dataclasses import fields
import json
from unittest.mock import MagicMock, patch

import pytest

from src.data_pipeline.base_spec import BridgeSpec, SPEC_BOUNDS, validate_spec_bounds
from src.data_pipeline.ifc_generator_v2 import BuildingSpec


# =====================================================================
# A. Neo4j Read-Only Execution Tests
# =====================================================================

class TestNeo4jReadOnly:
    """Verify that neo4j_client.run_query runs exclusively within managed read transactions."""

    def test_run_query_uses_execute_read_and_not_session_run(self):
        from src.knowledge_graph.neo4j_client import run_query

        mock_driver = MagicMock()
        mock_session = MagicMock()
        mock_driver.session.return_value.__enter__.return_value = mock_session
        mock_session.execute_read.return_value = [{"col": 42}]

        with patch("src.knowledge_graph.neo4j_client.get_driver", return_value=mock_driver):
            results = run_query("MATCH (n) RETURN n")

        assert results == [{"col": 42}]
        # Must invoke execute_read
        mock_session.execute_read.assert_called_once()
        # Must NOT directly call session.run (which defaults to write access)
        mock_session.run.assert_not_called()


# =====================================================================
# B. Chat Message Length & Whitespace Tests
# =====================================================================

def _fake_llm_stream(**kwargs):
    return iter(["Phản hồi mẫu"]), [], {}

REFLECTION = {"confidence": 0.95, "scores": {}, "feedback": "tốt", "should_retry": False}


class TestChatMessageLength:
    """Verify chat length limit (4,000 chars) and rejection of empty/whitespace messages."""

    @pytest.fixture(autouse=True)
    def _simple_mode(self, monkeypatch):
        monkeypatch.setattr("src.api.router_chat.settings.agent_mode", "simple")

    def test_message_exceeding_4000_chars_returns_422_and_skips_llm(self, client, auth_headers):
        oversized_message = "a" * 4001
        with patch("src.rag.graph_rag.ask", side_effect=_fake_llm_stream) as mock_ask, \
             patch("src.rag.reflection.evaluate_response", return_value=REFLECTION):
            response = client.post(
                "/api/v1/chat",
                json={"message": oversized_message},
                headers=auth_headers,
            )

        assert response.status_code == 422
        # Crucial security guarantee: LLM pipeline must NEVER be invoked
        mock_ask.assert_not_called()

    def test_message_at_exact_4000_chars_accepted_200(self, client, auth_headers):
        exact_message = "a" * 4000
        with patch("src.rag.graph_rag.ask", side_effect=_fake_llm_stream) as mock_ask, \
             patch("src.rag.reflection.evaluate_response", return_value=REFLECTION):
            response = client.post(
                "/api/v1/chat",
                json={"message": exact_message},
                headers=auth_headers,
            )

        assert response.status_code == 200
        assert mock_ask.call_count == 1

    def test_whitespace_only_message_returns_422_and_skips_llm(self, client, auth_headers):
        whitespace_msg = "   "
        with patch("src.rag.graph_rag.ask", side_effect=_fake_llm_stream) as mock_ask, \
             patch("src.rag.reflection.evaluate_response", return_value=REFLECTION):
            response = client.post(
                "/api/v1/chat",
                json={"message": whitespace_msg},
                headers=auth_headers,
            )

        assert response.status_code == 422
        mock_ask.assert_not_called()

    def test_empty_message_returns_422_and_skips_llm(self, client, auth_headers):
        with patch("src.rag.graph_rag.ask", side_effect=_fake_llm_stream) as mock_ask, \
             patch("src.rag.reflection.evaluate_response", return_value=REFLECTION):
            response = client.post(
                "/api/v1/chat",
                json={"message": ""},
                headers=auth_headers,
            )

        assert response.status_code == 422
        mock_ask.assert_not_called()


# =====================================================================
# C. IFC Parameter Bounds Validation Tests
# =====================================================================

class TestSpecBoundsValidation:
    """Verify validation of BuildingSpec and BridgeSpec dimensions and types."""

    def test_default_specs_within_bounds(self):
        # Default instances of both dataclasses must pass validation
        building = BuildingSpec()
        bridge = BridgeSpec()
        validate_spec_bounds(building)
        validate_spec_bounds(bridge)

    def test_building_storeys_out_of_bounds_raises_value_error(self):
        building = BuildingSpec(num_storeys=1000)
        with pytest.raises(ValueError) as exc:
            validate_spec_bounds(building)
        msg = str(exc.value)
        assert "num_storeys=1000 (cho phép 1–40)" in msg

    def test_int_field_with_fractional_float_raises_value_error(self):
        building = BuildingSpec()
        building.num_storeys = 3.5  # float with fractional part
        with pytest.raises(ValueError) as exc:
            validate_spec_bounds(building)
        assert "num_storeys=3.5 (cho phép 1–40)" in str(exc.value)

    def test_boolean_for_numeric_field_rejected(self):
        building = BuildingSpec()
        building.num_storeys = True  # bool subclass of int
        with pytest.raises(ValueError) as exc:
            validate_spec_bounds(building)
        assert "num_storeys=True (cho phép 1–40)" in str(exc.value)

    def test_nan_for_numeric_field_rejected(self):
        building = BuildingSpec()
        building.storey_height = float("nan")
        with pytest.raises(ValueError) as exc:
            validate_spec_bounds(building)
        assert "storey_height=nan (cho phép 2400–6000)" in str(exc.value)

    def test_multiple_violations_reported_in_single_message(self):
        building = BuildingSpec(num_storeys=1000)
        building.storey_height = 1000.0  # below min 2400
        with pytest.raises(ValueError) as exc:
            validate_spec_bounds(building)
        msg = str(exc.value)
        assert "num_storeys=1000 (cho phép 1–40)" in msg
        assert "storey_height=1000.0 (cho phép 2400–6000)" in msg

    def test_bridge_bounds_violations_detected(self):
        bridge = BridgeSpec(total_length=100.0)  # below 6000
        with pytest.raises(ValueError) as exc:
            validate_spec_bounds(bridge)
        assert "total_length=100.0 (cho phép 6000–500000)" in str(exc.value)

    def test_structure_type_tampering_building_bounds_enforced(self):
        building = BuildingSpec(num_storeys=1000, structure_type="x")
        with pytest.raises(ValueError) as exc:
            validate_spec_bounds(building)
        assert "num_storeys=1000 (cho phép 1–40)" in str(exc.value)

    def test_structure_type_tampering_bridge_bounds_enforced(self):
        bridge = BridgeSpec(total_length=100.0, structure_type="building")
        with pytest.raises(ValueError) as exc:
            validate_spec_bounds(bridge)
        assert "total_length=100.0 (cho phép 6000–500000)" in str(exc.value)

    def test_all_numeric_fields_have_bounds_coverage(self):
        """Verifies that all numeric dataclass fields are covered by SPEC_BOUNDS."""
        for spec_cls, spec_type in [(BuildingSpec, "building"), (BridgeSpec, "bridge")]:
            bounds = SPEC_BOUNDS[spec_type]
            for f in fields(spec_cls):
                is_num = f.type in (int, float, "int", "float") or (
                    isinstance(f.default, (int, float)) and not isinstance(f.default, bool)
                )
                if is_num:
                    assert (
                        f.name in bounds
                    ), f"Field '{f.name}' in {spec_cls.__name__} has no bounds in SPEC_BOUNDS['{spec_type}']"


class TestDesignToolBoundsEnforcement:
    """Verify that design_tool checks bounds and halts generation upon violation."""

    def test_building_design_halts_on_bounds_violation(self):
        from src.rag.tools.design_tool import tool_design_building

        mock_llm_response = MagicMock()
        mock_llm_response.text = json.dumps({
            "project_name": "Dự án cao tầng",
            "building_name": "Tòa chọc trời",
            "num_storeys": 1000,
        })

        mock_client = MagicMock()
        mock_client.models.generate_content.return_value = mock_llm_response

        with patch("src.rag.tools.design_tool.get_llm_client", return_value=mock_client), \
             patch("src.data_pipeline.ifc_generator_v2.generate_from_spec") as mock_generate:
            result = tool_design_building("Thiết kế tòa nhà 1000 tầng", {})

        # Must return error dict matching existing contract
        assert "error" in result
        assert "num_storeys=1000 (cho phép 1–40)" in result["error"]
        assert result["summary"] == ""
        assert result["violations"] == []
        # Crucial security guarantee: generator is NEVER called with invalid spec
        mock_generate.assert_not_called()

    def test_bridge_design_halts_on_bounds_violation(self):
        from src.rag.tools.design_tool import tool_design_building

        mock_llm_response = MagicMock()
        mock_llm_response.text = json.dumps({
            "project_name": "Cầu siêu dài",
            "bridge_name": "Cầu khổng lồ",
            "total_length": 1000000,  # exceeds max 500000
            "num_spans": 5,
        })

        mock_client = MagicMock()
        mock_client.models.generate_content.return_value = mock_llm_response

        with patch("src.rag.tools.design_tool.get_llm_client", return_value=mock_client), \
             patch("src.data_pipeline.ifc_bridge_generator.generate_bridge") as mock_generate:
            result = tool_design_building("Thiết kế cầu bê tông 1000m", {"building_type": "bridge"})

        assert "error" in result
        assert "total_length=1000000 (cho phép 6000–500000)" in result["error"]
        assert result["summary"] == ""
        assert result["violations"] == []
        mock_generate.assert_not_called()

    def test_tool_design_building_with_structure_type_tampering_halts(self):
        from src.rag.tools.design_tool import tool_design_building

        mock_llm_response = MagicMock()
        mock_llm_response.text = json.dumps({
            "structure_type": "x",
            "num_storeys": 1000,
        })

        mock_client = MagicMock()
        mock_client.models.generate_content.return_value = mock_llm_response

        with patch("src.rag.tools.design_tool.get_llm_client", return_value=mock_client), \
             patch("src.data_pipeline.ifc_generator_v2.generate_from_spec") as mock_generate:
            result = tool_design_building("Thiết kế tòa nhà", {})

        assert "error" in result
        assert "num_storeys=1000 (cho phép 1–40)" in result["error"]
        assert result["summary"] == ""
        assert result["violations"] == []
        mock_generate.assert_not_called()

