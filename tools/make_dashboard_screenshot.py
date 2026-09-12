#!/usr/bin/env python3
"""生成 README 用的看板截图。

做法：离线渲染 dashboard.PAGE_HTML，在页面脚本执行前注入一份
拦截 fetch 的适配层，把 /admin/dashboard 和 /admin/models 的响应
换成下面的 demo 假数据 —— 不连真实服务、不读 auth/、不出现任何
真实账号信息。

用法：
    .venv/bin/python3 tools/make_dashboard_screenshot.py [输出目录]
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

import dashboard  # noqa: E402

# ---------------------------------------------------------------- demo 数据
# 全部是编造的示例账号，邮箱用 example.com，uid 用占位符。
DEMO_DASHBOARD = {
    "version": "1.2.2",
    "updated_at": 1789200000,
    "accounts": [
        {
            "nickname": "demo.intl@example.com",
            "uid": "demo-intl-0001",
            "auth_file": "demo-intl-0001.info",
            "profile": "intl-work",
            "region": "intl",
            "product": "workbuddy",
            "healthy": True,
            "token_expired": False,
            "enabled": True,
            "sticky_sessions": 1,
            "model_cooldowns": {},
            "credits": 1280.5,
            "soonest_expiry": "2026-10-12 04:00",
            "checkin_ok": True,
            "checkin_date": "2026-09-12",
            "checkin_message": None,
            "token_expires_at": "2026-10-12 04:00",
        },
        {
            "nickname": "demo.cn@example.com",
            "uid": "demo-cn-0002",
            "auth_file": "demo-cn-0002.info",
            "profile": "cn-cli",
            "region": "cn",
            "product": "codebuddy",
            "healthy": True,
            "token_expired": False,
            "enabled": True,
            "sticky_sessions": 0,
            "model_cooldowns": {},
            "credits": 4025.0,
            "soonest_expiry": "2026-11-01 00:00",
            "checkin_ok": True,
            "checkin_date": "2026-09-12",
            "checkin_message": None,
            "token_expires_at": "2026-11-01 00:00",
        },
    ],
    "totals": {"domestic": 4025.0, "international": 1280.5},
    "routing": {"enabled": 2, "total": 2},
    "recent_routes": [
        {"at": "2026-09-12 10:24", "nickname": "demo.intl@example.com",
         "model": "fast-model", "rate": 0.34, "profile": "intl-work",
         "auth_file": "demo-intl-0001.info"},
        {"at": "2026-09-12 10:21", "nickname": "demo.cn@example.com",
         "model": "glm-5.2", "rate": 0.79, "profile": "cn-cli",
         "auth_file": "demo-cn-0002.info"},
        {"at": "2026-09-12 10:18", "nickname": "demo.intl@example.com",
         "model": "gpt-5.6-luna", "rate": 0.14, "profile": "intl-work",
         "auth_file": "demo-intl-0001.info"},
        {"at": "2026-09-12 10:15", "nickname": "demo.cn@example.com",
         "model": "minimax-m2.7", "rate": 0.19, "profile": "cn-cli",
         "auth_file": "demo-cn-0002.info"},
    ],
}

DEMO_MODELS = {
    "intl": [
        {"id": "hy4-preview-f", "credits": 0.0, "by_profile": {"intl-work": 0.0}},
        {"id": "gpt-5.6-luna", "credits": 0.14, "by_profile": {"intl-work": 0.14}},
        {"id": "fast-model", "credits": 0.34, "by_profile": {"intl-work": 0.34}},
        {"id": "balanced-model", "credits": 0.59, "by_profile": {"intl-work": 0.59}},
        {"id": "gemini-3.5-flash", "credits": 0.99, "by_profile": {"intl-work": 0.99}},
        {"id": "gpt-5.3-codex", "credits": 1.25, "by_profile": {"intl-work": 1.25}},
    ],
    "cn": [
        {"id": "hy3-x", "credits": 0.05, "by_profile": {"cn-cli": 0.05}},
        {"id": "glm-5.3-flash", "credits": 0.06, "by_profile": {"cn-cli": 0.06}},
        {"id": "minimax-m2.7", "credits": 0.19, "by_profile": {"cn-cli": 0.19}},
        {"id": "minimax-m3", "credits": 0.25, "by_profile": {"cn-cli": 0.25}},
        {"id": "deepseek-v4-pro", "credits": 0.51, "by_profile": {"cn-cli": 0.51}},
        {"id": "glm-5.2", "credits": 0.79, "by_profile": {"cn-cli": 0.79}},
    ],
}

# 在页面自身脚本之前插进去：把 fetch 换成返回 demo 数据的桩。
INJECT = """
<script>
(function () {
  const DASHBOARD = %s;
  const MODELS = %s;
  const realFetch = window.fetch;
  window.fetch = function (url, opts) {
    const u = String(url || '');
    if (u.indexOf('/admin/dashboard') === 0) {
      return Promise.resolve(new Response(JSON.stringify(DASHBOARD),
        { status: 200, headers: { 'Content-Type': 'application/json' } }));
    }
    if (u.indexOf('/admin/models') === 0) {
      return Promise.resolve(new Response(JSON.stringify({ models: MODELS }),
        { status: 200, headers: { 'Content-Type': 'application/json' } }));
    }
    return realFetch ? realFetch.apply(this, arguments) : Promise.reject(new Error('blocked'));
  };
})();
</script>
""" % (json.dumps(DEMO_DASHBOARD, ensure_ascii=False),
       json.dumps(DEMO_MODELS, ensure_ascii=False))

# 截图时把刷新按钮的"上次刷新"时间固定住，避免出现随机时刻。
FREEZE_CLOCK = """
<script>
(function () {
  const fixed = new Date('2026-09-12T10:24:31');
  const RealDate = Date;
  function FrozenDate(...args) {
    if (args.length === 0) return new RealDate(fixed.getTime());
    return new RealDate(...args);
  }
  FrozenDate.now = () => fixed.getTime();
  FrozenDate.prototype = RealDate.prototype;
  window.Date = FrozenDate;
})();
</script>
"""


def find_chrome() -> str:
    for candidate in (
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        shutil.which("google-chrome"),
        shutil.which("chromium"),
    ):
        if candidate and Path(candidate).exists():
            return candidate
    raise SystemExit("找不到 Chrome / Chromium，无法截图")


def build_page() -> str:
    html = dashboard.PAGE_HTML
    # 注入脚本要排在页面自身的 <script> 之前
    marker = "<script>"
    idx = html.index(marker)
    return html[:idx] + FREEZE_CLOCK + INJECT + html[idx:]


def capture(chrome: str, url_or_file: str, out: Path, width: int, height: int,
            wait_ms: int = 2500) -> None:
    subprocess.run(
        [
            chrome, "--headless=new", "--disable-gpu", "--hide-scrollbars",
            "--force-device-scale-factor=2",
            f"--window-size={width},{height}",
            f"--screenshot={out}",
            f"--virtual-time-budget={wait_ms}",
            url_or_file,
        ],
        check=True, capture_output=True, timeout=90,
    )


def main() -> None:
    out_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else REPO / "docs"
    out_dir.mkdir(parents=True, exist_ok=True)
    chrome = find_chrome()
    page = build_page()

    with tempfile.TemporaryDirectory() as tmp:
        tmp_html = Path(tmp) / "dashboard.html"
        tmp_html.write_text(page, encoding="utf-8")

        shots = [
            ("dashboard.png", "file://" + str(tmp_html), 1280, 900),
        ]
        for name, url, w, h in shots:
            target = out_dir / name
            capture(chrome, url, target, w, h)
            size = target.stat().st_size
            print(f"✅ {target}  ({size // 1024} KB, {w}x{h} @2x)")

    # 校验：截图页面里不能出现任何真实账号痕迹
    page_lower = page.lower()
    leaks = [t for t in ("temporam", "sincere.newenergy", "leo solar energy",
                         "a5b2d01a", "workbuddy-desktop.info")
             if t in page_lower]
    print("\n泄漏自检:", "✅ 无真实账号信息" if not leaks else f"❌ 发现: {leaks}")


if __name__ == "__main__":
    main()
