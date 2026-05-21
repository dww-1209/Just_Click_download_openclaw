"""卸载工具 —— 完成页面。

职责：卸载流程的最后一页，展示卸载完成的结果状态。
    支持两种展示模式：
    - 完全成功：绿色状态卡片 + 标准已删除清单
    - 部分完成：黄色警告卡片 + 已删除/失败混合清单，提示用户手动清理
"""

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QPushButton, QHBoxLayout,
    QFrame,
)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont

from src.models.constants import is_windows


class UninstallDonePage(QWidget):
    """卸载完成页面 —— 展示卸载结果并提供退出或重新检测的入口。

    职责：作为卸载流程的最后一页，根据后台线程的执行结果展示两种状态：
    - 完全成功：绿色状态卡片 + 标准已删除清单
    - 部分完成：黄色警告卡片 + 已删除/失败混合清单，提示用户手动清理
    同时提供「退出」和「重新检测环境」两个按钮，方便用户验证残留。
    """

    recheck_clicked = Signal()  # 用户点击「重新检测环境」，触发回到卸载欢迎页重新扫描
    exit_clicked = Signal()     # 用户点击「退出」，触发关闭卸载工具

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._setup_ui()

    def _setup_ui(self) -> None:
        # 卸载完成页:与 welcome 页一致的版式
        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(0)
        main_layout.setContentsMargins(0, 0, 0, 0)

        # 内容区透明:必须用 QWidget#锚定 选择器,见 show_uninstall_progress.py:39
        content = QWidget()
        content.setObjectName("uninstDoneContent")
        content.setStyleSheet("QWidget#uninstDoneContent { background-color: transparent; }")
        layout = QVBoxLayout(content)
        layout.setContentsMargins(56, 48, 56, 32)
        layout.setSpacing(0)

        # ── 标题(动态:卸载完成 / 卸载部分完成) ──────────
        self.title_label = QLabel("卸载完成")
        self.title_label.setStyleSheet(
            "color: #0F172A; font-size: 32px; font-weight: 700; "
            "letter-spacing: -1px; background: transparent; border: none;"
        )
        layout.addWidget(self.title_label)

        # 状态行:dot + 短描述
        status_row = QHBoxLayout()
        status_row.setSpacing(10)
        status_row.setContentsMargins(0, 0, 0, 0)
        self.status_dot = QLabel()
        self.status_dot.setFixedSize(8, 8)
        self.status_dot.setStyleSheet("background-color: #16A34A; border-radius: 4px;")
        self.status_desc = QLabel("您的系统已恢复到安装前状态。")
        self.status_desc.setStyleSheet("color: #475569; font-size: 13px;")
        status_row.addWidget(self.status_dot, alignment=Qt.AlignVCenter)
        status_row.addWidget(self.status_desc)
        status_row.addStretch(1)
        layout.addSpacing(16)
        layout.addLayout(status_row)

        # ── 清单 ──────────────────────────────────────────
        section_label = QLabel("操作清单")
        section_label.setStyleSheet(
            "color: #64748B; font-size: 11px; font-weight: 600; "
            "letter-spacing: 1.5px; background: transparent; border: none;"
        )
        layout.addSpacing(40)
        layout.addWidget(section_label)
        layout.addSpacing(8)

        self.checklist_frame = QFrame()
        self.checklist_frame.setObjectName("checklistFrame")
        self.checklist_frame.setStyleSheet(
            "QFrame#checklistFrame { background-color: white; border: 1px solid #E2E8F0; "
            "border-radius: 8px; }"
            "QFrame#checklistFrame QLabel { background: transparent; border: none; }"
        )
        cl_layout = QVBoxLayout(self.checklist_frame)
        cl_layout.setContentsMargins(20, 16, 20, 16)
        cl_layout.setSpacing(8)

        # 清单文本(动态更新)
        self.checklist_label = QLabel(
            "OpenClaw 程序文件 — 已删除\n"
            "配置文件 (含 API Key) — 已删除\n"
            "命令行工具 — 已删除\n"
            "Gateway 服务 — 已停止"
        )
        self.checklist_label.setStyleSheet(
            "color: #475569; font-size: 13px; line-height: 1.7;"
        )
        cl_layout.addWidget(self.checklist_label)
        layout.addWidget(self.checklist_frame)

        layout.addStretch(1)
        main_layout.addWidget(content, 1)

        # ── 底部按钮栏 ────────────────────────────────────
        button_bar = QFrame()
        button_bar.setStyleSheet(
            "QFrame { background-color: #FAFBFC; border-top: 1px solid #E2E8F0; }"
        )
        btn_layout = QHBoxLayout(button_bar)
        btn_layout.setContentsMargins(56, 16, 56, 16)
        btn_layout.setSpacing(8)
        btn_layout.addStretch(1)

        self.exit_btn = QPushButton("退出")
        self.exit_btn.setFixedHeight(36)
        self.exit_btn.clicked.connect(self.exit_clicked.emit)

        self.recheck_btn = QPushButton("重新检测")
        self.recheck_btn.setFixedHeight(36)
        self.recheck_btn.setObjectName("primaryButton")
        self.recheck_btn.clicked.connect(self.recheck_clicked.emit)

        btn_layout.addWidget(self.exit_btn)
        btn_layout.addWidget(self.recheck_btn)

        main_layout.addWidget(button_bar)

    def set_success(self) -> None:
        """完全成功:绿色 dot + 标题"卸载完成"。"""
        self.title_label.setText("卸载完成")
        self.status_dot.setStyleSheet("background-color: #16A34A; border-radius: 4px;")
        self.status_desc.setText("您的系统已恢复到安装前状态。")
        self.status_desc.setStyleSheet("color: #475569; font-size: 13px;")
        self.checklist_label.setText(self._build_checklist_text())
        self.checklist_label.setStyleSheet(
            "color: #475569; font-size: 13px; line-height: 1.7;"
        )

    def set_partial(self, failed_items: list[str]) -> None:
        """部分完成:琥珀 dot + 标题"卸载部分完成"。

        Args:
            failed_items: 未能成功删除的项目名称列表
        """
        self.title_label.setText("卸载部分完成")
        self.status_dot.setStyleSheet("background-color: #D97706; border-radius: 4px;")
        self.status_desc.setText("部分文件未能删除,您可以手动清理剩余文件。")
        self.status_desc.setStyleSheet("color: #92400E; font-size: 13px;")

        # 用 HTML 富文本对失败项染红,QLabel 默认支持
        lines: list[str] = self._build_checklist_lines()
        success_part = "<br>".join(
            f'<span style="color:#475569;">{ln}</span>' for ln in lines
        )
        fail_part = "<br>".join(
            f'<span style="color:#991B1B;">{item} — 删除失败</span>' for item in failed_items
        )
        if fail_part:
            self.checklist_label.setText(f"{success_part}<br>{fail_part}")
        else:
            self.checklist_label.setText(success_part)
        self.checklist_label.setStyleSheet("font-size: 13px; line-height: 1.7;")
        self.checklist_label.setTextFormat(Qt.RichText)

    def _build_checklist_lines(self) -> list[str]:
        """构造卸载清单的行列表。

        Windows 上多两行(桌面快捷方式 + 开始菜单项),Mac 上保持原样。
        位置:在"命令行工具"之后、"Gateway 服务"之前。
        """
        lines = [
            "OpenClaw 程序文件 — 已删除",
            "配置文件 (含 API Key) — 已删除",
            "命令行工具 — 已删除",
        ]
        if is_windows():
            lines.append("桌面快捷方式 — 已删除")
            lines.append("开始菜单项 — 已删除")
        lines.append("Gateway 服务 — 已停止")
        return lines

    def _build_checklist_text(self) -> str:
        """构造卸载清单的纯文本(给 set_success 用,不带 HTML)。"""
        return "\n".join(self._build_checklist_lines())
