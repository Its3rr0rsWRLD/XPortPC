"""Capture process, entry thread and pipe state before cleaning up an EXE timeout."""
import ctypes
from ctypes import wintypes
import os
import subprocess
import threading
import time


class ThreadEntry(ctypes.Structure):
    _fields_ = [(name, wintypes.DWORD) for name in (
        "size", "usage", "tid", "pid", "priority", "delta", "flags")]


def thread_ids(pid):
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    snapshot = kernel.CreateToolhelp32Snapshot
    snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    snapshot.restype = wintypes.HANDLE
    handle = snapshot(4, 0)  # TH32CS_SNAPTHREAD
    if handle == ctypes.c_void_p(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    import _winapi
    try:
        first, next_entry = kernel.Thread32First, kernel.Thread32Next
        for function in (first, next_entry):
            function.argtypes = [wintypes.HANDLE, ctypes.POINTER(ThreadEntry)]
            function.restype = wintypes.BOOL
        entry = ThreadEntry(size=ctypes.sizeof(ThreadEntry))
        present = first(handle, ctypes.byref(entry))
        threads = []
        while present:
            if entry.pid == pid:
                threads.append(entry.tid)
            present = next_entry(handle, ctypes.byref(entry))
        return sorted(threads)
    finally:
        _winapi.CloseHandle(handle)


def read_module_memory(pid, path, rva, size):
    """Read size bytes at rva of the module in process pid whose file is path (same file, not the first module).

    Raises OSError if the process cannot be opened, no module has that file, or the read fails or is short.
    """
    import _winapi

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    psapi = ctypes.WinDLL("psapi", use_last_error=True)
    kernel.ReadProcessMemory.argtypes = [wintypes.HANDLE, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t,
                                         ctypes.POINTER(ctypes.c_size_t)]
    psapi.EnumProcessModulesEx.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.HMODULE), wintypes.DWORD,
                                           ctypes.POINTER(wintypes.DWORD), wintypes.DWORD]
    psapi.GetModuleFileNameExW.argtypes = [wintypes.HANDLE, wintypes.HMODULE, wintypes.LPWSTR, wintypes.DWORD]
    process = _winapi.OpenProcess(0x0400 | 0x0010, False, pid)  # PROCESS_QUERY_INFORMATION | PROCESS_VM_READ
    try:
        modules, needed = (wintypes.HMODULE * 1024)(), wintypes.DWORD()
        if not psapi.EnumProcessModulesEx(process, modules, ctypes.sizeof(modules), ctypes.byref(needed),
                                          0x03):  # LIST_MODULES_ALL
            raise ctypes.WinError(ctypes.get_last_error())
        name = ctypes.create_unicode_buffer(32768)
        for module in modules[:min(needed.value, ctypes.sizeof(modules)) // ctypes.sizeof(wintypes.HMODULE)]:
            if psapi.GetModuleFileNameExW(process, module, name, len(name)):
                try:
                    if os.path.samefile(name.value, path):
                        break
                except OSError:
                    pass
        else:
            raise OSError(f"process {pid} has no module for {path}")
        data, read = ctypes.create_string_buffer(size), ctypes.c_size_t()
        if not kernel.ReadProcessMemory(process, module + rva, data, size, ctypes.byref(read)) \
                or read.value != size:
            raise ctypes.WinError(ctypes.get_last_error())
        return data.raw
    finally:
        _winapi.CloseHandle(process)


def thread_exit_code(handle):
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    query = kernel.GetExitCodeThread
    query.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    query.restype = wintypes.BOOL
    code = wintypes.DWORD()
    if not query(handle, ctypes.byref(code)):
        raise ctypes.WinError(ctypes.get_last_error())
    return code.value


class Pipe:
    def __init__(self, stream):
        self.chunks = []
        self.eof = False
        self.error = None
        self.reader = threading.Thread(target=self.drain, args=(stream,), daemon=True)
        self.reader.start()

    def drain(self, stream):
        try:
            while chunk := os.read(stream.fileno(), 4096):
                self.chunks.append(chunk)
            self.eof = True
        except OSError as error:
            self.error = str(error)
        finally:
            stream.close()

    def snapshot(self):
        return {"bytes": b"".join(self.chunks), "eof": self.eof, "error": self.error}


def launch(command, data, *, env=None, timeout=15, on_unfinished=None):
    """Run command with data on stdin. If the process or a pipe is still open at the deadline, record the
    entry thread and live threads and, when given, call on_unfinished(pid) while the process is still alive;
    its return value is stored as result["unfinished"], and signaled_after_hook/code_after_hook tell whether
    the process ended in the meantime."""
    import _winapi

    # Popen closes the initial thread handle. Retain a duplicate for a
    # diagnostic even after that thread exits. Launches here are serial.
    create_process = _winapi.CreateProcess
    entry_handle = entry_tid = None

    def capture(*args):
        nonlocal entry_handle, entry_tid
        handles = create_process(*args)
        current = _winapi.GetCurrentProcess()
        entry_handle = _winapi.DuplicateHandle(current, handles[1], current, 0, False, 2)
        entry_tid = handles[3]
        return handles

    started = time.monotonic()
    deadline = started + timeout
    _winapi.CreateProcess = capture
    try:
        child = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                 stderr=subprocess.PIPE, env=env, bufsize=0)
    finally:
        _winapi.CreateProcess = create_process
    try:
        stdout, stderr = Pipe(child.stdout), Pipe(child.stderr)
        with child.stdin:
            try:
                child.stdin.write(data)
            except BrokenPipeError:
                pass
        try:
            child.wait(timeout=max(0, deadline - time.monotonic()))
        except subprocess.TimeoutExpired:
            pass
        for pipe in (stdout, stderr):
            pipe.reader.join(timeout=max(0, deadline - time.monotonic()))
        process_signaled = _winapi.WaitForSingleObject(child._handle, 0) == 0
        streams = {"stdout": stdout.snapshot(), "stderr": stderr.snapshot()}
        result = {"command": list(map(str, command)), "pid": child.pid,
                  "elapsed_ms": round(1000 * (time.monotonic() - started), 1),
                  "process_signaled": process_signaled,
                  "code": _winapi.GetExitCodeProcess(child._handle), **streams}
        if not process_signaled or not all(pipe["eof"] for pipe in streams.values()):
            result.update(entry_tid=entry_tid,
                          entry_signaled=_winapi.WaitForSingleObject(entry_handle, 0) == 0,
                          entry_code=thread_exit_code(entry_handle),
                          live_threads=thread_ids(child.pid))
            if on_unfinished and not process_signaled:
                result["unfinished"] = on_unfinished(child.pid)
            # The process may have ended between the deadline and the end of the hook; record that separately.
            result["signaled_after_hook"] = _winapi.WaitForSingleObject(child._handle, 0) == 0
            result["code_after_hook"] = _winapi.GetExitCodeProcess(child._handle) if result["signaled_after_hook"] else None
            print(f"EXE state before timeout cleanup: {result}", flush=True)
        return result
    finally:
        try:
            if child.poll() is None:
                child.kill()
                child.wait(timeout=5)
        finally:
            _winapi.CloseHandle(entry_handle)
