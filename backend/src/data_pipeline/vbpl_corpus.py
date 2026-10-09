"""Turn the vbpl.vn crawl (data/vbpl_bxd) into standard JSON files for ingestion.

For every document in `catalog.json` (written by scripts/crawl_vbpl_bxd.py):
1. Candidate source groups: official supplements, DOCX attachments, text PDFs, the HTML text.
   They usually duplicate each other; the group whose text parses into the most numbered
   clauses wins (ties: more characters).
2. Files of the winning group are bucketed by regulation code — one circular can issue several
   QCVN (QCVN_07-1.docx ... QCVN_07-10.docx) — and each bucket becomes one standard JSON.
3. Validity from vbpl (`effStatus`) is kept on every standard so answers can warn about
   expired regulations. Documents without usable text (scans, legacy .doc, circular only)
   still get a JSON with whatever text exists and `full_text: false`.

The JSON schema is the one `chunker.chunk_standard` and `graph_builder` consume.
"""

from __future__ import annotations

import html as html_lib
import json
import re
import zipfile
from collections import Counter
from pathlib import Path

import structlog

from src.data_pipeline.qcvn_text_parser import (
    ParseResult,
    detect_codes,
    normalize,
    parse_regulation_text,
    strip_page_furniture,
)

logger = structlog.get_logger()

STATUS_MAP = {
    "còn hiệu lực": "active",
    "hết hiệu lực toàn bộ": "expired",
    "hết hiệu lực một phần": "partially_expired",
    "chưa có hiệu lực": "not_yet_effective",
    "ngưng hiệu lực": "suspended",
}
_FILE_PART = re.compile(r"QCVN[\s_]*(\d{1,2})[-_.](\d{1,2})(?!\d)", re.IGNORECASE)
_AMENDMENT = re.compile(r"Sửa\s+đổi\s+(\d+)\s*:\s*(\d{4})", re.IGNORECASE)
_SUPERSEDES = re.compile(
    r"(?:thay\s+thế|bãi\s+bỏ)[^.;]{0,250}?(QCVN\s*[\d\-]+\s*:\s*\d{4}\s*/\s*[A-ZĐ]{2,8})", re.IGNORECASE
)
_CODE = re.compile(r"(QC(?:XD)?VN)\s*([\d\-]+)\s*:\s*(\d{4})\s*/\s*([A-ZĐ]{2,8})")


def status_of(eff_status: str) -> str:
    return STATUS_MAP.get((eff_status or "").strip().lower(), "unknown")


# ------------------------------------------------------------- text loading --
def docx_text(path: Path) -> str:
    """Paragraph text of a .docx (table cells become their own lines)."""
    with zipfile.ZipFile(path) as zf:
        xml = zf.read("word/document.xml").decode("utf-8", errors="replace")
    xml = re.sub(r"</w:p>|</w:tc>", "\n", xml)
    xml = re.sub(r"<w:tab/>|<w:br/>", " ", xml)
    return html_lib.unescape(re.sub(r"<[^>]+>", "", xml))


def pdf_text(path: Path) -> str:
    import fitz  # PyMuPDF

    with fitz.open(path) as doc:
        return strip_page_furniture([page.get_text("text") for page in doc])


def html_txt_body(path: Path) -> str:
    """The crawler's TXT = metadata header + "=====" line + text; return only the text."""
    text = path.read_text(encoding="utf-8")
    parts = re.split(r"^={20,}\s*$", text, maxsplit=1, flags=re.MULTILINE)
    return parts[1] if len(parts) == 2 else text


def load_text(data_dir: Path, kind: str, rel_path: str) -> str:
    path = data_dir / rel_path
    if kind == "html":
        return html_txt_body(path)
    if kind == "docx":
        return docx_text(path)
    if kind == "pdf":
        return pdf_text(path)
    raise ValueError(f"unsupported kind {kind}")


# ------------------------------------------------------------ code / naming --
def _code_parts(code: str) -> tuple[str, str, str, str] | None:
    m = _CODE.match(code)
    return (m.group(1), m.group(2), m.group(3), m.group(4)) if m else None


def standard_code_for(doc: dict, file_name: str, text: str, *, single_regulation: bool) -> str:
    """Regulation code for one source file of `doc`.

    Order: part number in the file name (QCVN_07-1.docx -> QCVN 07-1:2023/BXD), the single
    code in the document title, the code in the file's own text (preferring the issue year,
    since a text also cites older regulations), then a label from the document number.
    Amendments and consolidated texts get a suffix so they never overwrite the base regulation.
    """
    title_codes = doc.get("qcvnCodes") or []
    code = None
    part = _FILE_PART.search(file_name or "")
    if part and title_codes:
        base = _code_parts(title_codes[0])
        if base and base[1].split("-")[0].lstrip("0") == part.group(1).lstrip("0"):
            code = f"{base[0]} {base[1].split('-')[0]}-{int(part.group(2))}:{base[2]}/{base[3]}"
    if code is None and len(title_codes) == 1 and single_regulation:
        code = title_codes[0]
    if code is None:
        detected = detect_codes(text)
        year = (doc.get("issueDate") or "")[:4]
        same_year = [c for c in detected if _code_parts(c) and _code_parts(c)[2] in {year, str(int(year) - 1) if year.isdigit() else ""}]
        code = (same_year or detected or [None])[0]
        if code is None and len(title_codes) == 1:
            code = title_codes[0]
    if code is None:
        code = f"QCVN (văn bản {doc['docNum'].replace(' ', '')})"
    amendment = _AMENDMENT.search(doc.get("title", ""))
    if amendment and "Sửa đổi" not in code:
        code = f"{code} – Sửa đổi {amendment.group(1)}:{amendment.group(2)}"
    if "hợp nhất" in (doc.get("docType") or "").lower():
        code = f"{code} (hợp nhất {doc['docNum'].replace(' ', '')})"
    return code


def standard_name_for(doc: dict, text: str) -> str:
    """'QUY CHUẨN KỸ THUẬT QUỐC GIA VỀ ...' heading of the text, else the document title."""
    lines = [ln for ln in normalize(text[:6000]).split("\n") if ln]
    for i, ln in enumerate(lines):
        if re.match(r"^QUY\s+CHUẨN\s+KỸ\s+THUẬT\s+QUỐC\s+GIA", ln, re.IGNORECASE) and len(ln) > 30:
            name = ln
            for nxt in lines[i + 1:i + 3]:
                if nxt.isupper() and not _CODE.search(nxt):
                    name = f"{name} {nxt}"
            return re.sub(r"\s+", " ", name).strip().capitalize()
    return doc.get("title", "")


# ---------------------------------------------------------- source choosing --
def candidate_groups(doc: dict) -> dict[str, list[dict]]:
    """Text-bearing files of a document, grouped by source kind."""
    stored = lambda f: "skipped" not in f and f.get("path")  # noqa: E731
    groups: dict[str, list[dict]] = {}
    sups = [f for f in doc.get("supplements", []) if stored(f) and f.get("kind") in ("pdf", "docx") and not f.get("scanned")]
    if sups:
        groups["supplement"] = sups
    docx = [f for f in doc.get("attachments", []) if stored(f) and f.get("kind") == "docx" and (f.get("text_chars") or 0) > 0]
    if docx:
        groups["docx"] = docx
    seen_sha: set[str] = set()
    pdfs = []
    for f in doc.get("attachments", []):
        if stored(f) and f.get("kind") == "pdf" and not f.get("scanned") and (f.get("text_chars") or 0) > 0 \
                and f.get("sha256") not in seen_sha:
            seen_sha.add(f.get("sha256"))
            pdfs.append(f)
    if pdfs:
        groups["pdf"] = pdfs
    if doc.get("html") and doc["html"].get("path"):
        groups["html"] = [{"fileName": doc["html"]["fileName"], "kind": "html", "path": doc["html"]["path"]}]
    return groups


def _bucket(doc: dict, files: list[dict], texts: dict[str, str]) -> dict[str, list[dict]]:
    single = len({f["path"] for f in files}) == 1 or len(doc.get("qcvnCodes") or []) == 1
    buckets: dict[str, list[dict]] = {}
    for f in files:
        code = standard_code_for(doc, f.get("fileName", ""), texts[f["path"]], single_regulation=single)
        buckets.setdefault(code, []).append(f)
    return buckets


def choose_source(doc: dict, data_dir: Path) -> tuple[str | None, dict[str, tuple[list[dict], str, ParseResult]]]:
    """Best source group and, per regulation code, (files, joined text, parse result)."""
    best_kind, best, best_score = None, {}, (-1, -1)
    for kind, files in candidate_groups(doc).items():
        texts = {}
        for f in files:
            try:
                texts[f["path"]] = load_text(data_dir, f["kind"], f["path"])
            except Exception as e:  # damaged file: skip it, keep the others
                logger.warning("source_unreadable", doc=doc["docNum"], file=f.get("fileName"), error=str(e))
        files = [f for f in files if f["path"] in texts]
        if not files:
            continue
        buckets = _bucket(doc, files, texts)
        if len(buckets) > 1:  # a signature page or cover sheet must not become its own regulation
            buckets = {c: b for c, b in buckets.items() if sum(len(texts[f["path"]]) for f in b) >= 300} or buckets
        parsed = {}
        for code, bucket in buckets.items():
            joined = "\n".join(texts[f["path"]] for f in bucket)
            parsed[code] = (bucket, joined, parse_regulation_text(joined))
        score = (sum(r.clause_count for _, _, r in parsed.values()), sum(len(t) for _, t, _ in parsed.values()))
        if score > best_score:
            best_kind, best, best_score = kind, parsed, score
    return best_kind, best


# ------------------------------------------------------------------ building --
def _related(text: str, own: str) -> list[str]:
    own_base = own.split(" –")[0].split(" (")[0]
    counts = Counter(
        f"{p} {n}:{y}/{a}" for p, n, y, a in _CODE.findall(text) if f"{p} {n}:{y}/{a}" != own_base
    )
    return [c for c, _ in counts.most_common(15)]


def build_standard(doc: dict, code: str, files: list[dict], text: str, result: ParseResult, source_kind: str) -> dict:
    eff_status = doc.get("effStatus") or ""
    preamble = " ".join(
        a["content"] for ch in result.chapters if ch.get("kind") == "preamble"
        for s in ch["sections"] for a in s["articles"]
    )
    supersedes = [c for c in dict.fromkeys(m.group(1) for m in _SUPERSEDES.finditer(preamble)) if c not in code]
    year = _code_parts(code)[2] if _code_parts(code) else (doc.get("issueDate") or "0000")[:4]
    full_text = doc.get("contentStatus") == "full_text" and source_kind is not None and result.clause_count >= 3
    return {
        "standard_code": code,
        "standard_name": standard_name_for(doc, text),
        "year": int(year) if str(year).isdigit() else 0,
        "issuing_body": "Bộ Xây dựng",
        "status": status_of(eff_status),
        "eff_status": eff_status or "Chưa rõ",
        "expired": bool(doc.get("expired")),
        "doc_num": doc["docNum"],
        "doc_type": doc.get("docType", ""),
        "doc_title": doc.get("title", ""),
        "issue_date": doc.get("issueDate", ""),
        "effective_date": doc.get("effFrom", ""),
        "vbpl_url": doc.get("vbplUrl", ""),
        "source_id": f"vbpl:{doc['id']}:{code}",
        "source_kind": source_kind or "none",
        "source_files": [{"fileName": f.get("fileName"), "kind": f.get("kind"), "sha256": f.get("sha256")} for f in files],
        "full_text": full_text,
        "content_status": doc.get("contentStatus", ""),
        "parse": {"structure": result.structure, "clauses": result.clause_count, "coverage": round(result.coverage, 4)},
        "scope": "",
        "supersedes": supersedes[0] if supersedes else "",
        "related_standards": _related(text, code),
        "chapters": result.chapters,
    }


def build_document(doc: dict, data_dir: Path) -> list[dict]:
    """Standard JSON dicts for one catalog document."""
    kind, parsed = choose_source(doc, data_dir)
    if not parsed:
        # no readable text at all: a metadata-only record still answers "is QCVN X in force?"
        code = standard_code_for(doc, "", doc.get("title", ""), single_regulation=True)
        empty = ParseResult(chapters=[], structure="none", clause_count=0, input_chars=0, output_chars=0)
        return [build_standard(doc, code, [], "", empty, None)]
    return [build_standard(doc, code, files, text, result, kind) for code, (files, text, result) in parsed.items()]


def _safe_name(code: str, doc_id: str) -> str:
    stem = re.sub(r"[^\w.\-]+", "_", code, flags=re.UNICODE).strip("_")
    return f"{stem}__{doc_id[:12]}.json"


def build_corpus(data_dir: Path, out_dir: Path) -> dict:
    """Write one JSON per regulation into `out_dir` (cleared first); return a report."""
    data_dir, out_dir = Path(data_dir), Path(out_dir)
    catalog = json.loads((data_dir / "catalog.json").read_text(encoding="utf-8"))
    out_dir.mkdir(parents=True, exist_ok=True)
    for old in out_dir.glob("*.json"):
        old.unlink()

    report = {"documents": 0, "standards": 0, "full_text": 0, "articles": 0, "items": []}
    for doc in catalog["documents"]:
        report["documents"] += 1
        try:
            standards = build_document(doc, data_dir)
        except Exception as e:  # one broken document must not stop the corpus
            logger.error("document_parse_failed", doc=doc.get("docNum"), error=str(e))
            report["items"].append({"doc_num": doc.get("docNum"), "error": str(e)})
            continue
        for std in standards:
            articles = sum(len(s["articles"]) for ch in std["chapters"] for s in ch["sections"])
            (out_dir / _safe_name(std["standard_code"], doc["id"])).write_text(
                json.dumps(std, ensure_ascii=False, indent=1), encoding="utf-8"
            )
            report["standards"] += 1
            report["full_text"] += int(std["full_text"])
            report["articles"] += articles
            report["items"].append({
                "doc_num": doc["docNum"], "code": std["standard_code"], "status": std["status"],
                "source": std["source_kind"], "full_text": std["full_text"], "articles": articles,
                **std["parse"],
            })
    (out_dir / "_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    return report
