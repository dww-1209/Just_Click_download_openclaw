"""帮助函数模块 - 提供用户友好的提示和错误信息"""

from typing import Optional

from src.models.install import ErrorCategory
from src.models.constants import is_windows, is_macos


def _platform_permission_solutions() -> list[str]:
    """权限类问题的平台相关排查清单。

    本安装器走 asInvoker(无 UAC),所有目录都在用户家目录下,因此"以管理员身份
    运行"几乎总是错的猜测。真正常见的根因是:杀毒/防火墙/沙箱策略写拦截。
    """
    if is_windows():
        return [
            "暂时关闭 Windows Defender 实时防护或第三方杀毒软件后重试",
            "右键安装包→属性,勾选「解除锁定」(若有此选项)后重试",
            "确认 ~/openclaw-cn 与 ~/.openclaw 所在磁盘有写入权限",
        ]
    if is_macos():
        return [
            "在「系统设置 → 隐私与安全性」中允许本程序运行",
            "确认 ~/openclaw-cn 与 ~/.openclaw 属于当前用户(可在终端执行 ls -l ~ 查看)",
            "若在公司 Mac 上,联系 IT 解除 MDM 写入限制",
        ]
    # Linux
    return [
        "检查目标目录权限,如 ls -ld ~/openclaw-cn 是否当前用户可写",
        "若安装到非家目录(/opt 等),用 sudo 重新运行,或选择家目录下的路径",
    ]


def _platform_service_start_solutions() -> list[str]:
    """服务启动失败的平台相关排查清单。"""
    common = [
        "检查端口 18789 是否被其他程序占用",
        "重启电脑后重试",
        "检查安装是否完整(可在高级模式查看完整日志)",
    ]
    if is_windows():
        # 防火墙在 Windows 是首要嫌疑,排在前面
        return [
            "首次启动时检查 Windows 安全中心是否弹出防火墙询问,允许网络访问",
            *common,
        ]
    return common


class UserMessageHelper:
    """用户消息帮助类 - 将技术错误转换为小白友好的提示"""

    @staticmethod
    def get_friendly_error_message(error_type: str, details: str = "") -> str:
        """获取用户友好的错误消息(兼容旧接口)。

        新代码请优先调用 ``get_friendly_message_by_category``,通过 ErrorCategory
        枚举生成更精确的提示;本接口作为 ``error_detail`` 缺失时的回退。

        历史原因:旧版安装器要求管理员权限,solutions 普遍含"以管理员身份运行"。
        当前版本走 asInvoker,该建议已无意义,已从绝大多数场景移除;权限/服务启动
        类提示改用 ``_platform_*_solutions`` 按平台输出。
        """

        error_messages = {
            "network": {
                "title": "网络连接失败",
                "message": "无法连接到网络,请检查:",
                "solutions": [
                    "检查网线或 WiFi 是否连接正常",
                    "关闭 VPN 或代理后重试",
                    "暂时关闭防火墙或杀毒软件",
                ],
            },
            "permission": {
                "title": "权限不足",
                "message": "目标目录写入受阻,请尝试:",
                "solutions": _platform_permission_solutions(),
            },
            "disk_space": {
                "title": "磁盘空间不足",
                "message": "安装目录空间不足,请:",
                "solutions": [
                    "清理磁盘空间",
                    "选择其他有足够空间的磁盘",
                    "卸载不常用的软件",
                ],
            },
            "download": {
                "title": "下载失败",
                "message": "无法下载 OpenClaw,请:",
                "solutions": [
                    "检查网络连接",
                    "关闭 VPN 或代理后重试",
                    "暂时关闭防火墙或杀毒软件",
                    "稍后重试(可能是服务器暂时不可用)",
                ],
            },
            "install": {
                "title": "安装失败",
                "message": "安装过程中出现错误,请:",
                "solutions": [
                    "暂时关闭杀毒软件后重试",
                    "检查安装目录是否有写入权限",
                    "重试安装",
                    "保留日志后联系技术支持",
                ],
            },
            "service_start": {
                "title": "服务启动失败",
                "message": "OpenClaw 服务未能正常启动,请:",
                "solutions": _platform_service_start_solutions(),
            },
            "port_in_use": {
                "title": "端口被占用",
                "message": "默认端口已被其他程序使用,请:",
                "solutions": [
                    "关闭占用端口 18789 的其他程序",
                    "重启电脑后重试",
                ],
            },
            "unknown": {
                "title": "发生错误",
                "message": "程序运行过程中出现错误,请:",
                "solutions": [
                    "重试操作",
                    "重启电脑后重试",
                    "查看高级模式中的完整日志,联系技术支持",
                ],
            },
        }

        error_info = error_messages.get(error_type, error_messages["unknown"])

        # 构建完整错误消息
        lines = [
            f"【{error_info['title']}】",
            "",
            error_info["message"],
            "",
        ]

        for i, solution in enumerate(error_info["solutions"], 1):
            lines.append(f"{i}. {solution}")

        if details:
            lines.extend(["", f"详细信息:{details}"])

        return "\n".join(lines)

    @staticmethod
    def get_friendly_message_by_category(
        category: ErrorCategory,
        user_message: str = "",
        suggestion: str = "",
        details: str = "",
    ) -> str:
        """根据 ErrorCategory 生成用户友好的错误消息

        优先使用传入的 user_message 和 suggestion，如果没有则按分类生成默认值。
        """
        category_titles = {
            ErrorCategory.NETWORK_TIMEOUT: "下载超时",
            ErrorCategory.NETWORK_DNS: "DNS 解析失败",
            ErrorCategory.NETWORK_SSL: "SSL/TLS 证书错误",
            ErrorCategory.NETWORK_HTTP_ERROR: "服务器返回错误",
            ErrorCategory.NETWORK_UNKNOWN: "网络异常",
            ErrorCategory.PERMISSION_DENIED: "权限不足",
            ErrorCategory.DISK_FULL: "磁盘空间不足",
            ErrorCategory.DISK_IO_ERROR: "磁盘读写错误",
            ErrorCategory.PROCESS_TIMEOUT: "操作超时",
            ErrorCategory.PROCESS_NOT_FOUND: "缺少必要组件",
            ErrorCategory.PROCESS_CRASHED: "程序异常退出",
            ErrorCategory.ANTIVIRUS_BLOCKED: "安全软件阻止",
            ErrorCategory.DEPENDENCY_MISSING: "缺少依赖",
            ErrorCategory.ALREADY_EXISTS: "操作冲突",
            ErrorCategory.UNKNOWN: "发生错误",
        }

        title = category_titles.get(category, "发生错误")
        msg = user_message or "安装过程中出现问题"
        sugg = suggestion or "请重试，如果问题持续请联系技术支持"

        lines = [
            f"【{title}】",
            "",
            msg,
            "",
            "建议操作：",
            sugg,
        ]

        if details:
            lines.extend(["", f"详细信息：{details}"])

        return "\n".join(lines)

    @staticmethod
    def get_stage_message(stage: str) -> str:
        """获取安装阶段的用户友好描述"""

        stage_messages = {
            "welcome": "欢迎使用 OpenClaw 安装程序",
            "env_check": "正在检测系统环境...",
            "path_select": "请选择安装位置",
            "installing": "正在安装 OpenClaw...",
            "configuring": "正在配置 OpenClaw...",
            "completed": "安装完成！",
            "error": "安装过程中出现错误"
        }

        return stage_messages.get(stage, "处理中...")

    @staticmethod
    def get_progress_message(stage: str, percent: int) -> str:
        """获取进度消息"""

        if stage == "downloading":
            if percent < 30:
                return "正在连接服务器..."
            elif percent < 60:
                return "正在下载文件..."
            else:
                return "即将下载完成..."

        elif stage == "installing":
            if percent < 40:
                return "正在解压文件..."
            elif percent < 70:
                return "正在安装组件..."
            else:
                return "正在完成安装..."

        elif stage == "configuring":
            return "正在写入配置文件..."

        elif stage == "completed":
            return "安装完成！"

        return "正在处理..."


def format_size(size_bytes: float) -> str:
    """将字节大小格式化为人类可读的字符串"""

    if size_bytes < 1024:
        return f"{size_bytes:.1f} B"
    elif size_bytes < 1024 ** 2:
        return f"{size_bytes / 1024:.1f} KB"
    elif size_bytes < 1024 ** 3:
        return f"{size_bytes / (1024 ** 2):.1f} MB"
    else:
        return f"{size_bytes / (1024 ** 3):.1f} GB"


def format_time(seconds: float) -> str:
    """将秒数格式化为人类可读的字符串"""

    if seconds < 60:
        return f"{int(seconds)}秒"
    elif seconds < 3600:
        minutes = int(seconds / 60)
        secs = int(seconds % 60)
        return f"{minutes}分{secs}秒"
    else:
        hours = int(seconds / 3600)
        minutes = int((seconds % 3600) / 60)
        return f"{hours}小时{minutes}分"
