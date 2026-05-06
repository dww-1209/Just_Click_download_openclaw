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

from src.models.env_check import (
    CheckStatus,
    OpenClawStatus,
    EnvCheckResult,
    BrowserResult,
)


class CheckItemWidget(QFrame):
    """单个检测项显示组件。

    职责：将「检测项名称 + 状态标签 + 详情文本」封装为一行可复用的卡片。
    状态标签使用彩色圆角 pill 样式（绿/橙/红），让非技术用户一眼识别通过、
    警告、失败三种结果，无需阅读英文日志。
    """

    def __init__(self, name: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.name = name
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 5, 10, 5)

        self.name_label = QLabel(self.name)
        self.name_label.setMinimumWidth(150)

        self.status_label = QLabel("... 检测中")
        self.status_label.setAlignment(Qt.AlignRight)

        layout.addWidget(self.name_label)
        layout.addStretch(1)
        layout.addWidget(self.status_label)

    def set_status(self, status: CheckStatus, message: str = "") -> None:
        """根据检测结果更新状态标签样式与文本。"""
        if status == CheckStatus.OK:
            tag = '<span style="background:#E8F5E9; color:#2E7D32; padding:2px 10px; border-radius:10px; font-size:12px; font-weight:bold;">✓ OK</span>'
            self.status_label.setText(f'{tag}&nbsp;&nbsp;<span style="color:#1E293B; font-size:13px;">{message}</span>')
        elif status == CheckStatus.WARNING:
            tag = '<span style="background:#FFF8E1; color:#F57C00; padding:2px 10px; border-radius:10px; font-size:12px; font-weight:bold;">⚠</span>'
            self.status_label.setText(f'{tag}&nbsp;&nbsp;<span style="color:#1E293B; font-size:13px;">{message}</span>')
        else:
            tag = '<span style="background:#FFEBEE; color:#C62828; padding:2px 10px; border-radius:10px; font-size:12px; font-weight:bold;">✗</span>'
            self.status_label.setText(f'{tag}&nbsp;&nbsp;<span style="color:#1E293B; font-size:13px;">{message}</span>')


class OpenClawInstalledWidget(QWidget):
    """OpenClaw 已安装选项组件（US-02 分支场景）。

    职责：当环境检测到 OpenClaw 已安装时，代替常规的「下一步」按钮，
    向用户提供 5 种快捷操作。该组件默认隐藏，仅在检测到已安装状态后显示。
    设计上采用两行按钮布局：第一行为高频正向操作（启动/配置），
    第二行为低频或破坏性操作（手动配置/重新下载），降低误触风险。
    """

    quick_start_clicked = Signal()       # 用户点击「快速启动」——直接拉起已有 Gateway
    config_and_start_clicked = Signal()  # 用户点击「重新配置并启动」——清空配置后重新 onboarding
    provider_config_clicked = Signal()   # 用户点击「配置模型」——跳转到 Provider 配置页
    manual_config_clicked = Signal()     # 用户点击「手动配置」——打开配置文件目录供用户手动编辑
    reinstall_clicked = Signal()         # 用户点击「重新下载」——删除旧版本后重新执行 US-04 安装流程

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        self.setObjectName("openclawInstalledWidget")
        self.setStyleSheet("QWidget#openclawInstalledWidget { background-color: #e8f4e8; border-radius: 8px; }")

        title = QLabel("检测到 OpenClaw 已安装")
        title_font = QFont()
        title_font.setBold(True)
        title_font.setPointSize(12)
        title.setFont(title_font)

        desc = QLabel("请选择操作：")

        # 第一行按钮：高频正向操作，使用 primaryButton 样式突出显示
        quick_layout = QHBoxLayout()
        quick_layout.addStretch(1)

        self.quick_start_btn = QPushButton("快速启动")
        self.quick_start_btn.setFixedSize(140, 36)
        self.quick_start_btn.setObjectName("primaryButton")
        self.quick_start_btn.clicked.connect(self.quick_start_clicked.emit)

        self.config_and_start_btn = QPushButton("重新配置并启动")
        self.config_and_start_btn.setFixedSize(140, 36)
        self.config_and_start_btn.setObjectName("primaryButton")
        self.config_and_start_btn.clicked.connect(self.config_and_start_clicked.emit)

        self.provider_config_btn = QPushButton("配置模型")
        self.provider_config_btn.setFixedSize(140, 36)
        self.provider_config_btn.setObjectName("primaryButton")
        self.provider_config_btn.clicked.connect(self.provider_config_clicked.emit)

        quick_layout.addWidget(self.quick_start_btn)
        quick_layout.addWidget(self.config_and_start_btn)
        quick_layout.addWidget(self.provider_config_btn)
        quick_layout.addStretch(1)

        # 第二行按钮：低频或偏门操作，使用默认样式，视觉上弱于第一行
        other_layout = QHBoxLayout()
        other_layout.addStretch(1)

        self.manual_config_btn = QPushButton("手动配置")
        self.manual_config_btn.setFixedSize(120, 36)
        self.manual_config_btn.clicked.connect(self.manual_config_clicked.emit)

        self.reinstall_btn = QPushButton("重新下载")
        self.reinstall_btn.setFixedSize(120, 36)
        self.reinstall_btn.clicked.connect(self.reinstall_clicked.emit)

        other_layout.addWidget(self.manual_config_btn)
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
    """环境检测页面（US-02）—— 安装前的系统兼容性检查。

    职责：在后台线程中并行检测操作系统、磁盘空间、权限、浏览器支持以及
    OpenClaw 是否已安装，并将结果实时反映到 UI。检测结果决定用户可走的分支：
    - 全新安装：检测通过后启用「下一步」
    - 已安装场景：展示 OpenClawInstalledWidget，提供快速启动/重新配置/重装等选项
    """

    retry_clicked = Signal()             # 检测失败或用户希望重新检测时触发
    next_clicked = Signal()              # 检测通过且为全新安装时，用户点击「下一步」触发
    back_clicked = Signal()              # 用户点击「返回」回到欢迎页
    openclaw_quick_start = Signal()      # 已安装场景：用户选择「快速启动」
    openclaw_config_and_start = Signal() # 已安装场景：用户选择「重新配置并启动」
    openclaw_provider_config = Signal()  # 已安装场景：用户选择「配置模型」
    openclaw_manual_config = Signal()    # 已安装场景：用户选择「手动配置」
    openclaw_reinstall = Signal()        # 已安装场景：用户选择「重新下载」

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._setup_ui()
        self._hide_openclaw_widget()

    def _setup_ui(self) -> None:
        from PySide6.QtWidgets import QScrollArea
        from PySide6.QtCore import QSize

        # 主布局：上部为可滚动检测内容，下部为固定按钮栏。
        # 使用 QScrollArea 保证在笔记本小屏（1366×768）或高 DPI 缩放时
        # 所有检测项和提示信息均可完整浏览。
        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(10)
        main_layout.setContentsMargins(24, 24, 24, 24)

        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameShape(QScrollArea.NoFrame)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

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
        self.progress_bar.setRange(0, 0)  # 设置为不确定模式，表示检测正在进行中
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
        # 状态机设计：
        #   - 检测中：next_button 禁用，retry_button 隐藏
        #   - 检测通过（全新安装）：next_button 启用，retry_button 隐藏
        #   - 检测失败：next_button 禁用，retry_button 显示
        #   - 已安装：next_button 隐藏，由 OpenClawInstalledWidget 接管操作
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

        self.next_button = QPushButton("下一步")
        self.next_button.setFixedSize(100, 36)
        self.next_button.setObjectName("primaryButton")
        self.next_button.clicked.connect(self.next_clicked.emit)
        self.next_button.setEnabled(False)

        button_layout.addWidget(self.retry_button)
        button_layout.addWidget(self.back_button)
        button_layout.addWidget(self.next_button)

        main_layout.addLayout(button_layout)

    def _hide_openclaw_widget(self) -> None:
        self.openclaw_widget.hide()

    def _show_openclaw_widget(self) -> None:
        self.openclaw_widget.show()

    def start_checking(self) -> None:
        self.progress_bar.setRange(0, 0)
        self.status_label.setText("正在检测您的系统环境，请稍后...")
        self.next_button.setEnabled(False)
        self.retry_button.hide()
        self._hide_openclaw_widget()

    def update_os_result(self, os_type: str) -> None:
        os_name = {"windows": "Windows", "macos": "macOS", "linux": "Linux"}.get(
            os_type, os_type
        )
        self.os_item.set_status(CheckStatus.OK, os_name)

    def update_disk_result(self, status: CheckStatus, message: str, path: str | None = None) -> None:
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

    def update_permission_result(self, status: CheckStatus, message: str) -> None:
        self.permission_item.set_status(status, message)

    def update_browser_result(self, result: BrowserResult) -> None:
        if result.status == CheckStatus.OK:
            self.browser_item.set_status(CheckStatus.OK, result.message)
        else:
            self.browser_item.set_status(
                CheckStatus.WARNING,
                f"{result.message}（建议安装以使用浏览器自动化）"
            )

    def update_openclaw_result(self, status: OpenClawStatus, message: str) -> None:
        if status == OpenClawStatus.INSTALLED:
            self.openclaw_item.set_status(CheckStatus.OK, "已安装")
            self._show_openclaw_widget()
            self.next_button.setEnabled(False)
            self.next_button.hide()
        else:
            self.openclaw_item.set_status(CheckStatus.OK, "未安装")
            self._hide_openclaw_widget()
            self.next_button.setEnabled(True)

    def check_complete(self, is_ready: bool, message: str) -> None:
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

    def reset(self) -> None:
        self.progress_bar.setRange(0, 0)
        self.next_button.setEnabled(False)
        self.retry_button.hide()
        self._hide_openclaw_widget()
        self.hint_label.setText("")
