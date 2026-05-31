"""BIM Agent — specialist for IFC/BIM model analysis.

Handles:
  - Querying building elements from uploaded IFC models
  - Storey/space/element analysis
  - Material usage reports
  - Combining IFC data with regulation compliance
"""

import structlog

from src.agents.base import BaseAgent
from src.rag.agent import tool_ifc_query, tool_qcvn_search

logger = structlog.get_logger()


class BIMAgent(BaseAgent):
    """Expert in BIM/IFC model analysis."""

    name = "bim_analyst"
    description = "Chuyên gia phân tích mô hình BIM/IFC"

    SYSTEM_PROMPT = """Bạn là chuyên gia phân tích mô hình BIM/IFC.
Chuyên môn:
- Đọc và phân tích cấu trúc mô hình IFC (Industry Foundation Classes)
- Phân tích cấu kiện: cột, dầm, sàn, tường, cầu thang
- Báo cáo vật liệu và thuộc tính kỹ thuật
- So sánh mô hình với quy chuẩn

Khi trả lời:
- Liệt kê CỤ THỂ tên cấu kiện, kích thước, vật liệu
- Nêu rõ thuộc tính IFC (FireRating, IsExternal, LoadBearing, etc.)
- Tổng hợp dưới dạng bảng khi có nhiều cấu kiện
- Đề xuất cải thiện nếu phát hiện vấn đề
"""

    def get_tools(self) -> list[str]:
        return ["ifc_query", "qcvn_search"]

    def run(self, question: str, entities: dict, **kwargs) -> dict:
        documents = []
        tool_results = {}

        # Query IFC model data
        ifc_docs = tool_ifc_query(question, entities)
        documents.extend(ifc_docs)

        # Also check regulations for compliance context
        q_lower = question.lower()
        compliance_keywords = ["tuân thủ", "vi phạm", "quy chuẩn", "đạt", "yêu cầu"]
        if any(kw in q_lower for kw in compliance_keywords):
            qcvn_docs = tool_qcvn_search(question, entities)
            documents.extend(qcvn_docs)
            logger.info("bim_agent_compliance_check", extra_docs=len(qcvn_docs))

        logger.info("bim_agent_run", total_docs=len(documents))
        return {
            "documents": documents,
            "tool_results": tool_results,
            "metadata": {"agent": self.name, "system_prompt": self.SYSTEM_PROMPT},
        }
