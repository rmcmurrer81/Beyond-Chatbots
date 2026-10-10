"""Lossless report-history container. No file or model work at import.

Root retains and authenticates every original wrapper/observer/process artifact
separately. This container carries the FULL four original reports and every new
report, including wrong answers. Contents are audit history, never model input.
"""
import hashlib
import json
import struct

MAGIC = b'NBCH219\x00'
HEADER = struct.Struct('<8sII')
ITEM = struct.Struct('<II')
MANIFEST_CAP, REPORT_CAP, HISTORY_CAP = 65536, 524288, 4194304
OLD_KEYS = ('217/baseline','217/train','217/blind-post','217/reopen')
NEW_KEYS = ('219/before-correction','219/correction-train','219/blind-post','219/reopen')


def need(ok, why):
    if not ok: raise RuntimeError(why)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def pack(manifest, entries):
    need(type(manifest) is bytes and 0 < len(manifest) <= MANIFEST_CAP and
         type(entries) is list and 4 <= len(entries) <= 8, 'Full finite history frame')
    expected = OLD_KEYS+NEW_KEYS[:len(entries)-4]
    parts = [HEADER.pack(MAGIC,len(manifest),len(entries)),manifest]
    for (name,raw),key in zip(entries,expected):
        need(type(name) is str and name==key and type(raw) is bytes and 0<len(raw)<=REPORT_CAP,
             'Exact ordered complete report history')
        key_raw=name.encode('ascii')
        parts.extend((ITEM.pack(len(key_raw),len(raw)),key_raw,raw))
    result=b''.join(parts)
    need(len(result)<=HISTORY_CAP, 'Complete history bound; never clip')
    return result


def unpack(raw):
    need(type(raw) is bytes and HEADER.size<=len(raw)<=HISTORY_CAP, 'Full bounded history bytes')
    magic,manifest_size,count=HEADER.unpack(raw[:HEADER.size])
    need(magic==MAGIC and 0<manifest_size<=MANIFEST_CAP and 4<=count<=8 and
         HEADER.size+manifest_size<=len(raw), 'History framing BEFORE any report allocation')
    at=HEADER.size; manifest=raw[at:at+manifest_size]; at+=manifest_size
    entries=[]; spans=[]
    for key in OLD_KEYS+NEW_KEYS[:count-4]:
        need(at+ITEM.size<=len(raw),'Entire history record header')
        name_size,size=ITEM.unpack(raw[at:at+ITEM.size]); at+=ITEM.size
        need(name_size==len(key) and 0<size<=REPORT_CAP and at+name_size+size<=len(raw),
             'Exact finite report extent BEFORE slice')
        need(raw[at:at+name_size]==key.encode('ascii'),'Original ordered history role')
        at+=name_size; spans.append((key,at,size)); entries.append((key,raw[at:at+size])); at+=size
    need(at==len(raw) and pack(manifest,entries)==raw,'Full history roundtrip with no trailing bytes')
    return manifest,entries,spans


def original(manifest, reports, owner, mode, previous):
    need(type(manifest) is bytes and 0<len(manifest)<=MANIFEST_CAP,'Bounded original manifest before parse')
    value=json.loads(manifest)
    need(type(value) is dict and set(value)=={'schema','owner','mode','archives'} and
         value['schema']=='newbrain.foundation219.original-history-manifest.v1' and value['owner']==owner and
         value['mode']==mode and type(value['archives']) is dict and
         set(value['archives'])=={'baseline','train','blind-post','reopen'}, 'Same-owner full original archive map')
    need(type(reports) is dict and set(reports)==set(value['archives']),'Four full original reports required')
    entries=[]
    for key in ('baseline','train','blind-post','reopen'):
        raw=reports[key]; pin=value['archives'][key]
        need(type(raw) is bytes and 0<len(raw)<=360448 and type(pin) is dict and
             set(pin)=={'path','bytes','sha256'} and pin['bytes']==len(raw) and pin['sha256']==sha(raw) and
             previous['archives'][key]['bytes']==len(raw) and previous['archives'][key]['sha256']==sha(raw),
             'Full original byte source and original metadata archive identity')
        entries.append(('217/'+key,raw))
    return entries


def append(manifest, entries, role, report, previous_raw=None):
    need(len(entries)-4<len(NEW_KEYS) and '219/'+role==NEW_KEYS[len(entries)-4], 'One exact next history role')
    result=pack(manifest,entries+[('219/'+role,report)])
    if previous_raw is not None:
        prior_manifest,prior_entries,_=unpack(previous_raw)
        need(prior_manifest==manifest and prior_entries==entries,'Every complete previous report byte retained')
        # Only the header's count changes. Everything else is an exact prefix.
        need(result[HEADER.size:len(previous_raw)]==previous_raw[HEADER.size:],
             'Exact serialized history payload prefix, not merely a digest')
    return result
