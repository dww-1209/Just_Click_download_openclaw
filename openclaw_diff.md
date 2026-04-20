# OpenClaw 官方版 vs 中国社区版 源码差异分析

> 分析日期: 2026-04-20
> 官方版: `openclaw-2026.4.15`
> 中国社区版: `openclaw-cn-v2026.2.23-cn`

---

## 一、总体定位与架构

| 维度 | 官方版 | 中国社区版 |
|------|--------|-----------|
| 技术栈 | TypeScript/Node.js Monorepo | TypeScript/Node.js Monorepo |
| 包管理 | pnpm workspace | pnpm workspace |
| 前端框架 | Vite + 原生 TS (非 React/Vue) | Vite + 原生 TS (非 React/Vue) |
| 移动端 | Android(Kotlin) / iOS(Swift) / macOS(Swift) | Android(Kotlin) / iOS(Swift) / macOS(Swift) |
| 插件数量 | 106 个扩展 | 37 个扩展 |
| 目标用户 | **全球开发者，企业级功能** | **中国开发者，本土生态集成** |

**核心结论**: 中国社区版是官方版的一个**功能精简 + 中国特色增强**的分支。社区版删除了大量面向海外用户的高级功能和企业级安全特性，同时增加了国内主流模型（豆包、火山、Kimi、通义千问等）、浏览器自动化、WhatsApp Web 集成等特性。

---

## 二、package.json / 项目配置差异

### 2.1 基本信息

| 字段 | 官方版 (2026.4.15) | 中国社区版 (2026.2.23-cn) |
|------|-------------------|-------------------------|
| name | `openclaw` | `openclaw` |
| version | `2026.4.15` | `2026.2.23-cn` |
| description | Multi-channel AI gateway... | 更懂中文环境的 Local Agent 实战社区版 |
| author | *(空)* | OpenClaw CN Community |
| homepage | github.com/openclaw/openclaw | https://open-claw.org.cn |
| repository | GitHub | gitee.com/OpenClaw-CN/openclaw-cn |
| engines.node | `>=22.14.0` | `>=22.12.0` |
| packageManager | `pnpm@10.32.1` | `pnpm@10.23.0` |

### 2.2 依赖差异

**官方版新增/升级的依赖：**
- `@anthropic-ai/vertex-sdk`, `@aws-sdk/credential-provider-node` — AWS/GCP 相关
- `@google/genai` ^1.49.0 — Google GenAI
- `@lancedb/lancedb`, `matrix-js-sdk`, `nostr-tools` — 官方版新增
- `@modelcontextprotocol/sdk` 1.29.0 — **MCP SDK（官方版特有）**
- `jimp`, `music-metadata` — 媒体处理
- `proxy-agent`, `silk-wasm`, `uuid` — 网络/媒体工具

**中国社区版保留但官方版不同的：**
- `@discordjs/voice` ^0.19.0, `@line/bot-sdk` ^10.6.0
- 多个核心依赖版本较旧（如 `@agentclientprotocol/sdk` 0.14.1 vs 0.18.2）

### 2.3 Scripts 差异

**官方版独有：**
- 大量 Android/iOS 构建和发布脚本
- `build:docker`, `build:ci-artifacts`
- `canon:*`, `check:*`, `deadcode:*`, `lint:*`
- `qa:*`, `release:*`, `test:*` 测试矩阵大幅扩展
- `plugin-sdk:*` 相关脚本

**中国社区版修改：**
- `build` 使用 `tsdown` 直接调用
- `gateway:dev` 增加 `CLAWDBOT_SKIP_CHANNELS=1`
- `tui:dev` 增加 `CLAWDBOT_PROFILE=dev`
- `test` 使用 `test-parallel.mjs`

### 2.4 pnpm-workspace.yaml

- 官方版有 `minimumReleaseAge: 2880` 和 `ignoredBuiltDependencies`
- 社区版将部分配置移入 `package.json` 的 `pnpm` 字段

### 2.5 .env.example

**几乎完全一致**，仅 `OPENCLAW_GATEWAY_TOKEN` 默认值不同（官方版为空，社区版给了示例值）。

---

## 三、Extensions 插件差异

### 3.1 数量对比

| 维度 | 官方版 | 中国社区版 |
|------|--------|-----------|
| 插件总数 | **106** | **37** |
| AI/LLM 提供商 | ~60+ | **0** |
| 通道插件 | 25 | 25 |
| 搜索/工具 | ~10 | 0 |
| 图像/视频/语音 | ~8 | 0 |

### 3.2 官方版特有而中国社区版没有的插件（72 个）

主要是：
- **LLM / AI 提供商**: openai, anthropic, google, deepseek, groq, mistral, moonshot, ollama, qwen, together, xai, nvidia, vllm, sglang, volcengine 等约 40+ 个
- **搜索 / 浏览**: brave, browser, duckduckgo, searxng, tavily, exa, firecrawl
- **图像/视频/语音生成**: image-generation-core, video-generation-core, speech-core, fal, runway, elevenlabs, deepgram
- **开发/代码工具**: codex, github-copilot, kilocode, kimi-coding, opencode, diffs
- **记忆/存储扩展**: active-memory, memory-wiki

### 3.3 中国社区版特有而官方版没有的插件（3 个）

| 插件名 | 功能 |
|--------|------|
| `google-gemini-cli-auth` | Google Gemini CLI OAuth 认证 |
| `minimax-portal-auth` | MiniMax Portal OAuth 认证 |
| `qwen-portal-auth` | 通义千问 Portal OAuth 认证 |

### 3.4 共有插件的差异

共有 34 个插件（几乎全是通讯通道插件）：

| 插件 | 官方版文件数 | 社区版文件数 | 说明 |
|------|-------------|-------------|------|
| discord | 334 | 8 | 社区版极度精简 |
| telegram | 268 | 6 | 社区版极度精简 |
| slack | 221 | 6 | 社区版极度精简 |
| feishu | 178 | 56 | 社区版保留核心，去掉企业级功能 |
| zalo | 61 | 21 | 社区版精简 |
| zalouser | 69 | 20 | 社区版精简 |

**结论**: 社区版对通道插件做了大幅精简，仅保留核心 channel/runtime 实现。

---

## 四、src/ 核心源码差异

### 4.1 src/agents/ - Agent 核心

| 维度 | 官方版 | 中国社区版 |
|------|--------|-----------|
| 文件总数 | ~795 | ~417 |
| 模型发现 | `pi-model-discovery-runtime.ts` + `model-suppression.runtime.ts` | 简化为 `pi-model-discovery.ts` |
| 模型配置 | 多个文件 + 大量 provider 测试 | 合并为更简单的 `models-config.ts` |
| CLI Runner | 完整 `cli-runner/` 目录 | 简化为 `cli-runner.ts` |

**中国社区版新增的中国特色模型支持：**
- `byteplus-models.ts` — BytePlus ARK（Seed、Kimi、GLM）
- `doubao-models.ts` — 火山引擎 Doubao
- `volc-models.shared.ts` — 火山引擎共享模型
- `opencode-zen-models.ts` — OpenCode Zen
- `together-models.ts` — Together AI
- `synthetic-models.ts` — Synthetic
- `huggingface-models.ts` — Hugging Face
- `cloudflare-ai-gateway.ts` — Cloudflare AI Gateway

**中国社区版删减的国际版特性：**
- Anthropic 专用模块（`anthropic-payload-policy.ts`, `anthropic-transport-stream.ts` 等）
- OpenAI WS 实时语音模块（`openai-ws-*.ts`）
- Google/Gemini 专用传输流
- 大量 Subagent Registry 持久化和 E2E 测试

### 4.2 src/web/ - Web 服务

| 维度 | 官方版 | 中国社区版 |
|------|--------|-----------|
| 文件数 | **1 个** | **41 个** |
| 功能 | Web 搜索/抓取 Provider 共享配置 | **WhatsApp Web (Baileys) 完整集成** |

中国社区版实现了完整的 WhatsApp Web 集成：
- `session.ts` — WA Socket 管理
- `login.ts` / `login-qr.ts` — QR 码登录
- `accounts.ts` — 多账号管理
- `inbound.ts` / `outbound.ts` — 消息收发
- `auto-reply.ts` — 自动回复引擎
- `monitor-inbox.*.ts` — 收件箱监控
- `media.ts` / `qr-image.ts` — 媒体处理

### 4.3 src/gateway/ - 网关

| 维度 | 官方版 | 中国社区版 |
|------|--------|-----------|
| 文件总数 | ~380 | ~183 |

**关键差异：**
- 官方版有完整 MCP HTTP 支持（`mcp-http.*`），社区版**完全移除**
- 官方版有 Tailscale 暴露、CanvasHostServer、共享网关会话生成
- 社区版有浏览器控制服务器（`server-browser.ts`）、心跳运行器、远程 Skills 缓存、启动时更新检查
- 社区版认证模块大幅精简

### 4.4 CLI 入口

**`openclaw.mjs`：**
- 官方版：~180 行，含 Node 版本检查、编译缓存、预计算帮助文本、详细错误提示
- 社区版：~56 行，无版本检查，无预计算帮助优化

**`src/cli/program.ts`：** 两者几乎完全一致

### 4.5 src/memory/ - 记忆系统

| 维度 | 官方版 | 中国社区版 |
|------|--------|-----------|
| 文件数 | 69 | 84 |
| 位置 | `extensions/memory-core/src/memory/` | `src/memory/`（核心化） |

**关键差异：**
- 社区版将记忆系统从扩展移入核心
- 社区版新增批量处理（`batch-gemini.ts`, `batch-openai.ts`, `batch-voyage.ts`）
- 社区版新增多厂商嵌入模型（`embeddings-gemini.ts`, `embeddings-mistral.ts`, `embeddings-openai.ts`, `embeddings-voyage.ts`）
- 官方版有大量细粒度 manager 状态文件，社区版已移除/合并

### 4.6 src/sessions/ - 会话管理

| 维度 | 官方版 | 中国社区版 |
|------|--------|-----------|
| 文件数 | 18 | 8 |

- 社区版大幅精简，移除了会话生命周期事件和 ID 解析等子模块
- 移除了 `session-id.ts`, `session-chat-type.ts`, `session-lifecycle-events.ts` 等

### 4.7 src/infra/ - 基础设施

| 维度 | 官方版 | 中国社区版 |
|------|--------|-----------|
| 文件数 | 631 | 298 |

**主要移除（社区版）：**
- 审批系统：`approval-handler-*`, `approval-native-*`, `approval-request-*` 等
- 执行安全：`exec-approval-forwarder.runtime.ts`, `exec-inline-eval.ts` 等
- 归档/备份：`archive-helpers.ts`, `backup-create.ts` 等
- 网络/发现：`bonjour-discovery.ts`, `network-discovery-display.ts` 等
- 安装/更新：`install-flow.ts`, `update-check.ts`, `update-runner.ts` 等
- 出站消息系统（outbound/）：大量 delivery、envelope、format、identity 文件
- Provider 用量统计：大量 `provider-usage.*` 文件

### 4.8 src/config/ - 配置系统

| 维度 | 官方版 | 中国社区版 |
|------|--------|-----------|
| 文件数 | 314 | 191 |

- 社区版移除了大量 Zod schema 文件和测试
- 社区版将 `legacy.ts` 拆分为 `legacy.migrations.part-1/2/3.ts`
- 社区版新增 `merge-config.ts`, `runtime-group-policy-provider.ts`
- 社区版新增 Telegram/Slack 相关配置：`telegram-custom-commands.ts`, `slack-http-config.test.ts`

### 4.9 src/cron/ - 定时任务

| 维度 | 官方版 | 中国社区版 |
|------|--------|-----------|
| 文件数 | 150 | 71 |

- 社区版移除了大量 `isolated-agent.*` 测试和运行时文件
- 社区版移除了大量 `service.*` 测试文件
- 社区版 `CronService` 移除 `enqueueRun()` 方法

### 4.10 src/secrets/ - 密钥管理

| 维度 | 官方版 | 中国社区版 |
|------|--------|-----------|
| 文件数 | 108 | **0（完全移除）** |

- **社区版完全移除了 `src/secrets/` 目录**，这是架构上最剧烈的变化之一
- 官方版提供完整的密钥运行时系统（`prepareSecretsRuntimeSnapshot`, `activateSecretsRuntimeSnapshot` 等）

### 4.11 src/server/ - HTTP/WebSocket 服务器

| 维度 | 官方版 | 中国社区版 |
|------|--------|-----------|
| 文件数 | 37 | 20 |

- 社区版移除了 `http-auth.ts`, `readiness.ts`, `preauth-connection-budget.ts`
- 社区版 `ws-connection.ts` 简化（304 行 vs 405 行），移除预授权预算机制

### 4.12 src/auto-reply/ - 自动回复

| 维度 | 官方版 | 中国社区版 |
|------|--------|-----------|
| 文件数 | 463 | 228 |

- 社区版移除大量命令子模块（`commands-acp/`, `commands-btw`, `commands-compact` 等）
- 社区版移除 ACP 调度模块（`dispatch-acp.*`）
- 社区版移除 Fast Path 相关函数
- 社区版 `get-reply.ts` 新增 `applyLinkUnderstanding`, `applyMediaUnderstanding`

---

## 五、中国社区版特有模块

### 5.1 src/wizard/ — 安装/配置向导

- 官方版使用 `setup.*` 命名
- 社区版使用 `onboarding.*` 命名
- 社区版增加了**风险确认**（`requireRiskAcknowledgement`）和 **i18n 支持**
- 社区版安全提示更详细（"OpenClaw is a hobby project and still in beta"）

### 5.2 src/providers/ — Provider 认证与模型（中国社区版独有）

| 文件 | 功能 |
|------|------|
| `github-copilot-auth.ts` | GitHub Copilot 设备流 OAuth |
| `github-copilot-models.ts` | Copilot 可用模型列表 |
| `kilocode-shared.ts` | **Kilocode** 聚合平台（Claude Opus 4.6、GLM-5、Kimi K2.5、GPT-5.2、Gemini 3 等） |
| `qwen-portal-oauth.ts` | **通义千问** Portal OAuth 刷新 Token |
| `google-shared.*.ts` | Google Provider 共享工具（function call 顺序修复） |

### 5.3 src/browser/ — 浏览器自动化（中国社区版独有，101 个文件）

基于 **Playwright + Chrome DevTools Protocol (CDP)** 的完整浏览器控制服务器：

| 子模块 | 功能 |
|--------|------|
| `chrome.ts` | 启动 Chrome 实例 |
| `cdp.ts` | Chrome DevTools Protocol 通信 |
| `pw-ai.ts` | Playwright AI 辅助操作 |
| `pw-tools-core.*.ts` | 点击、输入、截图、下载、滚动等 |
| `extension-relay.ts` | Chrome 扩展与 OpenClaw 通信桥梁 |
| `server.ts` | Express HTTP 服务器，浏览器控制 REST API |

**核心功能**: 允许 Agent 通过 HTTP API 远程控制 Chrome 浏览器。

### 5.4 其他中国社区版特有/内嵌模块

- `src/line/` — Line 集成
- `src/imessage/` — iMessage 集成
- `src/whatsapp/` — WhatsApp 集成（非 web/ 下的 Baileys）
- `src/signal/` — Signal 集成
- `src/slack/` — Slack 集成（内嵌到 src/ 而非仅 extensions）
- `src/discord/` — Discord 集成（内嵌到 src/ 而非仅 extensions）
- `src/telegram/` — Telegram 集成（内嵌到 src/ 而非仅 extensions）
- `src/terminal/` — 终端模拟 (PTY)
- `src/tts/` — 文本转语音
- `src/tui/` — 终端 UI
- `src/media/` — 媒体处理
- `src/media-understanding/` — 媒体理解
- `src/link-understanding/` — 链接理解
- `src/markdown/` — Markdown 处理
- `src/logging/` — 日志系统
- `src/pairing/` — 设备配对
- `src/process/` — 进程管理
- `src/routing/` — 消息路由
- `src/security/` — 安全策略
- `src/hooks/` — 生命周期钩子
- `src/compat/` — 兼容性层
- `src/daemon/` — 守护进程
- `src/node-host/` — Node 宿主环境
- `src/shared/` — 共享工具
- `src/types/` — 类型定义

> 注：部分模块在官方版中也有对应实现，但命名或位置不同（如官方版的 `src/channels/` 对应社区版分散的 IM 模块）。

---

## 六、ui/ 前端差异

### 6.1 文件规模

| 维度 | 官方版 | 中国社区版 |
|------|--------|-----------|
| 总文件数 | ~280 | ~160 |

### 6.2 功能模块差异

**官方版有而中国社区版没有的功能：**
- Dreams / Dreaming 系统
- Command Palette (`Cmd/Ctrl + K`)
- ModelAuth 模型认证状态
- Wiki Import / Memory Palace
- 完整的 Usage 统计（时间序列、日志、高级图表）
- Palette、Overview Attention、Overview Cards 等视图
- 模型覆盖/目录（`chatModelOverrides`, `chatModelCatalog`）

**中国社区版新增：**
- `ui/data/moonshot-kimi-k2.ts` — 内置 Moonshot Kimi K2 模型配置

### 6.3 i18n 国际化

| 维度 | 官方版 | 中国社区版 |
|------|--------|-----------|
| 支持语言 | **13 种**（en, de, es, fr, id, ja-JP, ko, pl, pt-BR, tr, uk, zh-CN, zh-TW） | **4 种**（en, pt-BR, zh-CN, zh-TW） |
| i18n 架构 | `registry.ts` + 懒加载 + 机器翻译目录 | 硬编码在 `translate.ts` 中 |
| 默认语言 | 跟随浏览器 | 中文优先（`zh` 直接映射到 `zh-CN`） |

### 6.4 主题系统

- 官方版：多主题切换（`claw` 等）+ `themeMode` + `themeOrder`
- 社区版：仅 `themeMode`（`system`/`light`/`dark`），简化主题系统

---

## 七、移动端 apps/ 差异

### 7.1 文件数量

| 平台 | 官方版 | 中国社区版 |
|------|--------|-----------|
| Android | 187 文件 | 108 文件 |
| iOS | 199 文件 | 143 文件 |
| macOS | 371 文件 | 323 文件 |
| shared | 121 文件 | 93 文件 |

### 7.2 Android 核心差异

- **包名变更**：官方版 `ai.openclaw.app` → 社区版 `ai.openclaw.android`
- 社区版新增 `applyImmersiveMode()`（沉浸式全屏）
- 社区版新增 WebView 调试支持
- 社区版新增更多权限预申请（NEARBY_WIFI_DEVICES, POST_NOTIFICATIONS）
- 官方版延迟初始化 `NodeForegroundService`，社区版 `onCreate` 直接启动

### 7.3 iOS 核心差异

- 官方版有完整 `ExecApprovalNotificationBridge`（执行审批通知），社区版**缺失**
- 官方版 APNs 静默推送支持 `ExecApproval`，社区版仅支持 `WatchPrompt`
- 官方版 `GatewayConnectionController` 支持 `bootstrapToken`，社区版**缺失**
- 官方版 WatchPrompt 支持最多 4 个动态动作，社区版仅支持 2 个

### 7.4 macOS 核心差异

- 官方版新增 `LossyDecodable<T>` 容错解码（允许部分损坏 JSON 被跳过）
- 官方版 `Skills` 安装支持 `dangerouslyForceUnsafeInstall` 参数
- 社区版显式标记 `Sendable`，更符合 Swift 6 并发要求

---

## 八、部署配置差异

### 8.1 Dockerfile

| 维度 | 官方版 | 中国社区版 |
|------|--------|-----------|
| 构建阶段 | **多阶段构建**（ext-deps → build → runtime-assets → runtime） | **单阶段构建** |
| Node 版本 | `node:24-bookworm` | `node:22-bookworm` |
| 构建脚本 | `pnpm build:docker` + `pnpm ui:build` + `pnpm qa:lab:build` | `pnpm build` + `pnpm ui:build` |
| 运行时优化 | `pnpm prune --prod`、删除 `.d.ts` / `.map` | 无 |
| 健康检查 | `HEALTHCHECK` 内建 | **无** |
| 安全加固 | read-only rootfs 准备、GPG 指纹校验 | 基础实现 |

### 8.2 docker-compose.yml

- 官方版有 `healthcheck` 配置
- 官方版有 `cap_drop: [NET_RAW, NET_ADMIN]` 和 `security_opt: [no-new-privileges:true]`
- 社区版 CLI 未指定 `network_mode: "service:openclaw-gateway"`

### 8.3 PaaS 部署配置

- **fly.toml**：两个版本**完全一致**
- **render.yaml**：社区版额外增加 `SETUP_PASSWORD` 和 `PORT` 环境变量

### 8.4 K8s 部署（官方版特有）

中国社区版**完全没有** `scripts/k8s/` 目录。官方版包含：
- `deployment.yaml` — 含 initContainer、liveness/readiness Probe、securityContext
- `service.yaml` — ClusterIP Service
- `configmap.yaml` — 默认配置
- `pvc.yaml` — 10Gi 持久化存储
- `kustomization.yaml` — Kustomize 资源列表

### 8.5 Dockerfile.sandbox 系列

- 官方版使用 BuildKit `--mount=type=cache` 构建缓存
- 社区版使用基础 `RUN apt-get`

---

## 九、测试覆盖差异

### 9.1 测试文件数量

| 指标 | 官方版 | 中国社区版 |
|------|--------|-----------|
| `.test.ts` 总数 | **4,241** | **1,565** |
| 测试覆盖率 | 极高 | 大幅精简 |

### 9.2 test/ 目录差异

- 官方版有 `fixtures/`, `helpers/`, `mocks/`, `scripts/` 等完整测试基础设施
- 社区版仅保留基础 setup、e2e、UI 测试

### 9.3 Vitest 配置

- **官方版**：50+ 个 project 子配置，按模块精细拆分
- **社区版**：仅 5 个简单派生配置（e2e, unit, extensions, gateway, live）

---

## 十、文档/docs 差异

### 10.1 语言支持

- **官方版**：完整英文文档，多语言导航（.i18n），无 README_EN.md
- **中国社区版**：
  - 根目录有 **`README_EN.md`**（英文版 README）
  - `docs/ja-JP/` 下有完整日文文档
  - `docs/zh-CN/` 下有 **大量中文文档**（数百个 md 文件）

### 10.2 目录差异

- 官方版独有：`.generated/`, `snippets/`
- 社区版独有：`design/`, `experiments/`, `ja-JP/`, `zh-CN/`

---

## 十一、scripts/ 脚本差异

### 11.1 文件数量

| 维度 | 官方版 | 中国社区版 |
|------|--------|-----------|
| 顶层文件数 | ~170 个 | ~60 个 |

### 11.2 关键差异

**官方版独有：**
- `build-all.mjs`, `build-stamp.mjs`, `tsdown-build.mjs`
- `openclaw-npm-publish.sh`, `plugin-clawhub-publish.sh`
- 大量 iOS 发布脚本
- 约 30 个架构检查脚本（`check-architecture-smells.mjs`, `check-extension-*.mjs` 等）
- `test-planner/` 目录
- `k8s/` 目录

**中国社区版特有：**
- `install-cn.ps1`, `install-cn.sh` — 中国安装脚本

---

## 十二、skills/ 技能模板差异

### 12.1 数量

| 版本 | 技能数量 |
|------|---------|
| 官方版 | 46 个 |
| 中国社区版 | 45 个 |

### 12.2 差异明细

| 技能 | 官方版 | 中国社区版 | 说明 |
|------|--------|-----------|------|
| `node-connect` | ✅ | ❌ | 节点连接技能 |
| `taskflow` | ✅ | ❌ | 任务流技能 |
| `taskflow-inbox-triage` | ✅ | ❌ | 收件箱分类任务流 |
| `nano-banana-pro` | ❌ | ✅ | 中国版新增（含 `generate_image.py`） |
| `openai-image-gen` | ❌ | ✅ | 中国版新增（含 `gen.py`、`test_gen.py`） |
| 其余 43 个技能 | ✅ | ✅ | 完全一致 |

---

## 十三、总体差异总结表

| 维度 | 官方版 (2026.4.15) | 中国社区版 (2026.2.23-cn) |
|------|-------------------|--------------------------|
| **代码规模** | 极大（~10,000+ 文件） | 中等（~3,500+ 文件） |
| **测试覆盖** | 4,241 个测试文件，50+ vitest 配置 | 1,565 个测试文件，5 个 vitest 配置 |
| **LLM 提供商** | 60+ 个（全球主流） | 0 个扩展，依赖内嵌 provider（火山、豆包、Kimi、Kilocode、Qwen 等） |
| **通讯通道** | 25 个（完整源码） | 25 个（精简版） |
| **浏览器自动化** | ❌ 无 | ✅ Playwright + CDP 完整实现（101 文件） |
| **WhatsApp Web** | ❌ 无 | ✅ Baileys 完整集成（41 文件） |
| **MCP 协议** | ✅ 完整支持 | ❌ 完全移除 |
| **密钥管理** | ✅ `src/secrets/`（108 文件） | ❌ 完全移除 |
| **审批系统** | ✅ 完整（ExecApproval、Native Approval） | ❌ 大量移除 |
| **iOS 安全特性** | ✅ ExecApproval、Bootstrap Token、TLS Pinning | ❌ 缺失 |
| **Docker/K8s** | ✅ 多阶段构建、健康检查、K8s 清单 | ❌ 单阶段构建、无健康检查、无 K8s |
| **PaaS 部署** | ✅ fly.toml + render.yaml | ✅ fly.toml + render.yaml（更简化的 render.yaml） |
| **i18n** | 13 种语言 | 4 种语言（中文优先） |
| **文档** | 英文为主 | 中英双语 + 日文 + 大量中文文档 |
| **安装向导** | `setup.*` | `onboarding.*`（增加风险确认和 i18n） |
| **主题系统** | 多主题切换 | 仅 light/dark/system |
| **技能模板** | 46 个（含 taskflow） | 45 个（新增 image-gen 技能） |
| **目标用户** | 全球开发者，企业级 | 中国开发者，开箱即用 |

---

## 十四、核心差异原因分析

1. **精简策略**：社区版删除了大量测试、边缘功能、企业级安全特性，以减小包体积和复杂度
2. **本土化**：增加国内主流模型（火山、豆包、Kimi、通义千问）、浏览器自动化（国内网站兼容）、WhatsApp Web（海外华人常用）
3. **易用性优先**：增加安装向导、中文文档、简化配置、预置模型参数
4. **安全取舍**：移除了审批系统、密钥管理、TLS Pinning 等，可能是为了简化部署，但也降低了安全性
5. **维护策略**：社区版依赖版本较旧，测试覆盖大幅减少，可能维护成本更低但稳定性风险更高

---

## 十五、面向国内用户的社区版优势总结（⭐重要）

> 本章节面向非技术用户/小白用户，用大白话总结中国社区版的核心优势。

### 15.1 浏览器自动化 —— AI 替你"玩"浏览器

**这到底是啥？**

AI 有一双看不见的手，能帮你操作 Chrome 浏览器。你平时上网要做的操作——打开网页、点按钮、填表单、往下翻、截图保存——这些 AI 全都能自动帮你做。你不需要动手，只需要跟 AI 说一句话，它就会自己去浏览器里完成任务。

**它能做什么？**

| AI 能做的事 | 对应你平时的操作 | 实际使用场景 |
|------------|----------------|-------------|
| 打开网页 | 你在地址栏输入网址按回车 | "帮我查一下今天北京的天气" |
| 点击按钮 | 你鼠标点"搜索""提交" | "帮我在淘宝搜索 iPhone 16" |
| 填写表单 | 你在输入框打字 | "帮我填一下这个快递单" |
| 滚动页面 | 你鼠标滚轮往下滑 | "把这个新闻页面往下翻，找到评论区" |
| 截图保存 | 你按 PrintScreen | "把当前页面截个图发给我" |
| 下载文件 | 你点"下载"按钮 | "把这个 PDF 下载到桌面" |
| 输入文字 | 你在搜索框打字 | "在百度搜索栏输入'OpenClaw'" |

**底层原理（简单版）**

OpenClaw 会在你的电脑里自动启动一个 Chrome 浏览器，通过 CDP（Chrome DevTools Protocol）技术像"远程遥控"一样控制它。AI 发出指令 → OpenClaw 翻译成浏览器操作 → 浏览器执行 → 把结果返回给 AI。

**你不需要安装任何额外的东西**，只要电脑里有 Chrome/Edge/Brave 浏览器就行，OpenClaw 会自动找到它们。

**一句话总结**

> **浏览器自动化 = AI 可以替你打开网页、点点按按、填表截图，就像你雇了一个会上网的助手。**

---

### 15.2 WhatsApp Web —— 让 AI 能"聊"微信的海外兄弟

**这到底是啥？**

**WhatsApp Web 不是 OpenClaw 的网页聊天界面。** OpenClaw 自己的网页聊天界面叫 WebChat UI（浏览器里看到的 "OpenClaw Control" 页面），两个版本都有。

中国社区版特有的 WhatsApp Web 是另一回事：**它让 AI 能够通过 WhatsApp（微信的海外兄弟，全球用户最多的即时通讯软件）和别人聊天。**

**通俗场景**

- 你开了一家跨境电商店，有外国客户通过 WhatsApp 问你问题
- 正常情况下你需要自己盯着手机回复
- **有了这个功能，AI 可以帮你自动回复 WhatsApp 消息**
- 客户问"这件衣服多少钱？" → AI 自动回复价格
- 客户问"什么时候发货？" → AI 自动回复物流信息

**需要下载 App 吗？**

**需要你手机上已有 WhatsApp App**（就像你手机上有微信一样），但不需要下载 OpenClaw 的 App。

**使用流程（通过命令行/终端执行）**

```
第 1 步：确认你手机上有 WhatsApp App
         ↓
第 2 步：在终端/命令行中输入以下命令：
         openclaw channels login --channel whatsapp
         ↓
         OpenClaw 在终端窗口显示一个 QR 二维码
         （可能是 ASCII 图形或 base64 图片）
         ↓
第 3 步：打开手机 WhatsApp
         设置 → 已关联的设备 → 关联新设备
         扫描终端中显示的 QR 码
         ↓
第 4 步：登录成功！
         AI 现在可以通过 WhatsApp 收发消息了
```

**重要澄清**

- OpenClaw **本体是命令行工具**，不是带按钮的 GUI 软件
- WebChat UI（浏览器里的聊天页面）里**并没有一个"点击连接 WhatsApp"的按钮**
- 连接 WhatsApp 需要通过**终端命令**触发，或在 WebChat 中让 AI 代为执行（如果 AI 有对应工具权限）

登录时 OpenClaw 在终端提示：
- `"Scan this QR in WhatsApp → Linked Devices."`（在 WhatsApp 的"已关联的设备"中扫描此二维码）

登录成功后终端显示：
- `"✅ Linked! WhatsApp is ready."`（已连接！WhatsApp 已就绪。）

**还支持多账号**

代码显示支持多个 WhatsApp 账号，每个账号有独立的登录凭据和自动回复策略。

**一句话总结**

> **WhatsApp 功能 = 让 AI 能登录你的 WhatsApp，帮你自动回复海外客户的消息。需要你手机上先有 WhatsApp App，然后在终端输入命令 `openclaw channels login --channel whatsapp`，扫描终端显示的 QR 码即可。**

---

### 15.3 社区版 vs 官方版：国内用户怎么选？

| 考量维度 | 官方版 | 中国社区版 | 国内用户影响 |
|---------|--------|-----------|-------------|
| **网络访问** | 依赖 GitHub、海外模型 API | 代码托管在 Gitee、预置国内模型 | 官方版在国内网络环境下很难顺畅使用 |
| **模型选择** | 60+ 提供商（OpenAI、Claude、Gemini 等） | 仅内置火山/豆包、Kimi、通义千问、Kilocode 等 | 国内用户本来就主要用国产模型，社区版预置好了 |
| **安装难度** | 需手动配置模型 API Key、阅读英文文档 | 有 `onboarding` 安装向导、中文文档、风险提示 | 社区版对小白友好得多 |
| **界面语言** | 13 种语言，默认英文 | 中文优先（4 种语言） | 社区版体验更自然 |
| **浏览器控制** | ❌ 无 | ✅ Playwright + CDP | 社区版能让 AI 帮你操作网页（查快递、填表单等） |
| **WhatsApp** | ❌ 无 | ✅ 完整集成 | 有跨境通讯需求的用户受益 |
| **MCP 工具生态** | ✅ 完整 | ❌ 无 | 高级用户/开发者会受限 |
| **企业级安全** | ✅ 审批系统、密钥管理、TLS Pinning | ❌ 大量移除 | 个人用户无感知，企业用户有风险 |
| **稳定性** | 4,200+ 测试，CI 完善 | 1,500+ 测试，精简很多 | 社区版潜在 Bug 更多，但核心功能可用 |
| **部署运维** | Docker 多阶段构建、K8s、健康检查 | 单阶段构建、无 K8s、无健康检查 | 个人用户单机运行无差别 |

**推荐结论**

**首选社区版的用户：**
- 完全不懂技术的**小白用户**（中文向导、中文文档）
- 主要使用**国内模型**（豆包、Kimi、通义千问）的用户
- 需要**浏览器自动化**（让 AI 帮你操作网页）的用户
- 有**WhatsApp 通讯**需求的用户
- 只想**单机快速运行**，不折腾配置的用户

**首选官方版的用户：**
- 需要**频繁切换多个海外模型**（Claude、GPT、Gemini 等）的用户
- 需要**MCP 工具生态**（接入数据库、Git、Slack 等标准化工具）的开发者
- 有**企业级安全要求**（执行审批、密钥管理、TLS Pinning）的用户
- 需要**K8s 生产部署**的团队
- **网络环境能稳定访问海外服务**的技术用户

### 最终建议

> 对于**绝大多数国内个人用户**，社区版是更现实的选择——不是因为功能更强，而是因为：
> 1. 在国内网络环境下**能跑起来**
> 2. 预置了**国内主流模型**，不用自己配置
> 3. 有**中文界面和文档**
> 4. 额外的浏览器自动化和 WhatsApp 集成有实用价值

> 中国社区版比官方版多了两个超实用的功能：一个是**浏览器自动化**——AI 能替你打开网页、查信息、填表截图；另一个是 **WhatsApp 集成**——AI 能帮你自动回复海外客户的消息。这两个功能官方版都没有。
