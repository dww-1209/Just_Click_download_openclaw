# OpenClaw 一键安装器

面向小白用户的 OpenClaw（小龙虾）图形化一键安装工具。

## 功能特点

- **真正一键安装**：只需点击"开始安装"，无需选择路径
- **自动下载安装**：使用官方命令自动下载安装 OpenClaw
- **自动启动服务**：安装完成后自动启动 gateway 服务
- **自动打开 WebUI**：自动获取 token 并打开浏览器访问 WebChat
- **管理员权限**：程序启动即请求管理员权限，确保安装顺利

## 使用方式

### 普通用户

1. 下载 `OpenClaw安装器.exe`（Windows）或对应平台的可执行文件
2. **双击运行**（Windows 会自动弹出 UAC 请求管理员权限）
3. 点击 **"开始安装"**
4. 等待安装完成（可能需要 20 分钟，因openclaw官方对下载中的某些组件未采用预编译，故Rust编译速度会较慢）
5. 安装完成后会自动打开浏览器访问 WebChat

### 安装详情

| 项目 | 说明 |
|------|------|
| 安装位置 | 自动安装到用户目录 (`~/.openclaw` 或 `%USERPROFILE%\.openclaw`) |
| 依赖安装 | 自动检测并安装 Node.js (≥v22) |
| 服务端口号 | 18789 |
| WebUI 地址 | `http://127.0.0.1:18789?token=<自动获取>` |

## 开发者

**安装依赖：**
```bash
uv sync
```

**运行开发版本：**
```bash
uv run python main.py
```

**打包可执行文件：**
```bash
# 输出到 F:\download_exe\
uv run python build.py

# 或指定其他路径
uv run python build.py --output "C:\Users\用户名\Desktop"
```

打包完成后，可执行文件位于指定目录。

## 技术说明

### 安装方式

本安装器使用 OpenClaw 官方提供的命令行安装脚本：

- **Windows**: `iwr -useb https://openclaw.ai/install.ps1 | iex`
- **Linux/macOS**: `curl -fsSL https://openclaw.ai/install.sh | bash`

官方脚本特点：
- 自动检测并安装 Node.js 依赖
- 不支持自定义安装路径（固定安装到用户目录）
- 自动完成初始化配置

### 启动流程

1. 安装完成后，程序自动执行 `openclaw gateway start` 启动服务
2. 检查 18789 端口是否开放
3. 执行 `openclaw dashboard` 获取带 token 的 WebUI URL
4. 自动打开系统默认浏览器访问 WebChat

### 项目结构

```
/ui           # 界面层（PySide6）- 欢迎页、安装进度页、完成页
/services     # 业务逻辑层 - 安装服务
/core         # OpenClaw 管理 - 启动/停止/打开 WebUI
/infra        # 系统操作 - 命令执行
/models       # 数据结构定义
```

## 注意事项

1. **网络要求**：安装过程需要从 openclaw.ai 下载脚本和依赖，请保持网络畅通
2. **杀毒软件**：部分杀毒软件可能拦截 PowerShell/curl 命令，如遇问题请暂时关闭
3. **安装时间**：首次安装需要下载 Node.js 等依赖，可能需要 5-10 分钟
4. **端口占用**：如果 18789 端口被占用，服务可能启动失败
5. **macOS 安全放行**：macOS 首次运行未签名的 `.app` 时，系统会拦截并提示`无法验证开发者`。请前往 `系统设置 > 隐私与安全性` 找到拦截记录，点击 `仍要打开` 即可正常启动。
6. **Linux 系统要求**：仅支持 **Ubuntu 24.04 LTS 及以上版本** 的桌面环境。首次运行时，程序会自动安装所需的 Node.js、cmake 等系统依赖；如遇窗口无法打开，可能需要预装 Qt X11 运行库（完整桌面版 Ubuntu 通常已自带）。

   ```bash
   # 若提示缺少 Qt 平台插件，可手动安装：
   sudo apt install -y libxcb-cursor0 libxkbcommon-x11-0 libxcb-xinerama0 libxcb-randr0 libxcb-xfixes0 libxcb-shape0 libxcb-sync1 libxcb-render-util0 libxcb-keysyms1 libxcb-image0 libxcb-icccm4 libxcb-util1 libegl1 libopengl0
   ```

## 故障排除

| 问题 | 解决方案 |
|------|---------|
| 安装失败 | 检查网络连接，关闭杀毒软件后重试 |
| 服务启动失败 | 检查 18789 端口是否被占用 |
| 浏览器未打开 | 手动访问 `http://127.0.0.1:18789` |

## 许可证

MIT
