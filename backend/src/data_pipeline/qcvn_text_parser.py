"""Structure parser for real QCVN text (PDF / DOCX / HTML-derived plain text).

Real QCVN documents are numbered clause by clause, not by "Chương/Điều":

    1 QUY ĐỊNH CHUNG                 -> chapter "1"
    1.1 Phạm vi điều chỉnh            -> section "1.1"
    1.1.1 Quy chuẩn này quy định ...  -> article "1.1.1" (deeper levels 1.1.1.1 stay inside it)
    PHỤ LỤC A (quy định) ...          -> annex chapter "A" with clauses A.1, A.1.1 ...

Text before the first chapter (issuing circular, foreword) becomes a "preamble" chapter "0".
Nothing is dropped except tables of contents and repeated page headers/footers: a line that
does not start a recognised clause is appended to the clause being read, so
`ParseResult.coverage` (kept chars / input chars) stays close to 1.

Output follows the JSON schema used by `chunker.chunk_standard` and `graph_builder`:
chapters -> sections -> articles {number, title, content, requirements}.
"""

from __future__ import annotations

import bisect
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass, field

# ---------------------------------------------------------------- patterns --
_CLAUSE = re.compile(r"^((?:\d{1,2}|[A-ZĐ])(?:\.\d{1,3}){1,5})\.?(?:\s+(.*))?$")
_NUMBER_ONLY = re.compile(r"^(?:\d{1,2}|[A-ZĐ])(?:\.\d{1,3}){1,5}\.?$")
_CHAPTER_NUM = re.compile(r"^(\d{1,2})\.?\s+(\S.*)$")
_CHAPTER_WORD = re.compile(r"^(?:CHƯƠNG|Chương|PHẦN|Phần)\s+(\d{1,2}|[IVX]{1,5})\b[.:]?\s*(.*)$")
_ANNEX = re.compile(r"^(?:PHỤ\s+LỤC|Phụ\s+lục)\s+([A-ZĐ])\b[.:]?\s*(.*)$")
_DIEU = re.compile(r"^Điều\s+(\d{1,3})\s*[.:]?\s*(.*)$")
_TOC_LEADER = re.compile(r"(?:\.{4,}|…{2,}|[.…]{3,})\s*\d{1,4}\s*$")
_PAGE_NUMBER = re.compile(r"^(?:-\s*)?\d{1,4}(?:\s*-)?$|^Trang\s+\d+", re.IGNORECASE)
# a "clause" whose text starts with a unit or a number is a measurement / table row ("2.5 m", "1.2 3.4")
_MEASUREMENT = re.compile(r"^(?:\d|mm\b|cm\b|m\b|m2|m²|m3|m³|%|kg|kN|MPa|ha\b|km\b|°|lux\b|dB\b|giờ\b|phút\b|lần\b)")
_LIST_ITEM = re.compile(r"^(?:[a-zđ]\)|[-–+•●▪*]\s|\d{1,2}\)\s|[ivx]{1,4}\)\s)")
_QCVN_CODE = re.compile(r"\b(QC(?:XD)?VN)\s*([\d\-]+)\s*:\s*(\d{4})\s*/\s*([A-ZĐ]{2,8})")

MIN_CLAUSES = 3  # fewer numbered clauses than this -> fall back to "Điều N" or plain blocks
BLOCK_CHARS = 1500  # size of plain-text blocks in the last-resort fallback


# --------------------------------------------------------------- data model --
@dataclass
class _Clause:
    number: str
    lines: list[str] = field(default_factory=list)


@dataclass
class _Chapter:
    number: str
    kind: str  # "preamble" | "chapter" | "annex" | "text"
    title: str
    clauses: list[_Clause] = field(default_factory=list)
    body: list[str] = field(default_factory=list)  # text before the first clause


@dataclass
class ParseResult:
    chapters: list[dict]
    structure: str  # "numbered" | "dieu" | "blocks"
    clause_count: int
    input_chars: int
    output_chars: int

    @property
    def coverage(self) -> float:
        return self.output_chars / self.input_chars if self.input_chars else 1.0


# ------------------------------------------------------------------ helpers --
def normalize(text: str) -> str:
    """NFC, unify whitespace and dashes, keep line breaks."""
    text = unicodedata.normalize("NFC", text).replace("\r\n", "\n").replace("\r", "\n")
    text = text.replace(" ", " ").replace("​", "").replace("\t", " ")
    return "\n".join(re.sub(r" {2,}", " ", line).strip() for line in text.split("\n"))


def _is_upper(text: str) -> bool:
    letters = [c for c in text if c.isalpha()]
    return len(letters) >= 3 and all(c.isupper() for c in letters)


def strip_page_furniture(pages: list[str]) -> str:
    """Join PDF pages, dropping running headers/footers and page numbers.

    A line is furniture when it sits in the first/last 4 lines of a page and either is a
    page number or repeats (after removing digits) on at least 30% of the pages.
    """
    page_lines = [[ln for ln in normalize(p).split("\n") if ln] for p in pages]
    if len(page_lines) < 3:
        return "\n".join("\n".join(lines) for lines in page_lines)

    def key(line: str) -> str:
        return re.sub(r"\d+", "#", line)

    def keys(line: str) -> set[str]:
        # exact text, plus a digit-insensitive form for short lines ("Trang 12", "CÔNG BÁO/Số 921...")
        return {line, key(line)} if len(line.split()) <= 6 else {line}

    edge_counts: Counter = Counter()
    for lines in page_lines:
        edge_counts.update(set().union(*(keys(ln) for ln in set(lines[:4] + lines[-4:]))) if lines else set())
    threshold = max(3, int(0.3 * len(page_lines)))
    repeated = {k for k, n in edge_counts.items() if n >= threshold}

    out = []
    for lines in page_lines:
        n = len(lines)
        for i, ln in enumerate(lines):
            at_edge = i < 4 or i >= n - 4
            if at_edge and (_PAGE_NUMBER.match(ln) or keys(ln) & repeated):
                continue
            out.append(ln)
    return "\n".join(out)


def _prepare_lines(text: str) -> list[str]:
    """Normalised non-empty lines; TOC lines dropped; lone clause numbers joined to the next line."""
    raw = [ln for ln in normalize(text).split("\n") if ln and not _TOC_LEADER.search(ln)]
    lines: list[str] = []
    i = 0
    while i < len(raw):
        ln = raw[i]
        nxt = raw[i + 1] if i + 1 < len(raw) else ""
        if _NUMBER_ONLY.match(ln) and nxt and not _MEASUREMENT.match(nxt):
            lines.append(f"{ln.rstrip('.')} {nxt}")
            i += 2
            continue
        if re.fullmatch(r"\d{1,2}\.?", ln) and _is_upper(nxt) and not _CLAUSE.match(nxt):  # "1" / "QUY ĐỊNH CHUNG"
            lines.append(f"{ln.rstrip('.')} {nxt}")
            i += 2
            continue
        lines.append(ln)
        i += 1
    return lines


def reflow(lines: list[str]) -> str:
    """Re-join lines wrapped by PDF layout; keep breaks before list items and after sentence ends."""
    out: list[str] = []
    for ln in lines:
        if out and not _LIST_ITEM.match(ln) and not out[-1].endswith((".", ":", ";", "!", "?")) \
                and not _CLAUSE.match(ln):
            out[-1] = f"{out[-1]} {ln}"
        else:
            out.append(ln)
    return "\n".join(out)


def _first_sentence(text: str, limit: int = 160) -> str:
    text = text.strip()
    m = re.match(r"(.{10,}?[.:;])(?:\s|$)", text)
    title = m.group(1) if m else text
    return title if len(title) <= limit else title[: limit - 1].rstrip() + "…"


def _roman_to_int(value: str) -> str:
    if value.isdigit():
        return value
    numerals = {"I": 1, "V": 5, "X": 10}
    total = 0
    for i, ch in enumerate(value):
        v = numerals[ch]
        total += -v if i + 1 < len(value) and numerals[value[i + 1]] > v else v
    return str(total)


# ------------------------------------------------------------- requirements --
# Longest units first so "mm" is never read as "m"; the lookahead stops "m" matching "mét..." prefixes.
_UNITS = r"(?P<unit>mm²|mm2|mm|cm|m²|m2|m³|m3|m|km|ha|kN/m²|kN/m2|kN/m³|kN|MPa|kg/m³|kg|phút|giờ|%|lux|dB|°C)(?![\w²³/])"
# Vietnamese numbers: "." groups thousands, "," is the decimal mark ("1.500" = 1500, "1,5" = 1.5)
_NUMBER = r"(?P<num>\d{1,3}(?:\.\d{3})+(?:,\d+)?|\d+(?:[.,]\d+)?)"
_MIN_REQ = re.compile(r"(?:không\s+(?:được\s+)?nhỏ\s+hơn|không\s+(?:được\s+)?thấp\s+hơn|tối\s+thiểu(?:\s+là)?|ít\s+nhất(?:\s+là)?|≥|>=)\s*" + _NUMBER + r"\s*" + _UNITS, re.IGNORECASE)
_MAX_REQ = re.compile(r"(?:không\s+(?:được\s+)?lớn\s+hơn|không\s+(?:được\s+)?vượt\s+quá|không\s+quá|tối\s+đa(?:\s+là)?|≤|<=)\s*" + _NUMBER + r"\s*" + _UNITS, re.IGNORECASE)


def parse_vn_number(text: str) -> float:
    """'1.500' -> 1500.0, '1,5' -> 1.5, '2.5' -> 2.5, '12.000,5' -> 12000.5."""
    if re.fullmatch(r"\d{1,3}(?:\.\d{3})+(?:,\d+)?", text):
        text = text.replace(".", "")
    return float(text.replace(",", "."))


def extract_requirements(content: str, article_number: str) -> list[dict]:
    """Numeric minimum/maximum requirements stated in a clause."""
    reqs = []
    for kind, pattern, key in (("minimum", _MIN_REQ, "min_value"), ("maximum", _MAX_REQ, "max_value")):
        for m in pattern.finditer(content):
            start = max(content.rfind(".", 0, m.start()), content.rfind("\n", 0, m.start())) + 1
            end = m.end() + 60
            snippet = re.sub(r"\s+", " ", content[start:end]).strip()
            reqs.append({
                "type": f"{kind}_value",
                "description": f"Điều {article_number}: {snippet[:220]}",
                key: parse_vn_number(m.group("num")),
                "unit": m.group("unit").replace("2", "²").replace("3", "³") if m.group("unit") in ("m2", "m3", "mm2") else m.group("unit"),
            })
    return reqs


def detect_codes(text: str, limit: int = 12000) -> list[str]:
    """QCVN codes in the head of a text, most frequent first ("QCVN 06:2022/BXD")."""
    counts = Counter(f"{p} {n}:{y}/{a}" for p, n, y, a in _QCVN_CODE.findall(text[:limit]))
    return [code for code, _ in counts.most_common()]


# ------------------------------------------------------------------ parsing --
_ANNEX_ORDER = "ABCDĐEFGHIJKLMNOPQRSTUVWXYZ"


def _order_key(number: str) -> tuple:
    """Reading-order key: chapters 1..N, then annexes A, B, ... (Đ sorts after D)."""
    parts = number.split(".")
    head = parts[0]
    rest = tuple(int(p) for p in parts[1:])
    if head.isdigit():
        return (0, int(head), *rest)
    return (1, _ANNEX_ORDER.index(head) if head in _ANNEX_ORDER else 99, *rest)


def _longest_increasing(keys: list[tuple]) -> list[int]:
    """Indices of a longest strictly increasing subsequence (patience sorting, O(n log n))."""
    tails: list[tuple] = []
    tail_idx: list[int] = []
    prev = [-1] * len(keys)
    for i, k in enumerate(keys):
        pos = bisect.bisect_left(tails, k)
        if pos == len(tails):
            tails.append(k)
            tail_idx.append(i)
        else:
            tails[pos] = k
            tail_idx[pos] = i
        prev[i] = tail_idx[pos - 1] if pos else -1
    out, i = [], tail_idx[-1] if tail_idx else -1
    while i != -1:
        out.append(i)
        i = prev[i]
    return out[::-1]


def _heading_title(line: str, top: str) -> str | None:
    """Title if `line` heads chapter/annex `top` ("1 QUY ĐỊNH CHUNG", "Chương 2 ...", "PHỤ LỤC A ...")."""
    if top.isdigit():
        m = re.match(rf"^(?:CHƯƠNG|Chương|PHẦN|Phần)\s+{top}\b[.:]?\s*(.*)$", line)
        if m:
            return m.group(1).strip()
        m = re.match(rf"^{top}\.?\s+(\S.*)$", line)
        if m:
            title = m.group(1).strip()
            if len(re.findall(r"[^\W\d_]{2,}", title)) >= 2 and not _MEASUREMENT.match(title) \
                    and len(title) <= 150 and not title.endswith((",", ";")):
                return title
        return None
    m = _ANNEX.match(line)
    if m and m.group(1) == top and not re.match(r"^[.,;:]", line[m.end(1):]):
        rest = m.group(2).strip()
        return f"Phụ lục {top}" + (f" {rest}" if rest else "")
    return None


def _annex_heading_letter(line: str) -> str | None:
    """Letter of a stand-alone annex heading ("PHỤ LỤC I (tham khảo) ...", "Phụ lục I")."""
    m = _ANNEX.match(line)
    if not m or re.match(r"^[.,;:]", line[m.end(1):]):
        return None
    rest = m.group(2).strip()
    if line.startswith("PHỤ LỤC") or not rest or rest.startswith("("):
        return m.group(1)
    return None


def _parse_numbered(lines: list[str]) -> tuple[list[_Chapter], int]:
    # 1. candidate clause lines ("1.2.3 text", "A.1 text"); measurements and table rows excluded
    cands: list[tuple[int, str, str]] = []
    for i, ln in enumerate(lines):
        m = _CLAUSE.match(ln)
        if m and m.group(2) and not _MEASUREMENT.match(m.group(2).strip()):
            cands.append((i, m.group(1), m.group(2).strip()))
    # QCVN put annexes after the chapters: once a real annex heading appears, numbered lines
    # ("4.1 Hội trường" in an annex table) cannot be chapter clauses. Annex headings listed
    # close together are a table of contents, not the annexes themselves.
    annex_lines = [i for i, ln in enumerate(lines) if _annex_heading_letter(ln)]
    real_annexes = [
        i for k, i in enumerate(annex_lines)
        if not (k > 0 and i - annex_lines[k - 1] <= 8) and not (k + 1 < len(annex_lines) and annex_lines[k + 1] - i <= 8)
    ]
    first_numeric = next((i for i, number, _ in cands if number[0].isdigit()), None)
    cut = next((i for i in real_annexes if first_numeric is not None and i > first_numeric), None)
    if cut is not None:
        cands = [c for c in cands if not (c[1][0].isdigit() and c[0] > cut)]
    # 2. the skeleton = longest run of clause numbers in increasing reading order;
    #    TOC entries, table rows and cross-references fall off it
    picked = [cands[j] for j in _longest_increasing([_order_key(c[1]) for c in cands])]
    clause_at = {i: (number, rest) for i, number, rest in picked}
    first_line = picked[0][0] if picked else len(lines)

    # 3. walk the text: a picked clause opens (or continues) its chapter; other lines extend the
    #    clause being read. Lines just before a chapter's first clause may hold its heading.
    chapters: dict[str, _Chapter] = {}
    preamble = _Chapter("0", "preamble", "Phần mở đầu")
    order: list[_Chapter] = [preamble]
    state = {"chapter": preamble, "clause": None, "title_open": None}
    pending: list[str] = []

    def target() -> list[str]:
        clause = state["clause"]
        return clause.lines if clause is not None else state["chapter"].body

    def open_chapter(top: str) -> _Chapter:
        if top not in chapters:
            chapters[top] = _Chapter(top, "chapter" if top.isdigit() else "annex", "")
            order.append(chapters[top])
        return chapters[top]

    def flush(into: _Chapter | None = None) -> None:
        if into is not None and not into.title:
            for k, ln in enumerate(pending):
                title = _heading_title(ln, into.number)
                if title is not None:
                    target().extend(pending[:k])
                    tail = pending[k + 1:]
                    cont = []
                    for x in tail:  # "(quy định)" / wrapped upper-case title lines
                        if _is_upper(x) or x.startswith("("):
                            cont.append(x)
                        else:
                            break
                    into.title = " ".join([title, *cont]).strip()
                    into.body.extend(tail[len(cont):])
                    pending.clear()
                    return
        target().extend(pending)
        pending.clear()

    for i, ln in enumerate(lines):
        open_title = state["title_open"]
        state["title_open"] = None
        if open_title is not None and i not in clause_at and (_is_upper(ln) or ln.startswith("("))                 and len(open_title.title) < 200:
            open_title.title = f"{open_title.title} {ln}"
            state["title_open"] = open_title
            continue
        if i in clause_at:
            number, rest = clause_at[i]
            top = number.split(".")[0]
            if top != state["chapter"].number:
                chapter = open_chapter(top)
                flush(chapter)
                state["chapter"] = chapter
            else:
                flush()
            clause = _Clause(number, [rest])
            state["chapter"].clauses.append(clause)
            state["clause"] = clause
            continue
        letter = _annex_heading_letter(ln) if i > first_line else None
        current_key = _order_key((state["chapter"].number if state["chapter"].number != "0" else "1") + ".0")
        if letter and letter not in chapters and _order_key(letter + ".0") > current_key:
            # an annex without numbered clauses (figures, tables): give it its own chapter
            flush()
            chapter = open_chapter(letter)
            chapter.title = _heading_title(ln, letter) or f"Phụ lục {letter}"
            state["chapter"], state["clause"], state["title_open"] = chapter, None, chapter
            continue
        pending.append(ln)
        if len(pending) > 6:  # too far from the next clause to be a heading
            target().append(pending.pop(0))
    flush()
    return [c for c in order if c.clauses or c.body], len(picked)


def _parse_dieu(lines: list[str]) -> list[_Chapter]:
    chapter = _Chapter("1", "text", "Toàn văn")
    clause: _Clause | None = None
    for ln in lines:
        m = _DIEU.match(ln)
        if m:
            clause = _Clause(f"Điều {m.group(1)}", [m.group(2) or f"Điều {m.group(1)}"])
            chapter.clauses.append(clause)
        elif clause is not None:
            clause.lines.append(ln)
        else:
            chapter.body.append(ln)
    return [chapter]


def _parse_blocks(lines: list[str]) -> list[_Chapter]:
    chapter = _Chapter("1", "text", "Toàn văn")
    block: list[str] = []
    size = 0
    for ln in lines:
        block.append(ln)
        size += len(ln)
        if size >= BLOCK_CHARS:
            chapter.clauses.append(_Clause(f"Đoạn {len(chapter.clauses) + 1}", block))
            block, size = [], 0
    if block:
        chapter.clauses.append(_Clause(f"Đoạn {len(chapter.clauses) + 1}", block))
    return [chapter]


def _to_schema(chapters: list[_Chapter]) -> list[dict]:
    """chapters -> sections (x.y) -> articles (x.y.z; deeper levels folded into their article)."""
    result = []
    for ch in chapters:
        sections: dict[str, dict] = {}
        articles: dict[str, dict] = {}

        def section_for(key: str, title: str = "") -> dict:
            if key not in sections:
                sections[key] = {"number": key, "title": title, "articles": []}
            elif title and not sections[key]["title"]:
                sections[key]["title"] = title
            return sections[key]

        if ch.body:
            sec = section_for("0" if ch.kind == "preamble" else f"{ch.number}.0", ch.title)
            content = reflow(ch.body)
            sec["articles"].append({"number": sec["number"], "title": _first_sentence(ch.title or content),
                                    "content": content, "requirements": []})

        for cl in ch.clauses:
            parts = cl.number.split(".")
            text = reflow(cl.lines)
            if len(parts) < 2:  # "Điều N" / "Đoạn N" fallbacks: one section holds every article
                sec = section_for(ch.number, ch.title)
                art = {"number": cl.number, "title": _first_sentence(cl.lines[0]), "content": text, "requirements": []}
                sec["articles"].append(art)
                continue
            sec_key = ".".join(parts[:2])
            if len(parts) == 2:
                sec = section_for(sec_key, _first_sentence(cl.lines[0], 200))
                # "1.1 Phạm vi điều chỉnh" is a bare heading; "3.1 Bộ Xây dựng hướng dẫn ... ." is a clause
                bare_heading = len(cl.lines) == 1 and len(text) <= 80 and not text.rstrip().endswith((".", ":", ";"))
                if not bare_heading:
                    art = {"number": sec_key, "title": sec["title"], "content": f"{sec_key} {text}", "requirements": []}
                    sec["articles"].append(art)
                    articles[sec_key] = art
                continue
            art_key = ".".join(parts[:3])
            if len(parts) == 3:
                art = {"number": art_key, "title": _first_sentence(cl.lines[0]),
                       "content": f"{art_key} {text}", "requirements": []}
                section_for(sec_key)["articles"].append(art)
                articles[art_key] = art
            else:  # x.y.z.w -> inside x.y.z
                art = articles.get(art_key)
                if art is None:
                    art = {"number": art_key, "title": _first_sentence(cl.lines[0]), "content": "", "requirements": []}
                    section_for(sec_key)["articles"].append(art)
                    articles[art_key] = art
                art["content"] = f"{art['content']}\n{cl.number} {text}".strip()

        for sec in sections.values():
            for art in sec["articles"]:
                art["requirements"] = extract_requirements(art["content"], art["number"])
        if sections:
            result.append({"number": ch.number, "kind": ch.kind, "title": ch.title,
                           "sections": list(sections.values())})
    return result


def parse_regulation_text(text: str) -> ParseResult:
    """Parse plain regulation text into the chapters/sections/articles schema."""
    lines = _prepare_lines(text)
    input_chars = sum(len(ln) for ln in lines)
    chapters, count = _parse_numbered(lines)
    structure = "numbered"
    if count < MIN_CLAUSES:
        dieu = _parse_dieu(lines)
        if len(dieu[0].clauses) >= 2:
            chapters, structure, count = dieu, "dieu", len(dieu[0].clauses)
        else:
            chapters, structure, count = _parse_blocks(lines), "blocks", 0
    schema = _to_schema(chapters)
    output_chars = sum(
        len(re.sub(r"\s+", "", a["content"]))
        for ch in schema for s in ch["sections"] for a in s["articles"]
    ) + sum(  # headings kept as chapter / bare-section titles
        len(re.sub(r"\s+", "", t)) for ch in schema
        for t in [ch["title"], *(s["title"] for s in ch["sections"]
                                 if not any(a["number"] == s["number"] for a in s["articles"]))]
    )
    return ParseResult(
        chapters=schema,
        structure=structure,
        clause_count=count,
        input_chars=sum(len(re.sub(r"\s+", "", ln)) for ln in lines) or input_chars,
        output_chars=output_chars,
    )
