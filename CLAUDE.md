# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

OpenClaw Installer is a **cross-platform online installer** for the OpenClaw project (Chinese community fork). It does **not** bundle OpenClaw itself; instead, it downloads and builds OpenClaw from the Gitee remote at install time. The app is built with PySide6 and packaged into standalone executables via PyInstaller. The target users are non-technical end users who need a one-click installation experience on Windows, macOS, and Ubuntu.

An **offline installer** variant is also available. It bundles pre-built artifacts (source + node_modules + dist) along with Node.js and pnpm standalone binaries, allowing installation without any network access.

**Runtime constraint:** Python `>=3.12,<3.13` (locked in `pyproject.toml` because PyInstaller 6.11.x and PySide6 6.8.x have not been validated on 3.13 in this project). Core dependencies: `pyside6`, `pyinstaller`, `httpx`, `psutil`, `pytest`.

## Common Commands

- **Install dependencies:** `uv sync`
- **Run installer (dev):** `uv run python launch_installer.py`
- **Run offline installer (dev):** `uv run python launch_installer_offline.py`
- **Run uninstaller (dev):** `uv run python launch_uninstaller.py`
- **Run tests:** `uv run pytest tests/`
- **Run a single test:** `uv run pytest tests/test_models.py -k test_name`
- **Build executables:** `uv run python build.py`
- **Build to custom output:** `uv run python build.py --output <path>`
- **Clean build artifacts only:** `uv run python build.py --clean-only`
- **Build without cleaning first:** `uv run python build.py --no-clean`
- **Quick syntax check:** `python3 -m py_compile launch_installer.py launch_uninstaller.py`
- **Prepare offline resources:** `uv run python prepare_offline_resources.py --platform macos`

## Architecture

### Six-Layer Architecture (Frozen)

The project follows a **strictly layered architecture** with six layers. Dependency direction is top-down only: upper layers may import from lower layers, but never the reverse.

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    OpenClaw Installer — 六层架构全景图                       │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│   ┌─────────────────────────────────────────────────────────────────────┐   │
│   │                        Composition Root                             │   │
│   │  launch_installer.py / launch_installer_offline.py                  │   │
│   │  launch_uninstaller.py                                              │   │
│   │                                                                     │   │
│   │  【唯一允许跨层导入】负责：依赖装配 + Qt 信号连接                     │   │
│   │  InstallerWindow(                                                   │   │
│   │      env_checker_factory=SystemChecker,                             │   │
│   │      installer_factory=OpenClawInstaller,                           │   │
│   │      manager_factory=OpenClawManager,                               │   │
│   │      system_launcher=SystemLauncher(),                              │   │
│   │  )                                                                  │   │
│   └─────────────────────────────────────────────────────────────────────┘   │
│                                    │                                        │
│                                    ▼                                        │
│   ╔═════════════════════════════════════════════════════════════════════╗   │
│   ║  依赖方向：上层可导入下层；下层严禁导入上层（Frozen）               ║   │
│   ╚═════════════════════════════════════════════════════════════════════╝   │
│                                                                             │
│   ┌──────────────┐         ┌──────────────┐         ┌──────────────┐       │
│   │  1. UI 层    │  ───▶   │ 2. Services  │  ───▶   │ 3. Contracts │       │
│   │  src/ui/     │ Signal  │ src/services/│  导入   │ src/contracts│       │
│   │              │◄────────│              │─────────│              │       │
│   │ show_welcome │  Slot   │ perform_*    │         │ IInstaller   │       │
│   │ show_envcheck│         │ check_env    │         │ IManager     │       │
│   │ show_install │         │ configure_*  │         │ ISystemLaunch│       │
│   │ show_startup │         │              │         │ BaseInstaller│       │
│   └──────────────┘         └──────────────┘         │ BaseManager  │       │
│                                                     └──────┬───────┘       │
│                                                            │               │
│                                                            ▼               │
│                                               ┌──────────────┐            │
│                                               │  4. Core     │            │
│                                               │  src/core/   │            │
│                                               │              │            │
│                                               │ manage_open..│            │
│                                               └──────┬───────┘            │
│                                                      │                     │
│                                                      ▼                     │
│                                               ┌──────────────┐            │
│                                               │ 5. Adapters  │            │
│                                               │ src/adapters/│            │
│                                               │              │            │
│                                               │ install_*    │            │
│                                               │ run_shell    │            │
│                                               │ launch_system│            │
│                                               │ check_system │            │
│                                               └──────┬───────┘            │
│                                                      │                     │
│                                                      ▼                     │
│                                               ┌──────────────┐            │
│                                               │  6. Models   │            │
│                                               │  src/models/ │            │
│                                               │              │            │
│                                               │ constants    │            │
│                                               │ install.py   │            │
│                                               │ config.py    │            │
│                                               │ user_messages│            │
│                                               └──────────────┘            │
│                                                                             │
├─────────────────────────────────────────────────────────────────────────────┤
│  安全修改指南：                                                               │
│  ┌────────────────────────────────────────────────────────────────────────┐ │
│  │ 场景              │ 需要修改的层                │ 无需修改的层          │ │
│  ├────────────────────────────────────────────────────────────────────────┤ │
│  │ 换 PySide6→Web    │ UI 层                      │ Services 及以下       │ │
│  │ 换安装方式        │ Core + Adapters             │ UI + Services         │ │
│  │ 新增供应商配置    │ 先定义 Protocol → 各层实现   │ 现有页面保持兼容      │ │
│  │ 新增错误分类      │ Models(user_messages)       │ UI 自动适配           │ │
│  │ 新增平台支持      │ Adapters + Models(constants)│ 上层通过 Protocol 无感│ │
│  └────────────────────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────────────────┘
```

| Layer | Directory | Responsibility |
|---|---|---|
| 1. UI | `src/ui/` | PySide6 pages rendered inside `QStackedWidget` slides. Pure presentation; no business logic. |
| 2. Services | `src/services/` | `QThread` workers and service facades that bridge UI events to backend operations. |
| 3. Contracts | `src/contracts/` | `typing.Protocol` definitions (for callers) and `ABC` base classes (for implementers). |
| 4. Core | `src/core/` | High-level lifecycle orchestration (start/stop gateway, configure defaults, uninstall). |
| 5. Adapters | `src/adapters/` | Low-level system operations (shell execution, Git/Node.js installation, system checks, terminal/browser launch). |
| 6. Models | `src/models/` | Dataclasses, enums, constants, and pure utility functions. No external dependencies. |

**Architecture Freeze Declaration:** This six-layer structure is considered **frozen**. Any modification that adds new layers, changes dependency directions, or introduces cross-layer imports outside the Composition Root requires explicit design discussion. New features should fit within the existing layer boundaries.

### Composition Root Pattern

`launch_installer.py`, `launch_installer_offline.py`, and `launch_uninstaller.py` are the **only** files permitted to perform cross-layer imports. They act as the Composition Root: wiring concrete implementations into abstract interfaces and connecting Qt signals between UI pages and service workers.

The `InstallerWindow` (UI layer) no longer instantiates adapters or core classes directly. Instead, it receives factory functions and services via constructor injection:

```python
installer = InstallerWindow(
    env_checker_factory=SystemChecker,           # Callable[[], IEnvChecker]
    installer_factory=OpenClawInstaller,         # Callable[[], IInstaller]
    manager_factory=OpenClawManager,             # Callable[[], IOpenClawManager]
    system_launcher=SystemLauncher(),            # ISystemLauncher singleton
)
```

No other module should import across more than one layer boundary.

### Naming Conventions (Mandatory)

| Directory | Prefix / Pattern | Example |
|---|---|---|
| `src/contracts/` | `define_` + noun | `define_installer.py`, `define_manager.py`, `define_process.py`, `define_uninstaller.py`, `define_worker.py`, `define_env_checker.py`, `define_base_installer.py`, `define_base_manager.py`, `define_system_launcher.py`, `define_decorators.py` |
| `src/adapters/` | verb + noun | `install_openclaw.py`, `install_git.py`, `run_shell.py`, `check_system.py`, `provide_utils.py`, `launch_system.py` |
| `src/services/` | verb + noun | `perform_install.py`, `perform_uninstall.py`, `check_environment.py`, `configure_providers.py` |
| `src/ui/` | `show_` + noun | `show_welcome.py`, `show_envcheck.py`, `show_install_progress.py`, `show_default_config.py`, `show_provider_config.py`, `show_startup.py`, `show_uninstall_welcome.py`, `show_uninstall_progress.py`, `show_uninstall_done.py` |
| `src/core/` | noun (manager) | `manage_openclaw.py` |
| `src/models/` | noun (domain) | `constants.py`, `install.py`, `config.py`, `env_check.py`, `provider_config.py`, `user_messages.py`, `utils.py` |

When creating new files, always follow the convention of the target directory.

### Protocol + ABC Dual Abstraction

The `contracts/` layer uses two complementary abstraction mechanisms:

1. **`typing.Protocol`** — for callers. Service and UI layers depend on Protocol interfaces (e.g., `IInstaller`, `IOpenClawManager`, `ISystemLauncher`), allowing any implementation to be injected without inheritance.
2. **`ABC` base classes** — for implementers. Classes in `core/` and `adapters/` may inherit from `BaseInstaller` or `BaseOpenClawManager` to reuse shared utilities (`_log()`, `_check_cancelled()`, `_write_command_wrappers()`, `_check_nodejs_version()`) without being forced into a rigid hierarchy.

Key contracts:
- `define_installer.py` — `IInstaller`, `IInstallTask`
- `define_manager.py` — `IOpenClawManager`
- `define_process.py` — `IProcessRunner`
- `define_uninstaller.py` — `IUninstallTask`
- `define_worker.py` — `ProgressCallback`, `LogCallback`, `ConfigProgressCallback`
- `define_env_checker.py` — `IEnvChecker`
- `define_system_launcher.py` — `ISystemLauncher` (terminal/browser launch abstraction)
- `define_base_installer.py` — `BaseInstaller` (ABC with shared utilities)
- `define_base_manager.py` — `BaseOpenClawManager` (ABC)
- `define_decorators.py` — `@log_method`, `@check_cancelled`, `CancellationError`

### System Integration Abstraction

All cross-platform system calls (terminal launch, browser open) are centralized in `src/adapters/launch_system.py` via the `ISystemLauncher` Protocol:

- `open_terminal_command(candidates, args)` — launches the system terminal and runs a command. Platform strategy: Windows (`CREATE_NEW_CONSOLE`), macOS (`osascript`), Linux (`gnome-terminal`/`xterm`/`konsole` fallback).
- `open_url(url)` — opens a URL in the system default browser. Validates `http://`/`https://` protocol whitelist; falls back to `cmd start` on Windows if `webbrowser` fails.

The UI layer never imports `subprocess`, `webbrowser`, `shutil`, or `platform` directly.

### UI ↔ Backend Communication Pattern

All long-running operations (install, env check, config, startup) run in dedicated `QThread` subclasses defined in `services/`. They emit `Signal` objects back to the UI. The UI pages connect to these signals and update progress bars/logs accordingly. Never run blocking shell commands on the main thread.

Typical signal flow:

```
UI page (show_*.py)
  → triggers Service (perform_*.py / check_*.py / configure_*.py)
  → Service spawns Worker (QThread subclass)
  → Worker calls Core/Adapters via Protocol interfaces
  → Worker emits progress/log/complete signals
  → Service relays signals to UI page slots
```

### Online Installation Flow

The installer does **not** bundle OpenClaw. It performs an online build:

1. Detect or install Node.js >=22. **No admin privileges required** — the installer downloads the official pre-compiled tarball/zip from bundled `resources/{platform}/` and extracts it into `~/.openclaw-node/`. If the bundled resource is missing, it falls back to downloading from domestic mirrors (Aliyun, Tencent Cloud, Huawei Cloud, USTC, npmmirror).
2. Install pnpm globally via `npm install -g pnpm` (uses the Node.js installed in step 1, no admin required).
3. Clone `https://gitee.com/OpenClaw-CN/openclaw-cn.git` into `~/openclaw-cn`.
4. Run `pnpm install` and `pnpm build` inside the cloned repo.
5. Create platform-specific command wrappers (`openclaw` / `openclaw-cn`) — Windows: `.cmd` scripts in the npm global bin dir; macOS/Linux: shell scripts in `~/.local/bin`.
6. Execute `pnpm openclaw onboard --non-interactive ...` to generate default config.
7. Start `openclaw-cn gateway start` and poll port 18789 for health.
8. Launch `openclaw-cn dashboard` to get a tokenized URL and open the system browser.

Constants such as Node.js version, mirror URLs, and the Gitee repo are centralized in `src/models/constants.py`.

### Offline Installation Flow

The offline installer (`launch_installer_offline.py`) uses `OfflineOpenClawInstaller` instead of `OpenClawInstaller`:

1. Detect or install Node.js >=22 from bundled pre-compiled binaries (`resources/{platform}/node-v22.*`), extracted to `~/.openclaw-node/`.
2. Install pnpm via `npm install -g resources/pnpm-*.tgz` using the bundled npm tarball (cross-platform, no standalone binary needed).
3. Extract pre-built artifacts (`resources/{platform}/openclaw-prebuilt-{platform}.tar.gz`) to `~/openclaw-cn`.
4. Create command wrappers (same as online).
5. Run onboard (same as online).
6. Verify installation.

Offline resources are prepared via `prepare_offline_resources.py`, which downloads Node.js binaries, pnpm npm tarball, and packages a pre-built OpenClaw tree into `resources/{platform}/`.

### Resources Directory

`resources/` contains platform-specific pre-built binaries used by both online and offline installers:

```
resources/
├── macos/
│   ├── node-v22.14.0-darwin-arm64.tar.gz   # Node.js for Apple Silicon
│   ├── node-v22.14.0-darwin-x64.tar.gz     # Node.js for Intel Mac (fallback)
│   └── openclaw-prebuilt-macos.tar.gz       # Pre-built OpenClaw (offline only)
├── windows/
│   ├── node-v22.14.0-win-x64.zip            # Node.js for Windows x64
│   └── openclaw-prebuilt-windows.tar.gz     # Pre-built OpenClaw (offline only)
├── linux/
│   ├── node-v22.14.0-linux-x64.tar.xz       # Node.js for Linux x64
│   └── openclaw-prebuilt-linux.tar.gz       # Pre-built OpenClaw (offline only)
├── native-cache/
│   └── matrix-sdk-crypto/
│       └── matrix-sdk-crypto.darwin-arm64.node  # Pre-built matrix SDK native module
└── pnpm-10.10.0.tgz                          # pnpm npm tarball (cross-platform)
```

**Key design decisions:**
- Node.js is installed by extracting the official tarball/zip to `~/.openclaw-node/` — no admin privileges needed (replaces MSI/PKG/apt system installs).
- pnpm is installed via `npm install -g pnpm-*.tgz` using the bundled tarball — no standalone platform-specific binary needed.
- Online installer only needs `node-v22.*` tarball/zip; offline installer additionally needs `openclaw-prebuilt-*.tar.gz`.
- `native-cache/matrix-sdk-crypto/` holds pre-built `.node` files to bypass slow GitHub Releases downloads for the matrix-sdk-crypto postinstall script.

### Cross-Platform Packaging Details

`build.py` wraps PyInstaller with platform-specific adjustments:

- **Windows:** Bundles `libssl-3-x64.dll` and `libcrypto-3-x64.dll` to avoid `_ssl` load failures on target machines. Uses `--noupx` to reduce antivirus false positives.
- **macOS:** Sets `--osx-bundle-identifier` and generates `.command` launcher scripts that strip Gatekeeper quarantine attributes via `xattr -rd com.apple.quarantine` before launching the `.app` bundle.
- Both apps are built as `--onefile --windowed` executables.

### Error Classification System

`src/adapters/install_openclaw.py` and `src/adapters/run_shell.py` map subprocess failures and exceptions into `ErrorCategory` enums (`network_timeout`, `permission_denied`, `antivirus_blocked`, etc.). The UI uses this category to show localized, user-friendly error messages with actionable suggestions rather than raw stderr.

Error-to-message translation is centralized in `src/models/user_messages.py` via `UserMessageHelper`.

### sys.path Bootstrap

Both entry points prepend the project root to `sys.path` so that `src.*` imports resolve regardless of the CWD:

```python
_PROJECT_ROOT = Path(__file__).parent.resolve()
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))
```

## Two-Repo Workflow (Critical)

This working directory contains **two nested, independent Git repos**:

1. **Root** (`/Users/dww/Desktop/Just_Click_download_openclaw`) -> GitHub `dww-1209/Just_Click_download_openclaw` (source of truth for development).
2. **`agentclaw/` subdirectory** -> Gitea `http://47.116.45.225/ai-team/agentclaw` (downstream, sparse-checkout showing only `installer/`).

**Workflow:**
1. Develop and test in the **root directory** (GitHub repo).
2. After changes are committed in the root repo, manually copy/overwrite the relevant files into `agentclaw/installer/` (e.g., `cp -R src/ agentclaw/installer/src/`, `cp launch_installer.py agentclaw/installer/`, etc.).
3. Commit the synced changes inside `agentclaw/` and push to Gitea.

**Git trap:** Because `agentclaw/` sits inside the root repo's work tree, running `git` commands from inside `agentclaw/` will often resolve to the **parent** GitHub repo instead of the agentclaw repo. Always use absolute paths:

```bash
GIT_DIR=/Users/dww/Desktop/Just_Click_download_openclaw/agentclaw/.git \
GIT_WORK_TREE=/Users/dww/Desktop/Just_Click_download_openclaw/agentclaw \
git <command>
```

## Tests

`tests/` contains four pytest modules covering the bottom of the stack:

| File | Scope |
|---|---|
| `tests/test_models.py` | Dataclasses, enums, and pure helpers in `src/models/` |
| `tests/test_contracts.py` | Protocol/ABC shape checks for `src/contracts/` |
| `tests/test_run_shell.py` | Shell-execution adapter and error-category mapping |
| `tests/test_user_messages.py` | `UserMessageHelper` translation logic |

UI, services, and core orchestration are not unit-tested — those layers rely on the model/adapter tests for correctness and on manual end-to-end runs of the installer for integration coverage.

## CI/CD

`.github/workflows/build-windows.yml` runs on `windows-latest` on every push/PR to `main`. It installs deps via pip and runs `python build.py`, then uploads `dist/*.exe` and the full `dist/` tree as artifacts.

## Agent Collaboration Workflow

The project operates with three agents configured by the user:

1. **Primary assistant** (this instance) — main development agent.
2. **`code-reviewer`** — dedicated code-review agent.
3. **`doc-research-writer`** — research and documentation agent.

### Development Flow

1. The user proposes a development idea.
2. The primary assistant produces a code example or draft.
3. The primary assistant writes the code into the project.
4. The draft is handed to `code-reviewer` for review.
5. Only the version approved by `code-reviewer` is adopted as the final, committed code.

### Research & Documentation

- **Technical questions:** When the primary assistant encounters a technical question that cannot be resolved with existing knowledge, the query is delegated to `doc-research-writer` for targeted research.
- **Documentation updates:** Whenever the project undergoes a major update or requires partial documentation changes, the writing task is assigned to `doc-research-writer`.

### Commenting Policy

**All code must include Chinese comments.** This is a hard user requirement that overrides any default "no comments" guidance. Every module, class, function, and non-trivial logic block should be annotated in Chinese to ensure readability for the target maintainers.
