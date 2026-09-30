import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from agent_memory import Memory, load_config, sha
from install import install
from native import discover, prepare, verify


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
        self.assertIn("After EVERY run", m["new_routine"]["prompt"])
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
                       lambda c: c["agents"][1].update(id="../../escape")]:
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
