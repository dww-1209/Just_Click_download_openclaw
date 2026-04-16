"""Git 自动安装器 - Windows 平台"""

import subprocess
import os
import tempfile
import time
from pathlib import Path
from typing import Callable, Optional


def _get_hidden_startupinfo():
    """获取用于隐藏窗口的 startupinfo（Windows 专用）"""
    startupinfo = None
    if os.name == "nt":
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startupinfo.wShowWindow = 0  # SW_HIDE
    return startupinfo


def is_git_installed() -> bool:
    """检查 Git 是否已安装"""
    try:
        # 尝试多个可能的 git 路径
        git_paths = [
            "git",
            r"C:\Program Files\Git\cmd\git.exe",
            r"C:\Program Files\Git\bin\git.exe",
            r"C:\Program Files (x86)\Git\cmd\git.exe",
        ]

        for git_cmd in git_paths:
            try:
                result = subprocess.run(
                    [git_cmd, "--version"],
                    capture_output=True,
                    shell=True,
                    timeout=5,
                    startupinfo=_get_hidden_startupinfo(),
                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
                )
                if result.returncode == 0:
                    return True
            except Exception:
                continue

        return False
    except Exception:
        return False


def download_file(url: str, dest_path: Path, on_log: Optional[Callable[[str], None]] = None) -> bool:
    """下载文件（使用 PowerShell 避免 SSL 问题）"""
    def log(msg: str):
        if on_log:
            on_log(msg)
        print(msg)
    
    try:
        # 使用 PowerShell 的 Invoke-WebRequest 下载（更可靠）
        log(f"正在下载: {url[:60]}...")
        
        ps_command = f'''
        $ProgressPreference = 'SilentlyContinue'
        try {{
            Invoke-WebRequest -Uri "{url}" -OutFile "{dest_path}" -UseBasicParsing -TimeoutSec 180
            exit 0
        }} catch {{
            Write-Error $_.Exception.Message
            exit 1
        }}
        '''
        
        result = subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps_command],
            capture_output=True,
            timeout=200,
            startupinfo=_get_hidden_startupinfo(),
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        
        if result.returncode == 0:
            # 检查文件大小
            if dest_path.exists() and dest_path.stat().st_size > 10 * 1024 * 1024:  # > 10MB
                size_mb = dest_path.stat().st_size / 1024 / 1024
                log(f"下载成功: {size_mb:.1f} MB")
                return True
        else:
            stderr = result.stderr.decode('utf-8', errors='ignore') if result.stderr else ""
            log(f"下载失败: {stderr[:100]}")
            
        return False
        
    except Exception as e:
        log(f"下载异常: {str(e)[:100]}")
        return False


def install_git_windows(on_log: Optional[Callable[[str], None]] = None) -> bool:
    """在 Windows 上静默安装 Git"""
    def log(msg: str):
        if on_log:
            on_log(msg)
        print(msg)
    
    try:
        # 使用可用的镜像源
        git_urls = [
            # 淘宝 npm 镜像（之前验证最快的源）
            "https://registry.npmmirror.com/-/binary/git-for-windows/v2.43.0.windows.1/Git-2.43.0-64-bit.exe",
            # 清华大学开源软件镜像站（GitHub Release 同步）
            "https://mirrors.tuna.tsinghua.edu.cn/github-release/git-for-windows/git/LatestRelease/Git-2.47.1-64-bit.exe",
            # 南京大学镜像站（备用）
            "https://mirrors.nju.edu.cn/github-release/git-for-windows/git/LatestRelease/Git-2.47.1-64-bit.exe",
            # 阿里云镜像站（备用）
            "https://mirrors.aliyun.com/github-release/git-for-windows/git/LatestRelease/Git-2.47.1-64-bit.exe",
            # GitHub 官方（备用）
            "https://github.com/git-for-windows/git/releases/download/v2.47.1.windows.1/Git-2.47.1-64-bit.exe",
        ]
        
        # 创建临时目录
        with tempfile.TemporaryDirectory() as tmpdir:
            installer_path = Path(tmpdir) / "git-installer.exe"
            
            # 尝试下载
            downloaded = False
            for url in git_urls:
                if download_file(url, installer_path, on_log):
                    downloaded = True
                    log("Git 安装包下载成功")
                    break
                else:
                    log("尝试下一个镜像源...")
            
            if not downloaded:
                log("所有下载源都失败")
                return False
            
            # 静默安装
            install_args = [
                str(installer_path),
                "/VERYSILENT",
                "/NORESTART",
                "/NOCANCEL",
                "/SP-",
                "/SUPPRESSMSGBOXES",
            ]
            
            log("正在安装 Git...")
            result = subprocess.run(
                install_args,
                capture_output=True,
                timeout=300,
                startupinfo=_get_hidden_startupinfo(),
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
            
            if result.returncode == 0:
                log("Git 安装程序执行成功，等待环境变量刷新...")
                time.sleep(3)
                
                # 手动添加 Git 到当前进程 PATH
                git_install_paths = [
                    r"C:\Program Files\Git\cmd",
                    r"C:\Program Files\Git\bin",
                    r"C:\Program Files (x86)\Git\cmd",
                ]
                
                for git_path in git_install_paths:
                    if os.path.exists(git_path):
                        os.environ["PATH"] = git_path + os.pathsep + os.environ.get("PATH", "")
                        log(f"已添加 Git 路径: {git_path}")
                
                # 验证安装
                for i in range(5):
                    if is_git_installed():
                        log("Git 验证成功")
                        return True
                    log(f"等待 Git 就绪... ({i+1}/5)")
                    time.sleep(2)
                
                log("Git 安装后验证失败")
                return False
            else:
                stderr = result.stderr.decode('utf-8', errors='ignore') if result.stderr else ""
                log(f"Git 安装失败，返回码: {result.returncode}")
                if stderr:
                    log(f"错误: {stderr[:200]}")
                return False
                
    except Exception as e:
        log(f"安装 Git 时出错: {str(e)[:200]}")
        return False


def ensure_git_installed(on_log: Optional[Callable[[str], None]] = None) -> bool:
    """确保 Git 已安装"""
    def log(msg: str):
        if on_log:
            on_log(msg)
        print(msg)
    
    if is_git_installed():
        log("Git 已安装")
        return True
    
    log("Git 未安装，正在自动安装...")
    
    if install_git_windows(on_log):
        if is_git_installed():
            log("Git 安装成功")
            return True
        else:
            log("Git 安装后仍无法检测到")
    
    return False


if __name__ == "__main__":
    if ensure_git_installed():
        print("Git 准备就绪")
    else:
        print("Git 安装失败")
