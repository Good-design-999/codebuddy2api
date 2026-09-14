#!/usr/bin/env python3
"""(后端, 模型) 避让回归：官方回 11102「该站点无此模型」后不再反复派发，且能自动绕开/自愈。

合成凭据 + 临时目录，不访问网络、不读取本机 auth/。
运行：python -B tests/test_model_site_blocks.py
"""

import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # 仓库根：允许直接运行本文件

import converter
from app.model_blocks import ModelBlocks

DOMESTIC_PROFILE = "cn-cli"
INTL_PROFILE = "intl-cli"
DOMAINS = {DOMESTIC_PROFILE: "www.codebuddy.cn", INTL_PROFILE: "www.codebuddy.ai"}
DOMESTIC_ENDPOINT = converter.PROFILE_ENDPOINTS[DOMESTIC_PROFILE]
INTL_ENDPOINT = converter.PROFILE_ENDPOINTS[INTL_PROFILE]
MODEL = "tested-model"
OTHER_MODEL = "other-tested-model"


def _error_body(code, message, request_id="0198f5a6b7c8d9e0f1a2b3c4d5e6f7a8"):
    return json.dumps({"code": code, "msg": message, "requestId": request_id}).encode()


def test_parse_not_servable_reads_code_field():
    """11102 只在独立 code 字段上命中，比对整字段而不是整段文本。"""
    message = f"model [{MODEL}] service info not found"
    assert converter._parse_not_servable(_error_body(11102, message), 404) == ("11102", message)
    assert converter._parse_not_servable(_error_body(11102, "no such model"), 400) is not None
    print("✅ test_parse_not_servable_reads_code_field")


def test_parse_not_servable_ignores_other_errors():
    """额度、认证、审核等错误不能进避让表：它们是可重试的凭证级问题。"""
    cases = [
        (_error_body(11001, "quota exceeded"), 429),
        (_error_body(1002, "token expired"), 401),
        (_error_body(0, "ok"), 200),
        (b"<html>500</html>", 500),
        (b"", 404),
        (_error_body("other", "internal error"), 400),
        (json.dumps({"error": {"message": "rate limit reached"}}).encode(), 429),
        (_error_body("other", "boom", request_id="req-11102"), 404),   # 11102 只在 requestId 里
        (_error_body(11102, "service info not found"), 429),           # 只认 400/404
    ]
    for raw, status in cases:
        assert converter._parse_not_servable(raw, status) is None, (raw, status)
    print("✅ test_parse_not_servable_ignores_other_errors")


def test_parse_not_servable_reads_wrapped_error_object():
    """OpenAI 风格的 {"error": {...}} 包装同样能识别。"""
    raw = json.dumps({"error": {"code": "11102", "message": "model service info not found"}}).encode()
    assert converter._parse_not_servable(raw, 404) is not None
    assert converter._parse_not_servable(b'{"requestId": "11102"}', 404) is None   # 只有 ID 不算
    print("✅ test_parse_not_servable_reads_wrapped_error_object")


class ModelBlocksTests(unittest.TestCase):
    """避让表本身：TTL 半开、指数退避、落盘与立即解除。"""

    def test_expiry_is_half_open_not_blacklist(self):
        blocks = ModelBlocks(ttl_s=60, max_ttl_s=600)
        now = time.time()
        blocks.note("https://a", "m", code="11102", now=now)
        self.assertTrue(blocks.blocked("https://a", "m", now=now))
        self.assertEqual(blocks.until("https://a", "m", now=now + 59), blocks.until("https://a", "m", now=now))
        self.assertFalse(blocks.blocked("https://a", "m", now=now + 61))   # 到期放行重试
        self.assertEqual(blocks.until("https://a", "m", now=now + 61), 0.0)

    def test_repeated_hits_back_off(self):
        blocks = ModelBlocks(ttl_s=60, max_ttl_s=600)
        now = time.time()
        for hits, expected in ((1, 60), (2, 120), (3, 240), (4, 480), (5, 600), (6, 600)):
            row = blocks.note("https://a", "m", code="11102", now=now)
            self.assertEqual(row["hits"], hits)
            self.assertAlmostEqual(row["until"] - now, expected, delta=1)

    def test_clear_on_success(self):
        blocks = ModelBlocks(ttl_s=3600)
        now = time.time()
        blocks.note("https://a", "m", now=now)
        self.assertTrue(blocks.clear("https://a", "m", now=now + 1))
        self.assertFalse(blocks.blocked("https://a", "m", now=now + 1))
        self.assertFalse(blocks.clear("https://a", "m", now=now + 1))   # 幂等

    def test_persistence_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "model-site-blocks.json"
            blocks = ModelBlocks(path, ttl_s=3600)
            blocks.note("https://a", "m", code="11102", msg="service info not found")
            restored = ModelBlocks(path, ttl_s=3600)
            self.assertTrue(restored.blocked("https://a", "m"))
            self.assertEqual(restored.detail()[0]["hits"], 1)
            self.assertEqual(restored.detail()[0]["code"], "11102")
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_unreadable_file_is_not_fatal(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "model-site-blocks.json"
            path.write_text("{ not json", encoding="utf-8")
            blocks = ModelBlocks(path)
            self.assertEqual(blocks.view(), {})
            blocks.note("https://a", "m")
            self.assertTrue(blocks.blocked("https://a", "m"))

    def test_isolated_per_endpoint_and_model(self):
        blocks = ModelBlocks(ttl_s=3600)
        blocks.note("https://a", "m1")
        self.assertTrue(blocks.blocked("https://a", "m1"))
        self.assertFalse(blocks.blocked("https://a", "m2"))
        self.assertFalse(blocks.blocked("https://b", "m1"))


class PoolRoutingTests(unittest.TestCase):
    """池内路由：绕开缺模型的后端，全部后端都缺时快速失败，实测通了自动解除。"""

    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.enterContext(patch.dict(os.environ, {"CODEBUDDY_AUTH_DIR": str(self.root)}))
        self.enterContext(patch.dict(converter.CONFIG, {
            "api_key": "", "cred": None, "cred_pool": None, "ledger": None,
            "model_catalogs": {}, "account_catalogs": None, "model_cache": None,
            "model_guard": True, "models_remote": None, "models_intl": None,
            "max_images": 16, "image_policy": "truncate", "log_path": None,
            "max_request_bytes": 32 * 1024 * 1024, "log_body_limit": 65536,
            "desensitize": False, "no_compact": False, "admin_csrf": True,
        }))
        for profile in (DOMESTIC_PROFILE, INTL_PROFILE):
            uid = "synthetic-" + profile
            value = {"account": {"uid": uid, "enterpriseId": "synthetic-enterprise"},
                     "auth": {"domain": DOMAINS[profile], "accessToken": "synthetic-access",
                              "refreshToken": "synthetic-refresh",
                              "expiresAt": (time.time() + 86400) * 1000,
                              "lastRefreshTime": time.time() * 1000}}
            (self.root / (uid + ".info")).write_text(json.dumps(value), encoding="utf-8")
        def entry(identifier):
            return {"id": identifier, "name": identifier, "supportsToolCall": True,
                    "credits": {"input": 1, "output": 2}}
        converter.CONFIG["model_catalogs"] = {profile: [entry(MODEL), entry(OTHER_MODEL)]
                                              for profile in DOMAINS}
        self.pool = converter.CredentialPool(
            [self.root / ("synthetic-" + profile + ".info") for profile in DOMAINS],
            blocks_path=self.root / "model-site-blocks.json")
        converter.CONFIG["cred_pool"] = self.pool
        self.by_endpoint = {}
        for entry in self.pool.entries():
            self.by_endpoint[self.pool._entry_endpoint(entry)] = (entry["cm"], entry["id"])
        self.assertEqual(set(self.by_endpoint), {DOMESTIC_ENDPOINT, INTL_ENDPOINT})
        self.addCleanup(converter.invalidate_model_table)

    def cred_for(self, model=MODEL, region=None):
        return converter._cred_for({"model": model, "messages": [{"role": "user", "content": "hi"}]},
                                   model, region=region)

    def test_missing_model_is_not_picked_again(self):
        """国际站回 11102 之后：请求自动落到国内站，而不是继续打国际站。"""
        cm, _ = self.by_endpoint[INTL_ENDPOINT]
        self.pool.note_status(cm, 404, model=MODEL, raw=_error_body(11102, "service info not found"))
        self.assertTrue(self.pool._blocks.blocked(INTL_ENDPOINT, MODEL))
        self.assertIsNone(self.pool.model_block_until(MODEL))            # 还有后端可派发
        (picked_cm, _generation), _headers = self.cred_for()
        self.assertIs(picked_cm, self.by_endpoint[DOMESTIC_ENDPOINT][0])
        self.assertFalse(self.pool._blocks.blocked(DOMESTIC_ENDPOINT, MODEL))

    def test_error_code_field_decodes_to_block(self):
        """note_status 是唯一入口：404/400 + 11102 记避让，429 走原模型冷却。"""
        cm, cid = self.by_endpoint[DOMESTIC_ENDPOINT]
        self.pool.note_status(cm, 429, model=MODEL, raw=_error_body(4290, "quota"))
        self.assertFalse(self.pool._blocks.blocked(DOMESTIC_ENDPOINT, MODEL))
        self.assertGreater(self.pool._model_fail[(cid, MODEL)], time.time())
        cm, _ = self.by_endpoint[INTL_ENDPOINT]
        self.pool.note_status(cm, 404, model=MODEL, raw=_error_body(11102, "service info not found"))
        self.assertTrue(self.pool._blocks.blocked(INTL_ENDPOINT, MODEL))

    def test_fast_failure_when_no_backend_serves_it(self):
        """所有后端都没有该模型：404 明确回给客户端，不再拿空回复让下游编故事。"""
        for endpoint in (DOMESTIC_ENDPOINT, INTL_ENDPOINT):
            cm, _ = self.by_endpoint[endpoint]
            self.pool.note_status(cm, 404, model=MODEL, raw=_error_body(11102, "service info not found"))
        until = self.pool.model_block_until(MODEL)
        self.assertIsNotNone(until)
        with self.assertRaises(HTTPException) as caught:
            self.cred_for()
        self.assertEqual(caught.exception.status_code, 404)
        detail = caught.exception.detail["error"]
        self.assertIn(MODEL, detail["message"])
        self.assertEqual(detail["type"], "invalid_request_error")
        # 避让是 (后端, 模型) 粒度：同后端的别的模型照旧派发
        (picked_cm, _), _headers = self.cred_for(model=OTHER_MODEL)
        self.assertIn(picked_cm, [cm for cm, _ in self.by_endpoint.values()])

    def test_block_is_reported_when_only_one_backend_lists_the_model(self):
        """目录里只有一个后端能服务它，而那个后端已避让：回 404，不要给下游可重试的 503。"""
        converter.CONFIG["model_catalogs"][INTL_PROFILE] = [
            {"id": OTHER_MODEL, "name": OTHER_MODEL, "supportsToolCall": True,
             "credits": {"input": 1, "output": 2}}]
        converter.invalidate_model_table()
        cm, _ = self.by_endpoint[DOMESTIC_ENDPOINT]
        self.pool.note_status(cm, 404, model=MODEL, raw=_error_body(11102, "service info not found"))
        self.assertIsNotNone(self.pool.model_block_until(MODEL), "唯一能服务它的后端已避让")
        with self.assertRaises(HTTPException) as caught:
            self.cred_for()
        self.assertEqual(caught.exception.status_code, 404)
        self.assertIn(MODEL, caught.exception.detail["error"]["message"])
        # 国际站目录里还有的模型照常派发，避让没有被扩大化。
        (picked_cm, _), _headers = self.cred_for(model=OTHER_MODEL)
        self.assertIn(picked_cm, [cm for cm, _ in self.by_endpoint.values()])

    def test_region_scoped_fast_failure(self):
        """只在国际站内全部避让时才拒 intl 请求；cn 请求照旧通过。"""
        cm, _ = self.by_endpoint[INTL_ENDPOINT]
        self.pool.note_status(cm, 404, model=MODEL, raw=_error_body(11102, "service info not found"))
        self.assertIsNotNone(self.pool.model_block_until(MODEL, region="intl"))
        with self.assertRaises(HTTPException) as caught:
            self.cred_for(region="intl")
        self.assertEqual(caught.exception.status_code, 404)
        self.assertIsNone(self.pool.model_block_until(MODEL, region="cn"))
        self.assertIsNotNone(self.cred_for(region="cn"))

    def test_success_clears_the_block(self):
        """后端悄悄上线该模型：一次 200 就解除避让，不必等 TTL。"""
        cm, _ = self.by_endpoint[INTL_ENDPOINT]
        self.pool.note_status(cm, 404, model=MODEL, raw=_error_body(11102, "service info not found"))
        self.assertTrue(self.pool._blocks.blocked(INTL_ENDPOINT, MODEL))
        self.assertTrue(self.pool.note_model_ok(cm, MODEL))
        self.assertFalse(self.pool._blocks.blocked(INTL_ENDPOINT, MODEL))
        self.assertFalse(self.pool.note_model_ok(cm, MODEL))

    def test_blocks_survive_restart(self):
        """避让表落盘：重启后不必重新踩一次坑。"""
        cm, _ = self.by_endpoint[INTL_ENDPOINT]
        self.pool.note_status(cm, 404, model=MODEL, raw=_error_body(11102, "service info not found"))
        reopened = converter.CredentialPool(
            [self.root / ("synthetic-" + profile + ".info") for profile in DOMAINS],
            blocks_path=self.root / "model-site-blocks.json")
        self.assertTrue(reopened._blocks.blocked(INTL_ENDPOINT, MODEL))
        self.assertEqual([row["endpoint"] for row in reopened.model_blocks_detail()], [INTL_ENDPOINT])

    def test_alias_auto_is_blocked_under_client_name(self):
        """intl 把 auto 改写成 default-model 送上去：避让仍记在客户端可见的名字上。"""
        cm, _ = self.by_endpoint[INTL_ENDPOINT]
        self.pool.note_status(cm, 404, model="default-model",
                              raw=_error_body(11102, "service info not found"))
        self.assertTrue(self.pool._blocks.blocked(INTL_ENDPOINT, "auto"))
        self.assertFalse(self.pool._blocks.blocked(INTL_ENDPOINT, "default-model"))


if __name__ == "__main__":
    # CI 用 python -B 直接执行每个测试文件且不装 pytest：先跑模块级检查，再交给 unittest。
    for fn in (test_parse_not_servable_reads_code_field,
               test_parse_not_servable_ignores_other_errors,
               test_parse_not_servable_reads_wrapped_error_object):
        fn()
    unittest.main(verbosity=2)
