# Proposed useful-memory and learning experiments

Restart preservation is a storage/equivalence check. Useful memory must improve held-out performance without introducing false claims.

1. Memory admission: compare no-memory and admitted-memory controls; attach source/time/confidence, retain corrections and reject unsupported or poisoned records.
2. Type-specific retrieval: compare one generic retriever with separate factual, episodic and procedural retrieval; measure relevance, contradiction handling, false-memory following and correction.
3. Question-local event graph: build a bounded graph for the question, retain uncertainty and provenance, then compare it with retrieval-only and no-memory baselines.

Use frozen train/development/held-out splits with answers withheld from the system. Report accuracy, false-memory rate, correction recovery, restart equivalence, storage growth and latency separately. Preserve failed seeds and all prior controls. Any future learning or model change needs its own reviewed experiment and authority; no experiment ran in packaging.
