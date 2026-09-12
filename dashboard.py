#!/usr/bin/env python3
"""看板：账号、积分、最近路由；点亮的账号才参与路由。不返回 token。"""

from __future__ import annotations

import json
import os
import threading
import time
from collections import deque
from datetime import datetime, timedelta, timezone
from pathlib import Path

BJ = timezone(timedelta(hours=8))
_HISTORY_LOCK = threading.Lock()
_HISTORY: deque[dict] = deque(maxlen=80)
_SELECTION_LOCK = threading.Lock()
_DISABLED: set[str] = set()
_STORE: Path | None = None


def clear_routes():
    with _HISTORY_LOCK:
        _HISTORY.clear()


def clear_selection():
    global _STORE
    with _SELECTION_LOCK:
        _DISABLED.clear()
        _STORE = None


def set_store(path):
    """从 JSON 加载停用名单；文件不存在则全部启用。"""
    global _STORE
    _STORE = Path(path) if path else None
    load_selection()


def load_selection():
    names: set[str] = set()
    path = _STORE
    if path is not None:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            data = {}
        except (OSError, ValueError, UnicodeError):
            data = {}
        raw = data.get("disabled") if isinstance(data, dict) else None
        if isinstance(raw, list):
            names = {name for item in raw if (name := _basename(item))}
    with _SELECTION_LOCK:
        _DISABLED.clear()
        _DISABLED.update(names)


def is_enabled(auth_file) -> bool:
    name = _basename(auth_file)
    if not name:
        return True
    with _SELECTION_LOCK:
        return name not in _DISABLED


def set_enabled(auth_file, enabled: bool) -> bool:
    name = _basename(auth_file)
    if not name:
        raise ValueError("missing auth_file")
    with _SELECTION_LOCK:
        if enabled:
            _DISABLED.discard(name)
        else:
            _DISABLED.add(name)
        disabled = sorted(_DISABLED)
        path = _STORE
    if path is not None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(json.dumps({"disabled": disabled}, ensure_ascii=False, indent=2) + "\n",
                       encoding="utf-8")
        tmp.replace(path)
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
    return bool(enabled)


def record_route(entry: dict):
    item = {
        "ts": float(entry.get("ts") or time.time()),
        "rid": str(entry.get("rid") or "")[:16],
        "region": entry.get("region"),
        "profile": entry.get("profile"),
        "model": entry.get("model"),
        "nickname": entry.get("nickname"),
        "auth_file": _basename(entry.get("auth_file")),
        "uid": entry.get("uid"),
    }
    with _HISTORY_LOCK:
        _HISTORY.appendleft(item)


def recent_routes(limit: int = 40) -> list[dict]:
    n = max(1, min(int(limit or 40), 80))
    with _HISTORY_LOCK:
        return list(_HISTORY)[:n]


def account_from_cred(cred) -> dict:
    cm = cred[0] if isinstance(cred, tuple) else cred
    if cm is None:
        return {"nickname": None, "uid": None, "auth_file": None}
    path = getattr(cm, "path", None)
    name = Path(path).name if path else None
    try:
        summary = cm.summary() if hasattr(cm, "summary") else {}
    except Exception:
        summary = {}
    if not isinstance(summary, dict):
        summary = {}
    return {
        "nickname": summary.get("nickname"),
        "uid": summary.get("uid"),
        "auth_file": name,
    }


def snapshot(*, pool, ledger, version: str, model_details=None) -> dict:
    creds = pool.snapshot() if pool is not None else []
    ledger_snap = ledger.snapshot() if ledger is not None else {}
    if not isinstance(creds, list):
        creds = []
    if not isinstance(ledger_snap, dict):
        ledger_snap = {}
    accounts = [_account_view(item, ledger_snap) for item in creds if isinstance(item, dict)]
    groups = {"domestic": 0.0, "international": 0.0}
    for account in accounts:
        if not account.get("enabled"):
            continue
        key = "international" if account.get("region") == "intl" else "domestic"
        groups[key] += float(account.get("credits") or 0)
    rates = _rates_by_model(model_details)
    return {
        "version": version,
        "updated_at": time.time(),
        "accounts": accounts,
        "totals": {k: round(v, 2) for k, v in groups.items()},
        "routing": {
            "enabled": sum(1 for account in accounts if account.get("enabled")),
            "total": len(accounts),
        },
        "recent_routes": [_route_view(item, rates) for item in recent_routes()],
    }


def _rates_by_model(model_details) -> dict:
    """{模型: {profile: 倍率}}；倍率来自模型目录的 credits_by_profile。"""
    out: dict = {}
    if not isinstance(model_details, (list, tuple)):
        return out
    for item in model_details:
        if not isinstance(item, dict):
            continue
        name = item.get("id")
        if not name:
            continue
        by_profile = item.get("credits_by_profile")
        out[name] = dict(by_profile) if isinstance(by_profile, dict) else {}
    return out


def models_view(details_by_region) -> dict:
    """{region: [{id, credits, by_profile}]}；region 形如 intl / cn。

    details_by_region 形如 {region: current_model_details(region)}，
    倍率取该 region 下各 profile 的最小值，避免同一模型多档时读数含糊。
    """
    out: dict = {}
    if not isinstance(details_by_region, dict):
        return out
    for region, details in details_by_region.items():
        rows: list[dict] = []
        for item in details or []:
            if not isinstance(item, dict):
                continue
            name = item.get("id")
            if not name:
                continue
            by_profile = item.get("credits_by_profile")
            by_profile = dict(by_profile) if isinstance(by_profile, dict) else {}
            rows.append({"id": name, "credits": item.get("credits"),
                         "by_profile": by_profile})
        rows.sort(key=lambda row: (row["credits"] is None, row["credits"] if row["credits"] is not None else 0, row["id"]))
        out[region] = rows
    return out


def _route_view(item: dict, rates: dict) -> dict:
    """单条路由：附上该模型的费用倍率。"""
    view = {**item, "at": _fmt_ts(item.get("ts"))}
    model = item.get("model")
    profile = item.get("profile")
    by_profile = rates.get(model) if model else None
    if isinstance(by_profile, dict) and by_profile:
        value = by_profile.get(profile)
        if value is None:
            value = min(by_profile.values())
        view["rate"] = value
    else:
        view["rate"] = None
    return view


def _account_view(item: dict, ledger_snap: dict) -> dict:
    auth_file = _basename(item.get("auth_file"))
    account_key = item.get("account_key")
    rec = _credits_for(item.get("auth_file"), account_key, ledger_snap)
    credit = rec.get("credits") if isinstance(rec.get("credits"), dict) else {}
    checkin = rec.get("checkin") if isinstance(rec.get("checkin"), dict) else {}
    remaining = credit.get("credits")
    if remaining is None:
        remaining = sum(float(seg.get("remaining") or 0)
                        for seg in (credit.get("segments") or [])
                        if isinstance(seg, dict))
    return {
        "nickname": item.get("nickname"),
        "uid": item.get("uid"),
        "auth_file": auth_file,
        "profile": item.get("profile"),
        "region": item.get("region"),
        "product": item.get("product"),
        "healthy": bool(item.get("healthy")),
        "token_expired": bool(item.get("token_expired")),
        "enabled": is_enabled(auth_file),
        "sticky_sessions": int(item.get("sticky_sessions") or 0),
        "model_cooldowns": item.get("model_cooldowns") or {},
        "credits": round(float(remaining or 0), 2),
        "soonest_expiry": _fmt_ts(credit.get("soonest_expiry")),
        "checkin_ok": bool(checkin.get("ok")),
        "checkin_date": checkin.get("date"),
        "checkin_message": (str(checkin.get("message") or "")[:80] or None),
        "token_expires_at": _fmt_ts(item.get("token_expires_at"), millis=True),
    }


def _credits_for(auth_file, account_key, ledger_snap: dict) -> dict:
    if auth_file and auth_file in ledger_snap:
        rec = ledger_snap[auth_file]
        return rec if isinstance(rec, dict) else {}
    if account_key:
        for rec in ledger_snap.values():
            if isinstance(rec, dict) and rec.get("identity") == account_key:
                return rec
    name = _basename(auth_file)
    if name:
        for key, rec in ledger_snap.items():
            if _basename(key) == name and isinstance(rec, dict):
                return rec
    return {}


def _basename(path) -> str | None:
    if not path:
        return None
    name = os.path.basename(str(path))
    return name or None


def _fmt_ts(ts, millis: bool = False) -> str | None:
    try:
        value = float(ts)
    except (TypeError, ValueError):
        return None
    if value <= 0:
        return None
    if millis or value > 1e12:
        value = value / 1000
    return datetime.fromtimestamp(value, BJ).strftime("%Y-%m-%d %H:%M")


PAGE_HTML = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>codebuddy2api 看板</title>
<style>
:root {
  --bg: #12151c;
  --card: #1b202a;
  --line: #2c3442;
  --text: #e8edf5;
  --muted: #8b95a8;
  --ok: #3dd68c;
  --warn: #f5b942;
  --bad: #ef6b6b;
  --accent: #e38b3a;
}
* { box-sizing: border-box; }
body {
  margin: 0;
  font: 14px/1.5 -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
  background: var(--bg);
  color: var(--text);
}
header {
  display: flex;
  justify-content: space-between;
  gap: 16px;
  align-items: flex-end;
  padding: 22px 24px 12px;
  border-bottom: 1px solid var(--line);
}
h1 { margin: 0; font-size: 20px; letter-spacing: .02em; }
.sub { color: var(--muted); font-size: 12px; margin-top: 4px; }
.totals { display: flex; gap: 18px; color: var(--muted); font-size: 13px; }
.totals b { color: var(--accent); font-size: 16px; }
main { padding: 18px 24px 40px; }
.grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
  gap: 12px;
}
.card {
  background: var(--card);
  border: 1px solid var(--line);
  border-radius: 12px;
  padding: 14px 16px;
}
.card.pick {
  cursor: pointer;
  user-select: none;
}
.card.pick.on {
  border-color: var(--accent);
  box-shadow: 0 0 0 1px color-mix(in srgb, var(--accent) 45%, transparent);
}
.card.pick.off {
  opacity: .48;
  border-style: dashed;
}
.nick { font-size: 16px; font-weight: 650; word-break: break-all; }
.meta { color: var(--muted); font-size: 12px; margin: 4px 0 10px; }
.row { display: flex; justify-content: space-between; gap: 12px; margin: 5px 0; }
.k { color: var(--muted); }
.ok { color: var(--ok); }
.warn { color: var(--warn); }
.bad { color: var(--bad); }
table { width: 100%; border-collapse: collapse; font-size: 13px; }
th, td { text-align: left; padding: 8px 6px; border-bottom: 1px solid var(--line); }
th { color: var(--muted); font-weight: 550; }
.auth {
  display: none;
  margin: 12px 24px 0;
  padding: 12px 14px;
  border: 1px solid var(--line);
  border-radius: 10px;
  background: var(--card);
}
.auth input {
  width: min(360px, 100%);
  margin-right: 8px;
  padding: 7px 10px;
  border-radius: 8px;
  border: 1px solid var(--line);
  background: #10141b;
  color: var(--text);
}
button {
  background: var(--accent);
  color: #1a1208;
  border: 0;
  border-radius: 8px;
  padding: 7px 12px;
  font-weight: 650;
  cursor: pointer;
}
.err { color: var(--bad); margin: 12px 24px 0; }
.tabs { display: flex; gap: 8px; padding: 12px 24px 0; }
.tab {
  font: inherit; color: var(--muted); background: none; cursor: pointer;
  border: 1px solid var(--line); border-radius: 6px; padding: 6px 14px;
}
.tab:hover { color: var(--text); }
.tab.on { color: var(--text); background: var(--card); border-color: var(--accent); }
.rate-free { color: var(--ok); }
.rate-none { color: var(--muted); }
</style>
</head>
<body>
<header>
  <div>
    <h1>codebuddy2api 看板</h1>
    <div class="sub" id="sub">点亮的账号才会被路由；没点亮的不会用</div>
  </div>
  <div class="totals" id="totals"></div>
</header>
<nav class="tabs">
  <button type="button" class="tab on" data-view="accounts">账号</button>
  <button type="button" class="tab" data-view="models">模型与倍率</button>
</nav>
<div class="auth" id="auth">
  已启用 API key，请输入后查看数据
  <div style="margin-top:8px">
    <input id="key" type="password" placeholder="CODEBUDDY2API_KEY" autocomplete="off">
    <button type="button" id="save">保存</button>
  </div>
</div>
<div class="err" id="err"></div>
<main>
  <section id="view-accounts">
    <div class="grid" id="accounts"></div>
    <div class="card" style="margin-top:16px; overflow:auto">
      <div class="nick">最近路由</div>
      <div class="meta">看模型还不够时，以这里的账号为准</div>
      <table>
        <thead><tr><th>时间</th><th>账号</th><th>模型</th><th>倍率</th><th>profile</th><th>文件</th></tr></thead>
        <tbody id="routes"></tbody>
      </table>
    </div>
  </section>
  <section id="view-models" hidden>
    <div class="grid">
      <div class="card">
        <div class="nick">国际版模型</div>
        <div class="meta">走 intl-work / intl-cli；倍率为 credits 扣费系数，越小越省</div>
        <table>
          <thead><tr><th>模型</th><th>倍率</th><th>归属 profile</th></tr></thead>
          <tbody id="models-intl"></tbody>
        </table>
      </div>
      <div class="card">
        <div class="nick">国内版模型</div>
        <div class="meta">走 cn-cli / cn-work；倍率为 credits 扣费系数，越小越省</div>
        <table>
          <thead><tr><th>模型</th><th>倍率</th><th>归属 profile</th></tr></thead>
          <tbody id="models-cn"></tbody>
        </table>
      </div>
    </div>
  </section>
</main>
<script>
const $ = (id) => document.getElementById(id);
let busy = false;
function headers() {
  const h = { 'Content-Type': 'application/json' };
  const key = sessionStorage.getItem('codebuddy2api_key') || '';
  if (key) h['Authorization'] = 'Bearer ' + key;
  return h;
}
function cls(ok, badLabel, okLabel) {
  return ok ? '<span class="ok">' + okLabel + '</span>' : '<span class="bad">' + badLabel + '</span>';
}
async function load() {
  if (busy) return;
  let res;
  try {
    res = await fetch('/admin/dashboard', { headers: headers() });
  } catch (e) {
    $('err').textContent = '看板接口连不上，请确认服务还在跑';
    return;
  }
  if (res.status === 401) {
    $('auth').style.display = 'block';
    $('err').textContent = '需要 API key';
    return;
  }
  if (!res.ok) {
    $('err').textContent = '看板接口 ' + res.status;
    return;
  }
  $('auth').style.display = 'none';
  $('err').textContent = '';
  const data = await res.json();
  const t = data.totals || {};
  const r = data.routing || {};
  $('sub').textContent = 'v' + (data.version || '') + ' · 点卡片选用账号 · 已启用 '
    + (r.enabled ?? 0) + '/' + (r.total ?? 0)
    + ' · ' + new Date(data.updated_at * 1000).toLocaleString('zh-CN', { hour12: false });
  $('totals').innerHTML =
    '<div>国内选用 <b>' + (t.domestic ?? 0) + '</b></div>' +
    '<div>国际选用 <b>' + (t.international ?? 0) + '</b></div>';
  $('accounts').innerHTML = (data.accounts || []).map((a) =>
    '<section class="card pick ' + (a.enabled ? 'on' : 'off') + '" data-file="' +
      encodeURIComponent(a.auth_file || '') + '" data-enabled="' + (a.enabled ? '1' : '0') + '">' +
      '<div class="nick">' + (a.nickname || '(未命名)') + '</div>' +
      '<div class="meta">' + (a.profile || '') + ' · ' + (a.auth_file || '') + '</div>' +
      '<div class="row"><span class="k">路由</span>' +
        (a.enabled ? '<span class="ok">使用中 · 再点关闭</span>'
                   : '<span class="warn">未选用 · 点一下启用</span>') + '</div>' +
      '<div class="row"><span class="k">积分</span><b>' + a.credits + '</b></div>' +
      '<div class="row"><span class="k">状态</span>' + cls(a.healthy && !a.token_expired, '异常', '健康') + '</div>' +
      '<div class="row"><span class="k">黏绑会话</span><span>' + a.sticky_sessions + '</span></div>' +
      '<div class="row"><span class="k">签到</span>' +
        (a.checkin_ok ? '<span class="ok">成功 ' + (a.checkin_date || '') + '</span>'
                      : '<span class="warn">' + (a.checkin_message || '未成功') + '</span>') +
      '</div>' +
      '<div class="row"><span class="k">积分最早过期</span><span>' + (a.soonest_expiry || '-') + '</span></div>' +
    '</section>'
  ).join('') || '<div class="meta">还没有凭证</div>';
  document.querySelectorAll('.card.pick').forEach((el) => {
    el.onclick = () => toggle(el.dataset.file, el.dataset.enabled !== '1');
  });
  $('routes').innerHTML = (data.recent_routes || []).map((row) =>
    '<tr><td>' + (row.at || '') + '</td><td>' + (row.nickname || '-') +
    '</td><td>' + (row.model || '') +
    '</td><td>' + (row.rate === null || row.rate === undefined ? '-' : 'x' + row.rate) +
    '</td><td>' + (row.profile || '') +
    '</td><td>' + (row.auth_file || '') + '</td></tr>'
  ).join('') || '<tr><td colspan="6" class="k">还没有调用记录，先发一条请求</td></tr>';
}
function rateCell(credits) {
  if (credits === null || credits === undefined) return '<span class="rate-none">-</span>';
  if (credits === 0) return '<span class="rate-free">免费</span>';
  return 'x' + credits;
}
function fillModels(target, rows) {
  $(target).innerHTML = (rows || []).map((m) =>
    '<tr><td>' + (m.id || '') + '</td><td>' + rateCell(m.credits) +
    '</td><td>' + Object.keys(m.by_profile || {}).join(', ') + '</td></tr>'
  ).join('') || '<tr><td colspan="3" class="k">该地域暂无可用模型</td></tr>';
}
async function loadModels() {
  let res;
  try {
    res = await fetch('/admin/models', { headers: headers() });
  } catch (e) {
    $('err').textContent = '模型接口连不上，请确认服务还在跑';
    return;
  }
  if (res.status === 401) {
    $('auth').style.display = 'block';
    $('err').textContent = '需要 API key';
    return;
  }
  if (!res.ok) {
    $('err').textContent = '模型接口 ' + res.status;
    return;
  }
  const data = await res.json();
  const regions = data.regions || {};
  fillModels('models-intl', regions.intl);
  fillModels('models-cn', regions.cn);
}
function showView(name) {
  const isModels = name === 'models';
  $('view-accounts').hidden = isModels;
  $('view-models').hidden = !isModels;
  document.querySelectorAll('.tab').forEach((el) => {
    el.classList.toggle('on', el.dataset.view === name);
  });
  if (isModels) loadModels();
}
async function toggle(file, enabled) {
  const authFile = decodeURIComponent(file || '');
  if (!authFile || busy) return;
  busy = true;
  $('err').textContent = '';
  try {
    const res = await fetch('/admin/dashboard/accounts', {
      method: 'POST',
      headers: headers(),
      body: JSON.stringify({ auth_file: authFile, enabled: !!enabled }),
    });
    if (res.status === 401) {
      $('auth').style.display = 'block';
      $('err').textContent = '需要 API key';
      return;
    }
    if (!res.ok) {
      $('err').textContent = '切换失败 ' + res.status;
      return;
    }
  } catch (e) {
    $('err').textContent = '切换失败，请确认服务还在跑';
    return;
  } finally {
    busy = false;
  }
  await load();
}
$('save').onclick = () => {
  sessionStorage.setItem('codebuddy2api_key', $('key').value.trim());
  load();
  if (!$('view-models').hidden) loadModels();
};
document.querySelectorAll('.tab').forEach((el) => {
  el.onclick = () => showView(el.dataset.view);
});
load();
setInterval(load, 30000);
</script>
</body>
</html>
"""
