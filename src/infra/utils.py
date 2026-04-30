"""安装器公共工具函数

提取多文件重复使用的通用辅助函数，避免重复定义。
"""

import os
import stat


def remove_readonly(func, path, _):
    """shutil.rmtree 的 onerror 回调：移除只读属性后重试删除。

    用途：删除可能包含只读文件（如 Git 仓库中的文件）的目录时，
    先修改文件权限再重试删除操作。
    """
    os.chmod(path, stat.S_IWRITE)
    func(path)
