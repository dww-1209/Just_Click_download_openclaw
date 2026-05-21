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

from src.models.install import InstallStatus, InstallStage, InstallProgress, InstallResult
from src.models.constants import is_windows
from src.models.utils import redact_home_path


class InstallingPage(QWidget):
    """安装进度页面（US-04）—— 在线下载、构建与安装 OpenClaw。

    职责：展示 Node.js 安装、Git 克隆、pnpm install/build 等长耗时任务的实时进度。
    页面通过 QThread 后台 worker 接收信号，更新进度条、状态文本和日志区域。
    同时提供结构化错误分类展示，将技术错误翻译为面向非技术用户的友好提示。
    """

    retry_clicked = Signal()   # 安装失败后用户点击「重试」，触发重新执行安装流程
    next_clicked = Signal()    # 安装成功后用户点击「完成」，触发进入配置页
    back_clicked = Signal()    # 用户点击「返回」，可回到环境检测页（安装未开始时可用）
    cancel_clicked = Signal()  # 用户点击「退出」，触发关闭安装器

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._setup_ui()

    def _setup_ui(self) -> None:
        from PySide6.QtWidgets import QScrollArea, QFrame

        # 主布局:上部可滚动内容区,下部固定按钮栏(带 1px 顶部分割线)
        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(0)
        main_layout.setContentsMargins(0, 0, 0, 0)

        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameShape(QScrollArea.NoFrame)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll_area.setStyleSheet("QScrollArea { background-color: transparent; border: none; }")

        # 内容区透明:必须用 QWidget#锚定 选择器,见 show_uninstall_progress.py:39 同样修复
        content_widget = QWidget()
        content_widget.setObjectName("installProgressContent")
        content_widget.setStyleSheet("QWidget#installProgressContent { background-color: transparent; }")
        layout = QVBoxLayout(content_widget)
        layout.setContentsMargins(56, 40, 56, 32)
        layout.setSpacing(0)

        # ── 标题 ───────────────────────────────────────────────
        title = QLabel("安装中")
        title.setStyleSheet(
            "color: #0F172A; font-size: 28px; font-weight: 700; "
            "letter-spacing: -0.5px; background: transparent; border: none;"
        )
        layout.addWidget(title)

        # 状态文本(动态:下载/安装/配置/完成)
        self.status_label = QLabel("准备安装...")
        self.status_label.setStyleSheet(
            "color: #64748B; font-size: 13px; background: transparent; border: none;"
        )
        layout.addSpacing(8)
        layout.addWidget(self.status_label)

        # 子任务细粒度文本(如"正在克隆仓库...")
        self.task_label = QLabel("")
        self.task_label.setStyleSheet(
            "color: #94A3B8; font-size: 12px; background: transparent; border: none;"
        )
        self.task_label.setWordWrap(True)
        layout.addSpacing(4)
        layout.addWidget(self.task_label)

        # ── 耗时预期 ─────────────────────────────────────────
        # 用静音灰小字提示,不用饱和橙色块——预期信息不需要警示色
        self.time_hint_label = QLabel("预计耗时 10–20 分钟,请保持网络畅通。")
        self.time_hint_label.setStyleSheet(
            "color: #94A3B8; font-size: 12px; background: transparent; border: none;"
        )
        self.time_hint_label.setWordWrap(True)
        layout.addSpacing(20)
        layout.addWidget(self.time_hint_label)

        # ── Windows 安全授权提示 ────────────────────────────
        # 用 1px 描边 + 浅琥珀背景的 callout 卡片,取代原大色块
        # 仅在 Windows 上显示,因为 SmartScreen / UAC 是 Windows 特有
        self.security_hint = QLabel(
            "Windows 可能弹出安全授权窗口,请点击「允许」或「是」,否则安装无法继续。"
        )
        self.security_hint.setWordWrap(True)
        self.security_hint.setStyleSheet(
            "background-color: #FFFBEB; color: #92400E; border: 1px solid #FDE68A; "
            "border-radius: 6px; padding: 10px 14px; font-size: 12px; "
            "font-weight: 500;"
        )
        if not is_windows():
            self.security_hint.hide()
        else:
            layout.addSpacing(12)
            layout.addWidget(self.security_hint)

        # ── 进度条 ──────────────────────────────────────────
        # 不显示百分比文字,把数字放到状态标签里更稳
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(False)
        layout.addSpacing(24)
        layout.addWidget(self.progress_bar)

        # ── 日志区域 ────────────────────────────────────────
        # 小节标签 + 黑色日志框,黑色框已在全局 QSS #logArea 中定义
        log_section_label = QLabel("安装日志")
        log_section_label.setStyleSheet(
            "color: #64748B; font-size: 11px; font-weight: 600; "
            "letter-spacing: 1.5px; background: transparent; border: none;"
        )
        layout.addSpacing(28)
        layout.addWidget(log_section_label)
        layout.addSpacing(8)

        self.log_text = QPlainTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setMaximumBlockCount(100)
        self.log_text.setMinimumHeight(160)
        self.log_text.setObjectName("logArea")
        layout.addWidget(self.log_text, 1)

        # 安装失败时展示友好错误提示(浅琥珀 callout),平时隐藏
        self.hint_label = QLabel("")
        self.hint_label.setWordWrap(True)
        self.hint_label.hide()
        layout.addSpacing(12)
        layout.addWidget(self.hint_label)

        scroll_area.setWidget(content_widget)
        main_layout.addWidget(scroll_area, 1)

        # ── 底部按钮栏 ──────────────────────────────────────
        # 按钮状态机:
        #   - 安装前/安装中:back 可用,cancel 显示「退出」,retry/next 隐藏
        #   - 安装成功:显示 next(完成),隐藏 cancel/retry
        #   - 安装失败:显示 retry(重试),隐藏 next
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

        self.cancel_button = QPushButton("退出")
        self.cancel_button.setFixedHeight(36)
        self.cancel_button.clicked.connect(self._on_cancel_clicked)

        self.retry_button = QPushButton("重试")
        self.retry_button.setFixedHeight(36)
        self.retry_button.clicked.connect(self.retry_clicked.emit)
        self.retry_button.hide()

        self.next_button = QPushButton("完成")
        self.next_button.setFixedHeight(36)
        self.next_button.setObjectName("primaryButton")
        self.next_button.clicked.connect(self.next_clicked.emit)
        self.next_button.setEnabled(False)
        self.next_button.hide()

        button_layout.addWidget(self.cancel_button)
        button_layout.addWidget(self.retry_button)
        button_layout.addWidget(self.next_button)

        main_layout.addWidget(button_bar)

    def _on_cancel_clicked(self) -> None:
        """处理退出/取消点击"""
        self.cancel_clicked.emit()

    def start_installing(self) -> None:
        """开始安装 - 重置界面状态"""
        self.status_label.setText("正在安装...")
        self.status_label.setStyleSheet(
            "color: #64748B; font-size: 13px; background: transparent; border: none;"
        )
        self.task_label.setText("准备执行安装命令...")
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.log_text.clear()
        self.hint_label.hide()

        # 按钮状态 - 安装过程中禁用所有按钮，防止用户误操作导致状态混乱
        self.back_button.setEnabled(False)
        self.cancel_button.setText("退出")
        self.cancel_button.setEnabled(False)  # 安装中禁止退出，避免子进程孤儿化
        self.retry_button.hide()
        self.next_button.hide()

    def update_progress(self, progress: InstallProgress) -> None:
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

    def _append_log(self, message: str) -> None:
        """添加日志并自动滚动到底部"""
        self.log_text.appendPlainText(message)
        scrollbar = self.log_text.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    def add_log_line(self, log_line: str) -> None:
        """添加日志行"""
        self._append_log(log_line)

    def install_success(self, result: InstallResult) -> None:
        """安装成功"""
        self.status_label.setText("安装完成")
        self.status_label.setStyleSheet(
            "color: #15803D; font-size: 13px; font-weight: 600; "
            "background: transparent; border: none;"
        )
        self.task_label.setText("OpenClaw 已准备就绪,点击「下一步」继续配置。")
        self.progress_bar.setValue(100)

        self._append_log(f"安装成功！耗时: {result.duration_seconds:.1f}秒")

        # 按钮状态 - 安装成功，显示下一步按钮，等待用户点击
        self.back_button.setEnabled(True)
        self.cancel_button.setEnabled(True)
        self.cancel_button.hide()
        self.retry_button.hide()
        self.next_button.show()
        self.next_button.setEnabled(True)

    def install_failed(self, result: InstallResult) -> None:
        """安装失败

        改进后的错误显示逻辑：
        1. 优先使用 result.error_detail 中的结构化错误信息（分类、用户提示、建议）
        2. 如果没有 error_detail，回退到旧的关键词匹配逻辑
        3. 在日志区域追加完整的原始错误信息，方便高级用户排查
        """
        from src.models.user_messages import UserMessageHelper

        self.status_label.setText("安装失败")
        self.status_label.setStyleSheet(
            "color: #B91C1C; font-size: 13px; font-weight: 600; "
            "background: transparent; border: none;"
        )
        self.task_label.setText(result.message)

        friendly_msg = ""

        # error_message 也常被拼到 details/日志中,先过一遍脱敏再用
        safe_error_message = redact_home_path(result.error_message or "")

        # 优先使用结构化的 error_detail
        if result.error_detail is not None:
            friendly_msg = UserMessageHelper.get_friendly_message_by_category(
                category=result.error_detail.category,
                user_message=result.error_detail.user_message,
                suggestion=result.error_detail.suggestion,
                details=safe_error_message,
            )
            # 在日志中追加完整的诊断信息
            # 命令、上下文、原始错误都可能携带绝对路径(C:\Users\<name>...),
            # 截屏分享到 issue/客服时会暴露用户名,统一过 redact_home_path 把 home 替换为 ~。
            self._append_log("=" * 40)
            self._append_log("[诊断信息]")
            self._append_log(f"错误分类: {result.error_detail.category.value}")
            self._append_log(f"发生阶段: {result.error_detail.stage or '未知'}")
            self._append_log(f"上下文: {redact_home_path(result.error_detail.context) or '无'}")
            if result.error_detail.command:
                self._append_log(f"触发命令: {redact_home_path(result.error_detail.command)[:200]}")
            if result.error_detail.returncode is not None:
                self._append_log(f"返回码: {result.error_detail.returncode}")
            self._append_log("-" * 40)
            self._append_log("[原始错误输出]")
            raw = redact_home_path(result.error_detail.raw_error)
            if len(raw) > 3000:
                self._append_log(raw[:3000])
                self._append_log(f"... (后续截断，共 {len(raw)} 字符，请查看完整日志文件)")
            else:
                self._append_log(raw)
            self._append_log("=" * 40)
        elif result.error_message:
            # 回退：根据错误内容关键词判断错误类型
            error_lower = result.error_message.lower()
            if "网络" in error_lower or "download" in error_lower or "curl" in error_lower:
                friendly_msg = UserMessageHelper.get_friendly_error_message("download", safe_error_message)
            elif "权限" in error_lower or "permission" in error_lower or "access" in error_lower:
                friendly_msg = UserMessageHelper.get_friendly_error_message("permission", safe_error_message)
            elif "磁盘" in error_lower or "space" in error_lower:
                friendly_msg = UserMessageHelper.get_friendly_error_message("disk_space", safe_error_message)
            else:
                friendly_msg = UserMessageHelper.get_friendly_error_message("install", safe_error_message)

        if friendly_msg:
            self.hint_label.setText(friendly_msg)
            # 浅琥珀 callout:1px 描边 + 适度 padding,不再用饱和黄底
            self.hint_label.setStyleSheet(
                "color: #92400E; background-color: #FFFBEB; "
                "border: 1px solid #FDE68A; border-radius: 6px; "
                "padding: 10px 14px; font-size: 12px;"
            )
            self.hint_label.show()

        self._append_log(f"安装失败: {safe_error_message}")

        # 按钮状态
        self.back_button.setEnabled(True)
        self.cancel_button.hide()
        self.retry_button.show()
        self.next_button.hide()

    def install_cancelled(self) -> None:
        """安装已取消"""
        self.status_label.setText("安装已取消")
        self.status_label.setStyleSheet(
            "color: #92400E; font-size: 13px; font-weight: 600; "
            "background: transparent; border: none;"
        )
        self.task_label.setText("用户取消了安装")
        self._append_log("安装已取消")

        # 按钮状态
        self.back_button.setEnabled(True)
        self.cancel_button.setText("退出")
        self.retry_button.show()
        self.next_button.hide()

    def reset(self) -> None:
        """重置页面状态"""
        self.status_label.setText("准备安装...")
        self.status_label.setStyleSheet(
            "color: #64748B; font-size: 13px; background: transparent; border: none;"
        )
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
