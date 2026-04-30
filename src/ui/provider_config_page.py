"""Provider 配置页面 - 多选模型 + 汇总选默认 + 配置导入导出"""

import json

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QPushButton, QHBoxLayout, QFrame,
    QLineEdit, QComboBox, QScrollArea, QFileDialog, QMessageBox,
    QGraphicsDropShadowEffect, QCheckBox,
)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont, QColor

from src.models.provider_config import VENDOR_REGISTRY


# ═══════════════════════════════════════════════════════════════════
# 内联组件
# ═══════════════════════════════════════════════════════════════════

class PrimaryButton(QPushButton):
    """主操作按钮"""

    def __init__(self, text: str, parent=None):
        super().__init__(text, parent)
        self.setCursor(Qt.PointingHandCursor)
        self.setObjectName("primaryButton")


class SecondaryButton(QPushButton):
    """次要操作按钮"""

    def __init__(self, text: str, parent=None):
        super().__init__(text, parent)
        self.setCursor(Qt.PointingHandCursor)


class VendorRow(QFrame):
    """供应商配置行 — 可展开/折叠"""

    toggled = Signal(str)
    model_selection_changed = Signal()

    def __init__(self, vendor, parent=None):
        super().__init__(parent)
        self.vendor = vendor
        self.is_expanded = False
        self._key_type_state = {}  # {key_type_key: {"api_key": "", "selected": set()}}
        self._custom_models = []   # [(model_ref, display_name, key_type_key), ...]
        self._model_checkboxes = {}  # {model_ref: QCheckBox}
        self._current_key_type = None

        self._setup_ui()

    def _setup_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # 标题行
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

        # 内容区域
        self.content = QFrame()
        self.content.setStyleSheet(
            "QFrame { background-color: #ffffff; border-radius: 6px; "
            "border: 1px solid #e0e0e0; margin-top: 4px; }"
        )
        content_layout = QVBoxLayout(self.content)
        content_layout.setContentsMargins(14, 14, 14, 14)
        content_layout.setSpacing(10)

        # Key Type 选择
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

        # API Key
        key_layout = QHBoxLayout()
        key_label = QLabel("API Key:")
        key_label.setStyleSheet("font-weight: bold; color: #555;")
        self.key_input = QLineEdit()
        self.key_input.setEchoMode(QLineEdit.Password)
        self.key_input.setPlaceholderText("请输入 API Key")
        key_layout.addWidget(key_label)
        key_layout.addWidget(self.key_input, 1)
        content_layout.addLayout(key_layout)

        # 模型列表
        models_label = QLabel("选择模型（可多选）:")
        models_label.setStyleSheet("font-weight: bold; color: #555;")
        content_layout.addWidget(models_label)

        self.models_container = QWidget()
        self.models_layout = QVBoxLayout(self.models_container)
        self.models_layout.setContentsMargins(0, 0, 0, 0)
        self.models_layout.setSpacing(4)
        content_layout.addWidget(self.models_container)

        # 自定义模型
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

        # 初始化
        if self.vendor.key_types:
            self._current_key_type = self.vendor.key_types[0].key
        self._refresh_models()

    def _toggle(self):
        self.is_expanded = not self.is_expanded
        self.content.setVisible(self.is_expanded)
        self.arrow_label.setText("▼" if self.is_expanded else "▶")
        self.toggled.emit(self.vendor.id)

    def collapse(self):
        self.is_expanded = False
        self.content.hide()
        self.arrow_label.setText("▶")

    def _on_key_type_changed(self, index):
        self._save_current_state()
        key_type_key = self.key_type_combo.itemData(index)
        self._current_key_type = key_type_key
        self._refresh_models()
        self._restore_state()

    def _save_current_state(self):
        if not self._current_key_type:
            return
        selected = set()
        for ref, cb in self._model_checkboxes.items():
            if cb.isChecked():
                selected.add(ref)
        self._key_type_state[self._current_key_type] = {
            "api_key": self.key_input.text(),
            "selected": selected,
        }

    def _restore_state(self):
        if not self._current_key_type:
            return
        state = self._key_type_state.get(self._current_key_type, {})
        self.key_input.setText(state.get("api_key", ""))
        selected = state.get("selected", set())
        for ref, cb in self._model_checkboxes.items():
            cb.setChecked(ref in selected)

    def _refresh_models(self):
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

    def _add_custom_model(self):
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

    def _remove_custom_model(self, ref):
        key_type = self._current_key_type or ""
        self._custom_models = [(r, n, k) for r, n, k in self._custom_models if not (r == ref and k == key_type)]
        self._save_current_state()
        self._refresh_models()
        self.model_selection_changed.emit()

    def _on_model_changed(self):
        self.model_selection_changed.emit()

    def has_any_config(self):
        return bool(self.key_input.text().strip())

    def get_all_selected_models(self):
        all_selected = set()
        for ref, cb in self._model_checkboxes.items():
            if cb.isChecked():
                all_selected.add(ref)
        for state in self._key_type_state.values():
            all_selected.update(state.get("selected", set()))
        return list(all_selected)

    def get_all_configs(self):
        configs = []
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

    def load_config(self, api_key, selected_models, key_type):
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

        selected_set = set(selected_models) if selected_models else set()
        self._key_type_state[self._current_key_type] = {
            "api_key": api_key or "",
            "selected": selected_set,
        }

        preset_refs = set()
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

    def _refresh_for_key_type(self, index):
        if self.key_type_combo:
            self.key_type_combo.setCurrentIndex(index)
            key_type_key = self.key_type_combo.itemData(index)
            self._current_key_type = key_type_key
            self._refresh_models()
        else:
            self._current_key_type = self.vendor.key_types[0].key if self.vendor.key_types else None
            self._refresh_models()


class ProviderConfigPage(QWidget):
    """Provider 配置页面 - 多选模型 + 汇总选默认"""

    back_clicked = Signal()
    skip_clicked = Signal()
    save_and_start_clicked = Signal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.vendor_rows: dict[str, VendorRow] = {}
        self._setup_ui()

    def _setup_ui(self):
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

        # 标题
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

        # 提示标语
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

        # 供应商列表
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

        # 汇总区域
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

    def _on_vendor_toggled(self, vendor_id: str):
        """展开某个供应商时，折叠其他供应商"""
        for vid, row in self.vendor_rows.items():
            if vid != vendor_id and row.is_expanded:
                row.collapse()

    # ─────────────────────────────── 汇总刷新

    def _refresh_summary(self):
        """刷新汇总区域"""
        all_models = []  # [(vendor_name, model_ref, model_name), ...]

        for vendor in VENDOR_REGISTRY:
            row = self.vendor_rows.get(vendor.id)
            if not row or not row.has_any_config():
                continue

            # 收集所有 key type 的已选模型
            all_refs = row.get_all_selected_models()
            # 为每个 ref 找显示名
            preset_names = {}
            for kt in vendor.key_types:
                for m in kt.models:
                    preset_names[m.ref] = m.name

            for model_ref in all_refs:
                name = preset_names.get(model_ref, None)
                if name is None:
                    name = model_ref.split("/")[-1] if "/" in model_ref else model_ref
                all_models.append((vendor.name, model_ref, name))

        # 更新汇总内容
        if not all_models:
            self.summary_content.setText("请先配置 Provider 并选择模型")
            self.default_model_combo.clear()
            self.default_model_combo.addItem("（请先配置并选择模型）", None)
            self.default_model_combo.setEnabled(False)
            return

        lines = []
        for vendor in VENDOR_REGISTRY:
            vm = [(ref, name) for vn, ref, name in all_models if vn == vendor.name]
            if vm:
                parts = [f"{name}" for ref, name in vm]
                lines.append(f"{vendor.name}: {', '.join(parts)}")
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

    def _on_save_clicked(self):
        configured = {}
        for vendor_id, row in self.vendor_rows.items():
            for cfg in row.get_all_configs():
                key_type = cfg.get("key_type", "")
                # 用 vendor_id + key_type 作为唯一键
                config_key = f"{vendor_id}:{key_type}"
                configured[config_key] = cfg

        global_model = self.default_model_combo.currentData()

        # 收集所有已选模型作为 fallback 候选
        all_selected = set()
        for row in self.vendor_rows.values():
            for ref in row.get_all_selected_models():
                all_selected.add(ref)

        # fallback = 所有已选模型中排除默认模型
        fallback_models = []
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

    def _on_export_config(self):
        """导出当前配置到 JSON 文件"""
        configured = {}
        for vendor_id, row in self.vendor_rows.items():
            for cfg in row.get_all_configs():
                key_type = cfg.get("key_type", "")
                config_key = f"{vendor_id}:{key_type}"
                configured[config_key] = {
                    "api_key": cfg["api_key"],
                    "selected_models": cfg["selected_models"],
                }

        data = {
            "version": "1.0",
            "providers": configured,
            "global_default_model": self.default_model_combo.currentData() or "",
            "fallback_models": [],
        }

        path, _ = QFileDialog.getSaveFileName(
            self, "导出配置", "openclaw-config.json", "JSON (*.json)"
        )
        if path:
            try:
                with open(path, "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
                QMessageBox.information(self, "导出成功", f"配置已保存到:\n{path}")
            except Exception as e:
                QMessageBox.warning(self, "导出失败", str(e))

    def _on_import_config(self):
        """从 JSON 文件导入配置"""
        path, _ = QFileDialog.getOpenFileName(
            self, "导入配置", "", "JSON (*.json)"
        )
        if not path:
            return

        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            QMessageBox.warning(self, "导入失败", f"无法读取文件: {e}")
            return

        providers = data.get("providers", {})
        imported_count = 0
        for config_key, cfg in providers.items():
            parts = config_key.split(":", 1)
            if len(parts) != 2:
                continue
            vendor_id, key_type = parts
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

    def reset(self):
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
        self._refresh_summary()

    def load_config(self, existing: dict):
        """回填已有配置"""
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
            "openrouter": ("openrouter", "standard"),
            "zai": ("zai", "standard"),
            "xiaomi": ("xiaomi", "standard"),
            "dashscope": ("aliyun", "standard"),
            "aliyun-coding": ("aliyun", "coding"),
        }

        # 收集所有已配置的 model ref（primary + fallbacks）
        all_model_refs = set(fallback_models)
        if primary_model:
            all_model_refs.add(primary_model)

        # 为每个 model_ref 确定所属的 vendor
        def get_vendor_for_ref(model_ref: str):
            """返回 (vendor_id, key_type_key)"""
            prefix_map = {
                "moonshot/": ("kimi", "standard"),
                "kimi-coding/": ("kimi", "coding"),
                "deepseek/": ("deepseek", "standard"),
                "minimax/": ("minimax", "standard"),
                "volcengine/": ("volcengine", "standard"),
                "openrouter/": ("openrouter", "standard"),
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
        vendor_models: dict[str, list] = {}  # vendor_id -> [model_ref, ...]
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

        self._refresh_summary()

        # 回填全局默认模型
        if primary_model:
            for i in range(self.default_model_combo.count()):
                if self.default_model_combo.itemData(i) == primary_model:
                    self.default_model_combo.setCurrentIndex(i)
                    break

    # ─────────────────────────────── 保存状态提示

    def show_saving(self):
        self.save_button.setEnabled(False)
        self.save_button.setText("保存中...")
        self.skip_button.setEnabled(False)
        self.back_button.setEnabled(False)

    def hide_saving(self):
        self.save_button.setEnabled(True)
        self.save_button.setText("保存并启动")
        self.skip_button.setEnabled(True)
        self.back_button.setEnabled(True)

    def show_error(self, message: str):
        QMessageBox.warning(self, "配置保存失败", message)
