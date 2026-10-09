"""Static AST/lexer-based security test for frontend XSS vulnerabilities.

Enforces that every dynamic interpolation inside an HTML template literal in frontend/js/*.js
(excluding escape.js) is wrapped with escapeHtml(...) or explicitly permitted via ALLOWLIST.
"""

from pathlib import Path
import re
from typing import NamedTuple


class TemplateLiteral(NamedTuple):
    filename: str
    line: int
    static_parts: list[str]
    # Each item is (expression_string, has_nested_template, line_number)
    interpolations: list[tuple[str, bool, int]]


# ALLOWLIST: (filename, regex pattern, reason)
# Keep this list as minimal as possible per task requirements.
ALLOWLIST: list[tuple[str, str, str]] = [
    (
        "ui-polish.js",
        r"^\s*\d+\s*\+\s*Math\.random\(\)\s*\*\s*\d+\s*$",
        "Random percentage width for skeleton loading animation (pure arithmetic)",
    ),
    (
        "app.js",
        r"^\s*html\s*$",
        "_renderMarkdown: markdown processor already HTML-escapes raw text before wrapping in <p>",
    ),
    (
        "app.js",
        r"^\s*tag\s*$",
        "_renderMarkdown: hardcoded constant tag name ('td') for table cells",
    ),
    (
        "app.js",
        r"^\s*c\.trim\(\)\s*$",
        "_renderMarkdown: table cell content already HTML-escaped by earlier regex passes",
    ),
]


def extract_template_literals(js_code: str, filename: str = "<input>") -> list[TemplateLiteral]:
    """Parse JavaScript source code and extract all template literals with nesting support."""
    templates: list[TemplateLiteral] = []
    n = len(js_code)

    def skip_comment_or_string(idx: int) -> int:
        if idx >= n:
            return idx
        c = js_code[idx]
        # Line or block comment
        if c == "/" and idx + 1 < n:
            if js_code[idx + 1] == "/":
                end = js_code.find("\n", idx + 2)
                return n if end == -1 else end + 1
            if js_code[idx + 1] == "*":
                end = js_code.find("*/", idx + 2)
                return n if end == -1 else end + 2
        # Regular string literal
        if c in ('"', "'"):
            q = c
            idx += 1
            while idx < n:
                if js_code[idx] == "\\":
                    idx += 2
                    continue
                if js_code[idx] == q:
                    return idx + 1
                if js_code[idx] == "\n":
                    return idx
                idx += 1
            return idx
        return idx

    def parse_template(start_idx: int) -> int:
        start_line = js_code[:start_idx].count("\n") + 1
        idx = start_idx + 1  # Skip opening backtick
        static_parts: list[str] = []
        interpolations: list[tuple[str, bool, int]] = []
        current_static: list[str] = []

        while idx < n:
            if js_code[idx] == "\\":
                current_static.append(js_code[idx : idx + 2])
                idx += 2
                continue
            if js_code[idx] == "`":
                static_parts.append("".join(current_static))
                templates.append(
                    TemplateLiteral(
                        filename=filename,
                        line=start_line,
                        static_parts=static_parts,
                        interpolations=interpolations,
                    )
                )
                return idx + 1
            if js_code[idx : idx + 2] == "${":
                static_parts.append("".join(current_static))
                current_static = []
                interp_line = js_code[:idx].count("\n") + 1
                idx += 2
                interp_start = idx
                brace_depth = 1
                has_nested = False

                while idx < n and brace_depth > 0:
                    new_idx = skip_comment_or_string(idx)
                    if new_idx != idx:
                        idx = new_idx
                        continue
                    if js_code[idx] == "`":
                        has_nested = True
                        idx = parse_template(idx)
                        continue
                    if js_code[idx] == "{":
                        brace_depth += 1
                    elif js_code[idx] == "}":
                        brace_depth -= 1
                        if brace_depth == 0:
                            expr = js_code[interp_start:idx]
                            interpolations.append((expr, has_nested, interp_line))
                            idx += 1
                            break
                    idx += 1
                continue
            current_static.append(js_code[idx])
            idx += 1
        return idx

    idx = 0
    while idx < n:
        new_idx = skip_comment_or_string(idx)
        if new_idx != idx:
            idx = new_idx
            continue
        if js_code[idx] == "`":
            idx = parse_template(idx)
            continue
        idx += 1

    return templates


def check_js_for_xss(js_code: str, filename: str) -> list[str]:
    """Find unescaped innermost interpolations inside HTML template literals."""
    violations = []
    templates = extract_template_literals(js_code, filename)

    for tpl in templates:
        # Check if the static text of the template contains '<' (HTML template)
        has_html = any("<" in part for part in tpl.static_parts)
        if not has_html:
            continue

        for expr, has_sub_template, line_no in tpl.interpolations:
            # We check innermost interpolations (those not containing child template literals)
            if has_sub_template:
                continue

            clean = expr.strip()
            if clean.startswith("escapeHtml("):
                continue

            # Check if allowed by ALLOWLIST
            is_allowed = False
            for allowed_file, pattern, _reason in ALLOWLIST:
                if allowed_file == filename and re.match(pattern, clean):
                    is_allowed = True
                    break

            if not is_allowed:
                violations.append(
                    f"{filename}:{line_no}: Unescaped expression '${{{clean}}}' in HTML template"
                )

    return violations


class TestFrontendXSSScanner:
    """Verify that the static XSS detector correctly distinguishes safe and unsafe code."""

    def test_detector_detects_unescaped(self):
        js = "const html = `<b>${name}</b>`;"
        violations = check_js_for_xss(js, "test.js")
        assert len(violations) == 1
        assert "name" in violations[0]

    def test_detector_allows_escaped(self):
        js = "const html = `<b>${escapeHtml(name)}</b>`;"
        violations = check_js_for_xss(js, "test.js")
        assert violations == []

    def test_detector_ignores_non_html_template(self):
        js = "const id = `user_${userId}`; const style = `top: ${y}px`;"
        violations = check_js_for_xss(js, "test.js")
        assert violations == []

    def test_detector_handles_nested_templates(self):
        # Outer has <, inner has < and is unescaped -> must detect
        bad_js = "const html = `<div>${items.map(i => `<span>${i.name}</span>`)}</div>`;"
        violations = check_js_for_xss(bad_js, "test.js")
        assert len(violations) == 1
        assert "i.name" in violations[0]

        # Inner is properly escaped -> must pass
        good_js = "const html = `<div>${items.map(i => `<span>${escapeHtml(i.name)}</span>`)}</div>`;"
        violations = check_js_for_xss(good_js, "test.js")
        assert violations == []


class TestFrontendProductionFiles:
    """Scan all JavaScript files in frontend/js/ for XSS vulnerabilities."""

    def test_all_frontend_js_escaped(self):
        root_dir = Path(__file__).resolve().parents[3]
        js_dir = root_dir / "frontend" / "js"
        assert js_dir.is_dir(), f"Directory not found: {js_dir}"

        all_violations = []
        js_files = sorted(p for p in js_dir.glob("*.js") if p.name != "escape.js")
        assert len(js_files) > 0, "No JS files found to scan"

        for p in js_files:
            content = p.read_text(encoding="utf-8")
            violations = check_js_for_xss(content, p.name)
            all_violations.extend(violations)

        assert not all_violations, "Found unescaped HTML template interpolations:\n" + "\n".join(
            all_violations
        )
