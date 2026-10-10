"""Synthetic component compatibility checks, NOT runtime qualification.

The outer harness verifies and stages the pinned generic source before importing
this module. These checks deliberately do not instantiate RunIO, import campaign
fixtures, relax its CPython guard, or grant device/file/network authority. The
observer below is an explicit in-memory test observer, not a qualified observer.
"""

import copy
import math
import unittest

from cue_readout import LinearReadout, PARAMETER_LIMIT
from decision_restore import ARMS, projection, restore
from hearing_learner import CueLearner, canonical
from hearing_limits import (
    HearingHold, LifetimeLedger, PlasticityError, MAX_QUERIES, MAX_RAW_SAMPLES,
    MAX_SNAPSHOT_BYTES, MAX_STREAM_SAMPLES, MAX_STREAMS, MAX_TEACHINGS, SAMPLE_RATE, WINDOW,
)
from pcm_features import PCMStream, acoustic_features, feature_hash, validate_frame
from raw20_route import RawCueLearner, RawPCMStream, raw_binned20, validate_raw_frame


class ComponentObserver:
    """Records supplied checkpoints; may fail at one declared test boundary."""

    def __init__(self, fail_phase=None, fail_occurrence=1):
        self.events = []
        self.fail_phase = fail_phase
        self.fail_occurrence = fail_occurrence
        self.seen = 0
        self.failure = RuntimeError("synthetic observer refusal")

    def checkpoint(self, phase, counts):
        self.events.append((phase, dict(counts)))
        if phase == self.fail_phase:
            self.seen += 1
            if self.seen == self.fail_occurrence:
                raise self.failure


def tone(hz, samples=WINDOW):
    """Fresh generated PCM, independent of every historical campaign fixture."""
    return tuple(round(11000 * math.sin(2 * math.pi * hz * n / SAMPLE_RATE))
                 for n in range(samples))


def new_ledger(observer=None):
    return LifetimeLedger(observer if observer is not None else ComponentObserver())


def emit(ledger, stream_id, windows, raw=False, chunk=173, start_ns=230000000):
    stream_type = RawPCMStream if raw else PCMStream
    stream = stream_type(ledger, "aster-synthetic-owner", "generated-tone-source",
                         stream_id, start_ns=start_ns)
    samples = tuple(v for window in windows for v in window)
    frames = []
    for start in range(0, len(samples), chunk):
        frames.extend(stream.push(start, samples[start:start + chunk]))
    return frames, stream.close()


def complete_synthetic_arm(arm):
    """Real 7-stream/48-frame history required by the immutable restore schema."""
    raw = arm.startswith("RAW_")
    mode = arm[4:] if raw else arm
    ledger = new_ledger()
    learner = (RawCueLearner if raw else CueLearner)(mode, ledger)
    windows = {-1: tone(625), 1: tone(1375)}
    closes = []
    for block in range(3):
        frames, close = emit(ledger, "synthetic-teach-%d" % block,
                             [windows[-1 if i % 2 == 0 else 1] for i in range(8)], raw)
        closes.append(close)
        for i, frame in enumerate(frames):
            learner.teach(frame, -1 if i % 2 == 0 else 1)
    learner.freeze()
    for block in range(4):
        frames, close = emit(ledger, "synthetic-query-%d" % block,
                             [windows[-1 if i % 2 == 0 else 1] for i in range(6)], raw)
        closes.append(close)
        for frame in frames:
            learner.predict(frame)
    return learner, closes


class PCMComponentCases(unittest.TestCase):
    def test_causal_chunks_and_unpadded_trailing_samples(self):
        for stream_type, validate in ((PCMStream, validate_frame),
                                      (RawPCMStream, validate_raw_frame)):
            with self.subTest(route=stream_type.__name__):
                ledger = new_ledger()
                stream = stream_type(ledger, "owner-a", "source-a", "stream-a", start_ns=12345)
                pcm = tone(625, WINDOW + 37)
                offset = 0
                for count in (1, 127, 128, 255):
                    self.assertEqual(stream.push(offset, pcm[offset:offset + count]), ())
                    offset += count
                    self.assertEqual(len(ledger.frames), 0)
                (frame,) = stream.push(offset, pcm[offset:offset + 1])
                self.assertEqual((frame["start_sample"], frame["end_sample"]), (0, WINDOW))
                self.assertEqual((frame["start_ns"], frame["end_ns"]), (12345, 64012345))
                self.assertEqual(validate(frame, ledger), frame["features"])
                self.assertEqual(stream.push(WINDOW, pcm[WINDOW:]), ())
                self.assertEqual(stream.close(), {
                    "accepted_samples": WINDOW + 37, "completed_frames": 1,
                    "trailing_samples_retained": 37, "runtime_authority": False})
                self.assertEqual(tuple(stream.buffer), pcm[WINDOW:])
                with self.assertRaises(PlasticityError):
                    stream.close()
                with self.assertRaises(PlasticityError):
                    stream.push(WINDOW + 37, (0,))

    def test_chunk_partition_does_not_change_features_or_timestamps(self):
        for raw in (False, True):
            first, _ = emit(new_ledger(), "partition", [tone(625), tone(1375)], raw, chunk=256)
            second, _ = emit(new_ledger(), "partition", [tone(625), tone(1375)], raw, chunk=113)
            self.assertEqual(canonical(first), canonical(second))

    def test_exact_pcm_and_chunk_validation_fails_closed(self):
        malformed = [(0, []), (0, ()), (0, (0,) * 257), (1, (0,)),
                     (True, (0,)), (0, (False,)), (0, (0.0,)),
                     (0, (math.nan,)), (0, (32768,)), (0, (-32769,))]
        for stream_type in (PCMStream, RawPCMStream):
            for start, samples in malformed:
                with self.subTest(route=stream_type.__name__, start=start, samples=repr(samples)[:40]):
                    ledger = new_ledger()
                    stream = stream_type(ledger, "owner", "source", "invalid")
                    with self.assertRaises(HearingHold) as held:
                        stream.push(start, samples)
                    self.assertTrue(stream.failed)
                    self.assertTrue(ledger.failed)
                    self.assertIs(ledger.primary, held.exception.primary)
                    self.assertEqual(held.exception.prefix["accepted_samples"], 0)
                    self.assertEqual(ledger.raw_samples, 0)
                    with self.assertRaises(PlasticityError):
                        stream.push(0, (0,))
                    self.assertIs(ledger.primary, held.exception.primary)
        for function in (acoustic_features, raw_binned20):
            for value in ([0] * WINDOW, (0,) * (WINDOW - 1), (False,) * WINDOW,
                          (32768,) * WINDOW):
                with self.assertRaises(PlasticityError):
                    function(value)
        for rate in (True, 8000.0, 16000):
            with self.assertRaises(PlasticityError):
                PCMStream(new_ledger(), "owner", "source", "rate", sample_rate=rate)
        for owner in ("", "space owner", "nonascii-\u00e9", "x" * 65, 3):
            with self.assertRaises(PlasticityError):
                PCMStream(new_ledger(), owner, "source", "identity")

    def test_gap_and_overlap_retain_accepted_prefix(self):
        for stream_type in (PCMStream, RawPCMStream):
            for bad_start in (0, 2):
                ledger = new_ledger()
                stream = stream_type(ledger, "owner", "source", "prefix")
                stream.push(0, (12,))
                with self.assertRaises(HearingHold) as held:
                    stream.push(bad_start, (34,))
                self.assertEqual(held.exception.prefix["accepted_samples"], 1)
                self.assertEqual(stream.buffer, [12])
                self.assertEqual(ledger.raw_samples, 1)

    def test_observer_failure_retains_completed_frame_and_original_error(self):
        for stream_type, phase in ((PCMStream, "hearing.chunk.after"),
                                   (RawPCMStream, "raw.chunk.after")):
            observer = ComponentObserver(phase, fail_occurrence=2)
            ledger = new_ledger(observer)
            stream = stream_type(ledger, "owner", "source", "failure")
            pcm = tone(625)
            stream.push(0, pcm[:256])
            with self.assertRaises(HearingHold) as held:
                stream.push(256, pcm[256:])
            self.assertIs(held.exception.primary, observer.failure)
            self.assertIs(ledger.primary, observer.failure)
            self.assertEqual(held.exception.prefix["returned_frames"], 1)
            self.assertEqual(held.exception.prefix["accepted_samples"], WINDOW)
            self.assertEqual(len(ledger.frames), 1)
            self.assertFalse(stream.busy)
            with self.assertRaises(PlasticityError):
                ledger.checkpoint("resume")
            self.assertIs(ledger.primary, observer.failure)

    def test_observer_reentry_is_refused_and_retained(self):
        class ReentrantObserver(ComponentObserver):
            stream = None

            def checkpoint(self, phase, counts):
                super().checkpoint(phase, counts)
                self.stream.push(0, (0,))

        for stream_type in (PCMStream, RawPCMStream):
            observer = ReentrantObserver()
            ledger = new_ledger(observer)
            observer.stream = stream_type(ledger, "owner", "source", "reentrant")
            with self.assertRaises(HearingHold) as held:
                observer.stream.push(0, (10,))
            self.assertIs(ledger.primary, held.exception.primary)
            self.assertEqual(observer.stream.accepted, 0)
            self.assertEqual(observer.stream.buffer, [])
            self.assertEqual(ledger.raw_samples, 1)  # Attempt was charged before observer.
            self.assertTrue(observer.stream.failed)
            self.assertFalse(observer.stream.busy)
            with self.assertRaises(PlasticityError):
                ledger.checkpoint("resume")
            self.assertIs(ledger.primary, held.exception.primary)

    def test_forged_frames_rejected_even_when_rehashed(self):
        for raw, validate in ((False, validate_frame), (True, validate_raw_frame)):
            ledger = new_ledger()
            frames, _ = emit(ledger, "genuine", [tone(625)], raw)
            frame = frames[0]
            substitutions = {"owner": "impostor", "source": "impostor", "stream": "missing",
                             "start_sample": 1, "end_sample": 1024, "start_ns": 0,
                             "end_ns": 0, "sample_rate": 16000, "producer": "forged",
                             "runtime_authority": True, "external_ASR_calls": 1,
                             "external_model_calls": 1, "feature_sha256": "0" * 64,
                             "features": list(frame["features"]), "extra": "field"}
            if raw:
                substitutions["rms"] = 0.99
            for key, value in substitutions.items():
                with self.subTest(raw=raw, field=key):
                    forged = dict(frame, **{key: value})
                    with self.assertRaises(PlasticityError):
                        validate(forged, ledger)
            forged = dict(frame, features=(0.125,) * 20)
            forged["feature_sha256"] = feature_hash(forged["features"])
            with self.assertRaisesRegex(PlasticityError, "signature|substitution"):
                validate(forged, ledger)
            self.assertEqual(validate(frame, ledger), frame["features"])

    def test_known_spectral_counter_boolean_alias_is_not_strictly_guarded(self):
        # Characterization of an immutable upstream validation gap, not approval.
        # RAW rejects the same forgery. The harness must report this limitation.
        for raw, validate in ((False, validate_frame), (True, validate_raw_frame)):
            ledger = new_ledger()
            frames, _ = emit(ledger, "counter-types", [tone(625)], raw)
            for alias in (False, 0.0):
                forged = dict(frames[0], external_ASR_calls=alias, external_model_calls=alias)
                if raw:
                    with self.assertRaises(PlasticityError):
                        validate(forged, ledger)
                else:
                    self.assertEqual(validate(forged, ledger), frames[0]["features"])


class LinearReadoutComponentCases(unittest.TestCase):
    def test_parameter_projection_actually_clamps_both_limits(self):
        for direction in (-1, 1):
            snapshot = LinearReadout().snapshot()
            snapshot["weights"][0] = direction * PARAMETER_LIMIT
            snapshot["bias"] = -direction * PARAMETER_LIMIT
            head = LinearReadout.from_snapshot(snapshot)
            head.train((1.0,) + (0.0,) * 19, direction)
            self.assertEqual(head.snapshot()["weights"][0], direction * PARAMETER_LIMIT)
            self.assertAlmostEqual(head.snapshot()["bias"], -direction * 1.95)

    def test_gradient_loss_frozen_prediction_and_update_ceiling(self):
        head = LinearReadout()
        features = (1.0,) + (0.0,) * 19
        first = head.train(features, 1)
        self.assertEqual(first["parameters_computed"], 21)
        self.assertEqual(first["parameters_changed"], 2)
        self.assertLess(first["loss_after"], first["loss_before"])
        self.assertEqual(head.snapshot()["weights"][0], 0.05)
        self.assertEqual(head.snapshot()["bias"], 0.05)
        for i in range(63):
            head.train(features, 1 if i % 2 else -1)
        bounded = head.snapshot()
        self.assertEqual(bounded["updates"], 64)
        self.assertTrue(all(-PARAMETER_LIMIT <= v <= PARAMETER_LIMIT
                            for v in bounded["weights"] + [bounded["bias"]]))
        with self.assertRaisesRegex(PlasticityError, "budget"):
            head.train(features, 1)
        self.assertEqual(head.snapshot(), bounded)
        head.freeze()
        frozen = canonical(head.snapshot())
        for _ in range(4):
            self.assertIn(head.predict(features), (-1, 1))
        with self.assertRaisesRegex(PlasticityError, "frozen"):
            head.train(features, -1)
        self.assertEqual(canonical(head.snapshot()), frozen)
        self.assertEqual(canonical(LinearReadout.from_snapshot(head.snapshot()).snapshot()), frozen)

    def test_readout_rejects_invalid_features_labels_and_snapshots(self):
        head = LinearReadout()
        with self.assertRaises(PlasticityError):
            head.freeze()
        for features in ([0.0] * 20, (0.0,) * 19, (math.nan,) * 20,
                         (math.inf,) * 20, (False,) * 20, (-0.1,) * 20, (1.1,) * 20):
            with self.assertRaises(PlasticityError):
                head.train(features, 1)
        for target in (True, 1.0, 0, 2, "1"):
            with self.assertRaises(PlasticityError):
                head.train((0.5,) * 20, target)
        self.assertEqual(head.snapshot()["updates"], 0)
        original = head.snapshot()
        for key, value in {"extra": 0, "weights": [0.0] * 19, "bias": math.nan,
                           "frozen": 1, "updates": True, "schema": "other"}.items():
            with self.assertRaises(PlasticityError):
                LinearReadout.from_snapshot(dict(original, **{key: value}))
        with self.assertRaises(PlasticityError):
            LinearReadout.from_snapshot(dict(original, frozen=True))


class LearnerComponentCases(unittest.TestCase):
    def test_all_six_arms_complete_and_keep_frozen_decision_parameters(self):
        for arm in ARMS:
            with self.subTest(arm=arm):
                learner, closes = complete_synthetic_arm(arm)
                snapshot = learner.snapshot()
                self.assertEqual(snapshot["lifetime_counts"], {
                    "streams": 7, "frames": 48, "raw_samples": 24576,
                    "teachings": 24, "queries": 24, "runtime_authority": False})
                self.assertEqual(snapshot["head"]["updates"], 24)
                self.assertLessEqual(len(canonical(snapshot)), MAX_SNAPSHOT_BYTES)
                self.assertTrue(snapshot["head"]["frozen"])
                self.assertEqual(len(learner.updates), 24)
                self.assertEqual(len(learner.predictions), 24)
                self.assertEqual(len(closes), 7)
                self.assertTrue(all(c["trailing_samples_retained"] == 0 for c in closes))
                is_learning = arm in ("LEARNED", "RAW_LEARNED")
                self.assertEqual(any(v != 0.0 for v in snapshot["head"]["weights"]), is_learning)
                for index, update in enumerate(learner.updates, 1):
                    self.assertEqual(update["gradient_proposal"]["updates_after"], index)
                    if not is_learning:
                        self.assertEqual(update["parameter_digest_before"], update["parameter_digest_after"])
                if arm in ("FROZEN", "RAW_FROZEN"):
                    self.assertTrue(all(p["answer"] is None and p["abstention"] == "low_margin"
                                        for p in learner.predictions))
                if arm in ("LEARNED", "DSP", "INDEXED"):
                    self.assertEqual([p["answer"] for p in learner.predictions], [-1, 1] * 12)
                before = canonical(projection(snapshot))
                self.assertEqual(len(learner.ledger.frames), 48)
                with self.assertRaises(PlasticityError):
                    learner.teach({}, 1)
                self.assertEqual(canonical(projection(learner.snapshot())), before)

    def test_controls_abstain_on_conflicting_identical_teachings(self):
        for mode, reason in (("DSP", "centroid_ambiguity"),
                             ("INDEXED", "conflicting_nearest_tie")):
            ledger = new_ledger()
            learner = CueLearner(mode, ledger)
            frames, _ = emit(ledger, "ambiguous-controls", [tone(625)])
            learner.teach(frames[0], -1)
            learner.teach(frames[0], 1)
            learner.freeze()
            prediction = learner.predict(frames[0])
            self.assertIsNone(prediction["answer"])
            self.assertEqual(prediction["abstention"], reason)

    def test_observer_failure_after_commit_retains_complete_teaching_or_query(self):
        for raw in (False, True):
            prefix = "raw" if raw else "hearing"
            for operation in ("teaching", "query"):
                observer = ComponentObserver(prefix + "." + operation + ".after")
                ledger = new_ledger(observer)
                learner = (RawCueLearner if raw else CueLearner)("LEARNED", ledger)
                frames, _ = emit(ledger, "commit-failure", [tone(625), tone(1375)], raw)
                if operation == "query":
                    learner.teach(frames[0], -1)
                    learner.teach(frames[1], 1)
                    learner.freeze()
                    before = learner.head.snapshot()
                with self.assertRaises(HearingHold) as held:
                    if operation == "teaching":
                        learner.teach(frames[0], -1)
                    else:
                        learner.predict(frames[0])
                self.assertIs(ledger.primary, observer.failure)
                self.assertIs(held.exception.primary, observer.failure)
                self.assertTrue(learner.failed)
                self.assertFalse(learner.busy)
                if operation == "teaching":
                    self.assertEqual(len(learner.updates), 1)
                    self.assertEqual(held.exception.prefix["updates_completed"], 1)
                    self.assertEqual(learner.head.snapshot()["updates"], 1)
                else:
                    self.assertEqual(len(learner.predictions), 1)
                    self.assertEqual(held.exception.prefix["predictions_completed"], 1)
                    self.assertEqual(learner.head.snapshot(), before)

    def test_spectral_silence_untaught_and_out_of_bank_abstentions(self):
        for arm in ("LEARNED", "FROZEN", "DSP", "INDEXED"):
            learner, _ = complete_synthetic_arm(arm)
            frames, _ = emit(learner.ledger, "novel-synthetic",
                             [(0,) * WINDOW, tone(125), (10000,) * WINDOW])
            before = canonical(projection(learner.snapshot()))
            predictions = [learner.predict(f) for f in frames]
            self.assertEqual([p["abstention"] for p in predictions],
                             ["silent", "untaught_frequency_bin", "non_tonal_or_outside_bank"])
            self.assertTrue(all(p["answer"] is None for p in predictions))
            self.assertEqual(canonical(projection(learner.snapshot())), before)

    def test_failed_teaching_retains_error_without_committing_head(self):
        for raw in (False, True):
            ledger = new_ledger()
            learner = (RawCueLearner if raw else CueLearner)("LEARNED", ledger)
            frames, _ = emit(ledger, "teacher-input", [tone(625)], raw)
            before = learner.head.snapshot()
            with self.assertRaises(HearingHold) as held:
                learner.teach(dict(frames[0], owner="forged-owner"), 1)
            self.assertIs(ledger.primary, held.exception.primary)
            self.assertTrue(learner.failed)
            self.assertEqual(learner.head.snapshot(), before)
            self.assertEqual(ledger.teachings, 0)
            with self.assertRaises(PlasticityError):
                learner.teach(frames[0], 1)
            self.assertIs(ledger.primary, held.exception.primary)

    def test_query_budget_exhaustion_retains_completed_predictions(self):
        for raw in (False, True):
            ledger = new_ledger()
            learner = (RawCueLearner if raw else CueLearner)("LEARNED", ledger)
            frames, _ = emit(ledger, "budget-input", [tone(625), tone(1375)], raw)
            learner.teach(frames[0], -1)
            learner.teach(frames[1], 1)
            learner.freeze()
            before = learner.head.snapshot()
            for _ in range(MAX_QUERIES):
                learner.predict(frames[0])
            with self.assertRaises(HearingHold) as held:
                learner.predict(frames[0])
            self.assertEqual(len(learner.predictions), MAX_QUERIES)
            self.assertEqual(held.exception.prefix["predictions_completed"], MAX_QUERIES)
            self.assertEqual(ledger.queries, MAX_QUERIES + 1)  # Denied attempt is accounted.
            self.assertEqual(learner.head.snapshot(), before)
            self.assertTrue(ledger.failed)

    def test_teaching_budget_and_one_learner_per_ledger(self):
        for raw in (False, True):
            ledger = new_ledger()
            learner_type = RawCueLearner if raw else CueLearner
            learner = learner_type("LEARNED", ledger)
            with self.assertRaises(PlasticityError):
                learner_type("LEARNED", ledger)
            frames, _ = emit(ledger, "teaching-budget", [tone(625)], raw)
            for index in range(MAX_TEACHINGS):
                learner.teach(frames[0], -1 if index % 2 == 0 else 1)
            before = learner.head.snapshot()
            with self.assertRaises(HearingHold):
                learner.teach(frames[0], 1)
            self.assertEqual(len(learner.updates), MAX_TEACHINGS)
            self.assertEqual(ledger.teachings, MAX_TEACHINGS + 1)
            self.assertEqual(learner.head.snapshot(), before)


class SnapshotComponentCases(unittest.TestCase):
    def test_complete_decision_state_restore_and_equivalent_new_queries_all_arms(self):
        for arm in ARMS:
            with self.subTest(arm=arm):
                original, _ = complete_synthetic_arm(arm)
                saved = original.snapshot()
                ledger = new_ledger()
                restored = restore(arm, copy.deepcopy(saved), ledger)
                self.assertEqual(canonical(projection(restored.snapshot())), canonical(projection(saved)))
                self.assertEqual(ledger.counts(), {"streams": 0, "frames": 0, "raw_samples": 0,
                                                  "teachings": 0, "queries": 0, "runtime_authority": False})
                raw = arm.startswith("RAW_")
                frames, _ = emit(ledger, "restored-query", [tone(625), tone(1375)], raw)
                before = canonical(projection(restored.snapshot()))
                for frame, prior in zip(frames, original.predictions[:2]):
                    prediction = restored.predict(frame)
                    for key in ("answer", "abstention", "score", "feature_sha256",
                                "feature_producer", "decision_backend", "runtime_authority"):
                        self.assertEqual(prediction[key], prior[key], key)
                self.assertEqual(canonical(projection(restored.snapshot())), before)
                self.assertEqual(ledger.queries, 2)
                self.assertEqual(ledger.teachings, 0)

    def test_restore_rejects_incomplete_wrong_route_and_altered_history(self):
        for arm in ARMS:
            learner, _ = complete_synthetic_arm(arm)
            saved = learner.snapshot()
            candidates = []
            for key in ("head", "labels_mask", "lifetime_counts"):
                candidate = copy.deepcopy(saved)
                del candidate[key]
                candidates.append(("missing-" + key, candidate))
            for key, value in (("extra", 0), ("schema", "forged"), ("mode", "other"),
                               ("frozen", False), ("failed", True), ("runtime_authority", True),
                               ("labels_mask", True), ("external_ASR_calls", False)):
                candidates.append((key, dict(copy.deepcopy(saved), **{key: value})))
            for field, value in (("updates", 23), ("weights", [0.0] * 19), ("frozen", False)):
                candidate = copy.deepcopy(saved)
                candidate["head"][field] = value
                candidates.append(("head-" + field, candidate))
            candidate = copy.deepcopy(saved)
            candidate["head"]["weights"][0] = 0  # int -> float loses original JSON token.
            candidates.append(("head-integer-token", candidate))
            candidate = copy.deepcopy(saved)
            candidate["lifetime_counts"]["queries"] = 23
            candidates.append(("incomplete-history", candidate))
            for label, candidate in candidates:
                with self.subTest(arm=arm, mutation=label):
                    with self.assertRaises(PlasticityError):
                        restore(arm, candidate, new_ledger())
            wrong_arm = "RAW_LEARNED" if not arm.startswith("RAW_") else "LEARNED"
            with self.assertRaises(PlasticityError):
                restore(wrong_arm, saved, new_ledger())
            used = new_ledger()
            PCMStream(used, "owner", "source", "not-fresh")
            with self.assertRaises(PlasticityError):
                restore(arm, saved, used)

    def test_restore_requires_complete_support_centroids_and_prototypes(self):
        for arm in ("LEARNED", "FROZEN", "DSP", "INDEXED"):
            learner, _ = complete_synthetic_arm(arm)
            saved = learner.snapshot()
            mutations = [("support_mask", 0), ("support_mask", True), ("support_mask", 4096),
                         ("centroids", saved["centroids"][:1]),
                         ("centroids", list(reversed(saved["centroids"])))]
            bad_centroids = copy.deepcopy(saved["centroids"])
            bad_centroids[0][2] = 0  # Upstream requires exact float total.
            mutations.append(("centroids", bad_centroids))
            mutations.append(("prototypes", saved["prototypes"][:-1] if arm == "INDEXED"
                              else [[[0] * 20, 1]]))
            if arm == "INDEXED":
                bad = copy.deepcopy(saved["prototypes"])
                bad[0][0][0] = 256
                mutations.append(("prototypes", bad))
            for field, value in mutations:
                with self.subTest(arm=arm, field=field):
                    with self.assertRaises(PlasticityError):
                        restore(arm, dict(copy.deepcopy(saved), **{field: value}), new_ledger())


class LedgerComponentCases(unittest.TestCase):
    def test_stream_and_frame_ceilings_without_runtime_authority(self):
        for stream_type in (PCMStream, RawPCMStream):
            ledger = new_ledger()
            for index in range(MAX_STREAMS):
                stream = stream_type(ledger, "budget-owner", "budget-source", "bounded-%d" % index)
                chunk = (0,) * 256
                for start in range(0, MAX_STREAM_SAMPLES, 256):
                    stream.push(start, chunk)
                self.assertEqual(stream.accepted, MAX_STREAM_SAMPLES)
                if index == MAX_STREAMS - 1:
                    with self.assertRaises(HearingHold):
                        stream.push(MAX_STREAM_SAMPLES, (0,))
                    self.assertEqual(stream.accepted, MAX_STREAM_SAMPLES)
                else:
                    stream.close()
            self.assertEqual(ledger.raw_samples, MAX_RAW_SAMPLES)
            self.assertEqual(len(ledger.frames), MAX_RAW_SAMPLES // WINDOW)
            self.assertFalse(ledger.counts()["runtime_authority"])
            with self.assertRaises(PlasticityError):
                stream_type(ledger, "budget-owner", "budget-source", "ninth")
        ledger = new_ledger()
        for index in range(MAX_STREAMS):
            PCMStream(ledger, "owner", "source", "empty-%d" % index)
        with self.assertRaises(PlasticityError):
            PCMStream(ledger, "owner", "source", "overflow")
        with self.assertRaises(PlasticityError):
            PCMStream(ledger, "owner", "source", "empty-0")


if __name__ == "__main__":
    unittest.main(verbosity=2)
