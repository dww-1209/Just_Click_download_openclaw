# 产品需求文档：OpenClaw 一键安装启动器 - V1.1

## 1. 综述 (Overview)

### 1.1 项目背景与核心问题

OpenClaw 的官方使用方式依赖命令行下载与配置。对于熟悉终端的用户，这种方式可接受；但对于不熟悉命令行的普通用户，它带来了明显的使用门槛：

- 不知道该输入什么命令
- 不清楚安装过程中的每一步含义
- 容易因为路径、权限、网络、配置参数出错而中断
- 安装完成后仍需手动配置模型和 API Key，无法直接进入可用状态

本产品的目标，是提供一个桌面端图形化程序，把 OpenClaw 的"下载、安装、默认配置、模型配置、启动 WebChat"封装成一个傻瓜式流程。用户只需要按提示操作，尽量不接触命令行，就能完成安装和使用。

本产品的核心原则是：

- 面向小白用户
- 图形化引导
- 默认配置优先
- 不暴露复杂命令
- 命令行仅在后台静默执行
- 安装完成后直接进入 WebChat

### 1.2 产品定位

本产品是一个跨平台桌面安装启动器，不是 OpenClaw 本身的替代品。它的职责是：

- 调用操作系统能力
- 静默执行 openclaw 命令行工具完成安装与配置
- 提供图形化模型配置界面（多选模型、API Key 管理）
- 启动 WebChat 入口

### 1.3 目标用户

- 想使用 OpenClaw，但不会使用命令行的普通用户
- 希望快速体验 OpenClaw 的新手用户
- 希望减少安装成本和学习成本的用户

### 1.4 核心业务流程 / 用户旅程地图

**安装器流程（主程序）：**

1. **启动与欢迎阶段（US-01）** — 展示产品简介，用户点击"下一步"进入流程
2. **环境检测阶段（US-02）** — 自动检查操作系统、磁盘空间、权限、浏览器支持、OpenClaw 安装状态
3. **下载与安装阶段（US-04）** — 后台静默安装 Node.js 22 + pnpm，从 Gitee 克隆源码并本地构建
4. **加载默认配置阶段（US-05）** — 自动执行 onboard，写入默认配置
5. **Provider 模型配置阶段（US-05b）** — 用户选择 AI 模型提供商、填写 API Key、多选模型、设置默认模型
6. **启动服务与 WebChat 阶段（US-06）** — 启动 Gateway 服务，自动打开浏览器访问 WebChat

**独立卸载工具：**

- 检测 OpenClaw 安装状态 → 确认卸载 → 执行卸载（停止服务、删除目录、清理命令）→ 显示结果

### 1.5 全局数据契约表

| 名称 | 类型 | 说明 | 来源故事 | 备注 |
|---|---|---|---|---|
| `stage` | enum | 当前安装阶段 | 全局 | `welcome / env_check / installing / configuring / provider_config / startup / error` |
| `installStatus` | enum | 安装任务状态 | 全局 | `idle / running / success / failed / cancelled` |
| `checkStatus` | enum | 环境检测状态 | US-02 | `ok / warning / failed` |
| `osType` | enum | 操作系统类型 | US-02 / US-04 | `windows / macos / linux` |
| `serviceHost` | string | Web 服务地址主机 | US-06 | 默认 `localhost` |
| `servicePort` | number | Web 服务端口 | US-06 | 默认 `1606` |
| `webchatUrl` | string | WebChat 访问地址 | US-06 | 由服务启动结果生成 |
| `logLines` | array[string] | 安装与配置日志 | US-04 / US-05 / US-06 | 仅用于界面展示与排障 |
| `providersConfig` | dict | Provider 配置 | US-05b | `{vendor_id:key_type: {api_key, selected_models, ...}}` |
| `globalDefaultModel` | string | 全局默认模型 | US-05b | 如 `deepseek/deepseek-chat` |
| `fallbackModels` | array[string] | 备用模型列表 | US-05b | 排除默认模型后的已选模型 |

### 1.6 程序清单

本项目最终产出两个独立的桌面程序：

| 程序 | 入口文件 | 功能 | 目标用户 |
|---|---|---|---|
| **OpenClaw 安装器** | `main.py` | 环境检测、安装、配置、启动 | 首次安装用户 |
| **OpenClaw 卸载工具** | `uninstall_main.py` | 检测、卸载、清理 | 需要移除 OpenClaw 的用户 |

两个程序通过 `build.py` 统一打包，macOS 平台为每个程序生成对应的 `.command` 辅助启动脚本以绕过 Gatekeeper。

---

## 2. 用户故事详述 (User Stories)

---

## US-01：作为首次用户，我希望打开安装程序后看到一个清晰的欢迎页面，并通过点击"下一步"开始安装流程。

### 价值陈述

- 作为：首次使用 OpenClaw 的普通用户
- 我希望：打开程序后看到一个简单清晰的欢迎页
- 以便于：我不需要理解命令行就可以开始安装

### 业务规则与逻辑

1. 前置条件
   - 用户已下载并双击启动本安装程序
   - 程序可在 Windows、macOS、Linux 上运行

2. 操作流程 (Happy Path)
   1. 用户启动程序
   2. 系统展示欢迎页面
   3. 页面展示产品名称和简介
   4. 用户点击"下一步"
   5. 系统进入环境检测阶段（US-02）

3. 异常处理
   - 程序启动失败：提示"程序无法启动，请重新下载或检查系统兼容性"
   - 权限不足：提示"建议以管理员身份运行"

### 验收标准

- 场景1：正常进入欢迎页
  - GIVEN 用户双击启动程序
  - WHEN 程序成功加载
  - THEN 显示欢迎页、产品简介、下一步按钮和退出按钮

- 场景2：点击下一步
  - GIVEN 用户处于欢迎页
  - WHEN 用户点击"下一步"
  - THEN 系统进入环境检测阶段

- 场景3：点击退出
  - GIVEN 用户处于欢迎页
  - WHEN 用户点击"退出"
  - THEN 程序关闭

### 技术实现概要

- 影响范围：`ui/welcome_page.py`
- 前端：QLabel 展示产品名称和简介，QPushButton 提供"下一步"和"退出"
- 后端：本阶段无远程后端

### 页面布局

```
+------------------------------------------------------+
|              OpenClaw One-Click Installer            |
|                                                      |
|              [ LOGO / 产品名称区域 ]                 |
|                                                      |
|        欢迎使用 OpenClaw（小龙虾）一键安装           |
|                                                      |
|   本程序将帮助您自动完成 OpenClaw 的下载与配置       |
|   无需命令行操作，只需点击"下一步"即可开始          |
|                                                      |
|                              [ 退出 ]   [ 下一步 ]   |
+------------------------------------------------------+
```

---

## US-02：作为用户，我希望系统自动检测我的设备环境，并在必要时提示问题。

### 价值陈述

- 作为：普通用户
- 我希望：程序自动检查我的环境状态
- 以便于：提前发现问题，避免安装失败

### 业务规则与逻辑

1. 前置条件
   - 用户已从 US-01 点击"下一步"

2. 检测内容
   - **操作系统类型** — 识别 Windows / macOS / Linux
   - **磁盘空间** — 检查剩余空间是否足够（> 5GB）
   - **权限状态** — 检查当前用户是否有管理员/写入权限
   - **浏览器支持** — 检测 Chrome / Edge / Brave 等 Chromium 系浏览器（提示项，不影响安装流程）
   - **OpenClaw 安装状态** — 检测是否已存在 OpenClaw 安装

3. 网络检测说明
   - **US-02 阶段不检测网络**，网络问题由 US-04 下载阶段自行处理

4. OpenClaw 已安装分支
   - 若检测到 OpenClaw 已安装，页面显示操作选项：
     - **快速启动** — 跳过配置，直接启动 Gateway 并打开 WebChat
     - **重新配置并启动** — 进入 US-05 加载默认配置
     - **配置模型** — 直接进入 Provider Config 页面（US-05b）
     - **手动配置** — 打开终端让用户手动执行 `openclaw config`
     - **重新下载** — 清理旧安装后重新执行 US-04

5. 异常处理
   - 磁盘空间不足：阻止继续，提示释放空间
   - 权限不足：显示警告但不阻断（后续安装阶段再次验证）

### 验收标准

- 场景1：环境检测通过且未安装 OpenClaw
  - GIVEN 用户进入环境检测页
  - WHEN 系统完成检测
  - THEN 显示通过状态，"下一步"按钮可用，进入 US-04

- 场景2：检测到 OpenClaw 已安装
  - GIVEN 用户进入环境检测页且 OpenClaw 已安装
  - WHEN 系统完成检测
  - THEN 显示"已安装"状态，提供快速启动/重新配置/配置模型/手动配置/重新下载选项

- 场景3：磁盘不足
  - GIVEN 磁盘空间不足
  - WHEN 系统完成检测
  - THEN 页面提示空间不足并阻止继续

### 技术实现概要

- 影响范围：`ui/env_check_page.py`、`infra/system_checker.py`、`models/env_check.py`
- 前端：展示检测进度和每项结果，控制"下一步"按钮状态
- 后端：通过本地系统 API 读取系统信息

### 页面布局

```
+------------------------------------------------------+
|                  环境检测                            |
+------------------------------------------------------+
|   正在检测您的系统环境，请稍候...                    |
|                                                      |
|   操作系统:        [OK] Windows / macOS / Linux      |
|   磁盘空间:        [OK] 可用 120 GB                  |
|   权限状态:        [OK] 正常                         |
|   浏览器支持:      [!] 未检测到 Chrome/Edge         |
|   OpenClaw 安装:   [OK] 已安装                       |
|                                                      |
|   +-----------------------------------------------+  |
|   |  检测到 OpenClaw 已安装                        |  |
|   |  [快速启动] [重新配置并启动] [配置模型]        |  |
|   |  [手动配置] [重新下载]                         |  |
|   +-----------------------------------------------+  |
|                                                      |
|                              [ 返回 ]   [ 下一步 ]   |
+------------------------------------------------------+
```

---

## US-04：作为用户，我希望程序在后台静默完成 OpenClaw 的下载与安装，并展示安装状态。

### 价值陈述

- 作为：不熟悉命令行的用户
- 我希望：程序在后台帮我完成安装
- 以便于：我看不到命令行窗口，也不需要手动输入命令

### 业务规则与逻辑

1. 前置条件
   - 已完成 US-01、US-02
   - 环境检测通过或用户选择"重新下载"

2. 安装方式
   - **不使用 npm install -g**，而是采用**本地构建**方式：
     1. 检查/安装 Node.js 22
     2. 安装 pnpm
     3. 从 Gitee 克隆 `openclaw-cn` 到 `~/openclaw-cn`
     4. `pnpm install` 安装依赖
     5. `pnpm ui:build` 构建前端
     6. `pnpm build` 构建核心
     7. `pnpm openclaw onboard` 初始化
     8. 创建命令包装器（`openclaw` / `openclaw-cn`）
   - 安装路径固定为 `~/openclaw-cn`，**不支持用户自定义路径**

3. 关键约束
   - 不弹出可见命令行窗口
   - 实时捕获输出并更新界面进度
   - 支持取消操作

4. 异常处理
   - 下载失败：提示网络问题并提供重试
   - 构建失败：展示简化错误信息和日志
   - 用户取消：安全终止流程

### 验收标准

- 场景1：正常安装
  - GIVEN 用户进入安装阶段
  - WHEN 程序执行安装
  - THEN 后台静默执行，UI 显示实时进度和日志
  - AND 成功后自动进入 US-05

- 场景2：网络中断
  - GIVEN 安装过程中网络不可用
  - WHEN 下载失败
  - THEN 页面提示网络错误并提供重试

- 场景3：用户取消
  - GIVEN 安装正在进行
  - WHEN 用户点击"取消"
  - THEN 提示确认并安全终止流程

### 技术实现概要

- 影响范围：`ui/installing_page.py`、`infra/installer.py`
- 前端：进度条、状态文本、日志区域
- 后端：QThread 后台执行安装命令，Signal 反馈进度

### 页面布局

```
+------------------------------------------------------+
|                  安装 OpenClaw                       |
+------------------------------------------------------+
|   状态: 正在安装依赖...                              |
|                                                      |
|   进度:  [##############------------]  45%           |
|                                                      |
|   当前任务: pnpm install                             |
|                                                      |
|   日志:                                              |
|   ----------------------------------------------     |
|   > 正在安装系统依赖 (Node.js 22, pnpm)...           |
|   > 正在从 Gitee 下载 openclaw-cn...                 |
|   > pnpm install 中...                               |
|   ----------------------------------------------     |
|                                                      |
|                              [ 返回 ]   [ 取消 ]     |
+------------------------------------------------------+
```

---

## US-05：作为用户，我希望安装完成后系统自动加载默认配置。

### 价值陈述

- 作为：刚安装完成的用户
- 我希望：程序自动执行 onboard 并写入默认配置
- 以便于：我不需要手动执行命令行配置

### 业务规则与逻辑

1. 前置条件
   - US-04 成功完成
   - OpenClaw 已安装成功

2. 配置内容
   - 执行 `openclaw onboard --non-interactive ...` 初始化
   - 写入默认环境变量和基础配置
   - 不要求用户填写任何配置项

3. 操作流程
   1. 安装完成后自动进入配置阶段
   2. 程序执行 onboard 和默认配置
   3. 成功后进入 Provider Config 阶段（US-05b）

### 验收标准

- 场景1：正常配置
  - GIVEN OpenClaw 安装完成
  - WHEN 系统进入配置阶段
  - THEN 自动执行 onboard 和默认配置
  - AND 成功后进入 Provider Config

- 场景2：配置失败
  - GIVEN 配置执行失败
  - WHEN 程序捕获错误
  - THEN 显示错误提示并允许重试

### 技术实现概要

- 影响范围：`ui/us05_config_page.py`、`core/openclaw_manager.py`
- 前端：进度条、日志区域、重试/下一步按钮
- 后端：QThread 执行 `configure_only()`

---

## US-05b：作为用户，我希望在安装完成后通过图形界面配置 AI 模型提供商和 API Key。

### 价值陈述

- 作为：安装完成后的用户
- 我希望：通过图形界面选择模型、填写 API Key
- 以便于：不需要手动编辑 JSON 配置文件

### 业务规则与逻辑

1. 前置条件
   - US-05 默认配置完成
   - 或从 US-02 直接点击"配置模型"进入

2. 支持的 Provider
   - Kimi (Moonshot) — 标准 API / Coding API
   - DeepSeek
   - MiniMax
   - Volcano Engine (豆包) — 标准 API / Coding Plan
   - OpenRouter
   - Z.AI (智谱 GLM) — 通用 API / Coding Plan
   - Xiaomi (MiMo)
   - 阿里云百炼 — DashScope API / Coding Plan

3. 功能特性
   - **Key Type 切换** — 同一供应商支持多种 API Key 类型（如标准 API vs Coding Plan）
   - **多选模型** — 每个 Key Type 下可多选预设模型，支持添加自定义模型
   - **API Key 输入** — 密码框输入，按供应商分别存储
   - **已选模型汇总** — 底部汇总所有已选模型
   - **全局默认模型** — 从已选模型中选择默认模型，其余自动作为 fallback
   - **配置导入/导出** — 支持将配置保存为 JSON 文件，或从 JSON 文件恢复
   - **防呆提示** — 页面顶部显示提示标语，提醒用户不要混用不同 Key Type

4. 配置存储
   - API Key 通过 `openclaw config set env.XXX_API_KEY` 写入 `~/.openclaw/openclaw.json`
   - 默认模型和 fallback 模型写入 `agents.defaults.model`
   - onboard 配置写入 provider baseUrl

5. 操作流程
   1. 用户展开供应商卡片
   2. 选择 Key Type（如有多个）
   3. 输入 API Key
   4. 勾选需要的模型（可多选）
   5. 可选：添加自定义模型
   6. 在汇总区选择全局默认模型
   7. 点击"保存并启动" → 写入配置 → 进入 US-06
   8. 或点击"跳过" → 直接进入 US-06（使用 onboard 默认配置）

### 验收标准

- 场景1：正常配置并启动
  - GIVEN 用户进入 Provider Config 页面
  - WHEN 用户填写 API Key、选择模型、点击"保存并启动"
  - THEN 配置写入成功，进入启动阶段

- 场景2：跳过配置
  - GIVEN 用户进入 Provider Config 页面
  - WHEN 用户点击"跳过"
  - THEN 直接进入启动阶段，使用 onboard 默认配置

- 场景3：配置导入
  - GIVEN 用户有之前导出的配置文件
  - WHEN 用户点击"导入配置"并选择文件
  - THEN 自动回填所有供应商的 API Key 和已选模型

### 技术实现概要

- 影响范围：`ui/provider_config_page.py`、`models/provider_config.py`、`core/openclaw_manager.py`
- 前端：可展开的供应商卡片（VendorRow）、模型多选 CheckBox、自定义模型输入、汇总下拉框
- 后端：`read_existing_provider_config()` 读取已有配置，`configure_providers()` 写入配置

### 页面布局

```
+------------------------------------------------------+
|              配置 AI 模型提供商                      |
|                                                      |
|  点击供应商展开配置，填写 API Key 后多选模型          |
|                                                      |
|  +-----------------------------------------------+   |
|  |  请确认您的 API Key 类型...                    |   |
|  +-----------------------------------------------+   |
|                                                      |
|  > Kimi (Moonshot)                                 |
|  > DeepSeek                                        |
|  > MiniMax                                         |
|  > Volcano Engine (豆包)                           |
|  > ...                                             |
|                                                      |
|  +-----------------------------------------------+   |
|  |  已选模型汇总                                  |   |
|  |  Kimi: Kimi K2.5, Kimi K2 Thinking             |   |
|  |  全局默认模型: [Kimi - Kimi K2.5]              |   |
|  |  其余已选模型将自动作为 fallback 备用          |   |
|  +-----------------------------------------------+   |
|                                                      |
|  [返回] [导入配置] [导出配置] [跳过] [保存并启动]   |
+------------------------------------------------------+
```

---

## US-06：作为用户，我希望配置完成后程序自动启动服务并打开 WebChat。

### 价值陈述

- 作为：配置完成后的用户
- 我希望：程序自动启动 Gateway 并打开浏览器
- 以便于：我无需手动执行命令就能使用 OpenClaw

### 业务规则与逻辑

1. 前置条件
   - US-05b 完成（或跳过）
   - 配置已写入 `~/.openclaw/openclaw.json`

2. 启动流程
   1. 启动 OpenClaw Gateway 服务
   2. 执行健康检查
   3. 获取 WebUI URL
   4. 自动打开系统默认浏览器访问 WebChat
   5. 若浏览器无法自动打开，提供可复制的访问地址

3. 服务状态监控
   - 启动过程中显示进度和日志
   - 服务启动成功后显示"正在打开浏览器..."
   - 若浏览器未自动打开，显示手动访问地址和"打开浏览器"按钮

### 验收标准

- 场景1：正常启动
  - GIVEN 配置完成
  - WHEN 程序启动 Gateway
  - THEN 服务启动成功，自动打开浏览器访问 WebChat

- 场景2：浏览器未自动打开
  - GIVEN 服务启动成功
  - WHEN 浏览器未自动打开
  - THEN 显示 WebChat 访问地址，提供"打开浏览器"按钮

- 场景3：启动失败
  - GIVEN Gateway 启动失败
  - WHEN 程序捕获错误
  - THEN 显示失败原因和日志，允许重试

### 技术实现概要

- 影响范围：`ui/us06_startup_page.py`、`core/openclaw_manager.py`
- 前端：进度显示、日志区域、URL 输入框、打开浏览器按钮
- 后端：`_start_gateway()`、`_health_check()`、`_open_browser()`

### 页面布局

```
+------------------------------------------------------+
|              启动 OpenClaw 服务                      |
+------------------------------------------------------+
|   正在启动 Gateway 服务...                           |
|                                                      |
|   进度:  [####################------]  70%           |
|                                                      |
|   日志:                                              |
|   ----------------------------------------------     |
|   > Gateway started on port 1606                   |
|   > WebUI available at http://localhost:1606       |
|   ----------------------------------------------     |
|                                                      |
|   服务已启动！                                       |
|   访问地址: http://localhost:1606?token=xxx          |
|                                                      |
|                    [ 打开浏览器 ]                     |
|                              [ 返回 ]   [ 完成 ]     |
+------------------------------------------------------+
```

---

## 3. 独立卸载工具

### 3.1 产品定位

独立的桌面程序，用于完全移除 OpenClaw 及其相关配置。与安装器分离，避免主程序界面臃肿。

### 3.2 卸载流程

1. **检测阶段** — 检测 `~/openclaw-cn` 和 `~/.openclaw` 是否存在
   - 已安装：显示安装信息，提供"确认卸载"按钮
   - 未安装：提示"无需卸载"，仅提供"退出"按钮

2. **确认阶段** — 弹窗确认（卸载将永久删除程序、配置和 API Key）

3. **执行阶段** — 后台执行卸载：
   - 停止 Gateway 服务
   - 删除 `~/openclaw-cn`（程序文件）
   - 删除 `~/.openclaw`（配置文件，含 API Key）
   - 卸载 npm 全局包 `openclaw` / `openclaw-cn`
   - 删除命令包装器（`~/.local/bin/openclaw` 或 `~\AppData\Roaming\npm\openclaw.cmd`）

4. **完成阶段** — 显示卸载结果清单，提供"重新检测"和"退出"

### 3.3 技术实现

- 入口：`uninstall_main.py`
- UI 页面：`ui/uninstall_welcome_page.py`、`ui/uninstall_progress_page.py`、`ui/uninstall_done_page.py`
- 卸载逻辑：`core/openclaw_manager.uninstall()`

---

## 4. 打包与分发

### 4.1 构建系统

- 构建脚本：`build.py`
- 打包工具：PyInstaller
- 一次构建同时产出两个程序：安装器 + 卸载工具

### 4.2 macOS 特殊处理

- 两个 `.app` 均生成对应的 `.command` 辅助启动脚本
- 脚本自动移除 Gatekeeper 隔离属性（`xattr -rd com.apple.quarantine`）
- 用户首次运行时先双击 `.command` 文件即可绕过"无法打开"提示

### 4.3 输出文件

```
dist/
├── OpenClaw安装器.app
├── OpenClaw卸载工具.app
├── 双击运行-OpenClaw安装器.command
└── 双击运行-OpenClaw卸载工具.command
```

---

## 5. 项目结构

```
├── main.py                    # 安装器入口
├── uninstall_main.py          # 卸载工具入口
├── build.py                   # 打包脚本（双程序）
├── core/
│   └── openclaw_manager.py    # OpenClaw 服务管理器
├── infra/
│   ├── installer.py           # 安装逻辑
│   └── system_checker.py      # 系统环境检测
├── models/
│   ├── env_check.py           # 环境检测数据模型
│   ├── install.py             # 安装状态数据模型
│   ├── config.py              # 配置状态数据模型
│   └── provider_config.py     # Provider 数据定义
├── services/
│   ├── env_check_service.py   # 环境检测服务
│   └── install_service.py     # 安装服务
├── ui/
│   ├── welcome_page.py        # US-01 欢迎页
│   ├── env_check_page.py      # US-02 环境检测页
│   ├── installing_page.py     # US-04 安装页
│   ├── us05_config_page.py    # US-05 默认配置页
│   ├── provider_config_page.py # US-05b 模型配置页
│   ├── us06_startup_page.py   # US-06 启动页
│   ├── uninstall_welcome_page.py   # 卸载-检测页
│   ├── uninstall_progress_page.py  # 卸载-进度页
│   └── uninstall_done_page.py      # 卸载-完成页
└── .gitignore
```

---

## 6. 已废弃功能

以下功能在 PRD V1.0 中规划但实际未实现：

| 功能 | 废弃原因 |
|---|---|
| US-03 安装路径选择 | OpenClaw 官方安装方式固定到用户目录（`~/openclaw-cn`），无需也不支持自定义路径 |
| US-02 网络检测 | 网络检测移至 US-04 下载阶段自行处理，US-02 仅检测本地环境 |
| 安装器内嵌卸载按钮 | 卸载功能已独立为单独程序，避免主程序界面臃肿 |

---

## 7. 总结

本 PRD 覆盖的完整流程：

**安装器：**
1. US-01 启动与欢迎
2. US-02 环境检测（含浏览器检测、OpenClaw 已安装分支）
3. US-04 下载与安装（pnpm 本地构建）
4. US-05 加载默认配置（onboard）
5. US-05b Provider 模型配置（多供应商、多选模型、API Key）
6. US-06 启动服务与 WebChat

**卸载工具：**
- 检测 → 确认 → 执行卸载 → 完成清单

**打包：**
- `build.py` 一次构建产出安装器 + 卸载工具 + macOS `.command` 辅助脚本
