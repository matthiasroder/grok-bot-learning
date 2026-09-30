# Native deployment and restoration

The Python tools prepare and verify files. They do not impersonate native Grok management tools. Grok's supported tool names and UI can change; consult the tools available in your own session and the [official documentation](https://docs.x.ai/grok-bot/bots).

## Copyable setup prompt

Use this with the existing bot you chose as curator after creating your private configuration and running the installer. Replace the root if needed. Review the requested scope before sending it.

> Integrate the prepared shared-learning system at /workspace/grok-learning across the active bots explicitly listed in config.json. Read current/SKILL.md, manifests/native-activation.json, and manifests/native-restoration.json. The runtime must remain disabled during integration. Confirm each bot exists in the native app, compare its current description with the saved original or exact target, and stop on unrelated drift. Use supported native Grok tools to apply each exact target description, preserving every unrelated field. Do not write native profile JSON or internal databases. Do not message or wake sibling bots unless I explicitly authorize the needed coordination.
>
> Inspect my existing routines. If the proposed routine name already exists, stop rather than overwrite it; let me choose a new name. Otherwise create the specified review routine on yourself with its exact prompt, schedule, time zone, and enabled state. Read it back in the native UI/tool, and preserve other routines.
>
> Before activation, prove exact restoration for a populated original description and for each originally empty description, then reapply the targets. Use only supported native setters. An empty description may require the owning bot's own setter; if messaging that bot is needed, explain the exact request to me. Do not substitute placeholder text. Run current/native.py verify --root /workspace/grok-learning and require every profile activated with zero drift/missing. File readback alone does not establish native bot existence or a saved routine. Save actual tool results and verification in manifests/native-application-report.json.
>
> Once all checks pass, enable agent-memory and run a session as your own ID. Record a real verified setup outcome, propose a bot-local workflow lesson, review its evidence, and query it in a new session. Save the actual results and IDs. Do not fabricate a user preference or claim every bot has run merely because its profile was updated. Finish with a concise report. Keep original roles and approvals authoritative.

This prompt authorizes the described integration when the owner chooses to send it. It is not authority for unrelated tasks, messages, logins, or business actions.

## Native compatibility observations

In the original deployment on 2026-09-30, another bot's `UpdateAgent` rejected an empty or whitespace-only description. The owning bot's `UpdateState` profile setter accepted `description=""`. We verified empty readback and reapplied the original target on three bots. The tools also normalized leading whitespace for initially empty descriptions.

These are observed behaviors from one deployment, not a stable SDK contract. The generated target avoids padding for an empty original. If the current native setter normalizes a nonempty original, report the mismatch instead of silently changing the restoration baseline.

Exported folders can survive native deletion. A stale folder does not justify recreating a bot. Mark confirmed-absent IDs inactive in private configuration. Run `agent-memory init` to reconcile the database roster; it retains their historical evidence. Do not run init casually while editing scopes.

## Restoration

1. Run `agent-memory disable`. Stop scheduled learning activity by pausing only the added review routine.
2. If lesson state also needs reverting, run `agent-memory rollback CHECKPOINT`. It keeps newer evidence/history and leaves learning disabled.
3. Read `manifests/native-restoration.json`. Compare each current description with `expected_current_description`. If a person has since edited it, reconcile that change rather than overwriting it.
4. Restore each exact original description through supported native setters, including the owning-bot path for empty originals if necessary. Confirm the human has authorized any required messages.
5. Verify descriptions and unrelated fields against `backups/native-baseline/`. Do not delete evidence, conversations, or pre-existing routines. A paused added routine can be removed separately when the owner requests it.

Native manifests contain private profile contents. Keep them outside the source checkout and out of public issues and pull requests.
