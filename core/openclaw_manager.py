import subprocess
import platform
import time
import os
import signal
import webbrowser
import re
from pathlib import Path
from typing import Optional, Callable

from models.config import (
    ConfigStatus,
    ServiceStatus,
    ConfigProgress,
    ConfigResult,
)


class OpenClawManager:
    """OpenClaw Service Manager"""

    def __init__(self):
        self.process: Optional[subprocess.Popen] = None
        self.is_cancelled = False
        self._webui_url: Optional[str] = None
        self._log_lines: list = []
        self._on_log: Optional[Callable[[str], None]] = None
    
    def _log(self, message: str):
        """Log message"""
        timestamp = time.strftime("%H:%M:%S")
        log_line = f"[{timestamp}] {message}"
        self._log_lines.append(log_line)
        print(log_line)
        if self._on_log:
            self._on_log(log_line)

    def configure_only(
        self,
        on_progress: Callable[[ConfigProgress], None] = None,
        on_log: Callable[[str], None] = None,
    ) -> ConfigResult:
        """US-05: Configure only, do not start gateway"""
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
                    error_message="未找到 OpenClaw 命令",
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

        except Exception as e:
            self._log(f"Exception: {type(e).__name__}: {e}")
            import traceback
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
        """US-06: Start gateway and open browser only"""
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

            # Note: Browser is NOT opened automatically anymore
            # User will manually click "Open WebChat" button
            return ConfigResult(
                status=ConfigStatus.COMPLETED,
                service_status=ServiceStatus.RUNNING,
                webchat_url=webui_url or "http://127.0.0.1:18789",
                message='网关服务已启动，请点击"打开 WebChat"按钮',
                browser_opened=False,  # Not auto-opened
                log_lines=self._log_lines.copy(),
            )

        except Exception as e:
            self._log(f"Exception: {type(e).__name__}: {e}")
            import traceback
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
        """Quick start - skip config, directly start gateway"""
        return self.startup_only(on_progress=on_progress, on_log=on_log)

    def setup_and_start(
        self,
        on_progress: Callable[[ConfigProgress], None] = None,
    ) -> ConfigResult:
        """Legacy: Setup and start service (config + startup)"""
        # First configure
        config_result = self.configure_only(on_progress=on_progress)
        if config_result.status != ConfigStatus.COMPLETED:
            return config_result
        
        # Then startup
        return self.startup_only(on_progress=on_progress)

    def _check_openclaw_installed(self) -> bool:
        """Check if openclaw command is available"""
        try:
            result = self._run_openclaw_command("--version")
            return result.returncode == 0
        except Exception:
            return False

    def _setup_default_config(self) -> bool:
        """Setup default configuration"""
        try:
            self._log("Setting default config...")
            configs = [
                ("gateway.mode", "local"),
                ("gateway.bind", "loopback"),
                ("gateway.port", "18789"),
                ("gateway.allowUnconfigured", "true"),
            ]
            
            for key, value in configs:
                try:
                    result = self._run_openclaw_command(f'config set {key} "{value}"')
                    if result.returncode == 0:
                        self._log(f"Set {key}={value} OK")
                    else:
                        self._log(f"Set {key} failed: rc={result.returncode}")
                        if result.stderr:
                            self._log(f"  stderr: {result.stderr[:200]}")
                except Exception as e:
                    self._log(f"Set {key} error: {e}")
                    continue
            
            self._log("Running onboard...")
            try:
                cmd = 'onboard --non-interactive --accept-risk --mode local --skip-skills --skip-health --no-install-daemon'
                result = self._run_openclaw_command(cmd)
                self._log(f"onboard return code: {result.returncode}")
                if result.stdout:
                    self._log(f"onboard stdout: {result.stdout[:500]}")
                if result.stderr:
                    self._log(f"onboard stderr: {result.stderr[:500]}")
            except Exception as e:
                self._log(f"onboard error: {e}")
            
            return True
            
        except Exception as e:
            self._log(f"Setup config error: {e}")
            return False

    def _start_gateway(self) -> bool:
        """Start OpenClaw gateway service"""
        try:
            self._log("Checking if gateway already running...")
            for i in range(3):
                try:
                    result = self._run_openclaw_command("gateway status")
                    if result.returncode == 0 and "running" in result.stdout.lower():
                        self._log("Gateway already running")
                        return True
                except Exception as e:
                    self._log(f"Check status error: {e}")
                time.sleep(0.5)
            
            if self._is_port_open(18789):
                self._log("Port occupied, trying to release...")
                self._kill_port_process(18789)
                time.sleep(1)
            
            # All platforms: use foreground mode (no admin required)
            os_type = platform.system().lower()
            self._log(f"Detected OS: {os_type}")
            self._log("Starting gateway in foreground mode...")
            
            # Use 'openclaw gateway' (without 'start') for foreground mode
            # This doesn't require admin privileges or scheduled task on any OS
            popen_kwargs = {
                "shell": True,
                "stdout": subprocess.PIPE,
                "stderr": subprocess.PIPE,
                "text": True,
            }
            
            if os_type == "windows":
                # Windows needs PowerShell wrapper and creation flags
                full_command = f'powershell -WindowStyle Hidden -NoProfile -ExecutionPolicy Bypass -Command "openclaw gateway"'
                popen_kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
            else:
                # Linux/macOS: run directly
                full_command = "openclaw gateway"
            
            self._log(f"Execute: {full_command[:80]}...")
            
            # Use Popen to run in background, not blocking
            self.process = subprocess.Popen(full_command, **popen_kwargs)
            
            self._log(f"Gateway process started with PID: {self.process.pid}")
            
            self._log("Waiting for service initialization...")
            time.sleep(3)
            
            self._log("Waiting for gateway ready...")
            for i in range(20):  # Wait up to 20 seconds
                if self.is_cancelled:
                    return False
                
                time.sleep(1)
                
                # Check if process is still running (all platforms foreground mode)
                if self.process:
                    if self.process.poll() is not None:
                        # Process exited
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
                
                # Check status via command
                try:
                    result = self._run_openclaw_command("gateway status")
                    self._log(f"Status check #{i+1}: rc={result.returncode}")
                    if result.returncode == 0:
                        if "running" in result.stdout.lower():
                            self._log("Gateway ready")
                            return True
                        else:
                            self._log(f"Status output: {result.stdout[:200]}")
                except Exception as e:
                    self._log(f"Status check error: {e}")
                
                # Check if port is open
                if self._is_port_open(18789):
                    self._log("Port 18789 is open, gateway is ready")
                    return True
                
                if (i + 1) % 5 == 0:
                    self._log(f"Waiting for gateway... ({i+1}/20s)")

            self._log("Gateway start timeout")
            return False

        except Exception as e:
            self._log(f"Start gateway error: {type(e).__name__}: {e}")
            import traceback
            self._log(f"Traceback: {traceback.format_exc()}")
            return False

    def _run_openclaw_command(self, command: str) -> subprocess.CompletedProcess:
        """Execute openclaw command using PowerShell with hidden window"""
        import os
        
        os_type = platform.system().lower()
        env = os.environ.copy()
        
        if os_type == "windows":
            ps_command = f'openclaw {command}'
            full_command = f'powershell -WindowStyle Hidden -NoProfile -ExecutionPolicy Bypass -Command "{ps_command}"'
            
            self._log(f"Execute: {full_command[:100]}...")
            
            result = subprocess.run(
                full_command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=30,
                env=env,
            )
            
            return result
        else:
            # Linux/macOS: ensure ~/.local/bin is in PATH because openclaw may be installed there
            home = os.path.expanduser("~")
            local_bin = os.path.join(home, ".local", "bin")
            env["PATH"] = f"{local_bin}:{env.get('PATH', '')}"
            
            result = subprocess.run(
                f"openclaw {command}",
                shell=True,
                capture_output=True,
                text=True,
                timeout=30,
                env=env,
            )
            return result

    def _kill_port_process(self, port: int):
        """Kill process occupying port"""
        try:
            os_type = platform.system().lower()
            if os_type == "windows":
                result = subprocess.run(
                    f'netstat -ano | findstr :{port}',
                    shell=True,
                    capture_output=True,
                    text=True
                )
                if result.returncode == 0 and result.stdout:
                    lines = result.stdout.strip().split('\n')
                    for line in lines:
                        parts = line.strip().split()
                        if len(parts) >= 5:
                            pid = parts[-1]
                            try:
                                subprocess.run(
                                    f'taskkill /PID {pid} /F',
                                    shell=True,
                                    capture_output=True
                                )
                                self._log(f"Killed process PID: {pid}")
                            except Exception as e:
                                self._log(f"Kill process error: {e}")
            else:
                result = subprocess.run(
                    f'lsof -ti:{port}',
                    shell=True,
                    capture_output=True,
                    text=True
                )
                if result.returncode == 0 and result.stdout:
                    pids = result.stdout.strip().split('\n')
                    for pid in pids:
                        try:
                            subprocess.run(
                                f'kill -9 {pid}',
                                shell=True,
                                capture_output=True
                            )
                            self._log(f"Killed process PID: {pid}")
                        except Exception as e:
                            self._log(f"Kill process error: {e}")
        except Exception as e:
            self._log(f"Release port error: {e}")

    def _is_port_open(self, port: int) -> bool:
        """Check if port is open"""
        import socket
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(2)
            result = sock.connect_ex(("localhost", port))
            sock.close()
            return result == 0
        except Exception:
            return False

    def _health_check(self) -> bool:
        """Health check - check port 18789"""
        return self._is_port_open(18789)

    def _get_webui_url(self) -> str:
        """Get WebUI URL using dashboard command"""
        for attempt in range(10):
            try:
                self._log(f"Getting WebUI URL (attempt {attempt + 1}/10)...")
                
                result = self._run_openclaw_command("dashboard --no-open")
                
                output = result.stdout + result.stderr
                self._log(f"dashboard output: {output[:300]}")
                
                if result.returncode == 0:
                    url_match = re.search(r'https?://[^\s\n\r]+', output)
                    if url_match:
                        url = url_match.group(0)
                        if "token=" in url or "18789" in url:
                            self._log(f"Got URL: {url}")
                            return url
                else:
                    self._log(f"dashboard return code: {result.returncode}")
                    
            except Exception as e:
                self._log(f"Get URL error: {type(e).__name__}: {e}")
            
            if attempt < 9:
                time.sleep(1)
        
        self._log("Failed to get URL from dashboard, using default")
        return "http://127.0.0.1:18789"

    def _open_browser(self, url: str) -> bool:
        """Open system default browser"""
        self._log(f"Opening browser: {url}")
        
        try:
            webbrowser.open(url, new=2)
            self._log("webbrowser.open success")
            return True
        except Exception as e:
            self._log(f"webbrowser.open failed: {e}")
        
        if platform.system().lower() == "windows":
            try:
                result = subprocess.run(
                    f'start "" "{url}"',
                    shell=True,
                    capture_output=True,
                    timeout=5,
                )
                if result.returncode == 0:
                    self._log("start command success")
                    return True
            except Exception as e:
                self._log(f"start command failed: {e}")
        
        try:
            if platform.system().lower() == "windows":
                os.system(f'start "" "{url}"')
            elif platform.system().lower() == "darwin":
                os.system(f'open "{url}"')
            else:
                os.system(f'xdg-open "{url}"')
            self._log("os.system executed")
            return True
        except Exception as e:
            self._log(f"os.system failed: {e}")
        
        return False

    def _stop_gateway(self):
        """Stop gateway service"""
        try:
            self._log("Stopping gateway...")
            
            # All platforms use foreground mode now: terminate the process we started
            if self.process and self.process.poll() is None:
                self._log(f"Terminating gateway process (PID: {self.process.pid})")
                self.process.terminate()
                try:
                    self.process.wait(timeout=5)
                except:
                    self._log("Force killing gateway process...")
                    self.process.kill()
            
            # Also try command-line stop and release port 18789
            try:
                self._run_openclaw_command("gateway stop")
            except Exception as e:
                self._log(f"gateway stop command error: {e}")
            
            self._kill_port_process(18789)
        except Exception as e:
            self._log(f"Stop gateway error: {e}")

    def stop(self):
        """Stop service (external call)"""
        self.is_cancelled = True
        self._stop_gateway()

    def is_running(self) -> bool:
        """Check if service is running"""
        return self.process is not None and self.process.poll() is None
