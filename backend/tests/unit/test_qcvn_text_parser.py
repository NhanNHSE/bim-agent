"""Structure parser for real QCVN text (src/data_pipeline/qcvn_text_parser.py)."""

import pytest

from src.data_pipeline.qcvn_text_parser import (
    detect_codes,
    extract_requirements,
    parse_regulation_text,
    parse_vn_number,
    reflow,
    strip_page_furniture,
)

REGULATION = """BỘ XÂY DỰNG
THÔNG TƯ Ban hành QCVN 99:2024/BXD
Điều 1. Ban hành kèm theo Thông tư này QCVN 99:2024/BXD.
Điều 2. Thông tư này thay thế QCVN 99:2015/BXD.
MỤC LỤC
1 QUY ĐỊNH CHUNG ........ 5
2 QUY ĐỊNH KỸ THUẬT ....... 8
1 QUY ĐỊNH CHUNG
1.1 Phạm vi điều chỉnh
1.1.1 Quy chuẩn này quy định các yêu cầu
kỹ thuật cho nhà thử nghiệm.
1.1.2 Áp dụng cho:
a) Nhà ở;
b) Nhà công cộng.
1.2 Giải thích từ ngữ
Trong quy chuẩn này các từ ngữ được hiểu như sau.
2 QUY ĐỊNH KỸ THUẬT
2.1 Lối thoát nạn
2.1.1 Chiều rộng lối thoát nạn không nhỏ hơn 1,2 m và cửa không nhỏ hơn 800 mm.
2.5 m là chiều cao thông thủy tối thiểu của lối đi.
2.1.2 Khoảng cách đến lối ra không quá 1.500 mm.
2.1.2.1 Trường hợp đặc biệt cho phép tăng thêm.
Bảng 1
1.1 Nhà ở 2,5
3 TỔ CHỨC THỰC HIỆN
3.1 Bộ Xây dựng hướng dẫn thực hiện quy chuẩn này.
"""


def _articles(result):
    return {a["number"]: a for ch in result.chapters for s in ch["sections"] for a in s["articles"]}


class TestNumberedStructure:
    def test_chapters_sections_articles(self):
        r = parse_regulation_text(REGULATION)
        assert r.structure == "numbered"
        assert [(c["number"], c["kind"]) for c in r.chapters] == [
            ("0", "preamble"), ("1", "chapter"), ("2", "chapter"), ("3", "chapter")]
        assert [c["title"] for c in r.chapters[1:]] == ["QUY ĐỊNH CHUNG", "QUY ĐỊNH KỸ THUẬT", "TỔ CHỨC THỰC HIỆN"]
        sections = [s["number"] for s in r.chapters[2]["sections"]]
        assert sections == ["2.1"]
        assert set(_articles(r)) >= {"1.1.1", "1.1.2", "1.2", "2.1.1", "2.1.2", "3.1"}

    def test_wrapped_lines_and_list_items(self):
        a = _articles(parse_regulation_text(REGULATION))
        assert a["1.1.1"]["content"] == "1.1.1 Quy chuẩn này quy định các yêu cầu kỹ thuật cho nhà thử nghiệm."
        assert a["1.1.2"]["content"].split("\n") == ["1.1.2 Áp dụng cho:", "a) Nhà ở;", "b) Nhà công cộng."]

    def test_deeper_levels_folded_into_article(self):
        a = _articles(parse_regulation_text(REGULATION))
        assert "2.1.2.1" not in a
        assert "2.1.2.1 Trường hợp đặc biệt cho phép tăng thêm." in a["2.1.2"]["content"]

    def test_measurements_and_table_rows_are_not_clauses(self):
        a = _articles(parse_regulation_text(REGULATION))
        assert "2.5" not in a
        assert "2.5 m là chiều cao thông thủy" in a["2.1.1"]["content"]
        # "1.1 Nhà ở 2,5" in a table after 2.1.2 is out of reading order -> stays text
        assert "1.1 Nhà ở 2,5" in a["2.1.2"]["content"]

    def test_toc_dropped_and_preamble_kept(self):
        r = parse_regulation_text(REGULATION)
        preamble = r.chapters[0]["sections"][0]["articles"][0]["content"]
        assert "thay thế QCVN 99:2015/BXD" in preamble
        assert "........" not in preamble

    def test_nothing_lost(self):
        assert parse_regulation_text(REGULATION).coverage > 0.97

    def test_requirements_attached(self):
        reqs = _articles(parse_regulation_text(REGULATION))["2.1.1"]["requirements"]
        assert {(r["min_value"], r["unit"]) for r in reqs} == {(1.2, "m"), (800.0, "mm")}


class TestAnnexes:
    def test_annex_clauses_and_wrapped_reference(self):
        text = REGULATION + """PHỤ LỤC A (quy định)
YÊU CẦU BỔ SUNG
A.1 Quy định chung
A.1.1 Nội dung phụ lục A được áp dụng cùng
Phụ lục B. Nội dung này tiếp tục câu trước.
"""
        r = parse_regulation_text(text)
        assert r.chapters[-1]["number"] == "A"
        assert r.chapters[-1]["kind"] == "annex"
        assert r.chapters[-1]["title"] == "Phụ lục A (quy định) YÊU CẦU BỔ SUNG"
        assert "Phụ lục B. Nội dung này" in _articles(r)["A.1.1"]["content"]

    def test_numbered_table_rows_inside_annex_are_not_chapters(self):
        filler = "\n".join(f"Nội dung bảng dòng {i}." for i in range(12))
        text = REGULATION + f"""PHỤ LỤC A (tham khảo)
{filler}
4 Hội trường, nhà hát
4.1 Hội trường lớn 300 lux
4.2 Gian khán giả 200 lux
5.1 Phòng học 300 lux
"""
        r = parse_regulation_text(text)
        assert [c["number"] for c in r.chapters] == ["0", "1", "2", "3", "A"]
        annex_text = " ".join(a["content"] for s in r.chapters[-1]["sections"] for a in s["articles"])
        assert "4.1 Hội trường lớn" in annex_text

    def test_annex_without_clauses_gets_own_chapter(self):
        filler = "\n".join(f"Ghi chú {i}." for i in range(10))
        text = REGULATION + f"{filler}\nPHỤ LỤC I (tham khảo)\nCÁC HÌNH MINH HỌA\nHình I.1 Sơ đồ lối thoát nạn.\n"
        r = parse_regulation_text(text)
        assert r.chapters[-1]["number"] == "I"
        assert "Hình I.1" in r.chapters[-1]["sections"][0]["articles"][0]["content"]


class TestFallbacks:
    def test_dieu_structure(self):
        text = "QUYẾT ĐỊNH\nĐiều 1. Ban hành quy chuẩn xây dựng.\nNội dung một.\nĐiều 2. Hiệu lực thi hành.\nNội dung hai.\n"
        r = parse_regulation_text(text)
        assert r.structure == "dieu"
        numbers = [a["number"] for s in r.chapters[0]["sections"] for a in s["articles"]]
        assert numbers == ["1.0", "Điều 1", "Điều 2"]  # "QUYẾT ĐỊNH" heading text, then each Điều

    def test_plain_blocks(self):
        text = "\n".join(f"Đoạn văn không đánh số thứ {i} có nội dung đủ dài để tạo khối." for i in range(80))
        r = parse_regulation_text(text)
        assert r.structure == "blocks"
        assert r.coverage > 0.99
        assert len(r.chapters[0]["sections"][0]["articles"]) > 1


class TestPageFurniture:
    def test_running_headers_and_page_numbers_removed(self):
        pages = [
            f"CÔNG BÁO/Số 921 + 922/Ngày 20-12-2022\n{n}\nQCVN 06:2022/BXD\n"
            f"Dòng nội dung {n}.1 của trang.\nDòng nội dung {n}.2 có số 15 ở giữa.\n15\nKết thúc trang {n}.\n"
            for n in range(1, 6)
        ]
        text = strip_page_furniture(pages)
        assert "CÔNG BÁO" not in text
        assert "QCVN 06:2022/BXD" not in text
        assert "Dòng nội dung 3.2 có số 15 ở giữa." in text
        assert "\n3\n" not in f"\n{text}\n"

    def test_short_documents_untouched(self):
        assert "Tiêu đề" in strip_page_furniture(["Tiêu đề\nnội dung", "Tiêu đề\nkhác"])


class TestRequirements:
    @pytest.mark.parametrize("text,value", [("1.500", 1500.0), ("1,5", 1.5), ("2.5", 2.5), ("12.000,5", 12000.5), ("30", 30.0)])
    def test_vietnamese_numbers(self, text, value):
        assert parse_vn_number(text) == value

    def test_mm_is_not_read_as_m(self):
        reqs = extract_requirements("Chiều dày tường không nhỏ hơn 500 mm.", "1.1")
        assert [(r["min_value"], r["unit"]) for r in reqs] == [(500.0, "mm")]

    def test_minimum_and_maximum(self):
        reqs = extract_requirements("Diện tích tối thiểu là 30 m2; chiều cao không quá 1.500 mm.", "2.3")
        assert {(r["type"], r.get("min_value", r.get("max_value")), r["unit"]) for r in reqs} == {
            ("minimum_value", 30.0, "m²"), ("maximum_value", 1500.0, "mm")}
        assert all(r["description"].startswith("Điều 2.3:") for r in reqs)


def test_reflow_keeps_list_items_and_sentence_ends():
    assert reflow(["Áp dụng cho các", "trường hợp sau:", "a) nhà ở;", "- nhà xưởng.", "Câu mới"]) == \
        "Áp dụng cho các trường hợp sau:\na) nhà ở;\n- nhà xưởng.\nCâu mới"


def test_detect_codes_most_frequent_first():
    text = "QCVN 06:2022/BXD ... QCVN 06:2022/BXD ... thay thế QCVN 06:2021/BXD"
    assert detect_codes(text) == ["QCVN 06:2022/BXD", "QCVN 06:2021/BXD"]
