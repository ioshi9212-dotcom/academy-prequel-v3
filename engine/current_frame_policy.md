# Current Frame Policy

The scene header and visible frame must be built from current_state/current_frame only.

Use the current date, time, location, weather, visible outfit, visible inventory, nearby/active characters and POV state.

Hard visible-canon rule:
- Do not invent or replace clothing, colors, shoes, hairstyle, accessories, injuries, tools, weapons, sports gear or nearby items.
- If current_state says Akira wears sneakers, black cargo pants, top, burgundy hoodie, output exactly that meaning. Never rewrite it as sweater, white sweater, trousers, jeans, skirt, uniform, dress, sports shoes, boots, jacket of another color, or Academy uniform.
- Do not mention outfit at all if you are not sure. Silence is better than invented clothing.
- Do not invent uniform until uniform_worn=true or the player explicitly changes clothes.
- Do not invent energy effects, wet/dry ground, blood, bruises, weapons, rings, gloves, boxing gloves or props unless state/scene contract supports them.

If a player action changes the frame, save it through state changes after the scene.
