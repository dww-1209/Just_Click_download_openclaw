"""US-05 配置页面 - 仅执行配置"""

import sys

from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QLabel,
    QPushButton,
    QHBoxLayout,
    QProgressBar,
    QFrame,
    QApplication,
    QTextEdit,
)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont

from models.config import ConfigStatus, ConfigProgress, ConfigResult


class ConfigStepWidget(QFrame):
    """配置步骤显示组件"""

    def __init__(self, step_name: str, parent=None):
        super().__init__(parent)
        self.step_name = step_name
        self._setup_ui()

    def _setup_ui(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 5, 10, 5)

        self.icon_label = QLabel("○")
        self.icon_label.setStyleSheet("font-size: 16px;")

        self.name_label = QLabel(self.step_name)
        self.name_label.setMinimumWidth(200)

        layout.addWidget(self.icon_label)
        layout.addWidget(self.name_label)
        layout.addStretch(1)

    def set_pending(self):
        self.icon_label.setText("○")
        self.icon_label.setStyleSheet("font-size: 16px; color: #999;")

    def set_running(self):
        self.icon_label.setText("...")
        self.icon_label.setStyleSheet("font-size: 16px; color: orange;")

    def set_completed(self):
        self.icon_label.setText("✓")
        self.icon_label.setStyleSheet("font-size: 16px; color: green;")

    def set_failed(self):
        self.icon_label.setText("✗")
        self.icon_label.setStyleSheet("font-size: 16px; color: red;")


class US05ConfigPage(QWidget):
    """US-05 配置页面 - 仅执行配置"""

    retry_clicked = Signal()  # 重试配置
    next_clicked = Signal()   # 配置完成，进入下一步
    back_clicked = Signal()   # 返回上一页
    manual_config_clicked = Signal()  # 手动配置

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
        layout.setSpacing(15)
        layout.setContentsMargins(40, 20, 40, 20)

        # 标题
        title = QLabel("正在配置 OpenClaw")
        title.setAlignment(Qt.AlignCenter)
        title_font = QFont()
        title_font.setPointSize(20)
        title_font.setBold(True)
        title.setFont(title_font)

        # 状态说明
        self.status_label = QLabel("正在为您自动配置 OpenClaw，请稍候...")
        self.status_label.setAlignment(Qt.AlignCenter)
        self.status_label.setWordWrap(True)

        # 步骤显示区域
        steps_frame = QFrame()
        steps_frame.setStyleSheet(
            "background-color: #f9f9f9; border-radius: 8px; padding: 10px;"
        )
        steps_layout = QVBoxLayout(steps_frame)
        steps_layout.setSpacing(10)

        self.step_install = ConfigStepWidget("安装完成")
        self.step_config = ConfigStepWidget("初始化配置")

        steps_layout.addWidget(self.step_install)
        steps_layout.addWidget(self.step_config)

        # 进度条
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setMinimumHeight(25)

        # 当前任务
        self.task_label = QLabel("")
        self.task_label.setAlignment(Qt.AlignCenter)
        self.task_label.setStyleSheet("color: #666;")

        # 日志显示区域（可折叠，用于排查问题）
        self.log_frame = QFrame()
        self.log_frame.setStyleSheet(
            "background-color: #1e1e1e; border-radius: 8px; padding: 10px;"
        )
        self.log_frame.hide()  # 默认隐藏

        log_layout = QVBoxLayout(self.log_frame)
        log_header = QLabel("详细日志（供技术人员排查使用）")
        log_header.setStyleSheet("color: #ccc; font-size: 11px;")
        log_layout.addWidget(log_header)

        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setStyleSheet(
            "background-color: #1e1e1e; color: #d4d4d4; "
            "font-family: Consolas, Monaco, monospace; font-size: 11px;"
        )
        self.log_text.setMaximumHeight(150)
        log_layout.addWidget(self.log_text)

        # 显示/隐藏日志按钮
        self.toggle_log_btn = QPushButton("显示详细日志")
        self.toggle_log_btn.setStyleSheet("color: #666; font-size: 11px;")
        self.toggle_log_btn.clicked.connect(self._toggle_log)

        # 成功提示
        self.success_frame = QFrame()
        self.success_frame.setStyleSheet(
            "background-color: #e8f4e8; border-radius: 8px; padding: 15px;"
        )
        self.success_frame.hide()

        success_layout = QVBoxLayout(self.success_frame)
        success_title = QLabel("✓ 配置完成")
        success_title.setStyleSheet("color: green; font-weight: bold; font-size: 14px;")
        success_desc = QLabel('配置已成功完成，点击"下一步"启动服务')
        success_desc.setStyleSheet("color: #666;")
        success_layout.addWidget(success_title)
        success_layout.addWidget(success_desc)

        # 错误提示区域
        self.error_frame = QFrame()
        self.error_frame.setStyleSheet(
            "background-color: #fff3cd; border-radius: 8px; padding: 15px;"
        )
        self.error_frame.hide()

        error_layout = QVBoxLayout(self.error_frame)
        self.error_title = QLabel("配置失败")
        self.error_title.setStyleSheet("color: #856404; font-weight: bold;")
        self.error_label = QLabel("")
        self.error_label.setWordWrap(True)
        self.error_label.setStyleSheet("color: #856404;")
        
        # 原始错误输出
        self.error_detail_label = QLabel("")
        self.error_detail_label.setWordWrap(True)
        self.error_detail_label.setStyleSheet(
            "color: #856404; font-family: monospace; font-size: 10px; background-color: #fff8e1; padding: 5px;"
        )
        self.error_detail_label.hide()
        
        error_layout.addWidget(self.error_title)
        error_layout.addWidget(self.error_label)
        error_layout.addWidget(self.error_detail_label)

        # 按钮区域
        button_layout = QHBoxLayout()
        button_layout.addStretch(1)

        self.back_button = QPushButton("返回")
        self.back_button.setFixedSize(100, 36)
        self.back_button.clicked.connect(self.back_clicked.emit)

        self.manual_config_button = QPushButton("手动配置")
        self.manual_config_button.setFixedSize(100, 36)
        self.manual_config_button.clicked.connect(self.manual_config_clicked.emit)
        self.manual_config_button.hide()

        self.retry_button = QPushButton("重试")
        self.retry_button.setFixedSize(100, 36)
        self.retry_button.clicked.connect(self.retry_clicked.emit)
        self.retry_button.hide()

        self.next_button = QPushButton("下一步")
        self.next_button.setFixedSize(100, 36)
        self.next_button.setStyleSheet(
            "background-color: #4CAF50; color: white; font-weight: bold;"
        )
        self.next_button.clicked.connect(self.next_clicked.emit)
        self.next_button.hide()

        button_layout.addWidget(self.back_button)
        button_layout.addWidget(self.manual_config_button)
        button_layout.addWidget(self.retry_button)
        button_layout.addWidget(self.next_button)

        # 添加所有组件到内容区域
        layout.addWidget(title)
        layout.addSpacing(15)
        layout.addWidget(self.status_label)
        layout.addSpacing(15)
        layout.addWidget(steps_frame)
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

        scroll_area.setWidget(content_widget)
        main_layout.addWidget(scroll_area, 1)

        # 按钮区域（固定在底部）
        button_layout.setContentsMargins(40, 10, 40, 0)
        main_layout.addLayout(button_layout)

    def _toggle_log(self):
        """切换日志显示"""
        if self.log_frame.isVisible():
            self.log_frame.hide()
            self.toggle_log_btn.setText("显示详细日志")
        else:
            self.log_frame.show()
            self.toggle_log_btn.setText("隐藏详细日志")

    def add_log_line(self, line: str):
        """添加日志行"""
        self.log_text.append(line)
        # 滚动到底部
        scrollbar = self.log_text.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    def start_configuring(self):
        """开始配置 - 重置状态"""
        self.status_label.setText("正在为您自动配置 OpenClaw，请稍候...")
        self.status_label.setStyleSheet("")

        self.step_install.set_completed()
        self.step_config.set_running()

        self.progress_bar.setValue(0)
        self.task_label.setText("准备配置...")

        self.log_text.clear()
        self.log_frame.hide()
        self.toggle_log_btn.setText("显示详细日志")

        self.success_frame.hide()
        self.error_frame.hide()
        self.error_detail_label.hide()

        self.back_button.show()
        self.manual_config_button.hide()
        self.retry_button.hide()
        self.next_button.hide()

    def update_progress(self, progress: ConfigProgress):
        """更新进度"""
        self.progress_bar.setValue(progress.progress_percent)

        if progress.message:
            self.task_label.setText(progress.message)

        # 根据阶段更新步骤状态
        if progress.stage == ConfigStatus.CONFIGURING:
            self.step_config.set_running()
        elif progress.stage == ConfigStatus.COMPLETED:
            self.step_config.set_completed()
        elif progress.stage == ConfigStatus.FAILED:
            self.step_config.set_failed()

    def config_success(self, result: ConfigResult):
        """配置成功"""
        self.status_label.setText("✓ 配置完成")
        self.status_label.setStyleSheet("color: green; font-weight: bold;")

        self.step_install.set_completed()
        self.step_config.set_completed()

        self.progress_bar.setValue(100)
        self.task_label.setText("配置完成")

        self.success_frame.show()
        self.error_frame.hide()

        # 按钮状态
        self.back_button.hide()
        self.manual_config_button.hide()
        self.retry_button.hide()
        self.next_button.show()

    def config_failed(self, result: ConfigResult):
        """配置失败"""
        self.status_label.setText("✗ 配置失败")
        self.status_label.setStyleSheet("color: red; font-weight: bold;")

        self.step_install.set_completed()
        self.step_config.set_failed()

        # 显示友好的错误信息
        error_text = result.error_message or "配置过程中发生错误"
        self.error_label.setText(error_text)
        
        # 显示详细日志
        if result.log_lines:
            detail = "\n".join(result.log_lines[-20:])  # 显示最后20行
            self.error_detail_label.setText(detail)
            self.error_detail_label.show()
        
        self.error_frame.show()
        self.success_frame.hide()

        # 按钮状态
        self.back_button.show()
        self.manual_config_button.show()
        self.retry_button.show()
        self.next_button.hide()

    def reset(self):
        """重置页面"""
        self.step_install.set_pending()
        self.step_config.set_pending()

        self.progress_bar.setValue(0)
        self.task_label.setText("")

        self.log_text.clear()
        self.log_frame.hide()
        self.toggle_log_btn.setText("显示详细日志")

        self.success_frame.hide()
        self.error_frame.hide()
        self.error_detail_label.hide()

        self.back_button.show()
        self.manual_config_button.hide()
        self.retry_button.hide()
        self.next_button.hide()
