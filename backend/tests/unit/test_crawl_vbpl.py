"""QCVN crawler for vbpl.vn (scripts/crawl_vbpl_bxd.py).

Network is replaced by httpx.MockTransport that mimics the two Next.js Server Actions
(document search, document files) and the presigned file downloads.
"""

import io
import json
import zipfile

import fitz
import httpx
import pytest

from scripts import crawl_vbpl_bxd as crawler_mod
from scripts.crawl_vbpl_bxd import (
    ACTION_GET_DOCUMENT_FILES,
    ACTION_SEARCH_DOCUMENTS,
    VbplBxdCrawler,
    VbplError,
    content_status,
    detect_kind,
    extract_qcvn_codes,
    is_expired,
    is_qcvn_document,
    normalize_doc_num,
)


def make_pdf(text: str, pages: int = 1) -> bytes:
    doc = fitz.open()
    for _ in range(pages):
        page = doc.new_page()
        if text:
            page.insert_textbox(page.rect + (36, 36, -36, -36), text, fontsize=8)
    data = doc.tobytes()
    doc.close()
    return data


def make_docx(text: str) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("[Content_Types].xml", "<Types/>")
        zf.writestr("word/document.xml", f"<w:document><w:body><w:p><w:r><w:t>{text}</w:t></w:r></w:p></w:body></w:document>")
    return buf.getvalue()


ERROR_PAGE = b'\r\n<!DOCTYPE html PUBLIC "-//W3C//DTD XHTML 1.0 Transitional//EN"><html>error</html>'


class TestQcvnSelection:
    @pytest.mark.parametrize("title", [
        "Thông tư số 06/2022/TT-BXD Quy chuẩn kỹ thuật quốc gia QCVN 06:2022/BXD về an toàn cháy",
        "Thông tư số 05/2022/TT-BXD Ban hành Quy chuẩn kỹ thuật quốc gia về phân cấp công trình",
        "Thông tư số 12/2026/TT-BXD Ban hành Quy chuẩn kỹ thuật quốc gia về động cơ xe mô tô điện",
        "Văn bản hợp nhất Ban hành QCVN 07:2023/BXD Quy chuẩn kỹ thuật quốc gia về hạ tầng kỹ thuật",
        "Thông tư số 07/2010/TT-BXD Ban hành Quy chuẩn kỹ thuật quốc gia An toàn cháy cho nhà và công trình",
        'Quyết định số 40/2005/QĐ-BXD Về việc ban hành QCXDVN 09: 2005 "Quy chuẩn xây dựng Việt Nam"',
        "Quyết định số 682/BXD-CSXD Về việc ban hành quy chuẩn xây dựng Việt nam",
    ])
    def test_regulations_selected_in_every_field_and_era(self, title):
        assert is_qcvn_document(title, "Thông tư")

    @pytest.mark.parametrize("title", [
        "Thông tư số 18/2010/TT-BXD Quy định việc áp dụng quy chuẩn, tiêu chuẩn trong hoạt động xây dựng",
        "Thông tư số 57/2026/TT-BXD Quy định về thẩm định thiết kế, kiểm định, kiểm tra",
        'Quyết định số 34/2005/QĐ-BXD Về việc ban hành TCXDVN 356: 2005 "Kết cấu bê tông"',
        "Thông tư số 10/2011/TT-BXD Ban hành Tiêu chuẩn kỹ năng nghề quốc gia đối với nghề Hàn",
        "Thông tư số 13/2023/TT-BXD Ban hành Hệ thống chỉ tiêu thống kê ngành Xây dựng",
    ])
    def test_standards_and_ordinary_legal_documents_rejected(self, title):
        assert is_qcvn_document(title, "Thông tư") is None

    def test_translations_rejected(self):
        assert is_qcvn_document("Thông tư ban hành QCVN 06:2022/BXD", "Bản dịch văn bản") is None

    def test_extract_codes(self):
        assert extract_qcvn_codes("Ban hành Sửa đổi 1:2025 QCVN 07:2023/BXD Quy chuẩn") == ["QCVN 07:2023/BXD"]
        assert extract_qcvn_codes('ban hành QCXDVN 09: 2005 "Quy chuẩn"') == ["QCXDVN 09:2005"]
        assert extract_qcvn_codes("Ban hành Quy chuẩn kỹ thuật quốc gia về Gara ôtô") == []

    def test_expired_status(self):
        assert is_expired("Hết hiệu lực toàn bộ")
        assert is_expired("Ngưng hiệu lực")
        assert not is_expired("Hết hiệu lực một phần")
        assert not is_expired("Còn hiệu lực")

    def test_doc_num_normalized(self):
        assert normalize_doc_num("09/2023/TT- BXD") == "09/2023/TT-BXD"


class TestFileChecks:
    def test_detect_kind_by_content_not_extension(self):
        assert detect_kind(make_pdf("x")) == "pdf"
        assert detect_kind(make_docx("x")) == "docx"
        assert detect_kind(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\0" * 100) == "doc"
        assert detect_kind(ERROR_PAGE) is None  # vbpl "docx" that is really an error page
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("other.txt", "x")
        assert detect_kind(buf.getvalue()) is None

    def test_content_status(self, monkeypatch):
        monkeypatch.setattr(crawler_mod, "FULL_TEXT_MIN_CHARS", 1000)
        assert content_status(5000, []) == "full_text"
        assert content_status(1500 - 1000, [{"kind": "pdf", "text_chars": 2000, "scanned": False}]) == "full_text"
        assert content_status(500, [{"kind": "pdf", "text_chars": 50, "scanned": True}]) == "scan_only"
        assert content_status(500, [{"kind": "doc", "text_chars": None, "scanned": None}]) == "doc_only"
        # a legacy .doc beside a scan is the better source (convertible without OCR)
        assert content_status(500, [{"kind": "pdf", "text_chars": 0, "scanned": True},
                                    {"kind": "doc", "text_chars": None, "scanned": None}]) == "doc_only"
        assert content_status(500, []) == "circular_only"
        assert content_status(0, []) == "none"


# ---------------------------------------------------------------- fake vbpl --
LONG_TEXT = "Quy chuan ky thuat quoc gia ve an toan chay cho nha va cong trinh. " * 60  # ~4 000 chars
CIRCULAR_HTML = "<html><body><p>BỘ XÂY DỰNG</p><p>Thông tư ban hành quy chuẩn</p></body></html>"

ITEMS = [
    {"id": "1001", "docNum": "06/2022/TT-BXD", "title": "Thông tư số 06/2022/TT-BXD Quy chuẩn kỹ thuật quốc gia QCVN 06:2022/BXD",
     "docType": {"name": "Thông tư"}, "effStatus": {"name": "Còn hiệu lực"}, "issueDate": "2022-11-30T00:00:00", "effFrom": "2023-01-16"},
    {"id": "1002", "docNum": "07/2010/TT-BXD", "title": "Thông tư số 07/2010/TT-BXD Ban hành Quy chuẩn kỹ thuật quốc gia An toàn cháy",
     "docType": {"name": "Thông tư"}, "effStatus": {"name": "Hết hiệu lực toàn bộ"}, "issueDate": "2010-07-28", "effFrom": "2010-08-01"},
    {"id": "1003", "docNum": "57/2026/TT-BXD", "title": "Thông tư số 57/2026/TT-BXD Quy định về thẩm định thiết kế",
     "docType": {"name": "Thông tư"}, "effStatus": {"name": "Còn hiệu lực"}, "issueDate": "2026-07-07", "effFrom": "2026-07-07"},
]

FILES = {
    "1001": [
        {"fileName": "1001_content.html", "presignedUrl": "https://s3.test/1001_content.html?sig=a"},
        {"fileName": "1001_content_bk_20260530.html", "presignedUrl": "https://s3.test/bk.html?sig=a"},
        {"fileName": "QCVN06 (B&W).docx", "presignedUrl": "https://s3.test/fake1.docx?sig=a"},
        {"fileName": "QCVN06 (B&amp;W).docx", "presignedUrl": "https://s3.test/fake2.docx?sig=a"},
        {"fileName": "Template.pdf", "presignedUrl": "https://s3.test/Template.pdf?sig=a"},
        {"fileName": "VanBanGoc_06.pdf", "presignedUrl": "https://s3.test/goc06.pdf?sig=a"},
        {"fileName": "1001.xml", "presignedUrl": "https://s3.test/1001.xml?sig=a"},
    ],
    "1002": [
        {"fileName": "VanBanGoc_07.pdf", "presignedUrl": "https://s3.test/scan07.pdf?sig=a"},
    ],
}


class FakeVbpl:
    """Routes requests like vbpl.vn + its S3 presigned URLs; records every call."""

    def __init__(self):
        self.downloads = {
            "/1001_content.html": CIRCULAR_HTML.encode(),
            "/bk.html": b"<html>" + b"old backup " * 500 + b"</html>",
            "/fake1.docx": ERROR_PAGE,
            "/fake2.docx": ERROR_PAGE,
            "/Template.pdf": make_pdf("Dang cap nhat"),
            "/goc06.pdf": make_pdf(LONG_TEXT, pages=3),
            "/scan07.pdf": make_pdf("", pages=4),
            "/1001.xml": b"<xml/>",
        }
        self.files = json.loads(json.dumps(FILES))
        self.calls = []
        self.expired_urls = set()

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.calls.append((request.method, request.url.path))
        if request.method == "POST":
            action = request.headers.get("Next-Action")
            payload = json.loads(request.content)[0]
            if action == ACTION_SEARCH_DOCUMENTS:
                assert payload["agencyIds"] == ["49"]
                body = {"items": ITEMS, "total": len(ITEMS)}
                return httpx.Response(200, text=f'0:{{"a":"$@1"}}\n1:{json.dumps(body, ensure_ascii=False)}\n')
            if action == ACTION_GET_DOCUMENT_FILES:
                return httpx.Response(200, text=f'0:{{"a":"$@1"}}\n1:{json.dumps(self.files.get(payload, []))}\n')
            return httpx.Response(404, text="unknown action")
        if str(request.url) in self.expired_urls:
            # Like S3: the old signature is dead, the next files listing signs afresh
            for files in self.files.values():
                for f in files:
                    f["presignedUrl"] = f["presignedUrl"].replace("sig=a", "sig=b")
            return httpx.Response(403, text="expired")
        data = self.downloads.get(request.url.path)
        return httpx.Response(200, content=data) if data is not None else httpx.Response(404)

    def file_downloads(self):
        return [path for method, path in self.calls if method == "GET"]


@pytest.fixture
def fake():
    return FakeVbpl()


@pytest.fixture
def make_crawler(tmp_path, fake, monkeypatch):
    monkeypatch.setattr(crawler_mod, "FULL_TEXT_MIN_CHARS", 3000)
    monkeypatch.setattr(crawler_mod.time, "sleep", lambda _s: None)
    monkeypatch.setattr(crawler_mod, "SUPPLEMENTS", {})
    created = []

    def _make(**kwargs):
        c = VbplBxdCrawler(output_dir=tmp_path, workers=1, delay=0, transport=httpx.MockTransport(fake.handler), **kwargs)
        created.append(c)
        return c

    yield _make
    for c in created:
        c.close()


def _catalog(tmp_path):
    return json.loads((tmp_path / "catalog.json").read_text(encoding="utf-8"))


class TestCrawlRun:
    def test_only_regulations_processed_and_expired_kept(self, make_crawler, fake, tmp_path):
        docs = make_crawler().run()

        assert [d["docNum"] for d in docs] == ["06/2022/TT-BXD", "07/2010/TT-BXD"]
        assert "/1003" not in str(fake.calls)  # ordinary legal document never fetched
        cat = _catalog(tmp_path)
        assert cat["metadata"]["agencyDocuments"] == 3
        assert cat["metadata"]["qcvnDocuments"] == 2
        expired = next(d for d in cat["documents"] if d["docNum"] == "07/2010/TT-BXD")
        assert expired["expired"] is True
        assert expired["contentStatus"] == "scan_only"
        assert expired["attachments"][0]["scanned"] is True

    def test_short_html_still_downloads_attachments(self, make_crawler, tmp_path):
        make_crawler().run()
        doc = next(d for d in _catalog(tmp_path)["documents"] if d["docNum"] == "06/2022/TT-BXD")

        assert doc["qcvnCodes"] == ["QCVN 06:2022/BXD"]
        assert doc["html"]["fileName"] == "1001_content.html"  # *_bk_* backups ignored
        assert doc["contentStatus"] == "full_text"  # from the PDF, not the circular HTML
        stored = [a for a in doc["attachments"] if "skipped" not in a]
        assert [a["fileName"] for a in stored] == ["VanBanGoc_06.pdf"]
        assert stored[0]["pages"] == 3 and not stored[0]["scanned"]
        assert (tmp_path / stored[0]["path"]).read_bytes()[:5] == b"%PDF-"

    def test_fake_docx_and_template_pdf_not_saved(self, make_crawler, fake, tmp_path):
        make_crawler().run()
        doc = next(d for d in _catalog(tmp_path)["documents"] if d["docNum"] == "06/2022/TT-BXD")

        skipped = [a for a in doc["attachments"] if "skipped" in a]
        assert [a["fileName"] for a in skipped] == ["QCVN06 (B&W).docx"]  # "&amp;" duplicate collapsed
        assert "/Template.pdf" not in fake.file_downloads()
        assert "/1001.xml" not in fake.file_downloads()
        assert not list(tmp_path.rglob("*.docx"))

    def test_text_file_has_status_header_and_expiry_warning(self, make_crawler, fake, tmp_path):
        fake.files["1002"].append({"fileName": "1002_content.html", "presignedUrl": "https://s3.test/1002.html"})
        fake.downloads["/1002.html"] = CIRCULAR_HTML.encode()
        make_crawler().run()

        current = (tmp_path / "text" / "06_2022_TT-BXD_id1001.txt").read_text(encoding="utf-8")
        old = (tmp_path / "text" / "07_2010_TT-BXD_id1002.txt").read_text(encoding="utf-8")
        assert "Tình trạng hiệu lực: Còn hiệu lực" in current and "CẢNH BÁO" not in current
        assert "Tình trạng hiệu lực: Hết hiệu lực toàn bộ" in old and "CẢNH BÁO" in old
        assert "BỘ XÂY DỰNG" in current

    def test_catalog_has_no_presigned_urls(self, make_crawler, tmp_path):
        make_crawler().run()
        raw = (tmp_path / "catalog.json").read_text(encoding="utf-8")
        assert "sig=" not in raw and "presigned" not in raw.lower()

    def test_rerun_does_not_redownload_attachments(self, make_crawler, fake):
        for f in fake.files["1001"] + fake.files["1002"]:
            f["size"] = len(fake.downloads["/" + f["presignedUrl"].split("/")[-1].split("?")[0]])
        make_crawler().run()
        fake.calls.clear()
        make_crawler().run()

        assert "/goc06.pdf" not in fake.file_downloads()
        assert "/scan07.pdf" not in fake.file_downloads()

    def test_expired_presigned_url_refreshed(self, make_crawler, fake, tmp_path):
        fake.expired_urls.add("https://s3.test/goc06.pdf?sig=a")
        make_crawler().run()

        doc = next(d for d in _catalog(tmp_path)["documents"] if d["docNum"] == "06/2022/TT-BXD")
        assert any(a["fileName"] == "VanBanGoc_06.pdf" and "sha256" in a for a in doc["attachments"])
        assert doc["contentStatus"] == "full_text"

    def test_filters_and_partial_runs_merge_into_catalog(self, make_crawler, tmp_path):
        make_crawler(keyword="06/2022").run()
        assert [d["docNum"] for d in _catalog(tmp_path)["documents"]] == ["06/2022/TT-BXD"]
        make_crawler(status_filter="Hết hiệu lực").run()
        assert {d["docNum"] for d in _catalog(tmp_path)["documents"]} == {"06/2022/TT-BXD", "07/2010/TT-BXD"}

    def test_one_failing_document_does_not_stop_the_run(self, make_crawler, fake, tmp_path):
        original_handler = fake.handler

        def failing_handler(request):
            if request.method == "POST" and json.loads(request.content)[0] == "1002":
                return httpx.Response(500)
            return original_handler(request)

        fake.handler = failing_handler
        docs = make_crawler().run()
        by_num = {d["docNum"]: d for d in docs}
        assert by_num["07/2010/TT-BXD"]["contentStatus"] == "error"
        assert "VbplError" in by_num["07/2010/TT-BXD"]["error"]
        assert by_num["06/2022/TT-BXD"]["contentStatus"] == "full_text"


class TestSupplements:
    def _supplement(self, data: bytes, sha: str):
        return {"06/2022/TT-BXD": [{
            "fileName": "CongBao_part1.pdf", "url": "https://congbao.test/part1.pdf",
            "sha256": sha, "note": "official gazette",
        }]}

    def test_verified_supplement_stored(self, make_crawler, fake, tmp_path, monkeypatch):
        data = make_pdf(LONG_TEXT, pages=2)
        fake.downloads["/part1.pdf"] = data
        monkeypatch.setattr(crawler_mod, "SUPPLEMENTS", self._supplement(data, crawler_mod._sha256(data)))
        make_crawler().run()

        doc = next(d for d in _catalog(tmp_path)["documents"] if d["docNum"] == "06/2022/TT-BXD")
        sup = doc["supplements"][0]
        assert sup["sourceUrl"] == "https://congbao.test/part1.pdf"
        assert sup["sha256"] == crawler_mod._sha256(data)
        assert (tmp_path / sup["path"]).exists()

    def test_changed_supplement_rejected(self, make_crawler, fake, tmp_path, monkeypatch):
        fake.downloads["/part1.pdf"] = make_pdf("tampered")
        monkeypatch.setattr(crawler_mod, "SUPPLEMENTS", self._supplement(b"", "0" * 64))
        make_crawler().run()

        doc = next(d for d in _catalog(tmp_path)["documents"] if d["docNum"] == "06/2022/TT-BXD")
        assert "sha256" in doc["supplements"][0]["skipped"]
        assert not list(tmp_path.rglob("CongBao_part1.pdf"))


def test_stale_server_action_id_reported(make_crawler, fake):
    fake.handler = lambda request: httpx.Response(404, text="Server action not found")
    with pytest.raises(VbplError, match="Server Action ID"):
        make_crawler().fetch_documents_page(1)
