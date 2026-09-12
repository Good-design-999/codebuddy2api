"""看板：账号/积分匹配、点选路由、不泄漏 token、鉴权边界。"""

import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from fastapi.testclient import TestClient

import converter
import dashboard


def write_credential(root: Path, name="alice.info", uid="uid-a", nickname="alice@example.com"):
    path = root / name
    now = time.time()
    path.write_text(json.dumps({
        "account": {"uid": uid, "nickname": nickname, "enterpriseId": "ent"},
        "auth": {
            "domain": "www.workbuddy.ai",
            "accessToken": "synthetic-access",
            "refreshToken": "synthetic-refresh",
            "expiresAt": (now + 86400) * 1000,
            "lastRefreshTime": now * 1000,
        },
    }), encoding="utf-8")
    return path


class DashboardTests(unittest.TestCase):
    def setUp(self):
        dashboard.clear_routes()
        dashboard.clear_selection()
        self.addCleanup(dashboard.clear_routes)
        self.addCleanup(dashboard.clear_selection)
        self.enterContext(patch.dict(converter.CONFIG, {
            "api_key": "", "cred": None, "cred_pool": None, "ledger": None,
            "log_path": None, "model_guard": False, "account_catalogs": None,
            "model_cache": None,
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
        self.assertIn("点卡片选用账号", response.text)
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
        self.assertEqual(body["routing"], {"enabled": 0, "total": 0})

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
        self.assertTrue(account["enabled"])
        self.assertFalse(account["checkin_ok"])
        self.assertEqual(body["totals"]["international"], 1100.0)
        self.assertEqual(body["routing"], {"enabled": 1, "total": 1})
        dumped = str(body)
        self.assertNotIn("/private/var", dumped)
        self.assertNotIn("test-only-token", dumped)

    def test_record_route_keeps_account_not_token(self):
        cm = Mock()
        cm.path = "/tmp/auth/workbuddy-desktop.info"
        cm.summary.return_value = {"nickname": "cn-user@example.com", "uid": "uid-cn"}
        dashboard.record_route({
            "ts": time.time(), "rid": "abcd", "region": "cn", "profile": "cn-cli",
            "model": "hy4-preview", **dashboard.account_from_cred((cm, 1)),
        })
        routes = dashboard.recent_routes()
        self.assertEqual(routes[0]["nickname"], "cn-user@example.com")
        self.assertEqual(routes[0]["auth_file"], "workbuddy-desktop.info")
        self.assertNotIn("token", routes[0])

    def test_routes_carry_rate_from_catalog(self):
        cm = Mock()
        cm.path = "/tmp/auth/alice.info"
        cm.summary.return_value = {"nickname": "alice@example.com", "uid": "uid-a"}
        dashboard.record_route({
            "ts": time.time(), "rid": "beef", "region": "intl", "profile": "intl-work",
            "model": "gpt-5.5", **dashboard.account_from_cred((cm, 1)),
        })
        body = dashboard.snapshot(
            pool=None, ledger=None, version="9.9.9",
            model_details=[{"id": "gpt-5.5", "credits": 3.31,
                            "credits_by_profile": {"intl-work": 3.31}}],
        )
        self.assertEqual(body["recent_routes"][0]["rate"], 3.31)

    def test_routes_without_catalog_report_none_rate(self):
        cm = Mock()
        cm.path = "/tmp/auth/bob.info"
        cm.summary.return_value = {"nickname": "bob@example.com", "uid": "uid-b"}
        dashboard.record_route({
            "ts": time.time(), "rid": "cafe", "region": "cn", "profile": "cn-cli",
            "model": "hy4-preview", **dashboard.account_from_cred((cm, 1)),
        })
        body = dashboard.snapshot(pool=None, ledger=None, version="9.9.9")
        self.assertIsNone(body["recent_routes"][0]["rate"])

    def test_models_view_groups_by_region_and_sorts_by_rate(self):
        view = dashboard.models_view({
            "intl": [
                {"id": "gpt-5.5", "credits": 3.31, "credits_by_profile": {"intl-work": 3.31}},
                {"id": "fast-model", "credits": 0.34, "credits_by_profile": {"intl-work": 0.34}},
                {"id": "hy4-preview-f", "credits": 0.0, "credits_by_profile": {"intl-work": 0.0}},
            ],
            "cn": [
                {"id": "glm-5.2", "credits": 0.79, "credits_by_profile": {"cn-cli": 0.79}},
                {"id": "legacy", "credits": None, "credits_by_profile": {}},
            ],
        })
        self.assertEqual([row["id"] for row in view["intl"]],
                         ["hy4-preview-f", "fast-model", "gpt-5.5"])
        # 无倍率的排在最后，不影响前面按倍率升序
        self.assertEqual([row["id"] for row in view["cn"]], ["glm-5.2", "legacy"])
        self.assertEqual(view["cn"][0]["by_profile"], {"cn-cli": 0.79})

    def test_models_view_tolerates_missing_regions(self):
        self.assertEqual(dashboard.models_view({}), {})
        self.assertEqual(dashboard.models_view(None), {})
        self.assertEqual(dashboard.models_view({"intl": None}), {"intl": []})

    def test_admin_models_endpoint_returns_both_regions(self):
        captured = []

        def fake_details(region=None):
            captured.append(region)
            return [{"id": "fast-model", "credits": 0.34,
                     "credits_by_profile": {"intl-work": 0.34}}]

        with patch.object(converter, "current_model_details", side_effect=fake_details):
            res = self.client.get("/admin/models")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(sorted(captured), ["cn", "intl"])
        self.assertEqual(sorted(res.json()["regions"].keys()), ["cn", "intl"])

    def test_admin_models_requires_api_key_when_configured(self):
        converter.CONFIG["api_key"] = "test-only-api-key"
        self.assertEqual(self.client.get("/admin/models").status_code, 401)
        allowed = self.client.get("/admin/models",
                                  headers={"Authorization": "Bearer test-only-api-key"})
        self.assertEqual(allowed.status_code, 200)
        self.assertEqual(sorted(allowed.json()["regions"].keys()), ["cn", "intl"])

    def test_add_account_button_is_present_in_page(self):
        res = self.client.get("/")
        body = res.text
        self.assertIn('id="add-account"', body)
        self.assertIn('id="login-modal"', body)
        self.assertIn('id="login-intl"', body)
        self.assertIn('id="login-cn"', body)

    def test_oauth_start_returns_link_and_requires_api_key(self):
        started = {"login_id": "oa_test", "verification_uri": "https://example.com/login?state=xyz",
                   "expires_in": 300}
        with patch.object(converter._OAUTH, "start", return_value=started) as start:
            res = self.client.post("/admin/oauth/start?site=intl")
            self.assertEqual(res.status_code, 200)
            self.assertEqual(res.json()["verification_uri"], started["verification_uri"])
            self.assertEqual(start.call_args.kwargs.get("site"), "intl")
        converter.CONFIG["api_key"] = "test-only-api-key"
        self.assertEqual(self.client.post("/admin/oauth/start?site=cn").status_code, 401)

    def test_oauth_start_rejects_unknown_site(self):
        with patch.object(converter._OAUTH, "start", side_effect=ValueError("未知站点: x")):
            res = self.client.post("/admin/oauth/start?site=x")
        self.assertEqual(res.status_code, 400)

    def test_oauth_poll_reports_pending_then_success(self):
        with patch.object(converter._OAUTH, "poll", return_value={"done": False}) as poll:
            res = self.client.get("/admin/oauth/poll?login_id=oa_test")
            self.assertEqual(res.status_code, 200)
            self.assertFalse(res.json()["done"])
            self.assertEqual(poll.call_args.args[0], "oa_test")
        with patch.object(converter._OAUTH, "poll",
                          return_value={"done": True, "error": "登录超时，请重新发起"}):
            body = self.client.get("/admin/oauth/poll?login_id=oa_test").json()
        self.assertTrue(body["done"])
        self.assertIn("超时", body["error"])

    def test_selection_persists_and_skips_disabled_accounts(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            alice = write_credential(root, "alice.info", "uid-a", "alice@example.com")
            bob = write_credential(root, "bob.info", "uid-b", "bob@example.com")
            store = root / "dashboard-selection.json"
            dashboard.set_store(store)
            dashboard.set_enabled("alice.info", False)
            saved = json.loads(store.read_text(encoding="utf-8"))
            self.assertEqual(saved["disabled"], ["alice.info"])
            dashboard.clear_selection()
            dashboard.set_store(store)
            self.assertFalse(dashboard.is_enabled("alice.info"))
            self.assertTrue(dashboard.is_enabled("bob.info"))
            pool = converter.CredentialPool([alice, bob])
            picked = pool.pick("session", None)
            self.assertEqual(Path(picked.path).name, "bob.info")
            dashboard.set_enabled("bob.info", False)
            self.assertIsNone(pool.pick("session", None))
            dashboard.set_enabled("alice.info", True)
            picked = pool.pick("session", None)
            self.assertEqual(Path(picked.path).name, "alice.info")

    def test_toggle_endpoint_updates_enabled_and_requires_api_key(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = write_credential(root)
            store = root / "dashboard-selection.json"
            dashboard.set_store(store)
            pool = converter.CredentialPool([path])
            converter.CONFIG["cred_pool"] = pool
            converter.CONFIG["api_key"] = "test-only-api-key"
            denied = self.client.post("/admin/dashboard/accounts",
                                      json={"auth_file": "alice.info", "enabled": False})
            self.assertEqual(denied.status_code, 401)
            bad = self.client.post("/admin/dashboard/accounts",
                                   json={"auth_file": "../alice.info", "enabled": False},
                                   headers={"Authorization": "Bearer test-only-api-key"})
            self.assertEqual(bad.status_code, 400)
            missing = self.client.post("/admin/dashboard/accounts",
                                       json={"auth_file": "missing.info", "enabled": False},
                                       headers={"Authorization": "Bearer test-only-api-key"})
            self.assertEqual(missing.status_code, 404)
            ok = self.client.post("/admin/dashboard/accounts",
                                  json={"auth_file": "alice.info", "enabled": False},
                                  headers={"Authorization": "Bearer test-only-api-key"})
            self.assertEqual(ok.status_code, 200)
            body = ok.json()
            self.assertFalse(body["accounts"][0]["enabled"])
            self.assertEqual(body["routing"], {"enabled": 0, "total": 1})
            self.assertEqual(body["totals"]["international"], 0.0)
            self.assertFalse(dashboard.is_enabled("alice.info"))
            self.assertIsNone(pool.pick("session", None))


if __name__ == "__main__":
    unittest.main(verbosity=2)
