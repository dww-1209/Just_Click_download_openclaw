import subprocess
import platform
import os
import signal
import shutil
import time
import sys
import stat
import threading

from pathlib import Path
from typing import List, Callable, Optional

# 只在非 Windows 平台导入 select
if platform.system().lower() != "windows":
    import select

from models.install import (
    InstallStatus,
    InstallStage,
    InstallProgress,
    InstallResult,
    InstallErrorDetail,
    ErrorCategory,
    get_official_command,
)
from infra.git_installer import ensure_git_installed
from infra.shell_runner import run_shell, ShellResult


class OpenClawInstaller:
    """OpenClaw 安装器 - 底层命令执行"""

    def __init__(self, os_type: str = None):
        self.os_type = os_type or platform.system().lower()
        if self.os_type == "darwin":
            self.os_type = "macos"

        self.process: Optional[subprocess.Popen] = None
        self.log_lines: List[str] = []
        self.is_cancelled = False
        self.start_time: float = 0.0

    @staticmethod
    def _remove_readonly(func, path, _):
        os.chmod(path, stat.S_IWRITE)
        func(path)

    def install(
        self,
        on_progress: Callable[[InstallProgress], None] = None,
        on_log: Callable[[str], None] = None,
    ) -> InstallResult:
        """执行安装（全平台统一使用 Gitee + pnpm 本地构建）"""
        self.start_time = time.time()
        self.log_lines = []
        self.is_cancelled = False

        try:
            if on_progress:
                on_progress(
                    InstallProgress(
                        stage=InstallStage.DOWNLOADING,
                        progress_percent=5,
                        message="正在检查依赖环境...",
                        current_task="检查前置依赖",
                    )
                )

            if self.os_type == "windows":
                self._log("检查 Git 安装状态...", on_log)
                if not ensure_git_installed(on_log=lambda msg: self._log(msg, on_log)):
                    return InstallResult(
                        status=InstallStatus.FAILED,
                        message="Git 安装失败",
                        error_message="自动安装 Git 失败，请手动安装 Git 后重试\n下载地址: https://git-scm.com/download/win",
                        log_lines=self.log_lines.copy(),
                        duration_seconds=time.time() - self.start_time,
                    )
                self._log("Git 已就绪", on_log)
            elif self.os_type == "macos":
                self._log("检查前置依赖 (git, curl)...", on_log)
                for cmd, name in [("git", "Git"), ("curl", "curl")]:
                    try:
                        result = subprocess.run([cmd, "--version"], capture_output=True, shell=False, timeout=5)
                        if result.returncode != 0:
                            raise FileNotFoundError()
                    except FileNotFoundError:
                        return InstallResult(
                            status=InstallStatus.FAILED,
                            message=f"缺少 {name}",
                            error_message=f"系统未找到 {name}，请安装 Xcode Command Line Tools 后重试。",
                            log_lines=self.log_lines.copy(),
                            duration_seconds=time.time() - self.start_time,
                        )
                self._log("前置依赖已就绪", on_log)
            else:
                # Linux
                self._log("检查前置依赖 (git, curl)...", on_log)
                missing_deps = []
                for cmd, name in [("git", "Git"), ("curl", "curl")]:
                    try:
                        result = subprocess.run([cmd, "--version"], capture_output=True, shell=False, timeout=5)
                        if result.returncode != 0:
                            missing_deps.append(name)
                    except FileNotFoundError:
                        missing_deps.append(name)
                if missing_deps:
                    self._log(f"缺少依赖: {', '.join(missing_deps)}，将在系统授权后自动安装", on_log)
                else:
                    self._log("前置依赖已就绪", on_log)

                self._log("正在安装系统依赖 (Node.js 22, pnpm)...", on_log)
                pkexec_dep_cmd = (
                    "pkexec bash -c '"
                    "apt update >/dev/null 2>&1; "
                    "curl -fsSL https://deb.nodesource.com/setup_22.x | bash -E - >/dev/null 2>&1; "
                    "apt-get install -y nodejs git curl >/dev/null 2>&1; "
                    "npm install -g pnpm >/dev/null 2>&1; "
                    "echo \"[OK] system deps ready\""
                    "'"
                )
                dep_result = subprocess.run(
                    pkexec_dep_cmd, shell=True, capture_output=True, text=True, timeout=600
                )
                if dep_result.stdout:
                    for line in dep_result.stdout.splitlines():
                        if line.strip():
                            self._log(line.strip(), on_log)
                if dep_result.returncode != 0:
                    err = dep_result.stderr.strip() if dep_result.stderr else "系统依赖安装失败"
                    self._log(err, on_log)
                    return InstallResult(
                        status=InstallStatus.FAILED,
                        message="系统依赖安装失败",
                        error_message=f"自动安装 Node.js 失败，请确保网络畅通后重试。\n错误：{err}",
                        log_lines=self.log_lines.copy(),
                        duration_seconds=time.time() - self.start_time,
                        error_detail=InstallErrorDetail(
                            category=ErrorCategory.NETWORK_UNKNOWN,
                            stage="INSTALLING",
                            context="Linux 系统依赖安装 (pkexec)",
                            raw_error=err,
                            user_message="Linux 系统依赖安装失败",
                            suggestion="1. 确保网络畅通后重试\n2. 手动执行: sudo apt install -y nodejs git curl",
                        ),
                    )
                self._log("系统依赖安装完成", on_log)

            # 清理残留目录
            cleanup_dirs = [
                os.path.expanduser("~\\openclaw") if self.os_type == "windows" else os.path.expanduser("~/.openclaw"),
                os.path.expanduser("~\\openclaw-cn") if self.os_type == "windows" else os.path.expanduser("~/openclaw-cn"),
            ]
            if self.os_type == "windows":
                cleanup_dirs.extend([
                    os.path.expanduser(r"~\AppData\Local\openclaw"),
                    os.path.expanduser(r"~\AppData\Roaming\npm\node_modules\openclaw"),
                    os.path.expanduser(r"~\AppData\Roaming\npm\node_modules\openclaw-cn"),
                ])
            for d in cleanup_dirs:
                if os.path.exists(d):
                    try:
                        shutil.rmtree(d, onerror=self._remove_readonly)
                        self._log(f"已清理残留目录: {d}", on_log)
                    except Exception as e:
                        self._log(f"清理残留目录失败 {d}: {e}", on_log)

            # 统一走本地构建流程
            target_dir = os.path.expanduser("~\\openclaw-cn") if self.os_type == "windows" else os.path.expanduser("~/openclaw-cn")
            return self._install_local_build(target_dir, on_progress, on_log)

        except Exception as e:
            error_msg = f"安装过程出错: {str(e)}"
            self._log(error_msg, on_log)
            return InstallResult(
                status=InstallStatus.FAILED,
                message="安装失败",
                error_message=error_msg,
                log_lines=self.log_lines.copy(),
                duration_seconds=time.time() - self.start_time,
            )

    def _execute_command(
        self,
        command: str,
        on_progress: Callable[[InstallProgress], None],
        on_log: Callable[[str], None],
    ) -> InstallResult:
        """执行安装命令（隐藏窗口）"""
        try:
            # 根据操作系统设置启动参数（隐藏窗口）
            startupinfo = None
            creationflags = 0
            env = os.environ.copy()
            
            if platform.system().lower() == "windows":
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                startupinfo.wShowWindow = subprocess.SW_HIDE
                creationflags = subprocess.CREATE_NO_WINDOW
                # 设置 PowerShell 输出编码为 UTF-8，避免中文乱码
                env["PYTHONIOENCODING"] = "utf-8"

            # 配置 npm/pnpm 环境变量，加速依赖下载并兼容预置包注入
            env["npm_config_registry"] = "https://registry.npmmirror.com"
            env["npm_config_shamefully_hoist"] = "true"
            env["npm_config_prefer_offline"] = "true"
            env["ELECTRON_MIRROR"] = "https://npmmirror.com/mirrors/electron/"
            env["ELECTRON_BUILDER_BINARIES_MIRROR"] = "https://npmmirror.com/mirrors/electron-builder-binaries/"
            if platform.system().lower() in ("linux", "darwin"):
                # Linux/macOS 额外保留之前的镜像配置（已合并到上面通用配置）
                pass

            self._log(f"启动安装进程...", on_log)

            # 启动子进程
            # 使用官方管道命令（curl | bash 或 iwr | iex）
            self.process = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                universal_newlines=True,
                bufsize=1,
                encoding='utf-8',
                errors='replace',
                startupinfo=startupinfo,
                creationflags=creationflags,
                shell=True,
                env=env,
            )

            # 实时读取输出
            progress = 5  # 起始进度
            line_count = 0
            last_progress_update = time.time()
            last_progress_emit = time.time()
            current_stage = InstallStage.DOWNLOADING  # 默认阶段
            last_emitted_message = ""
            last_emitted_task = ""
            slow_download_hint = False
            
            # 管道命令可能没有实时输出，所以需要定时更新进度
            while True:
                if self.is_cancelled:
                    self._terminate_process()
                    return InstallResult(
                        status=InstallStatus.CANCELLED,
                        message="安装已取消",
                        log_lines=self.log_lines.copy(),
                        duration_seconds=time.time() - self.start_time,
                    )

                current_time = time.time()
                should_emit = False
                
                # 非阻塞读取输出（Windows 兼容方式）
                output = None
                if platform.system().lower() == "windows":
                    # Windows: 直接使用 readline（有超时机制）
                    try:
                        output = self.process.stdout.readline()
                    except (ValueError, OSError):
                        pass
                else:
                    # Unix/Linux/macOS: 使用 select 实现非阻塞
                    if hasattr(self.process.stdout, 'fileno'):
                        try:
                            readable, _, _ = select.select([self.process.stdout], [], [], 0.1)
                            if readable:
                                output = self.process.stdout.readline()
                        except (ValueError, OSError):
                            pass
                
                if output:
                    line = output.strip()
                    if line:  # 只记录非空行
                        self._log(line, on_log)
                        line_count += 1

                        # 根据日志内容检测阶段
                        line_lower = line.lower()
                        if any(
                            keyword in line_lower
                            for keyword in ["download", "downloading", "下载", "获取", "curl", "iwr"]
                        ):
                            current_stage = InstallStage.DOWNLOADING
                            if progress < 30:
                                progress = min(progress + 5, 30)
                                should_emit = True
                        elif any(
                            keyword in line_lower
                            for keyword in ["install", "installing", "安装", "npm", "node", "postinstall", "matrix-sdk"]
                        ):
                            current_stage = InstallStage.INSTALLING
                            if progress < 70:
                                progress = min(progress + 3, 70)
                                should_emit = True
                        elif any(
                            keyword in line_lower
                            for keyword in ["config", "configure", "配置", "设置", "done", "success"]
                        ):
                            current_stage = InstallStage.CONFIGURING
                            if progress < 90:
                                progress = min(progress + 2, 90)
                                should_emit = True
                        
                        # 检测到 npm 慢速下载日志时，给出友好提示
                        if any(k in line_lower for k in ["kb/s", "mb/s", "downloading", "extracting", "postinstall"]):
                            slow_download_hint = True
                
                # 定时更新进度（即使没输出也要动）
                if current_time - last_progress_update > 5.0:  # 每5秒更新一次
                    if progress < 90:
                        progress = min(progress + 2, 90)
                    last_progress_update = current_time
                    should_emit = True
                
                # 定期发送进度更新（每5秒，且只在内容变化时）
                if on_progress and (current_time - last_progress_emit > 5.0):
                    should_emit = True
                
                if should_emit and on_progress:
                    base_message = {
                        InstallStage.DOWNLOADING: "正在下载 OpenClaw...",
                        InstallStage.INSTALLING: "正在安装 OpenClaw...",
                        InstallStage.CONFIGURING: "正在配置 OpenClaw...",
                    }.get(current_stage, "正在安装...")
                    
                    if slow_download_hint and current_stage == InstallStage.INSTALLING:
                        progress_message = "正在下载 Node.js 依赖，网络较慢时请耐心等待..."
                    else:
                        progress_message = base_message

                    current_task = "正在执行官方安装脚本..." if line_count == 0 else f"已处理 {line_count} 行输出"
                    
                    if progress_message != last_emitted_message or current_task != last_emitted_task:
                        on_progress(
                            InstallProgress(
                                stage=current_stage,
                                progress_percent=progress,
                                message=progress_message,
                                current_task=current_task,
                            )
                        )
                        last_emitted_message = progress_message
                        last_emitted_task = current_task
                        last_progress_emit = current_time

                # 检查进程是否结束
                retcode = self.process.poll()
                if retcode is not None:
                    # 读取剩余输出
                    remaining = self.process.stdout.read()
                    if remaining:
                        for line in remaining.splitlines():
                            if line.strip():
                                self._log(line.strip(), on_log)
                    break

            # 处理结果
            if self.process.returncode == 0:
                self._log("安装命令执行成功", on_log)
                self._ensure_local_bin_in_path(on_log)

                if on_progress:
                    on_progress(
                        InstallProgress(
                            stage=InstallStage.COMPLETED,
                            progress_percent=100,
                            message="安装完成",
                            current_task="完成",
                        )
                    )

                return InstallResult(
                    status=InstallStatus.SUCCESS,
                    message="OpenClaw 安装成功",
                    log_lines=self.log_lines.copy(),
                    duration_seconds=time.time() - self.start_time,
                )
            else:
                # Linux: 官方脚本安装主体完成后，最后一步 TTY 交互初始化可能失败（GUI 无终端）
                # 这里如实返回 FAILED，由外层 install() 方法统一做补救（npm link + 命令验证）
                if platform.system().lower() == "linux":
                    log_text_all = "\n".join(self.log_lines)
                    if any(
                        marker in log_text_all for marker in ["安装完成", "OpenClaw CN 安装完成", "✓ OpenClaw CN"]
                    ):
                        self._log("检测到 OpenClaw 安装主体已完成，但脚本因 TTY 缺失返回非零，将尝试补救", on_log)
                
                # 根据操作系统提供友好的错误提示
                if platform.system().lower() == "windows":
                    if self.process.returncode == 1:
                        error_msg = (
                            "安装失败：可能是以下原因：\n"
                            "1. 网络连接问题（请检查网络）\n"
                            "2. PowerShell 权限限制\n"
                            "3. 安全软件阻止了安装\n\n"
                            "建议：\n"
                            "- 关闭杀毒软件/防火墙后重试\n"
                            "- 确保网络连接正常\n"
                            "- 以管理员身份重新运行本程序"
                        )
                    else:
                        error_msg = f"安装命令返回错误码: {self.process.returncode}，建议以管理员身份运行"
                else:
                    os_name = platform.system().lower()
                    log_text = "\n".join(self.log_lines[-20:])
                    
                    if os_name == "linux" and ("cmake" in log_text.lower() or "node-llama-cpp" in log_text.lower()):
                        error_msg = (
                            "安装失败：Node.js 依赖编译环境不足或网络受限\n\n"
                            "可能原因：\n"
                            "1. 访问 GitHub 下载 cmake 二进制失败\n"
                            "2. 系统缺少 cmake/make/g++ 编译工具\n\n"
                            "建议：\n"
                            "- 确保网络可访问 GitHub 后重试\n"
                            "- 或手动安装编译工具：sudo apt install -y cmake make build-essential"
                        )
                    elif os_name == "linux" and "git" in log_text.lower() and "command not found" in log_text.lower():
                        error_msg = "安装失败：系统缺少 Git，请确保网络正常后重试"
                    else:
                        error_msg = (
                            f"安装失败：官方脚本执行出错 (代码 {self.process.returncode})\n"
                            "可能原因：网络连接不稳定、GitHub 访问受限或系统依赖缺失。\n"
                            "建议检查网络后重试。"
                        )
                self._log(error_msg, on_log)

                return InstallResult(
                    status=InstallStatus.FAILED,
                    message="安装失败",
                    error_message=error_msg,
                    log_lines=self.log_lines.copy(),
                    duration_seconds=time.time() - self.start_time,
                )

        except Exception as e:
            error_msg = f"执行安装命令时出错: {str(e)}"
            self._log(error_msg, on_log)
            return InstallResult(
                status=InstallStatus.FAILED,
                message="安装失败",
                error_message=error_msg,
                log_lines=self.log_lines.copy(),
                duration_seconds=time.time() - self.start_time,
            )

    def _install_local_build(
        self,
        target_dir: str,
        on_progress: Callable[[InstallProgress], None],
        on_log: Callable[[str], None],
    ) -> InstallResult:
        """全平台统一本地构建流程：Gitee 克隆 + pnpm 构建"""
        is_windows = self.os_type == "windows"
        startupinfo = None
        creationflags = 0
        if is_windows:
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startupinfo.wShowWindow = subprocess.SW_HIDE
            creationflags = subprocess.CREATE_NO_WINDOW

        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"
        env["NODE_OPTIONS"] = "--max-old-space-size=8192"
        project_dir = Path(target_dir)

        def _check_cancelled() -> Optional[InstallResult]:
            if self.is_cancelled:
                return InstallResult(
                    status=InstallStatus.CANCELLED,
                    message="安装已取消",
                    log_lines=self.log_lines.copy(),
                    duration_seconds=time.time() - self.start_time,
                )
            return None

        def _run(cmd: str, timeout: float = 300) -> subprocess.CompletedProcess:
            kw = {"shell": True, "capture_output": True, "text": True, "timeout": timeout, "env": env}
            if is_windows:
                kw["startupinfo"] = startupinfo
                kw["creationflags"] = creationflags
            return subprocess.run(cmd, **kw)

        def _run_in_project(cmd: str, timeout: float = 300, progress: InstallProgress = None) -> int:
            if is_windows:
                full_cmd = f'cd /d "{project_dir}" && {cmd}'
            else:
                full_cmd = f'cd "{project_dir}" && {cmd}'
            if progress and on_progress:
                on_progress(progress)
            return self._run_cmd_with_streaming(
                full_cmd, env, timeout,
                startupinfo, creationflags, on_log
            )

        def _which(cmd_name: str) -> bool:
            if is_windows:
                return _run(f"where {cmd_name}", timeout=5).returncode == 0
            return subprocess.run(["which", cmd_name], capture_output=True, timeout=5).returncode == 0

        # 0. 卸载已有的全局 openclaw（兼容旧版）
        self._log("检查并清理已有的 OpenClaw 安装...", on_log)
        for pkg_cmd in [
            "npm unlink -g openclaw",
            "npm uninstall -g openclaw",
            "npm unlink -g openclaw-cn",
            "npm uninstall -g openclaw-cn",
        ]:
            _run(pkg_cmd, timeout=30)

        # 1. 检查/安装 Node.js 22+
        cancelled = _check_cancelled()
        if cancelled:
            return cancelled

        self._log("检查 Node.js 环境...", on_log)
        node_ok = False
        node_ver = _run("node -v", timeout=10)
        if node_ver.returncode == 0:
            try:
                major = int(node_ver.stdout.strip().lstrip("v").split(".")[0])
                if major >= 22:
                    node_ok = True
                    self._log(f"Node.js {node_ver.stdout.strip()} 已满足要求", on_log)
                else:
                    self._log(f"检测到 Node.js v{major}，版本过低，正在为您升级...", on_log)
            except Exception:
                pass

        if not node_ok:
            self._log("正在安装 Node.js 22...", on_log)
            if on_progress:
                on_progress(InstallProgress(stage=InstallStage.INSTALLING, progress_percent=10, message="正在安装系统依赖...", current_task="安装 Node.js"))

            if is_windows:
                node_urls = [
                    "https://mirrors.aliyun.com/nodejs-release/v22.14.0/node-v22.14.0-x64.msi",
                    "https://mirrors.cloud.tencent.com/nodejs-release/v22.14.0/node-v22.14.0-x64.msi",
                    "https://repo.huaweicloud.com/nodejs/v22.14.0/node-v22.14.0-x64.msi",
                    "https://mirrors.ustc.edu.cn/nodejs/v22.14.0/node-v22.14.0-x64.msi",
                    "https://npmmirror.com/mirrors/node/v22.14.0/node-v22.14.0-x64.msi",
                    "https://registry.npmmirror.com/-/binary/node/latest-v22.x/node-v22.14.0-x64.msi",
                    "https://nodejs.org/dist/v22.14.0/node-v22.14.0-x64.msi",
                ]
                # 使用用户级临时目录，避免管理员上下文下的目录重定向问题
                temp_dir = Path(os.environ.get("TEMP", os.path.expanduser("~\\AppData\\Local\\Temp")))
                node_msi = temp_dir / "node-v22-installer.msi"
                downloaded = False
                last_error_detail: Optional[InstallErrorDetail] = None

                def _is_valid_msi(path: Path) -> bool:
                    """校验 MSI 文件头魔数（OLE 复合文档格式）"""
                    if not path.exists():
                        return False
                    try:
                        with open(path, "rb") as f:
                            header = f.read(8)
                        # MSI 文件头魔数: D0 CF 11 E0 A1 B1 1A E1
                        return header == b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
                    except Exception:
                        return False

                for url in node_urls:
                    if _check_cancelled():
                        return _check_cancelled()
                    self._log(f"尝试下载 Node.js ({node_urls.index(url) + 1}/{len(node_urls)}): {url}", on_log)

                    # 方法1：Python 原生下载（避免 PowerShell 在管理员上下文中的网络代理断裂）
                    try:
                        import urllib.request
                        import ssl
                        ctx = ssl.create_default_context()
                        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
                        with urllib.request.urlopen(req, context=ctx, timeout=180) as resp:
                            with open(node_msi, "wb") as f:
                                f.write(resp.read())
                        if _is_valid_msi(node_msi):
                            downloaded = True
                            self._log(f"Node.js 安装包下载成功 ({node_msi.stat().st_size / 1024 / 1024:.1f} MB)", on_log)
                            break
                        else:
                            actual = node_msi.stat().st_size if node_msi.exists() else 0
                            self._log(f"下载完成但文件校验失败 ({actual} 字节)，判定为失败", on_log)
                    except Exception as e:
                        self._log(f"[Python 下载失败] {type(e).__name__}: {str(e)}", on_log)

                    # 方法2：PowerShell fallback
                    if not downloaded:
                        # 使用 -EncodedCommand 避免 cmd 对 PowerShell 语法的引号转义问题
                        import base64
                        ps_script = (
                            f'$ProgressPreference = "SilentlyContinue"; '
                            f'try {{ Invoke-WebRequest -Uri "{url}" -OutFile "{node_msi}" '
                            f'-UseBasicParsing -TimeoutSec 180; exit 0 }} catch {{ '
                            f'Write-Error "异常: $($_.Exception.Message)"; '
                            f'Write-Error "堆栈: $($_.ScriptStackTrace)"; exit 1 }}'
                        )
                        encoded = base64.b64encode(ps_script.encode("utf-16le")).decode("ascii")
                        ps_cmd = f"powershell -ExecutionPolicy Bypass -EncodedCommand {encoded}"
                        result = run_shell(
                            ps_cmd, timeout=200,
                            context=f"从 {url} 下载 Node.js msi 到 {node_msi}",
                            stage="DOWNLOADING",
                        )
                        if result.stderr.strip():
                            self._log(f"[PowerShell stderr]\n{result.stderr.strip()}", on_log)
                        if result.error_detail:
                            last_error_detail = result.error_detail
                            self._log(f"[错误分类] {result.error_detail.category.value}", on_log)
                            self._log(f"[用户提示] {result.error_detail.user_message}", on_log)
                            raw = result.error_detail.raw_error
                            self._log(f"[原始错误] {raw[:1000]}{'...' if len(raw) > 1000 else ''}", on_log)
                        if result.success and _is_valid_msi(node_msi):
                            downloaded = True
                            self._log(f"Node.js 安装包下载成功 (PowerShell, {node_msi.stat().st_size / 1024 / 1024:.1f} MB)", on_log)
                            break
                        else:
                            self._log(f"PowerShell 下载失败或文件校验不通过, rc={result.returncode}", on_log)

                if not downloaded:
                    err_detail = last_error_detail
                    user_msg = "无法下载 Node.js 22 安装包"
                    if err_detail:
                        user_msg = f"{err_detail.user_message}\n\n{err_detail.suggestion}"
                    return InstallResult(
                        status=InstallStatus.FAILED, message="Node.js 下载失败",
                        error_message=user_msg,
                        log_lines=self.log_lines.copy(), duration_seconds=time.time() - self.start_time,
                        error_detail=err_detail,
                    )

                # 安装前自动修复 Windows Installer（DeepSeek 方案）
                self._log("修复 Windows Installer 服务...", on_log)
                run_shell("msiexec /unregister", timeout=30)
                run_shell("msiexec /regserver", timeout=30)
                self._log("Windows Installer 服务已修复", on_log)

                # 安装前自动清理注册表残留
                self._log("清理可能的 Node.js 注册表残留...", on_log)
                reg_clean_result = run_shell(
                    'powershell -Command "Remove-Item -Path HKCU:\\Software\\Node.js -Recurse -Force -ErrorAction SilentlyContinue; Remove-Item -Path HKLM:\\SOFTWARE\\Node.js -Recurse -Force -ErrorAction SilentlyContinue"',
                    timeout=30,
                )
                if reg_clean_result.success:
                    self._log("注册表清理完成", on_log)
                else:
                    self._log("注册表无残留或清理失败（不影响安装）", on_log)

                # 安装 Node.js
                self._log(f"正在安装 Node.js (msi: {node_msi})...", on_log)
                msi_log = temp_dir / "node-v22-install.log"

                install_success = False
                for attempt in range(2):
                    if attempt > 0:
                        self._log("首次安装失败，等待 10 秒后重试...", on_log)
                        time.sleep(10)

                    install_result = run_shell(
                        f'msiexec /i "{node_msi}" /qn /norestart /l*v "{msi_log}"',
                        timeout=300,
                        context=f"安装 Node.js msi ({node_msi})",
                        stage="INSTALLING",
                    )
                    if install_result.stderr.strip():
                        self._log(f"[msiexec stderr]\n{install_result.stderr.strip()}", on_log)

                    if install_result.success:
                        install_success = True
                        break

                    # 读取 MSI 详细日志，输出最后 100 行供诊断
                    if msi_log.exists():
                        try:
                            log_content = msi_log.read_text(encoding="utf-8", errors="replace")
                            all_lines = log_content.splitlines()
                            # 输出日志最后 100 行
                            self._log(f"[MSI 安装日志 最后 {min(len(all_lines), 100)} 行]\n" + "\n".join(all_lines[-100:]), on_log)
                        except Exception as e:
                            self._log(f"[读取 MSI 日志失败] {e}", on_log)

                    if attempt == 0 and install_result.returncode == 1603:
                        self._log("检测到 1603 错误，可能是 Windows Installer 正忙或已有 Node.js 冲突，等待后重试...", on_log)
                        time.sleep(3)
                        continue

                if not install_success:
                    err_detail = install_result.error_detail
                    user_msg = (
                        "Node.js 安装失败 (错误 1603)\n\n"
                        "常见原因：\n"
                        "1. 电脑上已安装了其他版本的 Node.js，导致冲突\n"
                        "2. Windows 正在执行其他安装/更新程序\n"
                        "3. 安全软件阻止了安装\n\n"
                        "建议：\n"
                        "• 先手动卸载已有的 Node.js，再重试\n"
                        "• 重启电脑后重试\n"
                        "• 暂时关闭杀毒软件后重试"
                    )
                    if err_detail:
                        user_msg = f"{err_detail.user_message}\n\n{err_detail.suggestion}"
                    self._log(f"Node.js 安装失败: {user_msg}", on_log)
                    return InstallResult(
                        status=InstallStatus.FAILED, message="Node.js 安装失败",
                        error_message=user_msg,
                        log_lines=self.log_lines.copy(), duration_seconds=time.time() - self.start_time,
                        error_detail=err_detail,
                    )
                try:
                    import winreg
                    with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment") as key:
                        sys_path, _ = winreg.QueryValueEx(key, "Path")
                    os.environ["Path"] = sys_path + ";" + os.environ.get("Path", "")
                except Exception:
                    pass
                node_path = r"C:\Program Files\nodejs"
                if os.path.exists(node_path):
                    os.environ["Path"] = node_path + os.pathsep + os.environ.get("Path", "")
            elif self.os_type == "macos":
                # macOS：把所有需要管理员权限的命令收集起来，只弹一次密码框
                admin_cmds = []
                node_pkg = None
                macos_err_detail: Optional[InstallErrorDetail] = None

                # 1. 如果需要安装 Node.js，下载 .pkg 并准备安装命令
                if not node_ok:
                    node_pkg = Path("/tmp") / "node-v22-installer.pkg"
                    node_urls = [
                        "https://mirrors.aliyun.com/nodejs-release/v22.14.0/node-v22.14.0.pkg",
                        "https://mirrors.cloud.tencent.com/nodejs-release/v22.14.0/node-v22.14.0.pkg",
                        "https://repo.huaweicloud.com/nodejs/v22.14.0/node-v22.14.0.pkg",
                        "https://mirrors.ustc.edu.cn/nodejs/v22.14.0/node-v22.14.0.pkg",
                        "https://nodejs.org/dist/v22.14.0/node-v22.14.0.pkg",
                        "https://registry.npmmirror.com/-/binary/node/latest-v22.x/node-v22.14.0.pkg",
                    ]
                    downloaded = False
                    for url in node_urls:
                        if _check_cancelled():
                            return _check_cancelled()
                        self._log(f"尝试下载 Node.js ({node_urls.index(url) + 1}/{len(node_urls)}): {url}", on_log)
                        result = run_shell(
                            f'curl -fsSL -o "{node_pkg}" "{url}"',
                            timeout=300, shell=False,
                            context=f"从 {url} 下载 Node.js pkg",
                            stage="DOWNLOADING",
                        )
                        if result.stderr.strip():
                            self._log(f"[curl stderr] {result.stderr.strip()}", on_log)
                        if result.success and node_pkg.exists() and node_pkg.stat().st_size > 30 * 1024 * 1024:
                            downloaded = True
                            self._log(f"Node.js 安装包下载成功 ({node_pkg.stat().st_size / 1024 / 1024:.1f} MB)", on_log)
                            break
                        else:
                            if result.error_detail:
                                macos_err_detail = result.error_detail
                                self._log(f"[错误分类] {result.error_detail.category.value}", on_log)
                                self._log(f"[用户提示] {result.error_detail.user_message}", on_log)
                            else:
                                self._log(f"curl 下载失败, rc={result.returncode}", on_log)
                    if not downloaded:
                        user_msg = "无法下载 Node.js 22 安装包"
                        if macos_err_detail:
                            user_msg = f"{macos_err_detail.user_message}\n\n{macos_err_detail.suggestion}"
                        return InstallResult(
                            status=InstallStatus.FAILED, message="Node.js 下载失败",
                            error_message=user_msg,
                            log_lines=self.log_lines.copy(), duration_seconds=time.time() - self.start_time,
                            error_detail=macos_err_detail,
                        )
                    admin_cmds.append(f"installer -pkg {node_pkg} -target /")
                    # Node.js 装好后顺带把 pnpm 也装上（新 shell 里 /usr/local/bin 已在 PATH）
                    admin_cmds.append("cd /tmp && export PATH=/usr/local/bin:/usr/bin:/bin:$PATH && npm install -g pnpm")
                else:
                    # Node.js 已装好，检查 pnpm
                    if not _which("pnpm"):
                        pnpm_install = _run("npm install -g pnpm", timeout=120)
                        if pnpm_install.returncode != 0:
                            err_text = pnpm_install.stderr.strip() if pnpm_install.stderr else ""
                            if "EACCES" in err_text or "permission denied" in err_text.lower():
                                admin_cmds.append("cd /tmp && export PATH=/usr/local/bin:/usr/bin:/bin:$PATH && npm install -g pnpm")
                            else:
                                self._log(f"pnpm 安装失败: {err_text}", on_log)
                                return InstallResult(
                                    status=InstallStatus.FAILED, message="pnpm 安装失败",
                                    error_message=f"无法安装 pnpm: {err_text}",
                                    log_lines=self.log_lines.copy(), duration_seconds=time.time() - self.start_time,
                                    error_detail=pnpm_install.error_detail if hasattr(pnpm_install, "error_detail") else None,
                                )

                # 2. 一次性执行所有管理员命令（只弹一次密码框）
                if admin_cmds:
                    cmd_str = " && ".join(admin_cmds)
                    self._log("正在申请管理员权限安装系统依赖（只需输入一次密码）...", on_log)
                    install_script = f'do shell script "{cmd_str}" with administrator privileges'
                    result = run_shell(
                        f'osascript -e "{install_script}"',
                        timeout=300, shell=False,
                        context="通过 osascript 申请管理员权限安装系统依赖",
                        stage="INSTALLING",
                    )
                    # 清理临时文件
                    if node_pkg and node_pkg.exists():
                        try:
                            node_pkg.unlink()
                        except Exception:
                            pass
                    if not result.success:
                        err_detail = result.error_detail
                        user_msg = "安装失败：请确保输入了正确的管理员密码"
                        if err_detail:
                            user_msg = f"{err_detail.user_message}\n\n{err_detail.suggestion}"
                        self._log(f"系统依赖安装失败: {user_msg}", on_log)
                        return InstallResult(
                            status=InstallStatus.FAILED, message="系统依赖安装失败",
                            error_message=user_msg,
                            log_lines=self.log_lines.copy(), duration_seconds=time.time() - self.start_time,
                            error_detail=err_detail,
                        )

                # 刷新 PATH
                os.environ["PATH"] = "/usr/local/bin:" + os.environ.get("PATH", "")
            else:
                # Linux：理论上 install() 里已经通过 pkexec 安装了 Node.js，这里再检查一次
                self._log("Linux Node.js 应在系统依赖阶段已安装，跳过独立安装", on_log)

            env["PATH"] = os.environ.get("PATH", "")
            self._log("Node.js 安装完成，PATH 已刷新", on_log)

        # 2. 检查/安装 pnpm
        cancelled = _check_cancelled()
        if cancelled:
            return cancelled

        self._log("检查 pnpm 环境...", on_log)
        if not _which("pnpm"):
            self._log("正在安装 pnpm...", on_log)
            if on_progress:
                on_progress(InstallProgress(stage=InstallStage.INSTALLING, progress_percent=15, message="正在安装系统依赖...", current_task="安装 pnpm"))
            npm_cmd = "npm.cmd" if is_windows else "npm"
            pnpm_install = _run(f"{npm_cmd} install -g pnpm", timeout=120)

            # macOS：如果普通权限安装失败（EACCES），弹出密码框用管理员权限重试
            if pnpm_install.returncode != 0 and self.os_type == "macos":
                err_text = pnpm_install.stderr.strip() if pnpm_install.stderr else ""
                if "EACCES" in err_text or "permission denied" in err_text.lower():
                    self._log("普通权限安装 pnpm 失败，正在弹出密码框申请管理员权限...", on_log)
                    install_script = 'do shell script "cd /tmp && export PATH=/usr/local/bin:/usr/bin:/bin:$PATH && npm install -g pnpm" with administrator privileges'
                    pnpm_install = subprocess.run(
                        ["osascript", "-e", install_script],
                        capture_output=True, text=True, timeout=300
                    )

            if pnpm_install.returncode != 0:
                err = pnpm_install.stderr.strip() if pnpm_install.stderr else "未知错误"
                self._log(f"pnpm 安装失败: {err}", on_log)
                err_detail = pnpm_install.error_detail if hasattr(pnpm_install, "error_detail") else None
                user_msg = f"无法安装 pnpm: {err}"
                if err_detail:
                    user_msg = f"{err_detail.user_message}\n\n{err_detail.suggestion}"
                return InstallResult(
                    status=InstallStatus.FAILED, message="pnpm 安装失败",
                    error_message=user_msg,
                    log_lines=self.log_lines.copy(), duration_seconds=time.time() - self.start_time,
                    error_detail=err_detail,
                )
            self._log("pnpm 安装完成", on_log)

            # Windows: pnpm 刚全局安装完，需要把 npm 全局 bin 目录加到当前 env 的 PATH
            # 否则新开的 shell 找不到 pnpm
            if is_windows:
                try:
                    npm_bin_res = _run("npm bin -g", timeout=10)
                    if npm_bin_res.returncode == 0:
                        npm_bin_path = npm_bin_res.stdout.strip().strip('"').strip()
                        if npm_bin_path and os.path.exists(npm_bin_path) and npm_bin_path not in env.get("PATH", ""):
                            env["PATH"] = npm_bin_path + os.pathsep + env.get("PATH", "")
                            self._log(f"已添加 npm 全局 bin 到 PATH: {npm_bin_path}", on_log)
                except Exception as e:
                    self._log(f"获取 npm 全局 bin 路径失败: {e}", on_log)
                # fallback: 尝试常见的默认路径
                appdata = os.environ.get("APPDATA", "")
                fallback_paths = [
                    os.path.join(appdata, "npm"),
                    r"C:\Program Files\nodejs",
                ]
                for fp in fallback_paths:
                    if os.path.exists(fp) and fp not in env.get("PATH", ""):
                        env["PATH"] = fp + os.pathsep + env.get("PATH", "")
                        self._log(f"已添加 fallback PATH: {fp}", on_log)
        else:
            self._log("pnpm 已存在", on_log)

        # 3. 从 Gitee 克隆仓库
        cancelled = _check_cancelled()
        if cancelled:
            return cancelled

        self._log("正在从 Gitee 下载 openclaw-cn...", on_log)
        if on_progress:
            on_progress(InstallProgress(stage=InstallStage.DOWNLOADING, progress_percent=20, message="正在下载 OpenClaw...", current_task="git clone"))

        clone_result = _run(
            f'git clone https://gitee.com/OpenClaw-CN/openclaw-cn.git "{project_dir}"',
            timeout=300,
        )
        if clone_result.stdout:
            for line in clone_result.stdout.splitlines()[-50:]:
                if line.strip():
                    self._log(line.strip(), on_log)
        if clone_result.stderr:
            for line in clone_result.stderr.splitlines()[-20:]:
                if line.strip():
                    self._log(line.strip(), on_log)
        if clone_result.returncode != 0:
            err_detail = clone_result.error_detail if hasattr(clone_result, "error_detail") else None
            user_msg = "从 Gitee 克隆仓库失败，请检查网络或 Git 安装后重试"
            if err_detail:
                user_msg = f"{err_detail.user_message}\n\n{err_detail.suggestion}"
            return InstallResult(
                status=InstallStatus.FAILED, message="下载失败",
                error_message=user_msg,
                log_lines=self.log_lines.copy(), duration_seconds=time.time() - self.start_time,
                error_detail=err_detail,
            )
        self._log("仓库克隆完成", on_log)

        # 4. 设置 pnpm 国内镜像
        _run_in_project('pnpm config set registry https://registry.npmmirror.com/', timeout=30)

        # 5. pnpm install
        cancelled = _check_cancelled()
        if cancelled:
            return cancelled

        self._log("正在安装依赖...", on_log)
        if on_progress:
            on_progress(InstallProgress(stage=InstallStage.INSTALLING, progress_percent=35, message="正在安装依赖...", current_task="pnpm install"))
        rc = _run_in_project("pnpm install", timeout=600)
        if rc != 0:
            # 从最近日志中提取错误上下文
            recent_logs = "\n".join(self.log_lines[-30:])
            return InstallResult(
                status=InstallStatus.FAILED, message="依赖安装失败",
                error_message="pnpm install 失败，可能是网络不稳定或 npm 镜像源不可用。\n\n建议：\n1. 检查网络连接后重试\n2. 暂时关闭代理/VPN 后重试\n3. 查看高级模式中的完整日志",
                log_lines=self.log_lines.copy(), duration_seconds=time.time() - self.start_time,
                error_detail=InstallErrorDetail(
                    category=ErrorCategory.NETWORK_UNKNOWN,
                    stage="INSTALLING",
                    context="执行 pnpm install 安装项目依赖",
                    raw_error=f"returncode={rc}\n最近日志:\n{recent_logs}",
                    user_message="pnpm install 失败，可能是网络不稳定或 npm 镜像源不可用",
                    suggestion="1. 检查网络连接后重试\n2. 暂时关闭代理/VPN 后重试\n3. 查看高级模式中的完整日志",
                ),
            )

        # 6. pnpm ui:build
        cancelled = _check_cancelled()
        if cancelled:
            return cancelled

        self._log("正在构建前端界面...", on_log)
        if on_progress:
            on_progress(InstallProgress(stage=InstallStage.INSTALLING, progress_percent=55, message="正在构建前端界面...", current_task="pnpm ui:build"))
        rc = _run_in_project("pnpm ui:build", timeout=300)
        if rc != 0:
            recent_logs = "\n".join(self.log_lines[-20:])
            return InstallResult(
                status=InstallStatus.FAILED, message="前端构建失败",
                error_message="pnpm ui:build 失败，可能是内存不足或依赖缺失。\n\n建议：\n1. 关闭其他程序释放内存后重试\n2. 重启电脑后重试",
                log_lines=self.log_lines.copy(), duration_seconds=time.time() - self.start_time,
                error_detail=InstallErrorDetail(
                    category=ErrorCategory.UNKNOWN,
                    stage="INSTALLING",
                    context="执行 pnpm ui:build 构建前端",
                    raw_error=f"returncode={rc}\n最近日志:\n{recent_logs}",
                    user_message="前端构建失败，可能是内存不足或依赖缺失",
                    suggestion="1. 关闭其他程序释放内存后重试\n2. 重启电脑后重试",
                ),
            )

        # 7. pnpm build（Windows 需确保 bash 可用）
        cancelled = _check_cancelled()
        if cancelled:
            return cancelled

        if is_windows:
            bash_dir = ""
            for candidate in [r"C:\Program Files\Git\bin", r"C:\Program Files (x86)\Git\bin"]:
                if os.path.exists(os.path.join(candidate, "bash.exe")):
                    bash_dir = candidate
                    break
            if bash_dir:
                self._log(f"找到 Git bash: {bash_dir}", on_log)
                env["PATH"] = bash_dir + os.pathsep + env.get("PATH", "")
            else:
                where_bash = _run("where bash", timeout=5)
                if where_bash.returncode == 0 and where_bash.stdout.strip():
                    bash_dir = os.path.dirname(where_bash.stdout.strip().splitlines()[0].strip())
                    if bash_dir:
                        env["PATH"] = bash_dir + os.pathsep + env.get("PATH", "")
                        self._log(f"找到 bash: {bash_dir}", on_log)

        self._log("正在构建核心服务...", on_log)
        if on_progress:
            on_progress(InstallProgress(stage=InstallStage.INSTALLING, progress_percent=70, message="正在构建核心服务...", current_task="pnpm build"))
        rc = _run_in_project("pnpm build", timeout=300)
        if rc != 0:
            recent_logs = "\n".join(self.log_lines[-20:])
            return InstallResult(
                status=InstallStatus.FAILED, message="核心构建失败",
                error_message="pnpm build 失败，可能是内存不足或 TypeScript 编译错误。\n\n建议：\n1. 关闭其他程序释放内存后重试\n2. 重启电脑后重试",
                log_lines=self.log_lines.copy(), duration_seconds=time.time() - self.start_time,
                error_detail=InstallErrorDetail(
                    category=ErrorCategory.UNKNOWN,
                    stage="INSTALLING",
                    context="执行 pnpm build 构建核心服务",
                    raw_error=f"returncode={rc}\n最近日志:\n{recent_logs}",
                    user_message="核心构建失败，可能是内存不足或 TypeScript 编译错误",
                    suggestion="1. 关闭其他程序释放内存后重试\n2. 重启电脑后重试",
                ),
            )

        # 8. 初始化配置
        cancelled = _check_cancelled()
        if cancelled:
            return cancelled

        self._log("正在初始化配置...", on_log)
        if on_progress:
            on_progress(InstallProgress(stage=InstallStage.CONFIGURING, progress_percent=85, message="正在初始化配置...", current_task="pnpm openclaw onboard"))
        rc = _run_in_project(
            "pnpm openclaw onboard --non-interactive --accept-risk --mode local --skip-skills --skip-health --no-install-daemon --node-manager pnpm --skip-channels",
            timeout=120,
        )
        if rc != 0:
            self._log("onboard 返回非零，但可能已部分完成，继续尝试...", on_log)

        # 9. 创建全局命令 wrapper
        self._log("正在创建全局命令...", on_log)
        if is_windows:
            npm_bin_dir = ""
            npm_bin_result = _run("npm.cmd bin -g", timeout=10)
            if npm_bin_result.returncode == 0 and npm_bin_result.stdout.strip():
                npm_bin_dir = npm_bin_result.stdout.strip()
            else:
                npm_bin_dir = str(Path(os.path.expanduser(r"~\AppData\Roaming\npm")))
            Path(npm_bin_dir).mkdir(parents=True, exist_ok=True)
            for wrapper_name in ["openclaw.cmd", "openclaw-cn.cmd"]:
                wrapper_path = Path(npm_bin_dir) / wrapper_name
                wrapper_content = (
                    f'@echo off\n'
                    f'set CLAWHUB_REGISTRY=https://cn.clawhub-mirror.com/\n'
                    f'cd /d "{project_dir}"\n'
                    f'pnpm openclaw %*\n'
                )
                try:
                    wrapper_path.write_text(wrapper_content, encoding="utf-8")
                    self._log(f"已创建全局命令: {wrapper_path}", on_log)
                except Exception as e:
                    self._log(f"创建全局命令失败 {wrapper_path}: {e}", on_log)
        else:
            # macOS / Linux：在 ~/.local/bin 下创建 shell 脚本
            local_bin = Path(os.path.expanduser("~/.local/bin"))
            local_bin.mkdir(parents=True, exist_ok=True)
            for wrapper_name in ["openclaw", "openclaw-cn"]:
                wrapper_path = local_bin / wrapper_name
                wrapper_content = (
                    f'#!/bin/bash\n'
                    f'export CLAWHUB_REGISTRY=https://cn.clawhub-mirror.com/\n'
                    f'cd "{project_dir}" || exit 1\n'
                    f'pnpm openclaw "$@"\n'
                )
                try:
                    wrapper_path.write_text(wrapper_content, encoding="utf-8")
                    wrapper_path.chmod(0o755)
                    self._log(f"已创建全局命令: {wrapper_path}", on_log)
                except Exception as e:
                    self._log(f"创建全局命令失败 {wrapper_path}: {e}", on_log)
            npm_bin_dir = str(local_bin)
            self._ensure_local_bin_in_path(on_log)

        # 10. 刷新 PATH 并验证
        self._log("刷新 PATH 并验证 openclaw 命令...", on_log)
        if npm_bin_dir and os.path.exists(npm_bin_dir):
            current_path = os.environ.get("Path" if is_windows else "PATH", "")
            path_sep = ";" if is_windows else ":"
            if npm_bin_dir.lower() not in current_path.lower():
                path_key = "Path" if is_windows else "PATH"
                os.environ[path_key] = npm_bin_dir + path_sep + current_path
                self._log(f"已将 {npm_bin_dir} 加入当前进程 PATH", on_log)
            env["PATH" if is_windows else "PATH"] = os.environ.get("Path" if is_windows else "PATH", "")

        if is_windows:
            try:
                import winreg
                with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as key:
                    user_path, _ = winreg.QueryValueEx(key, "Path")
                user_path_expanded = os.path.expandvars(user_path)
                current_path = os.environ.get("Path", "")
                merged_paths = [p.strip() for p in current_path.split(";") if p.strip()]
                for p in user_path_expanded.split(";"):
                    p_strip = p.strip()
                    if p_strip and p_strip.lower() not in [mp.lower() for mp in merged_paths]:
                        merged_paths.append(p_strip)
                os.environ["Path"] = ";".join(merged_paths)
                env["Path"] = os.environ["Path"]
            except Exception as e:
                self._log(f"刷新 PATH 时出错（非致命）: {e}", on_log)

        def _verify_cmd(cmd: str) -> bool:
            if is_windows:
                return _run(f"where {cmd}", timeout=10).returncode == 0
            return subprocess.run(["which", cmd], capture_output=True, timeout=5).returncode == 0

        if not _verify_cmd("openclaw-cn") and not _verify_cmd("openclaw"):
            if is_windows and npm_bin_dir:
                try:
                    _run(f'setx PATH "%PATH%;{npm_bin_dir}"', timeout=10)
                except Exception:
                    pass
                env["Path"] = os.environ.get("Path", "")
                if not _verify_cmd("openclaw-cn") and not _verify_cmd("openclaw"):
                    return InstallResult(
                        status=InstallStatus.FAILED, message="openclaw 命令不可用",
                        error_message="安装成功但系统 PATH 中找不到 openclaw/openclaw-cn 命令，请重启程序后重试",
                        log_lines=self.log_lines.copy(), duration_seconds=time.time() - self.start_time,
                    )
            else:
                return InstallResult(
                    status=InstallStatus.FAILED, message="openclaw 命令不可用",
                    error_message="未找到 openclaw/openclaw-cn 可执行文件",
                    log_lines=self.log_lines.copy(), duration_seconds=time.time() - self.start_time,
                )

        self._log("安装成功", on_log)
        if on_progress:
            on_progress(InstallProgress(stage=InstallStage.COMPLETED, progress_percent=100, message="安装完成", current_task="完成"))
        return InstallResult(
            status=InstallStatus.SUCCESS, message="OpenClaw 安装成功",
            log_lines=self.log_lines.copy(), duration_seconds=time.time() - self.start_time,
        )

    def _run_cmd_with_streaming(
        self,
        cmd: str,
        env: dict,
        timeout: float,
        startupinfo,
        creationflags: int,
        on_log: Callable[[str], None],
    ) -> int:
        """运行命令，实时输出日志，支持无输出超时终止"""
        self._log(f"启动命令: {cmd}", on_log)
        process = subprocess.Popen(
            cmd,
            shell=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            universal_newlines=True,
            bufsize=1,
            encoding="utf-8",
            errors="replace",
            env=env,
            startupinfo=startupinfo,
            creationflags=creationflags,
        )
        self._log(f"进程已启动，PID: {process.pid}", on_log)
        last_output_time = [time.time()]
        cmd_start = time.time()
        next_heartbeat = cmd_start + 30

        def reader():
            try:
                for line in process.stdout:
                    if line:
                        stripped = line.strip()
                        if stripped:
                            self._log(stripped, on_log)
                            last_output_time[0] = time.time()
            except Exception:
                pass

        t = threading.Thread(target=reader, daemon=True)
        t.start()

        try:
            while process.poll() is None:
                time.sleep(2)
                now = time.time()
                if now > next_heartbeat:
                    elapsed = int(now - cmd_start)
                    self._log(f"命令仍在运行中，已等待 {elapsed} 秒，请耐心等待...", on_log)
                    next_heartbeat = now + 30
                if now - last_output_time[0] > timeout:
                    self._log(f"命令超过 {int(timeout)} 秒无输出，判定为卡住，强制终止...", on_log)
                    self._kill_process_tree(process)
                    break
            process.wait(timeout=5)
        except Exception as e:
            self._log(f"等待进程时出错: {e}", on_log)
            self._kill_process_tree(process)

        t.join(timeout=5)
        return process.returncode if process.poll() is not None else -1

    def _kill_process_tree(self, process: subprocess.Popen):
        """终止进程及其子进程"""
        try:
            process.kill()
        except Exception:
            pass
        try:
            subprocess.run(
                f"taskkill /F /T /PID {process.pid}",
                shell=True,
                capture_output=True,
                timeout=10,
            )
        except Exception:
            pass

    def _log(self, message: str, on_log: Callable[[str], None] = None):
        """记录日志"""
        import re
        # 过滤 ANSI 颜色码和光标控制序列，让日志在 UI 中更干净
        cleaned = re.sub(r'\x1b\[[0-9;?]*[A-Za-z]', '', message)
        timestamp = time.strftime("%H:%M:%S")
        log_line = f"[{timestamp}] {cleaned}"
        self.log_lines.append(log_line)
        if on_log:
            on_log(log_line)

    def _terminate_process(self):
        """终止安装进程"""
        if self.process and self.process.poll() is None:
            try:
                if platform.system().lower() == "windows":
                    self.process.terminate()
                else:
                    self.process.send_signal(signal.SIGTERM)

                # 等待进程结束
                try:
                    self.process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    self.process.kill()

            except Exception:
                pass

    def _ensure_local_bin_in_path(self, on_log: Callable[[str], None] = None):
        """确保 ~/.local/bin 在用户 shell 配置文件中，以便终端能直接使用 openclaw 命令"""
        import os
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
                        self._log(f"{rc_file} 已包含 {local_bin}", on_log)
                        continue
                    with open(rc_path, "a", encoding="utf-8") as f:
                        f.write(f"\n# Added by OpenClaw Installer\n{path_export}\n")
                    self._log(f"已将 {local_bin} 添加到 {rc_file}", on_log)
                except Exception as e:
                    self._log(f"修改 {rc_file} 失败: {e}", on_log)

    def cancel(self):
        """取消安装"""
        self.is_cancelled = True
        self._terminate_process()

    def is_running(self) -> bool:
        """检查是否正在运行"""
        return self.process is not None and self.process.poll() is None
