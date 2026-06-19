# Scene Assembly Gate

A play scene may start only after these are present:
- current_frame;
- at least one active character besides/including POV;
- character_slice for POV and active NPCs;
- relationship_slice or explicit empty state;
- knowledge_slice or explicit empty state;
- location/current arc context;
- response_format_contract.

If these are missing, technical mode must report the missing source instead of writing a scene.
