"""Acceptance tests for task 014 (review fixes, 2026-11-05). LOCKED — written by the reviewer.

Covers:
  A. IFC download via short-lived download token (the old ?token= link always returned 401)
  B. nginx: upload size limit and security headers
  C. Client IP behind the nginx proxy for auth rate limiting; backend port bound to localhost in prod
  D. No internal error text in HTTP responses of the IFC router
  E. Single, filename-checked GET /api/v1/ifc/geometry/{filename}
  F. /health reports Qdrant points_count
"""

import re
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi import HTTPException
from starlette.requests import Request

REPO_ROOT = Path(__file__).resolve().parents[3]
IN_CHECKOUT = (REPO_ROOT / "docker-compose.yml").exists()
needs_checkout = pytest.mark.skipif(
    not IN_CHECKOUT,
    reason="frontend/ và docker-compose.yml không có trong image backend; chạy ở job Unit Tests trên checkout repo",
)

LEAK = "LEAK-/app/secret/path"


@pytest.fixture
def ifc_dir(tmp_path, monkeypatch):
    """Point the IFC router at an empty temp upload dir."""
    from src.api import router_ifc
    monkeypatch.setattr(router_ifc.settings, "ifc_upload_dir", str(tmp_path))
    return tmp_path


def _user_id(client, headers) -> str:
    return str(client.get("/api/v1/auth/me", headers=headers).json()["sub"])


# ── A. Download token ─────────────────────────────────────────────────────────

class TestDownloadToken:
    def test_token_endpoint_returns_url_that_downloads_without_header(self, client, auth_headers, ifc_dir):
        (ifc_dir / "house.ifc").write_bytes(b"ISO-10303-21;\nHOUSE\n")
        res = client.post("/api/v1/ifc/download-token/house.ifc", headers=auth_headers)
        assert res.status_code == 200
        body = res.json()
        assert body["expires_in"] == 60
        assert body["url"].startswith("/api/v1/ifc/download/house.ifc?dt=")

        dl = client.get(body["url"])  # no Authorization header: a plain <a href> click
        assert dl.status_code == 200
        assert dl.content == b"ISO-10303-21;\nHOUSE\n"
        assert "house.ifc" in dl.headers.get("content-disposition", "")

    def test_bearer_header_still_downloads(self, client, auth_headers, ifc_dir):
        (ifc_dir / "house.ifc").write_bytes(b"DATA")
        res = client.get("/api/v1/ifc/download/house.ifc", headers=auth_headers)
        assert res.status_code == 200
        assert res.content == b"DATA"

    def test_no_credentials_is_401(self, client, ifc_dir):
        (ifc_dir / "house.ifc").write_bytes(b"DATA")
        assert client.get("/api/v1/ifc/download/house.ifc").status_code == 401

    def test_old_query_token_with_access_token_is_401(self, client, auth_headers, ifc_dir):
        (ifc_dir / "house.ifc").write_bytes(b"DATA")
        access = auth_headers["Authorization"].split(" ", 1)[1]
        assert client.get(f"/api/v1/ifc/download/house.ifc?token={access}").status_code == 401

    def test_access_token_is_not_accepted_as_dt(self, client, auth_headers, ifc_dir):
        (ifc_dir / "house.ifc").write_bytes(b"DATA")
        access = auth_headers["Authorization"].split(" ", 1)[1]
        assert client.get(f"/api/v1/ifc/download/house.ifc?dt={access}").status_code == 401

    def test_dt_for_another_file_is_401(self, client, auth_headers, ifc_dir):
        (ifc_dir / "a.ifc").write_bytes(b"A")
        (ifc_dir / "b.ifc").write_bytes(b"B")
        url = client.post("/api/v1/ifc/download-token/a.ifc", headers=auth_headers).json()["url"]
        token = url.split("?dt=", 1)[1]
        assert client.get(f"/api/v1/ifc/download/b.ifc?dt={token}").status_code == 401

    def test_expired_dt_is_401(self, client, auth_headers, ifc_dir):
        from src.core.security import create_download_token
        (ifc_dir / "house.ifc").write_bytes(b"DATA")
        token = create_download_token(_user_id(client, auth_headers), "house.ifc", ttl_seconds=-1)
        assert client.get(f"/api/v1/ifc/download/house.ifc?dt={token}").status_code == 401

    def test_garbage_dt_is_401(self, client, ifc_dir):
        (ifc_dir / "house.ifc").write_bytes(b"DATA")
        assert client.get("/api/v1/ifc/download/house.ifc?dt=not.a.jwt").status_code == 401

    def test_dt_cannot_be_used_as_bearer_access_token(self, client, auth_headers, ifc_dir):
        (ifc_dir / "house.ifc").write_bytes(b"DATA")
        url = client.post("/api/v1/ifc/download-token/house.ifc", headers=auth_headers).json()["url"]
        token = url.split("?dt=", 1)[1]
        res = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
        assert res.status_code == 401

    def test_token_endpoint_requires_auth(self, client, ifc_dir):
        (ifc_dir / "house.ifc").write_bytes(b"DATA")
        assert client.post("/api/v1/ifc/download-token/house.ifc").status_code == 401

    def test_token_endpoint_missing_file_is_404(self, client, auth_headers, ifc_dir):
        assert client.post("/api/v1/ifc/download-token/missing.ifc", headers=auth_headers).status_code == 404

    @pytest.mark.parametrize("name", ["evil.txt", ".hidden.ifc", "a:b.ifc", "a\\b.ifc"])
    def test_token_endpoint_bad_filename_is_400(self, client, auth_headers, ifc_dir, name):
        res = client.post(f"/api/v1/ifc/download-token/{name}", headers=auth_headers)
        assert res.status_code == 400

    def test_create_download_token_claims(self):
        import jwt
        from src.core.config import get_settings
        from src.core.security import create_download_token, DOWNLOAD_TOKEN_SCOPE
        s = get_settings()
        payload = jwt.decode(create_download_token("7", "house.ifc"), s.jwt_secret_key, algorithms=[s.jwt_algorithm])
        assert DOWNLOAD_TOKEN_SCOPE == "ifc_download"
        assert payload["sub"] == "7"
        assert payload["scope"] == "ifc_download"
        assert payload["file"] == "house.ifc"
        assert "exp" in payload

    def test_decode_download_token_rejects_mismatch(self):
        from src.core.security import create_download_token, decode_download_token
        token = create_download_token("7", "a.ifc")
        assert decode_download_token(token, "a.ifc")["sub"] == "7"
        with pytest.raises(HTTPException) as exc:
            decode_download_token(token, "b.ifc")
        assert exc.value.status_code == 401


@needs_checkout
class TestFrontendDownload:
    def _js(self) -> dict[str, str]:
        return {p.name: p.read_text(encoding="utf-8") for p in (REPO_ROOT / "frontend" / "js").glob("*.js")}

    def test_no_token_in_query_string(self):
        for name, src in self._js().items():
            assert "?token=" not in src, name

    def test_old_helper_removed(self):
        for name, src in self._js().items():
            assert "getIFCDownloadUrl" not in src, name

    def test_api_requests_download_token(self):
        api = self._js()["api.js"]
        assert "downloadIFC" in api
        assert "/ifc/download-token/" in api

    def test_call_sites_use_download_helper(self):
        js = self._js()
        assert "API.downloadIFC(" in js["app.js"]
        assert "API.downloadIFC(" in js["ifc-upload.js"]


# ── B. nginx ──────────────────────────────────────────────────────────────────

def _size_in_mb(value: str) -> float:
    m = re.fullmatch(r"(\d+)([kKmMgG]?)", value)
    assert m, f"unparseable size {value!r}"
    n, unit = int(m.group(1)), m.group(2).lower()
    return {"": n / 1024 / 1024, "k": n / 1024, "m": n, "g": n * 1024}[unit]


@needs_checkout
class TestNginx:
    def _conf(self) -> str:
        return (REPO_ROOT / "frontend" / "nginx.conf").read_text(encoding="utf-8")

    def test_body_size_allows_backend_upload_limit(self):
        from src.core.config import get_settings
        m = re.search(r"^\s*client_max_body_size\s+(\S+);", self._conf(), re.M)
        assert m, "client_max_body_size missing (nginx default is 1m)"
        assert _size_in_mb(m.group(1)) >= get_settings().ifc_max_upload_mb + 1

    @pytest.mark.parametrize("header,value", [
        ("X-Content-Type-Options", "nosniff"),
        ("X-Frame-Options", "DENY"),
        ("Referrer-Policy", "strict-origin-when-cross-origin"),
        ("Permissions-Policy", "camera=(), microphone=(), geolocation=()"),
    ])
    def test_security_header(self, header, value):
        pattern = rf'^\s*add_header\s+{re.escape(header)}\s+"{re.escape(value)}"\s+always;'
        assert re.search(pattern, self._conf(), re.M), f"{header} missing"

    def test_forwarded_for_is_overwritten_not_appended(self):
        conf = self._conf()
        assert "$proxy_add_x_forwarded_for" not in conf
        assert re.search(r"proxy_set_header\s+X-Forwarded-For\s+\$remote_addr;", conf)
        assert re.search(r"proxy_set_header\s+X-Real-IP\s+\$remote_addr;", conf)


# ── C. Client IP + compose ────────────────────────────────────────────────────

def _req(peer, headers=None) -> Request:
    scope = {
        "type": "http", "method": "POST", "path": "/",
        "headers": [(k.lower().encode(), v.encode()) for k, v in (headers or {}).items()],
        "client": peer,
    }
    return Request(scope)


class TestClientIp:
    @pytest.mark.parametrize("peer,headers,expected", [
        (("172.18.0.5", 5000), {"X-Real-IP": "203.0.113.7"}, "203.0.113.7"),   # trusted proxy (docker net)
        (("127.0.0.1", 5000), {"X-Real-IP": "203.0.113.7"}, "203.0.113.7"),    # trusted proxy (localhost)
        (("203.0.113.9", 5000), {"X-Real-IP": "1.2.3.4"}, "203.0.113.9"),      # untrusted peer: header ignored
        (("172.18.0.5", 5000), {}, "172.18.0.5"),                                # no header
        (("172.18.0.5", 5000), {"X-Real-IP": "not-an-ip"}, "172.18.0.5"),       # invalid header
        (("172.18.0.5", 5000), {"X-Forwarded-For": "9.9.9.9"}, "172.18.0.5"),   # XFF is never read
        (("testclient", 50000), {"X-Real-IP": "1.2.3.4"}, "testclient"),         # non-IP peer = untrusted
        (None, {"X-Real-IP": "1.2.3.4"}, "unknown"),
    ])
    def test_get_client_ip(self, peer, headers, expected):
        from src.core.client_ip import get_client_ip
        assert get_client_ip(_req(peer, headers)) == expected

    def test_trusted_proxies_setting_is_used(self, monkeypatch):
        from src.core.client_ip import get_client_ip
        from src.core.config import get_settings
        monkeypatch.setattr(get_settings(), "trusted_proxies", "10.0.0.0/8")
        assert get_client_ip(_req(("10.1.2.3", 1), {"X-Real-IP": "203.0.113.7"})) == "203.0.113.7"
        assert get_client_ip(_req(("172.18.0.5", 1), {"X-Real-IP": "203.0.113.7"})) == "172.18.0.5"

    def test_default_trusted_proxies(self):
        from src.core.config import Settings
        assert Settings.model_fields["trusted_proxies"].default == "127.0.0.1/32,::1/128,172.16.0.0/12"

    def test_login_limit_is_per_real_client_behind_proxy(self):
        from src.api.router_auth import _check_rate_limit
        proxy = ("172.18.0.5", 5000)
        for _ in range(10):
            _check_rate_limit(_req(proxy, {"X-Real-IP": "203.0.113.7"}), "login", 10)
        with pytest.raises(HTTPException) as exc:
            _check_rate_limit(_req(proxy, {"X-Real-IP": "203.0.113.7"}), "login", 10)
        assert exc.value.status_code == 429
        # another browser behind the same nginx is not blocked
        _check_rate_limit(_req(proxy, {"X-Real-IP": "203.0.113.8"}), "login", 10)


@needs_checkout
class TestCompose:
    def test_prod_backend_port_bound_to_localhost_by_default(self):
        text = (REPO_ROOT / "docker-compose.yml").read_text(encoding="utf-8")
        assert '"${BACKEND_BIND:-127.0.0.1}:${BACKEND_PORT:-8001}:8000"' in text
        assert '- "${BACKEND_PORT:-8001}:8000"' not in text

    def test_env_example_documents_new_settings(self):
        text = (REPO_ROOT / ".env.example").read_text(encoding="utf-8")
        assert re.search(r"^#?\s*TRUSTED_PROXIES=", text, re.M)
        assert re.search(r"^#?\s*BACKEND_BIND=", text, re.M)


# ── D. No internal error text in responses ────────────────────────────────────

class TestNoErrorLeak:
    def test_upload_failure(self, client, auth_headers, ifc_dir):
        with patch("src.api.router_ifc.parse_ifc", side_effect=RuntimeError(LEAK)):
            res = client.post(
                "/api/v1/ifc/upload", headers=auth_headers,
                files={"file": ("house.ifc", b"ISO-10303-21;", "application/octet-stream")},
            )
        assert res.status_code == 500
        assert LEAK not in res.text
        assert res.json()["detail"] == "Lỗi xử lý IFC. Vui lòng kiểm tra file và thử lại."

    def test_stats_failure(self, client, auth_headers):
        with patch("src.api.router_ifc.get_ifc_building_summary", side_effect=RuntimeError(LEAK)):
            res = client.get("/api/v1/ifc/stats", headers=auth_headers)
        assert res.status_code == 200
        assert LEAK not in res.text
        assert res.json() == {"error": "Không lấy được thống kê IFC", "building": None, "element_counts": {}}

    def test_elements_failure(self, client, auth_headers):
        with patch("src.api.router_ifc.query_elements_on_storey", side_effect=RuntimeError(LEAK)):
            res = client.get("/api/v1/ifc/elements?storey=T1", headers=auth_headers)
        assert res.status_code == 500
        assert LEAK not in res.text
        assert res.json()["detail"] == "Lỗi truy vấn dữ liệu BIM."

    def test_generate_sample_failure(self, client, auth_headers):
        with patch("scripts.generate_sample_ifc.generate_sample_ifc", side_effect=RuntimeError(LEAK)):
            res = client.post("/api/v1/ifc/generate-sample", headers=auth_headers)
        assert res.status_code == 500
        assert LEAK not in res.text
        assert res.json()["detail"] == "Lỗi tạo file mẫu."

    def test_design_failure(self, client, auth_headers):
        with patch("src.rag.agent.tool_design_building", side_effect=RuntimeError(LEAK)):
            res = client.post("/api/v1/ifc/design", headers=auth_headers, json={"description": "nhà 2 tầng"})
        assert res.status_code == 500
        assert LEAK not in res.text
        assert res.json()["detail"] == "Lỗi thiết kế công trình. Vui lòng thử lại."


# ── E. Geometry route ─────────────────────────────────────────────────────────

class TestGeometryRoute:
    def test_single_get_route(self):
        # FastAPI 0.142 nests included routers (app.routes holds _IncludedRouter), so inspect the IFC router itself
        from src.api.router_ifc import router
        routes = [r for r in router.routes
                  if getattr(r, "path", "") == "/api/v1/ifc/geometry/{filename}" and "GET" in getattr(r, "methods", set())]
        assert len(routes) == 1

    @pytest.mark.parametrize("name", ["evil.json", ".hidden.ifc", "a:b.ifc"])
    def test_bad_filename_is_400(self, client, auth_headers, ifc_dir, name):
        assert client.get(f"/api/v1/ifc/geometry/{name}", headers=auth_headers).status_code == 400

    def test_returns_real_meshes_of_the_ifc_file(self, client, auth_headers, ifc_dir, monkeypatch):
        # Contract changed in task 017: the viewer gets meshes of the IFC file itself, not a parsed summary
        from src.api import router_ifc
        from tests.unit.ifc_fixtures import build_house
        monkeypatch.setattr(router_ifc.settings, "ifc_geometry_cache_dir", str(ifc_dir / "cache"))
        build_house().write(str(ifc_dir / "house.ifc"))
        res = client.get("/api/v1/ifc/geometry/house.ifc", headers=auth_headers)
        assert res.status_code == 200
        assert res.json()["stats"]["building_name"] == "Nhà mẫu"
        assert len(res.json()["meshes"]) == 15

    def test_not_parsed_is_404(self, client, auth_headers, ifc_dir):
        assert client.get("/api/v1/ifc/geometry/house.ifc", headers=auth_headers).status_code == 404


# ── F. Health ─────────────────────────────────────────────────────────────────

class TestHealth:
    def test_reports_points_count(self, client):
        info = {"name": "qcvn_chunks", "status": "green", "points_count": 7191, "vectors_count": None}
        with patch("src.api.router_health.get_collection_info", return_value=info), \
             patch("src.api.router_health.neo4j_health", return_value=True):
            res = client.get("/api/v1/health")
        assert res.status_code == 200
        assert res.json()["services"]["qdrant_vectors"] == 7191
