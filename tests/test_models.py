"""数据模型单元测试

验证所有 dataclass 的构造、默认值、__post_init__ 和属性方法。
"""

import pytest
from dataclasses import fields

from src.models.install import (
    InstallStatus,
    InstallStage,
    InstallProgress,
    InstallResult,
    InstallConfig,
    get_official_command,
    get_openclaw_home,
)
from src.models.config import (
    ConfigStatus,
    ServiceStatus,
    OpenClawConfig,
    ConfigProgress,
    ConfigResult,
)
from src.models.env_check import (
    CheckStatus,
    OpenClawStatus,
    DiskSpaceResult,
    EnvCheckResult,
)


class TestInstallModels:
    """安装相关数据模型测试"""

    def test_install_status_enum(self) -> None:
        """InstallStatus 枚举值正确"""
        assert InstallStatus.IDLE.value == "idle"
        assert InstallStatus.SUCCESS.value == "success"
        assert InstallStatus.FAILED.value == "failed"

    def test_install_stage_enum(self) -> None:
        """InstallStage 枚举值正确"""
        assert InstallStage.DOWNLOADING.value == "downloading"
        assert InstallStage.COMPLETED.value == "completed"

    def test_install_progress_defaults(self) -> None:
        """InstallProgress 默认值正确"""
        p = InstallProgress(stage=InstallStage.INSTALLING)
        assert p.progress_percent == 0
        assert p.message == ""
        assert p.current_task == ""
        assert p.stage == InstallStage.INSTALLING

    def test_install_result_defaults(self) -> None:
        """InstallResult 默认值正确"""
        r = InstallResult(status=InstallStatus.SUCCESS)
        assert r.message == ""
        assert r.error_message == ""
        assert r.log_lines == []
        assert r.duration_seconds == 0.0
        assert r.error_detail is None

    def test_install_config_post_init(self) -> None:
        """InstallConfig __post_init__ 自动生成 command_template"""
        cfg = InstallConfig(os_type="windows")
        assert "install-cn.ps1" in cfg.command_template

        cfg_linux = InstallConfig(os_type="linux")
        assert "install-cn.sh" in cfg_linux.command_template

    def test_get_official_command(self) -> None:
        """get_official_command 返回正确格式的命令"""
        cmd = get_official_command("windows")
        assert "powershell" in cmd.lower()

        cmd_mac = get_official_command("macos")
        assert "curl" in cmd_mac


class TestConfigModels:
    """配置相关数据模型测试"""

    def test_config_status_enum(self) -> None:
        """ConfigStatus 枚举值正确"""
        assert ConfigStatus.CONFIGURING.value == "configuring"
        assert ConfigStatus.COMPLETED.value == "completed"

    def test_config_result_defaults(self) -> None:
        """ConfigResult log_lines 默认空列表"""
        r = ConfigResult(status=ConfigStatus.COMPLETED)
        assert r.log_lines == []
        assert r.webchat_url == ""

    def test_openclaw_config_webchat_url(self) -> None:
        """OpenClawConfig webchat_url 属性拼接正确"""
        cfg = OpenClawConfig(service_host="127.0.0.1", service_port=18789)
        assert "18789" in cfg.webchat_url
        assert "127.0.0.1" in cfg.webchat_url

    def test_config_progress_creation(self) -> None:
        """ConfigProgress 构造与字段访问"""
        p = ConfigProgress(
            stage=ConfigStatus.GATEWAY_STARTING,
            progress_percent=50,
            message="测试中",
        )
        assert p.progress_percent == 50
        assert p.message == "测试中"


class TestEnvCheckModels:
    """环境检测数据模型测试"""

    def test_check_status_enum(self) -> None:
        """CheckStatus 枚举值正确"""
        assert CheckStatus.OK.value == "ok"
        assert CheckStatus.FAILED.value == "failed"

    def test_env_check_result_post_init(self) -> None:
        """EnvCheckResult __post_init__ 自动设置 is_ready=False"""
        disk = DiskSpaceResult(status=CheckStatus.FAILED, available_gb=0.1)
        result = EnvCheckResult(
            os_type="linux",
            disk_space=disk,
            network=None,
            permission=None,  # type: ignore[arg-type]
            openclaw_install=None,  # type: ignore[arg-type]
            browser=None,  # type: ignore[arg-type]
        )
        assert result.is_ready is False

    def test_env_check_result_ready_when_disk_ok(self) -> None:
        """磁盘通过时 is_ready 保持 True"""
        disk = DiskSpaceResult(status=CheckStatus.OK, available_gb=10.0)
        result = EnvCheckResult(
            os_type="linux",
            disk_space=disk,
            network=None,
            permission=None,  # type: ignore[arg-type]
            openclaw_install=None,  # type: ignore[arg-type]
            browser=None,  # type: ignore[arg-type]
        )
        assert result.is_ready is True
