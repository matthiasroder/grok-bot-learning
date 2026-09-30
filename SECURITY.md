# Security and privacy

This is a trusted, single-account learning layer. It does not isolate bots from each other, authenticate caller-supplied bot IDs, enforce tool permissions, or verify that a stored source reference is true. Permission keyword checks and credential redaction are limited heuristics. Existing platform approvals and the current human request retain authority.

Do not place secrets, unneeded personal facts, raw tool payloads, or complete conversations in the learning store. Store only useful excerpts and source references. Keep private configuration, runtime databases, native snapshots, and transcripts outside the repository. The repository's examples and tests use synthetic data.

If you discover a vulnerability, contact the maintainer through the contact information at https://matthiasroder.com rather than opening a public issue containing private state. A minimal synthetic reproduction is usually enough. Do not include access keys or live native profile dumps.
