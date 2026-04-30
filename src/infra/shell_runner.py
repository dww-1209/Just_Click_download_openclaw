"""带完整诊断信息的子进程执行器

职责：封装 subprocess 调用，统一处理超时、编码、平台差异，
并将技术错误按类型分类，保留完整的原始输出，最终生成用户友好的提示。
"""

import subprocess
import platform
import os
import time
from dataclasses import dataclass, field
from typing import List, Optional, Dict

from src.models.install import ErrorCategory, InstallErrorDetail
from src.models.constants import is_windows, is_macos, is_linux


@dataclass
class ShellResult:
    """子进程执行结果（带完整诊断信息）

    Attributes:
        command: 执行的原始命令字符串。
        returncode: 进程返回码，默认 -1 表示未正常结束。
        stdout: 标准输出内容。
        stderr: 标准错误内容。
        elapsed_seconds: 实际执行耗时（秒）。
        timed_out: 是否因超时终止。
        process_not_found: 是否因找不到可执行文件而失败。
        permission_denied: 是否因权限不足而失败。
        error_detail: 结构化错误详情，供 UI 展示友好提示。
    """

    command: str
    returncode: int = -1
    stdout: str = ""
    stderr: str = ""
    elapsed_seconds: float = 0.0
    timed_out: bool = False
    process_not_found: bool = False
    permission_denied: bool = False
    error_detail: Optional[InstallErrorDetail] = None

    @property
    def success(self) -> bool:
        """判断命令是否成功执行

        成功条件：返回码为 0 且未超时、未出现进程未找到错误。
        """
        return self.returncode == 0 and not self.timed_out and not self.process_not_found

    @property
    def combined_output(self) -> str:
        """合并 stdout 和 stderr 的输出（去除首尾空白）"""
        parts = []
        if self.stdout.strip():
            parts.append(self.stdout.strip())
        if self.stderr.strip():
            parts.append(self.stderr.strip())
        return "\n".join(parts)


def get_hidden_startupinfo():
    """获取用于隐藏窗口的 startupinfo（Windows 专用）

    在 Windows 上，子进程默认会弹出控制台窗口；通过设置 STARTUPINFO
    的 STARTF_USESHOWWINDOW 标志并指定 SW_HIDE，可避免安装过程中
    出现闪黑的命令行窗口，提升用户体验。

    Returns:
        subprocess.STARTUPINFO or None: Windows 返回配置好的 startupinfo，
        其他平台返回 None。
    """
    startupinfo = None
    if is_windows():
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startupinfo.wShowWindow = subprocess.SW_HIDE
    return startupinfo


def run_shell(
    command: str,
    timeout: float = 300,
    env: Optional[Dict[str, str]] = None,
    cwd: Optional[str] = None,
    shell: bool = True,
    capture_output: bool = True,
    context: str = "",
    stage: str = "",
) -> ShellResult:
    """执行 shell 命令，返回带完整诊断信息的结果

    平台差异处理：
    - Windows 自动附加 startupinfo 和 CREATE_NO_WINDOW 标志以隐藏窗口。
    - 统一使用 utf-8 编码并设置 errors="replace"，避免非 ASCII 输出导致解码异常崩溃。

    异常处理：
    - TimeoutExpired：记录已收集的输出并分类为 PROCESS_TIMEOUT。
    - FileNotFoundError：分类为 PROCESS_NOT_FOUND。
    - PermissionError：分类为 PERMISSION_DENIED。

    Args:
        command: 要执行的命令字符串。
        timeout: 超时时间（秒），默认 300 秒。
        env: 额外的环境变量字典，会合并到当前进程环境中。
        cwd: 子进程工作目录。
        shell: 是否通过系统 shell 执行（默认 True，支持管道、重定向等）。
        capture_output: 是否捕获 stdout/stderr（默认 True）。
        context: 错误上下文描述（如"正在下载 Node.js"），用于生成用户友好提示。
        stage: 当前阶段标识（如 DOWNLOADING, INSTALLING），用于错误分类统计。

    Returns:
        ShellResult: 包含返回码、输出、耗时及结构化错误详情的执行结果。
    """
    start_time = time.time()
    kwargs = {
        "shell": shell,
        "cwd": cwd,
    }

    if capture_output:
        kwargs["stdout"] = subprocess.PIPE
        kwargs["stderr"] = subprocess.PIPE

    if env is not None:
        kwargs["env"] = env

    if is_windows():
        kwargs["startupinfo"] = get_hidden_startupinfo()
        kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW

    # 编码设置：使用 replace 避免解码失败导致异常崩溃
    # 某些工具（如旧版 Git for Windows）可能输出 GBK 或混合编码，replace 策略可保证程序不中断
    kwargs["text"] = True
    kwargs["encoding"] = "utf-8"
    kwargs["errors"] = "replace"

    result = ShellResult(command=command)

    try:
        proc = subprocess.run(command, timeout=timeout, **kwargs)
        result.returncode = proc.returncode
        if capture_output:
            result.stdout = proc.stdout or ""
            result.stderr = proc.stderr or ""
        result.elapsed_seconds = time.time() - start_time

    except subprocess.TimeoutExpired as e:
        # 超时后仍尝试读取已产生的输出，避免信息丢失
        result.timed_out = True
        result.elapsed_seconds = time.time() - start_time
        if e.stdout:
            result.stdout = (
                e.stdout.decode("utf-8", errors="replace")
                if isinstance(e.stdout, bytes)
                else str(e.stdout)
            )
        if e.stderr:
            result.stderr = (
                e.stderr.decode("utf-8", errors="replace")
                if isinstance(e.stderr, bytes)
                else str(e.stderr)
            )
        result.error_detail = _build_error_detail(
            category=ErrorCategory.PROCESS_TIMEOUT,
            stage=stage,
            context=context,
            raw_error=f"命令执行超时（超过 {timeout} 秒）\n\nstdout:\n{result.stdout}\n\nstderr:\n{result.stderr}",
            command=command,
            returncode=None,
        )

    except FileNotFoundError as e:
        result.process_not_found = True
        result.elapsed_seconds = time.time() - start_time
        result.error_detail = _build_error_detail(
            category=ErrorCategory.PROCESS_NOT_FOUND,
            stage=stage,
            context=context,
            raw_error=str(e),
            command=command,
        )

    except PermissionError as e:
        result.permission_denied = True
        result.elapsed_seconds = time.time() - start_time
        result.error_detail = _build_error_detail(
            category=ErrorCategory.PERMISSION_DENIED,
            stage=stage,
            context=context,
            raw_error=str(e),
            command=command,
        )

    except Exception as e:
        result.elapsed_seconds = time.time() - start_time
        result.error_detail = _build_error_detail(
            category=ErrorCategory.UNKNOWN,
            stage=stage,
            context=context,
            raw_error=f"{type(e).__name__}: {e}",
            command=command,
        )

    # 如果命令执行了但返回非零，尝试根据输出内容进一步分类错误
    if result.error_detail is None and result.returncode != 0:
        result.error_detail = classify_shell_error(result, context, stage)

    return result


def classify_shell_error(
    result: ShellResult, context: str = "", stage: str = ""
) -> Optional[InstallErrorDetail]:
    """根据 shell 输出内容和返回码对错误进行分类

    分类优先级：网络超时 > DNS > SSL > HTTP 错误 > 权限 > 磁盘满 > MSI 特定错误 >
    PowerShell 策略 > 未知。

    Args:
        result: ShellResult 实例，包含 stdout、stderr 和 returncode。
        context: 错误上下文描述。
        stage: 当前阶段标识。

    Returns:
        InstallErrorDetail or None: 结构化错误详情；若 returncode 为 0 则返回 None。
    """
    combined = (result.stdout + result.stderr).lower()
    returncode = result.returncode

    # 网络相关错误码和特征（按优先级排序）
    if any(k in combined for k in ["timeout", "timed out", "连接超时", "无法连接"]):
        return _build_error_detail(
            category=ErrorCategory.NETWORK_TIMEOUT,
            stage=stage,
            context=context,
            raw_error=result.combined_output,
            command=result.command,
            returncode=returncode,
        )

    if any(
        k in combined
        for k in ["getaddrinfo", "name resolution", "nodename nor servname", "无法解析"]
    ):
        return _build_error_detail(
            category=ErrorCategory.NETWORK_DNS,
            stage=stage,
            context=context,
            raw_error=result.combined_output,
            command=result.command,
            returncode=returncode,
        )

    if any(k in combined for k in ["ssl", "tls", "certificate", "cert", "证书"]):
        return _build_error_detail(
            category=ErrorCategory.NETWORK_SSL,
            stage=stage,
            context=context,
            raw_error=result.combined_output,
            command=result.command,
            returncode=returncode,
        )

    if any(
        k in combined for k in ["403", "404", "500", "502", "503", "forbidden", "not found"]
    ):
        return _build_error_detail(
            category=ErrorCategory.NETWORK_HTTP_ERROR,
            stage=stage,
            context=context,
            raw_error=result.combined_output,
            command=result.command,
            returncode=returncode,
        )

    # 权限相关（EACCES 为 Linux/macOS 权限不足的系统错误码）
    if any(
        k in combined
        for k in ["access denied", "permission denied", "拒绝访问", "权限不足", "eacces"]
    ):
        return _build_error_detail(
            category=ErrorCategory.PERMISSION_DENIED,
            stage=stage,
            context=context,
            raw_error=result.combined_output,
            command=result.command,
            returncode=returncode,
        )

    # 磁盘相关
    if any(
        k in combined
        for k in ["no space left", "disk full", "磁盘已满", "空间不足", "insufficient disk"]
    ):
        return _build_error_detail(
            category=ErrorCategory.DISK_FULL,
            stage=stage,
            context=context,
            raw_error=result.combined_output,
            command=result.command,
            returncode=returncode,
        )

    # msiexec 特定错误码（Windows 安装包常见错误）
    if "msiexec" in result.command.lower() or returncode in [1603, 1618, 1619, 1620, 1625, 1633]:
        if returncode == 1603:
            return _build_error_detail(
                category=ErrorCategory.PROCESS_CRASHED,
                stage=stage,
                context=context,
                raw_error=f"msiexec 返回 1603（安装期间出现严重错误）\n\n{result.combined_output}",
                command=result.command,
                returncode=returncode,
            )
        elif returncode == 1618:
            return _build_error_detail(
                category=ErrorCategory.ALREADY_EXISTS,
                stage=stage,
                context=context,
                raw_error=f"msiexec 返回 1618（另一个安装正在进行中）\n\n{result.combined_output}",
                command=result.command,
                returncode=returncode,
            )
        elif returncode == 1619:
            return _build_error_detail(
                category=ErrorCategory.PROCESS_CRASHED,
                stage=stage,
                context=context,
                raw_error=f"msiexec 返回 1619（安装包无法打开）\n\n{result.combined_output}",
                command=result.command,
                returncode=returncode,
            )

    # PowerShell 特定错误（执行策略拦截脚本运行）
    if "powershell" in result.command.lower():
        if "execution policy" in combined:
            return _build_error_detail(
                category=ErrorCategory.PERMISSION_DENIED,
                stage=stage,
                context=context,
                raw_error=f"PowerShell 执行策略被阻止\n\n{result.combined_output}",
                command=result.command,
                returncode=returncode,
            )

    # 默认：根据非零 returncode 归为未知错误
    if returncode != 0:
        return _build_error_detail(
            category=ErrorCategory.UNKNOWN,
            stage=stage,
            context=context,
            raw_error=result.combined_output,
            command=result.command,
            returncode=returncode,
        )

    return None


def _build_error_detail(
    category: ErrorCategory,
    stage: str,
    context: str,
    raw_error: str,
    command: str = "",
    returncode: Optional[int] = None,
) -> InstallErrorDetail:
    """构建 InstallErrorDetail，同时生成 user_message 和 suggestion

    Args:
        category: 错误分类枚举。
        stage: 当前阶段标识。
        context: 错误上下文描述。
        raw_error: 原始错误输出（供技术人员查看）。
        command: 触发错误的命令（可选）。
        returncode: 进程返回码（可选）。

    Returns:
        InstallErrorDetail: 包含分类、用户友好消息、建议及原始错误的结构化对象。
    """
    user_message = _get_user_message(category, context)
    suggestion = _get_suggestion(category)

    return InstallErrorDetail(
        category=category,
        stage=stage,
        context=context,
        raw_error=raw_error,
        user_message=user_message,
        suggestion=suggestion,
        command=command,
        returncode=returncode,
    )


def _get_user_message(category: ErrorCategory, context: str) -> str:
    """根据错误分类生成用户友好的消息

    Args:
        category: 错误分类。
        context: 上下文描述，若有值则追加到消息中。

    Returns:
        str: 本地化后的用户提示消息。
    """
    messages = {
        ErrorCategory.NETWORK_TIMEOUT: "下载超时：连接服务器响应过慢",
        ErrorCategory.NETWORK_DNS: "DNS 解析失败：无法找到服务器地址",
        ErrorCategory.NETWORK_SSL: "SSL/TLS 证书验证失败",
        ErrorCategory.NETWORK_HTTP_ERROR: "服务器返回错误（可能是文件不存在或服务器繁忙）",
        ErrorCategory.PERMISSION_DENIED: "权限不足，无法执行操作",
        ErrorCategory.DISK_FULL: "磁盘空间不足，无法写入文件",
        ErrorCategory.DISK_IO_ERROR: "磁盘读写错误",
        ErrorCategory.PROCESS_TIMEOUT: "操作超时，进程运行时间过长",
        ErrorCategory.PROCESS_NOT_FOUND: "找不到所需的程序（如 PowerShell 或 Git）",
        ErrorCategory.PROCESS_CRASHED: "子进程异常退出",
        ErrorCategory.ANTIVIRUS_BLOCKED: "安全软件阻止了操作",
        ErrorCategory.DEPENDENCY_MISSING: "缺少必要的依赖",
        ErrorCategory.ALREADY_EXISTS: "另一个相同的操作正在进行中",
        ErrorCategory.UNKNOWN: "发生未知错误",
    }
    base = messages.get(category, "发生错误")
    if context:
        return f"{base}\n上下文：{context}"
    return base


def _get_suggestion(category: ErrorCategory) -> str:
    """根据错误分类生成可操作建议

    每条建议针对对应错误场景给出最常见的排查/解决步骤，
    在 UI 中以弹窗或提示区形式展示给用户。

    Args:
        category: 错误分类。

    Returns:
        str: 多行建议文本。
    """
    suggestions = {
        ErrorCategory.NETWORK_TIMEOUT: (
            "1. 检查网络连接是否稳定\n"
            "2. 尝试切换网络（如使用手机热点）\n"
            "3. 暂时关闭 VPN 或代理后重试\n"
            "4. 如果网络较慢，请耐心等待，或稍后重试"
        ),
        ErrorCategory.NETWORK_DNS: (
            "1. 检查 DNS 设置，尝试更换为 114.114.114.114 或 8.8.8.8\n"
            "2. 刷新 DNS 缓存：在命令提示符执行 ipconfig /flushdns\n"
            "3. 检查是否使用了公司内网，可能需要联系 IT 开启访问权限"
        ),
        ErrorCategory.NETWORK_SSL: (
            "1. 检查系统时间是否正确（错误的系统时间会导致 SSL 验证失败）\n"
            "2. 如果是公司内网，可能是中间人设备拦截了 HTTPS，请联系 IT\n"
            "3. 尝试更换网络环境后重试"
        ),
        ErrorCategory.NETWORK_HTTP_ERROR: (
            "1. 可能是镜像源暂时不可用，请稍后重试\n"
            "2. 检查程序版本是否过旧，安装包路径可能已变更\n"
            "3. 尝试手动访问下载地址确认文件是否存在"
        ),
        ErrorCategory.PERMISSION_DENIED: (
            "1. 右键点击本程序，选择\"以管理员身份运行\"\n"
            "2. 暂时关闭杀毒软件或防火墙后重试\n"
            "3. 检查目标目录是否有写入权限"
        ),
        ErrorCategory.DISK_FULL: (
            "1. 清理磁盘空间（尤其是系统盘）\n"
            "2. 检查临时目录空间是否充足\n"
            "3. 卸载不常用的软件释放空间"
        ),
        ErrorCategory.PROCESS_TIMEOUT: (
            "1. 网络较慢时可能需要更长时间，请重试\n"
            "2. 尝试连接更稳定的网络\n"
            "3. 暂时关闭其他占用带宽的程序"
        ),
        ErrorCategory.PROCESS_NOT_FOUND: (
            "1. 系统缺少必要的组件（如 PowerShell 或 Git）\n"
            "2. 如果是公司电脑，可能是组策略限制了程序使用，请联系 IT"
        ),
        ErrorCategory.PROCESS_CRASHED: (
            "1. 可能是安全软件阻止了安装程序，请暂时关闭杀毒软件后重试\n"
            "2. 检查是否已有相同程序正在运行\n"
            "3. 重启电脑后重试"
        ),
        ErrorCategory.ANTIVIRUS_BLOCKED: (
            "1. 暂时关闭 Windows Defender 或第三方杀毒软件\n"
            "2. 将本程序添加到杀毒软件白名单\n"
            "3. 右键安装包选择\"属性\"，勾选\"解除锁定\"后重试"
        ),
        ErrorCategory.ALREADY_EXISTS: (
            "1. 等待其他安装程序完成后再试\n"
            "2. 重启电脑后重试"
        ),
        ErrorCategory.UNKNOWN: (
            "1. 重试安装\n"
            "2. 以管理员身份运行本程序\n"
            "3. 重启电脑后重试\n"
            "4. 查看高级模式中的完整日志，联系技术支持"
        ),
    }
    return suggestions.get(
        category, "请重试，如果问题持续请联系技术支持"
    )
