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


def build(output_dir: str = None):
    """使用 PyInstaller 打包
    
    Args:
        output_dir: 自定义输出目录，默认为 dist/
    """
    
    # 设置输出目录
    if output_dir is None:
        output_dir = "dist"
    
    # 确保输出目录存在
    os.makedirs(output_dir, exist_ok=True)
    
    print("=" * 50)
    print("OpenClaw 安装器打包工具")
    print("=" * 50)
    print()
    print(f"输出目录: {os.path.abspath(output_dir)}")
    print()
    
    # 显示系统信息
    import platform
    print(f"操作系统: {platform.system()}")
    print(f"平台: {sys.platform}")
    print(f"架构: {platform.machine()}")
    print(f"64位: {is_64bit()}")
    print()
    
    # 构建 PyInstaller 命令
    cmd = get_pyinstaller_cmd()
    
    # 添加参数
    args = [
        "--onefile",  # 打包成单个可执行文件
        "--windowed",  # 窗口模式（不显示控制台）
        "--name", "OpenClaw安装器",
        "--clean",  # 清理临时文件
        "--noconfirm",  # 不提示确认
        "--distpath", output_dir,  # 自定义输出目录
    ]

    # 将 assets 目录打包进可执行文件
    assets_dir = "assets"
    if os.path.exists(assets_dir):
        separator = ";" if is_windows() else ":"
        args.extend(["--add-data", f"{assets_dir}{separator}{assets_dir}"])
        print(f"  - 包含资源目录: {assets_dir}")
    else:
        print(f"  [提示] 资源目录不存在: {assets_dir}")

    # Windows 特定配置
    if is_windows():
        print("配置: Windows 模式")
        
        # 添加 manifest 文件以请求管理员权限
        manifest_path = "app.manifest"
        if os.path.exists(manifest_path):
            args.extend(["--manifest", manifest_path])
            print(f"  - 使用 manifest: {manifest_path}")
        else:
            print(f"  [警告] manifest 文件不存在: {manifest_path}")
        
        # 添加图标
        icon_path = "assets/icon.ico"
        if os.path.exists(icon_path):
            args.extend(["--icon", icon_path])
            print(f"  - 使用图标: {icon_path}")
        else:
            print(f"  [提示] 图标不存在: {icon_path}（使用默认图标）")
    
    # macOS 特定配置
    elif is_macos():
        print("配置: macOS 模式")
        
        args.extend([
            "--osx-bundle-identifier", "com.openclaw.installer",
        ])
        
        # 添加图标
        icon_path = "assets/icon.icns"
        if os.path.exists(icon_path):
            args.extend(["--icon", icon_path])
            print(f"  - 使用图标: {icon_path}")
        else:
            print(f"  [提示] 图标不存在: {icon_path}（使用默认图标）")
    
    else:
        print(f"配置: Linux/其他模式 ({sys.platform})")
    
    # 主入口文件
    args.append("main.py")
    
    # 组合完整命令
    full_cmd = cmd + args
    
    print()
    print("执行命令:")
    print(" ".join(full_cmd))
    print()
    
    # 执行打包
    result = subprocess.run(full_cmd)
    
    if result.returncode == 0:
        print()
        print("=" * 50)
        print("打包成功！")
        print("=" * 50)
        
        if is_windows():
            exe_name = "OpenClaw安装器.exe"
        elif is_macos():
            exe_name = "OpenClaw安装器.app"
        else:
            exe_name = "OpenClaw安装器"
        
        exe_path = os.path.join(output_dir, exe_name)
        
        if os.path.exists(exe_path):
            if is_macos() and os.path.isdir(exe_path):
                # macOS .app bundle: 计算整个目录大小
                total_size = sum(
                    os.path.getsize(os.path.join(dirpath, f))
                    for dirpath, _, filenames in os.walk(exe_path)
                    for f in filenames
                )
                size_mb = total_size / (1024 * 1024)
            else:
                size_mb = os.path.getsize(exe_path) / (1024 * 1024)
            print(f"输出文件: {exe_path}")
            print(f"文件大小: {size_mb:.1f} MB")
            print()
            print("提示:")
            print("- 将此文件提供给用户即可")
            if is_windows():
                print("- Windows 用户双击运行会自动请求管理员权限")
            elif is_macos():
                # 删除 PyInstaller 额外生成的 Unix 可执行文件，只保留 .app
                unix_exe = os.path.join(output_dir, "OpenClaw安装器")
                if os.path.exists(unix_exe) and not os.path.isdir(unix_exe):
                    os.remove(unix_exe)
                    print("- 已清理多余的 Unix 可执行文件，仅保留 .app")

                # 生成辅助启动脚本，帮助小白用户绕过 Gatekeeper
                launcher_name = "双击运行-OpenClaw安装器.command"
                launcher_path = os.path.join(output_dir, launcher_name)
                launcher_script = '''#!/bin/bash
# OpenClaw 安装器 macOS 启动脚本
# 作用：自动移除 Gatekeeper 隔离属性并启动程序

cd "$(dirname "$0")"
APP_BUNDLE="./OpenClaw安装器.app"
APP_EXE="$APP_BUNDLE/Contents/MacOS/OpenClaw安装器"

if [ ! -f "$APP_EXE" ]; then
    echo "错误：找不到 OpenClaw安装器.app，请确保本文件与程序在同一文件夹内。"
    read -n 1 -s -r -p "按任意键退出..."
    exit 1
fi

# 移除隔离属性（解决"无法打开"提示）
if xattr -p com.apple.quarantine "$APP_BUNDLE" >/dev/null 2>&1; then
    echo "正在移除安全隔离属性..."
    xattr -rd com.apple.quarantine "$APP_BUNDLE" 2>/dev/null || true
fi

echo "正在启动 OpenClaw 安装器..."
"$APP_EXE"
'''
                with open(launcher_path, 'w', encoding='utf-8') as f:
                    f.write(launcher_script)
                os.chmod(launcher_path, 0o755)
                print(f"- macOS 辅助脚本已生成: {launcher_name}")
                print("  将 dist/ 文件夹打包发给用户，让用户先双击 .command 文件即可")
        else:
            print(f"[警告] 输出文件不存在: {exe_path}")
            print("请检查 dist/ 目录")
    else:
        print()
        print("=" * 50)
        print("打包失败")
        print("=" * 50)
        print()
        print("可能的原因:")
        print("1. PyInstaller 未安装: uv add pyinstaller --dev")
        print("2. 代码语法错误")
        print("3. 缺少依赖")
        sys.exit(1)


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
