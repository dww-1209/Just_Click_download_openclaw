"""系统集成 adapter — 跨平台终端/浏览器唤起实现

实现 ISystemLauncher 协议,封装所有 subprocess、webbrowser、osascript 调用。
所有跨平台差异处理收敛在此模块,UI 层不接触任何系统调用 API。
"""

from __future__ import annotations

import shlex
import shutil
import subprocess
import webbrowser
from typing import Sequence

from src.models.constants import is_windows, is_macos


class SystemLauncher:
    """跨平台系统启动器,实现 ISystemLauncher 协议。

    平台策略:
    - Windows: subprocess.Popen + CREATE_NEW_CONSOLE / cmd start
    - macOS:  AppleScript (osascript) 唤起 Terminal / 默认浏览器
    - Linux:  依次尝试 gnome-terminal / xterm / konsole 终端模拟器
    """

    def open_terminal_command(
        self,
        command_candidates: Sequence[str],
        args: Sequence[str],
    ) -> bool:
        """在系统终端中打开并执行命令。

        从候选列表中按顺序选择第一个 PATH 中存在的命令,然后跨平台唤起终端。

        Args:
            command_candidates: 候选命令名列表(按优先级排序)。
            args: 命令参数列表。

        Returns:
            是否成功唤起终端。
        """
        # 选第一个在 PATH 中存在的候选命令
        command = next(
            (c for c in command_candidates if shutil.which(c)),
            None,
        )
        if command is None:
            return False

        cmd_path = shutil.which(command)
        if not cmd_path:
            return False

        try:
            if is_windows():
                # Windows: 直接通过 CREATE_NEW_CONSOLE 弹出新窗口,避免 shell 字符串拼接
                subprocess.Popen(
                    [cmd_path, *args],
                    creationflags=subprocess.CREATE_NEW_CONSOLE,
                )
                return True
            if is_macos():
                # macOS: 通过 AppleScript 唤起 Terminal,内嵌命令需做引号转义
                joined = " ".join(shlex.quote(a) for a in [command, *args])
                escaped = joined.replace('"', '\\"')
                script = f'tell application "Terminal" to do script "{escaped}"'
                subprocess.Popen(["osascript", "-e", script])
                return True
            # Linux: 依次尝试常见终端模拟器,使用 shlex.quote 防止命令注入
            joined = " ".join(shlex.quote(a) for a in [command, *args])
            terminals = [
                ["gnome-terminal", "--", "bash", "-c", f"{joined}; exec bash"],
                ["xterm", "-e", "bash", "-c", f"{joined}; exec bash"],
                ["konsole", "-e", "bash", "-c", f"{joined}; exec bash"],
            ]
            for term in terminals:
                if shutil.which(term[0]):
                    subprocess.Popen(term)
                    return True
            return False
        except (OSError, subprocess.SubprocessError):
            return False

    def open_url(self, url: str) -> bool:
        """在系统默认浏览器中打开 URL。

        优先使用 Python webbrowser 模块,Windows 失败时回退到 cmd start。

        Args:
            url: 必须以 http:// 或 https:// 开头的合法 URL。

        Returns:
            是否成功唤起浏览器。
        """
        # 拒绝非 http(s) 协议,防止 file://、javascript: 等被误用
        if not url.startswith(("http://", "https://")):
            return False

        try:
            if webbrowser.open(url, new=2):
                return True
        except (OSError, webbrowser.Error):
            pass

        # Windows fallback: 通过 cmd start 唤起默认浏览器
        if is_windows():
            try:
                subprocess.run(
                    ["cmd", "/c", "start", "", url],
                    shell=False,
                    capture_output=True,
                )
                return True
            except OSError:
                pass

        return False
