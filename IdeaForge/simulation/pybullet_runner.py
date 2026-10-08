from __future__ import annotations
import json

def run_urdf(urdf_path,seconds=5.0,time_step=1/240):
    try:
        import pybullet as p
        import pybullet_data
    except ImportError:
        return {"status":"pybullet_not_installed","instruction":"Run InstallSimulationTools.bat"}
    cid=p.connect(p.DIRECT)
    try:
        p.setAdditionalSearchPath(pybullet_data.getDataPath())
        p.setGravity(0,0,-9.81); p.setTimeStep(time_step)
        p.loadURDF("plane.urdf")
        body=p.loadURDF(str(urdf_path),[0,0,0.5],useFixedBase=False)
        steps=int(seconds/time_step)
        for _ in range(steps): p.stepSimulation()
        pos,orn=p.getBasePositionAndOrientation(body)
        joints=p.getNumJoints(body)
        return {"status":"completed","seconds":seconds,"steps":steps,"base_position":pos,"base_orientation":orn,"joint_count":joints}
    finally:
        p.disconnect(cid)

if __name__=="__main__":
    import argparse
    p=argparse.ArgumentParser(); p.add_argument("urdf"); p.add_argument("--seconds",type=float,default=5); a=p.parse_args()
    print(json.dumps(run_urdf(a.urdf,a.seconds),indent=2))
