"""Evaluator-owned complete synthetic trajectories; never imported by tracker."""
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import random
from experiments.vision_lab.scenes import draw

PROTOCOL = json.loads(Path(__file__).with_name('PROTOCOL.json').read_text(encoding='utf-8'))
FAMILIES = ('separated','near_crossing','occlusion','distractor','overlap',
            'appearance_change','frame_gap','ambiguous_stay','ambiguous_swap')


@dataclass(frozen=True)
class Frame:
    timestamp_ms: int
    rgb: bytes
    objects: tuple
    hidden_ids: tuple
    ambiguous_ids: tuple


@dataclass(frozen=True)
class Sequence:
    sequence_id: str
    family: str
    frames: tuple
    events: tuple
    parameters: dict


def sequences(split):
    if split not in ('development','heldout'):
        raise ValueError('Closed split')
    config = PROTOCOL['splits'][split]
    out = []
    for variant in range(config['variants']):
        # Appearance, position and timing vary together by a preregistered split;
        # entire streams, not sampled neighboring frames, are evaluation units.
        r = config['radii'][variant % len(config['radii'])]
        speed = config['speeds'][variant % len(config['speeds'])]
        offset = config['offsets'][variant % len(config['offsets'])]
        level = config['levels'][variant % len(config['levels'])]
        bg = config['backgrounds'][variant % len(config['backgrounds'])]
        for family in FAMILIES:
            # Twins use the same pixel generator seed, never their hidden IDs.
            pixel_family = 'ambiguous' if family.startswith('ambiguous') else family
            rng = random.Random(f'{config["seed"]}:{variant}:{pixel_family}')
            frames = []
            for k in range(24):
                if family == 'frame_gap' and k in config['dropped_ticks']:
                    continue
                moving_x = round(10+offset+speed*k)
                y = 18+offset
                specs = [('a','red','square',moving_x,y,r,level),
                         ('b','blue','circle',53-offset-round(speed*k),45-offset,r,level)]
                hidden = []; ambiguous = []
                if family in ('near_crossing','frame_gap'):
                    specs = [('a','red','square',moving_x,24-offset,r,level),
                             ('b','red','square',53-offset-round(speed*k),37+offset,r,level)]
                elif family == 'occlusion':
                    if k in config['hidden_ticks']:
                        hidden = ['a']
                elif family == 'distractor':
                    if 7 <= k <= 17:
                        specs.append(('c','green','triangle',32+offset,44-offset,r,level))
                    if k in config['hidden_ticks']:
                        hidden = ['a']
                elif family == 'overlap':
                    specs = [('a','red','square',moving_x,30,r,level),
                             ('b','blue','circle',53-offset-round(speed*k),30,r,level)]
                elif family == 'appearance_change':
                    if k >= 12:
                        specs[0] = ('a','green','square',moving_x,y,r,level)
                elif family.startswith('ambiguous'):
                    specs = [('a','red','square',23+offset,30,r,level),
                             ('b','red','square',42-offset,30,r,level)]
                    if 8 <= k <= 11:
                        hidden = ['a','b']
                    if k >= 12:
                        ambiguous = ['a','b']
                        if family == 'ambiguous_swap':
                            # Only evaluator identity changes. Input RGB stays
                            # exactly equal, with unchanged object drawing order.
                            specs = [tuple(['b']+list(specs[0][1:])),tuple(['a']+list(specs[1][1:]))]
                shown = [s for s in specs if s[0] not in hidden]
                raw,truth,masks = draw([s[1:] for s in shown],bg,0,0,rng)
                objects = []
                for spec,obj,mask in zip(shown,truth,masks):
                    # Visible-mask bbox, minimum nine visible pixels; objects
                    # completely hidden are not false negatives for detection.
                    if len(mask) >= 9:
                        xs=[i%64 for i in mask];ys=[i//64 for i in mask]
                        objects.append(dict(obj,truth_id=spec[0],box=[min(xs),min(ys),max(xs)+1,max(ys)+1],visible_area=len(mask)))
                frames.append(Frame(k*100,raw,tuple(objects),tuple(hidden),tuple(ambiguous)))
            events = []
            if family in ('occlusion','distractor'):
                h = config['hidden_ticks']
                events.append({'truth_id':'a','pre_ms':(min(h)-1)*100,'first_ms':(max(h)+1)*100,
                               'deadline_ms':(max(h)+3)*100,'ambiguous':False})
            if family.startswith('ambiguous'):
                events.extend({'truth_id':i,'pre_ms':700,'first_ms':1200,'deadline_ms':1400,'ambiguous':True} for i in ('a','b'))
            out.append(Sequence(f'{split}-{family}-{variant:02}',family,tuple(frames),tuple(events),
                                dict(radius=r,speed=speed,offset=offset,level=level,background=bg)))
    return tuple(out)


def receipt(sequence):
    return {'sequence_id':sequence.sequence_id,'family':sequence.family,
            'parameters':sequence.parameters,'events':sequence.events,
            'stream_sha256':stream_digest(sequence),
            'frames':[{'timestamp_ms':f.timestamp_ms,'rgb_sha256':hashlib.sha256(f.rgb).hexdigest(),
                       'objects':f.objects,'hidden_ids':f.hidden_ids,'ambiguous_ids':f.ambiguous_ids} for f in sequence.frames]}


def stream_digest(sequence):
    h=hashlib.sha256()
    for f in sequence.frames:
        h.update(f.timestamp_ms.to_bytes(8,'big'));h.update(f.rgb)
    return h.hexdigest()
