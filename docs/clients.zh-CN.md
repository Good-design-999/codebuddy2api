# 客户端配置

[返回首页](../README.zh-CN.md) · [English](clients.md)

先在 [WebUI](webui.zh-CN.md) 添加账号。下文的 `YOUR_GATEWAY_API_KEY` 替换为网关 API key，`MODEL_ID` 替换为模型的对外 ID；地址和端口按实际部署修改。

## 通用配置

| 协议 | Base URL |
|------|----------|
| OpenAI Chat / Responses | `http://127.0.0.1:8787/v1` |
| Anthropic Messages | `http://127.0.0.1:8787` |

国内／国际、CLI／WorkBuddy 账号共用这些地址，后端自动选路，不需要 `/cn`、`/intl` 前缀。客户端 API key 与 WebUI 登录密钥相同；管理 Cookie 不能替代客户端密钥。

查询可用模型：

```bash
curl http://127.0.0.1:8787/v1/models \
  -H 'Authorization: Bearer YOUR_GATEWAY_API_KEY'
```

以这里返回的 ID 或 WebUI 中的对外 ID 为准，不要假设所有账号支持同一组模型。可在 WebUI 配置别名；网关不自动猜测 Anthropic 模型名的映射。

## Codex CLI

将以下配置合并到 `~/.codex/config.toml`，不要覆盖已有配置：

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
codex --profile workbuddy "你的任务描述"
```

Codex 使用 `/v1/responses`。运行时上下文与真实指令分开处理；超限请求返回 HTTP 413，不静默截断最新用户请求。

## Claude Code / CC Switch

```bash
export ANTHROPIC_BASE_URL=http://127.0.0.1:8787
export ANTHROPIC_AUTH_TOKEN='YOUR_GATEWAY_API_KEY'
export ANTHROPIC_MODEL='MODEL_ID'
claude
```

- Claude Code、Anthropic SDK 和 CC Switch 的 Anthropic 提供商使用不带 `/v1/messages` 的 Base URL，SDK 会自行追加路径。只有明确要求完整端点的客户端才填写 `/v1/messages`。
- `POST /v1/messages` 在后端转换为 Chat Completions，支持原生工具调用与思考内容透传。
- WorkBuddy 的固定 CLI 模板适配由 `--desensitize` 控制；默认关闭，项目 Compose 配置已开启。保留完整行为指令等选项见 [进阶参考](advanced.zh-CN.md)。

## 其他 OpenAI 兼容客户端

Cherry Studio、ZCode、LobeChat、NextChat、Open WebUI 或自写 SDK 均按通用配置填写 Base URL、API key 和模型 ID。

三个生成接口分别是 `POST /v1/chat/completions`、`POST /v1/responses`、`POST /v1/messages`；需要 JSON 响应时显式设置 `stream: false`，需要 SSE 时设置 `stream: true`。

`developer` 消息会统一转换为 `system`，不修改调用方原始 payload。指定函数的 `tool_choice` 会转换为仅提供该函数并设为 `required`，无效名称在本地拒绝。
