"""Chunker for standard JSON (src/data_pipeline/chunker.py)."""

from src.data_pipeline.chunker import MAX_CHUNK_CHARS, chunk_standard, split_text


def standard(**overrides):
    data = {
        "standard_code": "QCVN 99:2024/BXD", "standard_name": "Quy chuẩn thử nghiệm", "year": 2024,
        "issuing_body": "Bộ Xây dựng", "status": "active", "eff_status": "Còn hiệu lực",
        "doc_num": "01/2024/TT-BXD", "source_id": "vbpl:1:QCVN 99:2024/BXD",
        "chapters": [
            {"number": "0", "kind": "preamble", "title": "Phần mở đầu", "sections": [
                {"number": "0", "title": "Phần mở đầu", "articles": [
                    {"number": "0", "title": "Thông tư", "content": "THÔNG TƯ ban hành quy chuẩn.", "requirements": []}]}]},
            {"number": "1", "kind": "chapter", "title": "QUY ĐỊNH CHUNG", "sections": [
                {"number": "1.1", "title": "Phạm vi", "articles": [
                    {"number": "1.1.1", "title": "Quy chuẩn này quy định", "content": "1.1.1 Quy chuẩn này quy định.",
                     "requirements": [{"type": "minimum_value", "description": "Điều 1.1.1: x", "min_value": 3, "unit": "m"}]}]}]},
            {"number": "A", "kind": "annex", "title": "Phụ lục A (quy định) BỔ SUNG", "sections": [
                {"number": "A.1", "title": "Chung", "articles": [
                    {"number": "A.1.1", "title": "Nội dung", "content": "A.1.1 Nội dung phụ lục.", "requirements": []}]}]},
        ],
    }
    data.update(overrides)
    return data


def articles(chunks):
    return {c["metadata"]["article_number"]: c for c in chunks if c["metadata"]["chunk_type"] == "article"}


class TestLabels:
    def test_annex_and_preamble_labels(self):
        by_num = articles(chunk_standard(standard()))
        assert "Phụ lục A (quy định) BỔ SUNG > Mục A.1: Chung" in by_num["A.1.1"]["text"]
        assert "Chương 1: QUY ĐỊNH CHUNG > Mục 1.1: Phạm vi" in by_num["1.1.1"]["text"]
        assert "Phần mở đầu (thông tư ban hành, lời nói đầu)" in by_num["0"]["text"]
        assert by_num["A.1.1"]["metadata"]["chapter_kind"] == "annex"

    def test_numbered_content_not_prefixed_with_dieu(self):
        text = articles(chunk_standard(standard()))["1.1.1"]["text"]
        assert "Điều 1.1.1" not in text
        assert text.endswith("1.1.1 Quy chuẩn này quy định.")  # real text already holds its requirements


class TestValidity:
    def test_expired_tag_in_every_chunk(self):
        chunks = chunk_standard(standard(status="expired", eff_status="Hết hiệu lực toàn bộ", expired=True))
        assert all(c["text"].startswith("[HẾT HIỆU LỰC] ") for c in chunks)
        assert all(c["metadata"]["expired"] is True for c in chunks)
        assert "Tình trạng hiệu lực: Hết hiệu lực toàn bộ" in chunks[0]["text"]

    def test_active_has_no_tag(self):
        assert not any(c["text"].startswith("[") and "HIỆU LỰC]" in c["text"][:30] for c in chunk_standard(standard()))

    def test_not_yet_effective_and_missing_full_text(self):
        overview = chunk_standard(standard(status="not_yet_effective", full_text=False))[0]["text"]
        assert overview.startswith("[CHƯA CÓ HIỆU LỰC] ")
        assert "chưa có toàn văn" in overview

    def test_source_id_on_every_chunk(self):
        assert {c["metadata"]["source_id"] for c in chunk_standard(standard())} == {"vbpl:1:QCVN 99:2024/BXD"}


class TestSplitting:
    def test_long_article_split_into_parts(self):
        long = "1.1.1 " + " ".join(f"Câu số {i} quy định một yêu cầu kỹ thuật cụ thể." for i in range(120))
        data = standard()
        data["chapters"][1]["sections"][0]["articles"][0]["content"] = long
        parts = [c for c in chunk_standard(data) if c["metadata"].get("article_number") == "1.1.1"]
        assert len(parts) > 3
        assert [c["metadata"]["part"] for c in parts] == list(range(1, len(parts) + 1))
        assert all(f"(phần {c['metadata']['part']}/{len(parts)})" in c["text"] for c in parts)
        assert all(len(c["text"]) < MAX_CHUNK_CHARS + 200 for c in parts)

    def test_split_text_keeps_everything(self):
        text = "\n".join(f"Đoạn {i}. " + "nội dung " * 40 for i in range(20))
        parts = split_text(text, 500)
        assert all(len(p) <= 500 for p in parts)
        assert "".join(parts).replace("\n", "").replace(" ", "") == text.replace("\n", "").replace(" ", "")

    def test_short_text_untouched(self):
        assert split_text("ngắn") == ["ngắn"]


def test_sample_data_still_supported():
    """Hand-written sample data: int chapter numbers, no kind, requirements stated separately."""
    sample = {
        "standard_code": "QCVN 06:2022/BXD", "standard_name": "An toàn cháy", "year": 2022,
        "chapters": [{"number": 1, "title": "Quy định chung", "sections": [{"number": "1.1", "title": "Phạm vi", "articles": [
            {"number": "1.1.1", "title": "Phạm vi áp dụng", "content": "Áp dụng cho nhà và công trình.",
             "requirements": [{"type": "minimum_dimension", "description": "Chiều rộng", "min_value": 1.2, "unit": "m"}]}]}]}],
    }
    chunks = chunk_standard(sample)
    text = articles(chunks)["1.1.1"]["text"]
    assert "Chương 1: Quy định chung > Mục 1.1: Phạm vi" in text
    assert "Điều 1.1.1: Phạm vi áp dụng" in text
    assert "Giá trị tối thiểu: 1.2 m" in text
    assert chunks[0]["metadata"]["source_id"] == "QCVN 06:2022/BXD"
