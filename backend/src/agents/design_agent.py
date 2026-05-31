"""Design Agent — specialist for Text-to-BIM generation.

Handles:
  - Interpreting design requirements from natural language
  - Generating IFC building models
  - Running compliance checks against QCVN
"""

import structlog

from src.agents.base import BaseAgent
from src.rag.agent import tool_design_building

logger = structlog.get_logger()


class DesignAgent(BaseAgent):
    """Expert in generating BIM models from text descriptions."""

    name = "design_architect"
    description = "Kiến trúc sư AI — thiết kế mô hình BIM từ mô tả"

    SYSTEM_PROMPT = """Bạn là kiến trúc sư AI chuyên thiết kế công trình xây dựng.
Chuyên môn:
- Phân tích yêu cầu thiết kế từ mô tả tự nhiên
- Tạo mô hình IFC (Industry Foundation Classes) tự động
- Kiểm tra tuân thủ quy chuẩn QCVN tự động

Khi trả lời:
- Mô tả tổng quan mô hình đã tạo (số tầng, kích thước, vật liệu)
- Trình bày kết quả kiểm tra quy chuẩn (vi phạm, cảnh báo, đạt)
- Gợi ý cải thiện nếu có vi phạm
- Cho biết có thể tải file IFC hoặc xem mô hình 3D
"""

    def get_tools(self) -> list[str]:
        return ["design_building"]

    def run(self, question: str, entities: dict, **kwargs) -> dict:
        documents = []
        tool_results = {}

        # Design the building
        result = tool_design_building(question, entities)
        tool_results["design"] = result

        # Add summary as document
        if result.get("summary"):
            documents.append({
                "text": result["summary"],
                "metadata": {"source": "ifc_generator"},
                "score": 1.0,
            })

        # Add violations as documents
        for v in result.get("violations", []):
            documents.append({
                "text": f"[{v['severity'].upper()}] {v['rule']}: {v['issue']}\nGợi ý: {v['suggestion']}",
                "metadata": {"source": "compliance_checker"},
                "score": 0.95,
            })

        logger.info("design_agent_run", total_docs=len(documents),
                     violations=len(result.get("violations", [])))
        return {
            "documents": documents,
            "tool_results": tool_results,
            "metadata": {"agent": self.name, "system_prompt": self.SYSTEM_PROMPT},
        }
