"""Pure prescribed wording assignment and fixed interleaving; no model or IO calls."""
import math
SCHEMA='newbrain.foundation228.method-order.v1'
METHODS=('FUNCTIONAL_POOL','QUERY_SELECTION')
LABELS=('a','b','c','unknown')
CYCLES,NEW_PASSES,BATCHES,BATCH_SIZE=64,3,6,8
STARTING_UPDATES,ADDED_UPDATES,ENDING_UPDATES=10720,1536,12256
FIXED_OFFSETS=tuple(tuple(range(i*8,(i+1)*8)) for i in range(6))

def need(v,why):
    if not v:raise ValueError(why)

def teacher_variant(method,cycle,new_pass):
    need(method in METHODS and type(cycle) is int and 0<=cycle<64 and
        type(new_pass) is int and 0<=new_pass<3,'One finite selected treatment boundary')
    return (3*cycle+new_pass)%4

def pool_row(method,cycle,new_pass,unit):
    need(type(unit) is int and 0<=unit<48,'Exact semantic teaching unit')
    return 48+4*unit+teacher_variant(method,cycle,new_pass)

def probe_update(method,cycle,new_pass):
    teacher_variant(method,cycle,new_pass)
    return STARTING_UPDATES+cycle*24+new_pass*8

def feedback_order(method,cycle,new_pass,packet):
    variant=teacher_variant(method,cycle,new_pass);expected=probe_update(method,cycle,new_pass)
    need(type(packet) is dict and set(packet)=={'schema','cycle','new_pass','completed_updates','parameter_sha256','variant','rows'} and
        packet['schema']=='newbrain.foundation228.exposed-feedback.v1' and packet['cycle']==cycle and
        type(packet['cycle']) is int and packet['new_pass']==new_pass and type(packet['new_pass']) is int and
        packet['completed_updates']==expected and type(packet['completed_updates']) is int and
        packet['variant']==variant and type(packet['variant']) is int,'Closed current selected-teacher feedback')
    digest=packet['parameter_sha256'];need(type(digest) is str and len(digest)==64 and all(c in '0123456789abcdef' for c in digest),'Full current parameter hash')
    rows=packet['rows'];need(type(rows) is list and len(rows)==48,'Complete selected48 teaching observations')
    by_row={}
    for row in rows:
        need(type(row) is dict and set(row)=={'row','variant','pool_row','receptive_wrong','target_loss'} and
            type(row['row']) is int and 0<=row['row']<48 and row['row'] not in by_row and
            type(row['variant']) is int and row['variant']==variant and type(row['pool_row']) is int and
            row['pool_row']==pool_row(method,cycle,new_pass,row['row']) and type(row['receptive_wrong']) is bool and
            type(row['target_loss']) is float and math.isfinite(row['target_loss']) and row['target_loss']>=0,
            'Each exact semantic unit and actual selected wording, including mistakes')
        by_row[row['row']]=row
    need(set(by_row)==set(range(48)),'No omitted, replaced or duplicated teacher probe')
    metrics=[]
    for batch,units in enumerate(FIXED_OFFSETS):
        losses=[by_row[u]['target_loss'] for u in units];maximum=max(losses)
        mean=0.0 if maximum==0 else sum(v/maximum for v in losses)/8*maximum
        need(math.isfinite(mean),'Full finite batch teacher loss')
        metrics.append({'batch':batch,'wrong_rows':sum(by_row[u]['receptive_wrong'] for u in units),'mean_target_loss':mean})
    return {'schema':SCHEMA,'method':method,'cycle':cycle,'new_pass':new_pass,
        'completed_updates':expected,'parameter_sha256':digest,'variant':variant,
        'pool_rows':[pool_row(method,cycle,new_pass,u) for u in range(48)],'batch_metrics':metrics,
        'chosen_order':list(range(6)),'mistake_count':sum(r['receptive_wrong'] for r in rows),
        'priority_basis':'prescribed_variant_and_fixed_interleaving_no_loss_ranking',
        'replacement':False,'extra_SGD_updates':0,'evaluation_rows_used':False}

def pass_blocks(method,new_pass,chosen_order):
    need(method in METHODS and type(new_pass) is int and 0<=new_pass<3 and
        type(chosen_order) is tuple and chosen_order==tuple(range(6)) and
        all(type(i) is int for i in chosen_order),'Exact fixed six-batch order')
    blocks=[]
    for slot,batch in enumerate(chosen_order):
        blocks.append(('new',batch))
        if slot in (2,5):blocks.append(('protected_old',2*new_pass+(slot==5)))
    return tuple(blocks)

def cycle_blocks(method,orders):
    need(type(orders) is tuple and len(orders)==3,'All three selected pass orders')
    blocks=tuple(item for p,order in enumerate(orders) for item in pass_blocks(method,p,order))
    need(len(blocks)==24 and all(blocks.count(('new',b))==3 and blocks.count(('protected_old',b))==1 for b in range(6)),
        'Exactly matched per-unit old/new presentation quotas')
    return blocks
