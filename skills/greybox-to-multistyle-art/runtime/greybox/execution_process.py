"""Private atomic receipts, local ownership locks and killable action processes."""
from __future__ import annotations

from contextlib import contextmanager
import errno
import json
import os
from pathlib import Path
import signal
import subprocess
import tempfile
import time


class LockBusyError(ValueError):
    """The OS lock is owned by another operation; its record is not corrupt."""


def replace_file(source, target, retry_timeout=1.0):
    """Replace atomically despite short-lived Windows reader handles.

    Sharing/access violations may outlive a reader's snapshot by a few
    milliseconds. Never truncate the destination or retry other OS errors;
    permanent permissions still fail within this local deadline.
    """
    deadline = time.monotonic() + retry_timeout
    while True:
        try:
            return os.replace(source, target)
        except PermissionError as error:
            remaining = deadline - time.monotonic()
            if os.name != "nt" or getattr(error, "winerror", None) not in {5, 32, 33} or remaining <= 0:
                raise
            time.sleep(min(.01, remaining))


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if path.is_symlink():
        raise ValueError("Execution files cannot be symbolic links")
    fd, temporary = tempfile.mkstemp(prefix=".execution-", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=False, allow_nan=False)
            handle.flush()
            os.fsync(handle.fileno())
        replace_file(temporary, path)
        if os.name != "nt":
            directory = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


_WINDOWS = os.name == "nt"


def read_json_snapshot(path, limit, *, reject_links=False, retry_timeout=1.0):
    """Read one bounded file generation, without retrying decoding or validation."""
    path = Path(path)
    deadline = time.monotonic() + retry_timeout
    while True:
        try:
            if reject_links and path.is_symlink():
                raise ValueError("Execution receipt cannot be a symbolic link")
            with path.open("rb") as handle:
                size = os.fstat(handle.fileno()).st_size
                if size > limit:
                    raise ValueError("JSON document exceeds its size limit")
                raw = handle.read(size + 1)
                if len(raw) != size:
                    raise ValueError("JSON document changed during read")
            break
        except PermissionError as error:
            # The Windows CRT can expose a sharing violation as EACCES alone.
            winerror = getattr(error, "winerror", None)
            retryable = _WINDOWS and (winerror in {5, 32, 33} or
                                      (winerror is None and error.errno == errno.EACCES))
            remaining = deadline - time.monotonic()
            if not retryable or remaining <= 0:
                raise
            time.sleep(min(.01, remaining))
    return json.loads(raw.decode("utf-8"))


def read_json(path, limit=140 * 1024 * 1024):
    result = read_json_snapshot(path, limit, reject_links=True)
    if not isinstance(result, dict):
        raise ValueError("Execution record must be an object")
    return result


@contextmanager
def exclusive(path):
    """OS ownership lock, released on death; never a remote capacity lease."""
    path = Path(path)
    try:
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    except FileExistsError as error:
        # Preserve WorkBuddy's broker semantics, matching core.ensure_directory.
        if error.errno != errno.EEXIST or not path.parent.is_dir():
            raise
    if path.is_symlink():
        raise ValueError("Execution lock cannot be a symbolic link")
    handle = path.open("a+b")
    try:
        if os.name == "nt":
            import msvcrt
            # Windows byte-range locks may extend beyond EOF. Lock first:
            # reading/writing byte zero before ownership can itself fail when
            # another process holds it (including while metadata is truncated).
            handle.seek(0)
            try:
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError:
                raise LockBusyError("Another executor owns this queue") from None
        else:
            import fcntl
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                raise LockBusyError("Another executor owns this queue") from None
        yield handle
    finally:
        handle.close()


def alive(pid):
    try:
        pid = int(pid)
    except (TypeError, ValueError, OverflowError):
        return False
    if pid <= 0:
        return False
    if os.name == "nt":
        # On Windows os.kill(pid, 0) calls TerminateProcess, not a probe.
        import ctypes
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.OpenProcess.restype = ctypes.c_void_p
        kernel.OpenProcess.argtypes = [ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong]
        kernel.GetExitCodeProcess.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulong)]
        kernel.CloseHandle.argtypes = [ctypes.c_void_p]
        handle = kernel.OpenProcess(0x1000, False, pid)
        if not handle:
            return ctypes.get_last_error() != 87  # Access denied is not death.
        try:
            code = ctypes.c_ulong()
            return not kernel.GetExitCodeProcess(handle, ctypes.byref(code)) or code.value == 259
        finally:
            kernel.CloseHandle(handle)
    try:
        os.kill(pid, 0)
        return True
    except PermissionError:
        return True
    except OSError:
        return False


def spawn(argv, *, stdin=None, stdout=None, stderr=None):
    kwargs = {"stdin": stdin, "stdout": stdout, "stderr": stderr, "close_fds": True}
    if os.name == "nt":
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        kwargs["start_new_session"] = True
    return subprocess.Popen(argv, **kwargs)


def kill_tree(process):
    """Only use a live child Popen handle; never kill an unverified reused PID."""
    if process.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"],
                       stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL, timeout=5, check=False)
    else:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    process.wait(timeout=5)
