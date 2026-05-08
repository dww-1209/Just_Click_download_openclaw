"""
OpenClaw 离线资源准备脚本

构建者使用：准备离线安装所需的全部资源。

使用方式:
    uv run python prepare_offline_resources.py --platform macos
    uv run python prepare_offline_resources.py --platform macos --source-dir ~/openclaw-cn

说明:
- 从 nodejs.org 下载 Node.js 预编译二进制包（tarball/zip）
- 从 npm registry（国内镜像优先）下载 pnpm npm tarball（.tgz，跨平台共用）
- 将 OpenClaw 预构建产物打包为 tar.gz（需先通过在线安装器或手动构建）
- 输出到 resources/{platform}/ 目录

注意：pnpm 的 npm tarball 输出到 resources/ 根目录，不区分平台，
      因为安装时统一通过 npm install -g 本地安装。
"""

from __future__ import annotations

import argparse
import os
import platform
import shutil
import sys
import tarfile
from pathlib import Path
from urllib.request import urlretrieve
from urllib.error import URLError


# 默认版本号
DEFAULT_NODEJS_VERSION = "22.14.0"
DEFAULT_PNPM_VERSION = "10.10.0"


def detect_platform() -> str:
    """检测当前平台。"""
    sys_platform = sys.platform
    machine = platform.machine().lower()
    if sys_platform == "win32":
        return "windows"
    if sys_platform == "darwin":
        return "macos"
    return "linux"


def detect_arch() -> str:
    """检测当前 CPU 架构。"""
    machine = platform.machine().lower()
    if machine in ("arm64", "aarch64"):
        return "arm64"
    if machine in ("x86_64", "amd64"):
        return "x64"
    return machine


def _download_with_progress(url: str, dest: Path) -> None:
    """下载文件并显示进度。"""
    print(f"下载: {url}")
    print(f"目标: {dest}")

    def _progress(block_num: int, block_size: int, total_size: int) -> None:
        downloaded = block_num * block_size
        if total_size > 0:
            percent = min(downloaded * 100 / total_size, 100)
            print(f"\r  进度: {percent:.1f}% ({downloaded // 1024 // 1024}MB / {total_size // 1024 // 1024}MB)", end="", flush=True)
        else:
            print(f"\r  已下载: {downloaded // 1024 // 1024}MB", end="", flush=True)

    try:
        urlretrieve(str(url), str(dest), reporthook=_progress)
        print()  # 换行
    except URLError as e:
        print(f"\n下载失败: {e}")
        raise


def download_nodejs(output_dir: Path, version: str, platform_name: str, arch: str) -> Path:
    """下载 Node.js 预编译二进制包。

    Returns:
        下载后的文件路径。
    """
    if platform_name == "macos":
        filename = f"node-v{version}-darwin-{arch}.tar.gz"
    elif platform_name == "linux":
        filename = f"node-v{version}-linux-{arch}.tar.xz"
    elif platform_name == "windows":
        filename = f"node-v{version}-win-{arch}.zip"
    else:
        raise ValueError(f"不支持的平台: {platform_name}")

    url = f"https://nodejs.org/dist/v{version}/{filename}"
    dest = output_dir / filename

    if dest.exists():
        print(f"Node.js 已存在，跳过下载: {dest}")
        return dest

    _download_with_progress(url, dest)
    print(f"Node.js 下载完成: {dest}")
    return dest


def download_pnpm(output_dir: Path, version: str, platform_name: str, arch: str) -> Path:
    """下载 pnpm npm tarball。

    使用 npm registry 的 .tgz 包，安装时通过 npm install -g 本地安装，
    无需平台相关的 standalone 二进制。

    Returns:
        下载后的文件路径（位于 resources/ 根目录，跨平台共用）。
    """
    # 统一输出到 resources/ 根目录，不区分平台
    resources_root = output_dir.parent
    dest = resources_root / f"pnpm-{version}.tgz"

    if dest.exists():
        print(f"pnpm 已存在，跳过下载: {dest}")
        return dest

    # 优先使用国内镜像
    mirrors = [
        f"https://registry.npmmirror.com/pnpm/-/pnpm-{version}.tgz",
        f"https://registry.npmjs.org/pnpm/-/pnpm-{version}.tgz",
    ]

    for url in mirrors:
        try:
            _download_with_progress(url, dest)
            print(f"pnpm 下载完成: {dest}")
            return dest
        except URLError as e:
            print(f"从 {url} 下载失败: {e}")
            continue

    raise RuntimeError(
        f"无法从任何镜像下载 pnpm npm tarball。请手动下载并放置到:\n"
        f"  https://registry.npmmirror.com/pnpm/-/pnpm-{version}.tgz\n"
        f"  -> {dest}"
    )


def pack_prebuilt(source_dir: Path, output_dir: Path, platform_name: str) -> Path:
    """将预构建产物打包为 tar.gz。

    Args:
        source_dir: OpenClaw 源码目录（含 node_modules 和 dist）。
        output_dir: 输出目录。
        platform_name: 平台名称，用于生成文件名。

    Returns:
        打包后的 tar.gz 文件路径。
    """
    if not source_dir.exists():
        raise FileNotFoundError(
            f"预构建产物目录不存在: {source_dir}\n"
            "请先通过在线安装器完成安装，或手动执行:\n"
            "  git clone https://gitee.com/OpenClaw-CN/openclaw-cn.git ~/openclaw-cn\n"
            "  cd ~/openclaw-cn && pnpm install && pnpm build"
        )

    # 检查关键目录是否存在
    node_modules = source_dir / "node_modules"
    if not node_modules.exists():
        print(f"警告: {source_dir}/node_modules 不存在，预构建产物可能不完整")

    output_file = output_dir / f"openclaw-prebuilt-{platform_name}.tar.gz"

    if output_file.exists():
        print(f"预构建产物包已存在，将覆盖: {output_file}")
        output_file.unlink()

    print(f"正在打包预构建产物...")
    print(f"  来源: {source_dir}")
    print(f"  目标: {output_file}")

    # 统计要打包的文件数（排除 .git）
    total_files = 0
    for root, dirs, files in os.walk(source_dir):
        if ".git" in dirs:
            dirs.remove(".git")
        total_files += len(files)
    print(f"  文件数（排除 .git）: {total_files}")

    packed = 0
    with tarfile.open(output_file, "w:gz") as tar:
        for item in source_dir.iterdir():
            if item.name == ".git":
                continue
            arcname = f"openclaw-cn/{item.name}"
            tar.add(item, arcname=arcname)
            if item.is_dir():
                for f in item.rglob("*"):
                    if f.is_file():
                        packed += 1
                        if packed % 5000 == 0:
                            print(f"\r  已打包: {packed}/{total_files}", end="", flush=True)
            else:
                packed += 1
                if packed % 5000 == 0:
                    print(f"\r  已打包: {packed}/{total_files}", end="", flush=True)

    print(f"\n预构建产物打包完成: {output_file}")

    # 显示大小
    size_mb = output_file.stat().st_size / (1024 * 1024)
    print(f"  大小: {size_mb:.1f} MB")

    return output_file


def main() -> None:
    """命令行入口。"""
    parser = argparse.ArgumentParser(
        description="OpenClaw 离线资源准备脚本",
        epilog="示例:\n"
               "  uv run python prepare_offline_resources.py --platform macos\n"
               "  uv run python prepare_offline_resources.py --platform macos --source-dir ~/openclaw-cn",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--platform",
        default=detect_platform(),
        choices=["macos", "windows", "linux"],
        help=f"目标平台 (默认: {detect_platform()})",
    )
    parser.add_argument(
        "--arch",
        default=detect_arch(),
        help=f"CPU 架构 (默认: {detect_arch()})",
    )
    parser.add_argument(
        "--output-dir",
        default=None,
        help="资源输出目录 (默认: resources/{platform})",
    )
    parser.add_argument(
        "--source-dir",
        default=str(Path.home() / "openclaw-cn"),
        help="OpenClaw 预构建产物来源目录 (默认: ~/openclaw-cn)",
    )
    parser.add_argument(
        "--nodejs-version",
        default=DEFAULT_NODEJS_VERSION,
        help=f"Node.js 版本 (默认: {DEFAULT_NODEJS_VERSION})",
    )
    parser.add_argument(
        "--pnpm-version",
        default=DEFAULT_PNPM_VERSION,
        help=f"pnpm standalone 版本 (默认: {DEFAULT_PNPM_VERSION})",
    )
    parser.add_argument(
        "--skip-nodejs",
        action="store_true",
        help="跳过 Node.js 下载",
    )
    parser.add_argument(
        "--skip-pnpm",
        action="store_true",
        help="跳过 pnpm 下载",
    )
    parser.add_argument(
        "--skip-prebuilt",
        action="store_true",
        help="跳过预构建产物打包",
    )

    args = parser.parse_args()

    platform_name = args.platform
    arch = args.arch
    output_dir = Path(args.output_dir) if args.output_dir else Path("resources") / platform_name
    source_dir = Path(args.source_dir)

    print("=" * 50)
    print("OpenClaw 离线资源准备工具")
    print("=" * 50)
    print()
    print(f"目标平台: {platform_name}")
    print(f"CPU 架构: {arch}")
    print(f"输出目录: {output_dir.resolve()}")
    print(f"预构建来源: {source_dir}")
    print()

    output_dir.mkdir(parents=True, exist_ok=True)

    # 1. 下载 Node.js
    if not args.skip_nodejs:
        try:
            download_nodejs(output_dir, args.nodejs_version, platform_name, arch)
            print()
        except Exception as e:
            print(f"Node.js 准备失败: {e}")
            sys.exit(1)
    else:
        print("跳过 Node.js 下载")

    # 2. 下载 pnpm
    if not args.skip_pnpm:
        try:
            download_pnpm(output_dir, args.pnpm_version, platform_name, arch)
            print()
        except Exception as e:
            print(f"pnpm 准备失败: {e}")
            sys.exit(1)
    else:
        print("跳过 pnpm 下载")

    # 3. 打包预构建产物
    if not args.skip_prebuilt:
        try:
            pack_prebuilt(source_dir, output_dir, platform_name)
            print()
        except Exception as e:
            print(f"预构建产物打包失败: {e}")
            sys.exit(1)
    else:
        print("跳过预构建产物打包")

    # 汇总
    print("=" * 50)
    print("资源准备完成")
    print("=" * 50)
    print()
    print(f"平台资源目录: {output_dir.resolve()}")
    for f in sorted(output_dir.iterdir()):
        size_mb = f.stat().st_size / (1024 * 1024)
        print(f"  {f.name}: {size_mb:.1f} MB")

    # 显示 resources/ 根目录下的 pnpm tarball
    resources_root = output_dir.parent
    pnpm_tgz = resources_root / f"pnpm-{args.pnpm_version}.tgz"
    if pnpm_tgz.exists():
        size_mb = pnpm_tgz.stat().st_size / (1024 * 1024)
        print(f"  pnpm-{args.pnpm_version}.tgz: {size_mb:.1f} MB (resources/ 根目录，跨平台共用)")

    print()
    print("下一步：")
    print(f"  uv run python build.py --offline --resources-dir {output_dir}")


if __name__ == "__main__":
    main()
