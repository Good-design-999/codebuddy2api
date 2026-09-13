# WebUI guide

[Home](../README.md) · [简体中文](webui.zh-CN.md)

## Open the console

Start the gateway using the [deployment guide](deployment.md), then open `http://127.0.0.1:8787/dashboard` and sign in with the current API key. Source installs need a frontend build; Docker builds include it. Use HTTPS unless connecting locally.

Management is locked without a key. After changing it, sign in again and restart any unfinished OAuth login.

## Common tasks

- **Overview:** view requests, usage and credential health. Official account balances may include usage from other clients.
- **Credentials:** select the domestic or international site for browser login, or import `.info`/ZIP files. Distinguish manual disabling, credential-level authentication circuits and model-level 429 cooldowns. Disabling keeps files; deletion removes them and requires removing model bindings first. Exports contain plaintext credentials; do not share them.
- **Models:** enable models, set public IDs, regions/products and specific accounts. Unavailable bindings never fall back to unselected accounts. Clients use the IDs published here.
- **Logs:** filter requests and inspect failed attempts. Clearing details keeps historical statistics.
- **Settings:** edit unlocked options; hot changes apply immediately, while restart-marked settings require a manual restart. Change locked options in the startup configuration; see [configuration precedence](advanced.md).
  - “Keep tool descriptions” is off by default and works across all three protocols, independently of prompt compaction; see [tool metadata retention](advanced.md#tool-metadata-retention) for configuration and limits.

Clearing **all logs and statistics** is irreversible. Enter the confirmation text shown in the dialog and re-enter the current API key. This does not delete credentials or gateway settings.

## Data and backups

Data defaults to `auth/`, or `/data/auth` inside Docker. Local installs can set `CODEBUDDY_AUTH_DIR`; Compose uses `CODEBUDDY2API_AUTH_PATH` for the host directory.

| File | Contents |
|------|----------|
| `*.info` | Official plaintext credentials; never migrated into SQLite |
| `control.sqlite3` | Gateway settings, model rules and credential metadata |
| `logs.sqlite3` | Request details and independent aggregate statistics |

Auditing defaults to 30-day detail retention and a 256 MiB logical detail budget, **not a hard limit on database or directory disk usage**. Detail cleanup and eviction preserve aggregates. SQLite failure diagnostics have a separate budget, defaulting to 8192 bytes. Existing text logs are retained, not backfilled as precise statistics.

Mount the whole data directory on writable local storage, not just a single database file, and do not share it between gateway instances.

Stop the gateway before copying the entire directory, including databases, any WAL/SHM files, credentials and catalog/credit state files; do not back up only `.info` files. Keep this private data secure.

See [client configuration](clients.md) for API keys and URLs.
