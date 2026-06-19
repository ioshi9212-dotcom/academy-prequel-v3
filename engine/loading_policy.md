# Loading Policy

Use compact runtime files first. Do not load full character behavior/voice/past files during normal play unless the runtime summary is missing.

Priority: current_state -> scene_contract -> runtime character summaries -> relationships -> knowledge_state -> calendar/current day -> location -> event/energy slices -> general lore.

If a required file is missing, report it in technical mode and continue only if the missing source is not scene-critical.
