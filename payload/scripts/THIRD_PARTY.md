# 组件来源与首次使用

本发行包提供集成安装和经过修改的机器人源码，不包含任何人的登录会话、主人QQ号、人设、聊天数据库或私人音色。

在线安装从上游下载：

- AstrBot 源码（AGPL-3.0）：https://github.com/AstrBotDevs/AstrBot
- uv / Python 运行环境：https://github.com/astral-sh/uv
- Ollama / Qwen 模型：https://github.com/ollama/ollama ，https://ollama.com/library/qwen3-vl
- FFmpeg：https://ffmpeg.org/download.html ，Windows 构建 https://www.gyan.dev/ffmpeg/builds/
- PHP：https://windows.php.net/download/
- RVC / UVR5：https://github.com/RVC-Project/Retrieval-based-Voice-Conversion-WebUI
- rvc-next：https://github.com/licyk/rvc-next
- PyTorch：https://pytorch.org/
- 视频解析器：https://github.com/jiuhunwl/short_videos（MIT；修改版源码随包提供）
- NapCat 官方独立引导：https://github.com/NapNeko/NapCatQQ/releases

SnowLuma 不随包提供，也不会由本安装器自动部署。选择 SnowLuma 时应自行安装，在其官方协议允许的范围内使用，再手动配置本机 OneBot 反向连接。安装器仅保存你选择的目录。

安装过程会校验 GitHub Release 提供的 SHA256；运行时模型由上游工具下载。网络受限时会停止并生成报告，不会将未完成的依赖安装显示为成功。

首次使用：

1. 填写机器人 QQ、主人 QQ 与可选人设，分别选择程序、模型、音色与缓存目录。
2. 同意需要的组件后在线安装。翻唱音色需使用者提供匹配的 PTH 与 INDEX。
3. 通过桌面快捷方式启动，在官方 QQ / 接入组件窗口登录自己的机器人账号。
4. 在专用 QQ 音乐窗口登录自己的账号；QQ 登录不能代替 QQ 音乐登录。
5. 本机 `localbot.json` 包含连接令牌与随机后台密码，请勿分享整个已安装目录。分享原始安装 EXE 即可。

当前配置为中性助手；新主人号、人设和所有账号都由安装者独立配置。政治拒绝、媒体筛查与桌面权限保持为应用规则；管理员权限始终依据平台提供的真实QQ号。
