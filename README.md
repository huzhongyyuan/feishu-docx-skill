# feishu-docx-skill

让 Codex / Claude Code 从 Linux 服务器或 macOS 直接读写飞书文档：报告、工作日记、周报、图片与视频附件。

A dedicated Feishu document profile and reusable agent skill, built on
[riba2534/feishu-cli](https://github.com/riba2534/feishu-cli).

本项目提供独立应用封装、交互式凭据配置、安装器和 agent skill。
飞书 API、文档转换和媒体上传由上游 `feishu-cli` 实现；本仓库不分发上游二进制或其技能文档。

```text
Codex / Claude Code
        │ 读取 skill
        ▼
   feishu-docx ── 独立 profile ── feishu-cli ── 飞书 API
        ▲
  服务器上的 Markdown、图片、视频
```

## 安装

要求 Python 3.9+、Linux 或 macOS，以及上游 `feishu-cli`。本项目以 **v1.43.0** 为兼容基线；
其他版本需根据其 `--help` 核对命令。上游安装包和校验文件见
[v1.43.0 Release](https://github.com/riba2534/feishu-cli/releases/tag/v1.43.0)。
将对应系统的 `feishu-cli` 放到 PATH 后：

```bash
git clone https://github.com/huzhongyyuan/feishu-docx-skill.git
cd feishu-docx-skill
python3 scripts/install.py --agent codex --agent claude
export PATH="$HOME/.local/bin:$PATH"
feishu-docx --version
feishu-docx setup
```

`setup` 在终端询问 App ID 和 App Secret，Secret 不回显。
先在[飞书开放平台](https://open.feishu.cn/app)创建你自己的应用并开通所需权限。
配置只保存在 `~/.feishu-cli/profiles/feishu-docx/config.yaml`（0600）；
这是 JSON 格式的 YAML 文件，不会进入本仓库。

上游程序不在 PATH 时可设置 `FEISHU_DOCX_CLI=/absolute/path/to/feishu-cli`。
安装器不下载依赖、不运行远端脚本、不修改 shell 或 agent 的模型配置，也不会覆盖已有安装。
可通过 `--prefix`、`--codex-skills`、`--claude-skills` 选择其他安装位置。
Codex 使用自定义配置目录时，将 `--codex-skills` 指向该目录的 `skills` 子目录。

默认安装位置：

| 内容 | 路径 |
| --- | --- |
| 命令 | `~/.local/bin/feishu-docx` |
| 程序与 skill | `~/.local/share/feishu-docx-skill/` |
| Codex 发现入口 | `~/.codex/skills/feishu-docx/` |
| Claude 发现入口 | `~/.claude/skills/feishu-docx/` |

只装命令可省略 `--agent`。安装后让对应 agent 在下一次加载技能时发现它；
skill 文件存在不代表已经运行的会话立即加载了它。

## 使用

向 agent 发出明确任务即可，例如：

> 使用 feishu-docx skill，把本次实验结果和 demo.mp4 更新到这份飞书文档：〈链接〉。
> 先读取现有内容，更新“实验结果”章节，写完回读核验并返回链接。

也可直接调用命令：

```bash
# 读取已有文档（也支持底层为 docx 的 /wiki/ 链接）
feishu-docx doc export "飞书文档链接" -o /tmp/document.md

# 从 Markdown 新建文档
feishu-docx doc import examples/report.md --title "实验报告示例"

# 向已有文档追加 Markdown
feishu-docx doc content-update "飞书文档链接" \
  --mode append --markdown-file examples/report.md

# 插入图片 / 视频附件
feishu-docx doc media-insert "飞书文档链接" --file figure.png --type image
feishu-docx doc media-insert "飞书文档链接" --file demo.mp4 --type file --file-view preview

# 写后回读
feishu-docx doc get "飞书文档链接" -o json
feishu-docx doc blocks "飞书文档链接" --raw
```

图片和视频示例需要你自己的文件。视频上传回执与实际可播放性须分别验证。
详细操作见 [SKILL.md](skills/feishu-docx/SKILL.md)。

## 认证与权限

该工具使用你的独立应用。应用获批 API scope 后，还需要目标文档或知识库的访问权限；
安装 skill 本身不会获得文档权限。最常用的是 `docx:document`（读写）和
`docs:document.media:upload`（上传媒体）。只读任务可按需使用只读 scope。
知识库解析、添加协作者的要求见 [访问说明](skills/feishu-docx/references/access.md)。

新文档可能只有机器人可见，按用户指定的接收人授予访问权限，不能默认公开。
独立 profile 中显式保存的 OAuth token 可能被上游读类命令优先使用。

封装会移除继承的 `FEISHU_*` 环境变量，并拒绝命令行身份覆盖；
它用于避免误用其他应用，不是操作系统沙箱或只读权限网关。
凭据文件由 `setup` 管理；它接受 JSON 格式，不解析任意 YAML。
轮换凭据使用 `feishu-docx setup --replace`。不要将 Secret 放进聊天或命令行参数。

## 验证与贡献

```bash
python3 -m unittest discover -s tests -v

# 可选：使用真实上游二进制验证配置解析及命令参数；仍不访问飞书 API
FEISHU_DOCX_TEST_CLI=/absolute/path/to/feishu-cli python3 -m unittest discover -s tests -v
```

测试覆盖配置缺失/损坏/权限、身份和所有权环境隔离、参数传递、并发配置写入、
安装器不覆盖现有文件等行为。测试使用临时目录与假凭据，不向飞书发送内容。
GitHub Actions 在 Linux / macOS 和多个 Python 版本运行同一测试集。

本项目不附带生产服务器清单、实际文档链接、凭据或内部测试日志。
离线测试不能证明你的飞书应用有线上读写权限；部署后先读取用户指定的文档，
再在已授权的目标上写入并回读核验。

卸载时删除本安装创建的命令链接、agent skill 链接和程序目录即可。
凭据目录独立保留，是否删除由你决定；若曾共用同名 profile，先核对其他调用方。

## License / Attribution

本仓库原创封装与 skill 采用 [MIT License](LICENSE)。
依赖的 [feishu-cli](https://github.com/riba2534/feishu-cli) 由 riba2534 及贡献者维护，
其许可证与第三方声明以[上游仓库](https://github.com/riba2534/feishu-cli/blob/main/THIRD_PARTY_NOTICES.md)为准。
本项目不是飞书官方产品。
