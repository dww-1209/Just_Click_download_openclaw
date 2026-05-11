"""OpenClaw 环境检测模块

在 US-02 阶段调用，检测：
- 操作系统类型
- 磁盘空间（> 5GB）
- 用户目录写入权限
- Chromium 系浏览器安装情况（提示项，不阻断）
- OpenClaw 是否已安装（命令行可用性 + 目录检测）

注意：US-02 不检测网络，网络问题在 US-04 安装阶段处理。
"""

import os
import shutil
import subprocess
from pathlib import Path
from typing import List
import psutil

from src.models.env_check import (
    CheckStatus,
    OpenClawStatus,
    DiskSpaceResult,
    NetworkResult,
    PermissionResult,
    OpenClawInstallResult,
    BrowserResult,
    EnvCheckResult,
)
from src.models.constants import is_windows, is_macos, is_linux, TIMEOUT_SHORT_CMD
from src.models.utils import resolve_openclaw_cmd


# 最小磁盘空间要求（GB）
MIN_DISK_SPACE_GB = 5


def get_openclaw_install_path() -> str:
    r"""获取 OpenClaw 官方脚本的默认安装路径
    
    官方脚本固定安装到用户目录：
    - Windows: %USERPROFILE%\.openclaw
    - Linux/macOS: ~/.openclaw
    
    Returns:
        安装路径字符串
    """
    home = os.path.expanduser("~")
    return os.path.join(home, ".openclaw")


COMMON_INSTALL_PATHS: List[str] = [
    "/usr/local/OpenClaw",
    "/opt/OpenClaw",
    "/Applications/OpenClaw",
]


def _get_os_type() -> str:
    """获取统一的操作系统类型标识字符串"""
    if is_windows():
        return "windows"
    elif is_macos():
        return "macos"
    else:
        return "linux"


def _check_disk_space() -> DiskSpaceResult:
    """检查 OpenClaw 安装路径的磁盘空间
    
    官方脚本固定安装到用户目录，因此只需要检查该路径所在磁盘的空间。
    
    Returns:
        DiskSpaceResult: 包含状态、可用空间GB、路径信息和消息
    """
    try:
        # 获取官方脚本的安装路径
        install_path = get_openclaw_install_path()
        
        # 获取路径所在的磁盘分区
        path_obj = Path(install_path)
        
        # 如果路径不存在，获取其父目录
        check_path = path_obj if path_obj.exists() else path_obj.parent
        
        try:
            usage = psutil.disk_usage(str(check_path))
            available_gb = usage.free / (1024**3)
        except (PermissionError, OSError) as e:
            return DiskSpaceResult(
                status=CheckStatus.FAILED,
                available_gb=0,
                message=f"无法访问安装路径磁盘: {str(e)}",
                path=install_path,
            )
        
        # 格式化路径显示（缩短用户目录为 ~）
        home = os.path.expanduser("~")
        display_path = install_path.replace(home, "~")
        
        if available_gb >= MIN_DISK_SPACE_GB:
            return DiskSpaceResult(
                status=CheckStatus.OK,
                available_gb=available_gb,
                message=f"可用空间: {available_gb:.1f}GB",
                path=display_path,
            )
        else:
            return DiskSpaceResult(
                status=CheckStatus.FAILED,
                available_gb=available_gb,
                message=f"空间不足: 可用 {available_gb:.1f}GB，需要至少 {MIN_DISK_SPACE_GB}GB",
                path=display_path,
            )
            
    except (OSError, ValueError, TypeError) as e:
        return DiskSpaceResult(
            status=CheckStatus.FAILED,
            available_gb=0,
            message=f"磁盘检测失败: {str(e)}",
            path=None,
        )


def _check_permission() -> PermissionResult:
    """检查用户目录写入权限

    在用户主目录下创建临时文件并删除，验证安装所需的写入权限。
    使用 WARNING 而非 FAILED，因为权限不足不一定完全阻断安装
   （部分场景仍可正常执行）。
    """
    test_dir = None
    try:
        # 创建临时测试目录和文件，验证读写删能力
        test_dir = Path.home() / ".openclaw_test"
        test_dir.mkdir(parents=True, exist_ok=True)
        test_file = test_dir / "test.txt"
        test_file.write_text("test")
        test_file.unlink()
        test_dir.rmdir()
        return PermissionResult(status=CheckStatus.OK, message="权限正常")

    except PermissionError as e:
        error_msg = f"无法写入用户目录: {str(e)}"
        return PermissionResult(
            status=CheckStatus.WARNING,
            message="权限不足，建议以管理员身份运行",
            error_detail=error_msg
        )
    except OSError as e:
        error_msg = f"磁盘操作失败: {str(e)}"
        return PermissionResult(
            status=CheckStatus.WARNING,
            message=f"文件系统错误: {str(e)}",
            error_detail=error_msg
        )
    except (ValueError, TypeError, RuntimeError) as e:
        error_msg = f"权限检测异常: {type(e).__name__}: {str(e)}"
        return PermissionResult(
            status=CheckStatus.WARNING,
            message="权限检测异常",
            error_detail=error_msg
        )


def _ensure_local_bin_in_rc() -> None:
    """将 ~/.local/bin 添加到用户 shell 配置文件中（如果不存在）"""
    home = os.path.expanduser("~")
    local_bin = os.path.join(home, ".local", "bin")
    path_export = f'export PATH="{local_bin}:$PATH"'
    written = False
    for rc_file in [".bashrc", ".zshrc", ".profile"]:
        rc_path = os.path.join(home, rc_file)
        if os.path.exists(rc_path):
            try:
                with open(rc_path, "r", encoding="utf-8") as f:
                    content = f.read()
                if local_bin in content:
                    written = True
                    continue
                with open(rc_path, "a", encoding="utf-8") as f:
                    f.write(f"\n# Added by OpenClaw Installer\n{path_export}\n")
                written = True
            except (OSError, ValueError):
                pass

    # 如果没有任何 rc 文件存在（全新系统），主动创建一个
    if not written:
        default_rc = ".zshrc" if is_macos() else ".bashrc"
        rc_path = os.path.join(home, default_rc)
        try:
            with open(rc_path, "w", encoding="utf-8") as f:
                f.write(f"# Created by OpenClaw Installer\n{path_export}\n")
        except (OSError, ValueError):
            pass



def _check_openclaw_installed() -> OpenClawInstallResult:
    """检测 OpenClaw 是否已安装

    判定逻辑(Windows / macOS / Linux 三平台一视同仁,核心是权威标志文件):

    1. **权威标志文件** —— `~/.openclaw/openclaw.json` 或 `~/openclaw-cn/dist/`
       且 dist 目录非空。这两者是安装器流程"成功完成"的真实痕迹:
       - openclaw.json 在用户首次 onboard / 配置 API Key 时生成
       - dist/ 是 pnpm build 后的输出
       任意一个存在就是已安装。注意 dist 必须**非空**:Windows 上 rmdir 偶尔
       会把 dist 里的文件删干净,但因为 scanner 持有 dist 自身的目录句柄而留下
       一个空壳文件夹 —— 那不是真的"已安装"。

    2. **macOS / Linux** 额外走 `which` + `{cmd} --version`,兼容历史
       `npm install -g` 装法,并用 `--version` 校验排除卸载残留的孤儿包装器。
       Windows **不走 PATH 兜底** —— `where` 找到 .cmd 不代表程序还在
       (cmd 包装器只是 `cd <project_dir> && pnpm openclaw`,目录被删了 cd 就
       静默失败,壳子还在但程序已经废了);Mac 上的 `--version` 校验在 Windows
       要冷启 Node 10-20s,会卡 UI,所以 Windows 完全依赖 Step 1。

    3. **macOS / Linux** 命令不可用但有残留时,自动写 `.bashrc/.zshrc`
       后重新检测一次 —— 应对"程序在但 PATH 没生效"的边缘情况。

    历史曾在 Windows 上扫 `~/OpenClaw / Program Files/OpenClaw / %LOCALAPPDATA%/OpenClaw`
    等"兜底"路径,只要有 `openclaw-cn`/`openclaw.json` 就算已安装 —— 这是误报根源
    之一,Mac 没有这一步,所以已经移除。
    """
    os_type = _get_os_type()
    errors = []  # 收集错误信息
    home = os.path.expanduser("~")

    # === Step 1: 权威标志文件 ===
    # 我们的安装器正常完成后,这两个文件至少有一个会存在。卸载只要把它们删了,
    # 即使 force_rmtree 失败留下空壳目录或锁定的 node_modules,这一步也会判 NOT_INSTALLED。
    config_file = os.path.join(home, ".openclaw", "openclaw.json")
    dist_dir = os.path.join(home, "openclaw-cn", "dist")
    if os.path.isfile(config_file):
        install_path = os.path.dirname(config_file)
        return OpenClawInstallResult(
            status=OpenClawStatus.INSTALLED,
            install_path=install_path,
            message=f"已安装: {install_path}",
        )
    # dist 必须存在**且非空**。Windows 卸载 rmdir 偶尔会把 dist 里的文件全清掉
    # 但留个空壳 —— 那是残留,不是安装。
    if os.path.isdir(dist_dir):
        try:
            if os.listdir(dist_dir):
                install_path = os.path.dirname(dist_dir)
                return OpenClawInstallResult(
                    status=OpenClawStatus.INSTALLED,
                    install_path=install_path,
                    message=f"已安装: {install_path}",
                )
        except OSError:
            pass

    # === Windows: Step 1 没命中就直接判 NOT_INSTALLED ===
    # 不走 PATH 兜底,理由见 docstring。
    if is_windows():
        return OpenClawInstallResult(
            status=OpenClawStatus.NOT_INSTALLED,
            message="未检测到 OpenClaw",
        )

    # === Step 2 (macOS / Linux 专用): which + --version 校验 ===
    env = os.environ.copy()
    local_bin = os.path.join(home, ".local", "bin")
    env["PATH"] = f"{local_bin}:{env.get('PATH', '')}"

    cmd = resolve_openclaw_cmd(env)

    cmd_found = False
    install_path = ""
    try:
        result = subprocess.run(
            ["which", cmd], capture_output=True, text=True, timeout=TIMEOUT_SHORT_CMD, env=env
        )
        if result.returncode == 0:
            exe_path = result.stdout.strip()
            install_path = os.path.dirname(exe_path)
            cmd_found = True
    except (OSError, subprocess.SubprocessError) as e:
        errors.append(f"检测命令异常: {type(e).__name__}: {str(e)}")

    if cmd_found:
        try:
            shell = os.environ.get("SHELL", "/bin/bash")
            ver_result = subprocess.run(
                [shell, "-ilc", f"{cmd} --version"],
                capture_output=True, text=True, timeout=TIMEOUT_SHORT_CMD,
            )
            if ver_result.returncode != 0:
                errors.append(f"{cmd} 命令存在但无法正常运行(可能缺少构建产物)")
            elif not errors:
                return OpenClawInstallResult(
                    status=OpenClawStatus.INSTALLED,
                    install_path=install_path,
                    message=f"已安装: {install_path}",
                )
        except (OSError, subprocess.SubprocessError) as e:
            errors.append(f"验证命令异常: {type(e).__name__}: {str(e)}")

    # === Step 3 (macOS / Linux 专用): 命令不可用但有残留目录,自动补 PATH 后重试 ===
    # 对应"残留目录 + 命令包装器还在 PATH 但 PATH 没生效"的边缘情况。
    residual_paths = [
        os.path.expanduser("~/.openclaw"),
        os.path.expanduser("~/openclaw-cn"),
    ]
    has_residual = any(os.path.exists(p) and os.path.isdir(p) for p in residual_paths)
    if has_residual:
        _ensure_local_bin_in_rc()
        cmd2 = resolve_openclaw_cmd(env)
        result = subprocess.run(
            ["which", cmd2],
            capture_output=True,
            text=True,
            timeout=TIMEOUT_SHORT_CMD,
            env=env,
        )
        if result.returncode == 0:
            exe_path = result.stdout.strip()
            install_path = os.path.dirname(exe_path)
            shell = os.environ.get("SHELL", "/bin/bash")
            ver_result = subprocess.run(
                [shell, "-ilc", f"{cmd2} --version"],
                capture_output=True,
                text=True,
                timeout=TIMEOUT_SHORT_CMD,
            )
            if ver_result.returncode == 0:
                return OpenClawInstallResult(
                    status=OpenClawStatus.INSTALLED,
                    install_path=install_path,
                    message=f"已安装: {install_path}(已自动修复环境变量)",
                )
            else:
                errors.append(f"{cmd2} 命令存在但构建产物缺失,建议重新安装以完成编译")

    # 未检测到可用安装
    error_detail = "; ".join(errors) if errors else ""
    return OpenClawInstallResult(
        status=OpenClawStatus.NOT_INSTALLED,
        message="未检测到 OpenClaw",
        error_detail=error_detail,
    )


def _check_browser() -> BrowserResult:
    """检测系统是否安装了 Chromium 系浏览器（Chrome/Edge/Brave 等）
    
    浏览器自动化功能（Playwright + CDP）需要 Chromium 系浏览器，Safari 不支持。
    这是一个提示项，不影响安装流程（is_ready 不受影响）。
    """
    found = []
    candidates = []

    if is_macos():
        # macOS
        candidates = [
            ("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome", "Google Chrome"),
            (os.path.expanduser("~/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"), "Google Chrome"),
            ("/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge", "Microsoft Edge"),
            (os.path.expanduser("~/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge"), "Microsoft Edge"),
            ("/Applications/Brave Browser.app/Contents/MacOS/Brave Browser", "Brave Browser"),
            (os.path.expanduser("~/Applications/Brave Browser.app/Contents/MacOS/Brave Browser"), "Brave Browser"),
            ("/Applications/Google Chrome Canary.app/Contents/MacOS/Google Chrome Canary", "Chrome Canary"),
            ("/Applications/Chromium.app/Contents/MacOS/Chromium", "Chromium"),
        ]
    elif is_windows():
        # Windows
        local_appdata = os.environ.get("LOCALAPPDATA", "")
        program_files = os.environ.get("ProgramFiles", "C:\\Program Files")
        program_files_x86 = os.environ.get("ProgramFiles(x86)", "C:\\Program Files (x86)")
        candidates = [
            (os.path.join(local_appdata, "Google", "Chrome", "Application", "chrome.exe"), "Google Chrome"),
            (os.path.join(program_files, "Google", "Chrome", "Application", "chrome.exe"), "Google Chrome"),
            (os.path.join(program_files_x86, "Google", "Chrome", "Application", "chrome.exe"), "Google Chrome"),
            (os.path.join(local_appdata, "Microsoft", "Edge", "Application", "msedge.exe"), "Microsoft Edge"),
            (os.path.join(program_files, "Microsoft", "Edge", "Application", "msedge.exe"), "Microsoft Edge"),
            (os.path.join(program_files_x86, "Microsoft", "Edge", "Application", "msedge.exe"), "Microsoft Edge"),
            (os.path.join(local_appdata, "BraveSoftware", "Brave-Browser", "Application", "brave.exe"), "Brave Browser"),
            (os.path.join(program_files, "BraveSoftware", "Brave-Browser", "Application", "brave.exe"), "Brave Browser"),
            (os.path.join(program_files_x86, "BraveSoftware", "Brave-Browser", "Application", "brave.exe"), "Brave Browser"),
        ]
        # 备用：通过 where/shutil.which 检测 PATH 中的浏览器
        try:
            path_candidates = {
                "msedge": "Microsoft Edge",
                "chrome": "Google Chrome",
                "brave": "Brave Browser",
            }
            for exe, name in path_candidates.items():
                if shutil.which(exe) and name not in found:
                    found.append(name)
        except (OSError, ValueError):
            pass
    else:
        # Linux
        candidates = [
            ("/usr/bin/google-chrome", "Google Chrome"),
            ("/usr/bin/google-chrome-stable", "Google Chrome"),
            ("/usr/bin/microsoft-edge", "Microsoft Edge"),
            ("/usr/bin/microsoft-edge-stable", "Microsoft Edge"),
            ("/usr/bin/brave-browser", "Brave Browser"),
            ("/usr/bin/brave", "Brave Browser"),
            ("/usr/bin/chromium", "Chromium"),
            ("/usr/bin/chromium-browser", "Chromium"),
        ]

    for path, name in candidates:
        if os.path.exists(path):
            if name not in found:
                found.append(name)

    if found:
        return BrowserResult(
            status=CheckStatus.OK,
            found_browsers=found,
            message=f"已安装: {', '.join(found)}",
        )
    else:
        return BrowserResult(
            status=CheckStatus.WARNING,
            found_browsers=[],
            message="未检测到 Chrome/Edge/Brave，浏览器自动化功能不可用",
        )


class SystemChecker:
    """系统环境检测器 — IEnvChecker 的具体实现。"""

    def check(self, install_path: str = None) -> EnvCheckResult:
        """执行环境检测。委托给模块级 check_environment 函数以保持兼容。"""
        return check_environment(install_path)


def check_environment(install_path: str = None) -> EnvCheckResult:
    """检查环境
    
    Args:
        install_path: 保留参数（已废弃），官方脚本固定安装到用户目录
    
    Returns:
        EnvCheckResult: 环境检测结果
    """
    os_type = _get_os_type()
    disk_result = _check_disk_space()
    permission_result = _check_permission()
    openclaw_result = _check_openclaw_installed()
    browser_result = _check_browser()

    # US-02 阶段不检测网络，留空或跳过
    # 网络检测将在 US-04 下载阶段由命令行自行处理
    network_result = None

    is_ready = disk_result.status != CheckStatus.FAILED

    message = "环境检测完成"
    if not is_ready:
        message = "环境检测未通过，请根据提示处理后重试"

    return EnvCheckResult(
        os_type=os_type,
        disk_space=disk_result,
        network=network_result,
        permission=permission_result,
        openclaw_install=openclaw_result,
        browser=browser_result,
        is_ready=is_ready,
        message=message,
    )
