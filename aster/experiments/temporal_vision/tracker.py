"""Bounded causal pixel tracking, ordinary engineering rather than neural learning.

Only immutable RGB and a monotonic millisecond timestamp enter observe().
Track numbers are inferred local handles, never known physical identities.
"""
from dataclasses import asdict, dataclass
from functools import lru_cache
import hashlib
import json
import math
import time

from experiments.vision_lab.pixels import extract, frame

MODES = ('motion_appearance', 'appearance_last_position', 'nearest_position', 'reset')
MAX_TRACKS = 16
MAX_FRAMES = 64
TTL_MS = 800
MAX_SPEED = 0.04  # pixels per millisecond; a declared engineering prior
SCHEMA = 'aster.temporal-tracker.v1'


def center(box):
    return ((box[0] + box[2]) / 2, (box[1] + box[3]) / 2)


def appearance(component):
    sums = [sum(component.pixels[c::3]) for c in range(3)]
    total = sum(sums)
    return tuple(v / total if total else 0.0 for v in sums)


def distance(a, b):
    return math.hypot(a[0] - b[0], a[1] - b[1])


def appearance_distance(a, b):
    return sum(abs(x-y) for x,y in zip(a,b))


@dataclass
class Track:
    id: int
    x: float
    y: float
    vx: float
    vy: float
    last_ms: int
    color: tuple
    area: int
    observations: int
    ambiguous: bool = False


class Tracker:
    def __init__(self, mode='motion_appearance'):
        if mode not in MODES:
            raise ValueError('Closed tracking mode')
        self.mode = mode
        self.tracks = []
        self.last_ms = None
        self.next_id = 1
        self.frames = 0
        self.last_latency = None  # observation-only telemetry, never an association input

    def observe(self, raw, timestamp_ms):
        frame(raw)
        if type(timestamp_ms) is not int or not 0 <= timestamp_ms <= 1_000_000_000:
            raise ValueError('Bounded integer timestamp required')
        if self.last_ms is not None and timestamp_ms <= self.last_ms:
            raise ValueError('Timestamp must increase strictly; duplicates and replay refused')
        if self.frames >= MAX_FRAMES:
            raise ValueError('Frame budget exhausted')
        # Validate before mutation; extraction failure cannot consume a frame.
        started = time.perf_counter()
        components, extraction = extract(raw)
        extracted = time.perf_counter()
        tracks = [] if self.mode == 'reset' else [t for t in self.tracks if timestamp_ms-t.last_ms <= TTL_MS]
        points = [center(c.box) for c in components]
        colors = [appearance(c) for c in components]
        candidates = {}
        for i, c in enumerate(components):
            for j, t in enumerate(tracks):
                dt = timestamp_ms-t.last_ms
                if distance(points[i], (t.x,t.y)) > 2 + MAX_SPEED*dt:
                    continue
                if self.mode != 'nearest_position':
                    if appearance_distance(colors[i],t.color) > 0.20 or not 0.65 <= c.area/t.area <= 1.50:
                        continue
                predicted = (t.x,t.y)
                if self.mode == 'motion_appearance':
                    predicted = (t.x+t.vx*dt, t.y+t.vy*dt)
                candidates[i,j] = distance(points[i], predicted)
        blocked_detections, blocked_tracks = set(), set()
        if self.mode in ('motion_appearance','appearance_last_position'):
            # Multiple plausible same-appearance histories after missing data are
            # fundamentally ambiguous. Motion extrapolation is not evidence that
            # an unseen object continued in a straight line behind an occluder.
            for i in range(len(components)):
                possible = [j for j in range(len(tracks)) if (i,j) in candidates]
                if any(tracks[j].ambiguous for j in possible) or (
                    len(possible) > 1 and any(timestamp_ms-tracks[j].last_ms > 100 for j in possible)
                ):
                    blocked_detections.add(i); blocked_tracks.update(possible)
            # Propagate within this candidate component, without choosing by ID.
            changed = True
            while changed:
                changed = False
                for i,j in candidates:
                    if i in blocked_detections or j in blocked_tracks:
                        if i not in blocked_detections or j not in blocked_tracks:
                            changed = True
                        blocked_detections.add(i); blocked_tracks.add(j)
        allowed = {(i,j):v for (i,j),v in candidates.items()
                   if i not in blocked_detections and j not in blocked_tracks}

        @lru_cache(None)
        def solve(i, used):
            if i == len(components):
                return (0, 0.0, ())
            best = solve(i+1, used)
            for j in range(len(tracks)):
                if not used & (1 << j) and (i,j) in allowed:
                    n,cost,pairs = solve(i+1,used | (1 << j))
                    row = (n+1, cost-allowed[i,j], ((i,j),)+pairs)
                    if row[:2] > best[:2]:
                        best = row
            return best

        assignment = dict(solve(0,0)[2])
        # Ambiguous histories stay quarantined until expiry; they are not quietly
        # reassigned on the next frame merely because another candidate vanished.
        for j in blocked_tracks:
            tracks[j].ambiguous = True
        rows = []
        for i,c in enumerate(components):
            row = {'box':list(c.box), 'area':c.area, 'track_id':None,
                   'identity_status':'uncertain', 'reason':'ambiguous_history'}
            if i in assignment:
                t = tracks[assignment[i]]
                dt = timestamp_ms-t.last_ms
                vx = (points[i][0]-t.x)/dt; vy = (points[i][1]-t.y)/dt
                speed = math.hypot(vx,vy)
                if speed > MAX_SPEED:
                    vx *= MAX_SPEED/speed; vy *= MAX_SPEED/speed
                t.x,t.y = points[i]; t.vx,t.vy = vx,vy
                t.last_ms = timestamp_ms; t.color = colors[i]; t.area = c.area
                t.observations += 1
                row.update(track_id=t.id,identity_status='continued',reason='engineered_association')
            elif i not in blocked_detections:
                if len(tracks) < MAX_TRACKS:
                    t = Track(self.next_id,*points[i],0.0,0.0,timestamp_ms,colors[i],c.area,1)
                    self.next_id += 1; tracks.append(t)
                    row.update(track_id=t.id,identity_status='new',reason='new_local_track_not_prior_identity')
                else:
                    row['reason'] = 'track_capacity'
            rows.append(row)
        self.tracks = tracks; self.last_ms = timestamp_ms; self.frames += 1
        self.last_latency = {'extraction_seconds':extracted-started,'association_seconds':time.perf_counter()-extracted}
        return {'predictions':rows,'extraction':extraction}

    def to_bytes(self):
        payload = {'schema':SCHEMA, 'mode':self.mode, 'last_ms':self.last_ms,
                   'next_id':self.next_id,'frames':self.frames,
                   'tracks':[asdict(t) for t in self.tracks]}
        encoded = canonical(payload)
        return canonical({'payload':payload,'sha256':hashlib.sha256(encoded).hexdigest()})

    @classmethod
    def from_bytes(cls, raw):
        if type(raw) is not bytes or not 0 < len(raw) <= 16384:
            raise ValueError('Bounded immutable checkpoint required')
        try:
            def pairs(rows):
                d = {}
                for k,v in rows:
                    if k in d: raise ValueError('Duplicate checkpoint key')
                    d[k] = v
                return d
            wrapper = json.loads(raw,object_pairs_hook=pairs,
                                 parse_constant=lambda v: (_ for _ in ()).throw(ValueError('Nonfinite checkpoint')))
            if type(wrapper) is not dict or set(wrapper) != {'payload','sha256'}:
                raise ValueError('Closed checkpoint wrapper')
            p = wrapper['payload']
            if hashlib.sha256(canonical(p)).hexdigest() != wrapper['sha256']:
                raise ValueError('Checkpoint digest mismatch')
            if type(p) is not dict or set(p) != {'schema','mode','last_ms','next_id','frames','tracks'} or p['schema'] != SCHEMA:
                raise ValueError('Closed checkpoint schema')
            obj = cls(p['mode'])
            if not integer(p['frames'],0,MAX_FRAMES) or not integer(p['next_id'],1,p['frames']*8+1):
                raise ValueError('Invalid counters')
            if (p['frames']==0) != (p['last_ms'] is None) or (p['last_ms'] is not None and not integer(p['last_ms'],0,1_000_000_000)):
                raise ValueError('Invalid timestamp')
            if type(p['tracks']) is not list or len(p['tracks']) > MAX_TRACKS:
                raise ValueError('Track capacity')
            ids = set()
            for t in p['tracks']:
                if type(t) is not dict or set(t) != set(Track.__dataclass_fields__):
                    raise ValueError('Closed track schema')
                if not integer(t['id'],1,p['next_id']-1) or t['id'] in ids:
                    raise ValueError('Invalid track ID')
                ids.add(t['id'])
                if not integer(t['observations'],1,p['frames']) or not integer(t['area'],9,4096) or type(t['ambiguous']) is not bool:
                    raise ValueError('Invalid track metadata')
                if p['last_ms'] is None or not integer(t['last_ms'],max(0,p['last_ms']-TTL_MS),p['last_ms']):
                    raise ValueError('Stale or future track')
                if not all(number(t[k],0,64) for k in ('x','y')) or not all(number(t[k],-MAX_SPEED,MAX_SPEED) for k in ('vx','vy')):
                    raise ValueError('Invalid track geometry')
                if math.hypot(t['vx'],t['vy']) > MAX_SPEED + 1e-12:
                    raise ValueError('Invalid speed')
                if type(t['color']) is not list or len(t['color']) != 3 or not all(number(v,0,1) for v in t['color']) or (sum(t['color']) != 0 and abs(sum(t['color'])-1)>1e-9):
                    raise ValueError('Invalid appearance')
                obj.tracks.append(Track(**dict(t,color=tuple(t['color']))))
            if p['frames']==0 and (obj.tracks or p['next_id']!=1):
                raise ValueError('Nonempty zero-frame checkpoint')
            obj.last_ms=p['last_ms']; obj.next_id=p['next_id']; obj.frames=p['frames']
            return obj
        except (TypeError,KeyError,UnicodeError,OverflowError,RecursionError) as exc:
            raise ValueError('Invalid checkpoint') from exc


def integer(v, low, high):
    return type(v) is int and low <= v <= high


def number(v, low, high):
    return type(v) in (int,float) and math.isfinite(v) and low <= v <= high


def canonical(value):
    return json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False).encode('utf-8')
