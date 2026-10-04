# Native deployment and restoration

The Python tools prepare and verify files. They do not impersonate native Grok management tools. Grok's supported tool names and UI can change; consult the tools available in your own session and the [official documentation](https://docs.x.ai/grok-bot/bots).

## Copyable setup prompt

Use this with the existing bot you chose as curator after creating your private configuration and running the installer. Replace the root if needed. Review the requested scope before sending it.

> Integrate the prepared shared-learning system at /workspace/grok-learning across the active bots explicitly listed in config.json. Read current/SKILL.md, manifests/native-activation.json, and manifests/native-restoration.json. The runtime must remain disabled during integration. Confirm each bot exists in the native app, compare its current description with the saved original or exact target, and stop on unrelated drift. Use supported native Grok tools to apply each exact target description, preserving every unrelated field. Do not write native profile JSON or internal databases. Do not message or wake sibling bots unless I explicitly authorize the needed coordination.
>
> Inspect my existing routines. If the proposed routine name already exists, stop rather than overwrite it; let me choose a new name. Otherwise create the specified review routine on yourself with its exact prompt, schedule, time zone, and enabled state. Read it back in the native UI/tool, and preserve other routines. The routine posts one short summary to the owner after every run, including a run with 0 candidates.
>
> Save current/SKILL.md into the Grok Bot skill catalog under the name `shared-learning`, using your UpdateState skill write. The catalog entry must match that canonical file, including its trigger description. A file on disk that is not in the catalog does not register the skill.
>
> Before activation, prove exact restoration for a populated original description and for each originally empty description, then reapply the targets. Use only supported native setters. An empty description may require the owning bot's own setter; if messaging that bot is needed, explain the exact request to me. Do not substitute placeholder text. Run current/native.py verify --root /workspace/grok-learning and require every profile activated with zero drift/missing. File readback alone does not establish native bot existence or a saved routine. Save actual tool results and verification in manifests/native-application-report.json.
>
> Once all checks pass, enable agent-memory and run a session as your own ID. Record a real verified setup outcome, propose a bot-local workflow lesson, review its evidence, and query it in a new session. Save the actual results and IDs. Do not fabricate a user preference or claim every bot has run merely because its profile was updated. Finish with a concise report. Keep original roles and approvals authoritative.

This prompt authorizes the described integration when the owner chooses to send it. It is not authority for unrelated tasks, messages, logins, or business actions.

## Skill catalog

`current/SKILL.md` is the canonical skill, rendered from `templates/SKILL.md` at install time. Save that same text into the Grok Bot skill catalog under the name `shared-learning`. The fleet owner writes it with UpdateState's skill write. Keep the catalog entry identical to the canonical file, and update both in the same change whenever the skill text changes. Do not register a second skill under another name.

The profile block names `shared-learning` by that catalog name. A copy that exists only as a file is not in the bot's skill catalog, so the bot will not open the trigger rules. The catalog description is what surfaces the skill when the user corrects the bot or says learn, remember, from now on, always, never, or stop doing X, and at the start of substantive work.

## Same-turn recording

A native memory save does not write the shared learning log and does not count as recording. The profile block says this explicitly. When the user corrects the bot, or says learn, remember, from now on, always, never, or stop doing X, the bot runs `record` in that same turn (kind `correction` or `preference`, origin `direct-user`, the user's exact words, `source_ref` = conversation + turn), in addition to any native memory save. For a lasting preference about that bot's own work it also runs `learn` with the returned event id, scoped to `bot:<that bot's id>`.

Scheduled reviews only consolidate candidates that were recorded. They cannot recover a correction that never reached the log.

## Empty descriptions

A profile description that must be exactly empty can only be restored by the owning bot's own profile setter. The sibling-agent update tool rejects empty or whitespace-only descriptions. Do not substitute placeholder text. Prove empty readback with the owning bot's setter, then reapply the target description.

## Upgrade an existing block

Profile blocks stay wrapped in `[shared-learning:begin]` and `[shared-learning:end]`. `prepare` appends the current block, or replaces the text between those markers when a block is already present. Text outside the markers is left unchanged. `prepare` refuses to regenerate a manifest that already exists, so the baseline backups stay intact.

When a manifest was prepared with an older block, run this version's `native.py` against the existing install:

```sh
python3 native.py upgrade --root /path/to/existing-install
python3 native.py verify --root /path/to/existing-install
```

`upgrade` rewrites the prepared target descriptions and the restoration manifest's expected descriptions, refreshes the proposed review prompt and `current/SKILL.md` from the templates beside that `native.py`, and does not write native profiles or replace baseline backups. Apply the new targets with supported native tools, update the catalog skill from the refreshed canonical file, then run `verify`. `verify` requires the exact current block, unchanged text outside the markers, and identical fields other than `description`. It exits nonzero otherwise.

## Native compatibility observations

In the original deployment on 2026-09-30, another bot's `UpdateAgent` rejected an empty or whitespace-only description. The owning bot's `UpdateState` profile setter accepted `description=""`. We verified empty readback and reapplied the original target on three bots. The tools also normalized leading whitespace for initially empty descriptions.

These are observed behaviors from one deployment, not a stable SDK contract. The generated target avoids padding for an empty original. If the current native setter normalizes a nonempty original, report the mismatch instead of silently changing the restoration baseline.

`init` and `roster` adopt a native profile that is not already listed in config, with bot-local scope only. `record`, `learn`, and `session` do that same sync once when the bot id is a canonical UUID, `profile.json` exists, and the bot is not excluded or inactive. Invalid ids and missing profiles do not sync. The sync writes the usual `roster-sync` audit row and does not modify native profiles, native config, or the enable flag.

For a profile that is not listed in config, put its id or exact profile name in `manifests/inactive-native-agents.json` so the next `roster` or `init` does not adopt it. A bot that is already in config follows that bot's `active` flag; set `active: false` to mark it absent. Either way, historical evidence stays. Deleting an adopted bot's folder marks that bot absent on the next sync. A configured bot stays present while `active` is true, even if its export folder is missing, because an export can be incomplete. Do not run init casually while editing scopes.

## Restoration

1. Run `agent-memory disable`. Stop scheduled learning activity by pausing only the added review routine.
2. If lesson state also needs reverting, run `agent-memory rollback CHECKPOINT`. It keeps newer evidence/history and leaves learning disabled.
3. Read `manifests/native-restoration.json`. Compare each current description with `expected_current_description`. If a person has since edited it, reconcile that change rather than overwriting it.
4. Restore each exact original description through supported native setters. An original that must be exactly empty has to go through the owning bot's own profile setter; the sibling-agent update tool rejects empty or whitespace-only descriptions. Confirm the human has authorized any required messages. Do not substitute placeholder text.
5. Verify descriptions and unrelated fields against `backups/native-baseline/`. Do not delete evidence, conversations, or pre-existing routines. A paused added routine can be removed separately when the owner requests it.

Native manifests contain private profile contents. Keep them outside the source checkout and out of public issues and pull requests.
