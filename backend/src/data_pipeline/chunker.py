"""Smart chunker for QCVN/TCVN documents.

Chia nhỏ văn bản quy chuẩn theo cấu trúc phân cấp (chương/phụ lục → mục → điều khoản)
thay vì cắt cơ học theo số ký tự. Mỗi chunk mang ngữ cảnh cha (mã, tên quy chuẩn, chương,
mục) và tình trạng hiệu lực, để câu trả lời trích đúng nguồn và cảnh báo văn bản hết hiệu lực.

Điều khoản dài được tách thành nhiều phần theo đoạn/câu: mô hình embedding chỉ đọc khoảng
128 token đầu của mỗi chunk, phần sau bị cắt khỏi vector.
"""

import json
import re

MAX_CHUNK_CHARS = 1200

_STATUS_TAGS = {
    "expired": "HẾT HIỆU LỰC",
    "partially_expired": "HẾT HIỆU LỰC MỘT PHẦN",
    "not_yet_effective": "CHƯA CÓ HIỆU LỰC",
    "suspended": "NGƯNG HIỆU LỰC",
}


def status_tag(standard_data: dict) -> str:
    """'[HẾT HIỆU LỰC] ' for regulations that should not be applied as current law, else ''."""
    tag = _STATUS_TAGS.get(standard_data.get("status", ""))
    return f"[{tag}] " if tag else ""


def chapter_label(chapter: dict) -> str:
    kind = chapter.get("kind", "chapter")
    title = chapter.get("title", "")
    if kind == "annex":
        return title or f"Phụ lục {chapter['number']}"
    if kind == "preamble":
        return "Phần mở đầu (thông tư ban hành, lời nói đầu)"
    if kind == "text":
        return title or "Toàn văn"
    return f"Chương {chapter['number']}: {title}".rstrip(": ")


def split_text(text: str, limit: int = MAX_CHUNK_CHARS) -> list[str]:
    """Split on paragraph, then sentence boundaries into pieces of at most ~`limit` chars."""
    if len(text) <= limit:
        return [text]
    units: list[str] = []
    for para in text.split("\n"):
        if len(para) <= limit:
            units.append(para)
            continue
        sentences = re.split(r"(?<=[.;:])\s+", para)
        buf = ""
        for sent in sentences:
            while len(sent) > limit:  # one huge "sentence" (a table): hard cut
                units.append(sent[:limit])
                sent = sent[limit:]
            if buf and len(buf) + len(sent) + 1 > limit:
                units.append(buf)
                buf = sent
            else:
                buf = f"{buf} {sent}".strip()
        if buf:
            units.append(buf)
    parts, buf = [], ""
    for unit in units:
        if buf and len(buf) + len(unit) + 1 > limit:
            parts.append(buf)
            buf = unit
        else:
            buf = f"{buf}\n{unit}" if buf else unit
    if buf:
        parts.append(buf)
    return parts


def _standard_metadata(standard_data: dict) -> dict:
    return {
        "standard_code": standard_data["standard_code"],
        "standard_name": standard_data["standard_name"],
        "year": standard_data.get("year", ""),
        "status": standard_data.get("status", "active"),
        "eff_status": standard_data.get("eff_status", ""),
        "expired": bool(standard_data.get("expired", False)),
        "doc_num": standard_data.get("doc_num", ""),
        "vbpl_url": standard_data.get("vbpl_url", ""),
        "source_id": standard_data.get("source_id") or standard_data["standard_code"],
    }


def chunk_standard(standard_data: dict, overlap_context: bool = True) -> list[dict]:
    """Chunk a structured QCVN/TCVN standard into embeddable pieces.

    Each chunk preserves hierarchical context:
    - Standard code + name (+ validity tag when not in force)
    - Chapter / annex label
    - Section
    - Article content (+ requirements)

    Args:
        standard_data: Parsed standard (sample_data_generator, qcvn_parser or vbpl_corpus).
        overlap_context: If True, include parent context in each chunk for better retrieval.

    Returns:
        List of chunks ready for embedding.
    """
    chunks = []
    standard_code = standard_data["standard_code"]
    standard_name = standard_data["standard_name"]
    tag = status_tag(standard_data)
    base_meta = _standard_metadata(standard_data)

    # Chunk 1: Standard overview (answers "is QCVN X in force / what does it replace?")
    overview_lines = [
        f"{tag}{standard_code} — {standard_name}",
        f"Năm ban hành: {standard_data.get('year', '')}",
        f"Cơ quan ban hành: {standard_data.get('issuing_body', '')}",
    ]
    if standard_data.get("doc_num"):
        overview_lines.append(f"Văn bản ban hành: {standard_data.get('doc_title') or standard_data['doc_num']}")
    if standard_data.get("eff_status"):
        overview_lines.append(f"Tình trạng hiệu lực: {standard_data['eff_status']}")
    if standard_data.get("effective_date"):
        overview_lines.append(f"Ngày có hiệu lực: {standard_data['effective_date']}")
    if standard_data.get("scope"):
        overview_lines.append(f"Phạm vi: {standard_data['scope']}")
    overview_lines.append(f"Trạng thái: {standard_data.get('status', 'active')}")
    if standard_data.get("supersedes"):
        overview_lines.append(f"Thay thế: {standard_data['supersedes']}")
    if standard_data.get("related_standards"):
        overview_lines.append(f"Tiêu chuẩn liên quan: {', '.join(standard_data['related_standards'])}")
    if standard_data.get("full_text") is False:
        overview_lines.append("Lưu ý: chưa có toàn văn quy chuẩn dạng chữ (chỉ có văn bản ban hành hoặc bản scan).")

    chunks.append({
        "text": "\n".join(overview_lines),
        "metadata": {
            **base_meta,
            "chunk_type": "overview",
            "related_standards": standard_data.get("related_standards", []),
        },
    })

    # Chunk per article (split when long), with chapter/section context
    for chapter in standard_data.get("chapters", []):
        ch_label = chapter_label(chapter)

        for section in chapter.get("sections", []):
            section_label = f"Mục {section['number']}: {section['title']}".rstrip(": ")

            for article in section.get("articles", []):
                content = article["content"]
                numbered = content.startswith(f"{article['number']} ")
                body = content if numbered else f"Điều {article['number']}: {article['title']}\n{content}"

                requirements_text = _format_requirements(article.get("requirements", []))
                pieces = split_text(body)
                for idx, piece in enumerate(pieces):
                    part = f" (phần {idx + 1}/{len(pieces)})" if len(pieces) > 1 else ""
                    if overlap_context:
                        chunk_text = f"{tag}[{standard_code}] {standard_name}\n{ch_label} > {section_label}{part}\n\n{piece}"
                    else:
                        chunk_text = f"{tag}{piece}"
                    if requirements_text and idx == len(pieces) - 1 and not standard_data.get("doc_num"):
                        # hand-written sample data states requirements separately from the text
                        chunk_text += f"\n\n{requirements_text}"

                    chunks.append({
                        "text": chunk_text,
                        "metadata": {
                            **base_meta,
                            "chapter_number": chapter["number"],
                            "chapter_title": chapter.get("title", ""),
                            "chapter_kind": chapter.get("kind", "chapter"),
                            "section_number": section["number"],
                            "section_title": section["title"],
                            "article_number": article["number"],
                            "article_title": article["title"],
                            "chunk_type": "article",
                            "part": idx + 1,
                            "parts": len(pieces),
                            "has_requirements": len(article.get("requirements", [])) > 0,
                        },
                    })

    return chunks


def _format_requirements(requirements: list[dict]) -> str:
    """Format requirements into human-readable text."""
    if not requirements:
        return ""

    lines = ["Yêu cầu kỹ thuật:"]
    for req in requirements:
        description = req.get("description", "")
        lines.append(f"• {description}")

        values = req.get("values", {})
        if isinstance(values, dict):
            for key, val in values.items():
                if isinstance(val, dict):
                    val_str = ", ".join(f"{k}: {v}" for k, v in val.items())
                    lines.append(f"  - {key}: {val_str}")
                else:
                    lines.append(f"  - {key}: {val}")

        # Single value requirements
        if "min_value" in req:
            unit = req.get("unit", "")
            lines.append(f"  Giá trị tối thiểu: {req['min_value']} {unit}")
        if "max_value" in req:
            unit = req.get("unit", "")
            lines.append(f"  Giá trị tối đa: {req['max_value']} {unit}")
        if "condition" in req:
            lines.append(f"  Điều kiện: {req['condition']}")
        if "exception" in req:
            lines.append(f"  Ngoại lệ: {req['exception']}")

    return "\n".join(lines)


def chunk_from_json_file(filepath: str) -> list[dict]:
    """Load a JSON standard file and chunk it.

    Args:
        filepath: Path to the JSON file.

    Returns:
        List of chunks.
    """
    with open(filepath, "r", encoding="utf-8") as f:
        data = json.load(f)
    return chunk_standard(data)
