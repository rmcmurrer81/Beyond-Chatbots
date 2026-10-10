"""Fresh-process read-only checkpoint probe. Internal lab helper, never production."""
import json
from pathlib import Path
import sys
from .source import load


def main():
    path,out=map(Path,sys.argv[1:])
    if path.is_symlink() or not path.is_file() or path.stat().st_size>32768:
        raise ValueError('Bounded ordinary checkpoint file required')
    data,model=load();network=model.FactorizedModel.from_bytes(path.read_bytes())
    rows=data.descriptors({'data_seed':20261006,'model_seed':13,'held_selector':0})['train']
    probes=tuple(data.render(rows[i]) for i in (0,15,31,47,63,79,95))
    with out.open('x',encoding='utf-8',newline='\n') as stream:
        json.dump({'digest':network.state_digest(),'predictions':network.predict(probes),'updates':network.updates},stream,allow_nan=False)
        stream.write('\n')


if __name__=='__main__':main()
