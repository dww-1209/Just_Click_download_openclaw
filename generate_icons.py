#!/usr/bin/env python3
"""从源 PNG 生成 macOS .icns + Windows .ico 应用图标。

源图: resources/logo.png(.gitignore 已排除,跨机器需用户自备)
输出: build/icons/openclaw.{icns,ico}(build/ 已 gitignored,产物不入仓库)

依赖:
- Mac 端: 系统自带 iconutil + sips 即可生成 .icns;Pillow 生成 .ico(给 Windows 用)。
- Windows 端: 仅生成 .ico,Pillow 必装。

使用方法:
    uv run python generate_icons.py                  # 默认从 resources/logo.png 读取
    uv run python generate_icons.py --source path.png

源图要求:
- 设计师交付的成品图,1024×1024 RGBA,内容居中、四周留白合理(squircle 遮罩友好)。
- 不在脚本里做缩放/居中/底色替换:成品图一旦预处理就容易引入裁切瑕疵。

设计原则:
- 源 PNG 不入仓库,跨机器使用必须用户自己准备好 resources/logo.png。
- 生成的 .icns/.ico 也不入仓库,每台机器各自生成。
- 脚本本身可提交,跨机器复用同一份生成逻辑。
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path


# 图标输出目录(build/ 已 gitignored;build.py 的 clean_build 会跳过此目录)
ICONS_DIR = Path(__file__).parent / "build" / "icons"

# 源 logo 默认路径(resources/logo.png 已加入 .gitignore)
DEFAULT_SOURCE = Path(__file__).parent / "resources" / "logo.png"

# Windows .ico 内置多尺寸(操作系统按用途选最合适的)
WINDOWS_ICO_SIZES = [16, 24, 32, 48, 64, 128, 256]

# macOS .icns 标准尺寸映射(iconutil 要求的命名约定)
MACOS_ICONSET_SIZES = [
    (16, "icon_16x16.png"),
    (32, "icon_16x16@2x.png"),
    (32, "icon_32x32.png"),
    (64, "icon_32x32@2x.png"),
    (128, "icon_128x128.png"),
    (256, "icon_128x128@2x.png"),
    (256, "icon_256x256.png"),
    (512, "icon_256x256@2x.png"),
    (512, "icon_512x512.png"),
    (1024, "icon_512x512@2x.png"),
]


def is_macos() -> bool:
    return sys.platform == "darwin"


def is_windows() -> bool:
    return sys.platform == "win32"


def generate_ico(source: Path, output: Path) -> bool:
    """从源 PNG 生成 Windows .ico (内置多尺寸)。

    Pillow 的 save(format='ICO', sizes=[...]) 会自动把所有尺寸内嵌到一个 .ico,
    Windows 任务栏/桌面/开始菜单各自挑合适的尺寸渲染。
    """
    try:
        from PIL import Image
    except ImportError:
        print("[错误] 缺少 Pillow,请先 uv add Pillow 或 pip install Pillow")
        return False

    img = Image.open(source).convert("RGBA")
    output.parent.mkdir(parents=True, exist_ok=True)
    img.save(
        output,
        format="ICO",
        sizes=[(s, s) for s in WINDOWS_ICO_SIZES],
    )
    print(f"  生成 {output} (含 {len(WINDOWS_ICO_SIZES)} 种尺寸: {WINDOWS_ICO_SIZES})")
    return True


def generate_icns(source: Path, output: Path) -> bool:
    """从源 PNG 生成 macOS .icns。

    流程:
    1. 用 sips 把源 PNG 缩到 10 个标准尺寸,落到临时 .iconset 目录
    2. 用 iconutil 把 .iconset 打包成 .icns

    Mac 系统自带 sips 与 iconutil,无需 Pillow。
    """
    if not is_macos():
        print("[跳过] .icns 生成仅在 macOS 上支持(需要 sips + iconutil)")
        return False

    iconset_dir = output.parent / "openclaw.iconset"
    if iconset_dir.exists():
        shutil.rmtree(iconset_dir)
    iconset_dir.mkdir(parents=True, exist_ok=True)

    for size, fname in MACOS_ICONSET_SIZES:
        out_png = iconset_dir / fname
        result = subprocess.run(
            ["sips", "-z", str(size), str(size), str(source), "--out", str(out_png)],
            capture_output=True,
        )
        if result.returncode != 0:
            print(f"[错误] sips 缩放到 {size}x{size} 失败: {result.stderr.decode(errors='replace')}")
            return False

    output.parent.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        ["iconutil", "-c", "icns", str(iconset_dir), "-o", str(output)],
        capture_output=True,
    )
    if result.returncode != 0:
        print(f"[错误] iconutil 打包失败: {result.stderr.decode(errors='replace')}")
        return False

    # iconset 临时目录用完即删,只保留最终 .icns
    shutil.rmtree(iconset_dir)
    print(f"  生成 {output} (含 {len(MACOS_ICONSET_SIZES)} 种尺寸,从 16x16 到 1024x1024)")
    return True


def main() -> int:
    parser = argparse.ArgumentParser(
        description="生成 macOS .icns + Windows .ico 应用图标",
    )
    parser.add_argument(
        "--source",
        default=str(DEFAULT_SOURCE),
        help=f"源 logo PNG 路径(默认: {DEFAULT_SOURCE})。"
             "建议 1024x1024 RGBA,带透明背景。",
    )
    args = parser.parse_args()

    source = Path(args.source).expanduser().resolve()
    if not source.exists():
        print(f"[错误] 源文件不存在: {source}")
        print(f"请把 logo PNG 放到 {source} 或用 --source 指定路径。")
        return 1

    print(f"源文件: {source}")
    print(f"输出目录: {ICONS_DIR}")
    print()

    ICONS_DIR.mkdir(parents=True, exist_ok=True)

    ico_ok = generate_ico(source, ICONS_DIR / "openclaw.ico")
    icns_ok = generate_icns(source, ICONS_DIR / "openclaw.icns") if is_macos() else True

    print()
    if ico_ok and icns_ok:
        print("图标生成完成。build.py 会自动检测并使用。")
        return 0
    else:
        print("部分图标生成失败,请检查上方错误信息。")
        return 1


if __name__ == "__main__":
    sys.exit(main())
