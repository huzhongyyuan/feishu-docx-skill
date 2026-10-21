---
name: feishu-docx
description: 从本机或远程服务器读取、创建和更新飞书文档，导入 Markdown 并插入图片或视频附件。使用独立的 feishu-docx 应用 profile；适用于实验报告、工作日记、周报和已有飞书文档修改，不用于飞书消息机器人或远程会话控制。
---

# 飞书文档

使用 `~/.local/bin/feishu-docx`；自定义安装时使用实际路径。该命令封装
`feishu-cli`，固定使用 `feishu-docx` profile，不继承其他应用的 `FEISHU_*` 环境变量。
用户已授权的文档操作直接完成；skill 本身不授予外发、共享或定时执行权限。

## 工作流程

1. 确认目标链接、要更新的内容和本地素材。已有文档先读正文与版本，定位待修改章节。
2. 选用下方命令。具体参数以已安装 CLI 的 `--help` 为准；使用匹配版本的上游技能时，
   运行 `feishu-docx skills read feishu-cli-docs references/workflows/write/workflow.md` 等按需读取。
3. 写入后回读被改内容，核对标题、正文和媒体块。记录文档链接、版本、成功项和失败项。
   若要证明视频可播放，需要在飞书客户端验证；上传成功不等于播放验收。

```bash
# 全文读取；大文档先用 doc read "链接" --outline / --heading "章节"
feishu-docx doc export "飞书链接" -o /tmp/document.md

# 将 Markdown 创建为新文档
feishu-docx doc import /path/to/report.md --title "实验报告"

# 向已有文档追加，或替换一个章节
feishu-docx doc content-update "飞书链接" --mode append --markdown-file /path/to/update.md
feishu-docx doc content-update "飞书链接" --mode replace_range \
  --selection-by-title "## 实验结果" --markdown-file /path/to/results.md

# 图片与视频附件
feishu-docx doc media-insert "飞书链接" --file /path/to/figure.png --type image
feishu-docx doc media-insert "飞书链接" --file /path/to/demo.mp4 --type file --file-view preview

# 回读元信息及正文
feishu-docx doc get "飞书链接" -o json
feishu-docx doc blocks "飞书链接" --raw
```

## 关键约定

- 缺配置时引导用户在服务器交互运行 `feishu-docx setup`，不要请求其把 Secret 发到聊天里。
  不打印凭据、不复制其他机器的应用配置、不用其他机器人静默重试。
- 应用需要对应 API scope，以及目标文档/知识库的资源权限。读写失败先区分缺 scope、
  文档未授权和链接错误；详见 [访问与故障定位](references/access.md)。
- `doc import --document-id` 是追加，不能当作替换。局部修改用 `content-update`；
  整篇覆盖须符合用户意图，会影响评论。需要并发保护时使用 `--revision-id`。
- 请求超时或部分失败后先回读，不直接重放创建、追加或上传，避免重复内容。
- 新文档由机器人创建时，先核对用户是否可见。只给用户指定的接收人授权；
  不自动公开、不默认发通知。权限命令按 `feishu-docx perm --help` 核对。
- 科研汇报链接服务器的原始结果，注明版本和采样时间；飞书副本不替代原始证据。
