"""QCVN/TCVN PDF Parser.

Extracts structured content from Vietnamese building standard PDF documents.
Handles hierarchical structure: Chương → Mục → Điều → Khoản.
"""

import re
import json
import os
from dataclasses import dataclass, field, asdict
from typing import Optional

import fitz  # PyMuPDF


@dataclass
class ParsedArticle:
    number: str
    title: str
    content: str
    requirements: list = field(default_factory=list)


@dataclass
class ParsedSection:
    number: str
    title: str
    articles: list = field(default_factory=list)


@dataclass
class ParsedChapter:
    number: int
    title: str
    sections: list = field(default_factory=list)


@dataclass
class ParsedStandard:
    standard_code: str = ""
    standard_name: str = ""
    year: int = 0
    issuing_body: str = ""
    status: str = "active"
    scope: str = ""
    supersedes: str = ""
    related_standards: list = field(default_factory=list)
    chapters: list = field(default_factory=list)
    raw_text: str = ""


# ===== Regex Patterns for Vietnamese Standards =====

# Match: "QCVN 06:2022/BXD" or "TCVN 2737:2023"
RE_STANDARD_CODE = re.compile(
    r'((?:QCVN|TCVN)\s*\d+(?:\.\d+)?(?::\d{4})?(?:/[A-Z]+)?)',
    re.IGNORECASE,
)

# Match: "CHƯƠNG 1", "CHƯƠNG I", "Chương 2"
RE_CHAPTER = re.compile(
    r'^(?:CHƯƠNG|Chương|CHUONG)\s+(\d+|[IVXLC]+)[\s.:–\-]+(.+?)$',
    re.MULTILINE,
)

# Match: "1.1", "1.2.", "2.3" at start of line — section markers
RE_SECTION = re.compile(
    r'^(\d+\.\d+)\.?\s+(.+?)$',
    re.MULTILINE,
)

# Match: "Điều 1.", "Điều 2.1.", "Điều 12" — article markers
RE_ARTICLE = re.compile(
    r'^(?:Điều|ĐIỀU|Dieu)\s+(\d+(?:\.\d+)*)\.?\s*[–\-:]?\s*(.+?)$',
    re.MULTILINE,
)

# Match: "1)", "a)", "1.", "a." — clause/point markers
RE_CLAUSE = re.compile(
    r'^(\d+|[a-z])[)\.]\s+(.+)',
    re.MULTILINE,
)

# Match: "Bảng 1", "Bảng 2.1" — table references
RE_TABLE_REF = re.compile(
    r'(?:Bảng|BẢNG)\s+(\d+(?:\.\d+)*)',
)

# Match year from standard code
RE_YEAR = re.compile(r':(\d{4})')

# Match supersedes references: "thay thế QCVN..."
RE_SUPERSEDES = re.compile(
    r'thay\s+thế\s+((?:QCVN|TCVN)\s*\d+(?:\.\d+)?(?::\d{4})?(?:/[A-Z]+)?)',
    re.IGNORECASE,
)


def parse_pdf(filepath: str) -> ParsedStandard:
    """Parse a QCVN/TCVN PDF file into structured data.

    Args:
        filepath: Path to the PDF file.

    Returns:
        ParsedStandard with hierarchical content.
    """
    doc = fitz.open(filepath)
    standard = ParsedStandard()

    # Step 1: Extract all text
    full_text = ""
    for page_num in range(len(doc)):
        page = doc[page_num]
        text = page.get_text("text")
        # Clean up common PDF artifacts
        text = _clean_text(text)
        full_text += text + "\n"

    doc.close()
    standard.raw_text = full_text

    # Step 2: Extract metadata from first pages
    _extract_metadata(standard, full_text[:3000])

    # Step 3: Parse hierarchical structure
    _parse_structure(standard, full_text)

    # Step 4: Extract cross-references
    _extract_references(standard, full_text)

    return standard


def _clean_text(text: str) -> str:
    """Clean common PDF extraction artifacts."""
    # Remove page numbers (standalone numbers at end of line)
    text = re.sub(r'\n\s*\d+\s*\n', '\n', text)
    # Remove excessive whitespace
    text = re.sub(r'[ \t]+', ' ', text)
    # Remove excessive newlines
    text = re.sub(r'\n{4,}', '\n\n\n', text)
    # Fix broken words (hyphenation at line break)
    text = re.sub(r'-\n(\S)', r'\1', text)
    return text.strip()


def _extract_metadata(standard: ParsedStandard, header_text: str):
    """Extract standard metadata from header/first pages."""
    # Standard code
    code_match = RE_STANDARD_CODE.search(header_text)
    if code_match:
        standard.standard_code = code_match.group(1).strip()

    # Year
    year_match = RE_YEAR.search(standard.standard_code)
    if year_match:
        standard.year = int(year_match.group(1))

    # Issuing body
    if "BXD" in standard.standard_code.upper():
        standard.issuing_body = "Bộ Xây dựng"
    elif "BKHCN" in standard.standard_code.upper():
        standard.issuing_body = "Bộ Khoa học và Công nghệ"
    elif standard.standard_code.upper().startswith("TCVN"):
        standard.issuing_body = "Bộ Khoa học và Công nghệ"

    # Standard name — usually on the line after the code
    lines = header_text.split('\n')
    for i, line in enumerate(lines):
        if RE_STANDARD_CODE.search(line):
            # Look at next non-empty lines for the name
            name_parts = []
            for j in range(i + 1, min(i + 5, len(lines))):
                next_line = lines[j].strip()
                if next_line and not next_line.startswith(('Số', 'Ban hành', 'Hà Nội')):
                    name_parts.append(next_line)
                    if len(name_parts) >= 2:
                        break
            if name_parts:
                standard.standard_name = ' '.join(name_parts)
            break

    # Supersedes
    supersedes_match = RE_SUPERSEDES.search(header_text)
    if supersedes_match:
        standard.supersedes = supersedes_match.group(1).strip()

    # Scope — look for "Phạm vi" section
    scope_match = re.search(
        r'(?:Phạm vi|PHẠM VI).*?(?:điều chỉnh|áp dụng)[:\s]*(.+?)(?:\n\n|\d+\.\d+)',
        header_text,
        re.DOTALL | re.IGNORECASE,
    )
    if scope_match:
        standard.scope = scope_match.group(1).strip()[:500]


def _parse_structure(standard: ParsedStandard, text: str):
    """Parse document into Chapters → Sections → Articles."""
    # Find all chapter positions
    chapter_matches = list(RE_CHAPTER.finditer(text))

    if chapter_matches:
        for i, match in enumerate(chapter_matches):
            chapter_num = _parse_roman_or_int(match.group(1))
            chapter_title = match.group(2).strip()

            # Get chapter text (from this match to next chapter or end)
            start = match.end()
            end = chapter_matches[i + 1].start() if i + 1 < len(chapter_matches) else len(text)
            chapter_text = text[start:end]

            chapter = ParsedChapter(
                number=chapter_num,
                title=chapter_title,
            )

            # Parse articles within this chapter
            _parse_articles_in_block(chapter, chapter_text, standard.standard_code)

            standard.chapters.append(chapter)
    else:
        # No chapter markers found — treat entire doc as one chapter
        chapter = ParsedChapter(number=1, title="Nội dung chính")
        _parse_articles_in_block(chapter, text, standard.standard_code)
        if chapter.sections:
            standard.chapters.append(chapter)


def _parse_articles_in_block(chapter: ParsedChapter, text: str, standard_code: str):
    """Parse articles within a chapter/section block."""
    article_matches = list(RE_ARTICLE.finditer(text))

    if not article_matches:
        # No articles found — create a single section with the text
        if text.strip():
            section = ParsedSection(
                number=str(chapter.number),
                title=chapter.title,
                articles=[ParsedArticle(
                    number=f"{chapter.number}.1",
                    title=chapter.title,
                    content=text.strip()[:2000],
                )],
            )
            chapter.sections.append(section)
        return

    # Group articles into sections (using section markers if present)
    current_section = ParsedSection(
        number=str(chapter.number),
        title=chapter.title,
    )

    for i, match in enumerate(article_matches):
        art_number = match.group(1).strip()
        art_title = match.group(2).strip()

        # Get article content
        start = match.end()
        end = article_matches[i + 1].start() if i + 1 < len(article_matches) else len(text)
        art_content = text[start:end].strip()

        # Truncate very long articles
        if len(art_content) > 3000:
            art_content = art_content[:3000] + "..."

        article = ParsedArticle(
            number=art_number,
            title=art_title,
            content=art_content,
        )

        # Try to extract numerical requirements from the content
        _extract_requirements(article)

        current_section.articles.append(article)

    if current_section.articles:
        chapter.sections.append(current_section)


def _extract_requirements(article: ParsedArticle):
    """Extract numerical requirements from article content."""
    content = article.content

    # Pattern: "không nhỏ hơn X m/mm/kN/..."
    min_matches = re.findall(
        r'(?:không\s+nhỏ\s+hơn|tối\s+thiểu|≥|>=)\s*([\d.,]+)\s*(m²|m³|m|mm|kN(?:/m[²³])?|phút|%|kg)',
        content,
        re.IGNORECASE,
    )
    for value, unit in min_matches:
        article.requirements.append({
            "type": "minimum_dimension",
            "description": f"Giá trị tối thiểu từ Điều {article.number}",
            "min_value": float(value.replace(',', '.')),
            "unit": unit,
        })

    # Pattern: "không lớn hơn X m/mm/..."
    max_matches = re.findall(
        r'(?:không\s+lớn\s+hơn|không\s+quá|tối\s+đa|≤|<=)\s*([\d.,]+)\s*(m²|m³|m|mm|kN(?:/m[²³])?|phút|%|kg)',
        content,
        re.IGNORECASE,
    )
    for value, unit in max_matches:
        article.requirements.append({
            "type": "maximum_dimension",
            "description": f"Giá trị tối đa từ Điều {article.number}",
            "max_value": float(value.replace(',', '.')),
            "unit": unit,
        })


def _extract_references(standard: ParsedStandard, text: str):
    """Extract references to other standards."""
    all_codes = RE_STANDARD_CODE.findall(text)
    seen = set()
    for code in all_codes:
        code = code.strip()
        if code != standard.standard_code and code not in seen:
            seen.add(code)
            standard.related_standards.append(code)


def _parse_roman_or_int(value: str) -> int:
    """Convert Roman numeral or integer string to int."""
    try:
        return int(value)
    except ValueError:
        roman_map = {'I': 1, 'V': 5, 'X': 10, 'L': 50, 'C': 100}
        result = 0
        prev = 0
        for char in reversed(value.upper()):
            curr = roman_map.get(char, 0)
            if curr < prev:
                result -= curr
            else:
                result += curr
            prev = curr
        return result if result > 0 else 1


def to_dict(standard: ParsedStandard) -> dict:
    """Convert ParsedStandard to dict (JSON-serializable)."""
    return {
        "standard_code": standard.standard_code,
        "standard_name": standard.standard_name,
        "year": standard.year,
        "issuing_body": standard.issuing_body,
        "status": standard.status,
        "scope": standard.scope,
        "supersedes": standard.supersedes,
        "related_standards": standard.related_standards,
        "chapters": [
            {
                "number": ch.number,
                "title": ch.title,
                "sections": [
                    {
                        "number": sec.number,
                        "title": sec.title,
                        "articles": [
                            {
                                "number": art.number,
                                "title": art.title,
                                "content": art.content,
                                "requirements": art.requirements,
                            }
                            for art in sec.articles
                        ],
                    }
                    for sec in ch.sections
                ],
            }
            for ch in standard.chapters
        ],
    }


def parse_pdf_to_json(pdf_path: str, output_dir: str = None) -> str:
    """Parse a PDF and save as structured JSON.

    Args:
        pdf_path: Path to the PDF file.
        output_dir: Directory to save JSON output. If None, saves next to PDF.

    Returns:
        Path to the created JSON file.
    """
    standard = parse_pdf(pdf_path)
    data = to_dict(standard)

    # Determine output path
    basename = os.path.splitext(os.path.basename(pdf_path))[0]
    # Clean filename
    basename = re.sub(r'[^\w\s\-]', '_', basename)

    if output_dir:
        os.makedirs(output_dir, exist_ok=True)
        json_path = os.path.join(output_dir, f"{basename}.json")
    else:
        json_path = os.path.splitext(pdf_path)[0] + ".json"

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    # Stats
    total_articles = sum(
        len(art)
        for ch in data["chapters"]
        for sec in ch["sections"]
        for art in [sec["articles"]]
    )
    print(f"✅ Parsed: {pdf_path}")
    print(f"   Code: {data['standard_code'] or 'N/A'}")
    print(f"   Name: {data['standard_name'][:80] or 'N/A'}")
    print(f"   Chapters: {len(data['chapters'])}, Articles: {total_articles}")
    print(f"   Output: {json_path}")

    return json_path


def parse_directory(pdf_dir: str, output_dir: str = "data/qcvn") -> list[str]:
    """Parse all PDFs in a directory.

    Args:
        pdf_dir: Directory containing PDF files.
        output_dir: Directory to save JSON outputs.

    Returns:
        List of created JSON file paths.
    """
    if not os.path.exists(pdf_dir):
        print(f"⚠️ Directory not found: {pdf_dir}")
        return []

    pdf_files = [f for f in os.listdir(pdf_dir) if f.lower().endswith('.pdf')]
    if not pdf_files:
        print(f"⚠️ No PDF files found in: {pdf_dir}")
        return []

    print(f"📄 Found {len(pdf_files)} PDF files in {pdf_dir}")
    print("=" * 60)

    created = []
    for filename in sorted(pdf_files):
        filepath = os.path.join(pdf_dir, filename)
        try:
            json_path = parse_pdf_to_json(filepath, output_dir)
            created.append(json_path)
        except Exception as e:
            print(f"❌ Failed: {filename} — {e}")

    print("=" * 60)
    print(f"📊 Parsed {len(created)}/{len(pdf_files)} files successfully")
    return created


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        path = sys.argv[1]
        if os.path.isdir(path):
            parse_directory(path)
        else:
            parse_pdf_to_json(path, "data/qcvn")
    else:
        print("Usage: python qcvn_parser.py <pdf_file_or_directory>")
