#!/usr/bin/env python3
"""
OpenClaw Release 上传脚本

将构建产物上传到阿里云 OSS，凭证通过环境变量配置。
后续可扩展 Gitea Release 自动更新下载链接等功能。

环境变量:
    OSS_ACCESS_KEY_ID      — 阿里云 AccessKey ID（需 OSS 写入权限，建议用子账号）
    OSS_ACCESS_KEY_SECRET  — 阿里云 AccessKey Secret
    OSS_BUCKET             — OSS Bucket 名称
    OSS_ENDPOINT           — OSS Endpoint（如 oss-cn-hangzhou.aliyuncs.com）

使用方法:
    # 上传单个文件
    uv run python upload_release.py --file dist/OpenClaw安装器-arm64.app.zip

    # 上传 dist/ 下所有 .app.zip
    uv run python upload_release.py --all

    # 指定 OSS 路径前缀（如按版本号组织）
    uv run python upload_release.py --all --path openclaw/releases/v1.1.5/

    # 同时上传 .command 辅助脚本
    uv run python upload_release.py --all --include-command
"""

import os
import sys
import argparse
from pathlib import Path


# ---------------------------------------------------------------------------
# OSS SDK 运行时检测
# ---------------------------------------------------------------------------

HAS_OSS2 = False
try:
    import oss2
    HAS_OSS2 = True
except ImportError:
    pass


# ---------------------------------------------------------------------------
# 凭证 & Bucket
# ---------------------------------------------------------------------------

def _get_oss_credentials() -> dict:
    """从环境变量读取 OSS 凭证并校验

    所有四个环境变量缺一不可。缺少任一项时打印提示并退出。
    """
    required = {
        'OSS_ACCESS_KEY_ID': '阿里云 AccessKey ID',
        'OSS_ACCESS_KEY_SECRET': '阿里云 AccessKey Secret',
        'OSS_BUCKET': 'OSS Bucket 名称',
        'OSS_ENDPOINT': 'OSS Endpoint（如 oss-cn-hangzhou.aliyuncs.com）',
    }

    creds = {}
    missing = []
    for var, desc in required.items():
        value = os.environ.get(var)
        if not value:
            missing.append(f"  {var} — {desc}")
        creds[var] = value

    if missing:
        print("错误：缺少 OSS 环境变量 —")
        for m in missing:
            print(m)
        print("\n请在当前 shell 中 export 上述变量后重试，或写入 ~/.zshrc 持久化。")
        print("（建议使用子账号 AK/SK，不要用主账号，避免权限过大）")
        sys.exit(1)

    return creds


def _get_bucket():
    """创建并返回 oss2.Bucket 实例"""
    creds = _get_oss_credentials()
    auth = oss2.Auth(creds['OSS_ACCESS_KEY_ID'], creds['OSS_ACCESS_KEY_SECRET'])
    return oss2.Bucket(auth, creds['OSS_ENDPOINT'], creds['OSS_BUCKET'])


# ---------------------------------------------------------------------------
# 上传
# ---------------------------------------------------------------------------

def _percent_callback(consumed_bytes: int, total_bytes: int):
    """上传进度回调 — 终端内联刷新"""
    if total_bytes:
        pct = min(int(100 * consumed_bytes / total_bytes), 100)
        print(f"\r  上传中... {pct}%", end='', flush=True)


def upload_file(local_path: str, oss_key: str, bucket=None) -> str | None:
    """上传单个文件到 OSS

    Args:
        local_path: 本地文件绝对或相对路径
        oss_key: OSS 对象 key（不含 bucket 前缀）
        bucket: 可复用的 Bucket 实例，None 则自动创建

    Returns:
        上传成功返回公开访问 URL，失败返回 None
    """
    if bucket is None:
        bucket = _get_bucket()

    local_path = Path(local_path)
    if not local_path.exists():
        print(f"  错误：文件不存在 — {local_path}")
        return None

    file_size = local_path.stat().st_size
    size_mb = file_size / (1024 * 1024)
    print(f"  上传: {local_path.name} ({size_mb:.1f} MB)")
    print(f"  目标: oss://{bucket.bucket_name}/{oss_key}")

    try:
        bucket.put_object_from_file(
            oss_key,
            str(local_path),
            progress_callback=_percent_callback,
        )
        print()  # 进度条以 \r 结尾，补一个换行

        # 构造公开访问 URL（假设 Bucket 已配置公共读）
        public_url = (
            f"https://{bucket.bucket_name}."
            f"{bucket.endpoint.replace('https://', '').replace('http://', '')}"
            f"/{oss_key}"
        )
        print(f"  ✓ 完成: {public_url}")
        return public_url

    except oss2.exceptions.OssError as e:
        print(f"\n  上传失败 (OSS 错误): {e}")
        return None
    except Exception as e:
        print(f"\n  上传失败: {e}")
        return None


# ---------------------------------------------------------------------------
# 文件收集
# ---------------------------------------------------------------------------

def _collect_dist_files(dist_dir: str, include_command: bool = False) -> list[Path]:
    """收集 dist/ 下需要上传的文件

    按优先级排序: 在线安装器 → 离线安装器 → 卸载工具 → command 脚本。
    只收集 .app.zip（macOS）或 .exe（Windows），跳过裸 .app bundle 和 .command。

    Args:
        dist_dir: dist 目录路径
        include_command: 是否同时收集 .command 辅助脚本
    """
    dist = Path(dist_dir)
    if not dist.is_dir():
        print(f"错误：dist/ 目录不存在 — {dist}")
        sys.exit(1)

    files: list[Path] = []

    # 优先 .app.zip（macOS 已压缩产物）
    for pattern in [
        "OpenClaw安装器-*.app.zip",
        "OpenClaw离线安装器-*.app.zip",
        "OpenClaw卸载工具-*.app.zip",
        "OpenClaw启动器-*.app.zip",
    ]:
        matched = sorted(dist.glob(pattern))
        files.extend(matched)

    # Windows .exe（无 .app.zip 时回退）
    if not any('.app.zip' in f.name for f in files):
        for pattern in [
            "OpenClaw安装器*.exe",
            "OpenClaw离线安装器*.exe",
            "OpenClaw卸载工具*.exe",
            "OpenClaw启动器*.exe",
        ]:
            matched = sorted(dist.glob(pattern))
            files.extend(matched)

    # .command 辅助脚本（macOS）
    if include_command:
        for pattern in ["双击运行-*.command"]:
            matched = sorted(dist.glob(pattern))
            files.extend(matched)

    return files


# ---------------------------------------------------------------------------
# 压缩（打包后 .app 是目录，上传前需要先 zip）
# ---------------------------------------------------------------------------

def _zip_app_bundle(app_path: Path) -> Path | None:
    """将 .app bundle 打包为 .zip

    macOS PyInstaller 产物是 .app 目录，上传前需要压缩。
    如果对应的 .zip 已存在且比 .app 新，则跳过压缩。
    """
    zip_path = app_path.with_suffix(app_path.suffix + '.zip')

    if zip_path.exists() and zip_path.stat().st_mtime >= app_path.stat().st_mtime:
        print(f"  跳过压缩（已有最新 .zip）: {zip_path.name}")
        return zip_path

    print(f"  压缩 .app → .zip...")
    import zipfile

    try:
        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zf:
            for dirpath, _, filenames in os.walk(app_path):
                for filename in filenames:
                    file_path = os.path.join(dirpath, filename)
                    arcname = os.path.relpath(file_path, app_path.parent)
                    zf.write(file_path, arcname)
        size_mb = zip_path.stat().st_size / (1024 * 1024)
        print(f"  ✓ 压缩完成: {zip_path.name} ({size_mb:.1f} MB)")
        return zip_path
    except Exception as e:
        print(f"  压缩失败: {e}")
        return None


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="OpenClaw Release 上传脚本 — 将构建产物上传到阿里云 OSS",
        epilog="示例:\n"
               "  uv run python upload_release.py --file dist/OpenClaw安装器-arm64.app.zip\n"
               "  uv run python upload_release.py --all\n"
               "  uv run python upload_release.py --all --path openclaw/releases/v1.1.5/",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument(
        '--file', '-f',
        help='上传单个文件',
    )
    source.add_argument(
        '--all', '-a',
        action='store_true',
        help='上传 dist/ 下所有 .app.zip（或 Windows .exe）',
    )

    parser.add_argument(
        '--include-command',
        action='store_true',
        help='同时上传 macOS .command 辅助启动脚本（仅 --all 模式下生效）',
    )
    parser.add_argument(
        '--path',
        default='openclaw/releases/',
        help='OSS 路径前缀（默认: openclaw/releases/）',
    )
    parser.add_argument(
        '--dist-dir',
        default='dist',
        help='dist 目录路径（默认: dist）',
    )

    args = parser.parse_args()

    # —— 前置检查 ——
    if not HAS_OSS2:
        print("错误：未安装阿里云 OSS Python SDK。请执行:")
        print("  uv add oss2")
        print("或")
        print("  uv pip install oss2")
        sys.exit(1)

    # 凭证校验（提前 fail-fast）
    bucket = None
    try:
        bucket = _get_bucket()
    except SystemExit:
        # _get_bucket 内部调用 _get_oss_credentials，缺失时已打印帮助信息
        raise

    print("=" * 50)
    print("OpenClaw Release 上传")
    print(f"Bucket: {bucket.bucket_name}")
    print("=" * 50)
    print()

    # —— 收集待上传文件 ——
    upload_tasks: list[tuple[Path, str]] = []  # (本地路径, oss_key)

    if args.file:
        file_path = Path(args.file)
        if not file_path.exists():
            print(f"错误：文件不存在 — {file_path}")
            sys.exit(1)

        # 如果是 .app 目录，先压缩
        if file_path.is_dir() and file_path.suffix == '.app':
            zip_path = _zip_app_bundle(file_path)
            if zip_path is None:
                sys.exit(1)
            file_path = zip_path

        # OSS key: path 前缀 + 文件名
        oss_key = (args.path.rstrip('/') + '/' + file_path.name).lstrip('/')
        upload_tasks.append((file_path, oss_key))

    elif args.all:
        files = _collect_dist_files(args.dist_dir, include_command=args.include_command)
        if not files:
            print(f"错误：在 {args.dist_dir}/ 下未找到可上传的文件")
            print("请先运行 uv run python build.py 构建产物")
            sys.exit(1)

        for f in files:
            oss_key = (args.path.rstrip('/') + '/' + f.name).lstrip('/')
            upload_tasks.append((f, oss_key))

    if not upload_tasks:
        print("没有需要上传的文件。")
        return

    print(f"待上传 {len(upload_tasks)} 个文件:")
    for _, key in upload_tasks:
        print(f"  → oss://{bucket.bucket_name}/{key}")
    print()

    # —— 逐个上传 ——
    success_urls: list[str] = []
    failed: list[str] = []

    for local, key in upload_tasks:
        url = upload_file(str(local), key, bucket=bucket)
        if url:
            success_urls.append(url)
        else:
            failed.append(local.name)
        print()

    # —— 汇总 ——
    print("=" * 50)
    print(f"上传完成: 成功 {len(success_urls)} / 失败 {len(failed)}")
    if failed:
        print(f"失败文件: {', '.join(failed)}")
    if success_urls:
        print()
        print("下载链接:")
        for url in success_urls:
            print(f"  {url}")
    print("=" * 50)

    if failed:
        sys.exit(1)


if __name__ == '__main__':
    main()
