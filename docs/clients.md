# Client configuration

[Home](../README.md) · [简体中文](clients.zh-CN.md)

Add an account in the [WebUI](webui.md) first. Replace `YOUR_GATEWAY_API_KEY` with the gateway API key and `MODEL_ID` with a public model ID. Adjust addresses and ports for your deployment.

## Common settings

| Protocol | Base URL |
|----------|----------|
| OpenAI Chat / Responses | `http://127.0.0.1:8787/v1` |
| Anthropic Messages | `http://127.0.0.1:8787` |

Domestic/international and CLI/WorkBuddy accounts use the same URLs. Backend routing is automatic; no `/cn` or `/intl` prefix is needed. Clients use the WebUI login key, not its management Cookie.

List available models:

```bash
curl http://127.0.0.1:8787/v1/models \
  -H 'Authorization: Bearer YOUR_GATEWAY_API_KEY'
```

Use an ID from this response or the WebUI; accounts do not necessarily support the same models. Public aliases can be configured in the UI. Anthropic model names are not automatically guessed or mapped.

## Codex CLI

Merge this into `~/.codex/config.toml`; do not overwrite existing configuration:

```toml
[model_providers.workbuddy]
name = "WorkBuddy (via local converter)"
base_url = "http://127.0.0.1:8787/v1"
wire_api = "responses"
env_key = "CODEBUDDY2API_KEY"

[profiles.workbuddy]
model = "MODEL_ID"
model_provider = "workbuddy"
```

```bash
export CODEBUDDY2API_KEY='YOUR_GATEWAY_API_KEY'
codex --profile workbuddy "your task"
```

Codex uses `/v1/responses`. Runtime context is processed separately from real instructions; oversized requests return HTTP 413 rather than silently truncating the latest user request.

## Claude Code / CC Switch

```bash
export ANTHROPIC_BASE_URL=http://127.0.0.1:8787
export ANTHROPIC_AUTH_TOKEN='YOUR_GATEWAY_API_KEY'
export ANTHROPIC_MODEL='MODEL_ID'
claude
```

- Claude Code, Anthropic SDKs and CC Switch's Anthropic provider use a Base URL without `/v1/messages`; SDKs append the path themselves. Only clients explicitly asking for a complete endpoint should include `/v1/messages`.
- `POST /v1/messages` is converted to upstream Chat Completions, retaining native tool calls and reasoning content.
- `--desensitize` controls WorkBuddy's fixed CLI-template adaptation. It is off by default and enabled in the project's Compose configuration. See the [advanced reference](advanced.md) for options such as retaining fuller instructions.

## Other OpenAI-compatible clients

Use the common Base URL, API key and model ID with Cherry Studio, ZCode, LobeChat, NextChat, Open WebUI or your own SDK client.

The generation endpoints are `POST /v1/chat/completions`, `POST /v1/responses` and `POST /v1/messages`. Set `stream: false` explicitly for JSON responses or `stream: true` for SSE.

`developer` messages are normalized to `system` without mutating the caller's original payload. Named function choices are sent upstream as `required` with only that function available; invalid names are rejected locally.
