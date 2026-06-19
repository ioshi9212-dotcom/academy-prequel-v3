# Academy Prequel V3 — Variant B Stage 1

This stage switches the Railway entrypoint to the V3 backend runtime and adds the first backend-controlled turn endpoint.

## Added

- `app/core/storage.py` — Railway `/data` runtime/session storage layer used by `app/main.py`.
- `app/services/ai_provider.py` — AI provider abstraction with safe `mock` provider and optional OpenAI-compatible provider.
- `app/variant_b_runtime.py` — Variant B turn pipeline.
- `app/server.py` now imports `app.variant_b_runtime:app`.

## New endpoint

```text
POST /api/v2/sessions/{session_id}/turn
```

Request example:

```json
{
  "user_input": "начнем",
  "mode": "play",
  "dry_run": true,
  "save_result": false,
  "ai_provider": "mock",
  "include_prompt_bundle": true
}
```

This endpoint currently:

1. ensures/loads the session;
2. normalizes legacy Academy state fields like `active_characters` into V3 fields like `active_character_ids`;
3. builds the compact scene contract;
4. checks required files and reports which files loaded/missed;
5. calls the mock AI provider;
6. returns a mock scene text and the backend prompt bundle.

It does **not** save the mock scene unless `save_result=true` and `dry_run=false`.

## GPT Actions schema

Use:

```text
/openapi-v2-actions.json
```

For Railway:

```text
https://<your-service>.up.railway.app/openapi-v2-actions.json
```

## Next stage

After deploy, test:

1. `/health`
2. `/debug/volume`
3. create session through `/api/v1/sessions`
4. call `/api/v2/sessions/{session_id}/turn` with `dry_run=true`
5. inspect `required_files_status` for missing lore/characters/runtime files.

Then we connect a real model provider and map AI JSON state changes into automatic save.
