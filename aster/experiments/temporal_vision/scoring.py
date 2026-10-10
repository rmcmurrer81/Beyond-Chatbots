"""Evaluator-only labels and fixed track ownership; never imported by inference."""
from collections import Counter
from experiments.vision_lab.scoring import match


class Evaluator:
    def __init__(self):
        self.seen = set()
        self.owner = {}
        self.established_truth = set()
        self.origin_ms = {}
        self.ambiguous_start_ms = {}
        self.last_id = {}
        self.histories = {}
        self.counts = Counter()

    def score(self, predictions, frame):
        pairs = match(predictions,frame.objects)
        matches = {j:i for i,j in pairs}
        counts = Counter(frames=1,expected=len(frame.objects),tp=len(pairs),
                         fp=len(predictions)-len(pairs),fn=len(frame.objects)-len(pairs))
        details=[]
        for j,obj in enumerate(frame.objects):
            truth = obj['truth_id']; p = predictions[matches[j]] if j in matches else None
            if truth in frame.ambiguous_ids:
                self.ambiguous_start_ms.setdefault(truth,frame.timestamp_ms)
            tid = None if p is None else p['track_id']
            eligible = truth in self.seen
            counts['eligible_identity'] += eligible
            correct=False; wrong=False; fresh=False
            if tid is not None:
                if tid not in self.owner:
                    # New IDs cannot acquire a known object's physical identity
                    # by consulting ground truth on a later frame.
                    self.owner[tid] = truth if truth not in self.established_truth else None
                    self.origin_ms[tid] = frame.timestamp_ms
                    if self.owner[tid] is not None: self.established_truth.add(truth)
                    fresh=True
                correct=self.owner[tid]==truth
                wrong=self.owner[tid] is not None and not correct
                if tid in self.owner and wrong:
                    counts['contaminated_instances']+=1
                if truth in self.last_id and self.last_id[truth]!=tid:
                    counts['identity_switches']+=1
                    counts['fragments']+=fresh
                self.last_id[truth]=tid
            if eligible:
                counts['identity_misses'] += p is None
                counts['identity_abstentions'] += p is not None and tid is None
                # Replacement/new ID is not a claim of old identity continuity.
                claim=tid is not None and p['identity_status']=='continued'
                counts['continuity_claims'] += claim
                counts['correct_continuations'] += claim and correct and not fresh
                counts['first_acquisitions'] += fresh and correct
                counts['wrong_continuations'] += claim and wrong
                counts['unanchored_continuations'] += claim and (self.owner.get(tid) is None or fresh)
                counts['new_identity_instances'] += tid is not None and p['identity_status']=='new'
                if truth in frame.ambiguous_ids:
                    counts['ambiguous_eligible']+=1
                    # Count claims only for tracks whose fixed owner is pre-event.
                    prior_claim=tid is not None and self.owner.get(tid) is not None and self.origin_ms[tid]<self.ambiguous_start_ms[truth]
                    counts['ambiguous_prior_claims'] += prior_claim
                    counts['ambiguous_no_prior_claim'] += not prior_claim
            self.histories[frame.timestamp_ms,truth] = {'track_id':tid,'correct':correct,'status':None if p is None else p['identity_status']}
            details.append({'truth_id':truth,'prediction_index':matches.get(j),'track_id':tid,
                            'eligible':eligible,'owner':self.owner.get(tid),'correct_origin':correct})
            self.seen.add(truth)
        self.counts.update(counts)
        return {'counts':dict(counts),'matches':pairs,'identities':details}

    def recovery(self, events):
        rows=[]
        for e in events:
            pre=self.histories.get((e['pre_ms'],e['truth_id']))
            established=bool(pre and pre['correct'] and pre['track_id'] is not None)
            successful=[]
            if established:
                for (ts,truth),v in self.histories.items():
                    if truth==e['truth_id'] and ts>=e['first_ms'] and v['track_id']==pre['track_id'] and v['correct']:
                        successful.append(ts)
            recovered_at=min(successful) if successful else None
            rows.append(dict(e,pre_established=established,pre_track_id=pre['track_id'] if pre else None,
                             recovered_ms=recovered_at,first_frame_success=recovered_at==e['first_ms'],
                             on_time_success=recovered_at is not None and recovered_at<=e['deadline_ms'],
                             recovery_latency_ms=None if recovered_at is None else recovered_at-e['first_ms']))
        return rows


def summarize(counts):
    out=dict(counts)
    def ratio(a,b): return counts.get(a,0)/counts.get(b,0) if counts.get(b,0) else None
    out['detection_precision']=counts.get('tp',0)/(counts.get('tp',0)+counts.get('fp',0)) if counts.get('tp',0)+counts.get('fp',0) else None
    out['detection_recall']=ratio('tp','expected')
    out['continuity_coverage']=ratio('continuity_claims','eligible_identity')
    out['correct_continuation_recall']=ratio('correct_continuations','eligible_identity')
    out['known_owner_error_over_all_continuity_claims']=ratio('wrong_continuations','continuity_claims')
    out['unanchored_continuation_rate']=ratio('unanchored_continuations','continuity_claims')
    claims=counts.get('correct_continuations',0)+counts.get('wrong_continuations',0)
    out['anchored_continuity_selective_error']=counts.get('wrong_continuations',0)/claims if claims else None
    return out
