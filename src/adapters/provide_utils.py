"""安装器公共工具函数（向后兼容重导出）

注意：实际实现已迁移至 src.models.utils，本文件保留以兼容现有代码。
新项目代码请直接从 src.models.utils 导入。
"""

from __future__ import annotations

from src.models.utils import remove_readonly, ensure_local_bin_in_path

__all__ = ["remove_readonly", "ensure_local_bin_in_path"]
