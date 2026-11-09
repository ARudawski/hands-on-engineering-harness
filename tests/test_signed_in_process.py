"""Model-free ownership/deadline regression for preparation subprocess trees."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
import threading
from unittest.mock import patch
from uuid import uuid4

from evaluation.signed_in import RequestStore
from evaluation.signed_in_process import AttemptProcesses, process_stopped
from evaluation.signed_in_native import NativeConnection


@unittest.skipUnless(os.name == 'nt', 'Windows Job Object contract')
class PreparationDeadline(unittest.TestCase):
    def test_full_startup_and_rpc_pipes_cannot_block_deadline_enforcement(self):
        for startup in (True, False):
            with self.subTest(startup=startup), tempfile.TemporaryDirectory() as folder:
                root = Path(folder)
                store = RequestStore(root/'state')
                origin, request_id = str(uuid4()), str(uuid4())
                owner = AttemptProcesses(store, origin, store.submit(origin, request_id, 'native-foundation', 11))
                finished = threading.Event()
                errors = []
                def block_pipe():
                    try:
                        if startup:
                            owner.start(['never_released', 'x'*131072], cwd=root)
                        else:
                            client = NativeConnection.__new__(NativeConnection)
                            client.mode, client.owner = 'prepare', owner
                            client.process = owner.start([sys.executable, '-I', '-c', 'import time; time.sleep(30)'], cwd=root)
                            client.send({'method': 'initialized', 'params': {'padding': 'x'*131072}})
                    except OSError:
                        errors.append('pipe_closed')
                    finally:
                        finished.set()
                try:
                    gate = 'import time; time.sleep(30)' if startup else __import__('evaluation.signed_in_process', fromlist=['GATE']).GATE
                    with patch('evaluation.signed_in_process.GATE', gate):
                        worker = threading.Thread(target=block_pipe, daemon=True)
                        worker.start()
                        bounded = finished.wait(3)
                        if not bounded:
                            # Independent test failsafe, never waits on the owner lock.
                            owner.kernel.TerminateJobObject(owner.handle, 1)
                            finished.wait(2)
                    self.assertTrue(bounded, 'a blocked writer must not hold the watchdog admission lock')
                    self.assertEqual(errors, ['pipe_closed'])
                    self.assertFalse(store.get(origin, request_id)['admission_open'])
                    self.assertEqual(store.get(origin, request_id)['first_failure'], 'deadline_exhausted')
                finally:
                    owner.close('interrupted')

    def test_cleanup_grace_closes_admission_before_stopping_owned_work(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            store = RequestStore(root/'state')
            origin, request_id = str(uuid4()), str(uuid4())
            owner = AttemptProcesses(store, origin, store.submit(origin, request_id, 'native-foundation', 30))
            try:
                process = owner.start([sys.executable, '-I', '-c', 'import time; time.sleep(30)'], cwd=root)
                owner.begin_cleanup('interrupted')
                time.sleep(.2)
                self.assertIsNone(process.poll(), 'native interrupt must have its bounded grace window')
                with self.assertRaises(TimeoutError):
                    owner.start([sys.executable, '-I', '-c', 'raise SystemExit(0)'], cwd=root)
                self.assertFalse(store.get(origin, request_id)['admission_open'])
            finally:
                result = owner.close('missing_evidence')
            self.assertTrue(result['job_empty'])
            self.assertEqual(store.get(origin, request_id)['first_failure'], 'interrupted')

    def test_hanging_preparation_child_stops_and_late_dispatch_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            store = RequestStore(root/'controller')
            origin, request_id = str(uuid4()), str(uuid4())
            request = store.submit(origin, request_id, 'native-foundation', 11)
            owner = AttemptProcesses(store, origin, request)
            try:
                pidfile = root/'child-pid'
                code = ('import subprocess,sys,time; from pathlib import Path; '
                        'p=subprocess.Popen([sys.executable,"-I","-c","import time; time.sleep(30)"]); '
                        'Path(sys.argv[1]).write_text(str(p.pid)); time.sleep(30)')
                process = owner.start([sys.executable, '-I', '-c', code, str(pidfile)], cwd=root)
                until = time.monotonic()+.8
                while not pidfile.exists() and time.monotonic()<until:
                    time.sleep(.01)
                self.assertTrue(pidfile.exists(), 'preparation child must actually start')
                child_pid = int(pidfile.read_text())
                process.communicate(timeout=4)
                self.assertNotEqual(process.returncode, 0)
                self.assertFalse(store.get(origin, request_id)['admission_open'])
                self.assertEqual(store.get(origin, request_id)['first_failure'], 'deadline_exhausted')
                with self.assertRaises(TimeoutError):
                    owner.start([sys.executable, '-I', '-c', 'raise SystemExit(0)'], cwd=root)
                self.assertTrue(process_stopped(child_pid))
            finally:
                cleanup = owner.close('interrupted')
            self.assertTrue(cleanup['job_empty'])
            self.assertTrue(cleanup['within_budget'])


if __name__ == '__main__':
    unittest.main()
