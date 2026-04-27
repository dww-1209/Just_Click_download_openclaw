#!/usr/bin/env python3
"""
OpenClaw 安装器打包脚本

使用方法:
    uv run python build.py

打包完成后，可执行文件位于 dist/ 目录

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
    
    优先使用 uv run，如果没有 uv 则直接使用 pyinstaller
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
    """清理之前的构建文件"""
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
):
    """打包单个程序
    
    Args:
        output_dir: 输出目录
        entry_file: 入口 py 文件
        app_name: 程序名称（不含扩展名）
        bundle_id: macOS bundle identifier
        launcher_script_name: macOS .command 脚本文件名（不含扩展名）
        launcher_display_name: .command 脚本中的显示名称
    """
    cmd = get_pyinstaller_cmd()
    args = [
        "--onefile",
        "--windowed",
        "--name", app_name,
        "--clean",
        "--noconfirm",
        "--distpath", output_dir,
    ]

    # assets
    assets_dir = "assets"
    if os.path.exists(assets_dir):
        sep = ";" if is_windows() else ":"
        args.extend(["--add-data", f"{assets_dir}{sep}{assets_dir}"])

    # Windows
    if is_windows():
        manifest_path = "app.manifest"
        if os.path.exists(manifest_path):
            args.extend(["--manifest", manifest_path])
        icon_path = "assets/icon.ico"
        if os.path.exists(icon_path):
            args.extend(["--icon", icon_path])

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

    # macOS
    elif is_macos():
        args.extend(["--osx-bundle-identifier", bundle_id])
        icon_path = "assets/icon.icns"
        if os.path.exists(icon_path):
            args.extend(["--icon", icon_path])

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


def build(output_dir: str = None):
    """使用 PyInstaller 打包安装器 + 卸载器"""
    if output_dir is None:
        output_dir = "dist"
    os.makedirs(output_dir, exist_ok=True)

    print("=" * 50)
    print("OpenClaw 打包工具")
    print("=" * 50)
    print()
    print(f"输出目录: {os.path.abspath(output_dir)}")
    print()

    import platform
    print(f"操作系统: {platform.system()}")
    print(f"平台: {sys.platform}")
    print(f"架构: {platform.machine()}")
    print()

    # 1. 打包安装器
    ok1 = _build_single(
        output_dir=output_dir,
        entry_file="main.py",
        app_name="OpenClaw安装器",
        bundle_id="com.openclaw.installer",
        launcher_script_name="双击运行-OpenClaw安装器",
        launcher_display_name="OpenClaw 安装器",
    )

    # 2. 打包卸载器
    ok2 = _build_single(
        output_dir=output_dir,
        entry_file="uninstall_main.py",
        app_name="OpenClaw卸载工具",
        bundle_id="com.openclaw.uninstaller",
        launcher_script_name="双击运行-OpenClaw卸载工具",
        launcher_display_name="OpenClaw 卸载工具",
    )

    print()
    print("=" * 50)
    if ok1 and ok2:
        print("全部打包成功！")
    elif ok1:
        print("安装器打包成功，卸载器打包失败")
    elif ok2:
        print("卸载器打包成功，安装器打包失败")
    else:
        print("打包失败")
        sys.exit(1)
    print("=" * 50)
    print()

    # 输出文件列表和大小
    for app_name in ["OpenClaw安装器", "OpenClaw卸载工具"]:
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
    """主函数"""
    import argparse
    
    parser = argparse.ArgumentParser(
        description="OpenClaw 安装器打包工具",
        epilog="示例: uv run python build.py"
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
    
    args = parser.parse_args()
    
    if args.clean_only:
        clean_build()
        return
    
    if not args.no_clean:
        clean_build()
    
    build(output_dir=args.output)


if __name__ == "__main__":
    main()
