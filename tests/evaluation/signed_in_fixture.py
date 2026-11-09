"""Windows sharing handles for a native trial's mutable task namespace.

No file data is read here. The sandboxed worker materializes and hashes public
inputs; these non-inheritable handles deny replacement until its Job is empty.
"""
import ctypes
from ctypes import wintypes
import ntpath
import os
from pathlib import Path


class WindowsPathLocks:
    def __init__(self, paths):
        self.handles=[]
        if os.name!='nt':raise RuntimeError('workflow_probe_incomplete')
        self.kernel=ctypes.WinDLL('kernel32',use_last_error=True)
        self.kernel.CreateFileW.argtypes=[wintypes.LPCWSTR,wintypes.DWORD,wintypes.DWORD,wintypes.LPVOID,
                                         wintypes.DWORD,wintypes.DWORD,wintypes.HANDLE]
        self.kernel.CreateFileW.restype=wintypes.HANDLE
        self.kernel.GetFileInformationByHandle.argtypes=[wintypes.HANDLE,wintypes.LPVOID]
        self.kernel.GetFileInformationByHandle.restype=wintypes.BOOL
        self.kernel.GetFinalPathNameByHandleW.argtypes=[wintypes.HANDLE,wintypes.LPWSTR,wintypes.DWORD,wintypes.DWORD]
        self.kernel.GetFinalPathNameByHandleW.restype=wintypes.DWORD
        self.kernel.CloseHandle.argtypes=[wintypes.HANDLE];self.kernel.CloseHandle.restype=wintypes.BOOL
        try:
            for path,directory in paths:self._open(Path(path),directory)
        except BaseException:
            self.close();raise

    def _open(self,path,directory):
        class Information(ctypes.Structure):
            _fields_=[('attributes',wintypes.DWORD),('created',wintypes.FILETIME),('accessed',wintypes.FILETIME),
                      ('written',wintypes.FILETIME),('volume',wintypes.DWORD),('size_high',wintypes.DWORD),
                      ('size_low',wintypes.DWORD),('links',wintypes.DWORD),('index_high',wintypes.DWORD),('index_low',wintypes.DWORD)]
        # Bit1 is READ_DATA for files / LIST_DIRECTORY for directories: Windows
        # needs it to enforce sharing. No read/list/mapping API is called here.
        # OPEN_REPARSE_POINT avoids following a final-component link; final path also catches parent junctions.
        handle=self.kernel.CreateFileW(str(path),0x81,3 if directory else 1,None,3,0x02200000,None)
        if handle in (None,ctypes.c_void_p(-1).value):raise RuntimeError('workflow_probe_incomplete')
        self.handles.append(handle)
        info=Information()
        if (not self.kernel.GetFileInformationByHandle(handle,ctypes.byref(info))
                or info.attributes & 0x400 or bool(info.attributes & 0x10)!=directory):
            raise RuntimeError('workflow_probe_incomplete')
        size=self.kernel.GetFinalPathNameByHandleW(handle,None,0,0)
        if not 0<size<=32768:raise RuntimeError('workflow_probe_incomplete')
        buffer=ctypes.create_unicode_buffer(size+1)
        written=self.kernel.GetFinalPathNameByHandleW(handle,buffer,len(buffer),0)
        if not 0<written<len(buffer):raise RuntimeError('workflow_probe_incomplete')
        actual=buffer.value
        if actual.startswith('\\\\?\\UNC\\'):actual='\\\\'+actual[8:]
        elif actual.startswith('\\\\?\\'):actual=actual[4:]
        if ntpath.normcase(ntpath.normpath(actual))!=ntpath.normcase(str(path.absolute())):
            raise RuntimeError('workflow_probe_incomplete')

    def close(self):
        success=True
        while self.handles:
            if not self.kernel.CloseHandle(self.handles.pop()):success=False
        return success

    def __del__(self):
        try:self.close()
        except Exception:pass
