Inactive body nerve feedback nomination

body_nerve_feedback.py implements an inactive deterministic feedback boundary
for one independently owned subject, model owner, body instance, rig and
interface revision. It performs no native IO, actuation or model binding.

Sensor routes carry region, modality, unit, spatial frame, monotonic clock,
producer and calibration commitments, measurement kind and finite range.
Contact, joint angle and surface displacement retain their observed geometric
scope. Force, pressure and temperature require their own distinct producer
and calibration provenance. Route registration alone does not authenticate
a native producer or establish physical calibration.

Unknown and error channels retain absent measurements. Disconnected,
mismatched, stale, duplicate, sham and out-of-range packets are refused.
No-contact observations do not generate force or pressure. Motor requests
are bounded and retained separately; recording one reports no observed motion.
Complete bounded histories remain available through immutable snapshots.

BodyQualificationOrder retains external review commitments and enforces
rest persistence, basis equivalence, then blink/breathing before stretch or
finger movement. Only separately authenticated actual independent reviews
can supply those receipts. A newer failed result removes that stage from
current progression. The helper does not execute any of those body tests.

Synthetic fixture controls qualify the interface boundary only. They do not
qualify biological nerves, realistic skin, native contact/physics, physiology,
subjective sensation, a live model/body connection, body readiness or birth.

Qualification is transitive across every upstream prerequisite. Each current
child review must be newer than its current prerequisite reviews. A failed or
freshly reaccepted rest/basis result invalidates older blink, breathing and
downstream observations until they are observed and reviewed in the new epoch.
