import platform
import os
import shutil
import subprocess
from pathlib import Path
from typing import List
import psutil

from models.env_check import (
    CheckStatus,
    OpenClawStatus,
    DiskSpaceResult,
    NetworkResult,
    PermissionResult,
    OpenClawInstallResult,
    EnvCheckResult,
)


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


def _get_windows_install_paths() -> List[str]:
    paths = []
    # 添加用户目录下的路径（默认安装路径）
    user_home = os.path.expanduser("~")
    paths.append(os.path.join(user_home, "OpenClaw"))
    paths.append(os.path.join(user_home, "openclaw"))
    
    # 添加系统路径
    program_files = os.environ.get("ProgramFiles", "C:\\Program Files")
    program_files_x86 = os.environ.get("ProgramFiles(x86)", "C:\\Program Files (x86)")
    paths.append(os.path.join(program_files, "OpenClaw"))
    paths.append(os.path.join(program_files_x86, "OpenClaw"))

    local_appdata = os.environ.get("LOCALAPPDATA", "")
    if local_appdata:
        paths.append(os.path.join(local_appdata, "OpenClaw"))
    
    # 添加当前工作目录下的路径
    paths.append(os.path.join(os.getcwd(), "OpenClaw"))

    return paths


def _get_os_type() -> str:
    system = platform.system().lower()
    if system == "windows":
        return "windows"
    elif system == "darwin":
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
            
    except Exception as e:
        return DiskSpaceResult(
            status=CheckStatus.FAILED,
            available_gb=0,
            message=f"磁盘检测失败: {str(e)}",
            path=None,
        )


def _check_permission() -> PermissionResult:
    """检查用户目录写入权限"""
    test_dir = None
    try:
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
    except Exception as e:
        error_msg = f"权限检测异常: {type(e).__name__}: {str(e)}"
        return PermissionResult(
            status=CheckStatus.WARNING, 
            message="权限检测异常",
            error_detail=error_msg
        )


def _ensure_local_bin_in_rc():
    """将 ~/.local/bin 添加到用户 shell 配置文件中（如果不存在）"""
    home = os.path.expanduser("~")
    local_bin = os.path.join(home, ".local", "bin")
    path_export = f'export PATH="{local_bin}:$PATH"'
    for rc_file in [".bashrc", ".zshrc", ".profile"]:
        rc_path = os.path.join(home, rc_file)
        if os.path.exists(rc_path):
            try:
                with open(rc_path, "r", encoding="utf-8") as f:
                    content = f.read()
                if local_bin in content:
                    continue
                with open(rc_path, "a", encoding="utf-8") as f:
                    f.write(f"\n# Added by OpenClaw Installer\n{path_export}\n")
            except Exception:
                pass


def _check_openclaw_installed() -> OpenClawInstallResult:
    """检测 OpenClaw 是否已安装
    
    检测逻辑：
    1. 检查系统 PATH 中是否有 openclaw 命令（Linux/macOS 额外包含 ~/.local/bin）
    2. Windows 下若命令找不到，允许 fallback 检查安装目录；Linux/macOS 要求命令必须可用
    """
    os_type = _get_os_type()
    errors = []  # 收集错误信息

    # 1. 检查系统 PATH（Linux/macOS 额外包含 ~/.local/bin）
    env = os.environ.copy()
    if os_type != "windows":
        home = os.path.expanduser("~")
        local_bin = os.path.join(home, ".local", "bin")
        env["PATH"] = f"{local_bin}:{env.get('PATH', '')}"

    if shutil.which("openclaw", path=env.get("PATH")) is not None:
        # 命令存在时，进一步验证是否能正常运行（避免 build 产物缺失的误报）
        try:
            if os_type == "windows":
                result = subprocess.run(
                    ["where", "openclaw"],
                    capture_output=True,
                    text=True,
                    timeout=5
                )
                if result.returncode == 0:
                    exe_path = result.stdout.strip().split('\n')[0].strip()
                    install_path = os.path.dirname(exe_path)
                    return OpenClawInstallResult(
                        status=OpenClawStatus.INSTALLED,
                        install_path=install_path,
                        message=f"已安装: {install_path}",
                    )
                else:
                    errors.append(f"where 命令返回错误码: {result.returncode}")
            else:
                result = subprocess.run(
                    ["which", "openclaw"],
                    capture_output=True,
                    text=True,
                    timeout=5,
                    env=env,
                )
                if result.returncode == 0:
                    exe_path = result.stdout.strip()
                    install_path = os.path.dirname(exe_path)
                    # Linux/macOS：再执行 --version 确保没有 missing dist/entry 等构建错误
                    ver_result = subprocess.run(
                        ["bash", "-c", f'export PATH="{env.get("PATH")}"; openclaw --version'],
                        capture_output=True,
                        text=True,
                        timeout=5,
                    )
                    if ver_result.returncode == 0:
                        return OpenClawInstallResult(
                            status=OpenClawStatus.INSTALLED,
                            install_path=install_path,
                            message=f"已安装: {install_path}",
                        )
                    else:
                        errors.append("openclaw 命令存在但无法正常运行（可能缺少构建产物）")
                else:
                    errors.append(f"which 命令返回错误码: {result.returncode}")
        except subprocess.TimeoutExpired:
            errors.append("检测命令超时")
        except Exception as e:
            errors.append(f"检测命令异常: {type(e).__name__}: {str(e)}")
        
        # 命令存在但验证失败，不直接返回已安装，继续后续自动修复逻辑
        if not errors:
            return OpenClawInstallResult(
                status=OpenClawStatus.INSTALLED,
                message="已安装（命令行检测到）",
            )

    # 2. Windows 允许 fallback 检查安装目录；Linux/macOS 若命令不可用但目录存在，尝试自动修复 PATH
    if os_type == "windows":
        paths_to_check = _get_windows_install_paths()
        openclaw_indicators = [
            "openclaw.exe", "OpenClaw.exe", "openclaw",
            "package.json", "server.js", "app.js",
            "main.py", "config.json", ".openclaw",
        ]
        for path in paths_to_check:
            if os.path.exists(path) and os.path.isdir(path):
                try:
                    items = os.listdir(path)
                    has_indicator = any(
                        indicator.lower() in [item.lower() for item in items]
                        for indicator in openclaw_indicators
                    )
                    if has_indicator:
                        return OpenClawInstallResult(
                            status=OpenClawStatus.INSTALLED,
                            install_path=path,
                            message=f"已安装: {path}",
                        )
                except PermissionError as e:
                    errors.append(f"无法访问路径 {path}: 权限不足")
                except OSError as e:
                    errors.append(f"无法访问路径 {path}: {str(e)}")
    else:
        # Linux/macOS: 若命令不可用但检测到残留目录，自动补写 .bashrc / .zshrc 后重新检测
        residual_paths = [
            os.path.expanduser("~/.openclaw"),
            os.path.expanduser("~/openclaw-cn"),
        ]
        has_residual = any(os.path.exists(p) and os.path.isdir(p) for p in residual_paths)
        if has_residual:
            _ensure_local_bin_in_rc()
            # 重新检测一次（同时验证 --version 确保没有 build 产物缺失）
            result = subprocess.run(
                ["which", "openclaw"],
                capture_output=True,
                text=True,
                timeout=5,
                env=env,
            )
            if result.returncode == 0:
                exe_path = result.stdout.strip()
                install_path = os.path.dirname(exe_path)
                ver_result = subprocess.run(
                    ["bash", "-c", f'export PATH="{env.get("PATH")}"; openclaw --version'],
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                if ver_result.returncode == 0:
                    return OpenClawInstallResult(
                        status=OpenClawStatus.INSTALLED,
                        install_path=install_path,
                        message=f"已安装: {install_path}（已自动修复环境变量）",
                    )
                else:
                    errors.append("openclaw 命令存在但构建产物缺失，建议重新安装以完成编译")

    # 未检测到可用安装
    error_detail = "; ".join(errors) if errors else ""
    return OpenClawInstallResult(
        status=OpenClawStatus.NOT_INSTALLED, 
        message="未检测到 OpenClaw",
        error_detail=error_detail
    )


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
        is_ready=is_ready,
        message=message,
    )
