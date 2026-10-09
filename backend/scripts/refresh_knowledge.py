"""Automated knowledge refresh for QCVN/TCVN regulations.

Full pipeline: crawl vbpl.vn -> parse corpus -> chunk & embed into Qdrant -> build Neo4j graph.
Supports single-run or periodic loop (--loop) mode.

Usage:
    # 1. Local single run:
    python backend/scripts/refresh_knowledge.py

    # Local run skipping crawl (re-use existing crawled files):
    python backend/scripts/refresh_knowledge.py --skip-crawl

    # Local run forcing full ingest & graph rebuild even if corpus is unchanged:
    python backend/scripts/refresh_knowledge.py --force

    # 2. Inside docker container:
    docker exec bim-backend python scripts/refresh_knowledge.py
    docker exec bim-backend python scripts/refresh_knowledge.py --skip-crawl --force

    # 3. Docker Compose service (runs periodically via --loop):
    # Service 'knowledge-refresh' defined in docker-compose.yml runs:
    # python scripts/refresh_knowledge.py --loop --interval-hours 168
"""

import argparse
from pathlib import Path
import sys

from src.data_pipeline.knowledge_refresh import run_loop, run_refresh

DEFAULT_DATA_DIR = Path(__file__).resolve().parents[1] / "data" / "vbpl_bxd"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Automated knowledge refresh for QCVN/TCVN")
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=DEFAULT_DATA_DIR,
        help="Path to vbpl data directory (default: backend/data/vbpl_bxd)",
    )
    parser.add_argument("--skip-crawl", action="store_true", help="Skip crawling vbpl.vn")
    parser.add_argument("--force", action="store_true", help="Force ingest and graph rebuild even if corpus is unchanged")
    parser.add_argument("--loop", action="store_true", help="Run periodically in an infinite loop")
    parser.add_argument(
        "--interval-hours",
        type=float,
        default=168.0,
        help="Loop interval in hours (default: 168)",
    )
    args = parser.parse_args(argv)

    if args.loop:
        print(f"🔄 Starting knowledge refresh loop (interval: {args.interval_hours}h, dir: {args.data_dir})...")
        run_loop(
            args.data_dir,
            interval_hours=args.interval_hours,
            crawl=not args.skip_crawl,
            force=args.force,
        )
        return 0

    print("=" * 60)
    print("🔄 BIM AI Agent — Knowledge Refresh")
    print(f"   Data dir: {args.data_dir}")
    print(f"   Crawl: {'No' if args.skip_crawl else 'Yes'} | Force: {'Yes' if args.force else 'No'}")
    print("=" * 60)

    report = run_refresh(
        args.data_dir,
        crawl=not args.skip_crawl,
        force=args.force,
    )

    print("\nSummary:")
    for step in report.get("steps", []):
        name = step.get("name", "")
        status = step.get("status", "")
        sec = step.get("seconds", 0.0)
        detail = step.get("detail", {})
        print(f"  - {name:<8}: {status:<8} ({sec:.2f}s) {detail}")

    print("=" * 60)
    if report.get("ok"):
        print(f"✅ Refresh completed successfully! (changed={report.get('changed')})")
        return 0
    else:
        print("❌ Refresh finished with errors.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
