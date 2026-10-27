# 本地 QQ 智能助手

一个可直接在 Windows 10/11 **64 位**上在线安装的本地 QQ 机器人发行版。
安装器是一个单独的 EXE，Python 运行环境、Ollama、模型、FFmpeg、PHP、PyTorch/RVC
等依赖在安装时联网下载，按使用者自己填写的目录放置。

本仓库是**源码仓库**：安装器（C#）、重建脚本、安装载荷与集成修改后的后端源码。
编译出的安装器不进入 Git，而是作为 Release 附件发布。

## 引用与修改声明

本项目是**在若干公开开源项目基础上集成与修改**而成的，不是从零自研。
凡经修改的部分均在此逐项标明来源、修改性质与许可，详见 [NOTICE.md](NOTICE.md)。

| 上游公开项目 | 许可 | 与本项目的关系 |
| --- | --- | --- |
| [AstrBotDevs/AstrBot](https://github.com/AstrBotDevs/AstrBot) | AGPL-3.0 | **主要基础**：`payload/backend/app/` 是 AstrBot 的**修改版源码**，本项目在其上做了本地化移植与集成改动 |
| [jiuhunwl/short_videos](https://github.com/jiuhunwl/short_videos) | MIT | **修改后再分发**：`payload/tools/video-parser/` 为其解析器源码的修改版，原始许可已随包提供 |
| [astral-sh/uv](https://github.com/astral-sh/uv)、[ollama/ollama](https://github.com/ollama/ollama) | MIT 等（见各自项目） | 安装时从上游下载，未修改、未内置 |
| [RVC-Project/Retrieval-based-Voice-Conversion-WebUI](https://github.com/RVC-Project/Retrieval-based-Voice-Conversion-WebUI)、[licyk/rvc-next](https://github.com/licyk/rvc-next) | 见各自项目 | 安装时从上游获取，未内置 |
| [NapNeko/NapCatQQ](https://github.com/NapNeko/NapCatQQ) | 见上游 | 仅调用官方独立安装向导，不分发其组件 |
| FFmpeg、PHP、PyTorch | 见各自上游 | 安装时从上游获取 |

如果你要复用本项目，请同时遵守上面各上游项目的许可；尤其 AstrBot 部分为 AGPL-3.0，
分发修改版时需保留许可并提供对应源码（即本仓库 `payload/backend/app/`）。

## 特性

- 中性助手：不含原作者的人设、主人 QQ 号、聊天记录、登录资料或私人音色。
- 安装界面分别填写机器人 QQ、主人 QQ、机器人名称与可选自定义人设。
- 程序、大模型、PTH/INDEX 音色、下载与缓存目录可分别选择。
- 实时日志窗口、错误报告、Ollama 内存保护与翻唱优先调度。
- 管理命令与桌面操作按安装者填写的真实主人 QQ 号鉴权，不依据昵称或自称放行。
- 普通用户可用点歌与翻唱；桌面操作仅主人可用；群聊需艾特机器人。

内置插件（`payload/templates/plugins/`）：

| 插件 | 功能 |
| --- | --- |
| `music_request` | QQ 音乐 / 网易云搜索、数字选歌、完整音频与 MP3 发送 |
| `cover_request` | PTH/INDEX 选择、UVR5 分离、RVC 翻唱、语音与 MP3 输出 |
| `desktop_agent` | 主人专属打开软件、截图、圈选点击 |
| `video_parse` | 视频链接解析、B 站找视频、筛查、发送与清理 |
| `sticker_memory` | 表情识别、收藏及对话使用 |

## 安装（面向使用者）

1. 从本仓库 Releases 下载 `本地QQ助手在线安装.exe`。
2. 运行后分别选择程序安装目录、大模型目录、PTH/INDEX 音色目录、下载与缓存目录。
3. 填写机器人 QQ、主人 QQ、机器人名称，可选填写自定义人设。
4. 确认组件列表并同意后开始在线安装。必需依赖缺失时安装会停止并生成错误报告，
   不会显示安装成功。
5. QQ 接入使用 NapCat 官方独立安装向导；也可连接自行安装的 SnowLuma。
6. 通过桌面快捷方式启动，分别登录**自己的**机器人 QQ 与 QQ 音乐账号
   （两个登录互相独立，QQ 登录不能代替 QQ 音乐登录）。

翻唱功能需要使用者自备匹配的 PTH 与 INDEX 音色文件，安装包不附带任何私人音色。

> 安装器只有 1.7 MB 左右，但依赖体积远大于此：Ollama、模型、Python、PyTorch/RVC
> 会在安装时下载。

> 请只转发原始安装 EXE。安装完成后的目录包含令牌与随机后台密码
> （`localbot.json`），不要整体分享。

## 从源码构建

在 Windows 上，从仓库根目录执行：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\Rebuild.ps1
```

`Rebuild.ps1` 会先把 `payload/` 压缩为 `payload.zip`，再调用
Windows .NET Framework 自带的 C# 编译器
（`%WINDIR%\Microsoft.NET\Framework64\v4.0.30319\csc.exe`）编译 `Installer.cs`，
把载荷作为资源内嵌，输出 `LocalQQAssistantSetup.exe`。

安装器把 `payload/` 压缩并内嵌，因此使用者只需一个 EXE 即可开始安装。

修改源码后请重新构建，并重新计算发布文件的 SHA256。
编译时间戳等因素会让重建的 EXE 哈希不同，不必要求字节级一致。

## 目录结构

```text
Installer.cs                 # C# WinForms 安装界面；内嵌载荷解压与安装入口
Rebuild.ps1                  # 本地重建安装 EXE
payload/
  dependencies.json          # 上游下载地址、版本与 SHA256
  requirements-lock.txt      # 已解析的基础 Python 依赖
  THIRD_PARTY.md             # 第三方来源、许可与首次登录说明
  licenses/                  # 随包提供的上游许可
  backend/
    launch_backend.py
    app/                     # AstrBot 后端及集成修改后的源码
  templates/plugins/         # 上述五个插件
  tools/video-parser/        # PHP 视频解析器源码（MIT，含 LICENSE）
  scripts/
    install.ps1              # 在线依赖安装、第三方引导、快捷方式与卸载登记
    configure.py             # 生成安装者自己的全新配置
    runtime.py               # 启动服务、账号登录入口与实时日志
    run.ps1                  # 桌面快捷方式的运行入口
    live_console.py          # 实时日志、状态与错误报告
    memory_guard.py          # 专用 Ollama 内存监控与恢复
    uninstall.ps1            # 卸载程序组件，保留个人数据与模型目录
```

## 组件来源与许可

这是集成项目，第三方代码各按上游许可分发，不应整体宣称为同一许可。

- [AstrBot](https://github.com/AstrBotDevs/AstrBot)（AGPL-3.0）：后端主体，
  本仓库中的修改版同样遵循 AGPL-3.0，对应源码即 `payload/backend/app/`。
- [short_videos](https://github.com/jiuhunwl/short_videos)（MIT）：视频解析器，
  许可文本见 `payload/tools/video-parser/LICENSE`。
- [uv](https://github.com/astral-sh/uv)、[Ollama](https://github.com/ollama/ollama)、
  [FFmpeg](https://ffmpeg.org/download.html)、
  [PHP](https://windows.php.net/download/)、[PyTorch](https://pytorch.org/)、
  [RVC](https://github.com/RVC-Project/Retrieval-based-Voice-Conversion-WebUI)、
  [rvc-next](https://github.com/licyk/rvc-next)：安装时从上游获取。
- [NapCatQQ](https://github.com/NapNeko/NapCatQQ/releases)：使用官方独立安装向导。
- SnowLuma 不随包提供，也不由本安装器自动部署；如需使用请自行安装并配置本机
  OneBot 反向连接。

详细来源清单见 `payload/THIRD_PARTY.md`，随包许可文本见 `payload/licenses/`。
逐项引用与修改说明见 [NOTICE.md](NOTICE.md)。

## 验证状态

已通过：

- EXE 编译、载荷内嵌与解包。
- PowerShell 脚本语法与 UTF-8 中文编码。
- 独立下载的 Python、独立虚拟环境与基础依赖安装。
- 隔离后端启动、HTTP 接口与新生成后台密码登录。
- 中文与空格目录、模型与缓存目录分离。
- 主人号动态配置、中性人设与新建音乐登录资料隔离。
- 发行文件排除原账号、私人数据库与原浏览器资料。

尚未完成实机验证：

- 另一台物理电脑从零完成全部安装。
- 新 QQ 账号扫码、桥接连接与真实群消息收发。
- 新环境下的完整 UVR5/RVC 翻唱及不同显卡兼容性。

## 已知与限制

- 仅支持 Windows 10/11 64 位；安装过程需要联网。
- 网络受限时安装会停止并生成报告，不会把未完成的依赖安装标记为成功。
- 自动找视频只搜索 B 站；直接发来的其他已支持平台链接仍可解析。
