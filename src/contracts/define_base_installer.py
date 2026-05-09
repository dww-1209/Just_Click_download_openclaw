"""安装器抽象基类

职责:为所有安装器实现类提供共享工具和横切关注钩子,
消除 _log()、is_cancelled、cancel()、命令包装器创建、Node.js 版本检查等
逻辑在多个类中的重复实现。

设计原则:
- 本基类是可选的:实现类可以选择继承本基类(获得默认实现),
  或仅实现 IInstaller Protocol(保持灵活)。
- 基类提供的是"能力"而非"契约",真正的契约仍由 Protocol 定义。
- 所有子类共享的纯逻辑(无平台特化的 streaming 子进程管理)集中在此处,
  平台/runtime 特化逻辑仍由各 adapter 自行实现。
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import tarfile
import time
import zipfile
from abc import ABC
from pathlib import Path
from typing import Callable, Optional

from src.models.install import InstallResult, InstallStatus
from src.models.constants import is_windows, is_macos, is_linux, TIMEOUT_SHORT_CMD
from src.models.utils import safe_tar_extract


# Node.js 版本检查的子进程超时(秒);保持小值,避免 install() 卡在初始检查
_NODE_VERSION_CHECK_TIMEOUT = 10


class BaseInstaller(ABC):
    """安装器抽象基类。

    提供以下默认实现:
    - 统一日志记录(_log):自动过滤 ANSI 颜色码、追加时间戳并回调 UI。
    - 取消状态管理(is_cancelled、cancel、_check_cancelled、_build_cancelled_result)。
    - 通用工具方法(Node.js 版本检查、wrapper 创建、命令验证)。
    - 日志行缓存(log_lines)。

    子类只需调用 self._log("...") 和检查 self.is_cancelled 即可,
    无需重复实现日志格式化、取消检查和跨平台 wrapper 创建逻辑。
    """

    def __init__(self) -> None:
        # 子进程句柄(可选,某些子类需要持有以便 cancel 时终止)
        self.process: Optional[object] = None
        # 日志行缓存(供 InstallResult 携带回 UI)
        self.log_lines: list[str] = []
        # 取消标志,由 cancel() 设置,各步骤定期检查
        self.is_cancelled: bool = False
        # 日志回调,_log 中转发到此
        self._on_log: Optional[Callable[[str], None]] = None
        # 安装开始时间;install() 入口处会重置,用于 InstallResult.duration_seconds
        self.start_time: float = time.time()
        # 资源目录和平台标识;子类应在 __init__ 中覆盖
        self._platform: str = self._detect_platform()
        self._resource_dir: str = self._resolve_resource_dir()

    def _log(self, message: str) -> None:
        """统一日志记录:过滤 ANSI 颜色码、追加时间戳并回调 UI。

        Args:
            message: 日志内容,会自动过滤 ANSI 控制序列并追加时间戳。
        """
        cleaned = re.sub(r"\x1b\[[0-9;?]*[A-Za-z]", "", message)
        timestamp = time.strftime("%H:%M:%S")
        log_line = f"[{timestamp}] {cleaned}"
        self.log_lines.append(log_line)
        if self._on_log:
            self._on_log(log_line)

    def cancel(self) -> None:
        """请求取消安装。设置取消标志,子类可覆盖以添加进程终止逻辑。"""
        self.is_cancelled = True

    # ------------------------------------------------------------------
    # 取消状态相关辅助方法
    # ------------------------------------------------------------------

    def _build_cancelled_result(self) -> InstallResult:
        """构建标准的"已取消"安装结果。

        子类调用以避免重复构造 CANCELLED 状态的 InstallResult。
        """
        return InstallResult(
            status=InstallStatus.CANCELLED,
            message="安装已取消",
            log_lines=self.log_lines.copy(),
            duration_seconds=time.time() - self.start_time,
        )

    def _check_cancelled(self) -> Optional[InstallResult]:
        """若已被取消,返回 CANCELLED 结果;否则返回 None。

        典型用法:
            cancelled = self._check_cancelled()
            if cancelled:
                return cancelled
        """
        if self.is_cancelled:
            return self._build_cancelled_result()
        return None

    # ------------------------------------------------------------------
    # 通用环境检查 / 验证
    # ------------------------------------------------------------------

    def _check_nodejs_version(self, min_major: int = 22) -> bool:
        """检查系统 Node.js 是否满足最低主版本要求。

        优先用 shutil.which 定位 node 可执行文件,再尝试常见安装路径,
        以应对 nvm/fnm/Homebrew 等版本管理器导致 PATH 不一致的情况。

        Args:
            min_major: 最低主版本号,默认 22(OpenClaw 当前要求)。

        Returns:
            True 表示已满足要求并记录日志;False 表示版本过低或未安装。
        """
        import shutil

        # 按优先级尝试多个 node 路径
        candidates = ["node"]
        node_from_which = shutil.which("node")
        if node_from_which:
            candidates.insert(0, node_from_which)

        # 常见安装路径(nvm、fnm、Homebrew、官方 PKG、系统路径)
        home = os.path.expanduser("~")
        common_paths = [
            "/usr/local/bin/node",
            "/opt/homebrew/bin/node",
            os.path.join(home, ".local", "bin", "node"),
        ]
        # 动态查找 nvm 已安装的最高版本
        nvm_dir = os.path.join(home, ".nvm", "versions", "node")
        if os.path.isdir(nvm_dir):
            try:
                versions = sorted(
                    [d for d in os.listdir(nvm_dir) if d.startswith("v")],
                    key=lambda x: tuple(int(p) for p in x.lstrip("v").split(".")),
                    reverse=True,
                )
                if versions:
                    common_paths.insert(0, os.path.join(nvm_dir, versions[0], "bin", "node"))
            except (OSError, ValueError):
                pass

        for path in common_paths:
            if os.path.isfile(path) and path not in candidates:
                candidates.append(path)

        for node_cmd in candidates:
            try:
                result = subprocess.run(
                    [node_cmd, "-v"],
                    capture_output=True,
                    text=True,
                    timeout=_NODE_VERSION_CHECK_TIMEOUT,
                )
                if result.returncode == 0:
                    stdout = result.stdout.strip()
                    major = int(stdout.lstrip("v").split(".")[0])
                    if major >= min_major:
                        self._log(f"Node.js {stdout} 已满足要求 (路径: {node_cmd})")
                        # 若 node 是通过绝对路径找到的(nvm/fnm 等),将其所在目录加入 PATH,
                        # 确保后续 npm/pnpm 等命令也能被解析
                        if os.path.isabs(node_cmd):
                            node_bin_dir = os.path.dirname(node_cmd)
                            current_path = os.environ.get("PATH", "")
                            if node_bin_dir not in current_path.split(os.pathsep):
                                os.environ["PATH"] = node_bin_dir + os.pathsep + current_path
                                self._log(f"已将 {node_bin_dir} 加入 PATH")
                        return True
                    self._log(f"检测到 Node.js v{major},版本过低(需要 >= {min_major})")
            except (ValueError, TypeError, OSError, subprocess.SubprocessError):
                continue

        self._log("未检测到满足要求的 Node.js (>= 22)")
        return False

    @staticmethod
    def _verify_openclaw_command() -> bool:
        """验证 openclaw / openclaw-cn 命令是否在 PATH 中可解析。

        基于 shutil.which,跨平台等价于 Windows where + Linux/macOS which。
        子类如有更复杂的退化路径(如 Windows 下用绝对路径调用 wrapper)
        可在调用本方法之前补充自定义检查。
        """
        return any(shutil.which(c) for c in ("openclaw-cn", "openclaw"))

    # ------------------------------------------------------------------
    # 命令包装器(wrapper)创建 — 在线/离线安装均需创建
    # ------------------------------------------------------------------

    def _write_command_wrappers(
        self,
        bin_dir: Path,
        project_dir: Path,
        registry: Optional[str] = None,
    ) -> bool:
        """在 bin_dir 中创建 openclaw / openclaw-cn 全局命令包装器。

        Windows 写 .cmd 批处理,*nix 写带 chmod 0755 的 bash 脚本。
        wrapper 会先 cd 到 project_dir 再调用 pnpm openclaw,
        确保用户在任意目录调用都能命中正确的项目。

        Args:
            bin_dir: 写 wrapper 的目录(Windows 一般是 npm 全局 bin,*nix 一般是 ~/.local/bin)。
            project_dir: 项目根目录,wrapper 内部会 cd 到此目录。
            registry: 可选,在线安装会注入 CLAWHUB_REGISTRY 环境变量;离线安装通常传 None。

        Returns:
            True 表示全部 wrapper 创建成功;False 表示有任意一个写入失败。
        """
        bin_dir.mkdir(parents=True, exist_ok=True)
        success = True

        if is_windows():
            # Windows batch 中 % 会触发环境变量扩展，需转义为 %%
            project_dir_str = str(project_dir).replace("%", "%%")
            for name in ("openclaw.cmd", "openclaw-cn.cmd"):
                wrapper_path = bin_dir / name
                # @echo off 抑制命令回显;cd /d 支持跨盘符切换
                lines = ["@echo off"]
                if registry:
                    lines.append(f"set CLAWHUB_REGISTRY={registry}")
                lines.extend([
                    f'cd /d "{project_dir_str}"',
                    "pnpm openclaw %*",
                    "",
                ])
                content = "\n".join(lines)
                try:
                    wrapper_path.write_text(content, encoding="utf-8")
                    self._log(f"已创建全局命令: {wrapper_path}")
                except OSError as e:
                    self._log(f"创建全局命令失败 {wrapper_path}: {e}")
                    success = False
        else:
            for name in ("openclaw", "openclaw-cn"):
                wrapper_path = bin_dir / name
                lines = ["#!/bin/bash"]
                if registry:
                    lines.append(f"export CLAWHUB_REGISTRY={registry}")
                lines.extend([
                    f'cd "{project_dir}" || exit 1',
                    'pnpm openclaw "$@"',
                    "",
                ])
                content = "\n".join(lines)
                try:
                    wrapper_path.write_text(content, encoding="utf-8")
                    wrapper_path.chmod(0o755)
                    self._log(f"已创建全局命令: {wrapper_path}")
                except OSError as e:
                    self._log(f"创建全局命令失败 {wrapper_path}: {e}")
                    success = False

        return success

    # ------------------------------------------------------------------
    # 资源目录解析
    # ------------------------------------------------------------------

    def _detect_platform(self) -> str:
        """检测当前平台，返回 resources/ 子目录名。"""
        if is_windows():
            return "windows"
        if is_macos():
            return "macos"
        return "linux"

    def _resolve_resource_dir(self) -> str:
        """解析资源目录路径。

        按以下优先级查找：
        1. PyInstaller 运行时：sys._MEIPASS 临时目录
        2. 可执行文件同目录
        3. 开发模式：项目根目录下的 resources/
        """
        if getattr(sys, "_MEIPASS", None):
            return os.path.join(sys._MEIPASS, "resources", self._platform)

        exe_dir = Path(sys.executable).parent.resolve()
        candidate = exe_dir / "resources" / self._platform
        if candidate.exists():
            return str(candidate)

        project_root = Path(__file__).parent.parent.parent.resolve()
        return str(project_root / "resources" / self._platform)

    # ------------------------------------------------------------------
    # 内部 git（macOS/Windows 共用）
    # ------------------------------------------------------------------

    def _locate_internal_git(self, git_dest: Path) -> tuple[Path | None, Path | None]:
        """在解压目录中定位内部 git 的 bin/ 和 libexec/git-core/ 路径。"""
        for subdir_name in ["git-test", "git", "usr"]:
            candidate_bin = git_dest / subdir_name / "bin"
            candidate_exec = git_dest / subdir_name / "libexec" / "git-core"
            git_binary = candidate_bin / "git"
            if git_binary.is_file() and candidate_exec.is_dir():
                return candidate_bin, candidate_exec

        for git_binary in git_dest.rglob("bin/git"):
            inferred_exec = git_binary.parent.parent / "libexec" / "git-core"
            if inferred_exec.is_dir():
                return git_binary.parent, inferred_exec

        for git_binary in git_dest.rglob("bin/git"):
            return git_binary.parent, git_binary.parent.parent / "libexec" / "git-core"

        return None, None

    def _setup_git_if_needed(self) -> None:
        """在未安装 git 的系统上使用打包的内部 git。

        macOS：检测 Xcode CLT，未安装时解压内部 git 并创建 wrapper。
        Windows：直接解压 MinGit 便携版到 ~/.openclaw-git/ 并加入 PATH。
        Linux：暂不支持。
        """
        if is_linux():
            return

        git_dest = Path.home() / ".openclaw-git"

        if is_macos():
            self._setup_git_macos(git_dest)
        else:
            self._setup_git_windows(git_dest)

    def _setup_git_macos(self, git_dest: Path) -> None:
        """macOS：检测系统 git 是否可用，不可用时使用内部 git。

        检测顺序：
        1. shutil.which("git") 找到路径，非 /usr/bin/git 直接验证可用性
        2. /usr/bin/git 是 Xcode CLT shim，用 xcode-select -p 确认 CLT 已安装
        3. 以上都不可用时，解压并使用安装器内置的 git
        """
        import shutil

        # 1. 查找系统中的 git
        git_path = shutil.which("git")
        if git_path and git_path != "/usr/bin/git":
            # 可能是 Homebrew、MacPorts、之前安装的内部 git wrapper 等
            try:
                result = subprocess.run(
                    [git_path, "--version"],
                    capture_output=True,
                    text=True,
                    timeout=TIMEOUT_SHORT_CMD,
                )
                if result.returncode == 0 and "git version" in result.stdout:
                    self._log(f"系统 git 已可用: {git_path} ({result.stdout.strip()})")
                    return
            except (OSError, subprocess.SubprocessError):
                pass

        # 2. /usr/bin/git 是 Xcode CLT shim，检测 CLT 是否已安装
        if git_path == "/usr/bin/git":
            try:
                result = subprocess.run(
                    ["xcode-select", "-p"],
                    capture_output=True,
                    text=True,
                    timeout=TIMEOUT_SHORT_CMD,
                )
                if result.returncode == 0 and result.stdout.strip():
                    self._log(f"Xcode CLT 已安装 ({result.stdout.strip()})，/usr/bin/git 可用")
                    return
                self._log("Xcode CLT 未安装，/usr/bin/git 是 shim，将使用内部 git")
            except (OSError, subprocess.SubprocessError):
                self._log("Xcode CLT 检测失败，将使用内部 git")
        else:
            self._log("未找到系统 git，将使用内部 git")

        git_tgz_pattern = f"git-{self._platform}*.tar.gz"
        matches = sorted(Path(self._resource_dir).glob(git_tgz_pattern))
        if not matches:
            self._log(f"未找到内部 git 资源: {git_tgz_pattern}")
            return

        git_tgz = str(matches[0])

        if git_dest.exists() and any(git_dest.iterdir()):
            self._log(f"内部 git 已存在: {git_dest}")
        else:
            self._log(f"正在解压内部 git: {Path(git_tgz).name}")
            git_dest.mkdir(parents=True, exist_ok=True)
            try:
                with tarfile.open(git_tgz, "r:gz") as tar:
                    safe_tar_extract(tar, git_dest, self._log)
                self._log(f"内部 git 解压完成: {git_dest}")
            except (OSError, tarfile.TarError) as e:
                self._log(f"内部 git 解压失败: {e}")
                return

        git_bin, git_exec = self._locate_internal_git(git_dest)
        if not git_bin or not git_exec:
            self._log("内部 git 目录结构异常")
            return

        git_bin_str = str(git_bin)
        git_exec_str = str(git_exec)
        git_binary_path = os.path.join(git_bin_str, "git")

        if not os.path.isfile(git_binary_path):
            self._log(f"内部 git 二进制不存在: {git_binary_path}")
            return

        self._log(f"测试内部 git: {git_binary_path}")
        test_env = os.environ.copy()
        test_env["GIT_EXEC_PATH"] = git_exec_str
        test_env["PATH"] = git_bin_str + os.pathsep + test_env.get("PATH", "")
        try:
            test_result = subprocess.run(
                [git_binary_path, "--version"],
                capture_output=True,
                text=True,
                timeout=TIMEOUT_SHORT_CMD,
                env=test_env,
            )
            if test_result.returncode == 0 and "git version" in test_result.stdout:
                self._log(f"内部 git 验证通过: {test_result.stdout.strip()}")
            else:
                err = test_result.stderr.strip()[:200] if test_result.stderr else "无输出"
                self._log(f"内部 git 测试失败: {err}")
                return
        except (OSError, subprocess.TimeoutExpired) as e:
            self._log(f"内部 git 测试异常: {e}")
            return

        os.environ["GIT_EXEC_PATH"] = git_exec_str
        current_path = os.environ.get("PATH", "")
        if git_bin_str not in current_path.split(os.pathsep):
            os.environ["PATH"] = git_bin_str + os.pathsep + current_path
            self._log(f"已设置内部 git PATH: {git_bin_str}")

        local_bin = Path.home() / ".local" / "bin"
        local_bin.mkdir(parents=True, exist_ok=True)
        git_wrapper = local_bin / "git"
        # 转义路径中的双引号，避免破坏 bash 脚本语法
        _bp = git_binary_path.replace('"', '\\"')
        _ep = git_exec_str.replace('"', '\\"')
        wrapper_script = f'''#!/bin/bash
# OpenClaw 内部 git wrapper
set -e
GIT_BIN="{_bp}"
if [ ! -x "$GIT_BIN" ]; then
    echo "错误: 找不到内部 git: $GIT_BIN" >&2
    exit 1
fi
export GIT_EXEC_PATH="{_ep}"
exec "$GIT_BIN" "$@"
'''
        try:
            git_wrapper.write_text(wrapper_script, encoding="utf-8")
            git_wrapper.chmod(0o755)
            self._log(f"已创建 git wrapper: {git_wrapper}")
        except OSError as e:
            self._log(f"创建 git wrapper 失败: {e}")

    def _setup_git_windows(self, git_dest: Path) -> None:
        """Windows：解压 MinGit 便携版并加入 PATH。"""
        git_zip_pattern = "git-*.zip"
        matches = sorted(Path(self._resource_dir).glob(git_zip_pattern))
        if not matches:
            self._log(f"未找到内部 git 资源: {git_zip_pattern}")
            return

        git_zip = str(matches[0])

        if git_dest.exists() and any(git_dest.iterdir()):
            self._log(f"内部 git 已存在: {git_dest}")
        else:
            self._log(f"正在解压内部 git: {Path(git_zip).name}")
            git_dest.mkdir(parents=True, exist_ok=True)
            try:
                with zipfile.ZipFile(git_zip, "r") as zf:
                    for name in zf.namelist():
                        if name.startswith("/") or ".." in Path(name).parts:
                            self._log(f"拒绝不安全的 zip 成员: {name}")
                            return
                    zf.extractall(git_dest)
                self._log(f"内部 git 解压完成: {git_dest}")
            except (OSError, zipfile.BadZipFile) as e:
                self._log(f"内部 git 解压失败: {e}")
                return

        git_cmd_dir = git_dest / "cmd"
        if not (git_cmd_dir / "git.exe").is_file():
            for git_exe in git_dest.rglob("git.exe"):
                git_cmd_dir = git_exe.parent
                break

        if not (git_cmd_dir / "git.exe").is_file():
            self._log("内部 git 目录结构异常，找不到 git.exe")
            return

        git_cmd_str = str(git_cmd_dir)
        git_binary_path = str(git_cmd_dir / "git.exe")

        self._log(f"测试内部 git: {git_binary_path}")
        test_env = os.environ.copy()
        test_env["PATH"] = git_cmd_str + os.pathsep + test_env.get("PATH", "")
        try:
            test_result = subprocess.run(
                [git_binary_path, "--version"],
                capture_output=True,
                text=True,
                timeout=TIMEOUT_SHORT_CMD,
                env=test_env,
            )
            if test_result.returncode == 0 and "git version" in test_result.stdout:
                self._log(f"内部 git 验证通过: {test_result.stdout.strip()}")
            else:
                err = test_result.stderr.strip()[:200] if test_result.stderr else "无输出"
                self._log(f"内部 git 测试失败: {err}")
                return
        except (OSError, subprocess.TimeoutExpired) as e:
            self._log(f"内部 git 测试异常: {e}")
            return

        current_path = os.environ.get("PATH", "")
        if git_cmd_str not in current_path.split(os.pathsep):
            os.environ["PATH"] = git_cmd_str + os.pathsep + current_path
            self._log(f"已设置内部 git PATH: {git_cmd_str}")