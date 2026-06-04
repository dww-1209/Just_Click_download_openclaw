"""Launcher 主窗口 — 极简启动器

职责：管理 QStackedWidget 的 3 页流程：
  页面 0: 首页 — 显示当前模型状态 + 启动按钮 + 配置入口
  页面 1: Provider 配置 — 管理 API Key 和模型
  页面 2: 启动 — 启动 Gateway → 健康检查 → 打开 WebChat

首页特性：
- 自动读取 ~/.openclaw/openclaw.json 检测模型配置状态
- 已配置：显示当前模型名(绿色标识),启动按钮为主操作
- 未配置：警告提示 + 配置模型按钮提升到主操作位置
"""

import json
import os
import sys
from pathlib import Path
from typing import Callable

_PROJECT_ROOT = Path(__file__).parent.parent.resolve()
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from PySide6.QtWidgets import (
    QApplication, QStackedWidget, QWidget, QMessageBox,
    QVBoxLayout, QLabel, QPushButton, QHBoxLayout,
)
from PySide6.QtCore import Qt, QTimer, QSize, Signal
from PySide6.QtGui import QIcon

from src.ui._theme import GLOBAL_QSS
from src.models.utils import find_app_icon_path
from src.ui.show_provider_config import ProviderConfigPage
from src.ui.show_startup import US06StartupPage
from src.contracts import IOpenClawManager, ISystemLauncher


OpenClawManagerFactory = Callable[[], IOpenClawManager]


# ═══════════════════════════════════════════════════════════════════
# 模型配置状态读取
# ═══════════════════════════════════════════════════════════════════

def _read_model_status() -> tuple[str | None, bool]:
    """读取当前 OpenClaw 的模型配置状态

    从 ~/.openclaw/openclaw.json 中提取:
    - agents.defaults.model.primary → 主模型 ref
    - env 中是否有至少一个 *_API_KEY 变量

    Returns:
        (primary_model, has_api_keys)
        - primary_model: 当前主模型 ref,如 "moonshot/kimi-k2.5";None 表示未设置
        - has_api_keys: env 中是否有任意 API Key(粗略判断)
    """
    config_path = os.path.join(os.path.expanduser("~"), ".openclaw", "openclaw.json")
    try:
        if not os.path.exists(config_path):
            return (None, False)

        with open(config_path, "r", encoding="utf-8") as f:
            config = json.load(f)

        # 主模型
        agents = config.get("agents", {})
        defaults = agents.get("defaults", {})
        model = defaults.get("model", {})
        primary: str | None = None
        if isinstance(model, dict):
            primary = model.get("primary") or None
        elif isinstance(model, str) and model:
            primary = model

        # API Key 检查
        env = config.get("env", {})
        has_keys = any(
            k.endswith("_API_KEY") and str(v).strip()
            for k, v in env.items()
            if isinstance(v, str)
        )

        return (primary, has_keys)

    except (json.JSONDecodeError, OSError):
        return (None, False)


# ═══════════════════════════════════════════════════════════════════
# 首页 — 含模型配置状态
# ═══════════════════════════════════════════════════════════════════

class HomePage(QWidget):
    """Launcher 首页

    自动检测并展示当前模型配置状态：
    - 已配置 → 绿色标识 + 模型名 + 启动按钮为主操作
    - 未配置 → 警告提示 + 配置模型按钮提升为主操作
    """

    start_clicked = Signal()
    config_clicked = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._setup_ui()

    def _setup_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        outer.addStretch(1)

        content = QWidget()
        content.setObjectName("homeContent")
        content.setStyleSheet(
            "QWidget#homeContent { background: transparent; }"
            "QWidget#homeContent QLabel { background: transparent; border: none; }"
        )
        layout = QVBoxLayout(content)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.setAlignment(Qt.AlignCenter)

        # ── Logo ──
        logo = QLabel("OC")
        logo.setAlignment(Qt.AlignCenter)
        logo.setFixedSize(72, 72)
        logo.setStyleSheet(
            "background-color: #0F172A; color: white; "
            "border-radius: 18px; font-size: 28px; font-weight: 700; "
            "letter-spacing: -1px;"
        )
        logo_row = QHBoxLayout()
        logo_row.addStretch(1)
        logo_row.addWidget(logo)
        logo_row.addStretch(1)
        layout.addLayout(logo_row)

        # ── 标题 ──
        title = QLabel("OpenClaw")
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet(
            "color: #0F172A; font-size: 32px; font-weight: 700; "
            "letter-spacing: -0.5px; margin-top: 24px;"
        )
        layout.addSpacing(20)
        layout.addWidget(title)

        # ── 模型状态卡片 ──
        layout.addSpacing(24)

        self.status_card = QWidget()
        self.status_card.setObjectName("modelStatus")
        status_layout = QVBoxLayout(self.status_card)
        status_layout.setContentsMargins(0, 0, 0, 0)
        status_layout.setSpacing(0)
        status_layout.setAlignment(Qt.AlignCenter)

        # 已配置模型行
        self.model_row = QWidget()
        model_row_layout = QHBoxLayout(self.model_row)
        model_row_layout.setContentsMargins(0, 0, 0, 0)
        model_row_layout.setSpacing(8)
        model_row_layout.setAlignment(Qt.AlignCenter)

        self.model_dot = QLabel()
        self.model_dot.setFixedSize(8, 8)
        # dot 颜色在 refresh() 中设置

        self.model_label = QLabel("")
        self.model_label.setAlignment(Qt.AlignCenter)
        self.model_label.setStyleSheet("font-size: 13px; font-weight: 500;")

        model_row_layout.addWidget(self.model_dot)
        model_row_layout.addWidget(self.model_label)
        status_layout.addWidget(self.model_row)

        # 未配置时的副提示
        self.model_hint = QLabel("")
        self.model_hint.setAlignment(Qt.AlignCenter)
        self.model_hint.setWordWrap(True)
        self.model_hint.setStyleSheet("font-size: 12px; margin-top: 6px;")
        status_layout.addWidget(self.model_hint)

        layout.addWidget(self.status_card, alignment=Qt.AlignCenter)

        # ── 主操作区 ──
        layout.addSpacing(24)

        # 启动按钮 — 使用全局 primaryButton 样式(slate-900)
        start_row = QHBoxLayout()
        start_row.addStretch(1)
        self.start_btn = QPushButton("启动 OpenClaw")
        self.start_btn.setObjectName("primaryButton")
        self.start_btn.setCursor(Qt.PointingHandCursor)
        self.start_btn.setFixedSize(220, 44)
        self.start_btn.setStyleSheet(
            "QPushButton#primaryButton { font-size: 14px; font-weight: 600; }"
        )
        self.start_btn.clicked.connect(self.start_clicked.emit)
        start_row.addWidget(self.start_btn)
        start_row.addStretch(1)
        layout.addLayout(start_row)

        # 配置模型 — 默认用次要按钮样式,未配时描边加深
        layout.addSpacing(12)
        cfg_row = QHBoxLayout()
        cfg_row.addStretch(1)
        self.config_btn = QPushButton("配置模型")
        self.config_btn.setCursor(Qt.PointingHandCursor)
        self.config_btn.setFixedSize(180, 32)
        self.config_btn.clicked.connect(self.config_clicked.emit)
        cfg_row.addWidget(self.config_btn)
        cfg_row.addStretch(1)
        layout.addLayout(cfg_row)

        outer.addWidget(content, alignment=Qt.AlignCenter)
        outer.addStretch(1)

    def refresh(self) -> None:
        """读取模型配置并刷新状态显示

        每次从其他页面返回首页时调用,确保显示是最新状态。
        所有颜色对齐全局主题(_theme.py):slate 灰系 + 降饱和状态色。
        """
        primary, has_keys = _read_model_status()

        if primary:
            # ── 已配置:绿色状态点 + 静音灰提示 ──
            self.model_dot.setStyleSheet(
                "background-color: #16A34A; border-radius: 4px;"
            )
            if "/" in primary:
                _, model_name = primary.split("/", 1)
            else:
                model_name = primary
            self.model_label.setText(f"当前模型：{model_name}")
            self.model_label.setStyleSheet(
                "color: #475569; font-size: 13px; font-weight: 500;"
            )
            self.model_hint.setText("若已配置过模型，可选择快速启动")
            self.model_hint.setStyleSheet("color: #94A3B8; font-size: 12px; margin-top: 6px;")

            # 配置按钮 — 默认次要样式(白底 + slate 描边)
            self.config_btn.setStyleSheet(
                "QPushButton { font-size: 12px; font-weight: 500; }"
            )

        elif has_keys:
            # ── 有 Key 无模型:琥珀状态点 + 提示 ──
            self.model_dot.setStyleSheet(
                "background-color: #D97706; border-radius: 4px;"
            )
            self.model_label.setText("尚未设置默认模型")
            self.model_label.setStyleSheet(
                "color: #92400E; font-size: 13px; font-weight: 500;"
            )
            self.model_hint.setText("已配置 API Key,但未选择默认模型。请配置模型后启动。")
            self.model_hint.setStyleSheet("color: #92400E; font-size: 12px; margin-top: 6px;")

            # 配置按钮 — 描边加深,提示用户需要操作
            self.config_btn.setStyleSheet(
                "QPushButton { font-size: 12px; font-weight: 600; "
                "border: 1px solid #94A3B8; }"
            )

        else:
            # ── 未配置:红色状态点 + 醒目提示 ──
            self.model_dot.setStyleSheet(
                "background-color: #DC2626; border-radius: 4px;"
            )
            self.model_label.setText("未检测到模型配置")
            self.model_label.setStyleSheet(
                "color: #B91C1C; font-size: 13px; font-weight: 600;"
            )
            self.model_hint.setText("请先配置 API Key 和模型,否则启动后无法使用 OpenClaw。")
            self.model_hint.setStyleSheet("color: #991B1B; font-size: 12px; margin-top: 6px;")

            # 配置按钮 — 描边用降饱和红,字体加粗,但不填满底色
            self.config_btn.setStyleSheet(
                "QPushButton { font-size: 12px; font-weight: 600; "
                "border-color: #DC2626; color: #B91C1C; }"
                "QPushButton:hover { background-color: #FEF2F2; }"
            )


# ═══════════════════════════════════════════════════════════════════
# Launcher 主窗口控制器
# ═══════════════════════════════════════════════════════════════════

class LauncherWindow:
    """Launcher 主窗口控制器

    管理 3 个页面的生命周期、信号连接和状态流转。
    所有耗时操作都委托给 Service/Worker，自身不阻塞主线程。
    """

    def __init__(
        self,
        manager_factory: OpenClawManagerFactory,
        system_launcher: ISystemLauncher,
    ) -> None:
        self.app = QApplication(sys.argv)
        self.app.setApplicationName("OpenClaw Launcher")
        self.app.setStyleSheet(GLOBAL_QSS)

        icon_path = find_app_icon_path()
        if icon_path:
            self.app.setWindowIcon(QIcon(icon_path))

        self.current_page = 0

        self._manager_factory = manager_factory
        self.system_launcher = system_launcher

        self._openclaw_manager: IOpenClawManager | None = None

        self._setup_window()

    @property
    def openclaw_manager(self) -> IOpenClawManager:
        if self._openclaw_manager is None:
            self._openclaw_manager = self._manager_factory()
        return self._openclaw_manager

    def _setup_window(self) -> None:
        self.main_window = QWidget()
        self.main_window.setWindowTitle("OpenClaw 启动器")
        self.main_window.setMinimumSize(QSize(420, 420))

        self.stacked_widget = QStackedWidget()

        self.home_page = HomePage()                       # 0
        self.provider_config_page = ProviderConfigPage()  # 1
        self.startup_page = US06StartupPage()             # 2

        self.stacked_widget.addWidget(self.home_page)             # 0
        self.stacked_widget.addWidget(self.provider_config_page)  # 1
        self.stacked_widget.addWidget(self.startup_page)          # 2

        screen = QApplication.primaryScreen().geometry()
        window_width = 520
        window_height = min(480, int(screen.height() * 0.7))
        self.main_window.resize(window_width, window_height)

        layout = QVBoxLayout(self.main_window)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.stacked_widget)

        self._connect_signals()

    def _connect_signals(self) -> None:
        self.home_page.start_clicked.connect(self._on_start_clicked)
        self.home_page.config_clicked.connect(self._on_open_provider_config)

        self.provider_config_page.back_clicked.connect(self._on_provider_config_back)
        self.provider_config_page.skip_clicked.connect(self._on_provider_config_skip)
        self.provider_config_page.save_and_start_clicked.connect(self._on_provider_config_save)

        self.startup_page.retry_clicked.connect(self._on_startup_retry)
        self.startup_page.finish_clicked.connect(self._on_exit)
        self.startup_page.back_clicked.connect(self._on_startup_back)
        self.startup_page.open_webchat_clicked.connect(self._on_open_webchat)

    # ═══════════════════════════════════════════════════════════════
    # 首页
    # ═══════════════════════════════════════════════════════════════

    def _check_openclaw_exists(self) -> bool:
        home = os.path.expanduser("~")
        project_dir = os.path.join(home, "openclaw-cn")
        pkg_json = os.path.join(project_dir, "package.json")
        return os.path.isdir(project_dir) and os.path.isfile(pkg_json)

    def _on_start_clicked(self) -> None:
        """首页点击「启动」:同步检测安装 → 有就跳启动页,无就弹提示"""
        if self._check_openclaw_exists():
            self.current_page = 2
            self.stacked_widget.setCurrentIndex(2)
            self.main_window.resize(720, min(600, int(
                QApplication.primaryScreen().geometry().height() * 0.8
            )))
            self._start_startup(quick_start=True)
        else:
            QMessageBox.warning(
                self.main_window,
                "未检测到 OpenClaw",
                "未找到 OpenClaw 安装目录（~/openclaw-cn）。\n\n"
                "请先运行 OpenClaw 安装器完成安装后再使用本启动器。"
            )

    def _on_open_provider_config(self) -> None:
        """首页点击「配置模型」:进入 Provider 配置页"""
        self.current_page = 1
        self.stacked_widget.setCurrentIndex(1)
        self.main_window.resize(720, min(700, int(
            QApplication.primaryScreen().geometry().height() * 0.85
        )))
        self.provider_config_page.reset()
        existing = self.openclaw_manager.read_existing_provider_config()
        self.provider_config_page.load_config(existing)

    # ═══════════════════════════════════════════════════════════════
    # Provider 配置
    # ═══════════════════════════════════════════════════════════════

    def _on_provider_config_back(self) -> None:
        """回到首页,刷新模型状态,恢复小窗口"""
        self.current_page = 0
        self.stacked_widget.setCurrentIndex(0)
        self.home_page.refresh()
        self.main_window.resize(520, 480)

    def _on_provider_config_skip(self) -> None:
        self.current_page = 2
        self.stacked_widget.setCurrentIndex(2)
        self.main_window.resize(720, min(600, int(
            QApplication.primaryScreen().geometry().height() * 0.8
        )))
        self._start_startup(quick_start=False)

    def _on_provider_config_save(self, payload: dict) -> None:
        from src.services.configure_providers import ProviderConfigWorker

        self.provider_config_page.show_saving()
        self._provider_config_worker = ProviderConfigWorker(
            self.openclaw_manager,
            payload["providers"],
            payload["global_default_model"],
            payload.get("fallback_models", []),
        )
        self._provider_config_worker.complete.connect(self._on_provider_config_complete)
        self._provider_config_worker.start()

    def _on_provider_config_complete(self, ok: bool) -> None:
        self.provider_config_page.hide_saving()
        if ok:
            self.current_page = 2
            self.stacked_widget.setCurrentIndex(2)
            self.main_window.resize(720, min(600, int(
                QApplication.primaryScreen().geometry().height() * 0.8
            )))
            self._start_startup(quick_start=False)
        else:
            self.provider_config_page.show_error(
                "配置保存失败,请检查 API Key 和网络连接后重试。"
            )

    # ═══════════════════════════════════════════════════════════════
    # 启动
    # ═══════════════════════════════════════════════════════════════

    def _start_startup(self, quick_start: bool = False) -> None:
        from src.services.configure_providers import StartupWorker

        self.startup_page.reset()
        self.startup_page.start_startup()

        self.startup_worker = StartupWorker(
            self.openclaw_manager, quick_start=quick_start,
        )
        self.startup_worker.progress_updated.connect(self._on_startup_progress)
        self.startup_worker.log_line.connect(self.startup_page.add_log_line)
        self.startup_worker.complete.connect(self._on_startup_complete)
        self.startup_worker.start()

    def _on_startup_progress(self, progress) -> None:
        self.startup_page.update_progress(progress)

    def _on_startup_complete(self, result) -> None:
        from src.models.config import ConfigStatus
        if result.status == ConfigStatus.COMPLETED:
            self.startup_page.startup_success(result)
        else:
            self.startup_page.startup_failed(result)

    def _on_startup_retry(self) -> None:
        self._start_startup(quick_start=True)

    def _on_startup_back(self) -> None:
        """回到首页,刷新模型状态,恢复小窗口"""
        self.current_page = 0
        self.stacked_widget.setCurrentIndex(0)
        self.home_page.refresh()
        self.main_window.resize(520, 480)

    def _on_open_webchat(self) -> None:
        url = self.startup_page.url_input.text()
        if not url:
            self.startup_page.browser_hint.setText("地址为空,无法打开浏览器")
            return
        if not url.startswith(("http://", "https://")):
            self.startup_page.browser_hint.setText("地址格式不正确,无法打开浏览器")
            return

        self.startup_page.url_input.deselect()

        clipboard = QApplication.clipboard()
        original = clipboard.text()

        if self.system_launcher.open_url(url):
            self.startup_page.browser_hint.setText("浏览器已打开,如果未显示请检查是否被拦截")
        else:
            self.startup_page.browser_hint.setText("未能自动打开浏览器,请复制上方地址手动访问")

        def _restore_if_polluted() -> None:
            if clipboard.text() == url and original != url:
                clipboard.setText(original)

        QTimer.singleShot(100, _restore_if_polluted)
        QTimer.singleShot(500, _restore_if_polluted)

    # ═══════════════════════════════════════════════════════════════
    # 退出 & 清理
    # ═══════════════════════════════════════════════════════════════

    def _on_exit(self) -> None:
        if self._openclaw_manager is not None:
            self._openclaw_manager.stop()
        self.main_window.close()

    def show(self) -> None:
        self.main_window.show()
        self.home_page.refresh()

    def run(self) -> int:
        return self.app.exec()

    def cleanup(self) -> None:
        if self._openclaw_manager is not None:
            self._openclaw_manager.stop()
