#!/usr/bin/env python3
"""Build a standalone skill ZIP containing only versioned skill files and LICENSE."""
import hashlib
from pathlib import Path
import subprocess
import zipfile

ROOT = Path(__file__).resolve().parents[1]
VERSION = "0.2.0"


def main():
    paths = subprocess.check_output(["git", "ls-files", "--cached", "skills/feishu-publish"], cwd=ROOT, text=True).splitlines()
    if not paths:
        raise SystemExit("Stage the skill before packaging.")
    destination = ROOT / "dist" / ("feishu-publish-v" + VERSION + ".zip")
    destination.parent.mkdir(exist_ok=True)
    with zipfile.ZipFile(destination, "w", zipfile.ZIP_DEFLATED) as archive:
        for name in sorted(paths):
            path = Path(name)
            archive.write(ROOT / path, path.relative_to("skills"))
        archive.write(ROOT / "LICENSE", "feishu-publish/LICENSE")
    checksum = hashlib.sha256(destination.read_bytes()).hexdigest()
    destination.with_suffix(".zip.sha256").write_text(checksum + "  " + destination.name + "\n")
    print(destination)
    print(checksum)


if __name__ == "__main__":
    main()
