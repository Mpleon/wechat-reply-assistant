# 本机 HTTP API

默认地址 `http://127.0.0.1:8765`。非本机 Host、跨域 Origin / Sec-Fetch-Site 被拒绝。POST 需要 `X-CSRF-Token`，从 GET `/api/state` 获取。错误使用 `{ "error": "..." }`；400 为无效输入，409 为状态或版本冲突。

## 查看

- GET `/api/health`：服务标识与 PID。
- GET `/api/state`：运行状态、当前设置、模型配置列表、最近消息、草稿、事件、用量与测试状态。绝不返回密钥。
- GET `/media/stickers/<file>`、`/media/incoming/<file>`：受限媒体目录，不提供任意文件下载。

## 模型配置

POST `/api/profiles/save`：

```json
{
  "id": null,
  "version": null,
  "profile": {
    "name": "日常聊天",
    "provider": "custom",
    "base_url": "https://api.example.com/v1",
    "api_model": "MODEL_ID",
    "api_protocol": "chat_completions",
    "api_stream": true
  },
  "api_key": "USER_SUPPLIED_KEY",
  "clear_key": false
}
```

新增时 id/version 留空；编辑带上已有 ID 与版本号。空 Key 保留此配置已有凭据，clear_key 显式删除。保存不等于启用。

- POST `/api/profiles/activate`：`{"id":"PROFILE_ID"}`。
- POST `/api/profiles/delete`：`{"id":"PROFILE_ID","version":1}`；拒绝删除内置或当前启用项。
- POST `/api/model-test`：提交 `profile_id`、当前表单 `settings`、可选 `api_key`、`testcase`、`with_image`。未保存的新配置传空 profile_id，不会借用当前配置的 Key。测试结果从 state.tests 查询，不向微信发送。

## 运行及草稿

- POST `/api/control`：`{"enabled":true/false}`。启动监听从当前消息开始；暂停会使生成中、排队中的任务失效。
- POST `/api/reconnect`：重新连接本机微信数据。
- POST `/api/generate`：`{"instruction":"想聊的话题或要求"}`，没有新消息也可生成。
- POST `/api/jobs/<id>/edit`：version、parts，保存编辑。
- POST `/api/jobs/<id>/approve`：version、parts，确认发送。
- POST `/api/jobs/<id>/revise`：version、parts、instruction，生成新版本。
- POST `/api/jobs/<id>/skip`：version，跳过。
- POST `/api/media`：message_id，请求读取消息媒体。

parts 为 1–4 个 `{kind:"text"|"sticker",value:"文字或表情标识"}`。文本单条最多 500 字，表情必须在可用目录中。服务端固定收件人，客户端不能通过请求换收件人。

POST `/api/settings` 保存 system_prompt、use_style、mode、quiet_seconds。旧客户端提交模型字段时仅尝试更新当前配置；新页面使用独立的模型配置接口。


## 联系人

- `GET /api/state?peer_id=<id>`：返回所选联系人的 runtime/jobs/messages/events/calls，以及全局 contacts 列表。省略 id 兼容原联系人 legacy。
- `POST /api/contacts/add {identifier}`：微信号或内部 wxid，唯一解析后保存，默认暂停。重复账号拒绝。
- control/reconnect/generate/media 和 jobs 操作均支持 `peer_id`。草稿只能在所属联系人下操作。
- `POST /api/control {enabled:false,all:true}`：全部暂停；不支持一键开启所有人。
- 模型、提示词、回复方式设置仍为全局。每个浏览器标签页独立选择联系人。
