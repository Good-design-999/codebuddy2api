# 进阶参考

[返回首页](../README.zh-CN.md) · [English](advanced.md)

日常操作使用 [WebUI](webui.zh-CN.md)；部署方式见 [部署指南](deployment.zh-CN.md)，客户端示例见 [客户端配置](clients.zh-CN.md)。

## 配置与命令行

配置优先级：**显式 CLI 参数 > 环境变量 > WebUI 持久化配置 > 默认值**。WebUI 中可热更新的设置立即生效，标记为重启生效的设置需手动重启；锁定项须在启动配置中修改，WebUI 不改写 `.env`。

Compose 会显式传入部分环境变量及 CLI 参数，删除 `.env` 中的一行不一定解除锁定。修改这些值后重建容器；若要由 WebUI 接管，还需取消 Compose 中对应的显式设置。

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `--host` / `--port` | `127.0.0.1` / `8787` | 本地监听地址与端口 |
| `--api-key` | 无 | 管理与推理共用密钥；未设置时管理锁定 |
| `--admin-csrf [true/false]` | `true` | 管理 Origin/CSRF 校验；仅启动配置可关闭，API key 和会话鉴权不变 |
| `--auth-file` | 扫描 `auth/` | 指定凭据文件，可重复传入；不再扫描其他文件 |
| `--log` | 无 | 额外文本日志，50 MiB 轮转、保留 2 份；不影响默认 SQLite 审计 |
| `--desensitize` | 关 | 适配固定 CLI 模板、压缩运行时提示、零宽脱敏关键词 |
| `--no-compact` | 关 | 配合脱敏保留主要行为指令，仍适配模板及裁剪运行时上下文；不关闭 Responses 投影 |
| `--keep-tool-metadata [true/false]` | `false` | 保留工具描述及参数 schema 的 `description/title`，与提示词压缩独立 |
| `--skip-check` | 关 | 跳过启动预检 |
| `--credit-price-cny` | `0.014` | 国内积分折算单价，元/Credit |
| `--credit-price-usd` | `0.03` | 国际积分折算单价，美元/Credit |
| `--usd-rate` | `7.15` | 每美元对应人民币金额，用于 billing 折算 |
| `--model-catalog-ttl` | `21600` | 模型目录缓存有效期，秒 |
| `--no-model-guard` | 关 | 关闭目录外模型的本地拦截；表外透传仅限单产品，不绕过禁用、绑定或目录就绪检查 |
| `--auto-trial [true/false]` | `false` | 尝试领取国际 WorkBuddy 一次性体验积分 |
| `--max-images` | `16` | 单请求图片总数；`0` 不允许图片 |
| `--image-policy` | `truncate` | 保留最新图片；设为 `error` 时超限返回 413 |
| `--max-request-bytes` | `33554432` | 处理后的上游 JSON 字节上限，须为正整数 |
| `--log-body-limit` | `65536` | 兼容文本日志正文预览字节；`0` 只记摘要，不控制 SQLite 诊断预算 |

环境变量包括 `CODEBUDDY_AUTH_DIR`、`CODEBUDDY_IMPORT_DIR`、`CODEBUDDY2API_KEY`、`CODEBUDDY2API_ADMIN_CSRF`、`CODEBUDDY2API_KEEP_TOOL_METADATA`、`CODEBUDDY2API_LOG`，以及 `CODEBUDDY2API_MAX_IMAGES`、`CODEBUDDY2API_IMAGE_POLICY`、`CODEBUDDY2API_MAX_REQUEST_BYTES`、`CODEBUDDY2API_LOG_BODY_LIMIT`、`CODEBUDDY2API_AUTO_TRIAL`。启动示例见 [部署指南](deployment.zh-CN.md)。

体验积分领取默认关闭，仅适用于符合上游资格的 `intl-work` 账号。成功或已领取的结果按账号保存到 `auth/trial-ledger.json`，失败至少退避 24 小时，不立即重放 POST；资格与额度以上游为准，升级时保留该文件。

### 工具描述保留

默认关闭，沿用旧策略：启用脱敏会剥离工具描述，Responses 的工具投影也会剥离描述；`--no-compact` 不改变这一行为。开启后，Chat、Responses、Messages 保留已支持工具定义中的描述及参数 schema 的字符串 `description/title`。若启用脱敏，保留的文本仍会处理；提示词压缩、现有审核兜底条件与重试次数不变，兜底也遵守本开关。

- **WebUI**：系统设置 → 保留工具描述，未被启动来源锁定时可立即生效并持久化。
- **CLI**：在原启动命令追加 `--keep-tool-metadata` 或 `--keep-tool-metadata true`；显式 `false` 可覆盖环境变量。
- **环境变量**：设置 `CODEBUDDY2API_KEEP_TOOL_METADATA=true`；Compose 会传入已设置的值，未设置时不锁定 WebUI。删除或注释变量可解除环境锁定，不要设为空串。

需使用包含此功能的源码/镜像和 Compose 配置；修改容器环境后重新创建容器。保留描述可能增加输入 token 和审核拦截风险，不保证所有账号/模型都同样兼容；设为 `false` 可恢复旧策略。此开关不恢复 Responses 原有投影裁掉的其他 schema 字段或深层节点，也不放宽请求体预算。

## API 与鉴权

| 客户端接口 | 说明 |
|------------|------|
| `POST /v1/chat/completions` | OpenAI Chat Completions |
| `POST /v1/responses` | OpenAI Responses |
| `POST /v1/messages` | Anthropic Messages |
| `POST /v1/messages/count_tokens` | 兼容占位接口，当前固定返回 `{"input_tokens":0}`，不实际计数 |
| `GET /v1/models` | 可用模型及倍率信息 |
| `GET /v1/dashboard/billing/subscription` | 积分折算额度；`codebuddy_balance_usd` 为剩余余额 |
| `GET /v1/dashboard/billing/usage` | 美分计量的 `total_usage` 与按日明细 |

`hard_limit_usd` 是剩余额度加已用额度的美元折算，不是剩余余额。未指定日期范围时，余额等于 `hard_limit_usd - total_usage / 100`；这些是本地折算值，不是分发计费系统。

| 管理与共用接口 | 说明 |
|----------------|------|
| `GET /health` | 公开存活检查，仅返回 `{"status":"ok"}` |
| `GET /admin/credentials` | 凭证列表与运行状态 |
| `POST /admin/credentials` | 从服务端受控目录导入 `.info` |
| `DELETE /admin/credentials/{name}` | 按文件名删除凭证文件；仍被模型绑定引用时返回 409 |
| `PATCH /admin/credentials/{id}` | 按账号身份 ID 启停凭证，不删除文件 |
| `POST /admin/oauth/start` · `GET /admin/oauth/poll` | 发起与轮询登录；`site=cn`（默认）、`intl`（国际 WorkBuddy）或 `intl-codebuddy`（国际 CodeBuddy） |
| `GET /admin/credits` · `POST /admin/checkin` | 查询额度、手动触发签到与额度同步 |

页面使用 `/dashboard/*`，管理 API 使用 `/admin/*`，客户端保留原 `/v1/*`；不注册 `/cn`、`/intl` API 前缀。模型自动选路不要求客户端改变地址。

管理必须配置 API key；WebUI 使用同 key 建立 HttpOnly 管理 Cookie，Cookie 仅授权 `/admin/*`，不能用于 `/v1/*`。命令行 API 请求携带 `Authorization: Bearer <key>` 或 `X-Api-Key`。空 key 仅保留推理接口的历史无鉴权行为，不开放管理；`/health` 不返回账号、路径或异常详情。

### 管理 Origin / CSRF 开关

默认开启。OAuth 轮询在 `Origin`、`Sec-Fetch-Site` 均缺失时，兼容同源 `Referer`（协议、主机、端口一致），仍要求有效 CSRF token。已有 `Origin` 优先校验；无 `Origin` 但有 Fetch Metadata 时，只接受 `same-origin`，不会再用 Referer 回退。登录和写操作仍要求 Origin。

正常同源访问不需要关闭保护。若仍报错，先统一访问地址、检查反代传递的 Host 和协议，并刷新页面重新登录。仅在受信任本地环境需要关闭时，在原启动命令追加 `--admin-csrf false`，或在已有 `.env` 中设置：

```dotenv
CODEBUDDY2API_ADMIN_CSRF=false
```

仅启动时生效，CLI 优先于环境变量，不能通过 WebUI 修改。使用包含该开关的源码或镜像，并更新 Compose 配置；修改环境后须重新创建容器，不能仅执行 `docker compose restart`。旧镜像不会因新增变量自动获得此功能。

关闭会跳过登录请求的 Origin 检查，以及 Cookie 管理写操作和 OAuth 轮询的 Origin/CSRF 检查；API key、会话有效期、OAuth 任务归属、官方授权地址白名单和危险操作确认仍保留，不影响 `/v1/*`。

**关闭会降低浏览器跨站请求保护，不应将此配置直接暴露到公网。** 恢复 `--admin-csrf true` 或环境变量 `true` 并重启即可重新启用。

### 服务端路径导入

WebUI 可以直接上传文件；以下限制针对 `POST /admin/credentials` 的路径导入：

- 将文件放入 `auth/imports/`，或 `CODEBUDDY_IMPORT_DIR` 指定的服务端目录。
- 仅接受直接子级普通 `.info` 文件，拒绝符号链接、子目录及超过 1 MiB 的文件。
- 请求体为 `{"path":"account.info"}`，也可填写该文件的绝对路径。同名文件按导入规则更新。
- 身份由产品 profile、UID 和租户共同确定；另一文件已持有同一身份时返回 409。同 UID 的不同产品或租户可以共存。删除接口使用文件名，启停接口使用身份 ID，二者不要混用。

## 模型与调度

以 WebUI 和 `GET /v1/models` 为客户端选择依据。目录按账号/租户、地域、产品与客户端版本缓存到 `auth/model-catalog.json`，默认有效期 6 小时；新凭据触发同步，失败只保留同一账号的可信旧缓存。旧未隔离的目录不能授权其他账号。

标准模型字段之外，`credits` 是各来源最低倍率：`0.0` 表示该来源零倍率，`null` 表示未声明可解析倍率。`credits_by_profile` 提供来源明细，例如 `{"intl-work":0.0,"cn-cli":0.03}`；兼容客户端可忽略这些扩展字段，倍率不保证永久不变。

凭据 domain / token issuer 决定产品身份，聊天与刷新使用各自固定入口及独立产品头：

| Profile | 聊天 / 刷新入口 |
|---------|-----------------|
| `cn-cli` | `https://copilot.tencent.com` |
| `cn-work` | `https://www.workbuddy.cn` |
| `intl-cli` | `https://www.codebuddy.ai` |
| `intl-work` | `https://www.workbuddy.ai` |

- 默认仅为账号选择自身可信目录支持的模型；目录和余额不跨账号借用。具体零倍率模型优先，其次按积分过期时间、冷却与会话黏绑调度。
- 零余额账号退出付费模型轮询，仍可使用自身目录明确声明的具体零倍率模型；余额恢复后重新加入。国际付费模型须有已知正余额，具体零倍率模型可以例外。
- `auto` 是账号默认模型的调度别名，不代表任意模型。国际账号须有正余额且目录声明 `default-model`；国内 WorkBuddy 须声明 `auto`，国内 CLI 须有已知非空可用目录。`auto` 不享受具体零倍率模型的余额豁免。
- WebUI 的地域、产品和凭证绑定严格限制候选账号，不会回退到未选账号。模型禁用后直接请求同样拒绝；改名默认不保留原 ID，只有选择保留时才同时提供旧 ID。
- 已发送请求不会因账号不可用或 HTTP 错误换账号重放；后续请求才重新选路。目录同步或凭证未就绪通常返回带 `Retry-After` 的 503，不支持或禁用的模型返回 404。

## 请求处理边界

- 三个生成协议统一将 `developer` 归一为 `system`，已有 system 移到首位，缺失时补默认值；归一化不修改调用方 payload。Responses 上下文投影和可选脱敏另行处理内容，不能据此理解为整个链路逐字透传。
- 图片计入全部历史和工具结果，重复图片逐次计数，按消息与内容块数组顺序判断新旧。默认保留最新 16 张，只移除超额图片并保留文本和消息结构；图片清空的内容用文本占位。
- `--image-policy error` 在本地返回 `413 / too_many_images`。处理后仍超过字节上限则返回 `413 / request_too_large`，不为满足预算继续截断文本。
- 图片数量合规不保证单图大小或模型视觉能力满足上游要求。URL/base64 图片可转换，Responses 图片 `file_id` 不支持。
- 显式设置 `stream`：Chat 默认非流式，Responses / Messages 默认流式。Responses 流式以及带工具的 Chat / Messages 流式先聚合校验，再输出 SSE，并非所有路径都实时逐 token 转发。
- 兼容文本日志和 SQLite 审计使用独立预算；日志仅记录有界、脱敏预览，不是完整原始请求。日志、凭证导出和备份仍须按私有数据保管。

## 故障与重试

| 现象 | 处理与边界 |
|------|------------|
| WebUI 无法登录 | 确认设置了 API key；更换 key 后重新登录并重新发起未完成的 OAuth |
| 本地 401 | 客户端密钥与网关不一致 |
| 上游 401 / 403 | 凭证级认证熔断；在 WebUI 检查并重新登录 |
| 429 | 对该凭证的上游模型冷却，后续请求可重新绑定；当前请求不换账号重放。全部候选都在冷却时仍返回 429 |
| 建连失败 | 仅 `ConnectError` / `ConnectTimeout` 退避重试一次 |
| 发送后断连、读写超时、HTTP 错误 | 不做网络重放，避免重复计费；日志记录异常类型与耗时 |
| 工具参数损坏 | 聚合校验失败最多额外生成 3 次，可能消耗更多额度；耗尽后返回错误 |
| 上游空流或残流 | 没有有效输出、缺少结束标记或包含错误的流不伪装为成功 |
| 内容审核拒绝 | 脱敏 + `--no-compact` 下，仅完整非流式纯拒绝且模板确实缩短时，最多同账号兜底一次；流式不做审核重试，也不因此熔断或切号 |
| 响应慢 | 在 WebUI 查看耗时与失败尝试，再选择当前账号支持的更快模型 |
| 同账号多处登录相互失效 | 桌面端与网关独立刷新可能互相顶掉；优先独立扫码登录或停止另一端使用 |
