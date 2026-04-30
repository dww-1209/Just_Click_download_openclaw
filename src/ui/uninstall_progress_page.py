"""卸载工具 —— 进度/日志页面。

职责：展示卸载流程的实时进度、状态文本和命令行日志输出。
    作为卸载流程的第二页，在用户点击「确认卸载」后进入，
    通过后台线程执行停止 Gateway、删除目录、清理 npm wrappers 等操作，
    并将结果实时反映到进度条和日志区域。
"""

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QPushButton, QHBoxLayout,
    QProgressBar, QTextEdit, QFrame,
)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont


class UninstallProgressPage(QWidget):
    """卸载进度页面 —— 展示卸载过程的实时进度与日志。

    职责：作为卸载流程的第二页，在用户点击「确认卸载」后进入。
    通过后台线程执行停止 Gateway、删除目录、清理 npm wrappers 等操作，
    并将结果实时反映到进度条、状态文本和日志区域。提供「取消」按钮，
    但卸载一旦开始即不可真正中断（子进程已提交），按钮仅作状态提示。
    """

    cancel_clicked = Signal()  # 用户点击「取消」，但卸载开始后该按钮会被禁用，仅作状态提示

    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_ui()

    def _setup_ui(self):
        # 主布局：垂直排列标题、进度条、状态文本、日志区域和底部按钮。
        # 日志区域使用深色背景卡片，与安装/配置页保持一致的视觉风格。
        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(10)
        main_layout.setContentsMargins(24, 24, 24, 24)

        # 标题
        title = QLabel("正在卸载 OpenClaw")
        title.setAlignment(Qt.AlignCenter)
        tf = QFont()
        tf.setPointSize(18)
        tf.setBold(True)
        title.setFont(tf)

        # 进度条：范围 0-100，使用 dangerProgressBar 样式（红色主题），
        # 与安装页的 green 主题形成视觉反差，暗示操作的破坏性。
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setMinimumHeight(20)
        self.progress_bar.setObjectName("dangerProgressBar")

        self.progress_label = QLabel("准备卸载...")
        self.progress_label.setAlignment(Qt.AlignCenter)
        self.progress_label.setStyleSheet("color: #666; font-size: 12px; background: transparent; border: none;")

        # 日志区域：只读文本框，深色背景，最小高度 200px，确保足够空间展示删除命令的输出。
        log_frame = QFrame()
        log_frame.setStyleSheet(
            "QFrame { background-color: #1e1e1e; border-radius: 6px; }"
        )
        log_layout = QVBoxLayout(log_frame)
        log_layout.setContentsMargins(10, 10, 10, 10)

        self.log_edit = QTextEdit()
        self.log_edit.setReadOnly(True)
        self.log_edit.setObjectName("logArea")
        self.log_edit.setMinimumHeight(200)

        log_layout.addWidget(self.log_edit)

        main_layout.addWidget(title)
        main_layout.addSpacing(10)
        main_layout.addWidget(self.progress_bar)
        main_layout.addWidget(self.progress_label)
        main_layout.addSpacing(10)
        main_layout.addWidget(log_frame, 1)

        # 按钮区域：仅提供「取消」按钮，卸载开始后禁用并改为「卸载中...」文本，
        # 避免用户误以为可以中断已提交的删除操作。
        btn_layout = QHBoxLayout()
        btn_layout.setContentsMargins(40, 10, 40, 0)
        btn_layout.addStretch(1)

        self.cancel_btn = QPushButton("取消")
        self.cancel_btn.setFixedSize(100, 36)
        self.cancel_btn.clicked.connect(self.cancel_clicked.emit)

        btn_layout.addWidget(self.cancel_btn)
        btn_layout.addStretch(1)

        main_layout.addLayout(btn_layout)

    def reset(self):
        """重置页面状态，恢复到初始值。"""
        self.progress_bar.setValue(0)
        self.progress_label.setText("准备卸载...")
        self.log_edit.clear()
        self.cancel_btn.setEnabled(True)
        self.cancel_btn.setText("取消")

    def set_progress(self, percent: int, message: str):
        """更新进度条值和状态文本。"""
        self.progress_bar.setValue(percent)
        self.progress_label.setText(message)

    def add_log(self, line: str):
        """追加日志行并自动滚动到底部。"""
        self.log_edit.append(line)
        scrollbar = self.log_edit.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    def set_done(self):
        """卸载完成后禁用取消按钮并更新文本，防止用户误操作。"""
        self.cancel_btn.setEnabled(False)
        self.cancel_btn.setText("卸载中...")
