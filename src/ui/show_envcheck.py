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
from PySide6.QtGui import QFont, QKeySequence, QShortcut

from src.models.env_check import (
    CheckStatus,
    OpenClawStatus,
    EnvCheckResult,
    BrowserResult,
)


class CheckItemWidget(QFrame):
    """单个检测项显示组件。

    职责:将「检测项名称 + 状态点 + 状态文本」封装为一行可复用的检测条目。
    状态用 6px 圆点(green / amber / red)+ 文本,取代原来的彩色 pill 标签——
    pill 在企业级 UI 里偏"应用商店"风格,小圆点更克制、信息密度更高,
    且和现代 IDE/Dashboard(VSCode / Linear / Stripe)的状态指示一致。
    """

    def __init__(self, name: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.name = name
        self._setup_ui()

    def _setup_ui(self) -> None:
        # 单行布局:状态点 (6×6) → 检测项名 → 弹性间距 → 状态文本
        # 整行 1px 底边分隔,行高 36,密度高于原来的 padding 5px
        self.setStyleSheet(
            "QFrame { border-bottom: 1px solid #E2E8F0; }"
            "QFrame QLabel { background: transparent; border: none; }"
        )

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 10, 0, 10)
        layout.setSpacing(12)

        # 6px 圆点,默认 pending(灰)
        self.dot = QLabel()
        self.dot.setFixedSize(8, 8)
        self.dot.setStyleSheet(
            "background-color: #CBD5E1; border-radius: 4px; border: none;"
        )

        self.name_label = QLabel(self.name)
        self.name_label.setStyleSheet("color: #0F172A; font-size: 13px; font-weight: 500;")
        self.name_label.setMinimumWidth(140)

        self.status_label = QLabel("检测中")
        self.status_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.status_label.setStyleSheet("color: #94A3B8; font-size: 13px;")

        layout.addWidget(self.dot)
        layout.addWidget(self.name_label)
        layout.addStretch(1)
        layout.addWidget(self.status_label)

    def set_status(self, status: CheckStatus, message: str = "") -> None:
        """根据检测结果更新状态点颜色和文本。

        颜色用降饱和版本:
        - OK   #16A34A(slate-green-600)
        - WARN #D97706(amber-600)
        - FAIL #DC2626(red-600)
        都比 Material 默认色更克制,同时保留足够辨识度。
        """
        if status == CheckStatus.OK:
            self.dot.setStyleSheet(
                "background-color: #16A34A; border-radius: 4px; border: none;"
            )
            self.status_label.setStyleSheet("color: #475569; font-size: 13px;")
            self.status_label.setText(message or "通过")
        elif status == CheckStatus.WARNING:
            self.dot.setStyleSheet(
                "background-color: #D97706; border-radius: 4px; border: none;"
            )
            self.status_label.setStyleSheet("color: #92400E; font-size: 13px;")
            self.status_label.setText(message or "警告")
        else:
            self.dot.setStyleSheet(
                "background-color: #DC2626; border-radius: 4px; border: none;"
            )
            self.status_label.setStyleSheet("color: #991B1B; font-size: 13px;")
            self.status_label.setText(message or "失败")


class OpenClawInstalledWidget(QWidget):
    """OpenClaw 已安装选项组件(US-02 分支场景)。

    职责:当环境检测到 OpenClaw 已安装时,代替常规的「下一步」按钮,
    向用户提供 3 种快捷操作。该组件默认隐藏,仅在检测到已安装状态后显示。

    设计调整:三个按钮并排时只有一个是主操作(快速启动),其余两个用次要按钮样式,
    避免三个并列主按钮造成的"全部都很重要"的视觉噪声 — 这是 AI 味的典型来源。
    """

    quick_start_clicked = Signal()       # 用户点击「快速启动」——直接拉起已有 Gateway
    provider_config_clicked = Signal()   # 用户点击「配置模型」——跳转到 Provider 配置页
    reinstall_clicked = Signal()         # 用户点击「重新下载」——删除旧版本后重新执行 US-04 安装流程

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._setup_ui()

    def _setup_ui(self) -> None:
        # 卡片背景改为 slate-50 + 1px 描边,取代原来的浅绿底色
        # 原浅绿 #e8f4e8 是"成功/积极"的暗示,但这里实际是中性提示(检测到状态),
        # 不应该用情感色;改用静音的灰色卡片
        self.setObjectName("openclawInstalledWidget")
        self.setStyleSheet(
            "QWidget#openclawInstalledWidget { "
            "background-color: #F8FAFC; border: 1px solid #E2E8F0; border-radius: 8px; }"
            "QWidget#openclawInstalledWidget QLabel { background: transparent; border: none; }"
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(4)

        title = QLabel("检测到 OpenClaw 已安装")
        title.setStyleSheet("color: #0F172A; font-size: 14px; font-weight: 600;")

        desc = QLabel("选择以下操作之一继续:")
        desc.setStyleSheet("color: #64748B; font-size: 12px;")

        # 按钮行:三个按钮并排居中
        # 视觉层级:快速启动(主)> 配置模型(次)> 重新下载(次)
        # 注意:不能让 stretch 把 quick_start 孤立到右侧,否则用户视线扫左边两个按钮就停了
        # 改用「stretch + 三按钮 + stretch」居中布局,主操作放第一位,符合首要操作打头的认知
        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)
        btn_row.setContentsMargins(0, 12, 0, 0)

        self.quick_start_btn = QPushButton("快速启动")
        self.quick_start_btn.setMinimumHeight(36)
        self.quick_start_btn.setMinimumWidth(112)
        self.quick_start_btn.setObjectName("primaryButton")
        self.quick_start_btn.clicked.connect(self.quick_start_clicked.emit)

        self.provider_config_btn = QPushButton("配置模型")
        self.provider_config_btn.setMinimumHeight(36)
        self.provider_config_btn.setMinimumWidth(112)
        self.provider_config_btn.clicked.connect(self.provider_config_clicked.emit)

        self.reinstall_btn = QPushButton("重新下载")
        self.reinstall_btn.setMinimumHeight(36)
        self.reinstall_btn.setMinimumWidth(112)
        self.reinstall_btn.clicked.connect(self.reinstall_clicked.emit)

        btn_row.addStretch(1)
        btn_row.addWidget(self.quick_start_btn)
        btn_row.addWidget(self.provider_config_btn)
        btn_row.addWidget(self.reinstall_btn)
        btn_row.addStretch(1)

        layout.addWidget(title)
        layout.addWidget(desc)
        layout.addLayout(btn_row)


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
    openclaw_provider_config = Signal()  # 已安装场景：用户选择「配置模型」
    openclaw_reinstall = Signal()        # 已安装场景：用户选择「重新下载」

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._setup_ui()
        self._hide_openclaw_widget()

    def _setup_ui(self) -> None:
        from PySide6.QtWidgets import QScrollArea

        # 主布局:上部可滚动内容区,下部固定按钮栏(底部带 1px 分割线)。
        # 全局滚动条样式已在 installer_window 全局 QSS 中定义,这里不再单独设置。
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
        content_widget.setObjectName("envCheckContent")
        content_widget.setStyleSheet("QWidget#envCheckContent { background-color: transparent; }")
        layout = QVBoxLayout(content_widget)
        # 与 welcome 页一致的 56px 阅读宽度
        layout.setContentsMargins(56, 40, 56, 32)
        layout.setSpacing(0)

        # ── 标题区 ─────────────────────────────────────────────
        # 大号左对齐主标题 + 静音灰副文案,与 welcome 页保持一致的视觉节奏
        title = QLabel("环境检测")
        title.setStyleSheet(
            "color: #0F172A; font-size: 28px; font-weight: 700; "
            "letter-spacing: -0.5px; background: transparent; border: none;"
        )

        self.status_label = QLabel("正在检测您的系统环境...")
        self.status_label.setStyleSheet(
            "color: #64748B; font-size: 13px; background: transparent; border: none;"
        )
        self.status_label.setWordWrap(True)

        layout.addWidget(title)
        layout.addSpacing(8)
        layout.addWidget(self.status_label)
        layout.addSpacing(32)

        # ── 检测项小节 ─────────────────────────────────────────
        section_label = QLabel("检查项")
        section_label.setStyleSheet(
            "color: #64748B; font-size: 11px; font-weight: 600; "
            "letter-spacing: 1.5px; background: transparent; border: none;"
        )
        layout.addWidget(section_label)
        layout.addSpacing(8)

        # 顶部 1px 边,与每行的底部 1px 边形成完整的边框列表
        top_border = QFrame()
        top_border.setStyleSheet("background-color: #E2E8F0; max-height: 1px; min-height: 1px;")
        layout.addWidget(top_border)

        self.os_item = CheckItemWidget("操作系统")
        self.disk_item = CheckItemWidget("磁盘空间")
        self.permission_item = CheckItemWidget("权限状态")
        self.browser_item = CheckItemWidget("浏览器支持")
        self.openclaw_item = CheckItemWidget("OpenClaw 安装")

        layout.addWidget(self.os_item)
        layout.addWidget(self.disk_item)
        layout.addWidget(self.permission_item)
        layout.addWidget(self.browser_item)
        layout.addWidget(self.openclaw_item)

        # ── 进度条 + 提示 ────────────────────────────────────
        layout.addSpacing(20)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 0)  # 不确定模式
        self.progress_bar.setTextVisible(False)
        layout.addWidget(self.progress_bar)

        layout.addSpacing(20)

        # OpenClaw 已安装时显示的快捷操作面板
        self.openclaw_widget = OpenClawInstalledWidget()
        self.openclaw_widget.quick_start_clicked.connect(self.openclaw_quick_start.emit)
        self.openclaw_widget.provider_config_clicked.connect(self.openclaw_provider_config.emit)
        self.openclaw_widget.reinstall_clicked.connect(self.openclaw_reinstall.emit)
        layout.addWidget(self.openclaw_widget)

        layout.addSpacing(12)

        # 提示文本 — 不再用大色块,只用文字颜色区分通过/失败
        self.hint_label = QLabel("")
        self.hint_label.setWordWrap(True)
        self.hint_label.setStyleSheet(
            "color: #64748B; font-size: 12px; background: transparent; border: none;"
        )
        layout.addWidget(self.hint_label)

        layout.addStretch(1)

        scroll_area.setWidget(content_widget)
        main_layout.addWidget(scroll_area, 1)

        # ── 底部按钮栏 ──────────────────────────────────────────
        # 状态机设计:
        #   - 检测中:next_button 禁用,retry_button 隐藏
        #   - 检测通过(全新安装):next_button 启用,retry_button 隐藏
        #   - 检测失败:next_button 禁用,retry_button 显示
        #   - 已安装:next_button 隐藏,由 OpenClawInstalledWidget 接管操作
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

        self.next_button = QPushButton("下一步")
        self.next_button.setFixedHeight(36)
        self.next_button.setObjectName("primaryButton")
        self.next_button.clicked.connect(self.next_clicked.emit)
        self.next_button.setEnabled(False)

        button_layout.addWidget(self.retry_button)
        button_layout.addWidget(self.next_button)

        main_layout.addWidget(button_bar)

        # 回车推进:优先级 next_button > retry_button > quick_start_btn
        # 检测中两者都禁用,回车不会误触发。WidgetWithChildrenShortcut
        # 限定快捷键只在本页激活时生效。
        for seq in (QKeySequence(Qt.Key_Return), QKeySequence(Qt.Key_Enter)):
            sc = QShortcut(seq, self)
            sc.setContext(Qt.WidgetWithChildrenShortcut)
            sc.activated.connect(self._on_enter_pressed)

    def _on_enter_pressed(self) -> None:
        """按钮可见性按当前页状态变化,这里依次尝试,首个可点的就触发。
        已安装分支的「快速启动」在 self.openclaw_widget 子组件里,需要通过
        组件引用访问;next/retry 在本类持有。"""
        candidates = [self.next_button, self.retry_button]
        if self.openclaw_widget.isVisible():
            candidates.append(self.openclaw_widget.quick_start_btn)
        for btn in candidates:
            if btn.isEnabled() and btn.isVisible():
                btn.click()
                return

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
        os_name = {"windows": "Windows", "macos": "macOS"}.get(os_type, os_type)
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
            # 通过提示:仅文字 + 静音灰,不用大色块或 emoji
            self.hint_label.setText("系统环境符合要求,可以继续。")
            self.hint_label.setStyleSheet(
                "color: #475569; font-size: 12px; background: transparent; border: none;"
            )
        else:
            self.next_button.setEnabled(False)
            self.retry_button.show()
            # 失败提示:降饱和红文字,无 emoji,无背景色
            self.hint_label.setText("环境检测未通过,请根据上方提示处理后重试。")
            self.hint_label.setStyleSheet(
                "color: #B91C1C; font-size: 12px; background: transparent; border: none;"
            )

    def reset(self) -> None:
        self.progress_bar.setRange(0, 0)
        self.next_button.setEnabled(False)
        self.retry_button.hide()
        self._hide_openclaw_widget()
        self.hint_label.setText("")
