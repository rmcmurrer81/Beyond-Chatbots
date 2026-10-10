"""Fast, offline contracts for opt-in SI folds. Long gates are explicitly invoked.

python -m unittest discover -s tests -p test_physical_folds.py -v
python -m experiments.physical_voice.test_numerical --raw-dir /tmp/aster-fold-raw-new --output /tmp/aster-fold-results-new
"""
from dataclasses import replace
from decimal import Decimal, localcontext
import itertools
import contextlib
import hashlib
import io
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import math
import unittest
from unittest.mock import patch

from experiments.physical_voice import folds as f
from experiments.physical_voice import test_numerical as campaign


class PhysicalFoldContractTests(unittest.TestCase):
    def test_published_defaults_and_pair_accounting(self):
        p = f.FoldParameters()
        self.assertEqual((p.lower_mass_kg, p.upper_mass_kg), (1.25e-4, 2.5e-5))
        self.assertEqual((p.lower_stiffness_n_m, p.upper_stiffness_n_m, p.coupling_stiffness_n_m), (80, 8, 25))
        self.assertEqual(f.PAIR_FACTOR, 2)
        s = f.MechanicalState(0., 0.)
        e = f.evaluate(s)
        self.assertEqual(e.derivative, (0.,) * 6)
        self.assertEqual(e.energy_j_per_fold, 0.)
        self.assertAlmostEqual(e.full_flow_m3_s, 2 * .014 * .00018 * math.sqrt(1600 / 1.2))

    def test_pressure_branches(self):
        p = f.FoldParameters()
        for h1, h2, fraction in ((-.0001, -.0002, 0.), (.0001, -.0001, 1.),
                                (.0001, .0001, 0.), (.0001, .0002, 0.),
                                (.0002, .0001, .75), (0., -.0001, 0.)):
            with self.subTest(h1=h1, h2=h2):
                s = f.MechanicalState(h1 - p.lower_rest_half_gap_m, h2 - p.upper_rest_half_gap_m)
                e = f.evaluate(s)
                self.assertAlmostEqual(e.lower_force_n_per_fold, .014 * .0025 * 800 * fraction)
                self.assertAlmostEqual(e.full_flow_m3_s, 2 * .014 * max(0, min(h1, h2)) * math.sqrt(1600 / 1.2))

    def test_asymmetric_rest_gaps_use_geometry(self):
        p = replace(f.FoldParameters(), lower_rest_half_gap_m=.0003, upper_rest_half_gap_m=.0001)
        e = f.evaluate(f.MechanicalState(0., 0.), p)
        self.assertAlmostEqual(e.lower_force_n_per_fold, .014 * .0025 * 800 * (1 - 1/9))

    def test_asymmetric_contact_corners_match_high_precision_oracle(self):
        def neighboring(value, offset):
            for _ in range(abs(offset)):
                value = math.nextafter(value,math.inf if offset>0 else -math.inf)
            return value
        gaps = (.0001,.00018,.0003,.001,.002)
        for h01,h02,i,j in itertools.product(gaps,gaps,range(-4,5),range(-4,5)):
            p = replace(f.FoldParameters(),lower_rest_half_gap_m=h01,upper_rest_half_gap_m=h02)
            state = f.MechanicalState(neighboring(-h01,i),neighboring(-h02,j))
            with localcontext() as context:
                context.prec = 120
                h1 = Decimal.from_float(h01)+Decimal.from_float(state.lower_displacement_m)
                h2 = Decimal.from_float(h02)+Decimal.from_float(state.upper_displacement_m)
                expected = (0. if h1<=0 else 1. if h2<=0 else 0. if h1<=h2
                            else float((h1-h2)/h1*(1+h2/h1)))
            actual = f.evaluate(state,p).lower_force_n_per_fold/(p.fold_length_m*p.lower_thickness_m*800.)
            with self.subTest(h01=h01,h02=h02,i=i,j=j):
                self.assertAlmostEqual(actual,expected,delta=1e-14)

    def test_force_switch_does_not_switch_off_dc_flow(self):
        enabled = f.evaluate(f.MechanicalState(.0001, 0.))
        disabled = f.evaluate(f.MechanicalState(.0001, 0.), aerodynamic_force_enabled=False)
        self.assertGreater(enabled.lower_force_n_per_fold, 0)
        self.assertEqual(disabled.lower_force_n_per_fold, 0)
        self.assertEqual(disabled.full_flow_m3_s, enabled.full_flow_m3_s)

    def test_contact_sign_and_energy_gradient_identity(self):
        p = f.FoldParameters()
        s = f.MechanicalState(-.0004, -.0003, .1, -.08)
        e = f.evaluate(s, pressure_pa=0)
        x1, x2, v1, v2, _, _ = s.values()
        h1, h2 = p.lower_rest_half_gap_m + x1, p.upper_rest_half_gap_m + x2
        grad1 = p.lower_stiffness_n_m*x1 + p.coupling_stiffness_n_m*(x1-x2) + p.lower_contact_stiffness_n_m*min(h1,0)
        grad2 = p.upper_stiffness_n_m*x2 + p.coupling_stiffness_n_m*(x2-x1) + p.upper_contact_stiffness_n_m*min(h2,0)
        de = grad1*v1 + grad2*v2 + p.lower_mass_kg*v1*e.derivative[2] + p.upper_mass_kg*v2*e.derivative[3]
        self.assertAlmostEqual(de, e.derivative[4] - e.derivative[5], places=15)
        contact_off = f.evaluate(s, replace(p, lower_contact_stiffness_n_m=0, upper_contact_stiffness_n_m=0), pressure_pa=0)
        self.assertGreater(e.derivative[2], contact_off.derivative[2])
        self.assertGreater(e.derivative[3], contact_off.derivative[3])
        self.assertGreater(e.energy_j_per_fold, contact_off.energy_j_per_fold)

    def test_nearly_equal_gaps_keep_small_force(self):
        e = f.evaluate(f.MechanicalState(1e-16, 0.))
        self.assertGreater(e.lower_force_n_per_fold, 0.)
        self.assertLess(e.lower_force_n_per_fold, 1e-12)

    def test_sub_ulp_gap_difference_keeps_analytic_small_force(self):
        p = f.FoldParameters()
        for tiny in (1e-23, 1e-30, 1e-100):
            self.assertEqual(p.lower_rest_half_gap_m + tiny, p.upper_rest_half_gap_m)
            actual = f.evaluate(f.MechanicalState(tiny,0.)).lower_force_n_per_fold
            linear = p.fold_length_m*p.lower_thickness_m*800.*2.*tiny/p.lower_rest_half_gap_m
            self.assertGreater(actual,0.)
            self.assertAlmostEqual(actual/linear,1.,delta=1e-15)
            self.assertEqual(f.evaluate(f.MechanicalState(-tiny,0.)).lower_force_n_per_fold,0.)
        self.assertEqual(f.evaluate(f.MechanicalState(0.,0.)).lower_force_n_per_fold,0.)

    def test_hostile_numbers_and_types(self):
        for value in (None, True, '1', math.nan, math.inf, -math.inf, 10**1000):
            with self.subTest(value=type(value).__name__):
                with self.assertRaises(f.FoldError):
                    f.FoldParameters(lower_mass_kg=value)
                with self.assertRaises(f.FoldError):
                    f.PressureSchedule.constant(value)
                with self.assertRaises(f.FoldError):
                    f.SimulationPlan(initial=f.MechanicalState(value))
                with self.assertRaises(f.FoldError):
                    f.GuardLimits(velocity_m_s=value)

    def test_plan_and_step_work_quotas(self):
        for kwargs in ({'frames':0}, {'frames':240001}, {'frames':True}, {'frames':48.},
                       {'sample_rate':24000}, {'sample_rate':48000.}, {'substeps':3},
                       {'substeps':True}, {'aerodynamic_force_enabled':1}, {'parameters':{}},
                       {'initial':f.MechanicalState(aero_work_j_per_fold=1.)}):
            with self.subTest(kwargs=kwargs), self.assertRaises(f.FoldError):
                f.SimulationPlan(**kwargs)
        self.assertLessEqual(f.SimulationPlan(frames=240000, substeps=8).total_substeps, f.MAX_SUBSTEPS)
        for kwargs in ({'lower_damping_kg_s':-.01}, {'lower_mass_kg':0.},
                       {'lower_rest_half_gap_m':-.0001}, {'coupling_stiffness_n_m':-1.}):
            with self.assertRaises(f.FoldError):
                f.FoldParameters(**kwargs)
        with self.assertRaises(f.FoldError):
            f.GuardLimits(displacement_m=.021)

    def test_pressure_schedule_ramp_hold_jumps_and_validation(self):
        schedule = f.PressureSchedule((f.PressureKnot(0., 0., 'linear'),
                                       f.PressureKnot(.01, 800.), f.PressureKnot(.02, 0.)))
        self.assertEqual([schedule.at(t) for t in (0., .005, .01, .019, .02, .03)], [0., 400., 800., 800., 0., 0.])
        for knots in ((), [f.PressureKnot(0., 0.)], (f.PressureKnot(.1, 0.),),
                      (f.PressureKnot(0., 0.), f.PressureKnot(0., 1.))):
            with self.assertRaises(f.FoldError): f.PressureSchedule(knots)
        with self.assertRaises(f.FoldError): f.PressureKnot(0., -1.)
        with self.assertRaises(f.FoldError): f.PressureKnot(0., 2501.)
        with self.assertRaises(f.FoldError): f.PressureKnot(0., 1., 'spline')
        with self.assertRaises(f.FoldError): f.SimulationPlan(frames=1, pressure=schedule)

    def test_pressure_evaluated_at_every_stage(self):
        plan = f.SimulationPlan(frames=1, pressure=f.PressureSchedule((f.PressureKnot(0.,0.,'linear'),f.PressureKnot(1/48000,800.))))
        engine = f.FoldStepper(plan)
        original = f._evaluate
        seen = []
        def spy(*args):
            seen.append(args[3]); return original(*args)
        with patch.object(f, '_evaluate', side_effect=spy):
            engine.step_substep()
        self.assertEqual(seen, [0.,100.,100.,200.,200.])

    def test_guard_failure_is_atomic_without_internal_clipping(self):
        plan = f.SimulationPlan(frames=48, guards=f.GuardLimits(displacement_m=1.000001e-9))
        engine = f.FoldStepper(plan)
        before = engine.snapshot()
        with self.assertRaisesRegex(f.GuardViolation, 'substep 0.*displacement'):
            engine.step_substep()
        self.assertEqual(engine.snapshot(), before)

    def test_derivative_energy_flow_and_state_guards(self):
        cases = [({'acceleration_m_s2':1e-6}, f.MechanicalState()),
                 ({'mechanical_energy_j_per_fold':1e-18}, f.MechanicalState()),
                 ({'full_flow_m3_s':1e-6}, f.MechanicalState()),
                 ({'force_n_per_fold':1e-6}, f.MechanicalState(.0001, 0.)),
                 ({'power_w_per_fold':1e-8}, f.MechanicalState(0.,0.,.1,0.)),
                 ({'velocity_m_s':.01}, f.MechanicalState(0.,0.,.1,0.)),
                 ({'accumulated_work_j_per_fold':.01}, f.MechanicalState(aero_work_j_per_fold=.02))]
        for kwargs, state in cases:
            with self.subTest(kwargs=kwargs), self.assertRaises(f.GuardViolation):
                f.evaluate(state, guards=f.GuardLimits(**kwargs))
        with self.assertRaises(f.GuardViolation):
            f.evaluate(f.MechanicalState(damping_loss_j_per_fold=-1e-9))

    def test_exact_zero_stays_stationary_and_step_work_ends(self):
        plan = f.SimulationPlan(frames=48, initial=f.MechanicalState(0.,0.))
        engine = f.FoldStepper(plan)
        for frame in range(plan.frames):
            samples = engine.step_frame()
            self.assertEqual(len(samples), plan.substeps)
            self.assertTrue(all(s.mechanics == plan.initial for s in samples))
        self.assertEqual(engine.remaining_substeps, 0)
        with self.assertRaises(StopIteration): engine.step_substep()
        with self.assertRaises(StopIteration): engine.step_frame()

    def test_checkpoint_and_window_restore_are_bitwise_identical(self):
        plan = f.SimulationPlan(frames=480)
        engine, metrics = f.FoldStepper(plan), f.WindowMetrics()
        for _ in range(713): metrics.observe(engine.step_substep())
        restored = f.FoldStepper(plan, engine.snapshot())
        restored_metrics = f.WindowMetrics(state=metrics.snapshot())
        with self.assertRaises(f.FoldError): restored.step_frame()
        for original in engine:
            resumed = restored.step_substep()
            self.assertEqual(original, resumed)
            metrics.observe(original); restored_metrics.observe(resumed)
        self.assertEqual(engine.snapshot(), restored.snapshot())
        self.assertEqual(metrics.snapshot(), restored_metrics.snapshot())
        self.assertEqual(metrics.summary(), restored_metrics.summary())

    def test_restore_rejects_plan_version_state_and_diagnostic_tampering(self):
        plan = f.SimulationPlan(frames=48)
        engine = f.FoldStepper(plan)
        engine.step_frame(); state = engine.snapshot()
        changes = ({'version':2}, {'version':True}, {'substep_index':-1}, {'substep_index':193},
                   {'initial_energy_j_per_fold':0.}, {'max_energy_j_per_fold':0.},
                   {'max_abs_displacement_m':0.}, {'max_abs_velocity_m_s':math.nan},
                   {'mechanics':f.MechanicalState(math.inf)}, {'max_overlap_m':-.01})
        for change in changes:
            with self.subTest(change=change), self.assertRaises(f.FoldError):
                f.FoldStepper(plan, replace(state, **change))
        with self.assertRaises(f.FoldError): f.FoldStepper(replace(plan,substeps=8),state)

    def test_one_mass_linear_decay_matches_analytic_solution(self):
        p = replace(f.FoldParameters(), coupling_stiffness_n_m=0.,
                    lower_contact_stiffness_n_m=0., upper_contact_stiffness_n_m=0.)
        plan = f.SimulationPlan(frames=960, parameters=p, initial=f.MechanicalState(1e-5,0.), pressure=f.PressureSchedule.constant(0.))
        engine = f.FoldStepper(plan)
        for sample in engine: pass
        alpha = p.lower_damping_kg_s / (2 * p.lower_mass_kg)
        omega = math.sqrt(p.lower_stiffness_n_m/p.lower_mass_kg-alpha*alpha)
        t = plan.duration_s
        exact = 1e-5 * math.exp(-alpha*t) * (math.cos(omega*t)+alpha/omega*math.sin(omega*t))
        velocity = -1e-5*math.exp(-alpha*t)*(omega+alpha*alpha/omega)*math.sin(omega*t)
        self.assertAlmostEqual(sample.mechanics.lower_displacement_m, exact, delta=1e-14)
        self.assertAlmostEqual(sample.mechanics.lower_velocity_m_s, velocity, delta=1e-11)
        self.assertEqual(sample.mechanics.upper_displacement_m, 0.)
        self.assertLess(engine.snapshot().max_energy_residual_j_per_fold, 1e-17)

    def test_welford_preserves_tiny_ac_over_dc(self):
        m = f.Moments()
        for i in range(1000): m.add(.000184034779322 + (1e-15 if i%2 else -1e-15))
        self.assertGreater(m.variance, 9e-31)
        self.assertLess(m.variance, 1.1e-30)
        self.assertEqual(m.snapshot(), f.Moments(m.snapshot()).snapshot())
        wide = f.Moments(); wide.add(1e6); wide.add(-1e6)
        self.assertEqual(wide.snapshot(),f.Moments(wide.snapshot()).snapshot())

    def test_measurement_frequency_floor_and_geometry_not_zero_flow(self):
        engine = f.FoldStepper(f.SimulationPlan(frames=48,pressure=f.PressureSchedule.constant(0.)))
        m = f.WindowMetrics()
        for sample in engine: m.observe(sample)
        summary = m.summary()
        self.assertEqual(summary['f0_hz'],0.)
        self.assertEqual(summary['full_flow_ac_rms_m3_s'],0.)
        self.assertEqual(summary['geometric_closed_fraction'],0.)

    def test_measurement_rejects_nonmonotonic_and_invalid_restore(self):
        s = f.FoldStepper(f.SimulationPlan(frames=1)).step_substep()
        m = f.WindowMetrics(); m.observe(s)
        with self.assertRaises(f.FoldError): m.observe(s)
        for changed in ({'pressure_pa':math.nan},{'energy_j_per_fold':math.inf},{'mechanics':None},{'substep_index':True}):
            with self.assertRaises(f.FoldError): f.WindowMetrics().observe(replace(s,**changed))
        with self.assertRaises(f.FoldError): f.WindowMetrics(state=replace(m.snapshot(),closed_count=2))
        with self.assertRaises(f.FoldError): f.Moments(f.MomentsState(count=1,mean=2.,minimum=0.,maximum=1.))


class PhysicalCampaignPublicationTests(unittest.TestCase):
    """Path/receipt contracts use mocks; root discovery never runs the campaign."""
    def test_output_is_required_before_work_or_directory_creation(self):
        with tempfile.TemporaryDirectory() as root:
            raw = Path(root)/'raw'
            with patch.object(campaign,'cases') as work, contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as error:
                    campaign.main(['--raw-dir',str(raw)])
                self.assertEqual(error.exception.code,2)
                work.assert_not_called()
            self.assertFalse(raw.exists())

    def test_fresh_destinations_reserved_exclusively(self):
        with tempfile.TemporaryDirectory() as root:
            raw,output = Path(root)/'raw',Path(root)/'results'
            self.assertEqual(campaign.prepare_directories(raw,output),(raw.resolve(),output.resolve()))
            self.assertTrue(raw.is_dir());self.assertTrue(output.is_dir())
            (output/'metrics.json').write_text('retained-proof')
            with self.assertRaises(ValueError): campaign.prepare_directories(Path(root)/'other-raw',output)
            self.assertEqual((output/'metrics.json').read_text(),'retained-proof')
            self.assertFalse((Path(root)/'other-raw').exists())

    def test_lexical_aliases_return_canonical_fresh_paths(self):
        with tempfile.TemporaryDirectory() as root:
            base=Path(root);anchor=base/'anchor';anchor.mkdir()
            raw,output=anchor/'..'/'raw',anchor/'..'/'results'
            resolved_raw,resolved_output=campaign.prepare_directories(raw,output)
            self.assertEqual((resolved_raw,resolved_output),
                             ((base/'raw').resolve(),(base/'results').resolve()))
            self.assertTrue(resolved_raw.samefile(raw))
            self.assertTrue(resolved_output.samefile(output))

    def test_existing_files_directories_and_raw_paths_fail_without_clobber(self):
        for occupied in ('output-directory','output-file','raw-directory','raw-file'):
            with self.subTest(occupied=occupied),tempfile.TemporaryDirectory() as root:
                raw,output = Path(root)/'raw',Path(root)/'results'
                target = raw if occupied.startswith('raw') else output
                if occupied.endswith('directory'):
                    target.mkdir();(target/'sentinel').write_text('untouched')
                    sentinel = target/'sentinel'
                else:
                    target.write_text('untouched');sentinel = target
                with self.assertRaises(ValueError): campaign.prepare_directories(raw,output)
                self.assertEqual(sentinel.read_text(),'untouched')
                self.assertFalse((output if target==raw else raw).exists())

    def test_overlapping_and_repository_raw_destinations_are_rejected(self):
        with tempfile.TemporaryDirectory() as root:
            base=Path(root)
            for raw,output in ((base/'same',base/'same'),(base/'raw',base/'raw/results'),
                               (base/'results/raw',base/'results'),
                               (campaign.ROOT/'uncreated-raw-test',base/'results')):
                with self.subTest(raw=raw,output=output),self.assertRaises(ValueError):
                    campaign.prepare_directories(raw,output)
                self.assertFalse(output.exists())

    def test_symlinks_dangling_links_and_resolved_existing_paths_are_rejected(self):
        with tempfile.TemporaryDirectory() as root:
            base=Path(root);target=base/'target';target.mkdir()
            link=base/'link';link.symlink_to(target,target_is_directory=True)
            dangling=base/'dangling';dangling.symlink_to(base/'missing',target_is_directory=True)
            for output in (link,link/'child',dangling,base/'new/../target'):
                with self.subTest(output=output),self.assertRaises(ValueError):
                    campaign.prepare_directories(base/'raw',output)
                self.assertFalse((base/'raw').exists())
            self.assertFalse((base/'missing').exists())
            self.assertFalse((target/'child').exists())

    def test_bad_parent_path_and_invalid_cli_input_fail_closed(self):
        with tempfile.TemporaryDirectory() as root:
            base=Path(root);blocker=base/'file';blocker.write_text('safe')
            with self.assertRaises((OSError,ValueError)):
                campaign.prepare_directories(base/'raw',blocker/'results')
            self.assertEqual(blocker.read_text(),'safe')
            self.assertFalse((base/'raw').exists())
            with contextlib.redirect_stderr(io.StringIO()),self.assertRaises(SystemExit) as error:
                campaign.main(['--raw-dir',str(base/'raw'),'--output','\0'])
            self.assertEqual(error.exception.code,2)
            self.assertFalse((base/'raw').exists())

    def test_complete_mock_campaign_binds_new_receipts_and_refuses_reuse(self):
        with tempfile.TemporaryDirectory() as root:
            anchor=Path(root)/'anchor';anchor.mkdir()
            raw,output=anchor/'..'/'raw',anchor/'..'/'results'
            plan=f.SimulationPlan(frames=1)
            result={'name':'mock-case','proof':'harness-contract-only'}
            argv=['--raw-dir',str(raw),'--output',str(output)]
            with patch.object(campaign,'cases',return_value=[('mock-case',plan)]), \
                 patch.object(campaign,'run_case',return_value=result) as runner, \
                 patch.object(campaign,'gates',return_value={'mock-check':True}), \
                 contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(campaign.main(argv),0)
                runner.assert_called_once_with('mock-case',plan,raw.resolve())
            manifest=json.loads((output/'run-manifest.json').read_text())
            receipt=json.loads((output/'metrics.json').read_text())
            self.assertEqual(json.loads((output/'case-results.jsonl').read_text()),result)
            self.assertEqual(receipt['schema'],'aster-original-physical-fold-core-gate-v2')
            self.assertEqual(manifest['sources_sha256'],receipt['sources_sha256'])
            self.assertEqual(set(receipt['sources_sha256']),{
                'experiments/physical_voice/__init__.py',
                'experiments/physical_voice/folds.py',
                'experiments/physical_voice/test_numerical.py',
                'tests/test_physical_folds.py'})
            self.assertEqual(receipt['sources_sha256']['experiments/physical_voice/test_numerical.py'],
                             hashlib.sha256(Path(campaign.__file__).read_bytes()).hexdigest())
            original={path.name:path.read_bytes() for path in output.iterdir()}
            with contextlib.redirect_stderr(io.StringIO()),self.assertRaises(SystemExit):
                campaign.main(argv)
            self.assertEqual(original,{path.name:path.read_bytes() for path in output.iterdir()})

    def test_failed_mock_campaign_keeps_partial_and_final_failure_receipts(self):
        with tempfile.TemporaryDirectory() as root:
            raw,output=Path(root)/'raw',Path(root)/'results'
            plan=f.SimulationPlan(frames=1)
            result={'name':'completed-mock-case'}
            with patch.object(campaign,'cases',return_value=[('first',plan),('second',plan)]), \
                 patch.object(campaign,'run_case',side_effect=[result,RuntimeError('controlled test failure')]), \
                 self.assertRaisesRegex(RuntimeError,'controlled test failure'):
                campaign.main(['--raw-dir',str(raw),'--output',str(output)])
            final=json.loads((output/'metrics.json').read_text())
            self.assertFalse(final['passed'])
            self.assertEqual(final['cases'],[result])
            self.assertEqual(final['failure']['type'],'RuntimeError')
            self.assertEqual(json.loads((output/'case-results.jsonl').read_text()),result)
            self.assertTrue((output/'run-manifest.json').is_file())

    def test_work_quota_checked_before_paths_are_created(self):
        with tempfile.TemporaryDirectory() as root:
            raw,output=Path(root)/'raw',Path(root)/'results'
            fake=SimpleNamespace(total_substeps=campaign.MAX_CAMPAIGN_SUBSTEPS+1)
            with patch.object(campaign,'cases',return_value=[('oversized',fake)]),self.assertRaises(RuntimeError):
                campaign.main(['--raw-dir',str(raw),'--output',str(output)])
            self.assertFalse(raw.exists());self.assertFalse(output.exists())


if __name__ == '__main__':
    unittest.main()
