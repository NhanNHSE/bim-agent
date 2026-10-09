"""LangGraph Multi-Tool Agent for BIM AI — Orchestrator.

Coordinates the agent pipeline:
1. Classifies the user's question intent
2. Routes to appropriate tool(s)
3. Synthesizes results into a coherent response

Tools are defined in src.rag.tools.* modules.
LLM client is centralized in src.core.llm.
"""

import json
import time
from typing import TypedDict

from google.genai.types import GenerateContentConfig
import structlog

from src.core.config import get_settings
from src.core.llm import get_llm_client, get_model_name, MAX_RETRIES

# Tool imports
from src.rag.tools.qcvn_tool import tool_qcvn_search, tool_material_check
from src.rag.tools.ifc_tool import tool_ifc_query
from src.rag.tools.graph_tool import tool_graph_reasoning
from src.rag.tools.design_tool import tool_design_building

logger = structlog.get_logger()
settings = get_settings()


# ===== Agent State =====

class AgentState(TypedDict):
    """State passed between agent nodes."""
    question: str
    messages: list  # conversation history
    intent: str  # classified intent
    tools_to_use: list[str]
    tool_results: dict  # tool_name → results
    retrieved_docs: list  # all retrieved documents
    entities: dict  # extracted entities
    response: str  # final response


# ===== Tool Registry =====

_TOOL_REGISTRY = {
    "qcvn_search": tool_qcvn_search,
    "ifc_query": tool_ifc_query,
    "material_check": tool_material_check,
    "graph_reasoning": tool_graph_reasoning,
}


# Context sent to the LLM per retrieved document: chunks are ≤ ~1.6k chars
# (chunker.MAX_CHUNK_CHARS + context header); a 500-char cut used to hide half a clause
CONTEXT_CHARS_PER_DOC = 1600


# ===== Agent Nodes =====

def classify_question(state: AgentState) -> AgentState:
    """Classify the user's question and determine which tools to use."""
    client = get_llm_client()
    question = state["question"]
    q_lower = question.lower()

    # === Keyword pre-check for design_building ===
    design_keywords = ["thiết kế", "tạo mô hình", "xây dựng mô hình", "tạo tòa nhà",
                        "thiết kế tòa nhà", "thiết kế nhà", "tạo nhà", "xây nhà",
                        "thiết kế cầu", "thiet ke cau", "tạo cầu",
                        "design", "generate building", "generate bridge"]
    spec_keywords = ["tầng", "m²", "m2", "diện tích", "btct", "bê tông",
                      "văn phòng", "nhà ở", "chung cư", "trường học",
                      # Bridge-specific specs
                      "nhịp", "làn xe", "lan xe", "dầm", "dam",
                      "trụ cầu", "mố cầu", "cầu dầm", "cau dam"]

    # Also detect: "thiết kế cầu 30m" (design + bridge keyword)
    bridge_terms = [" cầu ", " cau ", "bridge"]
    # Filter out "cầu thang" first
    q_check = q_lower
    for safe in ["cầu thang", "cau thang"]:
        q_check = q_check.replace(safe, "")
    has_bridge = any(kw in q_check for kw in bridge_terms)

    has_design = any(kw in q_lower for kw in design_keywords)
    has_spec = any(kw in q_lower for kw in spec_keywords)

    if has_design and (has_spec or has_bridge):
        logger.info("design_detected_by_keyword", question=question[:80],
                    is_bridge=has_bridge)
        state["tools_to_use"] = ["design_building"]
        state["entities"] = {"topic": "thiết kế", "keywords": [],
                             "building_type": "bridge" if has_bridge else ""}
        state["intent"] = "design_building"
        return state

    prompt = f"""Phân loại câu hỏi sau đây về lĩnh vực xây dựng/BIM.

Câu hỏi: "{question}"

Chọn MỘT HOẶC NHIỀU tools phù hợp:
- design_building: Khi người dùng YÊU CẦU THIẾT KẾ/TẠO/XÂY DỰNG một công trình mới (tòa nhà HOẶC cầu). VD: "thiết kế nhà 5 tầng", "tạo mô hình văn phòng 200m²", "xây nhà 3 tầng BTCT", "thiết kế cầu dầm 30m, 3 nhịp, 2 làn xe", "thiết kế cầu BTCT vượt sông"
- qcvn_search: Tra cứu/hỏi về quy chuẩn QCVN, tiêu chuẩn TCVN, yêu cầu pháp lý. VD: "yêu cầu PCCC cho nhà F1", "chiều rộng lối thoát nạn tối thiểu?"
- graph_reasoning: Câu hỏi PHỨC TẠP cần suy luận đa bước, SO SÁNH giữa 2+ loại nhà/quy chuẩn, hoặc tìm MỐI LIÊN HỆ giữa các điều khoản. VD: "so sánh yêu cầu PCCC giữa F1 và F2", "QCVN 06 và TCVN 2737 liên quan nhau thế nào?", "tất cả yêu cầu cho vật liệu bê tông trong QCVN 06?"
- ifc_query: Truy vấn mô hình BIM/IFC đã có (cấu kiện, tầng, không gian). VD: "tầng 1 có bao nhiêu cột?", "vật liệu cột C1?"
- material_check: Kiểm tra thông số vật liệu. VD: "trọng lượng riêng bê tông?", "cường độ thép CB400V?"
- general_chat: Chào hỏi, câu hỏi chung

QUAN TRỌNG:
- Nếu câu hỏi có từ "thiết kế", "tạo", "xây", "làm" kèm thông số công trình (số tầng, diện tích, vật liệu, nhịp cầu, làn xe) → chọn design_building. KHÔNG chọn qcvn_search cho trường hợp này.
- design_building hỗ trợ CẢ tòa nhà VÀ cầu. VD: "thiết kế cầu 30m" → design_building.
- Nếu câu hỏi có từ "so sánh", "khác nhau", "liên quan", "mối liên hệ", hoặc đề cập đến 2+ quy chuẩn/loại nhà → chọn graph_reasoning (có thể kết hợp cùng qcvn_search).

Cũng trích xuất các thực thể:
- building_type: Nhóm công trình (F1, F2, F3...) nếu có
- standard_code: Mã quy chuẩn (QCVN 06, TCVN 2737...) nếu có
- topic: Chủ đề (PCCC, tải trọng, kết cấu...) nếu có
- material: Vật liệu (bê tông, thép...) nếu có
- storey: Tên tầng (Tầng 1, Tang 2...) nếu có
- keywords: Từ khóa chính (list)

Trả về JSON (chỉ JSON, không giải thích):
{{"tools": ["<tool_name>"], "entities": {{"building_type": "", "standard_code": "", "topic": "", "material": "", "storey": "", "keywords": []}}}}

Ví dụ:
- "Thiết kế nhà 5 tầng 200m²" → {{"tools": ["design_building"], "entities": {{"building_type": "F2", "topic": "thiết kế", "keywords": ["5 tầng", "200m²"]}}}}
- "Yêu cầu PCCC nhà F1?" → {{"tools": ["qcvn_search"], "entities": {{"building_type": "F1", "topic": "PCCC"}}}}
- "So sánh PCCC giữa nhà F1 và F2" → {{"tools": ["graph_reasoning", "qcvn_search"], "entities": {{"building_type": "F1", "topic": "PCCC", "keywords": ["F1", "F2", "so sánh"]}}}}
"""

    for attempt in range(MAX_RETRIES):
        model = get_model_name(fallback=(attempt == MAX_RETRIES - 1))
        try:
            response = client.models.generate_content(
                model=model,
                contents=prompt,
                config=GenerateContentConfig(temperature=0.0, max_output_tokens=400),
            )
            text = response.text.strip()
            if "```" in text:
                text = text.split("```")[1]
                if text.startswith("json"):
                    text = text[4:]
            parsed = json.loads(text)

            state["tools_to_use"] = parsed.get("tools", ["general_chat"])
            state["entities"] = parsed.get("entities", {})
            state["intent"] = ", ".join(state["tools_to_use"])
            logger.info("question_classified", intent=state["intent"], entities=state["entities"])
            return state

        except Exception as e:
            err = str(e)
            if ("503" in err or "429" in err) and attempt < MAX_RETRIES - 1:
                time.sleep(2 ** (attempt + 1))
            else:
                logger.warning("classification_failed", error=err)
                state["tools_to_use"] = ["qcvn_search"]
                state["entities"] = {}
                state["intent"] = "fallback_qcvn"
                return state

    return state


def execute_tools(state: AgentState) -> AgentState:
    """Execute the selected tools and collect results."""
    question = state["question"]
    entities = state["entities"]
    all_docs = []

    for tool_name in state["tools_to_use"]:
        if tool_name in _TOOL_REGISTRY:
            docs = _TOOL_REGISTRY[tool_name](question, entities)
            all_docs.extend(docs)
        elif tool_name == "design_building":
            result = tool_design_building(question, entities)
            state["tool_results"]["design"] = result
            if result.get("summary"):
                all_docs.append({
                    "text": result["summary"],
                    "metadata": {"source": "ifc_generator"},
                    "score": 1.0,
                })
            for v in result.get("violations", []):
                all_docs.append({
                    "text": f"[{v['severity'].upper()}] {v['rule']}: {v['issue']}\nGợi ý: {v['suggestion']}",
                    "metadata": {"source": "compliance_checker"},
                    "score": 0.95,
                })
        elif tool_name == "general_chat":
            pass  # No retrieval needed

    # Deduplicate
    seen = set()
    unique_docs = []
    for doc in all_docs:
        key = doc["text"][:200]
        if key not in seen:
            seen.add(key)
            unique_docs.append(doc)

    # Sort by score
    unique_docs.sort(key=lambda x: x.get("score", 0), reverse=True)

    state["retrieved_docs"] = unique_docs[:20]  # Limit
    logger.info("tools_executed", tools=state["tools_to_use"], total_docs=len(unique_docs))
    return state


# ===== Main Entry Point =====

def ask(question: str, messages: list = None, stream: bool = True, mode: str = None):
    """Run the agent pipeline.

    Args:
        question: User's question.
        messages: Previous conversation messages.
        stream: If True, return a generator.
        mode: UI mode - 'consult', 'design', 'analyze'. If set, skips LLM classification.

    Returns:
        Tuple of (response_or_generator, retrieved_documents, entities, tool_results).
    """

    # Initialize state
    state = AgentState(
        question=question,
        messages=messages or [],
        intent="",
        tools_to_use=[],
        tool_results={},
        retrieved_docs=[],
        entities={},
        response="",
    )

    # Step 1: Classify (skip if mode is explicit)
    mode_tool_map = {
        "design": ["design_building"],
        "analyze": ["ifc_query"],
    }
    if mode and mode in mode_tool_map:
        state["tools_to_use"] = mode_tool_map[mode]
        state["intent"] = mode
        state["entities"] = {}
        logger.info("mode_override", mode=mode, tools=state["tools_to_use"])
    else:
        state = classify_question(state)

    # Step 2: Execute tools
    state = execute_tools(state)

    # Step 3: Rerank (reuse existing reranker)
    from src.rag.graph_rag import _rerank
    if state["retrieved_docs"]:
        ranked = _rerank(question, state["retrieved_docs"])
        logger.info("agent_ranked_results", count=len(ranked))
    else:
        ranked = []

    # Step 4: Generate
    tool_results = state.get("tool_results", {})
    if stream:
        return _generate_stream(question, ranked, messages, state["intent"]), ranked, state["entities"], tool_results
    else:
        response = "".join(_generate_stream(question, ranked, messages, state["intent"]))
        return response, ranked, state["entities"], tool_results


def _generate_stream(question, documents, messages, intent):
    """Generate streaming response with intent-aware system prompt."""
    client = get_llm_client()

    # Build context from documents
    context_parts = []
    for i, doc in enumerate(documents):
        preview = doc["text"][:CONTEXT_CHARS_PER_DOC]
        meta = doc.get("metadata", {})
        source = meta.get("standard_code") or meta.get("source", "unknown")
        if meta.get("article_number"):
            source += f", {meta['article_number']}"
        context_parts.append(f"[{i+1}] ({source}) {preview}")

    context = "\n\n".join(context_parts) if context_parts else "Không có dữ liệu liên quan."

    # Intent-aware system instruction
    intent_instructions = ""
    if "ifc_query" in intent:
        intent_instructions = """
Bạn đang trả lời về dữ liệu từ mô hình BIM/IFC. Hãy:
- Liệt kê cụ thể các cấu kiện, vật liệu, kích thước nếu có
- Nêu rõ thuộc tính kỹ thuật (FireRating, IsExternal, etc.)
- Kết hợp với quy chuẩn nếu người dùng hỏi về tính tuân thủ
"""
    elif "material_check" in intent:
        intent_instructions = """
Bạn đang trả lời về thông số vật liệu xây dựng. Hãy:
- Nêu trọng lượng riêng, cường độ, và các thông số kỹ thuật
- Trích dẫn tiêu chuẩn TCVN cụ thể
"""
    elif "design_building" in intent:
        intent_instructions = """
Bạn vừa thiết kế một mô hình BIM theo yêu cầu. Hãy:
- Mô tả tổng quan mô hình đã tạo (số tầng, kích thước, vật liệu)
- Trình bày kết quả kiểm tra quy chuẩn (nếu có vi phạm, cảnh báo)
- Gợi ý cải thiện nếu cần
- Cho biết có thể tải file IFC hoặc xem mô hình 3D
"""
    elif "graph_reasoning" in intent:
        intent_instructions = """
Bạn đang suy luận đa bước từ Knowledge Graph quy chuẩn xây dựng. Hãy:
- Trình bày kết quả SO SÁNH dưới dạng bảng nếu phù hợp
- Nêu rõ MỐI LIÊN HỆ giữa các quy chuẩn/điều khoản
- Trích dẫn cụ thể số điều, mã quy chuẩn
- Tổng hợp kết luận cuối cùng
"""

    prompt = f"""Bạn là chuyên gia tư vấn quy chuẩn xây dựng Việt Nam và BIM.
{intent_instructions}

Dựa trên ngữ cảnh dưới đây, hãy trả lời câu hỏi.
Trả lời bằng tiếng Việt, cụ thể và chính xác. Trích dẫn mã quy chuẩn và số điều khoản.
Nếu không có đủ dữ liệu, nói rõ giới hạn.
Văn bản gắn nhãn [HẾT HIỆU LỰC] không còn áp dụng: ưu tiên văn bản còn hiệu lực; chỉ trích văn bản hết hiệu lực khi người dùng hỏi về nó hoặc không có văn bản thay thế, và khi đó phải nói rõ nó đã hết hiệu lực (nêu văn bản thay thế nếu có). Văn bản gắn nhãn [CHƯA CÓ HIỆU LỰC] phải nêu rõ là chưa có hiệu lực.

### Ngữ cảnh:
{context}

### Lịch sử hội thoại:
{_format_history(messages)}

### Câu hỏi:
{question}

### Trả lời:"""

    for attempt in range(MAX_RETRIES):
        model = get_model_name(fallback=(attempt == MAX_RETRIES - 1))
        try:
            stream = client.models.generate_content_stream(
                model=model,
                contents=prompt,
                config=GenerateContentConfig(temperature=0.3, max_output_tokens=8192),
            )
            for chunk in stream:
                if chunk.text:
                    yield chunk.text
            return
        except Exception as e:
            err = str(e)
            if ("503" in err or "429" in err) and attempt < MAX_RETRIES - 1:
                wait = 2 ** (attempt + 1)
                logger.warning("agent_llm_retry", model=model, attempt=attempt + 1, wait=wait)
                time.sleep(wait)
            else:
                raise


def _format_history(messages):
    if not messages:
        return "Không có"
    lines = []
    for m in messages[-6:]:  # Last 6 messages
        role = "Người dùng" if m.get("role") == "user" else "AI"
        lines.append(f"{role}: {m.get('content', '')[:200]}")
    return "\n".join(lines)
