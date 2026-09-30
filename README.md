简体中文 | [English](README.en.md)

# Remember-Me

**Remember-Me — originally created by Ting (peanutsuee)**

Remember-Me 是一个独立的图像记忆、存储、检索和管理项目。最初概念、产品设计和独立项目由 Ting（peanutsuee）发起。

官方仓库：https://github.com/peanutsuee/Remember-Me

Stage 7E 要求 Python 3.10 或更高版本，因为稳定版官方 MCP Python SDK v1 要求 Python 3.10+。

## Stage 7H-A 状态

当前包版本为 `0.1.0`。隐私安全的图像 Core（privacy-safe image core）、Standalone HTTP Host、原始本地 Dashboard 以及公开的 Standalone MCP server 已实现，可用于本地开发。0.x 是早期公开版本，不承诺长期 API 稳定。

- Dashboard 可在本地预览（Dashboard is available for local preview），并可执行真实资产操作，地址为 `/dashboard`。
- PNG/JPEG 上传、清理、浏览、搜索、筛选、元数据编辑、清理后图像预览和安全删除，均已通过 `/api/v1` 接入。
- Dashboard 采用独立的 Dusk Archive 设计，不复制或复用 Ombre-Brain Dashboard。
- Dashboard 尚未集成到 Ombre Brain。
- MCP 地址为 `/mcp`（MCP address is `/mcp`），使用 Streamable HTTP。
- MCP、HTTP API 和 Dashboard 共享同一个 Core runtime、repository、content store 和 SQLite 数据库。
- MCP server 恰好公开九个 `rm_asset_*` 工具，不提供诊断工具。
- Core 支持 Pillow 10.4 至 12.x。当前 Ombre-Brain 兼容性所接受的 Pillow 12 目标版本是 Pillow 12.3.0。
- Stage 7F 的固定 fixture 在 Pillow 10.4.0、11.3.0 和 12.3.0 下产生了完全相同的清理后字节。但未来 Pillow 版本或其他输入仍可能导致编码器输出变化，因此生产环境应固定使用已测试的确切 Pillow 版本。
- Claude 一键保存附件尚未实现（Claude one-click attachment saving has not been implemented）。
- 这仍是早期开发版本，目前 `not deployable as a complete production product`，也尚未部署。

Remember-Me 是唯一的长期图像核心来源。Ombre Brain 未来可以通过轻量插件或适配器使用它，而不是维护一份复制的 Core。当前设计是单用户，不承诺多租户行为。两个独立进程不得写入同一个 SQLite 数据库。

## 本地 Dashboard 预览

无需部署或注册账号。

Windows PowerShell：

在 Remember-Me 仓库根目录中运行：

```powershell
py -m venv .venv

.\.venv\Scripts\python.exe -m pip install -e ".[standalone,test]"

.\.venv\Scripts\python.exe -m remember_me serve `
  --data-root ".\.dashboard-preview"
```

打开：

```text
http://127.0.0.1:8787/dashboard
```

使用 `Ctrl+C` 停止 Host。

`.dashboard-preview` 是本地测试数据。它不会连接 Ombre Brain、Render 或生产数据，预览完成后可以删除。默认回环模式不需要 Token。不要让两个进程写入同一个数据目录。

macOS 或 Linux：

在 Remember-Me 仓库根目录中运行：

```sh
python3 -m venv .venv
./.venv/bin/python -m pip install -e ".[standalone,test]"
./.venv/bin/python -m remember_me serve \
  --data-root "./.dashboard-preview"
```

然后打开 `http://127.0.0.1:8787/dashboard`，并使用 `Ctrl+C` 停止。

请参阅 `docs/dashboard.md`、`docs/design-system.md`、`docs/standalone-host.md`、`docs/http-api.md`、`docs/mcp.md`、`docs/mcp-tools.md` 和 `docs/security.md`。

## 本地 MCP

同一个 `remember-me serve` 进程会在以下地址提供 MCP：

```text
http://127.0.0.1:8787/mcp
```

正式工具名称为：

- `rm_asset_upload_link`
- `rm_asset_upload_status`
- `rm_asset_get`
- `rm_asset_update_metadata`
- `rm_asset_reindex_embeddings`
- `rm_asset_search`
- `rm_asset_download_link`
- `rm_asset_view`
- `rm_asset_inspect`

配置 Standalone Bearer Token 后，MCP 客户端必须在 `Authorization` Header 中发送它。Token 绝不会在 URL 或 Cookie 中接受。签名上传和下载 URL 使用独立的短期 Ticket 凭据。

`REMEMBER_ME_PUBLIC_BASE_URL` 控制签名 URL 使用的绝对 base。它必须是不带凭据、query 或 fragment 的绝对 URL。非回环网络使用需要 HTTPS。回环模式下如果省略该变量，Remember-Me 使用 `http://127.0.0.1:<port>`。Host 绝不会根据不可信的 Host 或 forwarded headers 推导签名 URL。

## Dashboard 安全

Dashboard 页面和静态文件可以公开加载，但资产 API 仍保留现有的 Bearer 认证策略。在 Token 模式下，用户会在当前标签页中解锁 archive。Token 只存储在 `sessionStorage` 中，绝不会存储在 localStorage、Cookie、URL 或页面内容中。

图像通过 Authorization Header 获取，转换为 Blob Object URL，以受限并发数延迟加载，并在不再需要时撤销。用户元数据使用安全的 DOM 文本 API 渲染，而不是可执行 HTML。

Dashboard 使用限制严格的 CSP，不使用外部字体或脚本、第三方请求、通配符 CORS、analytics 或 telemetry。Standalone Host 不提供 TLS（does not provide TLS），也不是部署包。任何非回环绑定仍要求 `REMEMBER_ME_ALLOW_NETWORK=true` 和有效的 Bearer Token。

## 本地 Python Core

```python
from remember_me import create_local_service

service = create_local_service("./remember-me-data")
```

调用方负责进程生命周期、访问控制和备份策略。

## 版本维度

- Python package：`0.1.0`
- HTTP API：`v1alpha1`，路由位于 `/api/v1` 下
- Dashboard：`v1alpha1`
- MCP API：`v1alpha1`，位于 `/mcp` 的 Streamable HTTP
- 数据兼容性：`ombre-brain-assets-v1`

这些版本独立演进。HTTP API、Dashboard 和 MCP API 都是开发阶段契约，不承诺长期稳定性。

`0.1.0` 计划仅通过 GitHub Release 的 `v0.1.0` 发布，不上传 PyPI。供后续
OB 固定的是自行构建并验证的 `remember_me-0.1.0.tar.gz`，不是 GitHub
自动生成的源码包。

Pillow 版本范围不会改变 `ombre-brain-assets-v1`、sanitizer 行为、hash 算法、content-addressed paths 或 public API contracts。升级固定的生产 Pillow 版本前，请重新验证图像输出。

## 可信的单资产导入

`RememberMeCore.import_asset()` 是供可信 Host 导入一个可信、已经清理过的旧版 PNG 或 JPEG 的同步 public boundary。Core 仍会验证图像结构和元数据。Import 会保留有效的 32 字符小写十六进制 asset ID、资产时间戳、元数据以及每个 tag 的创建时间。
它接受清理后的字节，绝不接受 filesystem path、CAS key、Ticket、URL、embedding、vector 或 model identity。Remember-Me 根据实际存储的 SHA-256 和 MIME type 推导 CAS path。

`stored_sha256` 会根据提供的清理后字节重新计算，并且必须完全匹配。`source_sha256` 是原始上传字节的历史 provenance，而原始字节可能已经不存在；Import 会验证其小写 SHA-256 格式并保留它，但不会声称从清理后字节重新计算了它。兼容的 `decoded_bytes` 字段同样记录原始接收字节长度，因此会做范围验证，但无法从清理后字节重建。

Import 会验证现有 PNG/JPEG 字节流，但不会重新编码。`dry_run=True` 会执行验证、blob integrity checks 和 conflict checks，但不会创建文件或数据库行。完全相同的记录重复导入时会幂等跳过。同一个 asset ID 的持久字段发生变化，或同一个 stored SHA 归属于另一个 ID，都会形成稳定冲突。Import 不会创建 embeddings、Tickets、links、aliases、migrations 或 batch jobs。它拒绝 `kind=file`；Stage 7H-A 只支持 PNG 和 JPEG 图像。Import 不会启用 runtime、迁移生产环境或执行 Reindex。Embeddings 不会被迁移，之后必须通过明确授权的 Reindex 重新构建。Host 必须调用公开的 Core contract，不得依赖内部 storage 或 repository modules。

## 公开上传规则

公开上传接口不接受 `expected_sha256`（does not accept `expected_sha256`）。服务器会在收到字节后计算权威 hash。客户端和模型不得猜测或提供 hash。公开响应和 Dashboard 不会暴露 source hashes、stored hashes、blob keys、data roots 或 filesystem paths。

## Claude 网络设置

Claude 聊天附件不会自动注入标准 MCP tool calls。一键保存需要 code-execution environment 将原始字节发送到 `rm_asset_upload_link` 返回的短期 URL，并且需要启用 `Allow network egress`。

在 `Additional allowed domains` 中，只输入你自己的 Remember-Me deployment 的 hostname：

- 只输入 hostname；
- 不要包含 `https://`；
- 不要包含 path；
- 不要包含 Token；
- 不要包含 signed URL；
- 保持 restricted-domain mode 启用；
- 不要启用 `All domains`。

通过 Dashboard 手动上传不需要 Claude network access（Manual uploads through the Dashboard do not require Claude network access）。只使用你自己的 Remember-Me Host 的精确 hostname。不要启用 `All domains`。Stage 7E 提供 signed transfer URLs，但不会部署 Host，也不会自动获取当前聊天的附件字节。

## 来源与许可

独立编写的 Remember-Me 代码和文档，按照每个文件及 `LICENSE` 中的标示，采用 Common Public Attribution License Version 1.0（`CPAL-1.0`）许可。

Stage 7B 的六个核心模块通过有记录的 clean-room 工程流程，依据冻结的行为规范、公开契约、净化测试和数据兼容性要求独立重新实现。

该工程流程及其相似度审查本身并不确定版权归属、法律上的独立性或许可证义务。

仓库同时为仍受覆盖的内容和历史分发保留必要的上游 MIT notice，包括：

`Copyright (c) 2026 P0lar1zzZ`

Stage 7D Dashboard 和 Stage 7E MCP adapter 是原创的 CPAL 实现。没有阅读或复制 Ombre-Brain 的 Dashboard HTML、CSS、JavaScript、layout、visual system、authentication、Cookie、CSRF、MCP、transfer、Viewer 或 tool-registration code。请参阅 `NOTICE`、`LICENSES/MIT-Ombre-Brain.txt` 和 `docs/source-provenance.md`。

## Unicode metadata 与语义检索

`0.1.0` 保留安全清洗后的 metadata spelling，storage/display
不主动 NFC/NFKC；比较、tag identity、搜索和过滤单独使用 NFKC canonical key。
不修改 schema、blob/hash identity，不迁移或恢复历史 spelling。
Import 保留 spelling 和 timestamps，但拒绝 canonical tag collision；旧版本的
import/search 不保证兼容新 spelling。详见 [数据兼容说明](docs/data-compatibility.md)。

注入向量 provider 时，Core 的纯语义命中默认要求余弦分数 `>= 0.42`。
关键词命中不受此门槛影响；低分结果不会附带 `semantic` reason 或
`semantic_score`。可在 `create_local_runtime(..., semantic_min_score=0.42)`
或 `create_local_service(...)` 中覆盖，数值须为有限的 `[0, 1]`；显式 `0`
保留原先仅接受正分的行为。无匹配正常返回 `total=0, results=[]`。
默认 `NullVectorProvider` 仍只执行关键词搜索。

Reindex 在验证新向量并确认资产及 provider 状态未变化后原子替换旧向量。
生成失败或取消时保留旧记录；无文本或明确禁用时仍按现有规则同步清理。
批次逐资产处理，重跑已完成目标会跳过。详见
[公开 Core 契约](docs/public-api-contract.md)。
