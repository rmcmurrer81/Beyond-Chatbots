"""Fixed pixel engineering, not learned segmentation or general scene understanding.

Inference accepts exactly one 64x64 RGB byte frame. There is no camera, screen,
filesystem, annotation, prompt, temporal memory, model download or network input.
"""
from dataclasses import dataclass
import statistics

SIDE = 64
FRAME_BYTES = SIDE * SIDE * 3
THRESHOLD = 40
MIN_AREA = 9
MAX_COMPONENTS = 8


@dataclass(frozen=True)
class Component:
    box: tuple
    pixels: bytes
    area: int


def frame(raw):
    if type(raw) is not bytes or len(raw) != FRAME_BYTES:
        raise ValueError('Expected exactly 64x64 immutable RGB bytes')
    return raw


def masked_patch(raw, indices):
    """Tight pixel mask crop, aspect-preserving nearest resize into a black 32 frame.

    The same adapter is applied to observed components and the labeled oracle.
    A one-pixel border is maintained; no class or source tag enters the adapter.
    """
    frame(raw)
    indices = tuple(indices)
    if not indices or len(indices) > SIDE * SIDE or any(type(i) is not int or not 0 <= i < SIDE*SIDE for i in indices):
        raise ValueError('Expected a bounded nonempty pixel mask')
    xs = [i % SIDE for i in indices]; ys = [i // SIDE for i in indices]
    x0, y0, x1, y1 = min(xs), min(ys), max(xs)+1, max(ys)+1
    width, height = x1-x0, y1-y0
    scale = min(30/width, 30/height, 1.0)
    w, h = max(1, round(width*scale)), max(1, round(height*scale))
    left, top = (32-w)//2, (32-h)//2
    members = set(indices); output = bytearray(3072)
    for y in range(h):
        sy = y0 + min(height-1, y*height//h)
        for x in range(w):
            sx = x0 + min(width-1, x*width//w)
            index = sy*SIDE+sx
            if index in members:
                dst = ((top+y)*32+left+x)*3
                output[dst:dst+3] = raw[index*3:index*3+3]
    return Component((x0,y0,x1,y1), bytes(output), len(indices))


def extract(raw):
    """Median border background, max-channel contrast, 8-connectivity; fixed caps."""
    frame(raw)
    border = [i for i in range(SIDE*SIDE) if i//SIDE in (0,SIDE-1) or i%SIDE in (0,SIDE-1)]
    background = tuple(int(statistics.median(raw[3*i+c] for i in border)) for c in range(3))
    foreground = {i for i in range(SIDE*SIDE) if max(abs(raw[3*i+c]-background[c]) for c in range(3)) > THRESHOLD}
    components = []; discarded = 0
    while foreground:
        seed = min(foreground); foreground.remove(seed); queue=[seed]; indices=[]
        while queue:
            i=queue.pop(); indices.append(i); x,y=i%SIDE,i//SIDE
            for dy in (-1,0,1):
                for dx in (-1,0,1):
                    nx,ny=x+dx,y+dy
                    if 0<=nx<SIDE and 0<=ny<SIDE:
                        j=ny*SIDE+nx
                        if j in foreground:
                            foreground.remove(j); queue.append(j)
        if len(indices) < MIN_AREA:
            discarded += 1
        else:
            components.append(masked_patch(raw,indices))
            if len(components)>MAX_COMPONENTS:
                return (), {'reason':'component_limit', 'discarded_small':discarded, 'background':background}
    components.sort(key=lambda item:(item.box[1],item.box[0]))
    return tuple(components), {'reason':'components' if components else 'no_component', 'discarded_small':discarded, 'background':background}


def global_patch(raw):
    """Declared 64→32 nearest downsample; original model then crops nonzero pixels."""
    frame(raw)
    return b''.join(raw[((2*y)*SIDE+2*x)*3:((2*y)*SIDE+2*x)*3+3] for y in range(32) for x in range(32))
