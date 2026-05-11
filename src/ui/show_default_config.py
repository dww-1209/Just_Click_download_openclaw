"""US-05 配置页面 —— 执行 OpenClaw 的初始化配置（onboarding）。

职责：在安装完成后，调用 openclaw onboard --non-interactive 自动生成默认配置文件，
并展示配置步骤的进度与结果。支持「重试」「手动配置」「下一步」三种用户分支。
"""

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

from src.models.config import ConfigStatus, ConfigProgress, ConfigResult


class ConfigStepWidget(QFrame):
    """配置步骤显示组件。

    职责：以图标（○ / ... / ✓ / ✗）+ 文字的形式展示单一步骤的状态。
    用于 US05ConfigPage 的步骤列表，让用户直观看到「安装完成 → 初始化配置」
    两个阶段的流转情况。
    """

    def __init__(self, step_name: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.step_name = step_name
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 5, 10, 5)

        self.icon_label = QLabel("○")
        self.icon_label.setStyleSheet("font-size: 16px;")

        self.name_label = QLabel(self.step_name)
        self.name_label.setMinimumWidth(200)

        layout.addWidget(self.icon_label)
        layout.addWidget(self.name_label)
        layout.addStretch(1)

    def set_pending(self) -> None:
        """步骤未开始：灰色空心圆圈"""
        self.icon_label.setText("○")
        self.icon_label.setStyleSheet("font-size: 16px; color: #999;")

    def set_running(self) -> None:
        """步骤进行中：橙色省略号，表示正在处理"""
        self.icon_label.setText("...")
        self.icon_label.setStyleSheet("font-size: 16px; color: orange;")

    def set_completed(self) -> None:
        """步骤完成：绿色对勾"""
        self.icon_label.setText("✓")
        self.icon_label.setStyleSheet("font-size: 16px; color: green;")

    def set_failed(self) -> None:
        """步骤失败：红色叉号"""
        self.icon_label.setText("✗")
        self.icon_label.setStyleSheet("font-size: 16px; color: red;")


class US05ConfigPage(QWidget):
    """US-05 配置页面 —— 执行 OpenClaw 初始化配置（onboarding）。

    职责：在安装完成后，通过后台线程调用 openclaw onboard --non-interactive
    生成默认配置文件，并实时展示步骤进度（安装完成 → 初始化配置）。
    支持「重试」「手动配置」「下一步」三种用户分支，以及可折叠的详细日志区域
    供技术人员排查问题。
    """

    retry_clicked = Signal()         # 配置失败后用户点击「重试」，触发重新执行 onboarding
    next_clicked = Signal()          # 配置成功后用户点击「下一步」，触发进入启动页
    back_clicked = Signal()          # 用户点击「返回」，回到安装进度页
    manual_config_clicked = Signal() # 用户点击「手动配置」，打开配置文件目录供手动编辑

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._setup_ui()

    def _setup_ui(self) -> None:
        from PySide6.QtWidgets import QScrollArea

        # 主布局：上部为可滚动内容区，下部为固定按钮栏。
        # 使用 QScrollArea 保证在小屏设备上所有步骤、日志和提示信息均可完整浏览。
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

        # 标题
        title = QLabel("正在配置 OpenClaw")
        title.setAlignment(Qt.AlignCenter)
        title_font = QFont()
        title_font.setPointSize(20)
        title_font.setBold(True)
        title.setFont(title_font)

        # 状态说明：动态更新，配置中/成功/失败时分别改变文本与颜色
        self.status_label = QLabel("正在为您自动配置 OpenClaw，请稍候...")
        self.status_label.setAlignment(Qt.AlignCenter)
        self.status_label.setWordWrap(True)

        # 步骤显示区域：使用浅色卡片包裹，突出两个阶段的流转状态
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

        # 进度条：0-100，与 ConfigProgress.progress_percent 同步
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setMinimumHeight(25)

        # 当前任务：展示更细粒度的子任务文本
        self.task_label = QLabel("")
        self.task_label.setAlignment(Qt.AlignCenter)
        self.task_label.setStyleSheet("color: #666;")

        # 日志显示区域（可折叠，用于排查问题）
        # 设计意图：默认隐藏，避免非技术用户被大量日志干扰；
        # 出现问题后由用户或技术支持手动展开查看最后 N 行输出。
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
        self.log_text.setObjectName("logArea")
        self.log_text.setMaximumHeight(150)
        log_layout.addWidget(self.log_text)

        # 显示/隐藏日志按钮
        self.toggle_log_btn = QPushButton("显示详细日志")
        self.toggle_log_btn.setStyleSheet("color: #666; font-size: 11px;")
        self.toggle_log_btn.clicked.connect(self._toggle_log)

        # 成功提示：绿色卡片，仅在配置完成后显示
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

        # 错误提示区域：黄色警告卡片，包含友好错误文本和可选的原始错误输出
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

        # 失败时只在黄底卡片里展示一句友好错误,完整日志走下面那个可折叠的黑底
        # "详细日志"面板。之前还有个 error_detail_label 把最后 20 行日志直接糊
        # 在黄底卡片里,跟黑底日志重复,而且小字等宽 + 不可复制,对小白用户没用。

        error_layout.addWidget(self.error_title)
        error_layout.addWidget(self.error_label)

        # 按钮区域
        # 按钮状态机：
        #   - 配置中：仅显示「返回」
        #   - 配置成功：隐藏「返回/重试/手动配置」，显示「下一步」
        #   - 配置失败：显示「返回」「手动配置」「重试」，隐藏「下一步」
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
        self.next_button.setObjectName("primaryButton")
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

    def _toggle_log(self) -> None:
        """切换日志显示"""
        if self.log_frame.isVisible():
            self.log_frame.hide()
            self.toggle_log_btn.setText("显示详细日志")
        else:
            self.log_frame.show()
            self.toggle_log_btn.setText("隐藏详细日志")

    def add_log_line(self, line: str) -> None:
        """添加日志行"""
        self.log_text.append(line)
        # 滚动到底部
        scrollbar = self.log_text.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    def start_configuring(self) -> None:
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

        self.back_button.show()
        self.manual_config_button.hide()
        self.retry_button.hide()
        self.next_button.hide()

    def update_progress(self, progress: ConfigProgress) -> None:
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

    def config_success(self, result: ConfigResult) -> None:
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

    def config_failed(self, result: ConfigResult) -> None:
        """配置失败"""
        self.status_label.setText("✗ 配置失败")
        self.status_label.setStyleSheet("color: red; font-weight: bold;")

        self.step_install.set_completed()
        self.step_config.set_failed()

        # 显示友好的错误信息
        error_text = result.error_message or "配置过程中发生错误"
        self.error_label.setText(error_text)

        # 完整日志走下面那个可折叠"详细日志"面板,这里黄底只放一句友好提示。

        self.error_frame.show()
        self.success_frame.hide()

        # 按钮状态
        self.back_button.show()
        self.manual_config_button.show()
        self.retry_button.show()
        self.next_button.hide()

    def reset(self) -> None:
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

        self.back_button.show()
        self.manual_config_button.hide()
        self.retry_button.hide()
        self.next_button.hide()
