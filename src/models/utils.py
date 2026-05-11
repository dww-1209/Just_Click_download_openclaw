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

from src.models.constants import is_windows, is_macos, TIMEOUT_SHORT_CMD


def windows_hidden_subprocess_kwargs() -> dict:
    """返回用于隐藏控制台窗口的 subprocess 关键字参数字典(仅 Windows 有效)。

    Windows GUI 程序(无 console)通过 subprocess 调用 cmd/where/taskkill 等
    控制台程序时，操作系统会创建一个**新的**控制台窗口短暂闪烁。需要同时:
    - STARTUPINFO + STARTF_USESHOWWINDOW + SW_HIDE: 即使被显示也立刻隐藏
    - CREATE_NO_WINDOW: 直接告诉系统不要创建新 console

    其他平台返回空 dict, 调用方可以无脑 ** 展开:
        subprocess.run(cmd, **windows_hidden_subprocess_kwargs(), capture_output=True, ...)

    Returns:
        dict: Windows 上含 startupinfo / creationflags 两个键; 其他平台为空 dict。
    """
    if not is_windows():
        return {}

    startupinfo = subprocess.STARTUPINFO()
    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startupinfo.wShowWindow = subprocess.SW_HIDE
    return {
        "startupinfo": startupinfo,
        "creationflags": subprocess.CREATE_NO_WINDOW,
    }


def kill_port_process(port: int, on_log: Callable[[str], None] | None = None) -> int:
    """释放被占用的本地端口(用于卸载/重装场景终结 Gateway 进程)。

    与 OpenClawManager._kill_port_process 等价,但作为独立函数提供给
    cleanup_reinstall 等无 manager 实例的场景使用。隐藏子进程窗口。

    Args:
        port: 端口号 (1-65535)。
        on_log: 可选的日志回调。

    Returns:
        int: 被结束的进程数量(如果检测/解析失败返回 0)。
    """
    try:
        port = int(port)
    except (TypeError, ValueError):
        return 0
    if not (1 <= port <= 65535):
        return 0

    hidden = windows_hidden_subprocess_kwargs()
    killed = 0

    if is_windows():
        try:
            result = subprocess.run(
                ["netstat", "-ano"],
                capture_output=True, text=True, timeout=15,
                **hidden,
            )
        except (OSError, subprocess.SubprocessError):
            return 0
        if result.returncode != 0 or not result.stdout:
            return 0

        killed_pids: set[str] = set()
        for line in result.stdout.splitlines():
            fields = line.split()
            if len(fields) < 4:
                continue
            proto = fields[0].upper()
            if proto not in ("TCP", "UDP", "TCP6", "UDP6"):
                continue
            local_addr = fields[1]
            if not (local_addr.endswith(f":{port}") or local_addr.endswith(f"]:{port}")):
                continue
            pid = fields[-1]
            if not pid.isdigit() or pid in killed_pids:
                continue
            killed_pids.add(pid)
            try:
                subprocess.run(
                    ["taskkill", "/PID", pid, "/F", "/T"],
                    capture_output=True, timeout=10, **hidden,
                )
                killed += 1
                if on_log:
                    on_log(f"已终止占用端口 {port} 的进程 PID={pid}")
            except (OSError, subprocess.SubprocessError):
                pass
    else:
        try:
            result = subprocess.run(
                ["lsof", "-ti", f":{port}"],
                capture_output=True, text=True, timeout=15,
            )
        except (OSError, subprocess.SubprocessError):
            return 0
        if result.returncode != 0 or not result.stdout:
            return 0

        for pid in result.stdout.strip().splitlines():
            pid = pid.strip()
            if not pid.isdigit():
                continue
            try:
                subprocess.run(["kill", "-9", pid], capture_output=True, timeout=10)
                killed += 1
                if on_log:
                    on_log(f"已终止占用端口 {port} 的进程 PID={pid}")
            except (OSError, subprocess.SubprocessError):
                pass

    return killed


def force_rmtree(path: str | Path, on_log: Callable[[str], None] | None = None) -> bool:
    """强制删除目录树,模仿 Mac rm -rf 的语义:逐文件删,锁住的跳过。

    三步:
    1. chmod/attrib 去只读属性,确保文件可删。
    2. _rmtree_skip_locked 自底向上遍历,逐个 os.unlink/os.rmdir。
       单个文件失败(锁住/权限不够)就跳过,不影响其他文件的删除。
       不像 Windows rmdir /s /q 那样"一个文件锁了整棵树留下"。
    3. 还有残留(锁住的文件删不掉)就 os.rename 移出权威路径,
       残渣后台清理。NTFS rename 不受子文件锁影响,几乎瞬间完成。

    Args:
        path: 要删除的目录路径。
        on_log: 可选的日志回调。

    Returns:
        True 表示权威路径已清理(目录不存在或已改名);
        False 表示连改名都失败(被 Explorer/CWD 锁死)。
    """
    path_str = str(path)
    if not os.path.exists(path_str):
        return True

    # 去掉只读属性,等效 Mac 的 chmod -R +w。
    # pnpm 依赖目录有时带只读位,不先去掉 os.unlink/os.rmdir 会失败。
    if is_windows():
        try:
            subprocess.run(
                ["cmd", "/c", "attrib", "-R", path_str + "\\*", "/S", "/D"],
                capture_output=True, timeout=30,
                **windows_hidden_subprocess_kwargs(),
            )
        except (OSError, subprocess.SubprocessError):
            pass
    else:
        try:
            subprocess.run(
                ["chmod", "-R", "+w", path_str],
                capture_output=True, timeout=30,
            )
        except (OSError, subprocess.SubprocessError):
            pass

    # 逐文件删除: 遇到锁住/权限不够的跳过,能删多少删多少。
    # 这等效 Mac 上 rm -rf 的语义 —— 不像 Windows rmdir /s /q 那样
    # "一个文件锁了整棵树留下",而是逐个文件尝试,失败的跳过,其他照删。
    # 传入 on_log 让删除大目录(node_modules ~100k 文件)时定期发心跳,
    # 否则 Windows + Defender 下几十秒一句话不输出,用户会以为程序卡死。
    _rmtree_skip_locked(path_str, on_log)

    # 目录已清空
    if not os.path.exists(path_str):
        if on_log:
            on_log(f"已删除: {path_str}")
        return True

    # 还有残留(锁住删不掉的文件) → rename 出去,权威路径立刻空出。
    try:
        import time as _time
        residue_path = f"{path_str}._residue.{int(_time.time())}"
        os.rename(path_str, residue_path)
        if on_log:
            on_log(f"已隔离残留: {os.path.basename(residue_path)}")
        # 残渣后台清理,不阻塞主流程
        try:
            if is_windows():
                subprocess.run(
                    ["cmd", "/c", "rmdir", "/s", "/q", residue_path],
                    capture_output=True, timeout=60,
                    **windows_hidden_subprocess_kwargs(),
                )
            else:
                subprocess.run(
                    ["rm", "-rf", residue_path],
                    capture_output=True, timeout=60,
                )
        except (OSError, subprocess.SubprocessError):
            pass
        return True
    except OSError:
        if on_log:
            on_log(f"删除 {path_str} 失败: 目录被占用")
        return False


def _rmtree_skip_locked(
    root_path: str,
    on_log: Callable[[str], None] | None = None,
) -> None:
    """逐文件删除目录树,锁住/权限不够的文件跳过,能删多少删多少。

    自底向上(os.walk topdown=False)遍历:先删子文件再删父目录。
    单个文件失败只跳过这一个,不影响其他文件的删除。这是 Mac rm -rf 的行为。

    Args:
        root_path: 要删除的目录树根路径。
        on_log: 可选的日志回调。删除大目录(node_modules)时,Windows+Defender
            可能让总耗时达分钟级,期间没有任何输出会让用户以为程序卡死。
            因此每删 5000 个 entry 输出一次心跳。
    """
    entries: list[tuple[str, bool]] = []  # [(path, is_dir), ...]
    try:
        for dirpath, dirnames, filenames in os.walk(root_path, topdown=False):
            for fn in filenames:
                entries.append((os.path.join(dirpath, fn), False))
            for dn in dirnames:
                entries.append((os.path.join(dirpath, dn), True))
    except OSError:
        pass

    total = len(entries)
    # 大目录(>10k entry)才出心跳,小目录避免噪音
    heartbeat = on_log is not None and total > 10000
    if heartbeat and on_log:
        on_log(f"开始删除 {total} 个文件/目录(大型目录可能需要数分钟,请耐心等待)...")

    deleted = 0
    for entry_path, is_dir in entries:
        try:
            if is_dir:
                os.rmdir(entry_path)
            else:
                os.unlink(entry_path)
        except OSError:
            # 权限不够:加写权限后重试一次
            try:
                os.chmod(entry_path, stat.S_IWRITE | stat.S_IREAD)
                if is_dir:
                    os.rmdir(entry_path)
                else:
                    os.unlink(entry_path)
            except OSError:
                pass  # 真删不掉就算了,最后剩下的会被 rename 出去

        deleted += 1
        # 每 5000 个 entry 一次心跳。频率不高于 ~30Hz 才不会拖累 UI(信号洪水),
        # 5000 文件在 SSD+无 Defender 是 ~0.5s,Windows+Defender 是 ~30s。
        if heartbeat and on_log and deleted % 5000 == 0:
            on_log(f"已删除 {deleted}/{total} ({deleted * 100 // total}%)...")


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
        hidden = windows_hidden_subprocess_kwargs()
        for cmd in ["openclaw-cn", "openclaw"]:
            try:
                result = subprocess.run(
                    ["where", cmd],
                    shell=False,
                    capture_output=True,
                    timeout=TIMEOUT_SHORT_CMD,
                    **hidden,
                )
                if result.returncode == 0:
                    return cmd
            except (OSError, subprocess.SubprocessError):
                pass
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
        default_rc = ".zshrc" if is_macos() else ".bashrc"
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


def redact_home_path(text: str) -> str:
    """将文本中的用户主目录路径替换为 ``~``,降低截图/日志分享时的隐私泄露风险。

    诊断日志和命令展示常常带绝对路径(如 ``C:\\Users\\<name>\\openclaw-cn``),
    一旦截屏发到 issue/客服群,就把用户名暴露出去。这个函数仅做一层简单替换,
    不影响文本里其他内容。

    分别尝试原始 home、正斜杠版、反斜杠版,以兼容跨平台路径混用的日志输出
    (Windows 上某些子进程会回吐 / 风格的路径,反之亦然)。

    Args:
        text: 任意文本,空字符串/None 直接原样返回。

    Returns:
        替换后的文本。若无法解析 home,返回原始文本。
    """
    if not text:
        return text
    home = os.path.expanduser("~")
    if not home or home == "~":
        return text
    text = text.replace(home, "~")
    home_fwd = home.replace("\\", "/")
    if home_fwd != home:
        text = text.replace(home_fwd, "~")
    home_bwd = home.replace("/", "\\")
    if home_bwd != home:
        text = text.replace(home_bwd, "~")
    return text


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
        # 在校验前先把成员名中的反斜杠归一为正斜杠。
        # tar 规范要求路径分隔符为 "/"，任何反斜杠都视作可疑：
        # - Windows 下 Path("foo\\..\\bar") 会被识别为 ".." 组件并被拦截，
        # - 但 POSIX 下 Path("foo\\..\\bar").parts 只看到一个组件 "foo\\..\\bar"，
        #   会漏检；统一归一后再走下面的检查就能在所有平台一致拦截。
        normalized_name = member.name.replace("\\", "/")
        normalized_parts = Path(normalized_name).parts

        # 拒绝绝对路径（POSIX 的 / 开头、Windows 的盘符、UNC 路径）和包含 .. 的原始路径
        is_absolute = (
            normalized_name.startswith("/")
            or normalized_name.startswith("//")  # UNC 形式
            or (len(normalized_name) >= 2 and normalized_name[1] == ":")  # Windows 盘符
        )
        if is_absolute or ".." in normalized_parts:
            msg = f"拒绝不安全的 tar 成员: {member.name}"
            if on_log:
                on_log(msg)
            raise tarfile.TarError(msg)

        # 校验最终解析后的绝对路径是否在目标目录内（第二层过滤）
        member_path = (dest_path / normalized_name).resolve()
        try:
            member_path.relative_to(dest_path)
        except ValueError:
            msg = f"拒绝不安全的 tar 成员: {member.name} -> {member_path}"
            if on_log:
                on_log(msg)
            raise tarfile.TarError(msg)

        # 拒绝设备文件（字符设备/块设备），防止恶意 tar 包创建设备节点
        if member.isdev():
            msg = f"拒绝 tar 设备文件: {member.name}"
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
