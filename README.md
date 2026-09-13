# codebuddy2api

Use your **WorkBuddy / CodeBuddy (Tencent)** subscription as local **OpenAI- and Anthropic-compatible APIs**.

[中文文档](README.zh-CN.md)

- Chat Completions, Responses and Anthropic Messages, with tool calling and streaming.
- Built-in **WebUI** for browser login, models, credentials, logs and settings — no desktop client required.
- Automatic multi-account routing across domestic and international sites, with credential refresh.

## Quick start

Requires Git and Docker Compose. This builds from source and includes the WebUI.

```bash
git clone https://github.com/maiphucgiang/codebuddy2api.git
cd codebuddy2api
cp .env.example .env
```

Edit `.env` and set `CODEBUDDY2API_KEY` to your own random key; do not overwrite an existing `.env`. Then start:

```bash
docker compose build
docker compose up -d
```

1. Open **http://127.0.0.1:8787/dashboard** and sign in with that API key.
2. In **Credentials**, add a domestic or international account through browser login, or import an `.info` file.
3. In **Models**, find an available model and use its public ID in your client.

The template binds to localhost only. Configure HTTPS and restrict network access before allowing remote connections; keep and securely back up the `auth/` data directory.

[Published images and local Python setup →](docs/deployment.md)

## Client setup

| Protocol | Base URL |
|----------|----------|
| OpenAI Chat / Responses | `http://127.0.0.1:8787/v1` |
| Anthropic Messages | `http://127.0.0.1:8787` |

- **API key:** the same key used to sign in to the WebUI.
- **Model:** a public ID from the WebUI or `GET /v1/models`.
- All accounts use these URLs; no region parameter is needed. Anthropic SDKs append `/v1/messages` themselves, so leave it out of the Base URL.

[Codex CLI, Claude Code / CC Switch and other client examples →](docs/clients.md)

## Documentation

| Guide | Contents |
|-------|----------|
| [WebUI guide](docs/webui.md) | Accounts, model routing, audit logs, settings and backups |
| [Deployment](docs/deployment.md) | Published images, local setup, CLI login and upgrades |
| [Client configuration](docs/clients.md) | Codex CLI, Claude Code, CC Switch and generic clients |
| [Advanced reference](docs/advanced.md) | Options, APIs, model scheduling, request limits and troubleshooting |

## Disclaimer

For personal learning only — no commercial use. Not affiliated with Tencent, WorkBuddy, CodeBuddy, OpenAI, or Anthropic. This project only calls official APIs of accounts you are logged into; use it solely with subscriptions you legally own. You are solely responsible for your account, credentials, and all associated risks.

## License

[MIT](LICENSE)

## Community

Thanks to the [LINUX DO](https://linux.do) community for providing an open and friendly platform for technical discussions.
