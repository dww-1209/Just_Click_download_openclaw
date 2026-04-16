from dataclasses import dataclass
from enum import Enum
from typing import Optional


class CheckStatus(Enum):
    """检测状态枚举"""

    OK = "ok"
    WARNING = "warning"
    FAILED = "failed"


class OpenClawStatus(Enum):
    """OpenClaw 安装状态"""

    INSTALLED = "installed"
    NOT_INSTALLED = "not_installed"


@dataclass
class DiskSpaceResult:
    """磁盘空间检测结果"""

    status: CheckStatus
    available_gb: float
    message: str = ""
    path: Optional[str] = None  # 检测的安装路径


@dataclass
class NetworkResult:
    """网络检测结果"""

    status: CheckStatus
    message: str = ""


@dataclass
class PermissionResult:
    """权限检测结果"""

    status: CheckStatus
    message: str = ""
    error_detail: str = ""  # 详细的错误信息，用于调试


@dataclass
class OpenClawInstallResult:
    """OpenClaw 安装检测结果"""

    status: OpenClawStatus
    install_path: Optional[str] = None
    version: Optional[str] = None
    message: str = ""
    error_detail: str = ""  # 详细的错误信息，用于调试


@dataclass
class EnvCheckResult:
    """环境检测总结果"""

    os_type: str
    disk_space: DiskSpaceResult
    network: Optional[NetworkResult]
    permission: PermissionResult
    openclaw_install: OpenClawInstallResult
    is_ready: bool = True
    message: str = ""

    def __post_init__(self):
        if self.disk_space.status == CheckStatus.FAILED:
            self.is_ready = False
