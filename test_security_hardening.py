"""
test_security_hardening.py
--------------------------
Security hardening and vulnerability protection test suite for ManasBot:
  1. SSRF (Server-Side Request Forgery) protection
  2. Multi-tenant API Key cryptographic isolation (cross-tenant access denial)
  3. Role-Based Access Control (RBAC) permission boundaries
  4. Input sanitization and prompt injection resistance
"""
import os
import unittest
from unittest.mock import patch
from fastapi.testclient import TestClient

os.environ["CENTRAL_DB_URL"] = "sqlite:///./test_security.db"
os.environ["DATABASE_URL"] = "sqlite:///./test_security.db"
os.environ["DISABLE_FAST_EMBED"] = "true"
os.environ["DISABLE_GROQ_CALLS"] = "true"

from backend.app.main import app
from backend.app.utils.security_validation import validate_public_url, is_safe_public_url
from backend.app.core.security import create_employee_token


class TestSecurityHardening(unittest.IsolatedAsyncioTestCase):

    def setUp(self):
        self.client = TestClient(app)

    # ── 1. SSRF Protection Tests ────────────────────────────────────────────

    def test_01_ssrf_validator_blocks_internal_and_metadata_targets(self):
        malicious_urls = [
            "http://127.0.0.1:8000/admin/secrets",
            "http://localhost:8080/debug",
            "http://0.0.0.0:5000",
            "http://169.254.169.254/latest/meta-data/",  # AWS / GCP metadata
            "http://192.168.1.100/router-login",
            "http://10.0.0.1/internal-api",
            "http://172.16.0.5:9000",
            "file:///etc/passwd",
            "ftp://ftp.local/backup.zip",
            "gopher://127.0.0.1:70",
            "http://metadata.google.internal/computeMetadata/v1/",
        ]
        for url in malicious_urls:
            with self.subTest(url=url):
                self.assertFalse(is_safe_public_url(url))
                with self.assertRaises(ValueError):
                    validate_public_url(url)

    def test_02_ssrf_validator_allows_valid_public_domain(self):
        safe_url = "https://example.com/docs/api-guide"
        validated = validate_public_url(safe_url)
        self.assertEqual(validated, safe_url)
        self.assertTrue(is_safe_public_url(safe_url))

    # ── 2. Cross-Tenant API Key Isolation Tests ──────────────────────────────

    def test_03_cross_tenant_access_blocked(self):
        """Verify that Tenant A's API key CANNOT access or mutate Tenant B's data."""
        with patch("backend.app.core.security.get_tenant_by_id") as mock_get_tenant:
            def _get_tenant(tid):
                if tid == "tenant_alpha":
                    return {"id": "tenant_alpha", "api_key": "KEY_ALPHA_123", "is_active": True}
                elif tid == "tenant_beta":
                    return {"id": "tenant_beta", "api_key": "KEY_BETA_456", "is_active": True}
                return None

            mock_get_tenant.side_effect = _get_tenant

            # Tenant Alpha tries to delete Tenant Beta's doc using Alpha's API key
            response = self.client.delete(
                "/admin/doc/some-doc-id?tenant_id=tenant_beta",
                headers={"X-Auth-Token": "KEY_ALPHA_123"},
            )
            # Must be rejected with 403 Forbidden
            self.assertEqual(response.status_code, 403)
            self.assertIn("Invalid token or unauthorized", response.json()["detail"])

    # ── 3. Role-Based Access Control (RBAC) Boundaries ───────────────────────

    def test_04_support_role_cannot_access_super_admin_endpoints(self):
        """Support agents must be forbidden from accessing admin/super_admin endpoints."""
        support_token = create_employee_token(
            employee_id="emp_support_01",
            email="support@example.com",
            role="support",
        )

        with patch("backend.app.core.security.get_employee_by_id") as mock_emp:
            mock_emp.return_value = {
                "id": "emp_support_01",
                "email": "support@example.com",
                "role": "support",
                "is_active": True,
                "role_changed_at": None,
            }

            # Try to delete tenant (requires super_admin role)
            response = self.client.delete(
                "/admin/tenant/some_tenant",
                headers={"Authorization": f"Bearer {support_token}"},
            )
            self.assertEqual(response.status_code, 403)
            self.assertEqual(response.json()["detail"], "Insufficient permissions.")

    def test_05_deactivated_employee_token_rejected(self):
        """Tokens for deactivated employees must be immediately rejected."""
        token = create_employee_token(
            employee_id="emp_inactive_01",
            email="inactive@example.com",
            role="admin",
        )
        with patch("backend.app.core.security.get_employee_by_id") as mock_emp:
            mock_emp.return_value = {
                "id": "emp_inactive_01",
                "email": "inactive@example.com",
                "role": "admin",
                "is_active": False,  # Deactivated account
            }
            response = self.client.delete(
                "/admin/tenant/some_tenant",
                headers={"Authorization": f"Bearer {token}"},
            )
            self.assertEqual(response.status_code, 401)
            self.assertIn("deactivated", response.json()["detail"].lower())

    # ── 4. Prompt Injection & Input Sanitization ─────────────────────────────

    async def test_06_html_input_sanitization_in_graph(self):
        """Verify that script tags and HTML injection are escaped properly."""
        from backend.rag.graph import guard_and_intent_node

        malicious_input = "<script>alert('xss');</script> Can I buy this?"
        state = {
            "question": malicious_input,
            "tenant_id": "test_tenant",
            "company": "Secure Corp",
            "industry": "Fintech",
        }
        result = await guard_and_intent_node(state)
        self.assertNotIn("<script>", result["question"])
        self.assertIn("&lt;script&gt;", result["question"])

    async def test_07_ssrf_redirect_to_internal_metadata_blocked(self):
        """Verify HTTP 302 redirects pointing to internal/metadata IPs are blocked before following."""
        from unittest.mock import MagicMock, AsyncMock
        from backend.app.utils.security_validation import safe_http_get_async

        redirect_resp = MagicMock()
        redirect_resp.status_code = 302
        redirect_resp.headers = {"location": "http://169.254.169.254/latest/meta-data/"}

        with patch("httpx.AsyncClient.get", new=AsyncMock(return_value=redirect_resp)):
            with self.assertRaises(ValueError) as ctx:
                await safe_http_get_async("https://example.com/start-redirect")
            self.assertIn("forbidden", str(ctx.exception).lower())

    def test_08_role_change_revokes_token_in_get_tenant_db(self):
        """Verify get_tenant_db rejects employee JWT issued prior to role_changed_at."""
        import datetime
        from fastapi import HTTPException
        from starlette.requests import Request
        from backend.app.core.security import get_tenant_db

        token = create_employee_token(
            employee_id="emp_revoked_01",
            email="emp@example.com",
            role="admin",
        )
        req = Request({
            "type": "http",
            "method": "GET",
            "path": "/admin/docs",
            "headers": [(b"authorization", f"Bearer {token}".encode("utf-8"))],
        })
        future_change = (datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(minutes=5)).isoformat()

        with patch("backend.app.core.security.get_tenant_by_id", return_value={"id": "t1", "api_key": "k1", "is_active": True}), \
             patch("backend.app.core.security.get_employee_by_id", return_value={"id": "emp_revoked_01", "role": "viewer", "is_active": True, "role_changed_at": future_change}):
            gen = get_tenant_db(request=req, tenant_id="t1", x_auth_token=None)
            with self.assertRaises(HTTPException) as ctx:
                next(gen)
            self.assertEqual(ctx.exception.status_code, 403)


if __name__ == "__main__":
    unittest.main()
