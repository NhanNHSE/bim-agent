"""QCVN Agent — specialist for Vietnamese building regulations.

Handles:
  - QCVN/TCVN standard lookups
  - Building type requirements
  - Material property checks
  - Multi-hop graph reasoning for complex regulation queries
"""

import structlog

from src.agents.base import BaseAgent
from src.rag.agent import (
    tool_qcvn_search,
    tool_material_check,
    tool_graph_reasoning,
)

logger = structlog.get_logger()


class QCVNAgent(BaseAgent):
    """Expert in Vietnamese building codes and standards."""

    name = "qcvn_expert"
    description = "Chuyên gia quy chuẩn xây dựng Việt Nam (QCVN/TCVN)"

    SYSTEM_PROMPT = """Bạn là chuyên gia hàng đầu về quy chuẩn xây dựng Việt Nam.
Chuyên môn:
- QCVN 06:2022/BXD (An toàn cháy)
- QCVN 03:2012/BXD (Phân loại công trình)
- TCVN 2737:1995 (Tải trọng)
- TCVN 5574:2018 (Kết cấu bê tông cốt thép)

Khi trả lời:
- Luôn trích dẫn SỐ ĐIỀU và MÃ QUY CHUẨN cụ thể
- Giải thích ý nghĩa thực tế của quy định
- Nếu câu hỏi liên quan đến so sánh, trình bày dưới dạng BẢNG
- Cảnh báo nếu quy định đã bị thay thế/hết hiệu lực
"""

    def get_tools(self) -> list[str]:
        return ["qcvn_search", "material_check", "graph_reasoning"]

    def run(self, question: str, entities: dict, **kwargs) -> dict:
        documents = []
        tool_results = {}

        # Always do vector + graph search for regulations
        docs = tool_qcvn_search(question, entities)
        documents.extend(docs)

        # Material check if material entity exists
        material = entities.get("material", "")
        if material:
            mat_docs = tool_material_check(question, entities)
            documents.extend(mat_docs)

        # Graph reasoning for complex questions
        q_lower = question.lower()
        complex_indicators = ["so sánh", "khác nhau", "liên quan", "mối liên hệ",
                              "tất cả", "toàn bộ", "giữa", "cùng"]
        if any(ind in q_lower for ind in complex_indicators):
            graph_docs = tool_graph_reasoning(question, entities)
            documents.extend(graph_docs)
            logger.info("qcvn_agent_graph_reasoning", extra_docs=len(graph_docs))

        logger.info("qcvn_agent_run", total_docs=len(documents))
        return {
            "documents": documents,
            "tool_results": tool_results,
            "metadata": {"agent": self.name, "system_prompt": self.SYSTEM_PROMPT},
        }
