"""卸载工具 —— 完成页面。

职责：卸载流程的最后一页，展示卸载完成的结果状态。
    支持两种展示模式：
    - 完全成功：绿色状态卡片 + 标准已删除清单
    - 部分完成：黄色警告卡片 + 已删除/失败混合清单，提示用户手动清理
"""

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QPushButton, QHBoxLayout,
    QFrame,
)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont


class UninstallDonePage(QWidget):
    """卸载完成页面 —— 展示卸载结果并提供退出或重新检测的入口。

    职责：作为卸载流程的最后一页，根据后台线程的执行结果展示两种状态：
    - 完全成功：绿色状态卡片 + 标准已删除清单
    - 部分完成：黄色警告卡片 + 已删除/失败混合清单，提示用户手动清理
    同时提供「退出」和「重新检测环境」两个按钮，方便用户验证残留。
    """

    recheck_clicked = Signal()  # 用户点击「重新检测环境」，触发回到卸载欢迎页重新扫描
    exit_clicked = Signal()     # 用户点击「退出」，触发关闭卸载工具

    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_ui()

    def _setup_ui(self):
        # 主布局：垂直排列标题、状态卡片、清单区域和底部按钮。
        # 状态卡片与清单区域使用不同背景色形成视觉层次。
        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(10)
        main_layout.setContentsMargins(24, 24, 24, 24)

        # 标题
        title = QLabel("OpenClaw 卸载工具")
        title.setAlignment(Qt.AlignCenter)
        tf = QFont()
        tf.setPointSize(20)
        tf.setBold(True)
        title.setFont(tf)

        # 状态区域：动态切换绿色（成功）或黄色（部分失败）背景
        # 使用圆角卡片包裹，突出最终结论，降低用户阅读成本。
        self.status_frame = QFrame()
        self.status_frame.setStyleSheet(
            "QFrame { background-color: #e8f5e9; border-radius: 8px; }"
            "QFrame QLabel { background: transparent; border: none; }"
        )
        sf_layout = QVBoxLayout(self.status_frame)
        sf_layout.setContentsMargins(20, 16, 20, 16)
        sf_layout.setSpacing(8)

        self.status_icon = QLabel("✅")
        self.status_icon.setAlignment(Qt.AlignCenter)
        self.status_icon.setStyleSheet("font-size: 40px; background: transparent; border: none;")

        self.status_title = QLabel("卸载完成")
        self.status_title.setAlignment(Qt.AlignCenter)
        stf = QFont()
        stf.setPointSize(16)
        stf.setBold(True)
        self.status_title.setFont(stf)
        self.status_title.setStyleSheet("color: #2e7d32; background: transparent; border: none;")

        self.status_desc = QLabel("您的系统已恢复到安装前状态。")
        self.status_desc.setAlignment(Qt.AlignCenter)
        self.status_desc.setStyleSheet("color: #555; font-size: 12px; background: transparent; border: none;")

        sf_layout.addWidget(self.status_icon)
        sf_layout.addWidget(self.status_title)
        sf_layout.addWidget(self.status_desc)

        # 清单区域：使用浅灰背景卡片，逐项列出已删除/已停止/删除失败的项目。
        # 设计意图：让用户对卸载结果有透明、可核对的清单，增强信任感。
        self.checklist_frame = QFrame()
        self.checklist_frame.setStyleSheet(
            "QFrame { background-color: #f8f9fa; border-radius: 8px; }"
            "QFrame QLabel { background: transparent; border: none; }"
        )
        cl_layout = QVBoxLayout(self.checklist_frame)
        cl_layout.setContentsMargins(16, 12, 16, 12)
        cl_layout.setSpacing(6)

        cl_title = QLabel("已删除项目")
        cl_title.setStyleSheet("font-weight: bold; font-size: 13px; color: #333; background: transparent; border: none;")

        self.checklist_label = QLabel(
            "✓ OpenClaw 程序文件  — 已删除\n"
            "✓ 配置文件（含 API Key）— 已删除\n"
            "✓ 命令行工具  — 已删除\n"
            "✓ Gateway 服务  — 已停止"
        )
        self.checklist_label.setStyleSheet(
            "color: #424242; font-size: 12px; line-height: 1.6; background: transparent; border: none;"
        )

        cl_layout.addWidget(cl_title)
        cl_layout.addWidget(self.checklist_label)

        main_layout.addWidget(title)
        main_layout.addSpacing(20)
        main_layout.addWidget(self.status_frame)
        main_layout.addSpacing(15)
        main_layout.addWidget(self.checklist_frame)
        main_layout.addStretch(1)

        # 按钮区域：「退出」放在左侧，「重新检测环境」放在右侧并使用主按钮样式，
        # 符合用户从左到右的阅读习惯，同时突出「重新检测」这一正向后续操作。
        btn_layout = QHBoxLayout()
        btn_layout.setContentsMargins(40, 10, 40, 0)
        btn_layout.addStretch(1)

        self.exit_btn = QPushButton("退出")
        self.exit_btn.setFixedSize(100, 36)
        self.exit_btn.clicked.connect(self.exit_clicked.emit)

        self.recheck_btn = QPushButton("重新检测环境")
        self.recheck_btn.setFixedSize(140, 36)
        self.recheck_btn.setObjectName("primaryButton")
        self.recheck_btn.clicked.connect(self.recheck_clicked.emit)

        btn_layout.addWidget(self.exit_btn)
        btn_layout.addWidget(self.recheck_btn)
        btn_layout.addStretch(1)

        main_layout.addLayout(btn_layout)

    def set_success(self):
        """设置为完全成功状态：绿色卡片 + 标准已删除清单。"""
        self.status_frame.setStyleSheet(
            "QFrame { background-color: #e8f5e9; border-radius: 8px; }"
            "QFrame QLabel { background: transparent; border: none; }"
        )
        self.status_icon.setText("✅")
        self.status_title.setText("卸载完成")
        self.status_title.setStyleSheet("color: #2e7d32; background: transparent; border: none;")
        self.status_desc.setText("您的系统已恢复到安装前状态。")
        self.checklist_label.setText(
            "✓ OpenClaw 程序文件  — 已删除\n"
            "✓ 配置文件（含 API Key）— 已删除\n"
            "✓ 命令行工具  — 已删除\n"
            "✓ Gateway 服务  — 已停止"
        )

    def set_partial(self, failed_items: list):
        """设置为部分完成状态：黄色卡片 + 已删除/失败混合清单。

        Args:
            failed_items: 未能成功删除的项目名称列表，将追加到清单末尾并以红色标注。
        """
        self.status_frame.setStyleSheet(
            "QFrame { background-color: #fff8e1; border-radius: 8px; }"
            "QFrame QLabel { background: transparent; border: none; }"
        )
        self.status_icon.setText("⚠️")
        self.status_title.setText("卸载部分完成")
        self.status_title.setStyleSheet("color: #e65100; background: transparent; border: none;")
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
