# 开发与验收

## 环境与运行

Windows 10/11、Python 3.12+、已登录的桌面微信。运行 `setup.ps1` 安装到 `.deps`；编辑 `local-runtime.json` 的 data_root 和目标联系人，或提供 `peer.json` 的稳定账号标识。机器配置不会提交到 Git。

运行 `python dashboard.py` 启动页面且保持暂停；运行 `start.ps1` 会打开页面并开启监听。默认人工确认。`stop.ps1` 暂停处理但保留页面。

Codex 模式需要 PATH 中可用且已登录的 Codex CLI。自定义 API 可以在页面配置，不需要 Codex 登录。

## 测试

```powershell
python -m unittest test_dashboard test_profiles test_usage
python -m unittest test_media_context test_sticker_failure
npm install --prefix app-test-tools
node test_profiles_browser.cjs
```

第一组以内存数据库和本地 HTTP 测试服务验证状态机、模型协议、凭据隔离和 token 计数；不发送微信消息。第二组需要本机依赖及 Windows 适配模块。

`test_browser.cjs` / `test_usage_browser.cjs` 会使用当前本机 Codex 生成测试草稿，消耗实际模型用量，但不点击确认发送。测试前确认人工审核模式；不要在自动模式下运行主动生成验收。截图、测试数据库和用量证据属于私有运行产物，不提交。

## 修改规则

1. 修改模型接口时覆盖 Chat Completions、Responses、普通 JSON、SSE、缺失 usage 和中断。
2. 修改发送流程时覆盖重复确认、对话过期、暂停、部分发送和结果不明，不能把“不确定”改成自动重试。
3. 修改配置时覆盖旧数据迁移、不同配置的 Key 隔离、未启用配置的编辑、正在生成时切换模型、删除行为。
4. 更新上游适配器前核对 LICENSE 和 SOURCES.json，审查 AST 提取范围，先读后写，在自己的文件传输助手上验证。不要用真实联系人作为开发测试接收人。
5. 提交前运行 `git diff --cached`，确认没有本机配置、聊天、截图、密钥、日志、模型输出或真实风格样本。

## 代码提交范围

`.gitignore` 默认排除所有文件，再逐项放行程序、测试、文档和许可证。新源码文件需要显式加入放行列表。不要使用 `git add -f` 绕过私有数据排除。

已知测试限制：自定义服务的真实模型、账户权限、图片支持和流式兼容性必须用用户自己的配置在页面测试；本地模拟 HTTP 测试不能证明所有服务商兼容。
