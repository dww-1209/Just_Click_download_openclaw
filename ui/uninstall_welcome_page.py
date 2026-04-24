"""卸载工具 — 确认/检测页面"""

import os

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QPushButton, QHBoxLayout,
    QFrame, QScrollArea,
)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont


class UninstallWelcomePage(QWidget):
    """检测 OpenClaw 安装状态并请求用户确认卸载"""

    confirm_clicked = Signal()
    cancel_clicked = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.installed = False
        self._setup_ui()
        self._check_installation()

    def _setup_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(10)
        main_layout.setContentsMargins(20, 20, 20, 20)

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

        # 状态区域
        self.status_frame = QFrame()
        self.status_frame.setStyleSheet(
            "QFrame { background-color: #f8f9fa; border-radius: 8px; border: 1px solid #e9ecef; }"
        )
        sf_layout = QVBoxLayout(self.status_frame)
        sf_layout.setContentsMargins(20, 16, 20, 16)
        sf_layout.setSpacing(8)

        self.status_icon = QLabel("🔍")
        self.status_icon.setAlignment(Qt.AlignCenter)
        self.status_icon.setStyleSheet("font-size: 32px;")

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
        self.warning_frame = QFrame()
        self.warning_frame.setStyleSheet(
            "QFrame { background-color: #fff3f3; border-radius: 8px; "
            "border: 1px solid #ffcdd2; }"
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
        btn_layout = QHBoxLayout()
        btn_layout.setContentsMargins(40, 10, 40, 0)
        btn_layout.addStretch(1)

        self.cancel_btn = QPushButton("取消")
        self.cancel_btn.setFixedSize(100, 36)
        self.cancel_btn.setStyleSheet(
            "QPushButton { background-color: #f5f5f5; color: #333; font-weight: bold; "
            "border-radius: 6px; font-size: 13px; border: 1px solid #ddd; }"
            "QPushButton:hover { background-color: #e0e0e0; }"
        )
        self.cancel_btn.clicked.connect(self.cancel_clicked.emit)

        self.confirm_btn = QPushButton("确认卸载")
        self.confirm_btn.setFixedSize(120, 36)
        self.confirm_btn.setStyleSheet(
            "QPushButton { background-color: #dc3545; color: white; font-weight: bold; "
            "border-radius: 6px; font-size: 13px; border: none; }"
            "QPushButton:hover { background-color: #c82333; }"
            "QPushButton:pressed { background-color: #bd2130; }"
        )
        self.confirm_btn.clicked.connect(self.confirm_clicked.emit)
        self.confirm_btn.hide()

        btn_layout.addWidget(self.cancel_btn)
        btn_layout.addWidget(self.confirm_btn)
        btn_layout.addStretch(1)

        main_layout.addLayout(btn_layout)

    def _check_installation(self):
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
        else:
            self.installed = False
            self.status_icon.setText("✅")
            self.status_title.setText("未检测到 OpenClaw")
            self.status_title.setStyleSheet("color: #2e7d32;")
            self.status_detail.setText("您的系统中没有 OpenClaw 安装记录，无需卸载。")
            self.cancel_btn.setText("退出")
