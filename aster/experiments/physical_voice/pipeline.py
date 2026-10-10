"""Opt-in finite physical motor-to-PCM pipeline; no runtime brain or devices.

Fold endpoints at 192 kHz -> causal FIR -> 48 kHz normalized oral/nasal tract
-> (lip+nose)/sqrt(2) -> fixed 2.0 FS/sqrt(W) conversion, user attenuation,
10 ms endpoint fades, and a delivery-only 0.20 FS ceiling. No peak normalization.
Mechanical and acoustic energy are separate ledgers, not a combined energy claim.
"""
from dataclasses import asdict, fields
import hashlib
import io
import math
import os
from pathlib import Path
import re
import struct
import sys
import time
import wave

from . import folds, filters, tract
from .protocol import (FS_PER_SQRT_WATT, MAX_MS, PEAK, POSE_KEYS, RATE, SUBSTEPS,
                       VoiceError, canonical, digest, frame_count, is_hash, need,
                       number, parse_json, validate)

ENGINE = 'aster.physical-voice.v1'
MAX_OPERATION_SECONDS = 300.
PCM_LIMIT = int(32767 * PEAK)
# Two root-power outlets are each guarded at100 sqrt(W); their fixed mono sum
# times2 FS/sqrt(W) is below283 FS before the separate delivery ceiling.
MAX_CONVERTED_FS = 300.
FADE_FRAMES = RATE // 100
SMOOTHING_S = .015
POSE_ALPHA = 1. - math.exp(-1. / (RATE * SMOOTHING_S))
SOURCE_FILES = ('__init__.py', 'folds.py', 'filters.py', 'tract.py', 'protocol.py',
                'pipeline.py', 'storage.py', 'bridge.py', 'demo.py')
MOMENT_NAMES = ('filtered_flow_m3_s', 'lip_root_power', 'nose_root_power', 'mono_root_power')
MECHANICAL_KEYS = {'initial_energy_j_per_fold', 'final_energy_j_per_fold',
    'aero_work_j_per_fold', 'damping_loss_j_per_fold', 'final_energy_residual_j_per_fold',
    'max_energy_j_per_fold', 'max_energy_residual_j_per_fold', 'max_abs_displacement_m',
    'max_abs_velocity_m_s', 'max_abs_acceleration_m_s2', 'max_overlap_m'}
WINDOW_KEYS = {'count', 'f0_hz', 'upward_crossings', 'lower_ptp_m', 'upper_ptp_m',
    'lower_ac_rms_m', 'upper_ac_rms_m', 'ac_linear_mechanical_energy_j_per_fold',
    'full_flow_mean_m3_s', 'full_flow_ac_rms_m3_s', 'full_flow_ptp_m3_s',
    'geometric_closed_fraction', 'period_min_s', 'period_max_s'}
ACOUSTIC_KEYS = {'initial_energy_j', 'final_energy_j', 'source_work_j', 'positive_source_work_j',
    'negative_source_work_j', 'propagation_loss_j', 'lip_out_energy_j', 'nose_out_energy_j',
    'max_energy_j', 'max_abs_wave', 'max_abs_boundary_pressure_pa', 'max_abs_source_flow_m3_s',
    'max_abs_lip_root_power', 'max_abs_nose_root_power', 'max_abs_step_residual_j',
    'max_abs_ledger_residual_j', 'final_energy_residual_j'}
MOMENT_KEYS = {'count', 'minimum', 'maximum', 'mean', 'ac_rms', 'rms'}
DELIVERY_KEYS = {'pre_fade_peak_fs', 'pre_limiter_peak_fs', 'limiter_activations',
                 'fixed_fs_per_sqrt_watt', 'gain', 'ceiling_fs', 'fade_frames'}


def _source_hashes():
    root = Path(__file__).parent
    hashes = {name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in SOURCE_FILES}
    # These imported filesystem helpers are part of the exact file interface.
    lab = root.parent / 'newbrain_text'
    for name in ('persistence.py', 'curriculum.py'):
        hashes['newbrain_text/' + name] = hashlib.sha256((lab / name).read_bytes()).hexdigest()
    return hashes


_IMPORTED_SOURCE_HASHES = _source_hashes()


def engine_binding():
    hashes = _source_hashes()
    need(hashes == _IMPORTED_SOURCE_HASHES, 'implementation_changed_during_process')
    # Avoid platform.system/machine: they may launch a hostname/network probe on Windows.
    machine = os.uname().machine if hasattr(os, 'uname') else str(struct.calcsize('P') * 8) + 'bit'
    return {'engine': ENGINE, 'source_files': hashes, 'source_sha256': digest(hashes),
            'runtime': {'python': '.'.join(str(x) for x in sys.version_info[:3]),
                        'implementation': sys.implementation.name, 'system': sys.platform,
                        'machine': machine, 'byteorder': sys.byteorder, 'word_bits': struct.calcsize('P') * 8}}


def validate_binding(binding):
    need(type(binding) is dict and set(binding) == {'engine', 'source_files', 'source_sha256', 'runtime'}
         and binding['engine'] == ENGINE, 'checkpoint_engine_refused')
    hashes = binding['source_files']
    need(type(hashes) is dict and set(hashes) == {*SOURCE_FILES, 'newbrain_text/persistence.py',
         'newbrain_text/curriculum.py'} and all(is_hash(value) for value in hashes.values())
         and binding['source_sha256'] == digest(hashes), 'checkpoint_sources_refused')
    runtime = binding['runtime']
    need(type(runtime) is dict and set(runtime) == {'python', 'implementation', 'system', 'machine',
         'byteorder', 'word_bits'} and runtime['byteorder'] in ('little', 'big')
         and type(runtime['word_bits']) is int and runtime['word_bits'] in (32, 64)
         and all(type(runtime[k]) is str and re.fullmatch(r'[A-Za-z0-9_.+-]{1,64}', runtime[k]) is not None
                 for k in ('python', 'implementation', 'system', 'machine')), 'checkpoint_runtime_refused')


def mechanical_plan(plan):
    source, frames = plan['source'], frame_count(plan)
    scale = source['stiffness_scale']
    parameters = folds.FoldParameters(lower_stiffness_n_m=80. * scale,
        upper_stiffness_n_m=8. * scale, coupling_stiffness_n_m=25. * scale,
        lower_contact_stiffness_n_m=240. * scale, upper_contact_stiffness_n_m=24. * scale,
        lower_damping_kg_s=source['damping_kg_s'], upper_damping_kg_s=source['damping_kg_s'],
        lower_rest_half_gap_m=source['rest_half_gap_m'], upper_rest_half_gap_m=source['rest_half_gap_m'])
    # Pressure is evaluated by the core at all RK stages. Parameters never change.
    duration = frames / RATE
    pressure = folds.PressureSchedule((folds.PressureKnot(0., 0., 'linear'),
        folds.PressureKnot(.015, source['pressure_pa'], 'hold'),
        folds.PressureKnot(duration - .025, source['pressure_pa'], 'linear'),
        folds.PressureKnot(duration, 0.)))
    return folds.SimulationPlan(frames=frames, substeps=SUBSTEPS, parameters=parameters,
                                pressure=pressure, initial=folds.MechanicalState())


def tract_config(plan):
    return tract.TractConfig(velum_opening=plan['velum'],
                            guards=tract.TractGuards(max_frames=frame_count(plan)))


def filter_config(plan):
    return filters.DecimatorConfig(oversample=SUBSTEPS, max_input_samples=frame_count(plan) * SUBSTEPS)


def timing():
    return {'mechanical_integration_rate': RATE * SUBSTEPS,
            'first_source_endpoint_time_s': 1. / (RATE * SUBSTEPS),
            'retained_raw_stream_first_index': 0, 'retained_raw_stream_stride': SUBSTEPS,
            'fir_taps': 36 * SUBSTEPS + 1, 'fir_delay_frames': 18, 'fir_delay_s': 18. / RATE,
            'delay_trimmed': False, 'zero_tail_flushed': False,
            'oral_one_way_delay_frames': 24, 'nasal_source_outlet_delay_frames': 28,
            'pose_smoothing_time_s': SMOOTHING_S, 'pressure_onset_s': .015, 'pressure_release_s': .025}


def _closed(cls, data):
    need(type(data) is dict and set(data) == {f.name for f in fields(cls)}, 'checkpoint_component_schema_refused')
    return dict(data)


def _decode_components(plan, state):
    """Validate and restore data structures without stepping any simulation."""
    mp = mechanical_plan(plan)
    saved = _closed(folds.StepperState, state['folds'])
    need(canonical(saved.pop('plan')) == canonical(asdict(mp)), 'checkpoint_mechanical_plan_mismatch')
    saved['mechanics'] = folds.MechanicalState(**_closed(folds.MechanicalState, saved['mechanics']))
    mechanical = folds.FoldStepper(mp, folds.StepperState(plan=mp, **saved))
    saved = _closed(folds.WindowState, state['window'])
    need(canonical(saved.pop('parameters')) == canonical(asdict(mp.parameters)), 'checkpoint_window_parameters_mismatch')
    need(type(saved['moments']) is list and len(saved['moments']) == 6, 'checkpoint_window_extent_refused')
    saved['moments'] = tuple(folds.MomentsState(**_closed(folds.MomentsState, item)) for item in saved['moments'])
    window = folds.WindowMetrics(mp.parameters, folds.WindowState(parameters=mp.parameters, **saved))
    saved = _closed(filters.DecimatorCheckpoint, state['filter'])
    fc = filter_config(plan)
    need(canonical(saved.pop('config')) == canonical(asdict(fc)), 'checkpoint_filter_config_mismatch')
    need(type(saved['ring']) is list and len(saved['ring']) == fc.tap_count, 'checkpoint_filter_extent_refused')
    saved['ring'] = tuple(saved['ring'])
    decimator = filters.FlowDecimator.from_checkpoint(filters.DecimatorCheckpoint(config=fc, **saved))
    saved = _closed(tract.TractState, state['tract'])
    tc = tract_config(plan)
    need(canonical(saved.pop('config')) == canonical(asdict(tc)), 'checkpoint_tract_config_mismatch')
    saved['articulation'] = tract.Articulation(**_closed(tract.Articulation, saved['articulation']))
    waves = _closed(tract.TractWaves, saved['waves'])
    for key in ('oral_forward', 'oral_backward', 'nasal_forward', 'nasal_backward'):
        need(type(waves[key]) is list and len(waves[key]) == (24 if key.startswith('oral') else 16),
             'checkpoint_tract_extent_refused')
        waves[key] = tuple(waves[key])
    saved['waves'] = tract.TractWaves(**waves)
    tube = tract.OralNasalTract.from_checkpoint(tract.TractState(config=tc, **saved))
    need(type(state['moments']) is dict and set(state['moments']) == set(MOMENT_NAMES),
         'checkpoint_moments_refused')
    moments = {key: folds.Moments(folds.MomentsState(**_closed(folds.MomentsState, value)))
               for key, value in state['moments'].items()}
    cursor = state['cursor']
    need(mechanical.snapshot().substep_index == decimator.input_samples == cursor * SUBSTEPS
         and decimator.output_samples == tube.checkpoint().sample_index == cursor
         and window.snapshot().moments[0].count == cursor * SUBSTEPS
         and all(item.count == cursor for item in moments.values()), 'checkpoint_progress_mismatch')
    need(window.previous_time_s == (cursor / RATE if cursor else None), 'checkpoint_window_time_mismatch')
    endpoint = folds.evaluate(mechanical.snapshot().mechanics, mp.parameters, mp.guards, mp.pressure.at(cursor / RATE))
    if cursor:
        need(window.previous_x1_m == mechanical.snapshot().mechanics.lower_displacement_m
             and state['filter']['ring'][(state['filter']['next_index'] - 1) % fc.tap_count] == endpoint.full_flow_m3_s,
             'checkpoint_last_source_mismatch')
    acoustic = tube.checkpoint()
    need(acoustic.initial_energy_j == 0., 'checkpoint_acoustic_preload_refused')
    for name, maximum in (('filtered_flow_m3_s', acoustic.max_abs_source_flow_m3_s),
                          ('lip_root_power', acoustic.max_abs_lip_root_power),
                          ('nose_root_power', acoustic.max_abs_nose_root_power)):
        need(max(abs(moments[name].minimum), abs(moments[name].maximum)) == maximum,
             'checkpoint_raw_extrema_mismatch')
    mono_peak = max(abs(moments['mono_root_power'].minimum), abs(moments['mono_root_power'].maximum))
    need(state['pre_fade_peak_fs'] == mono_peak * FS_PER_SQRT_WATT * plan['delivery_gain']
         and bool(state['limiter_activations']) == (state['pre_limiter_peak_fs'] > PEAK),
         'checkpoint_delivery_extrema_mismatch')
    need(type(state['pose']) is dict and set(state['pose']) == set(POSE_KEYS)
         and all(number(value, 0., 1.) for value in state['pose'].values())
         and canonical(state['pose']) == canonical(asdict(tube.checkpoint().articulation)),
         'checkpoint_pose_mismatch')
    return mechanical, window, decimator, tube, moments


def validate_checkpoint(plan, checkpoint):
    """Closed data/state/ledger checks only; no synthesis, brain, or device use."""
    plan = validate(plan)
    need(type(checkpoint) is dict and set(checkpoint) == {'state', 'sha256'}, 'checkpoint_envelope_refused')
    state = checkpoint['state']
    need(type(state) is dict and set(state) == {'schema', 'owner', 'intent_sha256', 'binding', 'cursor',
         'folds', 'window', 'filter', 'tract', 'pose', 'moments', 'pre_fade_peak_fs',
         'pre_limiter_peak_fs', 'limiter_activations'} and checkpoint['sha256'] == digest(state),
         'checkpoint_digest_mismatch')
    validate_binding(state['binding'])
    need(state['schema'] == 'aster.physical-voice-checkpoint.v1' and state['owner'] == plan['owner']
         and state['intent_sha256'] == digest(plan), 'checkpoint_binding_mismatch')
    need(type(state['cursor']) is int and 0 <= state['cursor'] <= frame_count(plan), 'checkpoint_cursor_refused')
    need(number(state['pre_fade_peak_fs'], 0., MAX_CONVERTED_FS) and number(state['pre_limiter_peak_fs'], 0., MAX_CONVERTED_FS)
         and state['pre_limiter_peak_fs'] <= state['pre_fade_peak_fs']
         and type(state['limiter_activations']) is int and 0 <= state['limiter_activations'] <= state['cursor'],
         'checkpoint_delivery_refused')
    try:
        _decode_components(plan, state)
    except (folds.FoldError, filters.FilterError, tract.TractError, TypeError, KeyError, OverflowError) as exc:
        raise VoiceError('checkpoint_components_refused') from exc
    return parse_json(canonical(state), 65536)


class PhysicalVoice:
    """Finite renderer; all state including metrics is resumable on the bound runtime.

    If a component fails midway through a frame, this renderer is poisoned and
    cannot emit further PCM or a checkpoint. Export is aborted, never truncated.
    """
    def __init__(self, plan, owner=None, deadline=None):
        self._plan = validate(plan, owner)
        self._binding = engine_binding()
        self._deadline = time.monotonic() + MAX_OPERATION_SECONDS if deadline is None else deadline
        self.frames, self.cursor = frame_count(self._plan), 0
        self._mechanical = folds.FoldStepper(mechanical_plan(self._plan))
        self._window = folds.WindowMetrics(self._mechanical.plan.parameters)
        self._filter = filters.FlowDecimator(filter_config(self._plan))
        self._pose = dict(self._plan['gestures'][0]['pose'])
        self._tract = tract.OralNasalTract(tract_config(self._plan), articulation=tract.Articulation(**self._pose))
        self._moments = {key: folds.Moments() for key in MOMENT_NAMES}
        self.pre_fade_peak_fs = self.pre_limiter_peak_fs = 0.
        self.limiter_activations = 0
        self._failed = False
        self._schedule = []
        end = 0
        for gesture in self._plan['gestures']:
            end += gesture['duration_ms'] * (RATE // 1000)
            self._schedule.append((end, gesture['pose']))

    @property
    def binding(self):
        return parse_json(canonical(self._binding))

    @property
    def plan(self):
        return validate(self._plan)

    def checkpoint(self):
        need(not self._failed, 'renderer_failed')
        state = {'schema': 'aster.physical-voice-checkpoint.v1', 'owner': self._plan['owner'],
                 'intent_sha256': digest(self._plan), 'binding': self.binding, 'cursor': self.cursor,
                 'folds': asdict(self._mechanical.snapshot()), 'window': asdict(self._window.snapshot()),
                 'filter': asdict(self._filter.checkpoint()), 'tract': asdict(self._tract.checkpoint()),
                 'pose': dict(self._pose), 'moments': {key: asdict(value.snapshot()) for key, value in self._moments.items()},
                 'pre_fade_peak_fs': self.pre_fade_peak_fs, 'pre_limiter_peak_fs': self.pre_limiter_peak_fs,
                 'limiter_activations': self.limiter_activations}
        # Detach every list/dictionary; callers must not mutate bound renderer data.
        state = parse_json(canonical(state), 65536)
        return {'state': state, 'sha256': digest(state)}

    @classmethod
    def restore(cls, plan, checkpoint, owner, deadline=None):
        box = cls(plan, owner, deadline)
        state = validate_checkpoint(box._plan, checkpoint)
        need(state['binding'] == box.binding, 'checkpoint_engine_runtime_mismatch')
        (box._mechanical, box._window, box._filter, box._tract,
         box._moments) = _decode_components(box._plan, state)
        box.cursor, box._pose = state['cursor'], dict(state['pose'])
        box.pre_fade_peak_fs = state['pre_fade_peak_fs']
        box.pre_limiter_peak_fs = state['pre_limiter_peak_fs']
        box.limiter_activations = state['limiter_activations']
        return box

    def render_frames(self, count):
        need(not self._failed, 'renderer_failed')
        need(type(count) is int and 0 <= count <= RATE * MAX_MS // 1000, 'frame_request_refused')
        end = min(self.frames, self.cursor + count)
        output = bytearray()
        try:
            while self.cursor < end:
                if self.cursor % 256 == 0:
                    need(time.monotonic() <= self._deadline, 'render_runtime_quota')
                filtered = None
                for _ in range(SUBSTEPS):
                    raw = self._mechanical.step_substep()
                    self._window.observe(raw)
                    value = self._filter.push(raw.full_flow_m3_s)
                    if value is not None:
                        need(filtered is None, 'decimation_progress_mismatch')
                        filtered = value
                need(filtered is not None, 'decimation_progress_mismatch')
                target = next(pose for stop, pose in self._schedule if self.cursor < stop)
                self._pose = {key: self._pose[key] + POSE_ALPHA * (target[key] - self._pose[key]) for key in POSE_KEYS}
                sample = self._tract.step(filtered, tract.Articulation(**self._pose))
                mono = (sample.lip_root_power + sample.nose_root_power) / math.sqrt(2.)
                for key, value in zip(MOMENT_NAMES, (filtered, sample.lip_root_power, sample.nose_root_power, mono)):
                    self._moments[key].add(value)
                scaled = mono * FS_PER_SQRT_WATT * self._plan['delivery_gain']
                self.pre_fade_peak_fs = max(self.pre_fade_peak_fs, abs(scaled))
                envelope = min(1., self.cursor / FADE_FRAMES, (self.frames - 1 - self.cursor) / FADE_FRAMES)
                delivered = scaled * envelope
                self.pre_limiter_peak_fs = max(self.pre_limiter_peak_fs, abs(delivered))
                self.limiter_activations += int(abs(delivered) > PEAK)
                # This ceiling affects only output delivery, never physical states.
                delivered = max(-PEAK, min(PEAK, delivered))
                pcm = int(round(delivered * 32767.))
                need(abs(pcm) <= PCM_LIMIT, 'pcm_ceiling_refused')
                output.extend(struct.pack('<h', pcm))
                self.cursor += 1
        except (Exception, KeyboardInterrupt):
            self._failed = True
            raise
        return bytes(output)

    def diagnostics(self):
        need(not self._failed, 'renderer_failed')
        state = self._mechanical.snapshot()
        final = folds.evaluate(state.mechanics, state.plan.parameters, state.plan.guards,
                               state.plan.pressure.at(self.cursor / RATE))
        mechanical = {key: getattr(state, key) for key in MECHANICAL_KEYS if hasattr(state, key)}
        mechanical.update(final_energy_j_per_fold=final.energy_j_per_fold,
            aero_work_j_per_fold=state.mechanics.aero_work_j_per_fold,
            damping_loss_j_per_fold=state.mechanics.damping_loss_j_per_fold,
            final_energy_residual_j_per_fold=final.energy_j_per_fold - state.initial_energy_j_per_fold
                - state.mechanics.aero_work_j_per_fold + state.mechanics.damping_loss_j_per_fold)
        acoustic_state = self._tract.checkpoint()
        acoustic = {key: getattr(acoustic_state, key) for key in ACOUSTIC_KEYS if hasattr(acoustic_state, key)}
        acoustic.update(final_energy_j=acoustic_state.energy_j, final_energy_residual_j=acoustic_state.energy_residual_j)
        moments = {key: {'count': m.count, 'minimum': m.minimum, 'maximum': m.maximum, 'mean': m.mean,
                        'ac_rms': math.sqrt(m.variance), 'rms': math.sqrt(m.variance + m.mean * m.mean)}
                   for key, m in self._moments.items()}
        return {'frames': self.cursor, 'mechanical_per_fold': mechanical, 'mechanical_window_all_endpoints': self._window.summary(),
                'acoustic': acoustic, 'raw_signals': moments, 'delivery': {
                    'pre_fade_peak_fs': self.pre_fade_peak_fs, 'pre_limiter_peak_fs': self.pre_limiter_peak_fs,
                    'limiter_activations': self.limiter_activations, 'fixed_fs_per_sqrt_watt': FS_PER_SQRT_WATT,
                    'gain': self._plan['delivery_gain'], 'ceiling_fs': PEAK, 'fade_frames': FADE_FRAMES}}


def validate_diagnostics(value, plan):
    """Validate stored metric shape/bounds, never claim their physics was rerun."""
    need(type(value) is dict and set(value) == {'frames', 'mechanical_per_fold',
        'mechanical_window_all_endpoints', 'acoustic', 'raw_signals', 'delivery'}
        and type(value['frames']) is int and value['frames'] == frame_count(plan), 'diagnostics_schema_refused')
    for key, keys in (('mechanical_per_fold', MECHANICAL_KEYS), ('mechanical_window_all_endpoints', WINDOW_KEYS),
                       ('acoustic', ACOUSTIC_KEYS), ('delivery', DELIVERY_KEYS)):
        part = value[key]
        need(type(part) is dict and set(part) == keys
             and all(number(item, -1e9, 1e9) for item in part.values()), 'diagnostics_scalars_refused')
    signals = value['raw_signals']
    need(type(signals) is dict and set(signals) == set(MOMENT_NAMES), 'diagnostics_signals_refused')
    for part in signals.values():
        need(type(part) is dict and set(part) == MOMENT_KEYS and type(part['count']) is int
             and part['count'] == frame_count(plan) and all(number(v, -1e9, 1e9) for v in part.values())
             and part['minimum'] <= part['mean'] <= part['maximum']
             and 0 <= part['ac_rms'] <= part['rms'], 'diagnostics_moments_refused')
    window, delivery = value['mechanical_window_all_endpoints'], value['delivery']
    need(type(window['count']) is int and window['count'] == frame_count(plan) * SUBSTEPS
         and type(window['upward_crossings']) is int and 0 <= window['upward_crossings'] <= window['count']
         and 0. <= window['geometric_closed_fraction'] <= 1., 'diagnostics_window_refused')
    need(type(delivery['limiter_activations']) is int and 0 <= delivery['limiter_activations'] <= frame_count(plan)
         and 0. <= delivery['pre_limiter_peak_fs'] <= delivery['pre_fade_peak_fs'] <= MAX_CONVERTED_FS
         and delivery['fixed_fs_per_sqrt_watt'] == FS_PER_SQRT_WATT and delivery['gain'] == plan['delivery_gain']
         and delivery['ceiling_fs'] == PEAK and type(delivery['fade_frames']) is int
         and delivery['fade_frames'] == FADE_FRAMES, 'diagnostics_delivery_refused')


def render(plan):
    box = PhysicalVoice(plan)
    return box.render_frames(box.frames)


def measurements(pcm):
    need(type(pcm) is bytes and 0 < len(pcm) <= RATE * MAX_MS // 1000 * 2 and len(pcm) % 2 == 0,
         'pcm_extent_refused')
    values = [item[0] for item in struct.iter_unpack('<h', pcm)]
    peak = max(abs(value) for value in values)
    return {'frames': len(values), 'duration_s': len(values) / RATE, 'sample_rate': RATE,
            'channels': 1, 'sample_width_bytes': 2, 'peak_pcm': peak, 'peak_fs': peak / 32767.,
            'peak_dbfs': 20. * math.log10(peak / 32767.) if peak else None,
            'rms_fs': math.sqrt(math.fsum(value * value for value in values) / len(values)) / 32767.,
            'mean_fs': math.fsum(values) / len(values) / 32767.,
            'nonzero_samples': sum(value != 0 for value in values),
            'full_scale_clipped_samples': sum(abs(value) >= 32767 for value in values),
            'within_delivery_ceiling': peak <= PCM_LIMIT, 'first_sample': values[0], 'last_sample': values[-1]}


def wav_bytes(pcm):
    measurements(pcm)
    result = io.BytesIO()
    with wave.open(result, 'wb') as stream:
        stream.setnchannels(1); stream.setsampwidth(2); stream.setframerate(RATE)
        stream.writeframes(pcm)
    return result.getvalue()
