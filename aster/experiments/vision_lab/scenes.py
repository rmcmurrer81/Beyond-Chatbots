"""Evaluator-owned invented raster grammar. Never imported by pixel inference."""
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import random
from .pixels import SIDE

PROTOCOL = json.loads(Path(__file__).with_name('PROTOCOL.json').read_text(encoding='utf-8'))
KNOWN_COLORS = ('red','green','blue')
KNOWN_SHAPES = ('square','circle','triangle')


@dataclass(frozen=True)
class Observation:
    source_id: str
    source_kind: str
    frame_index: int
    timestamp_ms: int
    rgb: bytes


@dataclass(frozen=True)
class Case:
    case_id: str
    family: str
    observation: Observation
    objects: tuple
    visible_masks: tuple
    detail: str


def inside(shape,x,y,r):
    if shape=='square': return abs(x)<=r and abs(y)<=r
    if shape=='circle': return x*x+y*y<=r*r
    if shape=='triangle': return -r<=y<=r and abs(x)<=(y+r)//2
    if shape=='diamond': return abs(x)+abs(y)<=r
    if shape=='ellipse': return 4*x*x+y*y<=r*r
    raise ValueError('Unknown synthetic shape')


def color_rgb(color,level):
    if color in KNOWN_COLORS:
        value=[0,0,0];value[KNOWN_COLORS.index(color)]=level;return tuple(value)
    if color=='yellow':return (level,level,0)
    if color=='cyan':return (0,level,level)
    if color=='gray':return (level,level,level)
    raise ValueError('Unknown synthetic color')


def draw(objects,bg,gradient,noise,rng,pattern=False,bridge=False,speckles=False):
    raw=bytearray(SIDE*SIDE*3);owner=[-1]*(SIDE*SIDE)
    for y in range(SIDE):
        for x in range(SIDE):
            delta=round(gradient*(2*x/(SIDE-1)-1))+(50 if pattern and (x//5)%2 else 0)
            for c in range(3):raw[3*(y*SIDE+x)+c]=max(0,min(255,bg+delta+rng.randint(-noise,noise)))
    rows=[]
    for j,(color,shape,cx,cy,r,level) in enumerate(objects):
        covered=[];rgb=color_rgb(color,level)
        for y in range(max(0,cy-r),min(SIDE,cy+r+1)):
            for x in range(max(0,cx-r),min(SIDE,cx+r+1)):
                if inside(shape,x-cx,y-cy,r):
                    i=y*SIDE+x;covered.append(i);owner[i]=j
                    for c in range(3):raw[3*i+c]=max(0,min(255,rgb[c]+rng.randint(-noise,noise)))
        xs=[i%SIDE for i in covered];ys=[i//SIDE for i in covered]
        rows.append({'color':color,'shape':shape,'box':(min(xs),min(ys),max(xs)+1,max(ys)+1),
                     'known':color in KNOWN_COLORS and shape in KNOWN_SHAPES,
                     'held_combination':color in KNOWN_COLORS and shape in KNOWN_SHAPES and
                         (KNOWN_COLORS.index(color)+KNOWN_SHAPES.index(shape))%3==0})
    if bridge:
        for x in range(21,44):raw[(31*SIDE+x)*3:(31*SIDE+x)*3+3]=bytes((240,0,0))
    if speckles:
        for _ in range(40):
            i=rng.randrange(SIDE*SIDE);raw[3*i:3*i+3]=bytes((255,255,255))
    masks=tuple(tuple(i for i,j in enumerate(owner) if j==k) for k in range(len(objects)))
    return bytes(raw),tuple(rows),masks


def cases(split):
    if split not in ('development','heldout'):raise ValueError('Closed split')
    dev=split=='development';seed=PROTOCOL['development_seed' if dev else 'heldout_seed'];rng=random.Random(seed)
    radii=(5,6) if dev else (4,7,9);levels=(192,224) if dev else (172,240)
    backgrounds=(0,45) if dev else (25,65,205)
    gradient,noise=(5,3) if dev else (12,8)
    output=[]
    def add(family,objects,bg=0,g=0,n=0,detail='',**kwargs):
        raw,truth,masks=draw(objects,bg,g,n,rng,**kwargs)
        index=len(output)
        source='synthetic-screen' if family=='screen_proxy' else 'synthetic-camera' if family=='camera_proxy' else 'synthetic-control'
        obs=Observation(f'{split}-{source}',source,index,index*100,raw)
        output.append(Case(f'{split}-{family}-{index:03}',family,obs,truth,masks,detail))
    for family in ('clean','camera_proxy'):
        for k in range(36):
            c,s=KNOWN_COLORS[k%3],KNOWN_SHAPES[(k//3)%3]
            cx,cy=11+2*rng.randrange(22),11+2*rng.randrange(22)
            r=radii[(k//9)%len(radii)];level=levels[k%2]
            add(family,[(c,s,cx,cy,r,level)],bg=backgrounds[(k//9+k%3+(k//3)%3)%len(backgrounds)] if family=='camera_proxy' else 0,
                g=gradient if family=='camera_proxy' else 0,n=noise if family=='camera_proxy' else 0)
    for k in range(24):
        dx,dy=2*(k//6),2*(k%2)
        centers=[(15+dx,15+dy),(47+dx,15+dy),(15+dx,47+dy),(47+dx,47+dy)];rng.shuffle(centers)
        count=2+k%3;objects=[]
        for j,(cx,cy) in enumerate(centers[:count]):
            objects.append((KNOWN_COLORS[(k+j)%3],KNOWN_SHAPES[(k//3+j)%3],cx,cy,radii[(k//9+j)%len(radii)],levels[j%2]))
        add('screen_proxy',objects,bg=backgrounds[(k//3)%len(backgrounds)],detail=f'{count} separated objects')
    for k in range(18):
        add('unknown_shape',[(KNOWN_COLORS[k%3],('diamond','ellipse')[k%2],23+2*(k//6),27+2*(k%3),radii[k%len(radii)],levels[k%2])],bg=backgrounds[(k//3)%len(backgrounds)])
        add('unknown_color',[(('yellow','cyan','gray')[k%3],KNOWN_SHAPES[(k//3)%3],23+2*(k//6),27+2*(k%3),radii[k%len(radii)],levels[k%2])],bg=backgrounds[(k//3)%len(backgrounds)])
    for k in range(12):
        add('mixed_unknown',[(KNOWN_COLORS[k%3],KNOWN_SHAPES[k%3],15,31,7,240),
                             ('yellow' if k%2 else KNOWN_COLORS[k%3],'circle' if k%2 else 'diamond',47,31+2*(k//6),7,240)],bg=backgrounds[(k//3)%len(backgrounds)])
        add('blank',[],bg=backgrounds[(k//3)%len(backgrounds)],g=gradient,n=noise,detail='background-only gradient and noise')
    for k in range(36):
        mode=k%9;c=KNOWN_COLORS[(k//9)%3];s=KNOWN_SHAPES[k%3];objects=[(c,s,31,31,7,240)]
        kwargs={};bg=65;detail=('border_contact','low_contrast','striped_background','same_color_touching','different_color_touching','overlap','speckles','thin_bridge','near_background_object')[mode]
        if mode==0:objects=[(c,s,1,31,9,240)]
        elif mode==1:objects=[('gray',s,31,31,7,90)]
        elif mode==2:kwargs['pattern']=True
        elif mode in (3,4):objects=[(c,'square',24,31,7,240),(c if mode==3 else KNOWN_COLORS[(KNOWN_COLORS.index(c)+1)%3],'circle',39,31,7,240)]
        elif mode==5:objects=[(c,s,28,31,9,240),(KNOWN_COLORS[(k+1)%3],'circle',35,31,9,172)]
        elif mode==6:kwargs['speckles']=True
        elif mode==7:objects=[(c,'square',15,31,7,240),(c,'circle',49,31,7,240)];kwargs['bridge']=True
        else:bg=0;objects=[(c,s,31,31,7,30)]
        add('stress',objects,bg=bg,n=1,detail=detail,**kwargs)
    expected=PROTOCOL['heldout_families']
    if any(sum(c.family==family for c in output)!=count for family,count in expected.items()):raise AssertionError('Frozen case counts')
    hashes=[hashlib.sha256(c.observation.rgb).hexdigest() for c in output]
    if len(set(hashes))!=len(hashes):raise AssertionError('Duplicate images inside split: '+str([(c.case_id,hashes.index(h)) for c,h in zip(output,hashes) if hashes.index(h)!=output.index(c)]))
    return tuple(output)


def receipt(case):
    o=case.observation
    return {'case_id':case.case_id,'family':case.family,'detail':case.detail,'source_id':o.source_id,
            'source_kind':o.source_kind,'frame_index':o.frame_index,'timestamp_ms':o.timestamp_ms,'clock_domain':'synthetic_case_index_100ms; not a video sequence or capture clock',
            'rgb_sha256':hashlib.sha256(o.rgb).hexdigest(),'objects':case.objects}
