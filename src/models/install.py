from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional


class InstallStatus(Enum):
    """安装状态枚举。

    描述整个安装流程的宏观状态：
    - IDLE：空闲/未开始
    - RUNNING：正在安装中
    - SUCCESS：安装成功完成
    - FAILED：安装失败
    - CANCELLED：用户主动取消
    """

    IDLE = "idle"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    CANCELLED = "cancelled"


class InstallStage(Enum):
    """安装阶段枚举。

    描述安装过程中当前所处的具体阶段，用于进度展示：
    - DOWNLOADING：下载依赖（Node.js、仓库代码等）
    - INSTALLING：执行安装命令（pnpm install / build）
    - CONFIGURING：初始化配置（onboard）
    - COMPLETED：全部完成
    """

    DOWNLOADING = "downloading"
    INSTALLING = "installing"
    CONFIGURING = "configuring"
    COMPLETED = "completed"


class ErrorCategory(Enum):
    """错误分类枚举。

    将安装过程中遇到的异常按业务维度分类，UI 层据此展示对应的中文提示和修复建议：
    - NETWORK_TIMEOUT / NETWORK_DNS / NETWORK_SSL / NETWORK_HTTP_ERROR / NETWORK_UNKNOWN：网络相关
    - PERMISSION_DENIED：权限不足
    - DISK_FULL / DISK_IO_ERROR：磁盘相关
    - PROCESS_TIMEOUT / PROCESS_NOT_FOUND / PROCESS_CRASHED：子进程相关
    - ANTIVIRUS_BLOCKED：被杀毒软件拦截
    - DEPENDENCY_MISSING：依赖缺失
    - ALREADY_EXISTS：文件/目录已存在冲突
    - UNKNOWN：未知错误
    """

    NETWORK_TIMEOUT = "network_timeout"
    NETWORK_DNS = "network_dns"
    NETWORK_SSL = "network_ssl"
    NETWORK_HTTP_ERROR = "network_http_error"
    NETWORK_UNKNOWN = "network_unknown"
    PERMISSION_DENIED = "permission_denied"
    DISK_FULL = "disk_full"
    DISK_IO_ERROR = "disk_io_error"
    PROCESS_TIMEOUT = "process_timeout"
    PROCESS_NOT_FOUND = "process_not_found"
    PROCESS_CRASHED = "process_crashed"
    ANTIVIRUS_BLOCKED = "antivirus_blocked"
    DEPENDENCY_MISSING = "dependency_missing"
    ALREADY_EXISTS = "already_exists"
    UNKNOWN = "unknown"


@dataclass
class InstallProgress:
    """安装进度数据对象。

    用于实时向 UI 传递当前安装阶段的进度信息。

    Attributes:
        stage: 当前安装阶段（InstallStage）。
        progress_percent: 整体进度百分比（0-100）。
        message: 当前步骤的简短描述，用于展示在进度条下方。
        current_task: 当前正在执行的具体任务名称。
    """

    stage: InstallStage
    progress_percent: int = 0
    message: str = ""
    current_task: str = ""


@dataclass
class InstallErrorDetail:
    """详细的安装错误信息。

    当安装失败时，由 infra 层构造并传递给 UI，用于展示友好的错误提示和排查信息。

    Attributes:
        category: 错误分类（ErrorCategory），决定 UI 展示哪类提示。
        stage: 发生错误的阶段（如 DOWNLOADING, INSTALLING）。
        context: 错误发生时的上下文描述（如"正在从 npmmirror 下载 Node.js"）。
        raw_error: 原始错误信息（完整 stderr / 异常堆栈），用于调试。
        user_message: 给用户看的简洁错误描述。
        suggestion: 建议用户采取的修复措施。
        command: 触发错误的命令（如果有）。
        returncode: 子进程返回码（如果有）。
    """

    category: ErrorCategory = ErrorCategory.UNKNOWN
    stage: Optional[str] = None
    context: str = ""
    raw_error: str = ""
    user_message: str = ""
    suggestion: str = ""
    command: str = ""
    returncode: Optional[int] = None


@dataclass
class InstallResult:
    """安装结果数据对象。

    安装流程结束后由 Worker 发射给 UI，包含最终状态、日志和错误详情。

    Attributes:
        status: 安装最终状态（InstallStatus）。
        message: 结果摘要信息。
        error_message: 错误摘要（失败时填写）。
        log_lines: 完整安装日志行列表，用于问题排查。
        duration_seconds: 安装耗时（秒）。
        error_detail: 结构化错误详情（失败时填写）。
    """

    status: InstallStatus
    message: str = ""
    error_message: str = ""
    log_lines: List[str] = field(default_factory=list)
    duration_seconds: float = 0.0
    error_detail: Optional[InstallErrorDetail] = None


@dataclass
class InstallConfig:
    """安装配置数据对象。

    保存与当前安装任务相关的配置参数。

    Attributes:
        os_type: 目标操作系统类型（windows / linux / macos）。
        command_template: OpenClaw 官方安装命令模板，根据 os_type 自动生成。
    """

    os_type: str
    # OpenClaw 官方安装命令模板
    command_template: str = ""

    def __post_init__(self):
        if not self.command_template:
            self.command_template = get_official_command(self.os_type)


def get_official_command(os_type: str, use_mirror: bool = True) -> str:
    """获取 OpenClaw 官方安装命令。

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
        完整的安装命令字符串。
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
    """获取 OpenClaw 默认安装目录。

    Returns:
        OpenClaw 默认安装路径（用户主目录下的 .openclaw 文件夹）。
    """
    import os
    home = os.path.expanduser("~")
    return os.path.join(home, ".openclaw")
