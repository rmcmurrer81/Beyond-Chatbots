"""Fast offline contracts for the separately gated original acoustic tract.

python -m unittest discover -s tests -p test_physical_tract.py -v
Heavy response/tone sweeps: test-results/physical-voice/tract/filter_gate.py.
"""
from dataclasses import FrozenInstanceError, replace
import itertools
import math
import random
import unittest
from unittest.mock import patch

from experiments.physical_voice import tract as t
from experiments.physical_voice import filters as f


class TractContracts(unittest.TestCase):
    def test_config_controls_and_wave_inputs_are_strict_and_immutable(self):
        for x in (True, float('nan'), float('inf'), -1., 1.01, '0.5'):
            with self.assertRaises(t.TractError):
                t.Articulation(tongue_height=x)
        for kwargs in ({'velum_opening': .001}, {'velum_opening': True}, {'propagation_gain':1.001},
                       {'source_area_m2':0}, {'nasal_base_areas_m2':[1e-4]*16},
                       {'nasal_base_areas_m2':(1e-4,)*15}, {'sound_speed_m_s':float('nan')},
                       {'guards':None}, {'velum_opening':.01,'nasal_base_areas_m2':(1e-6,)*16}):
            with self.assertRaises(t.TractError):
                t.TractConfig(**kwargs)
        for kwargs in ({'oral_forward':(0.,)*23}, {'nasal_backward':[0.]*16},
                       {'lip_radiation_state':float('nan')}, {'nose_radiation_state':True}):
            with self.assertRaises(t.TractError):
                t.TractWaves(**kwargs)
        with self.assertRaises(FrozenInstanceError):
            t.TractConfig().velum_opening = .5
        with self.assertRaises(t.TractError):
            t.TractGuards(max_frames=True)
        with self.assertRaises(t.TractError):
            t.TractGuards(max_abs_flow_m3_s=.021)

    def test_geometry_envelope_source_fixed_and_control_effects(self):
        source = 1.23e-4
        for params in itertools.product((0., .5, 1.), repeat=4):
            areas = t.oral_areas(t.Articulation(*params), source)
            self.assertEqual(len(areas),24)
            self.assertEqual(areas[0],source)
            self.assertTrue(all(t.AREA_MIN_M2 <= x <= t.AREA_MAX_M2 for x in areas))
        base = t.Articulation()
        a = t.oral_areas(base)
        self.assertLess(t.oral_areas(replace(base,tongue_height=1.))[11],a[11])
        self.assertGreater(t.oral_areas(replace(base,jaw_opening=1.))[-1],a[-1])
        self.assertLess(t.oral_areas(replace(base,lip_rounding=1.))[-1],a[-1])
        self.assertLess(t.oral_areas(replace(base,tongue_position=.1))[6],t.oral_areas(replace(base,tongue_position=.9))[6])
        near = t.oral_areas(replace(base,tongue_height=base.tongue_height+1e-7))
        self.assertLess(max(abs(x-y) for x,y in zip(a,near)),1e-10)

    def test_junction_norm_pressure_and_volume_flow(self):
        rng = random.Random(12031)
        for ports in (2,3):
            for _ in range(100):
                incoming=tuple(rng.uniform(-2,2) for _ in range(ports))
                admittance=tuple(10**rng.uniform(-9,-5) for _ in range(ports))
                outgoing=t.scatter(incoming,admittance)
                norm_in=math.fsum(a*a for a in incoming)
                norm_out=math.fsum(b*b for b in outgoing)
                self.assertAlmostEqual(norm_in,norm_out,delta=2e-14*max(1.,norm_in))
                pressures=[(a+b)/math.sqrt(y) for a,b,y in zip(incoming,outgoing,admittance)]
                self.assertLess(max(pressures)-min(pressures),1e-9)
                flow=math.fsum(math.sqrt(y)*(a-b) for a,b,y in zip(incoming,outgoing,admittance))
                self.assertAlmostEqual(flow,0.,delta=2e-17)
                twice=t.scatter(outgoing,admittance)
                for a,b in zip(incoming,twice):
                    self.assertAlmostEqual(a,b,delta=4e-15)
        for y in (0.,-1.,float('nan')):
            with self.assertRaises(t.TractError):
                t.scatter((0.,0.),(1e-6,y))

    def test_radiation_orthogonality_state_storage_and_dc_zero(self):
        rng=random.Random(12)
        for _ in range(100):
            a,s=rng.uniform(-3,3),rng.uniform(-3,3)
            b,r,sn=t.radiation(a,s)
            self.assertAlmostEqual(a*a+s*s,b*b+r*r+sn*sn,delta=1e-14)
        state=0.
        for _ in range(120):
            reflected,outgoing,state=t.radiation(1.,state)
        self.assertAlmostEqual(outgoing,0.,delta=5e-16)
        self.assertAlmostEqual(reflected,-1.,delta=5e-16)
        self.assertGreater(state*state,0.)
        # Nyquist input goes primarily out rather than back into the tube.
        state=0.
        for i in range(120):
            reflected,outgoing,state=t.radiation((-1.)**i,state)
        self.assertAlmostEqual(reflected,0.,delta=5e-16)
        self.assertAlmostEqual(abs(outgoing),1.,delta=5e-16)

    def test_source_returning_wave_identity_and_negative_work(self):
        c=t.TractConfig(propagation_gain=1.)
        u=math.sqrt(c.source_area_m2/(c.air_density_kg_m3*c.sound_speed_m_s))
        for incoming,flow in ((.2,.1*u),(-1.,.5*u),(.3,-.4*u),(.4,0.)):
            solver=t.OralNasalTract(c,t.TractWaves(oral_backward=(incoming,)+(0.,)*23))
            sample=solver.step(flow)
            a,b=sample.source_returning_root_power,sample.source_launched_root_power
            self.assertEqual(a,incoming)
            self.assertAlmostEqual(b,a+flow/u,delta=1e-15)
            self.assertAlmostEqual((b-a)*u,flow,delta=1e-19)
            self.assertAlmostEqual(sample.source_work_j,t.DT*(b*b-a*a),delta=1e-20)
            self.assertAlmostEqual(sample.source_work_j,t.DT*sample.boundary_pressure_pa*flow,delta=1e-20)
            self.assertAlmostEqual(solver.checkpoint().energy_residual_j,0.,delta=1e-20)
            if incoming<0 and flow>0:
                self.assertLess(sample.source_work_j,0.)
                self.assertGreater(solver.checkpoint().negative_source_work_j,0.)

    def test_exact_oneway_24_and_roundtrip_48_sample_delay(self):
        # Test fixture only: uniform tube and an ideal -1 pressure-release lip.
        c=t.TractConfig(propagation_gain=1.)
        u=math.sqrt(c.source_area_m2/(c.air_density_kg_m3*c.sound_speed_m_s))
        with patch.object(t,'oral_areas',return_value=(c.source_area_m2,)*24):
            solver=t.OralNasalTract(c)
            samples=[solver.step(u if i==0 else 0.) for i in range(60)]
            self.assertTrue(all(x.lip_root_power==0 for x in samples[:24]))
            self.assertNotEqual(samples[24].lip_root_power,0.)
        with patch.object(t,'oral_areas',return_value=(c.source_area_m2,)*24), patch.object(t,'_radiation',side_effect=lambda a,s:(-a,0.,s)):
            solver=t.OralNasalTract(c)
            samples=[solver.step(u if i==0 else 0.) for i in range(97)]
            self.assertTrue(all(x.source_returning_root_power==0 for x in samples[:48]))
            self.assertEqual(samples[48].source_returning_root_power,-1.)
            self.assertEqual(samples[96].source_returning_root_power,1.)
            self.assertAlmostEqual(solver.checkpoint().energy_j,t.DT,delta=1e-19)
            self.assertEqual(solver.checkpoint().propagation_loss_j,0.)

    def test_uniform_test_fixture_quarterwave_modes(self):
        c=t.TractConfig(propagation_gain=1.)
        u=math.sqrt(c.source_area_m2/(c.air_density_kg_m3*c.sound_speed_m_s))
        with patch.object(t,'oral_areas',return_value=(c.source_area_m2,)*24), patch.object(t,'_radiation',side_effect=lambda a,s:(-a,0.,s)):
            solver=t.OralNasalTract(c)
            values=[solver.step(u if i==0 else 0.).source_returning_root_power for i in range(1_056)][96:]
        def dft(freq):
            return abs(sum(x*complex(math.cos(2*math.pi*freq*i/t.SAMPLE_RATE),-math.sin(2*math.pi*freq*i/t.SAMPLE_RATE)) for i,x in enumerate(values)))
        for frequency in (500,1500,2500,3500):
            self.assertAlmostEqual(dft(frequency),20.,delta=1e-11)
            self.assertLess(dft(frequency+500),1e-11)

    def test_sourceoff_conservation_with_radiation_storage_and_loss(self):
        rng=random.Random(2026)
        initial=t.TractWaves(*(tuple(rng.uniform(-.02,.02) for _ in range(n)) for n in (24,24,16,16)),.02,-.03)
        for gain in (1.,.997):
            solver=t.OralNasalTract(t.TractConfig(velum_opening=.5,propagation_gain=gain),initial)
            previous=initial.energy_j
            for _ in range(400):
                sample=solver.step(0.)
                self.assertLessEqual(sample.stored_energy_j,previous+1e-21)
                previous=sample.stored_energy_j
            s=solver.checkpoint()
            self.assertAlmostEqual(s.energy_j+s.propagation_loss_j+s.lip_out_energy_j+s.nose_out_energy_j,initial.energy_j,delta=2e-20)
            self.assertEqual(s.source_work_j,0.)
            self.assertGreater(s.lip_out_energy_j,0.)
            self.assertGreater(s.nose_out_energy_j,0.)
            self.assertLess(s.energy_j,initial.energy_j)
            self.assertEqual(s.propagation_loss_j==0.,gain==1.)

    def test_dynamic_area_changes_are_passive_and_do_not_rescale_waves(self):
        initial=t.TractWaves(oral_forward=(.1,)+(0.,)*23,nasal_backward=(0.,)*15+(.15,))
        solver=t.OralNasalTract(t.TractConfig(velum_opening=.8,propagation_gain=1.),initial)
        for i in range(500):
            previous=solver.checkpoint()
            pose=t.Articulation((i%11)/10,(i%7)/6,(i%13)/12,(i%17)/16)
            sample=solver.step(0.,pose)
            self.assertLessEqual(sample.stored_energy_j,previous.energy_j+1e-20)
            self.assertEqual(sample.source_work_j,0.)
        s=solver.checkpoint()
        self.assertAlmostEqual(s.energy_j+s.lip_out_energy_j+s.nose_out_energy_j,initial.energy_j,delta=2e-19)
        # A wave newly launched at the unchanged source is identical across poses.
        a=t.OralNasalTract(t.TractConfig(propagation_gain=1.)); b=t.OralNasalTract(t.TractConfig(propagation_gain=1.))
        a.step(1e-4,t.Articulation(0,0,0,0)); b.step(1e-4,t.Articulation(1,1,1,1))
        self.assertEqual(a.checkpoint().waves,b.checkpoint().waves)

    def test_closed_velum_keeps_preloaded_nasal_tail_and_exact_rigid_reflection(self):
        c=t.TractConfig(propagation_gain=1.,velum_opening=0.)
        initial=t.TractWaves(nasal_backward=(.1,)+(0.,)*15)
        solver=t.OralNasalTract(c,initial)
        first=solver.step(0.)
        self.assertEqual(solver.checkpoint().waves.nasal_forward[0],.1)
        self.assertEqual(first.lip_root_power,0.)
        for _ in range(300):
            sample=solver.step(0.)
            self.assertEqual(sample.lip_root_power,0.)
            self.assertEqual(sample.source_returning_root_power,0.)
        self.assertGreater(solver.checkpoint().nose_out_energy_j,0.)
        self.assertGreater(solver.checkpoint().energy_j,0.)
        no_nose=t.OralNasalTract(c)
        with_nose=t.OralNasalTract(c,initial)
        for i in range(150):
            flow=1e-4 if i==0 else 0.
            a,b=no_nose.step(flow),with_nose.step(flow)
            self.assertEqual(a.lip_root_power,b.lip_root_power)
            self.assertEqual(a.boundary_pressure_pa,b.boundary_pressure_pa)
        self.assertEqual(no_nose.checkpoint().nose_out_energy_j,0.)

    def test_open_velum_uses_actual_first_section_and_changes_spectrum(self):
        config=t.TractConfig(velum_opening=.25)
        self.assertEqual(config.nasal_areas_m2[0],config.nasal_base_areas_m2[0]*.25)
        solver=t.OralNasalTract(config)
        self.assertEqual(solver._branch_u[2],math.sqrt(config.nasal_areas_m2[0]/(config.air_density_kg_m3*config.sound_speed_m_s)))
        closed=t.OralNasalTract(t.TractConfig())
        open_values=[]; closed_values=[]
        for i in range(1600):
            flow=1e-4 if i==0 else 0.
            open_values.append(solver.step(flow).lip_root_power)
            closed_values.append(closed.step(flow).lip_root_power)
        self.assertGreater(solver.checkpoint().nose_out_energy_j,0.)
        def mag(values,f):
            return abs(sum(x*complex(math.cos(2*math.pi*f*i/48000),-math.sin(2*math.pi*f*i/48000)) for i,x in enumerate(values)))
        differences=[abs(mag(open_values,f)-mag(closed_values,f)) for f in (500,1000,1500,2000,3000)]
        self.assertGreater(max(differences),.005)

    def test_actual_open_branch_matches_threeport_scattering(self):
        c=t.TractConfig(velum_opening=.37,propagation_gain=1.)
        initial=t.TractWaves(oral_forward=(0.,)*11+(.2,)+(0.,)*12,
                            oral_backward=(0.,)*12+(-.15,)+(0.,)*11,
                            nasal_backward=(.05,)+(0.,)*15)
        solver=t.OralNasalTract(c,initial)
        rc=c.air_density_kg_m3*c.sound_speed_m_s
        y=(solver.areas_m2[11]/rc,solver.areas_m2[12]/rc,c.nasal_areas_m2[0]/rc)
        expected=t.scatter((.2,-.15,.05),y)
        solver.step(0.)
        w=solver.checkpoint().waves
        actual=w.oral_backward[11],w.oral_forward[12],w.nasal_forward[0]
        for a,b in zip(actual,expected):
            self.assertAlmostEqual(a,b,delta=2e-16)
        self.assertAlmostEqual(solver.checkpoint().energy_j,initial.energy_j,delta=1e-20)

    def test_complete_checkpoint_exact_block_replay_including_controls_and_tail(self):
        c=t.TractConfig(velum_opening=.6)
        flows=[1e-4*math.sin(i*.061) for i in range(333)]
        controls=[t.Articulation((i%13)/12,.3,.7,.2) for i in range(333)]
        uninterrupted=t.OralNasalTract(c)
        expected=[uninterrupted.step(f,a) for f,a in zip(flows,controls)]
        segmented=t.OralNasalTract(c)
        actual=[]
        for i,(flow,pose) in enumerate(zip(flows,controls)):
            actual.append(segmented.step(flow,pose))
            if i%19==0:
                saved=segmented.checkpoint()
                segmented=t.OralNasalTract.from_checkpoint(saved)
                self.assertEqual(saved,segmented.checkpoint())
        self.assertEqual(actual,expected)
        self.assertEqual(segmented.checkpoint(),uninterrupted.checkpoint())
        constant=t.OralNasalTract(c)
        a=constant.process(flows)
        blocked=t.OralNasalTract(c)
        b=blocked.process(flows[:5])+blocked.process(())+blocked.process(flows[5:79])+blocked.process(flows[79:])
        self.assertEqual(a,b)
        self.assertEqual(constant.checkpoint(),blocked.checkpoint())
        for kwargs in ({'version':True},{'version':2},{'sample_index':-1},{'sample_index':True},
                       {'source_work_j':float('nan')},{'lip_out_energy_j':-1.},
                       {'max_abs_wave':0.},{'initial_energy_j':1.}):
            with self.assertRaises(t.TractError):
                t.OralNasalTract.from_checkpoint(replace(segmented.checkpoint(),**kwargs))

    def test_guard_failures_are_atomic_and_do_not_clip_or_reset(self):
        solver=t.OralNasalTract(t.TractConfig(guards=t.TractGuards(max_abs_root_power=.01)))
        original=solver.checkpoint(); areas=solver.areas_m2
        for flow in (float('nan'),float('inf'),True,.03,.01):
            with self.assertRaises(t.TractError):
                solver.step(flow,t.Articulation(1.,1.,1.,1.))
            self.assertEqual(solver.checkpoint(),original)
            self.assertEqual(solver.areas_m2,areas)
        limited=t.OralNasalTract(t.TractConfig(guards=t.TractGuards(max_frames=1)))
        limited.step(1e-5)
        saved=limited.checkpoint()
        with self.assertRaises(t.GuardViolation):
            limited.step(0.)
        self.assertEqual(saved,limited.checkpoint())
        self.assertLess(t.OralNasalTract().step(-1e-5).source_launched_root_power,0.)


class FilterContracts(unittest.TestCase):
    def test_fixed_design_signed_impulse_dc_delay_and_independent_convolution(self):
        for m in (2,4,8):
            c=f.DecimatorConfig(m)
            filter=f.FlowDecimator(c)
            taps=filter.taps
            self.assertEqual(len(taps),36*m+1)
            self.assertEqual(taps,tuple(reversed(taps)))
            self.assertAlmostEqual(math.fsum(taps),1.,delta=3e-16)
            self.assertEqual(c.delay_output_samples,18)
            self.assertEqual(c.delay_s,.000375)
            values=(-.005,)+(0.,)*(40*m-1)
            actual=filter.process(values)
            self.assertEqual(max(range(len(actual)),key=lambda i:abs(actual[i])),18)
            self.assertLess(actual[18],0.)
            for j,y in enumerate(actual):
                expected=math.fsum(tap*values[j*m-k] for k,tap in enumerate(taps) if 0<=j*m-k<len(values))
                self.assertEqual(y,expected)
            dc=f.FlowDecimator(c).process((-.001,)*(80*m))
            self.assertAlmostEqual(dc[-1],-.001,delta=1e-18)

    def test_filter_phase_complete_checkpoint_block_parity_and_guards(self):
        values=tuple(.004*math.sin(i*.073) for i in range(733))
        for m in (2,4,8):
            whole=f.FlowDecimator(f.DecimatorConfig(m)); expected=whole.process(values)
            chunked=f.FlowDecimator(f.DecimatorConfig(m)); actual=[]
            for start,end in ((0,1),(1,6),(6,6),(6,137),(137,301),(301,733)):
                actual.extend(chunked.process(values[start:end]))
                chunked=f.FlowDecimator.from_checkpoint(chunked.checkpoint())
            self.assertEqual(tuple(actual),expected)
            self.assertEqual(chunked.checkpoint(),whole.checkpoint())
            state=chunked.checkpoint()
            for bad in (True,float('nan'),float('inf'),.011):
                with self.assertRaises(f.FilterError): chunked.push(bad)
                self.assertEqual(state,chunked.checkpoint())
            for kwargs in ({'version':True},{'input_samples':True},{'next_index':0},
                           {'output_samples':0},{'ring':list(state.ring)}):
                with self.assertRaises(f.FilterError): replace(state,**kwargs)
        for m in (True,1,3,4.,9):
            with self.assertRaises(f.FilterError): f.DecimatorConfig(m)
        limited=f.FlowDecimator(f.DecimatorConfig(max_input_samples=1))
        limited.push(.001); state=limited.checkpoint()
        with self.assertRaises(f.GuardViolation): limited.push(0.)
        self.assertEqual(state,limited.checkpoint())



if __name__ == '__main__':
    unittest.main()
