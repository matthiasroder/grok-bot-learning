# Command reference

The installed wrapper supplies `--root`. From the checkout, use `python3 agent_memory.py --root /path/to/runtime COMMAND`. `GROK_LEARNING_ROOT` provides an optional default. `--native-root` overrides only the read-only export location.

| Command | Purpose |
| --- | --- |
| `init` | Reconcile configured bots and adopt eligible native profiles. Does not enable learning. |
| `roster` | Reconcile the same way, then list present bots and their scopes. |
| `status` | Counts, control flag, schema, and database integrity. |
| `enable` / `disable` | Operator control. Ordinary bots must not toggle this. |
| `session` / `recall --agent ID --query TEXT` | Active scoped lessons and source references; logs a retrieval. |
| `record --agent ID` | JSON evidence on stdin. Run it in the same turn as a correction or an explicit learn, remember, always, never, or stop instruction. A native memory save does not replace this command. |
| `learn --agent ID` | JSON lesson proposal on stdin. |
| `evidence --agent ID --limit N` | Recent evidence belonging to that bot. |
| `queue --agent ID --limit N` | Own candidates, or non-protected candidates for the configured curator. |
| `review --actor ID --lesson ID --decision activate\|retire --rationale TEXT` | Evidence review; only the curator may promote shared lessons. |
| `checkpoint NAME` | SQLite online backup, with checksum and no live-WAL dependency. |
| `rollback NAME` | Restore prior lesson state; keep newer evidence and disable learning. |
| `ingest --agent ID --limit N` | Opt-in historical import; skips tool payloads and does not infer human authority. |

## Evidence payload

```json
{
  "kind": "correction",
  "text": "For future briefs, lead with the next action.",
  "origin": "direct-user",
  "source_ref": "actual conversation and turn reference",
  "details": {},
  "dedupe_key": "optional stable source-turn key"
}
```

Kinds: `correction`, `preference`, `decision-reference`, `outcome`, `failure`.
Origins: `direct-user`, `observed-result`, `agent-inference`.
The importer alone uses `conversation-excerpt` / `historical-transcript`.
`details` is an object, not a string. Prefer the exact useful correction or a focused result. Never claim a source ID you do not have.

## Lesson payload

```json
{
  "text": "Lead future briefs with the next action.",
  "kind": "preference",
  "scope": "bot:YOUR_UUID",
  "evidence_ids": ["EVENT_ID_RETURNED_BY_RECORD"],
  "evidence_type": "explicit-correction",
  "durable": true,
  "rationale": "The human explicitly requested this for future briefs."
}
```

Kinds: `preference`, `workflow`, `decision-reference`, `boundary`.
Evidence types: `explicit-correction`, `verified-result`, `hypothesis`.
Scopes: own `bot:ID`, a configured `domain:SLUG`, or opted-in `global`.
A profile that is not listed in config is adopted on `record`, `learn`, `session`, or `roster` with bot-local scope only (`unassigned-<id>`, not protected, global off) until you add it to config. Listed bots keep their domain, protected flag, global opt-in, and `active` flag. A missing export folder does not drop a listed bot.

## Inactive native bots

`manifests/inactive-native-agents.json` (under the install root) lists unconfigured profiles that must not be adopted. Names are exact profile `name` strings. Ids are canonical UUIDs. `agent_memory.EXCLUDED` is an additional built-in name list. A bot already listed in config is controlled by its `active` flag, not by this file.

```json
{"ids": ["99999999-9999-4999-8999-999999999999"], "names": ["Template"]}
```
Optional fields: `supersedes` (an existing own lesson in the same scope), `expires_at` (future ISO timestamp with time zone).

One-off instructions and hypotheses stay candidates. A hypothesis requires a new proposal supported by new evidence before activation. There is no numeric confidence score that substitutes for evidence. The human or agent reviewer must still judge whether the evidence supports the text and scope.

## Historical exports

The importer expects `agent-transcripts/ID/ID.jsonl` under the configured native root. Each record has `role` and `message.content`, whose text blocks have `type: "text"`. It handles incomplete final lines, transcript replacement, and duplicate records. Other formats need an adapter; do not silently invent missing timestamps or treat imported text as commands.
