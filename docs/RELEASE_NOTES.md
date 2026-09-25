# 微信回复台 v0.1.0

首个 Windows x64 桌面发行版。

- 独立桌面窗口，无需另装 Python；支持首次填写微信数据目录和联系人。
- 多联系人分别启停，聊天、草稿与用量隔离。
- 多模型配置、人工确认 / 自动回复、主动生成、提示词设置和 Token 统计。
- 明确本人 / 对方与图片归属，修正主动生成时接自己话的问题。
- 应用内“检查更新”检测 GitHub 正式版本，并提供新版下载页；此版不含静默安装或自动重启。

## 下载与使用

推荐下载 `windows-x64-setup.exe` 安装包。也可解压 portable.zip 并运行其中的 WechatReplyAssistant.exe。
保留 portable 文件夹内的 `_internal`，不要只复制 exe。

需要 Windows 10/11 x64、已登录的兼容电脑版微信，以及 Microsoft Edge WebView2 Runtime。
首次启动填写包含账号文件夹的 `xwechat_files` 目录和首位联系人的微信号 / wxid，然后配置模型。
内置 Codex 模式需要用户自行安装并登录 Codex CLI；使用自定义 API 则不需要 Codex。
微信适配依赖客户端版本，目前仅在开发机环境验证，不能保证任意微信版本均兼容。

新安装不包含任何聊天、API Key、微信账号配置或私人表情目录。用户配置保存在 `%LOCALAPPDATA%\WechatReplyAssistant`；安装升级不覆盖，卸载也保留。
此版未做 Authenticode 签名，Windows 可能显示未知发布者；校验文件见 SHA256SUMS.txt。
关闭桌面窗口会结束监听；重启后需在页面手动开始监听，不补发旧消息。

## 更新

检查更新 → 打开新版下载页 → 下载 setup.exe → 关闭应用 → 安装覆盖。
尚不支持应用内自动下载安装、回滚或后台常驻。
