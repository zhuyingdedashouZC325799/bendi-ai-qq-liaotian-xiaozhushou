# 引用与修改声明 / Attribution Notice

本仓库（本地 QQ 智能助手）是在以下**公开项目**基础上集成、修改而成。
每项均标注来源、修改性质与许可，便于使用者判断与遵守。

## 1. AstrBot —— 主要基础（修改后分发）

- 来源：https://github.com/AstrBotDevs/AstrBot
- 许可：AGPL-3.0（许可文本见 `payload/licenses/AstrBot-AGPL.txt`）
- 关系：`payload/backend/app/` 是 AstrBot 的**修改版源码**。本项目在其之上完成了
  Windows 便携化移植与集成改动，主要包括：
  - 便携设置层 `payload/backend/app/portable_settings.py`：安装路径、主人 QQ 号、
    人设与端口由安装者配置，不写死任何一台机器的路径。
  - 本地启动入口 `payload/backend/launch_backend.py` 与配套脚本
    （`payload/scripts/runtime.py`、`live_console.py`、`configure.py`、
    `memory_guard.py`）。
  - 面向 QQ 场景的插件集成与桌面操作入口。
- 义务：按 AGPL-3.0 分发修改版时应保留许可与来源声明，并向使用者提供对应源码；
  本仓库即作为该对应源码的公开位置。**不将 AstrBot 部分改标为其他许可。**

## 2. short_videos 视频解析器 —— 修改后再分发

- 来源：https://github.com/jiuhunwl/short_videos
- 许可：MIT（原始许可文本已随包提供：`payload/tools/video-parser/LICENSE`）
- 关系：`payload/tools/video-parser/` 为其 PHP 解析器源码的修改版，保留上游署名。

## 3. 安装时从上游获取、未内置也未修改

| 项目 | 来源 | 说明 |
| --- | --- | --- |
| uv / Python 运行环境 | https://github.com/astral-sh/uv | 在线下载，校验 SHA256 |
| Ollama 与 Qwen 模型 | https://github.com/ollama/ollama、https://ollama.com/library/qwen3-vl | 在线下载 |
| NapCat | https://github.com/NapNeko/NapCatQQ/releases | 仅调用官方独立安装向导 |
| PyTorch | https://pytorch.org/ | 在线安装 |
| RVC / UVR5 | https://github.com/RVC-Project/Retrieval-based-Voice-Conversion-WebUI | 在线获取 |
| rvc-next | https://github.com/licyk/rvc-next | 在线获取 |
| FFmpeg | https://ffmpeg.org/download.html、https://www.gyan.dev/ffmpeg/builds/ | 在线获取 |
| PHP | https://windows.php.net/download/ | 在线获取 |

## 4. 未内置、不自动部署

- SnowLuma：不随包提供、不自动部署。使用者如需使用请自行安装，并在其官方协议
  允许范围内配置本机 OneBot 反向连接；安装器仅保存所选目录。

## 5. 本项目自有部分

`Installer.cs`、`Rebuild.ps1`、`payload/scripts/`、`payload/templates/plugins/`
中的集成与安装逻辑为本项目自行编写或修改的内容，随本仓库公开。
其中若包含上游代码，仍以上游许可为准。
