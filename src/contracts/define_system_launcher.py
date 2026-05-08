"""系统集成接口定义

抽象终端、浏览器等系统级唤起操作,使 UI 层无需关心底层实现细节。
未来若需支持新终端模拟器(WSL、kitty、iTerm 等)或其他启动机制,
只需在 adapter 层扩展,UI 层不需要改动。
"""

from __future__ import annotations

from typing import Protocol, Sequence


class ISystemLauncher(Protocol):
    """系统启动器接口。

    负责跨平台唤起终端、浏览器等系统外部程序。
    UI 层只调用接口,具体实现由 adapter 层提供。
    """

    def open_terminal_command(
        self,
        command_candidates: Sequence[str],
        args: Sequence[str],
    ) -> bool:
        """在系统终端中打开并执行命令。

        Args:
            command_candidates: 候选命令名列表(按优先级,首个 PATH 中存在的会被选用),
                                例如 ("openclaw-cn", "openclaw")
            args: 命令参数,例如 ("config",)

        Returns:
            是否成功唤起终端。
        """
        ...

    def open_url(self, url: str) -> bool:
        """在系统默认浏览器中打开 URL。

        Args:
            url: 必须以 http:// 或 https:// 开头的合法 URL。

        Returns:
            是否成功唤起浏览器。
        """
        ...
