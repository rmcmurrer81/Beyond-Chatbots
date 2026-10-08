# IdeaForge Fabrication

IdeaForge can generate real STL files when the part fits a supported parametric generator and the necessary dimensions are known.

Initial supported workflow:

- record the exact 3D printer model in **My Equipment**;
- research/store its build-volume and relevant capabilities;
- create a prototype plan;
- generate supported simple geometry such as an enclosure;
- render STL with OpenSCAD when OpenSCAD is installed;
- check mesh dimensions and whether the STL fits the stored printer build volume.

## Enclosures

Create an enclosure JSON using `fabrication/enclosure.schema.json`, then run:

`python -m fabrication.enclosure path/to/enclosure.json`

IdeaForge always writes the editable `.scad` files. If the `openscad` executable is available, it also exports `.stl`.

## Why not generate arbitrary final CAD immediately?

A language model can describe shapes but should not invent critical dimensions or pretend an arbitrary free-form mesh is fabrication-ready. Complex mechanisms use `custom_cad` until enough verified geometry exists for a proper CAD pipeline.

Prototype geometry should be validated against the actual printer and tested physically before being treated as a final component.
