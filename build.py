#!/usr/bin/env python3
"""
OpenClaw 安装器打包脚本

一次构建同时产出两个桌面程序：安装器 + 卸载工具。
使用 PyInstaller 打包为单文件可执行程序（--onefile --windowed），
并针对不同平台做特殊处理：
- Windows：包含 OpenSSL DLL、禁用 UPX 压缩
- macOS：生成 .command 辅助启动脚本绕过 Gatekeeper

使用方法:
    uv run python build.py

说明:
- sys.platform == "win32" 适用于所有 Windows（包括 64 位）
- 64 位检测使用 platform.machine() == "AMD64"
"""

import subprocess
import sys
import os
import shutil
from pathlib import Path


def is_windows() -> bool:
    """检查是否为 Windows 系统

    注意: sys.platform 在 Windows 上总是返回 "win32"，
    无论 32 位还是 64 位系统。这是 Python 的历史遗留命名。
    """
    return sys.platform == "win32"


def is_macos() -> bool:
    """检查是否为 macOS 系统"""
    return sys.platform == "darwin"


def is_64bit() -> bool:
    """检查是否为 64 位系统"""
    import platform
    return platform.machine().endswith('64')


def get_pyinstaller_cmd() -> list:
    """获取 PyInstaller 命令

    优先使用 uv run，如果没有 uv 则直接使用 pyinstaller，
    最后 fallback 到 python -m PyInstaller。
    """
    # 检查是否可以使用 uv
    uv_path = shutil.which("uv")
    if uv_path:
        return [uv_path, "run", "pyinstaller"]

    # 检查 pyinstaller 是否可用
    pyinstaller_path = shutil.which("pyinstaller")
    if pyinstaller_path:
        return [pyinstaller_path]

    # 都没找到，尝试用 python -m
    return [sys.executable, "-m", "PyInstaller"]


def clean_build():
    """清理之前的构建文件

    删除 build/、dist/、所有 __pycache__ 目录以及 .spec 文件，
    确保下次构建从干净状态开始。
    """
    dirs_to_remove = ['build', 'dist']
    for dir_name in dirs_to_remove:
        if os.path.exists(dir_name):
            print(f"清理 {dir_name}/...")
            shutil.rmtree(dir_name)

    # 清理 __pycache__
    for pycache in Path('.').rglob('__pycache__'):
        if pycache.exists():
            shutil.rmtree(pycache)

    # 清理 .spec 文件
    for spec_file in Path('.').glob('*.spec'):
        if spec_file.exists():
            spec_file.unlink()

    print("清理完成")


def _build_single(
    output_dir: str,
    entry_file: str,
    app_name: str,
    bundle_id: str,
    launcher_script_name: str = None,
    launcher_display_name: str = None,
    add_data: list[str] | None = None,
):
    """打包单个程序

    根据当前平台自动添加平台特定的 PyInstaller 参数：
    - Windows：包含 app.manifest、OpenSSL DLL、禁用 UPX
    - macOS：设置 bundle identifier，构建后删除 Unix 可执行文件并生成 .command 脚本

    Args:
        output_dir: 输出目录
        entry_file: 入口 py 文件
        app_name: 程序名称（不含扩展名）
        bundle_id: macOS bundle identifier
        launcher_script_name: macOS .command 脚本文件名（不含扩展名）
        launcher_display_name: .command 脚本中的显示名称
        add_data: 额外打包的资源目录列表（PyInstaller --add-data）。
                  每个元素格式为 "SRC:DEST"（macOS/Linux）或 "SRC;DEST"（Windows）
    """
    cmd = get_pyinstaller_cmd()
    sep = ";" if is_windows() else ":"
    args = [
        "--onefile",
        "--windowed",
        "--name", app_name,
        "--clean",
        "--noconfirm",
        "--distpath", output_dir,
    ]

    # 离线资源打包
    if add_data:
        for data_spec in add_data:
            args.extend(["--add-data", data_spec])

    # Windows
    if is_windows():
        manifest_path = "app.manifest"
        if os.path.exists(manifest_path):
            args.extend(["--manifest", manifest_path])

        # 修复：PyInstaller 默认不会打包 OpenSSL DLL，导致目标机器上 _ssl 加载失败
        # 自动检测并包含 libssl / libcrypto DLL
        try:
            import _ssl
            ssl_dir = os.path.dirname(_ssl.__file__)
            sep = ";"
            for dll_name in ["libssl-3-x64.dll", "libcrypto-3-x64.dll"]:
                dll_path = os.path.join(ssl_dir, dll_name)
                if os.path.exists(dll_path):
                    args.extend(["--add-binary", f"{dll_path}{sep}."])
                    print(f"  包含 SSL DLL: {dll_name}")
        except Exception:
            pass

        # 降低杀毒软件误报率（UPX 压缩会被部分杀软误报）
        args.append("--noupx")

    # macOS
    elif is_macos():
        args.extend(["--osx-bundle-identifier", bundle_id])

    args.append(entry_file)
    full_cmd = cmd + args

    print()
    print(f"--- 正在打包: {app_name} ---")
    print(" ".join(full_cmd))
    print()

    result = subprocess.run(full_cmd)

    if result.returncode != 0:
        print(f"[错误] {app_name} 打包失败")
        return False

    # macOS 后处理
    if is_macos():
        # 删除 PyInstaller 额外生成的 Unix 可执行文件
        unix_exe = os.path.join(output_dir, app_name)
        if os.path.exists(unix_exe) and not os.path.isdir(unix_exe):
            os.remove(unix_exe)

        # 生成辅助启动脚本
        if launcher_script_name and launcher_display_name:
            launcher_path = os.path.join(output_dir, f"{launcher_script_name}.command")
            script = f'''#!/bin/bash
# {launcher_display_name} macOS 启动脚本
# 作用：自动移除 Gatekeeper 隔离属性并启动程序

cd "$(dirname "$0")"
APP_BUNDLE="./{app_name}.app"
APP_EXE="$APP_BUNDLE/Contents/MacOS/{app_name}"

if [ ! -f "$APP_EXE" ]; then
    echo "错误：找不到 {app_name}.app，请确保本文件与程序在同一文件夹内。"
    read -n 1 -s -r -p "按任意键退出..."
    exit 1
fi

if xattr -p com.apple.quarantine "$APP_BUNDLE" >/dev/null 2>&1; then
    echo "正在移除安全隔离属性..."
    xattr -rd com.apple.quarantine "$APP_BUNDLE" 2>/dev/null || true
fi

echo "正在启动 {launcher_display_name}..."
"$APP_EXE"
'''
            with open(launcher_path, 'w', encoding='utf-8') as f:
                f.write(script)
            os.chmod(launcher_path, 0o755)

    return True


def build(output_dir: str = None, offline: bool = False, resources_dir: str = None):
    """使用 PyInstaller 打包安装器 + 卸载器

    依次调用 _build_single 打包两个程序，构建完成后输出文件大小和平台提示。
    任一失败时会返回错误码 1。

    Args:
        output_dir: 输出目录
        offline: 是否构建离线版安装器
        resources_dir: 离线资源目录路径，离线构建时通过 --add-data 打包
    """
    if output_dir is None:
        output_dir = "dist"
    os.makedirs(output_dir, exist_ok=True)

    # 自动检测当前平台的离线资源目录
    auto_resources_dir = None
    platform_name = "windows" if is_windows() else ("macos" if is_macos() else "linux")
    candidate = f"resources/{platform_name}"
    if os.path.isdir(candidate) and any(os.scandir(candidate)):
        auto_resources_dir = candidate

    # 显式参数优先，未指定时回退到自动检测
    if not offline and auto_resources_dir:
        offline = True
        resources_dir = auto_resources_dir
    elif offline and not resources_dir and auto_resources_dir:
        resources_dir = auto_resources_dir

    print("=" * 50)
    if offline:
        print("OpenClaw 离线打包工具")
    else:
        print("OpenClaw 打包工具")
    print("=" * 50)
    print()
    print(f"输出目录: {os.path.abspath(output_dir)}")
    if offline and resources_dir:
        print(f"离线资源: {os.path.abspath(resources_dir)}")
    print()

    import platform
    print(f"操作系统: {platform.system()}")
    print(f"平台: {sys.platform}")
    print(f"架构: {platform.machine()}")
    print()

    # 1. 打包在线版安装器（始终构建）
    sep = ";" if is_windows() else ":"
    add_data_online = []
    native_cache_dir = "resources/native-cache"
    if os.path.isdir(native_cache_dir):
        add_data_online.append(f"{native_cache_dir}{sep}resources/native-cache")

    # macOS 在线版自带 git，避免 Xcode CLT 弹窗
    # Node.js 由在线安装器从网络镜像下载，不打包以减小体积
    if is_macos():
        for git_tgz in Path("resources/macos").glob("git-*.tar.gz"):
            add_data_online.append(f"{git_tgz}{sep}resources/macos")

    ok_online = _build_single(
        output_dir=output_dir,
        entry_file="launch_installer.py",
        app_name="OpenClaw安装器",
        bundle_id="com.openclaw.installer",
        launcher_script_name="双击运行-OpenClaw安装器",
        launcher_display_name="OpenClaw 安装器",
        add_data=add_data_online,
    )

    # 2. 打包离线版安装器（资源存在时额外构建）
    ok_offline = True
    if offline and resources_dir and os.path.isdir(resources_dir):
        add_data_offline = []
        # 保持 resources/{platform} 的目录结构，与 _resolve_resource_dir 期望一致
        platform_name = os.path.basename(resources_dir)
        add_data_offline.append(f"{resources_dir}{sep}resources/{platform_name}")
        # pnpm npm tarball 在 resources/ 根目录，跨平台共用，也需要打包
        for pnpm_tgz in Path("resources").glob("pnpm-*.tgz"):
            add_data_offline.append(f"{pnpm_tgz}{sep}resources")
        # 离线版自带 git（macOS 避免 Xcode CLT 弹窗，Windows 避免依赖系统 git）
        for git_tgz in Path(resources_dir).glob("git-*.tar.gz"):
            add_data_offline.append(f"{git_tgz}{sep}resources/{platform_name}")
        for git_zip in Path(resources_dir).glob("git-*.zip"):
            add_data_offline.append(f"{git_zip}{sep}resources/{platform_name}")
        for mingit_zip in Path(resources_dir).glob("MinGit-*.zip"):
            add_data_offline.append(f"{mingit_zip}{sep}resources/{platform_name}")
        ok_offline = _build_single(
            output_dir=output_dir,
            entry_file="launch_installer_offline.py",
            app_name="OpenClaw离线安装器",
            bundle_id="com.openclaw.installer.offline",
            launcher_script_name="双击运行-OpenClaw离线安装器",
            launcher_display_name="OpenClaw 离线安装器",
            add_data=add_data_offline,
        )

    # 3. 打包卸载器
    ok_uninstall = _build_single(
        output_dir=output_dir,
        entry_file="launch_uninstaller.py",
        app_name="OpenClaw卸载工具",
        bundle_id="com.openclaw.uninstaller",
        launcher_script_name="双击运行-OpenClaw卸载工具",
        launcher_display_name="OpenClaw 卸载工具",
    )

    print()
    print("=" * 50)
    results = []
    if ok_online:
        results.append("在线安装器")
    if ok_offline:
        results.append("离线安装器")
    if ok_uninstall:
        results.append("卸载工具")

    if len(results) == 3:
        print("全部打包成功！")
    elif results:
        print(f"部分打包成功: {', '.join(results)}")
    else:
        print("打包失败")
        sys.exit(1)
    print("=" * 50)
    print()

    # 输出文件列表和大小
    app_names = ["OpenClaw安装器"]
    if offline and resources_dir and os.path.isdir(resources_dir):
        app_names.append("OpenClaw离线安装器")
    app_names.append("OpenClaw卸载工具")
    for app_name in app_names:
        if is_macos():
            exe_path = os.path.join(output_dir, f"{app_name}.app")
        elif is_windows():
            exe_path = os.path.join(output_dir, f"{app_name}.exe")
        else:
            exe_path = os.path.join(output_dir, app_name)

        if os.path.exists(exe_path):
            if is_macos() and os.path.isdir(exe_path):
                total_size = sum(
                    os.path.getsize(os.path.join(dirpath, f))
                    for dirpath, _, filenames in os.walk(exe_path)
                    for f in filenames
                )
                size_mb = total_size / (1024 * 1024)
            else:
                size_mb = os.path.getsize(exe_path) / (1024 * 1024)
            print(f"  {app_name}: {size_mb:.1f} MB")

    if is_macos():
        print()
        print("macOS 提示:")
        print("- 已生成 .command 辅助脚本，双击可绕过 Gatekeeper")
        print("- 将 dist/ 文件夹打包发给用户即可")


def main():
    """命令行入口：解析参数并执行打包或清理"""
    import argparse

    parser = argparse.ArgumentParser(
        description="OpenClaw 安装器打包工具",
        epilog="示例: uv run python build.py\n"
                "      uv run python build.py --offline --resources-dir resources/macos"
    )
    parser.add_argument(
        "--clean-only",
        action="store_true",
        help="仅清理构建文件",
    )
    parser.add_argument(
        "--no-clean",
        action="store_true",
        help="打包前不清理",
    )
    parser.add_argument(
        "--output", "-o",
        default="dist",
        help="输出目录 (默认: dist)",
    )
    parser.add_argument(
        "--offline",
        action="store_true",
        help="构建离线版安装器（需配合 --resources-dir）",
    )
    parser.add_argument(
        "--resources-dir",
        default=None,
        help="离线资源目录路径，离线构建时通过 --add-data 打包到安装器中",
    )

    args = parser.parse_args()

    if args.clean_only:
        clean_build()
        return

    if not args.no_clean:
        clean_build()

    build(output_dir=args.output, offline=args.offline, resources_dir=args.resources_dir)


if __name__ == "__main__":
    main()
