import subprocess
import platform
import os
import signal
import shutil
import time
import sys

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
    get_official_command,
)
from infra.git_installer import ensure_git_installed


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

    def install(
        self,
        on_progress: Callable[[InstallProgress], None] = None,
        on_log: Callable[[str], None] = None,
    ) -> InstallResult:
        """执行安装

        Args:
            on_progress: 进度回调函数
            on_log: 日志回调函数

        Returns:
            InstallResult: 安装结果
        """
        self.start_time = time.time()
        self.log_lines = []
        self.is_cancelled = False

        try:
            # 1. 先确保前置依赖已就绪
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
                # macOS：curl 默认自带；git 如果没装，官方脚本调用时系统会自动弹窗引导安装 Xcode Command Line Tools
                self._log("检查前置依赖 (curl)...", on_log)
                try:
                    result = subprocess.run(
                        ["curl", "--version"],
                        capture_output=True,
                        shell=False,
                        timeout=5,
                    )
                    if result.returncode != 0:
                        raise FileNotFoundError()
                except FileNotFoundError:
                    return InstallResult(
                        status=InstallStatus.FAILED,
                        message="缺少 curl",
                        error_message="系统未找到 curl，请检查 macOS 系统完整性后重试。",
                        log_lines=self.log_lines.copy(),
                        duration_seconds=time.time() - self.start_time,
                    )
                self._log("前置依赖已就绪（macOS 会自动处理 Git 安装）", on_log)
            else:
                # Linux：先 pkexec 预装系统依赖，再运行官方脚本（避免 sudo 无 TTY 且保证命令对普通用户可见）
                self._log("检查前置依赖 (git, curl)...", on_log)
                missing_deps = []
                for cmd, name in [("git", "Git"), ("curl", "curl")]:
                    try:
                        result = subprocess.run(
                            [cmd, "--version"],
                            capture_output=True,
                            shell=False,
                            timeout=5,
                        )
                        if result.returncode != 0:
                            missing_deps.append(name)
                    except FileNotFoundError:
                        missing_deps.append(name)
                
                if missing_deps:
                    self._log(f"缺少依赖: {', '.join(missing_deps)}，将在系统授权后自动安装", on_log)
                else:
                    self._log("前置依赖已就绪", on_log)
                
                self._log("正在安装系统依赖 (Node.js 22, pnpm, cmake, build tools)...", on_log)
                pkexec_dep_cmd = (
                    "pkexec bash -c '"
                    "apt update >/dev/null 2>&1; "
                    "curl -fsSL https://deb.nodesource.com/setup_22.x | bash -E - >/dev/null 2>&1; "
                    "apt-get install -y nodejs git curl cmake make build-essential >/dev/null 2>&1; "
                    "npm install -g pnpm >/dev/null 2>&1; "
                    "echo \"[OK] system deps ready\""
                    "'"
                )
                dep_result = subprocess.run(
                    pkexec_dep_cmd,
                    shell=True,
                    capture_output=True,
                    text=True,
                    timeout=600,
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
                        error_message=f"自动安装 Node.js / cmake 失败，请确保网络畅通后重试。\n错误：{err}",
                        log_lines=self.log_lines.copy(),
                        duration_seconds=time.time() - self.start_time,
                    )
                self._log("系统依赖安装完成", on_log)

            # 2. 执行 OpenClaw 安装（使用国内镜像）
            # 先清理残留目录，避免之前测试注入的脏数据导致 pnpm EPERM
            cleanup_dirs = [
                os.path.expanduser("~\\openclaw"),
                os.path.expanduser("~\\openclaw-cn"),
            ] if self.os_type == "windows" else [
                os.path.expanduser("~/.openclaw"),
                os.path.expanduser("~/openclaw-cn"),
            ]
            for d in cleanup_dirs:
                if os.path.exists(d):
                    try:
                        shutil.rmtree(d)
                        self._log(f"已清理残留目录: {d}", on_log)
                    except Exception as e:
                        self._log(f"清理残留目录失败 {d}: {e}", on_log)

            command = get_official_command(self.os_type, use_mirror=True)
            self._log("准备执行安装命令", on_log)
            self._log(f"操作系统: {self.os_type}", on_log)
            self._log("使用国内镜像加速...", on_log)

            # 报告开始下载阶段
            if on_progress:
                on_progress(
                    InstallProgress(
                        stage=InstallStage.DOWNLOADING,
                        progress_percent=0,
                        message="开始下载 OpenClaw...",
                        current_task="执行官方安装命令",
                    )
                )

            # 执行命令（隐藏窗口模式）
            install_result = self._execute_command(command, on_progress, on_log)
            
            # Linux/macOS 补救：如果安装主体成功但命令不可用，尝试 npm link
            if self.os_type in ("linux", "macos") and install_result.status == InstallStatus.FAILED:
                log_text_all = "\n".join(install_result.log_lines)
                if any(marker in log_text_all for marker in ["安装完成", "OpenClaw CN 安装完成", "✓ OpenClaw CN"]):
                    self._log("检测到安装主体已完成，尝试修复 openclaw 命令...", on_log)
                    fix_cmds = [
                        'bash -c "cd ~/openclaw-cn && npm run build 2>&1 || true"',
                        'bash -c "mkdir -p ~/.local/lib/node_modules ~/.local/bin && export NPM_CONFIG_PREFIX=~/.local && cd ~/openclaw-cn && npm link 2>&1 || true"',
                        'bash -c "[ -f ~/.local/bin/openclaw ] && chmod +x ~/.local/bin/openclaw 2>&1 || true"',
                        'bash -c "[ -f ~/openclaw-cn/bin/openclaw ] && ln -sf ~/openclaw-cn/bin/openclaw ~/.local/bin/openclaw 2>&1 || true"',
                    ]
                    for fix_cmd in fix_cmds:
                        fix_result = subprocess.run(fix_cmd, shell=True, capture_output=True, text=True, timeout=300)
                        if fix_result.stdout:
                            for line in fix_result.stdout.splitlines():
                                if line.strip():
                                    self._log(line.strip(), on_log)
                    
                    # 确保 ~/.local/bin 在 .bashrc / .zshrc / .profile 中
                    self._ensure_local_bin_in_path(on_log)
                    
                    # 验证是否修复成功：命令可用且 dist/entry 存在
                    env_cmd = 'export PATH="$HOME/.local/bin:$PATH"; which openclaw && ls ~/openclaw-cn/dist/entry.* 1>/dev/null 2>&1'
                    verify = subprocess.run(["bash", "-c", env_cmd], capture_output=True, text=True, timeout=5)
                    if verify.returncode == 0:
                        self._log(f"openclaw 已修复: {verify.stdout.strip()}", on_log)
                        return InstallResult(
                            status=InstallStatus.SUCCESS,
                            message="OpenClaw 安装成功",
                            log_lines=self.log_lines.copy(),
                            duration_seconds=time.time() - self.start_time,
                        )
                    else:
                        self._log("openclaw 修复失败: 构建产物缺失或命令不可用，建议手动执行安装脚本", on_log)
            
            return install_result

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
