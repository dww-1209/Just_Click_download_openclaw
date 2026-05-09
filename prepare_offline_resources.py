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
import subprocess
import sys
import tarfile
from pathlib import Path
from urllib.request import urlretrieve
from urllib.error import URLError


# 默认版本号
DEFAULT_NODEJS_VERSION = "22.14.0"
DEFAULT_PNPM_VERSION = "10.10.0"
DEFAULT_GIT_VERSION = "2.54.0"  # MinGit for Windows


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


def download_git(output_dir: Path, version: str, platform_name: str, arch: str) -> Path | None:
    """下载/准备内部 git 资源。

    Windows：从 GitHub releases 下载 MinGit 便携版（zip 格式）。
    macOS：内部 git 需要手动从 Xcode CLT 复制，本函数仅做存在性检查。
    Linux：暂不支持。

    Returns:
        下载后的文件路径，或 None（如果平台不需要/不支持）。
    """
    if platform_name == "windows":
        filename = f"MinGit-{version}-64-bit.zip"
        dest = output_dir / filename

        if dest.exists():
            print(f"MinGit 已存在，跳过下载: {dest}")
            return dest

        # GitHub releases 为主源，npmmirror 为备用镜像
        mirrors = [
            f"https://github.com/git-for-windows/git/releases/download/v{version}.windows.1/{filename}",
        ]
        for url in mirrors:
            try:
                _download_with_progress(url, dest)
                print(f"MinGit 下载完成: {dest}")
                return dest
            except URLError as e:
                print(f"从 {url} 下载失败: {e}")
                continue

        print(
            f"无法自动下载 MinGit。请手动下载并放置到:\n"
            f"  https://github.com/git-for-windows/git/releases/download/v{version}.windows.1/{filename}\n"
            f"  -> {dest}"
        )
        return None

    if platform_name == "macos":
        git_tgz = output_dir / f"git-macos-{arch}.tar.gz"
        if git_tgz.exists():
            print(f"内部 git 已存在: {git_tgz}")
            return git_tgz

        # 自动检测 Xcode CLT 并打包内部 git
        xcode_git = Path("/Library/Developer/CommandLineTools/usr/bin/git")
        xcode_git_core = Path("/Library/Developer/CommandLineTools/usr/libexec/git-core")

        if xcode_git.is_file() and xcode_git_core.is_dir():
            print(f"检测到 Xcode CLT，正在自动打包内部 git...")

            import tempfile
            with tempfile.TemporaryDirectory(prefix="git-macos-") as tmpdir:
                git_stage = Path(tmpdir) / f"git-macos-{arch}"
                bin_dir = git_stage / "bin"
                libexec_dir = git_stage / "libexec"

                bin_dir.mkdir(parents=True)
                libexec_dir.mkdir(parents=True)

                # 复制 git 二进制
                shutil.copy2(xcode_git, bin_dir / "git")
                print(f"  复制: {xcode_git} -> {bin_dir}/git")

                # 复制 git-core 辅助程序
                shutil.copytree(xcode_git_core, libexec_dir / "git-core", dirs_exist_ok=True)
                print(f"  复制: {xcode_git_core} -> {libexec_dir}/git-core")

                # 如有 lib/ 目录也一并复制（某些 git 功能需要动态库）
                xcode_lib = Path("/Library/Developer/CommandLineTools/usr/lib")
                if xcode_lib.is_dir():
                    # 只复制与 git 相关的动态库
                    git_stage_lib = git_stage / "lib"
                    git_stage_lib.mkdir(exist_ok=True)
                    for lib_file in xcode_lib.glob("libgit*"):
                        shutil.copy2(lib_file, git_stage_lib)
                        print(f"  复制: {lib_file} -> {git_stage_lib}/")

                # 打包
                print(f"  正在打包: {git_tgz}")
                try:
                    subprocess.run(
                        ["tar", "czf", str(git_tgz), "-C", tmpdir, f"git-macos-{arch}"],
                        check=True,
                        capture_output=True,
                    )
                    size_mb = git_tgz.stat().st_size / (1024 * 1024)
                    print(f"内部 git 打包完成: {git_tgz} ({size_mb:.1f} MB)")
                    return git_tgz
                except subprocess.CalledProcessError as e:
                    print(f"打包失败: {e}")
                    if git_tgz.exists():
                        git_tgz.unlink()
        else:
            print(
                f"未检测到 Xcode CLT（{xcode_git} 不存在）。\n"
                f"请在已安装 Xcode Command Line Tools 的 Mac 上运行此脚本，或手动准备:\n"
                f"  1. mkdir -p /tmp/git-macos-{arch}/bin /tmp/git-macos-{arch}/libexec\n"
                f"  2. cp /Library/Developer/CommandLineTools/usr/bin/git /tmp/git-macos-{arch}/bin/\n"
                f"  3. cp -R /Library/Developer/CommandLineTools/usr/libexec/git-core /tmp/git-macos-{arch}/libexec/\n"
                f"  4. cd /tmp && tar czf git-macos-{arch}.tar.gz git-macos-{arch}/\n"
                f"  5. mv git-macos-{arch}.tar.gz {output_dir}/"
            )
        return None

    # Linux 暂不支持
    return None


def _is_junction(path: Path) -> bool:
    """检测 Windows junction（重解析点）。

    pnpm workspace 在 Windows 上创建 junction 而非 symlink，
    pathlib.Path.is_symlink() 对 junction 返回 False。
    """
    if sys.platform != "win32":
        return False
    try:
        st = os.lstat(path)
        return bool(st.st_file_attributes & os.stat.FILE_ATTRIBUTE_REPARSE_POINT)
    except (OSError, AttributeError):
        return False


def _add_to_tar(tar: tarfile.TarFile, path: Path, arcname: str) -> None:
    """递归添加文件/目录到 tar，跳过 symlink/junction 目录避免循环。

    pnpm workspace 在 Windows 上使用 junction 链接本地包，若当作普通目录
    递归进入会导致无限嵌套（如 extensions/bluebubbles/node_modules/openclaw/...）。
    """
    if path.is_symlink() or _is_junction(path):
        # symlink（含 junction）：只记录链接本身，绝不跟随
        tar.add(path, arcname=arcname)
        return

    if path.is_dir():
        # 添加目录本身，但不递归（recursive=False）
        tar.add(path, arcname=arcname, recursive=False)
        try:
            for child in path.iterdir():
                if child.name == ".git":
                    continue
                _add_to_tar(tar, child, f"{arcname}/{child.name}")
        except OSError as e:
            print(f"  警告: 无法访问 {path}: {e}")
    else:
        tar.add(path, arcname=arcname)


def _pack_with_system_tar(source_dir: Path, output_file: Path) -> bool:
    """尝试使用系统 tar 命令打包（MSYS2/Git Bash tar 能正确处理 Windows junction）。

    Returns:
        True 如果打包成功。
    """
    tar_cmd = shutil.which("tar")
    if not tar_cmd:
        return False

    try:
        result = subprocess.run(
            [
                tar_cmd,
                "-czf", str(output_file),
                "-C", str(source_dir),
                "--exclude=.git",
                ".",
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False


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

    # Windows 上优先使用系统 tar（MSYS2/Git Bash），避免 Python tarfile
    # 将 junction 误当作普通目录递归进入导致的路径爆炸。
    if sys.platform == "win32" and _pack_with_system_tar(source_dir, output_file):
        print(f"  使用系统 tar 打包完成")
    else:
        # 回退到 Python tarfile，手动遍历并跳过 symlink 目录
        print(f"  使用 Python tarfile 打包（跳过 symlink 目录）...")
        with tarfile.open(output_file, "w:gz") as tar:
            for item in source_dir.iterdir():
                if item.name == ".git":
                    continue
                _add_to_tar(tar, item, f"openclaw-cn/{item.name}")

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
    parser.add_argument(
        "--skip-git",
        action="store_true",
        help="跳过内部 git 下载/检查",
    )
    parser.add_argument(
        "--git-version",
        default=DEFAULT_GIT_VERSION,
        help=f"MinGit 版本 (默认: {DEFAULT_GIT_VERSION})",
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

    # 3. 下载/检查内部 git
    if not args.skip_git:
        try:
            download_git(output_dir, args.git_version, platform_name, arch)
            print()
        except Exception as e:
            print(f"内部 git 准备失败: {e}")
            # git 下载失败不阻塞流程（部分平台不需要）
    else:
        print("跳过内部 git 下载")

    # 4. 打包预构建产物
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
