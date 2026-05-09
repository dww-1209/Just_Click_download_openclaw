import subprocess
import platform
import os
import signal
import shutil
import time
import sys
import stat
import shlex
import tarfile
import threading
import zipfile

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
from src.models.constants import (
    is_windows, is_macos, is_linux,
    TIMEOUT_SHORT_CMD, TIMEOUT_OPENCLAW_CMD, TIMEOUT_INSTALL_CMD,
    TIMEOUT_NODE_MSI_INSTALL, TIMEOUT_GIT_INSTALL_MAX, TIMEOUT_BUILD_CMD,
    NODEJS_MSI_MIRRORS, NODEJS_PKG_MIRRORS,
    REGISTRY_NPM_MIRROR, REGISTRY_CLAWHUB,
    NODEJS_VERSION, NODEJS_ARCHIVE_MIRROR_BASES,
)
from src.models.utils import ensure_dir_in_path, ensure_local_bin_in_path, force_rmtree, safe_tar_extract
from src.contracts.define_base_installer import BaseInstaller
from src.contracts.define_decorators import log_method


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

        # 平台标识（用于 resources/ 子目录名）
        self._platform = "windows" if is_windows() else ("macos" if is_macos() else "linux")

        # Node.js 本地安装目录（tarball/zip 解压目标，无需管理员权限）
        self._node_dir: Path = Path.home() / ".openclaw-node"

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
                # macOS：检查 curl（系统自带），然后设置内部 git 避免 Xcode CLT 弹窗
                self._log("检查前置依赖 (git, curl)...")

                # curl：macOS 自带，极少缺失
                try:
                    result = subprocess.run(["curl", "--version"], capture_output=True, shell=False, timeout=TIMEOUT_SHORT_CMD)
                    if result.returncode != 0:
                        raise FileNotFoundError()
                except FileNotFoundError:
                    return InstallResult(
                        status=InstallStatus.FAILED,
                        message="缺少 curl",
                        error_message="系统未找到 curl，macOS 通常自带 curl，若缺失请重新安装系统。",
                        log_lines=self.log_lines.copy(),
                        duration_seconds=time.time() - self.start_time,
                    )

                # git：使用安装器内置的 git，绕过 Xcode CLT 弹窗
                # _setup_git_if_needed() 会检测 Xcode CLT 是否已安装，
                # 已安装则直接使用系统 git，未安装则解压并使用内部 git。
                self._setup_git_if_needed()

                # 验证 git 可用
                try:
                    result = subprocess.run(["git", "--version"], capture_output=True, shell=False, timeout=TIMEOUT_SHORT_CMD)
                    if result.returncode != 0:
                        raise FileNotFoundError()
                except FileNotFoundError:
                    return InstallResult(
                        status=InstallStatus.FAILED,
                        message="Git 不可用",
                        error_message="系统未找到可用的 Git，且安装器内置的 Git 也无法使用。请确保资源包中包含 git 文件。",
                        log_lines=self.log_lines.copy(),
                        duration_seconds=time.time() - self.start_time,
                    )

                self._log("前置依赖已就绪")

            else:
                # Linux：仅需 git/curl；Node.js 由 _install_nodejs() 统一安装，pnpm 由 _step2 安装
                self._log("检查前置依赖 (git, curl)...")
                missing_deps = []
                for cmd, name in [("git", "Git"), ("curl", "curl")]:
                    try:
                        result = subprocess.run([cmd, "--version"], capture_output=True, shell=False, timeout=TIMEOUT_SHORT_CMD)
                        if result.returncode != 0:
                            missing_deps.append(name)
                    except FileNotFoundError:
                        missing_deps.append(name)

                if missing_deps:
                    self._log(f"缺少依赖: {', '.join(missing_deps)}，将在系统授权后自动安装")
                    # 使用 pkexec 安装 git/curl（apt 需要 root）
                    self._log("正在安装系统依赖 (git, curl)...")
                    self._log("[授权提示] 即将通过 pkexec 执行系统级安装命令：")
                    self._log("  apt update && apt-get install -y git curl")
                    pkexec_dep_cmd = (
                        "pkexec bash -c '"
                        "apt update >/dev/null 2>&1; "
                        "apt-get install -y git curl >/dev/null 2>&1; "
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
                            error_message=f"自动安装 git/curl 失败，请确保网络畅通后重试。\n错误：{err}",
                            log_lines=self.log_lines.copy(),
                            duration_seconds=time.time() - self.start_time,
                            error_detail=InstallErrorDetail(
                                category=ErrorCategory.NETWORK_UNKNOWN,
                                stage="INSTALLING",
                                context="Linux 系统依赖安装 (pkexec)",
                                raw_error=err,
                                user_message="Linux 系统依赖安装失败",
                                suggestion="1. 确保网络畅通后重试\n2. 手动执行: sudo apt install -y git curl",
                            ),
                        )
                    self._log("系统依赖安装完成")
                else:
                    self._log("前置依赖已就绪")

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
                    if force_rmtree(d, self._log):
                        self._log(f"已清理残留目录: {d}")
                    else:
                        self._log(f"清理残留目录失败 {d}")

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
        """语义化别名:转发到基类的 _check_cancelled,保持现有调用站点稳定。"""
        return self._check_cancelled()

    def _run_shell_cmd(self, cmd: str, timeout: float = 300) -> ShellResult:
        """在独立 shell 中执行命令，复用 run_shell 的错误分类与诊断能力。"""
        return run_shell(cmd, timeout=timeout, env=self._inst_env)

    def _which_cmd(self, cmd_name: str) -> bool:
        """检测命令是否在 PATH 中可用。"""
        if self._inst_is_win:
            return self._run_shell_cmd(f"where {cmd_name}", timeout=TIMEOUT_SHORT_CMD).returncode == 0
        return subprocess.run(
            ["which", cmd_name], capture_output=True, timeout=TIMEOUT_SHORT_CMD, env=self._inst_env
        ).returncode == 0

    def _verify_command(self, cmd_name: str) -> bool:
        """验证命令是否在 PATH 中可解析。"""
        if self._inst_is_win:
            return self._run_shell_cmd(f"where {cmd_name}", timeout=TIMEOUT_NODE_MSI_INSTALL).returncode == 0
        return subprocess.run(
            ["which", cmd_name], capture_output=True, timeout=TIMEOUT_SHORT_CMD, env=self._inst_env
        ).returncode == 0

    def _resolve_nodejs_archive_name(self) -> Optional[str]:
        """根据当前平台解析 Node.js 预编译归档文件名。

        Returns:
            归档文件名(如 node-v22.14.0-darwin-arm64.tar.gz),不支持的平 台返回 None。
        """
        system = platform.system().lower()
        machine = platform.machine().lower()
        version = NODEJS_VERSION
        if system == "darwin":
            if machine in ("arm64", "aarch64"):
                return f"node-v{version}-darwin-arm64.tar.gz"
            return f"node-v{version}-darwin-x64.tar.gz"
        elif system == "windows" or system == "win32":
            return f"node-v{version}-win-x64.zip"
        else:  # linux
            if machine in ("arm64", "aarch64"):
                return f"node-v{version}-linux-arm64.tar.xz"
            return f"node-v{version}-linux-x64.tar.xz"

    def _resolve_resource_dir(self) -> str:
        """解析资源目录路径。

        按以下优先级查找 resources/{platform}/ 目录:
        1. PyInstaller 运行时: sys._MEIPASS 临时目录
        2. 可执行文件同目录(支持分发时 resources/ 与 exe 同目录)
        3. 开发模式: 项目根目录下的 resources/

        Returns:
            资源目录绝对路径。
        """
        # PyInstaller 模式
        if getattr(sys, "_MEIPASS", None):
            return os.path.join(sys._MEIPASS, "resources", self._platform)

        # 可执行文件同目录模式
        exe_dir = Path(sys.executable).parent.resolve()
        candidate = exe_dir / "resources" / self._platform
        if candidate.exists():
            return str(candidate)

        # 开发模式: 从 adapters/ 向上三级到项目根
        project_root = Path(__file__).parent.parent.parent.resolve()
        return str(project_root / "resources" / self._platform)

    def _install_nodejs(self) -> Optional[InstallResult]:
        """从网络镜像下载并安装 Node.js 预编译二进制包。

        在线版安装器不打包 Node.js，而是从国内镜像下载 tarball/zip，
        解压到 ~/.openclaw-node/ 并加入 PATH。无需管理员权限。
        """
        import urllib.request
        import tempfile

        # 检测现有 Node.js
        if self._check_nodejs_version():
            self._log("Node.js 已满足要求,跳过安装")
            return None

        self._log("正在安装 Node.js 22...")
        if self._inst_on_progress:
            self._inst_on_progress(
                InstallProgress(
                    stage=InstallStage.INSTALLING,
                    progress_percent=10,
                    message="正在安装系统依赖...",
                    current_task="安装 Node.js",
                )
            )

        # 确定归档文件名
        filename = self._resolve_nodejs_archive_name()
        if not filename:
            return InstallResult(
                status=InstallStatus.FAILED,
                message="不支持的系统架构",
                error_message="当前系统架构不受支持,无法自动安装 Node.js",
                log_lines=self.log_lines.copy(),
                duration_seconds=time.time() - self.start_time,
            )

        # 从镜像源下载
        download_path = None
        for base_url in NODEJS_ARCHIVE_MIRROR_BASES:
            if self.is_cancelled:
                return self._build_cancelled_result()

            url = f"{base_url}/{filename}"
            self._log(f"正在下载 Node.js: {url}")
            try:
                fd, download_path = tempfile.mkstemp(suffix=f"_{filename}")
                os.close(fd)

                req = urllib.request.Request(
                    url,
                    headers={"User-Agent": "OpenClaw-Installer/1.0"},
                )
                with urllib.request.urlopen(req, timeout=180) as response:
                    with open(download_path, "wb") as f:
                        while True:
                            chunk = response.read(8192)
                            if not chunk:
                                break
                            f.write(chunk)

                file_size = os.path.getsize(download_path)
                self._log(f"下载完成: {file_size / 1024 / 1024:.1f} MB")
                if file_size < 10 * 1024 * 1024:
                    self._log("下载文件过小，尝试下一个镜像...")
                    os.remove(download_path)
                    download_path = None
                    continue
                break
            except Exception as e:
                self._log(f"下载失败: {e}")
                if download_path and os.path.exists(download_path):
                    os.remove(download_path)
                    download_path = None
                continue

        if not download_path:
            return InstallResult(
                status=InstallStatus.FAILED,
                message="Node.js 下载失败",
                error_message="无法从任何镜像源下载 Node.js，请检查网络连接后重试",
                log_lines=self.log_lines.copy(),
                duration_seconds=time.time() - self.start_time,
            )

        # 清理旧版本
        if self._node_dir.exists():
            if not force_rmtree(self._node_dir, self._log):
                self._log(f"清理旧 Node.js 目录失败: {self._node_dir}")

        # 解压
        self._node_dir.mkdir(parents=True, exist_ok=True)
        try:
            if download_path.endswith(".zip"):
                with zipfile.ZipFile(download_path, "r") as zf:
                    zf.extractall(self._node_dir)
            else:
                with tarfile.open(download_path, "r:*") as tar:
                    safe_tar_extract(tar, self._node_dir, self._log)
        except (OSError, tarfile.TarError, zipfile.BadZipFile) as e:
            os.remove(download_path)
            return InstallResult(
                status=InstallStatus.FAILED,
                message="Node.js 解压失败",
                error_message=f"Node.js 安装包解压失败: {e}",
                log_lines=self.log_lines.copy(),
                duration_seconds=time.time() - self.start_time,
            )
        finally:
            if os.path.exists(download_path):
                os.remove(download_path)

        # Flatten: 如果解压后只有一个 node-v* 子目录，把内容提到根目录
        subdirs = [d for d in self._node_dir.iterdir() if d.is_dir() and d.name.startswith("node-v")]
        if len(subdirs) == 1:
            subdir = subdirs[0]
            for item in subdir.iterdir():
                target = self._node_dir / item.name
                if target.exists():
                    if item.is_dir():
                        shutil.rmtree(target)
                    else:
                        target.unlink()
                shutil.move(str(item), str(target))
            subdir.rmdir()
            self._log(f"已 flatten 目录: {subdir.name}")

        # 确定 PATH 中的可执行目录
        if is_windows():
            node_bin = str(self._node_dir)
        else:
            node_bin = str(self._node_dir / "bin")

        # 加入当前进程 PATH
        if os.path.exists(node_bin):
            current_path = os.environ.get("PATH", "")
            if node_bin not in current_path.split(os.pathsep):
                os.environ["PATH"] = node_bin + os.pathsep + current_path
                self._log(f"已将 {node_bin} 加入 PATH")
        else:
            self._log(f"警告: 未找到 Node.js bin 目录 {node_bin}")

        # macOS/Linux: 持久化到 shell 配置文件
        if not is_windows():
            ensure_dir_in_path(node_bin, self._log)

        # 验证
        if not self._check_nodejs_version():
            return InstallResult(
                status=InstallStatus.FAILED,
                message="Node.js 安装后验证失败",
                error_message="Node.js 已安装但版本检测失败,请尝试重启程序后重试",
                log_lines=self.log_lines.copy(),
                duration_seconds=time.time() - self.start_time,
            )

        self._log("Node.js 安装成功")
        return None

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
        """步骤 3：从 Gitee 克隆仓库，带自动重试机制。

        大仓库克隆偶尔因网络波动导致 RPC failed / early EOF，
        支持最多 3 次重试，遇到可重试网络错误时自动清理残留并重试。
        """
        self._log("正在从 Gitee 下载 openclaw-cn...")
        if self._inst_on_progress:
            self._inst_on_progress(InstallProgress(stage=InstallStage.DOWNLOADING, progress_percent=20, message="正在下载 OpenClaw...", current_task="git clone"))

        # 保险：如果目标目录仍存在（前期清理未彻底），先强制删除
        if self._inst_project_dir.exists():
            self._log(f"目标目录仍存在，尝试强制删除: {self._inst_project_dir}")
            force_rmtree(self._inst_project_dir, self._log)
            if self._inst_project_dir.exists():
                return InstallResult(
                    status=InstallStatus.FAILED, message="目录清理失败",
                    error_message=f"无法删除旧目录 {self._inst_project_dir}，可能是文件权限问题。\n\n建议：\n1. 手动执行: chmod -R +w {self._inst_project_dir} && rm -rf {self._inst_project_dir}\n2. 重启电脑后重试",
                    log_lines=self.log_lines.copy(), duration_seconds=time.time() - self.start_time,
                )

        max_retries = 3
        for attempt in range(1, max_retries + 1):
            if self.is_cancelled:
                return self._build_cancelled_result()

            self._log(f"第 {attempt}/{max_retries} 次尝试克隆...")
            clone_result = self._run_shell_cmd(
                f'git clone https://gitee.com/OpenClaw-CN/openclaw-cn.git {shlex.quote(str(self._inst_project_dir))}',
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

            if clone_result.returncode == 0:
                self._log("仓库克隆完成")
                return None

            # 判断是否为可重试的网络错误
            err_text = (clone_result.stderr or "").lower()
            retryable = any(k in err_text for k in [
                "rpc failed", "early eof", "transfer closed",
                "unexpected disconnect", "index-pack",
            ])
            if retryable and attempt < max_retries:
                self._log(f"克隆中断（网络波动），{3 if attempt == 1 else 1} 秒后重试...")
                time.sleep(3 if attempt == 1 else 1)
                # 清理可能残留的不完整目录
                if self._inst_project_dir.exists():
                    force_rmtree(self._inst_project_dir, self._log)
                continue

            # 非网络错误或已用完重试次数
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

    def _resolve_native_cache_dir(self) -> Optional[str]:
        """解析原生缓存资源目录路径。

        按以下优先级查找 resources/native-cache/matrix-sdk-crypto：
        1. PyInstaller 运行时：sys._MEIPASS 临时目录
        2. 可执行文件同目录
        3. 开发模式：项目根目录下

        Returns:
            缓存目录路径，若不存在则返回 None。
        """
        cache_subdir = "resources/native-cache/matrix-sdk-crypto"
        # PyInstaller 模式
        if getattr(sys, "_MEIPASS", None):
            candidate = os.path.join(sys._MEIPASS, cache_subdir)
            if os.path.isdir(candidate):
                return candidate

        # 可执行文件同目录模式
        exe_dir = Path(sys.executable).parent.resolve()
        candidate = exe_dir / cache_subdir
        if candidate.exists():
            return str(candidate)

        # 开发模式：从 adapters/ 向上两级到项目根
        project_root = Path(__file__).parent.parent.parent.resolve()
        candidate = project_root / cache_subdir
        if candidate.exists():
            return str(candidate)

        return None

    def _step5b_inject_native_cache(self) -> None:
        """步骤 5b：注入 matrix-sdk-crypto 预编译原生缓存。

        pnpm install 执行后，matrix-sdk-crypto 的 postinstall 脚本可能因网络问题
        未能从 GitHub 下载预编译的 .node 文件。本步骤作为兜底：若检测到 .node
        文件缺失，则使用安装器内置的缓存副本进行注入，避免后续触发 Rust 源码编译。
        """
        cache_dir = self._resolve_native_cache_dir()
        if not cache_dir:
            self._log("未找到原生缓存目录，跳过注入")
            return

        # 确定当前平台对应的 .node 文件名
        system = platform.system().lower()
        machine = platform.machine().lower()
        if system == "darwin":
            if machine in ("arm64", "aarch64"):
                node_file = "matrix-sdk-crypto.darwin-arm64.node"
            else:
                node_file = "matrix-sdk-crypto.darwin-x64.node"
        elif system == "windows" or system == "win32":
            if machine == "arm64":
                node_file = "matrix-sdk-crypto.win32-arm64-msvc.node"
            elif machine in ("amd64", "x86_64", "x64"):
                node_file = "matrix-sdk-crypto.win32-x64-msvc.node"
            else:
                node_file = "matrix-sdk-crypto.win32-ia32-msvc.node"
        else:  # linux
            if machine in ("arm64", "aarch64"):
                node_file = "matrix-sdk-crypto.linux-arm64-gnu.node"
            else:
                node_file = "matrix-sdk-crypto.linux-x64-gnu.node"

        cache_file = os.path.join(cache_dir, node_file)
        if not os.path.exists(cache_file):
            self._log(f"原生缓存文件不存在: {node_file}")
            return

        # 在 pnpm virtual store 中查找 matrix-sdk-crypto 的实际安装路径
        import glob
        project_dir = self._inst_project_dir
        search_pattern = str(
            project_dir / "node_modules" / ".pnpm" / "@matrix-org+matrix-sdk-crypto-nodejs@*"
            / "node_modules" / "@matrix-org" / "matrix-sdk-crypto-nodejs"
        )
        matches = glob.glob(search_pattern)
        if not matches:
            self._log("未找到 matrix-sdk-crypto 安装路径，跳过注入")
            return

        target_dir = matches[0]
        target_file = os.path.join(target_dir, node_file)

        # 若目标文件已存在且大小正常，则无需注入
        if os.path.exists(target_file):
            existing_size = os.path.getsize(target_file)
            cache_size = os.path.getsize(cache_file)
            if existing_size == cache_size:
                self._log(f"matrix-sdk-crypto 原生文件已存在且大小匹配，跳过注入")
                return
            self._log(f"matrix-sdk-crypto 原生文件大小不匹配 ({existing_size} != {cache_size})，执行替换")

        try:
            shutil.copy2(cache_file, target_file)
            self._log(f"已注入 matrix-sdk-crypto 原生缓存: {node_file}")
        except OSError as e:
            self._log(f"注入 matrix-sdk-crypto 原生缓存失败: {e}")

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
        """步骤 9:创建全局命令 wrapper。

        平台差异:
        - Windows:bin_dir 优先取 npm.cmd bin -g 的输出,失败时回退 ~/AppData/Roaming/npm。
        - *nix:固定使用 ~/.local/bin。

        实际写文件由基类的 _write_command_wrappers 处理,
        本方法只负责选 bin_dir、注入 CLAWHUB_REGISTRY 和 PATH 维护。

        Returns:
            命令包装器所在的目录路径(空字符串表示失败或未创建)。
        """
        self._log("正在创建全局命令...")
        if self._inst_is_win:
            npm_bin_result = self._run_shell_cmd("npm.cmd bin -g", timeout=TIMEOUT_NODE_MSI_INSTALL)
            if npm_bin_result.returncode == 0 and npm_bin_result.stdout.strip():
                npm_bin_dir = npm_bin_result.stdout.strip()
            else:
                npm_bin_dir = str(Path(os.path.expanduser(r"~\AppData\Roaming\npm")))
            self._write_command_wrappers(
                Path(npm_bin_dir),
                self._inst_project_dir,
                registry=REGISTRY_CLAWHUB,
            )
            return npm_bin_dir
        else:
            local_bin = Path(os.path.expanduser("~/.local/bin"))
            self._write_command_wrappers(
                local_bin,
                self._inst_project_dir,
                registry=REGISTRY_CLAWHUB,
            )
            ensure_local_bin_in_path(self._inst_on_log)
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

            result = self._install_nodejs()
            if result:
                return result

            self._log("Node.js 安装完成，PATH 已刷新")

        # 无论 Node.js 是新安装还是已存在，都同步 PATH 到 _inst_env
        # _check_nodejs_version 可能已将 nvm/fnm/Homebrew 的 bin 加入 os.environ
        self._inst_env["PATH"] = os.environ.get("PATH", "")

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

        # 步骤 5b：注入 matrix-sdk-crypto 预编译原生缓存（兜底）
        self._step5b_inject_native_cache()

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

        # taskkill 仅在 Windows 上存在，其他平台跳过
        if is_windows():
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
