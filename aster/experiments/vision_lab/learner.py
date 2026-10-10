"""Fresh supervised lab models; original model and optimizer remain unmodified."""
import hashlib
from .pixels import extract,global_patch,masked_patch


def train(data,model,seed,binding):
    descriptors=data.descriptors(dict(binding,model_seed=seed))
    rows=descriptors['train'];frames=tuple(data.render(r) for r in rows)
    labels=tuple((r[0],r[1]) for r in rows)
    network=model.FactorizedModel(seed)
    schedule=data.cyclic_indices(96,3840,binding['data_seed']^0x52455631)
    losses=[]
    for update in range(320):
        indices=schedule[update*12:(update+1)*12]
        loss=network.teach(tuple(frames[i] for i in indices),tuple(labels[i] for i in indices),lambda *_:None)
        if update%32==0 or update==319:losses.append([update+1,loss])
    return network,Nearest(model,frames,labels),frames,labels,losses


class Nearest:
    """Independent nearest shape/color exemplars; no optimizer or confidence score."""
    def __init__(self,model,frames,labels):
        self.model=model;self.labels=labels
        features=[model.encode(x) for x in frames]
        self.s=model.np.stack([x[0] for x in features]);self.c=model.np.stack([x[1] for x in features])

    def predict(self,frames):
        s,c=self.model.inputs(frames)
        si=((s[:,None,:]-self.s[None,:,:])**2).sum(axis=2).argmin(axis=1)
        ci=((c[:,None,:]-self.c[None,:,:])**2).sum(axis=2).argmin(axis=1)
        return tuple({'ids':(self.labels[int(ci[i])][0],self.labels[int(si[i])][1]),'confidence':None,'abstain':False} for i in range(len(frames)))


def prediction_rows(predictor,components):
    if not components:return []
    rows=predictor.predict(tuple(c.pixels for c in components))
    return [{'box':list(c.box),'area':c.area,'ids':list(p['ids']),
             'confidence':None if p['confidence'] is None else list(p['confidence']),
             'abstain':p['abstain'],'supported':p['ids'][1]<3,
             'accepted':not p['abstain'] and p['ids'][1]<3} for c,p in zip(components,rows)]


def predict(predictor,raw):
    components,extraction=extract(raw)
    return {'predictions':prediction_rows(predictor,components),'extraction':extraction}


def global_predict(predictor,raw):
    p=predictor.predict((global_patch(raw),))[0]
    return {'ids':list(p['ids']),'confidence':list(p['confidence']),'abstain':p['abstain'],
            'supported':p['ids'][1]<3,'accepted':not p['abstain'] and p['ids'][1]<3}


def oracle_predict(predictor,raw,masks):
    # Ground-truth visible masks are only for this evaluator diagnostic.
    return prediction_rows(predictor,tuple(masked_patch(raw,m) for m in masks if m))
