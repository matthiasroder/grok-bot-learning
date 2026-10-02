#!/usr/bin/env python3
"""Install a disabled, self-contained release into a NEW directory."""
import argparse
import json
from pathlib import Path
import shlex
import shutil
from string import Template
import sys

from agent_memory import Memory, RELEASE, load_config


def install(root, config_path):
    root = Path(root).expanduser().resolve()
    config_path = Path(config_path).resolve()
    config = load_config(config_path)
    source = Path(__file__).resolve().parent
    if root.exists():
        raise ValueError("Destination exists; choose a new directory. Existing state is never overwritten.")
    root.mkdir(parents=True, mode=0o700)
    release = root / "releases" / RELEASE
    release.mkdir(parents=True)
    for name in ("agent_memory.py", "native.py"):
        shutil.copy2(source / name, release / name)
    shutil.copytree(source / "templates", release / "templates")
    shutil.copy2(config_path, root / "config.json")
    (root / "config.json").chmod(0o600)
    (root / "current").symlink_to(Path("releases") / RELEASE)
    (root / "bin").mkdir()
    command = root / "bin" / "agent-memory"
    command.write_text("#!/bin/sh\nexec " + shlex.quote(sys.executable) + " " +
                       shlex.quote(str(root / "current" / "agent_memory.py")) +
                       " --root " + shlex.quote(str(root)) + ' "$@"\n')
    command.chmod(0o700)
    values = {"ROOT": str(root), "CLI": shlex.quote(str(command)), "CURATOR_ID": config["curator_id"]}
    (release / "SKILL.md").write_text(Template((source / "templates" / "SKILL.md").read_text()).substitute(values))
    memory = Memory(root)
    try:
        memory.roster()
        memory.switch(False)
        memory.checkpoint("pre-activation")
        return {"root": str(root), "enabled": False, "agents": memory.status()["agents"],
                "next": "Prepare native manifests, register current/SKILL.md in the skill catalog as "
                        "shared-learning, apply with supported Grok tools, verify, then enable."}
    finally:
        memory.close()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--root", required=True)
    p.add_argument("--config", required=True)
    a = p.parse_args()
    try:
        print(json.dumps(install(a.root, a.config), indent=2))
    except (ValueError, OSError) as e:
        p.exit(2, str(e) + "\n")


if __name__ == "__main__":
    main()
