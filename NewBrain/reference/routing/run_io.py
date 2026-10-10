"""Observed IO with separate normal/emergency accounts for fresh jobs210-v02.

Source-only until the root reviews and launches it. No native peak, startup or
hostile-process sandbox guarantee. Earlier attempts and reporting caps remain.
"""
import hashlib
import json
import os
from pathlib import Path
import stat
import sys
import time
import types

APPLICATION_CAP = 83886080
EMERGENCY_CAP = 167772160
COMBINED_APPLICATION_CAP = 251658240
SOURCE_CAP = 67108864
ENTRY_CAP = 4194304


def need(ok, why):
    if not ok:
        raise RuntimeError(why)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'),
                      ensure_ascii=True, allow_nan=False).encode('ascii')


class ProductPreflightError(RuntimeError):
    def __init__(self, detail):
        self.detail = detail
        super().__init__('Entire product/readback preflight: '+canonical(detail).decode('ascii'))


class RunIO:
    def __init__(self, output, stop):
        self.output, self.stop = Path(output).resolve(), Path(stop).resolve()
        self.started = time.perf_counter()
        self.application = self.emergency = self.source = 0
        self.rows, self.observer_rows = [], []
        self.failure_details, self.failed_products = [], []
        self.phase = 'created'
        need(self.output.is_dir(), 'Root must create fresh output directory')
        need(sys.version_info[:3] == (3, 14, 4) and sys.flags.isolated == 1 and
             sys.flags.no_site == 1 and sys.flags.ignore_environment == 1 and
             sys.flags.no_user_site == 1 and sys.dont_write_bytecode, 'Verified -I -S -B runtime')

    def charge(self, n, source=False, *, emergency=False):
        need(type(n) is int and n >= 0 and not (source and emergency), 'Exact complete owned cost')
        field, cap = ('source', SOURCE_CAP) if source else (
            ('emergency', EMERGENCY_CAP) if emergency else ('application', APPLICATION_CAP))
        value = getattr(self, field) + n
        need(value <= cap, 'Complete cumulative '+field+' IO exceeded; no borrowing or clipping')
        if not source:
            total = self.application+self.emergency+n
            need(total <= COMBINED_APPLICATION_CAP, 'Complete combined application IO exceeded')
        setattr(self, field, value)

    def read(self, path, cap, source=False, *, emergency=False):
        self.charge(cap+1, source, emergency=emergency)
        fd, primary, close_error, raw = None, None, None, None
        try:
            path = Path(path)
            before = path.lstat()
            need(stat.S_ISREG(before.st_mode) and before.st_nlink == 1 and
                 not getattr(before, 'st_file_attributes', 0) & 1024 and
                 before.st_size <= cap, 'Complete own plain input')
            fd = os.open(path, os.O_RDONLY | getattr(os, 'O_BINARY', 0))
            a = os.fstat(fd)
            need((a.st_dev,a.st_ino,a.st_size,a.st_mtime_ns,a.st_nlink) ==
                 (before.st_dev,before.st_ino,before.st_size,before.st_mtime_ns,before.st_nlink),
                 'Actual path/descriptor bridge')
            raw = os.read(fd, cap+1)
            b, after = os.fstat(fd), path.lstat()
            view = lambda s: (s.st_dev,s.st_ino,s.st_size,s.st_mtime_ns,s.st_ctime_ns,s.st_nlink)
            need(view(a) == view(b) and view(before) == view(after) and len(raw) == a.st_size,
                 'Actual full input changed/short read')
        except BaseException as error:
            primary = error
        finally:
            if fd is not None:
                try: os.close(fd)
                except BaseException as error: close_error = error
            self.rows.append({'kind':'source-read' if source else 'application-read',
                'account':'source' if source else ('emergency' if emergency else 'normal'),
                'path':str(path),'requested':cap+1,'returned':len(raw) if type(raw) is bytes else None,
                'close_attempted':fd is not None,'close_acknowledged':fd is not None and close_error is None,
                'primary_type':type(primary).__name__ if primary else None,
                'close_error_type':type(close_error).__name__ if close_error else None})
        if primary is not None:
            if close_error is not None:
                raise BaseExceptionGroup('Original read+close failures',[primary,close_error])
            raise primary
        if close_error is not None: raise close_error
        return raw

    def write(self, name, raw, cap, *, emergency=False):
        # Record each conjunct and the exact already-encoded payload before any
        # write. Failure custody has a different fixed account, never a reset.
        account, bound = ('emergency',EMERGENCY_CAP) if emergency else ('application',APPLICATION_CAP)
        charged = getattr(self,account)
        basename_ok = type(name) is str and Path(name).name == name and name not in ('.','..')
        raw_ok = type(raw) is bytes
        cap_ok = type(cap) is int and cap > 0
        length = len(raw) if raw_ok else None
        cost = length+cap+1 if raw_ok and cap_ok else None
        conjuncts = {'owned_basename':basename_ok,'raw_exact_bytes':raw_ok,
                     'cap_positive_exact_int':cap_ok,
                     'payload_fits_role_cap':raw_ok and cap_ok and length <= cap,
                     'complete_write_readback_fits_account':cost is not None and charged+cost <= bound,
                     'complete_write_readback_fits_combined':cost is not None and
                        self.application+self.emergency+cost <= COMBINED_APPLICATION_CAP}
        detail = {'name':name if type(name) is str else None,'phase':self.phase,
                  'raw_type':type(raw).__name__,'encoded_payload_length':length,
                  'role_cap':cap if type(cap) is int else None,'readback_requested':cap+1 if cap_ok else None,
                  'complete_product_readback_cost':cost,'account':account,'already_charged':charged,
                  'account_cap':bound,'normal_charged':self.application,'emergency_charged':self.emergency,
                  'combined_cap':COMBINED_APPLICATION_CAP,'conjuncts':conjuncts}
        if not all(conjuncts.values()):
            self.failure_details.append(detail)
            if not emergency:
                self.failed_products.append({'name':detail['name'],'raw':raw if raw_ok else None,'detail':detail})
            raise ProductPreflightError(detail)
        self.charge(length, emergency=emergency)
        path = self.output/name
        fd, primary, close_error = None, None, None
        try:
            fd = os.open(path, os.O_WRONLY|os.O_CREAT|os.O_EXCL|getattr(os,'O_BINARY',0),0o600)
            need(os.write(fd,raw) == length, 'Partial original write retained as failure')
            os.fsync(fd)
        except BaseException as error: primary = error
        finally:
            if fd is not None:
                try: os.close(fd)
                except BaseException as error: close_error = error
            self.rows.append({'kind':'application-write','account':'emergency' if emergency else 'normal',
                'path':str(path),'requested':length,
                'close_attempted':fd is not None,'close_acknowledged':fd is not None and close_error is None,
                'primary_type':type(primary).__name__ if primary else None,
                'close_error_type':type(close_error).__name__ if close_error else None})
        try:
            if primary is not None:
                if close_error is not None: raise BaseExceptionGroup('Original write+close failures',[primary,close_error])
                raise primary
            if close_error is not None: raise close_error
            need(self.read(path,cap,emergency=emergency) == raw,'Full saved-byte readback differs')
        except BaseException:
            if not emergency:
                self.failed_products.append({'name':name,'raw':raw,'detail':detail})
            raise
        return {'path':str(path),'bytes':length,'sha256':hashlib.sha256(raw).hexdigest()}

    def checkpoint(self, phase, counts=None):
        self.phase = phase
        elapsed = time.perf_counter()-self.started
        need(elapsed <= 42, 'Observed42-second local work boundary')
        if self.stop.exists():
            reason = self.read(self.stop,4096)
            raise RuntimeError('Root cooperative stop: '+repr(reason))
        need(len(self.observer_rows) < 12288,'Finite full observer record')
        row={'phase':phase,'counts':dict(counts) if counts is not None else None,
             'local_elapsed_seconds':elapsed}
        need(len(canonical(row))<=256,'Complete selected observer row bound; never clip')
        self.observer_rows.append(row)

    def census(self):
        need(len(sys.modules)<=1024,'Finite actual module census before snapshot')
        snapshot=tuple(sys.modules.items()); names=tuple(n for n,_ in snapshot)
        files, lookup, modules = [], {}, []
        for name,module in snapshot:
            self.checkpoint('observed-module-census')
            if module is None: modules.append([name,None,None]);continue
            need(type(module) is types.ModuleType,'Observed ordinary module')
            filename=vars(module).get('__file__');spec=vars(module).get('__spec__')
            origin=getattr(spec,'origin',None) if spec is not None else None
            if filename is None: index=None
            else:
                need(type(filename) is str,'Actual file origin string')
                path=Path(filename).resolve();key=str(path)
                if key not in lookup:
                    size=path.stat().st_size
                    raw=self.read(path,size,source=True)
                    lookup[key]=len(files)
                    files.append({'path':key,'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest()})
                index=lookup[key]
            modules.append([name,index,origin])
        need(tuple(sys.modules)==names,'Observed census changed while captured')
        return {'schema':'newbrain.observed-module-census210.v1','files':files,'modules':modules,
                'earlier_startup_native_transient_or_kernel_operations':None}

    def finish(self, entry_result):
        self.checkpoint('entry.complete.before-result')
        raw=canonical({'schema':'newbrain.complete-entry-result210.v2','entry_result':entry_result,
             'explicit_source_requested_bytes':self.source,
             'explicit_normal_bytes_before_result':self.application,
             'explicit_emergency_bytes_before_result':self.emergency,
             'explicit_IO_rows_before_result':self.rows,'observer_rows':self.observer_rows,
             'whole_process_resource_and_return_qualification':'ROOT_REQUIRED',
             'unobserved_native_transient_details':None})
        saved=self.write('ENTRY-RESULT.json',raw,ENTRY_CAP)
        status=canonical(saved)+b'\n'
        self.charge(len(status));sys.stdout.buffer.write(status);sys.stdout.buffer.flush()
        return 0
