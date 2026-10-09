"""Automated knowledge refresh pipeline for QCVN/TCVN regulations.

Orchestrates: crawl -> parse -> corpus fingerprinting -> (on change/force) ingest Qdrant -> build Neo4j graph.
"""

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import time
from typing import Any, Callable, Optional

import structlog

logger = structlog.get_logger()


@dataclass
class StepResult:
    name: str  # "crawl" | "parse" | "ingest" | "graph"
    status: str  # "ok" | "skipped" | "failed"
    seconds: float
    detail: dict = field(default_factory=dict)


def corpus_fingerprint(parsed_dir: Path) -> str:
    """Compute sha256 fingerprint over (filename, content bytes) of non-underscore JSON files.

    Returns "" if directory is empty or does not exist.
    """
    parsed_dir = Path(parsed_dir)
    if not parsed_dir.is_dir():
        return ""
    files = sorted(f for f in os.listdir(parsed_dir) if f.endswith(".json") and not f.startswith("_"))
    if not files:
        return ""
    hasher = hashlib.sha256()
    for filename in files:
        content = (parsed_dir / filename).read_bytes()
        hasher.update(filename.encode("utf-8"))
        hasher.update(content)
    return hasher.hexdigest()


def _save_and_return_report(
    report_path: Path,
    steps: list[StepResult],
    started_at: str,
    fingerprint: str,
    changed: bool,
) -> dict[str, Any]:
    ok = not any(s.status == "failed" for s in steps)
    finished_at = datetime.now(timezone.utc).isoformat()
    report: dict[str, Any] = {
        "ok": ok,
        "started_at": started_at,
        "finished_at": finished_at,
        "fingerprint": fingerprint,
        "changed": changed,
        "steps": [asdict(s) for s in steps],
    }
    try:
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as e:
        logger.error("write_report_failed", error=str(e), path=str(report_path))
    return report


def run_refresh(
    data_dir: Path,
    *,
    crawl: bool = True,
    force: bool = False,
    crawl_fn: Optional[Callable[[Path], Any]] = None,
    parse_fn: Optional[Callable[[Path, Path], Any]] = None,
    ingest_fn: Optional[Callable[[Path], Any]] = None,
    graph_fn: Optional[Callable[[Path], Any]] = None,
    index_empty_fn: Optional[Callable[[], bool]] = None,
    clock: Callable[[], float] = time.time,
) -> dict[str, Any]:
    """Execute a single cycle of the knowledge refresh pipeline."""
    data_dir = Path(data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    parsed_dir = data_dir / "parsed"
    state_path = data_dir / "refresh_state.json"
    report_path = data_dir / "refresh_report.json"

    started_at = datetime.now(timezone.utc).isoformat()
    steps: list[StepResult] = []
    fingerprint = ""
    changed = False

    # 1. Crawl
    if crawl:
        if crawl_fn is None:
            def _default_crawl(dd: Path) -> Any:
                from scripts.crawl_vbpl_bxd import VbplBxdCrawler
                crawler = VbplBxdCrawler(output_dir=dd)
                try:
                    return crawler.run()
                finally:
                    crawler.close()
            crawl_fn = _default_crawl

        t0 = clock()
        try:
            res = crawl_fn(data_dir)
            detail: dict[str, Any] = {}
            if isinstance(res, list):
                detail["count"] = len(res)
                detail["errors"] = sum(1 for item in res if isinstance(item, dict) and "error" in item)
            elif isinstance(res, dict):
                detail["count"] = len(res)
            steps.append(StepResult(name="crawl", status="ok", seconds=round(clock() - t0, 3), detail=detail))
            logger.info("refresh_step_completed", step="crawl", **detail)
        except Exception as e:
            err = f"{type(e).__name__}: {e}"
            steps.append(StepResult(name="crawl", status="failed", seconds=round(clock() - t0, 3), detail={"error": err}))
            logger.error("refresh_step_failed", step="crawl", error=err)
            return _save_and_return_report(report_path, steps, started_at, fingerprint, changed)
    else:
        steps.append(StepResult(name="crawl", status="skipped", seconds=0.0, detail={}))
        logger.info("refresh_step_skipped", step="crawl")

    # 2. Parse
    if parse_fn is None:
        from src.data_pipeline.vbpl_corpus import build_corpus
        parse_fn = build_corpus

    t0 = clock()
    try:
        parse_res = parse_fn(data_dir, parsed_dir)
        detail = {}
        if isinstance(parse_res, dict):
            for k in ("documents", "standards", "full_text", "articles"):
                if k in parse_res:
                    detail[k] = parse_res[k]
        steps.append(StepResult(name="parse", status="ok", seconds=round(clock() - t0, 3), detail=detail))
        logger.info("refresh_step_completed", step="parse", **detail)
    except Exception as e:
        err = f"{type(e).__name__}: {e}"
        steps.append(StepResult(name="parse", status="failed", seconds=round(clock() - t0, 3), detail={"error": err}))
        logger.error("refresh_step_failed", step="parse", error=err)
        return _save_and_return_report(report_path, steps, started_at, fingerprint, changed)

    # 3. Fingerprint & change detection
    fingerprint = corpus_fingerprint(parsed_dir)
    state: dict[str, Any] = {}
    if state_path.is_file():
        try:
            state = json.loads(state_path.read_text(encoding="utf-8"))
        except Exception as e:
            logger.warning("read_state_failed", error=str(e))

    changed = fingerprint != state.get("fingerprint")

    if index_empty_fn is None:
        def _default_index_empty() -> bool:
            from src.embeddings.vector_store import get_collection_info
            info = get_collection_info()
            return info.get("status") == "not_found" or info.get("points_count", 0) == 0
        index_empty_fn = _default_index_empty

    is_empty = False
    try:
        is_empty = bool(index_empty_fn())
    except Exception as e:
        logger.warning("check_index_empty_failed", error=str(e))

    should_run = force or changed or is_empty

    if not should_run:
        steps.append(StepResult(name="ingest", status="skipped", seconds=0.0, detail={"reason": "corpus unchanged"}))
        steps.append(StepResult(name="graph", status="skipped", seconds=0.0, detail={"reason": "corpus unchanged"}))
        logger.info("refresh_steps_skipped", reason="corpus unchanged")
        return _save_and_return_report(report_path, steps, started_at, fingerprint, changed)

    # 4. Ingest
    if ingest_fn is None:
        from src.data_pipeline.ingest import ingest_json_dir
        ingest_fn = ingest_json_dir

    t0 = clock()
    try:
        ingest_res = ingest_fn(parsed_dir)
        detail = ingest_res if isinstance(ingest_res, dict) else {}
        steps.append(StepResult(name="ingest", status="ok", seconds=round(clock() - t0, 3), detail=detail))
        logger.info("refresh_step_completed", step="ingest", **detail)
    except Exception as e:
        err = f"{type(e).__name__}: {e}"
        steps.append(StepResult(name="ingest", status="failed", seconds=round(clock() - t0, 3), detail={"error": err}))
        logger.error("refresh_step_failed", step="ingest", error=err)
        return _save_and_return_report(report_path, steps, started_at, fingerprint, changed)

    # 5. Graph
    if graph_fn is None:
        from src.knowledge_graph.graph_builder import build_graph_for_corpus
        graph_fn = build_graph_for_corpus

    t0 = clock()
    try:
        graph_res = graph_fn(parsed_dir)
        detail = graph_res if isinstance(graph_res, dict) else {}
        steps.append(StepResult(name="graph", status="ok", seconds=round(clock() - t0, 3), detail=detail))
        logger.info("refresh_step_completed", step="graph", **detail)
    except Exception as e:
        err = f"{type(e).__name__}: {e}"
        steps.append(StepResult(name="graph", status="failed", seconds=round(clock() - t0, 3), detail={"error": err}))
        logger.error("refresh_step_failed", step="graph", error=err)
        return _save_and_return_report(report_path, steps, started_at, fingerprint, changed)

    # 6. Save state only when ingest and graph are both ok
    try:
        state_data = {
            "fingerprint": fingerprint,
            "completed_at": datetime.now(timezone.utc).isoformat(),
        }
        state_path.write_text(json.dumps(state_data, ensure_ascii=False, indent=2), encoding="utf-8")
        logger.info("state_saved", fingerprint=fingerprint)
    except Exception as e:
        logger.error("write_state_failed", error=str(e))

    return _save_and_return_report(report_path, steps, started_at, fingerprint, changed)


def run_loop(
    data_dir: Path,
    *,
    interval_hours: float,
    max_runs: int | None = None,
    sleep: Callable[[float], Any] = time.sleep,
    **refresh_kwargs: Any,
) -> None:
    """Run knowledge refresh periodically."""
    runs = 0
    while max_runs is None or runs < max_runs:
        try:
            logger.info("loop_refresh_run_start", run=runs + 1, data_dir=str(data_dir))
            run_refresh(data_dir, **refresh_kwargs)
        except Exception as e:
            logger.error("loop_refresh_run_failed", run=runs + 1, error=str(e))
        runs += 1
        if max_runs is not None and runs >= max_runs:
            break
        sleep(interval_hours * 3600)
