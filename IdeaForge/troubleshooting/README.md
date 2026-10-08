# IdeaForge Troubleshooting

Troubleshooting is project-aware.

You can report a problem in ordinary language:

- "the 3D print keeps warping at the corners"
- "this bracket binds when I rotate the joint"
- "the display says error E07"
- "the motor jitters but does not turn"
- "the enclosure STL is too large for my printer"
- "the program crashes when I press Prototype"

You can also attach a photo or screenshot.

IdeaForge combines:

- your problem description;
- the current project's saved design/memory/research/fabrication/simulation files;
- visual evidence from Qwen3-VL when an image is attached;
- fresh web searches;
- relevant equipment/model information.

Each diagnostic session is saved under:

`projects/<project>/troubleshooting/`

The report separates observed facts from hypotheses, checks and possible fixes. Follow-up statements such as "that didn't work" or "that fixed it" are saved to the active incident so IdeaForge can avoid repeating unsuccessful steps and retain the eventual solution.
