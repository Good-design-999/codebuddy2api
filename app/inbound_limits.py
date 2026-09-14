#!/usr/bin/env python3
"""inbound_limits.py — 推理端点入站原始字节限量。

端点先 await request.json() 再检查处理后的上游请求体，原始入站大小无人管：大 JSON、
被忽略的顶层字段、将被剥离的图片都在解析前已经占用了内存。本中间件在 ASGI receive 层
累计原始字节（含 chunked 传输，不看 Content-Length），超限直接 413，不进入 JSON 解析。
缓冲体随后原样回放给下游，端点行为不变。
"""

from __future__ import annotations

import json


class InboundBodyLimitMiddleware:
    """/v1/* 请求的原始字节上限；limit<=0 时关闭。"""

    def __init__(self, app, config):
        self.app = app
        self.config = config

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or not scope.get("path", "").startswith("/v1/"):
            return await self.app(scope, receive, send)
        try:
            limit = int(self.config.get("max_inbound_bytes") or 0)
        except (TypeError, ValueError):
            limit = 0
        if limit <= 0:
            return await self.app(scope, receive, send)

        body = bytearray()
        more = True
        while more:
            message = await receive()
            if message["type"] == "http.request":
                body.extend(message.get("body", b""))
                more = bool(message.get("more_body"))
                if len(body) > limit:
                    return await self._reject(send, scope["path"], limit)
            elif message["type"] == "http.disconnect":
                return

        buffered = bytes(body)
        replayed = False

        async def replay():
            nonlocal replayed
            if replayed:
                return {"type": "http.disconnect"}
            replayed = True
            return {"type": "http.request", "body": buffered, "more_body": False}

        await self.app(scope, replay, send)

    @staticmethod
    async def _reject(send, path: str, limit: int):
        # 与协议化错误处理一致的外形（middle ware 在路由之前，自行成形）
        if path.startswith("/v1/messages"):
            payload = {"type": "error", "error": {"type": "invalid_request_error",
                                                  "message": f"request body exceeds {limit} bytes",
                                                  "code": "request_too_large"}}
        else:
            payload = {"error": {"message": f"request body exceeds {limit} bytes",
                                 "type": "invalid_request_error", "code": "request_too_large"}}
        raw = json.dumps(payload).encode("utf-8")
        await send({"type": "http.response.start", "status": 413,
                    "headers": [(b"content-type", b"application/json"),
                                (b"content-length", str(len(raw)).encode())]})
        await send({"type": "http.response.body", "body": raw})
