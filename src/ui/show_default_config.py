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
    QPlainTextEdit,
)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont, QKeySequence, QShortcut

from src.models.config import ConfigStatus, ConfigProgress, ConfigResult


class ConfigStepWidget(QFrame):
    """配置步骤显示组件。

    职责:以"状态点 + 步骤名"展示单一步骤的状态。状态用 6×6 圆点指示
    (灰=未开始 / 琥珀=进行中 / 绿=完成 / 红=失败),取代原来的字符图标
    (○ / ... / ✓ / ✗)——后者在不同字体下渲染差异大,且偏 ASCII 风格,
    与企业级 UI 不一致。
    """

    def __init__(self, step_name: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.step_name = step_name
        self._setup_ui()

    def _setup_ui(self) -> None:
        self.setStyleSheet(
            "QFrame { border-bottom: 1px solid #E2E8F0; }"
            "QFrame QLabel { background: transparent; border: none; }"
        )
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 10, 0, 10)
        layout.setSpacing(12)

        self.dot = QLabel()
        self.dot.setFixedSize(8, 8)
        self.dot.setStyleSheet(
            "background-color: #CBD5E1; border-radius: 4px; border: none;"
        )

        self.name_label = QLabel(self.step_name)
        self.name_label.setStyleSheet("color: #0F172A; font-size: 13px; font-weight: 500;")
        self.name_label.setMinimumWidth(200)

        # 右侧状态文本
        self.status_text = QLabel("")
        self.status_text.setStyleSheet("color: #94A3B8; font-size: 12px;")
        self.status_text.setAlignment(Qt.AlignRight | Qt.AlignVCenter)

        layout.addWidget(self.dot)
        layout.addWidget(self.name_label)
        layout.addStretch(1)
        layout.addWidget(self.status_text)

    def _set_dot(self, color: str) -> None:
        self.dot.setStyleSheet(
            f"background-color: {color}; border-radius: 4px; border: none;"
        )

    def set_pending(self) -> None:
        self._set_dot("#CBD5E1")
        self.status_text.setText("")

    def set_running(self) -> None:
        self._set_dot("#D97706")
        self.status_text.setText("进行中")
        self.status_text.setStyleSheet("color: #92400E; font-size: 12px;")

    def set_completed(self) -> None:
        self._set_dot("#16A34A")
        self.status_text.setText("已完成")
        self.status_text.setStyleSheet("color: #15803D; font-size: 12px;")

    def set_failed(self) -> None:
        self._set_dot("#DC2626")
        self.status_text.setText("失败")
        self.status_text.setStyleSheet("color: #991B1B; font-size: 12px;")


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

        # 主布局:上部可滚动内容区,下部固定按钮栏(带 1px 顶部分割线)
        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(0)
        main_layout.setContentsMargins(0, 0, 0, 0)

        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameShape(QScrollArea.NoFrame)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll_area.setStyleSheet("QScrollArea { background-color: transparent; border: none; }")

        # 内容区透明:必须用 QWidget#锚定 选择器,见 show_uninstall_progress.py:39
        content_widget = QWidget()
        content_widget.setObjectName("configContent")
        content_widget.setStyleSheet("QWidget#configContent { background-color: transparent; }")
        layout = QVBoxLayout(content_widget)
        layout.setContentsMargins(56, 40, 56, 32)
        layout.setSpacing(0)

        # ── 标题 ───────────────────────────────────────────────
        title = QLabel("初始化配置")
        title.setStyleSheet(
            "color: #0F172A; font-size: 28px; font-weight: 700; "
            "letter-spacing: -0.5px; background: transparent; border: none;"
        )
        layout.addWidget(title)

        # 状态说明:动态更新
        self.status_label = QLabel("正在为 OpenClaw 生成默认配置...")
        self.status_label.setStyleSheet(
            "color: #64748B; font-size: 13px; background: transparent; border: none;"
        )
        self.status_label.setWordWrap(True)
        layout.addSpacing(8)
        layout.addWidget(self.status_label)

        # ── 步骤列表 ──────────────────────────────────────────
        section_label = QLabel("步骤")
        section_label.setStyleSheet(
            "color: #64748B; font-size: 11px; font-weight: 600; "
            "letter-spacing: 1.5px; background: transparent; border: none;"
        )
        layout.addSpacing(28)
        layout.addWidget(section_label)
        layout.addSpacing(8)

        top_border = QFrame()
        top_border.setStyleSheet("background-color: #E2E8F0; max-height: 1px; min-height: 1px;")
        layout.addWidget(top_border)

        self.step_install = ConfigStepWidget("安装完成")
        self.step_config = ConfigStepWidget("初始化配置")
        layout.addWidget(self.step_install)
        layout.addWidget(self.step_config)

        # ── 进度条 ──────────────────────────────────────────
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(False)
        layout.addSpacing(20)
        layout.addWidget(self.progress_bar)

        # 子任务文本
        self.task_label = QLabel("")
        self.task_label.setStyleSheet(
            "color: #94A3B8; font-size: 12px; background: transparent; border: none;"
        )
        layout.addSpacing(8)
        layout.addWidget(self.task_label)

        # ── 成功提示卡片(浅绿描边,无大色块) ────────────────
        self.success_frame = QFrame()
        self.success_frame.setStyleSheet(
            "QFrame { background-color: #F0FDF4; border: 1px solid #BBF7D0; "
            "border-radius: 6px; }"
            "QFrame QLabel { background: transparent; border: none; }"
        )
        self.success_frame.hide()
        success_layout = QVBoxLayout(self.success_frame)
        success_layout.setContentsMargins(14, 12, 14, 12)
        success_layout.setSpacing(2)

        success_title = QLabel("配置完成")
        success_title.setStyleSheet("color: #15803D; font-size: 13px; font-weight: 600;")
        success_desc = QLabel("点击「下一步」继续。")
        success_desc.setStyleSheet("color: #166534; font-size: 12px;")
        success_layout.addWidget(success_title)
        success_layout.addWidget(success_desc)

        # ── 错误提示卡片(浅红描边) ──────────────────────
        # "配置失败"是 error 语义,色板与全局 dangerButton (#B91C1C) 对齐;
        # 琥珀色保留给 warning(防火墙/SmartScreen 提示)。
        self.error_frame = QFrame()
        self.error_frame.setStyleSheet(
            "QFrame { background-color: #FEF2F2; border: 1px solid #FECACA; "
            "border-radius: 6px; }"
            "QFrame QLabel { background: transparent; border: none; }"
        )
        self.error_frame.hide()
        error_layout = QVBoxLayout(self.error_frame)
        error_layout.setContentsMargins(14, 12, 14, 12)
        error_layout.setSpacing(4)

        self.error_title = QLabel("配置失败")
        self.error_title.setStyleSheet("color: #B91C1C; font-size: 13px; font-weight: 600;")
        self.error_label = QLabel("")
        self.error_label.setWordWrap(True)
        self.error_label.setStyleSheet("color: #B91C1C; font-size: 12px;")
        error_layout.addWidget(self.error_title)
        error_layout.addWidget(self.error_label)

        layout.addSpacing(20)
        layout.addWidget(self.success_frame)
        layout.addWidget(self.error_frame)

        # ── 详细日志(可折叠) ─────────────────────────────────
        self.toggle_log_btn = QPushButton("显示详细日志")
        self.toggle_log_btn.setStyleSheet(
            "QPushButton { color: #64748B; font-size: 12px; border: none; "
            "background: transparent; padding: 4px 0; min-width: 0; "
            "text-align: left; font-weight: 500; }"
            "QPushButton:hover { color: #0F172A; }"
        )
        self.toggle_log_btn.setCursor(Qt.PointingHandCursor)
        self.toggle_log_btn.clicked.connect(self._toggle_log)

        self.log_frame = QFrame()
        self.log_frame.hide()
        log_layout = QVBoxLayout(self.log_frame)
        log_layout.setContentsMargins(0, 0, 0, 0)

        # 用 QPlainTextEdit + setMaximumBlockCount 而不是 QTextEdit:
        # QTextEdit.append 是富文本路径,每次插入都重做 HTML 解析+完整 layout。
        # Provider 配置失败重试时日志可能突发到几百行,主线程槽函数被堆满,
        # 5 秒内来不及处理 DWM 探测就触发"程序无响应"弹窗。
        self.log_text = QPlainTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setMaximumBlockCount(200)
        self.log_text.setObjectName("logArea")
        self.log_text.setMaximumHeight(160)
        log_layout.addWidget(self.log_text)

        layout.addSpacing(16)
        layout.addWidget(self.toggle_log_btn)
        layout.addSpacing(8)
        layout.addWidget(self.log_frame)
        layout.addStretch(1)

        scroll_area.setWidget(content_widget)
        main_layout.addWidget(scroll_area, 1)

        # ── 底部按钮栏 ──────────────────────────────────────
        # 按钮状态机:
        #   - 配置中:仅显示「返回」
        #   - 配置成功:隐藏「返回/重试/手动配置」,显示「下一步」
        #   - 配置失败:显示「返回」「手动配置」「重试」,隐藏「下一步」
        button_bar = QFrame()
        button_bar.setStyleSheet(
            "QFrame { background-color: #FAFBFC; border-top: 1px solid #E2E8F0; }"
        )
        button_layout = QHBoxLayout(button_bar)
        button_layout.setContentsMargins(56, 16, 56, 16)
        button_layout.setSpacing(8)

        self.back_button = QPushButton("返回")
        self.back_button.setFixedHeight(36)
        self.back_button.clicked.connect(self.back_clicked.emit)

        button_layout.addWidget(self.back_button)
        button_layout.addStretch(1)

        self.manual_config_button = QPushButton("手动配置")
        self.manual_config_button.setFixedHeight(36)
        self.manual_config_button.clicked.connect(self.manual_config_clicked.emit)
        self.manual_config_button.hide()

        self.retry_button = QPushButton("重试")
        self.retry_button.setFixedHeight(36)
        self.retry_button.clicked.connect(self.retry_clicked.emit)
        self.retry_button.hide()

        self.next_button = QPushButton("下一步")
        self.next_button.setFixedHeight(36)
        self.next_button.setObjectName("primaryButton")
        self.next_button.clicked.connect(self.next_clicked.emit)
        self.next_button.hide()

        button_layout.addWidget(self.manual_config_button)
        button_layout.addWidget(self.retry_button)
        button_layout.addWidget(self.next_button)

        main_layout.addWidget(button_bar)

        # 回车推进:next > retry,manual_config 不进回车序列(用户必须显式点)
        for seq in (QKeySequence(Qt.Key_Return), QKeySequence(Qt.Key_Enter)):
            sc = QShortcut(seq, self)
            sc.setContext(Qt.WidgetWithChildrenShortcut)
            sc.activated.connect(self._on_enter_pressed)

    def _on_enter_pressed(self) -> None:
        for btn in (self.next_button, self.retry_button):
            if btn.isEnabled() and btn.isVisible():
                btn.click()
                return

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
        # appendPlainText 是 QPlainTextEdit 的纯文本快路径,比 QTextEdit.append 快一个数量级
        self.log_text.appendPlainText(line)
        # 滚动到底部
        scrollbar = self.log_text.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    def start_configuring(self) -> None:
        """开始配置 - 重置状态"""
        self.status_label.setText("正在为 OpenClaw 生成默认配置...")
        self.status_label.setStyleSheet(
            "color: #64748B; font-size: 13px; background: transparent; border: none;"
        )

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
        self.status_label.setText("配置完成")
        self.status_label.setStyleSheet(
            "color: #15803D; font-size: 13px; font-weight: 600; "
            "background: transparent; border: none;"
        )

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
        self.status_label.setText("配置失败")
        self.status_label.setStyleSheet(
            "color: #B91C1C; font-size: 13px; font-weight: 600; "
            "background: transparent; border: none;"
        )

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
