"""卸载工具 —— 确认/检测页面。

职责：卸载流程的第一页。检测用户系统中是否存在 OpenClaw 安装记录
（程序目录 ~/openclaw-cn 与配置目录 ~/.openclaw），并根据检测结果展示
不同的状态卡片与操作按钮：
- 已安装：展示警告清单，提供「确认卸载」按钮
- 未安装：提示无需卸载，仅提供「退出」按钮
"""

import os

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QPushButton, QHBoxLayout,
    QFrame, QScrollArea,
)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont


class UninstallWelcomePage(QWidget):
    """卸载工具欢迎页 —— 检测 OpenClaw 安装状态并请求用户确认卸载。

    职责：作为卸载流程的第一页，在初始化时自动检测系统中是否存在 OpenClaw
    安装记录（程序目录 ~/openclaw-cn 与配置目录 ~/.openclaw）。根据检测结果
    动态切换 UI：
    - 已安装：展示红色状态卡片 + 警告清单，提供「确认卸载」按钮
    - 未安装：展示绿色状态卡片，仅提供「退出」按钮
    """

    confirm_clicked = Signal()  # 用户点击「确认卸载」，触发进入卸载进度页
    cancel_clicked = Signal()   # 用户点击「取消/退出」，触发关闭卸载工具

    def __init__(self, parent=None):
        super().__init__(parent)
        self.installed = False
        self._setup_ui()
        self._check_installation()

    def _setup_ui(self):
        # 主布局：上部为可滚动内容区，下部为固定按钮栏。
        # 使用 QScrollArea 保证在小屏设备上警告清单不会被截断。
        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(10)
        main_layout.setContentsMargins(24, 24, 24, 24)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setSpacing(15)
        layout.setContentsMargins(40, 20, 40, 20)

        # 标题
        title = QLabel("OpenClaw 卸载工具")
        title.setAlignment(Qt.AlignCenter)
        tf = QFont()
        tf.setPointSize(20)
        tf.setBold(True)
        title.setFont(tf)

        # 状态区域：动态展示检测中 / 已安装 / 未安装三种状态
        # 使用浅灰背景卡片，与页面底色形成层次对比
        self.status_frame = QFrame()
        self.status_frame.setStyleSheet(
            "QFrame { background-color: #f8f9fa; border-radius: 8px; }"
            "QFrame QLabel { background: transparent; border: none; }"
        )
        sf_layout = QVBoxLayout(self.status_frame)
        sf_layout.setContentsMargins(20, 16, 20, 16)
        sf_layout.setSpacing(8)

        self.status_icon = QLabel("🔍")
        self.status_icon.setAlignment(Qt.AlignCenter)
        self.status_icon.setStyleSheet("font-size: 32px; background: transparent; border: none;")

        self.status_title = QLabel("正在检测...")
        self.status_title.setAlignment(Qt.AlignCenter)
        stf = QFont()
        stf.setPointSize(14)
        stf.setBold(True)
        self.status_title.setFont(stf)

        self.status_detail = QLabel("")
        self.status_detail.setAlignment(Qt.AlignCenter)
        self.status_detail.setWordWrap(True)
        self.status_detail.setStyleSheet("color: #666; font-size: 12px;")

        sf_layout.addWidget(self.status_icon)
        sf_layout.addWidget(self.status_title)
        sf_layout.addWidget(self.status_detail)

        # 警告区域（仅已安装时显示）
        # 使用红色背景卡片，明确告知用户卸载的不可逆后果，
        # 尤其强调 API Key 等敏感配置的删除，避免用户事后追责。
        self.warning_frame = QFrame()
        self.warning_frame.setStyleSheet(
            "QFrame { background-color: #fff3f3; border-radius: 8px; }"
            "QFrame QLabel { background: transparent; border: none; }"
        )
        wf_layout = QVBoxLayout(self.warning_frame)
        wf_layout.setContentsMargins(16, 12, 16, 12)
        wf_layout.setSpacing(6)

        warn_title = QLabel("⚠️  卸载将永久删除以下内容")
        warn_title.setStyleSheet("color: #c62828; font-weight: bold; font-size: 13px;")

        warn_list = QLabel(
            "• OpenClaw 程序文件（~/openclaw-cn）\n"
            "• 所有配置文件（~/.openclaw，含 API Key）\n"
            "• 命令行工具（openclaw / openclaw-cn）\n"
            "• Gateway 服务进程"
        )
        warn_list.setStyleSheet("color: #b71c1c; font-size: 12px; line-height: 1.6;")

        wf_layout.addWidget(warn_title)
        wf_layout.addWidget(warn_list)
        self.warning_frame.hide()

        layout.addWidget(title)
        layout.addSpacing(10)
        layout.addWidget(self.status_frame)
        layout.addWidget(self.warning_frame)
        layout.addStretch(1)

        scroll.setWidget(content)
        main_layout.addWidget(scroll, 1)

        # 按钮区域
        # 按钮状态机：
        #   - 检测中 / 未安装：仅显示「退出」
        #   - 已安装：显示「取消」+「确认卸载」（dangerButton 样式）
        btn_layout = QHBoxLayout()
        btn_layout.setContentsMargins(40, 10, 40, 0)
        btn_layout.addStretch(1)

        self.cancel_btn = QPushButton("取消")
        self.cancel_btn.setFixedSize(100, 36)
        self.cancel_btn.clicked.connect(self.cancel_clicked.emit)

        self.confirm_btn = QPushButton("确认卸载")
        self.confirm_btn.setFixedSize(120, 36)
        self.confirm_btn.setObjectName("dangerButton")
        self.confirm_btn.clicked.connect(self.confirm_clicked.emit)
        self.confirm_btn.hide()

        btn_layout.addWidget(self.cancel_btn)
        btn_layout.addWidget(self.confirm_btn)
        btn_layout.addStretch(1)

        main_layout.addLayout(btn_layout)

    def _check_installation(self):
        """检测用户主目录下是否存在 OpenClaw 程序与配置目录，并据此刷新 UI 状态。"""
        home = os.path.expanduser("~")
        has_src = os.path.exists(os.path.join(home, "openclaw-cn"))
        has_cfg = os.path.exists(os.path.join(home, ".openclaw"))

        if has_src or has_cfg:
            self.installed = True
            self.status_icon.setText("🔴")
            self.status_title.setText("检测到 OpenClaw 已安装")
            self.status_title.setStyleSheet("color: #c62828;")

            details = []
            if has_src:
                details.append("程序文件: ~/openclaw-cn")
            if has_cfg:
                details.append("配置文件: ~/.openclaw")
            self.status_detail.setText("\n".join(details))

            self.warning_frame.show()
            self.confirm_btn.show()
            self.cancel_btn.setText("取消")
        else:
            self.installed = False
            self.status_icon.setText("✅")
            self.status_title.setText("未检测到 OpenClaw")
            self.status_title.setStyleSheet("color: #2e7d32; background: transparent; border: none;")
            self.status_detail.setText("您的系统中没有 OpenClaw 安装记录，无需卸载。")
            self.cancel_btn.setText("退出")
            self.warning_frame.hide()
            self.confirm_btn.hide()
