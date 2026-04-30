"""Git 自动安装器 - Windows 平台

改进点：
1. 下载优先使用 Python urllib.request，避免 PowerShell 管理员网络上下文断裂
2. 完整保留原始错误信息（stdout/stderr/异常堆栈），不再截断
3. 使用 infra.shell_runner 统一执行子进程，自动分类错误类型
4. 失败时输出详细的上下文、用户提示和修复建议
"""

import subprocess
import os
import tempfile
import time
from pathlib import Path
from typing import Callable, Optional

from src.infra.shell_runner import run_shell, ShellResult


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


def download_file(
    url: str, dest_path: Path, on_log: Optional[Callable[[str], None]] = None
) -> bool:
    """下载文件（优先 Python 原生请求，避免 PowerShell 管理员网络上下文断裂）

    失败时会通过 on_log 输出完整的诊断信息，包括：
    - 错误分类（网络超时 / DNS / SSL / HTTP 错误等）
    - 用户友好的提示
    - 具体的修复建议
    - 完整的原始错误输出（不截断）
    """

    def log(msg: str):
        if on_log:
            on_log(msg)
        print(msg)

    # 方法1：Python 原生下载（不依赖 PowerShell，继承当前进程的完整网络上下文）
    try:
        log(f"正在下载: {url[:80]}...")
        import urllib.request
        import ssl

        ctx = ssl.create_default_context()
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, context=ctx, timeout=180) as resp:
            with open(dest_path, "wb") as f:
                f.write(resp.read())
        if dest_path.exists() and dest_path.stat().st_size > 10 * 1024 * 1024:  # > 10MB
            size_mb = dest_path.stat().st_size / 1024 / 1024
            log(f"下载成功: {size_mb:.1f} MB")
            return True
        else:
            actual = dest_path.stat().st_size if dest_path.exists() else 0
            log(f"Python 下载完成但文件过小 ({actual} 字节)，判定为失败")
    except Exception as e:
        log(f"[Python 下载失败] {type(e).__name__}: {str(e)}")

    # 方法2：PowerShell fallback（Python SSL/网络受限时使用）
    try:
        log("尝试 PowerShell 下载...")
        # 使用 -EncodedCommand 避免 cmd 对 PowerShell 语法的引号转义问题
        import base64
        ps_script = (
            f"$ProgressPreference = 'SilentlyContinue'; "
            f"try {{ Invoke-WebRequest -Uri '{url}' -OutFile '{dest_path}' "
            f"-UseBasicParsing -TimeoutSec 180; exit 0 }} catch {{ "
            f"Write-Error \"异常类型: $($_.Exception.GetType().FullName)\"; "
            f"Write-Error \"异常消息: $($_.Exception.Message)\"; "
            f"Write-Error \"堆栈跟踪: $($_.ScriptStackTrace)\"; exit 1 }}"
        )
        encoded = base64.b64encode(ps_script.encode("utf-16le")).decode("ascii")
        ps_cmd = f"powershell -ExecutionPolicy Bypass -EncodedCommand {encoded}"

        result = run_shell(
            ps_cmd,
            timeout=200,
            context=f"从 {url[:80]}... 下载文件到 {dest_path}",
            stage="DOWNLOADING",
        )

        if result.stderr.strip():
            log(f"[PowerShell stderr]\n{result.stderr.strip()}")

        if result.success:
            if dest_path.exists() and dest_path.stat().st_size > 10 * 1024 * 1024:
                size_mb = dest_path.stat().st_size / 1024 / 1024
                log(f"下载成功: {size_mb:.1f} MB (PowerShell)")
                return True
            else:
                actual = dest_path.stat().st_size if dest_path.exists() else 0
                log(f"PowerShell 下载完成但文件过小 ({actual} 字节)")
        else:
            if result.error_detail:
                log(f"[错误分类] {result.error_detail.category.value}")
                log(f"[用户提示] {result.error_detail.user_message}")
                log(f"[修复建议] {result.error_detail.suggestion}")
                # 原始错误完整输出，最多 2000 字符防止日志爆炸，但比之前的 100 多得多
                raw = result.error_detail.raw_error
                if len(raw) > 2000:
                    log(f"[原始错误] {raw[:2000]}\n... (后续截断，共 {len(raw)} 字符)")
                else:
                    log(f"[原始错误] {raw}")
            else:
                log(f"PowerShell 下载失败，returncode={result.returncode}")

        return False

    except Exception as e:
        log(f"[下载异常] {type(e).__name__}: {str(e)}")
        return False


def install_git_windows(on_log: Optional[Callable[[str], None]] = None) -> bool:
    """在 Windows 上静默安装 Git

    安装失败时会输出完整的诊断链：
    哪个镜像源失败 → 什么类型的错误 → 用户应该怎么做
    """

    def log(msg: str):
        if on_log:
            on_log(msg)
        print(msg)

    try:
        git_urls = [
            "https://registry.npmmirror.com/-/binary/git-for-windows/v2.43.0.windows.1/Git-2.43.0-64-bit.exe",
            "https://mirrors.tuna.tsinghua.edu.cn/github-release/git-for-windows/git/LatestRelease/Git-2.47.1-64-bit.exe",
            "https://mirrors.nju.edu.cn/github-release/git-for-windows/git/LatestRelease/Git-2.47.1-64-bit.exe",
            "https://mirrors.aliyun.com/github-release/git-for-windows/git/LatestRelease/Git-2.47.1-64-bit.exe",
            "https://github.com/git-for-windows/git/releases/download/v2.47.1.windows.1/Git-2.47.1-64-bit.exe",
        ]

        with tempfile.TemporaryDirectory() as tmpdir:
            installer_path = Path(tmpdir) / "git-installer.exe"

            # 尝试下载
            downloaded = False
            failed_sources: list[str] = []
            for url in git_urls:
                log(f"尝试镜像源 ({len(failed_sources) + 1}/{len(git_urls)}): {url[:60]}...")
                if download_file(url, installer_path, on_log):
                    downloaded = True
                    log(f"Git 安装包下载成功 ({installer_path.stat().st_size / 1024 / 1024:.1f} MB)")
                    break
                else:
                    failed_sources.append(url)

            if not downloaded:
                log("=" * 50)
                log("[最终错误] 所有 Git 镜像源均下载失败")
                log(f"尝试过的源 ({len(failed_sources)} 个):")
                for i, src in enumerate(failed_sources, 1):
                    log(f"  {i}. {src}")
                log("建议:")
                log("  1. 检查网络连接是否正常")
                log("  2. 如果是公司内网，可能需要联系 IT 开启外部访问")
                log("  3. 手动下载 Git 安装包后重试")
                log("=" * 50)
                return False

            # 静默安装
            install_cmd = (
                f'"{installer_path}" /VERYSILENT /NORESTART /NOCANCEL /SP- /SUPPRESSMSGBOXES'
            )

            log("正在安装 Git...")
            result = run_shell(
                install_cmd,
                timeout=300,
                context="执行 Git 安装程序",
                stage="INSTALLING",
            )

            if result.stderr.strip():
                log(f"[Git 安装 stderr]\n{result.stderr.strip()}")

            if result.success:
                log("Git 安装程序执行成功，等待环境变量刷新...")
                time.sleep(3)

                git_install_paths = [
                    r"C:\Program Files\Git\cmd",
                    r"C:\Program Files\Git\bin",
                    r"C:\Program Files (x86)\Git\cmd",
                ]

                for git_path in git_install_paths:
                    if os.path.exists(git_path):
                        os.environ["PATH"] = git_path + os.pathsep + os.environ.get("PATH", "")
                        log(f"已添加 Git 路径: {git_path}")

                for i in range(5):
                    if is_git_installed():
                        log("Git 验证成功")
                        return True
                    log(f"等待 Git 就绪... ({i + 1}/5)")
                    time.sleep(2)

                log("[最终错误] Git 安装后验证失败：安装程序已执行但系统仍找不到 git 命令")
                log("建议: 重启电脑后重试，或手动安装 Git")
                return False
            else:
                log("=" * 50)
                log("[最终错误] Git 安装程序执行失败")
                if result.error_detail:
                    log(f"[错误分类] {result.error_detail.category.value}")
                    log(f"[用户提示] {result.error_detail.user_message}")
                    log(f"[修复建议] {result.error_detail.suggestion}")
                    raw = result.error_detail.raw_error
                    if len(raw) > 2000:
                        log(f"[原始错误] {raw[:2000]}\n... (后续截断，共 {len(raw)} 字符)")
                    else:
                        log(f"[原始错误] {raw}")
                else:
                    log(f"[原始错误] returncode={result.returncode}, stdout={result.stdout}, stderr={result.stderr}")
                log("=" * 50)
                return False

    except Exception as e:
        log("=" * 50)
        log(f"[最终错误] 安装 Git 时发生未捕获异常: {type(e).__name__}: {str(e)}")
        log("=" * 50)
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
