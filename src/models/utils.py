"""模型层公共工具函数

职责：提供纯数据/工具辅助函数，供 models、core、adapters 等各层共享使用。

设计原则：
- 本层只包含不依赖任何业务逻辑和系统调用的纯工具函数。
- 若函数涉及文件系统操作但属于通用辅助（如 remove_readonly），也可放在此处。
"""

from __future__ import annotations

import os
import shutil
import stat
import subprocess
import tarfile
from pathlib import Path
from typing import Callable, Any, Optional

from src.models.constants import is_windows, TIMEOUT_SHORT_CMD


def force_rmtree(path: str | Path, on_log: Callable[[str], None] | None = None) -> bool:
    """强制删除目录树，处理只读文件和复杂目录结构。

    Python 3.12+ 的 shutil.rmtree 使用 _rmtree_safe_fd，onerror 回调
    在处理 os.open 时存在重试语义问题，可能导致子树未被删除。本函数
    绕过 Python shutil：先给整棵树加写权限，再用平台原生命令删除。

    Args:
        path: 要删除的目录路径。
        on_log: 可选的日志回调。

    Returns:
        True 表示删除成功或目录不存在；False 表示删除失败。
    """
    path_str = str(path)
    if not os.path.exists(path_str):
        return True

    if is_windows():
        # 先去掉只读属性，再强制删除
        try:
            subprocess.run(
                ["cmd", "/c", "attrib", "-R", path_str + "\\*", "/S", "/D"],
                capture_output=True, timeout=30,
            )
        except (OSError, subprocess.SubprocessError):
            pass
        try:
            result = subprocess.run(
                ["cmd", "/c", "rmdir", "/s", "/q", path_str],
                capture_output=True, timeout=60,
            )
            return result.returncode == 0
        except (OSError, subprocess.SubprocessError) as e:
            if on_log:
                on_log(f"删除 {path_str} 失败: {e}")
            return False
    else:
        # 先 chmod -R +w 给所有文件/目录加上写权限。
        # 某些 pnpm 依赖目录权限极端（如 d-w-------，只有写无读/执行），
        # rm -rf 需要遍历（读+执行）和删除（写）权限，这里统一加写权限即可，
        # 比 777 更收敛，避免临时暴露敏感文件给其他用户。
        try:
            subprocess.run(
                ["chmod", "-R", "+w", path_str],
                capture_output=True, timeout=30,
            )
        except (OSError, subprocess.SubprocessError):
            pass
        try:
            result = subprocess.run(
                ["rm", "-rf", path_str],
                capture_output=True, timeout=60,
            )
            if result.returncode != 0 and on_log:
                err = result.stderr.decode("utf-8", errors="replace") if result.stderr else ""
                on_log(f"删除 {path_str} 失败: {err}")
            return result.returncode == 0
        except (OSError, subprocess.SubprocessError) as e:
            if on_log:
                on_log(f"删除 {path_str} 失败: {e}")
            return False


def remove_readonly(func: Callable[..., None], path: str, _: Any) -> None:
    """shutil.rmtree 的 onerror 回调：移除只读属性后重试删除操作。

    用途：删除可能包含只读文件（如 Git 仓库中的文件）的目录时，
    先修改文件权限再重试删除操作。

    注意：Python 3.12+ 的 shutil.rmtree 内部使用 _rmtree_safe_fd，
    此时 func 可能是 os.open（需要 flags 参数）。遇到 os.open 时只修改
    权限并返回，让 rmtree 自动重试；其他情况（os.unlink/os.rmdir）
    正常调用删除。
    """
    os.chmod(path, stat.S_IWRITE)
    if func is os.open:
        # os.open 需要 flags 参数，在 _rmtree_safe_fd 内部使用。
        # 我们只负责修改权限，rmtree 会自动重试。
        return
    func(path)


def resolve_openclaw_cmd(env: Optional[dict] = None) -> str:
    """检测系统中可用的 openclaw 命令。

    优先检测 openclaw-cn，fallback 到 openclaw。
    Windows 使用 where 命令（能正确处理 %APPDATA% 等环境变量展开），
    Linux/macOS 使用 shutil.which。

    Args:
        env: 可选的环境变量字典，用于 Linux/macOS 的自定义 PATH 检测。

    Returns:
        str: 检测到的命令名（如 "openclaw-cn"），若都未找到则返回 "openclaw"。
    """
    if is_windows():
        for cmd in ["openclaw-cn", "openclaw"]:
            result = subprocess.run(
                ["where", cmd],
                shell=False,
                capture_output=True,
                timeout=TIMEOUT_SHORT_CMD,
            )
            if result.returncode == 0:
                return cmd
    else:
        path_env = env.get("PATH", os.environ.get("PATH", "")) if env else os.environ.get("PATH", "")
        for cmd in ["openclaw-cn", "openclaw"]:
            if shutil.which(cmd, path=path_env) is not None:
                return cmd
    return "openclaw"


def ensure_dir_in_path(directory: str, on_log: Callable[[str], None] | None = None) -> None:
    """将指定目录持久化到用户 shell 配置文件的 PATH 中。

    会依次检查 .bashrc、.zshrc、.profile，避免重复写入。
    这是为"安装完成后用户新开终端能直接使用命令"做的持久化配置。

    Args:
        directory: 要加入 PATH 的目录绝对路径。
        on_log: 可选的日志回调函数，用于输出操作结果。
    """
    # Windows 平台无 bashrc/zshrc 概念，直接跳过
    if is_windows():
        if on_log:
            on_log("Windows 平台跳过 shell 配置写入")
        return

    path_export = f'export PATH="{directory}:$PATH"'

    home = os.path.expanduser("~")
    written = False
    for rc_file in [".bashrc", ".zshrc", ".profile"]:
        rc_path = os.path.join(home, rc_file)
        if os.path.exists(rc_path):
            try:
                with open(rc_path, "r", encoding="utf-8") as f:
                    content = f.read()
                if directory in content:
                    if on_log:
                        on_log(f"{rc_file} 已包含 {directory}")
                    written = True
                    continue
                with open(rc_path, "a", encoding="utf-8") as f:
                    f.write(f"\n# Added by OpenClaw Installer\n{path_export}\n")
                if on_log:
                    on_log(f"已将 {directory} 添加到 {rc_file}")
                written = True
            except OSError as e:
                if on_log:
                    on_log(f"修改 {rc_file} 失败: {e}")

    # 如果没有任何 rc 文件存在（全新系统），主动创建一个
    if not written:
        # macOS 默认 zsh，Linux 默认 bash
        default_rc = ".zshrc" if sys.platform == "darwin" else ".bashrc"
        rc_path = os.path.join(home, default_rc)
        try:
            with open(rc_path, "w", encoding="utf-8") as f:
                f.write(f"# Created by OpenClaw Installer\n{path_export}\n")
            if on_log:
                on_log(f"已创建 {default_rc} 并添加 {directory}")
        except OSError as e:
            if on_log:
                on_log(f"创建 {default_rc} 失败: {e}")


def ensure_local_bin_in_path(on_log: Callable[[str], None] | None = None) -> None:
    """确保 ~/.local/bin 被写入用户 shell 配置文件。

    这是 ensure_dir_in_path 的便捷封装，用于 openclaw 命令包装器的 PATH 持久化。
    """
    home = os.path.expanduser("~")
    local_bin = os.path.join(home, ".local", "bin")
    ensure_dir_in_path(local_bin, on_log)


def detect_openclaw_installation() -> tuple[bool, list[str]]:
    """检测用户主目录下是否存在 OpenClaw 安装记录。

    检查两个目录:
    - ~/openclaw-cn: 程序源码/构建目录
    - ~/.openclaw: 配置文件目录

    Returns:
        (是否已安装, 检测到的目录描述列表)
    """
    home = os.path.expanduser("~")
    details: list[str] = []
    if os.path.exists(os.path.join(home, "openclaw-cn")):
        details.append("程序文件: ~/openclaw-cn")
    if os.path.exists(os.path.join(home, ".openclaw")):
        details.append("配置文件: ~/.openclaw")
    return bool(details), details


def safe_tar_extract(
    tar: tarfile.TarFile,
    dest: Path | str,
    on_log: Callable[[str], None] | None = None,
) -> None:
    """安全解压 tar 包，防止路径遍历攻击（zip-slip）。

    校验每个成员的最终解析后的绝对路径是否在目标目录内，
    同时校验软链接目标是否逃逸出目标目录。
    所有 Python 版本统一走手动校验路径，确保行为一致且异常可感知。

    Args:
        tar: 已打开的 tarfile 对象。
        dest: 解压目标目录。
        on_log: 可选的日志回调，用于输出拒绝信息。

    Raises:
        tarfile.TarError: 当发现不安全的路径遍历成员时抛出。
    """
    dest_path = Path(dest).resolve()

    for member in tar.getmembers():
        # 拒绝绝对路径和包含 .. 的原始路径（第一层过滤）
        # 使用 Path.parts 精确检测路径遍历组件，避免误杀合法文件名如 foo..bar.txt
        if member.name.startswith("/") or ".." in Path(member.name).parts:
            msg = f"拒绝不安全的 tar 成员: {member.name}"
            if on_log:
                on_log(msg)
            raise tarfile.TarError(msg)

        # 校验最终解析后的绝对路径是否在目标目录内（第二层过滤）
        member_path = (dest_path / member.name).resolve()
        try:
            member_path.relative_to(dest_path)
        except ValueError:
            msg = f"拒绝不安全的 tar 成员: {member.name} -> {member_path}"
            if on_log:
                on_log(msg)
            raise tarfile.TarError(msg)

        # 校验软链接目标是否逃逸出目标目录
        # 注意：软链接目标应相对于软链接文件所在目录解析，而非解压目标目录
        if member.issym() or member.islnk():
            link_target = (member_path.parent / member.linkname).resolve()
            try:
                link_target.relative_to(dest_path)
            except ValueError:
                msg = f"拒绝不安全的软链接目标: {member.linkname}"
                if on_log:
                    on_log(msg)
                raise tarfile.TarError(msg)

    tar.extractall(dest)
