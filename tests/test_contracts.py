"""接口契约测试

验证核心实现类是否满足 Protocol 接口契约。
由于 Python Protocol 是鸭子类型，本测试通过实例化并检查关键方法是否存在来验证。
"""

import inspect
from typing import get_type_hints

import pytest

from src.contracts.define_manager import IOpenClawManager
from src.contracts.define_installer import IInstaller
from src.contracts.define_uninstaller import IUninstallTask
from src.contracts.define_base_manager import BaseOpenClawManager
from src.contracts.define_base_installer import BaseInstaller
from src.core.manage_openclaw import OpenClawManager
from src.adapters.install_openclaw import OpenClawInstaller


class TestProtocolCompliance:
    """验证实现类是否满足接口契约"""

    def test_openclaw_manager_has_interface_methods(self) -> None:
        """OpenClawManager 包含 IOpenClawManager 所需的所有方法"""
        required_methods = [
            "configure_only",
            "startup_only",
            "quick_start",
            "setup_and_start",
            "configure_providers",
            "read_existing_provider_config",
            "stop",
            "is_running",
            "uninstall",
        ]
        for method_name in required_methods:
            assert hasattr(OpenClawManager, method_name), f"缺少方法: {method_name}"
            assert callable(getattr(OpenClawManager, method_name)), f"不是可调用方法: {method_name}"

    def test_openclaw_installer_has_interface_methods(self) -> None:
        """OpenClawInstaller 包含 IInstaller 所需的所有方法"""
        required_methods = ["install", "cancel", "is_running"]
        for method_name in required_methods:
            assert hasattr(OpenClawInstaller, method_name), f"缺少方法: {method_name}"
            assert callable(getattr(OpenClawInstaller, method_name)), f"不是可调用方法: {method_name}"

    def test_manager_methods_have_type_hints(self) -> None:
        """OpenClawManager 的公共方法具有类型注解"""
        hints = get_type_hints(OpenClawManager.configure_only)
        assert "return" in hints
        assert "on_progress" in hints
        assert "on_log" in hints

    def test_installer_methods_have_type_hints(self) -> None:
        """OpenClawInstaller 的公共方法具有类型注解"""
        hints = get_type_hints(OpenClawInstaller.install)
        assert "return" in hints
        assert "on_progress" in hints
        assert "on_log" in hints

    def test_manager_can_be_instantiated(self) -> None:
        """OpenClawManager 可以无参数实例化"""
        manager = OpenClawManager()
        assert manager is not None
        assert hasattr(manager, "is_running")
        assert manager.is_running() is False


class TestBaseClassInheritance:
        """验证实现类是否正确继承 ABC 基类并获得默认实现"""

        def test_openclaw_manager_inherits_base(self) -> None:
            """OpenClawManager 继承 BaseOpenClawManager"""
            assert issubclass(OpenClawManager, BaseOpenClawManager)

        def test_openclaw_installer_inherits_base(self) -> None:
            """OpenClawInstaller 继承 BaseInstaller"""
            assert issubclass(OpenClawInstaller, BaseInstaller)

        def test_manager_has_base_log(self) -> None:
            """OpenClawManager 实例具有基类提供的 _log 方法"""
            manager = OpenClawManager()
            assert hasattr(manager, "_log")
            assert callable(manager._log)
            # 调用 _log 不会抛出异常
            manager._log("test message")
            assert len(manager._log_lines) == 1
            assert "test message" in manager._log_lines[0]

        def test_installer_has_base_log(self) -> None:
            """OpenClawInstaller 实例具有基类提供的 _log 方法"""
            installer = OpenClawInstaller()
            assert hasattr(installer, "_log")
            assert callable(installer._log)
            installer._log("test message")
            assert len(installer.log_lines) == 1
            assert "test message" in installer.log_lines[0]

        def test_manager_cancel_state(self) -> None:
            """OpenClawManager.stop() 正确设置基类管理的取消状态"""
            manager = OpenClawManager()
            assert manager.is_cancelled is False
            manager.stop()
            assert manager.is_cancelled is True
            assert manager._check_cancelled() is True

        def test_installer_cancel_state(self) -> None:
            """OpenClawInstaller.cancel() 正确设置基类管理的取消状态"""
            installer = OpenClawInstaller()
            assert installer.is_cancelled is False
            installer.cancel()
            assert installer.is_cancelled is True
