"""安装完成页面 — 安装流程的终点

职责：在新安装完成后，告知用户安装器使命结束、可以安全删除，
并提供「打开启动器」按钮直接唤起 Launcher（如果本地有的话）。

与 US06StartupPage 的区别：
- 不启动 Gateway，不配 Provider，只做"收尾 + 引导"
- 用户确认后关闭安装器，日常使用交给 Launcher
"""

import os
import subprocess
from pathlib import Path

from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel, QPushButton, QHBoxLayout, QFrame
from PySide6.QtCore import Qt, Signal

from src.models.constants import is_windows, is_macos


def _find_launcher_app() -> str | None:
    """在当前目录（dist/ 或 .app 同级）查找启动器

    开发模式：dist/ 目录下找 .app
    打包模式：PyInstaller _MEIPASS 同级找 .app
    """
    # 优先：可执行文件所在目录（打包后 .app/Contents/MacOS/ → 回到 dist/ 同级）
    import sys
    candidates: list[Path] = []

    if getattr(sys, 'frozen', False):
        # 打包后：sys.executable 在 .app/Contents/MacOS/<name>
        exe_dir = Path(sys.executable).parent  # Contents/MacOS
        app_dir = exe_dir.parent.parent        # .app
        dist_dir = app_dir.parent              # dist/ 或用户放的位置
        candidates.append(dist_dir)
    else:
        # 开发模式：项目根下的 dist/
        candidates.append(Path(__file__).parent.parent.parent / "dist")

    # 同时检查用户桌面和 ~/Applications（常见放置位置）
    home = Path.home()
    candidates.append(home / "Desktop")
    candidates.append(home / "Applications")

    for base in candidates:
        if not base.is_dir():
            continue
        # 匹配 OpenClaw启动器*.app（支持 -arm64、-x64 等后缀）
        for entry in base.iterdir():
            if entry.name.startswith("OpenClaw启动器") and entry.name.endswith(".app"):
                return str(entry)

    return None


class InstallDonePage(QWidget):
    """安装完成页面

    展示安装成功摘要，提示用户可删除安装器，
    并提供按钮打开启动器或关闭安装器。
    """

    finish_clicked = Signal()
    open_launcher_clicked = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._launcher_path: str | None = None
        self._setup_ui()

    def _setup_ui(self) -> None:
        """构建完成页 UI：标题 + 说明 + 按钮组"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(56, 60, 56, 40)
        layout.setSpacing(0)

        # ── 成功图标 ──
        check_row = QHBoxLayout()
        check_row.setContentsMargins(0, 0, 0, 0)
        check_row.addStretch(1)
        check = QLabel("✓")
        check.setAlignment(Qt.AlignCenter)
        check.setFixedSize(64, 64)
        check.setStyleSheet(
            "background-color: #16A34A; color: white; "
            "border-radius: 32px; font-size: 32px; font-weight: 700;"
        )
        check_row.addWidget(check)
        check_row.addStretch(1)
        layout.addLayout(check_row)

        # ── 标题 ──
        layout.addSpacing(24)
        title = QLabel("安装完成")
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet(
            "color: #0F172A; font-size: 28px; font-weight: 700; "
            "letter-spacing: -0.5px; background: transparent; border: none;"
        )
        layout.addWidget(title)

        # ── 说明文字 ──
        layout.addSpacing(16)

        desc_card = QFrame()
        desc_card.setObjectName("doneCard")
        desc_card.setStyleSheet(
            "QFrame#doneCard { background-color: #F8FAFC; border: 1px solid #E2E8F0; "
            "border-radius: 8px; }"
            "QFrame#doneCard QLabel { background: transparent; border: none; }"
        )
        desc_layout = QVBoxLayout(desc_card)
        desc_layout.setContentsMargins(20, 16, 20, 16)
        desc_layout.setSpacing(8)

        lines = [
            ("提示", "color: #475569; font-size: 11px; font-weight: 600; letter-spacing: 1.5px;"),
            ("OpenClaw 已成功安装到您的电脑。", "color: #0F172A; font-size: 13px;"),
            ("", ""),
            ("本安装器已完成使命，可以安全删除以释放磁盘空间。", "color: #64748B; font-size: 12px;"),
            ("日常使用请打开 <b>OpenClaw 启动器</b>，轻量且仅需 40MB。", "color: #64748B; font-size: 12px;"),
        ]
        for text, style in lines:
            if not text:
                continue
            label = QLabel(text)
            label.setWordWrap(True)
            label.setStyleSheet(style)
            label.setAlignment(Qt.AlignLeft)
            desc_layout.addWidget(label)

        layout.addWidget(desc_card)

        # ── 按钮组 ──

        layout.addSpacing(24)

        # 检测本地是否有启动器
        self._launcher_path = _find_launcher_app()
        if self._launcher_path:
            launcher_name = os.path.basename(self._launcher_path).replace(".app", "")
            launcher_btn = QPushButton(f"打开 {launcher_name}")
            launcher_btn.setObjectName("primaryButton")
            launcher_btn.setCursor(Qt.PointingHandCursor)
            launcher_btn.setFixedHeight(44)
            launcher_btn.clicked.connect(self._on_open_launcher)
            launcher_btn_row = QHBoxLayout()
            launcher_btn_row.addStretch(1)
            launcher_btn_row.addWidget(launcher_btn)
            launcher_btn_row.addStretch(1)
            layout.addLayout(launcher_btn_row)
            layout.addSpacing(12)

        # 完成按钮
        finish_btn = QPushButton("完成" if self._launcher_path else "关闭安装器")
        finish_btn.setFixedHeight(36)
        finish_btn.setStyleSheet(
            "QPushButton { color: #64748B; font-size: 13px; border: 1px solid #E2E8F0; "
            "border-radius: 6px; background: white; }"
            "QPushButton:hover { background: #F1F5F9; color: #0F172A; }"
        )
        finish_btn.setCursor(Qt.PointingHandCursor)
        finish_btn.clicked.connect(self.finish_clicked.emit)
        finish_btn_row = QHBoxLayout()
        finish_btn_row.addStretch(1)
        finish_btn_row.addWidget(finish_btn)
        finish_btn_row.addStretch(1)
        layout.addLayout(finish_btn_row)

        layout.addStretch(1)

    def _on_open_launcher(self) -> None:
        """尝试打开本地启动器"""
        if not self._launcher_path:
            return
        try:
            if is_macos():
                subprocess.Popen(
                    ["open", self._launcher_path],
                    start_new_session=True,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            elif is_windows():
                os.startfile(self._launcher_path)
        except (OSError, subprocess.SubprocessError):
            pass
