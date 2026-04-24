"""卸载工具 — 完成页面"""

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QPushButton, QHBoxLayout,
    QFrame,
)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont


class UninstallDonePage(QWidget):
    """显示卸载完成结果"""

    recheck_clicked = Signal()
    exit_clicked = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_ui()

    def _setup_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(10)
        main_layout.setContentsMargins(20, 20, 20, 20)

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
            "QFrame { background-color: #e8f5e9; border-radius: 8px; "
            "border: 1px solid #a5d6a7; }"
        )
        sf_layout = QVBoxLayout(self.status_frame)
        sf_layout.setContentsMargins(20, 16, 20, 16)
        sf_layout.setSpacing(8)

        self.status_icon = QLabel("✅")
        self.status_icon.setAlignment(Qt.AlignCenter)
        self.status_icon.setStyleSheet("font-size: 40px;")

        self.status_title = QLabel("卸载完成")
        self.status_title.setAlignment(Qt.AlignCenter)
        stf = QFont()
        stf.setPointSize(16)
        stf.setBold(True)
        self.status_title.setFont(stf)
        self.status_title.setStyleSheet("color: #2e7d32;")

        self.status_desc = QLabel("您的系统已恢复到安装前状态。")
        self.status_desc.setAlignment(Qt.AlignCenter)
        self.status_desc.setStyleSheet("color: #555; font-size: 12px;")

        sf_layout.addWidget(self.status_icon)
        sf_layout.addWidget(self.status_title)
        sf_layout.addWidget(self.status_desc)

        # 清单区域
        self.checklist_frame = QFrame()
        self.checklist_frame.setStyleSheet(
            "QFrame { background-color: #f8f9fa; border-radius: 8px; "
            "border: 1px solid #e9ecef; }"
        )
        cl_layout = QVBoxLayout(self.checklist_frame)
        cl_layout.setContentsMargins(16, 12, 16, 12)
        cl_layout.setSpacing(6)

        cl_title = QLabel("已删除项目")
        cl_title.setStyleSheet("font-weight: bold; font-size: 13px; color: #333;")

        self.checklist_label = QLabel(
            "✓ OpenClaw 程序文件  — 已删除\n"
            "✓ 配置文件（含 API Key）— 已删除\n"
            "✓ 命令行工具  — 已删除\n"
            "✓ Gateway 服务  — 已停止"
        )
        self.checklist_label.setStyleSheet(
            "color: #424242; font-size: 12px; line-height: 1.6;"
        )

        cl_layout.addWidget(cl_title)
        cl_layout.addWidget(self.checklist_label)

        main_layout.addWidget(title)
        main_layout.addSpacing(20)
        main_layout.addWidget(self.status_frame)
        main_layout.addSpacing(15)
        main_layout.addWidget(self.checklist_frame)
        main_layout.addStretch(1)

        # 按钮
        btn_layout = QHBoxLayout()
        btn_layout.setContentsMargins(40, 10, 40, 0)
        btn_layout.addStretch(1)

        self.exit_btn = QPushButton("退出")
        self.exit_btn.setFixedSize(100, 36)
        self.exit_btn.setStyleSheet(
            "QPushButton { background-color: #f5f5f5; color: #333; font-weight: bold; "
            "border-radius: 6px; font-size: 13px; border: 1px solid #ddd; }"
            "QPushButton:hover { background-color: #e0e0e0; }"
        )
        self.exit_btn.clicked.connect(self.exit_clicked.emit)

        self.recheck_btn = QPushButton("重新检测环境")
        self.recheck_btn.setFixedSize(140, 36)
        self.recheck_btn.setStyleSheet(
            "QPushButton { background-color: #4CAF50; color: white; font-weight: bold; "
            "border-radius: 6px; font-size: 13px; border: none; }"
            "QPushButton:hover { background-color: #43a047; }"
        )
        self.recheck_btn.clicked.connect(self.recheck_clicked.emit)

        btn_layout.addWidget(self.exit_btn)
        btn_layout.addWidget(self.recheck_btn)
        btn_layout.addStretch(1)

        main_layout.addLayout(btn_layout)

    def set_success(self):
        self.status_frame.setStyleSheet(
            "QFrame { background-color: #e8f5e9; border-radius: 8px; "
            "border: 1px solid #a5d6a7; }"
        )
        self.status_icon.setText("✅")
        self.status_title.setText("卸载完成")
        self.status_title.setStyleSheet("color: #2e7d32;")
        self.status_desc.setText("您的系统已恢复到安装前状态。")
        self.checklist_label.setText(
            "✓ OpenClaw 程序文件  — 已删除\n"
            "✓ 配置文件（含 API Key）— 已删除\n"
            "✓ 命令行工具  — 已删除\n"
            "✓ Gateway 服务  — 已停止"
        )

    def set_partial(self, failed_items: list):
        self.status_frame.setStyleSheet(
            "QFrame { background-color: #fff8e1; border-radius: 8px; "
            "border: 1px solid #ffe082; }"
        )
        self.status_icon.setText("⚠️")
        self.status_title.setText("卸载部分完成")
        self.status_title.setStyleSheet("color: #e65100;")
        self.status_desc.setText("部分文件未能删除，您可以手动清理剩余文件。")

        lines = [
            "✓ OpenClaw 程序文件  — 已删除",
            "✓ 配置文件（含 API Key）— 已删除",
            "✓ 命令行工具  — 已删除",
            "✓ Gateway 服务  — 已停止",
        ]
        for item in failed_items:
            lines.append(f"✗ {item}  — 删除失败")
        self.checklist_label.setText("\n".join(lines))
