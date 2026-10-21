#!/usr/bin/env python3
"""Install this wrapper and optional agent skill without replacing existing files."""

import argparse
from pathlib import Path
import shutil
import sys


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prefix", type=Path, default=Path.home() / ".local")
    parser.add_argument("--agent", choices=("codex", "claude"), action="append", default=[])
    parser.add_argument("--codex-skills", type=Path, default=Path.home() / ".codex/skills")
    parser.add_argument("--claude-skills", type=Path, default=Path.home() / ".claude/skills")
    opts = parser.parse_args()
    source = Path(__file__).resolve().parent.parent
    package = opts.prefix.expanduser().absolute() / "share/feishu-docx-skill"
    command = opts.prefix.expanduser().absolute() / "bin/feishu-docx"
    links = []
    for agent in sorted(set(opts.agent)):
        directory = getattr(opts, agent + "_skills").expanduser().absolute()
        links.append(directory / "feishu-docx")
    for path in [package, command, *links]:
        if path.exists() or path.is_symlink():
            parser.error(f"目标已存在，未覆盖：{path}。请核对旧安装或选择其他路径。")
    created = []
    try:
        package.parent.mkdir(parents=True, exist_ok=True)
        package.mkdir()
        created.append(package)
        shutil.copytree(source / "bin", package / "bin")
        shutil.copytree(source / "skills", package / "skills")
        shutil.copy2(source / "LICENSE", package / "LICENSE")
        (package / "bin/feishu-docx").chmod(0o755)
        command.parent.mkdir(parents=True, exist_ok=True)
        command.symlink_to(package / "bin/feishu-docx")
        created.append(command)
        for link in links:
            link.parent.mkdir(parents=True, exist_ok=True)
            link.symlink_to(package / "skills/feishu-docx")
            created.append(link)
    except OSError:
        for path in reversed(created):
            if path.is_symlink():
                path.unlink()
            elif path.is_dir():
                shutil.rmtree(path)
        raise
    print(f"已安装：{command}")
    for link in links:
        print(f"Skill：{link}")
    print("请确认 bin 目录在 PATH 中，然后运行 feishu-docx setup。")
    print("未安装上游 CLI、未写凭据、未修改 agent 配置、未访问飞书。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
