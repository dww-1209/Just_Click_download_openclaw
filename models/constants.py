"""项目常量配置"""

# Node.js 版本
NODEJS_VERSION = "22.14.0"
NODEJS_MAJOR_VERSION = 22

# 默认服务端口号
DEFAULT_GATEWAY_PORT = 18789

# 安装路径
INSTALL_DIR_NAME = "openclaw-cn"
CONFIG_DIR_NAME = ".openclaw"

# 命令名称
CMD_OPENCLAW = "openclaw"
CMD_OPENCLAW_CN = "openclaw-cn"

# Gitee 仓库
GITEE_REPO_URL = "https://gitee.com/OpenClaw-CN/openclaw-cn.git"

# npm/pnpm 镜像
REGISTRY_NPM_MIRROR = "https://registry.npmmirror.com"
REGISTRY_CLAWHUB = "https://cn.clawhub-mirror.com/"

# Electron 镜像（用于构建时加速）
ELECTRON_MIRROR = "https://npmmirror.com/mirrors/electron/"
ELECTRON_BUILDER_BINARIES_MIRROR = "https://npmmirror.com/mirrors/electron-builder-binaries/"

# Node.js MSI 下载镜像（Windows）
NODEJS_MSI_MIRRORS = [
    f"https://mirrors.aliyun.com/nodejs-release/v{NODEJS_VERSION}/node-v{NODEJS_VERSION}-x64.msi",
    f"https://mirrors.cloud.tencent.com/nodejs-release/v{NODEJS_VERSION}/node-v{NODEJS_VERSION}-x64.msi",
    f"https://repo.huaweicloud.com/nodejs/v{NODEJS_VERSION}/node-v{NODEJS_VERSION}-x64.msi",
    f"https://mirrors.ustc.edu.cn/nodejs/v{NODEJS_VERSION}/node-v{NODEJS_VERSION}-x64.msi",
    f"https://npmmirror.com/mirrors/node/v{NODEJS_VERSION}/node-v{NODEJS_VERSION}-x64.msi",
    f"https://registry.npmmirror.com/-/binary/node/latest-v{NODEJS_MAJOR_VERSION}.x/node-v{NODEJS_VERSION}-x64.msi",
    f"https://nodejs.org/dist/v{NODEJS_VERSION}/node-v{NODEJS_VERSION}-x64.msi",
]

# Node.js PKG 下载镜像（macOS）
NODEJS_PKG_MIRRORS = [
    f"https://mirrors.aliyun.com/nodejs-release/v{NODEJS_VERSION}/node-v{NODEJS_VERSION}.pkg",
    f"https://mirrors.cloud.tencent.com/nodejs-release/v{NODEJS_VERSION}/node-v{NODEJS_VERSION}.pkg",
    f"https://repo.huaweicloud.com/nodejs/v{NODEJS_VERSION}/node-v{NODEJS_VERSION}.pkg",
    f"https://mirrors.ustc.edu.cn/nodejs/v{NODEJS_VERSION}/node-v{NODEJS_VERSION}.pkg",
    f"https://nodejs.org/dist/v{NODEJS_VERSION}/node-v{NODEJS_VERSION}.pkg",
    f"https://registry.npmmirror.com/-/binary/node/latest-v{NODEJS_MAJOR_VERSION}.x/node-v{NODEJS_VERSION}.pkg",
]

# MSI 文件头魔数（OLE 复合文档格式）
MSI_MAGIC_HEADER = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"

# 健康检查重试次数
HEALTH_CHECK_MAX_RETRIES = 20
HEALTH_CHECK_INTERVAL = 1

# Gateway 启动等待
GATEWAY_STARTUP_WAIT_SECONDS = 3
GATEWAY_STARTUP_MAX_WAIT_SECONDS = 20
