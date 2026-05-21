"""卸载工具 —— 确认/检测页面。

职责：卸载流程的第一页。检测用户系统中是否存在 OpenClaw 安装记录
（程序目录 ~/openclaw-cn 与配置目录 ~/.openclaw），并根据检测结果展示
不同的状态卡片与操作按钮：
- 已安装：展示警告清单，提供「确认卸载」按钮
- 未安装：提示无需卸载，仅提供「退出」按钮
"""

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QPushButton, QHBoxLayout,
    QFrame, QScrollArea,
)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont


class UninstallWelcomePage(QWidget):
    """卸载工具欢迎页 —— 检测 OpenClaw 安装状态并请求用户确认卸载。

    职责：作为卸载流程的第一页，在初始化时自动检测系统中是否存在 OpenClaw
    安装记录（程序目录 ~/openclaw-cn 与配置目录 ~/.openclaw）。根据检测结果
    动态切换 UI：
    - 已安装：展示红色状态卡片 + 警告清单，提供「确认卸载」按钮
    - 未安装：展示绿色状态卡片，仅提供「退出」按钮
    """

    confirm_clicked = Signal()  # 用户点击「确认卸载」，触发进入卸载进度页
    cancel_clicked = Signal()   # 用户点击「取消/退出」，触发关闭卸载工具

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.installed = False
        self._setup_ui()
        self.check_installation()

    def _setup_ui(self) -> None:
        # 卸载工具:同样套用 welcome 页的视觉系统(左对齐、56px 阅读边距、底部按钮栏)
        # 但语义偏向"破坏性确认",因此用红色 dot 和降饱和红 dangerButton
        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(0)
        main_layout.setContentsMargins(0, 0, 0, 0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setStyleSheet("QScrollArea { background-color: transparent; border: none; }")

        # 内容区透明:必须用 QWidget#锚定 选择器,见 show_uninstall_progress.py:39
        content = QWidget()
        content.setObjectName("uninstWelcomeContent")
        content.setStyleSheet("QWidget#uninstWelcomeContent { background-color: transparent; }")
        layout = QVBoxLayout(content)
        layout.setContentsMargins(56, 48, 56, 32)
        layout.setSpacing(0)

        # ── 标题 ───────────────────────────────────────────────
        title = QLabel("卸载 OpenClaw")
        title.setStyleSheet(
            "color: #0F172A; font-size: 32px; font-weight: 700; "
            "letter-spacing: -1px; background: transparent; border: none;"
        )
        layout.addWidget(title)

        layout.addSpacing(8)
        subtitle = QLabel("将系统恢复到安装 OpenClaw 之前的状态。")
        subtitle.setStyleSheet(
            "color: #64748B; font-size: 13px; background: transparent; border: none;"
        )
        layout.addWidget(subtitle)

        # ── 状态卡片(检测中/已安装/未安装) ──────────────────
        # 用 6×6 状态点 + 标题 + 说明 替代原来的大 emoji + 居中文字
        self.status_frame = QFrame()
        self.status_frame.setStyleSheet(
            "QFrame#uninstStatus { background-color: white; border: 1px solid #E2E8F0; "
            "border-radius: 8px; }"
            "QFrame#uninstStatus QLabel { background: transparent; border: none; }"
        )
        self.status_frame.setObjectName("uninstStatus")

        sf_layout = QVBoxLayout(self.status_frame)
        sf_layout.setContentsMargins(20, 18, 20, 18)
        sf_layout.setSpacing(0)

        status_row = QHBoxLayout()
        status_row.setSpacing(10)
        status_row.setContentsMargins(0, 0, 0, 0)

        self.status_dot = QLabel()
        self.status_dot.setFixedSize(8, 8)
        self.status_dot.setStyleSheet("background-color: #94A3B8; border-radius: 4px;")

        self.status_title = QLabel("正在检测...")
        self.status_title.setStyleSheet(
            "color: #0F172A; font-size: 14px; font-weight: 600;"
        )

        status_row.addWidget(self.status_dot, alignment=Qt.AlignVCenter)
        status_row.addWidget(self.status_title)
        status_row.addStretch(1)

        self.status_detail = QLabel("")
        self.status_detail.setWordWrap(True)
        self.status_detail.setStyleSheet("color: #64748B; font-size: 12px; padding-left: 18px;")

        sf_layout.addLayout(status_row)
        sf_layout.addSpacing(4)
        sf_layout.addWidget(self.status_detail)

        layout.addSpacing(28)
        layout.addWidget(self.status_frame)

        # ── 警告清单(仅已安装时显示) ────────────────────────
        self.warning_frame = QFrame()
        self.warning_frame.setObjectName("uninstWarning")
        self.warning_frame.setStyleSheet(
            "QFrame#uninstWarning { background-color: #FEF2F2; border: 1px solid #FECACA; "
            "border-radius: 8px; }"
            "QFrame#uninstWarning QLabel { background: transparent; border: none; }"
        )
        wf_layout = QVBoxLayout(self.warning_frame)
        wf_layout.setContentsMargins(20, 16, 20, 16)
        wf_layout.setSpacing(8)

        warn_title = QLabel("将永久删除以下内容")
        warn_title.setStyleSheet("color: #991B1B; font-size: 13px; font-weight: 600;")

        warn_list = QLabel(
            "OpenClaw 程序文件 (~/openclaw-cn)\n"
            "所有配置文件 (~/.openclaw,含 API Key)\n"
            "命令行工具 (openclaw / openclaw-cn)\n"
            "Gateway 服务进程"
        )
        warn_list.setStyleSheet("color: #7F1D1D; font-size: 12px; line-height: 1.7;")

        wf_layout.addWidget(warn_title)
        wf_layout.addWidget(warn_list)
        self.warning_frame.hide()

        layout.addSpacing(12)
        layout.addWidget(self.warning_frame)
        layout.addStretch(1)

        scroll.setWidget(content)
        main_layout.addWidget(scroll, 1)

        # ── 底部按钮栏 ─────────────────────────────────────
        # 按钮状态机:
        #   - 检测中 / 未安装:仅显示「退出」
        #   - 已安装:显示「取消」+「确认卸载」(dangerButton 样式)
        button_bar = QFrame()
        button_bar.setStyleSheet(
            "QFrame { background-color: #FAFBFC; border-top: 1px solid #E2E8F0; }"
        )
        btn_layout = QHBoxLayout(button_bar)
        btn_layout.setContentsMargins(56, 16, 56, 16)
        btn_layout.setSpacing(8)
        btn_layout.addStretch(1)

        self.cancel_btn = QPushButton("取消")
        self.cancel_btn.setFixedHeight(36)
        self.cancel_btn.clicked.connect(self.cancel_clicked.emit)

        self.confirm_btn = QPushButton("确认卸载")
        self.confirm_btn.setFixedHeight(36)
        self.confirm_btn.setObjectName("dangerButton")
        self.confirm_btn.clicked.connect(self.confirm_clicked.emit)
        self.confirm_btn.hide()

        btn_layout.addWidget(self.cancel_btn)
        btn_layout.addWidget(self.confirm_btn)

        main_layout.addWidget(button_bar)

    def check_installation(self) -> None:
        """检测用户主目录下是否存在 OpenClaw 程序与配置目录，并据此刷新 UI 状态。"""
        from src.models.utils import detect_openclaw_installation

        installed, details = detect_openclaw_installation()

        if installed:
            self.installed = True
            self.status_dot.setStyleSheet("background-color: #DC2626; border-radius: 4px;")
            self.status_title.setText("检测到 OpenClaw 已安装")
            self.status_title.setStyleSheet("color: #991B1B; font-size: 14px; font-weight: 600;")
            self.status_detail.setText("\n".join(details))

            self.warning_frame.show()
            self.confirm_btn.show()
            self.cancel_btn.setText("取消")
        else:
            self.installed = False
            self.status_dot.setStyleSheet("background-color: #16A34A; border-radius: 4px;")
            self.status_title.setText("未检测到 OpenClaw")
            self.status_title.setStyleSheet("color: #15803D; font-size: 14px; font-weight: 600;")
            self.status_detail.setText("您的系统中没有 OpenClaw 安装记录,无需卸载。")
            self.cancel_btn.setText("退出")
            self.warning_frame.hide()
            self.confirm_btn.hide()
