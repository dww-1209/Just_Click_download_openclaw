# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

OpenClaw Installer is a **cross-platform online installer** for the OpenClaw project (Chinese community fork). It does **not** bundle OpenClaw itself; instead, it downloads and builds OpenClaw from the Gitee remote at install time. The app is built with PySide6 and packaged into standalone executables via PyInstaller. The target users are non-technical end users who need a one-click installation experience on Windows, macOS, and Ubuntu.

## Common Commands

- **Install dependencies:** `uv sync`
- **Run installer (dev):** `uv run python installer.py`
- **Run uninstaller (dev):** `uv run python uninstaller.py`
- **Build executables:** `uv run python build.py`
- **Build to custom output:** `uv run python build.py --output <path>`
- **Clean build artifacts only:** `uv run python build.py --clean-only`
- **Build without cleaning first:** `uv run python build.py --no-clean`
- **Quick syntax check:** `python3 -m py_compile installer.py uninstaller.py` (no test suite exists)

## Architecture

### Dual-Entry Design

The project produces **two independent desktop apps** via `build.py`:

- `installer.py` — Main installer with a 6-step flow (欢迎 → 环境检测 → 安装 → 配置 → 模型 → 启动) via `QStackedWidget`.
- `uninstaller.py` — Standalone uninstaller: stop gateway → remove directories → clean npm wrappers.

Both entries prepend the project root to `sys.path` so that `src.*` imports resolve regardless of the CWD:

```python
_PROJECT_ROOT = Path(__file__).parent.resolve()
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))
```

### Layered Structure under `src/`

| Layer | Responsibility | Key Files |
|---|---|---|
| `ui/` | PySide6 pages (QStackedWidget slides) | `welcome_page.py`, `installing_page.py`, `provider_config_page.py`, ... |
| `services/` | QThread workers that bridge UI and infra | `install_service.py`, `env_check_service.py`, `workers.py` |
| `core/` | High-level OpenClaw lifecycle management | `openclaw_manager.py` — start/stop gateway, open WebUI, configure defaults |
| `infra/` | Low-level system operations | `openclaw_installer.py`, `git_installer.py`, `shell_runner.py`, `system_checker.py` |
| `models/` | Dataclasses, enums, constants | `install.py`, `config.py`, `constants.py`, `env_check.py` |

### UI ↔ Backend Communication Pattern

All long-running operations (install, env check, config) run in dedicated `QThread` subclasses defined in `services/`. They emit `Signal` objects back to the UI. The UI pages connect to these signals and update progress bars/logs accordingly. Never run blocking shell commands on the main thread.

### Online Installation Flow

The installer does **not** bundle OpenClaw. It performs an online build:

1. Detect or install Node.js ≥22 (platform-specific: MSI on Windows, PKG on macOS, apt on Ubuntu).
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

`src/infra/openclaw_installer.py` maps subprocess failures and exceptions into `ErrorCategory` enums (`network_timeout`, `permission_denied`, `antivirus_blocked`, etc.). The UI uses this category to show localized, user-friendly error messages with actionable suggestions rather than raw stderr.

## Two-Repo Workflow (Critical)

This working directory contains **two nested, independent Git repos**:

1. **Root** (`/Users/dww/Desktop/Just_Click_download_openclaw`) → GitHub `dww-1209/Just_Click_download_openclaw` (source of truth for development).
2. **`agentclaw/` subdirectory** → Gitea `http://47.116.45.225/ai-team/agentclaw` (downstream, sparse-checkout showing only `installer/`).

**Workflow:**
1. Develop and test in the **root directory** (GitHub repo).
2. After changes are committed in the root repo, manually copy/overwrite the relevant files into `agentclaw/installer/` (e.g., `cp -R src/ agentclaw/installer/src/`, `cp installer.py agentclaw/installer/`, etc.).
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
