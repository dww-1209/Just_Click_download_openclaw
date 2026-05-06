# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

OpenClaw Installer is a **cross-platform online installer** for the OpenClaw project (Chinese community fork). It does **not** bundle OpenClaw itself; instead, it downloads and builds OpenClaw from the Gitee remote at install time. The app is built with PySide6 and packaged into standalone executables via PyInstaller. The target users are non-technical end users who need a one-click installation experience on Windows, macOS, and Ubuntu.

## Common Commands

- **Install dependencies:** `uv sync`
- **Run installer (dev):** `uv run python launch_installer.py`
- **Run uninstaller (dev):** `uv run python launch_uninstaller.py`
- **Run tests:** `uv run pytest tests/`
- **Build executables:** `uv run python build.py`
- **Build to custom output:** `uv run python build.py --output <path>`
- **Clean build artifacts only:** `uv run python build.py --clean-only`
- **Build without cleaning first:** `uv run python build.py --no-clean`
- **Quick syntax check:** `python3 -m py_compile launch_installer.py launch_uninstaller.py`

## Architecture

### Six-Layer Architecture (Frozen)

The project follows a **strictly layered architecture** with six layers. Dependency direction is top-down only: upper layers may import from lower layers, but never the reverse.

| Layer | Directory | Responsibility |
|---|---|---|
| 1. UI | `src/ui/` | PySide6 pages rendered inside `QStackedWidget` slides. Pure presentation; no business logic. |
| 2. Services | `src/services/` | `QThread` workers and service facades that bridge UI events to backend operations. |
| 3. Contracts | `src/contracts/` | `typing.Protocol` definitions (for callers) and `ABC` base classes (for implementers). |
| 4. Core | `src/core/` | High-level lifecycle orchestration (start/stop gateway, open WebUI, configure defaults). |
| 5. Adapters | `src/adapters/` | Low-level system operations (shell execution, Git/Node.js installation, system checks). |
| 6. Models | `src/models/` | Dataclasses, enums, constants, and pure utility functions. No external dependencies. |

**Architecture Freeze Declaration:** This six-layer structure is considered **frozen**. Any modification that adds new layers, changes dependency directions, or introduces cross-layer imports outside the Composition Root requires explicit design discussion. New features should fit within the existing layer boundaries.

### Composition Root Pattern

`launch_installer.py` and `launch_uninstaller.py` are the **only** files permitted to perform cross-layer imports. They act as the Composition Root: wiring concrete implementations into abstract interfaces and connecting Qt signals between UI pages and service workers.

Example from `launch_installer.py`:

```python
from src.ui.show_welcome import WelcomePage
from src.ui.show_envcheck import EnvCheckPage
from src.services.check_environment import EnvCheckService
from src.services.perform_install import InstallService
from src.core.manage_openclaw import OpenClawManager
from src.adapters.install_openclaw import OpenClawInstaller
from src.adapters.check_system import SystemChecker
```

No other module should import across more than one layer boundary.

### Naming Conventions (Mandatory)

| Directory | Prefix / Pattern | Example |
|---|---|---|
| `src/contracts/` | `define_` + noun | `define_installer.py`, `define_manager.py`, `define_process.py`, `define_uninstaller.py`, `define_worker.py`, `define_env_checker.py`, `define_base_installer.py`, `define_base_manager.py` |
| `src/adapters/` | verb + noun | `install_openclaw.py`, `install_git.py`, `run_shell.py`, `check_system.py`, `provide_utils.py` |
| `src/services/` | verb + noun | `perform_install.py`, `perform_uninstall.py`, `check_environment.py`, `configure_providers.py` |
| `src/ui/` | `show_` + noun | `show_welcome.py`, `show_envcheck.py`, `show_install_progress.py`, `show_default_config.py`, `show_provider_config.py`, `show_startup.py`, `show_uninstall_welcome.py`, `show_uninstall_progress.py`, `show_uninstall_done.py` |
| `src/core/` | noun (manager) | `manage_openclaw.py` |
| `src/models/` | noun (domain) | `constants.py`, `install.py`, `config.py`, `env_check.py`, `provider_config.py`, `user_messages.py`, `utils.py` |

When creating new files, always follow the convention of the target directory.

### Protocol + ABC Dual Abstraction

The `contracts/` layer uses two complementary abstraction mechanisms:

1. **`typing.Protocol`** — for callers. Service and UI layers depend on Protocol interfaces (e.g., `IInstaller`, `IOpenClawManager`), allowing any implementation to be injected without inheritance.
2. **`ABC` base classes** — for implementers. Classes in `core/` and `adapters/` may inherit from `BaseInstaller` or `BaseOpenClawManager` to reuse shared utilities (`_log()`, `is_cancelled`, `_check_cancelled()`) without being forced into a rigid hierarchy.

Key contracts:
- `define_installer.py` — `IInstaller`, `IInstallTask`
- `define_manager.py` — `IOpenClawManager`
- `define_process.py` — `IProcessRunner`
- `define_uninstaller.py` — `IUninstallTask`
- `define_worker.py` — `ProgressCallback`, `LogCallback`, `ConfigProgressCallback`
- `define_env_checker.py` — `IEnvChecker`
- `define_base_installer.py` — `BaseInstaller` (ABC)
- `define_base_manager.py` — `BaseOpenClawManager` (ABC)
- `define_decorators.py` — `@log_method`, `@check_cancelled`（位于 `adapters/`，供 core 和 adapters 层复用）

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

1. Detect or install Node.js >=22 (platform-specific: MSI on Windows, PKG on macOS, apt on Ubuntu).
2. Install pnpm globally.
3. Clone `https://gitee.com/OpenClaw-CN/openclaw-cn.git` into `~/openclaw-cn`.
4. Run `pnpm install` and `pnpm build` inside the cloned repo.
5. Create platform-specific command wrappers (`openclaw` / `openclaw-cn`) — Windows: `.cmd` scripts in the npm global bin dir; macOS/Linux: shell scripts in `~/.local/bin`.
6. Execute `pnpm openclaw onboard --non-interactive ...` to generate default config.
7. Start `openclaw-cn gateway start` and poll port 18789 for health.
8. Launch `openclaw-cn dashboard` to get a tokenized URL and open the system browser.

Constants such as Node.js version, mirror URLs, and the Gitee repo are centralized in `src/models/constants.py`.

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
