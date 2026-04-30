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
# 安装器
uv run python installer.py

# 卸载器
uv run python uninstaller.py
```

**打包可执行文件：**
```bash
# 默认输出到 dist/
uv run python build.py

# 指定输出路径
uv run python build.py --output ~/Desktop

# 仅清理构建文件
uv run python build.py --clean-only
```

打包完成后：
- **Windows**：`dist/OpenClaw安装器.exe`、`dist/OpenClaw卸载工具.exe`
- **macOS**：`dist/OpenClaw安装器.app` + `双击运行-OpenClaw安装器.command`

### 项目结构

```
├── installer.py               # 安装器入口（6 步流程）
├── uninstaller.py             # 卸载工具入口
├── build.py                   # PyInstaller 打包脚本（双程序）
├── src/
│   ├── core/
│   │   └── openclaw_manager.py    # OpenClaw 服务管理（启动/停止/配置/Provider）
│   ├── infra/
│   │   ├── openclaw_installer.py  # 安装逻辑（Gitee + pnpm 本地构建）
│   │   ├── git_installer.py       # Git 自动安装器（Windows）
│   │   ├── shell_runner.py        # Shell 命令执行 + 错误分类
│   │   └── system_checker.py      # 系统环境检测
│   ├── models/
│   │   ├── constants.py           # 项目常量（Node.js 版本、镜像、端口等）
│   │   ├── install.py             # 安装状态数据模型 + 错误分类枚举
│   │   ├── config.py              # 配置状态数据模型
│   │   ├── env_check.py           # 环境检测数据模型
│   │   └── provider_config.py     # Provider 数据定义
│   ├── services/
│   │   ├── install_service.py     # 安装服务（QThread Worker）
│   │   ├── env_check_service.py   # 环境检测服务
│   │   └── workers.py             # 配置/启动/Provider Worker
│   └── ui/
│       ├── welcome_page.py            # US-01 欢迎页
│       ├── env_check_page.py          # US-02 环境检测页
│       ├── installing_page.py         # US-04 安装进度页
│       ├── default_config_page.py     # US-05 默认配置页
│       ├── provider_config_page.py    # US-05b 模型配置页
│       ├── startup_page.py            # US-06 启动页
│       ├── uninstall_welcome_page.py  # 卸载-检测页
│       ├── uninstall_progress_page.py # 卸载-进度页
│       └── uninstall_done_page.py     # 卸载-完成页
```

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

安装过程中的所有子进程失败都会通过 `ErrorCategory` 枚举分类（网络超时、DNS、SSL、权限不足、磁盘已满、杀毒软件拦截等），UI 根据分类展示本地化错误描述和修复建议，而非原始 stderr。

### UI ↔ 后端通信

所有长耗时操作（安装、环境检测、配置、启动）都在独立的 `QThread` 子类中执行，通过 `Signal` 对象将进度和日志反馈给 UI。主线程始终保持响应，支持取消操作。
