# Changelog

## 0.3.0

- Adopt a native bot profile that is not already in config, so `record`, `learn`, and `session` accept a bot created after the last `init`.
- `roster` reconciles before listing and still writes the `roster-sync` audit entry.
- Skip unlisted profiles whose names are in `EXCLUDED` or whose ids or names are in `manifests/inactive-native-agents.json`. Configured bots keep their domain, protected flag, global opt-in, and `active` flag.
- Mark an adopted bot absent when its profile folder is gone on the next sync. Evidence is kept. A configured bot stays present if the export folder is missing.
- The shared-learning skill text now says a new bot is adopted on first use. Update the catalog copy of that skill when upgrading. Profile blocks are unchanged, so native profiles do not need to be rewritten for this release.

## 0.2.0

- Shared-learning block v2: record a correction in the same turn as the user's words, in addition to any native memory save.
