#!/usr/bin/env python3
"""test_credit_identity_dedupe.py — 同一账号在多个凭据路径下重复记账时，余额只算一次。

ledger 以凭据绝对路径为键、路径只作索引（见 CreditLedger.bind_identity）。换
CODEBUDDY_AUTH_DIR / 搬动项目目录时把旧的 credits-ledger.json 一起带过来，同一身份
就会留在两个键上，aggregate_credits 逐键相加会把一份余额算成两份。

直接运行：python3 tests/test_credit_identity_dedupe.py
"""

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # 仓库根：允许直接运行本文件

from app import credits
from app.credits import CreditLedger, aggregate_credits, dedupe_by_identity

IDENTITY = "a" * 64
OTHER = "b" * 64


def _balance(remaining, total=None, fetched_at=0.0, intl=False):
    return {"credits": float(remaining), "count": 1, "intl": intl,
            "fetched_at": fetched_at, "soonest_expiry": None,
            "segments": [{"remaining": float(remaining),
                          "total": float(total if total is not None else remaining),
                          "expires_at": None}]}


def _snapshot(cred_id, identity, balance):
    return {cred_id: {"identity": identity, "checkin": {}, "credits": balance, "error": None}}


def test_same_identity_counted_once():
    """一账号两路径：合计等于一份余额，而不是两倍。"""
    snap = {}
    snap.update(_snapshot("/old/auth/x.info", IDENTITY, _balance(100)))
    snap.update(_snapshot("/new/auth/x.info", IDENTITY, _balance(100)))
    agg = aggregate_credits(snap)
    assert agg["remaining"] == 100.0, agg
    assert agg["used_by_quota"] == 0.0, agg
    print("✅ test_same_identity_counted_once")


def test_distinct_identities_still_sum():
    """不同账号照旧累加：去重不能把多账号池子折叠成一条。"""
    snap = {"/auth/x.info": {"identity": IDENTITY, "credits": _balance(100)},
            "/auth/y.info": {"identity": OTHER, "credits": _balance(50)}}
    agg = aggregate_credits(snap)
    assert agg["remaining"] == 150.0, agg
    assert len(dedupe_by_identity(snap)) == 2, snap
    print("✅ test_distinct_identities_still_sum")


def test_unbound_entries_are_preserved():
    """未绑定身份的历史条目全部保留：归属未知时不得静默丢数据。"""
    snap = {"legacy-a": {"credits": _balance(10)},
            "legacy-b": {"credits": _balance(20)},
            "no-credits": {},
            "checkin-only": {"checkin": {"date": "2026-01-01", "ok": True}}}
    assert len(dedupe_by_identity(snap)) == 4
    assert aggregate_credits(snap)["remaining"] == 30.0
    print("✅ test_unbound_entries_are_preserved")


def test_freshest_record_wins():
    """同身份取 fetched_at 最新的一条，旧路径上的过期余额不再虚增总额。"""
    snap = _snapshot("/old/auth/x.info", IDENTITY, _balance(900, 900, fetched_at=10.0))
    snap["/new/auth/x.info"] = {"identity": IDENTITY, "credits": _balance(10, 900, fetched_at=20.0)}
    agg = aggregate_credits(snap)
    assert agg["remaining"] == 10.0, agg
    assert agg["used_by_quota"] == 890.0, agg
    print("✅ test_freshest_record_wins")


def test_empty_record_does_not_shadow_balance():
    """刚 bind 还没刷到积分的条目，不应盖掉同身份已有的余额。"""
    snap = _snapshot("/old/auth/x.info", IDENTITY, _balance(120, fetched_at=10.0))
    snap["/new/auth/x.info"] = {"identity": IDENTITY, "credits": {}}
    assert aggregate_credits(snap)["remaining"] == 120.0
    # 反过来：有数据的那条胜出，与写入顺序无关
    flipped = dict(reversed(list(snap.items())))
    assert aggregate_credits(flipped)["remaining"] == 120.0
    print("✅ test_empty_record_does_not_shadow_balance")


def test_groups_are_not_cross_merged():
    """国内/国际各一份余额属于两个身份，折叠后两站数值都不丢。"""
    snap = {"/old/x.info": {"identity": IDENTITY, "credits": _balance(100)},
            "/new/x.info": {"identity": IDENTITY, "credits": _balance(100)},
            "/old/i.info": {"identity": OTHER, "credits": _balance(30, intl=True)},
            "/new/i.info": {"identity": OTHER, "credits": _balance(30, intl=True)}}
    groups = aggregate_credits(snap)["groups"]
    assert groups["domestic"]["remaining"] == 100.0, groups
    assert groups["international"]["remaining"] == 30.0, groups
    print("✅ test_groups_are_not_cross_merged")


def test_ledger_reload_keeps_duplicate_rows():
    """去重发生在读取口径：落盘的重复行不删（看板仍能看到），但合计不再翻倍。"""
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "credits-ledger.json"
        ledger = CreditLedger(path)
        for cred_id in ("/moved/auth/x.info", "/current/auth/x.info"):
            ledger.bind_identity(cred_id, IDENTITY)
            ledger.update_credits(cred_id, _balance(77))
        assert len(ledger.snapshot()) == 2
        assert aggregate_credits(ledger.snapshot())["remaining"] == 77.0
        assert aggregate_credits(CreditLedger(path).snapshot())["remaining"] == 77.0
    print("✅ test_ledger_reload_keeps_duplicate_rows")


def main():
    for fn in (test_same_identity_counted_once, test_distinct_identities_still_sum,
               test_unbound_entries_are_preserved, test_freshest_record_wins,
               test_empty_record_does_not_shadow_balance, test_groups_are_not_cross_merged,
               test_ledger_reload_keeps_duplicate_rows):
        fn()
    print("\n全部通过 ✅")


if __name__ == "__main__":
    sys.exit(main())
