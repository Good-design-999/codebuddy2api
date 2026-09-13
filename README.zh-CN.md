# codebuddy2api

把 **WorkBuddy / CodeBuddy（腾讯代码助手）** 订阅变成本机可用的 **OpenAI / Anthropic 兼容 API**。

[English](README.md)

- 支持 Chat Completions、Responses 和 Anthropic Messages，包含工具调用与流式输出。
- 内置 **WebUI**：扫码添加账号，管理模型、凭证、日志与设置，无需桌面端。
- 多账号自动选路，兼容国内／国际站，自动刷新凭证。

## 快速开始

需要 Git 和 Docker Compose；以下方式从源码构建，已包含 WebUI。

```bash
git clone https://github.com/maiphucgiang/codebuddy2api.git
cd codebuddy2api
cp .env.example .env
```

编辑 `.env`，将 `CODEBUDDY2API_KEY` 设置为你自己的随机密钥；已有 `.env` 请勿覆盖。然后启动：

```bash
docker compose build
docker compose up -d
```

1. 打开 **http://127.0.0.1:8787/dashboard**，使用刚设置的 API key 登录。
2. 在「凭证管理」扫码添加国内或国际账号，也可导入 `.info` 文件。
3. 在「模型路由」查看可用模型，将其对外 ID 填入客户端。

按模板配置时仅允许本机访问。远程访问前请配置 HTTPS 并限制网络访问；保留并妥善备份 `auth/` 数据目录。

[使用发布镜像或本地 Python 运行 →](docs/deployment.zh-CN.md)

## 客户端接入

| 协议 | Base URL |
|------|----------|
| OpenAI Chat / Responses | `http://127.0.0.1:8787/v1` |
| Anthropic Messages | `http://127.0.0.1:8787` |

- **API Key**：与 WebUI 登录使用同一个密钥。
- **模型**：使用 WebUI 中的对外 ID，或查询 `GET /v1/models`。
- 国内、国际账号共用这些地址，无需额外的地域参数。Anthropic SDK 会自行追加 `/v1/messages`，不要把它写入 Base URL。

[Codex CLI、Claude Code / CC Switch 等配置示例 →](docs/clients.zh-CN.md)

## 文档

| 指南 | 内容 |
|------|------|
| [WebUI 使用指南](docs/webui.zh-CN.md) | 添加账号、模型路由、日志审计、设置与备份 |
| [部署指南](docs/deployment.zh-CN.md) | 发布镜像、本地运行、命令行登录与升级 |
| [客户端配置](docs/clients.zh-CN.md) | Codex CLI、Claude Code、CC Switch 与通用客户端 |
| [进阶参考](docs/advanced.zh-CN.md) | 参数、API、模型调度、请求限制与故障排查 |

## 免责声明

本项目仅供个人学习使用，不得用于商业用途。与腾讯、WorkBuddy、CodeBuddy、OpenAI、Anthropic 无官方关联。本项目仅调用你已登录账号的官方接口，请仅在你合法拥有订阅的前提下使用；账号与凭据的一切使用责任及风险由使用者自行承担。

## 开源协议

[MIT](LICENSE)

## 社区

感谢 [LINUX DO](https://linux.do) 社区提供开放、友善的技术交流平台。
