# 构建与发布

使用 Windows x64、Python 3.12 和 Inno Setup 6。开发环境使用独立 venv：

```powershell
python -m venv .build-venv
.build-venv\Scripts\python.exe -m pip install -r requirements-build.txt
.build-venv\Scripts\python.exe -m unittest test_dashboard test_profiles test_usage test_contacts test_media_context test_sticker_failure test_release
.build-venv\Scripts\python.exe packaging/build.py --iscc 'C:\Program Files (x86)\Inno Setup 6\ISCC.exe'
```

构建脚本只复制 `git ls-files` 中的文件到干净目录，拒绝已跟踪的私人配置。新增文件先纳入 Git；不得把工作目录整体加入安装包。PyInstaller 构建 one-folder 包，使用隔离数据目录运行 `--self-test`，成功后用 Inno Setup 生成安装包、portable ZIP 和 SHA256SUMS。产物位于 `release/<version>`，均不提交 Git。

本地可另外运行 exe 的 `--ui-smoke-test`，用隐藏 WebView2 窗口验证桌面运行时；通过时在指定 `WECHAT_ASSISTANT_HOME` 下写入 ui-test.json。不要用真实联系人发测试消息。

每次发布：修改 `app_version.py` 的 VERSION 和 `docs/RELEASE_NOTES.md`，更新 CHANGELOG，测试后提交并推送。再创建并推送同名版本标签，例如 VERSION=0.1.1 对应 `v0.1.1`。tag 必须与代码版本一致。

```powershell
git tag v0.1.1
git push origin v0.1.1
```

GitHub Actions 在 Windows 上测试、构建并发布 GitHub Release（安装包、ZIP、校验和）；普通 main 提交不发版。也可手动运行工作流，仅生成构建产物，不发布正式版本。需要仓库 Actions 启用且 GITHUB_TOKEN 有 contents:write 权限。失败时修复原因后用新版本标签发布，不覆盖已经发布的版本。

更新检查读取公开仓库 Releases/latest，比较三段数字版本。当前采用用户下载并安装覆盖；没有静默更新、差分更新或代码签名。用户数据与程序目录分开，安装包不携带或删除用户数据。发布前检查上游与打包依赖许可证。源码运行方式与数据目录保持兼容。

技术参考：[PyInstaller 运行路径](https://www.pyinstaller.org/en/stable/runtime-information.html)、[pywebview 打包](https://pywebview.flowrl.com/guide/freezing)、[Inno Setup 编译器参数](https://jrsoftware.org/ishelp/topic_compilercmdline.htm)。
