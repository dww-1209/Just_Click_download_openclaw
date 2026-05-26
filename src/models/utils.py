"""模型层公共工具函数

职责：提供纯数据/工具辅助函数，供 models、core、adapters 等各层共享使用。

设计原则：
- 本层只包含不依赖任何业务逻辑和系统调用的纯工具函数。
- 若函数涉及文件系统操作但属于通用辅助（如 remove_readonly），也可放在此处。
"""

from __future__ import annotations

import os
import shutil
import stat
import subprocess
import sys
import tarfile
from pathlib import Path
from typing import Callable, Any, Optional

from src.models.constants import is_windows, TIMEOUT_SHORT_CMD


def windows_hidden_subprocess_kwargs() -> dict:
    """返回用于隐藏控制台窗口的 subprocess 关键字参数字典(仅 Windows 有效)。

    Windows GUI 程序(无 console)通过 subprocess 调用 cmd/where/taskkill 等
    控制台程序时，操作系统会创建一个**新的**控制台窗口短暂闪烁。需要同时:
    - STARTUPINFO + STARTF_USESHOWWINDOW + SW_HIDE: 即使被显示也立刻隐藏
    - CREATE_NO_WINDOW: 直接告诉系统不要创建新 console

    其他平台返回空 dict, 调用方可以无脑 ** 展开:
        subprocess.run(cmd, **windows_hidden_subprocess_kwargs(), capture_output=True, ...)

    Returns:
        dict: Windows 上含 startupinfo / creationflags 两个键; 其他平台为空 dict。
    """
    if not is_windows():
        return {}

    startupinfo = subprocess.STARTUPINFO()
    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startupinfo.wShowWindow = subprocess.SW_HIDE
    return {
        "startupinfo": startupinfo,
        "creationflags": subprocess.CREATE_NO_WINDOW,
    }


def kill_port_process(port: int, on_log: Callable[[str], None] | None = None) -> int:
    """释放被占用的本地端口(用于卸载/重装场景终结 Gateway 进程)。

    与 OpenClawManager._kill_port_process 等价,但作为独立函数提供给
    cleanup_reinstall 等无 manager 实例的场景使用。隐藏子进程窗口。

    Args:
        port: 端口号 (1-65535)。
        on_log: 可选的日志回调。

    Returns:
        int: 被结束的进程数量(如果检测/解析失败返回 0)。
    """
    try:
        port = int(port)
    except (TypeError, ValueError):
        return 0
    if not (1 <= port <= 65535):
        return 0

    hidden = windows_hidden_subprocess_kwargs()
    killed = 0

    if is_windows():
        try:
            result = subprocess.run(
                ["netstat", "-ano"],
                capture_output=True, text=True, timeout=15,
                **hidden,
            )
        except (OSError, subprocess.SubprocessError):
            return 0
        if result.returncode != 0 or not result.stdout:
            return 0

        killed_pids: set[str] = set()
        for line in result.stdout.splitlines():
            fields = line.split()
            if len(fields) < 4:
                continue
            proto = fields[0].upper()
            if proto not in ("TCP", "UDP", "TCP6", "UDP6"):
                continue
            local_addr = fields[1]
            if not (local_addr.endswith(f":{port}") or local_addr.endswith(f"]:{port}")):
                continue
            pid = fields[-1]
            if not pid.isdigit() or pid in killed_pids:
                continue
            killed_pids.add(pid)
            try:
                subprocess.run(
                    ["taskkill", "/PID", pid, "/F", "/T"],
                    capture_output=True, timeout=10, **hidden,
                )
                killed += 1
                if on_log:
                    on_log(f"已终止占用端口 {port} 的进程 PID={pid}")
            except (OSError, subprocess.SubprocessError):
                pass
    else:
        try:
            result = subprocess.run(
                ["lsof", "-ti", f":{port}"],
                capture_output=True, text=True, timeout=15,
            )
        except (OSError, subprocess.SubprocessError):
            return 0
        if result.returncode != 0 or not result.stdout:
            return 0

        for pid in result.stdout.strip().splitlines():
            pid = pid.strip()
            if not pid.isdigit():
                continue
            try:
                subprocess.run(["kill", "-9", pid], capture_output=True, timeout=10)
                killed += 1
                if on_log:
                    on_log(f"已终止占用端口 {port} 的进程 PID={pid}")
            except (OSError, subprocess.SubprocessError):
                pass

    return killed


def force_rmtree(
    path: str | Path,
    on_log: Callable[[str], None] | None = None,
    wait: bool = False,
) -> bool:
    """强制删除目录树。

    平台分流:

    - **Mac**(快路径,APFS/ext4 友好 + 无 Defender):直接 chmod +w 后
      逐文件 unlink/rmdir,几秒删完 100k 文件,UI 立刻关窗。`wait` 参数在这条
      路径上几乎无意义,因为同步删本来就快。极少数文件锁场景才走 rename 兜底。

    - **Windows**(rename 隔离 + 后台清理):
      - **wait=False(默认,安装/重装路径用)**:rename 优先 + 后台 daemon 清残渣。
        rename 完(<100ms)就返回 True,daemon 慢慢删。卸载场景**不要用这个**——
        用户看到"已卸载"就关窗,daemon 会被中断,残渣留在磁盘。
      - **wait=True(卸载路径用)**:同步等到真删干净才返回。先 rename 挪开
        避免占用句柄,然后前台 robocopy /MIR 真删 + 心跳输出。耗时可能数分钟。

    历史 bug(2026-05 修): Windows wait=False 模式下卸载器调用,导致用户秒关窗
    → daemon 中断 → 用户重新打开卸载器,cleanup_orphan_residues 又检测到残渣
    → 又跑卸载逻辑 → 又秒关 → 永远清不完的死循环。Windows 卸载场景必须 wait=True。

    历史 bug(2026-05 修): Mac 上误用 Windows 的 rename + 同步等待路径,导致卸载
    出现"卸载部分完成,请你手动清理"假阳性(rename 后 _background_purge_sync 在
    Mac 上走 _rmtree_skip_locked 同步删,边删边检测路径存在,概率性卡住)。
    Mac 必须走"直接逐文件删"的早期快路径。

    Args:
        path: 要删除的目录路径。
        on_log: 可选的日志回调。
        wait: 仅 Windows 有效。True 时同步等待清理完成;False 时 rename + 后台 daemon。

    Returns:
        True 表示已清理完成或已隔离;False 表示彻底失败。
    """
    path_str = str(path)
    if not os.path.exists(path_str):
        return True

    import time as _time
    import threading as _threading

    # ── Mac 快路径 ──────────────────────────────────────────────
    # APFS / ext4 + 没有 Defender 实时扫描,直接逐文件删 100k 文件几秒搞定,
    # 不需要 rename 隔离这一圈。早期版本就是这套(commit 4d0a747 之前),
    # 卸载体验"秒退窗"。Windows 那套 rename + robocopy + daemon 是为了绕开
    # 文件锁/Defender 扫描墙,Mac 上属于纯拖累。
    #
    # rename 隔离机制只有在文件锁住、daemon 中断风险高时才有意义,Mac 都没有。
    # 同步删完 → 用户看到"已彻底清理"立刻关窗,不会出现"卸载部分完成"假阳性。
    if not is_windows():
        # u+rwx 同时加读/写/执行三个位:
        # - 写位: pnpm 依赖目录有时带只读位,不去掉 unlink/rmdir 会失败
        # - 执行位: 关键!_rmtree_skip_locked 内部用 os.walk 遍历,目录缺 x 位会
        #   直接进不去(POSIX 语义),连内容都列不出来,fallback chmod 永远不触发。
        #   这就是上次"卸载部分完成"的根因——上一版用 0o600 (S_IRWUSR|S_IWUSR)
        #   清属性,把目录的 x 位也清了,从此残渣永远清不掉。
        try:
            subprocess.run(
                ["chmod", "-R", "u+rwx", path_str],
                capture_output=True, timeout=30,
            )
        except (OSError, subprocess.SubprocessError):
            pass

        _rmtree_skip_locked(path_str, on_log)
        if not os.path.exists(path_str):
            if on_log:
                on_log(f"已删除: {path_str}")
            return True

        # 极少进到这里(Mac 文件锁罕见),兜底 rename + rm -rf 残渣
        try:
            residue_path = f"{path_str}._residue.{int(_time.time() * 1000)}"
            os.rename(path_str, residue_path)
            if on_log:
                on_log(f"已隔离剩余残留: {os.path.basename(residue_path)}")
            if wait:
                subprocess.run(["rm", "-rf", residue_path],
                               capture_output=True, timeout=300)
            else:
                _threading.Thread(
                    target=lambda: subprocess.run(
                        ["rm", "-rf", residue_path], capture_output=True, timeout=300),
                    daemon=True, name="force_rmtree_bg_unix",
                ).start()
            return True
        except OSError:
            if on_log:
                on_log(f"删除 {path_str} 失败: 目录被句柄占用")
            return False

    # ── Windows 路径(rename 优先 + 后台/同步清理)──────────────────
    # Windows 上必须 rename 隔离(daemon 中断会留死循环残渣 + Defender 串行删慢),
    # 详见上方 docstring 的"历史 bug(2026-05 修)"段落。
    residue_path = f"{path_str}._residue.{int(_time.time() * 1000)}"
    try:
        os.rename(path_str, residue_path)
        if on_log:
            if wait:
                on_log(f"已隔离: {os.path.basename(residue_path)},正在彻底清理...")
            else:
                on_log(f"已隔离残留(后台清理中): {os.path.basename(residue_path)}")

        if wait:
            # 同步清残渣,直到真删完才返回。心跳由 _background_purge_sync 内部输出。
            _background_purge_sync(residue_path, on_log)
            if not os.path.exists(residue_path):
                if on_log:
                    on_log(f"已彻底清理: {os.path.basename(residue_path)}")
                return True
            else:
                if on_log:
                    on_log(f"清理未完全(部分文件被句柄占用): {os.path.basename(residue_path)}")
                return False
        else:
            # 后台 daemon 线程清残渣,不阻塞主流程。
            # daemon=True: 安装器进程退出时线程自动结束,不会成为僵尸。
            # 没清完的 .residue.* 留在磁盘上,下次 cleanup_for_reinstall 会一并扫掉。
            _threading.Thread(
                target=_background_purge,
                args=(residue_path,),
                daemon=True,
                name="force_rmtree_bg",
            ).start()
            return True
    except OSError:
        # rename 失败(目录被锁),退化为同步逐文件删
        pass

    if on_log:
        on_log(f"目录被占用,改为逐文件删除: {path_str}")

    # 第二招: 同步逐文件删。这是 fallback,大多数情况进不到这里。
    # 不再做 attrib /S /D —— 那是浪费时间(扫一遍 + 真删一遍 = 扫两遍),
    # _rmtree_skip_locked 内层有 chmod+retry 兜底已经够用。
    _rmtree_skip_locked(path_str, on_log)

    if not os.path.exists(path_str):
        if on_log:
            on_log(f"已删除: {path_str}")
        return True

    # 同步删之后还残留:再试一次 rename 兜底
    try:
        residue_path2 = f"{path_str}._residue.{int(_time.time() * 1000)}"
        os.rename(path_str, residue_path2)
        if on_log:
            on_log(f"已隔离剩余残留: {os.path.basename(residue_path2)}")
        if wait:
            _background_purge_sync(residue_path2, on_log)
        return True
    except OSError:
        if on_log:
            on_log(f"删除 {path_str} 失败: 目录被句柄占用")
        return False


def _background_purge(target_path: str) -> None:
    """后台 daemon 线程的清理实现:Windows 用 robocopy,其他平台用 Python 流式删。

    安全门禁(2026-05 修): **只允许 basename 含 ._residue. 的隔离目录走 robocopy**。
    历史教训:robocopy /MIR 是"镜像同步"语义,在 daemon 并发或路径解析异常时
    可能误清空非隔离目录(实际撞过 ~/openclaw-cn 被清空的事故)。所以 path 必须
    是 force_rmtree 改名后的 .residue 路径,任何其他路径都退化到 Python 单线程
    路径,牺牲速度换安全。

    Windows + Defender 下,单线程 DeleteFile 串行删 100k 文件要 1-3 分钟;
    robocopy /MIR /MT:16 用 16 个并发线程跑 DeleteFile,实测能快 5-10 倍,
    且锁住的文件 (/R:0 /W:0) 立刻跳过不重试。流程:
    1. 创建一个空临时目录
    2. robocopy 把空目录"镜像"到 target,等于删空 target
    3. rmdir 删掉变空的 target 和临时目录

    其他平台 (macOS) 走 Python 的 _rmtree_skip_locked 已经够快
    (rm -rf 等价语义),且没有 robocopy 这种 native 工具的等价物。
    """
    if not os.path.exists(target_path):
        return

    # 安全门禁:basename 必须含 ._residue. 才允许 robocopy。
    # force_rmtree 改名后的隔离路径形如 "xxx._residue.<ms>",
    # cleanup_orphan_residues 扫的也是这种路径。
    # 任何"长得像正常项目目录"的路径都不能用 robocopy/MIR 清,以免误伤。
    is_residue = "._residue." in os.path.basename(target_path)

    if is_windows() and is_residue:
        try:
            import tempfile
            empty_dir = tempfile.mkdtemp(prefix="oc_empty_")
            try:
                # robocopy: 内置工具,无需安装。返回码 0-7 都算成功 (含跳过/不一致),
                # 8+ 才算真失败。这里完全吞掉返回码,反正后面会 rmdir 兜底。
                # /MIR  镜像 source 到 dest = 把 dest 清空(因为 source 是空的)
                # /MT:16 16 线程并发删,绕开单线程 DeleteFile 串行瓶颈
                # /R:0 /W:0 锁住的文件立刻跳过,不重试
                # /NFL/NDL/NJH/NJS/NC/NS/NP 全静默,不打印进度
                subprocess.run(
                    [
                        "robocopy", empty_dir, target_path,
                        "/MIR", "/MT:16",
                        "/R:0", "/W:0",
                        "/NFL", "/NDL", "/NJH", "/NJS", "/NC", "/NS", "/NP",
                    ],
                    capture_output=True,
                    timeout=600,  # 10 分钟兜底,理论上不会触发
                    **windows_hidden_subprocess_kwargs(),
                )
            finally:
                # 清掉临时空目录;target_path 此时也已经空了,顺手 rmdir 干掉
                for d in (empty_dir, target_path):
                    try:
                        os.rmdir(d)
                    except OSError:
                        pass
            return
        except (OSError, subprocess.SubprocessError):
            # robocopy 不可用 (理论上 Vista+ 都内置) → 走 Python 兜底
            pass

    # 非 Windows / 非 _residue 路径 / robocopy 失败:走 Python 流式删
    try:
        _rmtree_skip_locked(target_path, None)
    except Exception:
        pass


def _background_purge_sync(target_path: str, on_log: Callable[[str], None] | None) -> None:
    """同步版本的 _background_purge,带心跳日志。卸载器专用。

    与 _background_purge 不同:
    - 阻塞调用方直到 robocopy/Python 流式删跑完
    - 起一个心跳线程每 5 秒输出"还在清理"日志,让用户知道程序没卡死
    - robocopy 用 /MT:32 提到 32 线程(后台 daemon 的 /MT:16 是怕抢资源,这里前台跑就猛点)
    """
    if not os.path.exists(target_path):
        return

    is_residue = "._residue." in os.path.basename(target_path)

    # 起心跳线程:每 5 秒说一句"还在清理 N 个文件"
    import threading as _threading
    import time as _time
    stop_heartbeat = _threading.Event()

    def _heartbeat() -> None:
        start = _time.time()
        while not stop_heartbeat.wait(5.0):
            try:
                # 估算剩余:用 os.scandir 浅扫一层,大致看到还有多少 entry
                count = 0
                for _ in os.scandir(target_path):
                    count += 1
                    if count > 1000:
                        break
                elapsed = int(_time.time() - start)
                if on_log:
                    suffix = "+" if count > 1000 else ""
                    on_log(f"  正在清理...(已 {elapsed}s,目录顶层剩余 {count}{suffix} 项,请耐心等待)")
            except OSError:
                # 目录已删则正常,心跳自然结束
                if not os.path.exists(target_path):
                    return

    hb_thread = _threading.Thread(target=_heartbeat, daemon=True, name="purge_heartbeat")
    hb_thread.start()

    try:
        if is_windows() and is_residue:
            try:
                import tempfile
                empty_dir = tempfile.mkdtemp(prefix="oc_empty_")
                try:
                    # /MT:32: 前台跑,放手用 32 线程(daemon 用 /MT:16 是怕抢主流程资源)
                    subprocess.run(
                        [
                            "robocopy", empty_dir, target_path,
                            "/MIR", "/MT:32",
                            "/R:0", "/W:0",
                            "/NFL", "/NDL", "/NJH", "/NJS", "/NC", "/NS", "/NP",
                        ],
                        capture_output=True,
                        timeout=1800,  # 30 分钟兜底
                        **windows_hidden_subprocess_kwargs(),
                    )
                finally:
                    for d in (empty_dir, target_path):
                        try:
                            os.rmdir(d)
                        except OSError:
                            pass
            except (OSError, subprocess.SubprocessError):
                # robocopy 失败(理论上 Vista+ 都内置)→ 走 Python 兜底
                try:
                    _rmtree_skip_locked(target_path, on_log)
                except Exception:
                    pass
        else:
            # 非 Windows 或非 residue 路径:Python 流式删 + rm -rf 兜底
            # 与 force_rmtree Mac 主路径对齐(utils.py:215-217),双重保险。
            # 历史 bug: 仅靠 _rmtree_skip_locked 的"软删除"语义,遇到 pnpm workspace
            # 循环 symlink、特殊文件类型时会静默残留,卸载循环报"部分完成"死循环。
            try:
                _rmtree_skip_locked(target_path, on_log)
            except Exception:
                pass
            if os.path.exists(target_path):
                try:
                    subprocess.run(
                        ["rm", "-rf", target_path],
                        capture_output=True, timeout=300,
                    )
                except (OSError, subprocess.SubprocessError):
                    pass
    finally:
        stop_heartbeat.set()


def cleanup_orphan_residues(
    parent_dir: str | Path,
    on_log: Callable[[str], None] | None = None,
    wait: bool = False,
) -> int:
    """扫描指定目录下的 *._residue.* 残渣并后台清理。

    force_rmtree 的 rename 兜底会留下 .residue.<timestamp> 文件夹,正常情况下
    daemon 线程会清掉,但安装器进程异常退出时可能留下残渣。下次安装/卸载时
    调用本函数把它们补一刀。同样不阻塞主流程,起 daemon 线程后台清。

    Args:
        parent_dir: 要扫描的父目录(如用户主目录)。
        on_log: 可选的日志回调。
        wait: True 时同步等待每个残渣清完才返回,卸载器专用;
              False 时起 daemon 线程后台清,不阻塞主流程。

    Returns:
        发现的残渣个数(wait=False 时不等于成功清理数)。
    """
    parent = Path(parent_dir)
    if not parent.exists():
        return 0

    # 收集所有残渣
    residues: list[str] = []
    try:
        for entry in parent.iterdir():
            if "._residue." in entry.name:
                residues.append(str(entry))
    except OSError:
        pass

    if not residues:
        return 0

    if wait:
        # 同步模式:逐个清,前台跑,带心跳
        if on_log:
            on_log(f"发现 {len(residues)} 个历史残渣,开始彻底清理...")
        for i, _path in enumerate(residues, 1):
            name = os.path.basename(_path)
            if on_log:
                on_log(f"[{i}/{len(residues)}] 清理 {name}...")
            _background_purge_sync(_path, on_log)
            if not os.path.exists(_path) and on_log:
                on_log(f"[{i}/{len(residues)}] 已彻底清理 {name}")
        return len(residues)

    # 异步模式:起 daemon 后台清,立即返回
    import threading as _threading
    for _path in residues:
        if on_log:
            on_log(f"发现历史残渣,后台清理: {os.path.basename(_path)}")
        _threading.Thread(
            target=_background_purge,
            args=(_path,),
            daemon=True,
            name="orphan_residue_bg",
        ).start()
    return len(residues)


def _rmtree_skip_locked(
    root_path: str,
    on_log: Callable[[str], None] | None = None,
) -> None:
    """流式逐文件删除目录树,锁住/权限不够的文件跳过,能删多少删多少。

    自底向上(os.walk topdown=False)遍历:边遍历边删,不 buffer。
    心跳改为时间驱动:每 1.5s 输出一次进度,与文件数量无关——这样大小目录
    都有合理的反馈频率,UI 不会因为信号洪水卡顿(~0.7Hz 远低于 30Hz 安全线)。

    Args:
        root_path: 要删除的目录树根路径。
        on_log: 可选的日志回调。
    """
    import time as _t

    last_hb = _t.monotonic()
    deleted = 0
    started_log = False

    try:
        # 流式遍历:不 buffer,边走边删
        for dirpath, dirnames, filenames in os.walk(root_path, topdown=False):
            # 先删文件
            for fn in filenames:
                entry_path = os.path.join(dirpath, fn)
                try:
                    os.unlink(entry_path)
                except OSError:
                    try:
                        # 文件加 owner 读+写,够用了。S_IRWXU = 0o700 兼容文件/目录两种,
                        # 但文件不需要 x 位,这里给 0o600 (S_IWRITE | S_IREAD) 即可。
                        os.chmod(entry_path, stat.S_IWRITE | stat.S_IREAD)
                        os.unlink(entry_path)
                    except OSError:
                        pass  # 真删不掉就跳过
                deleted += 1
                # 时间驱动心跳:每 1.5s 输出一次
                if on_log:
                    now = _t.monotonic()
                    if now - last_hb > 1.5:
                        if not started_log:
                            on_log(f"正在清理大型目录,已处理 {deleted} 个文件...")
                            started_log = True
                        else:
                            on_log(f"清理中... 已处理 {deleted} 个文件/目录")
                        last_hb = now

            # 再删空目录(或 symlink-to-dir)
            for dn in dirnames:
                entry_path = os.path.join(dirpath, dn)
                # pnpm workspace 内部循环 symlink(如 extensions/*/node_modules/openclaw
                # 指回项目根)在 os.walk(followlinks=False) 下会出现在 dirnames 里。
                # 此时必须 unlink(删链接本身),不能 rmdir(rmdir 对 symlink 报 ENOTDIR)。
                # 历史 bug: 之前一律走 rmdir,导致 pnpm workspace 残渣永远删不干净,
                # 卸载循环报"部分完成"。
                if os.path.islink(entry_path):
                    try:
                        os.unlink(entry_path)
                    except OSError:
                        pass
                    deleted += 1
                    continue
                try:
                    os.rmdir(entry_path)
                except OSError:
                    try:
                        # 目录必须给 S_IRWXU (0o700),含 x 执行位,否则 Mac 上
                        # 后续 rmdir 仍会因为父进程进不去目录而失败,且会留下
                        # drw------- 怪异权限的残渣,下次卸载循环检测不掉。
                        # Windows 上 0o700 与 0o600 等价(不区分 x 位),无副作用。
                        os.chmod(entry_path, stat.S_IRWXU)
                        os.rmdir(entry_path)
                    except OSError:
                        pass
                deleted += 1
    except OSError:
        pass

    # 最后试着删根目录本身
    try:
        os.rmdir(root_path)
    except OSError:
        pass


def remove_readonly(func: Callable[..., None], path: str, _: Any) -> None:
    """shutil.rmtree 的 onerror 回调：移除只读属性后重试删除操作。

    用途：删除可能包含只读文件（如 Git 仓库中的文件）的目录时，
    先修改文件权限再重试删除操作。

    注意：Python 3.12+ 的 shutil.rmtree 内部使用 _rmtree_safe_fd，
    此时 func 可能是 os.open（需要 flags 参数）。遇到 os.open 时只修改
    权限并返回，让 rmtree 自动重试；其他情况（os.unlink/os.rmdir）
    正常调用删除。
    """
    os.chmod(path, stat.S_IWRITE)
    if func is os.open:
        # os.open 需要 flags 参数，在 _rmtree_safe_fd 内部使用。
        # 我们只负责修改权限，rmtree 会自动重试。
        return
    func(path)


def resolve_pnpm_cmd(env: Optional[dict] = None) -> str:
    """解析 pnpm 命令的可执行路径。

    优先级:
    1. ~/.openclaw-node/bin/pnpm (macOS) / ~/.openclaw-node/pnpm.cmd (Win) ——
       这是 install_openclaw.py 自己解压的位置, 是个强 invariant。安装器走完
       一定有, 路径写死即可零猜测。
    2. shutil.which("pnpm", path=env["PATH"]) —— 兜底场景: 用户手动 brew/npm
       装了 pnpm 且 PATH 已经包含。
    3. 仅 macOS: 调用 `bash -lc 'command -v pnpm'` 让用户 shell 加载 .zshrc/
       .bash_profile, 拿到 nvm/volta/brew 装的 pnpm 真实路径。
       Mac GUI 启动(.app/.command/launchd)拿到的 PATH 是 launchd 注入的最小集,
       不读 shell rc 文件,前两条都会失败。这条路径模拟"用户在终端能跑 pnpm"
       的环境,适用于开发机/已自己装过 pnpm 的高级用户场景。
       Windows 不需要这条:Windows 的 PATH 来自注册表,GUI 子进程能完整继承,
       Win 用户用 npm/scoop 装的 pnpm 走第 2 条就能命中。

    为什么不直接硬编码 ~/Library/pnpm 等候选目录:
    - 由我们的安装器装的 pnpm 一定在 .openclaw-node 下, 命中路径 1。
    - 硬编码 corepack/volta/asdf 路径是赌博——用户可能根本没装那些工具,
      反而增加误判风险。借用 shell 的查找逻辑比手写一堆候选可靠得多。

    Args:
        env: 可选环境变量字典。仅 PATH 这一项会被使用,用于 shutil.which 兜底。

    Returns:
        pnpm 可执行文件的绝对路径。三条路径都失败时返回裸名 "pnpm",
        让上层 subprocess.Popen 自己抛 FileNotFoundError —— 这是用户手动
        删除 .openclaw-node/bin/pnpm 等极端情况, 不应静默兜底。
    """
    home = os.path.expanduser("~")
    if is_windows():
        local_pnpm = os.path.join(home, ".openclaw-node", "pnpm.cmd")
    else:
        local_pnpm = os.path.join(home, ".openclaw-node", "bin", "pnpm")

    if os.path.isfile(local_pnpm):
        return local_pnpm

    path_env = (env or {}).get("PATH") or os.environ.get("PATH", "")
    resolved = shutil.which("pnpm", path=path_env)
    if resolved:
        return resolved

    # 兜底路径 3 (仅 macOS): 借用用户的 shell 加载 rc 文件后的 PATH 查找。
    # 关键陷阱:
    # - launchd 启动的 GUI 子进程拿到的 env 不含 $SHELL,要用 pwd.getpwuid 拿
    #   用户在系统设置里配的默认 shell。
    # - 必须用 `-lic` (login + interactive) 才能加载 ~/.zshrc。zsh 的 nvm/volta
    #   钩子绝大多数装在 .zshrc 里, 仅 -lc (login,非交互) 不会加载。bash 同理:
    #   仅 .bash_profile 会被 -lc 加载, .bashrc 要 -i 才行。
    # - 3 秒超时:oh-my-zsh / starship 之类启动慢,但也不能等太久阻塞 GUI。
    # - 候选 shell 顺序:用户默认 shell → zsh → bash。macOS 11+ 默认 zsh,
    #   开发者机器多半 nvm 写在 .zshrc;少数还在用 bash 的也兜得住。
    if not is_windows():
        candidate_shells: list[str] = []
        try:
            import pwd
            user_shell = pwd.getpwuid(os.getuid()).pw_shell
            if user_shell and os.path.isfile(user_shell):
                candidate_shells.append(user_shell)
        except (KeyError, OSError, ImportError):
            pass
        for shell_path in ("/bin/zsh", "/bin/bash"):
            if shell_path not in candidate_shells and os.path.isfile(shell_path):
                candidate_shells.append(shell_path)

        for shell_path in candidate_shells:
            try:
                result = subprocess.run(
                    [shell_path, "-lic", "command -v pnpm"],
                    capture_output=True,
                    text=True,
                    timeout=3,
                )
            except (OSError, subprocess.SubprocessError):
                continue
            # 取 stdout 最后一行非空内容(rc 文件可能打印 banner 在前)
            for line in reversed(result.stdout.splitlines()):
                line = line.strip()
                if line and os.path.isfile(line):
                    return line

    return "pnpm"


def resolve_openclaw_cmd(env: Optional[dict] = None) -> str:
    """检测系统中可用的 openclaw 命令。

    优先检测 openclaw-cn，fallback 到 openclaw。
    Windows 使用 where 命令（能正确处理 %APPDATA% 等环境变量展开），
    macOS 使用 shutil.which。

    Args:
        env: 可选的环境变量字典，用于 macOS 的自定义 PATH 检测。

    Returns:
        str: 检测到的命令名（如 "openclaw-cn"），若都未找到则返回 "openclaw"。
    """
    if is_windows():
        hidden = windows_hidden_subprocess_kwargs()
        for cmd in ["openclaw-cn", "openclaw"]:
            try:
                result = subprocess.run(
                    ["where", cmd],
                    shell=False,
                    capture_output=True,
                    timeout=TIMEOUT_SHORT_CMD,
                    **hidden,
                )
                if result.returncode == 0:
                    return cmd
            except (OSError, subprocess.SubprocessError):
                pass
    else:
        path_env = env.get("PATH", os.environ.get("PATH", "")) if env else os.environ.get("PATH", "")
        for cmd in ["openclaw-cn", "openclaw"]:
            if shutil.which(cmd, path=path_env) is not None:
                return cmd
    return "openclaw"


def persist_user_path_windows(
    new_dir: str, on_log: Callable[[str], None] | None = None
) -> bool:
    """Windows: 把目录追加到 HKCU\\Environment\\Path,新终端立即可见。

    为何不用 setx:
    - setx 1024 字符截断,开发机 PATH 易超。
    - setx 写入时 %PATH% 展开会合并 USER+SYSTEM,再写回 USER 时污染。
    winreg 直接读写注册表,无截断、不混淆。
    写入后广播 WM_SETTINGCHANGE 通知 Explorer / 新进程刷新。

    Returns:
        True 写入成功或已存在。
    """
    if not is_windows():
        return False
    try:
        import winreg
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, "Environment", 0,
            winreg.KEY_READ | winreg.KEY_WRITE,
        ) as key:
            try:
                current_value, value_type = winreg.QueryValueEx(key, "Path")
            except FileNotFoundError:
                current_value, value_type = "", winreg.REG_EXPAND_SZ

            existing = [p for p in current_value.split(";") if p]
            if any(new_dir.lower() == p.strip().lower() for p in existing):
                if on_log:
                    on_log(f"用户 PATH 已包含 {new_dir},无需重复写入")
                return True

            new_value = (current_value.rstrip(";") + ";" + new_dir) if current_value else new_dir
            winreg.SetValueEx(key, "Path", 0, value_type, new_value)
            if on_log:
                on_log(f"已通过 winreg 将 {new_dir} 写入用户 PATH")

        try:
            import ctypes
            HWND_BROADCAST = 0xFFFF
            WM_SETTINGCHANGE = 0x001A
            SMTO_ABORTIFHUNG = 0x0002
            result = ctypes.c_long()
            ctypes.windll.user32.SendMessageTimeoutW(
                HWND_BROADCAST, WM_SETTINGCHANGE, 0,
                "Environment", SMTO_ABORTIFHUNG, 5000, ctypes.byref(result),
            )
        except (OSError, AttributeError) as e:
            if on_log:
                on_log(f"广播环境变量变更失败(非致命): {e}")
        return True
    except (OSError, ImportError) as e:
        if on_log:
            on_log(f"通过 winreg 写入用户 PATH 失败: {e}")
        return False


def ensure_dir_in_path(directory: str, on_log: Callable[[str], None] | None = None) -> None:
    """将指定目录持久化到用户 shell 配置文件的 PATH 中。

    会依次检查 .bashrc、.zshrc、.profile，避免重复写入。
    这是为"安装完成后用户新开终端能直接使用命令"做的持久化配置。

    Args:
        directory: 要加入 PATH 的目录绝对路径。
        on_log: 可选的日志回调函数，用于输出操作结果。
    """
    # Windows: 写注册表 HKCU\Environment\Path,新进程会自动继承。
    if is_windows():
        persist_user_path_windows(directory, on_log)
        return

    path_export = f'export PATH="{directory}:$PATH"'

    home = os.path.expanduser("~")
    written = False
    for rc_file in [".bashrc", ".zshrc", ".profile"]:
        rc_path = os.path.join(home, rc_file)
        if os.path.exists(rc_path):
            try:
                with open(rc_path, "r", encoding="utf-8") as f:
                    content = f.read()
                if directory in content:
                    if on_log:
                        on_log(f"{rc_file} 已包含 {directory}")
                    written = True
                    continue
                with open(rc_path, "a", encoding="utf-8") as f:
                    f.write(f"\n# Added by OpenClaw Installer\n{path_export}\n")
                if on_log:
                    on_log(f"已将 {directory} 添加到 {rc_file}")
                written = True
            except OSError as e:
                if on_log:
                    on_log(f"修改 {rc_file} 失败: {e}")

    # 如果没有任何 rc 文件存在（全新系统），主动创建一个
    if not written:
        # macOS 默认 zsh
        default_rc = ".zshrc"
        rc_path = os.path.join(home, default_rc)
        try:
            with open(rc_path, "w", encoding="utf-8") as f:
                f.write(f"# Created by OpenClaw Installer\n{path_export}\n")
            if on_log:
                on_log(f"已创建 {default_rc} 并添加 {directory}")
        except OSError as e:
            if on_log:
                on_log(f"创建 {default_rc} 失败: {e}")


def ensure_local_bin_in_path(on_log: Callable[[str], None] | None = None) -> None:
    """确保 ~/.local/bin 被写入用户 shell 配置文件。

    这是 ensure_dir_in_path 的便捷封装，用于 openclaw 命令包装器的 PATH 持久化。
    """
    home = os.path.expanduser("~")
    local_bin = os.path.join(home, ".local", "bin")
    ensure_dir_in_path(local_bin, on_log)


def detect_openclaw_installation() -> tuple[bool, list[str]]:
    """检测系统中是否存在任何 OpenClaw 残留(供卸载器使用)。

    设计原则:**宽松检测,任一残留就提供卸载**。这与安装器的"严格检测,完整可用才算
    已装"是相反的方向。卸载器存在的意义就是"清理一切残留",哪怕用户手动删过一部分,
    剩下的也应该一并卸干净。

    检查范围与 OpenClawManager.uninstall() 删除的目标完全对齐:
    - ~/openclaw-cn:程序源码/构建目录
    - ~/.openclaw:配置文件 + API key 等
    - ~/.openclaw-git:macOS 离线版内置 git
    - ~/.openclaw-node:在线版下载的 Node.js
    - 命令包装器:Windows %APPDATA%\\Roaming\\npm\\openclaw*.cmd / *nix ~/.local/bin/openclaw*
    - 历史隔离残渣:~/openclaw-cn._residue.* 等(force_rmtree 后台清理未完成留下的)

    Returns:
        (是否需要卸载, 检测到的残留描述列表)
    """
    home = os.path.expanduser("~")
    details: list[str] = []

    # 1. 主要目录(全平台)
    main_dirs = [
        ("openclaw-cn", "程序文件: ~/openclaw-cn"),
        (".openclaw", "配置文件: ~/.openclaw"),
        (".openclaw-git", "内置 Git: ~/.openclaw-git"),
        (".openclaw-node", "内置 Node.js: ~/.openclaw-node"),
    ]
    for dirname, label in main_dirs:
        if os.path.exists(os.path.join(home, dirname)):
            details.append(label)

    # 2. 命令包装器(平台分两套)
    if is_windows():
        wrapper_dir = os.path.join(home, "AppData", "Roaming", "npm")
        wrapper_files = ["openclaw.cmd", "openclaw-cn.cmd"]
        wrapper_label_template = "命令包装器: %APPDATA%\\Roaming\\npm\\{}"
    else:
        wrapper_dir = os.path.join(home, ".local", "bin")
        wrapper_files = ["openclaw", "openclaw-cn"]
        wrapper_label_template = "命令包装器: ~/.local/bin/{}"
    for wf in wrapper_files:
        if os.path.isfile(os.path.join(wrapper_dir, wf)):
            details.append(wrapper_label_template.format(wf))

    # 3. 历史隔离残渣(force_rmtree 后台清理未完成的)
    try:
        for entry in os.listdir(home):
            if "._residue." in entry and (
                entry.startswith("openclaw-cn") or entry.startswith(".openclaw")
            ):
                details.append(f"历史残渣: ~/{entry}")
    except OSError:
        pass

    return bool(details), details


def redact_home_path(text: str) -> str:
    """将文本中的用户主目录路径替换为 ``~``,降低截图/日志分享时的隐私泄露风险。

    诊断日志和命令展示常常带绝对路径(如 ``C:\\Users\\<name>\\openclaw-cn``),
    一旦截屏发到 issue/客服群,就把用户名暴露出去。这个函数仅做一层简单替换,
    不影响文本里其他内容。

    分别尝试原始 home、正斜杠版、反斜杠版,以兼容跨平台路径混用的日志输出
    (Windows 上某些子进程会回吐 / 风格的路径,反之亦然)。

    Args:
        text: 任意文本,空字符串/None 直接原样返回。

    Returns:
        替换后的文本。若无法解析 home,返回原始文本。
    """
    if not text:
        return text
    home = os.path.expanduser("~")
    if not home or home == "~":
        return text
    text = text.replace(home, "~")
    home_fwd = home.replace("\\", "/")
    if home_fwd != home:
        text = text.replace(home_fwd, "~")
    home_bwd = home.replace("/", "\\")
    if home_bwd != home:
        text = text.replace(home_bwd, "~")
    return text


def safe_tar_extract(
    tar: tarfile.TarFile,
    dest: Path | str,
    on_log: Callable[[str], None] | None = None,
) -> None:
    """安全解压 tar 包，防止路径遍历攻击（zip-slip）。

    校验每个成员的最终解析后的绝对路径是否在目标目录内，
    同时校验软链接目标是否逃逸出目标目录。
    所有 Python 版本统一走手动校验路径，确保行为一致且异常可感知。

    Args:
        tar: 已打开的 tarfile 对象。
        dest: 解压目标目录。
        on_log: 可选的日志回调，用于输出拒绝信息。

    Raises:
        tarfile.TarError: 当发现不安全的路径遍历成员时抛出。
    """
    dest_path = Path(dest).resolve()

    # 性能关键(2026-05-14 优化): 校验循环中绝对禁止调用 Path.resolve() 这种
    # 触发文件系统访问的 API。230k 个 tar 成员,Windows + Defender 下每次 resolve()
    # 都触发 Defender 扫描,单次 ~1-3ms,累计循环耗时 5-15 分钟,严重拖慢解压。
    # 改为纯字符串校验:
    # 1. 拒绝绝对路径前缀(/、盘符、UNC)
    # 2. 拒绝任意 ".." 组件(无需 resolve 就能识别 zip-slip)
    # 3. 拒绝软链接 linkname 含绝对路径或 ".." 逃逸的情况
    # 这等价于"绝对路径白名单(必须以非 .. 相对路径开头)",安全等级与 resolve 一致。
    dest_str = str(dest_path).replace("\\", "/")

    for member in tar.getmembers():
        # 归一反斜杠: tar 规范用 "/",反斜杠都视作可疑。
        # POSIX 下 Path("foo\\..\\bar").parts 只看到一个组件,漏检 ".." 攻击,
        # 归一后跨平台检查一致。
        normalized_name = member.name.replace("\\", "/")
        normalized_parts = normalized_name.split("/")

        # 拒绝绝对路径(POSIX /、Windows 盘符、UNC //)和含 ".." 的原始路径
        is_absolute = (
            normalized_name.startswith("/")
            or normalized_name.startswith("//")
            or (len(normalized_name) >= 2 and normalized_name[1] == ":")
        )
        if is_absolute or ".." in normalized_parts:
            msg = f"拒绝不安全的 tar 成员: {member.name}"
            if on_log:
                on_log(msg)
            raise tarfile.TarError(msg)

        # 拒绝设备文件
        if member.isdev():
            msg = f"拒绝 tar 设备文件: {member.name}"
            if on_log:
                on_log(msg)
            raise tarfile.TarError(msg)

        # 校验软链接 linkname:
        # SYMTYPE 我们的打包脚本约定生成相对路径(如 "../../.."),解压时按相对解析。
        # 用纯字符串模拟"link 所在目录 + linkname"的结果,看会不会跑出 dest_path。
        # 不调 resolve(),避免文件系统访问。
        if member.issym() or member.islnk():
            link_name = member.linkname.replace("\\", "/")
            # 绝对路径软链接直接拒绝(我们的打包流程不应该产生这种)
            if (
                link_name.startswith("/")
                or link_name.startswith("//")
                or (len(link_name) >= 2 and link_name[1] == ":")
            ):
                msg = f"拒绝不安全的软链接目标(绝对路径): {member.linkname}"
                if on_log:
                    on_log(msg)
                raise tarfile.TarError(msg)

            # 模拟 link 所在目录的相对位置(在 dest_path 下),计算 linkname 解析后
            # 的相对深度。用计数器代替路径拼接 + resolve。
            # link 在 tar 内位置: dest_path/<member.name 路径>。link 父目录深度 = parts 数 - 1。
            link_parent_depth = len(normalized_parts) - 1  # link 父目录在 dest 下的深度
            depth = link_parent_depth
            for part in link_name.split("/"):
                if part in ("", "."):
                    continue
                if part == "..":
                    depth -= 1
                    if depth < 0:
                        msg = f"拒绝不安全的软链接目标(逃出 dest): {member.linkname}"
                        if on_log:
                            on_log(msg)
                        raise tarfile.TarError(msg)
                else:
                    depth += 1

    # 分两阶段解压(2026-05-14 验证后定稿):
    # Win 上用 7z.exe(7-Zip 命令行版,多线程,不加 \\?\ 前缀避开 LongPaths 限制),
    # 比 Python tarfile 快 5-10 倍。7z 找不到才退化到 Python tarfile。
    # 7z.exe 优先位置: 项目内置 resources/windows/7z.exe > C:\Program Files\7-Zip\
    # > C:\Program Files (x86)\7-Zip\ > PATH 上的 7z。
    #
    # SYMTYPE 在 Win 上仍需手动处理:默认 extract 创建文件软链接,我们要的是
    # 目录型链接(junction 或 directory symlink)。
    members_all = tar.getmembers()
    sym_members = [m for m in members_all if m.issym()]
    non_sym_members = [m for m in members_all if not m.issym()]

    if non_sym_members:
        if is_windows():
            _extract_with_7z_or_python(tar, dest_path, sym_members, on_log)
        else:
            tar.extractall(dest, members=non_sym_members)

    if sym_members:
        total = len(sym_members)
        if on_log:
            on_log(f"还原 {total} 个目录链接(使用 NTFS junction,通常数秒完成)...")
        for idx, sym in enumerate(sym_members, start=1):
            if is_windows():
                _extract_directory_symlink(sym, dest_path, on_log)
            else:
                tar.extract(sym, dest)
            # 每 500 个心跳一次,避免长跑无声让用户以为卡死
            if on_log and idx % 500 == 0:
                on_log(f"  目录链接进度: {idx}/{total}")
        if on_log:
            on_log(f"目录链接全部还原完成 ({total}/{total})")


def find_app_icon_path() -> Optional[str]:
    """返回当前平台合适的应用图标文件绝对路径,找不到返回 None。

    优先级:
    1. PyInstaller 打包后的 _MEIPASS/build/icons/
    2. 开发模式下项目根 build/icons/(generate_icons.py 的产物)
    3. 兜底用 resources/logo.png(原图,Qt 也能识别 PNG)

    用途:三个入口窗口(InstallerWindow / UninstallerWindow)都通过这个找图标,
    避免重复硬编码路径,也保证 PyInstaller 打包后能正确解析。
    """
    # macOS .icns 给 Finder/Dock 看,运行时窗口图标用 PNG 反而更通用;
    # Windows .ico 是窗口图标的天然格式,直接用。
    icon_filename = "openclaw.ico" if is_windows() else "openclaw.icns"

    candidates = []
    # 1. PyInstaller 打包路径
    if hasattr(sys, "_MEIPASS"):
        candidates.append(os.path.join(sys._MEIPASS, "build", "icons", icon_filename))
        candidates.append(os.path.join(sys._MEIPASS, "build", "icons", "openclaw.icns"))
        candidates.append(os.path.join(sys._MEIPASS, "build", "icons", "openclaw.ico"))
        candidates.append(os.path.join(sys._MEIPASS, "resources", "logo.png"))

    # 2. 开发模式
    project_root = Path(__file__).parent.parent.parent.resolve()
    candidates.extend([
        str(project_root / "build" / "icons" / icon_filename),
        str(project_root / "build" / "icons" / "openclaw.icns"),
        str(project_root / "build" / "icons" / "openclaw.ico"),
        str(project_root / "resources" / "logo.png"),
    ])

    for c in candidates:
        if os.path.isfile(c):
            return c
    return None


def _find_7z_exe() -> Optional[str]:
    """找 Windows 上的 7z.exe 可执行文件路径,按优先级:
    1. 项目内置 resources/windows/7z.exe(便于离线版自包含)
    2. 系统安装位置(C:\\Program Files\\7-Zip\\、Program Files (x86)\\7-Zip\\)
    3. PATH 上的 7z

    Returns:
        7z.exe 绝对路径,找不到返回 None。
    """
    if not is_windows():
        return None

    # 1. 项目 resources/windows/(开发模式 + PyInstaller _MEIPASS)
    candidates = []
    if hasattr(sys, "_MEIPASS"):
        candidates.append(os.path.join(sys._MEIPASS, "resources", "windows", "7z.exe"))
        candidates.append(os.path.join(sys._MEIPASS, "resources", "windows", "7za.exe"))
    project_root = Path(__file__).parent.parent.parent.resolve()
    candidates.extend([
        str(project_root / "resources" / "windows" / "7z.exe"),
        str(project_root / "resources" / "windows" / "7za.exe"),
    ])

    # 2. 系统安装位置
    candidates.extend([
        r"C:\Program Files\7-Zip\7z.exe",
        r"C:\Program Files (x86)\7-Zip\7z.exe",
    ])

    for c in candidates:
        if os.path.isfile(c):
            return c

    # 3. PATH 兜底
    return shutil.which("7z.exe") or shutil.which("7za.exe")


def _extract_with_7z_or_python(
    tar: tarfile.TarFile,
    dest_path: Path,
    sym_members: list,
    on_log: Callable[[str], None] | None,
) -> None:
    """Windows 解压主路径:优先 7z.exe,失败退化 Python tarfile。

    7z.exe 解压 .tar.gz 需要两步(它先解 gzip 再解 tar),用管道一步到位:
        7z x -so <archive.tar.gz> | 7z x -si -ttar -o<dest>
    或更直接的两步:
        7z e -so <archive.tar.gz> > <archive.tar>  # 第一步:解 gzip
        7z x -ttar -o<dest> <archive.tar>          # 第二步:解 tar
    用临时文件而不是管道,避免 Python 中转管道反而拖慢。
    """
    archive_path = tar.name
    if not archive_path:
        if on_log:
            on_log("tarball 无文件路径,退化到 Python tarfile")
        non_sym = [m for m in tar.getmembers() if not m.issym()]
        tar.extractall(str(dest_path), members=non_sym)
        return

    seven_z = _find_7z_exe()
    if not seven_z:
        if on_log:
            on_log("未找到 7z.exe,退化到 Python tarfile(慢但稳定)")
        non_sym = [m for m in tar.getmembers() if not m.issym()]
        tar.extractall(str(dest_path), members=non_sym)
        return

    # 7z.exe 解压 .tar.gz 流程:先解到临时 .tar,再 7z x 该 .tar
    # exclude SYMTYPE 路径:避免 7z 错误创建文件软链接,我们 Python 后处理
    import tempfile
    if on_log:
        on_log(f"使用 7z.exe 解压(可执行文件: {seven_z})...")

    tmp_tar_fd, tmp_tar_path = tempfile.mkstemp(suffix=".tar", prefix="oc_extract_")
    os.close(tmp_tar_fd)
    try:
        # 第一步:解 gzip → .tar
        # stderr 同样需要 DEVNULL 避免管道死锁(同第二步)
        if on_log:
            on_log(f"  步骤 1/2: 解压 gzip → 临时 .tar")
        with open(tmp_tar_path, "wb") as tar_out:
            result1 = subprocess.run(
                [seven_z, "e", "-so", "-bsp0", archive_path],
                stdout=tar_out,
                stderr=subprocess.DEVNULL,
                timeout=600,
                **windows_hidden_subprocess_kwargs(),
            )
        if result1.returncode != 0:
            if on_log:
                on_log(f"  7z 解 gzip 失败,返回码 {result1.returncode}")
            raise RuntimeError("7z gzip extract failed")

        # 第二步:解 tar 到目标目录,exclude SYMTYPE
        # -bso0 / -bse0 / -bsp0 = 关 stdout / stderr / progress 输出。
        # 必须关 —— 7z 默认每文件输出一行,跑 23 万文件会输出几 MB,把 subprocess
        # 64KB pipe buffer 写满,导致 Python 不读 + 7z 不能写 → 双向死锁。
        # 实测前一次跑到 20 万文件后卡了 47 分钟没动,就是这个 bug。
        if on_log:
            on_log(f"  步骤 2/2: 解压 tar 到目标目录(预计 7-10 分钟,请勿关闭窗口)")
        cmd = [
            seven_z, "x", "-ttar",
            f"-o{dest_path}",
            tmp_tar_path,
            "-y",      # 全部 yes,跳过 prompts
            "-bso0",   # 关 stdout(每文件进度日志)
            "-bsp0",   # 关 progress 输出
            # 不关 stderr(-bse0),保留真错误信息;但用 DEVNULL 防止管道死锁
        ]
        # SYMTYPE 成员要 exclude(由 Python 后处理重建为 junction/dirlink)。
        # 历史 bug(2026-05 修): 之前用 `-x!<path>` 单参数追加,3000+ junction
        # 时命令行超过 Windows CreateProcess 32K 限制,抛 WinError 206
        # ("文件名或扩展名太长")。改用 7z 的 `-x@<listfile>` 从文件读 exclude
        # 列表,把命令行长度恒定下来。
        # 注意:7z 的 list file 用 \r\n 行结束符,内部按 OEM/UTF-8 解析。
        # 我们的 SYMTYPE 路径都是 ASCII(pnpm 包名 + 数字版本),UTF-8 编码安全。
        sym_list_path = None
        if sym_members:
            sym_list_fd, sym_list_path = tempfile.mkstemp(suffix=".txt", prefix="oc_exclude_")
            with os.fdopen(sym_list_fd, "w", encoding="utf-8", newline="\r\n") as f:
                for sym in sym_members:
                    f.write(sym.name + "\n")
            cmd.append(f"-x@{sym_list_path}")

        # 心跳线程:每 5 秒扫一次 dest_path 文件数,让用户知道在动。
        # 7z 必须 -bso0 关 stdout 否则管道死锁,所以无法从子进程拿进度,只能外部数。
        import threading
        heartbeat_stop = threading.Event()

        def _heartbeat() -> None:
            # 只在 10s 后打一条提示,不再周期刷屏。
            # 用户怕的是"完全没动静",一条提示足够;持续刷会让人焦虑、且超出预计时间会有落差。
            if not heartbeat_stop.wait(10.0):
                if on_log:
                    on_log("  解压中...(共约 7-8 万文件,请耐心等待)")

        hb_thread = threading.Thread(target=_heartbeat, daemon=True)
        hb_thread.start()
        try:
            result2 = subprocess.run(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,  # 必须 DEVNULL,见上面注释
                timeout=1800,
                **windows_hidden_subprocess_kwargs(),
            )
        finally:
            heartbeat_stop.set()
            hb_thread.join(timeout=2)
        if sym_list_path:
            try:
                os.remove(sym_list_path)
            except OSError:
                pass
        # 7z 退出码: 0 = 成功, 1/2 = warnings(实际成功),其他才是真失败。
        # 我们的 tarball 含相对路径 SYMTYPE,7z 视为"危险链接"会全部拒绝并抛
        # warnings(rc=2),但所有非 SYMTYPE 文件都成功解压。SYMTYPE 后续由 Python
        # _extract_directory_symlink 单独重建,所以 rc=2 视为成功。
        if result2.returncode not in (0, 1, 2):
            if on_log:
                on_log(f"  7z 解 tar 真正失败,返回码 {result2.returncode}")
            raise RuntimeError("7z tar extract failed")
        if result2.returncode in (1, 2) and on_log:
            on_log(f"  7z 警告退出 (rc={result2.returncode}),SYMTYPE 已交由 Python 后处理")

        if on_log:
            on_log("7z.exe 解压完成")

    except (OSError, subprocess.SubprocessError, RuntimeError) as e:
        if on_log:
            on_log(f"7z 调用异常({e}),退化到 Python tarfile...")
        non_sym = [m for m in tar.getmembers() if not m.issym()]
        tar.extractall(str(dest_path), members=non_sym)
    finally:
        try:
            os.remove(tmp_tar_path)
        except OSError:
            pass


def _extract_directory_symlink(
    member: tarfile.TarInfo,
    dest_path: Path,
    on_log: Callable[[str], None] | None,
) -> None:
    """解压 SYMTYPE 成员,优先创建目录型 symlink,fallback 到 NTFS junction(Windows 专用)。

    pnpm workspace 在 Windows 上原本用 junction,我们打包时把它转成了 SYMTYPE 相对路径
    (linkname 形如 "../../../.."),解压时要确保还原成可用的目录链接。
    """
    normalized_name = member.name.replace("\\", "/")
    link_path = dest_path / normalized_name

    # 确保父目录存在
    link_path.parent.mkdir(parents=True, exist_ok=True)

    # 已存在则先删,避免 FileExistsError
    if link_path.exists() or link_path.is_symlink():
        try:
            if link_path.is_dir() and not link_path.is_symlink():
                # 不应该,但保险起见用 rmdir(空目录)而不是递归删
                link_path.rmdir()
            else:
                link_path.unlink()
        except OSError:
            pass

    # 第一招: os.symlink target_is_directory=True (Win10+ 开发者模式可免特权)
    try:
        if is_windows():
            os.symlink(member.linkname, link_path, target_is_directory=True)
        else:
            os.symlink(member.linkname, link_path)
        return
    except OSError as e:
        if not is_windows():
            # 非 Windows 平台无 fallback,直接报错
            if on_log:
                on_log(f"创建 symlink 失败 {link_path} -> {member.linkname}: {e}")
            raise

    # 第二招(仅 Windows): NTFS junction,无特权要求。
    # junction 必须用绝对路径,把相对 linkname 解析成绝对路径。
    #
    # 历史 bug(2026-05 修): 原先走 `cmd /c mklink /J` 子进程,3037 个 junction
    # 每个都要 fork cmd.exe + Defender 扫描,实测跑 15 分钟+。更恶劣的是
    # subprocess.run(timeout=5) 在 Windows 睡眠/时间跳变时会拿到负秒数立即
    # TimeoutExpired (报 "-916 seconds" 那种负数超时),整个解压流程崩溃。
    # 改用 _winapi.CreateJunction —— 直接调 NTFS 内核 API,无子进程,几乎零延迟。
    target_abs = (link_path.parent / member.linkname).resolve()
    try:
        import _winapi
        _winapi.CreateJunction(str(target_abs), str(link_path))
        return
    except (OSError, AttributeError, ImportError) as e:
        # _winapi.CreateJunction 是 CPython 内部 API,极端情况下可能不存在,
        # 退化到 mklink /J(单进程超时给到 30s,避免时钟跳变误判)
        target_abs_str = str(target_abs)
        try:
            subprocess.run(
                ["cmd", "/c", "mklink", "/J", str(link_path), target_abs_str],
                check=True,
                capture_output=True,
                timeout=30,
                **windows_hidden_subprocess_kwargs(),
            )
        except (OSError, subprocess.SubprocessError) as e2:
            if on_log:
                on_log(f"创建 junction 失败 {link_path} -> {target_abs}: {e2} (_winapi 兜底亦失败: {e})")
            raise
