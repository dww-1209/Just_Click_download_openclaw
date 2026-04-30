from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QLabel,
    QPushButton,
    QHBoxLayout,
    QFrame,
)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont


def _step_bubble(text: str, number: int, active: bool = False) -> QFrame:
    """创建一个步骤气泡组件"""
    frame = QFrame()
    frame.setStyleSheet(
        "QFrame { background-color: " + ("#e8f5e9" if active else "#f5f5f5") + "; "
        "border-radius: 8px; padding: 4px; }"
    )
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(8, 8, 8, 8)
    layout.setSpacing(4)
    num_label = QLabel(str(number))
    num_label.setAlignment(Qt.AlignCenter)
    num_label.setStyleSheet(
        "background-color: " + ("#4CAF50" if active else "#bbb") + "; "
        "color: white; border-radius: 12px; font-weight: bold; font-size: 12px;"
    )
    num_label.setFixedSize(24, 24)
    text_label = QLabel(text)
    text_label.setAlignment(Qt.AlignCenter)
    text_label.setStyleSheet("font-size: 11px; color: #333;")
    layout.addWidget(num_label, alignment=Qt.AlignCenter)
    layout.addWidget(text_label)
    return frame


def _step_line() -> QLabel:
    line = QLabel()
    line.setFixedSize(20, 2)
    line.setStyleSheet("background-color: #ddd;")
    return line


class WelcomePage(QWidget):
    """欢迎页面 - US-01"""

    next_clicked = Signal()
    exit_clicked = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_ui()

    def _setup_ui(self):
        from PySide6.QtWidgets import QScrollArea

        # 主布局
        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(10)
        main_layout.setContentsMargins(24, 24, 24, 24)

        # 创建滚动区域
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameShape(QScrollArea.NoFrame)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        # 内容容器
        content_widget = QWidget()
        layout = QVBoxLayout(content_widget)
        layout.setSpacing(15)
        layout.setContentsMargins(40, 30, 40, 30)

        title = QLabel("OpenClaw 安装程序")
        title.setAlignment(Qt.AlignCenter)
        title_font = QFont()
        title_font.setPointSize(22)
        title_font.setBold(True)
        title.setFont(title_font)

        logo_area = QLabel("🦞")
        logo_area.setAlignment(Qt.AlignCenter)
        logo_area.setStyleSheet(
            "background-color: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #e8f5e9, stop:1 #c8e6c9); "
            "min-height: 120px; border-radius: 12px; font-size: 48px;"
        )

        welcome_text = QLabel("欢迎使用 OpenClaw（小龙虾）")
        welcome_text.setAlignment(Qt.AlignCenter)
        welcome_text_font = QFont()
        welcome_text_font.setPointSize(13)
        welcome_text.setFont(welcome_text_font)

        description_text = QLabel(
            "本程序将帮您一键安装 OpenClaw（小龙虾）\n"
            "无需任何技术基础，点击开始即可自动完成\n\n"
            "全程无需手动操作，请保持网络畅通"
        )
        description_text.setAlignment(Qt.AlignCenter)
        description_text.setWordWrap(True)
        desc_font = QFont()
        desc_font.setPointSize(10)
        description_text.setFont(desc_font)

        # 步骤流程指示器
        steps_layout = QHBoxLayout()
        steps_layout.setSpacing(6)
        steps_layout.setContentsMargins(0, 10, 0, 10)
        steps = [
            ("环境检测", False),
            ("下载安装", False),
            ("自动配置", False),
            ("启动服务", False),
        ]
        for i, (name, active) in enumerate(steps):
            steps_layout.addWidget(_step_bubble(name, i + 1, active))
            if i < len(steps) - 1:
                steps_layout.addWidget(_step_line())

        layout.addStretch(1)
        layout.addWidget(title)
        layout.addSpacing(20)
        layout.addWidget(logo_area)
        layout.addSpacing(20)
        layout.addWidget(welcome_text)
        layout.addSpacing(10)
        layout.addWidget(description_text)
        layout.addSpacing(20)
        layout.addLayout(steps_layout)
        layout.addStretch(2)

        scroll_area.setWidget(content_widget)
        main_layout.addWidget(scroll_area, 1)

        # 按钮区域（固定在底部）
        button_layout = QHBoxLayout()
        button_layout.setContentsMargins(40, 10, 40, 0)
        button_layout.addStretch(1)

        self.exit_button = QPushButton("退出")
        self.exit_button.setFixedSize(100, 36)
        self.exit_button.clicked.connect(self.exit_clicked.emit)

        self.next_button = QPushButton("开始安装")
        self.next_button.setFixedSize(120, 40)
        self.next_button.setObjectName("primaryButton")
        self.next_button.clicked.connect(self.next_clicked.emit)

        button_layout.addWidget(self.exit_button)
        button_layout.addWidget(self.next_button)

        main_layout.addLayout(button_layout)
