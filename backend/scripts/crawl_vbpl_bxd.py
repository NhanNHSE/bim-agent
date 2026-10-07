#!/usr/bin/env python3
"""VBPL.VN — Thu thập Quy chuẩn kỹ thuật quốc gia (QCVN) do Bộ Xây dựng ban hành.

Nguồn: Cơ sở dữ liệu quốc gia về văn bản pháp luật (https://vbpl.vn). Script gọi trực
tiếp Next.js Server Action của trang (giống trình duyệt), không cần đăng nhập.

Quy trình:
1. Duyệt toàn bộ danh mục văn bản của Bộ Xây dựng (~1.250 văn bản, ~26 request).
2. Giữ các văn bản QCVN (xem `is_qcvn_document`) ở MỌI lĩnh vực và MỌI tình trạng hiệu
   lực. Văn bản hết hiệu lực vẫn được giữ để chatbot cảnh báo / trả lời khi được hỏi.
3. Với mỗi văn bản:
   - HTML "văn bản gốc" -> TXT sạch (thư mục text/), header ghi rõ tình trạng hiệu lực.
   - Tải MỌI file đính kèm PDF/DOCX/DOC (thư mục files/). Với nhiều QCVN, HTML chỉ chứa
     thông tư ban hành (~1.500 ký tự), toàn văn quy chuẩn nằm trong file đính kèm.
     Loại file được xác định theo magic bytes: vbpl có file ".docx" thực chất là trang
     lỗi HTML, và "Template.pdf" là file giữ chỗ.
   - Nguồn bổ sung chính thức (SUPPLEMENTS) cho văn bản mà vbpl thiếu toàn văn,
     kiểm tra sha256 trước khi lưu.
4. Ghi catalog.json (được commit vào git): metadata, sha256 từng file, trạng thái nội
   dung `full_text` / `doc_only` / `scan_only` / `circular_only` / `none`.
   Các file tải về (text/, files/) KHÔNG commit (xem data/vbpl_bxd/.gitignore).

Chạy lại nhiều lần an toàn: file đính kèm đã có (cùng kích thước) không tải lại.

Sử dụng:
    # Toàn bộ QCVN của Bộ Xây dựng
    python backend/scripts/crawl_vbpl_bxd.py

    # Lọc thêm theo tình trạng hiệu lực / từ khóa trong tiêu đề hoặc số hiệu
    python backend/scripts/crawl_vbpl_bxd.py --status "Còn hiệu lực"
    python backend/scripts/crawl_vbpl_bxd.py --keyword "06:2022" --max-docs 3

    # Trong container Docker
    docker exec bim-backend python scripts/crawl_vbpl_bxd.py
"""

import argparse
import concurrent.futures
import hashlib
import html
import io
import json
import math
import re
import sys
import threading
import time
import unicodedata
import zipfile
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx
from bs4 import BeautifulSoup


# ==============================================================================
# Cấu hình VBPL Server Action & Headers
# ==============================================================================
VBPL_BASE_URL = "https://vbpl.vn"
VBPL_SEARCH_URL = "https://vbpl.vn/van-ban/trung-uong"

# Next.js Server Action IDs lấy từ Webpack bundles của vbpl.vn.
# Khi vbpl triển khai bản mới, các ID này có thể đổi -> mở DevTools (tab Network) trên
# trang tìm kiếm, tìm request POST có header "Next-Action" và cập nhật lại.
ACTION_SEARCH_DOCUMENTS = "c529d164f28418e5898a834422629e64c6816af1"
ACTION_GET_DOCUMENT_FILES = "7b29f485c8e43b71a94bfc11b54459d7e27293e6"

# Mã cơ quan ban hành Bộ Xây dựng trên hệ thống CSDL Quốc gia VBPL
BXD_AGENCY_ID = "49"
BXD_AGENCY_NAME = "Bộ Xây dựng"

# backend/data/vbpl_bxd — tính theo vị trí script nên chạy ở đâu cũng đúng
# (trong Docker: /app/data/vbpl_bxd)
DEFAULT_OUTPUT_DIR = Path(__file__).resolve().parents[1] / "data" / "vbpl_bxd"

BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
}
ACTION_HEADERS = {
    "Accept": "text/x-component",
    "Content-Type": "text/plain;charset=UTF-8",
    "Origin": VBPL_BASE_URL,
    "Referer": VBPL_SEARCH_URL,
}

# Văn bản có ít hơn ngưỡng này (HTML hoặc file đính kèm) coi như chỉ có thông tư ban hành
FULL_TEXT_MIN_CHARS = 10_000
# PDF có trung bình ít hơn ngưỡng này ký tự/trang coi là bản scan (cần OCR)
SCAN_MAX_CHARS_PER_PAGE = 100
ATTACHMENT_EXTS = (".pdf", ".docx", ".doc")

# Văn bản là QCVN khi tiêu đề nhắc tới quy chuẩn (không phải tiêu chuẩn TCVN/TCXDVN).
# "Quy chuẩn xây dựng (Việt Nam)" / QCXDVN là tên gọi trước năm 2009 của QCVN.
_QCVN_TITLE = re.compile(
    r"\bQCVN\b|\bQCXDVN\b|quy\s+chuẩn\s+kỹ\s+thuật\s+quốc\s+gia|quy\s+chuẩn\s+xây\s+dựng",
    re.IGNORECASE,
)
_QCVN_CODE = re.compile(r"\b(QC(?:XD)?VN)\s*([\d\-]+)\s*:\s*(\d{4})(?:\s*/\s*([A-ZĐ]+))?")

# Nguồn chính thức bổ sung cho văn bản mà vbpl.vn không có toàn văn quy chuẩn.
# Khóa = số hiệu văn bản (bỏ khoảng trắng, viết hoa). sha256 đã kiểm tra thủ công.
SUPPLEMENTS: Dict[str, List[Dict[str, str]]] = {
    # vbpl chỉ có HTML của thông tư ban hành (~1.500 ký tự), không có file đính kèm
    "06/2022/TT-BXD": [
        {
            "fileName": "CongBao_QCVN_06-2022_phan1.pdf",
            "url": "https://congbaocdn.chinhphu.vn/CongBaoCP/VanBan/2022/11/38322/42582-1-2022921-92206-2022-tt-bxd.pdf",
            "sha256": "9ad902448f5eac6efb7a3e2c81c3be289aa47a6c191f5a1c7e99535f94eb2c2d",
            "note": "Công báo Chính phủ — toàn văn QCVN 06:2022/BXD, phần 1/3 (thông tư + Chương 1–6)",
        },
        {
            "fileName": "CongBao_QCVN_06-2022_phan2.pdf",
            "url": "https://congbaocdn.chinhphu.vn/CongBaoCP/VanBan/2022/11/38322/42585-1-2022923-92406-2022-tt-bxd.pdf",
            "sha256": "eced5368a5abd73e0bde9000c655dc78d8fb4ed20e1d1cdf4d6390303cd3dfc2",
            "note": "Công báo Chính phủ — QCVN 06:2022/BXD, phần 2/3 (Phụ lục A–G)",
        },
        {
            "fileName": "CongBao_QCVN_06-2022_phan3.pdf",
            "url": "https://congbaocdn.chinhphu.vn/CongBaoCP/VanBan/2022/11/38322/42588-1-2022925-92606-2022-tt-bxd.pdf",
            "sha256": "24e6c52d8c372f1c2d6904b05131999252ddf9feef30f9b910f29addd5b4e5ba",
            "note": "Công báo Chính phủ — QCVN 06:2022/BXD, phần 3/3 (Phụ lục H)",
        },
    ],
}


class VbplError(RuntimeError):
    """vbpl.vn trả về dữ liệu không như mong đợi (thường do Server Action ID đã đổi)."""


# ==============================================================================
# Hàm thuần (không gọi mạng) — có unit test
# ==============================================================================
def sanitize_filename(name: str) -> str:
    """Chuyển đổi ký tự đặc biệt thành tên file an toàn trên mọi hệ điều hành."""
    cleaned = re.sub(r'[\\/*?:"<>|]', "_", name)
    cleaned = re.sub(r"\s+", "_", cleaned)
    return cleaned.strip("._")


def normalize_doc_num(doc_num: str) -> str:
    """'09/2023/TT- BXD' -> '09/2023/TT-BXD' (khóa tra SUPPLEMENTS)."""
    return re.sub(r"\s+", "", doc_num or "").upper()


def is_qcvn_document(title: str, doc_type: str = "") -> Optional[str]:
    """Trả về cụm từ khiến văn bản được nhận là QCVN, hoặc None.

    Bỏ qua bản dịch (trùng nội dung với văn bản tiếng Việt).
    """
    if "bản dịch" in (doc_type or "").lower():
        return None
    match = _QCVN_TITLE.search(unicodedata.normalize("NFC", title or ""))
    return match.group(0) if match else None


def extract_qcvn_codes(title: str) -> List[str]:
    """Các mã quy chuẩn nêu trong tiêu đề, ví dụ ['QCVN 06:2022/BXD']."""
    codes = []
    for prefix, number, year, agency in _QCVN_CODE.findall(unicodedata.normalize("NFC", title or "")):
        code = f"{prefix.upper()} {number}:{year}" + (f"/{agency}" if agency else "")
        if code not in codes:
            codes.append(code)
    return codes


def is_expired(eff_status: str) -> bool:
    status = (eff_status or "").lower()
    return status.startswith("hết hiệu lực toàn bộ") or status.startswith("ngưng hiệu lực")


def detect_kind(data: bytes) -> Optional[str]:
    """Xác định loại file theo nội dung (không tin phần mở rộng)."""
    if data[:5] == b"%PDF-":
        return "pdf"
    if data[:8] == b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1":
        return "doc"
    if data[:2] == b"PK":
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as zf:
                if "word/document.xml" in zf.namelist():
                    return "docx"
        except zipfile.BadZipFile:
            return None
    return None


def inspect_file(kind: str, data: bytes) -> Dict[str, Any]:
    """Số trang, số ký tự trích được và cờ bản scan của một file đính kèm."""
    if kind == "pdf":
        import fitz  # PyMuPDF

        try:
            with fitz.open(stream=data, filetype="pdf") as doc:
                pages = len(doc)
                chars = sum(len(page.get_text("text").strip()) for page in doc)
        except Exception:
            return {"pages": None, "text_chars": None, "scanned": None}
        return {
            "pages": pages,
            "text_chars": chars,
            "scanned": chars < SCAN_MAX_CHARS_PER_PAGE * max(pages, 1),
        }
    if kind == "docx":
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            xml = zf.read("word/document.xml").decode("utf-8", errors="replace")
        text = html.unescape(re.sub(r"<[^>]+>", "", re.sub(r"</w:p>", "\n", xml)))
        return {"pages": None, "text_chars": len(text.strip()), "scanned": False}
    # .doc (Word 97-2003): chưa đọc được nội dung -> cần chuyển sang .docx
    return {"pages": None, "text_chars": None, "scanned": None}


def content_status(html_chars: int, files: List[Dict[str, Any]]) -> str:
    """Mức độ đầy đủ nội dung quy chuẩn đã thu được cho một văn bản."""
    if html_chars >= FULL_TEXT_MIN_CHARS or any(
        (f.get("text_chars") or 0) >= FULL_TEXT_MIN_CHARS for f in files
    ):
        return "full_text"
    # .doc (Word 97-2003) chuyển sang chữ được (LibreOffice) — dễ hơn OCR bản scan
    if any(f.get("kind") == "doc" for f in files):
        return "doc_only"
    if any(f.get("scanned") for f in files):
        return "scan_only"
    if html_chars > 0:
        return "circular_only"
    return "none"


def clean_html_content(html_str: str) -> str:
    """Làm sạch HTML của văn bản gốc, loại bỏ script/style/meta, giữ lại text sạch."""
    soup = BeautifulSoup(html_str, "html.parser")
    for tag in soup(["script", "style", "meta", "link", "noscript"]):
        tag.decompose()

    text = soup.get_text(separator="\n", strip=True)
    lines = [line.strip() for line in text.split("\n")]
    cleaned_lines = []
    prev_empty = False
    for line in lines:
        if not line:
            if not prev_empty:
                cleaned_lines.append("")
                prev_empty = True
        else:
            cleaned_lines.append(line)
            prev_empty = False

    return "\n".join(cleaned_lines)


def get_file_url(fdict: Optional[Dict[str, Any]]) -> str:
    """Lấy URL hợp lệ từ đối tượng tệp (hỗ trợ cả 'url' và 'presignedUrl')."""
    if not fdict:
        return ""
    return fdict.get("url") or fdict.get("presignedUrl") or ""


def _name(value: Any, default: str = "") -> str:
    """Trường vbpl có thể là dict {"name": ...} hoặc chuỗi."""
    if isinstance(value, dict):
        return value.get("name") or default
    return str(value) if value else default


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# ==============================================================================
# Crawler
# ==============================================================================
class VbplBxdCrawler:
    """Crawler QCVN của Bộ Xây dựng trên vbpl.vn."""

    def __init__(
        self,
        output_dir: Path = DEFAULT_OUTPUT_DIR,
        save_html: bool = False,
        keyword: Optional[str] = None,
        status_filter: Optional[str] = None,
        max_docs: int = 0,
        page_size: int = 50,
        workers: int = 4,
        delay: float = 0.2,
        transport: Optional[httpx.BaseTransport] = None,
    ):
        self.output_dir = Path(output_dir)
        self.text_dir = self.output_dir / "text"
        self.files_dir = self.output_dir / "files"
        self.catalog_path = self.output_dir / "catalog.json"

        self.save_html = save_html
        self.keyword = keyword.strip().lower() if keyword else None
        self.status_filter = status_filter.strip().lower() if status_filter else None
        self.max_docs = max_docs
        self.page_size = min(page_size, 100)
        self.workers = max(1, workers)
        self.delay = delay
        self._transport = transport  # để test thay mạng bằng httpx.MockTransport

        self.text_dir.mkdir(parents=True, exist_ok=True)
        self.files_dir.mkdir(parents=True, exist_ok=True)

        self.client = self._new_client()
        self._thread_local = threading.local()
        self._lock = threading.Lock()
        self._counter = 0

    def _new_client(self) -> httpx.Client:
        return httpx.Client(
            headers=BROWSER_HEADERS,
            follow_redirects=True,
            timeout=60.0,
            transport=self._transport,
        )

    def _thread_client(self) -> httpx.Client:
        if not hasattr(self._thread_local, "client"):
            self._thread_local.client = self._new_client()
        return self._thread_local.client

    def close(self):
        self.client.close()

    # -------------------------------------------------------------- vbpl API --
    def _call_action(self, client: httpx.Client, action_id: str, payload: Any) -> str:
        return client.post(
            VBPL_SEARCH_URL,
            headers={**ACTION_HEADERS, "Next-Action": action_id},
            content=json.dumps([payload]),
        ).text

    def fetch_documents_page(self, page_number: int, retries: int = 3) -> Dict[str, Any]:
        """Một trang danh mục văn bản của Bộ Xây dựng (mới nhất trước)."""
        payload = {
            "pageNumber": page_number,
            "pageSize": self.page_size,
            "sortBy": "issueDate",
            "sortDirection": "desc",
            "groupVbpl": True,
            "agencyIds": [BXD_AGENCY_ID],
            "documentType": ["ALL"],
        }
        for attempt in range(retries):
            try:
                body = self._call_action(self.client, ACTION_SEARCH_DOCUMENTS, payload)
                for line in body.split("\n"):
                    if "items" in line and '"total"' in line:
                        data = json.loads(line[line.find(":") + 1 :])
                        if isinstance(data, dict) and "items" in data:
                            return data
            except (httpx.HTTPError, json.JSONDecodeError):
                pass
            time.sleep(1.0 * (attempt + 1))
        raise VbplError(
            f"Không đọc được danh mục trang {page_number}. vbpl.vn có thể đã đổi "
            "Server Action ID (ACTION_SEARCH_DOCUMENTS) — xem hướng dẫn ở đầu file."
        )

    def fetch_document_files(self, doc_id: str, client: httpx.Client, retries: int = 3) -> List[Dict[str, Any]]:
        """Danh sách tệp (HTML, PDF, DOCX...) của văn bản, kèm presigned URL có hạn."""
        for attempt in range(retries):
            try:
                body = self._call_action(client, ACTION_GET_DOCUMENT_FILES, doc_id)
                for line in body.split("\n"):
                    if line.startswith("1:"):
                        data = json.loads(line[2:])
                        if isinstance(data, list):
                            return data
            except (httpx.HTTPError, json.JSONDecodeError):
                pass
            time.sleep(0.5 * (attempt + 1))
        raise VbplError(
            f"Không lấy được danh sách tệp của văn bản {doc_id}. vbpl.vn có thể đã đổi "
            "Server Action ID (ACTION_GET_DOCUMENT_FILES)."
        )

    def fetch_catalog(self) -> List[Dict[str, Any]]:
        """Toàn bộ danh mục văn bản của Bộ Xây dựng."""
        first = self.fetch_documents_page(1)
        total = int(first.get("total", 0))
        pages = math.ceil(total / self.page_size)
        print(f"📊 Bộ Xây dựng có {total:,} văn bản trên vbpl.vn ({pages} trang danh mục).")
        items = list(first.get("items", []))
        for page in range(2, pages + 1):
            time.sleep(self.delay)
            items.extend(self.fetch_documents_page(page).get("items", []))
        return items

    # ------------------------------------------------------------- tải file --
    def _get(self, client: httpx.Client, url: str) -> Optional[httpx.Response]:
        try:
            return client.get(url)
        except httpx.HTTPError:
            return None

    def _download_vbpl_file(self, client: httpx.Client, doc_id: str, fdict: Dict[str, Any]) -> Optional[bytes]:
        """Tải một tệp vbpl; presigned URL hết hạn (401/403) thì xin URL mới một lần."""
        resp = self._get(client, get_file_url(fdict))
        if resp is not None and resp.status_code in (401, 403):
            fresh = next(
                (f for f in self.fetch_document_files(doc_id, client) if f.get("fileName") == fdict.get("fileName")),
                None,
            )
            resp = self._get(client, get_file_url(fresh)) if fresh else None
        if resp is None or resp.status_code != 200:
            return None
        return resp.content

    def _best_html_text(self, client: httpx.Client, doc_id: str, files: List[Dict[str, Any]]):
        """HTML văn bản gốc có nhiều phiên bản (_content, _body_content, _content_origin);
        độ đầy đủ khác nhau tùy văn bản -> lấy bản cho nhiều chữ nhất."""
        best = ("", "", "")  # (text, fileName, raw_html)
        for f in files:
            name = f.get("fileName", "")
            if not name.endswith(".html") or "_bk_" in name:
                continue
            raw = self._download_vbpl_file(client, doc_id, f)
            if not raw:
                continue
            raw_html = raw.decode("utf-8", errors="replace")
            text = clean_html_content(raw_html)
            if len(text) > len(best[0]):
                best = (text, name, raw_html)
        return best

    def _text_header(self, doc: Dict[str, Any]) -> str:
        lines = [
            f"Số hiệu: {doc['docNum']}",
            f"Tiêu đề: {doc['title']}",
            f"Mã quy chuẩn: {', '.join(doc['qcvnCodes']) or '(không nêu trong tiêu đề)'}",
            f"Cơ quan ban hành: {BXD_AGENCY_NAME}",
            f"Loại văn bản: {doc['docType']}",
            f"Ngày ban hành: {doc['issueDate']}",
            f"Ngày hiệu lực: {doc['effFrom']}",
            f"Tình trạng hiệu lực: {doc['effStatus'] or 'Chưa rõ'}",
        ]
        if doc["expired"]:
            lines.append("CẢNH BÁO: Văn bản này đã HẾT HIỆU LỰC — chỉ dùng để tra cứu lịch sử.")
        lines.append(f"Link tra cứu VBPL: {doc['vbplUrl']}")
        return "\n".join(lines) + "\n" + "=" * 60 + "\n\n"

    def _store_file(self, folder: Path, file_name: str, data: bytes, extra: Dict[str, Any]) -> Dict[str, Any]:
        kind = detect_kind(data)
        if kind is None:
            return {"fileName": file_name, "skipped": "không phải PDF/DOCX/DOC hợp lệ (vbpl trả về trang lỗi)", **extra}
        folder.mkdir(parents=True, exist_ok=True)
        target = folder / sanitize_filename(file_name)
        if not target.exists() or target.read_bytes() != data:
            target.write_bytes(data)
        return {
            "fileName": file_name,
            "kind": kind,
            "size": len(data),
            "sha256": _sha256(data),
            **inspect_file(kind, data),
            "path": target.relative_to(self.output_dir).as_posix(),
            **extra,
        }

    def process_document(self, doc: Dict[str, Any], client: httpx.Client) -> Dict[str, Any]:
        """Tải HTML, file đính kèm và nguồn bổ sung của một văn bản; cập nhật `doc`."""
        doc_key = f"{sanitize_filename(doc['docNum']) or 'KhongSo'}_id{doc['id']}"
        folder = self.files_dir / doc_key
        files = self.fetch_document_files(doc["id"], client)

        # 1. HTML văn bản gốc -> TXT
        text, html_name, raw_html = self._best_html_text(client, doc["id"], files)
        doc["html"] = None
        if text:
            txt_path = self.text_dir / f"{doc_key}.txt"
            txt_path.write_text(self._text_header(doc) + text, encoding="utf-8")
            if self.save_html:
                folder.mkdir(parents=True, exist_ok=True)
                (folder / sanitize_filename(html_name)).write_text(raw_html, encoding="utf-8")
            doc["html"] = {
                "fileName": html_name,
                "chars": len(text),
                "path": txt_path.relative_to(self.output_dir).as_posix(),
            }

        # 2. File đính kèm PDF/DOCX/DOC (bỏ trùng tên dạng "B&amp;W" và Template.pdf)
        attachments, seen = [], set()
        for f in files:
            raw_name = f.get("fileName", "")
            name = html.unescape(raw_name)
            if not name.lower().endswith(ATTACHMENT_EXTS) or name.lower().endswith("template.pdf") or name in seen:
                continue
            seen.add(name)
            target = folder / sanitize_filename(name)
            if target.exists() and f.get("size") and target.stat().st_size == int(f["size"]):
                data = target.read_bytes()
            else:
                data = self._download_vbpl_file(client, doc["id"], f)
            if data is None:
                attachments.append({"fileName": name, "skipped": "tải thất bại"})
                continue
            attachments.append(self._store_file(folder, name, data, {}))
        doc["attachments"] = attachments

        # 3. Nguồn chính thức bổ sung (kiểm tra sha256)
        supplements = []
        for sup in SUPPLEMENTS.get(normalize_doc_num(doc["docNum"]), []):
            extra = {"sourceUrl": sup["url"], "note": sup["note"]}
            target = folder / sanitize_filename(sup["fileName"])
            data = target.read_bytes() if target.exists() else None
            if data is None or _sha256(data) != sup["sha256"]:
                resp = self._get(client, sup["url"])
                data = resp.content if resp is not None and resp.status_code == 200 else None
            if data is None:
                supplements.append({"fileName": sup["fileName"], "skipped": "tải thất bại", **extra})
            elif _sha256(data) != sup["sha256"]:
                supplements.append({"fileName": sup["fileName"], "skipped": "sha256 không khớp — nguồn đã thay đổi", **extra})
            else:
                supplements.append(self._store_file(folder, sup["fileName"], data, extra))
        doc["supplements"] = supplements

        stored = [f for f in attachments + supplements if "skipped" not in f]
        doc["contentStatus"] = content_status(doc["html"]["chars"] if doc["html"] else 0, stored)
        return doc

    # ------------------------------------------------------------------ run --
    def _to_doc(self, item: Dict[str, Any], reason: str) -> Dict[str, Any]:
        eff_status = _name(item.get("effStatus"))
        title = item.get("title") or item.get("documentName") or ""
        return {
            "id": str(item["id"]),
            "docNum": item.get("docNum") or "",
            "title": title,
            "qcvnCodes": extract_qcvn_codes(title),
            "matchedBy": reason,
            "docType": _name(item.get("docType")),
            "issueDate": (item.get("issueDate") or "")[:10],
            "effFrom": (item.get("effFrom") or "")[:10],
            "effTo": (item.get("effTo") or "")[:10],
            "effStatus": eff_status,
            "expired": is_expired(eff_status),
            "vbplUrl": f"{VBPL_BASE_URL}/van-ban/chi-tiet/{item['id']}",
        }

    def select_documents(self, items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        docs = []
        for item in items:
            if not item.get("id"):
                continue
            reason = is_qcvn_document(item.get("title") or "", _name(item.get("docType")))
            if reason:
                docs.append(self._to_doc(item, reason))
        if self.status_filter:
            docs = [d for d in docs if self.status_filter in d["effStatus"].lower()]
        if self.keyword:
            docs = [d for d in docs if self.keyword in d["title"].lower() or self.keyword in d["docNum"].lower()]
        if self.max_docs > 0:
            docs = docs[: self.max_docs]
        return docs

    def _process_safely(self, doc: Dict[str, Any], total: int) -> Dict[str, Any]:
        try:
            self.process_document(doc, self._thread_client())
        except Exception as e:  # một văn bản lỗi không làm dừng cả lượt
            doc["error"] = f"{type(e).__name__}: {e}"
            doc["contentStatus"] = "error"
        with self._lock:
            self._counter += 1
            print(f"[{self._counter:03d}/{total:03d}] {doc['docNum']:<22} {doc['contentStatus']:<13} {doc['effStatus']}")
        return doc

    def write_catalog(self, docs: List[Dict[str, Any]], total_agency_docs: int) -> None:
        """Gộp kết quả vào catalog.json (giữ văn bản không thuộc lượt chạy này)."""
        merged: Dict[str, Dict[str, Any]] = {}
        if self.catalog_path.exists():
            for d in json.loads(self.catalog_path.read_text(encoding="utf-8")).get("documents", []):
                merged[d["id"]] = d
        for d in docs:
            merged[d["id"]] = d
        documents = sorted(merged.values(), key=lambda d: (d.get("issueDate", ""), d["docNum"]), reverse=True)
        by_status: Dict[str, int] = {}
        for d in documents:
            by_status[d.get("contentStatus", "?")] = by_status.get(d.get("contentStatus", "?"), 0) + 1
        catalog = {
            "metadata": {
                "source": VBPL_SEARCH_URL,
                "agency": BXD_AGENCY_NAME,
                "updatedAt": time.strftime("%Y-%m-%d %H:%M:%S"),
                "selection": "Tiêu đề chứa QCVN / QCXDVN / 'Quy chuẩn kỹ thuật quốc gia' / "
                "'Quy chuẩn xây dựng'; mọi lĩnh vực, mọi tình trạng hiệu lực; bỏ bản dịch",
                "agencyDocuments": total_agency_docs,
                "qcvnDocuments": len(documents),
                "byContentStatus": dict(sorted(by_status.items())),
            },
            "documents": documents,
        }
        self.catalog_path.write_text(json.dumps(catalog, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    def run(self) -> List[Dict[str, Any]]:
        print("=" * 75)
        print("🏛️  VBPL.VN — THU THẬP QCVN CỦA BỘ XÂY DỰNG")
        print(f"📁 Thư mục lưu: {self.output_dir}")
        print("=" * 75)
        items = self.fetch_catalog()
        docs = self.select_documents(items)
        total = len(docs)
        print(f"📚 Văn bản QCVN cần xử lý: {total}\n")

        with concurrent.futures.ThreadPoolExecutor(max_workers=self.workers) as executor:
            docs = list(executor.map(lambda d: self._process_safely(d, total), docs))

        self.write_catalog(docs, total_agency_docs=len(items))
        self._print_summary(docs)
        return docs

    def _print_summary(self, docs: List[Dict[str, Any]]) -> None:
        by_status: Dict[str, int] = {}
        for d in docs:
            by_status[d["contentStatus"]] = by_status.get(d["contentStatus"], 0) + 1
        print("\n" + "=" * 75)
        print("📊 Kết quả theo trạng thái nội dung:")
        for status, count in sorted(by_status.items()):
            print(f"   {status:<14} {count}")
        missing = [d for d in docs if d["contentStatus"] != "full_text" and not d["expired"]]
        if missing:
            print("\n⚠️  Văn bản còn/chưa hiệu lực nhưng CHƯA có toàn văn dạng chữ:")
            for d in missing:
                print(f"   {d['docNum']:<22} {d['contentStatus']:<13} {d['title'][:70]}")
        print(f"\n💾 Catalog: {self.catalog_path}")
        print("=" * 75)


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):  # console Windows (cp1252) không in được tiếng Việt
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(
        description="Thu thập QCVN của Bộ Xây dựng từ vbpl.vn",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR,
                        help=f"Thư mục lưu (mặc định: {DEFAULT_OUTPUT_DIR})")
    parser.add_argument("--save-html", action="store_true", help="Lưu thêm HTML thô vào files/")
    parser.add_argument("--keyword", default=None, help="Lọc theo từ khóa trong tiêu đề/số hiệu (VD: '06:2022')")
    parser.add_argument("--status", default=None, help="Lọc theo tình trạng hiệu lực (VD: 'Còn hiệu lực')")
    parser.add_argument("--max-docs", type=int, default=0, help="Giới hạn số văn bản (0 = toàn bộ)")
    parser.add_argument("--workers", type=int, default=4, help="Số luồng tải đồng thời (mặc định: 4)")
    parser.add_argument("--delay", type=float, default=0.2, help="Độ trễ giữa các trang danh mục (giây)")
    args = parser.parse_args()

    crawler = VbplBxdCrawler(
        output_dir=args.output_dir,
        save_html=args.save_html,
        keyword=args.keyword,
        status_filter=args.status,
        max_docs=args.max_docs,
        workers=args.workers,
        delay=args.delay,
    )
    try:
        docs = crawler.run()
    except VbplError as e:
        print(f"❌ {e}")
        return 1
    finally:
        crawler.close()
    return 1 if any(d.get("error") for d in docs) else 0


if __name__ == "__main__":
    sys.exit(main())
