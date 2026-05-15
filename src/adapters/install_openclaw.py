import subprocess
import os
import platform  # 仅用于 platform.machine() 获取 CPU 架构；OS 判断统一走 is_windows/is_macos
import signal
import shutil
import time
import sys
import stat
import tarfile
import threading
import zipfile

from pathlib import Path
from typing import List, Callable, Optional

from src.models.constants import (
    is_windows, is_macos,
    TIMEOUT_SHORT_CMD, TIMEOUT_OPENCLAW_CMD, TIMEOUT_INSTALL_CMD,
    TIMEOUT_NODE_MSI_INSTALL, TIMEOUT_GIT_INSTALL_MAX, TIMEOUT_BUILD_CMD,
    NODEJS_MSI_MIRRORS, NODEJS_PKG_MIRRORS,
    REGISTRY_NPM_MIRROR, REGISTRY_CLAWHUB,
    NODEJS_VERSION, NODEJS_ARCHIVE_MIRROR_BASES,
    NPMMIRROR_BINARY_BASE, PNPM_REQUIRED_MAJOR,
)

# 只在非 Windows 平台导入 select（Windows 下 select.select 不支持文件描述符）
if not is_windows():
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
from src.models.utils import (
    cleanup_orphan_residues,
    ensure_dir_in_path,
    ensure_local_bin_in_path,
    force_rmtree,
    safe_tar_extract,
    windows_hidden_subprocess_kwargs,
)
from src.contracts.define_base_installer import BaseInstaller
from src.contracts.define_decorators import log_method


class OpenClawInstaller(BaseInstaller):
    """OpenClaw 安装器 - 负责底层命令执行与全平台安装流程调度。

    设计要点：
    - 所有耗时操作均通过回调（on_progress / on_log）向 UI 层反馈，避免阻塞主线程。
    - 安装流程为"在线构建"模式：不预置 OpenClaw 本体，而是从 Gitee 拉取源码后本地编译。
    - 平台差异（Windows / macOS）集中在 Node.js 安装方式与命令包装器生成上，其余步骤尽量统一。
    """

    def __init__(self, os_type: str = None) -> None:
        """初始化安装器，自动识别或接受外部传入的操作系统类型。

        Args:
            os_type: 可选，强制指定操作系统类型（"windows" / "macos"）。
                     默认通过 is_windows()/is_macos() 自动判断。
        """
        super().__init__()
        if os_type:
            self.os_type = os_type
        elif is_windows():
            self.os_type = "windows"
        else:
            # 仅支持 Win/Mac;Linux 在入口已被拦截
            self.os_type = "macos"

        self.process: Optional[subprocess.Popen] = None
        self.start_time: float = 0.0

        # 平台标识（用于 resources/ 子目录名）
        self._platform = "windows" if is_windows() else "macos"

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

            else:
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

            # ========================
            # 阶段 1：清理残留目录
            # ========================
            # 避免旧版本文件与新构建产物冲突。注意:如果是从"重新下载"进来的,
            # ReinstallWorker 已经清理过 ~/openclaw-cn 和 ~/.openclaw,这里会跳过;
            # 但 npm 全局 node_modules 目录(Windows)可能残留,仍需兜底。
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
            has_cleanup = any(os.path.exists(d) for d in cleanup_dirs)
            if has_cleanup:
                self._log("正在清理残留目录...")
            for d in cleanup_dirs:
                if os.path.exists(d):
                    if force_rmtree(d, self._log):
                        self._log(f"已清理残留目录: {d}")
                    else:
                        self._log(f"清理残留目录失败 {d}")
            # 顺便扫一下用户主目录里历史 .residue 残渣(上次安装异常退出留下的),
            # 后台 daemon 清理,不阻塞当前流程
            cleanup_orphan_residues(os.path.expanduser("~"), self._log)

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
        machine = platform.machine().lower()
        version = NODEJS_VERSION
        if is_macos():
            if machine in ("arm64", "aarch64"):
                return f"node-v{version}-darwin-arm64.tar.gz"
            return f"node-v{version}-darwin-x64.tar.gz"
        elif is_windows():
            return f"node-v{version}-win-x64.zip"
        return None  # 仅支持 macOS/Windows

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
                        # Python 3.12 shutil.rmtree 在只读文件场景会留下子树,统一走 force_rmtree
                        force_rmtree(target, self._log)
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

        # macOS: 持久化到 shell 配置文件
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

    def _run_in_project_dir(self, cmd: list[str], silence_timeout: float = 300, progress: InstallProgress = None) -> int:
        """在 project_dir 目录下执行命令，并可选地发送进度更新。

        安全策略：使用 shell=False + cwd 参数，彻底避免命令注入风险。

        Args:
            cmd: 要执行的命令参数列表。
            silence_timeout: 无输出静默超时阈值（秒）。这不是命令总耗时上限，
                而是"连续无输出多久判定假死"的阈值；详见 _run_cmd_with_streaming 文档。
            progress: 可选的进度对象，会在执行前推送到 UI。
        """
        if progress and self._inst_on_progress:
            self._inst_on_progress(progress)
        return self._run_cmd_with_streaming(
            cmd, self._inst_env, silence_timeout,
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
        """步骤 2:启用 corepack 并安装 pnpm shim。

        关键转折(2026-05 实测):之前用 `npm install -g pnpm@<major>` 全局装 pnpm 是错的。
        理由:Node 24 内置的 corepack 会在 PATH 里部署 `pnpm` shim,这个 shim 进入项目
        目录时会自动读 package.json 的 `packageManager` 字段、动态切换到指定的 pnpm 版本。
        OpenClaw 项目锁的是 `pnpm@10.23.0`,corepack 会在 cwd 切到这个版本运行。
        而 `npm install -g pnpm` **会覆盖 corepack shim**,装一个固定版本(如 10.33.4),
        从此 pnpm 不再读项目 packageManager,版本永远停在 10.33.4。
        即使大版本对了(10),小版本与 OpenClaw lockfile 不匹配也会撞 hoist 行为差异
        (实测崩在 yargs/cliui ESM 解析,Mac 同 pnpm 10.23.0 跑通,Win 10.33.4 不通)。

        所以正确做法:`corepack enable pnpm` 让 PATH 上有 corepack shim,后续 pnpm install
        在项目目录跑会自动用 10.23.0,行为与 Mac 完全对齐。

        前提:Node 22.12+ 内置 corepack。Node 自动安装那一步已确保版本满足。
        """
        self._log("配置 pnpm 环境(通过 corepack)...")
        if self._inst_on_progress:
            self._inst_on_progress(InstallProgress(
                stage=InstallStage.INSTALLING, progress_percent=15,
                message="正在配置 pnpm...", current_task="corepack enable pnpm",
            ))

        # 只跑一次 `corepack enable pnpm`,把 shim 写到 Node 的 bin 目录(Win:
        # nvm4w/nodejs/,Mac: ~/.nvm/.../bin/),从此 PATH 里的 `pnpm` 就是
        # corepack shim。已启用过的话再跑也幂等。
        # 不再做 `corepack prepare` 预下载、`pnpm --version` 验证 —— 后续 _step5
        # 进项目目录跑 pnpm install 时,corepack shim 会自动读 packageManager 字段
        # 下载并切到项目要求的版本(实测会暂停几秒下 ~3MB,可接受)。
        # enable 失败才 fallback 到 npm install -g(常见于 macOS brew 装 Node 的
        # EACCES,corepack enable 写 bin 目录被拒)。
        corepack_cmd = "corepack.cmd" if self._inst_is_win else "corepack"
        enable_res = self._run_shell_cmd(f"{corepack_cmd} enable pnpm", timeout=60)
        if enable_res.returncode != 0:
            err = (enable_res.stderr or enable_res.stdout or "").strip()
            self._log(f"corepack enable pnpm 失败: {err}")
            self._log(f"退化到 npm install -g pnpm@{PNPM_REQUIRED_MAJOR}(corepack 不可用)...")
            return self._fallback_npm_install_pnpm()

        self._log("pnpm 已就绪(corepack shim,进项目目录后会自动切到 lockfile 锁定的版本)")
        return None

    def _fallback_npm_install_pnpm(self) -> Optional[InstallResult]:
        """corepack 不可用时的兜底:用 npm install -g pnpm@<major> 全局装。

        副作用警告:这会覆盖 corepack shim,装一个固定小版本的 pnpm。可能导致
        与项目 lockfile 不匹配的小版本兼容问题(如 yargs/cliui ESM 解析差异)。
        但总比根本没 pnpm 强,作为 corepack 失败时的最后一招。
        """
        self._log(f"正在通过 npm 全局安装 pnpm@{PNPM_REQUIRED_MAJOR}...")
        npm_cmd = "npm.cmd" if self._inst_is_win else "npm"
        pnpm_install = self._run_shell_cmd(
            f"{npm_cmd} install -g pnpm@{PNPM_REQUIRED_MAJOR}", timeout=120
        )

        if pnpm_install.returncode != 0 and self.os_type == "macos":
            err_text = pnpm_install.stderr.strip() if pnpm_install.stderr else ""
            if "EACCES" in err_text or "permission denied" in err_text.lower():
                self._log("普通权限安装 pnpm 失败,正在弹出密码框申请管理员权限...")
                install_script = (
                    f'do shell script "cd /tmp && export PATH=/usr/local/bin:/usr/bin:/bin:$PATH '
                    f'&& npm install -g pnpm@{PNPM_REQUIRED_MAJOR}" with administrator privileges'
                )
                pnpm_install = subprocess.run(
                    ["osascript", "-e", install_script],
                    capture_output=True, text=True, timeout=TIMEOUT_INSTALL_CMD,
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
        self._log("pnpm 安装完成(npm 全局安装方式)")

        # 把 npm global bin 加到 PATH,确保后续能找到 pnpm.cmd
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
        return None

    def _step3_clone_repository(self) -> Optional[InstallResult]:
        """步骤 3：从 Gitee 克隆仓库，带自动重试机制。

        大仓库克隆偶尔因网络波动导致 RPC failed / early EOF，
        支持最多 3 次重试，遇到可重试网络错误时自动清理残留并重试。
        """
        self._log("正在从 Gitee 下载 openclaw-cn...")
        if self._inst_on_progress:
            self._inst_on_progress(InstallProgress(stage=InstallStage.DOWNLOADING, progress_percent=20, message="正在下载 OpenClaw...", current_task="git clone"))

        # 保险：如果目标目录仍存在（前期清理未彻底），先强制删除。
        # 删不掉就改名(force_rmtree 内部已有 rename 兜底),改名也失败就用临时目录。
        target_dir = str(self._inst_project_dir)
        if self._inst_project_dir.exists():
            self._log(f"目标目录仍存在,尝试清理: {self._inst_project_dir}")
            force_rmtree(self._inst_project_dir, self._log)
        if self._inst_project_dir.exists():
            # force_rmtree 两次都失败了(rmdir + rename),目录被外部进程锁死。
            # 不硬阻断安装,改为 clone 到临时目录再 rename 过去。
            import time as _ctime
            fallback_dir = Path(f"{target_dir}.tmp.{int(_ctime.time())}")
            self._log(f"目录被占用,clone 到临时位置: {fallback_dir}")
            self._inst_project_dir = fallback_dir

        max_retries = 3
        for attempt in range(1, max_retries + 1):
            if self.is_cancelled:
                return self._build_cancelled_result()

            self._log(f"第 {attempt}/{max_retries} 次尝试克隆...")
            # 用列表参数 + shell=False 调用，规避 Windows 路径含空格时 shlex.quote 转义错误
            #
            # 几个关键参数:
            # - --depth 1 + --single-branch: 浅克隆,只拉默认分支的 HEAD 这一个 commit。
            #   安装器只需要源码用于 pnpm install/build,不需要历史。完整克隆 6500+ 文件
            #   带全部历史在 Gitee 国内网络上经常 RPC failed / early EOF;浅克隆把传输量
            #   缩到几十 MB,断流概率大幅下降。
            # - http.postBuffer=524288000: HTTP 接收缓冲增大到 500MB(默认 1MB)。
            #   sideband 包写满缓冲就会触发 "transfer closed with outstanding read data",
            #   这是用户日志里那个 curl 18 的根因。
            # - core.compression=0: 关 client 端压缩。Gitee 服务端已经压缩过,客户端再
            #   解压+压缩反而占 CPU 拖慢传输,关掉对网络弱机器有帮助。
            clone_result = run_shell(
                [
                    "git",
                    "-c", "http.postBuffer=524288000",
                    "-c", "core.compression=0",
                    "clone",
                    "--depth", "1",
                    "--single-branch",
                    "https://gitee.com/OpenClaw-CN/openclaw-cn.git",
                    str(self._inst_project_dir),
                ],
                timeout=TIMEOUT_INSTALL_CMD,
                env=self._inst_env,
                context="从 Gitee 克隆 openclaw-cn 仓库",
                stage="DOWNLOADING",
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
        """步骤 4：设置 pnpm 国内镜像，并为已知原生包注入 binary 镜像 env var。

        - registry 切到 npmmirror（npm tarball 走国内）。
        - sharp 通过 npm_config_sharp_libvips_binary_host 切到 npmmirror 二进制镜像。
        - electron / electron-builder 通过 ELECTRON_MIRROR 等切到 npmmirror。
        - matrix-sdk-crypto / node-llama-cpp 没有官方镜像 env var，硬编码 GitHub URL，
          只能靠 _step5 的重试机制兜底。
        """
        self._run_in_project_dir(['pnpm', 'config', 'set', 'registry', REGISTRY_NPM_MIRROR], silence_timeout=TIMEOUT_OPENCLAW_CMD)

        # sharp：postinstall 时下载 libvips 预编译产物，npmmirror 镜像了 sharp-libvips 全量
        self._inst_env["npm_config_sharp_libvips_binary_host"] = f"{NPMMIRROR_BINARY_BASE}/sharp-libvips"
        # 旧版 sharp 用 sharp_binary_host，一并设上确保兼容
        self._inst_env["npm_config_sharp_binary_host"] = f"{NPMMIRROR_BINARY_BASE}/sharp"
        # electron / playwright 等常见原生包的镜像（同 ~/.npmrc 里写 ELECTRON_MIRROR 的效果）
        self._inst_env["ELECTRON_MIRROR"] = f"{NPMMIRROR_BINARY_BASE}/electron/"
        self._inst_env["ELECTRON_BUILDER_BINARIES_MIRROR"] = f"{NPMMIRROR_BINARY_BASE}/electron-builder-binaries/"
        self._inst_env["PLAYWRIGHT_DOWNLOAD_HOST"] = f"{NPMMIRROR_BINARY_BASE}/playwright"
        # node-sass / sass-embedded 等
        self._inst_env["SASS_BINARY_SITE"] = f"{NPMMIRROR_BINARY_BASE}/node-sass"

        # node-llama-cpp 的 postinstall 默认跳过。原因:
        # 1. 它会从 GitHub Releases 下 GPU/CPU 预编译,国内网慢且经常 0xC0000005 段错误
        #    (常见于缺 VC++ 运行库 / Defender 拦截 .node 文件 / 老 CPU 不支持 AVX2)。
        # 2. OpenClaw 主流程不依赖本地 llama 推理(使用 cloud API),跳过对核心功能无影响。
        # 3. 如未来需要本地推理,删掉这一行即可恢复(用户需自行确保 VC++ 运行库等环境)。
        # 该 env var 是 node-llama-cpp 官方支持的开关,见其 config.js。
        # self._inst_env["NODE_LLAMA_CPP_SKIP_DOWNLOAD"] = "true"

        self._log("已注入原生包二进制镜像环境变量")

    # pnpm install 失败重试时识别的「可重试」错误关键词（小写匹配）。
    # native crash 错误码（3221225477=0xC0000005, 134=SIGABRT, 139=SIGSEGV）单独判定，
    # 这类崩溃重试也无效，应该尽早 bail。
    _PNPM_RETRYABLE_KEYWORDS = (
        "etimedout", "econnreset", "econnrefused", "enotfound",
        "socket hang up", "network", "fetch failed", "tunneling socket",
        "request to https", "getaddrinfo", "transfer closed",
        "ssl_error", "tls_error", "unable to verify",
    )
    # 这些 exit code 是 native 段错误/中止，不是网络问题，重试无意义
    _NATIVE_CRASH_EXIT_CODES = (3221225477, 134, 139, 3221225725, 3221225495)

    def _step5_pnpm_install_deps(self) -> Optional[InstallResult]:
        """步骤 5：pnpm install（安装项目依赖），支持网络错误下的多次重试。

        策略：
        - 最多 3 次尝试,每次都用普通 `pnpm install`(不加 --prefer-offline)。
          之前用 --prefer-offline 重试踩过坑:首次失败时 store 状态不完整,
          再加 --prefer-offline 会让 pnpm 优先用残缺 store 跳过远程下载,
          导致 .bin wrapper / esbuild optional deps 找不到文件而 ENOENT。
          所以重试时还是走完整 install,慢一点但保证一致性。
        - 失败后看 exit code & stderr:
          - native crash 码(3221225477/134/139 等)→ 不重试,直接 bail,
            提示装 VC++ 运行库或关杀软。
          - 网络关键词或不可分类 → 普通 install 重试,失败的 postinstall
            会在重新拉一遍 tarball 后再跑。
        - 重试前先把 node_modules 删掉,避免脏 store 误导 pnpm。
        """
        self._log("正在安装依赖...")
        if self._inst_on_progress:
            self._inst_on_progress(InstallProgress(stage=InstallStage.INSTALLING, progress_percent=35, message="正在安装依赖...", current_task="pnpm install"))

        max_attempts = 3
        last_rc = 0
        last_recent_logs = ""
        node_modules_dir = self._inst_project_dir / "node_modules"

        for attempt in range(1, max_attempts + 1):
            if self.is_cancelled:
                return self._build_cancelled_result()

            # 重试时清掉上次残缺的 node_modules,避免脏 store 让 pnpm 误判已安装。
            # 第一次进来 node_modules 不存在,跳过。
            if attempt > 1 and node_modules_dir.exists():
                self._log("清理上次残缺的 node_modules 后重试...")
                force_rmtree(node_modules_dir, self._log)

            cmd = ['pnpm', 'install']
            self._log(f"第 {attempt}/{max_attempts} 次尝试 pnpm install...")

            rc = self._run_in_project_dir(cmd, silence_timeout=TIMEOUT_BUILD_CMD)
            if rc == 0:
                if attempt > 1:
                    self._log(f"pnpm install 在第 {attempt} 次尝试时成功")
                return None

            last_rc = rc
            last_recent_logs = "\n".join(self.log_lines[-30:])

            # native crash:不可重试,直接 bail 给出有针对性的提示
            if rc in self._NATIVE_CRASH_EXIT_CODES:
                self._log(f"检测到原生模块崩溃(exit code {rc}),不再重试")
                break

            # 判断 stderr 是否含可重试网络关键词;不含也允许重试,但提示"非典型错误"
            stderr_lower = last_recent_logs.lower()
            is_network_err = any(k in stderr_lower for k in self._PNPM_RETRYABLE_KEYWORDS)
            if attempt < max_attempts:
                if is_network_err:
                    self._log(f"检测到网络错误,{2 if attempt == 1 else 3} 秒后重试...")
                else:
                    self._log(f"pnpm install 失败(exit code {rc}),{2 if attempt == 1 else 3} 秒后重试...")
                time.sleep(2 if attempt == 1 else 3)

        # 所有重试均失败,根据最后一次的错误特征给出诊断
        if last_rc in self._NATIVE_CRASH_EXIT_CODES:
            # 0xC0000005 / SIGSEGV / SIGABRT:原生模块崩溃,常见原因是杀软拦截 .node。
            # 实测中现代 Windows(Win10/11)出厂或日常使用基本都已带 VC++ 运行库,
            # 故不再自动下载/安装 vc_redist;仅在错误提示中保留链接,让极少数用户自行处理。
            return InstallResult(
                status=InstallStatus.FAILED, message="原生模块崩溃",
                error_message=(
                    f"依赖安装时原生模块崩溃(exit code {last_rc})。\n\n"
                    f"常见原因:\n"
                    f"1. 杀毒软件/Windows Defender 拦截了 .node 文件\n"
                    f"   建议: 暂时关闭实时保护后重试\n"
                    f"2. 缺少 Visual C++ 运行库(罕见,现代 Windows 大多自带)\n"
                    f"   下载地址: https://aka.ms/vs/17/release/vc_redist.x64.exe\n"
                    f"3. CPU 不支持某些指令集(老机器需特殊编译)\n"
                ),
                log_lines=self.log_lines.copy(), duration_seconds=time.time() - self.start_time,
                error_detail=InstallErrorDetail(
                    category=ErrorCategory.PROCESS_CRASHED,
                    stage="INSTALLING",
                    context="执行 pnpm install 时原生模块 postinstall 崩溃",
                    raw_error=f"returncode={last_rc}\n最近日志:\n{last_recent_logs}",
                    user_message=f"原生模块崩溃(exit code {last_rc}),通常是杀软拦截 .node 文件",
                    suggestion=(
                        "1. 暂时关闭杀毒软件/Windows Defender 实时保护后重试\n"
                        "2. 若仍失败,安装 Visual C++ 运行库: https://aka.ms/vs/17/release/vc_redist.x64.exe\n"
                        "3. 若是老 CPU,可尝试在 BIOS 中检查 SSE4/AVX 支持"
                    ),
                ),
            )

        # 网络/未知错误:已经重试 3 次仍失败
        return InstallResult(
            status=InstallStatus.FAILED, message="依赖安装失败",
            error_message=(
                "pnpm install 失败(已重试 3 次)。\n\n"
                "可能原因:\n"
                "1. 网络持续不稳定(尤其是访问 GitHub Releases)\n"
                "2. 部分原生模块预编译产物只在 GitHub 有,国内无镜像\n\n"
                "建议:\n"
                "1. 切换网络环境(手机热点 / 公司网 / 家庭网)后重试\n"
                "2. 暂时开启代理/VPN 后重试\n"
                "3. 查看高级模式中的完整日志,定位具体卡在哪个包"
            ),
            log_lines=self.log_lines.copy(), duration_seconds=time.time() - self.start_time,
            error_detail=InstallErrorDetail(
                category=ErrorCategory.NETWORK_UNKNOWN,
                stage="INSTALLING",
                context="执行 pnpm install 安装项目依赖(已重试 3 次)",
                raw_error=f"returncode={last_rc}\n最近日志:\n{last_recent_logs}",
                user_message="pnpm install 失败(已重试 3 次),网络或 GitHub Releases 访问异常",
                suggestion=(
                    "1. 切换网络环境后重试\n"
                    "2. 暂时开启代理/VPN(尤其是能访问 GitHub 的代理)后重试\n"
                    "3. 查看高级模式中的完整日志,定位具体卡在哪个包"
                ),
            ),
        )

    def _step6_build_ui(self) -> Optional[InstallResult]:
        """步骤 6：pnpm ui:build（构建前端界面）。"""
        self._log("正在构建前端界面...")
        if self._inst_on_progress:
            self._inst_on_progress(InstallProgress(stage=InstallStage.INSTALLING, progress_percent=55, message="正在构建前端界面...", current_task="pnpm ui:build"))
        rc = self._run_in_project_dir(['pnpm', 'ui:build'], silence_timeout=TIMEOUT_INSTALL_CMD)
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
        """步骤 7：pnpm build（构建核心服务）。

        重要(Windows): pnpm build 内部会调 `pnpm dlx rolldown`,而 dlx 缓存一旦因
        网络抖动/进程中断留下不完整状态,会被 hash 永久命中,导致后续每次都缺
        `@rolldown/binding-win32-x64-msvc` 这种平台原生绑定。表现:
            Cannot find native binding... Cannot find module '@rolldown/binding-win32-x64-msvc'
        修复策略(2026-05):
            1. build 前先清理 %LOCALAPPDATA%\pnpm-cache\dlx,强制重拉
            2. build 失败若命中"Cannot find native binding"特征,清缓存后再 retry 一次
        离线版直接复用从在线版打的产物,所以只要在线版打出来是干净的,离线就不踩这个坑。
        """
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

            # build 前清 dlx 缓存,避免命中残缺缓存导致 native binding 缺失
            self._clean_pnpm_dlx_cache()

        self._log("正在构建核心服务...")
        if self._inst_on_progress:
            self._inst_on_progress(InstallProgress(stage=InstallStage.INSTALLING, progress_percent=70, message="正在构建核心服务...", current_task="pnpm build"))
        rc = self._run_in_project_dir(['pnpm', 'build'], silence_timeout=TIMEOUT_INSTALL_CMD)

        # Windows + native binding 缺失时自动 retry 一次
        if rc != 0 and self._inst_is_win and self._is_native_binding_failure():
            self._log("检测到 native binding 缺失(疑似 dlx 缓存损坏),清空 dlx 缓存后重试...")
            self._clean_pnpm_dlx_cache(force=True)
            if self._inst_on_progress:
                self._inst_on_progress(InstallProgress(stage=InstallStage.INSTALLING, progress_percent=72, message="正在重试构建核心服务...", current_task="pnpm build (retry)"))
            rc = self._run_in_project_dir(['pnpm', 'build'], silence_timeout=TIMEOUT_INSTALL_CMD)

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

    def _clean_pnpm_dlx_cache(self, force: bool = False) -> None:
        """清空 pnpm dlx 缓存(Windows 专用)。

        位置: %LOCALAPPDATA%\\pnpm-cache\\dlx
        force=True 时无条件清,否则只在目录存在时清。失败不抛异常,只记日志。
        """
        if not self._inst_is_win:
            return
        local_appdata = os.environ.get("LOCALAPPDATA", "")
        if not local_appdata:
            return
        dlx_dir = os.path.join(local_appdata, "pnpm-cache", "dlx")
        if not os.path.exists(dlx_dir):
            if force:
                self._log(f"dlx 缓存目录不存在,跳过清理: {dlx_dir}")
            return
        try:
            self._log(f"清理 pnpm dlx 缓存: {dlx_dir}")
            force_rmtree(dlx_dir, self._log)
        except Exception as e:
            self._log(f"清理 dlx 缓存失败(继续): {e}")

    def _is_native_binding_failure(self) -> bool:
        """检测最近日志是否含 native binding 缺失特征。"""
        recent = "\n".join(self.log_lines[-50:])
        markers = [
            "Cannot find native binding",
            "Cannot find module '@rolldown/binding",
            "Cannot find module '@swc/core-",
            "Cannot find module '@esbuild/",
        ]
        return any(m in recent for m in markers)

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
            silence_timeout=TIMEOUT_INSTALL_CMD,
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

    def _persist_user_path_via_winreg(self, new_dir: str) -> bool:
        """通过 winreg 将目录追加到 HKCU\\Environment\\Path（用户级 PATH）。

        为何不用 setx：
        - setx 有 1024 字符截断限制，开发机 PATH 容易超过。
        - setx 写入的 %PATH% 在 cmd 中展开时会合并 USER + SYSTEM 路径，
          再写回 USER PATH 时会把系统路径重复写进用户 PATH。
        - winreg 直接读写注册表，无截断、不混淆 USER/SYSTEM。

        实现要点：
        1. 仅修改 HKCU\\Environment\\Path（用户级），不需要管理员权限。
        2. 保留原始值类型（REG_EXPAND_SZ 用于含 %VAR% 的展开变量；REG_SZ 用于纯字符串）。
        3. 写入后广播 WM_SETTINGCHANGE，让 Explorer / 新启动的 cmd 立即读取新值。
        4. 任何异常都吞掉记日志，不影响主流程（PATH 持久化失败只影响后续新终端，本进程已通过 _inst_env 注入）。

        Args:
            new_dir: 要追加的绝对目录路径。

        Returns:
            True 表示已写入或已存在；False 表示发生异常。
        """
        try:
            import winreg
            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER, "Environment", 0, winreg.KEY_READ | winreg.KEY_WRITE
            ) as key:
                try:
                    current_value, value_type = winreg.QueryValueEx(key, "Path")
                except FileNotFoundError:
                    current_value, value_type = "", winreg.REG_EXPAND_SZ

                # 解析现有 PATH，防止重复添加（大小写不敏感比对）
                existing = [p for p in current_value.split(";") if p]
                if any(new_dir.lower() == p.strip().lower() for p in existing):
                    self._log(f"用户 PATH 已包含 {new_dir}，无需重复写入")
                    return True

                new_value = (current_value.rstrip(";") + ";" + new_dir) if current_value else new_dir
                winreg.SetValueEx(key, "Path", 0, value_type, new_value)
                self._log(f"已通过 winreg 将 {new_dir} 写入用户 PATH")

            # 广播 WM_SETTINGCHANGE，通知系统环境变量变更
            try:
                import ctypes
                HWND_BROADCAST = 0xFFFF
                WM_SETTINGCHANGE = 0x001A
                SMTO_ABORTIFHUNG = 0x0002
                result = ctypes.c_long()
                ctypes.windll.user32.SendMessageTimeoutW(
                    HWND_BROADCAST, WM_SETTINGCHANGE, 0,
                    "Environment", SMTO_ABORTIFHUNG, 5000, ctypes.byref(result),
                )
            except (OSError, AttributeError) as e:
                self._log(f"广播环境变量变更失败（非致命）: {e}")

            return True
        except (OSError, ImportError) as e:
            self._log(f"通过 winreg 写入用户 PATH 失败: {e}")
            return False

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
                # 用 winreg 直接写 HKCU\Environment\Path，规避 setx 的 1024 字符截断
                # 以及 %PATH% 在 cmd 展开时合并 USER+SYSTEM 导致的 PATH 污染。
                self._persist_user_path_via_winreg(npm_bin_dir)
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
        - macOS：通过 osascript 处理需要管理员权限的操作，尽量减少弹窗次数。

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

        # Windows 上 pnpm 创建 .bin/ wrapper 时,如果 PATHEXT 含 .JS,会尝试给
        # .js 文件添加 .EXE 后缀(实际是 pnpm 内部的兼容逻辑),撞 ENOENT 写不出
        # wrapper,导致后续 postinstall 脚本(如 node-llama-cpp)找不到依赖入口,
        # 撞 ERR_MODULE_NOT_FOUND。Windows 默认 PATHEXT 就含 .JS / .JSE,所以
        # 这是 Windows 通用问题。修复:从 PATHEXT 移除 .JS / .JSE,让 pnpm 老实
        # 用 .CMD 包装。
        if self._inst_is_win:
            pathext = self._inst_env.get("PATHEXT", "")
            cleaned = ";".join(
                p for p in pathext.split(";") if p.strip().upper() not in (".JS", ".JSE")
            )
            self._inst_env["PATHEXT"] = cleaned

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
        silence_timeout: float,
        startupinfo,
        creationflags: int,
        on_log: Callable[[str], None],
        cwd: str | None = None,
    ) -> int:
        """运行命令并实时流式输出日志，支持"无输出超时"自动终止。

        安全策略：使用 shell=False 接收命令列表，彻底避免命令注入。

        设计意图：
        - pnpm install / build 等命令耗时很长，用户需要看到实时进度以避免焦虑。
        - 某些网络/构建过程会假死（持续无输出），通过 last_output_time 检测并在超过 silence_timeout 后强制 kill。
        - 每 30 秒输出一次心跳日志，告知用户"程序仍在工作"。

        Args:
            cmd: 要执行的命令参数列表（如 ["pnpm", "install"]）。
            env: 环境变量字典。
            silence_timeout: **无输出**静默超时阈值（秒）。注意这不是命令总耗时上限，
                而是"连续多少秒没有任何输出就判定为假死"。命令实际可以运行远超此值，
                只要它不停产生输出。
            startupinfo: Windows 专用启动信息（隐藏窗口）。
            creationflags: Windows 专用创建标志。
            on_log: 日志回调。
            cwd: 可选的工作目录。

        Returns:
            int: 进程退出码；若被强制终止则返回 -1。
        """
        # Windows + shell=False + Popen 不查 PATHEXT —— 用户装的 pnpm 实际是
        # %APPDATA%\Roaming\npm\pnpm.cmd 这种批处理包装器,直接传 ["pnpm", ...]
        # 给 Popen 会报 [WinError 2] 系统找不到指定的文件。shutil.which 会查
        # PATHEXT,把 cmd[0] 解析成完整的 .cmd 路径再交给 Popen 就能执行(.cmd 文件
        # CreateProcess 接收完整路径时会自动通过 cmd.exe 执行)。
        # `where` 命中但 Popen 找不到 = 这一类 bug 的典型特征。
        if self._inst_is_win and cmd:
            head = cmd[0]
            # 已经是完整路径(含分隔符)或已带扩展名就不再 which
            if not (os.path.sep in head or "/" in head) and not os.path.splitext(head)[1]:
                resolved = shutil.which(head, path=env.get("PATH"))
                if resolved:
                    cmd = [resolved] + cmd[1:]
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
                if now - last_output_time[0] > silence_timeout:
                    self._log(f"命令超过 {int(silence_timeout)} 秒无输出，判定为卡住，强制终止...")
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
                    **windows_hidden_subprocess_kwargs(),  # 隐藏 taskkill 黑窗
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
