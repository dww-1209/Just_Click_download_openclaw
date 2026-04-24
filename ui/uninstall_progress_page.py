"""卸载工具 — 进度/日志页面"""

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QPushButton, QHBoxLayout,
    QProgressBar, QTextEdit, QFrame,
)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont


class UninstallProgressPage(QWidget):
    """显示卸载进度和日志输出"""

    cancel_clicked = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_ui()

    def _setup_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(10)
        main_layout.setContentsMargins(20, 20, 20, 20)

        # 标题
        title = QLabel("正在卸载 OpenClaw")
        title.setAlignment(Qt.AlignCenter)
        tf = QFont()
        tf.setPointSize(18)
        tf.setBold(True)
        title.setFont(tf)

        # 进度条
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setMinimumHeight(20)
        self.progress_bar.setStyleSheet(
            "QProgressBar { border: 1px solid #ddd; border-radius: 6px; "
            "background-color: #f5f5f5; text-align: center; }"
            "QProgressBar::chunk { background-color: #dc3545; border-radius: 6px; }"
        )

        self.progress_label = QLabel("准备卸载...")
        self.progress_label.setAlignment(Qt.AlignCenter)
        self.progress_label.setStyleSheet("color: #666; font-size: 12px;")

        # 日志区域
        log_frame = QFrame()
        log_frame.setStyleSheet(
            "QFrame { background-color: #1e1e1e; border-radius: 6px; }"
        )
        log_layout = QVBoxLayout(log_frame)
        log_layout.setContentsMargins(10, 10, 10, 10)

        self.log_edit = QTextEdit()
        self.log_edit.setReadOnly(True)
        self.log_edit.setStyleSheet(
            "QTextEdit { background-color: #1e1e1e; color: #4ec9b0; "
            "border: none; font-family: 'SF Mono', 'Consolas', monospace; "
            "font-size: 12px; }"
        )
        self.log_edit.setMinimumHeight(200)

        log_layout.addWidget(self.log_edit)

        main_layout.addWidget(title)
        main_layout.addSpacing(10)
        main_layout.addWidget(self.progress_bar)
        main_layout.addWidget(self.progress_label)
        main_layout.addSpacing(10)
        main_layout.addWidget(log_frame, 1)

        # 按钮
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

        btn_layout.addWidget(self.cancel_btn)
        btn_layout.addStretch(1)

        main_layout.addLayout(btn_layout)

    def reset(self):
        self.progress_bar.setValue(0)
        self.progress_label.setText("准备卸载...")
        self.log_edit.clear()
        self.cancel_btn.setEnabled(True)
        self.cancel_btn.setText("取消")

    def set_progress(self, percent: int, message: str):
        self.progress_bar.setValue(percent)
        self.progress_label.setText(message)

    def add_log(self, line: str):
        self.log_edit.append(line)
        # 滚动到底部
        scrollbar = self.log_edit.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    def set_done(self):
        self.cancel_btn.setEnabled(False)
        self.cancel_btn.setText("卸载中...")
