#!/usr/bin/env python3
"""Grok fleet learning: local evidence, scoped lessons, auditable retrieval, rollback.

Python standard library only. Never writes Grok's native configuration or databases.
"""
from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import sys
import tempfile
import uuid

SCHEMA = 1
RELEASE = "0.1.0"
BEGIN = "[shared-learning:begin]"
END = "[shared-learning:end]"
SENSITIVE = re.compile(r"(?i)(?:\b(?:password|passphrase|api[_ -]?key|access[_ -]?token|authorization)\s*[:=]\s*\S+|\bBearer\s+\S+|\b(?:sk-|ghp_|github_pat_)[A-Za-z0-9_-]{16,})")
BOUNDARY = re.compile(r"(?i)\b(?:approval|permission|authorization|authorisation|publish|publishing|posten|send|sending|payment|pay|delete|deploy|credentials?|password|secrets?|bypass|execute|sudo)\b")


def now():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def dump(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def sha(value):
    return hashlib.sha256(value if isinstance(value, bytes) else value.encode()).hexdigest()


def clean(text, limit=16000):
    if not isinstance(text, str) or not text.strip():
        raise ValueError("Expected nonempty text")
    if len(text) > limit:
        raise ValueError(f"Text exceeds {limit} characters; record a focused excerpt")
    return SENSITIVE.sub("[redacted]", text.strip())


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(prefix=".pending-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(json.dumps(value, ensure_ascii=False, indent=2) + "\n")
            f.flush()
            os.fsync(f.fileno())
        os.chmod(temp, 0o600)
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def load_config(path):
    """Load an explicit roster; fail before touching state on invalid configuration."""
    obj = json.loads(Path(path).read_text())
    if not isinstance(obj, dict) or obj.get("schema") != 1:
        raise ValueError("config.json must have schema=1")
    agents = obj.get("agents")
    if not isinstance(agents, list) or not agents:
        raise ValueError("Configure at least one agent")
    ids = set()
    for agent in agents:
        if not isinstance(agent, dict):
            raise ValueError("Every agent must be an object")
        aid = agent.get("id")
        if not isinstance(aid, str) or str(uuid.UUID(aid)) != aid:
            raise ValueError("Agent IDs must be canonical UUID strings")
        if aid in ids:
            raise ValueError("Duplicate agent ID")
        ids.add(aid)
        if not isinstance(agent.get("name"), str) or not agent["name"].strip():
            raise ValueError("Every agent needs a name")
        for field in ("active", "protected", "include_global"):
            if field in agent and not isinstance(agent[field], bool):
                raise ValueError(field + " must be a boolean")
        domain = agent.get("domain")
        if domain is not None and (not isinstance(domain, str) or not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,63}", domain)):
            raise ValueError("Domain must be a lowercase slug or null")
        if agent.get("protected") and agent.get("include_global"):
            raise ValueError("Protected bots cannot receive global lessons")
    curator = obj.get("curator_id")
    if not any(a["id"] == curator and a.get("active", True) and not a.get("protected", False) for a in agents):
        raise ValueError("curator_id must identify an active, non-protected configured bot")
    native = obj.get("native_root", "/home/box/agent-data")
    if not isinstance(native, str) or not Path(native).is_absolute():
        raise ValueError("native_root must be an absolute path")
    routine = obj.get("routine", {})
    if not isinstance(routine, dict):
        raise ValueError("routine must be an object")
    for key, default in [("name", "shared-learning-review"), ("schedule", "15 8,18 * * *"), ("timezone", "UTC")]:
        value = routine.get(key, default)
        if not isinstance(value, str) or not value.strip() or "\n" in value:
            raise ValueError("Invalid routine " + key)
    return obj


class Memory:
    def __init__(self, root, native=None):
        self.root = Path(root).resolve()
        self.config = load_config(self.root / "config.json")
        self.curator = self.config["curator_id"]
        self.native = Path(native or self.config.get("native_root", "/home/box/agent-data")).expanduser().resolve()
        self.root.joinpath("state").mkdir(parents=True, exist_ok=True)
        self.dbpath = self.root / "state" / "learning.sqlite3"
        self.db = sqlite3.connect(self.dbpath, timeout=20)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA foreign_keys=ON")
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA busy_timeout=20000")
        self.db.execute("PRAGMA synchronous=FULL")
        self.db.executescript("""
        CREATE TABLE IF NOT EXISTS metadata(key TEXT PRIMARY KEY, value TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS agents(id TEXT PRIMARY KEY, name TEXT NOT NULL,
          domain TEXT NOT NULL, protected INTEGER NOT NULL, include_global INTEGER NOT NULL,
          present INTEGER NOT NULL DEFAULT 1);
        CREATE TABLE IF NOT EXISTS events(id TEXT PRIMARY KEY, agent_id TEXT NOT NULL REFERENCES agents(id),
          kind TEXT NOT NULL, text TEXT NOT NULL, source_ref TEXT NOT NULL, origin TEXT NOT NULL,
          details TEXT NOT NULL, recorded_at TEXT NOT NULL, source_key TEXT UNIQUE NOT NULL);
        CREATE TABLE IF NOT EXISTS lessons(id TEXT PRIMARY KEY, agent_id TEXT NOT NULL REFERENCES agents(id),
          text TEXT NOT NULL, kind TEXT NOT NULL, scope TEXT NOT NULL, status TEXT NOT NULL,
          evidence_ids TEXT NOT NULL, evidence_type TEXT NOT NULL, rationale TEXT NOT NULL,
          created_at TEXT NOT NULL, updated_at TEXT NOT NULL, expires_at TEXT,
          revision INTEGER NOT NULL, supersedes TEXT);
        CREATE TABLE IF NOT EXISTS lesson_versions(seq INTEGER PRIMARY KEY AUTOINCREMENT,
          lesson_id TEXT NOT NULL, revision INTEGER NOT NULL, snapshot TEXT NOT NULL,
          actor TEXT NOT NULL, action TEXT NOT NULL, created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS retrievals(id TEXT PRIMARY KEY, agent_id TEXT NOT NULL,
          query TEXT NOT NULL, lesson_ids TEXT NOT NULL, created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS source_cursors(path TEXT PRIMARY KEY, agent_id TEXT NOT NULL,
          offset INTEGER NOT NULL, line_number INTEGER NOT NULL, boundary_hash TEXT NOT NULL,
          generation INTEGER NOT NULL, updated_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS audit(seq INTEGER PRIMARY KEY AUTOINCREMENT,
          actor TEXT NOT NULL, action TEXT NOT NULL, details TEXT NOT NULL, created_at TEXT NOT NULL);
        CREATE VIRTUAL TABLE IF NOT EXISTS lessons_fts USING fts5(lesson_id UNINDEXED, text);
        CREATE INDEX IF NOT EXISTS event_agent ON events(agent_id, recorded_at);
        CREATE INDEX IF NOT EXISTS lesson_scope ON lessons(scope, status);
        """)
        version = self.db.execute("SELECT value FROM metadata WHERE key='schema'").fetchone()
        if version and int(version[0]) != SCHEMA:
            raise ValueError("Unsupported schema; do not attempt an automatic destructive downgrade")
        self.db.execute("INSERT OR IGNORE INTO metadata VALUES('schema',?)", (str(SCHEMA),))
        self.db.commit()
        os.chmod(self.dbpath, 0o600)

    def close(self):
        self.db.close()

    def control(self):
        p = self.root / "state" / "control.json"
        return json.loads(p.read_text()) if p.is_file() else {"enabled": False, "release": RELEASE}

    def require_enabled(self):
        if not self.control().get("enabled"):
            raise ValueError("Shared learning is disabled; continue the original bot task normally")

    def audit(self, actor, action, details):
        self.db.execute("INSERT INTO audit(actor,action,details,created_at) VALUES(?,?,?,?)",
                        (actor, action, dump(details), now()))

    def roster(self):
        # Explicit configuration is authoritative; stale exported folders are not.
        self.config = load_config(self.root / "config.json")
        self.curator = self.config["curator_id"]
        seen = []
        with self.db:
            self.db.execute("UPDATE agents SET present=0")
            for obj in self.config["agents"]:
                if not obj.get("active", True):
                    continue
                aid, name = obj["id"], obj["name"]
                domain = obj.get("domain") or "unassigned-" + aid
                protected = obj.get("protected", False)
                include_global = obj.get("include_global", False)
                self.db.execute("""INSERT INTO agents VALUES(?,?,?,?,?,1)
                ON CONFLICT(id) DO UPDATE SET name=excluded.name,domain=excluded.domain,
                protected=excluded.protected,include_global=excluded.include_global,present=1""",
                    (aid, name, domain, int(protected), int(include_global)))
                seen.append({"id": aid, "name": name, "domain": domain, "protected": protected})
            self.audit("system", "roster-sync", {"count": len(seen)})
        return seen

    def agent(self, aid):
        row = self.db.execute("SELECT * FROM agents WHERE id=? AND present=1", (aid,)).fetchone()
        if not row:
            raise ValueError("Unknown or absent bot; use the current roster ID")
        return dict(row)

    def allowed_scopes(self, aid):
        a = self.agent(aid)
        scopes = ["bot:" + aid]
        if not a["protected"] and not a["domain"].startswith("unassigned-"):
            scopes.append("domain:" + a["domain"])
        if a["include_global"]:
            scopes.append("global")
        return scopes

    def record(self, aid, obj, internal=False):
        if not internal:
            self.require_enabled()
        self.agent(aid)
        if not isinstance(obj, dict):
            raise ValueError("Evidence input must be a JSON object")
        kind = obj.get("kind")
        if kind not in {"correction", "preference", "decision-reference", "outcome", "failure", "conversation-excerpt"}:
            raise ValueError("Invalid evidence kind")
        origin = obj.get("origin")
        if origin not in {"direct-user", "observed-result", "historical-transcript", "agent-inference"}:
            raise ValueError("Invalid evidence origin")
        if origin == "historical-transcript" and not internal:
            raise ValueError("Historical-transcript origin is reserved for the read-only importer")
        text = clean(obj.get("text"))
        ref = clean(obj.get("source_ref"), 2000)
        details = obj.get("details", {})
        if not isinstance(details, dict) or len(dump(details)) > 10000:
            raise ValueError("Details must be a small object")
        # Clean common secret formats in metadata too; never collect tool inputs/results.
        details = json.loads(SENSITIVE.sub("[redacted]", dump(details))) if not SENSITIVE.search(dump(details)) else {"redacted": True}
        source_key = sha(aid + "\n" + clean(obj.get("dedupe_key", ref + "\n" + kind + "\n" + text), 20000))
        old = self.db.execute("SELECT id FROM events WHERE source_key=?", (source_key,)).fetchone()
        if old:
            return {"id": old[0], "created": False}
        eid = "event-" + uuid.uuid4().hex
        with self.db:
            self.db.execute("INSERT OR IGNORE INTO events VALUES(?,?,?,?,?,?,?,?,?)",
                (eid, aid, kind, text, ref, origin, dump(details), now(), source_key))
            stored = self.db.execute("SELECT id FROM events WHERE source_key=?", (source_key,)).fetchone()[0]
        if stored != eid:
            return {"id": stored, "created": False}
        return {"id": eid, "created": True, "origin": origin}

    def event(self, eid):
        row = self.db.execute("SELECT * FROM events WHERE id=?", (eid,)).fetchone()
        if not row:
            raise ValueError("Evidence event does not exist")
        return dict(row)

    def version(self, lid, actor, action):
        row = dict(self.db.execute("SELECT * FROM lessons WHERE id=?", (lid,)).fetchone())
        self.db.execute("INSERT INTO lesson_versions(lesson_id,revision,snapshot,actor,action,created_at) VALUES(?,?,?,?,?,?)",
            (lid, row["revision"], dump(row), actor, action, now()))
        self.db.execute("DELETE FROM lessons_fts WHERE lesson_id=?", (lid,))
        self.db.execute("INSERT INTO lessons_fts VALUES(?,?)", (lid, row["text"]))

    def learn(self, aid, obj):
        self.require_enabled()
        self.agent(aid)
        if not isinstance(obj, dict):
            raise ValueError("Lesson input must be a JSON object")
        text = clean(obj.get("text"), 3000)
        kind = obj.get("kind", "preference")
        if kind not in {"preference", "workflow", "decision-reference", "boundary"}:
            raise ValueError("Invalid lesson kind")
        scope = obj.get("scope", "bot:" + aid)
        if scope not in self.allowed_scopes(aid):
            raise ValueError("Scope is outside this bot's permitted learning domains")
        eids = obj.get("evidence_ids")
        if not isinstance(eids, list) or not 1 <= len(eids) <= 10 or not all(isinstance(eid, str) for eid in eids):
            raise ValueError("Provide one to ten evidence event IDs")
        events = [self.event(eid) for eid in eids]
        if any(e["agent_id"] != aid for e in events):
            raise ValueError("A bot may propose only from its own evidence")
        etype = obj.get("evidence_type", "hypothesis")
        if etype not in {"explicit-correction", "verified-result", "hypothesis"}:
            raise ValueError("Invalid evidence type")
        rationale = clean(obj.get("rationale"), 3000)
        expiry = obj.get("expires_at")
        if expiry is not None:
            if not isinstance(expiry, str) or not expiry:
                raise ValueError("Expiry must be a future ISO timestamp with timezone or null")
            parsed = dt.datetime.fromisoformat(expiry)
            if parsed.tzinfo is None or parsed <= dt.datetime.now(dt.timezone.utc):
                raise ValueError("Expiry must be a future ISO timestamp with timezone")
        # History, inferences, permissions, and transferred lessons never self-promote.
        direct = any(e["origin"] == "direct-user" and e["kind"] in {"correction", "preference"} for e in events)
        active = (scope == "bot:" + aid and kind == "preference" and
                  etype == "explicit-correction" and obj.get("durable") is True and
                  direct and not BOUNDARY.search(text))
        status = "active" if active else "candidate"
        same = self.db.execute("SELECT id,status FROM lessons WHERE text=? AND scope=? AND status IN ('active','candidate')", (text, scope)).fetchone()
        if same:
            return {"id": same[0], "status": same[1], "created": False}
        lid = "lesson-" + uuid.uuid4().hex
        supersedes = obj.get("supersedes")
        if supersedes:
            old = self.lesson(supersedes)
            if old["scope"] != scope or old["agent_id"] != aid:
                raise ValueError("Supersession must stay within the same bot and scope")
        stamp = now()
        with self.db:
            self.db.execute("INSERT INTO lessons VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (lid, aid, text, kind, scope, status, dump(eids), etype, rationale,
                 stamp, stamp, expiry, 1, supersedes))
            if active and supersedes:
                self._status(supersedes, "superseded", aid, "explicit correction replaced lesson")
            self.version(lid, aid, "learn")
        return {"id": lid, "status": status, "created": True}

    def lesson(self, lid):
        row = self.db.execute("SELECT * FROM lessons WHERE id=?", (lid,)).fetchone()
        if not row:
            raise ValueError("Unknown lesson")
        return dict(row)

    def _status(self, lid, status, actor, rationale):
        self.db.execute("UPDATE lessons SET status=?,revision=revision+1,updated_at=?,rationale=? WHERE id=?",
            (status, now(), rationale, lid))
        self.version(lid, actor, status)

    def review(self, actor, lid, decision, rationale):
        self.require_enabled()
        a = self.agent(actor)
        item = self.lesson(lid)
        owner = self.agent(item["agent_id"])
        if actor != item["agent_id"] and (actor != self.curator or owner["protected"]):
            raise ValueError("Review is restricted to the owner or the curator of non-protected bots")
        if item["scope"] != "bot:" + item["agent_id"] and actor != self.curator:
            raise ValueError("Shared lesson promotion requires curator review")
        if decision not in {"activate", "retire"}:
            raise ValueError("Review decision must be activate or retire")
        if decision == "activate":
            if item["kind"] == "boundary" or BOUNDARY.search(item["text"]):
                raise ValueError("Authority changes remain in original profiles; boundary lessons cannot be activated")
            if item["evidence_type"] == "hypothesis":
                raise ValueError("Hypotheses require a new evidence-backed proposal before activation")
            if item["expires_at"] and dt.datetime.fromisoformat(item["expires_at"]) <= dt.datetime.now(dt.timezone.utc):
                raise ValueError("Cannot activate an expired lesson")
            evidence = [self.event(eid) for eid in json.loads(item["evidence_ids"])]
            if item["evidence_type"] == "explicit-correction" and not any(e["origin"] == "direct-user" for e in evidence):
                raise ValueError("Historical text alone cannot establish a current durable correction")
            if item["evidence_type"] == "verified-result" and not any(e["origin"] == "observed-result" for e in evidence):
                raise ValueError("A verified-result lesson needs an observed result")
        with self.db:
            self._status(lid, "active" if decision == "activate" else "retired", actor, clean(rationale, 3000))
            if decision == "activate" and item["supersedes"]:
                self._status(item["supersedes"], "superseded", actor, "replaced by " + lid)
        return self.lesson(lid)

    def recall(self, aid, query, limit=8):
        if not self.control().get("enabled"):
            return {"enabled": False, "lessons": [], "instruction": "Continue your original task normally."}
        scopes = self.allowed_scopes(aid)
        query = clean(query, 1500)
        words = re.findall(r"[^\W_]{2,}", query, re.UNICODE)[:20]
        hits = []
        if words:
            match = " OR ".join('"' + w.replace('"', '""') + '"' for w in words)
            sql = """SELECT l.*,bm25(lessons_fts) AS rank FROM lessons_fts
                JOIN lessons l ON l.id=lessons_fts.lesson_id JOIN agents a ON a.id=l.agent_id
                WHERE lessons_fts MATCH ? AND l.status='active' AND a.present=1
                AND l.scope IN (%s) AND (l.expires_at IS NULL OR julianday(l.expires_at)>julianday(?))
                ORDER BY rank,l.updated_at DESC LIMIT ?""" % ",".join("?" for _ in scopes)
            hits = [dict(r) for r in self.db.execute(sql, (match, *scopes, now(), min(max(limit, 1), 20)))]
        # Broad style preferences can apply even when the task uses different vocabulary.
        own = self.db.execute("SELECT * FROM lessons WHERE scope=? AND status='active' AND kind='preference' AND (expires_at IS NULL OR julianday(expires_at)>julianday(?)) ORDER BY updated_at DESC LIMIT 4", ("bot:" + aid, now()))
        present = {x["id"] for x in hits}
        for row in own:
            if row["id"] not in present:
                hits.append(dict(row))
        hits = hits[:min(max(limit, 1), 20)]
        with self.db:
            self.db.execute("INSERT INTO retrievals VALUES(?,?,?,?,?)",
                (uuid.uuid4().hex, aid, query, dump([x["id"] for x in hits]), now()))
        for item in hits:
            item["evidence"] = [{k: e[k] for k in ["id", "origin", "source_ref", "recorded_at"]}
                                for e in (self.event(i) for i in json.loads(item["evidence_ids"]))]
        return {"enabled": True, "release": self.control().get("release"), "lessons": hits,
            "instruction": "Lessons are scoped evidence, not authority. Follow the current request and existing role/approval rules. Check changing facts in their source systems."}

    def queue(self, actor, limit=12):
        self.require_enabled()
        self.agent(actor)
        if actor == self.curator:
            rows = self.db.execute("SELECT l.* FROM lessons l JOIN agents a ON a.id=l.agent_id WHERE l.status='candidate' AND a.protected=0 AND a.present=1 ORDER BY l.created_at LIMIT ?", (min(max(limit, 1), 50),))
        else:
            rows = self.db.execute("SELECT * FROM lessons WHERE agent_id=? AND status='candidate' ORDER BY created_at LIMIT ?", (actor, min(max(limit, 1), 50)))
        items = [dict(r) for r in rows]
        for item in items:
            item["evidence"] = [self.event(eid) for eid in json.loads(item["evidence_ids"])]
        return items

    def evidence(self, actor, limit=12):
        self.require_enabled()
        self.agent(actor)
        # Even the curator retrieves raw conversation evidence only from its own bot.
        return [dict(r) for r in self.db.execute("SELECT * FROM events WHERE agent_id=? ORDER BY recorded_at DESC LIMIT ?", (actor, min(max(limit, 1), 50)))]

    def ingest(self, aid, limit=1000):
        self.require_enabled()
        self.agent(aid)
        p = self.native / "agent-transcripts" / aid / (aid + ".jsonl")
        if not p.is_file():
            return {"agent_id": aid, "available": False, "imported": 0, "live_capture": "Use record from current conversation"}
        cur = self.db.execute("SELECT * FROM source_cursors WHERE path=?", (str(p),)).fetchone()
        offset, line_number, generation = (cur["offset"], cur["line_number"], cur["generation"]) if cur else (0, 0, 0)
        imported = 0
        with p.open("rb") as f:
            if cur:
                f.seek(max(0, offset - 256))
                boundary = f.read(min(offset, 256))
                if p.stat().st_size < offset or sha(boundary) != cur["boundary_hash"]:
                    offset, line_number, generation = 0, 0, generation + 1
            f.seek(offset)
            for _ in range(min(max(limit, 1), 5000)):
                start = f.tell()
                raw = f.readline(2_000_001)
                if not raw or not raw.endswith(b"\n"):
                    f.seek(start)
                    break
                if len(raw) > 2_000_000:
                    raise ValueError("Oversized transcript record; inspect source format")
                line_number += 1
                try:
                    obj = json.loads(raw)
                except (ValueError, UnicodeDecodeError):
                    continue
                if not isinstance(obj, dict):
                    continue
                role = obj.get("role")
                msg = obj.get("message")
                if role not in {"user", "assistant"} or not isinstance(msg, dict):
                    continue
                content = msg.get("content")
                if not isinstance(content, list):
                    continue
                texts = [b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text" and isinstance(b.get("text"), str)]
                text = "\n".join(texts).strip()
                if not text:
                    continue
                text = text[:15000]
                result = self.record(aid, {"kind": "conversation-excerpt", "text": text,
                    "source_ref": f"{p}#line={line_number};sha256={sha(raw)}",
                    "origin": "historical-transcript", "details": {"role": role,
                    "source_mtime": dt.datetime.fromtimestamp(p.stat().st_mtime, dt.timezone.utc).isoformat(),
                    "message_time": None, "verified_human": False, "generation": generation},
                    "dedupe_key": "transcript:" + str(p) + ":" + str(line_number) + ":" + sha(raw)}, internal=True)
                imported += int(result["created"])
            offset = f.tell()
            f.seek(max(0, offset - 256))
            boundary = sha(f.read(min(offset, 256)))
        with self.db:
            self.db.execute("INSERT OR REPLACE INTO source_cursors VALUES(?,?,?,?,?,?,?)",
                (str(p), aid, offset, line_number, boundary, generation, now()))
        return {"agent_id": aid, "available": True, "imported": imported, "offset": offset,
                "remaining_bytes": max(0, p.stat().st_size - offset), "source_mtime": dt.datetime.fromtimestamp(p.stat().st_mtime, dt.timezone.utc).isoformat(),
                "warning": "Filesystem modification time is not a message timestamp or a guarantee of freshness."}

    def checkpoint(self, name):
        if not re.fullmatch(r"[a-zA-Z0-9_-]{1,80}", name):
            raise ValueError("Invalid checkpoint name")
        dest = self.root / "backups" / name
        dest.mkdir(parents=True, exist_ok=False)
        target = dest / "learning.sqlite3"
        conn = sqlite3.connect(target)
        try:
            self.db.backup(conn)
            # A checkpoint must be self-contained, with no WAL/SHM sidecar dependency.
            conn.execute("PRAGMA journal_mode=DELETE")
        finally:
            conn.close()
        os.chmod(target, 0o600)
        atomic_json(dest / "manifest.json", {"schema": SCHEMA, "created_at": now(),
            "database_sha256": sha(target.read_bytes()), "control": self.control()})
        return {"checkpoint": name, "path": str(dest)}

    def switch(self, enabled):
        value = self.control()
        value.update({"enabled": bool(enabled), "changed_at": now(), "release": RELEASE})
        atomic_json(self.root / "state" / "control.json", value)
        with self.db:
            self.audit("operator", "enable" if enabled else "disable", {"release": RELEASE})
        return value

    def rollback(self, name):
        if not re.fullmatch(r"[a-zA-Z0-9_-]{1,80}", name):
            raise ValueError("Invalid checkpoint name")
        dest = self.root / "backups" / name
        manifest = json.loads((dest / "manifest.json").read_text())
        target = dest / "learning.sqlite3"
        if manifest["schema"] != SCHEMA or sha(target.read_bytes()) != manifest["database_sha256"]:
            raise ValueError("Checkpoint verification failed")
        old = sqlite3.connect(target.resolve().as_uri() + "?mode=ro", uri=True)
        old.row_factory = sqlite3.Row
        baseline = [dict(x) for x in old.execute("SELECT * FROM lessons")]
        old.close()
        self.switch(False)
        baseline_ids = {x["id"] for x in baseline}
        with self.db:
            for row in list(self.db.execute("SELECT id FROM lessons")):
                if row[0] not in baseline_ids:
                    self._status(row[0], "candidate", "operator", "Preserved after rollback; revalidation required")
            for saved in baseline:
                current = self.lesson(saved["id"])
                saved["revision"] = current["revision"] + 1
                saved["updated_at"] = now()
                keys = list(saved)
                self.db.execute("UPDATE lessons SET " + ",".join(k + "=?" for k in keys if k != "id") + " WHERE id=?",
                    [saved[k] for k in keys if k != "id"] + [saved["id"]])
                self.version(saved["id"], "operator", "rollback:" + name)
            self.audit("operator", "rollback", {"checkpoint": name, "events_preserved": True})
        return {"enabled": False, "checkpoint": name, "events_preserved": True,
            "native_profiles": "Not modified by this command. Native restoration manifest is separate; appended learning instructions are inert while disabled."}

    def status(self):
        result = {"control": self.control(), "schema": SCHEMA, "database": str(self.dbpath)}
        for table in ["events", "lessons", "retrievals", "lesson_versions"]:
            result[table] = self.db.execute("SELECT count(*) FROM " + table).fetchone()[0]
        result["agents"] = self.db.execute("SELECT count(*) FROM agents WHERE present=1").fetchone()[0]
        result["lesson_status"] = dict(self.db.execute("SELECT status,count(*) FROM lessons GROUP BY status"))
        result["integrity"] = self.db.execute("PRAGMA integrity_check").fetchone()[0]
        return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=os.environ.get("GROK_LEARNING_ROOT", "/workspace/grok-learning"))
    parser.add_argument("--native-root", help="Override the configured read-only native export root")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ["init", "roster", "status", "enable", "disable"]:
        sub.add_parser(name)
    for name in ["checkpoint", "rollback"]:
        p = sub.add_parser(name); p.add_argument("name")
    for name in ["record", "learn", "queue", "evidence", "ingest", "session", "recall"]:
        p = sub.add_parser(name); p.add_argument("--agent", required=True)
        if name in {"session", "recall"}: p.add_argument("--query", required=True)
        if name in {"queue", "evidence", "ingest"}: p.add_argument("--limit", type=int, default=12 if name != "ingest" else 1000)
    p = sub.add_parser("review")
    p.add_argument("--actor", required=True); p.add_argument("--lesson", required=True)
    p.add_argument("--decision", choices=["activate", "retire"], required=True)
    p.add_argument("--rationale", required=True)
    args = parser.parse_args(argv)
    memory = None
    try:
        memory = Memory(args.root, args.native_root)
        cmd = args.command
        if cmd == "init": result = {"roster": memory.roster(), "status": memory.status()}
        elif cmd == "roster": result = [dict(r) for r in memory.db.execute("SELECT * FROM agents WHERE present=1 ORDER BY name")]
        elif cmd == "status": result = memory.status()
        elif cmd in {"enable", "disable"}: result = memory.switch(cmd == "enable")
        elif cmd == "checkpoint": result = memory.checkpoint(args.name)
        elif cmd == "rollback": result = memory.rollback(args.name)
        elif cmd in {"record", "learn"}: result = getattr(memory, cmd)(args.agent, json.load(sys.stdin))
        elif cmd in {"queue", "evidence", "ingest"}: result = getattr(memory, cmd)(args.agent, args.limit)
        elif cmd in {"session", "recall"}: result = memory.recall(args.agent, args.query)
        elif cmd == "review": result = memory.review(args.actor, args.lesson, args.decision, args.rationale)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (ValueError, TypeError, OSError, sqlite3.Error, KeyError) as exc:
        print(json.dumps({"error": str(exc), "continue_original_task": True}), file=sys.stderr)
        return 2
    finally:
        if memory: memory.close()


if __name__ == "__main__":
    raise SystemExit(main())
