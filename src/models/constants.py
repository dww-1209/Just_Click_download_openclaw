"""项目常量配置模块。

职责：集中管理安装器所需的全部硬编码常量，包括 Node.js 版本、镜像地址、
仓库 URL、健康检查参数等，便于统一维护和替换。
"""

# Node.js 版本
NODEJS_VERSION = "22.14.0"
NODEJS_MAJOR_VERSION = 22

# 默认服务端口号
DEFAULT_GATEWAY_PORT = 18789

# 安装路径
INSTALL_DIR_NAME = "openclaw-cn"   # 克隆到用户主目录下的文件夹名
CONFIG_DIR_NAME = ".openclaw"      # 配置文件夹名

# 命令名称
CMD_OPENCLAW = "openclaw"
CMD_OPENCLAW_CN = "openclaw-cn"

# Gitee 仓库地址（在线安装时克隆的源码仓库）
GITEE_REPO_URL = "https://gitee.com/OpenClaw-CN/openclaw-cn.git"

# Git for Windows 下载镜像列表
GIT_FOR_WINDOWS_URLS = [
    "https://registry.npmmirror.com/-/binary/git-for-windows/v2.43.0.windows.1/Git-2.43.0-64-bit.exe",
    "https://mirrors.tuna.tsinghua.edu.cn/github-release/git-for-windows/git/LatestRelease/Git-2.47.1-64-bit.exe",
    "https://mirrors.nju.edu.cn/github-release/git-for-windows/git/LatestRelease/Git-2.47.1-64-bit.exe",
    "https://mirrors.aliyun.com/github-release/git-for-windows/git/LatestRelease/Git-2.47.1-64-bit.exe",
    "https://github.com/git-for-windows/git/releases/download/v2.47.1.windows.1/Git-2.47.1-64-bit.exe",
]

# npm/pnpm 镜像（用于加速依赖下载）
REGISTRY_NPM_MIRROR = "https://registry.npmmirror.com"
REGISTRY_CLAWHUB = "https://cn.clawhub-mirror.com/"

# Electron 镜像（用于构建时加速 Electron 下载）
ELECTRON_MIRROR = "https://npmmirror.com/mirrors/electron/"
ELECTRON_BUILDER_BINARIES_MIRROR = "https://npmmirror.com/mirrors/electron-builder-binaries/"

# Node.js MSI 下载镜像列表（Windows）
# 按优先级排列：国内镜像在前，官方源兜底
NODEJS_MSI_MIRRORS = [
    f"https://mirrors.aliyun.com/nodejs-release/v{NODEJS_VERSION}/node-v{NODEJS_VERSION}-x64.msi",
    f"https://mirrors.cloud.tencent.com/nodejs-release/v{NODEJS_VERSION}/node-v{NODEJS_VERSION}-x64.msi",
    f"https://repo.huaweicloud.com/nodejs/v{NODEJS_VERSION}/node-v{NODEJS_VERSION}-x64.msi",
    f"https://mirrors.ustc.edu.cn/nodejs/v{NODEJS_VERSION}/node-v{NODEJS_VERSION}-x64.msi",
    f"https://npmmirror.com/mirrors/node/v{NODEJS_VERSION}/node-v{NODEJS_VERSION}-x64.msi",
    f"https://registry.npmmirror.com/-/binary/node/latest-v{NODEJS_MAJOR_VERSION}.x/node-v{NODEJS_VERSION}-x64.msi",
    f"https://nodejs.org/dist/v{NODEJS_VERSION}/node-v{NODEJS_VERSION}-x64.msi",
]

# Node.js PKG 下载镜像列表（macOS）
# 按优先级排列：国内镜像在前，官方源兜底
NODEJS_PKG_MIRRORS = [
    f"https://mirrors.aliyun.com/nodejs-release/v{NODEJS_VERSION}/node-v{NODEJS_VERSION}.pkg",
    f"https://mirrors.cloud.tencent.com/nodejs-release/v{NODEJS_VERSION}/node-v{NODEJS_VERSION}.pkg",
    f"https://repo.huaweicloud.com/nodejs/v{NODEJS_VERSION}/node-v{NODEJS_VERSION}.pkg",
    f"https://mirrors.ustc.edu.cn/nodejs/v{NODEJS_VERSION}/node-v{NODEJS_VERSION}.pkg",
    f"https://nodejs.org/dist/v{NODEJS_VERSION}/node-v{NODEJS_VERSION}.pkg",
    f"https://registry.npmmirror.com/-/binary/node/latest-v{NODEJS_MAJOR_VERSION}.x/node-v{NODEJS_VERSION}.pkg",
]

# Node.js 预编译二进制包(tarball/zip)下载镜像基础 URL 列表
# 按优先级排列：国内镜像在前，官方源兜底
# 实际使用时拼接文件名，如 f"{base}/node-v{NODEJS_VERSION}-darwin-arm64.tar.gz"
NODEJS_ARCHIVE_MIRROR_BASES = [
    f"https://mirrors.aliyun.com/nodejs-release/v{NODEJS_VERSION}",
    f"https://mirrors.cloud.tencent.com/nodejs-release/v{NODEJS_VERSION}",
    f"https://repo.huaweicloud.com/nodejs/v{NODEJS_VERSION}",
    f"https://mirrors.ustc.edu.cn/nodejs/v{NODEJS_VERSION}",
    f"https://npmmirror.com/mirrors/node/v{NODEJS_VERSION}",
    f"https://nodejs.org/dist/v{NODEJS_VERSION}",
]

# MSI 文件头魔数（OLE 复合文档格式），用于校验下载的文件是否为有效 MSI
MSI_MAGIC_HEADER = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"

# 健康检查重试次数和间隔（秒）
HEALTH_CHECK_MAX_RETRIES = 20
HEALTH_CHECK_INTERVAL = 1

# Gateway 启动等待时间（秒）
GATEWAY_STARTUP_WAIT_SECONDS = 3      # 首次等待时间
GATEWAY_STARTUP_MAX_WAIT_SECONDS = 20  # 最大等待时间

# 命令执行超时（秒）
TIMEOUT_INSTALL_CMD = 300       # 安装命令默认超时
TIMEOUT_DOWNLOAD = 180          # 文件下载超时
TIMEOUT_GIT_INSTALL_POLL = 5    # Git 安装轮询间隔
TIMEOUT_GIT_INSTALL_MAX = 600   # Git 安装最大等待时间（10分钟）
TIMEOUT_SHORT_CMD = 5           # 短命令超时（where、which 等）
TIMEOUT_OPENCLAW_CMD = 30       # openclaw 子命令超时
TIMEOUT_SOCKET_CONNECT = 2      # 端口检测超时
TIMEOUT_NODE_MSI_INSTALL = 300  # Node.js MSI 安装超时
TIMEOUT_BUILD_CMD = 900         # pnpm install/build 超时

# ─────────────────────────────────────────────────────────────────────
# 自定义 Provider 模型能力参数（UI 下拉档位 + 默认值）
# ─────────────────────────────────────────────────────────────────────
# 设计原则：默认值采用 2026 年主流模型的"最低安全基线"，保证用户填写任意
# OpenAI/Anthropic 兼容端点（自建代理、本地部署、小众模型）都至少能跑通；
# 想要更长上下文/更长输出的用户可自行从下拉框选高档位或填自定义值。
#
# - 上下文 128K：海外旗舰已普遍 1M，但国产开源（DeepSeek V3.x、Kimi K2、
#   Qwen3、Llama 4 base）仍以 128K 为主流基线，自托管模型更可能只支持 32K-128K，
#   填高了反而触发 422。128K 是覆盖面最广的"安全下界"。
# - 最大输出 8K：8K 是几乎所有 OpenAI 兼容端点都不会拒绝的兼容值，16K+ 在部分
#   自托管模型上会报错。Claude/Gemini 上限 64K，o-series 推理输出可达 128K。
# - 推理模式默认关闭：2026 年推理形态三种并存——(a) 天生推理模型 flag 无效、
#   (b) 可切换 thinking（Claude 4.x / Gemini 2.5 / DeepSeek V3.2 / Qwen3）、
#   (c) 不支持的传 thinking:true 会 422。默认关最安全，且开启会显著增加延迟和成本。
PROVIDER_DEFAULT_CONTEXT_WINDOW = 128_000
PROVIDER_DEFAULT_MAX_TOKENS = 8_192
PROVIDER_DEFAULT_REASONING = False

# 上下文长度下拉档位 [(标签, token 值)]，None 表示"不指定"由后端自动识别
PROVIDER_CONTEXT_WINDOW_OPTIONS: list[tuple[str, int | None]] = [
    ("128K (默认)", 128_000),
    ("32K", 32_000),
    ("200K", 200_000),
    ("500K", 500_000),
    ("1M", 1_000_000),
    ("2M", 2_000_000),
    ("不指定 (由后端自动识别)", None),
]

# 最大输出 tokens 下拉档位
PROVIDER_MAX_TOKENS_OPTIONS: list[tuple[str, int | None]] = [
    ("8K (默认)", 8_192),
    ("4K", 4_096),
    ("16K", 16_384),
    ("32K", 32_768),
    ("64K", 65_536),
    ("128K", 131_072),
    ("不指定 (由后端自动识别)", None),
]

# 自定义档位输入框的合法范围
PROVIDER_CONTEXT_WINDOW_MIN = 1024
PROVIDER_CONTEXT_WINDOW_MAX = 10_000_000
PROVIDER_MAX_TOKENS_MIN = 256
PROVIDER_MAX_TOKENS_MAX = 200_000

# 统一平台判断函数（避免项目中混用 platform.system() 和 sys.platform）
import sys
import platform


def is_windows() -> bool:
    """判断当前系统是否为 Windows。"""
    return sys.platform == "win32"


def is_macos() -> bool:
    """判断当前系统是否为 macOS。"""
    return sys.platform == "darwin"


def is_linux() -> bool:
    """判断当前系统是否为 Linux。"""
    return sys.platform.startswith("linux")
