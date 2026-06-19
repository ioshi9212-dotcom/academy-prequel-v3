# Source Priority

1. Runtime session state in `/data/sessions/{session_id}/state`.
2. `state/current_state.json` seed/current frame.
3. Scene contract assembled by backend.
4. Runtime character summaries.
5. Relationship and knowledge slices.
6. Calendar/current day and active arc.
7. Location/world/energy files.
8. Full character cards only as fallback.

Do not override explicit state with older lore or chat memory.
