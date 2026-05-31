"""QCVN/TCVN Document Crawler.

Downloads public QCVN/TCVN building standards from official Vietnamese government sources.

Sources:
- moc.gov.vn (Bộ Xây dựng)
- vbpl.vn (Cơ sở dữ liệu quốc gia)
- Các nguồn công khai khác

Usage:
    docker exec bim-backend python scripts/crawl_qcvn.py
    docker exec bim-backend python scripts/crawl_qcvn.py --list
    docker exec bim-backend python scripts/crawl_qcvn.py --code "QCVN 06:2022/BXD"
"""

import argparse
import os
import re
import time
from urllib.parse import urljoin, quote

import httpx
from bs4 import BeautifulSoup

# ===== Curated list of important AEC standards =====
STANDARDS_LIST = [
    # === QCVN (Quy chuẩn) — Bộ Xây dựng ===
    {
        "code": "QCVN 06:2022/BXD",
        "name": "An toàn cháy cho nhà và công trình",
        "priority": "critical",
        "keywords": "PCCC cháy thoát nạn chịu lửa",
    },
    {
        "code": "QCVN 03:2022/BXD",
        "name": "Phân cấp công trình phục vụ thiết kế xây dựng",
        "priority": "critical",
        "keywords": "phân cấp công trình chiều cao diện tích",
    },
    {
        "code": "QCVN 04:2021/BXD",
        "name": "Nhà ở và công trình công cộng",
        "priority": "high",
        "keywords": "nhà ở công cộng thiết kế",
    },
    {
        "code": "QCVN 01:2021/BXD",
        "name": "Quy hoạch xây dựng",
        "priority": "high",
        "keywords": "quy hoạch xây dựng đô thị",
    },
    {
        "code": "QCVN 09:2017/BXD",
        "name": "Công trình xây dựng sử dụng năng lượng hiệu quả",
        "priority": "medium",
        "keywords": "năng lượng hiệu quả tiết kiệm",
    },
    {
        "code": "QCVN 02:2022/BXD",
        "name": "Số liệu điều kiện tự nhiên dùng trong xây dựng",
        "priority": "medium",
        "keywords": "khí hậu gió mưa nhiệt độ",
    },
    # === TCVN (Tiêu chuẩn) ===
    {
        "code": "TCVN 2737:2023",
        "name": "Tải trọng và tác động — Tiêu chuẩn thiết kế",
        "priority": "critical",
        "keywords": "tải trọng hoạt tải tĩnh tải gió",
    },
    {
        "code": "TCVN 5574:2018",
        "name": "Thiết kế kết cấu bê tông và bê tông cốt thép",
        "priority": "critical",
        "keywords": "bê tông cốt thép kết cấu",
    },
    {
        "code": "TCVN 5575:2012",
        "name": "Kết cấu thép — Tiêu chuẩn thiết kế",
        "priority": "high",
        "keywords": "thép kết cấu hàn bu lông",
    },
    {
        "code": "TCVN 9386:2012",
        "name": "Thiết kế công trình chịu động đất",
        "priority": "high",
        "keywords": "động đất kháng chấn",
    },
    {
        "code": "TCVN 5738:2021",
        "name": "Hệ thống báo cháy tự động — Yêu cầu kỹ thuật",
        "priority": "medium",
        "keywords": "báo cháy đầu báo sprinkler",
    },
    {
        "code": "TCVN 3890:2023",
        "name": "Phương tiện phòng cháy chữa cháy cho nhà và công trình",
        "priority": "medium",
        "keywords": "chữa cháy bình chữa cháy trụ nước",
    },
]

OUTPUT_DIR = "data/pdf"
SEARCH_SOURCES = [
    {
        "name": "Thư viện Xây dựng",
        "search_url": "https://thuvienxaydung.net/tim-kiem?q={query}",
        "domain": "thuvienxaydung.net",
    },
]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "vi-VN,vi;q=0.9,en;q=0.8",
}


def search_standard(code: str, name: str = "") -> list[dict]:
    """Search for a standard across multiple sources.

    Args:
        code: Standard code (e.g., "QCVN 06:2022/BXD")
        name: Standard name for better search results.

    Returns:
        List of found results with download URLs.
    """
    results = []
    query = f"{code} {name}".strip()

    # Search via Google
    google_results = _search_google(query + " PDF download")
    results.extend(google_results)

    return results


def _search_google(query: str, max_results: int = 5) -> list[dict]:
    """Search Google for PDF download links."""
    results = []
    try:
        search_url = f"https://www.google.com/search?q={quote(query)}&num={max_results}"
        with httpx.Client(headers=HEADERS, follow_redirects=True, timeout=15) as client:
            resp = client.get(search_url)
            if resp.status_code == 200:
                soup = BeautifulSoup(resp.text, "html.parser")
                for link in soup.find_all("a", href=True):
                    href = link.get("href", "")
                    # Extract actual URL from Google redirect
                    if "/url?q=" in href:
                        actual_url = href.split("/url?q=")[1].split("&")[0]
                        if actual_url.endswith(".pdf"):
                            results.append({"url": actual_url, "source": "google"})
    except Exception as e:
        print(f"  ⚠️ Google search failed: {e}")

    return results


def download_pdf(url: str, filename: str, output_dir: str = OUTPUT_DIR) -> str | None:
    """Download a PDF file.

    Args:
        url: URL to download.
        filename: Output filename.
        output_dir: Directory to save to.

    Returns:
        Path to downloaded file, or None if failed.
    """
    os.makedirs(output_dir, exist_ok=True)
    filepath = os.path.join(output_dir, filename)

    if os.path.exists(filepath):
        print(f"  ⏭️  Already exists: {filepath}")
        return filepath

    try:
        with httpx.Client(headers=HEADERS, follow_redirects=True, timeout=60) as client:
            resp = client.get(url)
            if resp.status_code == 200 and len(resp.content) > 1000:
                # Verify it's actually a PDF
                if resp.content[:5] == b'%PDF-':
                    with open(filepath, "wb") as f:
                        f.write(resp.content)
                    size_mb = len(resp.content) / (1024 * 1024)
                    print(f"  ✅ Downloaded: {filepath} ({size_mb:.1f} MB)")
                    return filepath
                else:
                    print(f"  ⚠️ Not a valid PDF: {url}")
            else:
                print(f"  ❌ Download failed (status {resp.status_code}): {url}")
    except Exception as e:
        print(f"  ❌ Download error: {e}")

    return None


def crawl_all(priorities: list[str] = None):
    """Crawl and download all standards in the curated list.

    Args:
        priorities: Filter by priority level(s). Default: all.
    """
    standards = STANDARDS_LIST
    if priorities:
        standards = [s for s in standards if s["priority"] in priorities]

    print("=" * 60)
    print("🕷️  BIM AI Agent — QCVN/TCVN Crawler")
    print(f"📋 Standards to download: {len(standards)}")
    print("=" * 60)

    downloaded = []
    failed = []

    for i, std in enumerate(standards):
        code = std["code"]
        name = std["name"]
        print(f"\n[{i+1}/{len(standards)}] {code} — {name}")

        # Clean filename
        safe_code = re.sub(r'[:/\\]', '_', code).replace(' ', '_')
        filename = f"{safe_code}.pdf"

        # Check if already downloaded
        filepath = os.path.join(OUTPUT_DIR, filename)
        if os.path.exists(filepath):
            print(f"  ⏭️  Already exists, skipping")
            downloaded.append(filepath)
            continue

        # Search for download links
        results = search_standard(code, name)

        if results:
            for result in results:
                path = download_pdf(result["url"], filename)
                if path:
                    downloaded.append(path)
                    break
            else:
                print(f"  ❌ No valid PDF found")
                failed.append(code)
        else:
            print(f"  ❌ No results found")
            failed.append(code)

        # Rate limiting — be respectful
        time.sleep(2)

    # Summary
    print("\n" + "=" * 60)
    print("📊 Crawl Summary")
    print(f"   ✅ Downloaded: {len(downloaded)}")
    print(f"   ❌ Failed: {len(failed)}")
    if failed:
        print(f"   Missing: {', '.join(failed)}")
    print("\n💡 For failed downloads, you can manually download from:")
    print("   - https://moc.gov.vn (Bộ Xây dựng)")
    print("   - https://vbpl.vn (CSDL Quốc gia)")
    print("   - https://thuvienphapluat.vn")
    print(f"\n📁 Place PDF files in: {OUTPUT_DIR}/")
    print("=" * 60)

    return downloaded


def list_standards():
    """Print the curated list of standards."""
    print("\n📋 Danh sách QCVN/TCVN xây dựng trọng điểm:\n")
    print(f"{'Mã':<25} {'Ưu tiên':<10} {'Tên'}")
    print("-" * 80)
    for std in STANDARDS_LIST:
        priority_emoji = {"critical": "🔴", "high": "🟡", "medium": "🟢"}.get(std["priority"], "⚪")
        print(f"{std['code']:<25} {priority_emoji} {std['priority']:<7} {std['name']}")

    print(f"\n📊 Tổng: {len(STANDARDS_LIST)} tiêu chuẩn")
    print(f"   🔴 Critical: {sum(1 for s in STANDARDS_LIST if s['priority'] == 'critical')}")
    print(f"   🟡 High: {sum(1 for s in STANDARDS_LIST if s['priority'] == 'high')}")
    print(f"   🟢 Medium: {sum(1 for s in STANDARDS_LIST if s['priority'] == 'medium')}")


def main():
    parser = argparse.ArgumentParser(description="Crawl QCVN/TCVN PDF documents")
    parser.add_argument("--list", action="store_true", help="List available standards")
    parser.add_argument("--code", type=str, help="Download a specific standard by code")
    parser.add_argument("--priority", type=str, choices=["critical", "high", "medium"],
                        help="Filter by priority")
    parser.add_argument("--all", action="store_true", help="Download all standards")
    parser.add_argument("--output", type=str, default=OUTPUT_DIR, help="Output directory")
    args = parser.parse_args()

    global OUTPUT_DIR
    if args.output:
        OUTPUT_DIR = args.output

    if args.list:
        list_standards()
    elif args.code:
        # Find in list or create ad-hoc
        std = next((s for s in STANDARDS_LIST if s["code"] == args.code), None)
        name = std["name"] if std else ""
        safe_code = re.sub(r'[:/\\]', '_', args.code).replace(' ', '_')
        results = search_standard(args.code, name)
        if results:
            download_pdf(results[0]["url"], f"{safe_code}.pdf")
        else:
            print(f"❌ No PDF found for {args.code}")
            print("💡 Try downloading manually from moc.gov.vn or thuvienphapluat.vn")
    elif args.all:
        crawl_all()
    elif args.priority:
        crawl_all(priorities=[args.priority])
    else:
        # Default: download critical standards only
        crawl_all(priorities=["critical"])


if __name__ == "__main__":
    main()
