import sys

from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QLabel,
    QPushButton,
    QHBoxLayout,
    QProgressBar,
    QPlainTextEdit,
    QFrame,
)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont

from models.install import InstallStatus, InstallStage, InstallProgress, InstallResult


class InstallingPage(QWidget):
    """安装进度页面 - US-04"""

    retry_clicked = Signal()
    next_clicked = Signal()
    back_clicked = Signal()
    cancel_clicked = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_ui()

    def _setup_ui(self):
        from PySide6.QtWidgets import QScrollArea

        # 主布局
        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(10)
        main_layout.setContentsMargins(20, 20, 20, 20)

        # 创建滚动区域
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameShape(QScrollArea.NoFrame)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        # 内容容器
        content_widget = QWidget()
        layout = QVBoxLayout(content_widget)
        layout.setSpacing(12)
        layout.setContentsMargins(40, 20, 40, 20)

        # 标题
        title = QLabel("安装 OpenClaw")
        title.setAlignment(Qt.AlignCenter)
        title_font = QFont()
        title_font.setPointSize(18)
        title_font.setBold(True)
        title.setFont(title_font)

        # 状态标签
        self.status_label = QLabel("准备安装...")
        self.status_label.setAlignment(Qt.AlignCenter)
        status_font = QFont()
        status_font.setPointSize(11)
        self.status_label.setFont(status_font)

        # 当前任务
        self.task_label = QLabel("")
        self.task_label.setAlignment(Qt.AlignCenter)
        self.task_label.setStyleSheet("color: #666;")

        # 耗时提示
        self.time_hint_label = QLabel("预计耗时 10-20 分钟，请保持网络畅通并耐心等待")
        self.time_hint_label.setAlignment(Qt.AlignCenter)
        self.time_hint_label.setStyleSheet("color: #e67e22; font-size: 12px; padding: 6px;")
        self.time_hint_label.setWordWrap(True)

        # Windows 系统授权提示（Git 安装时可能触发 Defender / SmartScreen）
        self.security_hint = QLabel(
            "⚠️ Windows 可能会弹出安全授权窗口，请点击\"允许\"或\"是\"，否则安装无法继续"
        )
        self.security_hint.setWordWrap(True)
        self.security_hint.setAlignment(Qt.AlignCenter)
        self.security_hint.setStyleSheet(
            "background-color: #fff3e0; color: #bf360c; border: 1px solid #ffb74d; "
            "border-radius: 6px; padding: 10px; font-size: 13px; font-weight: bold;"
        )
        if sys.platform != "win32":
            self.security_hint.hide()

        # 进度条
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setFormat("%p%")
        self.progress_bar.setMinimumHeight(22)

        # 日志区域
        log_label = QLabel("安装日志:")

        self.log_text = QPlainTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setMaximumBlockCount(100)  # 限制日志行数
        self.log_text.setMinimumHeight(100)
        self.log_text.setStyleSheet("""
            QPlainTextEdit {
                background-color: #1e1e1e;
                color: #d4d4d4;
                border: 1px solid #333;
                border-radius: 6px;
                padding: 10px;
                font-family: Consolas, Monaco, monospace;
                font-size: 11px;
            }
        """)

        # 提示信息
        self.hint_label = QLabel("")
        self.hint_label.setWordWrap(True)
        self.hint_label.setStyleSheet("color: #666;")
        self.hint_label.hide()

        # 添加所有组件到布局
        layout.addWidget(title)
        layout.addSpacing(15)
        layout.addWidget(self.status_label)
        layout.addSpacing(8)
        layout.addWidget(self.task_label)
        layout.addSpacing(8)
        layout.addWidget(self.time_hint_label)
        layout.addSpacing(10)
        layout.addWidget(self.security_hint)
        layout.addSpacing(15)
        layout.addWidget(self.progress_bar)
        layout.addSpacing(15)
        layout.addWidget(log_label)
        layout.addWidget(self.log_text, 1)
        layout.addSpacing(10)
        layout.addWidget(self.hint_label)

        scroll_area.setWidget(content_widget)
        main_layout.addWidget(scroll_area, 1)

        # 按钮区域（固定在底部）
        button_layout = QHBoxLayout()
        button_layout.setContentsMargins(40, 10, 40, 0)
        button_layout.addStretch(1)

        self.back_button = QPushButton("返回")
        self.back_button.setFixedSize(100, 36)
        self.back_button.clicked.connect(self.back_clicked.emit)

        self.cancel_button = QPushButton("退出")
        self.cancel_button.setFixedSize(100, 36)
        self.cancel_button.clicked.connect(self._on_cancel_clicked)

        self.retry_button = QPushButton("重试")
        self.retry_button.setFixedSize(100, 36)
        self.retry_button.clicked.connect(self.retry_clicked.emit)
        self.retry_button.hide()

        self.next_button = QPushButton("完成")
        self.next_button.setFixedSize(100, 36)
        self.next_button.clicked.connect(self.next_clicked.emit)
        self.next_button.setEnabled(False)
        self.next_button.hide()

        button_layout.addWidget(self.back_button)
        button_layout.addWidget(self.cancel_button)
        button_layout.addWidget(self.retry_button)
        button_layout.addWidget(self.next_button)

        main_layout.addLayout(button_layout)

    def _on_cancel_clicked(self):
        """处理退出/取消点击"""
        self.cancel_clicked.emit()

    def start_installing(self):
        """开始安装 - 重置界面状态"""
        self.status_label.setText("正在安装...")
        self.status_label.setStyleSheet("")
        self.task_label.setText("准备执行安装命令...")
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.log_text.clear()
        self.hint_label.hide()

        # 按钮状态 - 安装过程中禁用所有按钮
        self.back_button.setEnabled(False)
        self.cancel_button.setText("退出")
        self.cancel_button.setEnabled(False)  # 安装中禁止退出
        self.retry_button.hide()
        self.next_button.hide()

    def update_progress(self, progress: InstallProgress):
        """更新进度"""
        self.progress_bar.setValue(progress.progress_percent)

        # 根据阶段更新状态文本
        stage_messages = {
            InstallStage.DOWNLOADING: "正在下载...",
            InstallStage.INSTALLING: "正在安装...",
            InstallStage.CONFIGURING: "正在配置...",
            InstallStage.COMPLETED: "安装完成",
        }

        stage_text = stage_messages.get(progress.stage, "处理中...")
        self.status_label.setText(stage_text)

        if progress.current_task:
            self.task_label.setText(progress.current_task)

        if progress.message:
            self._append_log(progress.message)

    def _append_log(self, message: str):
        """添加日志"""
        self.log_text.appendPlainText(message)
        # 滚动到底部
        scrollbar = self.log_text.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    def add_log_line(self, log_line: str):
        """添加日志行"""
        self._append_log(log_line)

    def install_success(self, result: InstallResult):
        """安装成功"""
        self.status_label.setText("[OK] 安装成功！")
        self.status_label.setStyleSheet("color: green;")
        self.task_label.setText("OpenClaw 已准备就绪，点击完成开始使用")
        self.progress_bar.setValue(100)

        self._append_log(f"安装成功！耗时: {result.duration_seconds:.1f}秒")

        # 按钮状态 - 安装成功，显示下一步按钮，等待用户点击
        self.back_button.setEnabled(True)
        self.cancel_button.setEnabled(True)  # 重新启用退出按钮
        self.cancel_button.hide()  # 隐藏退出按钮
        self.retry_button.hide()
        self.next_button.show()
        self.next_button.setEnabled(True)  # 启用下一步按钮

    def install_failed(self, result: InstallResult):
        """安装失败"""
        from models.helpers import UserMessageHelper
        
        self.status_label.setText("[X] 安装失败")
        self.status_label.setStyleSheet("color: red;")
        self.task_label.setText(result.message)

        # 显示友好的错误提示
        if result.error_message:
            # 根据错误内容判断错误类型
            error_lower = result.error_message.lower()
            if "网络" in error_lower or "download" in error_lower or "curl" in error_lower:
                friendly_msg = UserMessageHelper.get_friendly_error_message("download", result.error_message)
            elif "权限" in error_lower or "permission" in error_lower or "access" in error_lower:
                friendly_msg = UserMessageHelper.get_friendly_error_message("permission", result.error_message)
            elif "磁盘" in error_lower or "space" in error_lower:
                friendly_msg = UserMessageHelper.get_friendly_error_message("disk_space", result.error_message)
            else:
                friendly_msg = UserMessageHelper.get_friendly_error_message("install", result.error_message)
            
            self.hint_label.setText(friendly_msg)
            self.hint_label.setStyleSheet("color: #856404; background-color: #fff3cd; padding: 10px; border-radius: 5px;")
            self.hint_label.show()

        self._append_log(f"安装失败: {result.error_message}")

        # 按钮状态
        self.back_button.setEnabled(True)
        self.cancel_button.hide()
        self.retry_button.show()
        self.next_button.hide()

    def install_cancelled(self):
        """安装已取消"""
        self.status_label.setText("安装已取消")
        self.status_label.setStyleSheet("color: orange;")
        self.task_label.setText("用户取消了安装")
        self._append_log("安装已取消")

        # 按钮状态
        self.back_button.setEnabled(True)
        self.cancel_button.setText("退出")
        self.retry_button.show()
        self.next_button.hide()

    def reset(self):
        """重置页面状态"""
        self.status_label.setText("准备安装...")
        self.status_label.setStyleSheet("")
        self.task_label.setText("")
        self.progress_bar.setValue(0)
        self.log_text.clear()
        self.hint_label.hide()

        self.back_button.setEnabled(True)
        self.back_button.show()
        self.cancel_button.setText("退出")
        self.cancel_button.show()
        self.retry_button.hide()
        self.next_button.hide()
        self.next_button.setEnabled(False)
