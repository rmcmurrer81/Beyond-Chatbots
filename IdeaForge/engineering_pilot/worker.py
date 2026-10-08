"""Private fixed operation dispatcher for killable expensive dependencies."""
import json
from pathlib import Path
import sys
import time


def search(p, deadline):
    from scipy.optimize import differential_evolution
    from .schema import cheap_checks
    variables = ('length_1_m','length_2_m','width_m')
    # Modest local changes around reviewed geometry; derived proposals, not measured facts.
    bounds = [(max(.05,p[k]*.9),min(.5,p[k]*1.1)) if k!='width_m'
              else (max(.01,p[k]*.9),min(.08,p[k]*1.1)) for k in variables]
    feasible = {}
    count = 0
    def objective(x):
        nonlocal count
        if time.monotonic() >= deadline: raise TimeoutError('Search budget exhausted')
        count += 1
        candidate = dict(p,**dict(zip(variables,map(float,x))))
        checks = cheap_checks(candidate)
        if checks['status']=='passed': feasible[tuple(x)] = candidate
        return checks['mass_kg'] + 1000*len(checks['violations'])
    objective([p[k] for k in variables])
    differential_evolution(objective,bounds,seed=7,maxiter=4,popsize=5,polish=False,workers=1)
    shortlist = sorted(feasible.values(),key=lambda x: (cheap_checks(x)['mass_kg'], x['length_1_m'],x['length_2_m'],x['width_m']))[:3]
    return {'status':'passed' if shortlist else 'failed','variables':list(variables),'bounds':bounds,
            'evaluations':count,'seed':7,'shortlist':shortlist,
            'meaning':'bounded sampled proposals; no global optimum claim; CAD and dynamics run only for shortlist'}


def main():
    request=json.load(sys.stdin)
    p=request['parameters']; deadline=time.monotonic()+request['seconds']
    try:
        if sys.argv[1]=='cad':
            from .cad import export
            result=export(p,Path(request['directory']))
        elif sys.argv[1]=='dynamics':
            from .dynamics import evaluate
            result=evaluate(p,deadline)
        elif sys.argv[1]=='search': result=search(p,deadline)
        else: raise ValueError('Unknown fixed operation')
    except ImportError as exc: result={'status':'unknown','reason':'optional dependency unavailable','detail':str(exc)}
    except TimeoutError as exc: result={'status':'unknown','reason':str(exc)}
    except Exception as exc: result={'status':'unknown','reason':'operation could not complete','detail':f'{type(exc).__name__}: {exc}'}
    print(json.dumps(result,allow_nan=False))

if __name__=='__main__': main()
