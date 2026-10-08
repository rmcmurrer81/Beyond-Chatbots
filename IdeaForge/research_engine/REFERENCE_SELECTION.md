# Reference and Variant Selection

For projects based on a character, prop, costume, robot, vehicle, device, or other visually specific target, IdeaForge can create a reference gallery after research.

The gallery is stored in:

`projects/<project>/research/gallery.json`

with local thumbnails under:

`projects/<project>/research/gallery/`

If the metadata suggests multiple design variants, IdeaForge creates:

`reference_variants.json`

The user can choose a target by saying things like:

- "use variant 2"
- "I want reference image 4"
- "use the first design"

The choice is saved under:

`design/selected_reference.json`

Later design/prototype work should use the selected reference rather than mixing unrelated visual versions.
