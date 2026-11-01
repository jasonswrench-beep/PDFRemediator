"""Bounded local subprocess execution with complete logs and cancellation."""
from __future__ import annotations

import os
import math
from pathlib import Path
import subprocess
import time

import psutil


def cancelled(cancel=None):
    return bool(cancel is not None and (cancel.is_set() if hasattr(cancel, "is_set") else cancel()))


def _kill_tree(child):
    try:
        descendants = psutil.Process(child.pid).children(recursive=True)
    except psutil.NoSuchProcess:
        descendants = []
    for proc in reversed(descendants):
        try:
            proc.kill()
        except psutil.NoSuchProcess:
            pass
    if child.poll() is None:
        child.kill()
    child.wait(timeout=15)


def run(command, directory, timeout_seconds=600, memory_limit_bytes=4 * 1024**3,
        cancel=None, env=None, success_codes=(0,), stdout_path=None, stderr_path=None,
        cwd=None):
    """Run an explicit argv without a shell; keep partial logs on all outcomes.

    Memory is a sampled process-tree RSS bound, not an operating-system hard
    allocation guarantee. The sample interval and peak are recorded honestly.
    """
    if (type(timeout_seconds) not in (int,float) or not math.isfinite(timeout_seconds) or timeout_seconds <= 0
        or type(memory_limit_bytes) is not int or memory_limit_bytes < 16 * 1024**2):
        raise ValueError("Invalid process time or memory limit")
    directory = Path(directory).resolve()
    directory.mkdir(parents=True, exist_ok=True)
    out = Path(stdout_path) if stdout_path else directory / "stdout.txt"
    err = Path(stderr_path) if stderr_path else directory / "stderr.txt"
    if out.exists() or err.exists():
        raise FileExistsError("Refusing to overwrite subprocess evidence")
    result = {"command": [str(x) for x in command], "status": "error", "returncode": None,
              "stdout": str(out), "stderr": str(err), "timeout_seconds": timeout_seconds,
              "observed_rss_limit_bytes": memory_limit_bytes, "memory_sample_interval_seconds": .05,
              "memory_limit_is_sampled": True, "peak_observed_process_tree_rss_bytes": 0}
    started = time.monotonic()
    child = None
    try:
        with out.open("xb") as stdout, err.open("xb") as stderr:
            if cancelled(cancel):
                result["status"] = "cancelled"
            else:
                child = subprocess.Popen(result["command"], stdout=stdout, stderr=stderr,
                                         env=env, cwd=cwd or directory, shell=False,
                                         creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                while child.poll() is None:
                    if cancelled(cancel):
                        result["status"] = "cancelled"
                        break
                    if time.monotonic() - started >= timeout_seconds:
                        result["status"] = "timeout"
                        break
                    try:
                        parent = psutil.Process(child.pid)
                        rss = 0
                        for proc in [parent] + parent.children(recursive=True):
                            try:
                                rss += proc.memory_info().rss
                            except psutil.NoSuchProcess:
                                pass
                        result["peak_observed_process_tree_rss_bytes"] = max(rss, result["peak_observed_process_tree_rss_bytes"])
                        if rss > memory_limit_bytes:
                            result["status"] = "memory-limit"
                            break
                    except psutil.NoSuchProcess:
                        pass
                    except psutil.AccessDenied as exc:
                        result["status"] = "error"
                        result["error"] = "Cannot enforce sampled memory bound: " + str(exc)
                        break
                    time.sleep(.05)
                else:
                    result["status"] = "completed" if child.returncode in success_codes else "failed"
    except OSError as exc:
        result["status"] = "error"
        result["error"] = f"{type(exc).__name__}: {exc}"
    except KeyboardInterrupt:
        result["status"] = "cancelled"
    finally:
        if child is not None:
            if child.poll() is None:
                _kill_tree(child)
            result["returncode"] = child.returncode
        result["seconds"] = round(time.monotonic() - started, 6)
        result["elapsed_seconds"] = result["seconds"]
    return result


def local_environment(java_home=None):
    """Remove inherited JVM configuration before invoking the pinned tools."""
    env = os.environ.copy()
    for name in ("JAVA_OPTS", "JDK_JAVA_OPTIONS", "JAVA_TOOL_OPTIONS", "_JAVA_OPTIONS"):
        env.pop(name, None)
    env["PYTHONUTF8"] = "1"
    if java_home:
        env["JAVA_HOME"] = str(java_home)
        env["PATH"] = str(Path(java_home) / "bin") + os.pathsep + env.get("PATH", "")
    return env
