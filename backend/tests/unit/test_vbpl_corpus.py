"""Corpus builder for the vbpl.vn crawl (src/data_pipeline/vbpl_corpus.py)."""

import json
import zipfile

import fitz
import pytest

from src.data_pipeline.vbpl_corpus import (
    build_corpus,
    build_document,
    standard_code_for,
    status_of,
)

BODY = """1 QUY ĐỊNH CHUNG
1.1 Phạm vi điều chỉnh
1.1.1 Quy chuẩn này quy định yêu cầu kỹ thuật cho công trình thử nghiệm.
1.1.2 Quy chuẩn áp dụng cho mọi công trình xây dựng mới.
1.2 Đối tượng áp dụng
1.2.1 Tổ chức, cá nhân có liên quan.
2 QUY ĐỊNH KỸ THUẬT
2.1 Yêu cầu chung
2.1.1 Chiều cao tầng không nhỏ hơn 3 m.
2.1.2 Chiều rộng hành lang không nhỏ hơn 1.400 mm.
"""
PREAMBLE = "THÔNG TƯ Ban hành QCVN 99:2024/BXD\nĐiều 2. Thông tư này thay thế QCVN 99:2015/BXD.\n"


def write_docx(path, text):
    paras = "".join(f"<w:p><w:r><w:t>{line}</w:t></w:r></w:p>" for line in text.split("\n"))
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("[Content_Types].xml", "<Types/>")
        zf.writestr("word/document.xml", f"<w:document><w:body>{paras}</w:body></w:document>")


def write_html_txt(path, text):
    path.write_text("Số hiệu: x\nTiêu đề: y\n" + "=" * 60 + "\n\n" + text, encoding="utf-8")


def doc_entry(doc_id, doc_num, title, eff="Còn hiệu lực", content_status="full_text", **extra):
    return {
        "id": doc_id, "docNum": doc_num, "title": title, "qcvnCodes": extra.pop("codes", []),
        "docType": extra.pop("docType", "Thông tư"), "issueDate": extra.pop("issueDate", "2024-05-01"),
        "effFrom": "2024-07-01", "effStatus": eff, "expired": eff.startswith("Hết hiệu lực toàn bộ"),
        "vbplUrl": f"https://vbpl.vn/van-ban/chi-tiet/{doc_id}", "contentStatus": content_status,
        "html": None, "attachments": [], "supplements": [], **extra,
    }


@pytest.fixture
def corpus(tmp_path):
    (tmp_path / "text").mkdir()
    (tmp_path / "files").mkdir()
    return tmp_path


class TestSourceChoice:
    def test_docx_beats_short_circular_html(self, corpus):
        write_html_txt(corpus / "text" / "a.txt", PREAMBLE)
        write_docx(corpus / "files" / "qc.docx", PREAMBLE + BODY)
        doc = doc_entry("1", "01/2024/TT-BXD", "Thông tư ban hành QCVN 99:2024/BXD", codes=["QCVN 99:2024/BXD"],
                        html={"fileName": "1_content.html", "chars": 80, "path": "text/a.txt"},
                        attachments=[{"fileName": "qc.docx", "kind": "docx", "text_chars": 500, "path": "files/qc.docx", "sha256": "s1"}])
        [std] = build_document(doc, corpus)

        assert std["source_kind"] == "docx"
        assert std["standard_code"] == "QCVN 99:2024/BXD"
        assert std["full_text"] is True
        assert std["supersedes"] == "QCVN 99:2015/BXD"
        assert std["status"] == "active"
        assert std["source_id"] == "vbpl:1:QCVN 99:2024/BXD"
        arts = {a["number"] for ch in std["chapters"] for s in ch["sections"] for a in s["articles"]}
        assert {"1.1.1", "2.1.2"} <= arts

    def test_text_pdf_used_and_scans_ignored(self, corpus):
        pdf = fitz.open()
        page = pdf.new_page()
        page.insert_textbox(page.rect + (36, 36, -36, -36), "QCVN 98:2024/BXD\n" + "\n".join(
            ["1 QUY DINH CHUNG", "1.1 Pham vi", "1.1.1 Quy chuan nay ap dung.", "1.1.2 Doi tuong ap dung.",
             "1.2 Giai thich", "1.2.1 Tu ngu duoc hieu nhu sau."]), fontsize=9)
        pdf.save(corpus / "files" / "t.pdf")
        doc = doc_entry("2", "02/2024/TT-BXD", "Thông tư ban hành quy chuẩn kỹ thuật quốc gia",
                        attachments=[
                            {"fileName": "t.pdf", "kind": "pdf", "text_chars": 300, "scanned": False, "path": "files/t.pdf", "sha256": "a"},
                            {"fileName": "scan.pdf", "kind": "pdf", "text_chars": 0, "scanned": True, "path": "files/missing.pdf", "sha256": "b"},
                        ])
        [std] = build_document(doc, corpus)
        assert std["source_kind"] == "pdf"
        assert std["standard_code"] == "QCVN 98:2024/BXD"  # read from the text: the title has no code
        assert std["parse"]["clauses"] >= 3


class TestCodes:
    def test_part_number_from_file_name(self, corpus):
        for part in (1, 2):
            write_docx(corpus / "files" / f"QCVN_07-{part}.docx", BODY)
        doc = doc_entry("3", "15/2023/TT-BXD", "Ban hành QCVN 07:2023/BXD", codes=["QCVN 07:2023/BXD"],
                        attachments=[{"fileName": f"QCVN_07-{p}.docx", "kind": "docx", "text_chars": 400,
                                      "path": f"files/QCVN_07-{p}.docx", "sha256": str(p)} for p in (1, 2)])
        codes = sorted(s["standard_code"] for s in build_document(doc, corpus))
        assert codes == ["QCVN 07-1:2023/BXD", "QCVN 07-2:2023/BXD"]

    def test_amendment_and_consolidated_get_suffixes(self):
        amend = doc_entry("4", "09/2023/TT-BXD", "Ban hành Sửa đổi 1:2023 QCVN 06:2022/BXD", codes=["QCVN 06:2022/BXD"])
        assert standard_code_for(amend, "", "", single_regulation=True) == "QCVN 06:2022/BXD – Sửa đổi 1:2023"
        vbhn = doc_entry("5", "81/2026/VBHN-TT-BXD", "Văn bản hợp nhất QCVN 07:2023/BXD",
                         codes=["QCVN 07:2023/BXD"], docType="Văn bản hợp nhất")
        assert standard_code_for(vbhn, "", "", single_regulation=True) == "QCVN 07:2023/BXD (hợp nhất 81/2026/VBHN-TT-BXD)"

    def test_issue_year_preferred_over_cited_codes(self):
        doc = doc_entry("6", "12/2018/TT-BXD", "Ban hành quy chuẩn về gara", issueDate="2018-12-26")
        text = "Viện dẫn QCVN 06:2010/BXD, QCVN 06:2010/BXD, QCVN 06:2010/BXD. Quy chuẩn QCVN 13:2018/BXD."
        assert standard_code_for(doc, "a.docx", text, single_regulation=True) == "QCVN 13:2018/BXD"


class TestValidity:
    @pytest.mark.parametrize("eff,status", [
        ("Còn hiệu lực", "active"), ("Hết hiệu lực toàn bộ", "expired"),
        ("Hết hiệu lực một phần", "partially_expired"), ("Chưa có hiệu lực", "not_yet_effective"), ("", "unknown")])
    def test_status_mapping(self, eff, status):
        assert status_of(eff) == status

    def test_document_without_text_still_recorded(self, corpus):
        doc = doc_entry("7", "02/2021/TT-BXD", "Ban hành QCVN 06:2021/BXD", eff="Hết hiệu lực toàn bộ",
                        content_status="none", codes=["QCVN 06:2021/BXD"])
        [std] = build_document(doc, corpus)
        assert std["standard_code"] == "QCVN 06:2021/BXD"
        assert std["status"] == "expired" and std["expired"] is True
        assert std["full_text"] is False and std["chapters"] == []


def test_build_corpus_writes_one_file_per_regulation(corpus):
    write_docx(corpus / "files" / "qc.docx", PREAMBLE + BODY)
    catalog = {"documents": [
        doc_entry("1", "01/2024/TT-BXD", "Ban hành QCVN 99:2024/BXD", codes=["QCVN 99:2024/BXD"],
                  attachments=[{"fileName": "qc.docx", "kind": "docx", "text_chars": 500, "path": "files/qc.docx", "sha256": "s"}]),
        doc_entry("2", "02/2021/TT-BXD", "Ban hành QCVN 06:2021/BXD", eff="Hết hiệu lực toàn bộ",
                  content_status="none", codes=["QCVN 06:2021/BXD"]),
    ]}
    (corpus / "catalog.json").write_text(json.dumps(catalog, ensure_ascii=False), encoding="utf-8")
    out = corpus / "parsed"
    out.mkdir()
    (out / "stale.json").write_text("{}", encoding="utf-8")

    report = build_corpus(corpus, out)

    assert report["standards"] == 2 and report["full_text"] == 1
    files = sorted(p.name for p in out.glob("*.json"))
    assert "stale.json" not in files and "_report.json" in files
    assert len([f for f in files if not f.startswith("_")]) == 2
