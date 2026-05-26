"""欢迎页(US-01)— 企业级简约风格试点版本

设计原则(对应"去 AI 味"的重构):
- 不使用 emoji,品牌标改为程序化绘制的字母方块
- 左对齐布局取代居中堆叠,建立稳定的视觉锚点
- 配色降饱和(slate 调色板)+ 强调色限制在主 CTA
- 文案去营销化,只保留必要信息
- 8pt 网格间距,密度更高
"""

from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QLabel,
    QPushButton,
    QHBoxLayout,
    QScrollArea,
    QFrame,
)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont, QKeySequence, QShortcut


# 局部样式表(只作用于本页元素,不污染全局 QSS)
# 主按钮用 slate-900 取代全局的 Material Green,呈现极克制的企业级强调色
_LOCAL_QSS = """
QWidget#welcomePage {
    background-color: #FAFBFC;
}

QFrame#brandMark {
    background-color: #0F172A;
    border-radius: 10px;
}

QLabel#brandMarkText {
    color: white;
    background: transparent;
    font-weight: 700;
    font-size: 18px;
    letter-spacing: -0.5px;
}

QLabel#brandName {
    color: #0F172A;
    font-size: 15px;
    font-weight: 600;
    letter-spacing: -0.2px;
}

QLabel#brandTagline {
    color: #94A3B8;
    font-size: 12px;
    font-weight: 500;
}

QLabel#pageTitle {
    color: #0F172A;
    font-size: 32px;
    font-weight: 700;
    letter-spacing: -1px;
}

QLabel#pageBody {
    color: #475569;
    font-size: 14px;
    font-weight: 400;
}

QLabel#sectionLabel {
    color: #64748B;
    font-size: 11px;
    font-weight: 600;
    letter-spacing: 1.5px;
}

QLabel#stepNumber {
    color: #94A3B8;
    font-size: 13px;
    font-weight: 600;
    letter-spacing: 0.5px;
}

QLabel#stepLabel {
    color: #1E293B;
    font-size: 14px;
    font-weight: 500;
}

QLabel#stepDuration {
    color: #94A3B8;
    font-size: 12px;
    font-weight: 500;
}

QFrame#stepDivider {
    background-color: #E2E8F0;
    max-height: 1px;
    min-height: 1px;
}

/* 按钮风格已统一到全局 QSS,这里复用 #primaryButton / 默认次要按钮 */
"""


def _make_brand_mark() -> QFrame:
    """品牌标志 — 用 QFrame + QLabel 程序化绘制,避免 emoji 跨平台渲染差异。

    设计:深色圆角方块 + 白色字母 "OC"。在 Win/Mac 渲染一致,
    高 DPI 下保持锐利,且与企业级软件(Linear/Vercel/Stripe)的极简
    品牌呈现风格一致。
    """
    mark = QFrame()
    mark.setObjectName("brandMark")
    mark.setFixedSize(40, 40)

    layout = QVBoxLayout(mark)
    layout.setContentsMargins(0, 0, 0, 0)

    text = QLabel("OC")
    text.setObjectName("brandMarkText")
    text.setAlignment(Qt.AlignCenter)
    layout.addWidget(text)
    return mark


def _make_step_row(number: str, label: str, duration: str = "") -> QWidget:
    """单条流程预览 — 数字编号 + 步骤名 + 预估耗时,无色块、无图标。

    用纯排版构建层级:数字用静音灰小字(辅助信息),步骤名用 slate-800
    中等字重(主信息),耗时右对齐用静音灰。整行左对齐,8pt 垂直节奏。
    给用户量化锚点("现在卡在哪一步、还要多久"),避免在 pnpm install
    阶段误以为程序卡死。
    """
    row = QWidget()
    layout = QHBoxLayout(row)
    layout.setContentsMargins(0, 8, 0, 8)
    layout.setSpacing(20)

    num = QLabel(number)
    num.setObjectName("stepNumber")
    num.setFixedWidth(24)

    name = QLabel(label)
    name.setObjectName("stepLabel")

    layout.addWidget(num)
    layout.addWidget(name)
    layout.addStretch(1)

    if duration:
        dur = QLabel(duration)
        dur.setObjectName("stepDuration")
        layout.addWidget(dur)
    return row


def _make_divider() -> QFrame:
    """步骤之间的 1px 分隔线,起视觉节奏作用。"""
    line = QFrame()
    line.setObjectName("stepDivider")
    return line


class WelcomePage(QWidget):
    """欢迎页面(US-01)—— 安装流程的起点。

    职责:展示品牌、说明本程序作用、预览安装阶段,并提供「开始安装」入口。
    作为 QStackedWidget 的第一页,定下整个安装器的视觉基调。
    """

    next_clicked = Signal()   # 用户点击「开始安装」,触发进入环境检测页
    exit_clicked = Signal()   # 用户点击「退出」,触发关闭安装器

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("welcomePage")
        self.setStyleSheet(_LOCAL_QSS)
        self._setup_ui()

    def _setup_ui(self) -> None:
        # 页面整体:可滚动内容区 + 固定底部按钮栏
        # 滚动区兜底高 DPI / 笔记本小屏(1366×768)场景
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
        content.setObjectName("welcomeContent")
        content.setStyleSheet("QWidget#welcomeContent { background-color: transparent; }")
        content_layout = QVBoxLayout(content)
        # 左右内边距 56px,在 800 宽窗口里留出舒适的"阅读宽度",避免行长过长
        content_layout.setContentsMargins(56, 48, 56, 32)
        content_layout.setSpacing(0)

        # ── 品牌行(顶部) ────────────────────────────────────────
        # 标志 + 产品名 + 副标,横向排列且左对齐,建立第一个视觉锚点
        brand_row = QHBoxLayout()
        brand_row.setSpacing(14)
        brand_row.setContentsMargins(0, 0, 0, 0)

        brand_row.addWidget(_make_brand_mark())

        brand_text_col = QVBoxLayout()
        brand_text_col.setSpacing(2)
        brand_text_col.setContentsMargins(0, 2, 0, 0)

        brand_name = QLabel("OpenClaw")
        brand_name.setObjectName("brandName")
        brand_tagline = QLabel("一键安装程序")
        brand_tagline.setObjectName("brandTagline")

        brand_text_col.addWidget(brand_name)
        brand_text_col.addWidget(brand_tagline)
        brand_text_col.addStretch(1)

        brand_row.addLayout(brand_text_col)
        brand_row.addStretch(1)

        content_layout.addLayout(brand_row)

        # ── 主标题 ───────────────────────────────────────────────
        # 占据视觉重心,大号字 + 字距收紧,呼应现代企业级产品(Linear / Vercel)
        title = QLabel("欢迎")
        title.setObjectName("pageTitle")
        # QSS 不支持 letter-spacing,需要通过 QFont 设置
        title_font = title.font()
        title_font.setLetterSpacing(QFont.AbsoluteSpacing, -1.0)
        title.setFont(title_font)

        content_layout.addSpacing(56)
        content_layout.addWidget(title)

        # ── 正文 ─────────────────────────────────────────────────
        # 两段:第一段说明产品,第二段说明本程序作用与预期耗时
        # 文案极简,不含营销语("一键"、"无需技术基础"等已删除)
        body = QLabel(
            "OpenClaw 是一款本地运行的 AI Agent 平台。\n"
            "本程序将为您准备 OpenClaw 的运行环境,整个过程预计 10–15 分钟。"
        )
        body.setObjectName("pageBody")
        body.setWordWrap(True)
        # 行高:Qt 通过 QTextDocument 控制,简单方案是用 QLabel 的 lineWidth 不行,
        # 这里通过段间空行让节奏舒展
        content_layout.addSpacing(16)
        content_layout.addWidget(body)

        # ── 流程预览 ──────────────────────────────────────────────
        # 4 行最简列表,数字编号 + 步骤名,行间用 1px 分隔线
        # 取代原来的彩色气泡(气泡在企业级 UI 里偏"应用商店宣传图"风格)
        section_label = QLabel("接下来的流程")
        section_label.setObjectName("sectionLabel")

        content_layout.addSpacing(48)
        content_layout.addWidget(section_label)
        content_layout.addSpacing(8)

        # 耗时锚点:基于实测,网络好时各阶段大致区间。
        # 下载安装受 pnpm 镜像速度影响最大,给个上限让用户有心理预期。
        steps = [
            ("环境检测", "约 30 秒"),
            ("下载安装", "5–10 分钟"),
            ("自动配置", "约 1 分钟"),
            ("启动服务", "约 30 秒"),
        ]
        for i, (name, duration) in enumerate(steps):
            content_layout.addWidget(
                _make_step_row(f"{i + 1:02d}", name, duration)
            )
            if i < len(steps) - 1:
                content_layout.addWidget(_make_divider())

        content_layout.addStretch(1)

        scroll.setWidget(content)
        main_layout.addWidget(scroll, 1)

        # ── 底部按钮栏 ─────────────────────────────────────────────
        # 保留右对齐布局(主操作放右,符合 Win/Mac 阅读习惯)
        # 主按钮改用 slate-900 深色,极克制的强调色,不再使用饱和绿
        button_bar = QFrame()
        button_bar.setStyleSheet(
            "QFrame { background-color: #FAFBFC; border-top: 1px solid #E2E8F0; }"
        )

        button_layout = QHBoxLayout(button_bar)
        button_layout.setContentsMargins(56, 16, 56, 16)
        button_layout.setSpacing(8)
        button_layout.addStretch(1)

        # "退出"降级为文字链接:消除与主 CTA 的视觉权重对等问题。
        # 用户随时能从右上角×退出,这里只保留一个静音灰的兜底入口。
        self.exit_button = QPushButton("退出")
        self.exit_button.setFixedHeight(36)
        self.exit_button.setCursor(Qt.PointingHandCursor)
        self.exit_button.setStyleSheet(
            "QPushButton { color: #94A3B8; background: transparent; "
            "border: none; padding: 7px 12px; font-size: 13px; "
            "font-weight: 500; min-width: 0; }"
            "QPushButton:hover { color: #475569; }"
            "QPushButton:pressed { color: #0F172A; }"
        )
        self.exit_button.clicked.connect(self.exit_clicked.emit)

        self.next_button = QPushButton("开始安装")
        self.next_button.setObjectName("primaryButton")
        self.next_button.setFixedHeight(36)
        self.next_button.clicked.connect(self.next_clicked.emit)

        button_layout.addWidget(self.exit_button)
        button_layout.addWidget(self.next_button)

        main_layout.addWidget(button_bar)

        # 回车键直接触发主 CTA。QStackedWidget 里子页面 setDefault 不生效
        # (要 QDialog 父级),所以走 QShortcut。Qt.WidgetWithChildrenShortcut
        # 限定快捷键只在本页激活时响应,避免跨页串台。
        for seq in (QKeySequence(Qt.Key_Return), QKeySequence(Qt.Key_Enter)):
            sc = QShortcut(seq, self)
            sc.setContext(Qt.WidgetWithChildrenShortcut)
            sc.activated.connect(self._on_enter_pressed)

    def _on_enter_pressed(self) -> None:
        """回车推进主 CTA,前提是按钮启用且未隐藏。"""
        if self.next_button.isEnabled() and self.next_button.isVisible():
            self.next_button.click()
