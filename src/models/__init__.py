"""数据模型模块

职责：作为 Models 层的聚合导出点，集中暴露所有数据结构定义和状态契约。
本模块不依赖任何业务逻辑层，只包含纯数据类、枚举和工具函数，
供 UI、Services、Core、Adapters 等各层按需导入。
"""

from .env_check import (
    CheckStatus,
    OpenClawStatus,
    DiskSpaceResult,
    NetworkResult,
    PermissionResult,
    OpenClawInstallResult,
    EnvCheckResult,
)

from .install import (
    ErrorCategory,
    InstallErrorDetail,
    InstallStatus,
    InstallStage,
    InstallProgress,
    InstallResult,
    InstallConfig,
    get_official_command,
)

from .config import (
    ConfigStatus,
    ServiceStatus,
    OpenClawConfig,
    ConfigProgress,
    ConfigResult,
    DEFAULT_CONFIG_PATH,
    DEFAULT_CONFIG_DIR,
)

from .user_messages import (
    UserMessageHelper,
    format_size,
    format_time,
)

from .utils import remove_readonly, ensure_local_bin_in_path

__all__ = [
    # env_check
    "CheckStatus",
    "OpenClawStatus",
    "DiskSpaceResult",
    "NetworkResult",
    "PermissionResult",
    "OpenClawInstallResult",
    "EnvCheckResult",
    # install
    "ErrorCategory",
    "InstallErrorDetail",
    "InstallStatus",
    "InstallStage",
    "InstallProgress",
    "InstallResult",
    "InstallConfig",
    "get_official_command",
    # config
    "ConfigStatus",
    "ServiceStatus",
    "OpenClawConfig",
    "ConfigProgress",
    "ConfigResult",
    "DEFAULT_CONFIG_PATH",
    "DEFAULT_CONFIG_DIR",
    # helpers
    "UserMessageHelper",
    "format_size",
    "format_time",
    "remove_readonly",
    "ensure_local_bin_in_path",
]
