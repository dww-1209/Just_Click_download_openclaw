"""重装前清理 Adapter

职责: 在重装(覆盖安装)前清理旧的 OpenClaw 部署,把"停 Gateway、删源码/配置目录、
卸 npm 包"这类系统调用封装在 Adapter 层,避免 services 直接 import subprocess。

设计要点:
- 本 adapter 是"尽力而为"语义: 任何子步骤失败都吞掉异常,继续做下一步。
  目的是让重装流程不会因为旧安装残留状态(进程僵死、npm 包损坏)被卡住,
  让用户最终能进入安装阶段。
- 调用方(services 层 ReinstallWorker)不需要看到具体异常,只通过 on_log
  接收人类可读日志。
- **不要调用 openclaw CLI 来停 Gateway**: 该 CLI 是 Node.js wrapper,冷启动需要
  ~10-20s,在卸载/重装场景里会让 UI 看起来卡死;且启动 Node 时还可能再生成
  ~/.openclaw 目录,导致随后 force_rmtree 还得再删一遍。改为直接 kill 占用
  18789 端口的进程,这是 Gateway 唯一占用的资源。
"""

from __future__ import annotations

import os
import subprocess
from typing import Callable, Optional

from src.models.constants import DEFAULT_GATEWAY_PORT, is_windows
from src.models.utils import force_rmtree, kill_port_process, windows_hidden_subprocess_kwargs

# 单步骤超时(秒): 偏短即可,因为旧 Gateway 是本机进程、npm uninstall 是本地操作
_STEP_TIMEOUT = 30


def _quiet_run(cmd: list[str]) -> None:
    """运行子命令,完全吞掉所有错误,Windows 上隐藏控制台窗口。

    用于尽力而为的清理动作: 找不到 cmd / 子进程崩溃 / 超时 都不影响主流程。
    """
    kwargs = {
        "shell": False,
        "capture_output": True,
        "timeout": _STEP_TIMEOUT,
    }
    # Windows 子进程默认会闪一个黑色 cmd 窗口,GUI 程序里非常碍眼。
    kwargs.update(windows_hidden_subprocess_kwargs())
    try:
        subprocess.run(cmd, **kwargs)
    except (OSError, subprocess.SubprocessError):
        pass


def cleanup_for_reinstall(on_log: Optional[Callable[[str], None]] = None) -> bool:
    """执行重装前的旧安装清理。

    步骤:
    1. 停止 Gateway: 直接 kill 占用 18789 端口的进程,不调用 openclaw CLI。
    2. 删除源码目录 ``~/openclaw-cn`` 与配置目录 ``~/.openclaw``。
    3. 卸载历史遗留的全局 npm 包。

    所有步骤都是尽力而为,任何一步失败都不会中断流程。

    Args:
        on_log: 可选的人类可读日志回调,会输出每个步骤的进展。

    Returns:
        始终返回 True。
    """
    log = on_log or (lambda _msg: None)

    log("正在清理旧安装...")

    # 1) 停 Gateway: 直接 kill 端口占用进程
    # Gateway 唯一占用的就是 18789 端口。跑或不跑都不影响清理流程。
    log("正在停止 Gateway 服务...")
    killed = kill_port_process(DEFAULT_GATEWAY_PORT, log)
    if killed:
        log(f"Gateway 已停止({killed} 个进程)")
    else:
        # 把"未运行"说得像正常结果,不要让用户以为卡住了
        log("Gateway 未运行,无需停止")

    # 2) 删源码 + 配置
    log("正在删除旧文件...")
    for d in (os.path.expanduser("~/openclaw-cn"), os.path.expanduser("~/.openclaw")):
        if os.path.exists(d):
            if force_rmtree(d, log):
                log(f"已删除: {d}")
            else:
                log(f"删除失败(将继续): {d}")
    log("旧文件已处理")

    # 3) 删除命令包装器
    # cleanup_for_reinstall 之前漏掉了这一步,导致重装后 wrapper 还在,用户
    # 终端里 openclaw 命令仍然可用(指向已经空了的 ~/openclaw-cn,但 wrapper 本身
    # 没删)。卸载器(uninstall)的步骤 4 有删 wrapper,这里也对齐。
    if is_windows():
        wrapper_dir = os.path.join(os.path.expanduser("~"), r"AppData\Roaming\npm")
        for w in ("openclaw.cmd", "openclaw-cn.cmd"):
            wpath = os.path.join(wrapper_dir, w)
            if os.path.exists(wpath):
                try:
                    os.remove(wpath)
                    log(f"已删除命令: {wpath}")
                except OSError:
                    log(f"删除命令失败(将继续): {wpath}")
    else:
        wrapper_dir = os.path.join(os.path.expanduser("~"), ".local", "bin")
        for w in ("openclaw", "openclaw-cn", "git"):
            wpath = os.path.join(wrapper_dir, w)
            if os.path.exists(wpath):
                try:
                    os.remove(wpath)
                    log(f"已删除命令: {wpath}")
                except OSError:
                    log(f"删除命令失败(将继续): {wpath}")

    # 4) 卸全局 npm 包(兼容旧版 npm install -g 的安装方式)
    log("正在清理 npm 包...")
    npm_cmd = "npm.cmd" if is_windows() else "npm"
    for pkg in ("openclaw-cn", "openclaw"):
        _quiet_run([npm_cmd, "uninstall", "-g", pkg])
    log("npm 包已清理")

    log("旧安装清理完成,开始安装...")
    return True
