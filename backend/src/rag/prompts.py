"""AEC-specific prompt templates for the RAG pipeline."""

SYSTEM_PROMPT = """Bạn là trợ lý AI chuyên ngành Kiến trúc, Kỹ thuật và Xây dựng (AEC) tại Việt Nam.

**Vai trò:** Tư vấn về quy chuẩn xây dựng (QCVN), tiêu chuẩn kỹ thuật (TCVN), và các vấn đề kỹ thuật trong thiết kế, thi công công trình.

**Nguyên tắc trả lời:**
1. **Chính xác tuyệt đối:** Chỉ trả lời dựa trên dữ liệu được cung cấp. KHÔNG bịa đặt điều khoản, con số hoặc tiêu chuẩn.
2. **Trích dẫn nguồn:** Luôn ghi rõ mã QCVN/TCVN, số điều, số khoản khi trích dẫn.
3. **Ngôn ngữ chuyên nghiệp:** Sử dụng thuật ngữ kỹ thuật chính xác nhưng giải thích dễ hiểu.
4. **Cảnh báo giới hạn:** Nếu thông tin không đủ hoặc câu hỏi ngoài phạm vi dữ liệu, hãy nói rõ và gợi ý nguồn tra cứu thêm.
5. **An toàn là trên hết:** Với các vấn đề liên quan đến kết cấu, PCCC, thoát nạn — luôn khuyến nghị tham khảo ý kiến kỹ sư chuyên môn.
6. **Hiệu lực văn bản:** Văn bản gắn nhãn [HẾT HIỆU LỰC] không còn áp dụng: ưu tiên văn bản còn hiệu lực; chỉ trích văn bản hết hiệu lực khi người dùng hỏi về nó hoặc không có văn bản thay thế, và khi đó phải nói rõ nó đã hết hiệu lực (nêu văn bản thay thế nếu có). Văn bản gắn nhãn [CHƯA CÓ HIỆU LỰC] phải nêu rõ là chưa có hiệu lực.

**Định dạng trả lời:**
- Sử dụng Markdown
- Bảng cho dữ liệu so sánh
- Danh sách đánh số cho quy trình
- In đậm cho giá trị quan trọng (tải trọng, khoảng cách, thời gian chịu lửa)
"""


def build_rag_prompt(
    question: str,
    documents: list[dict],
    messages: list = None,
) -> str:
    """Build the complete prompt for the LLM.

    Args:
        question: User's question.
        documents: Retrieved documents with text and metadata.
        messages: Previous conversation messages.

    Returns:
        Complete prompt string.
    """
    # Format retrieved context
    context_parts = []
    for i, doc in enumerate(documents):
        source = doc.get("metadata", {}).get("standard_code", "N/A")
        article = doc.get("metadata", {}).get("article_number", "")
        source_label = f"[{source}"
        if article:
            source_label += f", Điều {article}"
        source_label += "]"

        context_parts.append(f"--- Tài liệu {i+1} {source_label} ---\n{doc['text']}")

    context = "\n\n".join(context_parts)

    # Format conversation history
    history = ""
    if messages:
        history_parts = []
        for msg in messages[-6:]:  # Last 3 exchanges
            role = "Người dùng" if msg.get("role") == "user" else "Trợ lý"
            history_parts.append(f"{role}: {msg['content'][:500]}")
        history = "\n".join(history_parts)
        history = f"\n--- Lịch sử hội thoại ---\n{history}\n"

    prompt = f"""{SYSTEM_PROMPT}
{history}
--- Dữ liệu tham khảo ---
{context}

--- Câu hỏi ---
{question}

Hãy trả lời câu hỏi dựa trên dữ liệu tham khảo ở trên. Trích dẫn cụ thể mã QCVN/TCVN và điều khoản."""

    return prompt


def build_entity_extraction_prompt(question: str) -> str:
    """Build prompt to extract entities from a user question.

    Used by GraphRAG to identify relevant nodes in the knowledge graph.

    Args:
        question: User's question.

    Returns:
        Prompt for entity extraction.
    """
    return f"""Phân tích câu hỏi sau và trích xuất các thực thể liên quan đến xây dựng.

Câu hỏi: "{question}"

Trả về JSON với các trường sau (để trống nếu không có):
{{
    "building_type": "",     // Loại công trình: "nhà ở", "nhà cao tầng", "nhà công nghiệp", "F1", "F2"...
    "standard_code": "",     // Mã QCVN/TCVN nếu được nhắc đến
    "topic": "",             // Chủ đề: "PCCC", "tải trọng", "thoát nạn", "chịu lửa", "vật liệu"...
    "material": "",          // Vật liệu: "bê tông", "thép", "gạch"...
    "parameter": "",         // Thông số kỹ thuật: "chiều rộng", "khoảng cách", "tải trọng"...
    "keywords": []           // Từ khóa tìm kiếm bổ sung
}}

Chỉ trả về JSON, không giải thích."""
