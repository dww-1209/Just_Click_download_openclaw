"""安装完成页面 — 安装流程的终点

职责：在新安装完成后，告知用户安装器使命结束、可以安全删除，
并提供「打开启动器」按钮直接唤起 Launcher（如果本地有的话）。

Windows 额外提供"创建桌面快捷方式"和"开始菜单快捷方式"的选项，
快捷方式指向启动器而非安装器——安装器装完即可删除。
"""

import os
import subprocess
from pathlib import Path

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QPushButton, QHBoxLayout, QFrame, QCheckBox,
)
from PySide6.QtCore import Qt, Signal

from src.models.constants import is_windows, is_macos


def _find_launcher() -> str | None:
    """在安装器同级目录或常见位置查找启动器

    开发模式：dist/ 目录下找 .app（macOS）/ .exe（Windows）
    打包模式：sys.executable 同级目录找
    """
    import sys
    candidates: list[Path] = []

    if getattr(sys, 'frozen', False):
        # 打包后：sys.executable 指向当前程序（安装器），
        # 启动器在同一目录下
        exe_dir = Path(sys.executable).parent
        # macOS: .app/Contents/MacOS/<name> → 回到 dist/ 层级
        if is_macos() and exe_dir.name == "MacOS":
            app_dir = exe_dir.parent.parent  # .app
            dist_dir = app_dir.parent
            candidates.append(dist_dir)
            candidates.append(exe_dir)  # 万一就在同目录
        else:
            candidates.append(exe_dir)
    else:
        # 开发模式：项目根下的 dist/
        candidates.append(Path(__file__).parent.parent.parent / "dist")

    # 常见放置位置
    home = Path.home()
    candidates.append(home / "Desktop")
    candidates.append(home / "Applications")

    # 按平台匹配文件名模式
    if is_macos():
        name_prefix = "OpenClaw启动器"
        ext = ".app"
    else:
        name_prefix = "OpenClaw启动器"
        ext = ".exe"

    for base in candidates:
        if not base.is_dir():
            continue
        for entry in base.iterdir():
            if entry.name.startswith(name_prefix) and entry.name.endswith(ext):
                return str(entry)

    return None


class InstallDonePage(QWidget):
    """安装完成页面

    展示安装成功摘要，提示用户可删除安装器，
    提供按钮打开启动器或关闭安装器。
    Windows 额外提供快捷方式创建选项。
    """

    finish_clicked = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._launcher_path: str | None = None
        self._chk_desktop: QCheckBox | None = None
        self._chk_start_menu: QCheckBox | None = None
        self._setup_ui()

    def _setup_ui(self) -> None:
        """构建完成页 UI：标题 + 说明 + 快捷方式选项(Windows) + 按钮组"""
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

        # ── Windows 快捷方式选项 ──
        # 快捷方式指向启动器而非安装器：安装器装完可删除
        if is_windows():
            layout.addSpacing(16)
            self._chk_desktop = QCheckBox("在桌面创建启动器快捷方式")
            self._chk_desktop.setChecked(True)
            self._chk_start_menu = QCheckBox("固定到开始菜单")
            self._chk_start_menu.setChecked(True)
            for chk in (self._chk_desktop, self._chk_start_menu):
                chk.setStyleSheet(
                    "QCheckBox { color: #475569; font-size: 12px; }"
                )
            layout.addWidget(self._chk_desktop)
            layout.addWidget(self._chk_start_menu)

        # ── 按钮组 ──
        layout.addSpacing(24)

        # 检测本地是否有启动器
        self._launcher_path = _find_launcher()
        if self._launcher_path:
            launcher_name = os.path.basename(self._launcher_path)
            if launcher_name.endswith(".app"):
                launcher_name = launcher_name.replace(".app", "")
            elif launcher_name.endswith(".exe"):
                launcher_name = launcher_name.replace(".exe", "")

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
        finish_btn.clicked.connect(self._on_finish_clicked)
        finish_btn_row = QHBoxLayout()
        finish_btn_row.addStretch(1)
        finish_btn_row.addWidget(finish_btn)
        finish_btn_row.addStretch(1)
        layout.addLayout(finish_btn_row)

        layout.addStretch(1)

    def _create_shortcuts_if_needed(self) -> None:
        """根据 checkbox 状态创建快捷方式(仅 Windows)

        快捷方式指向启动器,不是指向安装器。
        失败不阻塞——快捷方式不是核心功能,仅记日志。
        """
        if not is_windows():
            return
        if self._chk_desktop is None or self._chk_start_menu is None:
            return

        desktop_checked = self._chk_desktop.isChecked()
        start_menu_checked = self._chk_start_menu.isChecked()
        if not desktop_checked and not start_menu_checked:
            return

        # 快捷方式目标必须是启动器而非安装器
        from src.adapters.manage_shortcuts import create_shortcuts
        target = self._launcher_path  # 启动器 exe 路径
        create_shortcuts(desktop_checked, start_menu_checked, target=target)

    def _on_open_launcher(self) -> None:
        """尝试打开本地启动器,同时创建 Windows 快捷方式"""
        self._create_shortcuts_if_needed()

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

    def _on_finish_clicked(self) -> None:
        """点击「完成」：创建快捷方式(Windows)，退出安装器"""
        self._create_shortcuts_if_needed()
        self.finish_clicked.emit()
