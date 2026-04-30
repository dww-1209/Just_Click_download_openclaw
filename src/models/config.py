from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, Dict, Any
import json


class ConfigStatus(Enum):
    """配置状态枚举。

    描述 OpenClaw 配置与启动流程中的各个阶段，用于 UI 进度展示：
    - IDLE：空闲/未开始
    - CONFIGURING：正在执行 onboard 初始化配置
    - GATEWAY_STARTING：正在启动网关服务
    - STARTING：服务就绪，准备打开 WebUI
    - HEALTH_CHECKING：正在进行健康检查（轮询端口）
    - COMPLETED：全部完成
    - FAILED：配置或启动失败
    """

    IDLE = "idle"
    CONFIGURING = "configuring"
    GATEWAY_STARTING = "gateway_starting"  # 启动网关阶段
    STARTING = "starting"  # 服务就绪，准备打开 WebUI
    HEALTH_CHECKING = "health_checking"
    COMPLETED = "completed"
    FAILED = "failed"


class ServiceStatus(Enum):
    """服务状态枚举。

    描述 OpenClaw 网关服务的运行状态：
    - STOPPED：已停止
    - STARTING：正在启动中
    - RUNNING：正常运行
    - FAILED：启动失败
    """

    STOPPED = "stopped"
    STARTING = "starting"
    RUNNING = "running"
    FAILED = "failed"


@dataclass
class OpenClawConfig:
    """OpenClaw 默认配置数据对象。

    保存服务监听地址、端口等核心配置，可序列化为 JSON 配置文件。

    Attributes:
        config_mode: 配置模式（如 "default"）。
        service_host: 服务监听主机（默认 localhost）。
        service_port: 服务监听端口（默认 18789）。
        auto_start: 是否自动启动服务（默认 True）。
    """

    config_mode: str = "default"
    service_host: str = "localhost"
    service_port: int = 18789
    auto_start: bool = True

    def to_dict(self) -> Dict[str, Any]:
        """将配置转换为字典格式（键名使用 camelCase 以兼容前端）。

        Returns:
            配置字典。
        """
        return {
            "configMode": self.config_mode,
            "serviceHost": self.service_host,
            "servicePort": self.service_port,
            "autoStart": self.auto_start,
        }

    @property
    def webchat_url(self) -> str:
        """生成 WebUI 访问地址。

        Returns:
            完整的 HTTP URL（如 http://localhost:18789）。
        """
        return f"http://{self.service_host}:{self.service_port}"

    def save_to_file(self, file_path: str):
        """将配置保存为 JSON 文件。

        Args:
            file_path: 目标文件路径。
        """
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, indent=2, ensure_ascii=False)


@dataclass
class ConfigProgress:
    """配置进度数据对象。

    用于实时向 UI 传递当前配置/启动阶段的进度信息。

    Attributes:
        stage: 当前配置状态（ConfigStatus）。
        progress_percent: 整体进度百分比（0-100）。
        message: 当前步骤的简短描述。
        current_task: 当前正在执行的具体任务名称。
    """

    stage: ConfigStatus
    progress_percent: int = 0
    message: str = ""
    current_task: str = ""


@dataclass
class ConfigResult:
    """配置结果数据对象。

    配置/启动流程结束后由 Worker 发射给 UI，包含最终状态、服务状态和访问信息。

    Attributes:
        status: 配置最终状态（ConfigStatus）。
        config: 生成的 OpenClawConfig 对象（成功时）。
        service_status: 网关服务状态（ServiceStatus）。
        webchat_url: WebUI 访问地址。
        message: 结果摘要信息。
        error_message: 错误摘要（失败时填写）。
        browser_opened: 是否已成功打开系统浏览器。
        log_lines: 完整日志行列表，用于问题排查。
    """

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
