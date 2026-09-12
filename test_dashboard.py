"""只读看板：账号/积分匹配、不泄漏 token、鉴权边界。"""

import time
import unittest
from unittest.mock import Mock, patch

from fastapi.testclient import TestClient

import converter
import dashboard


class DashboardTests(unittest.TestCase):
    def setUp(self):
        dashboard.clear_routes()
        self.addCleanup(dashboard.clear_routes)
        self.enterContext(patch.dict(converter.CONFIG, {
            "api_key": "", "cred": None, "cred_pool": None, "ledger": None,
            "log_path": None, "model_guard": False,
        }))
        self.client = TestClient(converter.app)

    def test_page_is_public_html_without_touching_credentials(self):
        converter.CONFIG["api_key"] = "test-only-api-key"
        pool = Mock()
        pool.snapshot.side_effect = AssertionError("must not snapshot")
        converter.CONFIG["cred_pool"] = pool
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn("text/html", response.headers["content-type"])
        self.assertIn("codebuddy2api 看板", response.text)
        self.assertNotIn("test-only-token", response.text)
        pool.snapshot.assert_not_called()

    def test_dashboard_requires_api_key_when_configured(self):
        converter.CONFIG["api_key"] = "test-only-api-key"
        denied = self.client.get("/admin/dashboard")
        self.assertEqual(denied.status_code, 401)
        allowed = self.client.get("/admin/dashboard",
                                  headers={"Authorization": "Bearer test-only-api-key"})
        self.assertEqual(allowed.status_code, 200)
        body = allowed.json()
        self.assertEqual(body["accounts"], [])
        self.assertEqual(body["recent_routes"], [])

    def test_snapshot_matches_credits_by_basename_and_hides_paths(self):
        pool = Mock()
        pool.snapshot.return_value = [{
            "auth_file": "/private/var/auth/a.info",
            "healthy": True, "token_expired": False, "sticky_sessions": 2,
            "uid": "uid-a", "account_key": "key-a", "nickname": "alice@example.com",
            "profile": "intl-work", "region": "intl", "product": "workbuddy",
            "model_cooldowns": {}, "token_expires_at": 1820663545100,
        }]
        ledger = Mock()
        ledger.snapshot.return_value = {
            "/var/auth/a.info": {
                "identity": "key-a",
                "checkin": {"date": "2026-09-12", "ok": False, "message": "活动未开启"},
                "credits": {"credits": 1100.0, "soonest_expiry": 1807777752.0, "intl": True,
                            "segments": [{"remaining": 1100.0}]},
            }
        }
        body = dashboard.snapshot(pool=pool, ledger=ledger, version="1.1.2")
        account = body["accounts"][0]
        self.assertEqual(account["nickname"], "alice@example.com")
        self.assertEqual(account["auth_file"], "a.info")
        self.assertEqual(account["credits"], 1100.0)
        self.assertEqual(account["sticky_sessions"], 2)
        self.assertFalse(account["checkin_ok"])
        self.assertEqual(body["totals"]["international"], 1100.0)
        dumped = str(body)
        self.assertNotIn("/private/var", dumped)
        self.assertNotIn("test-only-token", dumped)

    def test_record_route_keeps_account_not_token(self):
        cm = Mock()
        cm.path = "/tmp/auth/workbuddy-desktop.info"
        cm.summary.return_value = {"nickname": "Leo solar energy", "uid": "uid-cn"}
        dashboard.record_route({
            "ts": time.time(), "rid": "abcd", "region": "cn", "profile": "cn-cli",
            "model": "hy4-preview", **dashboard.account_from_cred((cm, 1)),
        })
        routes = dashboard.recent_routes()
        self.assertEqual(routes[0]["nickname"], "Leo solar energy")
        self.assertEqual(routes[0]["auth_file"], "workbuddy-desktop.info")
        self.assertNotIn("token", routes[0])


if __name__ == "__main__":
    unittest.main(verbosity=2)
