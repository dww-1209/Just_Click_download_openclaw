from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional


class InstallStatus(Enum):
    """安装状态枚举"""

    IDLE = "idle"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    CANCELLED = "cancelled"


class InstallStage(Enum):
    """安装阶段枚举"""

    DOWNLOADING = "downloading"
    INSTALLING = "installing"
    CONFIGURING = "configuring"
    COMPLETED = "completed"


@dataclass
class InstallProgress:
    """安装进度"""

    stage: InstallStage
    progress_percent: int = 0
    message: str = ""
    current_task: str = ""


@dataclass
class InstallResult:
    """安装结果"""

    status: InstallStatus
    message: str = ""
    error_message: str = ""
    log_lines: List[str] = field(default_factory=list)
    duration_seconds: float = 0.0


@dataclass
class InstallConfig:
    """安装配置"""

    os_type: str
    # OpenClaw 官方安装命令模板
    command_template: str = ""

    def __post_init__(self):
        if not self.command_template:
            self.command_template = get_official_command(self.os_type)


def get_official_command(os_type: str, use_mirror: bool = True) -> str:
    """获取 OpenClaw 官方安装命令
    
    使用官方提供的命令行安装方式（默认使用国内镜像加速）：
    - Linux/macOS: curl -fsSL https://open-claw.org.cn/install-cn.sh | bash
    - Windows: iwr -useb https://open-claw.org.cn/install-cn.ps1 | iex
    
    注意：官方脚本不支持自定义安装路径，默认安装到用户目录：
    - Windows: %USERPROFILE%\\.openclaw
    - Linux/macOS: ~/.openclaw
    
    Args:
        os_type: windows/linux/macos
        use_mirror: 是否使用国内镜像（默认 True）

    Returns:
        完整的安装命令
    """
    if use_mirror:
        # 国内镜像（推荐）
        if os_type == "windows":
            command = (
                f'powershell -NoProfile -ExecutionPolicy Bypass -Command "'
                f'iwr -useb https://open-claw.org.cn/install-cn.ps1 | iex"'
            )
        elif os_type == "linux":
            command = 'bash -c "curl -fsSL https://open-claw.org.cn/install-cn.sh | bash"'
        else:
            command = 'bash -c "curl -fsSL https://open-claw.org.cn/install-cn.sh | bash"'
    else:
        # 官方原版（国际网络）
        if os_type == "windows":
            command = (
                f'powershell -NoProfile -ExecutionPolicy Bypass -Command "'
                f'iwr -useb https://openclaw.ai/install.ps1 | iex"'
            )
        elif os_type == "linux":
            command = 'bash -c "curl -fsSL https://openclaw.ai/install.sh | bash"'
        else:
            command = 'bash -c "curl -fsSL https://openclaw.ai/install.sh | bash"'
    
    return command


def get_openclaw_home() -> str:
    """获取 OpenClaw 默认安装目录
    
    Returns:
        OpenClaw 默认安装路径
    """
    import os
    home = os.path.expanduser("~")
    return os.path.join(home, ".openclaw")
