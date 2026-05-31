"""Smart chunker for QCVN/TCVN documents.

Chia nhỏ văn bản quy chuẩn theo cấu trúc phân cấp (Chương → Mục → Điều → Khoản)
thay vì cắt cơ học theo số ký tự. Có overlap giữa các chunks.
"""

import json
from typing import Any


def chunk_standard(standard_data: dict, overlap_context: bool = True) -> list[dict]:
    """Chunk a structured QCVN/TCVN standard into embeddable pieces.

    Each chunk preserves hierarchical context:
    - Standard code + name (always included)
    - Chapter title
    - Section title
    - Article content + requirements

    Args:
        standard_data: Parsed standard data (from sample_data_generator or qcvn_parser).
        overlap_context: If True, include parent context in each chunk for better retrieval.

    Returns:
        List of chunks ready for embedding.
    """
    chunks = []
    standard_code = standard_data["standard_code"]
    standard_name = standard_data["standard_name"]
    standard_year = standard_data.get("year", "")

    # Chunk 1: Standard overview
    overview_text = (
        f"{standard_code} — {standard_name}\n"
        f"Năm ban hành: {standard_year}\n"
        f"Cơ quan ban hành: {standard_data.get('issuing_body', '')}\n"
        f"Phạm vi: {standard_data.get('scope', '')}\n"
        f"Trạng thái: {standard_data.get('status', 'active')}"
    )
    if standard_data.get("supersedes"):
        overview_text += f"\nThay thế: {standard_data['supersedes']}"
    if standard_data.get("related_standards"):
        overview_text += f"\nTiêu chuẩn liên quan: {', '.join(standard_data['related_standards'])}"

    chunks.append({
        "text": overview_text,
        "metadata": {
            "standard_code": standard_code,
            "standard_name": standard_name,
            "chunk_type": "overview",
            "year": standard_year,
            "related_standards": standard_data.get("related_standards", []),
        },
    })

    # Chunk per article (with chapter/section context)
    for chapter in standard_data.get("chapters", []):
        chapter_title = f"Chương {chapter['number']}: {chapter['title']}"

        for section in chapter.get("sections", []):
            section_title = f"Mục {section['number']}: {section['title']}"

            for article in section.get("articles", []):
                # Build chunk text with hierarchical context
                if overlap_context:
                    chunk_text = (
                        f"[{standard_code}] {standard_name}\n"
                        f"{chapter_title} > {section_title}\n\n"
                        f"Điều {article['number']}: {article['title']}\n"
                        f"{article['content']}"
                    )
                else:
                    chunk_text = (
                        f"Điều {article['number']}: {article['title']}\n"
                        f"{article['content']}"
                    )

                # Add requirements as part of chunk text
                requirements_text = _format_requirements(article.get("requirements", []))
                if requirements_text:
                    chunk_text += f"\n\n{requirements_text}"

                chunks.append({
                    "text": chunk_text,
                    "metadata": {
                        "standard_code": standard_code,
                        "standard_name": standard_name,
                        "chapter_number": chapter["number"],
                        "chapter_title": chapter["title"],
                        "section_number": section["number"],
                        "section_title": section["title"],
                        "article_number": article["number"],
                        "article_title": article["title"],
                        "chunk_type": "article",
                        "year": standard_year,
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
        req_type = req.get("type", "")
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
