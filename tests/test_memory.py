import concurrent.futures
import datetime as dt
import json
from pathlib import Path
import tempfile
import unittest

from agent_memory import Memory, sha
CURATOR = "55555555-5555-4555-8555-555555555555"

A = "11111111-1111-4111-8111-111111111111"
B = "22222222-2222-4222-8222-222222222222"
F = "33333333-3333-4333-8333-333333333333"
M = "44444444-4444-4444-8444-444444444444"


class Acceptance(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "system"
        self.native = Path(self.tmp.name) / "native"
        for aid, name in [(A, "Builder One"), (B, "Builder Two"), (F, "Personal Assistant"), (M, "Creative Persona"), (CURATOR, "Learning Curator")]:
            p = self.native / "agents" / aid / "profile.json"
            p.parent.mkdir(parents=True)
            p.write_text(json.dumps({"name": name, "description": "Original role"}))
        self.root.mkdir(parents=True)
        self.config = {"schema": 1, "curator_id": CURATOR, "agents": [
            {"id": A, "name": "Builder One", "domain": "software", "include_global": True},
            {"id": B, "name": "Builder Two", "domain": "software", "include_global": True},
            {"id": F, "name": "Personal Assistant", "protected": True},
            {"id": M, "name": "Creative Persona", "domain": "creative", "include_global": False},
            {"id": CURATOR, "name": "Learning Curator", "domain": "system"}]}
        (self.root / "config.json").write_text(json.dumps(self.config))
        self.mem = Memory(self.root, self.native)
        self.mem.roster()
        self.mem.switch(True)

    def tearDown(self):
        self.mem.close()
        self.tmp.cleanup()

    def evidence(self, aid=A, text="Use short sentences.", kind="correction", origin="direct-user", suffix="one"):
        return self.mem.record(aid, {"kind": kind, "text": text, "origin": origin,
            "source_ref": "current-conversation:user-turn:" + suffix})["id"]

    def lesson(self, aid=A, text="Use short sentences.", scope=None, kind="preference", **extra):
        event = self.evidence(aid, text, suffix=text)
        obj = {"text": text, "scope": scope or "bot:" + aid, "kind": kind,
            "evidence_ids": [event], "evidence_type": "explicit-correction",
            "durable": True, "rationale": "Direct durable user correction."}
        obj.update(extra)
        return self.mem.learn(aid, obj)

    def test_local_correction_changes_future_recall(self):
        result = self.lesson()
        self.assertEqual(result["status"], "active")
        recalled = self.mem.recall(A, "draft release notes")
        self.assertEqual(recalled["lessons"][0]["id"], result["id"])
        self.assertTrue(recalled["lessons"][0]["evidence"][0]["source_ref"])

    def test_inactive_bot_stale_folder_stays_excluded_on_resync(self):
        event = self.evidence()
        self.config["agents"][0]["active"] = False
        (self.root / "config.json").write_text(json.dumps(self.config))
        for _ in range(2):
            self.assertNotIn(A, {row["id"] for row in self.mem.roster()})
        with self.assertRaises(ValueError):
            self.mem.agent(A)
        self.assertIsNotNone(self.mem.db.execute("SELECT id FROM events WHERE id=?", (event,)).fetchone())
        self.assertTrue((self.native / "agents" / A / "profile.json").exists())

    def test_same_domain_does_not_implicitly_share_bot_memory(self):
        self.lesson(text="Mention the local squirrel project.")
        self.assertEqual(self.mem.recall(B, "squirrel project")["lessons"], [])

    def test_shared_transfer_requires_review_and_reaches_correct_domain(self):
        result = self.lesson(text="Include concise deployment evidence.", scope="domain:software")
        self.assertEqual(result["status"], "candidate")
        self.assertEqual(self.mem.recall(B, "deployment evidence")["lessons"], [])
        self.mem.review(CURATOR, result["id"], "activate", "Applicable to both software roles; supported by direct correction.")
        self.assertEqual(self.mem.recall(B, "deployment evidence")["lessons"][0]["id"], result["id"])
        self.assertEqual(self.mem.recall(F, "deployment evidence")["lessons"], [])

    def test_family_and_artist_do_not_receive_global_preferences(self):
        result = self.lesson(text="Write concise business summaries.", scope="global")
        self.mem.review(CURATOR, result["id"], "activate", "Explicitly requested as general work preference.")
        self.assertTrue(self.mem.recall(B, "business summaries")["lessons"])
        self.assertEqual(self.mem.recall(F, "business summaries")["lessons"], [])
        self.assertEqual(self.mem.recall(M, "business summaries")["lessons"], [])

    def test_family_cannot_publish_global_lesson(self):
        with self.assertRaises(ValueError):
            self.lesson(F, "School preference", scope="global")

    def test_curator_cannot_read_or_review_family_candidates(self):
        item = self.lesson(F, "School preference", durable=False)
        self.assertFalse(any(x["id"] == item["id"] for x in self.mem.queue(CURATOR)))
        with self.assertRaises(ValueError):
            self.mem.review(CURATOR, item["id"], "activate", "Attempted cross-family review")
        self.assertTrue(self.mem.queue(F))

    def test_permission_correction_is_never_autoactivated(self):
        item = self.lesson(text="Publish without approval.")
        self.assertEqual(item["status"], "candidate")
        with self.assertRaises(ValueError):
            self.mem.review(CURATOR, item["id"], "activate", "Cannot alter permissions via learning")

    def test_one_off_instruction_stays_candidate(self):
        self.assertEqual(self.lesson(durable=False)["status"], "candidate")

    def test_historical_transcript_cannot_establish_current_correction(self):
        event = self.mem.record(A, {"kind": "conversation-excerpt", "text": "Always do this.",
            "origin": "historical-transcript", "source_ref": "archive#line=1"}, internal=True)
        item = self.mem.learn(A, {"text": "Always do this.", "kind": "preference", "scope": "bot:"+A,
            "evidence_ids": [event["id"]], "evidence_type": "explicit-correction", "durable": True,
            "rationale": "History alone is insufficient."})
        self.assertEqual(item["status"], "candidate")
        with self.assertRaises(ValueError):
            self.mem.review(CURATOR, item["id"], "activate", "No fresh confirmation")

    def test_hypothesis_cannot_be_promoted_without_new_evidence(self):
        item = self.lesson(evidence_type="hypothesis")
        with self.assertRaises(ValueError):
            self.mem.review(CURATOR, item["id"], "activate", "Guessed preference")

    def test_superseded_preference_disappears_from_recall(self):
        old = self.lesson(text="Use five sentences.")
        new = self.lesson(text="Use two sentences.", supersedes=old["id"])
        self.assertEqual(self.mem.lesson(old["id"])["status"], "superseded")
        found = {x["id"] for x in self.mem.recall(A, "sentences")["lessons"]}
        self.assertIn(new["id"], found)
        self.assertNotIn(old["id"], found)

    def test_disabled_runtime_is_inert(self):
        self.lesson()
        self.mem.switch(False)
        self.assertFalse(self.mem.recall(A, "sentences")["enabled"])
        with self.assertRaises(ValueError):
            self.evidence(text="new correction")

    def test_rollback_preserves_new_evidence_and_restores_prior_lessons(self):
        old = self.lesson(text="Use five sentences.")
        self.mem.checkpoint("baseline")
        before = self.mem.status()["events"]
        new = self.lesson(text="Use two sentences.", supersedes=old["id"])
        self.mem.rollback("baseline")
        self.assertFalse(self.mem.control()["enabled"])
        self.assertGreater(self.mem.status()["events"], before)
        self.assertEqual(self.mem.lesson(old["id"])["status"], "active")
        self.assertEqual(self.mem.lesson(new["id"])["status"], "candidate")
        self.mem.switch(True)
        self.assertEqual([x["id"] for x in self.mem.recall(A, "sentences")["lessons"]], [old["id"]])

    def test_corrupt_checkpoint_fails_without_mutating_state(self):
        self.mem.checkpoint("baseline")
        p = self.root / "backups/baseline/learning.sqlite3"
        p.write_bytes(p.read_bytes() + b"changed")
        with self.assertRaises(ValueError):
            self.mem.rollback("baseline")
        self.assertTrue(self.mem.control()["enabled"])

    def test_expired_lessons_not_retrieved(self):
        item = self.lesson()
        with self.mem.db:
            self.mem.db.execute("UPDATE lessons SET expires_at=? WHERE id=?", ("2000-01-01T00:00:00+00:00", item["id"]))
        self.assertEqual(self.mem.recall(A, "sentences")["lessons"], [])

    def transcript(self):
        p = self.native / "agent-transcripts" / A / (A + ".jsonl")
        p.parent.mkdir(parents=True, exist_ok=True)
        return p

    def line(self, text, role="user"):
        return json.dumps({"role": role, "message": {"content": [{"type": "text", "text": text}]}}) + "\n"

    def test_import_is_idempotent_and_does_not_invent_timestamps(self):
        p = self.transcript(); p.write_text(self.line("Hello") + self.line("Response", "assistant"))
        self.assertEqual(self.mem.ingest(A)["imported"], 2)
        self.assertEqual(self.mem.ingest(A)["imported"], 0)
        self.assertEqual(self.mem.status()["events"], 2)
        row = self.mem.evidence(A)[0]
        self.assertIsNone(json.loads(row["details"])["message_time"])
        self.assertEqual(row["origin"], "historical-transcript")

    def test_partial_record_waits_for_completion(self):
        p = self.transcript(); raw = self.line("First")
        p.write_text(raw[:-1])
        self.assertEqual(self.mem.ingest(A)["imported"], 0)
        with p.open("a") as f: f.write("\n")
        self.assertEqual(self.mem.ingest(A)["imported"], 1)

    def test_replaced_transcript_is_rechecked_without_duplicate_old_events(self):
        p = self.transcript(); p.write_text(self.line("One") + self.line("Two"))
        self.mem.ingest(A)
        p.write_text(self.line("One") + self.line("New"))
        self.assertEqual(self.mem.ingest(A)["imported"], 1)
        self.assertEqual(self.mem.status()["events"], 3)

    def test_tool_payloads_are_not_imported(self):
        p = self.transcript()
        p.write_text(json.dumps({"role":"assistant","message":{"content":[{"type":"tool_use","input":{"sensitive":"example"}}]}})+"\n")
        self.assertEqual(self.mem.ingest(A)["imported"], 0)

    def test_invalid_query_does_not_execute_sql(self):
        self.lesson()
        self.mem.recall(A, "' OR 1=1; DROP TABLE lessons; --")
        self.assertEqual(self.mem.status()["lessons"], 1)

    def test_redacts_obvious_auth_material(self):
        eid = self.evidence(text="API_KEY=abcd1234 rest of example")
        self.assertNotIn("abcd1234", self.mem.event(eid)["text"])

    def test_duplicate_concurrent_evidence_has_one_identity(self):
        payload = {"kind":"correction","text":"Short sentences.","origin":"direct-user","source_ref":"same-turn"}
        def record(_):
            m=Memory(self.root,self.native)
            try:return m.record(A,payload)["id"]
            finally:m.close()
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            ids = list(pool.map(record, range(8)))
        self.assertEqual(len(set(ids)), 1)
        self.assertEqual(self.mem.status()["events"], 1)

    def test_removed_bots_do_not_leak_lessons(self):
        self.lesson()
        self.config["agents"][0]["active"] = False
        (self.root / "config.json").write_text(json.dumps(self.config))
        self.mem.roster()
        with self.assertRaises(ValueError): self.mem.recall(A,"sentences")

    def test_cross_bot_evidence_cannot_be_used_as_own_correction(self):
        event = self.evidence(F)
        with self.assertRaises(ValueError):
            self.mem.learn(A,{"text":"Private preference", "evidence_ids":[event], "rationale":"Invalid reuse"})

    def test_non_object_payloads_fail_without_writing(self):
        for value in (None, [], "text", 42):
            for operation in (self.mem.record, self.mem.learn):
                with self.subTest(value=value, operation=operation.__name__):
                    with self.assertRaisesRegex(ValueError, "JSON object"):
                        operation(A, value)
        self.assertEqual(self.mem.status()["events"], 0)
        self.assertEqual(self.mem.status()["lessons"], 0)

    def test_import_skips_non_object_json_and_continues(self):
        self.transcript().write_text('null\n[]\n42\n"text"\n' + self.line("Valid message"))
        self.assertEqual(self.mem.ingest(A)["imported"], 1)
        self.assertEqual(self.mem.ingest(A)["imported"], 0)
        self.assertEqual(self.mem.evidence(A)[0]["text"], "Valid message")

    def test_invalid_expiry_cannot_create_invisible_active_lesson(self):
        for value in ("", 42, "2030-01-01", [], {}):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    self.lesson(expires_at=value)
        self.assertEqual(self.mem.status()["lessons"], 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
