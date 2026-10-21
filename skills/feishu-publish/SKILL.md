---
name: feishu-publish
description: 使用已授权的飞书用户身份，将本地 Markdown、纯文本、Word 或根据需求撰写的内容创建为可编辑飞书云文档；支持回读检查、重复请求去重和中断记录。用于发布新文档，不用于消息发送或已有文档局部编辑。
---

# 飞书用户身份发布

脚本就在本 skill 的 `scripts/` 中，不依赖其他 skill。下文 `PUBLISH` 指
`python3 <本 skill 的绝对路径>/scripts/publish.py`；完整仓库安装后也可用 `feishu-publish`。
依赖 Python 3.9+、Linux/macOS，以及独立安装的 `feishu-cli` v1.43.0。
上游安装包见 [官方项目 Release](https://github.com/riba2534/feishu-cli/releases/tag/v1.43.0)。

用户请求发布即授权发布其指定内容；沿用已有授权，不逐步询问确认。
自然语言需求先完成文稿，保存为 UTF-8 Markdown，再发布。只导入任务需要的文件和素材。

## 首次设置

在目标服务器执行；授权链接可在用户自己的电脑或手机打开，服务器无需桌面浏览器。

```bash
feishu-cli profile add document-publisher
feishu-cli --profile document-publisher config create-app --save
# 打开上一步创建应用的链接，选择用户所属组织并确认。
PUBLISH configure --profile document-publisher --identity user
PUBLISH login
# 打开授权链接，使用同一个账号和组织确认文档访问。
PUBLISH doctor --online
```

将 `PUBLISH` 替换成上述实际命令。上游不在 PATH 时，`configure` 可加 `--cli /absolute/path/to/feishu-cli`。
如果应用创建受到组织限制，报告实际错误，由用户在开放平台配置自己的应用；不借用其他应用。
`doctor --online` 只验证授权用户可识别，不证明文档写入或目标文件夹可访问。

首次默认申请 `auth:user.id:read`、`offline_access`、`docx:document`。
图片/附件需 `login --media`，Word 需 `login --word`，后者申请文档媒体上传和导入权限。
应用本身也须获准这些权限；复杂图表可能另需画板权限，应根据实际错误单独说明。
不申请消息发送权限，不填写邮箱，不额外添加协作者，不转移所有权。

## 发布与回读

```bash
PUBLISH publish /absolute/path/report.md --title '本周项目进展' --expect-text '全文结束标记'
PUBLISH publish /absolute/path/report.md --folder '飞书云盘文件夹链接或token'
PUBLISH publish /absolute/path/report.md --asset /absolute/path/figure.png
PUBLISH publish /absolute/path/report.txt
PUBLISH publish /absolute/path/report.docx
PUBLISH verify <上次结果的key>
```

- 标题默认使用文件名；不指定文件夹时由飞书接口决定默认位置。只接受云盘文件夹，不把 wiki 文档节点当文件夹。
- Markdown 由上游转成原生标题、段落、列表、表格和代码块；纯文本按字面写入段落；Word 使用导入任务。输入和每个声明素材上限 20 MiB。
- Markdown 引用的本地图片/附件逐个用 `--asset` 声明，纳入去重哈希。该参数只登记依赖，不会插入未被 Markdown 引用的素材。
  远程 URL 的内容不参与哈希；需要可复核发布时先下载到本地并修改引用。其他未声明依赖变化不会触发新的发布。
- `--expect-text` 可重复，适合检查末尾标记、关键结果和表格文字。`ok: true` 表示导入报告及本轮回读检查通过；
  Markdown/Word 不做全文逐字比对，图片、复杂表格和排版仍需实际访问验收。纯文本比较完整文字，忽略空白差异。
- 返回文档链接、检查结果和 `key`，保留失败项；不要把只读可访问说成完整视觉验收。

## 重复请求与中断

默认状态目录为 `~/.local/state/feishu-publish`，目录 0700、记录 0600。
去重键包含授权用户/应用、输入哈希、标题、目标文件夹和可选业务编号；同一状态目录内的重复请求复用原记录。
不同服务器必须明确共用支持文件锁的状态目录才能协调，独立目录不跨机器去重。
所有命令均可在子命令前加 `--state-dir /path/to/private-state`。

写入前先保存阶段，创建成功立即保存文档编号和链接；异常后不重放整个发布。
有链接则先核对现有内容；Word 有 ticket 时 `verify` 查询原任务。创建响应丢失且没有编号时，核查云盘后再决定后续处理。
`verify` 不补写正文。部分内容失败时保留已有文档，依据回读结果制定有明确范围的修复，不删除记录来强制重试。
确实需要另一份文档时使用 `--copy-key <固定业务编号>`；相同业务编号仍去重。

凭据和令牌由上游 profile 管理，本工具只存 profile 选择和发布记录。
用户令牌不输出、不写入记录、不放入命令行参数；Markdown 导入通过子进程环境传递。
授权失效直接报错，不切换应用身份。`scripts/login.py` 是默认状态目录下的兼容登录入口。
