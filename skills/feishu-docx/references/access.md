# 访问与故障定位

## 配置与身份

`feishu-docx setup` 将 App ID / Secret 写入
`~/.feishu-cli/profiles/feishu-docx/config.yaml`。文件内容为 JSON（合法 YAML 子集），
仅当前用户可读写。封装命令使用显式配置路径，避免读取当前工作目录里的其他配置。

此 profile 与默认 `feishu-cli` profile 分离。若用户明确需要 OAuth，使用上游
`feishu-cli --profile feishu-docx auth login` 并按上游说明完成授权；同 profile
保存的用户 token 可能被读类命令优先采用。封装不声称所有命令都强制使用 Bot 身份。

不传 `--config`、`--profile`、`--bot-app-id`、`--bot-app-secret` 或
`--user-access-token` 给封装；需要另一个身份时明确使用上游工具及对应 profile。
运行前的 `FEISHU_*` 环境变量会被移除；`FEISHU_DOCX_CLI` 仅用于选择上游可执行文件。

## 权限

- 文档读取：`docx:document:readonly`；文档写入：`docx:document`。
- 图片/附件上传：`docs:document.media:upload`。
- 知识库链接解析：`wiki:wiki:readonly`，并需要节点访问权限。
- 添加协作者：`docs:permission.member:create`，且调用者有相应资源管理权限。

应用获批 scope 和某一篇文档的访问权限是两件事。已有文档须把应用加入协作者，
或使用具备访问权限的已授权用户身份。以飞书当前 API 返回的缺失权限为准。

## 诊断顺序

1. `feishu-docx --version`：检查上游程序是否可运行。
2. `feishu-docx doc get "文档链接" -o json`：读取元信息；不要用写入探测权限。
3. 保存不含凭据的错误码和 `log_id`。`forbidden` 排查身份和协作者；缺 scope
   排查应用权限；`not found` 核对链接和节点类型。
4. 成功返回文档元信息后再读取正文。读成功不能证明有写权限。

不在共享日志中使用 `--debug` 展示认证信息。确需深入诊断时先核对日志会输出什么。
命令支持 `/docx/` 链接与底层为 docx 的 `/wiki/` 链接；其他知识库内容类型用相应上游命令。
