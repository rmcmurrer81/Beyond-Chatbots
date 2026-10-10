# Requirements and reproducibility limits

The NewBrain starter and its retained tests use Python's standard library. The routing/state numerical references also import NumPy. No dependency version or cross-platform reproduction has been established for this new package.

Avatar Builder and Body Prototype contain reference libraries. Their caller, selected asset/dependency closure and separately accepted native runtime are not included. Some functions expect externally supplied Blender/native objects. Do not treat these folders as standalone applications.

Aster and IdeaForge requirements must remain those of the exact incoming upstream snapshot; that source handoff is pending. No dependency installation, import, tests or runtime execution occurred while preparing this package.

Full component terms and current restrictions are in LICENSE-STATUS.md. There is no package-wide permissive-license grant.
