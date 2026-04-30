from PySide6.QtCore import QThread, Signal

from src.core.openclaw_manager import OpenClawManager


class ConfigWorker(QThread):
    progress_updated = Signal(object)
    log_line = Signal(str)
    complete = Signal(object)

    def __init__(self, manager: OpenClawManager):
        super().__init__()
        self.manager = manager

    def run(self):
        result = self.manager.configure_only(
            on_progress=self.progress_updated.emit,
            on_log=self.log_line.emit,
        )
        self.complete.emit(result)


class StartupWorker(QThread):
    progress_updated = Signal(object)
    log_line = Signal(str)
    complete = Signal(object)

    def __init__(self, manager: OpenClawManager, quick_start: bool = False):
        super().__init__()
        self.manager = manager
        self.quick_start = quick_start

    def run(self):
        result = self.manager.startup_only(
            on_progress=self.progress_updated.emit,
            on_log=self.log_line.emit,
        )
        self.complete.emit(result)


class ProviderConfigWorker(QThread):
    progress_updated = Signal(object)
    log_line = Signal(str)
    complete = Signal(bool)

    def __init__(
        self,
        manager: OpenClawManager,
        providers_config: dict,
        global_default_model: str,
        fallback_models: list,
    ):
        super().__init__()
        self.manager = manager
        self.providers_config = providers_config
        self.global_default_model = global_default_model
        self.fallback_models = fallback_models

    def run(self):
        ok = self.manager.configure_providers(
            self.providers_config,
            self.global_default_model,
            self.fallback_models,
            on_progress=self.progress_updated.emit,
            on_log=self.log_line.emit,
        )
        self.complete.emit(ok)
