#!/usr/bin/env python3
"""Publish local files as the explicitly authorized Feishu user."""
import argparse
import json
from pathlib import Path
import sys

from publisher import (BASE_SCOPES, CLI, Publisher, PublishError, VERSION,
                       connect, lock, prepare, read_json, safe_text, write_json)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", action="version", version="feishu-publish " + VERSION)
    parser.add_argument("--state-dir", type=Path, default=Path.home() / ".local/state/feishu-publish")
    commands = parser.add_subparsers(dest="action", required=True)
    configure = commands.add_parser("configure", help="保存 profile 选择，不复制凭据")
    configure.add_argument("--profile", default="document-publisher")
    configure.add_argument("--identity", choices=["user"], default="user")
    configure.add_argument("--cli", default="feishu-cli")
    login = commands.add_parser("login", help="由上游 CLI 完成用户授权并管理令牌")
    login.add_argument("--media", action="store_true", help="额外申请文档媒体上传权限")
    login.add_argument("--word", action="store_true", help="额外申请 Word 导入和媒体上传权限")
    doctor = commands.add_parser("doctor", help="检查依赖；--online 只读验证授权用户")
    doctor.add_argument("--online", action="store_true")
    publish = commands.add_parser("publish", help="创建、写入、回读；重复请求复用已有结果")
    publish.add_argument("file", type=Path)
    publish.add_argument("--title")
    publish.add_argument("--folder", default="")
    publish.add_argument("--asset", action="append", default=[], help="将依赖素材内容纳入输入哈希")
    publish.add_argument("--expect-text", action="append", default=[], help="回读须包含的关键文字，可重复")
    publish.add_argument("--copy-key", default="", help="明确创建另一份时使用固定业务编号；同编号仍去重")
    verify = commands.add_parser("verify", help="只读复查已有文档或查询原 Word 导入 ticket")
    verify.add_argument("key")
    args = parser.parse_args(argv)
    root = args.state_dir.expanduser().absolute()
    try:
        if args.action == "configure":
            cli = CLI(args.profile, args.cli)
            with lock(root, "configuration"):
                write_json(root / "config.json", {"profile": cli.profile, "cli": cli.binary, "identity": "user"})
            result = {"ok": True, "identity": "user", "profile": cli.profile, "version": VERSION}
        else:
            config = read_json(root / "config.json")
            if not isinstance(config, dict) or config.get("identity") != "user":
                raise PublishError("仅支持已明确配置的 user 身份，请先运行 configure --identity user。")
            cli = CLI(config["profile"], config["cli"])
            if args.action == "login":
                scopes = list(BASE_SCOPES)
                if args.media or args.word:
                    scopes.append("docs:document.media:upload")
                if args.word:
                    scopes.append("docs:document:import")
                return cli.login(scopes)
            if args.action == "doctor":
                version = cli.run(["--version"])
                if version.returncode:
                    raise PublishError("无法读取上游版本。")
                result = {"ok": True, "profile": cli.profile, "identity": "user",
                          "version": VERSION, "upstream": version.stdout.strip(),
                          "tested_upstream": "v1.43.0", "online": args.online}
                if args.online:
                    connect(cli)
                    result["authorized_user_verified"] = True
                    result["document_write_tested"] = False
            else:
                # Validate local input before asking the CLI for an access token.
                source = prepare(args.file, args.asset) if args.action == "publish" else None
                api, identity = connect(cli)
                publisher = Publisher(root / "receipts", cli, api, identity)
                result = (publisher.publish(source, args.title, args.folder, args.expect_text, args.copy_key)
                          if source else publisher.verify(args.key))
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result["ok"] else 1
    except (PublishError, OSError, ValueError, KeyError, TypeError) as exc:
        print(json.dumps({"ok": False, "error": safe_text(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
