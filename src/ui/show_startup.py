"""US-06 启动页面 —— 启动 Gateway 服务并打开 WebChat。

职责：在配置完成后，通过后台线程启动 openclaw-cn gateway start，
轮询 18789 端口健康检查，成功后获取带 token 的 WebChat URL 并展示给用户。
同时提供倒计时防抖、URL 复制、浏览器打开等交互，确保非技术用户能一键进入 WebChat。
"""

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QPushButton, QHBoxLayout,
    QProgressBar, QFrame, QLineEdit, QApplication, QPlainTextEdit,
    QCheckBox,
)
from PySide6.QtCore import Qt, Signal, QTimer
from PySide6.QtGui import QFont, QKeySequence, QShortcut

from src.models.config import ConfigStatus, ConfigProgress, ConfigResult
from src.models.constants import is_windows


class StartupStepWidget(QFrame):
    """启动步骤显示组件 — 与 ConfigStepWidget 保持视觉一致。"""

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
        self.dot.setStyleSheet("background-color: #CBD5E1; border-radius: 4px; border: none;")

        self.name_label = QLabel(self.step_name)
        self.name_label.setStyleSheet("color: #0F172A; font-size: 13px; font-weight: 500;")
        self.name_label.setMinimumWidth(200)

        self.status_text = QLabel("")
        self.status_text.setStyleSheet("color: #94A3B8; font-size: 12px;")
        self.status_text.setAlignment(Qt.AlignRight | Qt.AlignVCenter)

        layout.addWidget(self.dot)
        layout.addWidget(self.name_label)
        layout.addStretch(1)
        layout.addWidget(self.status_text)

    def _set_dot(self, color: str) -> None:
        self.dot.setStyleSheet(f"background-color: {color}; border-radius: 4px; border: none;")

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


class US06StartupPage(QWidget):
    """US-06 启动页面 —— 启动 Gateway 服务并打开 WebChat。

    职责：在配置完成后，通过后台线程启动 openclaw-cn gateway start，
    轮询 18789 端口健康检查，成功后获取带 token 的 WebChat URL 并展示给用户。
    页面提供倒计时防抖（避免用户过早点击导致连接失败）、URL 复制、浏览器打开等交互，
    同时以醒目的红色警告提示用户「不要关闭安装器窗口」，因为 Gateway 是前台进程。
    """

    retry_clicked = Signal()         # 启动失败后用户点击「重试」，触发重新启动 Gateway
    finish_clicked = Signal()        # 用户点击「完成」，触发关闭安装器
    back_clicked = Signal()          # 用户点击「返回」，回到配置页
    open_webchat_clicked = Signal()  # 倒计时结束后用户点击「打开 WebChat」，触发打开系统浏览器

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._setup_ui()

    def _setup_ui(self) -> None:
        from PySide6.QtWidgets import QScrollArea

        # 主布局:上部可滚动内容区,下部固定按钮栏(带 1px 顶部分割线)
        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(0)
        main_layout.setContentsMargins(0, 0, 0, 0)

        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setFrameShape(QScrollArea.NoFrame)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll_area.setStyleSheet("QScrollArea { background-color: transparent; border: none; }")

        # 内容区透明:必须用 QWidget#锚定 选择器,见 show_uninstall_progress.py:39
        content_widget = QWidget()
        content_widget.setObjectName("startupContent")
        content_widget.setStyleSheet("QWidget#startupContent { background-color: transparent; }")
        layout = QVBoxLayout(content_widget)
        layout.setContentsMargins(56, 40, 56, 32)
        layout.setSpacing(0)

        # ── 标题 ───────────────────────────────────────────────
        title = QLabel("启动服务")
        title.setStyleSheet(
            "color: #0F172A; font-size: 28px; font-weight: 700; "
            "letter-spacing: -0.5px; background: transparent; border: none;"
        )
        layout.addWidget(title)

        self.status_label = QLabel("正在启动网关服务...")
        self.status_label.setStyleSheet(
            "color: #64748B; font-size: 13px; background: transparent; border: none;"
        )
        self.status_label.setWordWrap(True)
        layout.addSpacing(8)
        layout.addWidget(self.status_label)

        # ── 步骤列表 ───────────────────────────────────────
        section_label = QLabel("步骤")
        section_label.setStyleSheet(
            "color: #64748B; font-size: 11px; font-weight: 600; "
            "letter-spacing: 1.5px; background: transparent; border: none;"
        )
        layout.addSpacing(28)
        layout.addWidget(section_label)
        layout.addSpacing(8)

        self.steps_frame = QWidget()
        self.steps_frame.setObjectName("startupStepsFrame")
        self.steps_frame.setStyleSheet("QWidget#startupStepsFrame { background: transparent; }")
        steps_layout = QVBoxLayout(self.steps_frame)
        steps_layout.setContentsMargins(0, 0, 0, 0)
        steps_layout.setSpacing(0)
        top_border = QFrame()
        top_border.setStyleSheet("background-color: #E2E8F0; max-height: 1px; min-height: 1px;")
        steps_layout.addWidget(top_border)
        self.step_gateway = StartupStepWidget("启动网关")
        self.step_health = StartupStepWidget("服务检查")
        steps_layout.addWidget(self.step_gateway)
        steps_layout.addWidget(self.step_health)
        layout.addWidget(self.steps_frame)

        # ── Windows 防火墙提示(浅琥珀 callout) ─────────────
        self.firewall_hint = QLabel(
            "Windows 可能弹出防火墙授权窗口,请点击「允许访问」,否则 WebChat 无法正常打开。"
        )
        self.firewall_hint.setWordWrap(True)
        self.firewall_hint.setStyleSheet(
            "background-color: #FFFBEB; color: #92400E; border: 1px solid #FDE68A; "
            "border-radius: 6px; padding: 10px 14px; font-size: 12px; font-weight: 500;"
        )
        if not is_windows():
            self.firewall_hint.hide()
        else:
            layout.addSpacing(16)
            layout.addWidget(self.firewall_hint)

        # ── 进度条 ──────────────────────────────────────────
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(False)
        layout.addSpacing(20)
        layout.addWidget(self.progress_bar)

        self.task_label = QLabel("")
        self.task_label.setStyleSheet(
            "color: #94A3B8; font-size: 12px; background: transparent; border: none;"
        )
        layout.addSpacing(8)
        layout.addWidget(self.task_label)

        # ── 成功卡片:WebChat 入口集合 ────────────────────────
        # 设计思路:从原来的"绿色满色块"改为"白色卡片 + 1px 描边",
        # 用排版和细节(标题字号、URL 行高、按钮宽度)建立层次,而非用色块吼叫
        self.success_frame = QFrame()
        self.success_frame.setStyleSheet(
            "QFrame { background-color: white; border: 1px solid #E2E8F0; border-radius: 8px; }"
            "QFrame QLabel { background: transparent; border: none; }"
        )
        self.success_frame.hide()

        success_layout = QVBoxLayout(self.success_frame)
        success_layout.setSpacing(0)
        success_layout.setContentsMargins(24, 22, 24, 22)

        # 顶部:绿色 dot + "已就绪"标签
        ready_row = QHBoxLayout()
        ready_row.setSpacing(8)
        ready_dot = QLabel()
        ready_dot.setFixedSize(8, 8)
        ready_dot.setStyleSheet("background-color: #16A34A; border-radius: 4px;")
        ready_text = QLabel("服务已就绪")
        ready_text.setStyleSheet("color: #15803D; font-size: 12px; font-weight: 600; letter-spacing: 0.3px;")
        ready_row.addWidget(ready_dot)
        ready_row.addWidget(ready_text)
        ready_row.addStretch(1)
        success_layout.addLayout(ready_row)

        success_title = QLabel("OpenClaw 已就绪")
        success_title.setStyleSheet(
            "color: #0F172A; font-size: 22px; font-weight: 700; letter-spacing: -0.5px;"
        )
        success_layout.addSpacing(8)
        success_layout.addWidget(success_title)

        url_desc = QLabel("WEBCHAT 访问地址")
        url_desc.setStyleSheet(
            "color: #94A3B8; font-size: 11px; font-weight: 600; letter-spacing: 1.5px;"
        )
        success_layout.addSpacing(20)
        success_layout.addWidget(url_desc)

        self.url_input = QLineEdit()
        self.url_input.setReadOnly(True)
        self.url_input.setMinimumHeight(36)

        self.copy_button = QPushButton("复制")
        self.copy_button.setFixedWidth(72)
        self.copy_button.setFixedHeight(36)
        self.copy_button.clicked.connect(self._copy_url)

        url_input_layout = QHBoxLayout()
        url_input_layout.setSpacing(8)
        url_input_layout.addWidget(self.url_input)
        url_input_layout.addWidget(self.copy_button)
        success_layout.addSpacing(6)
        success_layout.addLayout(url_input_layout)

        # 主 CTA:打开 WebChat
        self.open_webchat_btn = QPushButton("打开 WebChat")
        self.open_webchat_btn.setCursor(Qt.PointingHandCursor)
        self.open_webchat_btn.setObjectName("primaryButton")
        self.open_webchat_btn.setFixedHeight(40)
        self.open_webchat_btn.setEnabled(False)
        self.open_webchat_btn.clicked.connect(self.open_webchat_clicked.emit)
        success_layout.addSpacing(16)
        success_layout.addWidget(self.open_webchat_btn)

        # 倒计时:启动成功后等待 8 秒再启用「打开 WebChat」按钮,
        # 避免 Gateway 未完全就绪导致 502/连接拒绝。
        self.countdown_label = QLabel("等待连接稳定... 8 秒")
        self.countdown_label.setStyleSheet("color: #94A3B8; font-size: 11px;")
        self.countdown_label.hide()
        success_layout.addSpacing(8)
        success_layout.addWidget(self.countdown_label, alignment=Qt.AlignCenter)

        self.browser_hint = QLabel("点击按钮在浏览器中打开。")
        self.browser_hint.setStyleSheet("color: #64748B; font-size: 11px;")
        self.fallback_hint = QLabel("若按钮无法打开,可复制上方地址到浏览器访问。")
        self.fallback_hint.setStyleSheet("color: #94A3B8; font-size: 11px;")
        success_layout.addSpacing(4)
        success_layout.addWidget(self.browser_hint, alignment=Qt.AlignCenter)
        success_layout.addWidget(self.fallback_hint, alignment=Qt.AlignCenter)

        # 分隔线
        success_divider = QFrame()
        success_divider.setStyleSheet("background-color: #F1F5F9; max-height: 1px; min-height: 1px;")
        success_layout.addSpacing(20)
        success_layout.addWidget(success_divider)

        # 关键警告:请勿关闭本窗口
        # Gateway 以前台子进程方式运行,安装器窗口关闭会回收进程树
        # 用红色 dot + 醒目文字,不再用大色块——大色块在企业级 UI 里偏 toy
        warn_row = QHBoxLayout()
        warn_row.setSpacing(10)
        warn_row.setContentsMargins(0, 0, 0, 0)
        warn_dot = QLabel()
        warn_dot.setFixedSize(8, 8)
        warn_dot.setStyleSheet("background-color: #DC2626; border-radius: 4px;")
        # 顶部对齐,文字多行时 dot 不要被拉到中间
        warn_text = QLabel("请勿关闭本窗口。Gateway 在此进程内运行,关闭后 OpenClaw 服务会停止。")
        warn_text.setWordWrap(True)
        warn_text.setStyleSheet("color: #991B1B; font-size: 12px; font-weight: 500;")
        warn_row.addWidget(warn_dot, alignment=Qt.AlignTop)
        warn_row.addWidget(warn_text, 1)
        success_layout.addSpacing(16)
        success_layout.addLayout(warn_row)

        # 使用提示:WebChat 默认展示 thinking,新手会困惑
        # 用极轻的"提示" prefix + 静音灰文字,代替彩色蓝色卡片
        self.thinking_hint = QLabel(
            "提示  打开 WebChat 后,可点击聊天界面右上角的脑图图标关闭工具调用过程,只看 OpenClaw 的最终回复。"
        )
        self.thinking_hint.setWordWrap(True)
        self.thinking_hint.setStyleSheet("color: #64748B; font-size: 12px;")
        success_layout.addSpacing(12)
        success_layout.addWidget(self.thinking_hint)

        layout.addSpacing(20)
        layout.addWidget(self.success_frame)

        # ── 错误卡片(浅红描边) ─────────────────────────
        # "启动失败"是 error 语义,色板与全局 dangerButton (#B91C1C) 对齐;
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
        self.error_title = QLabel("启动失败")
        self.error_title.setStyleSheet("color: #B91C1C; font-size: 13px; font-weight: 600;")
        self.error_label = QLabel("")
        self.error_label.setWordWrap(True)
        self.error_label.setStyleSheet("color: #B91C1C; font-size: 12px;")
        # 之前这里还有一个 error_detail_label,展示 result.log_lines[-20:],
        # 跟下方"详细日志"面板内容完全重复。已去掉,保留单一详细日志来源。
        error_layout.addWidget(self.error_title)
        error_layout.addWidget(self.error_label)
        layout.addWidget(self.error_frame)

        # ── 详细日志(可折叠) ────────────────────────────
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
        # QTextEdit 是富文本路径,Gateway 启动慢/健康检查重试时日志可能突发,
        # 主线程槽函数被堆满会触发 Windows"程序无响应"弹窗。
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

        self.scroll_area.setWidget(content_widget)
        main_layout.addWidget(self.scroll_area, 1)

        # ── 底部按钮栏 ────────────────────────────────────
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

        self.retry_button = QPushButton("重试")
        self.retry_button.setFixedHeight(36)
        self.retry_button.clicked.connect(self.retry_clicked.emit)
        self.retry_button.hide()

        self.finish_button = QPushButton("完成")
        self.finish_button.setFixedHeight(36)
        self.finish_button.setObjectName("primaryButton")
        self.finish_button.clicked.connect(self._on_finish_clicked)
        self.finish_button.hide()

        button_layout.addWidget(self.retry_button)
        button_layout.addWidget(self.finish_button)

        main_layout.addWidget(button_bar)

        # 回车推进:成功页打开 WebChat,失败页重试,启动中(任何主按钮都不可见)无操作。
        # 注意 open_webchat_btn 启动后有 8 秒倒计时禁用,期间回车不会误触发。
        for seq in (QKeySequence(Qt.Key_Return), QKeySequence(Qt.Key_Enter)):
            sc = QShortcut(seq, self)
            sc.setContext(Qt.WidgetWithChildrenShortcut)
            sc.activated.connect(self._on_enter_pressed)

    def _on_enter_pressed(self) -> None:
        for btn in (
            self.open_webchat_btn,
            self.retry_button,
            self.finish_button,
        ):
            if btn.isEnabled() and btn.isVisible():
                btn.click()
                return

    def _toggle_log(self) -> None:
        if self.log_frame.isVisible():
            self.log_frame.hide()
            self.toggle_log_btn.setText("显示详细日志")
        else:
            self.log_frame.show()
            self.toggle_log_btn.setText("隐藏详细日志")

    def _copy_url(self) -> None:
        url = self.url_input.text()
        if url:
            clipboard = QApplication.clipboard()
            clipboard.setText(url)
            self.copy_button.setText("已复制!")

    def add_log_line(self, line: str) -> None:
        # appendPlainText 是 QPlainTextEdit 的纯文本快路径,比 QTextEdit.append 快一个数量级
        self.log_text.appendPlainText(line)
        scrollbar = self.log_text.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    def start_startup(self) -> None:
        """重置并进入启动中状态:恢复步骤显示、进度条、防火墙提示(Windows),
        隐藏成功/错误区域,重置日志。"""
        # 清除上次失败留下的守卫标记,允许本次启动重新触发失败 UI
        self._failed_step_set = False
        self.status_label.setText("正在启动网关服务...")
        self.status_label.setStyleSheet(
            "color: #64748B; font-size: 13px; background: transparent; border: none;"
        )

        self.steps_frame.show()
        self.progress_bar.show()
        if is_windows():
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

        self.back_button.show()
        self.retry_button.hide()
        self.finish_button.hide()

    def update_progress(self, progress: ConfigProgress) -> None:
        """根据后台线程发射的 ConfigProgress 更新进度条、任务文本和步骤状态。"""
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
            # 守卫:同一次启动期间多次收到 FAILED 进度时,只触发一次失败 UI,
            # 否则 set_failed 会被反复调用,且按钮状态可能被中间进度覆盖。
            if not getattr(self, '_failed_step_set', False):
                self.step_gateway.set_failed()
                self._failed_step_set = True

    def startup_success(self, result: ConfigResult) -> None:
        """启动成功回调:更新状态文本、隐藏进行中区域、展示成功卡片,
        并启动倒计时防抖后启用「打开 WebChat」按钮。"""
        self.status_label.setText("网关服务已启动")
        self.status_label.setStyleSheet(
            "color: #15803D; font-size: 13px; font-weight: 600; "
            "background: transparent; border: none;"
        )

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
            self.browser_hint.setText("点击按钮在浏览器中打开。")

        self.error_frame.hide()

        self.back_button.hide()
        self.retry_button.hide()
        self.finish_button.show()

        # 自动滚动到底部，确保按钮可见
        QTimer.singleShot(100, lambda: self.scroll_area.verticalScrollBar().setValue(
            self.scroll_area.verticalScrollBar().maximum()
        ))

        # 启动倒计时，等待连接稳定后再允许打开 WebChat
        self._start_countdown()

    def startup_failed(self, result: ConfigResult) -> None:
        """启动失败回调:展示错误卡片和日志摘要,显示「返回」「重试」按钮。"""
        self.status_label.setText("启动失败")
        self.status_label.setStyleSheet(
            "color: #B91C1C; font-size: 13px; font-weight: 600; "
            "background: transparent; border: none;"
        )

        error_text = result.error_message or "服务启动失败"
        self.error_label.setText(error_text)

        # 失败时直接展开下方详细日志,免去用户多点一次"显示详细日志"
        if result.log_lines:
            self.log_frame.show()
            self.toggle_log_btn.setText("隐藏详细日志 ▲")

        self.error_frame.show()
        self.success_frame.hide()

        self.back_button.show()
        self.retry_button.show()
        self.finish_button.hide()

    def _start_countdown(self) -> None:
        """启动 8 秒倒计时，等待网关连接稳定后再启用「打开 WebChat」按钮。

        设计原因：Gateway 进程启动后需要数秒完成初始化并注册路由，
        若用户立即点击打开浏览器，可能遇到 502/连接拒绝，产生「启动失败」的误判。
        倒计时期间按钮禁用，并以文本提示安抚用户。
        """
        self._countdown_value = 8
        self.open_webchat_btn.setEnabled(False)
        self.countdown_label.setText(f"等待连接稳定... {self._countdown_value} 秒")
        self.countdown_label.show()

        self._countdown_timer = QTimer(self)
        self._countdown_timer.timeout.connect(self._update_countdown)
        self._countdown_timer.start(1000)  # 每秒更新一次

    def _update_countdown(self) -> None:
        """更新倒计时文本；归零后停止计时器并启用「打开 WebChat」按钮。"""
        self._countdown_value -= 1
        if self._countdown_value > 0:
            self.countdown_label.setText(
                f"等待连接稳定... {self._countdown_value} 秒"
            )
        else:
            self._countdown_timer.stop()
            self.countdown_label.hide()
            self.open_webchat_btn.setEnabled(True)

    def reset(self) -> None:
        """重置页面到初始状态，停止可能运行中的倒计时。"""
        # 同 start_startup,reset 也要清失败守卫,避免下一次启动被旧标记吞掉
        self._failed_step_set = False
        self.step_gateway.set_pending()
        self.step_health.set_pending()

        self.progress_bar.setValue(0)
        self.task_label.setText("")

        self.log_text.clear()
        self.log_frame.hide()
        self.toggle_log_btn.setText("显示详细日志 ▼")

        self.success_frame.hide()
        self.error_frame.hide()

        # 重置倒计时状态
        if hasattr(self, '_countdown_timer') and self._countdown_timer:
            self._countdown_timer.stop()
        self.countdown_label.hide()
        self.open_webchat_btn.setEnabled(False)

        self.back_button.show()
        self.retry_button.hide()
        self.finish_button.hide()

    def _on_finish_clicked(self) -> None:
        """完成按钮点击槽：直接发射信号退出。

        快捷方式创建职责已由安装器的 InstallDonePage 承担，
        启动器只负责日常启动和模型配置。
        """
        self.finish_clicked.emit()
