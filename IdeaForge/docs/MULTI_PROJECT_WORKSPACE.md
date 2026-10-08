# Multi-Project Workspace

IdeaForge is designed to let several invention projects coexist.

## Spoken project commands

You can say:

- "show my projects"
- "close this project"
- "open my R2-D2 project"
- "start another project"
- "start a new project for Alpha 5"
- "research this project"
- "use variant 2"
- "use image 4"

Closing a project means closing it from the current workspace view. It does **not** cancel queued/running research.

Background research continues while IdeaForge is running. If IdeaForge is closed during a queued/running job, the project state is saved and the job is queued again on the next launch.

## Workspace layout

The main window has three areas:

### Projects
Shows each project, whether it is open/closed in the workspace, and research status.

### Conversation
Typed and hands-free conversation.

### Project Details & References
Shows:
- current project summary;
- visual target;
- build-type options;
- subsystem list;
- research status;
- detected reference/design variants;
- selected reference;
- downloaded local reference thumbnails.

## Character / prop / franchise builds

If the idea is based on a visually specific target, the project plan can store:

- `visual_reference_target`
- `reference_selection_expected`
- `build_type_options`

Research prioritizes the visual target and builds a local reference gallery.

If metadata suggests multiple versions/designs, IdeaForge creates a variant list. You can choose by voice/text or press **Use this** under a reference image.

The choice is saved in:

`design/selected_reference.json`

Prototype planning reads that file so later fabrication work follows the chosen look instead of mixing unrelated versions.

## Research status

Project research state is saved in:

`workspace_state.json`

Typical states:
- idle
- queued
- running
- complete
- error

This state is visible in the left project list.
