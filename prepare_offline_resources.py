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
import posixpath
import shutil
import stat
import subprocess
import sys
import tarfile
import time
from pathlib import Path
from urllib.request import urlretrieve
from urllib.error import URLError


# 默认版本号
DEFAULT_NODEJS_VERSION = "22.14.0"
DEFAULT_PNPM_VERSION = "10.10.0"
DEFAULT_GIT_VERSION = "2.54.0"  # 仅作历史参考；Windows 完整版 Git 资源需手动打包,见 README §4


def detect_platform() -> str:
    """检测当前平台（仅支持 windows / macos）。"""
    sys_platform = sys.platform
    if sys_platform == "win32":
        return "windows"
    if sys_platform == "darwin":
        return "macos"
    raise RuntimeError(f"不支持的平台: {sys_platform}（仅支持 Windows / macOS）")


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

    Windows：检查是否已存在 git-*.zip（手动准备的完整版 Git for Windows 便携包），
            不再自动下载 MinGit（功能受限,且与项目期望的完整布局不一致）。
    macOS：内部 git 需要手动从 Xcode CLT 复制，本函数仅做存在性检查。

    Returns:
        已存在的 zip 路径,或 None(未找到/不需要/不支持)。
    """
    if platform_name == "windows":
        # 1) 优先复用已存在的 git-*.zip（支持手动打包的任意文件名,兼容 README §4 的手动流程）
        existing = sorted(output_dir.glob("git-*.zip"))
        if existing:
            print(f"已检测到 Windows git 资源: {existing[0].name}")
            return existing[0]

        # 2) 自动从系统 Git for Windows 安装目录打包，避免手动操作
        git_zip = output_dir / f"git-windows-{arch}.zip"
        # shutil.which 可能返回 mingw64/bin/git.exe(纯二进制目录),向上两级到 mingw64
        # 找不到 cmd/git.exe。要的是完整 Git for Windows 安装根(含 cmd/、mingw64/、usr/)。
        # 解析顺序:先尝试 cmd/git.exe(完整版根目录的入口);失败再向上探测 git_root。
        git_exe = shutil.which("git.exe", path=os.environ.get("PATH", ""))
        # 如果 which 命中的是 mingw64/bin/git.exe,向上 3 级才是根目录
        # (mingw64/bin -> mingw64 -> Git/);命中 cmd/git.exe 则向上 2 级到 Git/。
        candidates = []
        if git_exe:
            git_exe_path = Path(git_exe).resolve()
            # 向上探测 1-4 级,找包含 cmd/git.exe 的根目录
            cur = git_exe_path.parent
            for _ in range(4):
                if (cur / "cmd" / "git.exe").is_file() and (cur / "mingw64").is_dir():
                    candidates.append(cur)
                    break
                cur = cur.parent
        # 兜底:常见 Git for Windows 安装路径
        for fallback in [r"C:\Program Files\Git", r"C:\Program Files (x86)\Git"]:
            fb = Path(fallback)
            if fb.is_dir() and (fb / "cmd" / "git.exe").is_file() and (fb / "mingw64").is_dir():
                if fb not in candidates:
                    candidates.append(fb)

        if candidates:
            git_root = candidates[0]
            git_exe_path = git_root / "cmd" / "git.exe"
            expected_git = git_exe_path

            if expected_git.is_file():
                print(f"检测到系统 Git: {git_root}")
                print(f"正在打包内部 git...")

                import tempfile
                with tempfile.TemporaryDirectory(prefix="git-win-") as tmpdir:
                    stage = Path(tmpdir) / f"git-windows-{arch}"

                    # 复制必要目录(完整版 Git for Windows，不能用 MinGit 精简版)
                    dirs_to_copy = ["cmd", "mingw64", "usr"]
                    for dname in dirs_to_copy:
                        src = git_root / dname
                        if src.is_dir():
                            dst = stage / dname
                            shutil.copytree(src, dst, dirs_exist_ok=True)
                            print(f"  复制: {dname}/")

                    print(f"  正在打包: {git_zip}")
                    try:
                        shutil.make_archive(
                            str(git_zip.with_suffix("")),
                            "zip",
                            root_dir=tmpdir,
                            base_dir=f"git-windows-{arch}",
                        )
                        size_mb = git_zip.stat().st_size / (1024 * 1024)
                        print(f"内部 git 打包完成: {git_zip} ({size_mb:.1f} MB)")
                        return git_zip
                    except OSError as e:
                        print(f"打包失败: {e}")
                        if git_zip.exists():
                            git_zip.unlink()
        else:
            print("未找到完整版 Git for Windows 安装目录(应含 cmd/、mingw64/、usr/)。")

        # 3) 自动失败 → 给出手动准备指引（详细步骤见 README §4）
        print(
            "未找到 Windows git 资源(resources/windows/git-*.zip)。\n"
            "请在已装 Git for Windows 的机器上运行本脚本以自动打包，\n"
            "或手动准备(见 README §4):\n"
            "  1. 进入完整版 Git 安装目录(如 D:\\Git\\)\n"
            "  2. zip -r -q -6 git-<version>-windows-x64.zip . -x \"unins000.*\" \"tmp/*\" \"tmp\"\n"
            "  3. 放入 resources/windows/(文件名必须以 git- 开头)\n"
            "在线版安装器可直接从网络下载 git，本资源仅离线版需要。"
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

    return None


def _is_junction(path: Path) -> bool:
    """检测 Windows junction(重解析点)。

    pnpm workspace 在 Windows 上创建 junction 而非 symlink,
    pathlib.Path.is_symlink() 在 Python 3.8+ 对 junction 返回 True,但更早不会。
    保险起见用 lstat.st_file_attributes 直接查 FILE_ATTRIBUTE_REPARSE_POINT 位。

    历史 bug(2026-05-13 修): 之前写成 `os.stat.FILE_ATTRIBUTE_REPARSE_POINT`,
    把 `os.stat`(函数) 当成模块用,实际应该是 `stat.FILE_ATTRIBUTE_REPARSE_POINT`
    (stat 模块的常量)。错误访问触发 AttributeError → 被 except 吞 → 永远返回 False,
    导致 junction 没被识别、当普通目录递归进 tarball 体积爆炸。
    """
    if sys.platform != "win32":
        return False
    try:
        st = os.lstat(path)
        return bool(st.st_file_attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT)
    except (OSError, AttributeError):
        return False


def _read_link_target_clean(link_path: Path) -> str:
    """读软链接/junction 的目标,清掉 Windows NT 命名空间前缀。

    Windows 的 NTFS junction reparse data 有两种规范化形式:
    - "\\\\?\\C:\\path"  (DOS 设备路径,Win32 API 优先返回这种)
    - "\\??\\C:\\path"   (NT 内核命名空间,老格式)
    剥掉前缀后才是普通绝对路径。
    """
    raw = os.readlink(link_path)
    if raw.startswith("\\\\?\\"):
        return raw[4:]
    if raw.startswith("\\??\\"):
        return raw[4:]
    return raw


def _add_junction_as_relsymlink(
    tar: tarfile.TarFile,
    link_path: Path,
    arcname: str,
    tar_root_real: Path,
    tar_root_arc_prefix: str,
) -> bool:
    """把 NTFS junction 转成"指向 tar 内根目录的相对路径软链接"写入 tarball。

    思路:junction 在 Windows 上是绝对路径不可移植,但如果它指向的是 tar 根目录内的
    某处(对 pnpm workspace 来说就是 source_dir 自己或其子目录),就把它转成
    SYMTYPE 成员 + linkname=相对路径(如 "../../../.."),解压时无论目标机器在哪
    解析,relpath 都能回到 tar 根。

    Args:
        link_path: junction 文件的真实路径(在 source_dir 下)
        arcname: tarball 内对应的路径(已含 tar_root_arc_prefix,如 "openclaw-cn/extensions/.../openclaw")
        tar_root_real: source_dir.resolve(),用来判断 junction 目标是否在打包范围内
        tar_root_arc_prefix: tar 内对应 source_dir 根的前缀(如 "openclaw-cn"),
            用来把 target_abs 的相对位置正确映射到 tar 内层级

    Returns:
        True 表示成功写入 tarball;False 表示 junction 指向 tar root 之外,
        调用方应该跳过(不打进 tarball)。
    """
    try:
        raw = _read_link_target_clean(link_path)
    except OSError as e:
        print(f"  警告: 无法读 junction {link_path}: {e}")
        return False

    target_abs = Path(raw).resolve()
    try:
        target_in_tar = target_abs.relative_to(tar_root_real)
    except ValueError:
        # junction 指向 tar root 外,跳过(打进去也无意义,目标机器解析不到)
        print(f"  跳过指向仓库外的 junction: {link_path} -> {target_abs}")
        return False

    # arcname 已经含有 tar_root_arc_prefix(如 "openclaw-cn/.../openclaw"),
    # 把 target_in_tar 也加上同样的前缀,得到它在 tar 内的完整路径,再算 relpath。
    arc_posix = arcname.replace("\\", "/")
    link_dir_in_tar = posixpath.dirname(arc_posix)

    target_rel = str(target_in_tar).replace("\\", "/")
    if target_rel == ".":
        # target 就是 source_dir 本身,在 tar 内对应 tar_root_arc_prefix
        target_full_in_tar = tar_root_arc_prefix
    else:
        target_full_in_tar = posixpath.join(tar_root_arc_prefix, target_rel)

    rel = posixpath.relpath(target_full_in_tar, link_dir_in_tar or ".")

    ti = tarfile.TarInfo(name=arc_posix)
    ti.type = tarfile.SYMTYPE
    ti.linkname = rel
    # 用源 junction 的 mtime 而不是 time.time(),保留 reproducible build 友好性
    try:
        ti.mtime = int(os.lstat(link_path).st_mtime)
    except OSError:
        ti.mtime = 0
    ti.mode = 0o777
    tar.addfile(ti)
    return True


def _add_to_tar(
    tar: tarfile.TarFile,
    path: Path,
    arcname: str,
    tar_root_real: Path | None = None,
    tar_root_arc_prefix: str = "",
    skip_junction_check: bool = False,
) -> None:
    """递归添加文件/目录到 tar。

    junction 处理(2026-05-13 改):pnpm workspace 在 Windows 上用 junction 链接,
    junction 是绝对路径,直接 tar.add 会编码成 /c/... 这种不可移植的绝对软链接,
    解压到其他机器无意义。改为转成相对路径 SYMTYPE,解压端 mklink /J 还原。

    性能优化(2026-05-13 改):pnpm `.pnpm/` content-addressable store 内部全是真实
    文件 + hardlink,不存在 junction。但 Windows + Defender 下每次 os.lstat 都触发
    扫描,对 `.pnpm/` 里的 10 万文件逐个 lstat 会让打包时间从 5 分钟拖到 1 小时。
    skip_junction_check=True 时跳过 _is_junction 调用,直接 tar.add 整个子树
    (tarfile 内部 walk 比我们手写循环更高效,且会自动 hardlink 去重)。
    进入 `.pnpm/` 时设置该标志,极大提升性能。

    Args:
        tar_root_arc_prefix: source_dir 在 tar 内对应的目录名(如 "openclaw-cn"),
            junction 计算相对路径时用作前缀。
        skip_junction_check: 跳过 junction 检测,直接 tar.add 整个子树。
            仅在确认子树内不含 junction 时使用(如 pnpm `.pnpm/` 内部)。
    """
    # `.pnpm/` 子树 fast path:per-child 容错 + 仍要查 junction。
    # 历史 bug(2026-05 三次修):
    #   一次:外层 try 包整个 for,单包 OSError 中断整树 → 字母序后半段缺包
    #   二次:fast path 直接 tar.add(整树) 让 tarfile 内部 walk → 同样问题
    #   三次:fast path 跳过 _is_junction → workspace 包(@openclaw/bluebubbles 这种)
    #         在 .pnpm/ 内放 junction,被当目录递归,无限展开 → tarball 爆到 800MB+
    # 结论:fast path 真正能省的只是 is_symlink/is_dir 这类双 lstat;_is_junction
    #       一次 lstat 必须保留。
    if skip_junction_check:
        if path.name == ".git":
            return
        # 必须查 junction —— pnpm workspace 包会在 .pnpm/ 内放 junction
        if _is_junction(path):
            if tar_root_real is not None:
                _add_junction_as_relsymlink(
                    tar, path, arcname, tar_root_real, tar_root_arc_prefix,
                )
            return
        try:
            is_dir = path.is_dir() and not path.is_symlink()
        except OSError:
            is_dir = False
        if is_dir:
            try:
                tar.add(path, arcname=arcname, recursive=False)
            except OSError as e:
                print(f"  警告: 无法添加目录 {path}: {e}")
                return
            try:
                children = list(path.iterdir())
            except OSError as e:
                print(f"  警告: 无法列出 {path}: {e}")
                return
            for child in children:
                if child.name == ".git":
                    continue
                try:
                    _add_to_tar(
                        tar, child, f"{arcname}/{child.name}",
                        tar_root_real, tar_root_arc_prefix,
                        skip_junction_check=True,
                    )
                except OSError as e:
                    print(f"  警告: 无法添加 {child}: {e}")
            return
        try:
            tar.add(path, arcname=arcname)
        except OSError as e:
            print(f"  警告: 无法添加 {path}: {e}")
        return

    # 优先识别 junction(_is_junction 在非 Win 平台返回 False,Mac 走 is_symlink 即可)
    if _is_junction(path):
        if tar_root_real is not None:
            _add_junction_as_relsymlink(
                tar, path, arcname, tar_root_real, tar_root_arc_prefix,
            )
        # tar_root_real 为 None 时(理论上不会),保守跳过 junction
        return

    if path.is_symlink():
        # 普通 symlink (Mac 上的 pnpm workspace 软链接、相对路径) 直接 tar.add 即可,
        # tarfile 会保留相对 linkname,目标机器解压能正确解析
        tar.add(path, arcname=arcname)
        return

    if path.is_dir():
        # 添加目录本身,但不递归(recursive=False)
        tar.add(path, arcname=arcname, recursive=False)
        # 历史 bug(2026-05 修): 这里以前是整个 for 循环外包一层 try/except OSError,
        # 于是 .pnpm/ 下任意一个包的子树 tar.add 内部抛 OSError(路径过长/文件锁/Defender
        # 临时阻挡)就会中断剩余兄弟节点的迭代,造成"按字母序之后所有包都缺失"。
        # 实际症状:解压后 onboard 找不到 tsdown 等 t/u/v/w/x/y/z 字母段的包。
        # 改为对每个 child 单独 try,某个失败只跳过它,不影响其他。
        try:
            children = list(path.iterdir())
        except OSError as e:
            print(f"  警告: 无法列出 {path}: {e}")
            return
        for child in children:
            if child.name == ".git":
                continue
            # 进入 .pnpm/ 后启用 fast path —— 内部全是真实文件,无 junction
            child_skip = skip_junction_check or child.name == ".pnpm"
            try:
                _add_to_tar(
                    tar, child, f"{arcname}/{child.name}",
                    tar_root_real, tar_root_arc_prefix,
                    skip_junction_check=child_skip,
                )
            except OSError as e:
                print(f"  警告: 无法添加 {child}: {e}")
    else:
        tar.add(path, arcname=arcname)


def _pack_with_system_tar(source_dir: Path, output_file: Path) -> bool:
    """尝试使用系统 tar 命令打包,**跟随软链接/junction 写入目标内容**。

    重要(2026-05-13 修): Windows 上 pnpm workspace 用 junction 链接 workspace 包,
    Git Bash tar 默认会把 junction 当软链接编码成绝对路径(如 /c/Users/jiash/openclaw-cn),
    解压到目标机器时 safe_tar_extract 拒绝指向目标目录外的软链接,导致整个解压失败。
    用 --dereference (-h) 让 tar 跟随这些链接、把真实内容打进去,
    这样 tarball 在任何机器上解压都是自包含的。

    代价:tarball 体积会大一些(workspace 包内容会被复制多份),
    但相比"无法解压"是合理代价。

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
                "-czhf", str(output_file),  # -h = --dereference,跟随软链接/junction
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

    # Windows 平台:不能用系统 tar(Git Bash tar)。它会把 NTFS junction 编码成
    # 绝对路径软链接(/c/Users/...),解压到其他机器时 safe_tar_extract 拒绝
    # "指向目标外的软链接",整个解压失败。即使加 --dereference 跟随 junction,
    # tarball 体积会膨胀到 1-2GB(workspace 包内容被复制多份)。
    # 正解:走 Python tarfile,自定义 _add_junction_as_relsymlink 把 junction
    # 转为相对路径 SYMTYPE 成员,体积零增长,目标机器用 mklink /J 还原。
    #
    # 非 Windows 平台:Mac 上 pnpm 用相对 symlink,系统 tar 能正确处理,
    # 优先用它(更快、且能保留所有元数据)。
    use_system_tar = sys.platform != "win32" and _pack_with_system_tar(source_dir, output_file)
    if use_system_tar:
        print(f"  使用系统 tar 打包完成")
    else:
        # Windows 必走这条;Mac 系统 tar 失败时也退化到这里
        print(f"  使用 Python tarfile 打包...")
        # tar_root_real:source_dir 的真实绝对路径,用来判断 junction 目标是否
        # 在 tar 范围内(在内 → 转相对 SYMTYPE;在外 → 跳过)
        tar_root_real = source_dir.resolve()
        with tarfile.open(output_file, "w:gz") as tar:
            for item in source_dir.iterdir():
                if item.name == ".git":
                    continue
                _add_to_tar(
                    tar, item, f"openclaw-cn/{item.name}",
                    tar_root_real=tar_root_real,
                    tar_root_arc_prefix="openclaw-cn",
                )

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
        choices=["macos", "windows"],
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
        help=f"git 版本占位 (默认: {DEFAULT_GIT_VERSION},当前未使用,Windows git 需手动打包)",
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
