"""卸载工具 —— 进度/日志页面。

职责：展示卸载流程的实时进度、状态文本和命令行日志输出。
    作为卸载流程的第二页，在用户点击「确认卸载」后进入，
    通过后台线程执行停止 Gateway、删除目录、清理 npm wrappers 等操作，
    并将结果实时反映到进度条和日志区域。
"""

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QPushButton, QHBoxLayout,
    QProgressBar, QPlainTextEdit, QFrame,
)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont


class UninstallProgressPage(QWidget):
    """卸载进度页面 —— 展示卸载过程的实时进度与日志。

    职责：作为卸载流程的第二页，在用户点击「确认卸载」后进入。
    通过后台线程执行停止 Gateway、删除目录、清理 npm wrappers 等操作，
    并将结果实时反映到进度条、状态文本和日志区域。提供「取消」按钮，
    但卸载一旦开始即不可真正中断（子进程已提交），按钮仅作状态提示。
    """

    cancel_clicked = Signal()  # 用户点击「取消」，但卸载开始后该按钮会被禁用，仅作状态提示

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._setup_ui()

    def _setup_ui(self) -> None:
        # 卸载进度页:与安装进度页一致的版式,但用 dangerProgressBar 暗示破坏性
        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(0)
        main_layout.setContentsMargins(0, 0, 0, 0)

        # 内容区透明:必须用 QWidget#锚定 选择器,否则裸 setStyleSheet 会被 Qt
        # 当作 * 选择器向下递归注入,把全局 #logArea 的深色背景冲掉,导致日志区
        # 浅色背景 + 浅灰文字双浅看不清(2026-05-20 修)
        content = QWidget()
        content.setObjectName("uninstProgressContent")
        content.setStyleSheet("QWidget#uninstProgressContent { background-color: transparent; }")
        layout = QVBoxLayout(content)
        layout.setContentsMargins(56, 40, 56, 32)
        layout.setSpacing(0)

        title = QLabel("正在卸载")
        title.setStyleSheet(
            "color: #0F172A; font-size: 28px; font-weight: 700; "
            "letter-spacing: -0.5px; background: transparent; border: none;"
        )
        layout.addWidget(title)

        self.progress_label = QLabel("准备卸载...")
        self.progress_label.setStyleSheet(
            "color: #64748B; font-size: 13px; background: transparent; border: none;"
        )
        layout.addSpacing(8)
        layout.addWidget(self.progress_label)

        # 进度条:dangerProgressBar 样式(降饱和红),已在全局 QSS 中定义
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setObjectName("dangerProgressBar")
        layout.addSpacing(20)
        layout.addWidget(self.progress_bar)

        # 日志小节标签 + 黑色日志框(全局 QSS #logArea)
        log_section_label = QLabel("卸载日志")
        log_section_label.setStyleSheet(
            "color: #64748B; font-size: 11px; font-weight: 600; "
            "letter-spacing: 1.5px; background: transparent; border: none;"
        )
        layout.addSpacing(28)
        layout.addWidget(log_section_label)
        layout.addSpacing(8)

        # 用 QPlainTextEdit + setMaximumBlockCount 而不是 QTextEdit:
        # QTextEdit.append 是富文本路径,每次插入都重做 HTML 解析+完整 layout。
        # Windows 上一旦短时间涌入上千条日志(npm uninstall/pnpm 输出经过
        # _run_cmd_with_streaming 逐行 emit),主线程槽函数被堆满,5 秒内来不及
        # 处理 DWM 探测就触发"程序无响应"弹窗。QPlainTextEdit 是纯文本路径,
        # 配合 200 行上限,即使瞬时大量日志也能流畅追加。
        self.log_edit = QPlainTextEdit()
        self.log_edit.setReadOnly(True)
        self.log_edit.setMaximumBlockCount(200)
        self.log_edit.setObjectName("logArea")
        self.log_edit.setMinimumHeight(220)
        layout.addWidget(self.log_edit, 1)

        main_layout.addWidget(content, 1)

        # 按钮栏:仅「取消」,卸载开始后禁用
        button_bar = QFrame()
        button_bar.setStyleSheet(
            "QFrame { background-color: #FAFBFC; border-top: 1px solid #E2E8F0; }"
        )
        btn_layout = QHBoxLayout(button_bar)
        btn_layout.setContentsMargins(56, 16, 56, 16)
        btn_layout.addStretch(1)

        self.cancel_btn = QPushButton("取消")
        self.cancel_btn.setFixedHeight(36)
        self.cancel_btn.clicked.connect(self.cancel_clicked.emit)

        btn_layout.addWidget(self.cancel_btn)

        main_layout.addWidget(button_bar)

    def reset(self) -> None:
        """重置页面状态，恢复到初始值。"""
        self.progress_bar.setValue(0)
        self.progress_label.setText("准备卸载...")
        self.log_edit.clear()  # QPlainTextEdit 也有 clear() 方法
        self.cancel_btn.setEnabled(True)
        self.cancel_btn.setText("取消")

    def set_progress(self, percent: int, message: str) -> None:
        """更新进度条值和状态文本。"""
        self.progress_bar.setValue(percent)
        self.progress_label.setText(message)

    def add_log(self, line: str) -> None:
        """追加日志行并自动滚动到底部。"""
        # appendPlainText 是 QPlainTextEdit 的纯文本快路径,比 QTextEdit.append 快一个数量级
        self.log_edit.appendPlainText(line)
        scrollbar = self.log_edit.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    def set_done(self) -> None:
        """卸载完成后禁用取消按钮并更新文本，防止用户误操作。"""
        self.cancel_btn.setEnabled(False)
        self.cancel_btn.setText("卸载中...")
