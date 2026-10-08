"""Small fixed-base inverse-dynamics and bounded forward tracking experiment."""
import math
import time
from .schema import masses


def model_xml(p, dt, scale=1):
    a,b = p['length_1_m'],p['length_2_m']
    w,t = p['width_m'],p['thickness_m']
    m1,m2 = [m*scale for m in masses(p)]
    payload = p['payload_kg']*scale
    radius = p['payload_radius_m']
    def inertial(m,l):
        return f'<inertial pos="{l/2} 0 0" mass="{m}" diaginertia="{m*(w*w+t*t)/12} {m*(l*l+t*t)/12} {m*(l*l+w*w)/12}"/>'
    return f'''<mujoco model="reviewed_two_link_example"><compiler angle="radian"/><option timestep="{dt}" gravity="0 0 -9.81" integrator="RK4"><flag filterparent="disable"/></option><worldbody>
      <geom name="floor" type="plane" size="2 2 .1"/>
      <body name="link1" pos="0 0 1"><joint name="shoulder" axis="0 -1 0" range="-1.2 1.2" limited="true"/>{inertial(m1,a)}<geom name="solid1" type="box" pos="{a/2} 0 0" size="{a/2} {w/2} {t/2}"/>
        <body name="link2" pos="{a} 0 0"><joint name="elbow" axis="0 -1 0" range="-1.2 1.2" limited="true"/>{inertial(m2,b)}<geom name="solid2" type="box" pos="{b/2} 0 0" size="{b/2} {w/2} {t/2}"/>
          <body name="payload" pos="{b} 0 0"><inertial pos="0 0 0" mass="{payload}" diaginertia="{payload*radius*radius*.4} {payload*radius*radius*.4} {payload*radius*radius*.4}"/><geom name="load" type="sphere" size="{radius}"/></body>
        </body></body></worldbody><contact><exclude body1="link1" body2="link2"/><exclude body1="link2" body2="payload"/></contact>
      <actuator><motor joint="shoulder" gear="1" ctrllimited="true" ctrlrange="{-p['torque_limit_nm']} {p['torque_limit_nm']}"/><motor joint="elbow" gear="1" ctrllimited="true" ctrlrange="{-p['torque_limit_nm']} {p['torque_limit_nm']}"/></actuator></mujoco>'''


def trajectory(t):
    # One second, smooth closed periodic excursion; q, velocity, acceleration in SI.
    omega = 2*math.pi
    return ([.15*(1-math.cos(omega*t)), .10*(1-math.cos(omega*t))],
            [.15*omega*math.sin(omega*t), .10*omega*math.sin(omega*t)],
            [.15*omega*omega*math.cos(omega*t), .10*omega*omega*math.cos(omega*t)])


def evaluate(p, deadline):
    import mujoco as mj
    import numpy as np
    trials = []
    for dt,scale in ((.004,1),(.002,1),(.002,1+p['uncertainty_fraction']),(.002,1-p['uncertainty_fraction'])):
        if time.monotonic() >= deadline: raise TimeoutError('Dynamics time budget exhausted')
        model = mj.MjModel.from_xml_string(model_xml(p,dt,scale))
        desired,actual = mj.MjData(model),mj.MjData(model)
        # Independent static gravity result for uniform links plus spherical payload.
        mj.mj_inverse(model,desired)
        a,b = p['length_1_m'],p['length_2_m']
        m1,m2 = [x*scale for x in masses(p)]
        analytic = [9.81*(m1*a/2+m2*(a+b/2)+p['payload_kg']*scale*(a+b)),
                    9.81*(m2*b/2+p['payload_kg']*scale*b)]
        static_error = float(np.max(np.abs(desired.qfrc_inverse-np.array(analytic))))
        peak,error,contacts,max_joint_angle = 0.,0.,0,0.
        finite = True
        for step in range(round(1/dt)):
            if time.monotonic() >= deadline: raise TimeoutError('Dynamics time budget exhausted')
            q,v,acc = trajectory(step*dt)
            # Ideal computed-torque tracking: acceleration-domain gains avoid mass-dependent stiffness.
            desired.qpos[:],desired.qvel[:] = actual.qpos,actual.qvel
            desired.qacc[:] = np.array(acc)+100*(np.array(q)-actual.qpos)+20*(np.array(v)-actual.qvel)
            mj.mj_inverse(model,desired)
            command = desired.qfrc_inverse.copy()
            peak = max(peak,float(np.max(np.abs(command))))
            actual.ctrl[:] = np.clip(command,-p['torque_limit_nm'],p['torque_limit_nm'])
            mj.mj_step(model,actual)
            target_next = trajectory((step+1)*dt)[0]
            error = max(error,float(np.max(np.abs(actual.qpos-target_next))))
            contacts = max(contacts,actual.ncon)
            max_joint_angle = max(max_joint_angle,float(np.max(np.abs(actual.qpos))))
            if not np.all(np.isfinite(actual.qpos)) or not np.all(np.isfinite(command)):
                finite=False; break
        passed = finite and peak <= p['torque_limit_nm'] and error <= .05 and contacts == 0 and max_joint_angle <= 1.2 and static_error <= 1e-8
        trials.append({'dt_s':dt,'mass_scale':scale,'status':'passed' if passed else 'failed',
                       'peak_command_nm':peak,'max_tracking_error_rad':error,'max_contacts':contacts,
                       'static_analytic_error_nm':static_error,'max_joint_angle_rad':max_joint_angle,'finite':finite})
    difference = abs(trials[0]['peak_command_nm']-trials[1]['peak_command_nm'])
    stable = difference <= max(.01,.02*trials[1]['peak_command_nm'])
    return {'status':'passed' if stable and all(t['status']=='passed' for t in trials) else 'failed',
            'baseline_mjcf':model_xml(p,.002),'trials':trials,'timestep_peak_difference_nm':difference,'timestep_converged':stable,
            'scope':'1-second fixed-base idealized trajectory, uniform rigid solids, ideal torque actuators; no motor thermal/electrical or structural validation'}
