"""US-06 startup page - start gateway and open WebUI"""

import sys

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QPushButton, QHBoxLayout,
    QProgressBar, QFrame, QLineEdit, QApplication, QTextEdit,
)
from PySide6.QtCore import Qt, Signal, QTimer
from PySide6.QtGui import QFont

from models.config import ConfigStatus, ConfigProgress, ConfigResult


class StartupStepWidget(QFrame):
    def __init__(self, step_name, parent=None):
        super().__init__(parent)
        self.step_name = step_name
        self._setup_ui()

    def _setup_ui(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        self.icon_label = QLabel("○")
        self.icon_label.setStyleSheet("font-size: 18px; color: #bbb; min-width: 24px;")
        self.icon_label.setAlignment(Qt.AlignCenter)
        self.name_label = QLabel(self.step_name)
        self.name_label.setStyleSheet("font-size: 13px; color: #333;")
        self.name_label.setMinimumWidth(200)
        layout.addWidget(self.icon_label)
        layout.addWidget(self.name_label)
        layout.addStretch(1)

    def set_pending(self):
        self.icon_label.setText("○")
        self.icon_label.setStyleSheet("font-size: 18px; color: #bbb; min-width: 24px;")

    def set_running(self):
        self.icon_label.setText("●")
        self.icon_label.setStyleSheet("font-size: 18px; color: #f39c12; min-width: 24px;")

    def set_completed(self):
        self.icon_label.setText("✓")
        self.icon_label.setStyleSheet("font-size: 18px; color: #27ae60; font-weight: bold; min-width: 24px;")

    def set_failed(self):
        self.icon_label.setText("✗")
        self.icon_label.setStyleSheet("font-size: 18px; color: #e74c3c; font-weight: bold; min-width: 24px;")


class US06StartupPage(QWidget):
    retry_clicked = Signal()
    finish_clicked = Signal()
    back_clicked = Signal()
    open_webchat_clicked = Signal()  # New: open WebChat button clicked

    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_ui()

    def _setup_ui(self):
        from PySide6.QtWidgets import QScrollArea

        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(10)
        main_layout.setContentsMargins(24, 24, 24, 24)

        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setFrameShape(QScrollArea.NoFrame)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        content_widget = QWidget()
        layout = QVBoxLayout(content_widget)
        layout.setSpacing(15)
        layout.setContentsMargins(40, 20, 40, 20)

        title = QLabel("正在启动 OpenClaw")
        title.setAlignment(Qt.AlignCenter)
        title_font = QFont()
        title_font.setPointSize(20)
        title_font.setBold(True)
        title.setFont(title_font)

        self.status_label = QLabel("正在启动网关服务...")
        self.status_label.setAlignment(Qt.AlignCenter)
        self.status_label.setWordWrap(True)

        self.steps_frame = QFrame()
        self.steps_frame.setStyleSheet("background-color: #f9f9f9; border-radius: 8px; padding: 10px;")
        steps_layout = QVBoxLayout(self.steps_frame)
        steps_layout.setSpacing(10)

        self.step_gateway = StartupStepWidget("启动网关")
        self.step_health = StartupStepWidget("服务检查")

        steps_layout.addWidget(self.step_gateway)
        steps_layout.addWidget(self.step_health)

        # Windows 防火墙提示
        self.firewall_hint = QLabel(
            "⚠️ Windows 可能会弹出防火墙授权窗口，请点击\"允许访问\"，否则 WebChat 无法正常打开"
        )
        self.firewall_hint.setWordWrap(True)
        self.firewall_hint.setAlignment(Qt.AlignCenter)
        self.firewall_hint.setStyleSheet(
            "background-color: #fff3e0; color: #bf360c; border: 1px solid #ffb74d; "
            "border-radius: 6px; padding: 10px; font-size: 13px; font-weight: bold;"
        )
        if sys.platform != "win32":
            self.firewall_hint.hide()

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setMinimumHeight(25)

        self.task_label = QLabel("")
        self.task_label.setAlignment(Qt.AlignCenter)
        self.task_label.setStyleSheet("color: #666;")

        self.log_frame = QFrame()
        self.log_frame.setStyleSheet("background-color: #1e1e1e; border-radius: 8px; padding: 10px;")
        self.log_frame.hide()

        log_layout = QVBoxLayout(self.log_frame)
        log_header = QLabel("详细日志")
        log_header.setStyleSheet("color: #ccc; font-size: 11px;")
        log_layout.addWidget(log_header)

        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setObjectName("logArea")
        self.log_text.setMaximumHeight(150)
        log_layout.addWidget(self.log_text)

        self.toggle_log_btn = QPushButton("显示详细日志 ▼")
        self.toggle_log_btn.setStyleSheet(
            "QPushButton { color: #888; font-size: 11px; border: none; background: transparent; "
            "text-decoration: underline; padding: 4px; }"
            "QPushButton:hover { color: #555; }"
        )
        self.toggle_log_btn.setCursor(Qt.PointingHandCursor)
        self.toggle_log_btn.clicked.connect(self._toggle_log)

        self.success_frame = QFrame()
        self.success_frame.setStyleSheet(
            "QFrame { background-color: #e8f5e9; border: 1px solid #81c784; border-radius: 12px; }"
        )
        self.success_frame.hide()

        success_layout = QVBoxLayout(self.success_frame)
        success_layout.setSpacing(14)
        success_layout.setContentsMargins(24, 24, 24, 24)

        success_title = QLabel("✓ Openclaw 已就绪")
        success_title.setAlignment(Qt.AlignCenter)
        success_title_font = QFont()
        success_title_font.setBold(True)
        success_title_font.setPointSize(16)
        success_title.setFont(success_title_font)
        success_title.setStyleSheet("color: #2e7d32; background: transparent; border: none;")

        url_desc = QLabel("WebChat 访问地址")
        url_desc.setAlignment(Qt.AlignCenter)
        url_desc.setStyleSheet("color: #666; font-size: 11px; background: transparent; border: none;")

        self.url_input = QLineEdit()
        self.url_input.setReadOnly(True)

        self.copy_button = QPushButton("复制")
        self.copy_button.setFixedWidth(72)
        self.copy_button.clicked.connect(self._copy_url)

        url_input_layout = QHBoxLayout()
        url_input_layout.setSpacing(8)
        url_input_layout.addWidget(self.url_input)
        url_input_layout.addWidget(self.copy_button)

        self.browser_hint = QLabel("点击下方按钮即可打开 WebChat")
        self.browser_hint.setAlignment(Qt.AlignCenter)
        self.browser_hint.setStyleSheet(
            "color: #888; font-size: 11px; background: transparent; border: none;"
        )
        self.browser_hint.setWordWrap(True)

        self.fallback_hint = QLabel("若按钮无法打开，可复制上方地址到浏览器中访问")
        self.fallback_hint.setAlignment(Qt.AlignCenter)
        self.fallback_hint.setStyleSheet(
            "color: #aaa; font-size: 10px; background: transparent; border: none;"
        )
        self.fallback_hint.setWordWrap(True)

        # 提示：如何隐藏工具调用过程，只看最终回复
        self.thinking_hint = QLabel(
            "💡 提示：打开 WebChat 后，若界面显示了太多工具调用过程，"
            "可点击聊天界面右上角的 🧠（thinking）图标关闭，即可只查看 OpenClaw 的最终回复"
        )
        self.thinking_hint.setAlignment(Qt.AlignCenter)
        self.thinking_hint.setWordWrap(True)
        self.thinking_hint.setStyleSheet(
            "background-color: #e3f2fd; color: #1565c0; border: 1px solid #64b5f6; "
            "border-radius: 6px; padding: 10px; font-size: 12px;"
        )

        # 关键警告：请勿关闭安装器
        self.keep_alive_hint = QLabel(
            "⚠️ 请勿关闭本窗口！程序在运行，OpenClaw 才能正常使用"
        )
        self.keep_alive_hint.setAlignment(Qt.AlignCenter)
        self.keep_alive_hint.setWordWrap(True)
        self.keep_alive_hint.setStyleSheet(
            "background-color: #ffebee; color: #c62828; border: 1px solid #ef5350; "
            "border-radius: 6px; padding: 10px; font-size: 12px; font-weight: bold;"
        )

        # 倒计时提示
        self.countdown_label = QLabel("服务已就绪，正在等待连接稳定... 3 秒")
        self.countdown_label.setAlignment(Qt.AlignCenter)
        self.countdown_label.setStyleSheet(
            "color: #666; font-size: 12px; background: transparent; border: none;"
        )
        self.countdown_label.hide()

        # 打开 WebChat 按钮
        self.open_webchat_btn = QPushButton("打开 WebChat")
        self.open_webchat_btn.setCursor(Qt.PointingHandCursor)
        self.open_webchat_btn.setObjectName("primaryButton")
        self.open_webchat_btn.setFixedHeight(46)
        self.open_webchat_btn.setEnabled(False)
        self.open_webchat_btn.clicked.connect(self.open_webchat_clicked.emit)

        success_layout.addWidget(success_title)
        success_layout.addWidget(url_desc)
        success_layout.addLayout(url_input_layout)
        success_layout.addWidget(self.open_webchat_btn)
        success_layout.addWidget(self.fallback_hint)
        success_layout.addWidget(self.countdown_label)
        success_layout.addWidget(self.browser_hint)
        success_layout.addWidget(self.thinking_hint)
        success_layout.addWidget(self.keep_alive_hint)

        self.error_frame = QFrame()
        self.error_frame.setStyleSheet("background-color: #fff3cd; border-radius: 8px; padding: 15px;")
        self.error_frame.hide()

        error_layout = QVBoxLayout(self.error_frame)
        self.error_title = QLabel("启动失败")
        self.error_title.setStyleSheet("color: #856404; font-weight: bold;")
        self.error_label = QLabel("")
        self.error_label.setWordWrap(True)
        self.error_label.setStyleSheet("color: #856404;")
        
        self.error_detail_label = QLabel("")
        self.error_detail_label.setWordWrap(True)
        self.error_detail_label.setStyleSheet(
            "color: #856404; font-family: monospace; font-size: 10px; background-color: #fff8e1; padding: 5px;"
        )
        self.error_detail_label.hide()
        
        error_layout.addWidget(self.error_title)
        error_layout.addWidget(self.error_label)
        error_layout.addWidget(self.error_detail_label)

        button_layout = QHBoxLayout()
        button_layout.addStretch(1)

        self.back_button = QPushButton("返回")
        self.back_button.setFixedSize(100, 36)
        self.back_button.clicked.connect(self.back_clicked.emit)

        self.retry_button = QPushButton("重试")
        self.retry_button.setFixedSize(100, 36)
        self.retry_button.clicked.connect(self.retry_clicked.emit)
        self.retry_button.hide()

        self.finish_button = QPushButton("完成")
        self.finish_button.setFixedSize(100, 36)
        self.finish_button.setObjectName("primaryButton")
        self.finish_button.clicked.connect(self.finish_clicked.emit)
        self.finish_button.hide()

        button_layout.addWidget(self.back_button)
        button_layout.addWidget(self.retry_button)
        button_layout.addWidget(self.finish_button)

        layout.addWidget(title)
        layout.addSpacing(15)
        layout.addWidget(self.status_label)
        layout.addSpacing(15)
        layout.addWidget(self.steps_frame)
        layout.addSpacing(10)
        layout.addWidget(self.firewall_hint)
        layout.addSpacing(15)
        layout.addWidget(self.progress_bar)
        layout.addSpacing(10)
        layout.addWidget(self.task_label)
        layout.addSpacing(10)
        layout.addWidget(self.success_frame)
        layout.addWidget(self.error_frame)
        layout.addSpacing(10)
        layout.addWidget(self.toggle_log_btn)
        layout.addWidget(self.log_frame)
        layout.addStretch(1)

        self.scroll_area.setWidget(content_widget)
        main_layout.addWidget(self.scroll_area, 1)

        button_layout.setContentsMargins(40, 10, 40, 0)
        main_layout.addLayout(button_layout)

    def _toggle_log(self):
        if self.log_frame.isVisible():
            self.log_frame.hide()
            self.toggle_log_btn.setText("显示详细日志 ▼")
        else:
            self.log_frame.show()
            self.toggle_log_btn.setText("隐藏详细日志 ▲")

    def _copy_url(self):
        url = self.url_input.text()
        if url:
            clipboard = QApplication.clipboard()
            clipboard.setText(url)
            self.copy_button.setText("已复制!")

    def add_log_line(self, line):
        self.log_text.append(line)
        scrollbar = self.log_text.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    def start_startup(self):
        self.status_label.setText("正在启动网关服务...")
        self.status_label.setStyleSheet("")

        self.steps_frame.show()
        self.progress_bar.show()
        if sys.platform == "win32":
            self.firewall_hint.show()
        self.task_label.show()

        self.step_gateway.set_running()
        self.step_health.set_pending()

        self.progress_bar.setValue(0)
        self.task_label.setText("准备启动网关...")

        self.log_text.clear()
        self.log_frame.hide()
        self.toggle_log_btn.setText("显示详细日志 ▼")

        self.success_frame.hide()
        self.error_frame.hide()
        self.error_detail_label.hide()

        self.back_button.show()
        self.retry_button.hide()
        self.finish_button.hide()

    def update_progress(self, progress):
        self.progress_bar.setValue(progress.progress_percent)

        if progress.message:
            self.task_label.setText(progress.message)

        if progress.stage == ConfigStatus.GATEWAY_STARTING:
            self.step_gateway.set_running()
        elif progress.stage == ConfigStatus.HEALTH_CHECKING:
            self.step_gateway.set_completed()
            self.step_health.set_running()
        elif progress.stage == ConfigStatus.COMPLETED:
            self.step_gateway.set_completed()
            self.step_health.set_completed()
        elif progress.stage == ConfigStatus.FAILED:
            if not hasattr(self, '_failed_step_set'):
                self.step_gateway.set_failed()

    def startup_success(self, result):
        self.status_label.setText("网关服务已启动")
        self.status_label.setStyleSheet("color: green; font-weight: bold;")

        self.step_gateway.set_completed()
        self.step_health.set_completed()

        self.progress_bar.setValue(100)
        self.task_label.setText("服务已就绪")

        # 隐藏已完成的上部区域，把成功信息推到视野中
        self.steps_frame.hide()
        self.progress_bar.hide()
        self.firewall_hint.hide()
        self.task_label.hide()

        if result.webchat_url:
            self.url_input.setText(result.webchat_url)
            self.success_frame.show()
            self.browser_hint.setText("服务已就绪，点击下方按钮打开 WebChat")

        self.error_frame.hide()

        self.back_button.hide()
        self.retry_button.hide()
        self.finish_button.show()

        # 自动滚动到底部，确保按钮可见
        QTimer.singleShot(100, lambda: self.scroll_area.verticalScrollBar().setValue(
            self.scroll_area.verticalScrollBar().maximum()
        ))

        # 启动3秒倒计时，等待连接稳定
        self._start_countdown()

    def startup_failed(self, result):
        self.status_label.setText("启动失败")
        self.status_label.setStyleSheet("color: red; font-weight: bold;")

        error_text = result.error_message or "服务启动失败"
        self.error_label.setText(error_text)
        
        if result.log_lines:
            detail = "\n".join(result.log_lines[-20:])
            self.error_detail_label.setText(detail)
            self.error_detail_label.show()
        
        self.error_frame.show()
        self.success_frame.hide()

        self.back_button.show()
        self.retry_button.show()
        self.finish_button.hide()

    def _start_countdown(self):
        """启动8秒倒计时，等待网关连接稳定"""
        
        self._countdown_value = 8
        self.open_webchat_btn.setEnabled(False)
        pass
        self.countdown_label.setText(f"服务已就绪，正在等待连接稳定... {self._countdown_value} 秒")
        self.countdown_label.show()

        self._countdown_timer = QTimer(self)
        self._countdown_timer.timeout.connect(self._update_countdown)
        self._countdown_timer.start(1000)  # 每秒更新一次

    def _update_countdown(self):
        """更新倒计时"""
        self._countdown_value -= 1
        if self._countdown_value > 0:
            self.countdown_label.setText(
                f"服务已就绪，正在等待连接稳定... {self._countdown_value} 秒"
            )
        else:
            self._countdown_timer.stop()
            self.countdown_label.hide()
            self.open_webchat_btn.setEnabled(True)

    def reset(self):
        self.step_gateway.set_pending()
        self.step_health.set_pending()

        self.progress_bar.setValue(0)
        self.task_label.setText("")

        self.log_text.clear()
        self.log_frame.hide()
        self.toggle_log_btn.setText("显示详细日志 ▼")

        self.success_frame.hide()
        self.error_frame.hide()
        self.error_detail_label.hide()

        # 重置倒计时状态
        if hasattr(self, '_countdown_timer') and self._countdown_timer:
            self._countdown_timer.stop()
        self.countdown_label.hide()
        self.open_webchat_btn.setEnabled(False)

        self.back_button.show()
        self.retry_button.hide()
        self.finish_button.hide()
