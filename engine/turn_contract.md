# Turn Contract

Before every play turn the backend must assemble a compact scene contract from current_state, calendar/arc/location, character runtime summaries, relationships, knowledge, open threads, event queue, rating/gossip and energy atmosphere.

The scene must not be written if the contract is missing current_frame, character_slice, relationship_slice, knowledge_slice, or response_format_contract.

Play mode returns visible prose only. Technical/debug data is allowed only in technical mode.
