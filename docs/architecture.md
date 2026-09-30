# Architecture and trust

The native bot handles judgment. Python handles persistence, scope filters, lifecycle checks, and evidence references. There is no model API call inside the runtime. The bot must choose when to record useful evidence and how to propose a lesson.

## Storage

| Table | What it preserves |
| --- | --- |
| `agents` | Explicit roster, domains, protected/global flags, presence. |
| `events` | Focused correction/outcome evidence with source references. |
| `lessons` | Current candidate, active, retired, or superseded lesson state. |
| `lesson_versions` | Every lesson revision and its actor/action. |
| `lessons_fts` | Lexical search index of lesson text. |
| `retrievals` | Queries and returned lesson IDs. This proves retrieval, not causal influence on an answer. |
| `source_cursors` | Historical import offsets and source-boundary fingerprints. |
| `audit` | Operator and roster actions. |

SQLite uses WAL, a busy timeout, and full synchronous mode. Checkpoints use the online backup API and a standalone rollback-journal file, with a SHA-256 checksum. No raw live WAL copy is used as a backup.

## Lifecycle

A durable local preference can become active when its evidence includes a direct-user correction or preference, the proposal declares explicit-correction evidence, and its text does not match the permission-boundary heuristic. Shared lessons and workflows begin as candidates. The curator can promote a supported non-protected candidate; protected owners review their own local candidates.

These checks establish structural prerequisites. They cannot prove that the bot classified the human correctly, that a quoted statement was authentic, or that the lesson follows logically. Review and original approval rules remain necessary. Anyone with the shared account's shell access can bypass the CLI, so it is not a permissions enforcement service.

Rollback restores the checkpoint's lesson states and revises newer lessons to candidates while retaining events and revision history. It does not undo an email, a publication, a tool action, or another source-system change. It does not restore native profiles; that uses a separate manifest and supported tools.

## Scope

Bot-local lessons stay local. A shared domain only permits explicit domain proposals and recalls. Protected bots cannot propose shared lessons, do not receive global lessons, and are excluded from the curator's candidate queue. Global sharing is opt-in. The family/creative examples are examples of policy choices, not categories inferred from bot names.

The curator's raw `evidence` command still returns only its own events. Its candidate queue includes evidence attached to non-protected candidates. Private information can still be included in an incorrectly scoped proposal; the model and operator must check it. A shared OS account is unsuitable when bots need adversarial isolation.

## Reporting and measurement

The routine reports after each review, including empty and failed runs. It reports what the review changed, and does not scan protected data or pretend to summarize every locally activated preference. Users can inspect status, source evidence, and retrieval history separately.

Mechanism tests cover learning, sharing, recall, expiry, supersession, rollback, and native preparation. Long-term quality needs separate outcome measurements: repeated corrections, accepted outputs, successful task checks, and the cost of erroneous lessons. This release does not calculate those metrics or claim a benchmark improvement.
