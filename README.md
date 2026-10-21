# feishu-docx-skill

让 Linux 远程服务器或 macOS 上的 Agent 直接读写飞书文档。
**一次用户授权后，给出本地文件或写作需求，即可创建可编辑文档并取得链接。**

v0.2.0 将用户身份发布流程与原有应用 profile 工具放进同一个仓库、安装器和测试集。
用户发布入口为 `feishu-publish`，原有读取和编辑入口 `feishu-docx` 保留。
无需邮箱或机器人消息，服务器无需图形桌面；授权链接在自己的电脑或手机打开即可。

| 入口 | 适合的任务 | 身份与结果管理 |
| --- | --- | --- |
| `feishu-publish` | 将 Markdown、纯文本、Word 或 Agent 生成的内容发布为新文档 | 严格使用授权用户；保存记录、去重、回读检查 |
| `feishu-docx` | 读取、局部更新已有文档，插入图片和视频附件 | 沿用独立应用 profile；不提供发布去重 |

本项目基于 [riba2534/feishu-cli](https://github.com/riba2534/feishu-cli)。
Markdown 转换、OAuth 登录和令牌刷新由上游负责；本项目实现用户身份约束、发布流程和本地记录。
本次合并依据用户提供的 `feishu-publish v1.1.0` 功能说明实现，未取得该 ZIP 源码，
因此不是该 ZIP 的源码合并，也不沿用其版本号或实测结论。

## 安装

要求 Python 3.9+、Linux/macOS；上游兼容基线为 **feishu-cli v1.43.0**。
从 [v1.43.0 Release](https://github.com/riba2534/feishu-cli/releases/tag/v1.43.0)
下载对应平台的包并核对 SHA-256，将二进制放入 PATH。上游二进制不随本仓库分发。

```bash
git clone https://github.com/huzhongyyuan/feishu-docx-skill.git
cd feishu-docx-skill
python3 scripts/install.py --agent codex --agent claude
export PATH="$HOME/.local/bin:$PATH"
feishu-cli --version
feishu-publish --version
```

安装器同时安装两个命令和两个 skill。只装命令可省略 `--agent`；可指定 `--prefix`、
`--codex-skills`、`--claude-skills`。它不下载依赖、不修改 shell/模型设置、不复制凭据。
默认程序目录是 `~/.local/share/feishu-docx-skill`，命令在 `~/.local/bin`，
skill 链接在 `~/.codex/skills` / `~/.claude/skills`。

升级已有的本仓库安装：

```bash
git pull --ff-only
python3 scripts/install.py --upgrade --agent codex --agent claude
```

升级只替换可识别的本仓库程序及链接，保留旧程序目录备份，并输出备份路径。
如发现独立的同名 skill 或其他命令，停止并报告冲突，不覆盖。
凭据和发布记录位于程序目录之外，升级会保留它们。

## 首次用户授权

在目标服务器执行：

```bash
feishu-cli profile add document-publisher
feishu-cli --profile document-publisher config create-app --save
```

打开命令给出的链接，用自己的飞书账号选择组织并确认创建应用。随后执行：

```bash
feishu-publish configure --profile document-publisher --identity user
feishu-publish login
feishu-publish doctor --online
```

再次打开授权链接，用同一账号和组织确认文档访问。两次确认分别是创建应用、授予用户访问权限。
如组织限制创建应用，应由该组织按实际要求配置；工具不会绕过限制。
不在 PATH 的上游可用 `configure --cli /absolute/path/to/feishu-cli` 指定。

默认只请求用户标识、登录续期和文档读写权限。图片/附件用 `feishu-publish login --media`，
Word 用 `feishu-publish login --word` 补充文档媒体上传/导入权限；应用自身也需开通相应权限。
复杂图表可能需要额外画板权限及实际显示检查。
不请求消息发送权限，不额外添加协作者，不转移所有权。

## 发布

```bash
feishu-publish publish /path/report.md --title '本周项目进展' --expect-text '全文结束标记'
feishu-publish publish /path/report.md --folder '云盘文件夹链接或token'
feishu-publish publish /path/report.md --asset /path/figure.png
feishu-publish publish /path/report.txt
feishu-publish publish /path/report.docx
```

或告诉 Agent：

> 使用 $feishu-publish，把 /path/report.md 发布到飞书，标题为“本周项目进展”。

> 根据已确认的方案撰写功能说明，保存为飞书文档并返回链接和检查结果。

Agent 先生成文稿，再调用发布脚本。未指定标题时使用文件名，未指定文件夹时使用 API 默认位置。
支持 `.md`、`.markdown`、`.txt`、`.docx`、`.doc`；输入及每个声明素材不超过 20 MiB。
Markdown 转为原生文档块，纯文本按字面写入，Word 经飞书导入任务转换。

结果包含 `url`、`key`、`state`、`import`、`readback`、`error`。
`ok: true` 仅表示导入报告和回读检查通过；Markdown/Word 不做全文逐字比对，
可重复添加 `--expect-text` 检查关键文字。纯文本比较完整文字并忽略空白差异。
图片、复杂表格与排版需要打开文档验收，接口可读不等于全部内容和视觉效果已验收。

## 去重与中断处理

发布记录默认在 `~/.local/state/feishu-publish/receipts/`；目录 0700、文件 0600。
记录包含输入哈希、创建身份、目标、文档链接、写入阶段、回读结果及失败历史，不保存 OAuth 令牌。
同一授权用户/应用、相同内容、标题和目标的请求复用已有记录，不再创建。
同一状态目录中的并发请求通过文件锁协调；独立机器/状态目录不跨机器去重。

Markdown 的本地图片和附件用 `--asset` 逐个登记内容哈希；它不自动插入素材。
未声明素材、远程图片 URL 内容的变化无法由 Markdown 文件哈希检测，
需可复核的发布应先下载素材并改为本地引用。发布途中检测到源文件或已声明素材改变，会报告失败。

创建/写入前保存阶段；创建成功立即保存文档编号。超时或中断保留已有链接/Word ticket，
再次运行不会重放整篇。用以下命令只读核查或继续查询原 Word 任务：

```bash
feishu-publish verify <上次返回的key>
```

`verify` 不补写部分失败内容。没有文档编号的未知创建结果需先核查云盘。
确实需要另一份时使用 `--copy-key <固定业务编号>`，同编号仍去重；不要靠删除记录重试。
发布器自身不重试写请求；Markdown 转换内部沿用上游的有限请求重试，不自动重跑整个导入。
自定义状态目录放在子命令前：`feishu-publish --state-dir /private/state publish /path/report.md`。

用户授权由 `feishu-cli` 管理和刷新。每次发布先核实用户，随后固定使用该用户令牌；
令牌不出现在命令行参数、输出或发布记录中，Markdown 子进程通过环境接收令牌。
授权失败、权限不足或超时直接报告，不切换应用身份。
`doctor --online` 只验证授权身份，不代表已测试写权限。

## 独立 ZIP skill

[Releases](https://github.com/huzhongyyuan/feishu-docx-skill/releases) 提供 `feishu-publish-v0.2.0.zip` 和 SHA-256。
ZIP 内含自足的 `feishu-publish/` 目录与 Python 脚本，不含凭据或上游二进制。
解压前检查同名目录，避免覆盖原安装：

```bash
mkdir -p "$HOME/.codex/skills"
# 仅在目标 feishu-publish 目录不存在时解压
unzip feishu-publish-v0.2.0.zip -d "$HOME/.codex/skills"
python3 "$HOME/.codex/skills/feishu-publish/scripts/publish.py" configure --profile document-publisher --identity user
python3 "$HOME/.codex/skills/feishu-publish/scripts/login.py"
```

完整设置和故障处理见 [feishu-publish skill](skills/feishu-publish/SKILL.md)。
ZIP 与完整安装二选一即可，不把已安装的同名 skill 再覆盖一遍。

## 原有文档读取与编辑

应用 profile 按原方法配置，Secret 由终端交互输入，不放到聊天或参数里：

```bash
feishu-docx setup
feishu-docx doc export '飞书文档链接' -o /tmp/document.md
feishu-docx doc content-update '飞书文档链接' --mode append --markdown-file /path/update.md
feishu-docx doc media-insert '飞书文档链接' --file /path/demo.mp4 --type file --file-view preview
feishu-docx doc get '飞书文档链接' -o json
```

应用需要 API scope 和目标资源权限。已有文档先读取再修改，写后回读；视频播放另行验收。
此入口保留上游身份处理方式，不提供新发布入口的严格用户身份保证。
详情见 [feishu-docx skill](skills/feishu-docx/SKILL.md) 与[访问说明](skills/feishu-docx/references/access.md)。

## 测试与开发

```bash
python3 -m unittest discover -s tests -v
FEISHU_DOCX_TEST_CLI=/absolute/path/to/feishu-cli python3 -m unittest discover -s tests -v
# 构建仅包含已纳入 Git 的 skill 文件的 ZIP
python3 scripts/package_skill.py
```

测试覆盖身份隔离、去重、并发锁、超时/中断、部分失败、回读恢复、Word ticket 恢复、
输入变化、凭据不落盘及安装升级。可选真实上游测试将 v1.43.0 导入请求发到本地模拟服务，
检查原生标题/列表/代码块转换、用户令牌和过期授权不回退；不访问真实飞书文档。
GitHub Actions 在 Linux/macOS、多 Python 版本运行离线测试。

本版本新增发布链路的真实飞书 OAuth、Word 转换及视觉验收仍需在部署账号下完成；
仓库测试不作为这些线上验收的替代。仓库不含生产凭据、实际文档链接或服务器清单。

## 许可证

本仓库原创代码与 skill 使用 [MIT License](LICENSE)。上游 `feishu-cli` 的许可证与第三方声明
以[上游仓库](https://github.com/riba2534/feishu-cli/blob/main/THIRD_PARTY_NOTICES.md)为准。
本项目不是飞书官方产品。
