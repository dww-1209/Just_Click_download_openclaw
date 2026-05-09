# OpenClaw 一键安装器

面向非技术用户的 OpenClaw（小龙虾）图形化一键安装启动器。把"下载、安装、默认配置、模型配置、启动 WebChat"封装成一个傻瓜式流程，无需接触命令行。

## 功能特点

- **真正一键安装**：点击"开始安装"即可，后台自动完成所有步骤
- **环境自动检测**：安装前自动检查磁盘空间、权限、浏览器支持
- **本地构建模式**：从 Gitee 克隆源码，使用 pnpm 本地构建，不依赖 npm 全局包
- **自动依赖安装**：自动检测并安装 Node.js 22、pnpm、Git（Windows）
- **默认配置优先**：安装后自动执行 onboard 初始化，设置 Gateway 参数
- **图形化模型配置**：支持多供应商 API Key、多选模型、设置默认模型和 fallback
- **自动启动服务**：安装完成后自动启动 Gateway 并获取带 token 的 WebChat 地址
- **独立卸载工具**：完全移除 OpenClaw 及其配置、命令包装器
- **跨平台支持**：Windows / macOS / Ubuntu

## 安装流程（6 步）

1. **欢迎** — 展示产品简介
2. **环境检测** — 检查操作系统、磁盘空间（> 5GB）、权限、浏览器、OpenClaw 安装状态
3. **下载与安装** — 后台静默安装 Node.js 22 + pnpm，从 Gitee 克隆并构建
4. **加载默认配置** — 设置 Gateway 参数（mode=local, bind=loopback, port=18789）
5. **Provider 模型配置** — 选择 AI 模型供应商、填写 API Key、多选模型
6. **启动服务与 WebChat** — 启动 Gateway，获取访问地址，打开浏览器

> 若检测到 OpenClaw 已安装，环境检测页会提供额外选项：快速启动、重新配置、配置模型、手动配置、重新下载。

## 使用方式

### 普通用户

1. 下载对应平台的可执行文件
   - **Windows**：`OpenClaw安装器.exe` + `OpenClaw卸载工具.exe`
   - **macOS**：`.app` 包 + 对应的 `.command` 辅助启动脚本（首次运行先双击 `.command` 绕过 Gatekeeper）
2. 双击运行安装器，点击 **"开始安装"**
3. 等待安装完成（预计 10-20 分钟，视网络状况而定）
4. 在 Provider 配置页选择模型并填写 API Key（或点击"跳过"使用默认配置）
5. 服务启动后点击 **"打开 WebChat"** 按钮即可使用

### 卸载

运行 `OpenClaw卸载工具`，确认后会自动：
- 停止 Gateway 服务
- 删除程序目录 `~/openclaw-cn`
- 删除配置目录 `~/.openclaw`（含 API Key）
- 卸载 npm 全局包、删除命令包装器

## 安装详情

| 项目 | 说明 |
|---|---|
| 安装位置 | `~/openclaw-cn`（源码目录）、`~/.openclaw`（配置目录） |
| 源码来源 | Gitee: `https://gitee.com/OpenClaw-CN/openclaw-cn.git` |
| Node.js 版本 | ≥ 22 |
| 包管理器 | pnpm（全局安装） |
| 服务端口号 | 18789 |
| WebChat 地址 | `http://127.0.0.1:18789?token=<自动获取>` |
| 命令包装器 | Windows: `%APPDATA%\npm\openclaw.cmd` / macOS&Linux: `~/.local/bin/openclaw` |

## 开发者

**安装依赖：**
```bash
uv sync
```

**运行开发版本：**
```bash
# 安装器（在线版）
uv run python launch_installer.py

# 安装器（离线版）
uv run python launch_installer_offline.py

# 卸载器
uv run python launch_uninstaller.py
```

### 准备资源

`resources/` 目录是打包时的输入，GitHub 仓库中只保留空目录结构（通过 `.gitkeep`），实际资源文件需在本地准备。

#### 资源文件清单

| 文件 | 位置 | 用途 | 准备方式 |
|---|---|---|---|
| `pnpm-*.tgz` | `resources/` 根目录 | 跨平台共用的 pnpm npm tarball | `prepare_offline_resources.py` 自动下载 |
| `node-v*-darwin-*.tar.gz` | `resources/macos/` | macOS Node.js 预编译包 | `prepare_offline_resources.py` 自动下载 |
| `node-v*-win-*.zip` | `resources/windows/` | Windows Node.js 预编译包 | `prepare_offline_resources.py` 自动下载 |
| `openclaw-prebuilt-*.tar.gz` | `resources/{platform}/` | OpenClaw 预构建产物 | **必须用** `prepare_offline_resources.py` 打包 |
| `git-*.tar.gz` / `git-*.zip` | `resources/{platform}/` | 内部 git（绕过系统 git 限制） | **手动准备**，详见下方 |

> **文件名不硬编码版本号**：安装器使用 glob 匹配（如 `node-v*.tar.gz`），支持任意版本，按版本号降序选择最新版。

#### 1. 自动下载的资源（Node.js + pnpm）

```bash
# 下载 Node.js 预编译包 + pnpm npm tarball
uv run python prepare_offline_resources.py --platform macos --skip-prebuilt --skip-git
```

#### 2. 预构建产物（离线版必需）

**⚠️ 不能用简单的 `tar czf` 打包。** pnpm workspace 会产生 symlink/junction 循环链接（如 `extensions/bluebubbles/node_modules/openclaw` 指向项目根目录），直接压缩会导致无限递归或软链接丢失。

**正确做法**：

```bash
# 步骤 A：先通过在线安装器完成构建，生成 ~/openclaw-cn
uv run python launch_installer.py

# 步骤 B：使用 prepare_offline_resources.py 打包（自动处理 symlink/junction）
uv run python prepare_offline_resources.py --platform macos --skip-nodejs --skip-pnpm --skip-git
```

`prepare_offline_resources.py` 的处理逻辑：
- **Windows**：优先调用系统 tar（MSYS2/Git Bash），能正确处理 junction
- **回退**：Python tarfile 手动遍历，遇到 symlink/junction 只记录链接本身，绝不跟随进入

#### 3. 内部 git 资源（macOS 必需，Windows 推荐）

**这不是从 git 官网下载的安装包。** 全新 macOS 上的 `/usr/bin/git` 是一个 shim（约 100KB），调用时会触发"安装开发者命令行工具"弹窗，而 Xcode CLT 体积巨大（约 2GB）。

**macOS 内部 git 的制作方式**：

从**已安装 Xcode Command Line Tools** 的 Mac 上，复制真正的 git 二进制和辅助程序：

```bash
# 1. 创建临时目录
mkdir -p /tmp/git-macos-arm64/bin
mkdir -p /tmp/git-macos-arm64/libexec

# 2. 从 Xcode CLT 复制真正的 git 二进制（不是 /usr/bin/git shim）
cp /Library/Developer/CommandLineTools/usr/bin/git /tmp/git-macos-arm64/bin/

# 3. 复制 git-core 辅助程序（git 子命令依赖这些）
cp -R /Library/Developer/CommandLineTools/usr/libexec/git-core /tmp/git-macos-arm64/libexec/

# 4. 如有其他必要目录（lib/、share/ 等），也一并复制
# cp -R /Library/Developer/CommandLineTools/usr/libexec/... /tmp/git-macos-arm64/...

# 5. 打包
cd /tmp && tar czf git-macos-arm64.tar.gz git-macos-arm64/

# 6. 移动到资源目录
mv git-macos-arm64.tar.gz resources/macos/
```

**关键说明**：
- 来源必须是 `/Library/Developer/CommandLineTools/usr/bin/git`（真正的二进制），**不能**是 `/usr/bin/git`（shim）
- 必须同时包含 `libexec/git-core/` 目录，否则 git 子命令（如 `git clone`）无法运行
- 需要区分 ARM64 和 Intel x64 架构，文件名建议带架构标识（如 `git-macos-arm64.tar.gz`）
- 安装器会在目标机器上解压到 `~/.openclaw-git/`，创建 `~/.local/bin/git` wrapper 脚本，设置 `GIT_EXEC_PATH` 环境变量

**Windows 内部 git**：下载 [MinGit](https://github.com/git-for-windows/git/releases) 便携版 zip，或提供完整的 PortableGit 目录压缩包。安装器会解压到 `~/.openclaw-git/` 并加入 PATH。

#### 打包可执行文件

```bash
# 默认输出到 dist/（自动检测 resources/{platform}/ 是否存在，存在则同时构建离线版）
uv run python build.py

# 显式指定离线资源目录
uv run python build.py --offline --resources-dir resources/macos

# 仅清理构建文件
uv run python build.py --clean-only
```

打包完成后：
- **Windows**：`dist/OpenClaw安装器.exe`、`dist/OpenClaw离线安装器.exe`、`dist/OpenClaw卸载工具.exe`
- **macOS**：`dist/OpenClaw安装器.app`、`dist/OpenClaw离线安装器.app`、`dist/OpenClaw卸载工具.app` + 对应的 `.command` 辅助脚本

### 架构图（六层 + Composition Root）

```
                    ┌───────────────────────────────┐
                    │      Composition Root         │
                    │  launch_installer.py          │
                    │  launch_installer_offline.py  │
                    │  launch_uninstaller.py        │
                    │  【唯一允许跨层导入】         │
                    └───────────────┬───────────────┘
                                    │ 装配依赖 + 连接信号
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                        依赖方向：自上而下（Frozen）                          │
│                                                                             │
│    UI  ──▶  Services  ──▶  Contracts  ──▶  Core  ──▶  Adapters  ──▶  Models│
│                                                                             │
│   ┌────────┐    ┌────────┐    ┌────────┐    ┌────────┐    ┌────────┐       │
│   │show_*  │    │perform_│    │I*      │    │manage_ │    │install_│       │
│   │        │◄───│check_* │───▶│Base*   │◄───│        │◄───│run_    │       │
│   │Signal  │Slot│configure│    │Protocol│    │        │    │launch_ │       │
│   └────────┘    └────────┘    └────────┘    └────────┘    └────────┘       │
│                                                              │              │
│                                                              ▼              │
│                                                           ┌────────┐       │
│                                                           │constants│      │
│                                                           │install │      │
│                                                           │config  │      │
│                                                           └────────┘       │
│                                                                             │
│  安全修改：                                                                 │
│  • 换 UI 框架      → 只改 UI 层，下层通过 Protocol 无感知                   │
│  • 换安装方式      → 只改 Core + Adapters，UI/Services 不变                 │
│  • 新增功能        → 先定义 Protocol → 各层分别实现 → Root 装配             │
│  • 新增错误分类    → 只改 Models(user_messages)，UI 自动适配                │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 项目结构

```
├── launch_installer.py               # 安装器入口（6 步流程，Composition Root）
├── launch_installer_offline.py       # 离线安装器入口（Composition Root）
├── launch_uninstaller.py             # 卸载工具入口（Composition Root）
├── build.py                          # PyInstaller 打包脚本（三个程序）
├── src/
│   ├── ui/                           # UI 层：PySide6 页面
│   │   ├── show_welcome.py           # 欢迎页
│   │   ├── show_envcheck.py          # 环境检测页
│   │   ├── show_install_progress.py  # 安装进度页
│   │   ├── show_default_config.py    # 默认配置页
│   │   ├── show_provider_config.py   # Provider 模型配置页
│   │   ├── show_startup.py           # 启动服务与 WebChat 页
│   │   ├── show_uninstall_welcome.py # 卸载-欢迎/检测页
│   │   ├── show_uninstall_progress.py# 卸载-进度页
│   │   └── show_uninstall_done.py    # 卸载-完成页
│   ├── services/                     # 服务层：QThread Worker 与桥接
│   │   ├── perform_install.py        # 安装服务（InstallWorker / InstallService）
│   │   ├── perform_uninstall.py      # 卸载服务（UninstallWorker / UninstallService）
│   │   ├── check_environment.py      # 环境检测服务（EnvCheckWorker / EnvCheckService）
│   │   └── configure_providers.py    # 配置/启动/Provider 服务（ConfigWorker / StartupWorker / ProviderConfigWorker）
│   ├── contracts/                    # 契约层：Protocol + ABC 双抽象
│   │   ├── define_installer.py       # IInstaller / IInstallTask（面向调用者）
│   │   ├── define_manager.py         # IOpenClawManager（面向调用者）
│   │   ├── define_process.py         # IProcessRunner（面向调用者）
│   │   ├── define_uninstaller.py     # IUninstallTask（面向调用者）
│   │   ├── define_worker.py          # 进度/日志回调类型别名
│   │   ├── define_env_checker.py     # IEnvChecker（面向调用者）
│   │   ├── define_system_launcher.py # ISystemLauncher（面向调用者）
│   │   ├── define_base_installer.py  # BaseInstaller ABC（面向实现者）
│   │   ├── define_base_manager.py    # BaseOpenClawManager ABC（面向实现者）
│   │   └── define_decorators.py      # @log_method / @check_cancelled 装饰器
│   ├── core/                         # 核心层：生命周期管理
│   │   └── manage_openclaw.py        # OpenClawManager（配置/启停/卸载）
│   ├── adapters/                     # 适配器层：底层系统操作
│   │   ├── install_openclaw.py       # OpenClaw 安装逻辑（Gitee + pnpm 本地构建）
│   │   ├── install_openclaw_offline.py# 离线安装逻辑（预构建资源解压）
│   │   ├── install_git.py            # Git 自动安装器（Windows）
│   │   ├── run_shell.py              # Shell 命令执行 + 错误分类
│   │   ├── check_system.py           # 系统环境检测
│   │   ├── provide_utils.py          # 通用工具函数（remove_readonly 等）
│   │   └── launch_system.py          # 终端/浏览器唤起（跨平台封装）
│   └── models/                       # 模型层：数据定义与常量
│       ├── constants.py              # 项目常量（Node.js 版本、镜像、端口等）
│       ├── install.py                # 安装状态/阶段/进度/错误分类枚举
│       ├── config.py                 # 配置状态/服务状态/进度数据类
│       ├── env_check.py              # 环境检测结果数据类
│       ├── provider_config.py        # Provider 配置数据定义
│       ├── user_messages.py          # 用户友好错误消息翻译
│       └── utils.py                  # 纯工具函数（命令解析、权限处理等）
├── prepare_offline_resources.py      # 离线资源准备脚本（下载 Node.js / pnpm / 打包预构建产物）
├── resources/                        # 离线资源目录（仓库中为空，需自行准备，详见下方）
│   ├── pnpm-10.10.0.tgz              # 跨平台共用的 pnpm npm tarball（需自行下载）
│   ├── macos/                        # macOS 离线资源（示例文件名，支持 glob 匹配）
│   │   ├── node-v*-darwin-*.tar.gz            # Node.js 预编译包（ARM64 或 x64）
│   │   ├── openclaw-prebuilt-macos.tar.gz     # OpenClaw 预构建产物（需先 build）
│   │   └── git-macos-*.tar.gz                 # 内部 git（从 Xcode CLT 复制，见下方说明）
│   ├── windows/                      # Windows 离线资源（示例文件名，支持 glob 匹配）
│   │   ├── node-v*-win-*.zip                  # Node.js 预编译包
│   │   ├── openclaw-prebuilt-windows.tar.gz   # OpenClaw 预构建产物（需先 build）
│   │   └── git-*.zip / MinGit-*.zip           # 内部 git（MinGit / PortableGit）
│   └── linux/                        # Linux 离线资源（预留）
```

> **注意**：`resources/` 目录中的二进制文件体积较大（总计可达数百 MB），超出 Git 传输限制，因此 GitHub 仓库中只保留空目录结构（通过 `.gitkeep` 占位）。实际资源文件请在本地准备，详见下方"准备资源"部分。
>
> **文件名不硬编码版本号**：安装器使用 glob 模式匹配（如 `node-v*.tar.gz`、`git-*.tar.gz`），支持任意版本，按版本号降序自动选择最新版。

### 双仓库工作流

本项目包含两个独立的 Git 仓库：

1. **根目录** → GitHub `dww-1209/Just_Click_download_openclaw`（开发主仓库）
2. **`agentclaw/` 子目录** → Gitea `http://47.116.45.225/ai-team/agentclaw`（下游仓库）

开发完成后，手动将相关文件复制到 `agentclaw/installer/`，然后在 `agentclaw/` 内提交并 push。注意：`agentclaw/` 内执行 git 命令必须使用绝对路径：

```bash
GIT_DIR=/Users/dww/Desktop/Just_Click_download_openclaw/agentclaw/.git \
GIT_WORK_TREE=/Users/dww/Desktop/Just_Click_download_openclaw/agentclaw \
git <command>
```

## 注意事项

1. **网络要求**：安装过程需要从 Gitee、国内 npm 镜像下载源码和依赖。如遇下载失败，可尝试切换网络或稍后重试。
2. **Windows 管理员权限**：安装 Node.js MSI 需要管理员权限，请右键程序选择"以管理员身份运行"。
3. **杀毒软件**：部分杀毒软件可能拦截 PowerShell/msiexec 命令，如遇问题请暂时关闭或添加白名单。
4. **端口占用**：Gateway 默认使用 18789 端口。若被占用，安装器会尝试释放该端口。
5. **macOS 安全放行**：首次运行未签名的 `.app` 时，系统会拦截。请双击 `.command` 辅助脚本启动，或前往 `系统设置 > 隐私与安全性` 点击`仍要打开`。
6. **Linux 系统要求**：仅支持 **Ubuntu 24.04 LTS 及以上版本** 的桌面环境。首次运行会自动安装 Node.js 等系统依赖。如遇窗口无法打开，可能需要预装 Qt X11 运行库：
   ```bash
   sudo apt install -y libxcb-cursor0 libxkbcommon-x11-0 libxcb-xinerama0 libxcb-randr0 libxcb-xfixes0 libxcb-shape0 libxcb-sync1 libxcb-render-util0 libxcb-keysyms1 libxcb-image0 libxcb-icccm4 libxcb-util1 libegl1 libopengl0
   ```

## 技术说明

### 为什么使用本地构建而非 `npm install -g`？

OpenClaw 官方安装脚本固定安装到用户目录，且后续升级需要重新执行脚本。本项目采用**本地构建模式**：
- 将源码克隆到 `~/openclaw-cn`
- 使用 `pnpm install` + `pnpm build` 本地编译
- 创建命令包装器脚本指向本地项目

优点：构建可控、版本可回溯、不污染全局 npm 包、支持自定义配置。

### 错误分类系统

安装过程中的所有子进程失败都会通过 `ErrorCategory` 枚举分类（网络超时、DNS、SSL、权限不足、磁盘已满、杀毒软件拦截等），UI 根据分类展示本地化错误描述和修复建议，而非原始 stderr。错误消息翻译集中维护在 `src/models/user_messages.py`。

### UI ↔ 后端通信

所有长耗时操作（安装、环境检测、配置、启动）都在独立的 `QThread` 子类中执行，通过 `Signal` 对象将进度和日志反馈给 UI。主线程始终保持响应，支持取消操作。Service 层负责 Worker 生命周期管理和信号中继。

### 架构设计要点

- **六层架构**：UI → Services → Contracts → Core → Adapters → Models，依赖方向严格自上而下
- **Composition Root**：`launch_installer.py` / `launch_uninstaller.py` 是唯一允许跨层导入的装配器层
- **Protocol + ABC 双抽象**：Contracts 层同时提供 `typing.Protocol`（面向使用者）和 `ABC`（面向实现者），兼顾灵活性与代码复用
- **中文注释**：所有代码模块、类、函数和非平凡逻辑块均包含中文注释
