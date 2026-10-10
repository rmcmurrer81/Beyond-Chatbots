"""Lossless finite ledger of exposed teacher probes for the 221 methods.

No numerical imports, file IO, model calls or ranking at import. Full original
42-way BOS and after-teacher-word distributions, every returned scalar and
original clocks are encoded without rounding or dropped records. This is
exposed teacher data, not a fresh evaluation score or extra SGD update.
"""
import hashlib
import math
import struct
from datetime import datetime

METHODS = ('FUNCTIONAL_POOL', 'QUERY_SELECTION')
MODES = ('ON', 'OFF')
LABELS = ('a', 'b', 'c', 'unknown')
ROWS, VOCABULARY_SIZE = 9216, 42
MAGIC = b'NBPL228\x00'
HEADER = struct.Struct('<8sI32sBB')
ROW = struct.Struct('<HBBBBIBB?dQQ27s27s32s336s336s')
CAP = 8388608
FIELDS = ('schema','method','mode','cycle','new_pass','row','variant','pool_row','updates_completed',
    'chosen_label','expected_label','receptive_wrong','target_loss',
    'first_distribution','after_teacher_distribution','parameter_sha256','clock')


def need(ok, why):
    if not ok: raise ValueError(why)


def digest(value):
    need(type(value) is str and len(value) == 64 and
        all(c in '0123456789abcdef' for c in value), 'Full exact hash')
    return bytes.fromhex(value)


def utc(value):
    need(type(value) is str and len(value) == 27 and value.isascii() and value.endswith('Z'),
        'Full six-microsecond UTC stamp')
    parsed = datetime.fromisoformat(value[:-1]+'+00:00')
    need(parsed.isoformat(timespec='microseconds').replace('+00:00','Z') == value,
        'Canonical clock without lazy strptime import')
    return value.encode('ascii')


def distribution(value):
    need(type(value) is dict and set(value) == {'dtype','shape','raw_hex'} and
        value['dtype'] == '<f8' and value['shape'] == [VOCABULARY_SIZE] and
        type(value['raw_hex']) is str and len(value['raw_hex']) == VOCABULARY_SIZE*16,
        'Whole exact 42-way little-endian binary64 distribution')
    raw = bytes.fromhex(value['raw_hex'])
    need(raw.hex() == value['raw_hex'], 'Canonical whole raw probability bytes')
    values = struct.unpack('<42d', raw)
    need(all(math.isfinite(v) and 0 <= v <= 1 for v in values) and
        abs(sum(values)-1.0) <= 1e-12, 'Complete finite normalized probabilities')
    return raw


def pack(row):
    need(type(row) is dict and tuple(row) == FIELDS and
        row['schema'] == 'newbrain.method228.exposed-probe.v1' and
        row['method'] in METHODS and row['mode'] in MODES,
        'Closed original returned probe dictionary and insertion order')
    for key,lo,hi in (('cycle',0,63),('new_pass',0,2),('row',0,47),
        ('variant',0,3),('pool_row',0,239),('updates_completed',10720,12256)):
        need(type(row[key]) is int and lo<=row[key]<=hi,'Exact unit/variant/pool and global probe ordinals')
    variant=(3*row['cycle']+row['new_pass'])%4
    need(row['variant']==variant and row['pool_row']==(48+4*row['row']+variant) and
        row['updates_completed']==10720+24*row['cycle']+8*row['new_pass'],
        'One exact prescribed teacher variant at the interleaved pre-pass boundary')
    need(row['chosen_label'] in LABELS and row['expected_label'] in LABELS and
        type(row['receptive_wrong']) is bool and
        row['receptive_wrong']==(row['chosen_label']!=row['expected_label']) and
        type(row['target_loss']) is float and math.isfinite(row['target_loss']) and row['target_loss']>=0,
        'Full original receptive flag and stable teacher-target CE scalar')
    clock=row['clock']
    need(type(clock) is dict and tuple(clock)==('start_ns','end_ns','start_utc','end_utc') and
        all(type(clock[k]) is int and 0<=clock[k]<2**64 for k in ('start_ns','end_ns')) and
        clock['end_ns']>=clock['start_ns'],'Full ordered original physical clocks')
    return ROW.pack(row['cycle'],row['new_pass'],row['row'],row['variant'],row['pool_row'],
        row['updates_completed'],LABELS.index(row['chosen_label']),LABELS.index(row['expected_label']),
        row['receptive_wrong'],row['target_loss'],clock['start_ns'],clock['end_ns'],
        utc(clock['start_utc']),utc(clock['end_utc']),digest(row['parameter_sha256']),
        distribution(row['first_distribution']),distribution(row['after_teacher_distribution']))


def unpack(raw,method,mode):
    need(type(raw) is bytes and len(raw)==ROW.size and method in METHODS and mode in MODES,
        'Exact whole probe row and bound treatment/mode')
    v=ROW.unpack(raw)
    need(v[6]<len(LABELS) and v[7]<len(LABELS),'Exact receptive labels')
    row={'schema':'newbrain.method228.exposed-probe.v1','method':method,'mode':mode,
        'cycle':v[0],'new_pass':v[1],'row':v[2],'variant':v[3],'pool_row':v[4],
        'updates_completed':v[5],'chosen_label':LABELS[v[6]],'expected_label':LABELS[v[7]],
        'receptive_wrong':v[8],'target_loss':v[9],
        'first_distribution':{'dtype':'<f8','shape':[42],'raw_hex':v[15].hex()},
        'after_teacher_distribution':{'dtype':'<f8','shape':[42],'raw_hex':v[16].hex()},
        'parameter_sha256':v[14].hex(),
        'clock':{'start_ns':v[10],'end_ns':v[11],'start_utc':v[12].decode('ascii'),'end_utc':v[13].decode('ascii')}}
    need(pack(row)==raw,'Every bit, provenance, clock and dictionary order roundtrips')
    return row


class ProbeHold(Exception):
    def __init__(self, primary, retained):
        self.primary, self.retained = primary, retained
        super().__init__('Exposed probe ledger failed; original record and available partial ledger retained')


class ProbeLedger:
    def __init__(self, protocol, method, mode):
        self.protocol = digest(protocol)
        need(method in METHODS and mode in MODES, 'One actual selected method and mode')
        self.method, self.mode = method, mode
        self.rows, self.active = [], None

    def append(self, row, retained):
        retained['probe_ledger'] = self
        self.active = {'original_probe':row,'packed':None}; retained['probe_ledger_active'] = self.active
        try:
            need(len(self.rows) < ROWS and row['method'] == self.method and row['mode'] == self.mode,
                'Exactly one complete selected probe, no replacement')
            ordinal = (row['cycle']*3+row['new_pass'])*48+row['row']
            need(ordinal == len(self.rows), 'Every original ordered probe, including all wrong cases')
            raw = pack(row); self.active['packed'] = raw
            observed = unpack(raw,self.method,self.mode)
            need(observed == row and tuple(observed) == tuple(row), 'Whole returned dictionary preserved')
            if self.rows:
                prior = unpack(self.rows[-1],self.method,self.mode)
                need(prior['clock']['end_ns'] <= row['clock']['start_ns'], 'Actual probe clocks remain ordered')
            self.rows.append(raw); self.active = None
        except BaseException as primary:
            raise ProbeHold(primary,retained) from primary

    def state_bytes(self):
        need(type(self.rows) is list and len(self.rows) <= ROWS and
            all(type(r) is bytes and len(r) == ROW.size for r in self.rows),
            'Full finite probe ledger')
        result = HEADER.pack(MAGIC,len(self.rows),self.protocol,METHODS.index(self.method),MODES.index(self.mode))+b''.join(self.rows)
        need(len(result) <= HEADER.size+ROWS*ROW.size <= CAP, 'Complete whole ledger, never clipped')
        return result

    @classmethod
    def from_state_bytes(cls, raw, protocol, method, mode, retained):
        retained['probe_ledger_input_raw'] = raw
        need(type(raw) is bytes and HEADER.size <= len(raw) <= HEADER.size+ROWS*ROW.size,
            'Whole original ledger before allocation')
        magic,count,saved,meth,arm = HEADER.unpack(raw[:HEADER.size])
        need(magic == MAGIC and count <= ROWS and saved == digest(protocol) and
            meth == METHODS.index(method) and arm == MODES.index(mode) and
            len(raw) == HEADER.size+count*ROW.size, 'Full identity, order, count and extent')
        result = cls(protocol,method,mode); retained['probe_ledger_partial'] = result
        for i in range(count):
            row = unpack(raw[HEADER.size+i*ROW.size:HEADER.size+(i+1)*ROW.size],method,mode)
            result.append(row,retained)
        need(result.state_bytes() == raw, 'Every original ledger byte unchanged')
        return result
