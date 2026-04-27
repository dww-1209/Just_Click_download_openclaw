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

    def _resolve_openclaw_cmd(self) -> str:
        """检测系统中可用的 openclaw 命令（优先 openclaw-cn，fallback openclaw）"""
        import shutil
        os_type = platform.system().lower()
        if os_type == "windows":
            # Windows 下使用 where 更可靠（能处理 %APPDATA% 等环境变量展开）
            for cmd in ["openclaw-cn", "openclaw"]:
                result = subprocess.run(
                    f"where {cmd}",
                    shell=True,
                    capture_output=True,
                    timeout=5,
                )
                if result.returncode == 0:
                    return cmd
        else:
            for cmd in ["openclaw-cn", "openclaw"]:
                if shutil.which(cmd):
                    return cmd
        return "openclaw"

    def _check_openclaw_installed(self) -> bool:
        """Check if openclaw command is available"""
        try:
            cmd = self._resolve_openclaw_cmd()
            os_type = platform.system().lower()
            if os_type == "windows":
                # Windows: 直接用 where 检测命令是否存在，避免某些 CLI 不支持 --version
                result = subprocess.run(
                    f"where {cmd}",
                    shell=True,
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
                return result.returncode == 0
            else:
                # Linux/macOS: 使用 which 检测
                import os
                env = os.environ.copy()
                home = os.path.expanduser("~")
                local_bin = os.path.join(home, ".local", "bin")
                env["PATH"] = f"{local_bin}:{env.get('PATH', '')}"
                result = subprocess.run(
                    ["which", cmd],
                    capture_output=True,
                    text=True,
                    timeout=5,
                    env=env,
                )
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
                # openclaw-cn 不支持 allowUnconfigured，由 onboard 完成初始化
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
                cmd = 'onboard --non-interactive --accept-risk --mode local --skip-skills --skip-health --no-install-daemon --node-manager pnpm --skip-channels'
                result = self._run_openclaw_command(cmd)
                self._log(f"onboard return code: {result.returncode}")
                if result.stdout:
                    self._log(f"onboard stdout: {result.stdout[:500]}")
                if result.stderr:
                    self._log(f"onboard stderr: {result.stderr[:500]}")
            except Exception as e:
                self._log(f"onboard error: {e}")
            
            self._inject_browser_config()
            
            return True
            
        except Exception as e:
            self._log(f"Setup config error: {e}")
            return False

    def _inject_browser_config(self) -> None:
        """Inject browser default config into ~/.openclaw/openclaw.json"""
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
            
            cmd = self._resolve_openclaw_cmd()
            if os_type == "windows":
                # Windows needs PowerShell wrapper and creation flags
                full_command = f'powershell -WindowStyle Hidden -NoProfile -ExecutionPolicy Bypass -Command "{cmd} gateway"'
                popen_kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
            else:
                # Linux/macOS: run directly
                full_command = f"{cmd} gateway"
            
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
        import shutil
        
        os_type = platform.system().lower()
        env = os.environ.copy()
        cmd = self._resolve_openclaw_cmd()
        
        # 过滤掉包含非 ASCII 字符的环境变量，避免 Node.js ByteString 错误
        clean_env = {}
        for k, v in env.items():
            try:
                v.encode("ascii")
                clean_env[k] = v
            except UnicodeEncodeError:
                # 非 ASCII 值跳过，避免传递给 Node.js 子进程
                pass
        env = clean_env
        
        # 如果全局命令找不到，但本地项目存在，使用项目内 pnpm
        local_project = Path(os.path.expanduser("~")) / "openclaw-cn"
        local_fallback = (
            cmd == "openclaw"
            and not shutil.which("openclaw")
            and not shutil.which("openclaw-cn")
            and local_project.exists()
            and (local_project / "package.json").exists()
        )
        
        if os_type == "windows":
            if local_fallback:
                ps_command = f'cd "{local_project}"; pnpm openclaw {command}'
            else:
                ps_command = f'{cmd} {command}'
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
            
            if local_fallback:
                full_command = f'cd "{local_project}" && pnpm openclaw {command}'
            else:
                full_command = f"{cmd} {command}"
            
            result = subprocess.run(
                full_command,
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

    def read_existing_provider_config(self) -> dict:
        """读取已有的 Provider 配置
        
        从两个来源读取：
        1. ~/.openclaw/openclaw.json — env 变量、默认模型、providers 配置
        2. ~/.openclaw/agents/main/agent/auth-profiles.json — auth profile 中的 API Key
        
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

                # env 中的 API Key
                env = config.get("env", {})
                if isinstance(env, dict):
                    result["env"] = {k: v for k, v in env.items() if "_API_KEY" in k}

                # 默认模型
                agents = config.get("agents", {})
                defaults = agents.get("defaults", {})
                model = defaults.get("model", {})
                if isinstance(model, dict):
                    result["primary_model"] = model.get("primary", "")
                    result["fallback_models"] = model.get("fallbacks", [])
                elif isinstance(model, str):
                    result["primary_model"] = model

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
        providers_config: dict,
        global_default_model: str,
        fallback_models: Optional[list] = None,
        on_progress: Optional[Callable] = None,
        on_log: Optional[Callable[[str], None]] = None,
    ) -> bool:
        """配置 AI Provider：写入 env 变量和默认模型
        
        Args:
            providers_config: {vendor_id: {api_key, env_var, fallback_env_var, model, base_url, auth_choice, key_type}}
            global_default_model: 全局默认 model ref
            on_progress: 进度回调
            on_log: 日志回调
        
        Returns:
            bool: 是否全部成功
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
                on_progress({
                    "percent": int(10 + 80 * idx / total),
                    "message": f"正在配置 {vendor_id}...",
                })

            # 1. 设置主 env 变量
            try:
                cmd = f'config set env.{env_var} "{api_key}"'
                result = self._run_openclaw_command(cmd)
                if result.returncode == 0:
                    self._log(f"  Set env.{env_var} OK")
                else:
                    self._log(f"  Set env.{env_var} failed: rc={result.returncode}")
                    if result.stderr:
                        self._log(f"    stderr: {result.stderr[:200]}")
                    all_ok = False
            except Exception as e:
                self._log(f"  Set env.{env_var} error: {e}")
                all_ok = False

            # 2. 如有 fallback_env_var，也设置（用于兼容）
            if fallback_env_var and fallback_env_var != env_var:
                try:
                    cmd = f'config set env.{fallback_env_var} "{api_key}"'
                    result = self._run_openclaw_command(cmd)
                    if result.returncode == 0:
                        self._log(f"  Set env.{fallback_env_var} OK")
                except Exception as e:
                    self._log(f"  Set env.{fallback_env_var} error: {e}")

            # 3. 如有 auth_choice，执行 onboard（设置 provider baseUrl 等）
            if auth_choice:
                try:
                    onboard_cmd = (
                        f'onboard --auth-choice {auth_choice} '
                        f'--non-interactive --accept-risk --mode local '
                        f'--skip-skills --skip-health --no-install-daemon '
                        f'--node-manager pnpm --skip-channels'
                    )
                    result = self._run_openclaw_command(onboard_cmd)
                    self._log(f"  onboard return code: {result.returncode}")
                    if result.stdout:
                        self._log(f"  onboard stdout: {result.stdout[:300]}")
                except Exception as e:
                    self._log(f"  onboard error: {e}")

        # 4. 设置全局默认模型
        if global_default_model:
            self._log(f"Setting global default model: {global_default_model}")
            try:
                cmd = f'config set agents.defaults.model.primary "{global_default_model}"'
                result = self._run_openclaw_command(cmd)
                if result.returncode == 0:
                    self._log("  Set default model OK")
                else:
                    self._log(f"  Set default model failed: rc={result.returncode}")
                    if result.stderr:
                        self._log(f"    stderr: {result.stderr[:200]}")
                    all_ok = False
            except Exception as e:
                self._log(f"  Set default model error: {e}")
                all_ok = False

        # 5. 设置 fallback models
        if fallback_models:
            self._log(f"Setting fallback models: {fallback_models}")
            try:
                self._set_fallback_models(fallback_models)
                self._log("  Set fallback models OK")
            except Exception as e:
                self._log(f"  Set fallback models error: {e}")
                all_ok = False

        # 6. 写入自定义 provider 配置（无 onboard 的 provider，如 DashScope）
        for config_key, cfg in providers_config.items():
            auth_choice = cfg.get("auth_choice", "")
            base_url = cfg.get("base_url", "")
            if not auth_choice and base_url:
                try:
                    self._configure_custom_provider(config_key, cfg)
                except Exception as e:
                    self._log(f"  Configure custom provider {config_key} error: {e}")
                    all_ok = False

        self._on_log = None
        return all_ok

    def _set_fallback_models(self, fallback_models: list) -> None:
        """直接修改 openclaw.json 写入 fallback models"""
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
            self._log(f"  Failed to read config for fallbacks: {e}")
            config = {}

        # Ensure agents.defaults.model structure exists
        if "agents" not in config:
            config["agents"] = {}
        if "defaults" not in config["agents"]:
            config["agents"]["defaults"] = {}
        if "model" not in config["agents"]["defaults"]:
            config["agents"]["defaults"]["model"] = {}

        model_cfg = config["agents"]["defaults"]["model"]
        # If model is a string, convert to dict
        if isinstance(model_cfg, str):
            model_cfg = {"primary": model_cfg}
            config["agents"]["defaults"]["model"] = model_cfg

        model_cfg["fallbacks"] = fallback_models

        try:
            os.makedirs(os.path.dirname(config_path), exist_ok=True)
            with open(config_path, "w", encoding="utf-8") as f:
                json.dump(config, f, indent=2, ensure_ascii=False)
        except OSError as e:
            self._log(f"  Failed to write fallbacks: {e}")
            raise

    def _configure_custom_provider(self, config_key: str, cfg: dict) -> None:
        """直接修改 openclaw.json 写入自定义 provider 配置（如 DashScope）"""
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
        """将程序内部的 vendor_id 映射到 openclaw 的 provider ID"""
        if vendor_id == "kimi":
            return "kimi-coding" if key_type == "coding" else "moonshot"
        if vendor_id == "aliyun":
            return "aliyun-coding" if key_type == "coding" else "dashscope"
        if vendor_id == "volcengine":
            return "volcengine-plan" if key_type == "coding" else "volcengine"
        return vendor_id

    def stop(self):
        """Stop service (external call)"""
        self.is_cancelled = True
        self._stop_gateway()

    def is_running(self) -> bool:
        """Check if service is running"""
        return self.process is not None and self.process.poll() is None

    def uninstall(self, on_log: Optional[Callable[[str], None]] = None) -> bool:
        """完全卸载 OpenClaw：停止服务、删除目录、卸载 npm 包、清理命令包装器"""
        import shutil
        import platform

        all_ok = True
        os_type = platform.system().lower()
        home = os.path.expanduser("~")

        # 1. 停止 Gateway
        try:
            self._stop_gateway()
            if on_log:
                on_log("已停止 OpenClaw Gateway")
        except Exception as e:
            if on_log:
                on_log(f"停止 Gateway 失败（可能未运行）: {e}")

        # 2. 删除本地构建目录
        dirs_to_remove = [
            os.path.join(home, "openclaw-cn"),
            os.path.join(home, ".openclaw"),
        ]
        for d in dirs_to_remove:
            if os.path.exists(d):
                try:
                    shutil.rmtree(d, onerror=self._remove_readonly)
                    if on_log:
                        on_log(f"已删除: {d}")
                except Exception as e:
                    if on_log:
                        on_log(f"删除 {d} 失败: {e}")
                    all_ok = False

        # 3. 卸载 npm 全局包（兼容旧版直接 npm install -g 的情况）
        for pkg in ["openclaw-cn", "openclaw"]:
            try:
                result = subprocess.run(
                    f'npm uninstall -g {pkg}',
                    shell=True, capture_output=True, text=True
                )
                if result.returncode == 0:
                    if on_log:
                        on_log(f"已卸载 npm 包: {pkg}")
                elif on_log:
                    on_log(f"npm 包 {pkg} 可能未全局安装，跳过")
            except Exception as e:
                if on_log:
                    on_log(f"卸载 {pkg} 出错: {e}")

        # 4. 删除命令包装器
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
                except Exception as e:
                    if on_log:
                        on_log(f"删除 {wpath} 失败: {e}")

        if on_log:
            on_log("OpenClaw 卸载完成")
        return all_ok

    @staticmethod
    def _remove_readonly(func, path, _):
        import stat
        os.chmod(path, stat.S_IWRITE)
        func(path)
