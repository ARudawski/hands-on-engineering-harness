"""One Windows Job owns all subprocesses of a bounded signed-in attempt."""
import ctypes
import json
import os
import subprocess
import sys
import threading
import time


GATE = '''import json,os,subprocess,sys
raw=bytearray()
while True:
    byte=os.read(0,1)
    if not byte: sys.exit(1)
    if byte==b"\\n": break
    raw.extend(byte)
    if len(raw)>32768: sys.exit(1)
sys.exit(subprocess.call(json.loads(raw),stdin=sys.stdin.buffer,stdout=sys.stdout.buffer,stderr=sys.stderr.buffer))
'''


def process_stopped(pid):
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.OpenProcess.restype = ctypes.c_void_p
    kernel.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
    kernel.CloseHandle.argtypes = [ctypes.c_void_p]
    handle = kernel.OpenProcess(0x100000 | 0x1000, False, pid)
    if not handle:
        return ctypes.get_last_error() == 87
    try:
        return kernel.WaitForSingleObject(handle, 0) == 0
    finally:
        kernel.CloseHandle(handle)


class AttemptProcesses:
    def __init__(self, store, origin, request):
        if os.name != 'nt':
            raise OSError('Windows required')
        self.store, self.origin, self.request_id = store, origin, request['request_id']
        self.wall_deadline = request['deadline']
        self.deadline = time.monotonic() + max(0, self.wall_deadline - time.time())
        self.lock, self.done = threading.RLock(), threading.Event()
        self.processes = []
        self.closed, self.terminated = False, False
        self.stop_reason = None
        self.closure_failed, self.termination_failed = False, False
        self.cleanup_deadline = self.deadline
        self.kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        for name, args, result in (
            ('CreateJobObjectW', [ctypes.c_void_p, ctypes.c_wchar_p], ctypes.c_void_p),
            ('SetInformationJobObject', [ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p, ctypes.c_uint32], ctypes.c_int),
            ('AssignProcessToJobObject', [ctypes.c_void_p, ctypes.c_void_p], ctypes.c_int),
            ('TerminateJobObject', [ctypes.c_void_p, ctypes.c_uint32], ctypes.c_int),
            ('QueryInformationJobObject', [ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p, ctypes.c_uint32, ctypes.c_void_p], ctypes.c_int),
            ('CloseHandle', [ctypes.c_void_p], ctypes.c_int)):
            function = getattr(self.kernel, name)
            function.argtypes, function.restype = args, result

        class BasicLimits(ctypes.Structure):
            _fields_ = [('process_time', ctypes.c_int64), ('job_time', ctypes.c_int64),
                        ('flags', ctypes.c_uint32), ('min_working', ctypes.c_size_t),
                        ('max_working', ctypes.c_size_t), ('processes', ctypes.c_uint32),
                        ('affinity', ctypes.c_size_t), ('priority', ctypes.c_uint32),
                        ('scheduling', ctypes.c_uint32)]

        class Limits(ctypes.Structure):
            _fields_ = [('basic', BasicLimits), ('io', ctypes.c_uint64 * 6),
                        ('memory', ctypes.c_size_t * 4)]

        self.handle = self.kernel.CreateJobObjectW(None, None)
        if not self.handle:
            raise OSError('Job unavailable')
        limits = Limits()
        limits.basic.flags = 0x2000  # KILL_ON_JOB_CLOSE; no breakaway.
        if not self.kernel.SetInformationJobObject(self.handle, 9, ctypes.byref(limits), ctypes.sizeof(limits)):
            self.kernel.CloseHandle(self.handle)
            self.handle = None
            raise OSError('Job limits unavailable')
        self.watcher = threading.Thread(target=self.watch, daemon=True)
        self.watcher.start()

    def remaining(self, maximum=30, *, cleanup=False):
        left = min(self.deadline-time.monotonic(), self.wall_deadline-time.time())
        if cleanup:
            left = min(left, self.cleanup_deadline-time.monotonic())
        else:
            state = self.store.get(self.origin, self.request_id)
            if self.closed or not state['admission_open']:
                raise TimeoutError('Admission closed')
            left -= 10
        if left <= 0:
            raise TimeoutError('Request deadline')
        return min(maximum, left)

    def watch(self):
        while not self.done.wait(.05):
            with self.lock:
                try:
                    self.remaining(cleanup=self.closed)
                except Exception:
                    self.cancel('deadline_exhausted')
                    return

    def begin_cleanup(self, reason):
        with self.lock:
            if self.closed:
                return
            self.closed = True
            self.cleanup_deadline = min(self.deadline, time.monotonic()+10)
            try:
                self.store.stop(self.origin, self.request_id, reason)
            except Exception:
                self.closure_failed = True

    def cancel(self, reason):
        with self.lock:
            self.begin_cleanup(reason)
            if not self.terminated and self.handle:
                self.terminated = True
                self.stop_reason = reason
                if not self.kernel.TerminateJobObject(self.handle, 1):
                    self.termination_failed = True

    def start(self, command, *, cwd, env=None, stderr=subprocess.PIPE):
        with self.lock:
            self.remaining()
            # This trusted gate cannot spawn its payload before job assignment.
            process = subprocess.Popen([sys.executable, '-I', '-u', '-c', GATE], cwd=cwd, env=env,
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=stderr, text=True, encoding='utf-8')
            if not self.kernel.AssignProcessToJobObject(self.handle, int(process._handle)):
                process.kill()
                process.wait(timeout=2)
                for stream in (process.stdin, process.stdout, process.stderr):
                    if stream:
                        stream.close()
                raise OSError('Job assignment failed')
            self.processes.append(process)
            self.remaining()
        # The job owns this admitted command. Never hold the cutoff lock during I/O:
        # killing the owned reader then unblocks a stalled/full pipe writer.
        process.stdin.write(json.dumps([str(part) for part in command])+'\n')
        process.stdin.flush()
        return process

    def run(self, command, *, cwd, env=None, timeout=120):
        process = self.start(command, cwd=cwd, env=env)
        try:
            stdout, stderr = process.communicate(timeout=self.remaining(timeout))
        except BaseException:
            self.cancel('missing_evidence')
            raise
        if process.returncode or len(stdout)+len(stderr) > 4*1024*1024:
            raise RuntimeError('subprocess_failed')
        return stdout

    def active(self):
        # Four LARGE_INTEGERs then four DWORDs, per BASIC_ACCOUNTING_INFORMATION.
        accounting = ctypes.create_string_buffer(48)
        if not self.kernel.QueryInformationJobObject(self.handle, 1, accounting, 48, None):
            raise OSError('Job query failed')
        return ctypes.c_uint32.from_buffer(accounting, 40).value

    def close(self, reason):
        self.cancel(reason)
        self.done.set()
        self.watcher.join(timeout=.5)
        empty = False
        try:
            while self.remaining(.05, cleanup=True) > 0:
                if self.active() == 0:
                    empty = True
                    break
                time.sleep(.02)
        except (OSError, TimeoutError):
            pass
        finally:
            self.kernel.CloseHandle(self.handle)
            self.handle = None
        for process in self.processes:
            try:
                process.wait(timeout=self.remaining(1, cleanup=True))
                for stream in (process.stdin, process.stdout, process.stderr):
                    if stream:
                        try:
                            stream.close()
                        except BrokenPipeError:
                            pass  # Expected buffered stdin after terminating its reader.
            except (OSError, TimeoutError, subprocess.TimeoutExpired):
                empty = False
        return {'job_empty': empty, 'within_budget': time.time() <= self.wall_deadline,
                'closure_failed': self.closure_failed, 'termination_failed': self.termination_failed,
                'stop_reason': self.stop_reason}
