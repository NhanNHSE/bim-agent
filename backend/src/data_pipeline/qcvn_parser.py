"""QCVN/TCVN PDF Parser.

Turns a standalone regulation PDF into the structured JSON consumed by the chunker and the
graph builder. Structure detection lives in `qcvn_text_parser` (numbered clauses x.y.z and
annexes A.1.1, with "Điều N" / plain-block fallbacks); this module adds PDF text extraction,
scan detection and metadata.

For the vbpl.vn crawl use `vbpl_corpus.build_corpus` instead: it also picks the best source
per document and carries validity from the catalog.
"""

import json
import os
import re

from src.data_pipeline.qcvn_text_parser import (
    detect_codes,
    parse_regulation_text,
    strip_page_furniture,
)

# Average characters per page below which a PDF is treated as a scan (needs OCR)
SCAN_MAX_CHARS_PER_PAGE = 100


class ScannedPDFError(ValueError):
    """The PDF has (almost) no text layer — it needs OCR before it can be parsed."""


def extract_pdf_text(pdf_path: str) -> str:
    import fitz  # PyMuPDF

    with fitz.open(pdf_path) as doc:
        pages = [page.get_text("text") for page in doc]
    if sum(len(p.strip()) for p in pages) < SCAN_MAX_CHARS_PER_PAGE * max(len(pages), 1):
        raise ScannedPDFError(f"{pdf_path}: no text layer ({len(pages)} pages) — OCR required")
    return strip_page_furniture(pages)


def parse_text_to_dict(text: str, fallback_name: str = "") -> dict:
    """Structured standard dict from plain regulation text."""
    result = parse_regulation_text(text)
    codes = detect_codes(text)
    code = codes[0] if codes else fallback_name
    year = re.search(r":(\d{4})", code)
    name = next(
        (ln.strip() for ln in text[:6000].split("\n") if re.match(r"^\s*QUY\s+CHUẨN\s+KỸ\s+THUẬT", ln, re.IGNORECASE)),
        fallback_name,
    )
    return {
        "standard_code": code,
        "standard_name": name,
        "year": int(year.group(1)) if year else 0,
        "issuing_body": "",
        "status": "active",
        "scope": "",
        "supersedes": "",
        "related_standards": codes[1:16],
        "source_id": f"pdf:{fallback_name or code}",
        "full_text": result.clause_count >= 3,
        "parse": {"structure": result.structure, "clauses": result.clause_count, "coverage": round(result.coverage, 4)},
        "chapters": result.chapters,
    }


def parse_pdf(pdf_path: str) -> dict:
    """Parse a regulation PDF into a structured dict (raises ScannedPDFError for scans)."""
    basename = os.path.splitext(os.path.basename(pdf_path))[0]
    return parse_text_to_dict(extract_pdf_text(pdf_path), fallback_name=basename)


def parse_pdf_to_json(pdf_path: str, output_dir: str = None) -> str:
    """Parse a PDF and save as structured JSON.

    Args:
        pdf_path: Path to the PDF file.
        output_dir: Directory to save JSON output. If None, saves next to PDF.

    Returns:
        Path to the created JSON file.
    """
    data = parse_pdf(pdf_path)

    basename = re.sub(r"[^\w\s\-]", "_", os.path.splitext(os.path.basename(pdf_path))[0])
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)
        json_path = os.path.join(output_dir, f"{basename}.json")
    else:
        json_path = os.path.splitext(pdf_path)[0] + ".json"

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    total_articles = sum(len(sec["articles"]) for ch in data["chapters"] for sec in ch["sections"])
    print(f"✅ Parsed: {pdf_path}")
    print(f"   Code: {data['standard_code'] or 'N/A'}")
    print(f"   Name: {data['standard_name'][:80] or 'N/A'}")
    print(f"   Structure: {data['parse']['structure']}, clauses: {data['parse']['clauses']}, "
          f"coverage: {data['parse']['coverage']:.1%}")
    print(f"   Chapters: {len(data['chapters'])}, Articles: {total_articles}")
    print(f"   Output: {json_path}")
    return json_path


def parse_directory(pdf_dir: str, output_dir: str) -> list[str]:
    """Parse all PDFs in a directory; scans are reported and skipped.

    Args:
        pdf_dir: Directory containing PDF files.
        output_dir: Directory to save JSON outputs.

    Returns:
        List of created JSON file paths.
    """
    if not os.path.exists(pdf_dir):
        print(f"⚠️ Directory not found: {pdf_dir}")
        return []

    pdf_files = [f for f in os.listdir(pdf_dir) if f.lower().endswith(".pdf")]
    if not pdf_files:
        print(f"⚠️ No PDF files found in: {pdf_dir}")
        return []

    print(f"📄 Found {len(pdf_files)} PDF files in {pdf_dir}")
    print("=" * 60)

    created = []
    for filename in sorted(pdf_files):
        filepath = os.path.join(pdf_dir, filename)
        try:
            created.append(parse_pdf_to_json(filepath, output_dir))
        except ScannedPDFError as e:
            print(f"⏭️  Skipped scan: {e}")
        except Exception as e:
            print(f"❌ Failed: {filename} — {e}")

    print("=" * 60)
    print(f"📊 Parsed {len(created)}/{len(pdf_files)} files successfully")
    return created


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 2:
        path, out = sys.argv[1], sys.argv[2]
        parse_directory(path, out) if os.path.isdir(path) else parse_pdf_to_json(path, out)
    else:
        print("Usage: python -m src.data_pipeline.qcvn_parser <pdf_file_or_directory> <output_dir>")
