"""OpenClaw 生命周期管理器

职责：封装 OpenClaw 的安装后配置、网关启停、健康检查、WebUI 地址获取、
Provider 配置以及卸载等核心操作。所有耗时操作均通过回调函数向 UI 层汇报进度。
"""

import subprocess
import platform
import time
import os
import shutil
import signal
import webbrowser
import re
import traceback
from pathlib import Path
from typing import Optional, Callable, Any

from src.models.config import (
    ConfigStatus,
    ServiceStatus,
    ConfigProgress,
    ConfigResult,
)
from src.models.utils import remove_readonly, resolve_openclaw_cmd
from src.models.constants import is_windows, is_macos, is_linux, TIMEOUT_OPENCLAW_CMD, TIMEOUT_SHORT_CMD
from src.contracts.define_base_manager import BaseOpenClawManager
from src.adapters.define_decorators import log_method, check_cancelled


class OpenClawManager(BaseOpenClawManager):
    """OpenClaw 服务管理器

    管理 OpenClaw 网关进程的完整生命周期，包括：
    - 配置初始化（config set / onboard）
    - 网关启动/停止/健康检查
    - Provider 与模型配置
    - 浏览器打开 WebUI
    - 完全卸载
    """

    def __init__(self) -> None:
        super().__init__()
        self.process: Optional[subprocess.Popen] = None
        self._webui_url: Optional[str] = None

    def configure_only(
        self,
        on_progress: Callable[[ConfigProgress], None] = None,
        on_log: Callable[[str], None] = None,
    ) -> ConfigResult:
        """仅执行配置，不启动网关（US-05）

        流程：检测安装 → 设置默认配置（gateway.mode/local 等）→ 执行 onboard → 注入浏览器配置。

        Args:
            on_progress: 进度回调，用于驱动 UI 进度条。
            on_log: 日志回调，用于在 UI 中展示实时日志。

        Returns:
            ConfigResult: 包含状态、服务状态、消息及完整日志行列表。
        """
        self._log_lines = []
        self._on_log = on_log

        try:
            self._log("Checking OpenClaw installation...")
            if on_progress:
                on_progress(
                    ConfigProgress(
                        stage=ConfigStatus.CONFIGURING,
                        progress_percent=10,
                        message="Checking installation...",
                        current_task="Verify installation",
                    )
                )

            if not self._check_openclaw_installed():
                return ConfigResult(
                    status=ConfigStatus.FAILED,
                    service_status=ServiceStatus.FAILED,
                    message="OpenClaw 未安装",
                    error_message="未找到 openclaw 或 openclaw-cn 命令",
                    log_lines=self._log_lines.copy(),
                )

            self._log("Setting default config...")
            if on_progress:
                on_progress(
                    ConfigProgress(
                        stage=ConfigStatus.CONFIGURING,
                        progress_percent=30,
                        message="正在配置 OpenClaw...",
                        current_task="设置默认配置",
                    )
                )

            config_ok = self._setup_default_config()
            if not config_ok:
                return ConfigResult(
                    status=ConfigStatus.FAILED,
                    service_status=ServiceStatus.FAILED,
                    message="配置失败",
                    error_message="配置 OpenClaw 失败",
                    log_lines=self._log_lines.copy(),
                )

            self._log("Configuration complete")
            if on_progress:
                on_progress(
                    ConfigProgress(
                        stage=ConfigStatus.COMPLETED,
                        progress_percent=100,
                        message="配置完成",
                        current_task="完成",
                    )
                )

            return ConfigResult(
                status=ConfigStatus.COMPLETED,
                service_status=ServiceStatus.STOPPED,
                message="配置成功",
                log_lines=self._log_lines.copy(),
            )

        except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as e:
            # 顶层容错：捕获配置过程中所有已知运行时异常，防止 UI 崩溃
            self._log(f"Exception: {type(e).__name__}: {e}")
            self._log(f"Traceback: {traceback.format_exc()}")
            return ConfigResult(
                status=ConfigStatus.FAILED,
                service_status=ServiceStatus.FAILED,
                message="配置失败",
                error_message=str(e),
                log_lines=self._log_lines.copy(),
            )
        finally:
            self._on_log = None

    def startup_only(
        self,
        on_progress: Callable[[ConfigProgress], None] = None,
        on_log: Callable[[str], None] = None,
    ) -> ConfigResult:
        """仅启动网关并获取 WebUI 地址，不自动打开浏览器（US-06）

        流程：启动网关 → 健康检查（端口 18789）→ 获取 dashboard URL。
        浏览器不再自动打开，由用户在 UI 中手动点击按钮。

        Args:
            on_progress: 进度回调。
            on_log: 日志回调。

        Returns:
            ConfigResult: 若成功则包含 webchat_url 和 RUNNING 状态。
        """
        self._log_lines = []
        self._on_log = on_log

        try:
            self._log("Starting gateway...")
            if on_progress:
                on_progress(
                    ConfigProgress(
                        stage=ConfigStatus.GATEWAY_STARTING,
                        progress_percent=30,
                        message="正在启动网关...",
                        current_task="启动 openclaw gateway",
                    )
                )

            service_started = self._start_gateway()

            if not service_started:
                return ConfigResult(
                    status=ConfigStatus.FAILED,
                    service_status=ServiceStatus.FAILED,
                    message="网关启动失败",
                    error_message="无法启动 OpenClaw 网关服务",
                    log_lines=self._log_lines.copy(),
                )

            self._log("Health check...")
            if on_progress:
                on_progress(
                    ConfigProgress(
                        stage=ConfigStatus.HEALTH_CHECKING,
                        progress_percent=60,
                        message="正在检查服务状态...",
                        current_task="检查服务端口",
                    )
                )

            healthy = self._health_check()

            if not healthy:
                self._stop_gateway()
                return ConfigResult(
                    status=ConfigStatus.FAILED,
                    service_status=ServiceStatus.FAILED,
                    message="服务未就绪",
                    error_message="健康检查失败 - 端口 18789 未开放",
                    log_lines=self._log_lines.copy(),
                )

            self._log("Getting WebUI URL...")
            if on_progress:
                on_progress(
                    ConfigProgress(
                        stage=ConfigStatus.STARTING,
                        progress_percent=80,
                        message="正在获取访问地址...",
                        current_task="获取访问链接",
                    )
                )

            webui_url = self._get_webui_url()
            self._log(f"Final URL: {webui_url}")

            self._log("Gateway ready, URL obtained")
            if on_progress:
                on_progress(
                    ConfigProgress(
                        stage=ConfigStatus.COMPLETED,
                        progress_percent=100,
                        message="网关服务已启动",
                        current_task="等待用户打开 WebChat",
                    )
                )

            # 注意：不再自动打开浏览器，由用户在 UI 中手动点击 "打开 WebChat" 按钮
            return ConfigResult(
                status=ConfigStatus.COMPLETED,
                service_status=ServiceStatus.RUNNING,
                webchat_url=webui_url or "http://127.0.0.1:18789",
                message='网关服务已启动，请点击"打开 WebChat"按钮',
                browser_opened=False,  # 不自动打开
                log_lines=self._log_lines.copy(),
            )

        except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as e:
            # 顶层容错：捕获启动过程中所有已知运行时异常，防止 UI 崩溃
            self._log(f"Exception: {type(e).__name__}: {e}")
            self._log(f"Traceback: {traceback.format_exc()}")
            self._stop_gateway()
            return ConfigResult(
                status=ConfigStatus.FAILED,
                service_status=ServiceStatus.FAILED,
                message="Startup failed",
                error_message=str(e),
                log_lines=self._log_lines.copy(),
            )
        finally:
            self._on_log = None

    def quick_start(
        self,
        on_progress: Callable[[ConfigProgress], None] = None,
        on_log: Callable[[str], None] = None,
    ) -> ConfigResult:
        """快速启动：跳过配置，直接启动网关

        本质上是 startup_only 的别名，用于已配置过的场景。
        """
        return self.startup_only(on_progress=on_progress, on_log=on_log)

    def setup_and_start(
        self,
        on_progress: Callable[[ConfigProgress], None] = None,
    ) -> ConfigResult:
        """旧版入口：先配置再启动（config + startup）

        先调用 configure_only，若成功再调用 startup_only。
        """
        # 先执行配置
        config_result = self.configure_only(on_progress=on_progress)
        if config_result.status != ConfigStatus.COMPLETED:
            return config_result

        # 再启动网关
        return self.startup_only(on_progress=on_progress)

    def _check_openclaw_installed(self) -> bool:
        """检查 openclaw 命令是否可用

        Windows 使用 where 检测（避免某些 CLI 不支持 --version 导致误判）；
        Linux/macOS 使用 which 检测，并显式将 ~/.local/bin 加入 PATH，
        以确保用户通过安装器创建的 wrapper 能被找到。

        Returns:
            bool: 命令是否可用。
        """
        try:
            cmd = resolve_openclaw_cmd()
            os_type = platform.system().lower()
            if is_windows():
                # Windows: 直接用 where 检测命令是否存在，避免某些 CLI 不支持 --version
                result = subprocess.run(
                    ["where", cmd],
                    shell=False,
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
                return result.returncode == 0
            else:
                # Linux/macOS: 使用 which 检测，并确保 ~/.local/bin 在 PATH 中
                import os
                env = os.environ.copy()
                home = os.path.expanduser("~")
                local_bin = os.path.join(home, ".local", "bin")
                env["PATH"] = f"{local_bin}:{env.get('PATH', '')}"
                result = subprocess.run(
                    ["which", cmd],
                    capture_output=True,
                    text=True,
                    timeout=TIMEOUT_SHORT_CMD,
                    env=env,
                )
                return result.returncode == 0
        except (OSError, subprocess.SubprocessError):
            return False

    @log_method
    def _setup_default_config(self) -> bool:
        """设置 OpenClaw 默认配置并执行 onboard

        流程：
        1. 设置 gateway.mode=local、gateway.bind=loopback、gateway.port=18789。
        2. 执行 onboard --non-interactive ... 初始化环境。
        3. 若 onboard 返回非零但配置文件已存在，视为重复执行，仍然通过。
        4. 注入浏览器默认配置（启用 browser，defaultProfile=openclaw）。

        Returns:
            bool: 配置是否成功。
        """
        try:
            self._log("Setting default config...")
            configs = [
                ("gateway.mode", "local"),
                ("gateway.bind", "loopback"),
                ("gateway.port", "18789"),
                # openclaw-cn 不支持 allowUnconfigured，由 onboard 完成初始化
            ]

            for key, value in configs:
                try:
                    result = self._run_openclaw_command(["config", "set", key, value])
                    if result.returncode == 0:
                        self._log(f"Set {key}={value} OK")
                    else:
                        self._log(f"Set {key} failed: rc={result.returncode}")
                        if result.stderr:
                            self._log(f"  stderr: {result.stderr[:200]}")
                except (OSError, subprocess.SubprocessError) as e:
                    self._log(f"Set {key} error: {e}")
                    continue

            self._log("Running onboard...")
            onboard_ok = False
            try:
                result = self._run_openclaw_command([
                    "onboard", "--non-interactive", "--accept-risk", "--mode", "local",
                    "--skip-skills", "--skip-health", "--no-install-daemon",
                    "--node-manager", "pnpm", "--skip-channels",
                ])
                self._log(f"onboard return code: {result.returncode}")
                if result.stdout:
                    self._log(f"onboard stdout: {result.stdout[:500]}")
                if result.stderr:
                    self._log(f"onboard stderr: {result.stderr[:500]}")
                if result.returncode == 0:
                    onboard_ok = True
                else:
                    # onboard 非 0 可能是重复执行，检查配置目录是否已存在
                    import os
                    config_path = os.path.join(os.path.expanduser("~"), ".openclaw", "openclaw.json")
                    if os.path.exists(config_path):
                        self._log("onboard returned non-zero but config exists, treating as OK")
                        onboard_ok = True
                    else:
                        self._log("onboard failed and no config exists")
                        onboard_ok = False
            except (OSError, subprocess.SubprocessError) as e:
                self._log(f"onboard error: {e}")
                onboard_ok = False

            if not onboard_ok:
                return False

            self._inject_browser_config()

            return True

        except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as e:
            self._log(f"Setup config error: {e}")
            return False

    @log_method
    def _inject_browser_config(self) -> None:
        """向 ~/.openclaw/openclaw.json 注入浏览器默认配置

        若文件已存在则读取后追加/覆盖 browser 字段，不存在则新建。
        配置内容：enabled=True，defaultProfile="openclaw"。
        """
        import json
        import os

        config_path = os.path.join(os.path.expanduser("~"), ".openclaw", "openclaw.json")

        try:
            if os.path.exists(config_path):
                with open(config_path, "r", encoding="utf-8") as f:
                    config = json.load(f)
            else:
                config = {}
        except (json.JSONDecodeError, OSError) as e:
            self._log(f"Browser config: failed to read existing config: {e}")
            config = {}

        config["browser"] = {
            "enabled": True,
            "defaultProfile": "openclaw",
        }

        try:
            os.makedirs(os.path.dirname(config_path), exist_ok=True)
            with open(config_path, "w", encoding="utf-8") as f:
                json.dump(config, f, indent=2, ensure_ascii=False)
            self._log("Browser config injected: enabled=true, defaultProfile=openclaw")
        except OSError as e:
            self._log(f"Browser config: failed to write: {e}")

    def _build_clean_env(self) -> dict:
        """构建干净的子进程环境变量

        过滤掉包含非 ASCII 字符的环境变量（避免某些中文路径或特殊字符导致
        subprocess 编码错误），同时保留 HOME、PATH 等核心变量。
        最后确保 ~/.local/bin 在 PATH 最前面，以便找到 wrapper 脚本。

        Returns:
            dict: 清理后的环境变量字典。
        """
        import os
        env = os.environ.copy()
        keep_always = {"HOME", "PATH", "SHELL", "TMPDIR", "PWD", "OLDPWD"}
        clean_env = {}
        for k, v in env.items():
            if k in keep_always:
                clean_env[k] = v
                continue
            try:
                v.encode("ascii")
                clean_env[k] = v
            except UnicodeEncodeError:
                pass
        # 确保 ~/.local/bin 在 PATH 中（Linux/macOS wrapper 安装位置）
        home = os.path.expanduser("~")
        local_bin = os.path.join(home, ".local", "bin")
        clean_env["PATH"] = f"{local_bin}:{clean_env.get('PATH', '')}"
        return clean_env

    @log_method
    def _start_gateway(self) -> bool:
        """启动 OpenClaw 网关服务（前台模式）

        启动流程：
        1. 先检查网关是否已在运行（最多重试 3 次）。
        2. 若端口 18789 被占用，尝试释放该端口。
        3. 使用前台模式启动（openclaw gateway，不加 start），避免需要管理员权限。
        4. Windows 使用 PowerShell 包装并隐藏窗口；Linux/macOS 直接运行。
        5. 轮询最多 20 秒：检查进程是否存活、通过 gateway status 检查、检测端口开放。

        Returns:
            bool: 网关是否成功进入就绪状态。
        """
        try:
            self._log("Checking if gateway already running...")
            # 轮询 3 次检查是否已有实例在运行
            for i in range(3):
                try:
                    result = self._run_openclaw_command(["gateway", "status"])
                    if result.returncode == 0 and "running" in result.stdout.lower():
                        self._log("Gateway already running")
                        return True
                except (OSError, subprocess.SubprocessError) as e:
                    self._log(f"Check status error: {e}")
                time.sleep(0.5)

            # 若端口被占用，尝试释放（可能是之前异常退出的残留进程）
            if self._is_port_open(18789):
                self._log("Port occupied, trying to release...")
                self._kill_port_process(18789)
                time.sleep(1)

            # 所有平台统一使用前台模式（不需要管理员权限）
            os_type = platform.system().lower()
            self._log(f"Detected OS: {os_type}")
            self._log("Starting gateway in foreground mode...")

            # 使用 'openclaw gateway'（不带 'start'）前台启动，任何平台都不需要管理员权限
            env = self._build_clean_env()
            cmd = resolve_openclaw_cmd()

            # 如果全局命令找不到，但本地项目存在，则 fallback 到项目内 pnpm 执行
            local_project = Path(os.path.expanduser("~")) / "openclaw-cn"
            local_fallback = (
                cmd == "openclaw"
                and not shutil.which("openclaw")
                and not shutil.which("openclaw-cn")
                and local_project.exists()
                and (local_project / "package.json").exists()
            )

            popen_kwargs = {
                "shell": False,
                "stdout": subprocess.PIPE,
                "stderr": subprocess.PIPE,
                "text": True,
                "env": env,
            }

            if is_windows():
                if local_fallback:
                    full_cmd = ["pnpm", "openclaw", "gateway"]
                    popen_kwargs["cwd"] = str(local_project)
                else:
                    full_cmd = [cmd, "gateway"]
                # Windows 隐藏窗口
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                startupinfo.wShowWindow = 0
                popen_kwargs["startupinfo"] = startupinfo
                popen_kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW
            else:
                if local_fallback:
                    full_cmd = ["pnpm", "openclaw", "gateway"]
                    popen_kwargs["cwd"] = str(local_project)
                else:
                    full_cmd = [cmd, "gateway"]

            self._log(f"Execute: {' '.join(full_cmd[:5])}...")

            # 如果已有旧进程在运行，先终止它，避免僵尸进程或端口冲突
            if self.process is not None:
                try:
                    self._kill_process_tree(self.process)
                    self._log("已终止旧的 Gateway 进程")
                except (OSError, subprocess.SubprocessError):
                    pass
                self.process = None

            # 使用 Popen 后台运行，避免阻塞主线程
            self.process = subprocess.Popen(full_cmd, **popen_kwargs)

            self._log(f"Gateway process started with PID: {self.process.pid}")

            self._log("Waiting for service initialization...")
            time.sleep(3)

            self._log("Waiting for gateway ready...")
            # 最多等待 20 秒，每秒检查一次
            for i in range(20):
                if self.is_cancelled:
                    return False

                time.sleep(1)

                # 检查前台进程是否已异常退出
                if self.process:
                    if self.process.poll() is not None:
                        # 进程已退出，收集输出用于诊断
                        stdout, stderr = "", ""
                        try:
                            stdout, stderr = self.process.communicate(timeout=1)
                        except:
                            pass
                        self._log(f"Gateway process exited early! rc={self.process.returncode}")
                        if stdout:
                            self._log(f"stdout: {stdout[:500]}")
                        if stderr:
                            self._log(f"stderr: {stderr[:500]}")
                        return False

                # 通过 gateway status 命令检查服务状态
                try:
                    result = self._run_openclaw_command(["gateway", "status"])
                    self._log(f"Status check #{i+1}: rc={result.returncode}")
                    if result.returncode == 0:
                        if "running" in result.stdout.lower():
                            self._log("Gateway ready")
                            return True
                        else:
                            self._log(f"Status output: {result.stdout[:200]}")
                except (OSError, subprocess.SubprocessError) as e:
                    self._log(f"Status check error: {e}")

                # 检查端口是否已开放（兜底判断）
                if self._is_port_open(18789):
                    self._log("Port 18789 is open, gateway is ready")
                    return True

                # 每 5 秒输出一次等待提示，避免 UI 长时间无响应
                if (i + 1) % 5 == 0:
                    self._log(f"Waiting for gateway... ({i+1}/20s)")

            self._log("Gateway start timeout")
            return False

        except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as e:
            # 顶层容错：捕获网关启动过程中所有已知运行时异常，防止 UI 崩溃
            self._log(f"Start gateway error: {type(e).__name__}: {e}")
            self._log(f"Traceback: {traceback.format_exc()}")
            return False

    def _run_openclaw_command(self, args: list[str]) -> subprocess.CompletedProcess:
        """执行 openclaw 子命令（使用 shell=False，彻底避免命令注入）

        安全策略：
        - 不再接收字符串命令，只接受参数列表，使用 shell=False 执行。
        - Windows 直接调用可执行文件（配合 CREATE_NO_WINDOW 隐藏窗口）。
        - 若全局命令找不到但本地项目目录存在，fallback 到项目内 pnpm openclaw。

        Args:
            args: 要执行的 openclaw 子命令参数列表（如 ["config", "set", "gateway.mode", "local"]）。

        Returns:
            subprocess.CompletedProcess: 包含 returncode、stdout、stderr。
        """
        import os
        import shutil

        # 防御：确保 args 是字符串列表，防止注入
        if not isinstance(args, list) or not all(isinstance(a, str) for a in args):
            self._log("拒绝执行：参数必须是字符串列表")
            return subprocess.CompletedProcess(
                args=[], returncode=1, stdout="", stderr="参数类型错误",
            )

        os_type = platform.system().lower()
        cmd = resolve_openclaw_cmd()
        env = self._build_clean_env()

        # 如果全局命令找不到，但本地项目存在，则 fallback 到项目内 pnpm 执行
        local_project = Path(os.path.expanduser("~")) / "openclaw-cn"
        local_fallback = (
            cmd == "openclaw"
            and not shutil.which("openclaw")
            and not shutil.which("openclaw-cn")
            and local_project.exists()
            and (local_project / "package.json").exists()
        )

        if is_windows():
            if local_fallback:
                # 在项目目录内执行 pnpm openclaw <args>
                full_cmd = ["pnpm", "openclaw"] + args
                cwd = str(local_project)
            else:
                full_cmd = [cmd] + args
                cwd = None

            self._log(f"Execute: {' '.join(full_cmd[:5])}...")

            # Windows 隐藏窗口参数
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startupinfo.wShowWindow = 0  # SW_HIDE

            result = subprocess.run(
                full_cmd,
                shell=False,
                capture_output=True,
                text=True,
                timeout=TIMEOUT_OPENCLAW_CMD,
                env=env,
                cwd=cwd,
                startupinfo=startupinfo,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            return result
        else:
            if local_fallback:
                full_cmd = ["pnpm", "openclaw"] + args
                cwd = str(local_project)
            else:
                full_cmd = [cmd] + args
                cwd = None

            self._log(f"Execute: {' '.join(full_cmd[:5])}...")

            result = subprocess.run(
                full_cmd,
                shell=False,
                capture_output=True,
                text=True,
                timeout=TIMEOUT_OPENCLAW_CMD,
                env=env,
                cwd=cwd,
            )
            return result

    def _kill_port_process(self, port: int) -> None:
        """释放被占用的端口

        先对端口进行防御性校验（纯数字、1-65535），然后按平台执行：
        - Windows: netstat -ano 查找 PID，再 taskkill /F 强制结束。
        - Linux/macOS: lsof -ti :port 查找 PID，再 kill -9 强制结束。

        Args:
            port: 要释放的端口号。
        """
        try:
            # 防御性校验：确保 port 是纯数字且在合法范围内
            port = int(port)
            if not (1 <= port <= 65535):
                self._log(f"Invalid port: {port}")
                return

            os_type = platform.system().lower()
            if is_windows():
                result = subprocess.run(
                    ["netstat", "-ano"],
                    capture_output=True,
                    text=True,
                )
                if result.returncode == 0 and result.stdout:
                    for line in result.stdout.strip().splitlines():
                        if f":{port}" in line:
                            parts = line.strip().split()
                            if len(parts) >= 5:
                                pid = parts[-1]
                                if pid.isdigit():
                                    try:
                                        subprocess.run(
                                            ["taskkill", "/PID", pid, "/F"],
                                            capture_output=True,
                                        )
                                        self._log(f"Killed process PID: {pid}")
                                    except (OSError, subprocess.SubprocessError) as e:
                                        self._log(f"Kill process error: {e}")
            else:
                result = subprocess.run(
                    ["lsof", "-ti", f":{port}"],
                    capture_output=True,
                    text=True,
                )
                if result.returncode == 0 and result.stdout:
                    for pid in result.stdout.strip().splitlines():
                        pid = pid.strip()
                        if pid.isdigit():
                            try:
                                subprocess.run(
                                    ["kill", "-9", pid],
                                    capture_output=True,
                                )
                                self._log(f"Killed process PID: {pid}")
                            except (OSError, subprocess.SubprocessError) as e:
                                self._log(f"Kill process error: {e}")
        except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as e:
            self._log(f"Release port error: {e}")

    def _is_port_open(self, port: int) -> bool:
        """检测本地端口是否开放

        Args:
            port: 端口号。

        Returns:
            bool: 端口是否可连接。
        """
        import socket
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            sock.settimeout(2)
            return sock.connect_ex(("localhost", port)) == 0
        except (OSError, socket.error):
            return False
        finally:
            sock.close()

    def _health_check(self) -> bool:
        """健康检查：检测网关端口 18789 是否开放

        Returns:
            bool: 服务是否健康。
        """
        return self._is_port_open(18789)

    @log_method
    def _get_webui_url(self) -> str:
        """通过 dashboard 命令获取 WebUI 访问地址

        最多重试 10 次（每次间隔 1 秒），从 stdout+stderr 中正则提取 URL。
        若提取失败则返回默认地址 http://127.0.0.1:18789。

        Returns:
            str: WebUI 完整 URL（含 token）。
        """
        for attempt in range(10):
            try:
                self._log(f"Getting WebUI URL (attempt {attempt + 1}/10)...")

                result = self._run_openclaw_command(["dashboard", "--no-open"])

                output = result.stdout + result.stderr
                self._log(f"dashboard output: {output[:300]}")

                if result.returncode == 0:
                    url_match = re.search(r'https?://[^\s\n\r]+', output)
                    if url_match:
                        url = url_match.group(0)
                        # 校验 URL 是否包含 token 或目标端口，避免误匹配
                        if "token=" in url or "18789" in url:
                            self._log(f"Got URL: {url}")
                            return url
                else:
                    self._log(f"dashboard return code: {result.returncode}")

            except (OSError, subprocess.SubprocessError, re.error) as e:
                self._log(f"Get URL error: {type(e).__name__}: {e}")

            # 最后一次不再等待
            if attempt < 9:
                time.sleep(1)

        self._log("Failed to get URL from dashboard, using default")
        return "http://127.0.0.1:18789"

    def _open_browser(self, url: str) -> bool:
        """打开系统默认浏览器访问指定 URL

        尝试顺序：
        1. webbrowser.open（跨平台，最干净）。
        2. Windows: start 命令。
        3. 按平台使用 os.system 兜底（start / open / xdg-open）。

        Args:
            url: 要打开的完整 URL。

        Returns:
            bool: 是否至少有一种方式成功执行。
        """
        self._log(f"Opening browser: {url}")

        try:
            webbrowser.open(url, new=2)
            self._log("webbrowser.open success")
            return True
        except (OSError, webbrowser.Error) as e:
            self._log(f"webbrowser.open failed: {e}")

        if is_windows():
            try:
                result = subprocess.run(
                    ["cmd", "/c", "start", "", url],
                    shell=False,
                    capture_output=True,
                    timeout=TIMEOUT_SHORT_CMD,
                )
                if result.returncode == 0:
                    self._log("start command success")
                    return True
            except (OSError, subprocess.SubprocessError) as e:
                self._log(f"start command failed: {e}")

        try:
            if is_windows():
                os.system(f'start "" "{url}"')
            elif is_macos():
                os.system(f'open "{url}"')
            else:
                os.system(f'xdg-open "{url}"')
            self._log("os.system executed")
            return True
        except OSError as e:
            self._log(f"os.system failed: {e}")

        return False

    def _stop_gateway(self) -> None:
        """停止网关服务

        停止策略：
        1. 若前台进程仍在运行，先 terminate，5 秒内不退出则 kill。
        2. 执行 gateway stop 命令（兼容后台模式残留）。
        3. 强制释放端口 18789。
        """
        try:
            self._log("Stopping gateway...")

            # 所有平台现在使用前台模式：终止我们启动的进程
            if self.process and self.process.poll() is None:
                self._log(f"Terminating gateway process (PID: {self.process.pid})")
                self.process.terminate()
                try:
                    self.process.wait(timeout=TIMEOUT_SHORT_CMD)
                except:
                    self._log("Force killing gateway process...")
                    self.process.kill()

            # 同时尝试命令行 stop 并释放端口 18789（兜底）
            try:
                self._run_openclaw_command(["gateway", "stop"])
            except (OSError, subprocess.SubprocessError) as e:
                self._log(f"gateway stop command error: {e}")

            self._kill_port_process(18789)
        except (OSError, subprocess.SubprocessError) as e:
            self._log(f"Stop gateway error: {e}")

    def read_existing_provider_config(self) -> dict:
        """读取已有的 Provider 配置

        从两个来源读取：
        1. ~/.openclaw/openclaw.json —— env 变量、默认模型、providers 配置
        2. ~/.openclaw/agents/main/agent/auth-profiles.json —— auth profile 中的 API Key

        读取 env 时会做防污染过滤：跳过包含 Traceback/ERROR 或长度过短的值，
        避免之前崩溃时写入的堆栈信息被误读为 API Key。

        Returns:
            dict: {
                "env": {"DEEPSEEK_API_KEY": "sk-xxx", ...},
                "auth_profiles": {"kimi-coding": "sk-xxx", ...},
                "primary_model": "deepseek/deepseek-chat",
                "providers": {"deepseek": {"baseUrl": "...", ...}},
            }
        """
        import json
        import os

        result = {
            "env": {},
            "auth_profiles": {},
            "primary_model": "",
            "fallback_models": [],
            "providers": {},
        }

        # 1. 读取 openclaw.json
        config_path = os.path.join(os.path.expanduser("~"), ".openclaw", "openclaw.json")
        try:
            if os.path.exists(config_path):
                with open(config_path, "r", encoding="utf-8") as f:
                    config = json.load(f)

                # env 中的 API Key（防污染：跳过包含崩溃日志等异常内容的 key）
                env = config.get("env", {})
                if isinstance(env, dict):
                    clean_env = {}
                    for k, v in env.items():
                        if "_API_KEY" not in k:
                            continue
                        val = str(v).replace('"', '').replace('\n', ' ').strip()
                        if not val or len(val) < 10 or 'Traceback' in val or 'ERROR' in val:
                            continue
                        clean_env[k] = v
                    result["env"] = clean_env

                # 默认模型
                agents = config.get("agents", {})
                defaults = agents.get("defaults", {})
                model = defaults.get("model", {})
                if isinstance(model, dict):
                    result["primary_model"] = model.get("primary", "")
                    result["fallback_models"] = model.get("fallbacks", [])
                elif isinstance(model, str):
                    result["primary_model"] = model
                    result["fallback_models"] = []

                # providers 配置
                models_config = config.get("models", {})
                providers = models_config.get("providers", {})
                if isinstance(providers, dict):
                    result["providers"] = providers
        except (json.JSONDecodeError, OSError):
            pass

        # 2. 读取 auth-profiles.json
        auth_path = os.path.join(
            os.path.expanduser("~"), ".openclaw", "agents", "main", "agent", "auth-profiles.json"
        )
        try:
            if os.path.exists(auth_path):
                with open(auth_path, "r", encoding="utf-8") as f:
                    auth_store = json.load(f)

                profiles = auth_store.get("profiles", {})
                for profile_id, cred in profiles.items():
                    if not isinstance(cred, dict):
                        continue
                    # 提取 provider 和 key
                    # profile_id 格式: "provider:default" 或 "provider:work"
                    provider = cred.get("provider", "")
                    if not provider:
                        # 从 profile_id 推断
                        if ":" in profile_id:
                            provider = profile_id.split(":")[0]

                    if cred.get("type") == "api_key" and cred.get("key"):
                        result["auth_profiles"][provider] = cred["key"]
                    elif cred.get("type") == "token" and cred.get("token"):
                        result["auth_profiles"][provider] = cred["token"]
        except (json.JSONDecodeError, OSError):
            pass

        return result

    def configure_providers(
        self,
        providers_config: dict[str, Any],
        global_default_model: str,
        fallback_models: Optional[list[str]] = None,
        on_progress: Optional[Callable[[ConfigProgress], None]] = None,
        on_log: Optional[Callable[[str], None]] = None,
    ) -> bool:
        """配置 AI Provider：写入 env 变量和默认模型

        执行流程：
        1. 遍历 providers_config，设置主 env 变量和 fallback env 变量。
        2. 若 provider 有 auth_choice，执行 onboard 初始化 provider 配置。
        3. 设置全局默认模型（agents.defaults.model 对象格式）。
        4. 更新 provider 模型列表（覆盖 onboard 可能创建的过时模型别名）。
        5. 对无 onboard 的自定义 provider（如 DashScope）直接写入 models.providers。

        安全策略：写入 env 前会清理 API Key，过滤掉包含 Traceback/ERROR 或长度不足的值，
        防止之前崩溃堆栈污染配置。

        Args:
            providers_config: {vendor_id: {api_key, env_var, fallback_env_var, model, base_url, auth_choice, key_type}}
            global_default_model: 全局默认 model ref
            fallback_models: 备选模型列表
            on_progress: 进度回调
            on_log: 日志回调

        Returns:
            bool: 是否全部成功（任一子步骤失败会置为 False，但会继续执行后续步骤）。
        """
        self._on_log = on_log
        all_ok = True

        total = len(providers_config)
        for idx, (config_key, cfg) in enumerate(providers_config.items(), 1):
            # config_key 格式: "vendor_id:key_type" 或 "vendor_id"
            if ":" in config_key:
                vendor_id, _ = config_key.split(":", 1)
            else:
                vendor_id = config_key

            api_key = cfg.get("api_key", "").strip()
            env_var = cfg.get("env_var", "")
            fallback_env_var = cfg.get("fallback_env_var", "")
            auth_choice = cfg.get("auth_choice", "")

            if not api_key or not env_var:
                continue

            self._log(f"[{idx}/{total}] Configuring {vendor_id}...")
            if on_progress:
                on_progress(
                    ConfigProgress(
                        stage=ConfigStatus.CONFIGURING,
                        progress_percent=int(10 + 80 * idx / total),
                        message=f"正在配置 {vendor_id}...",
                        current_task=f"配置 {vendor_id}",
                    )
                )

            # 1. 设置主 env 变量（先清理异常字符，防止之前崩溃堆栈等垃圾数据污染配置）
            cleaned_key = api_key.replace('"', '').replace('\n', ' ').strip()
            if not cleaned_key or len(cleaned_key) < 10 or 'Traceback' in cleaned_key or 'ERROR' in cleaned_key:
                self._log(f"  Skip env.{env_var}: API Key 格式异常（可能包含崩溃日志或无效字符）")
                all_ok = False
                continue
            try:
                result = self._run_openclaw_command(["config", "set", f"env.{env_var}", cleaned_key])
                if result.returncode == 0:
                    self._log(f"  Set env.{env_var} OK")
                else:
                    self._log(f"  Set env.{env_var} failed: rc={result.returncode}")
                    if result.stderr:
                        # 脱敏：如果 stderr 中包含 API Key，替换为 ***，防止敏感信息泄露到日志
                        safe_stderr = result.stderr[:200]
                        # 同时检查原始 api_key 和 cleaned_key
                        for sensitive in (api_key, cleaned_key):
                            if sensitive and sensitive in safe_stderr:
                                safe_stderr = safe_stderr.replace(sensitive, "***")
                        self._log(f"    stderr: {safe_stderr}")
                    all_ok = False
            except (OSError, subprocess.SubprocessError) as e:
                self._log(f"  Set env.{env_var} error: {e}")
                all_ok = False

            # 2. 如有 fallback_env_var，也设置（用于兼容不同 provider 的命名习惯）
            if fallback_env_var and fallback_env_var != env_var:
                try:
                    result = self._run_openclaw_command(["config", "set", f"env.{fallback_env_var}", api_key])
                    if result.returncode == 0:
                        self._log(f"  Set env.{fallback_env_var} OK")
                except (OSError, subprocess.SubprocessError) as e:
                    self._log(f"  Set env.{fallback_env_var} error: {e}")

            # 3. 如有 auth_choice，执行 onboard（设置 provider baseUrl 等元信息）
            if auth_choice:
                try:
                    result = self._run_openclaw_command([
                        "onboard", "--auth-choice", auth_choice,
                        "--non-interactive", "--accept-risk", "--mode", "local",
                        "--skip-skills", "--skip-health", "--no-install-daemon",
                        "--node-manager", "pnpm", "--skip-channels",
                    ])
                    self._log(f"  onboard return code: {result.returncode}")
                    if result.stdout:
                        self._log(f"  onboard stdout: {result.stdout[:300]}")
                    if result.stderr:
                        self._log(f"  onboard stderr: {result.stderr[:300]}")
                    if result.returncode != 0:
                        # 检查 provider 是否已存在（onboard 可能是重复执行）
                        import json, os
                        config_path = os.path.join(os.path.expanduser("~"), ".openclaw", "openclaw.json")
                        provider_exists = False
                        try:
                            if os.path.exists(config_path):
                                with open(config_path, "r", encoding="utf-8") as f:
                                    cfg = json.load(f)
                                providers = cfg.get("models", {}).get("providers", {})
                                if vendor_id in providers:
                                    provider_exists = True
                        except (OSError, json.JSONDecodeError, ValueError):
                            pass
                        if provider_exists:
                            self._log(f"  onboard returned non-zero but provider {vendor_id} exists, treating as OK")
                        else:
                            self._log(f"  onboard FAILED, provider config may be incomplete")
                            all_ok = False
                except (OSError, subprocess.SubprocessError) as e:
                    self._log(f"  onboard error: {e}")
                    all_ok = False

        # 4. 设置全局默认模型 + fallback（agents.defaults.model 为对象格式）
        if global_default_model:
            self._log(f"Setting global default model: {global_default_model}")
            try:
                self._set_model_config(global_default_model, fallback_models)
                self._log("  Set model config OK")
            except (OSError, ValueError, RuntimeError) as e:
                self._log(f"  Set model config error: {e}")
                all_ok = False

        # 5. 更新 provider 模型列表（覆盖 onboard 可能创建的过时模型，如 k2p5 → kimi-for-coding）
        for config_key, cfg in providers_config.items():
            selected_models = cfg.get("selected_models", [])
            if selected_models:
                try:
                    self._update_provider_models(config_key, cfg)
                except (OSError, ValueError, RuntimeError) as e:
                    self._log(f"  Update provider models {config_key} error: {e}")
                    all_ok = False

        # 7. 写入自定义 provider 配置（无 onboard 的 provider，如 DashScope）
        for config_key, cfg in providers_config.items():
            auth_choice = cfg.get("auth_choice", "")
            base_url = cfg.get("base_url", "")
            if not auth_choice and base_url:
                try:
                    self._configure_custom_provider(config_key, cfg)
                except (OSError, ValueError, RuntimeError) as e:
                    self._log(f"  Configure custom provider {config_key} error: {e}")
                    all_ok = False

        self._on_log = None
        return all_ok

    def _set_model_config(self, primary: str, fallbacks: Optional[list] = None) -> None:
        """直接修改 openclaw.json 写入 agents.defaults.model（对象格式：primary + fallbacks）

        Args:
            primary: 主模型引用（如 "deepseek/deepseek-chat"）。
            fallbacks: 备选模型引用列表。
        """
        import json
        import os

        config_path = os.path.join(os.path.expanduser("~"), ".openclaw", "openclaw.json")

        try:
            if os.path.exists(config_path):
                with open(config_path, "r", encoding="utf-8") as f:
                    config = json.load(f)
            else:
                config = {}
        except (json.JSONDecodeError, OSError) as e:
            self._log(f"  Failed to read config for model: {e}")
            config = {}

        if "agents" not in config:
            config["agents"] = {}
        if "defaults" not in config["agents"]:
            config["agents"]["defaults"] = {}

        model_cfg = {"primary": primary}
        if fallbacks:
            model_cfg["fallbacks"] = fallbacks

        config["agents"]["defaults"]["model"] = model_cfg

        try:
            os.makedirs(os.path.dirname(config_path), exist_ok=True)
            with open(config_path, "w", encoding="utf-8") as f:
                json.dump(config, f, indent=2, ensure_ascii=False)
            self._log(f"  Set model config: primary={primary}, fallbacks={fallbacks or 'none'}")
        except OSError as e:
            self._log(f"  Failed to write model config: {e}")
            raise

    def _update_provider_models(self, config_key: str, cfg: dict) -> None:
        """直接修改 openclaw.json 更新 provider 模型列表（覆盖 onboard 过时模型）

        将 UI 中选中的模型写入 models.providers.<provider_id>.models，
        同时更新 agents.defaults.models 别名映射。

        Args:
            config_key: 格式 "vendor_id:key_type" 或 "vendor_id"。
            cfg: 包含 selected_models、model_prefix、key_type 等字段的配置字典。
        """
        import json
        import os

        config_path = os.path.join(os.path.expanduser("~"), ".openclaw", "openclaw.json")

        try:
            if os.path.exists(config_path):
                with open(config_path, "r", encoding="utf-8") as f:
                    config = json.load(f)
            else:
                config = {}
        except (json.JSONDecodeError, OSError) as e:
            self._log(f"  Failed to read config for model update: {e}")
            config = {}

        if "models" not in config:
            config["models"] = {}
        if "providers" not in config["models"]:
            config["models"]["providers"] = {}

        if ":" in config_key:
            vendor_id, key_type = config_key.split(":", 1)
        else:
            vendor_id = config_key
            key_type = cfg.get("key_type", "")

        provider_id = self._resolve_provider_id(vendor_id, key_type)
        model_prefix = cfg.get("model_prefix", "")

        models = []
        aliases = {}
        for model_ref in cfg.get("selected_models", []):
            model_id = model_ref.split("/")[-1] if "/" in model_ref else model_ref
            display_name = model_id
            models.append({
                "id": model_id,
                "name": display_name,
                "reasoning": False,
                "input": ["text"],
                "cost": {"input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0},
                "contextWindow": 262144,
                "maxTokens": 32768,
            })
            aliases[f"{provider_id}/{model_id}"] = {"alias": display_name}

        if provider_id in config["models"]["providers"]:
            config["models"]["providers"][provider_id]["models"] = models
        else:
            self._log(f"  WARNING: Provider {provider_id} not found in config, skipping model update (onboard may have failed)")
            return

        # 同时更新 agents.defaults.models alias（注意：是 defaults.models，不是 defaults.model.models）
        if "agents" not in config:
            config["agents"] = {}
        if "defaults" not in config["agents"]:
            config["agents"]["defaults"] = {}
        if "models" not in config["agents"]["defaults"]:
            config["agents"]["defaults"]["models"] = {}

        config["agents"]["defaults"]["models"].update(aliases)

        try:
            os.makedirs(os.path.dirname(config_path), exist_ok=True)
            with open(config_path, "w", encoding="utf-8") as f:
                json.dump(config, f, indent=2, ensure_ascii=False)
            self._log(f"  Updated provider {provider_id} models OK")
        except OSError as e:
            self._log(f"  Failed to write provider models: {e}")
            raise

    def _configure_custom_provider(self, config_key: str, cfg: dict) -> None:
        """直接修改 openclaw.json 写入自定义 provider 配置（如 DashScope）

        适用于没有 onboard auth_choice 的 provider，直接构造 models.providers 条目，
        包含 baseUrl、api、apiKey 和模型列表。

        Args:
            config_key: 格式 "vendor_id:key_type" 或 "vendor_id"。
            cfg: 包含 base_url、api_key、selected_models 等字段的配置字典。
        """
        import json
        import os

        config_path = os.path.join(os.path.expanduser("~"), ".openclaw", "openclaw.json")

        try:
            if os.path.exists(config_path):
                with open(config_path, "r", encoding="utf-8") as f:
                    config = json.load(f)
            else:
                config = {}
        except (json.JSONDecodeError, OSError) as e:
            self._log(f"  Failed to read config for custom provider: {e}")
            config = {}

        if "models" not in config:
            config["models"] = {}
        if "providers" not in config["models"]:
            config["models"]["providers"] = {}

        # 解析 config_key: "vendor_id:key_type"
        if ":" in config_key:
            vendor_id, key_type = config_key.split(":", 1)
        else:
            vendor_id = config_key
            key_type = cfg.get("key_type", "")

        # 确定 provider ID
        provider_id = self._resolve_provider_id(vendor_id, key_type)

        # 构建模型列表
        models = []
        for model_ref in cfg.get("selected_models", []):
            model_id = model_ref.split("/")[-1] if "/" in model_ref else model_ref
            models.append({
                "id": model_id,
                "name": model_id,
                "reasoning": False,
                "input": ["text"],
                "cost": {"input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0},
                "contextWindow": 128000,
                "maxTokens": 8192,
            })

        config["models"]["providers"][provider_id] = {
            "baseUrl": cfg["base_url"],
            "api": "openai-completions",
            "apiKey": cfg["api_key"],
            "models": models,
        }

        try:
            os.makedirs(os.path.dirname(config_path), exist_ok=True)
            with open(config_path, "w", encoding="utf-8") as f:
                json.dump(config, f, indent=2, ensure_ascii=False)
            self._log(f"  Set custom provider {provider_id} OK")
        except OSError as e:
            self._log(f"  Failed to write custom provider {provider_id}: {e}")
            raise

    def _resolve_provider_id(self, vendor_id: str, key_type: str) -> str:
        """将程序内部的 vendor_id 映射到 openclaw 的 provider ID

        部分厂商在 openclaw 中有多个 provider 身份（如 kimi 对应 moonshot/kimi-coding），
        通过 key_type 区分场景。

        Args:
            vendor_id: 内部厂商标识（如 "kimi"、"aliyun"）。
            key_type: 密钥类型（如 "coding"、空字符串）。

        Returns:
            str: openclaw 使用的 provider ID。
        """
        if vendor_id == "kimi":
            return "kimi-coding" if key_type == "coding" else "moonshot"
        if vendor_id == "aliyun":
            return "aliyun-coding" if key_type == "coding" else "dashscope"
        if vendor_id == "volcengine":
            return "volcengine-plan" if key_type == "coding" else "volcengine"
        return vendor_id

    def stop(self) -> None:
        """外部调用：停止服务并标记取消状态。复用基类的取消标志设置，再终止 Gateway。"""
        super().stop()
        self._stop_gateway()

    def is_running(self) -> bool:
        """检查前台网关进程是否仍在运行

        Returns:
            bool: 进程是否存活。
        """
        return self.process is not None and self.process.poll() is None

    def uninstall(
        self,
        on_log: Optional[Callable[[str], None]] = None,
        cancel_event: Optional[Callable[[], bool]] = None,
    ) -> bool:
        """完全卸载 OpenClaw

        卸载流程：
        1. 停止 Gateway（若正在运行）。
        2. 删除本地构建目录（~/openclaw-cn、~/.openclaw）。
        3. 卸载 npm 全局包（兼容旧版直接 npm install -g 的情况）。
        4. 删除命令包装器（Windows: %APPDATA%\npm\\*.cmd；Linux/macOS: ~/.local/bin）。

        每一步之前都会检查 cancel_event，若返回 True 则提前终止并返回 False。

        Args:
            on_log: 日志回调，用于在 UI 中展示卸载进度。
            cancel_event: 取消检查函数，返回 True 表示请求取消。

        Returns:
            bool: 是否全部成功（个别步骤失败不影响整体返回，但会记录日志）。
        """
        import shutil
        import platform

        all_ok = True
        os_type = platform.system().lower()
        home = os.path.expanduser("~")

        # 1. 停止 Gateway
        if cancel_event and cancel_event():
            if on_log:
                on_log("卸载已取消")
            return False
        try:
            self._stop_gateway()
            if on_log:
                on_log("已停止 OpenClaw Gateway")
        except (OSError, subprocess.SubprocessError) as e:
            if on_log:
                on_log(f"停止 Gateway 失败（可能未运行）: {e}")

        # 2. 删除本地构建目录
        if cancel_event and cancel_event():
            if on_log:
                on_log("卸载已取消")
            return False
        dirs_to_remove = [
            os.path.join(home, "openclaw-cn"),
            os.path.join(home, ".openclaw"),
        ]
        for d in dirs_to_remove:
            if os.path.exists(d):
                try:
                    shutil.rmtree(d, onerror=remove_readonly)
                    if on_log:
                        on_log(f"已删除: {d}")
                except (OSError, shutil.Error) as e:
                    if on_log:
                        on_log(f"删除 {d} 失败: {e}")
                    all_ok = False

        # 3. 卸载 npm 全局包（兼容旧版直接 npm install -g 的情况）
        if cancel_event and cancel_event():
            if on_log:
                on_log("卸载已取消")
            return False
        for pkg in ["openclaw-cn", "openclaw"]:
            try:
                result = subprocess.run(
                    ["npm", "uninstall", "-g", pkg],
                    shell=False, capture_output=True, text=True
                )
                if result.returncode == 0:
                    if on_log:
                        on_log(f"已卸载 npm 包: {pkg}")
                elif on_log:
                    on_log(f"npm 包 {pkg} 可能未全局安装，跳过")
            except (OSError, subprocess.SubprocessError) as e:
                if on_log:
                    on_log(f"卸载 {pkg} 出错: {e}")

        # 4. 删除命令包装器
        if cancel_event and cancel_event():
            if on_log:
                on_log("卸载已取消")
            return False
        if os_type == "win32":
            wrapper_dir = os.path.join(home, r"AppData\Roaming\npm")
            wrappers = ["openclaw.cmd", "openclaw-cn.cmd"]
        else:
            wrapper_dir = os.path.join(home, ".local", "bin")
            wrappers = ["openclaw", "openclaw-cn"]

        for w in wrappers:
            wpath = os.path.join(wrapper_dir, w)
            if os.path.exists(wpath):
                try:
                    os.remove(wpath)
                    if on_log:
                        on_log(f"已删除命令: {wpath}")
                except OSError as e:
                    if on_log:
                        on_log(f"删除 {wpath} 失败: {e}")

        if on_log:
            on_log("OpenClaw 卸载完成")
        return all_ok

