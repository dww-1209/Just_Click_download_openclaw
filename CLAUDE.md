# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目概述

OpenClaw 一键安装器：面向非技术用户的 PySide6 桌面 GUI，把"下载、安装、配置、启动 WebChat"封装成傻瓜式 6 步流程。打包产物为 Windows `.exe` / macOS `.app` 双程序（安装器 + 卸载器），同时支持在线和离线两种安装模式。

主要入口（**Composition Root**，唯一允许跨层导入的装配器）：
- `launch_installer.py` — 在线安装器
- `launch_installer_offline.py` — 离线安装器（仅替换 `installer_factory`）
- `launch_uninstaller.py` — 卸载器

## 常用命令

包管理使用 **uv**（Python 3.12，锁定 `<3.13`）：

```bash
uv sync                                                # 安装依赖

uv run python launch_installer.py                      # 运行在线安装器
uv run python launch_installer_offline.py              # 运行离线安装器
uv run python launch_uninstaller.py                    # 运行卸载器

uv run python build.py                                 # 打包安装器+卸载器到 dist/
uv run python build.py --offline --resources-dir resources/macos
uv run python build.py --clean-only                    # 只清理 build/ dist/ *.spec __pycache__
```

打包脚本（`build.py`）一次构建产出三个程序（在线安装器 + 离线安装器 + 卸载器），并按平台特殊处理：Windows 自动打包 `libssl/libcrypto` DLL 并禁用 UPX；macOS 设置 bundle id、生成 `双击运行-*.command` 辅助脚本（绕过 Gatekeeper）。

### 准备离线资源

`resources/{platform}/` 是离线版打包的输入。`prepare_offline_resources.py` 自动处理 Node.js 预编译包和 pnpm npm tarball，但 **macOS 离线版的 git tarball 需要手动准备**（全新 macOS 无 Xcode CLT 时避免弹窗）：

```bash
# 1. 基础资源（Node.js + pnpm tarball）
uv run python prepare_offline_resources.py --platform macos --skip-prebuilt

# 2. OpenClaw 预构建产物（需先通过在线安装器让 ~/openclaw-cn 完成 pnpm install && pnpm build）
uv run python prepare_offline_resources.py --platform macos --skip-nodejs --skip-pnpm

# 3. macOS git tarball（手动准备，从 Xcode CLT 复制）
# 确保本机已安装 Xcode Command Line Tools，然后：
mkdir -p /tmp/git-macos-arm64
cp -R /Library/Developer/CommandLineTools/usr/bin/git /tmp/git-macos-arm64/bin/
cp -R /Library/Developer/CommandLineTools/usr/libexec/git-core /tmp/git-macos-arm64/libexec/
# （如有其他必要目录如 lib/、share/ 也一并复制）
cd /tmp && tar czf git-macos-arm64.tar.gz git-macos-arm64/
mv git-macos-arm64.tar.gz resources/macos/
```

resources/ 目录结构：
```
resources/
├── pnpm-10.10.0.tgz          # 跨平台共用
├── macos/
│   ├── node-v22.14.0-darwin-arm64.tar.gz
│   ├── openclaw-prebuilt-macos.tar.gz
│   └── git-macos-arm64.tar.gz   # macOS 离线版独有
├── windows/
│   └── node-v22.14.0-win-x64.zip
└── linux/
    └── ...
```

### 测试

`pyproject.toml` 已包含 `pytest>=8.0.0`，但仓库当前没有提交任何测试用例（`tests/` 已从 git 移除，见 `27d1e9b`）。新增测试可用 `uv run pytest <path>` 运行。

## 架构（六层 + Composition Root）

依赖方向**严格自上而下**，违反此约束会破坏可替换性：

```
UI ──▶ Services ──▶ Contracts ──▶ Core ──▶ Adapters ──▶ Models
```

| 层 | 路径 | 职责 |
|---|---|---|
| UI | `src/ui/show_*.py`, `installer_window.py` | PySide6 页面，发 `Signal` 通过槽接收数据，**不接触具体类** |
| Services | `src/services/perform_*.py`, `configure_providers.py` | `QThread` Worker + 桥接 Service，把长耗时操作搬出主线程 |
| Contracts | `src/contracts/define_*.py` | `typing.Protocol`（面向调用者）+ `ABC`（面向实现者）双抽象 |
| Core | `src/core/manage_openclaw.py` | OpenClaw 生命周期管理（配置、启停、卸载） |
| Adapters | `src/adapters/install_*.py`, `run_shell.py` 等 | 系统交互、子进程、子平台差异 |
| Models | `src/models/constants.py`, `install.py` 等 | 纯数据：常量、枚举、`@dataclass`、用户友好错误消息 |

**Composition Root** 是唯一允许跨层导入的位置。`launch_installer.py` 在此处把 `SystemChecker / OpenClawInstaller / OpenClawManager / SystemLauncher` 注入到 `InstallerWindow`，离线版仅替换 `installer_factory=OfflineOpenClawInstaller`，其余完全复用。

### UI ↔ 后端通信

所有耗时操作（安装、检测、配置、启动）跑在 `QThread` 子类中，通过 `Signal` 把 `progress / log_line / complete` 反馈到 UI。Service 层负责 Worker 生命周期和信号中继。**绝不在 UI 槽函数里阻塞**。

### 错误分类系统

子进程失败统一通过 `ErrorCategory` 枚举分类（网络超时、DNS、SSL、权限、磁盘已满、杀毒拦截等）。UI 不展示原始 stderr，而是通过 `src/models/user_messages.py` 翻译成本地化中文描述 + 修复建议。新增错误类型时只改 `user_messages.py`，UI 自动适配。

### 关键常量

`src/models/constants.py` 集中所有可调参数：Node.js 版本、`DEFAULT_GATEWAY_PORT=18789`、Gitee 仓库 URL、各类镜像列表（npm/Node.js MSI/PKG/tarball）、超时阈值、健康检查参数。修改任何"魔法值"都应该改这里。平台判断函数 `is_windows() / is_macos() / is_linux()` 也在此模块——**项目内禁止混用 `platform.system()` 和 `sys.platform`**。

## 项目特有约定

### 1. 双仓库工作流（重要陷阱）

仓库根目录是 GitHub `dww-1209/Just_Click_download_openclaw`；`agentclaw/` 子目录是另一个独立 git 仓库，指向 Gitea `http://47.116.45.225/ai-team/agentclaw.git`，两者均出现在 `.gitignore` 中（`agentclaw/` 在 root 视角是被忽略的）。

**坑**：在 `agentclaw/` 内直接执行 `git status` / `git log`，git 仓库发现机制会找到父仓库的 `.git` 而非 `agentclaw/.git`，返回错误结果。**所有 agentclaw 相关 git 操作必须显式指定绝对路径**：

```bash
GIT_DIR=/Users/dww/Desktop/Just_Click_download_openclaw/agentclaw/.git \
GIT_WORK_TREE=/Users/dww/Desktop/Just_Click_download_openclaw/agentclaw \
git <command>
```

不要使用 `cd agentclaw && git status` 这类写法。

**部署流程**：开发完成后，将 `src/`、`launch_*.py`、`build.py`、`prepare_offline_resources.py`、`pyproject.toml` 等文件复制到 `agentclaw/installer/`（注意保持目录结构），然后在 agentclaw 仓库中提交并 push 到 Gitea。`agentclaw/` 目录本身在父仓库 `.gitignore` 中，不会被意外提交到 GitHub。

### 2. 注释要求（覆盖默认行为）

本项目代码**需要写中文注释**（覆盖 Claude Code 默认的"不写注释"建议）：
- 函数 / 类：写 docstring 或简短中文功能说明
- 复杂逻辑 / 条件分支：解释**为什么**这样写，而非做什么
- 平台特殊处理：标注 Windows / macOS / Linux 差异的原因
- 错误处理 / 重试逻辑：说明重试策略和兜底设计意图

不必每行都注释，但在非显而易见的约束、invariant、workaround 处必须注释。

### 3. 在线 vs 离线版本

- 在线版从 Gitee `https://gitee.com/OpenClaw-CN/openclaw-cn.git` 克隆源码，本地用 pnpm 构建（不依赖 `npm install -g`）。
- 离线版从打包进 exe 的 `resources/{platform}/` 解压预构建产物，无需网络。
- 两者只在 `installer_factory` 处不同（`OpenClawInstaller` vs `OfflineOpenClawInstaller`），UI / Services / Core 完全复用。

### 4. 安装目标路径

- 程序源码：`~/openclaw-cn`
- 配置（含 API Key）：`~/.openclaw`
- 命令包装器：Windows `%APPDATA%\npm\openclaw.cmd` / macOS&Linux `~/.local/bin/openclaw`
- Gateway 端口：`18789`（被占用时安装器会尝试释放）

### 5. macOS 离线版内部 git（避免 Xcode CLT 弹窗）

全新 macOS 上 `/usr/bin/git` 是一个 shim（约 100KB），调用时会触发"需要开发者命令行工具"弹窗。离线版通过以下方式绕过：
- 从 Xcode CLT 复制真正的 git 二进制 + `libexec/git-core/` 辅助程序，打包为 `resources/macos/git-macos-arm64.tar.gz`
- 安装时解压到 `~/.openclaw-git/`，自动检测 tarball 解压后的目录结构
- 创建 `~/.local/bin/git` wrapper 脚本（`set -e` + 存在性检查），指向内部 git，绝不 fallback 到 `/usr/bin/git`
- 设置 `GIT_EXEC_PATH` 环境变量让内部 git 找到辅助程序
- 创建 wrapper 前会先**测试执行**内部 git（`git --version`），只有测试通过才创建 wrapper

### 6. `force_rmtree` — 绕过 Python 3.12+ 的 shutil.rmtree 限制

Python 3.12 的 `shutil.rmtree` 使用 `_rmtree_safe_fd`，`onerror` 回调中调用 `os.open(path)` 会因缺少 `flags` 参数而失败，导致子树未被删除。`src/models/utils.py` 中的 `force_rmtree()` 直接用平台原生命令：`chmod -R +w && rm -rf`（macOS/Linux）或 `attrib -R && rmdir /s /q`（Windows）。

## 修改方向参考

- 换 UI 框架 → 只改 UI 层，下层通过 Protocol 无感知
- 换安装方式 → 改 Adapters（必要时改 Core），UI / Services 不变
- 新增功能 → 先在 Contracts 定义 Protocol → 各层分别实现 → Composition Root 装配
- 新增错误类型 → 改 `src/models/user_messages.py` 即可，UI 自动适配
- 新增镜像 / 调整超时 → 改 `src/models/constants.py`
- 新增平台（如 Linux ARM64）→ 改 `src/models/constants.py`（镜像 URL）+ Adapters（平台特殊处理）
- 离线版资源更新 → 改 `prepare_offline_resources.py` 或手动准备 tarball，保持 `resources/{platform}/` 目录结构

## 常见问题排查

**在线安装器 git clone 失败**：检查 Gitee 连通性，`src/adapters/install_openclaw.py` 有 3 次重试逻辑，错误分类在 `run_shell.py`。

**离线安装器"未找到预构建产物"**：检查 `resources/{platform}/openclaw-prebuilt-{platform}.tar.gz` 是否存在，文件名必须与 `_extract_prebuilt()` 中的 `filename` 一致。

**"pnpm not found" 在离线版**：`_which_cmd` 和 `_run_cmd_with_streaming` 必须使用同一个 `env`（`self._inst_env`），PATH 不一致会导致子进程找不到 pnpm。

**macOS 离线版仍弹 Xcode CLT**：检查 `resources/macos/git-macos-*.tar.gz` 是否包含真正的 git 二进制（非 `/usr/bin/git` shim），安装日志中应出现"内部 git 验证通过"。
