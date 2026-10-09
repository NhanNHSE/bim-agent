"""Unit tests for automated knowledge refresh pipeline and ingest module."""

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from scripts import refresh_knowledge
from src.data_pipeline import ingest
from src.data_pipeline.knowledge_refresh import (
    corpus_fingerprint,
    run_loop,
    run_refresh,
)
from src.knowledge_graph import graph_builder
from src.embeddings import vector_store


def create_fake_corpus(parsed_dir: Path) -> dict:
    parsed_dir.mkdir(parents=True, exist_ok=True)
    std1 = {
        "standard_code": "QCVN 1:2024/BXD",
        "standard_name": "Quy chuẩn kỹ thuật quốc gia 1",
        "chapters": [
            {
                "number": "1",
                "title": "Quy định chung",
                "sections": [
                    {
                        "number": "1.1",
                        "title": "Phạm vi điều chỉnh",
                        "articles": [
                            {
                                "number": "1.1.1",
                                "title": "Phạm vi",
                                "content": "Nội dung điều khoản quy chuẩn 1.",
                            }
                        ],
                    }
                ],
            }
        ],
    }
    std2 = {
        "standard_code": "QCVN 2:2024/BXD",
        "standard_name": "Quy chuẩn kỹ thuật quốc gia 2",
        "chapters": [
            {
                "number": "1",
                "title": "Quy định chung",
                "sections": [
                    {
                        "number": "1.1",
                        "title": "Phạm vi điều chỉnh",
                        "articles": [
                            {
                                "number": "1.1.1",
                                "title": "Phạm vi",
                                "content": "Nội dung điều khoản quy chuẩn 2.",
                            }
                        ],
                    }
                ],
            }
        ],
    }
    (parsed_dir / "qcvn_01.json").write_text(json.dumps(std1, ensure_ascii=False), encoding="utf-8")
    (parsed_dir / "qcvn_02.json").write_text(json.dumps(std2, ensure_ascii=False), encoding="utf-8")
    return {
        "documents": 2,
        "standards": 2,
        "full_text": 1,
        "articles": 5,
        "items": [],
    }


def make_fake_fns():
    crawl_calls = []
    parse_calls = []
    ingest_calls = []
    graph_calls = []

    def fake_crawl(data_dir):
        crawl_calls.append(data_dir)
        return [{"id": 1}, {"id": 2}]

    def fake_parse(data_dir, parsed_dir):
        parse_calls.append((data_dir, parsed_dir))
        return create_fake_corpus(parsed_dir)

    def fake_ingest(parsed_dir):
        ingest_calls.append(parsed_dir)
        return {"chunks": 10, "sources": 2}

    def fake_graph(parsed_dir):
        graph_calls.append(parsed_dir)
        return {"nodes": 20, "relationships": 30}

    return fake_crawl, fake_parse, fake_ingest, fake_graph, crawl_calls, parse_calls, ingest_calls, graph_calls


def test_first_run(tmp_path):
    """1. Lần chạy đầu: 4 step đều ok, ok=True, changed=True, có refresh_state.json và refresh_report.json; mỗi fake ingest/graph được gọi đúng 1 lần."""
    fake_crawl, fake_parse, fake_ingest, fake_graph, _, _, ingest_calls, graph_calls = make_fake_fns()

    report = run_refresh(
        tmp_path,
        crawl_fn=fake_crawl,
        parse_fn=fake_parse,
        ingest_fn=fake_ingest,
        graph_fn=fake_graph,
        index_empty_fn=lambda: False,
    )

    assert report["ok"] is True
    assert report["changed"] is True
    assert len(report["steps"]) == 4
    assert all(s["status"] == "ok" for s in report["steps"])
    assert (tmp_path / "refresh_state.json").exists()
    assert (tmp_path / "refresh_report.json").exists()
    assert len(ingest_calls) == 1
    assert len(graph_calls) == 1

    state = json.loads((tmp_path / "refresh_state.json").read_text(encoding="utf-8"))
    assert state.get("fingerprint") == report["fingerprint"]
    assert "completed_at" in state


def test_second_run_unchanged(tmp_path):
    """2. Lần hai, cùng nội dung (fake index_empty_fn trả False): ingest và graph skipped, không được gọi; ok=True, changed=False."""
    fake_crawl, fake_parse, fake_ingest, fake_graph, _, _, ingest_calls, graph_calls = make_fake_fns()

    # Run 1
    run_refresh(
        tmp_path,
        crawl_fn=fake_crawl,
        parse_fn=fake_parse,
        ingest_fn=fake_ingest,
        graph_fn=fake_graph,
        index_empty_fn=lambda: False,
    )
    ingest_calls.clear()
    graph_calls.clear()

    # Run 2
    report2 = run_refresh(
        tmp_path,
        crawl_fn=fake_crawl,
        parse_fn=fake_parse,
        ingest_fn=fake_ingest,
        graph_fn=fake_graph,
        index_empty_fn=lambda: False,
    )

    assert report2["ok"] is True
    assert report2["changed"] is False
    assert len(ingest_calls) == 0
    assert len(graph_calls) == 0
    steps_by_name = {s["name"]: s for s in report2["steps"]}
    assert steps_by_name["ingest"]["status"] == "skipped"
    assert steps_by_name["ingest"]["detail"] == {"reason": "corpus unchanged"}
    assert steps_by_name["graph"]["status"] == "skipped"
    assert steps_by_name["graph"]["detail"] == {"reason": "corpus unchanged"}


def test_force_run(tmp_path):
    """3. force=True, nội dung không đổi: ingest và graph được gọi lại."""
    fake_crawl, fake_parse, fake_ingest, fake_graph, _, _, ingest_calls, graph_calls = make_fake_fns()

    # Run 1
    run_refresh(
        tmp_path,
        crawl_fn=fake_crawl,
        parse_fn=fake_parse,
        ingest_fn=fake_ingest,
        graph_fn=fake_graph,
        index_empty_fn=lambda: False,
    )
    ingest_calls.clear()
    graph_calls.clear()

    # Run 2 with force=True
    report_forced = run_refresh(
        tmp_path,
        force=True,
        crawl_fn=fake_crawl,
        parse_fn=fake_parse,
        ingest_fn=fake_ingest,
        graph_fn=fake_graph,
        index_empty_fn=lambda: False,
    )

    assert report_forced["ok"] is True
    assert len(ingest_calls) == 1
    assert len(graph_calls) == 1
    steps_by_name = {s["name"]: s for s in report_forced["steps"]}
    assert steps_by_name["ingest"]["status"] == "ok"
    assert steps_by_name["graph"]["status"] == "ok"


def test_index_empty_triggers_ingest(tmp_path):
    """4. Nội dung không đổi nhưng index_empty_fn trả True: ingest được gọi."""
    fake_crawl, fake_parse, fake_ingest, fake_graph, _, _, ingest_calls, graph_calls = make_fake_fns()

    # Run 1
    run_refresh(
        tmp_path,
        crawl_fn=fake_crawl,
        parse_fn=fake_parse,
        ingest_fn=fake_ingest,
        graph_fn=fake_graph,
        index_empty_fn=lambda: False,
    )
    ingest_calls.clear()
    graph_calls.clear()

    # Run 2 with index_empty_fn returning True
    report = run_refresh(
        tmp_path,
        crawl_fn=fake_crawl,
        parse_fn=fake_parse,
        ingest_fn=fake_ingest,
        graph_fn=fake_graph,
        index_empty_fn=lambda: True,
    )

    assert report["ok"] is True
    assert len(ingest_calls) == 1
    assert len(graph_calls) == 1
    steps_by_name = {s["name"]: s for s in report["steps"]}
    assert steps_by_name["ingest"]["status"] == "ok"


def test_crawl_failure(tmp_path):
    """5. crawl raise RuntimeError("vbpl down"): parse, ingest, graph KHÔNG được gọi; ok=False; step crawl failed có "RuntimeError: vbpl down"; report vẫn được ghi; state không tồn tại."""
    fake_crawl, fake_parse, fake_ingest, fake_graph, _, parse_calls, ingest_calls, graph_calls = make_fake_fns()

    def failing_crawl(data_dir):
        raise RuntimeError("vbpl down")

    report = run_refresh(
        tmp_path,
        crawl_fn=failing_crawl,
        parse_fn=fake_parse,
        ingest_fn=fake_ingest,
        graph_fn=fake_graph,
        index_empty_fn=lambda: False,
    )

    assert report["ok"] is False
    assert len(parse_calls) == 0
    assert len(ingest_calls) == 0
    assert len(graph_calls) == 0
    assert len(report["steps"]) == 1
    crawl_step = report["steps"][0]
    assert crawl_step["name"] == "crawl"
    assert crawl_step["status"] == "failed"
    assert "RuntimeError: vbpl down" in crawl_step["detail"]["error"]
    assert (tmp_path / "refresh_report.json").exists()
    assert not (tmp_path / "refresh_state.json").exists()


def test_ingest_failure_and_retry(tmp_path):
    """6. ingest raise: graph không được gọi, state không được ghi; lần chạy kế tiếp (ingest bình thường) phải chạy ingest (vì chưa có state)."""
    fake_crawl, fake_parse, fake_ingest, fake_graph, _, _, ingest_calls, graph_calls = make_fake_fns()

    def failing_ingest(parsed_dir):
        raise RuntimeError("qdrant connection refused")

    # Run 1: ingest fails
    report1 = run_refresh(
        tmp_path,
        crawl_fn=fake_crawl,
        parse_fn=fake_parse,
        ingest_fn=failing_ingest,
        graph_fn=fake_graph,
        index_empty_fn=lambda: False,
    )
    assert report1["ok"] is False
    assert len(graph_calls) == 0
    assert not (tmp_path / "refresh_state.json").exists()
    steps1_by_name = {s["name"]: s for s in report1["steps"]}
    assert steps1_by_name["ingest"]["status"] == "failed"
    assert "graph" not in steps1_by_name

    # Run 2: normal ingest
    report2 = run_refresh(
        tmp_path,
        crawl_fn=fake_crawl,
        parse_fn=fake_parse,
        ingest_fn=fake_ingest,
        graph_fn=fake_graph,
        index_empty_fn=lambda: False,
    )
    assert report2["ok"] is True
    assert len(ingest_calls) == 1
    assert len(graph_calls) == 1
    assert (tmp_path / "refresh_state.json").exists()


def test_skip_crawl(tmp_path):
    """7. crawl=False: step crawl skipped, crawl_fn không được gọi."""
    fake_crawl, fake_parse, fake_ingest, fake_graph, crawl_calls, _, _, _ = make_fake_fns()

    report = run_refresh(
        tmp_path,
        crawl=False,
        crawl_fn=fake_crawl,
        parse_fn=fake_parse,
        ingest_fn=fake_ingest,
        graph_fn=fake_graph,
        index_empty_fn=lambda: False,
    )

    assert report["ok"] is True
    assert len(crawl_calls) == 0
    crawl_step = next(s for s in report["steps"] if s["name"] == "crawl")
    assert crawl_step["status"] == "skipped"


def test_corpus_fingerprint(tmp_path):
    """8. corpus_fingerprint: bỏ qua _report.json; không phụ thuộc thứ tự tạo file; đổi nội dung một file thì fingerprint đổi; thư mục rỗng trả ""."""
    parsed_dir = tmp_path / "parsed"
    parsed_dir.mkdir()

    # Empty directory returns ""
    assert corpus_fingerprint(parsed_dir) == ""
    assert corpus_fingerprint(tmp_path / "nonexistent") == ""

    # Create files
    file_b = parsed_dir / "b.json"
    file_a = parsed_dir / "a.json"
    file_b.write_text('{"code": "B"}', encoding="utf-8")
    file_a.write_text('{"code": "A"}', encoding="utf-8")

    fp1 = corpus_fingerprint(parsed_dir)
    assert fp1 != ""

    # Ignored report file starting with "_"
    report_file = parsed_dir / "_report.json"
    report_file.write_text('{"report": "some stats"}', encoding="utf-8")
    fp2 = corpus_fingerprint(parsed_dir)
    assert fp1 == fp2

    # Independent of file creation order
    parsed_dir_alt = tmp_path / "parsed_alt"
    parsed_dir_alt.mkdir()
    (parsed_dir_alt / "a.json").write_text('{"code": "A"}', encoding="utf-8")
    (parsed_dir_alt / "b.json").write_text('{"code": "B"}', encoding="utf-8")
    assert corpus_fingerprint(parsed_dir_alt) == fp1

    # Changing content changes fingerprint
    (parsed_dir / "a.json").write_text('{"code": "A_modified"}', encoding="utf-8")
    fp3 = corpus_fingerprint(parsed_dir)
    assert fp3 != fp1


def test_run_loop(tmp_path):
    """9. run_loop(max_runs=3) với fake sleep ghi lại đối số: chạy 3 lượt, sleep được gọi với interval_hours * 3600; một lượt raise (parse_fn raise ở lượt 2) không làm dừng vòng lặp."""
    sleep_calls = []
    runs = []

    def fake_sleep(duration):
        sleep_calls.append(duration)

    def counting_parse(data_dir, parsed_dir):
        runs.append(len(runs) + 1)
        if len(runs) == 2:
            raise RuntimeError("Transient parse error on run 2")
        return create_fake_corpus(parsed_dir)

    fake_crawl, _, fake_ingest, fake_graph, _, _, _, _ = make_fake_fns()

    run_loop(
        tmp_path,
        interval_hours=2.0,
        max_runs=3,
        sleep=fake_sleep,
        crawl_fn=fake_crawl,
        parse_fn=counting_parse,
        ingest_fn=fake_ingest,
        graph_fn=fake_graph,
        index_empty_fn=lambda: False,
    )

    assert len(runs) == 3
    assert len(sleep_calls) == 2
    assert all(s == 2.0 * 3600 for s in sleep_calls)


def test_cli_main(monkeypatch):
    """10. CLI: main() trong scripts/refresh_knowledge.py trả 1 khi run_refresh cho ok=False và 0 khi ok=True (monkeypatch run_refresh, giả lập sys.argv)."""
    monkeypatch.setattr("sys.argv", ["refresh_knowledge.py", "--skip-crawl"])

    # ok=True -> returns 0
    monkeypatch.setattr(
        refresh_knowledge,
        "run_refresh",
        lambda *args, **kwargs: {"ok": True, "changed": True, "steps": []},
    )
    exit_code_ok = refresh_knowledge.main()
    assert exit_code_ok == 0

    # ok=False -> returns 1
    monkeypatch.setattr(
        refresh_knowledge,
        "run_refresh",
        lambda *args, **kwargs: {
            "ok": False,
            "changed": False,
            "steps": [{"name": "crawl", "status": "failed", "seconds": 0.1, "detail": {"error": "down"}}],
        },
    )
    exit_code_err = refresh_knowledge.main()
    assert exit_code_err == 1


def test_ingest_json_dir(tmp_path, monkeypatch):
    """11. ingest.ingest_json_dir: monkeypatch embed_texts, upsert_chunks, ensure_collection, prune_sources trong module ingest. Kiểm tra trả đúng số chunk và prune_sources nhận đúng tập source_id. Với prune=False thì không gọi prune_sources. Thư mục rỗng thì ValueError."""
    mock_embed = MagicMock(side_effect=lambda texts: [[0.1] * 128 for _ in texts])
    mock_upsert = MagicMock()
    mock_ensure = MagicMock()
    mock_prune = MagicMock()

    monkeypatch.setattr(ingest, "embed_texts", mock_embed)
    monkeypatch.setattr(ingest, "upsert_chunks", mock_upsert)
    monkeypatch.setattr(ingest, "ensure_collection", mock_ensure)
    monkeypatch.setattr(ingest, "prune_sources", mock_prune)

    # Empty directory raises ValueError
    empty_dir = tmp_path / "empty"
    empty_dir.mkdir()
    with pytest.raises(ValueError):
        ingest.ingest_json_dir(empty_dir)

    # Directory with parsed json files
    parsed_dir = tmp_path / "parsed"
    create_fake_corpus(parsed_dir)

    # 1. Ingest with prune=True (default)
    result = ingest.ingest_json_dir(parsed_dir, prune=True)
    assert result["chunks"] > 0
    assert result["sources"] == 2
    mock_ensure.assert_called()
    mock_upsert.assert_called_once()
    mock_prune.assert_called_once_with({"QCVN 1:2024/BXD", "QCVN 2:2024/BXD"})

    # 2. Ingest with prune=False
    mock_prune.reset_mock()
    result_no_prune = ingest.ingest_json_dir(parsed_dir, prune=False)
    assert result_no_prune["chunks"] > 0
    mock_prune.assert_not_called()


def test_ingest_corrupted_json_fails_before_upsert_and_prune(tmp_path, monkeypatch):
    """12. Corrupted JSON file in directory causes ingest_json_dir to raise; upsert_chunks and prune_sources are not called."""
    mock_upsert = MagicMock()
    mock_prune = MagicMock()
    mock_ensure = MagicMock()

    monkeypatch.setattr(ingest, "upsert_chunks", mock_upsert)
    monkeypatch.setattr(ingest, "prune_sources", mock_prune)
    monkeypatch.setattr(ingest, "ensure_collection", mock_ensure)

    parsed_dir = tmp_path / "parsed"
    parsed_dir.mkdir()
    valid_data = {
        "standard_code": "QCVN 1:2024/BXD",
        "standard_name": "Valid QCVN",
        "chapters": [],
    }
    (parsed_dir / "valid.json").write_text(json.dumps(valid_data, ensure_ascii=False), encoding="utf-8")
    (parsed_dir / "broken.json").write_text("{not json", encoding="utf-8")

    with pytest.raises(Exception):
        ingest.ingest_json_dir(parsed_dir)

    mock_upsert.assert_not_called()
    mock_prune.assert_not_called()


def test_build_graph_missing_standard_code_fails_before_build_and_prune(tmp_path, monkeypatch):
    """13. File missing standard_code causes build_graph_for_corpus to raise ValueError; build_graph_from_directory and prune_standards are not called."""
    mock_build_dir = MagicMock()
    mock_prune_std = MagicMock()

    monkeypatch.setattr(graph_builder, "build_graph_from_directory", mock_build_dir)
    monkeypatch.setattr(graph_builder, "prune_standards", mock_prune_std)

    parsed_dir = tmp_path / "parsed"
    parsed_dir.mkdir()
    (parsed_dir / "missing_code.json").write_text('{"name": "No code"}', encoding="utf-8")

    with pytest.raises(ValueError) as excinfo:
        graph_builder.build_graph_for_corpus(parsed_dir)

    assert "missing_code.json" in str(excinfo.value)
    mock_build_dir.assert_not_called()
    mock_prune_std.assert_not_called()


def test_crawl_errors_detail(tmp_path):
    """14. Step crawl counts items with 'error' key when crawl returns a list; step remains ok."""
    def fake_crawl(data_dir):
        return [{"id": "1"}, {"id": "2", "error": "x"}]

    def fake_parse(data_dir, parsed_dir):
        return create_fake_corpus(parsed_dir)

    report = run_refresh(
        tmp_path,
        crawl_fn=fake_crawl,
        parse_fn=fake_parse,
        ingest_fn=lambda p: {"chunks": 1, "sources": 1},
        graph_fn=lambda p: {"nodes": 1, "relationships": 1},
        index_empty_fn=lambda: False,
    )

    crawl_step = next(s for s in report["steps"] if s["name"] == "crawl")
    assert crawl_step["status"] == "ok"
    assert crawl_step["detail"] == {"count": 2, "errors": 1}


def test_build_graph_empty_and_nonexistent_dir(tmp_path, monkeypatch):
    """15. Empty or nonexistent directory causes build_graph_for_corpus to raise ValueError; build_graph_from_directory and prune_standards are not called."""
    mock_build_dir = MagicMock()
    mock_prune_std = MagicMock()

    monkeypatch.setattr(graph_builder, "build_graph_from_directory", mock_build_dir)
    monkeypatch.setattr(graph_builder, "prune_standards", mock_prune_std)

    # Empty directory
    empty_dir = tmp_path / "empty"
    empty_dir.mkdir()
    with pytest.raises(ValueError, match="No standard JSON files"):
        graph_builder.build_graph_for_corpus(empty_dir)

    # Nonexistent directory
    nonexistent_dir = tmp_path / "nonexistent"
    with pytest.raises(ValueError, match="No standard JSON files"):
        graph_builder.build_graph_for_corpus(nonexistent_dir)

    mock_build_dir.assert_not_called()
    mock_prune_std.assert_not_called()


def test_prune_standards_empty_keep_raises(monkeypatch):
    """16. Empty keep set causes prune_standards to raise ValueError; run_write_query is not called."""
    mock_run_write = MagicMock()
    monkeypatch.setattr(graph_builder, "run_write_query", mock_run_write)

    with pytest.raises(ValueError, match="refusing to prune with an empty keep set"):
        graph_builder.prune_standards(set())

    mock_run_write.assert_not_called()


def test_prune_sources_empty_keep_raises(monkeypatch):
    """17. Empty keep set causes vector_store.prune_sources to raise ValueError; get_client is not called."""
    mock_get_client = MagicMock()
    monkeypatch.setattr(vector_store, "get_client", mock_get_client)

    with pytest.raises(ValueError, match="refusing to prune with an empty keep set"):
        vector_store.prune_sources(set())

    mock_get_client.assert_not_called()


