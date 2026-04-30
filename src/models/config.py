from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, Dict, Any
import json


class ConfigStatus(Enum):
    """配置状态枚举"""

    IDLE = "idle"
    CONFIGURING = "configuring"
    GATEWAY_STARTING = "gateway_starting"  # 启动网关阶段
    STARTING = "starting"  # 服务就绪，准备打开 WebUI
    HEALTH_CHECKING = "health_checking"
    COMPLETED = "completed"
    FAILED = "failed"


class ServiceStatus(Enum):
    """服务状态枚举"""

    STOPPED = "stopped"
    STARTING = "starting"
    RUNNING = "running"
    FAILED = "failed"


@dataclass
class OpenClawConfig:
    """OpenClaw 默认配置"""

    config_mode: str = "default"
    service_host: str = "localhost"
    service_port: int = 18789
    auto_start: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return {
            "configMode": self.config_mode,
            "serviceHost": self.service_host,
            "servicePort": self.service_port,
            "autoStart": self.auto_start,
        }

    @property
    def webchat_url(self) -> str:
        return f"http://{self.service_host}:{self.service_port}"

    def save_to_file(self, file_path: str):
        """保存配置到文件"""
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, indent=2, ensure_ascii=False)


@dataclass
class ConfigProgress:
    """配置进度"""

    stage: ConfigStatus
    progress_percent: int = 0
    message: str = ""
    current_task: str = ""


@dataclass
class ConfigResult:
    """配置结果"""

    status: ConfigStatus
    config: Optional[OpenClawConfig] = None
    service_status: ServiceStatus = ServiceStatus.STOPPED
    webchat_url: str = ""
    message: str = ""
    error_message: str = ""
    browser_opened: bool = False
    log_lines: list = None  # 详细日志，用于排查问题
    
    def __post_init__(self):
        if self.log_lines is None:
            self.log_lines = []


# 默认配置文件路径（相对于安装目录）
DEFAULT_CONFIG_PATH = "config.json"
DEFAULT_CONFIG_DIR = ".openclaw"
