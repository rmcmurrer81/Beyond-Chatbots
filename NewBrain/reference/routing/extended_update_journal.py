"""Lossless finite journal of original decoder update dictionaries and clocks.

No model, random seed, numerical import or file access at import. All original
update fields are reconstructed with exact binary64 bits and strict types.
"""
import hashlib
import math
import struct
from datetime import datetime

MAGIC = b'NBCJ001\x00'
MAX_ROWS = 16384
UPDATE_FIELDS = {'schema', 'loss', 'parameter_sha256_before', 'parameter_sha256_after',
                 'parameter_bytes_changed', 'gradient_norm', 'clip_multiplier',
                 'new_exposures', 'updates_completed', 'runtime_qualified'}
EXPOSURES = ('examples', 'prefix_tokens', 'target_tokens_including_eos')
ROW = struct.Struct('<dddI?III32s32s?QQ27s27s')
HEADER = struct.Struct('<8sI32s')


def need(ok, why):
    if not ok:
        raise ValueError(why)


def digest(value):
    need(type(value) is str and len(value) == 64 and
         all(c in '0123456789abcdef' for c in value), 'Exact hexadecimal digest')
    return bytes.fromhex(value)


def utc(value):
    need(type(value) is str and len(value) == 27 and value.isascii(), 'Six-microsecond UTC clock')
    parsed = datetime.fromisoformat(value[:-1]+'+00:00')
    need(parsed.isoformat(timespec='microseconds').replace('+00:00', 'Z') == value,
         'Canonical UTC clock; no lazy strptime import')
    return value.encode('ascii')


def pack(row, clock):
    need(type(row) is dict and set(row) == UPDATE_FIELDS and
         row['schema'] == 'newbrain.trained-dialogue.update.v1' and
         row['runtime_qualified'] is False, 'Original closed update schema')
    values = tuple(row[k] for k in ('loss', 'gradient_norm', 'clip_multiplier'))
    need(all(type(v) is float and math.isfinite(v) for v in values) and values[0] >= 0
         and values[1] >= 0 and 0 < values[2] <= 1, 'Original finite binary64 update scalars')
    need(type(row['updates_completed']) is int and 1 <= row['updates_completed'] <= MAX_ROWS
         and type(row['parameter_bytes_changed']) is bool, 'Original typed update counter/flag')
    counts = row['new_exposures']
    need(type(counts) is dict and set(counts) == set(EXPOSURES) and
         all(type(counts[k]) is int and 0 < counts[k] < 2**32 for k in EXPOSURES),
         'Complete typed original exposure dictionary')
    before, after = digest(row['parameter_sha256_before']), digest(row['parameter_sha256_after'])
    need(row['parameter_bytes_changed'] == (before != after), 'Original parameter change flag')
    need(type(clock) is dict and set(clock) == {'start_ns', 'end_ns', 'start_utc', 'end_utc'} and
         all(type(clock[k]) is int and 0 <= clock[k] < 2**64 for k in ('start_ns', 'end_ns'))
         and clock['end_ns'] >= clock['start_ns'], 'Ordered finite monotonic exposure clocks')
    return ROW.pack(*values, row['updates_completed'], row['parameter_bytes_changed'],
                    *(counts[k] for k in EXPOSURES), before, after, False,
                    clock['start_ns'], clock['end_ns'], utc(clock['start_utc']), utc(clock['end_utc']))


def unpack(raw):
    need(type(raw) is bytes and len(raw) == ROW.size, 'Exact complete journal row')
    v = ROW.unpack(raw)
    row = {'schema': 'newbrain.trained-dialogue.update.v1', 'loss': v[0],
           'parameter_sha256_before': v[8].hex(), 'parameter_sha256_after': v[9].hex(),
           'parameter_bytes_changed': v[4], 'gradient_norm': v[1], 'clip_multiplier': v[2],
           'new_exposures': dict(zip(EXPOSURES, v[5:8])), 'updates_completed': v[3],
           'runtime_qualified': v[10]}
    clock = {'start_ns': v[11], 'end_ns': v[12],
             'start_utc': v[13].decode('ascii'), 'end_utc': v[14].decode('ascii')}
    need(pack(row, clock) == raw, 'Exact row roundtrip, including signed zero and bool encoding')
    return row, clock


class UpdateJournal:
    def __init__(self, protocol):
        self.protocol = digest(protocol)
        self.rows, self.active = [], None

    def append(self, row, clock):
        self.active = {'original_update': row, 'clock': clock, 'packed': None}
        need(len(self.rows) < MAX_ROWS and row['updates_completed'] == len(self.rows)+1,
             'Complete fixed update order, no skipped counter')
        raw = pack(row, clock)
        self.active['packed'] = raw
        observed, observed_clock = unpack(raw)
        need(observed == row and tuple(observed) == tuple(row) and observed_clock == clock,
             'All original update fields and original insertion order retained')
        if self.rows:
            previous, prior_clock = unpack(self.rows[-1])
            need(previous['parameter_sha256_after'] == row['parameter_sha256_before'] and
                 prior_clock['end_ns'] <= clock['start_ns'], 'Complete parameter/clock chain')
        self.rows.append(raw)
        self.active = None

    def state_bytes(self):
        need(len(self.rows) <= MAX_ROWS, 'Finite full journal')
        return HEADER.pack(MAGIC, len(self.rows), self.protocol)+b''.join(self.rows)

    @classmethod
    def from_state_bytes(cls, raw, protocol):
        need(type(raw) is bytes and HEADER.size <= len(raw) <= HEADER.size+MAX_ROWS*ROW.size,
             'Finite complete binary journal extent')
        magic, count, saved_protocol = HEADER.unpack(raw[:HEADER.size])
        need(magic == MAGIC and type(count) is int and count <= MAX_ROWS and
             saved_protocol == digest(protocol) and len(raw) == HEADER.size+count*ROW.size,
             'Exact journal identity/count/protocol')
        result = cls(protocol)
        for index in range(count):
            start = HEADER.size+index*ROW.size
            row, clock = unpack(raw[start:start+ROW.size])
            result.append(row, clock)
        need(result.state_bytes() == raw, 'Entire ordered journal bytes unchanged on restore')
        return result

    def summary(self, initial_hash, final_hash):
        before, counts, losses = initial_hash, dict.fromkeys(EXPOSURES, 0), []
        changes = 0
        for raw in self.rows:
            row, _ = unpack(raw)
            need(row['parameter_sha256_before'] == before, 'Full update parameter chain')
            before = row['parameter_sha256_after']
            changes += row['parameter_bytes_changed']
            for key in counts:
                counts[key] += row['new_exposures'][key]
            losses.append(row['loss'])
        need(before == final_hash, 'Whole journal reaches the observed model')
        return {'updates': len(self.rows), 'parameter_changes': changes, 'exposures': counts,
                'loss_first': losses[0] if losses else None, 'loss_last': losses[-1] if losses else None,
                'loss_min': min(losses) if losses else None, 'loss_max': max(losses) if losses else None,
                'mixed_token_CE_is_not_generation_accuracy': True,
                'binary_sha256': hashlib.sha256(self.state_bytes()).hexdigest()}
