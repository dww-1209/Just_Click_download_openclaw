from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QLabel,
    QPushButton,
    QHBoxLayout,
    QProgressBar,
    QTextEdit,
    QFrame,
    QLineEdit,
    QApplication,
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
        self.icon_label.setText("OK")
        self.icon_label.setStyleSheet("font-size: 16px; color: green;")

    def set_failed(self):
        self.icon_label.setText("X")
        self.icon_label.setStyleSheet("font-size: 16px; color: red;")


class ConfigPage(QWidget):
    """配置完成页面 - US-05"""

    retry_clicked = Signal()
    finish_clicked = Signal()
    exit_clicked = Signal()

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
        title = QLabel("正在完成配置")
        title.setAlignment(Qt.AlignCenter)
        title_font = QFont()
        title_font.setPointSize(20)
        title_font.setBold(True)
        title.setFont(title_font)

        # 状态说明
        self.status_label = QLabel("OpenClaw 已安装完成，正在进行自动配置...")
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
        self.step_config = ConfigStepWidget("初始化默认配置")
        self.step_gateway = ConfigStepWidget("启动网关")
        self.step_service = ConfigStepWidget("服务就绪")
        self.step_browser = ConfigStepWidget("打开 WebChat")

        steps_layout.addWidget(self.step_install)
        steps_layout.addWidget(self.step_config)
        steps_layout.addWidget(self.step_gateway)
        steps_layout.addWidget(self.step_service)
        steps_layout.addWidget(self.step_browser)

        # 进度条
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setMinimumHeight(25)

        # 当前任务
        self.task_label = QLabel("")
        self.task_label.setAlignment(Qt.AlignCenter)
        self.task_label.setStyleSheet("color: #666;")

        # WebChat 地址显示（成功后显示）
        self.url_frame = QFrame()
        self.url_frame.setStyleSheet(
            "background-color: #e8f4e8; border-radius: 8px; padding: 15px;"
        )
        self.url_frame.hide()

        url_layout = QVBoxLayout(self.url_frame)

        url_title = QLabel("🎉 OpenClaw 已就绪！")
        url_title_font = QFont()
        url_title_font.setBold(True)
        url_title_font.setPointSize(14)
        url_title.setFont(url_title_font)
        url_title.setStyleSheet("color: green;")

        url_desc = QLabel("WebChat 访问地址：")

        self.url_input = QLineEdit()
        self.url_input.setReadOnly(True)
        self.url_input.setStyleSheet(
            "padding: 8px; font-size: 12px; background-color: white;"
        )

        self.copy_button = QPushButton("复制地址")
        self.copy_button.setFixedWidth(100)
        self.copy_button.clicked.connect(self._copy_url)

        url_input_layout = QHBoxLayout()
        url_input_layout.addWidget(self.url_input)
        url_input_layout.addWidget(self.copy_button)

        self.browser_hint = QLabel("已尝试自动打开浏览器，如未成功请手动访问上方地址")
        self.browser_hint.setStyleSheet("color: #666; font-size: 11px;")
        self.browser_hint.setWordWrap(True)

        url_layout.addWidget(url_title)
        url_layout.addWidget(url_desc)
        url_layout.addLayout(url_input_layout)
        url_layout.addWidget(self.browser_hint)

        # 错误提示区域
        self.error_frame = QFrame()
        self.error_frame.setStyleSheet(
            "background-color: #fff3cd; border-radius: 8px; padding: 15px;"
        )
        self.error_frame.hide()

        error_layout = QVBoxLayout(self.error_frame)
        self.error_label = QLabel("")
        self.error_label.setWordWrap(True)
        self.error_label.setStyleSheet("color: #856404;")
        error_layout.addWidget(self.error_label)

        # 按钮区域
        button_layout = QHBoxLayout()
        button_layout.addStretch(1)

        self.exit_button = QPushButton("退出")
        self.exit_button.setFixedSize(100, 36)
        self.exit_button.clicked.connect(self.exit_clicked.emit)

        self.retry_button = QPushButton("重试")
        self.retry_button.setFixedSize(100, 36)
        self.retry_button.clicked.connect(self.retry_clicked.emit)
        self.retry_button.hide()

        self.finish_button = QPushButton("一键配置并启动服务")
        self.finish_button.setFixedSize(100, 36)
        self.finish_button.clicked.connect(self.finish_clicked.emit)
        self.finish_button.setEnabled(False)
        self.finish_button.hide()

        button_layout.addWidget(self.exit_button)
        button_layout.addWidget(self.retry_button)
        button_layout.addWidget(self.finish_button)

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
        layout.addSpacing(15)
        layout.addWidget(self.url_frame)
        layout.addWidget(self.error_frame)
        layout.addStretch(1)

        scroll_area.setWidget(content_widget)
        main_layout.addWidget(scroll_area, 1)

        # 按钮区域（固定在底部）
        button_layout.setContentsMargins(40, 10, 40, 0)
        main_layout.addLayout(button_layout)

    def _copy_url(self):
        """复制 URL 到剪贴板"""
        url = self.url_input.text()
        if url:
            clipboard = QApplication.clipboard()
            clipboard.setText(url)
            self.copy_button.setText("已复制!")

    def start_configuring(self):
        """开始配置 - 重置状态"""
        self.status_label.setText("OpenClaw 已安装完成，正在进行自动配置...")
        self.status_label.setStyleSheet("")

        self.step_install.set_completed()
        self.step_config.set_running()
        self.step_gateway.set_pending()
        self.step_service.set_pending()
        self.step_browser.set_pending()

        self.progress_bar.setValue(0)
        self.task_label.setText("准备写入配置...")

        self.url_frame.hide()
        self.error_frame.hide()

        self.exit_button.show()
        self.retry_button.hide()
        self.finish_button.hide()
        self.finish_button.setEnabled(False)

    def update_progress(self, progress: ConfigProgress):
        """更新进度"""
        self.progress_bar.setValue(progress.progress_percent)

        if progress.message:
            self.task_label.setText(progress.message)

        # 根据阶段更新步骤状态
        if progress.stage == ConfigStatus.CONFIGURING:
            self.step_config.set_running()
        elif progress.stage == ConfigStatus.GATEWAY_STARTING:
            self.step_config.set_completed()
            self.step_gateway.set_running()
        elif progress.stage == ConfigStatus.STARTING:
            self.step_gateway.set_completed()
            self.step_service.set_running()
        elif progress.stage == ConfigStatus.HEALTH_CHECKING:
            self.step_service.set_running()
        elif progress.stage == ConfigStatus.COMPLETED:
            self.step_config.set_completed()
            self.step_gateway.set_completed()
            self.step_service.set_completed()
            self.step_browser.set_completed()

    def config_success(self, result: ConfigResult):
        """配置成功"""
        self.status_label.setText("✓ OpenClaw 已启动成功！")
        self.status_label.setStyleSheet("color: green; font-weight: bold;")

        self.step_install.set_completed()
        self.step_config.set_completed()
        self.step_service.set_completed()
        self.step_browser.set_completed()

        self.progress_bar.setValue(100)
        self.task_label.setText("配置完成")

        # 显示 URL
        if result.webchat_url:
            self.url_input.setText(result.webchat_url)
            self.url_frame.show()

            if not result.browser_opened:
                self.browser_hint.setText("未能自动打开浏览器，请手动复制上方地址访问")

        self.error_frame.hide()

        # 按钮状态
        self.exit_button.hide()
        self.retry_button.hide()
        self.finish_button.show()
        self.finish_button.setEnabled(True)

    def config_failed(self, result: ConfigResult):
        """配置失败"""
        from models.helpers import UserMessageHelper
        
        self.status_label.setText("✗ 配置启动失败")
        self.status_label.setStyleSheet("color: red; font-weight: bold;")

        self.step_install.set_completed()

        # 根据失败阶段标记步骤
        if result.status == ConfigStatus.CONFIGURING:
            self.step_config.set_failed()
        elif result.status == ConfigStatus.GATEWAY_STARTING:
            self.step_config.set_completed()
            self.step_gateway.set_failed()
        elif result.status == ConfigStatus.STARTING:
            self.step_config.set_completed()
            self.step_gateway.set_completed()
            self.step_service.set_failed()
        elif result.status == ConfigStatus.HEALTH_CHECKING:
            self.step_config.set_completed()
            self.step_gateway.set_completed()
            self.step_service.set_failed()
        else:
            self.step_config.set_completed()
            self.step_gateway.set_completed()
            self.step_service.set_completed()
            self.step_browser.set_failed()

        # 显示友好的错误信息
        error_text = result.error_message
        if "端口" in error_text or "port" in error_text.lower():
            error_text = UserMessageHelper.get_friendly_error_message("port_in_use", error_text)
        elif "权限" in error_text.lower() or "permission" in error_text.lower():
            error_text = UserMessageHelper.get_friendly_error_message("permission", error_text)
        elif "服务" in error_text or "service" in error_text.lower():
            error_text = UserMessageHelper.get_friendly_error_message("service_start", error_text)
        else:
            error_text = UserMessageHelper.get_friendly_error_message("unknown", error_text)

        self.error_label.setText(error_text)
        self.error_frame.show()
        self.url_frame.hide()

        # 按钮状态
        self.exit_button.show()
        self.retry_button.show()
        self.finish_button.hide()

    def reset(self):
        """重置页面"""
        self.step_install.set_pending()
        self.step_config.set_pending()
        self.step_gateway.set_pending()
        self.step_service.set_pending()
        self.step_browser.set_pending()

        self.progress_bar.setValue(0)
        self.task_label.setText("")

        self.url_frame.hide()
        self.error_frame.hide()

        self.exit_button.show()
        self.retry_button.hide()
        self.finish_button.hide()
        self.finish_button.setEnabled(False)
