"""Metadata extractor for QCVN/TCVN documents.

Enhanced metadata extraction using LLM for complex/messy PDFs
where regex-based extraction fails.
"""

import json
import re
from typing import Optional

from google import genai
from google.genai.types import GenerateContentConfig

from src.core.config import get_settings

settings = get_settings()


def extract_metadata_llm(text: str, max_chars: int = 4000) -> dict:
    """Use Gemini to extract structured metadata from document text.

    Useful when regex fails on messy PDF extractions.

    Args:
        text: Raw text from the first pages of a document.
        max_chars: Max characters to send to LLM.

    Returns:
        Dict with standard_code, standard_name, year, issuing_body, scope, supersedes.
    """
    client = genai.Client(api_key=settings.gemini_api_key)

    prompt = f"""Phân tích đoạn văn bản dưới đây từ một quy chuẩn/tiêu chuẩn xây dựng Việt Nam.
Trích xuất thông tin sau và trả về JSON:

{{
    "standard_code": "",      // Mã: "QCVN 06:2022/BXD" hoặc "TCVN 2737:2023"
    "standard_name": "",      // Tên đầy đủ
    "year": 0,                // Năm ban hành
    "issuing_body": "",       // Cơ quan: "Bộ Xây dựng" hoặc "Bộ KH&CN"
    "scope": "",              // Phạm vi áp dụng (tóm tắt 1-2 câu)
    "supersedes": ""          // Mã tiêu chuẩn được thay thế (nếu có)
}}

Văn bản:
---
{text[:max_chars]}
---

Chỉ trả về JSON, không giải thích."""

    try:
        response = client.models.generate_content(
            model=settings.llm_model,
            contents=prompt,
            config=GenerateContentConfig(temperature=0.0, max_output_tokens=500),
        )
        result_text = response.text.strip()
        # Extract JSON from response
        if "```" in result_text:
            result_text = result_text.split("```")[1]
            if result_text.startswith("json"):
                result_text = result_text[4:]
        return json.loads(result_text)
    except Exception as e:
        print(f"⚠️ LLM metadata extraction failed: {e}")
        return {}


def enrich_metadata(parsed_data: dict, raw_text: str = "") -> dict:
    """Enrich parsed data with additional metadata.

    Fills in missing fields using regex and LLM fallback.

    Args:
        parsed_data: Already parsed standard data dict.
        raw_text: Full raw text (for LLM fallback).

    Returns:
        Enriched data dict.
    """
    # Check if critical fields are missing
    missing_fields = []
    if not parsed_data.get("standard_code"):
        missing_fields.append("standard_code")
    if not parsed_data.get("standard_name"):
        missing_fields.append("standard_name")

    if missing_fields and raw_text:
        print(f"  ℹ️ Missing: {', '.join(missing_fields)} — trying LLM extraction...")
        llm_meta = extract_metadata_llm(raw_text)
        for field in missing_fields:
            if llm_meta.get(field):
                parsed_data[field] = llm_meta[field]

        # Fill other fields if still empty
        for key in ["year", "issuing_body", "scope", "supersedes"]:
            if not parsed_data.get(key) and llm_meta.get(key):
                parsed_data[key] = llm_meta[key]

    return parsed_data
