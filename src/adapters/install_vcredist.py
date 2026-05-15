"""Microsoft Visual C++ Runtime 自动检测/安装 - Windows 平台

用途:OpenClaw 依赖的原生 npm 包(node-llama-cpp/sharp/better-sqlite3 等)的 .node
文件运行时依赖 vcruntime140.dll / msvcp140.dll。这两个 DLL 不随 Windows 系统镜像分发,
普通用户多通过 Office/VSCode/游戏顺手装上 VC++ Redistributable 而拥有,但全新出厂的
笔记本、公司 IT 极简镜像、开发测试虚拟机往往缺失,导致 pnpm install 在 native postinstall
阶段段错误退出(exit code 3221225477 = STATUS_ACCESS_VIOLATION)。

本模块只在 Windows 上有意义,其他平台所有函数都返回安全默认值,可放心 import。

设计要点:
- 检测优先级: 注册表(权威)。HKLM\\SOFTWARE\\Microsoft\\VisualStudio\\14.0\\VC\\Runtimes\\X64
  的 "Installed" REG_DWORD = 1 表示已装。Wow6432Node 路径不查 —— vc_redist 的注册
  在 64 位机器上一律落到 64 位视图。
- 下载优先级: 资源目录(离线版打包) > 镜像列表(在线版)。这样离线版无需联网即可装。
- 安装方式: 静默 + UAC 提权。子进程通过 ShellExecuteW 的 "runas" verb 触发 UAC,
  /quiet /norestart 确保不弹 UI 也不让 vc_redist 自己重启系统。
- 退出码语义:0 = 成功;3010 = 成功但需重启(我们不重启,新进程加载 DLL 即可);
  其他都算失败。
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path
from typing import Callable, Optional

from src.models.constants import is_windows, VCREDIST_X64_MIRRORS, TIMEOUT_DOWNLOAD
from src.models.utils import windows_hidden_subprocess_kwargs


# vc_redist 静默安装的成功退出码:0=新装,1638=已是最新或已存在,3010=成功但建议重启。
# 我们都视为成功 —— 3010 的"重启"对 OpenClaw 不必要,新启动的子进程会加载新 DLL。
_VCREDIST_SUCCESS_EXIT_CODES = (0, 1638, 3010)


def is_vcredist_installed() -> bool:
    """检测 Visual C++ 2015-2022 x64 Redistributable 是否已安装。

    查注册表 HKLM\\SOFTWARE\\Microsoft\\VisualStudio\\14.0\\VC\\Runtimes\\X64
    下的 "Installed" 值。这是 vc_redist 安装时写入的官方标记,vs 2015/2017/2019/2022
    共享同一个键(都是 v14 ABI)。

    Returns:
        True 表示已装;False 表示未装或检测失败(非 Windows 平台)。
    """
    if not is_windows():
        return False

    try:
        import winreg  # 仅 Windows 可用,延迟 import
    except ImportError:
        return False

    # 必须用 64 位视图(KEY_WOW64_64KEY),否则 32 位 Python 进程会被重定向到
    # Wow6432Node 子树,看不到 64 位 VC++ 的真实安装状态。
    try:
        with winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            r"SOFTWARE\Microsoft\VisualStudio\14.0\VC\Runtimes\X64",
            0,
            winreg.KEY_READ | winreg.KEY_WOW64_64KEY,
        ) as key:
            installed, _ = winreg.QueryValueEx(key, "Installed")
            return int(installed) == 1
    except (OSError, FileNotFoundError, ValueError):
        return False


def _resolve_offline_vcredist() -> Optional[str]:
    """查找离线版打包的 vc_redist.x64.exe 路径。

    按以下优先级查找:
    1. PyInstaller 运行时:sys._MEIPASS/resources/windows/vc_redist.x64.exe
    2. 可执行文件同目录
    3. 开发模式:项目根目录下 resources/windows/vc_redist.x64.exe

    Returns:
        若找到返回绝对路径,否则 None(在线版/资源未打包都会返回 None)。
    """
    rel_path = "resources/windows/vc_redist.x64.exe"

    if getattr(sys, "_MEIPASS", None):
        candidate = os.path.join(sys._MEIPASS, rel_path)
        if os.path.isfile(candidate):
            return candidate

    exe_dir = Path(sys.executable).parent.resolve()
    candidate = exe_dir / rel_path
    if candidate.is_file():
        return str(candidate)

    # 开发模式:从 src/adapters/ 向上两级到项目根
    project_root = Path(__file__).parent.parent.parent.resolve()
    candidate = project_root / rel_path
    if candidate.is_file():
        return str(candidate)

    return None


def _download_vcredist(on_log: Optional[Callable[[str], None]] = None) -> Optional[str]:
    """从镜像列表下载 vc_redist.x64.exe 到临时目录。

    Args:
        on_log: 日志回调。

    Returns:
        下载成功返回临时文件路径,失败返回 None。调用方负责事后删除该文件。
    """
    log = on_log or (lambda _msg: None)

    fd, dest = tempfile.mkstemp(suffix="_vc_redist.x64.exe")
    os.close(fd)

    for url in VCREDIST_X64_MIRRORS:
        log(f"正在下载 VC++ 运行库: {url}")
        try:
            req = urllib.request.Request(
                url, headers={"User-Agent": "OpenClaw-Installer/1.0"}
            )
            with urllib.request.urlopen(req, timeout=TIMEOUT_DOWNLOAD) as response:
                with open(dest, "wb") as f:
                    while True:
                        chunk = response.read(64 * 1024)
                        if not chunk:
                            break
                        f.write(chunk)

            size = os.path.getsize(dest)
            # vc_redist.x64.exe 正常 ~25MB;若 <5MB 几乎肯定是错误页面
            if size < 5 * 1024 * 1024:
                log(f"下载文件过小({size} 字节),尝试下一个镜像...")
                continue

            log(f"下载完成: {size / 1024 / 1024:.1f} MB")
            return dest
        except (OSError, urllib.error.URLError) as e:
            log(f"下载失败: {e}")
            continue

    # 所有镜像都失败,清掉空文件
    try:
        os.remove(dest)
    except OSError:
        pass
    return None


def install_vcredist(
    on_log: Optional[Callable[[str], None]] = None,
) -> bool:
    """检测并安装 VC++ x64 运行库(Windows 专用)。

    流程:
    1. 检查是否已装 → 已装则直接返回 True
    2. 优先用离线打包的 vc_redist.x64.exe(若离线版资源存在)
    3. 否则从镜像下载到临时目录
    4. 用 UAC runas 启动 vc_redist /quiet /norestart 静默安装
    5. 等待退出码,判定成功或失败

    Args:
        on_log: 日志回调。

    Returns:
        True 表示已装或安装成功;False 表示安装失败(下载失败 / 用户拒绝 UAC /
        vc_redist 异常退出)。
    """
    log = on_log or (lambda _msg: None)

    if not is_windows():
        return True  # 非 Windows 不需要

    if is_vcredist_installed():
        log("VC++ 运行库已安装")
        return True

    log("未检测到 VC++ 运行库,准备安装...")

    # 1. 优先用离线版打包的 vc_redist
    installer_path = _resolve_offline_vcredist()
    is_temp = False
    if installer_path:
        log(f"使用离线打包的 VC++ 运行库: {installer_path}")
    else:
        # 2. 在线下载
        installer_path = _download_vcredist(on_log=log)
        is_temp = True
        if not installer_path:
            log("VC++ 运行库下载失败")
            return False

    try:
        return _run_vcredist_installer(installer_path, log)
    finally:
        # 在线下载的临时文件用完即删;离线打包的不删
        if is_temp and installer_path and os.path.exists(installer_path):
            try:
                os.remove(installer_path)
            except OSError:
                pass


def _run_vcredist_installer(installer_path: str, log: Callable[[str], None]) -> bool:
    """实际调用 vc_redist.x64.exe 静默安装,通过 UAC 提权。

    用 ShellExecuteW("runas", ...) 触发 UAC 弹窗 —— 这是 Windows 强制要求,
    任何方式都绕不开。subprocess.Popen 不带 UAC 在普通进程下会拒绝执行。

    Args:
        installer_path: vc_redist.x64.exe 的本地路径。
        log: 日志回调。

    Returns:
        True 表示安装成功(返回码 0/1638/3010);False 表示用户拒绝 UAC 或安装失败。
    """
    log("正在弹出 UAC 申请管理员权限...")

    try:
        import ctypes
        from ctypes import wintypes
    except ImportError:
        log("ctypes 不可用,无法触发 UAC")
        return False

    # ShellExecuteEx 才能拿到子进程句柄并等待退出;ShellExecuteW 不返回句柄,
    # 拿不到退出码,无法判定成功/失败。
    SEE_MASK_NOCLOSEPROCESS = 0x00000040

    class SHELLEXECUTEINFOW(ctypes.Structure):
        _fields_ = [
            ("cbSize", wintypes.DWORD),
            ("fMask", ctypes.c_ulong),
            ("hwnd", wintypes.HWND),
            ("lpVerb", wintypes.LPCWSTR),
            ("lpFile", wintypes.LPCWSTR),
            ("lpParameters", wintypes.LPCWSTR),
            ("lpDirectory", wintypes.LPCWSTR),
            ("nShow", ctypes.c_int),
            ("hInstApp", wintypes.HINSTANCE),
            ("lpIDList", ctypes.c_void_p),
            ("lpClass", wintypes.LPCWSTR),
            ("hkeyClass", wintypes.HKEY),
            ("dwHotKey", wintypes.DWORD),
            ("hIcon", wintypes.HANDLE),
            ("hProcess", wintypes.HANDLE),
        ]

    sei = SHELLEXECUTEINFOW()
    sei.cbSize = ctypes.sizeof(sei)
    sei.fMask = SEE_MASK_NOCLOSEPROCESS
    sei.lpVerb = "runas"
    sei.lpFile = installer_path
    sei.lpParameters = "/install /quiet /norestart"
    sei.nShow = 0  # SW_HIDE,不弹 vc_redist UI 窗口

    if not ctypes.windll.shell32.ShellExecuteExW(ctypes.byref(sei)):
        # 失败常见原因:用户在 UAC 弹窗点了"否",GetLastError() = 1223 (ERROR_CANCELLED)
        err = ctypes.windll.kernel32.GetLastError()
        if err == 1223:
            log("用户拒绝了 UAC 提权请求")
        else:
            log(f"UAC 提权失败,GetLastError={err}")
        return False

    log("UAC 已通过,VC++ 安装中(预计 1-2 分钟)...")

    # 等子进程退出
    INFINITE = 0xFFFFFFFF
    ctypes.windll.kernel32.WaitForSingleObject(sei.hProcess, INFINITE)

    exit_code = wintypes.DWORD()
    ctypes.windll.kernel32.GetExitCodeProcess(
        sei.hProcess, ctypes.byref(exit_code)
    )
    ctypes.windll.kernel32.CloseHandle(sei.hProcess)

    rc = exit_code.value
    if rc in _VCREDIST_SUCCESS_EXIT_CODES:
        log(f"VC++ 运行库安装成功(退出码 {rc})")
        return True

    log(f"VC++ 安装失败,退出码: {rc}")
    return False
