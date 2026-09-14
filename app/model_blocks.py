#!/usr/bin/env python3
"""model_blocks.py — (后端, 模型) 负缓存：官方已经答复「这里没有这个模型」，就别再往上打。

云端 /v3/config 的模型目录与实际能调通的模型并不一致：目录里没写的模型可能可用，目录里
写着的模型（国际站 www.codebuddy.ai 的 deepseek-v3-2-volc）却固定回 11102
"model [...] service info not found"。目录不可信，但 11102 是该后端的确定性答复，拿它当
避让依据比任何目录都准。多站点共存时，缺模型的后端必须被跳过，否则黏性会话会一直落到
它上面拿到空回复。

按后端（PROFILE_ENDPOINTS 里的入口）而不是按站点记账：同属国内站的 codebuddy 与
workbuddy 是两套后端，模型可用性互不相关，拉黑一个不该牵连另一个。

不做永久拉黑：按 TTL 半开，到期后放行一次；再命中就指数退避（上限 max_ttl_s），这样后端
悄悄上线某模型时能自愈，平时也不会一直白打。实测成功可 clear() 立即解除。
"""

from __future__ import annotations

import json
import os
import threading
import time

DEFAULT_TTL_S = 6 * 3600        # 首次避让时长
MAX_TTL_S = 24 * 3600           # 反复命中后的退避上限：最多一天再试一次
RETAIN_AFTER_S = 24 * 3600      # 过期记录再留一天，保住 hits 才能继续指数退避


class ModelBlocks:
    """线程安全的 {后端入口: {模型: 避让记录}}；可选落盘，重启后不必重新踩坑。"""

    def __init__(self, path=None, ttl_s: float = DEFAULT_TTL_S, max_ttl_s: float = MAX_TTL_S):
        self.path = str(path) if path else None
        self.ttl_s = max(60.0, float(ttl_s or 0))
        self.max_ttl_s = max(self.ttl_s, float(max_ttl_s or 0))
        self._lock = threading.Lock()
        self._data: dict[str, dict] = {}
        if self.path:
            self._load()

    # ---- 持久化 ----

    def _load(self):
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError):
            return
        if not isinstance(data, dict):
            return
        out: dict[str, dict] = {}
        for endpoint, models in (data.get("blocks") or {}).items():
            if not isinstance(models, dict):
                continue
            rows = {}
            for model, row in models.items():
                if isinstance(row, dict) and float(row.get("until") or 0) > 0:
                    rows[str(model)] = {"until": float(row["until"]), "hits": int(row.get("hits") or 1),
                                        "code": str(row.get("code") or ""),
                                        "since": float(row.get("since") or 0),
                                        "msg": str(row.get("msg") or "")[:200]}
            if rows:
                out[str(endpoint)] = rows
        with self._lock:
            self._data = out

    def _save_locked(self):
        if not self.path:
            return
        try:
            tmp = self.path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                f.write(json.dumps({"version": 1, "blocks": self._data}, ensure_ascii=False))
            os.replace(tmp, self.path)
            os.chmod(self.path, 0o600)
        except OSError:
            pass    # 避让表写失败只影响重启后的精度，绝不影响请求路径

    def _prune_locked(self, now: float):
        cutoff = now - RETAIN_AFTER_S
        for endpoint in list(self._data):
            rows = {m: r for m, r in self._data[endpoint].items() if float(r.get("until") or 0) > cutoff}
            if rows:
                self._data[endpoint] = rows
            else:
                self._data.pop(endpoint, None)

    # ---- 写入 ----

    def note(self, endpoint: str, model: str, code: str = "", msg: str = "",
             now: float | None = None) -> dict:
        """记一次「该后端不提供该模型」；重复命中按 hits 指数退避，返回该条目。"""
        endpoint, model = str(endpoint or ""), str(model or "")
        if not endpoint or not model:
            return {}
        now = time.time() if now is None else now
        with self._lock:
            previous = (self._data.get(endpoint) or {}).get(model) or {}
            hits = int(previous.get("hits") or 0) + 1
            ttl = min(self.ttl_s * (2 ** min(hits - 1, 6)), self.max_ttl_s)
            entry = {"until": round(now + ttl, 3), "hits": hits, "code": str(code or ""),
                     "since": float(previous.get("since") or now), "msg": str(msg or "")[:200]}
            self._data.setdefault(endpoint, {})[model] = entry
            self._prune_locked(now)
            self._save_locked()
            return dict(entry)

    def clear(self, endpoint: str, model: str, now: float | None = None) -> bool:
        """实测又通了就立刻解除，不必等 TTL 到期。"""
        now = time.time() if now is None else now
        with self._lock:
            rows = self._data.get(str(endpoint)) or {}
            row = rows.get(str(model))
            if not row or now >= float(row.get("until") or 0):
                return False
            rows.pop(str(model), None)
            self._save_locked()
            return True

    # ---- 读取 ----

    def until(self, endpoint: str, model: str, now: float | None = None) -> float:
        """仍在避让期返回解除时间戳，否则 0.0（到期即半开放行）。"""
        now = time.time() if now is None else now
        with self._lock:
            row = (self._data.get(str(endpoint)) or {}).get(str(model))
            value = float(row.get("until") or 0) if row else 0.0
        return value if value > now else 0.0

    def blocked(self, endpoint: str, model: str, now: float | None = None) -> bool:
        return self.until(endpoint, model, now) > 0.0

    def view(self, now: float | None = None) -> dict:
        """{后端入口: {模型: 解除时间}}，只含仍在避让期的条目。"""
        now = time.time() if now is None else now
        with self._lock:
            return {endpoint: {m: float(r.get("until") or 0) for m, r in rows.items()
                               if float(r.get("until") or 0) > now}
                    for endpoint, rows in self._data.items()}

    def detail(self, now: float | None = None) -> list:
        """看板用明细（按解除时间升序），含命中次数与官方错误码。"""
        now = time.time() if now is None else now
        with self._lock:
            rows = [{"endpoint": endpoint, "model": m, **r}
                    for endpoint, models in self._data.items() for m, r in models.items()
                    if float(r.get("until") or 0) > now]
        rows.sort(key=lambda r: r["until"])
        return rows
