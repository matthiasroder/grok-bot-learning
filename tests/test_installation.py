import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from agent_memory import Memory, load_config, owner_name, sha
from install import install
from native import BEGIN, BLOCK_VERSION, discover, integrate_description, prepare, upgrade, verify


def v1_block(agent_id):
    return (
        f"{BEGIN}\n"
        "Shared learning: on substantive work, run /opt/learning/bin/agent-memory session --agent "
        f"{agent_id} --query \"short task description\". If disabled or unavailable, continue the original task "
        "normally. If enabled, follow /opt/learning/current/SKILL.md.\n"
        "[shared-learning:end]"
    )


class PortableInstallation(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        self.config = json.loads((Path(__file__).resolve().parents[1] / "examples/fleet.example.json").read_text())
        self.native = self.base / "native"
        self.config["native_root"] = str(self.native)
        self.config_path = self.base / "fleet.json"
        self.config_path.write_text(json.dumps(self.config))
        self.root = self.base / "runtime with spaces"
        for agent in self.config["agents"]:
            p = self.native / "agents" / agent["id"] / "profile.json"
            p.parent.mkdir(parents=True)
            p.write_text(json.dumps({"name": agent["name"], "description": "Original role", "title": "Keep me"}))

    def tearDown(self):
        self.tmp.cleanup()

    def test_install_cli_and_native_roundtrip_without_touching_source(self):
        result = install(self.root, self.config_path)
        self.assertFalse(result["enabled"])
        command = [str(self.root / "bin/agent-memory")]
        status = json.loads(subprocess.check_output(command + ["status"], text=True))
        self.assertEqual(status["agents"], 5)
        originals = {p: p.read_bytes() for p in self.native.glob("agents/*/profile.json")}
        prepare(self.root)
        self.assertTrue(all(p.read_bytes() == data for p, data in originals.items()))
        self.assertFalse(verify(self.root)["all_activated"])
        m = json.loads((self.root / "manifests/native-activation.json").read_text())
        self.assertEqual(m["block_version"], BLOCK_VERSION)
        self.assertIn("After EVERY run", m["new_routine"]["prompt"])
        self.assertIn("0 candidates", m["new_routine"]["prompt"])
        self.assertIn("to the owner", m["new_routine"]["prompt"])
        sample = m["profile_updates"][0]["target_description"]
        self.assertIn("skill `shared-learning`", sample)
        self.assertIn("ALWAYS, in the same turn", sample)
        self.assertIn("A native memory save alone does not count as recording", sample)
        self.assertIn("approved by the user", sample)
        self.assertNotIn("current/SKILL.md", sample)
        self.assertNotIn("Matthias", sample)
        skill = (self.root / "current" / "SKILL.md").read_text()
        self.assertIn("## Trigger", skill)
        self.assertIn("a native memory save alone does not count as recording", skill)
        self.assertIn("Use this when the user corrects you or says learn, remember, from now on,", skill)
        self.assertIn("skill-catalog entry", skill)
        # Emulate a supported native setter only in this synthetic fixture.
        for row in m["profile_updates"]:
            p = self.native / "agents" / row["agent_id"] / "profile.json"
            obj = json.loads(p.read_text()); obj["description"] = row["target_description"]
            p.write_text(json.dumps(obj))
        self.assertTrue(verify(self.root)["all_activated"])
        reverse = json.loads((self.root / "manifests/native-restoration.json").read_text())
        for row in reverse["profile_updates"]:
            p = self.native / "agents" / row["agent_id"] / "profile.json"
            obj = json.loads(p.read_text()); obj["description"] = row["restore_description"]
            p.write_text(json.dumps(obj))
        self.assertTrue(all(p.read_bytes() == data for p, data in originals.items()))

    def test_existing_install_is_never_overwritten(self):
        install(self.root, self.config_path)
        with self.assertRaises(ValueError):
            install(self.root, self.config_path)

    def test_manifest_cannot_overwrite_saved_originals(self):
        install(self.root, self.config_path); prepare(self.root)
        path = self.root / "manifests/native-activation.json"; before = path.read_bytes()
        with self.assertRaises(ValueError):
            prepare(self.root)
        self.assertEqual(path.read_bytes(), before)

    def test_empty_description_target_has_no_leading_padding(self):
        aid = self.config["agents"][0]["id"]
        path = self.native / "agents" / aid / "profile.json"
        obj = json.loads(path.read_text()); obj["description"] = ""; path.write_text(json.dumps(obj))
        install(self.root, self.config_path); prepare(self.root)
        m = json.loads((self.root / "manifests/native-activation.json").read_text())
        row = next(r for r in m["profile_updates"] if r["agent_id"] == aid)
        self.assertTrue(row["target_description"].startswith("[shared-learning:begin]"))
        self.assertEqual(sha(Path(row["backup"]).read_bytes()), row["original_profile_sha256"])

    def test_unrelated_native_field_change_fails_verification(self):
        install(self.root, self.config_path); prepare(self.root)
        m = json.loads((self.root / "manifests/native-activation.json").read_text())
        row = m["profile_updates"][0]; p = self.native / "agents" / row["agent_id"] / "profile.json"
        obj = json.loads(p.read_text()); obj.update(description=row["target_description"], title="Changed")
        p.write_text(json.dumps(obj))
        check = verify(self.root)
        self.assertFalse(check["all_activated"])
        self.assertEqual(check["profiles"][0]["other_fields_changed"], ["title"])

    def test_config_rejects_unsafe_or_ambiguous_scope_settings(self):
        for mutate in [lambda c: c["agents"].append(c["agents"][0]),
                       lambda c: c.update(curator_id="missing"),
                       lambda c: c["agents"][3].update(include_global=True),
                       lambda c: c["agents"][1].update(active="false"),
                       lambda c: c["agents"][1].update(id="../../escape"),
                       lambda c: c.update(owner_name=""),
                       lambda c: c.update(owner_name="Ada\nLovelace"),
                       lambda c: c.update(owner_name="x[shared-learning:begin]")]:
            with self.subTest(mutate=mutate):
                config = copy.deepcopy(self.config); mutate(config)
                self.config_path.write_text(json.dumps(config))
                with self.assertRaises((ValueError, TypeError)):
                    load_config(self.config_path)
        self.assertFalse(self.root.exists())

    def test_names_do_not_control_scope_and_unconfigured_exports_are_ignored(self):
        for agent in self.config["agents"]:
            agent["name"] = "Renamed bot"
        self.config_path.write_text(json.dumps(self.config))
        extra = self.native / "agents" / "99999999-9999-4999-8999-999999999999" / "profile.json"
        extra.parent.mkdir(parents=True); extra.write_text('{"name":"Stale export"}')
        install(self.root, self.config_path)
        m = Memory(self.root)
        try:
            self.assertEqual(m.status()["agents"], 5)
            self.assertEqual(m.agent(self.config["agents"][1]["id"])["domain"], "software")
        finally:
            m.close()
        self.assertEqual(len(discover(self.native)["exported_profiles"]), 6)

    def test_owner_name_is_configurable(self):
        self.assertEqual(owner_name({}), "the user")
        self.config["owner_name"] = "Alex"
        self.config_path.write_text(json.dumps(self.config))
        install(self.root, self.config_path)
        prepare(self.root)
        text = json.loads((self.root / "manifests/native-activation.json").read_text())["profile_updates"][0]["target_description"]
        self.assertIn("approved by Alex", text)
        self.assertIn("when Alex corrects you", text)
        self.assertNotIn("Matthias", text)
        self.assertNotIn("/home/box", text)

    def test_prepare_replaces_v1_block_and_keeps_surrounding_text(self):
        aid = self.config["agents"][0]["id"]
        path = self.native / "agents" / aid / "profile.json"
        prefix, suffix = "Original role\n\n", "\n\nSignature stays."
        obj = json.loads(path.read_text())
        obj["description"] = prefix + v1_block(aid) + suffix
        raw = json.dumps(obj)
        path.write_text(raw)
        install(self.root, self.config_path)
        prepare(self.root)
        self.assertEqual(path.read_text(), raw)
        row = next(r for r in json.loads((self.root / "manifests/native-activation.json").read_text())["profile_updates"]
                   if r["agent_id"] == aid)
        self.assertEqual(row["original_description"], prefix + v1_block(aid) + suffix)
        self.assertTrue(row["target_description"].startswith(prefix))
        self.assertTrue(row["target_description"].endswith(suffix))
        self.assertEqual(row["target_description"].count(BEGIN), 1)
        self.assertNotIn("on substantive work, run", row["target_description"])
        self.assertIn("ALWAYS, in the same turn", row["target_description"])
        prepared = json.loads((self.root / "manifests/native-activation.json").read_text())
        for item in prepared["profile_updates"]:
            profile = self.native / "agents" / item["agent_id"] / "profile.json"
            current = json.loads(profile.read_text())
            current["description"] = item["target_description"]
            profile.write_text(json.dumps(current))
        check = verify(self.root)
        self.assertTrue(check["all_activated"])
        checked = next(item for item in check["profiles"] if item["agent_id"] == aid)
        self.assertTrue(checked["block_exact"])
        self.assertTrue(checked["outside_block_identical"])
        self.assertTrue(checked["other_fields_identical"])
        self.assertEqual(checked["other_fields_changed"], [])

    def test_upgrade_replaces_prepared_v1_targets_without_rewriting_baselines(self):
        install(self.root, self.config_path)
        prepare(self.root)
        manifest_path = self.root / "manifests/native-activation.json"
        manifest = json.loads(manifest_path.read_text())
        backups = {row["backup"]: Path(row["backup"]).read_bytes() for row in manifest["profile_updates"]}
        originals = {row["agent_id"]: row["original_description"] for row in manifest["profile_updates"]}
        for row in manifest["profile_updates"]:
            row["target_description"] = integrate_description(row["original_description"], v1_block(row["agent_id"]))
        manifest_path.write_text(json.dumps(manifest))
        for row in manifest["profile_updates"]:
            profile = self.native / "agents" / row["agent_id"] / "profile.json"
            obj = json.loads(profile.read_text())
            obj["description"] = row["target_description"]
            profile.write_text(json.dumps(obj))
        native_at_v1 = {p: p.read_bytes() for p in self.native.glob("agents/*/profile.json")}
        stale = verify(self.root)
        self.assertFalse(stale["all_activated"])
        self.assertTrue(all(not item["block_exact"] for item in stale["profiles"]))
        result = upgrade(self.root)
        self.assertEqual(result["block_version"], "v2")
        self.assertFalse(result["native_files_modified"])
        self.assertEqual(native_at_v1, {p: p.read_bytes() for p in self.native.glob("agents/*/profile.json")})
        upgraded = json.loads(manifest_path.read_text())
        self.assertIn("0 candidates", upgraded["new_routine"]["prompt"])
        for row in upgraded["profile_updates"]:
            self.assertEqual(row["original_description"], originals[row["agent_id"]])
            self.assertIn("ALWAYS, in the same turn", row["target_description"])
            self.assertNotIn("on substantive work, run", row["target_description"])
            self.assertEqual(Path(row["backup"]).read_bytes(), backups[row["backup"]])
        restoration = json.loads((self.root / "manifests/native-restoration.json").read_text())
        self.assertEqual(restoration["profile_updates"][0]["expected_current_description"],
                         upgraded["profile_updates"][0]["target_description"])
        self.assertEqual(restoration["profile_updates"][0]["restore_description"],
                         upgraded["profile_updates"][0]["original_description"])
        for row in upgraded["profile_updates"]:
            profile = self.native / "agents" / row["agent_id"] / "profile.json"
            obj = json.loads(profile.read_text())
            obj["description"] = row["target_description"]
            profile.write_text(json.dumps(obj))
        self.assertTrue(verify(self.root)["all_activated"])
        skill = (self.root / "current" / "SKILL.md").read_text()
        self.assertIn("## Trigger", skill)
        upgrade(self.root)
        again = json.loads(manifest_path.read_text())
        self.assertEqual([r["target_description"] for r in again["profile_updates"]],
                         [r["target_description"] for r in upgraded["profile_updates"]])

    def test_broken_shared_learning_markers_are_rejected(self):
        aid = self.config["agents"][0]["id"]
        path = self.native / "agents" / aid / "profile.json"
        obj = json.loads(path.read_text())
        obj["description"] = "Role [shared-learning:begin] only"
        path.write_text(json.dumps(obj))
        install(self.root, self.config_path)
        with self.assertRaises(ValueError):
            prepare(self.root)
        self.assertFalse((self.root / "manifests" / "native-activation.json").exists())

    def test_global_sharing_is_opt_in(self):
        for agent in self.config["agents"]:
            agent.pop("include_global", None)
        self.config_path.write_text(json.dumps(self.config))
        install(self.root, self.config_path)
        m = Memory(self.root)
        try:
            self.assertNotIn("global", m.allowed_scopes(self.config["agents"][1]["id"]))
        finally:
            m.close()


if __name__ == "__main__":
    unittest.main()
