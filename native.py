#!/usr/bin/env python3
"""Read native exports and prepare/verify manifests. NEVER write native files."""
import argparse
import json
from pathlib import Path
import shlex
from string import Template

from agent_memory import BEGIN, END, RELEASE, atomic_json, load_config, now, owner_name, sha


BLOCK_VERSION = "v2"


def discover(native):
    rows = []
    for path in sorted((Path(native) / "agents").glob("*/profile.json")):
        obj = json.loads(path.read_text())
        rows.append({"id": path.parent.name, "name": obj.get("name", ""), "source": str(path)})
    return {"exported_profiles": rows,
            "warning": "Exports can be stale or retain deleted bots. Profiles that are not in config are adopted unless excluded or listed in manifests/inactive-native-agents.json."}


def runtime_cli(root):
    return shlex.quote(str(Path(root) / "bin" / "agent-memory"))


def render_profile_block(cli, agent_id, owner):
    raw = (Path(__file__).parent / "templates" / "profile-block.txt").read_text()
    return Template(raw).substitute(CLI=cli, AGENT_ID=agent_id, OWNER=owner).strip("\n")


def review_prompt(root, config):
    return Template((Path(__file__).parent / "templates" / "review-routine.txt").read_text()).substitute(
        ROOT=str(root), CLI=runtime_cli(root), CURATOR_ID=config["curator_id"])


def split_block(description):
    """Return (before, block, after). block is None when no shared-learning markers are present."""
    if not isinstance(description, str):
        raise ValueError("Profile description must be a string")
    begins, ends = description.count(BEGIN), description.count(END)
    if begins == 0 and ends == 0:
        return description, None, ""
    if begins != 1 or ends != 1:
        raise ValueError("shared-learning markers must appear exactly once")
    start, stop = description.index(BEGIN), description.index(END)
    if stop < start:
        raise ValueError("shared-learning markers are out of order")
    stop += len(END)
    return description[:start], description[start:stop], description[stop:]


def integrate_description(description, block):
    """Append a new block, or replace the single existing block between the markers."""
    before, existing, after = split_block(description)
    if existing is None:
        return block if not description else description + "\n\n" + block
    return before + block + after


def outside_matches(original, updated):
    """True when updated carries the learning block and every other character matches original."""
    before, block, after = split_block(updated)
    if block is None:
        return False
    obefore, oblock, oafter = split_block(original)
    if oblock is None:
        if after:
            return False
        return before == (original + "\n\n" if original else "")
    return (before, after) == (obefore, oafter)


def prepare(root):
    root = Path(root).resolve()
    config = load_config(root / "config.json")
    native = Path(config.get("native_root", "/home/box/agent-data"))
    destination = root / "manifests" / "native-activation.json"
    if destination.exists():
        raise ValueError("An activation manifest already exists; preserve its originals, do not regenerate it.")
    owner = owner_name(config)
    cli = runtime_cli(root)
    rows, backups = [], []
    for agent in config["agents"]:
        if not agent.get("active", True):
            continue
        aid = agent["id"]
        path = native / "agents" / aid / "profile.json"
        data = path.read_bytes()
        obj = json.loads(data)
        description = obj.get("description", "")
        block = render_profile_block(cli, aid, owner)
        target = integrate_description(description, block)
        backup = root / "backups" / "native-baseline" / aid / "profile.json"
        rows.append({"agent_id": aid, "name": agent["name"], "original_description": description,
                     "target_description": target, "original_profile_sha256": sha(data), "backup": str(backup)})
        backups.append((backup, data))
    spec = config.get("routine", {})
    routine = {"owner_id": config["curator_id"], "name": spec.get("name", "shared-learning-review"),
               "schedule": spec.get("schedule", "15 8,18 * * *"), "timezone": spec.get("timezone", "UTC"),
               "enabled": True, "prompt": review_prompt(root, config)}
    # Validate every input before writing any snapshot. Existing backups are never replaced.
    for backup, _ in backups:
        if backup.exists():
            raise ValueError("Baseline backup already exists: " + str(backup))
    for backup, data in backups:
        backup.parent.mkdir(parents=True, exist_ok=True)
        with backup.open("xb") as f:
            f.write(data)
        backup.chmod(0o600)
    manifest = {"release": RELEASE, "block_version": BLOCK_VERSION, "created_at": now(),
                "profile_updates": rows, "new_routine": routine,
                "status": "prepared-only", "method": "Supported native Grok management tools or UI only"}
    atomic_json(destination, manifest)
    atomic_json(root / "manifests" / "native-restoration.json", {
        "profile_updates": [{"agent_id": r["agent_id"], "name": r["name"],
            "expected_current_description": r["target_description"], "restore_description": r["original_description"],
            "empty_restore_note": ("A description that must be exactly empty can only be restored by the owning "
                                   "bot's own profile setter. The sibling-agent update tool rejects empty or "
                                   "whitespace-only descriptions.")}
            for r in rows],
        "routine": "Pause only the added routine; preserve any pre-existing routine with that name.",
        "drift_rule": "Stop on unrelated edits. Do not blindly overwrite later user changes.",
        "first_step": "Disable shared learning. Evidence-preserving database rollback is a separate operation."})
    return {"prepared_profiles": len(rows), "block_version": BLOCK_VERSION, "manifest": str(destination),
            "native_files_modified": False}


def render_installed_skill(root, config):
    values = {"ROOT": str(root), "CLI": runtime_cli(root), "CURATOR_ID": config["curator_id"]}
    text = Template((Path(__file__).parent / "templates" / "SKILL.md").read_text()).substitute(values)
    path = Path(root) / "current" / "SKILL.md"
    if path.exists() or path.is_symlink():
        path.write_text(text)
    return text


def upgrade(root):
    """Replace learning blocks inside an existing manifest. Preserve baseline backups and originals."""
    root = Path(root).resolve()
    config = load_config(root / "config.json")
    destination = root / "manifests" / "native-activation.json"
    if not destination.is_file():
        raise ValueError("No activation manifest to upgrade; run prepare first.")
    manifest = json.loads(destination.read_text())
    owner = owner_name(config)
    cli = runtime_cli(root)
    for row in manifest["profile_updates"]:
        backup = Path(row["backup"])
        if sha(backup.read_bytes()) != row["original_profile_sha256"]:
            raise ValueError("Baseline checksum mismatch: " + row["agent_id"])
        preserved = row["original_description"]
        row["target_description"] = integrate_description(
            row["target_description"], render_profile_block(cli, row["agent_id"], owner))
        if row["original_description"] != preserved:
            raise ValueError("Upgrade must not alter original descriptions")
    manifest["release"] = RELEASE
    manifest["block_version"] = BLOCK_VERSION
    manifest["upgraded_at"] = now()
    if "new_routine" in manifest:
        manifest["new_routine"]["prompt"] = review_prompt(root, config)
    atomic_json(destination, manifest)
    restoration_path = root / "manifests" / "native-restoration.json"
    if restoration_path.is_file():
        restoration = json.loads(restoration_path.read_text())
        by_id = {r["agent_id"]: r["target_description"] for r in manifest["profile_updates"]}
        for row in restoration.get("profile_updates", []):
            row["expected_current_description"] = by_id[row["agent_id"]]
        atomic_json(restoration_path, restoration)
    render_installed_skill(root, config)
    return {"upgraded_profiles": len(manifest["profile_updates"]), "block_version": BLOCK_VERSION,
            "native_files_modified": False}


def verify(root):
    root = Path(root).resolve()
    config = load_config(root / "config.json")
    native = Path(config.get("native_root", "/home/box/agent-data"))
    manifest = json.loads((root / "manifests" / "native-activation.json").read_text())
    owner = owner_name(config)
    cli = runtime_cli(root)
    rows = []
    for row in manifest["profile_updates"]:
        path = native / "agents" / row["agent_id"] / "profile.json"
        expected = render_profile_block(cli, row["agent_id"], owner)
        state, changed = "missing", []
        single = block_exact = outside = other_ok = False
        if path.exists():
            current = json.loads(path.read_text())
            before_data = Path(row["backup"]).read_bytes()
            if sha(before_data) != row["original_profile_sha256"]:
                raise ValueError("Baseline checksum mismatch: " + row["agent_id"])
            before = json.loads(before_data)
            changed = [k for k in set(before) | set(current) if k != "description" and before.get(k) != current.get(k)]
            other_ok = not changed
            desc = current.get("description", "")
            original = before.get("description", "")
            if not isinstance(desc, str) or not isinstance(original, str):
                state = "drift"
            else:
                try:
                    _before, block, _after = split_block(desc)
                    single = block is not None
                    block_exact = block == expected
                    outside = outside_matches(original, desc)
                except ValueError:
                    single = block_exact = outside = False
                if desc == row["target_description"]:
                    state = "activated"
                elif desc == row["original_description"]:
                    state = "original"
                else:
                    state = "drift"
                if changed or (state == "activated" and not (single and block_exact and outside)):
                    state = "drift"
        rows.append({"agent_id": row["agent_id"], "name": row["name"], "state": state,
                     "other_fields_changed": changed, "single_block": single, "block_exact": block_exact,
                     "outside_block_identical": outside, "other_fields_identical": other_ok})
    counts = {s: sum(x["state"] == s for x in rows) for s in ("activated", "original", "drift", "missing")}
    result = {"block_version": BLOCK_VERSION, "counts": counts, "profiles": rows,
              "all_activated": bool(rows) and counts["activated"] == len(rows),
              "limitation": "File readback does not prove a bot still exists in the app or that a routine was saved. Verify both natively."}
    atomic_json(root / "manifests" / "native-verification.json", result)
    return result


def main():
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="command", required=True)
    d = sub.add_parser("discover"); d.add_argument("--native-root", default="/home/box/agent-data")
    for name in ("prepare", "verify", "upgrade"):
        s = sub.add_parser(name); s.add_argument("--root", required=True)
    a = p.parse_args()
    try:
        result = discover(a.native_root) if a.command == "discover" else globals()[a.command](a.root)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 1 if a.command == "verify" and not result["all_activated"] else 0
    except (ValueError, OSError, KeyError) as e:
        p.exit(2, str(e) + "\n")


if __name__ == "__main__":
    raise SystemExit(main())
