"""OpenClaw 离线安装器适配器

职责：在完全无网络环境下完成 OpenClaw 安装。
将预构建好的源码 + node_modules + dist 打包进安装器，
用户端只需解压 + 配置即可运行。

设计原则：
- 复用 BaseInstaller 的日志和取消机制。
- 所有资源从 PyInstaller 打包目录或本地 resources/ 目录读取。
- 先检测系统已有组件（Node.js、pnpm），有则跳过，无则从资源安装。
- 当前优先实现 macOS，Windows/Linux 架构已预留。
"""

from __future__ import annotations

import copy
import datetime
import os
import shutil
import subprocess
import sys
import tarfile
import time
import zipfile
from pathlib import Path
from typing import Callable

from src.models.constants import (
    is_windows,
    is_macos,
    is_linux,
    NODEJS_VERSION,
    CONFIG_DIR_NAME,
    TIMEOUT_SHORT_CMD,
    TIMEOUT_INSTALL_CMD,
)
from src.models.install import (
    InstallResult,
    InstallStatus,
    InstallStage,
    InstallProgress,
    InstallErrorDetail,
    ErrorCategory,
)
from src.models.utils import (
    ensure_dir_in_path,
    ensure_local_bin_in_path,
    force_rmtree,
    safe_tar_extract,
    windows_hidden_subprocess_kwargs,
)
from src.contracts.define_base_installer import BaseInstaller


# 离线安装进度百分比映射
_PROGRESS_NODEJS = 15
_PROGRESS_PNPM = 25
_PROGRESS_EXTRACT = 50
_PROGRESS_WRAPPER = 65
_PROGRESS_ONBOARD = 80
_PROGRESS_VERIFY = 95


class OfflineOpenClawInstaller(BaseInstaller):
    """OpenClaw 离线安装器。

    实现 IInstaller Protocol，通过预构建产物完成安装，不依赖网络。
    """

    def __init__(self) -> None:
        """初始化离线安装器。"""
        super().__init__()
        self._home = Path.home()
        self._project_dir = self._home / "openclaw-cn"
        self._node_dir = self._home / ".openclaw-node"
        self._pnpm_path: str | None = None
        self._running = False

    def _resource_exists(self, filename: str) -> bool:
        """检查指定资源文件是否存在。"""
        return os.path.exists(os.path.join(self._resource_dir, filename))

    def _log_progress(
        self,
        percent: int,
        message: str,
        task: str,
        on_progress: Callable[[InstallProgress], None] | None,
    ) -> None:
        """发射进度更新。"""
        if on_progress:
            on_progress(
                InstallProgress(
                    stage=InstallStage.INSTALLING,
                    progress_percent=percent,
                    message=message,
                    current_task=task,
                )
            )

    def _extract_nodejs_archive(self, archive_path: str, dest_dir: Path) -> bool:
        """解压 Node.js 归档文件并 flatten 到目标目录。

        与在线版共用同一套解压逻辑：先安全解压，再将 node-v*/ 顶层目录
        的内容移动到目标根目录。使用 shutil.move 保留软链接关系。

        Args:
            archive_path: 归档文件绝对路径。
            dest_dir: 解压目标目录。

        Returns:
            True 如果解压成功。
        """
        dest_dir.mkdir(parents=True, exist_ok=True)

        if archive_path.endswith(".zip"):
            try:
                with zipfile.ZipFile(archive_path, "r") as zf:
                    for name in zf.namelist():
                        if name.startswith("/") or ".." in Path(name).parts:
                            self._log(f"拒绝不安全的 zip 成员: {name}")
                            return False
                    zf.extractall(dest_dir)
            except (OSError, zipfile.BadZipFile) as e:
                self._log(f"解压 Node.js 失败: {e}")
                return False
        else:
            try:
                with tarfile.open(archive_path, "r:*") as tar:
                    safe_tar_extract(tar, dest_dir, self._log)
            except (OSError, tarfile.TarError) as e:
                self._log(f"解压 Node.js 失败: {e}")
                return False

        # Flatten: 如果解压后只有一个 node-v* 子目录，把内容提到根目录
        subdirs = [d for d in dest_dir.iterdir() if d.is_dir() and d.name.startswith("node-v")]
        if len(subdirs) == 1:
            subdir = subdirs[0]
            for item in subdir.iterdir():
                target = dest_dir / item.name
                if target.exists():
                    if item.is_dir():
                        # 用 force_rmtree 而非 shutil.rmtree:Python 3.12 的 shutil.rmtree
                        # 在 onerror 回调中调 os.open 缺 flags 参数会失败,Windows + 只读
                        # 文件场景会留下子树。force_rmtree 走 chmod -R +w + 逐文件 unlink,
                        # 单个文件失败不影响整体。
                        force_rmtree(target, self._log)
                    else:
                        target.unlink()
                shutil.move(str(item), str(target))
            subdir.rmdir()
            self._log(f"已 flatten 目录: {subdir.name}")

        return True

    def _install_nodejs(self) -> bool:
        """从资源目录安装 Node.js。

        使用 glob 匹配 resources/{platform}/ 下任意版本的 Node.js 预编译包，
        不依赖硬编码版本号。匹配到的包按版本号降序排列（优先用新版），
        解压后通过 node --version 校验主版本 >= 22。

        Returns:
            True 如果安装成功。
        """
        self._log("正在安装 Node.js >= 22...")

        # 按平台构造 glob 模式，匹配任意版本（如 node-v22.14.0-darwin-arm64.tar.gz）
        patterns = []
        if is_macos():
            patterns = ["node-v*-darwin-arm64.tar.gz", "node-v*-darwin-x64.tar.gz"]
        elif is_windows():
            patterns = ["node-v*-win-x64.zip", "node-v*-win-x64.tar.gz"]
        else:
            patterns = ["node-v*-linux-x64.tar.xz", "node-v*-linux-x64.tar.gz"]

        # 收集所有匹配文件
        all_matches: list[Path] = []
        for pattern in patterns:
            all_matches.extend(Path(self._resource_dir).glob(pattern))

        # 诊断：如果未找到，打印资源目录内容帮助定位问题
        if not all_matches:
            self._log(f"[诊断] _resource_dir = {self._resource_dir}")
            self._log(f"[诊断] _resource_dir exists = {os.path.isdir(self._resource_dir)}")
            try:
                if os.path.isdir(self._resource_dir):
                    files = os.listdir(self._resource_dir)
                    self._log(f"[诊断] 目录内容: {files}")
                else:
                    self._log("[诊断] 资源目录不存在")
            except OSError as e:
                self._log(f"[诊断] 读取目录失败: {e}")
            self._log("未找到任何 Node.js 离线资源")
            return False

        # 按文件名中的版本号降序排列（v23.1.0 > v22.14.0 > v22.13.0）
        def _extract_version(path: Path) -> tuple[int, ...]:
            """从 node-v{version}-... 文件名中提取版本号元组。"""
            name = path.name
            try:
                # node-v22.14.0-darwin-arm64.tar.gz -> "22.14.0"
                ver_str = name.split("-")[1].lstrip("v")
                return tuple(int(x) for x in ver_str.split("."))
            except (IndexError, ValueError):
                return (0, 0, 0)

        all_matches.sort(key=_extract_version, reverse=True)
        self._log(f"找到 {len(all_matches)} 个 Node.js 离线资源，按版本排序")

        for archive_path in all_matches:
            self._log(f"尝试解压: {archive_path.name}")
            self._node_dir.mkdir(parents=True, exist_ok=True)

            if not self._extract_nodejs_archive(str(archive_path), self._node_dir):
                self._log(f"解压失败，尝试下一个")
                continue

            # 将 ~/.openclaw-node/bin 加入当前进程 PATH
            node_bin = str(self._node_dir / "bin")
            if os.path.exists(node_bin):
                current_path = os.environ.get("PATH", "")
                if node_bin not in current_path.split(os.pathsep):
                    os.environ["PATH"] = node_bin + os.pathsep + current_path
                    self._log(f"已将 {node_bin} 加入 PATH")
                else:
                    self._log(f"{node_bin} 已在 PATH 中")
                ensure_dir_in_path(node_bin, self._on_log)

            # 验证版本 >= 22（会运行刚解压的 node --version）
            if self._check_nodejs_version():
                return True

            self._log(f"{archive_path.name} 版本不满足 >= 22，尝试下一个")

        self._log("所有 Node.js 离线资源均不可用（版本 < 22 或解压失败）")
        return False

    def _check_pnpm(self) -> bool:
        """检查 pnpm 是否可用。"""
        try:
            # Windows GUI 程序调子进程必须双保险隐藏窗口(STARTUPINFO + CREATE_NO_WINDOW),
            # 否则会闪一个黑色 cmd 窗口
            result = subprocess.run(
                ["pnpm", "-v"],
                capture_output=True,
                text=True,
                timeout=TIMEOUT_SHORT_CMD,
                **windows_hidden_subprocess_kwargs(),
            )
            if result.returncode == 0:
                self._log(f"pnpm {result.stdout.strip()} 已可用")
                return True
        except (OSError, subprocess.TimeoutExpired):
            pass
        return False

    def _find_pnpm_tarball(self) -> str | None:
        """查找 pnpm npm tarball 资源。

        查找顺序:
        1. resources/ 根目录 (pnpm-*.tgz)
        2. resources/{platform}/ 子目录

        Returns:
            tarball 绝对路径,未找到返回 None。
        """
        # resources/ 根目录
        parent = Path(self._resource_dir).parent
        for pattern in ["pnpm-*.tgz"]:
            matches = sorted(parent.glob(pattern))
            if matches:
                return str(matches[0])

        # 平台子目录
        for pattern in ["pnpm-*.tgz"]:
            matches = sorted(Path(self._resource_dir).glob(pattern))
            if matches:
                return str(matches[0])

        return None

    def _resolve_npm_cmd(self) -> str | None:
        """解析可用的 npm 命令路径。

        按优先级尝试:
        1. shutil.which("npm") — 当前 PATH 中的 npm
        2. 从 node 路径推断 — node 所在目录下的 npm
        3. 常见安装路径

        Returns:
            npm 可执行文件的绝对路径,找不到返回 None。
        """
        import shutil

        # 1. PATH 中搜索
        npm_from_which = shutil.which("npm")
        if npm_from_which:
            return npm_from_which

        # 2. 从 node 路径推断
        node_from_which = shutil.which("node")
        if node_from_which:
            npm_candidate = os.path.join(os.path.dirname(node_from_which), "npm")
            if os.path.isfile(npm_candidate):
                return npm_candidate

        # 3. 常见路径 + 动态查找 nvm 最新版本
        home = os.path.expanduser("~")
        common_paths = [
            "/usr/local/bin/npm",
            "/opt/homebrew/bin/npm",
            os.path.join(home, ".local", "bin", "npm"),
            str(self._node_dir / "bin" / "npm"),
        ]

        # 动态查找 nvm 已安装的最新版本
        nvm_dir = os.path.join(home, ".nvm", "versions", "node")
        if os.path.isdir(nvm_dir):
            try:
                versions = sorted(
                    [d for d in os.listdir(nvm_dir) if d.startswith("v")],
                    key=lambda x: tuple(int(p) for p in x.lstrip("v").split(".")),
                    reverse=True,
                )
                if versions:
                    common_paths.insert(0, os.path.join(nvm_dir, versions[0], "bin", "npm"))
            except (OSError, ValueError):
                pass

        for path in common_paths:
            if os.path.isfile(path):
                return path

        return None

    def _install_pnpm(self) -> bool:
        """通过 npm 本地安装 pnpm。

        从 resources/ 读取 pnpm 的 npm tarball,执行 npm install -g 本地安装。
        无需网络,不依赖平台相关的 standalone 二进制,一个 .tgz 跨平台通用。

        前提: Node.js 已安装(_install_nodejs 先执行)。

        Returns:
            True 如果安装成功。
        """
        self._log("正在安装 pnpm...")

        pnpm_tgz = self._find_pnpm_tarball()
        if not pnpm_tgz:
            self._log("未找到 pnpm npm tarball 资源(pnpm-*.tgz)")
            return False

        self._log(f"使用本地 pnpm 包: {Path(pnpm_tgz).name}")

        # 解析 npm 命令路径(优先用完整路径,避免 shell PATH 不一致)
        npm_path = self._resolve_npm_cmd()
        if not npm_path:
            self._log("未找到 npm 命令,请确保 Node.js 已正确安装")
            return False

        self._log(f"使用 npm: {npm_path}")

        result = subprocess.run(
            [npm_path, "install", "-g", pnpm_tgz],
            shell=False,
            capture_output=True,
            text=True,
            timeout=120,
            **windows_hidden_subprocess_kwargs(),  # 隐藏 Windows 黑窗
        )

        if result.returncode != 0:
            err = result.stderr.strip() if result.stderr else "未知错误"
            self._log(f"pnpm 安装失败: {err}")
            return False

        self._log("pnpm 安装成功")

        # 确保 npm 全局 bin 目录在 PATH 中
        if is_windows():
            npm_bin = Path(os.path.expanduser(r"~\AppData\Roaming\npm"))
        else:
            npm_bin = self._node_dir / "bin"

        bin_str = str(npm_bin)
        current_path = os.environ.get("PATH", "")
        if bin_str not in current_path:
            os.environ["PATH"] = bin_str + os.pathsep + current_path
            self._log(f"已将 {bin_str} 加入 PATH")

        if not is_windows():
            ensure_local_bin_in_path(self._on_log)

        if self._check_pnpm():
            self._pnpm_path = "pnpm"
            return True

        self._log("pnpm 安装后验证失败")
        return False

    def _extract_prebuilt(self) -> bool:
        """解压预构建产物到 ~/openclaw-cn。

        Returns:
            True 如果解压成功。
        """
        self._log("正在解压预构建产物...")

        filename = f"openclaw-prebuilt-{self._platform}.tar.gz"
        archive_path = os.path.join(self._resource_dir, filename)

        if not os.path.exists(archive_path):
            self._log(f"未找到预构建产物: {filename}")
            return False

        # 若已存在旧目录，先备份而非直接删除
        if self._project_dir.exists():
            backup_name = f"openclaw-cn.backup.{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}"
            backup_dir = self._home / backup_name

            # 处理备份名冲突
            counter = 1
            original_backup_dir = backup_dir
            while backup_dir.exists():
                backup_dir = self._home / f"{backup_name}.{counter}"
                counter += 1

            self._log(f"备份旧目录到 {backup_dir}...")
            try:
                shutil.move(str(self._project_dir), str(backup_dir))
            except OSError as e:
                self._log(f"备份旧目录失败: {e}")
                return False

        try:
            with tarfile.open(archive_path, "r:gz") as tar:
                safe_tar_extract(tar, self._home, self._log)
            self._log(f"已解压预构建产物到 {self._project_dir}")
        except (OSError, tarfile.TarError) as e:
            self._log(f"解压预构建产物失败: {e}")
            return False

        return True

    def _create_wrappers(self) -> bool:
        """创建全局命令包装器。

        Returns:
            True 如果创建成功。
        """
        self._log("正在创建全局命令包装器...")

        # bin_dir 由平台决定:Windows npm 全局,*nix ~/.local/bin
        if is_windows():
            bin_dir = Path(os.path.expanduser(r"~\AppData\Roaming\npm"))
        else:
            bin_dir = Path.home() / ".local" / "bin"

        # 离线版无需注入 CLAWHUB_REGISTRY(无网络可用)
        success = self._write_command_wrappers(bin_dir, self._project_dir, registry=None)

        # 把 wrapper 目录加入当前进程 PATH，使后续 _verify_installation 能立刻找到命令
        bin_str = str(bin_dir)
        current_path = os.environ.get("PATH", "")
        if bin_str not in current_path.split(os.pathsep):
            os.environ["PATH"] = bin_str + os.pathsep + current_path
            self._log(f"已将 {bin_str} 加入当前进程 PATH")

        # *nix 下额外保证 ~/.local/bin 在 shell 启动时进入 PATH
        if success and not is_windows():
            ensure_local_bin_in_path(self._on_log)

        return success

    def _run_onboard(self) -> bool:
        """执行 onboard 配置初始化。

        Returns:
            True 如果 onboard 成功或配置文件已存在。
        """
        self._log("正在初始化配置（onboard）...")

        # 确定 pnpm 路径：优先使用已记录的 standalone 路径，fallback 到系统 pnpm
        pnpm_cmd = self._pnpm_path or "pnpm"

        # 若 wrapper 尚未生效，直接使用项目目录内的 pnpm 执行
        cmd = [
            pnpm_cmd, "openclaw", "onboard",
            "--non-interactive", "--accept-risk", "--mode", "local",
            "--skip-skills", "--skip-health", "--no-install-daemon",
            "--node-manager", "pnpm", "--skip-channels",
        ]

        try:
            result = subprocess.run(
                cmd,
                cwd=self._project_dir,
                capture_output=True,
                text=True,
                timeout=TIMEOUT_INSTALL_CMD,
                env=os.environ.copy(),
                **windows_hidden_subprocess_kwargs(),  # 隐藏 Windows 黑窗(onboard 期间)
            )
            self._log(f"onboard return code: {result.returncode}")
            if result.stdout:
                self._log(f"onboard stdout: {result.stdout[:500]}")
            if result.stderr:
                self._log(f"onboard stderr: {result.stderr[:500]}")

            if result.returncode == 0:
                return True

            # 非零可能是重复执行，检查配置文件是否已存在
            config_path = self._home / CONFIG_DIR_NAME / "openclaw.json"
            if config_path.exists():
                self._log("onboard 返回非零但配置已存在，视为成功")
                return True

            self._log("onboard 失败")
            return False
        except (OSError, subprocess.TimeoutExpired) as e:
            self._log(f"onboard 异常: {e}")
            return False

    def _verify_installation(self) -> bool:
        """验证 openclaw 命令是否可用。

        Returns:
            True 如果命令可用。
        """
        self._log("验证安装结果...")

        # Windows 下 wrapper 可能尚未对新进程生效,优先使用完整路径调用
        if is_windows():
            npm_bin_dir = Path(os.path.expanduser(r"~\AppData\Roaming\npm"))
            for cmd_name in ["openclaw-cn.cmd", "openclaw.cmd"]:
                full_path = npm_bin_dir / cmd_name
                if full_path.exists():
                    try:
                        result = subprocess.run(
                            [str(full_path), "--version"],
                            capture_output=True,
                            text=True,
                            timeout=TIMEOUT_SHORT_CMD,
                            **windows_hidden_subprocess_kwargs(),  # 隐藏 Windows 黑窗
                        )
                        if result.returncode == 0:
                            self._log(f"验证通过: {cmd_name} {result.stdout.strip()}")
                            return True
                    except (OSError, subprocess.TimeoutExpired):
                        pass

        # 使用基类的通用 PATH 检查
        if self._verify_openclaw_command():
            self._log("openclaw 命令在 PATH 中可用")
            return True
        self._log("未找到 openclaw/openclaw-cn 命令")
        return False

    def install(
        self,
        on_progress: Callable[[InstallProgress], None] | None = None,
        on_log: Callable[[str], None] | None = None,
    ) -> InstallResult:
        """执行离线安装流程。

        流程：检测 Node.js → 检测/安装 pnpm → 解压预构建产物 →
              创建包装器 → onboard → 验证。

        Args:
            on_progress: 进度回调。
            on_log: 日志回调。

        Returns:
            InstallResult: 安装结果。
        """
        # 检查是否在调用前已被取消（在重置状态前保存）
        was_cancelled = self.is_cancelled
        self._on_log = on_log
        self.is_cancelled = False
        self.log_lines = []
        self._running = True

        # 若在进入 install() 前已被取消，直接返回
        if was_cancelled:
            self._running = False
            return InstallResult(
                status=InstallStatus.CANCELLED,
                message="安装已取消",
                log_lines=[],
                duration_seconds=0,
            )

        self.start_time = time.time()

        try:

            # 步骤 0: macOS 离线版设置内部 git（避免 Xcode CLT shim 弹窗）
            self._setup_git_if_needed()

            # 步骤 1: 检测/安装 Node.js
            self._log_progress(_PROGRESS_NODEJS, "检测系统环境...", "检查 Node.js", on_progress)
            if not self._check_nodejs_version():
                if self.is_cancelled:
                    return self._build_cancelled_result()
                if not self._install_nodejs():
                    return InstallResult(
                        status=InstallStatus.FAILED,
                        message="Node.js 安装失败",
                        error_message="未找到系统 Node.js >= 22，且离线资源中无可用的 Node.js 安装包。",
                        log_lines=self.log_lines.copy(),
                        duration_seconds=time.time() - self.start_time,
                        error_detail=InstallErrorDetail(
                            category=ErrorCategory.DEPENDENCY_MISSING,
                            stage="INSTALLING",
                            context="Node.js 离线安装",
                            raw_error="Node.js not found and no offline resource available",
                            user_message="Node.js 安装失败",
                            suggestion="请确保安装包内包含对应平台的 Node.js 预编译二进制资源",
                        ),
                    )

            if self.is_cancelled:
                return self._build_cancelled_result()

            # 步骤 2: 检测/安装 pnpm
            self._log_progress(_PROGRESS_PNPM, "检测包管理器...", "检查 pnpm", on_progress)
            if not self._check_pnpm():
                if self.is_cancelled:
                    return self._build_cancelled_result()
                if not self._install_pnpm():
                    return InstallResult(
                        status=InstallStatus.FAILED,
                        message="pnpm 安装失败",
                        error_message="未找到系统 pnpm，且离线资源中无可用的 pnpm standalone 文件。",
                        log_lines=self.log_lines.copy(),
                        duration_seconds=time.time() - self.start_time,
                        error_detail=InstallErrorDetail(
                            category=ErrorCategory.DEPENDENCY_MISSING,
                            stage="INSTALLING",
                            context="pnpm 离线安装",
                            raw_error="pnpm not found and no offline resource available",
                            user_message="pnpm 安装失败",
                            suggestion="请确保安装包内包含 pnpm standalone 可执行文件",
                        ),
                    )

            if self.is_cancelled:
                return self._build_cancelled_result()

            # 步骤 3: 解压预构建产物
            self._log_progress(_PROGRESS_EXTRACT, "解压预构建产物...", "解压 openclaw-cn", on_progress)
            if not self._extract_prebuilt():
                return InstallResult(
                    status=InstallStatus.FAILED,
                    message="预构建产物解压失败",
                    error_message=f"无法从 {self._resource_dir} 解压预构建产物",
                    log_lines=self.log_lines.copy(),
                    duration_seconds=time.time() - self.start_time,
                )

            if self.is_cancelled:
                return self._build_cancelled_result()

            # 步骤 4: 创建命令包装器
            self._log_progress(_PROGRESS_WRAPPER, "创建命令包装器...", "生成 openclaw 命令", on_progress)
            if not self._create_wrappers():
                return InstallResult(
                    status=InstallStatus.FAILED,
                    message="命令包装器创建失败",
                    error_message="无法创建全局 openclaw 命令",
                    log_lines=self.log_lines.copy(),
                    duration_seconds=time.time() - self.start_time,
                )

            if self.is_cancelled:
                return self._build_cancelled_result()

            # 步骤 5: onboard 配置
            self._log_progress(_PROGRESS_ONBOARD, "初始化配置...", "openclaw onboard", on_progress)
            if not self._run_onboard():
                return InstallResult(
                    status=InstallStatus.FAILED,
                    message="配置初始化失败",
                    error_message="onboard 执行失败，请检查日志",
                    log_lines=self.log_lines.copy(),
                    duration_seconds=time.time() - self.start_time,
                )

            if self.is_cancelled:
                return self._build_cancelled_result()

            # 步骤 6: 验证
            self._log_progress(_PROGRESS_VERIFY, "验证安装...", "检查命令可用性", on_progress)
            if not self._verify_installation():
                return InstallResult(
                    status=InstallStatus.FAILED,
                    message="安装验证失败",
                    error_message="openclaw 命令不可用，请尝试重启程序",
                    log_lines=self.log_lines.copy(),
                    duration_seconds=time.time() - self.start_time,
                )

            # 完成
            self._log_progress(100, "安装完成", "完成", on_progress)
            return InstallResult(
                status=InstallStatus.SUCCESS,
                message="OpenClaw 离线安装完成",
                log_lines=self.log_lines.copy(),
                duration_seconds=time.time() - self.start_time,
            )
        finally:
            self._running = False

    def is_running(self) -> bool:
        """检查安装是否正在进行中。"""
        return self._running
