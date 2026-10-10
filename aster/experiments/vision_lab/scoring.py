"""Label-blind maximum-cardinality IoU matching and conservative denominators."""
from functools import lru_cache


def iou(a,b):
    intersection=max(0,min(a[2],b[2])-max(a[0],b[0]))*max(0,min(a[3],b[3])-max(a[1],b[1]))
    union=(a[2]-a[0])*(a[3]-a[1])+(b[2]-b[0])*(b[3]-b[1])-intersection
    return intersection/union if union else 0.0


def match(predictions,objects):
    if len(predictions)>8 or len(objects)>8:raise ValueError('Matching cap')
    @lru_cache(None)
    def solve(i,used):
        if i==len(predictions):return (0,0.0,())
        best=solve(i+1,used)
        for j,obj in enumerate(objects):
            overlap=iou(predictions[i]['box'],obj['box'])
            if not used&(1<<j) and overlap>=0.5:
                n,total,pairs=solve(i+1,used|(1<<j))
                candidate=(n+1,total+overlap,((i,j),)+pairs)
                if candidate[:2]>best[:2]:best=candidate
        return best
    return list(solve(0,0)[2])


def score(predictions,objects):
    colors=('red','green','blue');shapes=('square','circle','triangle','diamond')
    pairs=match(predictions,objects)
    result=dict(expected=len(objects),known=sum(o['known'] for o in objects),unknown=sum(not o['known'] for o in objects),
                tp=len(pairs),fp=len(predictions)-len(pairs),fn=len(objects)-len(pairs),matched_known=0,
                color_correct=0,shape_correct=0,joint_correct=0,accepted_correct=0,accepted_wrong=0,
                known_abstained=0,unsupported=0,unknown_matched=0,unknown_false_accept=0,
                accepted_predictions=sum(p['accepted'] for p in predictions),held_known=0,held_accepted_correct=0)
    for i,j in pairs:
        p,o=predictions[i],objects[j]
        if not o['known']:
            result['unknown_matched']+=1;result['unknown_false_accept']+=p['accepted'];continue
        result['matched_known']+=1
        color=colors[p['ids'][0]]==o['color'];shape=shapes[p['ids'][1]]==o['shape'];joint=color and shape
        result['color_correct']+=color;result['shape_correct']+=shape;result['joint_correct']+=joint
        result['accepted_correct']+=p['accepted'] and joint;result['accepted_wrong']+=p['accepted'] and not joint
        result['known_abstained']+=p['abstain'];result['unsupported']+=not p['supported']
        result['held_known']+=o['held_combination'];result['held_accepted_correct']+=o['held_combination'] and p['accepted'] and joint
    result['held_expected']=sum(o['known'] and o['held_combination'] for o in objects)
    matched_indices={i for i,j in pairs}
    result['accepted_spurious']=sum(p['accepted'] and i not in matched_indices for i,p in enumerate(predictions))
    result['unknown_frame']=int(result['unknown']>0)
    result['unknown_false_accept_frame']=int(result['unknown_false_accept']>0)
    # On wholly unknown frames, any accepted component counts even if unmatched.
    if result['unknown'] and not result['known']:
        result['unknown_false_accept_frame']=int(result['accepted_predictions']>0)
    known_matches={i for i,j in pairs if objects[j]['known']}
    result['unknown_unsafe_accept_frame']=int(result['unknown']>0 and any(p['accepted'] and i not in known_matches for i,p in enumerate(predictions)))
    result['exact_frame']=int(result['fp']==0 and result['fn']==0 and result['accepted_correct']==result['known'] and result['unknown_false_accept']==0)
    result['frames']=1
    return result,pairs


def total(rows):
    output={key:sum(r[key] for r in rows) for key in rows[0]} if rows else {}
    def ratio(a,b):return output[a]/output[b] if output[b] else None
    if output:
        output['detection_precision']=output['tp']/(output['tp']+output['fp']) if output['tp']+output['fp'] else None
        output['detection_recall']=ratio('tp','expected')
        output['correct_accepted_known_recall']=ratio('accepted_correct','known')
        output['known_matched_coverage']=(output['accepted_correct']+output['accepted_wrong'])/output['matched_known'] if output['matched_known'] else None
        output['known_all_coverage']=(output['accepted_correct']+output['accepted_wrong'])/output['known'] if output['known'] else None
        output['known_selective_error']=output['accepted_wrong']/(output['accepted_correct']+output['accepted_wrong']) if output['accepted_correct']+output['accepted_wrong'] else None
        output['matched_joint_accuracy']=ratio('joint_correct','matched_known')
        output['unknown_false_accept_frame_rate']=ratio('unknown_false_accept_frame','unknown_frame')
        output['unknown_unsafe_accept_frame_rate']=ratio('unknown_unsafe_accept_frame','unknown_frame')
        output['unknown_false_accept_matched_rate']=ratio('unknown_false_accept','unknown_matched')
        output['exact_frame_rate']=ratio('exact_frame','frames')
    return output
