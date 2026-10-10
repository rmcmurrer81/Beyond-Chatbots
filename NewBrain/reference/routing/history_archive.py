"""Complete original 219 history container plus four new common-review reports.

The full accepted original container, including its header and all eight old
reports, is embedded unchanged. Report bytes are audit history, never features.
Root separately retains original wrappers, observers, process and IO records.
"""
import hashlib
import struct
import original_history_archive as old

MAGIC=b'NBCH220\x00'
HEADER=struct.Struct('<8sII')
ITEM=struct.Struct('<II')
NEW_KEYS=('220/before-review','220/review-train','220/blind-post','220/reopen')
ORIGINAL_CAP=1048576
REPORT_CAP=524288
HISTORY_CAP=4194304
SELECTED_HISTORY_UPPER=2752512


def need(ok,why):
    if not ok:raise RuntimeError(why)


def sha(raw):return hashlib.sha256(raw).hexdigest()


def original(raw,selected_hash):
    need(type(raw) is bytes and 0<len(raw)<=ORIGINAL_CAP and sha(raw)==selected_hash,'Full exact selected original219 history bytes')
    manifest,entries,spans=old.unpack(raw)
    need(len(entries)==8 and tuple(k for k,_ in entries)==old.OLD_KEYS+old.NEW_KEYS,'All four217 plus four219 full original reports')
    return manifest,entries,spans


def pack(original_raw,entries):
    need(type(original_raw) is bytes and 0<len(original_raw)<=ORIGINAL_CAP and type(entries) is list and 1<=len(entries)<=4,
         'Complete original container and finite selected report extension')
    old.unpack(original_raw)
    parts=[HEADER.pack(MAGIC,len(original_raw),len(entries)),original_raw]
    for (name,raw),key in zip(entries,NEW_KEYS):
        need(name==key and type(raw) is bytes and 0<len(raw)<=REPORT_CAP,'Exact ordered full report')
        name_raw=name.encode('ascii');parts.extend((ITEM.pack(len(name_raw),len(raw)),name_raw,raw))
    result=b''.join(parts);need(len(result)<=HISTORY_CAP,'No clipped original or new history bytes')
    need(result[HEADER.size:HEADER.size+len(original_raw)]==original_raw,'Whole original container, including header, unchanged')
    return result


def unpack(raw):
    need(type(raw) is bytes and HEADER.size<=len(raw)<=HISTORY_CAP,'Whole common-review history frame')
    magic,size,count=HEADER.unpack(raw[:HEADER.size])
    need(magic==MAGIC and 0<size<=ORIGINAL_CAP and 1<=count<=4 and HEADER.size+size<=len(raw),'Exact framing before allocation')
    at=HEADER.size;original_raw=raw[at:at+size];at+=size
    old_manifest,old_entries,old_spans=old.unpack(original_raw)
    need(len(old_entries)==8,'All original eight report objects')
    entries=[];spans=[]
    for key in NEW_KEYS[:count]:
        need(at+ITEM.size<=len(raw),'Complete report header')
        kn,n=ITEM.unpack(raw[at:at+ITEM.size]);at+=ITEM.size
        need(kn==len(key) and 0<n<=REPORT_CAP and at+kn+n<=len(raw) and raw[at:at+kn]==key.encode('ascii'),
             'Exact original order and extent before report slice')
        at+=kn;spans.append((key,at,n));entries.append((key,raw[at:at+n]));at+=n
    need(at==len(raw) and pack(original_raw,entries)==raw,'Full original and added byte roundtrip')
    return original_raw,old_manifest,old_entries,entries,old_spans,spans


def append(original_raw,entries,role,report,previous_raw=None):
    need(len(entries)<4 and '220/'+role==NEW_KEYS[len(entries)],'One exact next common-review role')
    result=pack(original_raw,entries+[('220/'+role,report)])
    if previous_raw is not None:
        prior,_,_,prior_entries,_,_=unpack(previous_raw)
        need(prior==original_raw and prior_entries==entries,'All full earlier history objects retained')
        need(result[HEADER.size:len(previous_raw)]==previous_raw[HEADER.size:],
             'Only outer count changes; the entire prior payload is an exact byte prefix')
    return result
