# Output Format

Play scene output must prioritize the actual scene, not the header.

## Header: compact, max 4 lines

📅 {date_human} · 🕒 {time_human}
📍 {location_human}
🌤 {weather_human}
✦ POV: {pov_character_id} · {pov_state_human}

Optional inventory/outfit line is allowed only if it is exact from state/current_outfit. Do not invent clothing, colors, uniform, accessories, hairstyle, or items.

## Required scene body

After the compact header, ALWAYS write scene prose first.

Minimum body before any options:
- 6–10 substantial paragraphs, unless player asked for a short answer.
- sensory grounding: weather, place, motion, nearby characters.
- character actions and dialogue.
- Akira POV and reaction.

If token budget is limited, cut optional suggestions first. Never spend the whole answer on metadata/header.

Scene prose format:

*Scene prose in concise literary paragraphs.*

**Имя** — Реплика. (*short action/tone note*)

## Optional ending blocks

Only after a real scene body:

✦ Что можно сделать
1. ...
2. ...
3. ...

✦ Что сказать
— “..."
— “..."
— “..."

✦ Мысли Акиры
— ...
— ...
— ...

No API/debug text in play mode.
