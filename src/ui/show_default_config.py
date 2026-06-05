"""US-05 配置页面 —— 执行 OpenClaw 的初始化配置（onboarding）+ 安装完成页。

职责：在安装完成后，调用 openclaw onboard --non-interactive 自动生成默认配置文件，
并展示配置步骤的进度与结果。支持「重试」「手动配置」「下一步」三种用户分支。

配置成功后点击「下一步」进入安装完成页（InstallDonePage），
告知用户安装器使命结束、可安全删除，提供「打开启动器」按钮。
Windows 额外提供桌面/开始菜单快捷方式创建选项，
快捷方式指向启动器而非安装器——安装器装完即可删除。
"""

import os
import subprocess
from pathlib import Path

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
    QCheckBox,
)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont, QKeySequence, QShortcut

from src.models.config import ConfigStatus, ConfigProgress, ConfigResult
from src.models.constants import is_windows, is_macos


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


# ═══════════════════════════════════════════════════════════════════
# 安装完成页 — 安装器流程的终点
# ═══════════════════════════════════════════════════════════════════


def _find_launcher() -> str | None:
    """在安装器同级目录或常见位置查找启动器

    开发模式：dist/ 目录下找 .app（macOS）/ .exe（Windows）
    打包模式：sys.executable 同级目录找
    """
    import sys
    candidates: list[Path] = []

    if getattr(sys, 'frozen', False):
        # 打包后：sys.executable 指向当前程序（安装器），
        # 启动器在同一目录下
        exe_dir = Path(sys.executable).parent
        # macOS: .app/Contents/MacOS/<name> → 回到 dist/ 层级
        if is_macos() and exe_dir.name == "MacOS":
            app_dir = exe_dir.parent.parent  # .app
            dist_dir = app_dir.parent
            candidates.append(dist_dir)
            candidates.append(exe_dir)  # 万一就在同目录
        else:
            candidates.append(exe_dir)
    else:
        # 开发模式：项目根下的 dist/
        candidates.append(Path(__file__).parent.parent.parent / "dist")

    # 常见放置位置
    home = Path.home()
    candidates.append(home / "Desktop")
    candidates.append(home / "Applications")

    # 按平台匹配文件名模式
    if is_macos():
        name_prefix = "OpenClaw启动器"
        ext = ".app"
    else:
        name_prefix = "OpenClaw启动器"
        ext = ".exe"

    for base in candidates:
        if not base.is_dir():
            continue
        for entry in base.iterdir():
            if entry.name.startswith(name_prefix) and entry.name.endswith(ext):
                return str(entry)

    return None


class InstallDonePage(QWidget):
    """安装完成页面

    展示安装成功摘要，提示用户可删除安装器，
    提供按钮打开启动器或关闭安装器。
    Windows 额外提供快捷方式创建选项。
    """

    finish_clicked = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._launcher_path: str | None = None
        self._chk_desktop: QCheckBox | None = None
        self._chk_start_menu: QCheckBox | None = None
        self._setup_ui()

    def _setup_ui(self) -> None:
        """构建完成页 UI：标题 + 说明 + 快捷方式选项(Windows) + 按钮组"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(56, 60, 56, 40)
        layout.setSpacing(0)

        # ── 成功图标 ──
        check_row = QHBoxLayout()
        check_row.setContentsMargins(0, 0, 0, 0)
        check_row.addStretch(1)
        check = QLabel("✓")
        check.setAlignment(Qt.AlignCenter)
        check.setFixedSize(64, 64)
        check.setStyleSheet(
            "background-color: #16A34A; color: white; "
            "border-radius: 32px; font-size: 32px; font-weight: 700;"
        )
        check_row.addWidget(check)
        check_row.addStretch(1)
        layout.addLayout(check_row)

        # ── 标题 ──
        layout.addSpacing(24)
        title = QLabel("安装完成")
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet(
            "color: #0F172A; font-size: 28px; font-weight: 700; "
            "letter-spacing: -0.5px; background: transparent; border: none;"
        )
        layout.addWidget(title)

        # ── 说明文字 ──
        layout.addSpacing(16)

        desc_card = QFrame()
        desc_card.setObjectName("doneCard")
        desc_card.setStyleSheet(
            "QFrame#doneCard { background-color: #F8FAFC; border: 1px solid #E2E8F0; "
            "border-radius: 8px; }"
            "QFrame#doneCard QLabel { background: transparent; border: none; }"
        )
        desc_layout = QVBoxLayout(desc_card)
        desc_layout.setContentsMargins(20, 16, 20, 16)
        desc_layout.setSpacing(8)

        lines = [
            ("提示", "color: #475569; font-size: 11px; font-weight: 600; letter-spacing: 1.5px;"),
            ("OpenClaw 已成功安装到您的电脑。", "color: #0F172A; font-size: 13px;"),
            ("", ""),
            ("本安装器已完成使命，可以安全删除以释放磁盘空间。", "color: #64748B; font-size: 12px;"),
            ("日常使用请打开 <b>OpenClaw 启动器</b>，轻量且仅需 40MB。", "color: #64748B; font-size: 12px;"),
        ]
        for text, style in lines:
            if not text:
                continue
            label = QLabel(text)
            label.setWordWrap(True)
            label.setStyleSheet(style)
            label.setAlignment(Qt.AlignLeft)
            desc_layout.addWidget(label)

        layout.addWidget(desc_card)

        # ── Windows 快捷方式选项 ──
        # 快捷方式指向启动器而非安装器：安装器装完可删除
        if is_windows():
            layout.addSpacing(16)
            self._chk_desktop = QCheckBox("在桌面创建启动器快捷方式")
            self._chk_desktop.setChecked(True)
            self._chk_start_menu = QCheckBox("固定到开始菜单")
            self._chk_start_menu.setChecked(True)
            for chk in (self._chk_desktop, self._chk_start_menu):
                chk.setStyleSheet(
                    "QCheckBox { color: #475569; font-size: 12px; }"
                )
            layout.addWidget(self._chk_desktop)
            layout.addWidget(self._chk_start_menu)

        # ── 按钮组 ──
        layout.addSpacing(24)

        # 检测本地是否有启动器
        self._launcher_path = _find_launcher()
        if self._launcher_path:
            launcher_name = os.path.basename(self._launcher_path)
            if launcher_name.endswith(".app"):
                launcher_name = launcher_name.replace(".app", "")
            elif launcher_name.endswith(".exe"):
                launcher_name = launcher_name.replace(".exe", "")

            launcher_btn = QPushButton(f"打开 {launcher_name}")
            launcher_btn.setObjectName("primaryButton")
            launcher_btn.setCursor(Qt.PointingHandCursor)
            launcher_btn.setFixedHeight(44)
            launcher_btn.clicked.connect(self._on_open_launcher)
            launcher_btn_row = QHBoxLayout()
            launcher_btn_row.addStretch(1)
            launcher_btn_row.addWidget(launcher_btn)
            launcher_btn_row.addStretch(1)
            layout.addLayout(launcher_btn_row)
            layout.addSpacing(12)

        # 完成按钮
        finish_btn = QPushButton("完成" if self._launcher_path else "关闭安装器")
        finish_btn.setFixedHeight(36)
        finish_btn.setStyleSheet(
            "QPushButton { color: #64748B; font-size: 13px; border: 1px solid #E2E8F0; "
            "border-radius: 6px; background: white; }"
            "QPushButton:hover { background: #F1F5F9; color: #0F172A; }"
        )
        finish_btn.setCursor(Qt.PointingHandCursor)
        finish_btn.clicked.connect(self._on_finish_clicked)
        finish_btn_row = QHBoxLayout()
        finish_btn_row.addStretch(1)
        finish_btn_row.addWidget(finish_btn)
        finish_btn_row.addStretch(1)
        layout.addLayout(finish_btn_row)

        layout.addStretch(1)

    def _create_shortcuts_if_needed(self) -> None:
        """根据 checkbox 状态创建快捷方式(仅 Windows)

        快捷方式指向启动器,不是指向安装器。
        失败不阻塞——快捷方式不是核心功能,仅记日志。
        """
        if not is_windows():
            return
        if self._chk_desktop is None or self._chk_start_menu is None:
            return

        desktop_checked = self._chk_desktop.isChecked()
        start_menu_checked = self._chk_start_menu.isChecked()
        if not desktop_checked and not start_menu_checked:
            return

        # 快捷方式目标必须是启动器而非安装器
        from src.adapters.manage_shortcuts import create_shortcuts
        target = self._launcher_path  # 启动器 exe 路径
        create_shortcuts(desktop_checked, start_menu_checked, target=target)

    def _on_open_launcher(self) -> None:
        """尝试打开本地启动器,同时创建 Windows 快捷方式"""
        self._create_shortcuts_if_needed()

        if not self._launcher_path:
            return
        try:
            if is_macos():
                subprocess.Popen(
                    ["open", self._launcher_path],
                    start_new_session=True,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            elif is_windows():
                os.startfile(self._launcher_path)
        except (OSError, subprocess.SubprocessError):
            pass

    def _on_finish_clicked(self) -> None:
        """点击「完成」：创建快捷方式(Windows)，退出安装器"""
        self._create_shortcuts_if_needed()
        self.finish_clicked.emit()
