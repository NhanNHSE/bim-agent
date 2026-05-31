"""Agent Self-Reflection — evaluates response quality before delivery.

After the agent generates a response, this module runs a fast LLM evaluation
to assess quality, relevance, and accuracy. The result is a confidence score
sent to the frontend via the SSE `done` event.

Evaluation criteria:
  1. Relevance: Does the response answer the question?
  2. Citation quality: Are specific regulation codes cited?
  3. Completeness: Is the answer thorough?
  4. Accuracy: No contradictions or hallucinations detected?
"""

import json
import re
import time

from google.genai.types import GenerateContentConfig
import structlog

from src.core.llm import get_llm_client, get_model_name

logger = structlog.get_logger()


def evaluate_response(question: str, response: str, documents: list = None,
                      intent: str = "") -> dict:
    """Evaluate an agent response for quality.

    Uses a fast LLM call to score the response on multiple criteria.

    Args:
        question: Original user question.
        response: Generated response text.
        documents: Retrieved documents used as context.
        intent: Classified intent (qcvn_search, ifc_query, etc.)

    Returns:
        {
            "confidence": float (0.0 - 1.0),
            "scores": {
                "relevance": float,
                "citations": float,
                "completeness": float,
                "accuracy": float,
            },
            "feedback": str,     # Brief quality note
            "should_retry": bool,
        }
    """
    client = get_llm_client()

    # Skip reflection for general chat or very short responses
    if intent == "general_chat" or len(response) < 50:
        return {
            "confidence": 0.85,
            "scores": {"relevance": 0.9, "citations": 0.8, "completeness": 0.8, "accuracy": 0.9},
            "feedback": "Câu trả lời chung, không cần đánh giá chuyên sâu.",
            "should_retry": False,
        }

    # Build context summary
    doc_summary = ""
    if documents:
        doc_texts = [d.get("text", "")[:200] for d in documents[:5]]
        doc_summary = "\n".join(f"- {t}" for t in doc_texts)

    prompt = f"""Bạn là chuyên gia đánh giá chất lượng AI. Hãy đánh giá câu trả lời sau đây.

### Câu hỏi gốc:
"{question}"

### Câu trả lời AI:
"{response[:2000]}"

### Dữ liệu tham chiếu (nếu có):
{doc_summary or "Không có dữ liệu tham chiếu"}

### Đánh giá theo 4 tiêu chí (0.0 - 1.0):
1. **relevance**: Câu trả lời có đúng chủ đề câu hỏi không?
2. **citations**: Có trích dẫn cụ thể số điều, mã quy chuẩn không? (0.5 nếu không cần trích dẫn)
3. **completeness**: Câu trả lời đầy đủ hay thiếu thông tin quan trọng?
4. **accuracy**: Có thông tin sai/mâu thuẫn với dữ liệu tham chiếu không?

### Trả về JSON (chỉ JSON):
{{"relevance": 0.0, "citations": 0.0, "completeness": 0.0, "accuracy": 0.0, "feedback": "nhận xét ngắn"}}
"""

    try:
        result = client.models.generate_content(
            model=get_model_name(fallback=True),  # Use faster/cheaper model
            contents=prompt,
            config=GenerateContentConfig(temperature=0.0, max_output_tokens=300),
        )
        text = result.text.strip()

        # Clean markdown fences
        if text.startswith("```"):
            text = re.sub(r"^```(?:json)?\n?", "", text)
            text = re.sub(r"\n?```$", "", text)

        scores = json.loads(text)
        feedback = scores.pop("feedback", "")

        # Calculate weighted confidence
        weights = {"relevance": 0.35, "citations": 0.2, "completeness": 0.25, "accuracy": 0.2}
        confidence = sum(
            scores.get(k, 0.5) * w for k, w in weights.items()
        )
        confidence = round(min(max(confidence, 0.0), 1.0), 2)

        should_retry = confidence < 0.4

        logger.info("reflection_complete",
                     confidence=confidence,
                     scores=scores,
                     should_retry=should_retry)

        return {
            "confidence": confidence,
            "scores": scores,
            "feedback": feedback,
            "should_retry": should_retry,
        }

    except Exception as e:
        logger.warning("reflection_failed", error=str(e))
        # On failure, return neutral score — don't block the response
        return {
            "confidence": 0.7,
            "scores": {"relevance": 0.7, "citations": 0.7, "completeness": 0.7, "accuracy": 0.7},
            "feedback": "Không thể đánh giá tự động.",
            "should_retry": False,
        }


def format_confidence_label(confidence: float) -> str:
    """Convert confidence score to human-readable label.

    Args:
        confidence: 0.0 - 1.0

    Returns:
        Vietnamese label string.
    """
    if confidence >= 0.85:
        return "Rất tin cậy"
    elif confidence >= 0.7:
        return "Tin cậy"
    elif confidence >= 0.5:
        return "Trung bình"
    elif confidence >= 0.3:
        return "Cần xem xét"
    else:
        return "Độ tin cậy thấp"
