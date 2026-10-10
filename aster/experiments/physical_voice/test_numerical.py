"""Explicit bounded scientific gate, NOT collected by root tests/ discovery.

Run from the repository root:
    python -m experiments.physical_voice.test_numerical --raw-dir /tmp/aster-fold-raw-new --output /tmp/aster-fold-results-new

Pure stdlib; no installs/network/microphone/playback. Both output and raw paths
must be fresh, non-overlapping directories. Existing evidence is never replaced.
Complete integration-rate traces must remain outside the repository.
Raw format: deterministic gzip containing one JSON header line, then little-
endian <10d records (time, pressure, x1,x2,v1,v2,work,loss,full_flow,energy).
All quantities are SI; energy/work/loss are per fold. Header records the plan.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict, replace
import gzip
import hashlib
import json
import math
from pathlib import Path
import platform
import struct
import sys
import time

from .folds import (FoldParameters, FoldStepper, MechanicalState, PressureKnot,
                    PressureSchedule, SAMPLE_RATE, SimulationPlan, WindowMetrics)

ROOT = Path(__file__).resolve().parents[2]
RECORD = struct.Struct('<10d')
MAX_CAMPAIGN_SUBSTEPS = 4_000_000
RAW_BYTE_QUOTA = 400_000_000


def _hash(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1 << 20), b''):
            h.update(block)
    return h.hexdigest()


def cases() -> list[tuple[str, SimulationPlan]]:
    p = FoldParameters()
    result = [(f'nominal_{ss}', SimulationPlan(substeps=ss)) for ss in (2, 4, 8)]
    result += [(f'seed_{name}', SimulationPlan(frames=28_800,initial=MechanicalState(seed,0.)))
               for name, seed in (('negative_nm',-1e-9), ('positive_pm',1e-12), ('positive_um',1e-6))]
    result += [('exact_zero', SimulationPlan(frames=9_600,initial=MechanicalState(0.,0.))),
               ('high_damping', SimulationPlan(frames=28_800,parameters=replace(p,lower_damping_kg_s=.08,upper_damping_kg_s=.08)))]
    contact = MechanicalState(-.0004,-.0003)
    result += [('zero_pressure_decay', SimulationPlan(frames=24_000,initial=contact,pressure=PressureSchedule.constant(0.))),
               ('force_disabled_decay', SimulationPlan(frames=24_000,initial=contact,aerodynamic_force_enabled=False))]
    conservative = replace(p,lower_damping_kg_s=0.,upper_damping_kg_s=0.)
    result += [(f'conservative_contact_{ss}',SimulationPlan(frames=24_000,substeps=ss,parameters=conservative,
                 initial=contact,pressure=PressureSchedule.constant(0.))) for ss in (2,4,8)]
    result += [('pressure_offset',SimulationPlan(pressure=PressureSchedule((PressureKnot(0.,800.),PressureKnot(.6,0.))))),
               ('pressure_ramp_on_off',SimulationPlan(frames=38_400,pressure=PressureSchedule((
                   PressureKnot(0.,0.,'linear'),PressureKnot(.05,800.),PressureKnot(.45,800.,'linear'),PressureKnot(.50,0.)))))]
    for factor in (.5,2.):
        changed = {name:getattr(p,name)*factor for name in (
            'lower_stiffness_n_m','upper_stiffness_n_m','coupling_stiffness_n_m',
            'lower_contact_stiffness_n_m','upper_contact_stiffness_n_m')}
        result.append((f'stiffness_{factor}',SimulationPlan(frames=28_800,parameters=replace(p,**changed))))
    for pressure in (200.,300.):
        result.append((f'constant_pressure_{pressure:g}',SimulationPlan(pressure=PressureSchedule.constant(pressure))))
    result.append(('warm_pressure_sweep',SimulationPlan(frames=96_000,pressure=PressureSchedule(tuple(
        PressureKnot(i*.4,pressure) for i,pressure in enumerate((200.,400.,800.,400.,200.)))))))
    return result


def phase_profile(points: list[tuple[float,float]]) -> list[float]:
    """Mean of complete settled cycles, aligned by interpolated x1 upcrossing."""
    crossings = []
    for i in range(1,len(points)):
        ta,xa = points[i-1]; tb,xb = points[i]
        if xa <= 0 < xb:
            crossings.append(ta+(tb-ta)*(-xa)/(xb-xa))
    bins = 128
    sums = [0.] * bins
    j = 0
    for start,end in zip(crossings,crossings[1:]):
        for k in range(bins):
            target = start+(end-start)*k/bins
            while j+1<len(points) and points[j+1][0]<target:
                j += 1
            ta,xa = points[j]; tb,xb = points[j+1]
            sums[k] += xa+(xb-xa)*(target-ta)/(tb-ta)
    return [x/(len(crossings)-1) for x in sums] if len(crossings)>1 else []


def run_case(name: str, plan: SimulationPlan, raw_dir: Path) -> dict:
    started, cpu_started = time.perf_counter(), time.process_time()
    solver = FoldStepper(plan)
    # All windows are fixed in advance; late always spans the final 0.2 s.
    windows = {'late':(max(0.,plan.duration_s-.2),plan.duration_s)}
    if name=='pressure_offset': windows['on']=(.35,.55)
    if name=='pressure_ramp_on_off': windows['on']=(.25,.4)
    if name=='warm_pressure_sweep':
        windows.update({f'plateau_{i+1}':(i*.4+.3,(i+1)*.4) for i in range(5)})
    meters = {key:WindowMetrics(plan.parameters) for key in windows}
    peaks = [0.] * 5
    previous_energy = solver.snapshot().initial_energy_j_per_fold
    energy_increases = 0
    points = []
    path = raw_dir / f'{name}.bin.gz'
    header = {'format':'aster-original-folds-raw-v1','record':'<10d',
              'fields':['time_s','pressure_pa','lower_displacement_m','upper_displacement_m',
                        'lower_velocity_m_s','upper_velocity_m_s','aero_work_j_per_fold',
                        'damping_loss_j_per_fold','full_flow_m3_s','energy_j_per_fold'],
              'plan':asdict(plan)}
    # Exclusive create avoids overwriting evidence from an earlier run.
    with path.open('xb') as raw:
        with gzip.GzipFile(filename='',mode='wb',fileobj=raw,mtime=0,compresslevel=1) as stream:
            stream.write(json.dumps(header,sort_keys=True,allow_nan=False).encode()+b'\n')
            buffer = bytearray()
            for sample in solver:
                y = sample.mechanics.values()
                buffer.extend(RECORD.pack(sample.time_s,sample.pressure_pa,*y,sample.full_flow_m3_s,sample.energy_j_per_fold))
                if len(buffer)>=80*1024:
                    stream.write(buffer); buffer.clear()
                block=min(4,int(sample.time_s/plan.duration_s*5))
                peaks[block]=max(peaks[block],abs(y[0]))
                energy_increases += sample.energy_j_per_fold > previous_energy+1e-16
                previous_energy = sample.energy_j_per_fold
                for key,(start,end) in windows.items():
                    if start <= sample.time_s <= end: meters[key].observe(sample)
                if name.startswith('nominal_') and sample.time_s>=plan.duration_s-.2:
                    points.append((sample.time_s,y[0]))
            if buffer: stream.write(buffer)
    state=solver.snapshot()
    denominator=state.max_energy_j_per_fold+abs(state.mechanics.aero_work_j_per_fold)+state.mechanics.damping_loss_j_per_fold
    result={'name':name,'plan':asdict(plan),'metrics':{key:meter.summary() for key,meter in meters.items()},
            'final_state':asdict(state),'max_abs_lower_displacement_by_fifths_m':peaks,
            'energy_increase_steps_over_1e_minus_16_j':energy_increases,
            'normalized_max_energy_residual':state.max_energy_residual_j_per_fold/denominator if denominator else 0.,
            'relative_conservative_energy_residual':state.max_energy_residual_j_per_fold/state.initial_energy_j_per_fold if state.initial_energy_j_per_fold else 0.,
            'phase_aligned_lower_profile_m':phase_profile(points) if points else [],
            'raw':{'file':path.name,'sha256':_hash(path),'compressed_bytes':path.stat().st_size,
                   'records':plan.total_substeps,'uncompressed_record_bytes':plan.total_substeps*RECORD.size},
            'wall_seconds':time.perf_counter()-started,'cpu_seconds':time.process_time()-cpu_started}
    print(json.dumps({'case':name,'f0_hz':result['metrics']['late']['f0_hz'],
                      'lower_ptp_m':result['metrics']['late']['lower_ptp_m'],
                      'wall_seconds':result['wall_seconds']},sort_keys=True),flush=True)
    return result


def gates(results: list[dict]) -> dict[str,bool]:
    r={case['name']:case for case in results}
    m=lambda name:r[name]['metrics']['late']
    nominal=m('nominal_8')
    checks={}
    checks['nominal_pressure_sustained_displacement_ac_energy']=(
        130<nominal['f0_hz']<140 and .00075<nominal['lower_ptp_m']<.00087
        and .0008<nominal['upper_ptp_m']<.00090
        and nominal['ac_linear_mechanical_energy_j_per_fold']>1e-6
        and .30<nominal['geometric_closed_fraction']<.38)
    checks['nominal_energy_work_balance']=all(r[f'nominal_{s}']['normalized_max_energy_residual']<2e-6 for s in (2,4,8))
    checks['late_cycle_envelope_stable']=all(
        max(r[f'nominal_{s}']['max_abs_lower_displacement_by_fifths_m'][1:]) /
        min(r[f'nominal_{s}']['max_abs_lower_displacement_by_fifths_m'][1:])<1.002 for s in (2,4,8))
    checks['timestep_frequency_amplitude_convergence']=all(
        abs(m(f'nominal_{s}')['f0_hz']/nominal['f0_hz']-1)<.001
        and abs(m(f'nominal_{s}')['lower_ptp_m']/nominal['lower_ptp_m']-1)<.002 for s in (2,4))
    ref=r['nominal_8']['phase_aligned_lower_profile_m']
    errors={str(s): math.sqrt(sum((a-b)**2 for a,b in zip(r[f'nominal_{s}']['phase_aligned_lower_profile_m'],ref))/len(ref))/nominal['lower_ptp_m'] for s in (2,4)}
    checks['phase_aligned_cycle_convergence']=all(error<.002 for error in errors.values())
    for s in (2,4): r[f'nominal_{s}']['phase_aligned_normalized_rms_error_vs_8']=errors[str(s)]
    checks['varied_once_only_seeds_same_settled_regime']=all(
        abs(m(name)['f0_hz']/nominal['f0_hz']-1)<.002
        and abs(m(name)['lower_ptp_m']/nominal['lower_ptp_m']-1)<.002
        for name in ('seed_negative_nm','seed_positive_pm','seed_positive_um'))
    zero=m('exact_zero')
    checks['exact_zero_stationary_despite_positive_dc_flow']=(zero['lower_ptp_m']==0 and zero['upper_ptp_m']==0
        and zero['ac_linear_mechanical_energy_j_per_fold']==0 and zero['full_flow_ac_rms_m3_s']==0
        and abs(zero['full_flow_mean_m3_s']-2*.014*.00018*math.sqrt(1600/1.2))<1e-18)
    checks['high_damping_decays']=m('high_damping')['lower_ptp_m']<1e-8 and m('high_damping')['ac_linear_mechanical_energy_j_per_fold']<1e-16
    checks['zero_pressure_contact_passive_decay']=r['zero_pressure_decay']['energy_increase_steps_over_1e_minus_16_j']==0 and m('zero_pressure_decay')['lower_ptp_m']<1e-8 and m('zero_pressure_decay')['full_flow_mean_m3_s']==0
    checks['force_disabled_contact_decay_with_dc_flow']=r['force_disabled_decay']['energy_increase_steps_over_1e_minus_16_j']==0 and m('force_disabled_decay')['lower_ptp_m']<1e-8 and m('force_disabled_decay')['full_flow_ac_rms_m3_s']<1e-12 and m('force_disabled_decay')['full_flow_mean_m3_s']>1e-4
    checks['conservative_contact_energy_bounded_and_refines']=all(r[f'conservative_contact_{s}']['relative_conservative_energy_residual']<1e-3 for s in (2,4,8)) and r['conservative_contact_8']['relative_conservative_energy_residual']<r['conservative_contact_2']['relative_conservative_energy_residual']
    checks['pressure_offset_and_ramp_decay']=all(
        r[name]['metrics']['on']['lower_ptp_m']>.0006 and m(name)['lower_ptp_m']<1e-8
        and m(name)['full_flow_mean_m3_s']==0 and m(name)['ac_linear_mechanical_energy_j_per_fold']<1e-16
        for name in ('pressure_offset','pressure_ramp_on_off'))
    checks['stiffness_only_changes_frequency']=90<m('stiffness_0.5')['f0_hz']<110<nominal['f0_hz']<180<m('stiffness_2.0')['f0_hz']<205
    checks['low_pressure_seed_decay_and_above_threshold_growth']=m('constant_pressure_200')['lower_ptp_m']<1e-8 and m('constant_pressure_300')['lower_ptp_m']>.00015
    sweep=r['warm_pressure_sweep']['metrics']
    checks['warm_sweep_uses_continuous_state_without_reseed']=sweep['plateau_1']['lower_ptp_m']<1e-8 and sweep['plateau_3']['lower_ptp_m']>.00075 and sweep['plateau_5']['lower_ptp_m']<sweep['plateau_3']['lower_ptp_m']/100
    return checks


def _fresh_directory(path: Path, label: str) -> Path:
    """Validate before reserving a new directory; never follow supplied symlinks."""
    if not isinstance(path, Path):
        raise ValueError(f'{label} must be a filesystem path')
    absolute = path.expanduser().absolute()
    for component in (absolute, *absolute.parents):
        if component.is_symlink():
            raise ValueError(f'{label} cannot contain a symlink')
    resolved = absolute.resolve()
    if resolved.exists():
        raise ValueError(f'{label} already exists; choose a fresh directory')
    for parent in resolved.parents:
        if parent.exists():
            if not parent.is_dir():
                raise ValueError(f'{label} parent is not a directory')
            break
    return resolved


def prepare_directories(raw_path: Path, output_path: Path) -> tuple[Path, Path]:
    """Validate both destinations, then exclusively reserve each fresh leaf.

    A concurrent reservation fails closed via mkdir(exist_ok=False). If the
    second reservation fails, a newly created empty first directory may remain;
    no existing content is removed or overwritten during cleanup.
    """
    raw_dir = _fresh_directory(raw_path, 'raw directory')
    output_dir = _fresh_directory(output_path, 'output directory')
    if raw_dir == ROOT or ROOT in raw_dir.parents:
        raise ValueError('raw trajectories must stay outside the repository')
    if (raw_dir == output_dir or raw_dir in output_dir.parents
            or output_dir in raw_dir.parents):
        raise ValueError('raw and output directories must not overlap')
    output_dir.mkdir(mode=0o700, parents=True, exist_ok=False)
    raw_dir.mkdir(mode=0o700, parents=True, exist_ok=False)
    return raw_dir, output_dir


def main(argv: list[str] | None = None) -> int:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--raw-dir',type=Path,required=True,help='fresh directory OUTSIDE repository; raw traces stay local')
    parser.add_argument('--output',type=Path,required=True,help='fresh results directory; existing evidence is never overwritten')
    args=parser.parse_args(argv)
    campaign=cases()
    steps=sum(plan.total_substeps for _,plan in campaign)
    if steps>MAX_CAMPAIGN_SUBSTEPS or steps*RECORD.size>RAW_BYTE_QUOTA:
        raise RuntimeError('campaign work/raw-byte quota exceeded')
    try:
        raw_dir, output_dir = prepare_directories(args.raw_dir, args.output)
    except (OSError, RuntimeError, ValueError) as exc:
        parser.error(str(exc))
    started,cpu_started=time.perf_counter(),time.process_time()
    report={'schema':'aster-original-physical-fold-core-gate-v2','python':sys.version,'platform':platform.platform(),
            'receipt_layout':{'directory_policy':'fresh-exclusive-no-clobber',
                              'source_manifest':'run-manifest.json','case_stream':'case-results.jsonl','final_metrics':'metrics.json'},
            'total_substeps':steps,'stage_checks':5*steps,'raw_format':__doc__,
            'sources_sha256':{path.relative_to(ROOT).as_posix():_hash(path) for path in (
                ROOT/'experiments/physical_voice/__init__.py',ROOT/'experiments/physical_voice/folds.py',
                Path(__file__),ROOT/'tests/test_physical_folds.py')},'cases':[],'checks':{},'passed':False}
    with (output_dir/'run-manifest.json').open('x', encoding='utf-8') as manifest_stream:
        manifest_stream.write(json.dumps(report,indent=2,sort_keys=True,allow_nan=False)+'\n')
    # Exclusive opens never truncate a file. Within this newly reserved run,
    # completed cases are appended/flushed once, then final metrics written once.
    with (output_dir/'case-results.jsonl').open('x', encoding='utf-8') as case_stream:
        try:
            for name,plan in campaign:
                result=run_case(name,plan,raw_dir)
                report['cases'].append(result)
                case_stream.write(json.dumps(result,sort_keys=True,allow_nan=False)+'\n')
                case_stream.flush()
            report['checks']=gates(report['cases'])
            report['passed']=all(report['checks'].values())
        except BaseException as exc:
            report['failure']={'type':type(exc).__name__,'message':str(exc)}
            raise
        finally:
            report['wall_seconds']=time.perf_counter()-started
            report['cpu_seconds']=time.process_time()-cpu_started
            with (output_dir/'metrics.json').open('x', encoding='utf-8') as final_stream:
                final_stream.write(json.dumps(report,indent=2,sort_keys=True,allow_nan=False)+'\n')
    print(json.dumps({'passed':report['passed'],'checks':report['checks'],
                      'wall_seconds':report['wall_seconds'],'cpu_seconds':report['cpu_seconds']},indent=2),flush=True)
    return 0 if report['passed'] else 1


if __name__=='__main__':
    raise SystemExit(main())
