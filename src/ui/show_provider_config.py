"""Provider 配置页面（US-03）—— 多选模型 + 汇总选默认 + 配置导入导出。

职责：为用户提供可视化的 AI 模型提供商配置界面，支持：
1. 展开/折叠各供应商卡片，填写 API Key 并多选模型；
2. 添加自定义模型（兼容官方最新未预设模型）；
3. 汇总已选模型并指定全局默认模型；
4. 配置的 JSON 导入/导出，便于备份与迁移。
该页面既可在安装流程中作为 US-03 使用，也可在已安装场景下通过环境检测页进入。
"""

import json
import re
from typing import Any

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QPushButton, QHBoxLayout, QFrame,
    QLineEdit, QComboBox, QScrollArea, QFileDialog, QMessageBox,
    QGraphicsDropShadowEffect, QCheckBox,
)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont, QColor

from src.models.provider_config import (
    VENDOR_REGISTRY,
    API_PROTOCOL_LABELS,
    API_PROTOCOL_BASE_URL_HINTS,
    API_PROTOCOL_OPENAI_COMPLETIONS,
    RESERVED_PROVIDER_IDS,
    CUSTOM_VENDOR_ID,
)


# 自定义 Provider ID 校验正则:小写字母开头,允许字母数字短横线,长度 2-32
_CUSTOM_PROVIDER_ID_RE = re.compile(r"^[a-z][a-z0-9-]{1,31}$")


# ═══════════════════════════════════════════════════════════════════
# 内联组件
# ═══════════════════════════════════════════════════════════════════

class PrimaryButton(QPushButton):
    """主操作按钮 —— 使用 primaryButton 样式，视觉上突出，用于「保存并启动」等关键操作。"""

    def __init__(self, text: str, parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        self.setCursor(Qt.PointingHandCursor)
        self.setObjectName("primaryButton")


class SecondaryButton(QPushButton):
    """次要操作按钮 —— 默认样式，用于「返回」「跳过」「导入/导出」等低频操作。"""

    def __init__(self, text: str, parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        self.setCursor(Qt.PointingHandCursor)


class VendorRow(QFrame):
    """供应商配置行 —— 可展开/折叠的卡片式组件。

    职责：封装单个供应商（如 Kimi、DeepSeek）的全部配置交互，包括：
    - Key Type 切换（标准 API / Coding Plan 等）
    - API Key 输入（密码模式，防止旁窥）
    - 预设模型多选（带推理标签）
    - 自定义模型添加/删除

    设计采用「手风琴」交互：同一时刻 ProviderConfigPage 只允许一个 VendorRow 展开，
    避免多个供应商同时展开导致页面过长、信息过载。
    """

    toggled = Signal(str)           # 展开/折叠状态变化时触发，携带 vendor_id，用于父级实现互斥折叠
    model_selection_changed = Signal()  # 模型勾选状态变化时触发，用于刷新汇总区域

    def __init__(self, vendor, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.vendor = vendor
        self.is_expanded = False
        self._key_type_state: dict[str, dict[str, Any]] = {}     # {key_type_key: {"api_key": "", "selected": set()}}
        self._custom_models: list[tuple[str, str, str]] = []      # [(model_ref, display_name, key_type_key), ...]
        self._model_checkboxes: dict[str, QCheckBox] = {}   # {model_ref: QCheckBox}
        self._current_key_type: str | None = None

        self._setup_ui()

    def _setup_ui(self) -> None:
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # 标题行（可点击展开/折叠）
        # 使用浅灰背景 + 圆角边框，与白色内容区形成层次对比
        self.header = QFrame()
        self.header.setStyleSheet(
            "QFrame { background-color: #f8f9fa; border-radius: 6px; "
            "border: 1px solid #e9ecef; }"
        )
        self.header.setCursor(Qt.PointingHandCursor)
        self.header.mousePressEvent = lambda e: self._toggle()

        header_layout = QHBoxLayout(self.header)
        header_layout.setContentsMargins(12, 10, 12, 10)

        self.title_label = QLabel(f"{self.vendor.icon} {self.vendor.name}")
        title_font = QFont()
        title_font.setPointSize(13)
        title_font.setBold(True)
        self.title_label.setFont(title_font)
        self.title_label.setStyleSheet("color: #333;")

        self.arrow_label = QLabel("▶")
        self.arrow_label.setStyleSheet("color: #888; font-size: 14px;")

        header_layout.addWidget(self.title_label)
        header_layout.addStretch(1)
        header_layout.addWidget(self.arrow_label)

        # 内容区域（默认折叠）
        # 白色背景 + 略深的边框，视觉上从标题行「下沉」一层
        self.content = QFrame()
        self.content.setStyleSheet(
            "QFrame { background-color: #ffffff; border-radius: 6px; "
            "border: 1px solid #e0e0e0; margin-top: 4px; }"
        )
        content_layout = QVBoxLayout(self.content)
        content_layout.setContentsMargins(14, 14, 14, 14)
        content_layout.setSpacing(10)

        # Key Type 选择：仅当供应商提供多种 Key 类型（如标准 API vs Coding Plan）时显示下拉框。
        # 不同 Key Type 对应不同的 base_url、env_var 和模型列表，必须严格区分，避免混用。
        if len(self.vendor.key_types) > 1:
            kt_layout = QHBoxLayout()
            kt_label = QLabel("Key 类型:")
            kt_label.setStyleSheet("font-weight: bold; color: #555;")
            self.key_type_combo = QComboBox()
            for kt in self.vendor.key_types:
                self.key_type_combo.addItem(kt.label, kt.key)
            self.key_type_combo.currentIndexChanged.connect(self._on_key_type_changed)
            kt_layout.addWidget(kt_label)
            kt_layout.addWidget(self.key_type_combo, 1)
            content_layout.addLayout(kt_layout)
        else:
            self.key_type_combo = None

        # API Key 输入：使用 Password 模式隐藏明文，防止屏幕共享或旁窥时泄露
        key_layout = QHBoxLayout()
        key_label = QLabel("API Key:")
        key_label.setStyleSheet("font-weight: bold; color: #555;")
        self.key_input = QLineEdit()
        self.key_input.setEchoMode(QLineEdit.Password)
        self.key_input.setPlaceholderText("请输入 API Key")
        key_layout.addWidget(key_label)
        key_layout.addWidget(self.key_input, 1)
        content_layout.addLayout(key_layout)

        # 模型列表：多选框形式，每个模型显示名称 + ref，推理模型额外标注 [推理]
        models_label = QLabel("选择模型（可多选）:")
        models_label.setStyleSheet("font-weight: bold; color: #555;")
        content_layout.addWidget(models_label)

        self.models_container = QWidget()
        self.models_layout = QVBoxLayout(self.models_container)
        self.models_layout.setContentsMargins(0, 0, 0, 0)
        self.models_layout.setSpacing(4)
        content_layout.addWidget(self.models_container)

        # 自定义模型：允许用户输入官方最新但未在预设列表中的模型 ID。
        # 自动补全 vendor prefix（如 moonshot/），减少用户输入错误。
        custom_layout = QHBoxLayout()
        custom_label = QLabel("自定义模型:")
        custom_label.setStyleSheet("font-weight: bold; color: #555;")
        self.custom_input = QLineEdit()
        prefix = self.vendor.key_types[0].model_prefix if self.vendor.key_types else ""
        self.custom_input.setPlaceholderText(
            f"输入模型 ID，如 {prefix}my-model" if prefix else "输入模型 ID"
        )
        add_btn = QPushButton("添加")
        add_btn.setFixedSize(70, 28)
        add_btn.clicked.connect(self._add_custom_model)
        custom_layout.addWidget(custom_label)
        custom_layout.addWidget(self.custom_input, 1)
        custom_layout.addWidget(add_btn)
        content_layout.addLayout(custom_layout)

        main_layout.addWidget(self.header)
        main_layout.addWidget(self.content)
        self.content.hide()

        # 初始化：默认选中第一个 Key Type 并加载对应模型列表
        if self.vendor.key_types:
            self._current_key_type = self.vendor.key_types[0].key
        self._refresh_models()

    def _toggle(self) -> None:
        self.is_expanded = not self.is_expanded
        self.content.setVisible(self.is_expanded)
        self.arrow_label.setText("▼" if self.is_expanded else "▶")
        self.toggled.emit(self.vendor.id)

    def collapse(self) -> None:
        self.is_expanded = False
        self.content.hide()
        self.arrow_label.setText("▶")

    def _on_key_type_changed(self, index: int) -> None:
        self._save_current_state()
        key_type_key = self.key_type_combo.itemData(index)
        self._current_key_type = key_type_key
        self._refresh_models()
        self._restore_state()

    def _save_current_state(self) -> None:
        if not self._current_key_type:
            return
        selected: set[str] = set()
        for ref, cb in self._model_checkboxes.items():
            if cb.isChecked():
                selected.add(ref)
        self._key_type_state[self._current_key_type] = {
            "api_key": self.key_input.text(),
            "selected": selected,
        }

    def _restore_state(self) -> None:
        if not self._current_key_type:
            return
        state = self._key_type_state.get(self._current_key_type, {})
        self.key_input.setText(state.get("api_key", ""))
        selected = state.get("selected", set())
        for ref, cb in self._model_checkboxes.items():
            cb.setChecked(ref in selected)

    def _refresh_models(self) -> None:
        while self.models_layout.count():
            item = self.models_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._model_checkboxes.clear()

        if not self._current_key_type:
            return

        key_type_info = None
        for kt in self.vendor.key_types:
            if kt.key == self._current_key_type:
                key_type_info = kt
                break
        if not key_type_info:
            return

        for model in key_type_info.models:
            cb = QCheckBox(f"{model.name}  ({model.ref})")
            if model.reasoning:
                cb.setText(f"{model.name}  ({model.ref})  [推理]")
            cb.stateChanged.connect(self._on_model_changed)
            self._model_checkboxes[model.ref] = cb
            self.models_layout.addWidget(cb)

        for ref, name, kt_key in self._custom_models:
            if kt_key != self._current_key_type:
                continue
            row_widget = QWidget()
            row_layout = QHBoxLayout(row_widget)
            row_layout.setContentsMargins(0, 0, 0, 0)
            row_layout.setSpacing(4)

            cb = QCheckBox(f"{name}  ({ref})  [自定义]")
            cb.setChecked(True)
            cb.stateChanged.connect(self._on_model_changed)
            self._model_checkboxes[ref] = cb

            del_btn = QPushButton("✕")
            del_btn.setFixedSize(24, 24)
            del_btn.setStyleSheet(
                "QPushButton { border: none; color: #999; font-size: 14px; background: transparent; }"
                "QPushButton:hover { color: #e74c3c; }"
            )
            del_btn.setCursor(Qt.PointingHandCursor)
            del_btn.clicked.connect(lambda checked, r=ref: self._remove_custom_model(r))

            row_layout.addWidget(cb)
            row_layout.addWidget(del_btn)
            row_layout.addStretch(1)
            self.models_layout.addWidget(row_widget)

        self._restore_state()

    def _add_custom_model(self) -> None:
        text = self.custom_input.text().strip()
        if not text:
            return
        prefix = ""
        for kt in self.vendor.key_types:
            if kt.key == self._current_key_type:
                prefix = kt.model_prefix
                break
        if "/" not in text and prefix:
            ref = f"{prefix}{text}"
        else:
            ref = text
        name = text.split("/")[-1] if "/" in text else text
        key_type = self._current_key_type or ""
        if not any(r == ref and k == key_type for r, n, k in self._custom_models):
            self._custom_models.append((ref, name, key_type))
        self.custom_input.clear()
        self._refresh_models()
        self.model_selection_changed.emit()

    def _remove_custom_model(self, ref: str) -> None:
        key_type = self._current_key_type or ""
        self._custom_models = [(r, n, k) for r, n, k in self._custom_models if not (r == ref and k == key_type)]
        self._save_current_state()
        self._refresh_models()
        self.model_selection_changed.emit()

    def _on_model_changed(self) -> None:
        self.model_selection_changed.emit()

    def has_any_config(self) -> bool:
        return bool(self.key_input.text().strip())

    def get_all_selected_models(self) -> list[str]:
        all_selected: set[str] = set()
        for ref, cb in self._model_checkboxes.items():
            if cb.isChecked():
                all_selected.add(ref)
        for state in self._key_type_state.values():
            all_selected.update(state.get("selected", set()))
        return list(all_selected)

    def get_all_configs(self) -> list[dict[str, Any]]:
        configs: list[dict[str, Any]] = []
        self._save_current_state()
        for key_type_key, state in self._key_type_state.items():
            api_key = state.get("api_key", "").strip()
            selected = state.get("selected", set())
            if not api_key and not selected:
                continue
            kt_info = None
            for kt in self.vendor.key_types:
                if kt.key == key_type_key:
                    kt_info = kt
                    break
            if not kt_info:
                continue
            configs.append({
                "vendor_id": self.vendor.id,
                "key_type": key_type_key,
                "api_key": api_key,
                "selected_models": list(selected),
                "base_url": kt_info.base_url,
                "env_var": kt_info.env_var,
                "auth_choice": kt_info.auth_choice,
            })
        return configs

    def load_config(self, api_key: str, selected_models: list[str], key_type: str) -> None:
        matched_kt = None
        for i, kt in enumerate(self.vendor.key_types):
            if kt.key == key_type:
                matched_kt = kt
                if self.key_type_combo:
                    self.key_type_combo.setCurrentIndex(i)
                self._current_key_type = kt.key
                break
        if not matched_kt and self.vendor.key_types:
            matched_kt = self.vendor.key_types[0]
            self._current_key_type = matched_kt.key

        self.key_input.setText(api_key or "")

        selected_set: set[str] = set(selected_models) if selected_models else set()
        self._key_type_state[self._current_key_type] = {
            "api_key": api_key or "",
            "selected": selected_set,
        }

        preset_refs: set[str] = set()
        if matched_kt:
            for m in matched_kt.models:
                preset_refs.add(m.ref)

        self._custom_models = []
        for ref in list(selected_set):
            if ref not in preset_refs:
                name = ref.split("/")[-1] if "/" in ref else ref
                self._custom_models.append((ref, name, self._current_key_type))
                selected_set.discard(ref)

        self._key_type_state[self._current_key_type]["selected"] = selected_set
        self._refresh_models()

    def _refresh_for_key_type(self, index: int) -> None:
        if self.key_type_combo:
            self.key_type_combo.setCurrentIndex(index)
            key_type_key = self.key_type_combo.itemData(index)
            self._current_key_type = key_type_key
            self._refresh_models()
        else:
            self._current_key_type = self.vendor.key_types[0].key if self.vendor.key_types else None
            self._refresh_models()


class CustomVendorRow(QFrame):
    """自定义 Provider 配置行 —— 让用户填写任意 OpenAI/Anthropic 兼容端点。

    与 VendorRow 不同,本组件没有预设模型/Key Type/auth_choice;用户需要自填:
    - Provider ID(写入 openclaw.json 的 models.providers.<id> key)
    - 协议类型(openai-completions / anthropic-messages / openai-responses)
    - baseUrl + apiKey
    - 模型 ID(至少 1 个,允许多选)+ 每个模型可选元数据(reasoning / contextWindow / maxTokens)

    架构定位:走 manage_openclaw._configure_custom_provider 直写 JSON,
    不走 openclaw onboard CLI(后者只支持 openai/anthropic 二选一,且每次启动 Node ~10s)。
    """

    toggled = Signal(str)
    model_selection_changed = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.is_expanded = False
        # 用户添加的模型列表: [(model_id, display_name, reasoning, context_window, max_tokens), ...]
        self._models: list[dict[str, Any]] = []
        self._model_checkboxes: dict[str, QCheckBox] = {}
        self._setup_ui()

    def _setup_ui(self) -> None:
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # 标题行(可点击展开/折叠),配色与 VendorRow 一致
        self.header = QFrame()
        self.header.setStyleSheet(
            "QFrame { background-color: #f8f9fa; border-radius: 6px; "
            "border: 1px solid #e9ecef; }"
        )
        self.header.setCursor(Qt.PointingHandCursor)
        self.header.mousePressEvent = lambda e: self._toggle()

        header_layout = QHBoxLayout(self.header)
        header_layout.setContentsMargins(12, 10, 12, 10)

        self.title_label = QLabel("⚙ 自定义 Provider")
        title_font = QFont()
        title_font.setPointSize(13)
        title_font.setBold(True)
        self.title_label.setFont(title_font)
        self.title_label.setStyleSheet("color: #333;")

        self.arrow_label = QLabel("▶")
        self.arrow_label.setStyleSheet("color: #888; font-size: 14px;")

        header_layout.addWidget(self.title_label)
        header_layout.addStretch(1)
        header_layout.addWidget(self.arrow_label)

        # 内容区
        self.content = QFrame()
        self.content.setStyleSheet(
            "QFrame { background-color: #ffffff; border-radius: 6px; "
            "border: 1px solid #e0e0e0; margin-top: 4px; }"
        )
        content_layout = QVBoxLayout(self.content)
        content_layout.setContentsMargins(14, 14, 14, 14)
        content_layout.setSpacing(10)

        # 1. Provider ID
        pid_layout = QHBoxLayout()
        pid_label = QLabel("Provider ID:")
        pid_label.setStyleSheet("font-weight: bold; color: #555;")
        pid_label.setMinimumWidth(90)
        self.provider_id_input = QLineEdit()
        self.provider_id_input.setPlaceholderText("如 my-openai、custom-claude (小写字母数字短横线)")
        pid_layout.addWidget(pid_label)
        pid_layout.addWidget(self.provider_id_input, 1)
        content_layout.addLayout(pid_layout)

        # 2. 协议类型
        proto_layout = QHBoxLayout()
        proto_label = QLabel("协议类型:")
        proto_label.setStyleSheet("font-weight: bold; color: #555;")
        proto_label.setMinimumWidth(90)
        self.protocol_combo = QComboBox()
        for proto_value, proto_label_text in API_PROTOCOL_LABELS:
            self.protocol_combo.addItem(proto_label_text, proto_value)
        # 默认选 OpenAI 兼容(覆盖 99% 场景)
        self.protocol_combo.setCurrentIndex(0)
        # 协议切换时自动更新 baseUrl 占位符,降低用户填写负担
        self.protocol_combo.currentIndexChanged.connect(self._on_protocol_changed)
        proto_layout.addWidget(proto_label)
        proto_layout.addWidget(self.protocol_combo, 1)
        content_layout.addLayout(proto_layout)

        proto_hint = QLabel(
            "OpenAI 兼容: GPT/DeepSeek/绝大多数 OpenAI 兼容代理  ·  "
            "Anthropic 兼容: Claude 官方/MiniMax  ·  "
            "Responses API: LM Studio/OpenAI 新版"
        )
        proto_hint.setStyleSheet("color: #888; font-size: 11px;")
        proto_hint.setWordWrap(True)
        content_layout.addWidget(proto_hint)

        # 3. Base URL
        url_layout = QHBoxLayout()
        url_label = QLabel("API 端点:")
        url_label.setStyleSheet("font-weight: bold; color: #555;")
        url_label.setMinimumWidth(90)
        self.base_url_input = QLineEdit()
        self.base_url_input.setPlaceholderText(API_PROTOCOL_BASE_URL_HINTS[API_PROTOCOL_OPENAI_COMPLETIONS])
        url_layout.addWidget(url_label)
        url_layout.addWidget(self.base_url_input, 1)
        content_layout.addLayout(url_layout)

        # 4. API Key
        key_layout = QHBoxLayout()
        key_label = QLabel("API Key:")
        key_label.setStyleSheet("font-weight: bold; color: #555;")
        key_label.setMinimumWidth(90)
        self.key_input = QLineEdit()
        self.key_input.setEchoMode(QLineEdit.Password)
        self.key_input.setPlaceholderText("sk-...")
        key_layout.addWidget(key_label)
        key_layout.addWidget(self.key_input, 1)
        content_layout.addLayout(key_layout)

        # 5. 模型列表区
        models_label = QLabel("模型(至少添加 1 个):")
        models_label.setStyleSheet("font-weight: bold; color: #555;")
        content_layout.addWidget(models_label)

        # 默认值说明: 让用户知道有自动兜底,无需操心 contextWindow / maxTokens / reasoning。
        # 上游 OpenClaw 对自定义 provider 的兜底为: contextWindow=200000、maxTokens=8192、
        # reasoning=False(参见 manage_openclaw._configure_custom_provider)。99% 场景够用,
        # 如需调整可通过导入完整 JSON 配置覆盖。
        models_hint = QLabel(
            "使用上游默认参数: 上下文 200K tokens / 单次输出 8K tokens。"
            "如有特殊需求请通过「导入配置」加载自定义 JSON。"
        )
        models_hint.setStyleSheet("color: #888; font-size: 11px;")
        models_hint.setWordWrap(True)
        content_layout.addWidget(models_hint)

        self.models_container = QWidget()
        self.models_layout = QVBoxLayout(self.models_container)
        self.models_layout.setContentsMargins(0, 0, 0, 0)
        self.models_layout.setSpacing(4)
        content_layout.addWidget(self.models_container)

        # 添加模型行: 仅保留「模型 ID + 显示名 + 添加按钮」三个字段。
        # 删除原有的 reasoning / contextWindow / maxTokens 输入框——这三个字段对非技术
        # 用户极易造成困惑(reasoning 难判断;ctx/max tokens 大多数人不知道自己模型的
        # 真实值,容易乱填),且后端 manage_openclaw 已对缺省值做了完整兜底(参见
        # _configure_custom_provider 的 meta.get(...) 默认值)。需要精细控制的高级用户
        # 可通过「导入配置」加载完整 JSON。
        add_layout = QHBoxLayout()
        self.add_model_id = QLineEdit()
        self.add_model_id.setPlaceholderText("模型 ID(如 gpt-5.2 / deepseek-chat)")
        self.add_model_name = QLineEdit()
        self.add_model_name.setPlaceholderText("显示名(可选,默认与模型 ID 相同)")

        add_btn = QPushButton("添加")
        add_btn.setFixedSize(70, 28)
        add_btn.clicked.connect(self._add_model)

        add_layout.addWidget(self.add_model_id, 2)
        add_layout.addWidget(self.add_model_name, 2)
        add_layout.addWidget(add_btn)
        content_layout.addLayout(add_layout)

        main_layout.addWidget(self.header)
        main_layout.addWidget(self.content)
        self.content.hide()

    def _toggle(self) -> None:
        self.is_expanded = not self.is_expanded
        self.content.setVisible(self.is_expanded)
        self.arrow_label.setText("▼" if self.is_expanded else "▶")
        self.toggled.emit(CUSTOM_VENDOR_ID)

    def collapse(self) -> None:
        self.is_expanded = False
        self.content.hide()
        self.arrow_label.setText("▶")

    def _on_protocol_changed(self, index: int) -> None:
        """切换协议时刷新 baseUrl 占位符。

        只改占位符不改实际内容: 用户已经填了的 URL 不能被自动覆盖,否则容易丢数据。
        """
        proto = self.protocol_combo.itemData(index)
        hint = API_PROTOCOL_BASE_URL_HINTS.get(proto, "")
        self.base_url_input.setPlaceholderText(hint)

    def _add_model(self) -> None:
        model_id = self.add_model_id.text().strip()
        if not model_id:
            return
        # 简单去重:同 model_id 已存在则忽略
        if any(m["id"] == model_id for m in self._models):
            self.add_model_id.clear()
            return
        display_name = self.add_model_name.text().strip() or model_id
        # reasoning / contextWindow / maxTokens 写死默认值。
        # 这些字段在 model_metadata 中仍然透传给 manage_openclaw,以保持
        # _configure_custom_provider 的数据契约稳定;但 UI 层不再让用户填写。
        # 默认值与上游兜底一致(参见 manage_openclaw 的 meta.get(..., default))。
        self._models.append({
            "id": model_id,
            "name": display_name,
            "reasoning": False,
            "contextWindow": 200000,
            "maxTokens": 8192,
        })
        self.add_model_id.clear()
        self.add_model_name.clear()
        self._refresh_model_rows()
        self.model_selection_changed.emit()

    def _remove_model(self, model_id: str) -> None:
        self._models = [m for m in self._models if m["id"] != model_id]
        self._refresh_model_rows()
        self.model_selection_changed.emit()

    def _refresh_model_rows(self) -> None:
        # 清空旧 widgets
        while self.models_layout.count():
            item = self.models_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._model_checkboxes.clear()

        if not self._models:
            empty = QLabel("(暂无模型,使用下方表单添加)")
            empty.setStyleSheet("color: #aaa; font-size: 11px; padding: 4px 0;")
            self.models_layout.addWidget(empty)
            return

        for m in self._models:
            row_widget = QWidget()
            row_layout = QHBoxLayout(row_widget)
            row_layout.setContentsMargins(0, 0, 0, 0)
            row_layout.setSpacing(4)

            # 注: reasoning 字段不再由 UI 暴露,但导入旧配置时可能仍为 True,
            # 兼容显示 [推理] 标签;新添加的模型 reasoning 恒为 False。
            tag = "  [推理]" if m.get("reasoning") else ""
            cb = QCheckBox(f"{m['name']}  ({m['id']}){tag}")
            cb.setChecked(True)
            cb.stateChanged.connect(self._on_model_changed)
            self._model_checkboxes[m["id"]] = cb

            del_btn = QPushButton("✕")
            del_btn.setFixedSize(24, 24)
            del_btn.setStyleSheet(
                "QPushButton { border: none; color: #999; font-size: 14px; background: transparent; }"
                "QPushButton:hover { color: #e74c3c; }"
            )
            del_btn.setCursor(Qt.PointingHandCursor)
            del_btn.clicked.connect(lambda _checked, mid=m["id"]: self._remove_model(mid))

            row_layout.addWidget(cb)
            row_layout.addWidget(del_btn)
            row_layout.addStretch(1)
            self.models_layout.addWidget(row_widget)

    def _on_model_changed(self) -> None:
        self.model_selection_changed.emit()

    # ─────────────────────────────── 对外 API（与 VendorRow 接口对齐）

    def has_any_config(self) -> bool:
        return bool(
            self.provider_id_input.text().strip()
            or self.base_url_input.text().strip()
            or self.key_input.text().strip()
            or self._models
        )

    def get_all_selected_models(self) -> list[str]:
        provider_id = self.provider_id_input.text().strip()
        if not provider_id:
            return []
        # 自定义 Provider 的 model ref 形式: <provider_id>/<model_id>
        return [
            f"{provider_id}/{m['id']}"
            for m in self._models
            if self._model_checkboxes.get(m["id"]) and self._model_checkboxes[m["id"]].isChecked()
        ]

    def validate(self) -> tuple[bool, str]:
        """保存前的字段校验。返回 (是否合法, 错误消息)。

        规则:
        - provider_id: 必填,正则 ^[a-z][a-z0-9-]{1,31}$,不能与上游内置 ID 冲突
        - base_url: 必填,本地地址允许 http,其他必须 https
        - api_key: 必填,长度 ≥ 10
        - 至少 1 个模型
        """
        provider_id = self.provider_id_input.text().strip()
        if not provider_id:
            return False, "Provider ID 不能为空"
        if not _CUSTOM_PROVIDER_ID_RE.match(provider_id):
            return False, "Provider ID 格式不合法(只允许小写字母/数字/短横线,2-32 字符,字母开头)"
        if provider_id in RESERVED_PROVIDER_IDS:
            return False, f"Provider ID '{provider_id}' 与 OpenClaw 内置 Provider 冲突,请换一个"

        base_url = self.base_url_input.text().strip()
        if not base_url:
            return False, "API 端点 URL 不能为空"
        if not (base_url.startswith("https://") or base_url.startswith("http://localhost") or base_url.startswith("http://127.0.0.1")):
            return False, "API 端点必须以 https:// 开头(本地端点 localhost/127.0.0.1 可用 http://)"

        api_key = self.key_input.text().strip()
        if not api_key:
            return False, "API Key 不能为空"
        if len(api_key) < 10:
            return False, "API Key 看起来太短(< 10 字符),请确认填写正确"

        if not self._models:
            return False, "请至少添加 1 个模型"

        return True, ""

    def get_config(self) -> dict[str, Any] | None:
        """返回单个自定义 Provider 的配置字典(与 VendorRow.get_all_configs 输出格式对齐)。

        返回 None 表示用户没填写任何内容(整张卡片为空,跳过)。
        """
        if not self.has_any_config():
            return None

        provider_id = self.provider_id_input.text().strip()
        # 收集勾选的模型(被取消勾选的不参与配置)
        selected_refs: list[str] = []
        model_metadata: dict[str, dict[str, Any]] = {}
        for m in self._models:
            cb = self._model_checkboxes.get(m["id"])
            if not cb or not cb.isChecked():
                continue
            ref = f"{provider_id}/{m['id']}"
            selected_refs.append(ref)
            model_metadata[ref] = {
                "name": m["name"],
                "reasoning": m["reasoning"],
                "contextWindow": m["contextWindow"],
                "maxTokens": m["maxTokens"],
            }

        return {
            "vendor_id": CUSTOM_VENDOR_ID,
            # 复用 key_type 字段作为用户填的 provider_id(_resolve_provider_id 据此返回)
            "key_type": provider_id,
            "api_key": self.key_input.text().strip(),
            "selected_models": selected_refs,
            "base_url": self.base_url_input.text().strip(),
            # 自定义 Provider 不写环境变量,直接 inline apiKey 到 models.providers
            "env_var": "",
            # 不走 onboard CLI,configure_providers 据此进入 _configure_custom_provider 分支
            "auth_choice": "",
            # 关键: 协议透传,manage_openclaw._configure_custom_provider 据此写 api 字段
            "api_protocol": self.protocol_combo.currentData() or API_PROTOCOL_OPENAI_COMPLETIONS,
            "model_metadata": model_metadata,
        }

    def reset(self) -> None:
        """清空所有字段(被 ProviderConfigPage.reset 调用)。"""
        self.provider_id_input.clear()
        self.base_url_input.clear()
        self.key_input.clear()
        self.protocol_combo.setCurrentIndex(0)
        self._models = []
        self.add_model_id.clear()
        self.add_model_name.clear()
        self._refresh_model_rows()
        if self.is_expanded:
            self.collapse()


class ProviderConfigPage(QWidget):
    """Provider 配置页面（US-03）—— 多选模型 + 汇总选默认 + 配置导入导出。

    职责：为用户提供可视化的 AI 模型提供商配置界面，支持展开/折叠供应商卡片、
    填写 API Key、多选预设模型、添加自定义模型、指定全局默认模型，以及配置的
    JSON 导入/导出。该页面既可在安装流程中作为 US-03 使用，也可在已安装场景下
    通过环境检测页进入。
    """

    back_clicked = Signal()              # 用户点击「返回」，回到上一页
    skip_clicked = Signal()              # 用户点击「跳过」，跳过模型配置直接进入启动页
    save_and_start_clicked = Signal(dict)  # 用户点击「保存并启动」，携带完整配置字典发射

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.vendor_rows: dict[str, VendorRow] = {}
        self.custom_row: CustomVendorRow | None = None  # 单实例自定义 Provider 卡片
        self._setup_ui()

    def _setup_ui(self) -> None:
        # 主布局：上部为可滚动内容区，下部为固定按钮栏。
        # 使用 QScrollArea 包裹供应商列表，避免供应商过多时页面无限伸长。
        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(10)
        main_layout.setContentsMargins(24, 24, 24, 24)

        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameShape(QScrollArea.NoFrame)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        content_widget = QWidget()
        layout = QVBoxLayout(content_widget)
        layout.setSpacing(12)
        layout.setContentsMargins(10, 10, 10, 10)

        # 标题与说明
        title = QLabel("配置 AI 模型提供商")
        title.setAlignment(Qt.AlignCenter)
        title_font = QFont()
        title_font.setPointSize(18)
        title_font.setBold(True)
        title.setFont(title_font)

        desc = QLabel("点击供应商展开配置，填写 API Key 后多选模型，支持添加官方最新模型。")
        desc.setAlignment(Qt.AlignCenter)
        desc.setWordWrap(True)
        desc.setStyleSheet("color: #666; font-size: 12px;")

        # 提示标语：黄色警告卡片，强调 Key 类型与模型不可混用。
        # 设计原因：实际支持中频繁出现用户将 Coding Plan Key 用于标准模型，
        # 导致请求 401/403，因此用醒目的顶部横幅提前预警。
        hint_frame = QFrame()
        hint_frame.setStyleSheet(
            "QFrame { background-color: #fff8e1; border-radius: 6px; "
            "border: 1px solid #ffe082; }"
        )
        hint_shadow = QGraphicsDropShadowEffect(hint_frame)
        hint_shadow.setBlurRadius(12)
        hint_shadow.setColor(QColor(255, 193, 7, 15))
        hint_shadow.setOffset(0, 2)
        hint_frame.setGraphicsEffect(hint_shadow)
        hint_layout = QHBoxLayout(hint_frame)
        hint_layout.setContentsMargins(12, 8, 12, 8)

        hint_icon = QLabel("!")
        hint_icon.setStyleSheet(
            "background-color: #ffa726; color: white; font-weight: bold; "
            "border-radius: 10px; padding: 2px 8px; font-size: 12px;"
        )
        hint_icon.setAlignment(Qt.AlignCenter)
        hint_icon.setFixedSize(24, 24)

        hint_text = QLabel("请确认您的 API Key 类型：标准 API（按量付费）和 Coding Plan（订阅）使用不同的模型，请勿混用。")
        hint_text.setStyleSheet("color: #e65100; font-size: 12px;")
        hint_text.setWordWrap(True)

        hint_layout.addWidget(hint_icon)
        hint_layout.addWidget(hint_text, 1)

        # 供应商列表：遍历 VENDOR_REGISTRY 为每个供应商创建 VendorRow 卡片。
        # 手风琴交互由 _on_vendor_toggled 实现互斥折叠。
        list_frame = QFrame()
        list_layout = QVBoxLayout(list_frame)
        list_layout.setSpacing(8)
        list_layout.setContentsMargins(0, 0, 0, 0)

        for vendor in VENDOR_REGISTRY:
            row = VendorRow(vendor)
            row.toggled.connect(self._on_vendor_toggled)
            row.model_selection_changed.connect(self._refresh_summary)
            self.vendor_rows[vendor.id] = row
            list_layout.addWidget(row)

        # 自定义 Provider 卡片放在预设列表末尾,与其他 vendor 共用手风琴互斥逻辑。
        # 适用场景: GPT 官方/Claude 官方/海外用户自建代理/任意 OpenAI 或 Anthropic 兼容端点。
        self.custom_row = CustomVendorRow()
        self.custom_row.toggled.connect(self._on_vendor_toggled)
        self.custom_row.model_selection_changed.connect(self._refresh_summary)
        list_layout.addWidget(self.custom_row)

        # 汇总区域：蓝色卡片，展示所有供应商已选模型的汇总列表，
        # 并提供全局默认模型下拉框。fallback 模型自动从非默认已选模型中推导。
        self.summary_frame = QFrame()
        self.summary_frame.setStyleSheet(
            "QFrame { background-color: #f3f8ff; border-radius: 8px; border: 1px solid #c5d8f0; }"
        )
        sum_shadow = QGraphicsDropShadowEffect(self.summary_frame)
        sum_shadow.setBlurRadius(12)
        sum_shadow.setColor(QColor(21, 101, 192, 15))
        sum_shadow.setOffset(0, 2)
        self.summary_frame.setGraphicsEffect(sum_shadow)
        summary_layout = QVBoxLayout(self.summary_frame)
        summary_layout.setSpacing(8)
        summary_layout.setContentsMargins(14, 12, 14, 12)

        summary_title = QLabel("已选模型汇总")
        summary_title.setStyleSheet("font-weight: bold; font-size: 13px; color: #1565c0; margin-bottom: 4px;")

        self.summary_content = QLabel("请先配置 Provider 并选择模型")
        self.summary_content.setStyleSheet("color: #424242; font-size: 12px; line-height: 1.6;")
        self.summary_content.setWordWrap(True)

        default_layout = QHBoxLayout()
        default_layout.setSpacing(8)

        default_label = QLabel("全局默认模型:")
        default_label.setStyleSheet("font-weight: bold; color: #0d47a1; font-size: 12px;")

        self.default_model_combo = QComboBox()
        self.default_model_combo.setMinimumWidth(280)
        self.default_model_combo.setEnabled(False)
        self.default_model_combo.addItem("（请先配置并选择模型）", None)

        default_layout.addWidget(default_label)
        default_layout.addWidget(self.default_model_combo)
        default_layout.addStretch(1)

        fallback_hint = QLabel("其余已选模型将自动作为 fallback 备用")
        fallback_hint.setStyleSheet("color: #888; font-size: 11px;")

        summary_layout.addWidget(summary_title)
        summary_layout.addWidget(self.summary_content)
        summary_layout.addLayout(default_layout)
        summary_layout.addWidget(fallback_hint)

        layout.addWidget(title)
        layout.addWidget(desc)
        layout.addWidget(hint_frame)
        layout.addWidget(list_frame)
        layout.addWidget(self.summary_frame)

        scroll_area.setWidget(content_widget)
        main_layout.addWidget(scroll_area, 1)

        # 底部按钮
        # 布局顺序：返回 | 导入 | 导出 | 跳过 | 保存并启动
        # 主操作「保存并启动」放在最右侧，符合用户从左到右的扫描习惯。
        btn_layout = QHBoxLayout()
        btn_layout.setContentsMargins(10, 10, 10, 0)
        btn_layout.addStretch(1)

        self.back_button = SecondaryButton("返回")
        self.back_button.setFixedSize(100, 36)
        self.back_button.clicked.connect(self.back_clicked.emit)

        self.import_btn = SecondaryButton("导入配置")
        self.import_btn.setFixedSize(100, 36)
        self.import_btn.clicked.connect(self._on_import_config)

        self.export_btn = SecondaryButton("导出配置")
        self.export_btn.setFixedSize(100, 36)
        self.export_btn.clicked.connect(self._on_export_config)

        self.skip_button = SecondaryButton("跳过")
        self.skip_button.setFixedSize(100, 36)
        self.skip_button.clicked.connect(self.skip_clicked.emit)

        self.save_button = PrimaryButton("保存并启动")
        self.save_button.setFixedSize(120, 36)
        self.save_button.clicked.connect(self._on_save_clicked)

        btn_layout.addWidget(self.back_button)
        btn_layout.addWidget(self.import_btn)
        btn_layout.addWidget(self.export_btn)
        btn_layout.addWidget(self.skip_button)
        btn_layout.addWidget(self.save_button)

        main_layout.addLayout(btn_layout)

    # ─────────────────────────────── 供应商展开互斥

    def _on_vendor_toggled(self, vendor_id: str) -> None:
        """展开某个供应商时，折叠其他供应商，实现手风琴效果。

        设计原因：避免多个供应商同时展开导致页面过长、信息过载，
        同时减少用户在不同供应商间来回滚动查找的成本。
        自定义 Provider 卡片(vendor_id == CUSTOM_VENDOR_ID)和预设卡片共用同一组互斥逻辑。
        """
        for vid, row in self.vendor_rows.items():
            if vid != vendor_id and row.is_expanded:
                row.collapse()
        # 自定义 Provider 与预设互斥:展开预设时折叠自定义,反之亦然
        if self.custom_row and vendor_id != CUSTOM_VENDOR_ID and self.custom_row.is_expanded:
            self.custom_row.collapse()

    # ─────────────────────────────── 汇总刷新

    def _refresh_summary(self) -> None:
        """刷新汇总区域：收集所有 VendorRow 的已选模型，更新汇总文本和默认模型下拉框。"""
        all_models: list[tuple[str, str, str]] = []  # [(vendor_name, model_ref, model_name), ...]

        for vendor in VENDOR_REGISTRY:
            row = self.vendor_rows.get(vendor.id)
            if not row or not row.has_any_config():
                continue

            # 收集所有 key type 的已选模型
            all_refs = row.get_all_selected_models()
            # 为每个 ref 找显示名
            preset_names: dict[str, str] = {}
            for kt in vendor.key_types:
                for m in kt.models:
                    preset_names[m.ref] = m.name

            for model_ref in all_refs:
                name = preset_names.get(model_ref, None)
                if name is None:
                    name = model_ref.split("/")[-1] if "/" in model_ref else model_ref
                all_models.append((vendor.name, model_ref, name))

        # 把自定义 Provider 的模型也加进汇总
        custom_vendor_label = "自定义"
        if self.custom_row and self.custom_row.has_any_config():
            for ref in self.custom_row.get_all_selected_models():
                name = ref.split("/")[-1] if "/" in ref else ref
                all_models.append((custom_vendor_label, ref, name))

        # 更新汇总内容
        if not all_models:
            self.summary_content.setText("请先配置 Provider 并选择模型")
            self.default_model_combo.clear()
            self.default_model_combo.addItem("（请先配置并选择模型）", None)
            self.default_model_combo.setEnabled(False)
            return

        lines: list[str] = []
        for vendor in VENDOR_REGISTRY:
            vm = [(ref, name) for vn, ref, name in all_models if vn == vendor.name]
            if vm:
                parts = [f"{name}" for ref, name in vm]
                lines.append(f"{vendor.name}: {', '.join(parts)}")
        # 自定义 Provider 摘要单独成行
        custom_vm = [(ref, name) for vn, ref, name in all_models if vn == custom_vendor_label]
        if custom_vm:
            parts = [f"{name}" for ref, name in custom_vm]
            lines.append(f"{custom_vendor_label}: {', '.join(parts)}")
        self.summary_content.setText("\n".join(lines))

        # 更新全局默认模型下拉框
        current_data = self.default_model_combo.currentData()
        self.default_model_combo.clear()
        self.default_model_combo.setEnabled(True)

        for vn, ref, name in all_models:
            display = f"{vn} - {name}"
            self.default_model_combo.addItem(display, ref)

        # 恢复之前的选择（如果还在列表中）
        if current_data:
            for i in range(self.default_model_combo.count()):
                if self.default_model_combo.itemData(i) == current_data:
                    self.default_model_combo.setCurrentIndex(i)
                    return

        # 默认选中第一个
        if self.default_model_combo.count() > 0:
            self.default_model_combo.setCurrentIndex(0)

    # ─────────────────────────────── 保存

    def _on_save_clicked(self) -> None:
        """收集所有 VendorRow 的配置，组装为统一字典后发射 save_and_start_clicked 信号。

        数据结构：
        {
            "providers": { "vendor_id:key_type": {...}, ... },
            "global_default_model": str,
            "fallback_models": [str, ...],
        }
        """
        configured: dict[str, dict[str, Any]] = {}
        for vendor_id, row in self.vendor_rows.items():
            for cfg in row.get_all_configs():
                key_type = cfg.get("key_type", "")
                # 用 vendor_id + key_type 作为唯一键
                config_key = f"{vendor_id}:{key_type}"
                configured[config_key] = cfg

        # 自定义 Provider: 仅当用户填了任何字段才校验,否则视为未使用,跳过
        if self.custom_row and self.custom_row.has_any_config():
            ok, err = self.custom_row.validate()
            if not ok:
                QMessageBox.warning(self, "自定义 Provider 配置无效", err)
                return
            custom_cfg = self.custom_row.get_config()
            if custom_cfg:
                # config_key = "custom:<provider_id>",天然唯一(provider_id 已过冲突校验)
                config_key = f"{CUSTOM_VENDOR_ID}:{custom_cfg['key_type']}"
                configured[config_key] = custom_cfg

        global_model = self.default_model_combo.currentData()

        # 收集所有已选模型作为 fallback 候选
        all_selected: set[str] = set()
        for row in self.vendor_rows.values():
            for ref in row.get_all_selected_models():
                all_selected.add(ref)
        if self.custom_row:
            for ref in self.custom_row.get_all_selected_models():
                all_selected.add(ref)

        # fallback = 所有已选模型中排除默认模型
        fallback_models: list[str] = []
        if global_model and global_model in all_selected:
            fallback_models = [ref for ref in all_selected if ref != global_model]
        elif all_selected:
            fallback_models = list(all_selected)

        self.save_and_start_clicked.emit({
            "providers": configured,
            "global_default_model": global_model or "",
            "fallback_models": fallback_models,
        })

    # ─────────────────────────────── 配置导入/导出

    def _on_export_config(self) -> None:
        """导出当前配置到 JSON 文件，便于用户备份或迁移到其他机器。"""
        configured: dict[str, dict[str, Any]] = {}
        for vendor_id, row in self.vendor_rows.items():
            for cfg in row.get_all_configs():
                key_type = cfg.get("key_type", "")
                config_key = f"{vendor_id}:{key_type}"
                configured[config_key] = {
                    "api_key": cfg["api_key"],
                    "selected_models": cfg["selected_models"],
                }

        # 自定义 Provider 导出比预设多几个字段:base_url / api_protocol / model_metadata,
        # 用 schema_version=2 标记,导入端据此判断是否走自定义路径
        if self.custom_row and self.custom_row.has_any_config():
            custom_cfg = self.custom_row.get_config()
            if custom_cfg:
                config_key = f"{CUSTOM_VENDOR_ID}:{custom_cfg['key_type']}"
                configured[config_key] = {
                    "api_key": custom_cfg["api_key"],
                    "selected_models": custom_cfg["selected_models"],
                    "base_url": custom_cfg["base_url"],
                    "api_protocol": custom_cfg["api_protocol"],
                    "model_metadata": custom_cfg["model_metadata"],
                }

        data: dict[str, Any] = {
            "version": "1.0",
            "providers": configured,
            "global_default_model": self.default_model_combo.currentData() or "",
            "fallback_models": [],
        }

        path, _ = QFileDialog.getSaveFileName(
            self, "导出配置", "openclaw-config.json", "JSON (*.json)"
        )
        if path:
            # 检查是否包含 API Key，若有则弹窗警告敏感信息泄露风险
            has_api_key = any(
                cfg.get("api_key", "").strip()
                for cfg in configured.values()
            )
            if has_api_key:
                reply = QMessageBox.warning(
                    self,
                    "敏感信息警告",
                    "导出的配置文件中包含明文 API Key，请妥善保管，\n"
                    "不要上传到公共仓库或发送给不信任的第三方。\n\n"
                    "确认继续导出？",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No,
                )
                if reply != QMessageBox.StandardButton.Yes:
                    return

            try:
                with open(path, "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
                QMessageBox.information(self, "导出成功", f"配置已保存到:\n{path}")
            except Exception as e:
                QMessageBox.warning(self, "导出失败", str(e))

    def _on_import_config(self) -> None:
        """从 JSON 文件导入配置，自动回填到对应 VendorRow 并刷新汇总。"""
        path, _ = QFileDialog.getOpenFileName(
            self, "导入配置", "", "JSON (*.json)"
        )
        if not path:
            return

        try:
            with open(path, "r", encoding="utf-8") as f:
                data: dict[str, Any] = json.load(f)
        except Exception as e:
            QMessageBox.warning(self, "导入失败", f"无法读取文件: {e}")
            return

        providers = data.get("providers", {})
        imported_count = 0
        # 单实例自定义 Provider:导入时取第一个 custom:* 条目
        custom_loaded = False
        for config_key, cfg in providers.items():
            parts = config_key.split(":", 1)
            if len(parts) != 2:
                continue
            vendor_id, key_type = parts

            # 自定义 Provider:走专门的回填路径
            if vendor_id == CUSTOM_VENDOR_ID:
                if custom_loaded or not self.custom_row:
                    continue
                # key_type 即用户填的 provider_id
                self.custom_row.reset()
                self.custom_row.provider_id_input.setText(key_type)
                self.custom_row.key_input.setText(cfg.get("api_key", ""))
                self.custom_row.base_url_input.setText(cfg.get("base_url", ""))
                api_value = cfg.get("api_protocol", API_PROTOCOL_OPENAI_COMPLETIONS)
                for idx, (proto_value, _label) in enumerate(API_PROTOCOL_LABELS):
                    if proto_value == api_value:
                        self.custom_row.protocol_combo.setCurrentIndex(idx)
                        break
                model_metadata = cfg.get("model_metadata", {}) or {}
                for ref in cfg.get("selected_models", []) or []:
                    model_id = ref.split("/")[-1] if "/" in ref else ref
                    meta = model_metadata.get(ref, {}) if isinstance(model_metadata, dict) else {}
                    self.custom_row._models.append({
                        "id": model_id,
                        "name": meta.get("name") or model_id,
                        "reasoning": bool(meta.get("reasoning", False)),
                        "contextWindow": int(meta.get("contextWindow", 200000)),
                        "maxTokens": int(meta.get("maxTokens", 8192)),
                    })
                self.custom_row._refresh_model_rows()
                custom_loaded = True
                imported_count += 1
                continue

            row = self.vendor_rows.get(vendor_id)
            if not row:
                continue
            row.load_config(
                cfg.get("api_key", ""),
                cfg.get("selected_models", []),
                key_type,
            )
            imported_count += 1

        # 回填全局默认模型
        global_model = data.get("global_default_model", "")
        if global_model:
            # 先刷新 summary 以更新 combo 选项
            self._refresh_summary()
            for i in range(self.default_model_combo.count()):
                if self.default_model_combo.itemData(i) == global_model:
                    self.default_model_combo.setCurrentIndex(i)
                    break
        else:
            self._refresh_summary()

        QMessageBox.information(
            self, "导入成功",
            f"已导入 {imported_count} 个 Provider 配置"
        )

    # ─────────────────────────────── 重置 / 回填

    def reset(self) -> None:
        """清空所有供应商配置，恢复到初始状态。"""
        for row in self.vendor_rows.values():
            row.key_input.clear()
            row.custom_input.clear()
            row._key_type_state.clear()
            if row.key_type_combo:
                row.key_type_combo.setCurrentIndex(0)
            # 重新加载预设模型（而不是只 clear）
            row._refresh_for_key_type(0)
            if row.is_expanded:
                row.collapse()
        if self.custom_row:
            self.custom_row.reset()
        self._refresh_summary()

    def load_config(self, existing: dict[str, Any]) -> None:
        """回填已有配置（从 openclaw 现有配置文件中解析并映射到 UI）。"""
        env = existing.get("env", {})
        auth_profiles = existing.get("auth_profiles", {})
        primary_model = existing.get("primary_model", "")
        fallback_models = existing.get("fallback_models", [])
        providers_cfg = existing.get("providers", {})

        provider_to_vendor = {
            "moonshot": ("kimi", "standard"),
            "kimi-coding": ("kimi", "coding"),
            "deepseek": ("deepseek", "standard"),
            "minimax": ("minimax", "standard"),
            "volcengine": ("volcengine", "standard"),
            "zai": ("zai", "standard"),
            "xiaomi": ("xiaomi", "standard"),
            "dashscope": ("aliyun", "standard"),
            "aliyun-coding": ("aliyun", "coding"),
        }

        # 收集所有已配置的 model ref（primary + fallbacks）
        all_model_refs: set[str] = set(fallback_models)
        if primary_model:
            all_model_refs.add(primary_model)

        # 为每个 model_ref 确定所属的 vendor
        def get_vendor_for_ref(model_ref: str) -> tuple[str | None, str | None]:
            """返回 (vendor_id, key_type_key)"""
            prefix_map = {
                "moonshot/": ("kimi", "standard"),
                "kimi-coding/": ("kimi", "coding"),
                "deepseek/": ("deepseek", "standard"),
                "minimax/": ("minimax", "standard"),
                "volcengine/": ("volcengine", "standard"),
                "zai/": ("zai", "standard"),
                "xiaomi/": ("xiaomi", "standard"),
                "dashscope/": ("aliyun", "standard"),
                "aliyun-coding/": ("aliyun", "coding"),
            }
            for prefix, (vid, kt_key) in prefix_map.items():
                if model_ref.startswith(prefix):
                    return (vid, kt_key)
            return (None, None)

        # 按 vendor 分组 model refs
        vendor_models: dict[str, list[str]] = {}  # vendor_id -> [model_ref, ...]
        for ref in all_model_refs:
            vid, _ = get_vendor_for_ref(ref)
            if vid:
                vendor_models.setdefault(vid, []).append(ref)

        for vendor in VENDOR_REGISTRY:
            row = self.vendor_rows.get(vendor.id)
            if not row:
                continue

            # 1. 匹配 API Key
            api_key = ""
            matched_key_type = ""

            for kt in vendor.key_types:
                if kt.env_var in env and env[kt.env_var]:
                    api_key = env[kt.env_var]
                    matched_key_type = kt.key
                    break
                if kt.fallback_env_var and kt.fallback_env_var in env and env[kt.fallback_env_var]:
                    api_key = env[kt.fallback_env_var]
                    matched_key_type = kt.key
                    break

            if not api_key:
                for pkey, (vid, default_kt) in provider_to_vendor.items():
                    if vid == vendor.id and pkey in auth_profiles:
                        api_key = auth_profiles[pkey]
                        if pkey == "kimi-coding":
                            matched_key_type = "coding"
                        elif pkey == "moonshot":
                            matched_key_type = "standard"
                        else:
                            matched_key_type = default_kt
                        break

            if not matched_key_type:
                if vendor.id in providers_cfg:
                    pcfg = providers_cfg[vendor.id]
                    if isinstance(pcfg, dict) and pcfg.get("baseUrl"):
                        for kt in vendor.key_types:
                            if kt.base_url == pcfg["baseUrl"]:
                                matched_key_type = kt.key
                                break
                for pkey, (vid, _) in provider_to_vendor.items():
                    if vid == vendor.id and pkey in providers_cfg:
                        pcfg = providers_cfg[pkey]
                        if isinstance(pcfg, dict) and pcfg.get("baseUrl"):
                            for kt in vendor.key_types:
                                if kt.base_url == pcfg["baseUrl"]:
                                    matched_key_type = kt.key
                                    break

            if not matched_key_type and primary_model:
                if vendor.id == "kimi":
                    if primary_model.startswith("kimi-coding/"):
                        matched_key_type = "coding"
                    elif primary_model.startswith("moonshot/"):
                        matched_key_type = "standard"

            # 2. 获取该 vendor 的已选模型
            selected = vendor_models.get(vendor.id, [])

            row.load_config(api_key, selected, matched_key_type)

        # 自定义 Provider 回填: providers_cfg 中所有非保留 ID 视为用户的自定义条目。
        # 当前设计单实例 UI,如果配置文件里有多个非保留 provider,只回填第一个有 selected_models 的那个。
        if self.custom_row:
            self.custom_row.reset()
            for prov_id, pcfg in providers_cfg.items():
                if not isinstance(pcfg, dict):
                    continue
                if prov_id in RESERVED_PROVIDER_IDS:
                    continue
                # 自定义 Provider 必有 baseUrl + apiKey,缺其一就不算用户配置
                if not pcfg.get("baseUrl") or not pcfg.get("apiKey"):
                    continue
                self.custom_row.provider_id_input.setText(prov_id)
                self.custom_row.base_url_input.setText(pcfg["baseUrl"])
                self.custom_row.key_input.setText(pcfg["apiKey"])
                # 协议回填: 配置中的 api 字段映射回下拉框 index
                api_value = pcfg.get("api", API_PROTOCOL_OPENAI_COMPLETIONS)
                for idx, (proto_value, _label) in enumerate(API_PROTOCOL_LABELS):
                    if proto_value == api_value:
                        self.custom_row.protocol_combo.setCurrentIndex(idx)
                        break
                # 模型列表回填,默认全部勾选(用户保存时未勾选的不写入)
                for m in pcfg.get("models", []) or []:
                    if not isinstance(m, dict) or not m.get("id"):
                        continue
                    self.custom_row._models.append({
                        "id": m["id"],
                        "name": m.get("name") or m["id"],
                        "reasoning": bool(m.get("reasoning", False)),
                        "contextWindow": int(m.get("contextWindow", 200000)),
                        "maxTokens": int(m.get("maxTokens", 8192)),
                    })
                self.custom_row._refresh_model_rows()
                # 单实例: 取第一个有效条目即返回
                break

        self._refresh_summary()

        # 回填全局默认模型
        if primary_model:
            for i in range(self.default_model_combo.count()):
                if self.default_model_combo.itemData(i) == primary_model:
                    self.default_model_combo.setCurrentIndex(i)
                    break

    # ─────────────────────────────── 保存状态提示

    def show_saving(self) -> None:
        """保存中状态：禁用所有按钮并将主按钮文本改为「保存中...」，防止重复提交。"""
        self.save_button.setEnabled(False)
        self.save_button.setText("保存中...")
        self.skip_button.setEnabled(False)
        self.back_button.setEnabled(False)

    def hide_saving(self) -> None:
        """恢复按钮可用状态。"""
        self.save_button.setEnabled(True)
        self.save_button.setText("保存并启动")
        self.skip_button.setEnabled(True)
        self.back_button.setEnabled(True)

    def show_error(self, message: str) -> None:
        """弹出配置保存失败的警告对话框。"""
        QMessageBox.warning(self, "配置保存失败", message)
