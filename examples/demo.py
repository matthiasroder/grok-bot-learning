#!/usr/bin/env python3
"""Exercise real learning and rollback with synthetic data in a temporary folder."""
import json
from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from agent_memory import Memory


def main():
    config = json.loads((Path(__file__).parent / "fleet.example.json").read_text())
    curator, writer, colleague = [a["id"] for a in config["agents"][:3]]
    with tempfile.TemporaryDirectory(prefix="grok-learning-demo-") as directory:
        root = Path(directory)
        (root / "config.json").write_text(json.dumps(config))
        memory = Memory(root)
        try:
            memory.roster()
            memory.checkpoint("before-demo")
            memory.switch(True)
            evidence = memory.record(writer, {"kind": "correction", "origin": "direct-user",
                "text": "For every software brief, lead with the next action.",
                "source_ref": "synthetic-demo:user-turn-1"})
            lesson = memory.learn(writer, {"text": "Lead software briefs with the next action.",
                "kind": "preference", "scope": "domain:software", "evidence_ids": [evidence["id"]],
                "evidence_type": "explicit-correction", "durable": True,
                "rationale": "Synthetic user explicitly requested this for all software briefs."})
            assert lesson["status"] == "candidate"
            assert not memory.recall(colleague, "software brief next action")["lessons"]
            memory.review(curator, lesson["id"], "activate", "Explicit domain-wide correction in synthetic evidence.")
            recalled = memory.recall(colleague, "software brief next action")
            assert recalled["lessons"][0]["id"] == lesson["id"]
            memory.rollback("before-demo")
            assert memory.status()["events"] == 1
            assert memory.lesson(lesson["id"])["status"] == "candidate"
            assert memory.recall(colleague, "software brief")["enabled"] is False
            print(json.dumps({"demo": "PASS", "synthetic_data_only": True,
                "verified": ["evidence captured", "shared lesson awaits review", "curator activates",
                             "other configured bot recalls with evidence", "rollback retains evidence and disables recall"]}, indent=2))
        finally:
            memory.close()


if __name__ == "__main__":
    main()
