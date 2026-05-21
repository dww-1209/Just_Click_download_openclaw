"""全局视觉主题(Theme)— 安装器与卸载器共用

为什么独立成模块:
- 安装器(launch_installer*.py 通过 InstallerWindow)和卸载器(launch_uninstaller.py)
  是两个不同的入口,但视觉风格必须保持一致——都是 OpenClaw 一键安装/卸载工具,
  用户感知上是同一产品。如果各自维护一份 QSS,改一处样式漏改另一处就会出现风格分裂。
- 抽离到这里后,两个入口都通过 `QApplication.setStyleSheet(GLOBAL_QSS)` 注入,
  改一次两边同时生效。
- UI 子页面(show_*.py)依然只读全局 QSS 暴露的 objectName / property,
  不允许 import 本模块内部细节,避免重新引入分层耦合。

设计 Token(企业级简约风格):
- 主色板: Slate (#0F172A 深 / #475569 中 / #94A3B8 静音 / #E2E8F0 边)
- 强调色: slate-900 主按钮(取代 Material Green,克制不喧宾夺主)
- 危险色: #B91C1C 降饱和红(取代 #DC3545)
- 状态色: 绿/橙/红仅用于 6×6 状态点 dot,不再大面积铺色
- 圆角:   6px 按钮/输入,8px 卡片/进度条,不用 16px 胶囊
- 字号:   11/12/13/14/28/32,用字重而非纯字号建立层级
"""

GLOBAL_QSS = """
/* 全局背景和字体 — 减少饱和、统一排版基线 */
QWidget {
    background-color: #FAFBFC;
    color: #0F172A;
    /* 字体优先级:
     * Qt 不识别 CSS 的 -apple-system 关键字,需要写真实字体名。
     * macOS 系统默认是 SF Pro,但 Qt 通过 ".AppleSystemUIFont" 别名访问;
     * 直接写 SF Pro 反而失败。所以策略是:Win 系统字体 → 中文兜底,
     * macOS 上让 sans-serif 兜底到系统默认。 */
    font-family: "Segoe UI", "PingFang SC", "Microsoft YaHei",
                 "Helvetica Neue", sans-serif;
    font-size: 13px;
}

QLabel {
    background: transparent;
    border: none;
    color: #0F172A;
}

/* ── 主按钮:slate-900 极克制强调色 ─────────────────────── */
QPushButton#primaryButton {
    background-color: #0F172A;
    color: white;
    border: none;
    border-radius: 6px;
    padding: 8px 20px;
    font-size: 13px;
    font-weight: 600;
    min-width: 88px;
}
QPushButton#primaryButton:hover { background-color: #1E293B; }
QPushButton#primaryButton:pressed { background-color: #334155; }
QPushButton#primaryButton:disabled {
    background-color: #E2E8F0;
    color: #94A3B8;
}

/* ── 次要按钮:描边样式 ─────────────────────────────────── */
QPushButton {
    background-color: white;
    color: #475569;
    border: 1px solid #CBD5E1;
    border-radius: 6px;
    padding: 7px 18px;
    font-size: 13px;
    font-weight: 500;
    min-width: 72px;
}
QPushButton:hover {
    background-color: #F1F5F9;
    color: #0F172A;
    border-color: #94A3B8;
}
QPushButton:pressed {
    background-color: #E2E8F0;
}
QPushButton:disabled {
    background-color: #F8FAFC;
    color: #CBD5E1;
    border-color: #E2E8F0;
}

/* ── 危险按钮:降饱和红,只在卸载确认这种破坏性操作上 ───── */
QPushButton#dangerButton {
    background-color: #B91C1C;
    color: white;
    border: none;
    border-radius: 6px;
    padding: 8px 20px;
    font-size: 13px;
    font-weight: 600;
    min-width: 88px;
}
QPushButton#dangerButton:hover { background-color: #991B1B; }
QPushButton#dangerButton:pressed { background-color: #7F1D1D; }
QPushButton#dangerButton:disabled {
    background-color: #E2E8F0;
    color: #94A3B8;
}

/* ── 顶栏步骤指示器(仅安装器使用) ───────────────────── */
QLabel#stepIndicatorItem {
    padding: 4px 0;
    font-size: 12px;
    font-weight: 500;
    letter-spacing: 0.2px;
}
QLabel#stepIndicatorItem[state="pending"] {
    color: #94A3B8;
}
QLabel#stepIndicatorItem[state="active"] {
    color: #0F172A;
    font-weight: 600;
    border-bottom: 2px solid #0F172A;
}
QLabel#stepIndicatorItem[state="done"] {
    color: #475569;
}

/* ── 日志区:深色背景,与企业级 IDE/终端样式一致 ────────── */
QPlainTextEdit#logArea, QTextEdit#logArea {
    background-color: #0F172A;
    color: #CBD5E1;
    font-family: "JetBrains Mono", "SF Mono", "Cascadia Code",
                 "Fira Code", Consolas, monospace;
    font-size: 12px;
    border-radius: 8px;
    padding: 12px;
    border: none;
    selection-background-color: #334155;
}
QPlainTextEdit#logArea:focus, QTextEdit#logArea:focus {
    border: none;
    outline: none;
}

/* ── 进度条:细线条 + 深色填充,不用饱和绿 ──────────────── */
QProgressBar {
    border: none;
    background-color: #E2E8F0;
    border-radius: 4px;
    height: 6px;
    text-align: center;
    color: #64748B;
    font-size: 11px;
    font-weight: 500;
}
QProgressBar::chunk {
    background-color: #0F172A;
    border-radius: 4px;
}

/* 危险进度条:卸载场景,降饱和红 */
QProgressBar#dangerProgressBar {
    border: none;
    background-color: #E2E8F0;
    border-radius: 4px;
    height: 6px;
    text-align: center;
}
QProgressBar#dangerProgressBar::chunk {
    background-color: #B91C1C;
    border-radius: 4px;
}

/* ── 输入框:1px 描边 + 聚焦深色边 ──────────────────────── */
QLineEdit {
    background-color: white;
    border: 1px solid #CBD5E1;
    border-radius: 6px;
    padding: 8px 12px;
    font-size: 13px;
    color: #0F172A;
    selection-background-color: #E2E8F0;
}
QLineEdit:focus {
    border: 1px solid #0F172A;
}
QLineEdit:disabled {
    background-color: #F8FAFC;
    color: #94A3B8;
}
QLineEdit:read-only {
    background-color: #F8FAFC;
    color: #475569;
}

/* ── 下拉框 ──────────────────────────────────────────── */
QComboBox {
    background-color: white;
    border: 1px solid #CBD5E1;
    border-radius: 6px;
    padding: 7px 10px;
    font-size: 13px;
    color: #0F172A;
}
QComboBox:focus {
    border: 1px solid #0F172A;
}
QComboBox::drop-down {
    border: none;
    width: 24px;
}
QComboBox QAbstractItemView {
    background-color: white;
    border: 1px solid #CBD5E1;
    border-radius: 6px;
    padding: 4px;
    selection-background-color: #F1F5F9;
    selection-color: #0F172A;
    outline: none;
}

/* ── 滚动条:细且静音,只在悬停时显眼 ───────────────────── */
QScrollBar:vertical {
    background: transparent;
    width: 10px;
    margin: 4px 2px 4px 0;
}
QScrollBar::handle:vertical {
    background: #CBD5E1;
    border-radius: 4px;
    min-height: 30px;
}
QScrollBar::handle:vertical:hover { background: #94A3B8; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0;
}
QScrollBar:horizontal {
    background: transparent;
    height: 10px;
    margin: 0 4px 2px 4px;
}
QScrollBar::handle:horizontal {
    background: #CBD5E1;
    border-radius: 4px;
    min-width: 30px;
}
QScrollBar::handle:horizontal:hover { background: #94A3B8; }
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
    width: 0;
}

/* ── 复选框 ──────────────────────────────────────────── */
QCheckBox {
    color: #0F172A;
    spacing: 8px;
    font-size: 13px;
}
QCheckBox::indicator {
    width: 16px;
    height: 16px;
    border: 1px solid #CBD5E1;
    border-radius: 3px;
    background-color: white;
}
QCheckBox::indicator:hover { border-color: #94A3B8; }
QCheckBox::indicator:checked {
    background-color: #0F172A;
    border-color: #0F172A;
    image: none;
}
"""
