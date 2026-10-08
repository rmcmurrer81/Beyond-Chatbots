# IdeaForge Simulation

IdeaForge treats simulation as a collection of specialized tests, not a magic proof that an invention works.

The simulation planner can propose:

- **mesh/print fit** — STL integrity and 3D-printer build-volume checks;
- **rigid-body** — gravity, contact and gross motion using PyBullet when a URDF exists;
- **kinematics** — once joints and geometry are defined;
- **structural** — requires load cases/material properties and a suitable solver;
- **thermal/power** — requires component losses, duty cycles and thermal paths;
- **optical/VR** — requires display/optics parameters and specialist modeling;
- **human factors** — requires dimensions, mass distribution and user constraints.

Run:

`python -m simulation.planner projects/<project>`

For a printable STL:

`python -m simulation.mesh_fit path/to/model.stl`

For a URDF after installing PyBullet:

`python -m simulation.pybullet_runner path/to/model.urdf`

Simulation results remain tied to their assumptions and model revision.
