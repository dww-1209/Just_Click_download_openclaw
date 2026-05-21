"""接口定义层（Interface Layer）

职责：定义各层之间的抽象契约（Protocol），使模块间通过接口而非具体实现交互。

设计原则：
- 本层只包含 typing.Protocol 定义和类型别名，不依赖 src 内任何业务实现层。
- 可以导入 src.models（纯数据层），但不得导入 src.services / src.core / src.adapters。
- 所有实现类通过鸭子类型隐式实现接口，无需显式继承。
"""

from src.contracts.define_base_installer import BaseInstaller
from src.contracts.define_base_manager import BaseOpenClawManager
from src.contracts.define_worker import ProgressCallback, LogCallback, ConfigProgressCallback
from src.contracts.define_manager import ConfigLogCallback
from src.contracts.define_installer import IInstaller
from src.contracts.define_manager import IOpenClawManager
from src.contracts.define_env_checker import IEnvChecker
from src.contracts.define_system_launcher import ISystemLauncher
from src.contracts.define_decorators import log_method

__all__ = [
    "BaseInstaller",
    "BaseOpenClawManager",
    "ProgressCallback",
    "LogCallback",
    "ConfigLogCallback",
    "ConfigProgressCallback",
    "IInstaller",
    "IOpenClawManager",
    "IEnvChecker",
    "ISystemLauncher",
    "log_method",
]
