"""Real Windows sharing semantics and sandbox-helper projections; no model calls."""
import os
import base64
import json
from pathlib import Path
import tempfile
import shutil
import subprocess
import sys
import unittest
from unittest.mock import Mock, patch

from evaluation.signed_in_fixture import WindowsPathLocks
from evaluation.signed_in_worker import fixture_snapshot
from evaluation.signed_in_workflow import expected_fixture_hashes
from evaluation.worker import native_foundation_files


class FixtureFiles(unittest.TestCase):
    def setUp(self):
        directory=tempfile.TemporaryDirectory();self.addCleanup(directory.cleanup)
        self.base=Path(directory.name);(self.base/'.tmp').mkdir()
        self.case=self.base/'.tmp/native-foundation';self.case.mkdir()
        for name,text in native_foundation_files().items():(self.case/name).write_text(text,encoding='utf-8',newline='\n')

    def test_snapshot_projects_integrity_and_records(self):
        self.assertEqual(fixture_snapshot(self.base),{'hashes':expected_fixture_hashes(),'extra_files':False,'record_present':False})
        (self.case/'spec.md').write_text('Stage 1 held',encoding='utf-8')
        (self.case/'index.md').write_text('spec.md',encoding='utf-8')
        self.assertTrue(fixture_snapshot(self.base)['record_present'])
        (self.case/'unexpected.txt').write_text('extra',encoding='utf-8')
        self.assertTrue(fixture_snapshot(self.base)['extra_files'])
        (self.case/'after.py').write_text('changed',encoding='utf-8')
        self.assertNotEqual(fixture_snapshot(self.base)['hashes'],expected_fixture_hashes())

    def test_helper_materializes_exact_public_bytes_and_refuses_replacement(self):
        consumer=self.base/'fresh';consumer.mkdir();(consumer/'.tmp').mkdir()
        helper=consumer/'h12-probe.py';shutil.copyfile(Path(__file__).parent/'evaluation/signed_in_worker.py',helper)
        (consumer/'h12-inputs.json').write_text('{}',encoding='utf-8')
        payload=base64.b64encode(json.dumps(native_foundation_files()).encode()).decode('ascii')
        command=[sys.executable,'-I','-B',str(helper),'fixture-prepare',payload]
        prepared=subprocess.run(command,capture_output=True,text=True,timeout=10)
        self.assertEqual(prepared.returncode,0,prepared.stderr)
        self.assertEqual(json.loads(prepared.stdout)['hashes'],expected_fixture_hashes())
        for name,text in native_foundation_files().items():
            self.assertEqual((consumer/'.tmp/native-foundation'/name).read_bytes(),text.encode('utf-8'))
        duplicate=subprocess.run(command,capture_output=True,text=True,timeout=10)
        self.assertNotEqual(duplicate.returncode,0)
        self.assertEqual(fixture_snapshot(consumer)['hashes'],expected_fixture_hashes())

    @unittest.skipUnless(os.name=='nt','Windows sharing semantics')
    def test_empty_task_namespace_cannot_be_replaced_before_fixture_creation(self):
        directory=self.base/'empty';directory.mkdir()
        guard=WindowsPathLocks([(directory,True)]);self.addCleanup(guard.close)
        with self.assertRaises(OSError):directory.rename(self.base/'renamed')
        with self.assertRaises(OSError):directory.rmdir()
        (directory/'record.md').write_text('allowed',encoding='utf-8')

    @unittest.skipUnless(os.name=='nt','Windows sharing semantics')
    def test_metadata_locks_block_replacement_but_allow_reads_and_records(self):
        guard=WindowsPathLocks([(self.base/'.tmp',True),(self.case,True)]+[(self.case/name,False) for name in native_foundation_files()])
        self.addCleanup(guard.close)
        path=self.case/'after.py'
        self.assertEqual(path.read_text(encoding='utf-8'),native_foundation_files()['after.py'])
        for label,operation in [('write',lambda:path.write_text('changed')),('delete',lambda:path.unlink()),
                               ('rename_file',lambda:path.rename(self.case/'moved.py')),
                               ('rename_case',lambda:self.case.rename(self.base/'.tmp/moved')),
                               ('rename_tmp',lambda:(self.base/'.tmp').rename(self.base/'moved'))]:
            with self.subTest(operation=label):
                with self.assertRaises(OSError):operation()
        (self.case/'spec.md').write_text('Stage 1 held',encoding='utf-8')
        (self.case/'index.md').write_text('spec.md',encoding='utf-8')
        self.assertTrue(fixture_snapshot(self.base)['record_present'])
        self.assertTrue(guard.close());path.write_text('released',encoding='utf-8')

    @unittest.skipUnless(os.name=='nt','Windows reparse semantics')
    def test_reparse_and_foreign_final_paths_are_rejected_without_content_reads(self):
        for attributes,final_path in [(0x400,str(self.case/'after.py')),(0,str(self.base/'foreign.py'))]:
            kernel=Mock();kernel.CreateFileW.return_value=99;kernel.CloseHandle.return_value=True
            def information(handle,pointer):pointer._obj.attributes=attributes;return True
            def final(handle,buffer,size,flags):
                if buffer is None:return len(final_path)+1
                buffer.value=final_path;return len(final_path)
            kernel.GetFileInformationByHandle.side_effect=information
            kernel.GetFinalPathNameByHandleW.side_effect=final
            with patch('evaluation.signed_in_fixture.ctypes.WinDLL',return_value=kernel):
                with self.assertRaisesRegex(RuntimeError,'^workflow_probe_incomplete$'):
                    WindowsPathLocks([(self.case/'after.py',False)])
            kernel.CloseHandle.assert_called_once_with(99)
            kernel.ReadFile.assert_not_called();kernel.CreateFileMappingW.assert_not_called()

    @unittest.skipUnless(os.name=='nt','Windows reparse semantics')
    def test_reparse_file_and_redirected_parent_are_rejected(self):
        target=self.base/'public.txt';target.write_text('PUBLIC',encoding='utf-8')
        link=self.base/'link.txt';parent=self.base/'redirect'
        try:
            link.symlink_to(target);parent.symlink_to(self.case,target_is_directory=True)
        except OSError as error:
            if getattr(error,'winerror',None)==1314:self.skipTest('Symlink privilege unavailable')
            raise
        for path,directory in [(link,False),(parent,True),(parent/'after.py',False)]:
            with self.assertRaisesRegex(RuntimeError,'^workflow_probe_incomplete$'):WindowsPathLocks([(path,directory)])
        target.write_text('UNCHANGED ACCESS',encoding='utf-8')


if __name__=='__main__':unittest.main()
