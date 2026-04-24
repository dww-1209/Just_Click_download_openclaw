from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QLabel,
    QPushButton,
    QHBoxLayout,
    QProgressBar,
    QFrame,
    QSpacerItem,
    QSizePolicy,
)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont

from models.env_check import (
    CheckStatus,
    OpenClawStatus,
    EnvCheckResult,
    BrowserResult,
)


class CheckItemWidget(QFrame):
    """单个检测项显示组件"""

    def __init__(self, name: str, parent=None):
        super().__init__(parent)
        self.name = name
        self._setup_ui()

    def _setup_ui(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 5, 10, 5)

        self.name_label = QLabel(self.name)
        self.name_label.setMinimumWidth(150)

        self.status_label = QLabel("... 检测中")
        self.status_label.setAlignment(Qt.AlignRight)

        layout.addWidget(self.name_label)
        layout.addStretch(1)
        layout.addWidget(self.status_label)

    def set_status(self, status: CheckStatus, message: str = ""):
        if status == CheckStatus.OK:
            self.status_label.setText(f"[OK] {message}")
            self.status_label.setStyleSheet("color: green;")
        elif status == CheckStatus.WARNING:
            self.status_label.setText(f"[!] {message}")
            self.status_label.setStyleSheet("color: orange;")
        else:
            self.status_label.setText(f"[X] {message}")
            self.status_label.setStyleSheet("color: red;")


class OpenClawInstalledWidget(QWidget):
    """OpenClaw 已安装选项组件"""

    quick_start_clicked = Signal()       # 快速启动
    config_and_start_clicked = Signal()  # 重新配置并启动
    provider_config_clicked = Signal()   # 配置模型
    manual_config_clicked = Signal()     # 手动配置
    uninstall_clicked = Signal()         # 卸载
    reinstall_clicked = Signal()         # 重新下载

    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        self.setStyleSheet("background-color: #e8f4e8; border-radius: 5px;")

        title = QLabel("检测到 OpenClaw 已安装")
        title_font = QFont()
        title_font.setBold(True)
        title_font.setPointSize(12)
        title.setFont(title_font)

        desc = QLabel("请选择操作：")

        # 第一行按钮：快速操作
        quick_layout = QHBoxLayout()
        quick_layout.addStretch(1)

        self.quick_start_btn = QPushButton("快速启动")
        self.quick_start_btn.setFixedSize(140, 35)
        self.quick_start_btn.setStyleSheet("background-color: #28a745; color: white; font-weight: bold;")
        self.quick_start_btn.clicked.connect(self.quick_start_clicked.emit)

        self.config_and_start_btn = QPushButton("重新配置并启动")
        self.config_and_start_btn.setFixedSize(140, 35)
        self.config_and_start_btn.clicked.connect(self.config_and_start_clicked.emit)

        self.provider_config_btn = QPushButton("配置模型")
        self.provider_config_btn.setFixedSize(140, 35)
        self.provider_config_btn.setStyleSheet(
            "background-color: #17a2b8; color: white; font-weight: bold;"
        )
        self.provider_config_btn.clicked.connect(self.provider_config_clicked.emit)

        quick_layout.addWidget(self.quick_start_btn)
        quick_layout.addWidget(self.config_and_start_btn)
        quick_layout.addWidget(self.provider_config_btn)
        quick_layout.addStretch(1)

        # 第二行按钮：其他选项
        other_layout = QHBoxLayout()
        other_layout.addStretch(1)

        self.manual_config_btn = QPushButton("手动配置")
        self.manual_config_btn.setFixedSize(120, 35)
        self.manual_config_btn.clicked.connect(self.manual_config_clicked.emit)

        self.uninstall_btn = QPushButton("卸载")
        self.uninstall_btn.setFixedSize(120, 35)
        self.uninstall_btn.setStyleSheet("background-color: #dc3545; color: white; font-weight: bold;")
        self.uninstall_btn.clicked.connect(self.uninstall_clicked.emit)

        self.reinstall_btn = QPushButton("重新下载")
        self.reinstall_btn.setFixedSize(120, 35)
        self.reinstall_btn.clicked.connect(self.reinstall_clicked.emit)

        other_layout.addWidget(self.manual_config_btn)
        other_layout.addWidget(self.uninstall_btn)
        other_layout.addWidget(self.reinstall_btn)
        other_layout.addStretch(1)

        layout.addWidget(title)
        layout.addSpacing(10)
        layout.addWidget(desc)
        layout.addSpacing(15)
        layout.addLayout(quick_layout)
        layout.addSpacing(10)
        layout.addLayout(other_layout)


class EnvCheckPage(QWidget):
    """环境检测页面 - US-02"""

    retry_clicked = Signal()
    next_clicked = Signal()
    back_clicked = Signal()
    openclaw_quick_start = Signal()      # 快速启动
    openclaw_config_and_start = Signal() # 重新配置并启动
    openclaw_provider_config = Signal()  # 配置模型
    openclaw_manual_config = Signal()    # 手动配置
    openclaw_uninstall = Signal()        # 卸载
    openclaw_reinstall = Signal()        # 重新下载

    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_ui()
        self._hide_openclaw_widget()

    def _setup_ui(self):
        from PySide6.QtWidgets import QScrollArea
        from PySide6.QtCore import QSize

        # 主布局
        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(10)
        main_layout.setContentsMargins(20, 20, 20, 20)

        # 创建滚动区域以适应小屏幕
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameShape(QScrollArea.NoFrame)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        # 内容容器
        content_widget = QWidget()
        layout = QVBoxLayout(content_widget)
        layout.setSpacing(15)
        layout.setContentsMargins(40, 20, 40, 20)

        title = QLabel("环境检测")
        title.setAlignment(Qt.AlignCenter)
        title_font = QFont()
        title_font.setPointSize(18)
        title_font.setBold(True)
        title.setFont(title_font)

        self.status_label = QLabel("正在检测您的系统环境，请稍后...")
        self.status_label.setAlignment(Qt.AlignCenter)

        self.os_item = CheckItemWidget("操作系统")
        self.disk_item = CheckItemWidget("磁盘空间")
        self.permission_item = CheckItemWidget("权限状态")
        self.browser_item = CheckItemWidget("浏览器支持")
        self.openclaw_item = CheckItemWidget("OpenClaw 安装")

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 0)
        self.progress_bar.setMinimumHeight(20)

        self.openclaw_widget = OpenClawInstalledWidget()
        self.openclaw_widget.quick_start_clicked.connect(
            self.openclaw_quick_start.emit
        )
        self.openclaw_widget.config_and_start_clicked.connect(
            self.openclaw_config_and_start.emit
        )
        self.openclaw_widget.provider_config_clicked.connect(
            self.openclaw_provider_config.emit
        )
        self.openclaw_widget.manual_config_clicked.connect(
            self.openclaw_manual_config.emit
        )
        self.openclaw_widget.uninstall_clicked.connect(
            self.openclaw_uninstall.emit
        )
        self.openclaw_widget.reinstall_clicked.connect(self.openclaw_reinstall.emit)

        self.hint_label = QLabel("")
        self.hint_label.setWordWrap(True)
        self.hint_label.setStyleSheet("color: #666;")
        self.hint_label.setAlignment(Qt.AlignCenter)

        layout.addWidget(title)
        layout.addSpacing(15)
        layout.addWidget(self.status_label)
        layout.addSpacing(15)
        layout.addWidget(self.os_item)
        layout.addWidget(self.disk_item)
        layout.addWidget(self.permission_item)
        layout.addWidget(self.browser_item)
        layout.addWidget(self.openclaw_item)
        layout.addSpacing(15)
        layout.addWidget(self.progress_bar)
        layout.addSpacing(15)
        layout.addWidget(self.openclaw_widget)
        layout.addSpacing(15)
        layout.addWidget(self.hint_label)
        layout.addStretch(1)

        scroll_area.setWidget(content_widget)
        main_layout.addWidget(scroll_area, 1)

        # 按钮区域（固定在底部）
        button_layout = QHBoxLayout()
        button_layout.setContentsMargins(40, 10, 40, 0)
        button_layout.addStretch(1)

        self.retry_button = QPushButton("重试")
        self.retry_button.setFixedSize(100, 36)
        self.retry_button.clicked.connect(self.retry_clicked.emit)
        self.retry_button.hide()

        self.back_button = QPushButton("返回")
        self.back_button.setFixedSize(100, 36)
        self.back_button.clicked.connect(self.back_clicked.emit)

        self.next_button = QPushButton("Next")
        self.next_button.setFixedSize(100, 36)
        self.next_button.clicked.connect(self.next_clicked.emit)
        self.next_button.setEnabled(False)

        button_layout.addWidget(self.retry_button)
        button_layout.addWidget(self.back_button)
        button_layout.addWidget(self.next_button)

        main_layout.addLayout(button_layout)

    def _hide_openclaw_widget(self):
        self.openclaw_widget.hide()

    def _show_openclaw_widget(self):
        self.openclaw_widget.show()

    def start_checking(self):
        self.progress_bar.setRange(0, 0)
        self.status_label.setText("正在检测您的系统环境，请稍后...")
        self.next_button.setEnabled(False)
        self.retry_button.hide()
        self._hide_openclaw_widget()

    def update_os_result(self, os_type: str):
        os_name = {"windows": "Windows", "macos": "macOS", "linux": "Linux"}.get(
            os_type, os_type
        )
        self.os_item.set_status(CheckStatus.OK, os_name)

    def update_disk_result(self, status: CheckStatus, message: str, path: str = None):
        """更新磁盘空间检测结果
        
        Args:
            status: 检测状态
            message: 状态消息
            path: 检测的安装路径（可选）
        """
        # 如果有路径信息，显示在消息中
        if path:
            display_msg = f"{path} - {message}"
        else:
            display_msg = message
        self.disk_item.set_status(status, display_msg)

    # US-02 不检测网络
    # def update_network_result(self, status: CheckStatus, message: str):
    #     self.network_item.set_status(status, message)

    def update_permission_result(self, status: CheckStatus, message: str):
        self.permission_item.set_status(status, message)

    def update_browser_result(self, result: BrowserResult):
        if result.status == CheckStatus.OK:
            self.browser_item.set_status(CheckStatus.OK, result.message)
        else:
            self.browser_item.set_status(
                CheckStatus.WARNING,
                f"{result.message}（建议安装以使用浏览器自动化）"
            )

    def update_openclaw_result(self, status: OpenClawStatus, message: str):
        if status == OpenClawStatus.INSTALLED:
            self.openclaw_item.set_status(CheckStatus.OK, "已安装")
            self._show_openclaw_widget()
            self.next_button.setEnabled(False)
            self.next_button.hide()
        else:
            self.openclaw_item.set_status(CheckStatus.OK, "未安装")
            self._hide_openclaw_widget()
            self.next_button.setEnabled(True)

    def check_complete(self, is_ready: bool, message: str):
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(100)
        self.status_label.setText(message)

        if is_ready:
            self.next_button.setEnabled(True)
            self.retry_button.hide()
            # 添加友好的提示
            self.hint_label.setText("[OK] 您的系统环境符合要求，可以继续安装")
            self.hint_label.setStyleSheet("color: green;")
        else:
            self.next_button.setEnabled(False)
            self.retry_button.show()
            self.hint_label.setText("[X] 环境检测未通过，请根据上方提示解决问题后重试")
            self.hint_label.setStyleSheet("color: red;")

    def reset(self):
        self.progress_bar.setRange(0, 0)
        self.next_button.setEnabled(False)
        self.retry_button.hide()
        self._hide_openclaw_widget()
        self.hint_label.setText("")
