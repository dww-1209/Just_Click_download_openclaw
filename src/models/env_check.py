from dataclasses import dataclass
from enum import Enum
from typing import Optional


class CheckStatus(Enum):
    """检测状态枚举。

    描述单项环境检测的结果等级：
    - OK：检测通过，无异常
    - WARNING：检测通过但存在警告（如磁盘空间紧张）
    - FAILED：检测不通过，会阻止安装继续
    """

    OK = "ok"
    WARNING = "warning"
    FAILED = "failed"


class OpenClawStatus(Enum):
    """OpenClaw 安装状态枚举。

    描述 OpenClaw 是否已在系统中安装：
    - INSTALLED：已检测到安装
    - NOT_INSTALLED：未检测到安装
    """

    INSTALLED = "installed"
    NOT_INSTALLED = "not_installed"


@dataclass
class DiskSpaceResult:
    """磁盘空间检测结果。

    Attributes:
        status: 检测状态（CheckStatus）。
        available_gb: 可用空间（GB）。
        message: 状态描述信息。
        path: 检测的安装路径（如有）。
    """

    status: CheckStatus
    available_gb: float
    message: str = ""
    path: Optional[str] = None  # 检测的安装路径


@dataclass
class NetworkResult:
    """网络检测结果。

    Attributes:
        status: 检测状态（CheckStatus）。
        message: 状态描述信息（如可达的镜像站点）。
    """

    status: CheckStatus
    message: str = ""


@dataclass
class PermissionResult:
    """权限检测结果。

    Attributes:
        status: 检测状态（CheckStatus）。
        message: 状态描述信息。
        error_detail: 详细的错误信息，用于调试。
    """

    status: CheckStatus
    message: str = ""
    error_detail: str = ""  # 详细的错误信息，用于调试


@dataclass
class OpenClawInstallResult:
    """OpenClaw 安装检测结果。

    Attributes:
        status: OpenClaw 安装状态（OpenClawStatus）。
        install_path: 检测到的安装路径（如已安装）。
        version: 检测到的版本号（如已安装）。
        message: 状态描述信息。
        error_detail: 详细的错误信息，用于调试。
    """

    status: OpenClawStatus
    install_path: Optional[str] = None
    version: Optional[str] = None
    message: str = ""
    error_detail: str = ""  # 详细的错误信息，用于调试


@dataclass
class BrowserResult:
    """浏览器检测结果。

    Attributes:
        status: 检测状态（CheckStatus）。
        found_browsers: 检测到的可用浏览器名称列表。
        message: 状态描述信息。
    """

    status: CheckStatus
    found_browsers: list[str]
    message: str = ""


@dataclass
class EnvCheckResult:
    """环境检测总结果。

    汇总所有单项检测结果，并计算整体是否满足安装条件。

    Attributes:
        os_type: 当前操作系统类型标识。
        disk_space: 磁盘空间检测结果。
        network: 网络检测结果（可能为 None）。
        permission: 权限检测结果。
        openclaw_install: OpenClaw 安装检测结果。
        browser: 浏览器检测结果。
        is_ready: 整体是否满足安装条件（磁盘检测失败时自动设为 False）。
        message: 整体状态描述信息。
    """

    os_type: str
    disk_space: DiskSpaceResult
    network: Optional[NetworkResult]
    permission: PermissionResult
    openclaw_install: OpenClawInstallResult
    browser: BrowserResult
    is_ready: bool = True
    message: str = ""

    def __post_init__(self) -> None:
        """后置初始化：若磁盘空间检测失败，则将整体就绪状态设为 False。"""
        if self.disk_space.status == CheckStatus.FAILED:
            self.is_ready = False
