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
from src.infra.git_installer import ensure_git_installed
from src.infra.shell_runner import run_shell, ShellResult
from src.infra import utils
from src.models.constants import (
    is_windows, is_macos, is_linux,
    TIMEOUT_SHORT_CMD, TIMEOUT_OPENCLAW_CMD, TIMEOUT_INSTALL_CMD,
    TIMEOUT_NODE_MSI_INSTALL, TIMEOUT_GIT_INSTALL_MAX, TIMEOUT_BUILD_CMD,
)


class OpenClawInstaller:
    """OpenClaw 安装器 - 负责底层命令执行与全平台安装流程调度。

    设计要点：
    - 所有耗时操作均通过回调（on_progress / on_log）向 UI 层反馈，避免阻塞主线程。
    - 安装流程为"在线构建"模式：不预置 OpenClaw 本体，而是从 Gitee 拉取源码后本地编译。
    - 平台差异（Windows/macOS/Linux）集中在 Node.js 安装方式与命令包装器生成上，其余步骤尽量统一。
    """

    def __init__(self, os_type: str = None):
        """初始化安装器，自动识别或接受外部传入的操作系统类型。

        Args:
            os_type: 可选，强制指定操作系统类型。默认通过 platform.system() 自动判断。
                     会将 "darwin" 统一映射为 "macos"，简化后续分支判断。
        """
        self.os_type = os_type or platform.system().lower()
        if is_macos():
            self.os_type = "macos"

        self.process: Optional[subprocess.Popen] = None
        self.log_lines: List[str] = []
        self.is_cancelled = False
        self.start_time: float = 0.0

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
                self._log("检查 Git 安装状态...", on_log)
                if not ensure_git_installed(on_log=lambda msg: self._log(msg, on_log)):
                    return InstallResult(
                        status=InstallStatus.FAILED,
                        message="Git 安装失败",
                        error_message="自动安装 Git 失败，请手动安装 Git 后重试\n下载地址: https://git-scm.com/download/win",
                        log_lines=self.log_lines.copy(),
                        duration_seconds=time.time() - self.start_time,
                    )
                self._log("Git 已就绪", on_log)

            elif self.os_type == "macos":
                # macOS：系统通常预装 git/curl，但全新系统可能缺失；
                # 若缺失 git，自动调用 xcode-select --install 弹出系统安装对话框
                self._log("检查前置依赖 (git, curl)...", on_log)
                for cmd, name in [("git", "Git"), ("curl", "curl")]:
                    try:
                        result = subprocess.run([cmd, "--version"], capture_output=True, shell=False, timeout=TIMEOUT_SHORT_CMD)
                        if result.returncode != 0:
                            raise FileNotFoundError()
                    except FileNotFoundError:
                        if cmd == "git":
                            self._log("系统未找到 Git，正在为您启动 Xcode Command Line Tools 安装...", on_log)
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
                                    self._log("用户取消安装，终止 Git 等待", on_log)
                                    break
                                time.sleep(5)
                                try:
                                    check = subprocess.run(["git", "--version"], capture_output=True, shell=False, timeout=TIMEOUT_SHORT_CMD)
                                    if check.returncode == 0:
                                        git_installed = True
                                        self._log("Git 安装完成", on_log)
                                        break
                                except FileNotFoundError:
                                    pass
                                elapsed = (attempt + 1) * 5
                                self._log(f"等待 Git 安装中... ({elapsed}秒)", on_log)
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
                self._log("前置依赖已就绪", on_log)

            else:
                # Linux：需要 git、curl；Node.js 若已满足则跳过 pkexec 提权安装
                self._log("检查前置依赖 (git, curl, Node.js)...", on_log)
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
                            self._log(f"Node.js {node_result.stdout.strip()} 已满足要求", on_log)
                except (OSError, subprocess.SubprocessError, ValueError):
                    pass

                if missing_deps:
                    self._log(f"缺少依赖: {', '.join(missing_deps)}，将在系统授权后自动安装", on_log)

                if not missing_deps and node_ok_linux:
                    self._log("前置依赖已就绪，跳过系统依赖安装", on_log)
                else:
                    # 使用 pkexec 一次性安装系统级依赖：
                    # 设计意图：Linux 下 apt 需要 root，pkexec 会弹出图形化授权框，比 sudo 更友好
                    self._log("正在安装系统依赖 (Node.js 22, pnpm)...", on_log)
                    # 安全提示：向用户展示将要执行的命令内容，让用户知情授权
                    self._log("[授权提示] 即将通过 pkexec 执行系统级安装命令：", on_log)
                    self._log("  apt update && curl -fsSL nodesource.com/setup_22.x | bash && apt-get install -y nodejs git curl && npm install -g pnpm", on_log)
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
                                self._log(line.strip(), on_log)
                    if dep_result.returncode != 0:
                        err = dep_result.stderr.strip() if dep_result.stderr else "系统依赖安装失败"
                        self._log(err, on_log)
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
                    self._log("系统依赖安装完成", on_log)

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
                        shutil.rmtree(d, onerror=utils.remove_readonly)
                        self._log(f"已清理残留目录: {d}", on_log)
                    except (OSError, shutil.Error) as e:
                        self._log(f"清理残留目录失败 {d}: {e}", on_log)

            # ========================
            # 阶段 2：进入统一本地构建流程
            # ========================
            target_dir = os.path.expanduser("~\\openclaw-cn") if is_windows() else os.path.expanduser("~/openclaw-cn")
            return self._install_local_build(target_dir, on_progress, on_log)

        except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as e:
            # 顶层容错：捕获安装主流程中所有已知运行时异常，防止 UI 崩溃
            error_msg = f"安装过程出错: {str(e)}"
            self._log(error_msg, on_log)
            return InstallResult(
                status=InstallStatus.FAILED,
                message="安装失败",
                error_message=error_msg,
                log_lines=self.log_lines.copy(),
                duration_seconds=time.time() - self.start_time,
            )

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
        _is_win = is_windows()
        startupinfo = None
        creationflags = 0
        if _is_win:
            # Windows 专用：隐藏子进程控制台窗口，避免弹出 CMD 黑框打扰用户
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startupinfo.wShowWindow = subprocess.SW_HIDE
            creationflags = subprocess.CREATE_NO_WINDOW

        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"
        # Node.js 构建前端时内存消耗大，显式放宽堆限制避免 OOM
        env["NODE_OPTIONS"] = "--max-old-space-size=8192"
        project_dir = Path(target_dir)

        def _check_cancelled() -> Optional[InstallResult]:
            """检查用户是否点击了取消按钮；若已取消，立即返回 CANCELLED 结果。"""
            if self.is_cancelled:
                return InstallResult(
                    status=InstallStatus.CANCELLED,
                    message="安装已取消",
                    log_lines=self.log_lines.copy(),
                    duration_seconds=time.time() - self.start_time,
                )
            return None

        def _run(cmd: str, timeout: float = 300) -> ShellResult:
            """在独立 shell 中执行命令，复用 run_shell 的错误分类与诊断能力。

            run_shell 内部已统一处理 Windows 隐藏窗口参数（startupinfo +
            CREATE_NO_WINDOW）以及编码、超时、异常捕获等逻辑，因此直接委托即可。
            """
            return run_shell(cmd, timeout=timeout, env=env)

        def _run_in_project(cmd: str, timeout: float = 300, progress: InstallProgress = None) -> int:
            """先 cd 到项目目录再执行命令，并可选地发送进度更新。

            使用 cd && cmd 的形式而非 cwd 参数，是因为某些平台/权限组合下 cwd 会失效。
            安全策略：对 project_dir 进行校验，拒绝包含 shell 元字符的路径。
            """
            # 防御：project_dir 不应包含会导致命令注入的字符
            if any(c in project_dir for c in '"&|;<>$`\\'):
                self._log(f"项目路径包含非法字符，安装终止: {project_dir}", on_log)
                return 1
            if _is_win:
                full_cmd = f'cd /d "{project_dir}" && {cmd}'
            else:
                full_cmd = f'cd "{project_dir}" && {cmd}'
            if progress and on_progress:
                on_progress(progress)
            return self._run_cmd_with_streaming(
                full_cmd, env, timeout,
                startupinfo, creationflags, on_log
            )

        def _which(cmd_name: str) -> bool:
            """检测命令是否在 PATH 中可用。"""
            if _is_win:
                return _run(f"where {cmd_name}", timeout=TIMEOUT_SHORT_CMD).returncode == 0
            return subprocess.run(["which", cmd_name], capture_output=True, timeout=TIMEOUT_SHORT_CMD).returncode == 0

        # ========================
        # 步骤 0：卸载已有的全局 openclaw（兼容旧版）
        # ========================
        self._log("检查并清理已有的 OpenClaw 安装...", on_log)
        for pkg_cmd in [
            "npm unlink -g openclaw",
            "npm uninstall -g openclaw",
            "npm unlink -g openclaw-cn",
            "npm uninstall -g openclaw-cn",
        ]:
            _run(pkg_cmd, timeout=TIMEOUT_OPENCLAW_CMD)

        # ========================
        # 步骤 1：检查/安装 Node.js 22+
        # ========================
        cancelled = _check_cancelled()
        if cancelled:
            return cancelled

        self._log("检查 Node.js 环境...", on_log)
        node_ok = False
        node_ver = _run("node -v", timeout=TIMEOUT_NODE_MSI_INSTALL)
        if node_ver.returncode == 0:
            try:
                major = int(node_ver.stdout.strip().lstrip("v").split(".")[0])
                if major >= 22:
                    node_ok = True
                    self._log(f"Node.js {node_ver.stdout.strip()} 已满足要求", on_log)
                else:
                    self._log(f"检测到 Node.js v{major}，版本过低，正在为您升级...", on_log)
            except (ValueError, TypeError):
                pass

        if not node_ok:
            self._log("正在安装 Node.js 22...", on_log)
            if on_progress:
                on_progress(InstallProgress(stage=InstallStage.INSTALLING, progress_percent=10, message="正在安装系统依赖...", current_task="安装 Node.js"))

            if _is_win:
                # Windows：msiexec 安装 MSI 必须管理员权限，提前检测并给出友好提示
                try:
                    import ctypes
                    if not ctypes.windll.shell32.IsUserAnAdmin():
                        return InstallResult(
                            status=InstallStatus.FAILED,
                            message="需要管理员权限",
                            error_message="安装 Node.js 需要管理员权限。\n\n请右键点击本程序，选择\"以管理员身份运行\"后重试。",
                            log_lines=self.log_lines.copy(),
                            duration_seconds=time.time() - self.start_time,
                        )
                except (OSError, ImportError, AttributeError):
                    pass

                # 多镜像源 fallback：优先国内镜像加速，最后回退到官方源
                node_urls = [
                    "https://mirrors.aliyun.com/nodejs-release/v22.14.0/node-v22.14.0-x64.msi",
                    "https://mirrors.cloud.tencent.com/nodejs-release/v22.14.0/node-v22.14.0-x64.msi",
                    "https://repo.huaweicloud.com/nodejs/v22.14.0/node-v22.14.0-x64.msi",
                    "https://mirrors.ustc.edu.cn/nodejs/v22.14.0/node-v22.14.0-x64.msi",
                    "https://npmmirror.com/mirrors/node/v22.14.0/node-v22.14.0-x64.msi",
                    "https://registry.npmmirror.com/-/binary/node/latest-v22.x/node-v22.14.0-x64.msi",
                    "https://nodejs.org/dist/v22.14.0/node-v22.14.0-x64.msi",
                ]
                # 使用 tempfile 获取安全的临时目录，避免环境变量被篡改导致路径遍历
                import tempfile
                temp_dir = Path(tempfile.gettempdir())
                node_msi = temp_dir / "node-v22-installer.msi"
                downloaded = False
                last_error_detail: Optional[InstallErrorDetail] = None

                def _is_valid_msi(path: Path) -> bool:
                    """校验 MSI 文件头魔数（OLE 复合文档格式），防止下载到 HTML 错误页或空文件。"""
                    if not path.exists():
                        return False
                    try:
                        with open(path, "rb") as f:
                            header = f.read(8)
                        # MSI 文件头魔数: D0 CF 11 E0 A1 B1 1A E1
                        return header == b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
                    except (OSError, ValueError):
                        return False

                for url in node_urls:
                    if _check_cancelled():
                        return _check_cancelled()
                    self._log(f"尝试下载 Node.js ({node_urls.index(url) + 1}/{len(node_urls)}): {url}", on_log)

                    # 方法1：Python 原生下载（避免 PowerShell 在管理员上下文中的网络代理断裂）
                    try:
                        import urllib.request
                        import ssl
                        ctx = ssl.create_default_context()
                        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
                        with urllib.request.urlopen(req, context=ctx, timeout=180) as resp:
                            with open(node_msi, "wb") as f:
                                f.write(resp.read())
                        if _is_valid_msi(node_msi):
                            downloaded = True
                            self._log(f"Node.js 安装包下载成功 ({node_msi.stat().st_size / 1024 / 1024:.1f} MB)", on_log)
                            break
                        else:
                            actual = node_msi.stat().st_size if node_msi.exists() else 0
                            self._log(f"下载完成但文件校验失败 ({actual} 字节)，判定为失败", on_log)
                    except (OSError, urllib.error.URLError, ssl.SSLError, ValueError) as e:
                        self._log(f"[Python 下载失败] {type(e).__name__}: {str(e)}", on_log)

                    # 方法2：PowerShell fallback（某些环境 urllib 被防火墙拦截，PowerShell 反而能走系统代理）
                    if not downloaded:
                        # 使用 -EncodedCommand 避免 cmd 对 PowerShell 语法的引号转义问题
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
                            self._log(f"[PowerShell stderr]\n{result.stderr.strip()}", on_log)
                        if result.error_detail:
                            last_error_detail = result.error_detail
                            self._log(f"[错误分类] {result.error_detail.category.value}", on_log)
                            self._log(f"[用户提示] {result.error_detail.user_message}", on_log)
                            raw = result.error_detail.raw_error
                            self._log(f"[原始错误] {raw[:1000]}{'...' if len(raw) > 1000 else ''}", on_log)
                        if result.success and _is_valid_msi(node_msi):
                            downloaded = True
                            self._log(f"Node.js 安装包下载成功 (PowerShell, {node_msi.stat().st_size / 1024 / 1024:.1f} MB)", on_log)
                            break
                        else:
                            self._log(f"PowerShell 下载失败或文件校验不通过, rc={result.returncode}", on_log)

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

                # 安装前自动修复 Windows Installer（解决常见 1603/2503 错误）
                self._log("修复 Windows Installer 服务...", on_log)
                run_shell("msiexec /unregister", timeout=TIMEOUT_OPENCLAW_CMD)
                run_shell("msiexec /regserver", timeout=TIMEOUT_OPENCLAW_CMD)
                self._log("Windows Installer 服务已修复", on_log)

                # 安装前自动清理注册表残留（旧版本 Node.js 可能导致 MSI 冲突）
                self._log("清理可能的 Node.js 注册表残留...", on_log)
                reg_clean_result = run_shell(
                    'powershell -Command "Remove-Item -Path HKCU:\\Software\\Node.js -Recurse -Force -ErrorAction SilentlyContinue; Remove-Item -Path HKLM:\\SOFTWARE\\Node.js -Recurse -Force -ErrorAction SilentlyContinue"',
                    timeout=TIMEOUT_OPENCLAW_CMD,
                )
                if reg_clean_result.success:
                    self._log("注册表清理完成", on_log)
                else:
                    self._log("注册表无残留或清理失败（不影响安装）", on_log)

                # 安装 Node.js
                self._log(f"正在安装 Node.js (msi: {node_msi})...", on_log)
                msi_log = temp_dir / "node-v22-install.log"

                # 重试逻辑：msiexec 可能因 Windows Installer 正忙而失败，允许重试一次
                install_success = False
                for attempt in range(2):
                    if attempt > 0:
                        self._log("首次安装失败，等待 10 秒后重试...", on_log)
                        time.sleep(10)

                    install_result = run_shell(
                        f'msiexec /i "{node_msi}" /qn /norestart /l*v "{msi_log}"',
                        timeout=TIMEOUT_INSTALL_CMD,
                        context=f"安装 Node.js msi ({node_msi})",
                        stage="INSTALLING",
                    )
                    if install_result.stderr.strip():
                        self._log(f"[msiexec stderr]\n{install_result.stderr.strip()}", on_log)

                    if install_result.success:
                        install_success = True
                        break

                    # 读取 MSI 详细日志，输出最后 100 行供诊断
                    if msi_log.exists():
                        try:
                            log_content = msi_log.read_text(encoding="utf-8", errors="replace")
                            all_lines = log_content.splitlines()
                            # 输出日志最后 100 行
                            self._log(f"[MSI 安装日志 最后 {min(len(all_lines), 100)} 行]\n" + "\n".join(all_lines[-100:]), on_log)
                        except (OSError, ValueError) as e:
                            self._log(f"[读取 MSI 日志失败] {e}", on_log)

                    if attempt == 0 and install_result.returncode == 1603:
                        self._log("检测到 1603 错误，可能是 Windows Installer 正忙或已有 Node.js 冲突，等待后重试...", on_log)
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
                    self._log(f"Node.js 安装失败: {user_msg}", on_log)
                    return InstallResult(
                        status=InstallStatus.FAILED, message="Node.js 安装失败",
                        error_message=user_msg,
                        log_lines=self.log_lines.copy(), duration_seconds=time.time() - self.start_time,
                        error_detail=err_detail,
                    )

                # 安装完成后立即刷新当前进程的 PATH，使后续 subprocess 能直接调用 node/npm
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

                # 清理临时 MSI 文件
                try:
                    if node_msi.exists():
                        node_msi.unlink()
                        self._log("已清理 Node.js 安装临时文件", on_log)
                except OSError:
                    pass

            elif self.os_type == "macos":
                # macOS：把所有需要管理员权限的命令收集起来，只弹一次密码框（osascript）
                # 设计意图：多次弹窗会严重降低用户体验，合并命令可显著减少交互次数
                admin_cmds = []
                node_pkg = None
                macos_err_detail: Optional[InstallErrorDetail] = None

                # 1. 如果需要安装 Node.js，下载 .pkg 并准备安装命令
                if not node_ok:
                    node_pkg = Path("/tmp") / "node-v22-installer.pkg"
                    node_urls = [
                        "https://mirrors.aliyun.com/nodejs-release/v22.14.0/node-v22.14.0.pkg",
                        "https://mirrors.cloud.tencent.com/nodejs-release/v22.14.0/node-v22.14.0.pkg",
                        "https://repo.huaweicloud.com/nodejs/v22.14.0/node-v22.14.0.pkg",
                        "https://mirrors.ustc.edu.cn/nodejs/v22.14.0/node-v22.14.0.pkg",
                        "https://nodejs.org/dist/v22.14.0/node-v22.14.0.pkg",
                        "https://registry.npmmirror.com/-/binary/node/latest-v22.x/node-v22.14.0.pkg",
                    ]
                    downloaded = False
                    for url in node_urls:
                        if _check_cancelled():
                            return _check_cancelled()
                        self._log(f"尝试下载 Node.js ({node_urls.index(url) + 1}/{len(node_urls)}): {url}", on_log)
                        result = run_shell(
                            f'curl -fsSL -o "{node_pkg}" "{url}"',
                            timeout=TIMEOUT_INSTALL_CMD, shell=False,
                            context=f"从 {url} 下载 Node.js pkg",
                            stage="DOWNLOADING",
                        )
                        if result.stderr.strip():
                            self._log(f"[curl stderr] {result.stderr.strip()}", on_log)
                        if result.success and node_pkg.exists() and node_pkg.stat().st_size > 30 * 1024 * 1024:
                            downloaded = True
                            self._log(f"Node.js 安装包下载成功 ({node_pkg.stat().st_size / 1024 / 1024:.1f} MB)", on_log)
                            break
                        else:
                            if result.error_detail:
                                macos_err_detail = result.error_detail
                                self._log(f"[错误分类] {result.error_detail.category.value}", on_log)
                                self._log(f"[用户提示] {result.error_detail.user_message}", on_log)
                            else:
                                self._log(f"curl 下载失败, rc={result.returncode}", on_log)
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
                    # Node.js 装好后顺带把 pnpm 也装上（新 shell 里 /usr/local/bin 已在 PATH）
                    admin_cmds.append("cd /tmp && export PATH=/usr/local/bin:/usr/bin:/bin:$PATH && npm install -g pnpm")
                else:
                    # Node.js 已装好，检查 pnpm
                    if not _which("pnpm"):
                        pnpm_install = _run("npm install -g pnpm", timeout=120)
                        if pnpm_install.returncode != 0:
                            err_text = pnpm_install.stderr.strip() if pnpm_install.stderr else ""
                            if "EACCES" in err_text or "permission denied" in err_text.lower():
                                admin_cmds.append("cd /tmp && export PATH=/usr/local/bin:/usr/bin:/bin:$PATH && npm install -g pnpm")
                            else:
                                self._log(f"pnpm 安装失败: {err_text}", on_log)
                                return InstallResult(
                                    status=InstallStatus.FAILED, message="pnpm 安装失败",
                                    error_message=f"无法安装 pnpm: {err_text}",
                                    log_lines=self.log_lines.copy(), duration_seconds=time.time() - self.start_time,
                                    error_detail=pnpm_install.error_detail if hasattr(pnpm_install, "error_detail") else None,
                                )

                # 2. 一次性执行所有管理员命令（只弹一次密码框）
                if admin_cmds:
                    cmd_str = " && ".join(admin_cmds)
                    self._log("正在申请管理员权限安装系统依赖（只需输入一次密码）...", on_log)
                    install_script = f'do shell script "{cmd_str}" with administrator privileges'
                    result = run_shell(
                        f'osascript -e "{install_script}"',
                        timeout=TIMEOUT_INSTALL_CMD, shell=False,
                        context="通过 osascript 申请管理员权限安装系统依赖",
                        stage="INSTALLING",
                    )
                    # 清理临时文件
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
                        self._log(f"系统依赖安装失败: {user_msg}", on_log)
                        return InstallResult(
                            status=InstallStatus.FAILED, message="系统依赖安装失败",
                            error_message=user_msg,
                            log_lines=self.log_lines.copy(), duration_seconds=time.time() - self.start_time,
                            error_detail=err_detail,
                        )

                # 刷新 PATH：macOS Node.js 默认装到 /usr/local/bin
                os.environ["PATH"] = "/usr/local/bin:" + os.environ.get("PATH", "")

            else:
                # Linux：理论上 install() 里已经通过 pkexec 安装了 Node.js，这里再检查一次即可
                self._log("Linux Node.js 应在系统依赖阶段已安装，跳过独立安装", on_log)

            env["PATH"] = os.environ.get("PATH", "")
            self._log("Node.js 安装完成，PATH 已刷新", on_log)

        # ========================
        # 步骤 2：检查/安装 pnpm
        # ========================
        cancelled = _check_cancelled()
        if cancelled:
            return cancelled

        self._log("检查 pnpm 环境...", on_log)
        if not _which("pnpm"):
            self._log("正在安装 pnpm...", on_log)
            if on_progress:
                on_progress(InstallProgress(stage=InstallStage.INSTALLING, progress_percent=15, message="正在安装系统依赖...", current_task="安装 pnpm"))
            npm_cmd = "npm.cmd" if _is_win else "npm"
            pnpm_install = _run(f"{npm_cmd} install -g pnpm", timeout=120)

            # macOS：如果普通权限安装失败（EACCES），弹出密码框用管理员权限重试
            if pnpm_install.returncode != 0 and self.os_type == "macos":
                err_text = pnpm_install.stderr.strip() if pnpm_install.stderr else ""
                if "EACCES" in err_text or "permission denied" in err_text.lower():
                    self._log("普通权限安装 pnpm 失败，正在弹出密码框申请管理员权限...", on_log)
                    install_script = 'do shell script "cd /tmp && export PATH=/usr/local/bin:/usr/bin:/bin:$PATH && npm install -g pnpm" with administrator privileges'
                    pnpm_install = subprocess.run(
                        ["osascript", "-e", install_script],
                        capture_output=True, text=True, timeout=TIMEOUT_INSTALL_CMD
                    )

            if pnpm_install.returncode != 0:
                err = pnpm_install.stderr.strip() if pnpm_install.stderr else "未知错误"
                self._log(f"pnpm 安装失败: {err}", on_log)
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
            self._log("pnpm 安装完成", on_log)

            # Windows/macOS: pnpm 刚全局安装完，需要把 npm 全局 bin 目录加到当前 env 的 PATH
            # 否则新开的 shell 找不到 pnpm（安装程序本身不会自动重读注册表 PATH）
            if _is_win:
                try:
                    npm_bin_res = _run("npm bin -g", timeout=TIMEOUT_NODE_MSI_INSTALL)
                    if npm_bin_res.returncode == 0:
                        npm_bin_path = npm_bin_res.stdout.strip().strip('"').strip()
                        if npm_bin_path and os.path.exists(npm_bin_path) and npm_bin_path not in env.get("PATH", ""):
                            env["PATH"] = npm_bin_path + os.pathsep + env.get("PATH", "")
                            self._log(f"已添加 npm 全局 bin 到 PATH: {npm_bin_path}", on_log)
                except (OSError, subprocess.SubprocessError) as e:
                    self._log(f"获取 npm 全局 bin 路径失败: {e}", on_log)
                # fallback: 尝试常见的默认路径（用户级安装 vs 系统级安装）
                appdata = os.environ.get("APPDATA", "")
                fallback_paths = [
                    os.path.join(appdata, "npm"),
                    r"C:\Program Files\nodejs",
                ]
                for fp in fallback_paths:
                    if os.path.exists(fp) and fp not in env.get("PATH", ""):
                        env["PATH"] = fp + os.pathsep + env.get("PATH", "")
                        self._log(f"已添加 fallback PATH: {fp}", on_log)
            elif self.os_type == "macos":
                try:
                    npm_bin_res = _run("npm bin -g", timeout=TIMEOUT_NODE_MSI_INSTALL)
                    if npm_bin_res.returncode == 0:
                        npm_bin_path = npm_bin_res.stdout.strip().strip()
                        if npm_bin_path and os.path.exists(npm_bin_path) and npm_bin_path not in env.get("PATH", ""):
                            env["PATH"] = npm_bin_path + ":" + env.get("PATH", "")
                            self._log(f"已添加 npm 全局 bin 到 PATH: {npm_bin_path}", on_log)
                except (OSError, subprocess.SubprocessError) as e:
                    self._log(f"获取 npm 全局 bin 路径失败: {e}", on_log)
        else:
            self._log("pnpm 已存在", on_log)

        # ========================
        # 步骤 3：从 Gitee 克隆仓库
        # ========================
        cancelled = _check_cancelled()
        if cancelled:
            return cancelled

        self._log("正在从 Gitee 下载 openclaw-cn...", on_log)
        if on_progress:
            on_progress(InstallProgress(stage=InstallStage.DOWNLOADING, progress_percent=20, message="正在下载 OpenClaw...", current_task="git clone"))

        clone_result = _run(
            f'git clone https://gitee.com/OpenClaw-CN/openclaw-cn.git "{project_dir}"',
            timeout=TIMEOUT_INSTALL_CMD,
        )
        if clone_result.stdout:
            for line in clone_result.stdout.splitlines()[-50:]:
                if line.strip():
                    self._log(line.strip(), on_log)
        if clone_result.stderr:
            for line in clone_result.stderr.splitlines()[-20:]:
                if line.strip():
                    self._log(line.strip(), on_log)
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
        self._log("仓库克隆完成", on_log)

        # ========================
        # 步骤 4：设置 pnpm 国内镜像
        # ========================
        _run_in_project('pnpm config set registry https://registry.npmmirror.com/', timeout=TIMEOUT_OPENCLAW_CMD)

        # ========================
        # 步骤 5：pnpm install（安装项目依赖）
        # ========================
        cancelled = _check_cancelled()
        if cancelled:
            return cancelled

        self._log("正在安装依赖...", on_log)
        if on_progress:
            on_progress(InstallProgress(stage=InstallStage.INSTALLING, progress_percent=35, message="正在安装依赖...", current_task="pnpm install"))
        rc = _run_in_project("pnpm install", timeout=TIMEOUT_BUILD_CMD)
        if rc != 0:
            # 从最近日志中提取错误上下文，帮助用户快速定位网络/镜像问题
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

        # ========================
        # 步骤 6：pnpm ui:build（构建前端界面）
        # ========================
        cancelled = _check_cancelled()
        if cancelled:
            return cancelled

        self._log("正在构建前端界面...", on_log)
        if on_progress:
            on_progress(InstallProgress(stage=InstallStage.INSTALLING, progress_percent=55, message="正在构建前端界面...", current_task="pnpm ui:build"))
        rc = _run_in_project("pnpm ui:build", timeout=TIMEOUT_INSTALL_CMD)
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

        # ========================
        # 步骤 7：pnpm build（构建核心服务）
        # ========================
        cancelled = _check_cancelled()
        if cancelled:
            return cancelled

        # Windows 构建脚本可能依赖 bash（如 Makefile 或 shell 脚本），提前把 Git bash 加入 PATH
        if _is_win:
            bash_dir = ""
            for candidate in [r"C:\Program Files\Git\bin", r"C:\Program Files (x86)\Git\bin"]:
                if os.path.exists(os.path.join(candidate, "bash.exe")):
                    bash_dir = candidate
                    break
            if bash_dir:
                self._log(f"找到 Git bash: {bash_dir}", on_log)
                env["PATH"] = bash_dir + os.pathsep + env.get("PATH", "")
            else:
                where_bash = _run("where bash", timeout=TIMEOUT_SHORT_CMD)
                if where_bash.returncode == 0 and where_bash.stdout.strip():
                    bash_dir = os.path.dirname(where_bash.stdout.strip().splitlines()[0].strip())
                    if bash_dir:
                        env["PATH"] = bash_dir + os.pathsep + env.get("PATH", "")
                        self._log(f"找到 bash: {bash_dir}", on_log)

        self._log("正在构建核心服务...", on_log)
        if on_progress:
            on_progress(InstallProgress(stage=InstallStage.INSTALLING, progress_percent=70, message="正在构建核心服务...", current_task="pnpm build"))
        rc = _run_in_project("pnpm build", timeout=TIMEOUT_INSTALL_CMD)
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

        # ========================
        # 步骤 8：初始化配置（onboard）
        # ========================
        cancelled = _check_cancelled()
        if cancelled:
            return cancelled

        self._log("正在初始化配置...", on_log)
        if on_progress:
            on_progress(InstallProgress(stage=InstallStage.CONFIGURING, progress_percent=85, message="正在初始化配置...", current_task="pnpm openclaw onboard"))
        rc = _run_in_project(
            "pnpm openclaw onboard --non-interactive --accept-risk --mode local --skip-skills --skip-health --no-install-daemon --node-manager pnpm --skip-channels",
            timeout=TIMEOUT_INSTALL_CMD,
        )
        if rc != 0:
            # onboard 非零退出有时只是部分警告，继续尝试启动，避免过度阻断
            self._log("onboard 返回非零，但可能已部分完成，继续尝试...", on_log)

        # ========================
        # 步骤 9：创建全局命令 wrapper
        # ========================
        # 设计意图：不污染 npm 全局包，而是用轻量脚本代理到本地项目目录执行 pnpm openclaw
        self._log("正在创建全局命令...", on_log)
        if _is_win:
            # Windows：在 npm 全局 bin 目录下创建 .cmd 批处理脚本
            npm_bin_dir = ""
            npm_bin_result = _run("npm.cmd bin -g", timeout=TIMEOUT_NODE_MSI_INSTALL)
            if npm_bin_result.returncode == 0 and npm_bin_result.stdout.strip():
                npm_bin_dir = npm_bin_result.stdout.strip()
            else:
                npm_bin_dir = str(Path(os.path.expanduser(r"~\AppData\Roaming\npm")))
            Path(npm_bin_dir).mkdir(parents=True, exist_ok=True)
            for wrapper_name in ["openclaw.cmd", "openclaw-cn.cmd"]:
                wrapper_path = Path(npm_bin_dir) / wrapper_name
                wrapper_content = (
                    f'@echo off\n'
                    f'set CLAWHUB_REGISTRY=https://cn.clawhub-mirror.com/\n'
                    f'cd /d "{project_dir}"\n'
                    f'pnpm openclaw %*\n'
                )
                try:
                    wrapper_path.write_text(wrapper_content, encoding="utf-8")
                    self._log(f"已创建全局命令: {wrapper_path}", on_log)
                except OSError as e:
                    self._log(f"创建全局命令失败 {wrapper_path}: {e}", on_log)
        else:
            # macOS / Linux：在 ~/.local/bin 下创建 shell 脚本，符合 XDG 规范
            local_bin = Path(os.path.expanduser("~/.local/bin"))
            local_bin.mkdir(parents=True, exist_ok=True)
            for wrapper_name in ["openclaw", "openclaw-cn"]:
                wrapper_path = local_bin / wrapper_name
                wrapper_content = (
                    f'#!/bin/bash\n'
                    f'export CLAWHUB_REGISTRY=https://cn.clawhub-mirror.com/\n'
                    f'cd "{project_dir}" || exit 1\n'
                    f'pnpm openclaw "$@"\n'
                )
                try:
                    wrapper_path.write_text(wrapper_content, encoding="utf-8")
                    wrapper_path.chmod(0o755)
                    self._log(f"已创建全局命令: {wrapper_path}", on_log)
                except OSError as e:
                    self._log(f"创建全局命令失败 {wrapper_path}: {e}", on_log)
            npm_bin_dir = str(local_bin)
            self._ensure_local_bin_in_path(on_log)

        # ========================
        # 步骤 10：刷新 PATH 并验证命令可用性
        # ========================
        self._log("刷新 PATH 并验证 openclaw 命令...", on_log)
        if npm_bin_dir and os.path.exists(npm_bin_dir):
            current_path = os.environ.get("Path" if _is_win else "PATH", "")
            path_sep = ";" if _is_win else ":"
            if npm_bin_dir.lower() not in current_path.lower():
                path_key = "Path" if _is_win else "PATH"
                os.environ[path_key] = npm_bin_dir + path_sep + current_path
                self._log(f"已将 {npm_bin_dir} 加入当前进程 PATH", on_log)
            env["PATH" if _is_win else "PATH"] = os.environ.get("Path" if _is_win else "PATH", "")

        if _is_win:
            # 合并系统 PATH 与用户 PATH，确保子进程能继承完整环境
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
                env["Path"] = os.environ["Path"]
            except (OSError, ImportError) as e:
                self._log(f"刷新 PATH 时出错（非致命）: {e}", on_log)

        def _verify_cmd(cmd: str) -> bool:
            """验证命令是否在 PATH 中可解析。"""
            if _is_win:
                return _run(f"where {cmd}", timeout=TIMEOUT_NODE_MSI_INSTALL).returncode == 0
            return subprocess.run(["which", cmd], capture_output=True, timeout=TIMEOUT_SHORT_CMD).returncode == 0

        if not _verify_cmd("openclaw-cn") and not _verify_cmd("openclaw"):
            if _is_win and npm_bin_dir:
                # 尝试通过 setx 持久化 PATH（对当前进程无效，但下次启动生效）
                try:
                    _run(f'setx PATH "%PATH%;{npm_bin_dir}"', timeout=TIMEOUT_NODE_MSI_INSTALL)
                except (OSError, subprocess.SubprocessError):
                    pass
                env["Path"] = os.environ.get("Path", "")
                if not _verify_cmd("openclaw-cn") and not _verify_cmd("openclaw"):
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

        self._log("安装成功", on_log)
        if on_progress:
            on_progress(InstallProgress(stage=InstallStage.COMPLETED, progress_percent=100, message="安装完成", current_task="完成"))
        return InstallResult(
            status=InstallStatus.SUCCESS, message="OpenClaw 安装成功",
            log_lines=self.log_lines.copy(), duration_seconds=time.time() - self.start_time,
        )

    def _run_cmd_with_streaming(
        self,
        cmd: str,
        env: dict,
        timeout: float,
        startupinfo,
        creationflags: int,
        on_log: Callable[[str], None],
    ) -> int:
        """运行命令并实时流式输出日志，支持"无输出超时"自动终止。

        设计意图：
        - pnpm install / build 等命令耗时很长，用户需要看到实时进度以避免焦虑。
        - 某些网络/构建过程会假死（持续无输出），通过 last_output_time 检测并在超过 timeout 后强制 kill。
        - 每 30 秒输出一次心跳日志，告知用户"程序仍在工作"。

        Args:
            cmd: 要执行的 shell 命令。
            env: 环境变量字典。
            timeout: 无输出超时阈值（秒）。
            startupinfo: Windows 专用启动信息（隐藏窗口）。
            creationflags: Windows 专用创建标志。
            on_log: 日志回调。

        Returns:
            int: 进程退出码；若被强制终止则返回 -1。
        """
        self._log(f"启动命令: {cmd}", on_log)
        process = subprocess.Popen(
            cmd,
            shell=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            universal_newlines=True,
            bufsize=1,
            encoding="utf-8",
            errors="replace",
            env=env,
            startupinfo=startupinfo,
            creationflags=creationflags,
        )
        self._log(f"进程已启动，PID: {process.pid}", on_log)
        last_output_time = [time.time()]
        cmd_start = time.time()
        next_heartbeat = cmd_start + 30

        def reader():
            """后台线程：逐行读取 stdout 并触发日志回调。"""
            try:
                for line in process.stdout:
                    if line:
                        stripped = line.strip()
                        if stripped:
                            self._log(stripped, on_log)
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
                    self._log(f"命令仍在运行中，已等待 {elapsed} 秒，请耐心等待...", on_log)
                    next_heartbeat = now + 30
                # 无输出超时检测：防止假死进程无限占用
                if now - last_output_time[0] > timeout:
                    self._log(f"命令超过 {int(timeout)} 秒无输出，判定为卡住，强制终止...", on_log)
                    self._kill_process_tree(process)
                    break
            process.wait(timeout=TIMEOUT_SHORT_CMD)
        except (OSError, subprocess.SubprocessError) as e:
            self._log(f"等待进程时出错: {e}", on_log)
            self._kill_process_tree(process)

        t.join(timeout=TIMEOUT_SHORT_CMD)
        return process.returncode if process.poll() is not None else -1

    def _kill_process_tree(self, process: subprocess.Popen):
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

    def _log(self, message: str, on_log: Callable[[str], None] = None):
        """记录日志并可选地通知 UI。

        会自动过滤 ANSI 颜色码和光标控制序列，保证日志在 UI 文本框中显示干净。
        """
        import re
        # 过滤 ANSI 颜色码和光标控制序列，让日志在 UI 中更干净
        cleaned = re.sub(r'\x1b\[[0-9;?]*[A-Za-z]', '', message)
        timestamp = time.strftime("%H:%M:%S")
        log_line = f"[{timestamp}] {cleaned}"
        self.log_lines.append(log_line)
        if on_log:
            on_log(log_line)

    def _terminate_process(self):
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

    def _ensure_local_bin_in_path(self, on_log: Callable[[str], None] = None):
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
                        self._log(f"{rc_file} 已包含 {local_bin}", on_log)
                        continue
                    with open(rc_path, "a", encoding="utf-8") as f:
                        f.write(f"\n# Added by OpenClaw Installer\n{path_export}\n")
                    self._log(f"已将 {local_bin} 添加到 {rc_file}", on_log)
                except OSError as e:
                    self._log(f"修改 {rc_file} 失败: {e}", on_log)

    def cancel(self):
        """取消安装。

        设置取消标志并立即终止当前子进程，后续步骤检测到标志后会提前返回 CANCELLED 结果。
        """
        self.is_cancelled = True
        self._terminate_process()

    def is_running(self) -> bool:
        """检查安装器当前是否有正在运行的子进程。"""
        return self.process is not None and self.process.poll() is None
