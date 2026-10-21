#!/usr/bin/env python3
"""Install both commands and skills; preserve the previous package on explicit upgrade."""
import argparse
from pathlib import Path
import shutil
import sys
import tempfile
import uuid

NAMES = ("feishu-docx", "feishu-publish")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prefix", type=Path, default=Path.home() / ".local")
    parser.add_argument("--agent", choices=("codex", "claude"), action="append", default=[])
    parser.add_argument("--codex-skills", type=Path, default=Path.home() / ".codex/skills")
    parser.add_argument("--claude-skills", type=Path, default=Path.home() / ".claude/skills")
    parser.add_argument("--upgrade", action="store_true", help="升级本安装器管理的安装，保留旧版本备份")
    opts = parser.parse_args()
    source = Path(__file__).resolve().parent.parent
    prefix = opts.prefix.expanduser().absolute()
    package = prefix / "share/feishu-docx-skill"
    links = {prefix / "bin" / name: package / "bin" / name for name in NAMES}
    for agent in sorted(set(opts.agent)):
        directory = getattr(opts, agent + "_skills").expanduser().absolute()
        links.update({directory / name: package / "skills" / name for name in NAMES})
    if package.exists() or package.is_symlink():
        if not opts.upgrade:
            parser.error(f"目标已存在，未覆盖：{package}；核对后用 --upgrade 或选择其他路径。")
        if package.is_symlink() or not all((package / item).is_file() for item in
                                         ("bin/feishu-docx", "skills/feishu-docx/SKILL.md", "LICENSE")):
            parser.error("无法识别旧安装，未覆盖。")
    for link, target in links.items():
        if link.exists() or link.is_symlink():
            if not opts.upgrade or not link.is_symlink() or link.resolve() != target.resolve():
                parser.error(f"目标不是本安装管理的链接，未覆盖：{link}")
    package.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".feishu-install-", dir=package.parent))
    created = []
    backup = None
    installed = False
    try:
        for directory in ("bin", "skills"):
            shutil.copytree(source / directory, staging / directory,
                            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        shutil.copy2(source / "LICENSE", staging / "LICENSE")
        for name in NAMES:
            (staging / "bin" / name).chmod(0o755)
        if package.exists():
            backup = package.with_name(package.name + ".backup-" + uuid.uuid4().hex[:12])
            package.rename(backup)
        staging.rename(package)
        installed = True
        for link, target in links.items():
            if not link.is_symlink():
                link.parent.mkdir(parents=True, exist_ok=True)
                link.symlink_to(target)
                created.append(link)
    except OSError:
        for link in reversed(created):
            link.unlink()
        if installed:
            shutil.rmtree(package)
        if backup:
            backup.rename(package)
        raise
    finally:
        if staging.exists():
            shutil.rmtree(staging)
    for link in links:
        print(f"已安装：{link}")
    if backup:
        print(f"旧版本完整保留：{backup}")
    print("未安装上游 CLI、未写凭据、未修改 agent 配置、未访问飞书。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
