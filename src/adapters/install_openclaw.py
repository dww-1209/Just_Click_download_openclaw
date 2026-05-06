import subprocess
import platform
import os
import signal
import shutil
import time
import sys
import stat
import threading

from pathlib import Path
from typing import List, Callable, Optional

# 只在非 Windows 平台导入 select（Windows 下 select.select 不支持文件描述符）
if platform.system().lower() != "windows":
    import select

from src.models.install import (
    InstallStatus,
    InstallStage,
    InstallProgress,
    InstallResult,
    InstallErrorDetail,
    ErrorCategory,
    get_official_command,
)
from src.adapters.install_git import ensure_git_installed
from src.adapters.run_shell import run_shell, ShellResult
from src.adapters.provide_utils import remove_readonly
from src.models.constants import (
    is_windows, is_macos, is_linux,
    TIMEOUT_SHORT_CMD, TIMEOUT_OPENCLAW_CMD, TIMEOUT_INSTALL_CMD,
    TIMEOUT_NODE_MSI_INSTALL, TIMEOUT_GIT_INSTALL_MAX, TIMEOUT_BUILD_CMD,
    NODEJS_MSI_MIRRORS, NODEJS_PKG_MIRRORS,
    REGISTRY_NPM_MIRROR, REGISTRY_CLAWHUB,
)
from src.contracts.define_base_installer import BaseInstaller
from src.adapters.define_decorators import log_method


class OpenClawInstaller(BaseInstaller):
    """OpenClaw 安装器 - 负责底层命令执行与全平台安装流程调度。

    设计要点：
    - 所有耗时操作均通过回调（on_progress / on_log）向 UI 层反馈，避免阻塞主线程。
    - 安装流程为"在线构建"模式：不预置 OpenClaw 本体，而是从 Gitee 拉取源码后本地编译。
    - 平台差异（Windows/macOS/Linux）集中在 Node.js 安装方式与命令包装器生成上，其余步骤尽量统一。
    """

    def __init__(self, os_type: str = None) -> None:
        """初始化安装器，自动识别或接受外部传入的操作系统类型。

        Args:
            os_type: 可选，强制指定操作系统类型。默认通过 platform.system() 自动判断。
                     会将 "darwin" 统一映射为 "macos"，简化后续分支判断。
        """
        super().__init__()
        self.os_type = os_type or platform.system().lower()
        if is_macos():
            self.os_type = "macos"

        self.process: Optional[subprocess.Popen] = None
        self.start_time: float = 0.0

        # 以下变量仅在 _install_local_build 执行期间有效，用于在拆分的步骤方法间共享状态
        self._inst_is_win: bool = False
        self._inst_env: dict = {}
        self._inst_project_dir: Path = Path()
        self._inst_on_progress: Optional[Callable[[InstallProgress], None]] = None
        self._inst_on_log: Optional[Callable[[str], None]] = None
        self._inst_startupinfo = None
        self._inst_creationflags: int = 0

    @log_method
    def install(
        self,
        on_progress: Callable[[InstallProgress], None] = None,
        on_log: Callable[[str], None] = None,
    ) -> InstallResult:
        """执行完整安装流程（全平台统一走 Gitee + pnpm 本地构建）。

        阶段概览：
        1. 前置依赖检查（Git / curl / Node.js，视平台而定）。
        2. 清理旧版本残留目录，避免冲突。
        3. 调用 _install_local_build() 执行：克隆 → pnpm install → 构建 → onboard → 创建 wrapper。

        Args:
            on_progress: 进度回调，用于驱动 UI 进度条与阶段文本。
            on_log: 日志回调，用于在 UI 中实时展示安装日志。

        Returns:
            InstallResult: 包含最终状态、消息、日志与耗时。
        """
        self.start_time = time.time()
        self.log_lines = []
        self.is_cancelled = False
        self._on_log = on_log

        try:
            if on_progress:
                on_progress(
                    InstallProgress(
                        stage=InstallStage.DOWNLOADING,
                        progress_percent=5,
                        message="正在检查依赖环境...",
                        current_task="检查前置依赖",
                    )
                )

            # ========================
            # 阶段 0：平台相关前置依赖检查
            # ========================
            if is_windows():
                # Windows：Git 是 clone 的必需工具；若未安装则尝试自动安装
                self._log("检查 Git 安装状态...")
                if not ensure_git_installed(on_log=lambda msg: self._log(msg)):
                    return InstallResult(
                        status=InstallStatus.FAILED,
                        message="Git 安装失败",
                        error_message="自动安装 Git 失败，请手动安装 Git 后重试\n下载地址: https://git-scm.com/download/win",
                        log_lines=self.log_lines.copy(),
                        duration_seconds=time.time() - self.start_time,
                    )
                self._log("Git 已就绪")

            elif self.os_type == "macos":
                # macOS：系统通常预装 git/curl，但全新系统可能缺失；
                # 若缺失 git，自动调用 xcode-select --install 弹出系统安装对话框
                self._log("检查前置依赖 (git, curl)...")
                for cmd, name in [("git", "Git"), ("curl", "curl")]:
                    try:
                        result = subprocess.run([cmd, "--version"], capture_output=True, shell=False, timeout=TIMEOUT_SHORT_CMD)
                        if result.returncode != 0:
                            raise FileNotFoundError()
                    except FileNotFoundError:
                        if cmd == "git":
                            self._log("系统未找到 Git，正在为您启动 Xcode Command Line Tools 安装...")
                            if on_progress:
                                on_progress(InstallProgress(
                                    stage=InstallStage.DOWNLOADING,
                                    progress_percent=5,
                                    message="检测到缺少 Git，正在启动系统安装程序，请按提示操作...",
                                    current_task="安装 Git (Xcode Command Line Tools)",
                                ))
                            subprocess.run(["xcode-select", "--install"], capture_output=True)

                            # 循环等待用户完成安装，最多 10 分钟（120 次 × 5 秒）
                            # 设计意图：系统对话框需要用户手动点击，无法自动完成，因此只能轮询检测
                            git_installed = False
                            for attempt in range(120):
                                # 检查用户是否取消安装，允许中断等待
                                if self.is_cancelled:
                                    self._log("用户取消安装，终止 Git 等待")
                                    break
                                time.sleep(5)
                                try:
                                    check = subprocess.run(["git", "--version"], capture_output=True, shell=False, timeout=TIMEOUT_SHORT_CMD)
                                    if check.returncode == 0:
                                        git_installed = True
                                        self._log("Git 安装完成")
                                        break
                                except FileNotFoundError:
                                    pass
                                elapsed = (attempt + 1) * 5
                                self._log(f"等待 Git 安装中... ({elapsed}秒)")
                                if on_progress and elapsed % 30 == 0:
                                    on_progress(InstallProgress(
                                        stage=InstallStage.DOWNLOADING,
                                        progress_percent=5,
                                        message=f"正在等待 Git 安装完成，已等待 {elapsed} 秒，请按系统提示完成安装...",
                                        current_task="安装 Git (Xcode Command Line Tools)",
                                    ))

                            if not git_installed:
                                return InstallResult(
                                    status=InstallStatus.FAILED,
                                    message="Git 安装超时",
                                    error_message=(
                                        "自动安装 Xcode Command Line Tools 超时，可能是连接 Apple 服务器较慢。\n\n"
                                        "建议尝试以下方案：\n"
                                        "1. 重新运行程序再次尝试自动安装\n"
                                        "2. 手动从 Apple 官网下载安装：\n"
                                        "   a. 访问 https://developer.apple.com/download/all/\n"
                                        "   b. 使用 Apple ID 登录\n"
                                        "   c. 搜索 'Command Line Tools for Xcode' 下载并安装\n"
                                        "3. 安装完成后重新运行本程序"
                                    ),
                                    log_lines=self.log_lines.copy(),
                                    duration_seconds=time.time() - self.start_time,
                                )
                        else:
                            # curl 缺失（极少见，macOS 系统预装）
                            return InstallResult(
                                status=InstallStatus.FAILED,
                                message=f"缺少 {name}",
                                error_message=f"系统未找到 {name}，请安装 Xcode Command Line Tools 后重试。",
                                log_lines=self.log_lines.copy(),
                                duration_seconds=time.time() - self.start_time,
                            )
                self._log("前置依赖已就绪")

            else:
                # Linux：需要 git、curl；Node.js 若已满足则跳过 pkexec 提权安装
                self._log("检查前置依赖 (git, curl, Node.js)...")
                missing_deps = []
                for cmd, name in [("git", "Git"), ("curl", "curl")]:
                    try:
                        result = subprocess.run([cmd, "--version"], capture_output=True, shell=False, timeout=TIMEOUT_SHORT_CMD)
                        if result.returncode != 0:
                            missing_deps.append(name)
                    except FileNotFoundError:
                        missing_deps.append(name)

                # 预检 Node.js 版本，满足 >=22 则跳过 pkexec 阶段，减少一次弹窗
                node_ok_linux = False
                try:
                    node_result = subprocess.run(["node", "-v"], capture_output=True, text=True, timeout=TIMEOUT_SHORT_CMD)
                    if node_result.returncode == 0:
                        major = int(node_result.stdout.strip().lstrip("v").split(".")[0])
                        if major >= 22:
                            node_ok_linux = True
                            self._log(f"Node.js {node_result.stdout.strip()} 已满足要求")
                except (OSError, subprocess.SubprocessError, ValueError):
                    pass

                if missing_deps:
                    self._log(f"缺少依赖: {', '.join(missing_deps)}，将在系统授权后自动安装")

                if not missing_deps and node_ok_linux:
                    self._log("前置依赖已就绪，跳过系统依赖安装")
                else:
                    # 使用 pkexec 一次性安装系统级依赖：
                    # 设计意图：Linux 下 apt 需要 root，pkexec 会弹出图形化授权框，比 sudo 更友好
                    self._log("正在安装系统依赖 (Node.js 22, pnpm)...")
                    # 安全提示：向用户展示将要执行的命令内容，让用户知情授权
                    self._log("[授权提示] 即将通过 pkexec 执行系统级安装命令：")
                    self._log("  apt update && curl -fsSL nodesource.com/setup_22.x | bash && apt-get install -y nodejs git curl && npm install -g pnpm")
                    pkexec_dep_cmd = (
                        "pkexec bash -c '"
                        "apt update >/dev/null 2>&1; "
                        "curl -fsSL https://deb.nodesource.com/setup_22.x | bash -E - >/dev/null 2>&1; "
                        "apt-get install -y nodejs git curl >/dev/null 2>&1; "
                        "npm install -g pnpm >/dev/null 2>&1; "
                        "echo \"[OK] system deps ready\""
                        "'"
                    )
                    dep_result = subprocess.run(
                        pkexec_dep_cmd, shell=True, capture_output=True, text=True, timeout=TIMEOUT_GIT_INSTALL_MAX
                    )
                    if dep_result.stdout:
                        for line in dep_result.stdout.splitlines():
                            if line.strip():
                                self._log(line.strip())
                    if dep_result.returncode != 0:
                        err = dep_result.stderr.strip() if dep_result.stderr else "系统依赖安装失败"
                        self._log(err)
                        return InstallResult(
                            status=InstallStatus.FAILED,
                            message="系统依赖安装失败",
                            error_message=f"自动安装 Node.js 失败，请确保网络畅通后重试。\n错误：{err}",
                            log_lines=self.log_lines.copy(),
                            duration_seconds=time.time() - self.start_time,
                            error_detail=InstallErrorDetail(
                                category=ErrorCategory.NETWORK_UNKNOWN,
                                stage="INSTALLING",
                                context="Linux 系统依赖安装 (pkexec)",
                                raw_error=err,
                                user_message="Linux 系统依赖安装失败",
                                suggestion="1. 确保网络畅通后重试\n2. 手动执行: sudo apt install -y nodejs git curl",
                            ),
                        )
                    self._log("系统依赖安装完成")

            # ========================
            # 阶段 1：清理残留目录
            # ========================
            # 避免旧版本文件与新构建产物冲突，尤其是 npm 全局包与本地仓库
            cleanup_dirs = [
                os.path.expanduser("~\\openclaw") if is_windows() else os.path.expanduser("~/.openclaw"),
                os.path.expanduser("~\\openclaw-cn") if is_windows() else os.path.expanduser("~/openclaw-cn"),
            ]
            if is_windows():
                cleanup_dirs.extend([
                    os.path.expanduser(r"~\AppData\Local\openclaw"),
                    os.path.expanduser(r"~\AppData\Roaming\npm\node_modules\openclaw"),
                    os.path.expanduser(r"~\AppData\Roaming\npm\node_modules\openclaw-cn"),
                ])
            for d in cleanup_dirs:
                if os.path.exists(d):
                    try:
                        shutil.rmtree(d, onerror=remove_readonly)
                        self._log(f"已清理残留目录: {d}")
                    except (OSError, shutil.Error) as e:
                        self._log(f"清理残留目录失败 {d}: {e}")

            # ========================
            # 阶段 2：进入统一本地构建流程
            # ========================
            target_dir = os.path.expanduser("~\\openclaw-cn") if is_windows() else os.path.expanduser("~/openclaw-cn")
            return self._install_local_build(target_dir, on_progress, on_log)

        except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as e:
            # 顶层容错：捕获安装主流程中所有已知运行时异常，防止 UI 崩溃
            error_msg = f"安装过程出错: {str(e)}"
            self._log(error_msg)
            return InstallResult(
                status=InstallStatus.FAILED,
                message="安装失败",
                error_message=error_msg,
                log_lines=self.log_lines.copy(),
                duration_seconds=time.time() - self.start_time,
            )

    # ------------------------------------------------------------------
    # 以下 helper 与 step 方法从 _install_local_build 中拆分出来，
    # 避免单方法过长（原方法约 768 行）。
    # ------------------------------------------------------------------

    def _check_cancelled_result(self) -> Optional[InstallResult]:
        """检查用户是否点击了取消按钮；若已取消，立即返回 CANCELLED 结果。"""
        if self.is_cancelled:
            return InstallResult(
                status=InstallStatus.CANCELLED,
                message="安装已取消",
                log_lines=self.log_lines.copy(),
                duration_seconds=time.time() - self.start_time,
            )
        return None

    def _run_shell_cmd(self, cmd: str, timeout: float = 300) -> ShellResult:
        """在独立 shell 中执行命令，复用 run_shell 的错误分类与诊断能力。"""
        return run_shell(cmd, timeout=timeout, env=self._inst_env)

    def _which_cmd(self, cmd_name: str) -> bool:
        """检测命令是否在 PATH 中可用。"""
        if self._inst_is_win:
            return self._run_shell_cmd(f"where {cmd_name}", timeout=TIMEOUT_SHORT_CMD).returncode == 0
        return subprocess.run(["which", cmd_name], capture_output=True, timeout=TIMEOUT_SHORT_CMD).returncode == 0

    def _verify_command(self, cmd_name: str) -> bool:
        """验证命令是否在 PATH 中可解析。"""
        if self._inst_is_win:
            return self._run_shell_cmd(f"where {cmd_name}", timeout=TIMEOUT_NODE_MSI_INSTALL).returncode == 0
        return subprocess.run(["which", cmd_name], capture_output=True, timeout=TIMEOUT_SHORT_CMD).returncode == 0

    def _is_valid_msi(self, path: Path) -> bool:
        """校验 MSI 文件头魔数（OLE 复合文档格式），防止下载到 HTML 错误页或空文件。"""
        if not path.exists():
            return False
        try:
            with open(path, "rb") as f:
                header = f.read(8)
            return header == b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
        except (OSError, ValueError):
            return False

    def _run_in_project_dir(self, cmd: list[str], timeout: float = 300, progress: InstallProgress = None) -> int:
        """在 project_dir 目录下执行命令，并可选地发送进度更新。

        安全策略：使用 shell=False + cwd 参数，彻底避免命令注入风险。
        """
        if progress and self._inst_on_progress:
            self._inst_on_progress(progress)
        return self._run_cmd_with_streaming(
            cmd, self._inst_env, timeout,
            self._inst_startupinfo, self._inst_creationflags, self._inst_on_log,
            cwd=str(self._inst_project_dir),
        )

    def _step0_uninstall_old_globals(self) -> None:
        """步骤 0：卸载已有的全局 openclaw（兼容旧版）。"""
        self._log("检查并清理已有的 OpenClaw 安装...")
        for pkg_cmd in [
            "npm unlink -g openclaw",
            "npm uninstall -g openclaw",
            "npm unlink -g openclaw-cn",
            "npm uninstall -g openclaw-cn",
        ]:
            self._run_shell_cmd(pkg_cmd, timeout=TIMEOUT_OPENCLAW_CMD)

    def _check_nodejs_version(self) -> bool:
        """检查 Node.js 版本是否满足 >= 22 的要求。

        Returns:
            True 如果 Node.js 已安装且版本 >= 22，否则 False。
        """
        node_ver = self._run_shell_cmd("node -v", timeout=TIMEOUT_NODE_MSI_INSTALL)
        if node_ver.returncode == 0:
            try:
                major = int(node_ver.stdout.strip().lstrip("v").split(".")[0])
                if major >= 22:
                    self._log(f"Node.js {node_ver.stdout.strip()} 已满足要求")
                    return True
                else:
                    self._log(f"检测到 Node.js v{major}，版本过低，正在为您升级...")
            except (ValueError, TypeError):
                pass
        return False

    def _install_nodejs_windows(self) -> Optional[InstallResult]:
        """在 Windows 上下载并安装 Node.js 22（MSI 方式）。"""
        try:
            import ctypes
            if not ctypes.windll.shell32.IsUserAnAdmin():
                return InstallResult(
                    status=InstallStatus.FAILED,
                    message="需要管理员权限",
                    error_message='安装 Node.js 需要管理员权限。\n\n请右键点击本程序，选择"以管理员身份运行"后重试。',
                    log_lines=self.log_lines.copy(),
                    duration_seconds=time.time() - self.start_time,
                )
        except (OSError, ImportError, AttributeError):
            pass

        node_urls = NODEJS_MSI_MIRRORS
        import tempfile
        temp_dir = Path(tempfile.gettempdir())
        node_msi = temp_dir / "node-v22-installer.msi"
        downloaded = False
        last_error_detail: Optional[InstallErrorDetail] = None

        for url in node_urls:
            cancelled = self._check_cancelled_result()
            if cancelled:
                return cancelled
            self._log(f"尝试下载 Node.js ({node_urls.index(url) + 1}/{len(node_urls)}): {url}")

            try:
                import urllib.request
                import ssl
                ctx = ssl.create_default_context()
                req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
                with urllib.request.urlopen(req, context=ctx, timeout=180) as resp:
                    with open(node_msi, "wb") as f:
                        f.write(resp.read())
                if self._is_valid_msi(node_msi):
                    downloaded = True
                    self._log(f"Node.js 安装包下载成功 ({node_msi.stat().st_size / 1024 / 1024:.1f} MB)")
                    break
                else:
                    actual = node_msi.stat().st_size if node_msi.exists() else 0
                    self._log(f"下载完成但文件校验失败 ({actual} 字节)，判定为失败")
            except (OSError, urllib.error.URLError, ssl.SSLError, ValueError) as e:
                self._log(f"[Python 下载失败] {type(e).__name__}: {str(e)}")

            if not downloaded:
                import base64
                ps_script = (
                    f'$ProgressPreference = "SilentlyContinue"; '
                    f'try {{ Invoke-WebRequest -Uri "{url}" -OutFile "{node_msi}" '
                    f'-UseBasicParsing -TimeoutSec 180; exit 0 }} catch {{ '
                    f'Write-Error "异常: $($_.Exception.Message)"; '
                    f'Write-Error "堆栈: $($_.ScriptStackTrace)"; exit 1 }}'
                )
                encoded = base64.b64encode(ps_script.encode("utf-16le")).decode("ascii")
                ps_cmd = f"powershell -ExecutionPolicy Bypass -EncodedCommand {encoded}"
                result = run_shell(
                    ps_cmd, timeout=200,
                    context=f"从 {url} 下载 Node.js msi 到 {node_msi}",
                    stage="DOWNLOADING",
                )
                if result.stderr.strip():
                    self._log(f"[PowerShell stderr]\n{result.stderr.strip()}")
                if result.error_detail:
                    last_error_detail = result.error_detail
                    self._log(f"[错误分类] {result.error_detail.category.value}")
                    self._log(f"[用户提示] {result.error_detail.user_message}")
                    raw = result.error_detail.raw_error
                    self._log(f"[原始错误] {raw[:1000]}{'...' if len(raw) > 1000 else ''}")
                if result.success and self._is_valid_msi(node_msi):
                    downloaded = True
                    self._log(f"Node.js 安装包下载成功 (PowerShell, {node_msi.stat().st_size / 1024 / 1024:.1f} MB)")
                    break
                else:
                    self._log(f"PowerShell 下载失败或文件校验不通过, rc={result.returncode}")

        if not downloaded:
            err_detail = last_error_detail
            user_msg = "无法下载 Node.js 22 安装包"
            if err_detail:
                user_msg = f"{err_detail.user_message}\n\n{err_detail.suggestion}"
            return InstallResult(
                status=InstallStatus.FAILED, message="Node.js 下载失败",
                error_message=user_msg,
                log_lines=self.log_lines.copy(), duration_seconds=time.time() - self.start_time,
                error_detail=err_detail,
            )

        self._log("修复 Windows Installer 服务...")
        run_shell("msiexec /unregister", timeout=TIMEOUT_OPENCLAW_CMD)
        run_shell("msiexec /regserver", timeout=TIMEOUT_OPENCLAW_CMD)
        self._log("Windows Installer 服务已修复")

        self._log("清理可能的 Node.js 注册表残留...")
        reg_clean_result = run_shell(
            'powershell -Command "Remove-Item -Path HKCU:\\Software\\Node.js -Recurse -Force -ErrorAction SilentlyContinue; Remove-Item -Path HKLM:\\SOFTWARE\\Node.js -Recurse -Force -ErrorAction SilentlyContinue"',
            timeout=TIMEOUT_OPENCLAW_CMD,
        )
        if reg_clean_result.success:
            self._log("注册表清理完成")
        else:
            self._log("注册表无残留或清理失败（不影响安装）")

        self._log(f"正在安装 Node.js (msi: {node_msi})...")
        msi_log = temp_dir / "node-v22-install.log"

        install_success = False
        for attempt in range(2):
            if attempt > 0:
                self._log("首次安装失败，等待 10 秒后重试...")
                time.sleep(10)

            install_result = run_shell(
                f'msiexec /i "{node_msi}" /qn /norestart /l*v "{msi_log}"',
                timeout=TIMEOUT_INSTALL_CMD,
                context=f"安装 Node.js msi ({node_msi})",
                stage="INSTALLING",
            )
            if install_result.stderr.strip():
                self._log(f"[msiexec stderr]\n{install_result.stderr.strip()}")

            if install_result.success:
                install_success = True
                break

            if msi_log.exists():
                try:
                    log_content = msi_log.read_text(encoding="utf-8", errors="replace")
                    all_lines = log_content.splitlines()
                    self._log(f"[MSI 安装日志 最后 {min(len(all_lines), 100)} 行]\n" + "\n".join(all_lines[-100:]))
                except (OSError, ValueError) as e:
                    self._log(f"[读取 MSI 日志失败] {e}")

            if attempt == 0 and install_result.returncode == 1603:
                self._log("检测到 1603 错误，可能是 Windows Installer 正忙或已有 Node.js 冲突，等待后重试...")
                time.sleep(3)
                continue

        if not install_success:
            err_detail = install_result.error_detail
            user_msg = (
                "Node.js 安装失败 (错误 1603)\n\n"
                "常见原因：\n"
                "1. 电脑上已安装了其他版本的 Node.js，导致冲突\n"
                "2. Windows 正在执行其他安装/更新程序\n"
                "3. 安全软件阻止了安装\n\n"
                "建议：\n"
                "• 先手动卸载已有的 Node.js，再重试\n"
                "• 重启电脑后重试\n"
                "• 暂时关闭杀毒软件后重试"
            )
            if err_detail:
                user_msg = f"{err_detail.user_message}\n\n{err_detail.suggestion}"
            self._log(f"Node.js 安装失败: {user_msg}")
            return InstallResult(
                status=InstallStatus.FAILED, message="Node.js 安装失败",
                error_message=user_msg,
                log_lines=self.log_lines.copy(), duration_seconds=time.time() - self.start_time,
                error_detail=err_detail,
            )

        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment") as key:
                sys_path, _ = winreg.QueryValueEx(key, "Path")
            os.environ["Path"] = sys_path + ";" + os.environ.get("Path", "")
        except (OSError, ImportError):
            pass
        node_path = r"C:\Program Files\nodejs"
        if os.path.exists(node_path):
            os.environ["Path"] = node_path + os.pathsep + os.environ.get("Path", "")

        try:
            if node_msi.exists():
                node_msi.unlink()
                self._log("已清理 Node.js 安装临时文件")
        except OSError:
            pass

        return None

    def _install_nodejs_macos(self, node_ok: bool) -> Optional[InstallResult]:
        """在 macOS 上下载并安装 Node.js 22（PKG 方式），必要时通过 osascript 申请管理员权限。

        设计意图：把所有需要管理员权限的命令收集起来，只弹一次密码框。

        Args:
            node_ok: Node.js 是否已满足版本要求（>= 22）。若已满足，仅处理 pnpm 缺失场景。
        """
        admin_cmds = []
        node_pkg = None
        macos_err_detail: Optional[InstallErrorDetail] = None

        if not node_ok:
            node_pkg = Path("/tmp") / "node-v22-installer.pkg"
            node_urls = NODEJS_PKG_MIRRORS
            downloaded = False
            for url in node_urls:
                cancelled = self._check_cancelled_result()
                if cancelled:
                    return cancelled
                self._log(f"尝试下载 Node.js ({node_urls.index(url) + 1}/{len(node_urls)}): {url}")
                result = run_shell(
                    f'curl -fsSL -o "{node_pkg}" "{url}"',
                    timeout=TIMEOUT_INSTALL_CMD, shell=False,
                    context=f"从 {url} 下载 Node.js pkg",
                    stage="DOWNLOADING",
                )
                if result.stderr.strip():
                    self._log(f"[curl stderr] {result.stderr.strip()}")
                if result.success and node_pkg.exists() and node_pkg.stat().st_size > 30 * 1024 * 1024:
                    downloaded = True
                    self._log(f"Node.js 安装包下载成功 ({node_pkg.stat().st_size / 1024 / 1024:.1f} MB)")
                    break
                else:
                    if result.error_detail:
                        macos_err_detail = result.error_detail
                        self._log(f"[错误分类] {result.error_detail.category.value}")
                        self._log(f"[用户提示] {result.error_detail.user_message}")
                    else:
                        self._log(f"curl 下载失败, rc={result.returncode}")
            if not downloaded:
                user_msg = "无法下载 Node.js 22 安装包"
                if macos_err_detail:
                    user_msg = f"{macos_err_detail.user_message}\n\n{macos_err_detail.suggestion}"
                return InstallResult(
                    status=InstallStatus.FAILED, message="Node.js 下载失败",
                    error_message=user_msg,
                    log_lines=self.log_lines.copy(), duration_seconds=time.time() - self.start_time,
                    error_detail=macos_err_detail,
                )
            admin_cmds.append(f"installer -pkg {node_pkg} -target /")
            admin_cmds.append("cd /tmp && export PATH=/usr/local/bin:/usr/bin:/bin:$PATH && npm install -g pnpm")
        else:
            if not self._which_cmd("pnpm"):
                pnpm_install = self._run_shell_cmd("npm install -g pnpm", timeout=120)
                if pnpm_install.returncode != 0:
                    err_text = pnpm_install.stderr.strip() if pnpm_install.stderr else ""
                    if "EACCES" in err_text or "permission denied" in err_text.lower():
                        admin_cmds.append("cd /tmp && export PATH=/usr/local/bin:/usr/bin:/bin:$PATH && npm install -g pnpm")
                    else:
                        self._log(f"pnpm 安装失败: {err_text}")
                        return InstallResult(
                            status=InstallStatus.FAILED, message="pnpm 安装失败",
                            error_message=f"无法安装 pnpm: {err_text}",
                            log_lines=self.log_lines.copy(), duration_seconds=time.time() - self.start_time,
                            error_detail=pnpm_install.error_detail if hasattr(pnpm_install, "error_detail") else None,
                        )

        if admin_cmds:
            cmd_str = " && ".join(admin_cmds)
            self._log("正在申请管理员权限安装系统依赖（只需输入一次密码）...")
            install_script = f'do shell script "{cmd_str}" with administrator privileges'
            result = run_shell(
                f'osascript -e "{install_script}"',
                timeout=TIMEOUT_INSTALL_CMD, shell=False,
                context="通过 osascript 申请管理员权限安装系统依赖",
                stage="INSTALLING",
            )
            if node_pkg and node_pkg.exists():
                try:
                    node_pkg.unlink()
                except OSError:
                    pass
            if not result.success:
                err_detail = result.error_detail
                user_msg = "安装失败：请确保输入了正确的管理员密码"
                if err_detail:
                    user_msg = f"{err_detail.user_message}\n\n{err_detail.suggestion}"
                self._log(f"系统依赖安装失败: {user_msg}")
                return InstallResult(
                    status=InstallStatus.FAILED, message="系统依赖安装失败",
                    error_message=user_msg,
                    log_lines=self.log_lines.copy(), duration_seconds=time.time() - self.start_time,
                    error_detail=err_detail,
                )

        os.environ["PATH"] = "/usr/local/bin:" + os.environ.get("PATH", "")
        return None

    def _install_nodejs_linux(self) -> Optional[InstallResult]:
        """Linux：理论上 install() 里已经通过 pkexec 安装了 Node.js，这里仅记录日志。"""
        self._log("Linux Node.js 应在系统依赖阶段已安装，跳过独立安装")
        return None

    def _step2_check_and_install_pnpm(self) -> Optional[InstallResult]:
        """步骤 2：检查/安装 pnpm。"""
        self._log("检查 pnpm 环境...")
        if not self._which_cmd("pnpm"):
            self._log("正在安装 pnpm...")
            if self._inst_on_progress:
                self._inst_on_progress(InstallProgress(stage=InstallStage.INSTALLING, progress_percent=15, message="正在安装系统依赖...", current_task="安装 pnpm"))
            npm_cmd = "npm.cmd" if self._inst_is_win else "npm"
            pnpm_install = self._run_shell_cmd(f"{npm_cmd} install -g pnpm", timeout=120)

            if pnpm_install.returncode != 0 and self.os_type == "macos":
                err_text = pnpm_install.stderr.strip() if pnpm_install.stderr else ""
                if "EACCES" in err_text or "permission denied" in err_text.lower():
                    self._log("普通权限安装 pnpm 失败，正在弹出密码框申请管理员权限...")
                    install_script = 'do shell script "cd /tmp && export PATH=/usr/local/bin:/usr/bin:/bin:$PATH && npm install -g pnpm" with administrator privileges'
                    pnpm_install = subprocess.run(
                        ["osascript", "-e", install_script],
                        capture_output=True, text=True, timeout=TIMEOUT_INSTALL_CMD
                    )

            if pnpm_install.returncode != 0:
                err = pnpm_install.stderr.strip() if pnpm_install.stderr else "未知错误"
                self._log(f"pnpm 安装失败: {err}")
                err_detail = pnpm_install.error_detail if hasattr(pnpm_install, "error_detail") else None
                user_msg = f"无法安装 pnpm: {err}"
                if err_detail:
                    user_msg = f"{err_detail.user_message}\n\n{err_detail.suggestion}"
                return InstallResult(
                    status=InstallStatus.FAILED, message="pnpm 安装失败",
                    error_message=user_msg,
                    log_lines=self.log_lines.copy(), duration_seconds=time.time() - self.start_time,
                    error_detail=err_detail,
                )
            self._log("pnpm 安装完成")

            if self._inst_is_win:
                try:
                    npm_bin_res = self._run_shell_cmd("npm bin -g", timeout=TIMEOUT_NODE_MSI_INSTALL)
                    if npm_bin_res.returncode == 0:
                        npm_bin_path = npm_bin_res.stdout.strip().strip('"').strip()
                        if npm_bin_path and os.path.exists(npm_bin_path) and npm_bin_path not in self._inst_env.get("PATH", ""):
                            self._inst_env["PATH"] = npm_bin_path + os.pathsep + self._inst_env.get("PATH", "")
                            self._log(f"已添加 npm 全局 bin 到 PATH: {npm_bin_path}")
                except (OSError, subprocess.SubprocessError) as e:
                    self._log(f"获取 npm 全局 bin 路径失败: {e}")
                appdata = os.environ.get("APPDATA", "")
                fallback_paths = [
                    os.path.join(appdata, "npm"),
                    r"C:\Program Files\nodejs",
                ]
                for fp in fallback_paths:
                    if os.path.exists(fp) and fp not in self._inst_env.get("PATH", ""):
                        self._inst_env["PATH"] = fp + os.pathsep + self._inst_env.get("PATH", "")
                        self._log(f"已添加 fallback PATH: {fp}")
            elif self.os_type == "macos":
                try:
                    npm_bin_res = self._run_shell_cmd("npm bin -g", timeout=TIMEOUT_NODE_MSI_INSTALL)
                    if npm_bin_res.returncode == 0:
                        npm_bin_path = npm_bin_res.stdout.strip().strip()
                        if npm_bin_path and os.path.exists(npm_bin_path) and npm_bin_path not in self._inst_env.get("PATH", ""):
                            self._inst_env["PATH"] = npm_bin_path + ":" + self._inst_env.get("PATH", "")
                            self._log(f"已添加 npm 全局 bin 到 PATH: {npm_bin_path}")
                except (OSError, subprocess.SubprocessError) as e:
                    self._log(f"获取 npm 全局 bin 路径失败: {e}")
        else:
            self._log("pnpm 已存在")
        return None

    def _step3_clone_repository(self) -> Optional[InstallResult]:
        """步骤 3：从 Gitee 克隆仓库。"""
        self._log("正在从 Gitee 下载 openclaw-cn...")
        if self._inst_on_progress:
            self._inst_on_progress(InstallProgress(stage=InstallStage.DOWNLOADING, progress_percent=20, message="正在下载 OpenClaw...", current_task="git clone"))

        clone_result = self._run_shell_cmd(
            f'git clone https://gitee.com/OpenClaw-CN/openclaw-cn.git "{self._inst_project_dir}"',
            timeout=TIMEOUT_INSTALL_CMD,
        )
        if clone_result.stdout:
            for line in clone_result.stdout.splitlines()[-50:]:
                if line.strip():
                    self._log(line.strip())
        if clone_result.stderr:
            for line in clone_result.stderr.splitlines()[-20:]:
                if line.strip():
                    self._log(line.strip())
        if clone_result.returncode != 0:
            err_detail = clone_result.error_detail if hasattr(clone_result, "error_detail") else None
            user_msg = "从 Gitee 克隆仓库失败，请检查网络或 Git 安装后重试"
            if err_detail:
                user_msg = f"{err_detail.user_message}\n\n{err_detail.suggestion}"
            return InstallResult(
                status=InstallStatus.FAILED, message="下载失败",
                error_message=user_msg,
                log_lines=self.log_lines.copy(), duration_seconds=time.time() - self.start_time,
                error_detail=err_detail,
            )
        self._log("仓库克隆完成")
        return None

    def _step4_set_pnpm_registry(self) -> None:
        """步骤 4：设置 pnpm 国内镜像。"""
        self._run_in_project_dir(['pnpm', 'config', 'set', 'registry', REGISTRY_NPM_MIRROR], timeout=TIMEOUT_OPENCLAW_CMD)

    def _step5_pnpm_install_deps(self) -> Optional[InstallResult]:
        """步骤 5：pnpm install（安装项目依赖）。"""
        self._log("正在安装依赖...")
        if self._inst_on_progress:
            self._inst_on_progress(InstallProgress(stage=InstallStage.INSTALLING, progress_percent=35, message="正在安装依赖...", current_task="pnpm install"))
        rc = self._run_in_project_dir(['pnpm', 'install'], timeout=TIMEOUT_BUILD_CMD)
        if rc != 0:
            recent_logs = "\n".join(self.log_lines[-30:])
            return InstallResult(
                status=InstallStatus.FAILED, message="依赖安装失败",
                error_message="pnpm install 失败，可能是网络不稳定或 npm 镜像源不可用。\n\n建议：\n1. 检查网络连接后重试\n2. 暂时关闭代理/VPN 后重试\n3. 查看高级模式中的完整日志",
                log_lines=self.log_lines.copy(), duration_seconds=time.time() - self.start_time,
                error_detail=InstallErrorDetail(
                    category=ErrorCategory.NETWORK_UNKNOWN,
                    stage="INSTALLING",
                    context="执行 pnpm install 安装项目依赖",
                    raw_error=f"returncode={rc}\n最近日志:\n{recent_logs}",
                    user_message="pnpm install 失败，可能是网络不稳定或 npm 镜像源不可用",
                    suggestion="1. 检查网络连接后重试\n2. 暂时关闭代理/VPN 后重试\n3. 查看高级模式中的完整日志",
                ),
            )
        return None

    def _step6_build_ui(self) -> Optional[InstallResult]:
        """步骤 6：pnpm ui:build（构建前端界面）。"""
        self._log("正在构建前端界面...")
        if self._inst_on_progress:
            self._inst_on_progress(InstallProgress(stage=InstallStage.INSTALLING, progress_percent=55, message="正在构建前端界面...", current_task="pnpm ui:build"))
        rc = self._run_in_project_dir(['pnpm', 'ui:build'], timeout=TIMEOUT_INSTALL_CMD)
        if rc != 0:
            recent_logs = "\n".join(self.log_lines[-20:])
            return InstallResult(
                status=InstallStatus.FAILED, message="前端构建失败",
                error_message="pnpm ui:build 失败，可能是内存不足或依赖缺失。\n\n建议：\n1. 关闭其他程序释放内存后重试\n2. 重启电脑后重试",
                log_lines=self.log_lines.copy(), duration_seconds=time.time() - self.start_time,
                error_detail=InstallErrorDetail(
                    category=ErrorCategory.UNKNOWN,
                    stage="INSTALLING",
                    context="执行 pnpm ui:build 构建前端",
                    raw_error=f"returncode={rc}\n最近日志:\n{recent_logs}",
                    user_message="前端构建失败，可能是内存不足或依赖缺失",
                    suggestion="1. 关闭其他程序释放内存后重试\n2. 重启电脑后重试",
                ),
            )
        return None

    def _step7_build_core(self) -> Optional[InstallResult]:
        """步骤 7：pnpm build（构建核心服务）。"""
        if self._inst_is_win:
            bash_dir = ""
            for candidate in [r"C:\Program Files\Git\bin", r"C:\Program Files (x86)\Git\bin"]:
                if os.path.exists(os.path.join(candidate, "bash.exe")):
                    bash_dir = candidate
                    break
            if bash_dir:
                self._log(f"找到 Git bash: {bash_dir}")
                self._inst_env["PATH"] = bash_dir + os.pathsep + self._inst_env.get("PATH", "")
            else:
                where_bash = self._run_shell_cmd("where bash", timeout=TIMEOUT_SHORT_CMD)
                if where_bash.returncode == 0 and where_bash.stdout.strip():
                    bash_dir = os.path.dirname(where_bash.stdout.strip().splitlines()[0].strip())
                    if bash_dir:
                        self._inst_env["PATH"] = bash_dir + os.pathsep + self._inst_env.get("PATH", "")
                        self._log(f"找到 bash: {bash_dir}")

        self._log("正在构建核心服务...")
        if self._inst_on_progress:
            self._inst_on_progress(InstallProgress(stage=InstallStage.INSTALLING, progress_percent=70, message="正在构建核心服务...", current_task="pnpm build"))
        rc = self._run_in_project_dir(['pnpm', 'build'], timeout=TIMEOUT_INSTALL_CMD)
        if rc != 0:
            recent_logs = "\n".join(self.log_lines[-20:])
            return InstallResult(
                status=InstallStatus.FAILED, message="核心构建失败",
                error_message="pnpm build 失败，可能是内存不足或 TypeScript 编译错误。\n\n建议：\n1. 关闭其他程序释放内存后重试\n2. 重启电脑后重试",
                log_lines=self.log_lines.copy(), duration_seconds=time.time() - self.start_time,
                error_detail=InstallErrorDetail(
                    category=ErrorCategory.UNKNOWN,
                    stage="INSTALLING",
                    context="执行 pnpm build 构建核心服务",
                    raw_error=f"returncode={rc}\n最近日志:\n{recent_logs}",
                    user_message="核心构建失败，可能是内存不足或 TypeScript 编译错误",
                    suggestion="1. 关闭其他程序释放内存后重试\n2. 重启电脑后重试",
                ),
            )
        return None

    def _step8_onboard_config(self) -> int:
        """步骤 8：初始化配置（onboard）。

        Returns:
            进程退出码；非零时调用方应视为警告而非致命错误。
        """
        self._log("正在初始化配置...")
        if self._inst_on_progress:
            self._inst_on_progress(InstallProgress(stage=InstallStage.CONFIGURING, progress_percent=85, message="正在初始化配置...", current_task="pnpm openclaw onboard"))
        rc = self._run_in_project_dir(
            ['pnpm', 'openclaw', 'onboard', '--non-interactive', '--accept-risk', '--mode', 'local', '--skip-skills', '--skip-health', '--no-install-daemon', '--node-manager', 'pnpm', '--skip-channels'],
            timeout=TIMEOUT_INSTALL_CMD,
        )
        if rc != 0:
            self._log("onboard 返回非零，但可能已部分完成，继续尝试...")
        return rc

    def _step9_create_command_wrappers(self) -> str:
        """步骤 9：创建全局命令 wrapper。

        Returns:
            命令包装器所在的目录路径（空字符串表示失败或未创建）。
        """
        self._log("正在创建全局命令...")
        if self._inst_is_win:
            npm_bin_dir = ""
            npm_bin_result = self._run_shell_cmd("npm.cmd bin -g", timeout=TIMEOUT_NODE_MSI_INSTALL)
            if npm_bin_result.returncode == 0 and npm_bin_result.stdout.strip():
                npm_bin_dir = npm_bin_result.stdout.strip()
            else:
                npm_bin_dir = str(Path(os.path.expanduser(r"~\AppData\Roaming\npm")))
            Path(npm_bin_dir).mkdir(parents=True, exist_ok=True)
            for wrapper_name in ["openclaw.cmd", "openclaw-cn.cmd"]:
                wrapper_path = Path(npm_bin_dir) / wrapper_name
                wrapper_content = (
                    f'@echo off\n'
                    f'set CLAWHUB_REGISTRY={REGISTRY_CLAWHUB}\n'
                    f'cd /d "{self._inst_project_dir}"\n'
                    f'pnpm openclaw %*\n'
                )
                try:
                    wrapper_path.write_text(wrapper_content, encoding="utf-8")
                    self._log(f"已创建全局命令: {wrapper_path}")
                except OSError as e:
                    self._log(f"创建全局命令失败 {wrapper_path}: {e}")
            return npm_bin_dir
        else:
            local_bin = Path(os.path.expanduser("~/.local/bin"))
            local_bin.mkdir(parents=True, exist_ok=True)
            for wrapper_name in ["openclaw", "openclaw-cn"]:
                wrapper_path = local_bin / wrapper_name
                wrapper_content = (
                    f'#!/bin/bash\n'
                    f'export CLAWHUB_REGISTRY={REGISTRY_CLAWHUB}\n'
                    f'cd "{self._inst_project_dir}" || exit 1\n'
                    f'pnpm openclaw "$@"\n'
                )
                try:
                    wrapper_path.write_text(wrapper_content, encoding="utf-8")
                    wrapper_path.chmod(0o755)
                    self._log(f"已创建全局命令: {wrapper_path}")
                except OSError as e:
                    self._log(f"创建全局命令失败 {wrapper_path}: {e}")
            self._ensure_local_bin_in_path(self._inst_on_log)
            return str(local_bin)

    def _step10_refresh_path_and_verify(self, npm_bin_dir: str) -> Optional[InstallResult]:
        """步骤 10：刷新 PATH 并验证命令可用性。"""
        self._log("刷新 PATH 并验证 openclaw 命令...")
        if npm_bin_dir and os.path.exists(npm_bin_dir):
            current_path = os.environ.get("Path" if self._inst_is_win else "PATH", "")
            path_sep = ";" if self._inst_is_win else ":"
            if npm_bin_dir.lower() not in current_path.lower():
                path_key = "Path" if self._inst_is_win else "PATH"
                os.environ[path_key] = npm_bin_dir + path_sep + current_path
                self._log(f"已将 {npm_bin_dir} 加入当前进程 PATH")
            self._inst_env["PATH" if self._inst_is_win else "PATH"] = os.environ.get("Path" if self._inst_is_win else "PATH", "")

        if self._inst_is_win:
            try:
                import winreg
                with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as key:
                    user_path, _ = winreg.QueryValueEx(key, "Path")
                user_path_expanded = os.path.expandvars(user_path)
                current_path = os.environ.get("Path", "")
                merged_paths = [p.strip() for p in current_path.split(";") if p.strip()]
                for p in user_path_expanded.split(";"):
                    p_strip = p.strip()
                    if p_strip and p_strip.lower() not in [mp.lower() for mp in merged_paths]:
                        merged_paths.append(p_strip)
                os.environ["Path"] = ";".join(merged_paths)
                self._inst_env["Path"] = os.environ["Path"]
            except (OSError, ImportError) as e:
                self._log(f"刷新 PATH 时出错（非致命）: {e}")

        if not self._verify_command("openclaw-cn") and not self._verify_command("openclaw"):
            if self._inst_is_win and npm_bin_dir:
                try:
                    self._run_shell_cmd(f'setx PATH "%PATH%;{npm_bin_dir}"', timeout=TIMEOUT_NODE_MSI_INSTALL)
                except (OSError, subprocess.SubprocessError):
                    pass
                self._inst_env["Path"] = os.environ.get("Path", "")
                if not self._verify_command("openclaw-cn") and not self._verify_command("openclaw"):
                    return InstallResult(
                        status=InstallStatus.FAILED, message="openclaw 命令不可用",
                        error_message="安装成功但系统 PATH 中找不到 openclaw/openclaw-cn 命令，请重启程序后重试",
                        log_lines=self.log_lines.copy(), duration_seconds=time.time() - self.start_time,
                    )
            else:
                return InstallResult(
                    status=InstallStatus.FAILED, message="openclaw 命令不可用",
                    error_message="未找到 openclaw/openclaw-cn 可执行文件",
                    log_lines=self.log_lines.copy(), duration_seconds=time.time() - self.start_time,
                )
        return None

    def _install_local_build(
        self,
        target_dir: str,
        on_progress: Callable[[InstallProgress], None],
        on_log: Callable[[str], None],
    ) -> InstallResult:
        """全平台统一的本地构建流程：Gitee 克隆 → pnpm 安装 → 构建 → onboard → 创建命令包装器。

        平台差异处理：
        - Windows：使用 STARTUPINFO + CREATE_NO_WINDOW 隐藏子进程黑框，避免用户体验割裂。
        - macOS/Linux：通过 osascript / pkexec 处理需要管理员权限的操作，尽量减少弹窗次数。

        Args:
            target_dir: 本地克隆目标路径。
            on_progress: 进度回调。
            on_log: 日志回调。

        Returns:
            InstallResult: 安装结果。
        """
        self._inst_is_win = is_windows()
        self._inst_startupinfo = None
        self._inst_creationflags = 0
        if self._inst_is_win:
            self._inst_startupinfo = subprocess.STARTUPINFO()
            self._inst_startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            self._inst_startupinfo.wShowWindow = subprocess.SW_HIDE
            self._inst_creationflags = subprocess.CREATE_NO_WINDOW

        self._inst_env = os.environ.copy()
        self._inst_env["PYTHONIOENCODING"] = "utf-8"
        self._inst_env["NODE_OPTIONS"] = "--max-old-space-size=8192"
        self._inst_project_dir = Path(target_dir)
        self._inst_on_progress = on_progress
        self._inst_on_log = on_log

        # 步骤 0：卸载已有的全局 openclaw（兼容旧版）
        self._step0_uninstall_old_globals()

        # 步骤 1：检查/安装 Node.js 22+
        cancelled = self._check_cancelled_result()
        if cancelled:
            return cancelled

        self._log("检查 Node.js 环境...")
        node_ok = self._check_nodejs_version()
        if not node_ok:
            self._log("正在安装 Node.js 22...")
            if on_progress:
                on_progress(InstallProgress(stage=InstallStage.INSTALLING, progress_percent=10, message="正在安装系统依赖...", current_task="安装 Node.js"))

            if self._inst_is_win:
                result = self._install_nodejs_windows()
            elif self.os_type == "macos":
                result = self._install_nodejs_macos(node_ok=False)
            else:
                result = self._install_nodejs_linux()
            if result:
                return result

            self._inst_env["PATH"] = os.environ.get("PATH", "")
            self._log("Node.js 安装完成，PATH 已刷新")

        # 步骤 2：检查/安装 pnpm
        cancelled = self._check_cancelled_result()
        if cancelled:
            return cancelled
        result = self._step2_check_and_install_pnpm()
        if result:
            return result

        # 步骤 3：从 Gitee 克隆仓库
        cancelled = self._check_cancelled_result()
        if cancelled:
            return cancelled
        result = self._step3_clone_repository()
        if result:
            return result

        # 步骤 4：设置 pnpm 国内镜像
        self._step4_set_pnpm_registry()

        # 步骤 5：pnpm install（安装项目依赖）
        cancelled = self._check_cancelled_result()
        if cancelled:
            return cancelled
        result = self._step5_pnpm_install_deps()
        if result:
            return result

        # 步骤 6：pnpm ui:build（构建前端界面）
        cancelled = self._check_cancelled_result()
        if cancelled:
            return cancelled
        result = self._step6_build_ui()
        if result:
            return result

        # 步骤 7：pnpm build（构建核心服务）
        cancelled = self._check_cancelled_result()
        if cancelled:
            return cancelled
        result = self._step7_build_core()
        if result:
            return result

        # 步骤 8：初始化配置（onboard）
        cancelled = self._check_cancelled_result()
        if cancelled:
            return cancelled
        self._step8_onboard_config()

        # 步骤 9：创建全局命令 wrapper
        npm_bin_dir = self._step9_create_command_wrappers()

        # 步骤 10：刷新 PATH 并验证命令可用性
        result = self._step10_refresh_path_and_verify(npm_bin_dir)
        if result:
            return result

        self._log("安装成功")
        if on_progress:
            on_progress(InstallProgress(stage=InstallStage.COMPLETED, progress_percent=100, message="安装完成", current_task="完成"))
        return InstallResult(
            status=InstallStatus.SUCCESS, message="OpenClaw 安装成功",
            log_lines=self.log_lines.copy(), duration_seconds=time.time() - self.start_time,
        )

    def _run_cmd_with_streaming(
        self,
        cmd: list[str],
        env: dict,
        timeout: float,
        startupinfo,
        creationflags: int,
        on_log: Callable[[str], None],
        cwd: str | None = None,
    ) -> int:
        """运行命令并实时流式输出日志，支持"无输出超时"自动终止。

        安全策略：使用 shell=False 接收命令列表，彻底避免命令注入。

        设计意图：
        - pnpm install / build 等命令耗时很长，用户需要看到实时进度以避免焦虑。
        - 某些网络/构建过程会假死（持续无输出），通过 last_output_time 检测并在超过 timeout 后强制 kill。
        - 每 30 秒输出一次心跳日志，告知用户"程序仍在工作"。

        Args:
            cmd: 要执行的命令参数列表（如 ["pnpm", "install"]）。
            env: 环境变量字典。
            timeout: 无输出超时阈值（秒）。
            startupinfo: Windows 专用启动信息（隐藏窗口）。
            creationflags: Windows 专用创建标志。
            on_log: 日志回调。
            cwd: 可选的工作目录。

        Returns:
            int: 进程退出码；若被强制终止则返回 -1。
        """
        self._log(f"启动命令: {' '.join(cmd)}")
        kwargs = {
            "shell": False,
            "stdout": subprocess.PIPE,
            "stderr": subprocess.STDOUT,
            "stdin": subprocess.DEVNULL,
            "universal_newlines": True,
            "bufsize": 1,
            "encoding": "utf-8",
            "errors": "replace",
            "env": env,
            "startupinfo": startupinfo,
            "creationflags": creationflags,
        }
        if cwd:
            kwargs["cwd"] = cwd
        process = subprocess.Popen(cmd, **kwargs)
        self._log(f"进程已启动，PID: {process.pid}")
        last_output_time = [time.time()]
        cmd_start = time.time()
        next_heartbeat = cmd_start + 30

        def reader() -> None:
            """后台线程：逐行读取 stdout 并触发日志回调。"""
            try:
                for line in process.stdout:
                    if line:
                        stripped = line.strip()
                        if stripped:
                            self._log(stripped)
                            last_output_time[0] = time.time()
            except (OSError, ValueError):
                pass

        t = threading.Thread(target=reader, daemon=True)
        t.start()

        try:
            while process.poll() is None:
                time.sleep(2)
                now = time.time()
                # 每 30 秒输出一次心跳，安抚用户
                if now > next_heartbeat:
                    elapsed = int(now - cmd_start)
                    self._log(f"命令仍在运行中，已等待 {elapsed} 秒，请耐心等待...")
                    next_heartbeat = now + 30
                # 无输出超时检测：防止假死进程无限占用
                if now - last_output_time[0] > timeout:
                    self._log(f"命令超过 {int(timeout)} 秒无输出，判定为卡住，强制终止...")
                    self._kill_process_tree(process)
                    break
            process.wait(timeout=TIMEOUT_SHORT_CMD)
        except (OSError, subprocess.SubprocessError) as e:
            self._log(f"等待进程时出错: {e}")
            self._kill_process_tree(process)

        t.join(timeout=TIMEOUT_SHORT_CMD)
        return process.returncode if process.poll() is not None else -1

    def _kill_process_tree(self, process: subprocess.Popen) -> None:
        """终止指定进程及其子进程。

        Windows 下使用 taskkill /F /T 递归杀进程树；
        其他平台先尝试 process.kill()，由操作系统回收子进程。
        """
        try:
            process.kill()
            # 等待进程退出，避免 PID 被回收后误杀其他进程（竞态条件修复）
            try:
                process.wait(timeout=TIMEOUT_SHORT_CMD)
            except (OSError, subprocess.SubprocessError):
                pass
        except (OSError, subprocess.SubprocessError):
            pass
        try:
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(process.pid)],
                shell=False,
                capture_output=True,
                timeout=TIMEOUT_NODE_MSI_INSTALL,
            )
        except (OSError, subprocess.SubprocessError):
            pass

    def _terminate_process(self) -> None:
        """终止当前正在执行的安装子进程。

        先发送 SIGTERM（优雅终止），等待 5 秒；若仍未结束则强制 kill。
        Windows 使用 process.terminate()，语义与 SIGTERM 类似。
        """
        if self.process and self.process.poll() is None:
            try:
                if is_windows():
                    self.process.terminate()
                else:
                    self.process.send_signal(signal.SIGTERM)

                # 等待进程结束
                try:
                    self.process.wait(timeout=TIMEOUT_SHORT_CMD)
                except subprocess.TimeoutExpired:
                    self.process.kill()

            except (OSError, subprocess.SubprocessError):
                pass

    def _ensure_local_bin_in_path(self, on_log: Callable[[str], None] = None) -> None:
        """确保 ~/.local/bin 被写入用户 shell 配置文件，以便终端能直接使用 openclaw 命令。

        会依次检查 .bashrc、.zshrc、.profile，避免重复写入。
        这是为"安装完成后用户新开终端能直接敲命令"做的持久化配置。
        """
        import os
        home = os.path.expanduser("~")
        local_bin = os.path.join(home, ".local", "bin")
        path_export = f'export PATH="{local_bin}:$PATH"'

        for rc_file in [".bashrc", ".zshrc", ".profile"]:
            rc_path = os.path.join(home, rc_file)
            if os.path.exists(rc_path):
                try:
                    with open(rc_path, "r", encoding="utf-8") as f:
                        content = f.read()
                    if local_bin in content:
                        self._log(f"{rc_file} 已包含 {local_bin}")
                        continue
                    with open(rc_path, "a", encoding="utf-8") as f:
                        f.write(f"\n# Added by OpenClaw Installer\n{path_export}\n")
                    self._log(f"已将 {local_bin} 添加到 {rc_file}")
                except OSError as e:
                    self._log(f"修改 {rc_file} 失败: {e}")

    def cancel(self) -> None:
        """取消安装。

        复用基类的取消标志设置，并立即终止当前子进程，
        后续步骤检测到标志后会提前返回 CANCELLED 结果。
        """
        super().cancel()
        self._terminate_process()

    def is_running(self) -> bool:
        """检查安装器当前是否有正在运行的子进程。"""
        return self.process is not None and self.process.poll() is None
