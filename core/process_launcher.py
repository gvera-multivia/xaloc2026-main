"""
Library for platform-agnostic process management.
Handles process launching, termination, and npm command resolution for Windows and Unix.
"""
import asyncio
import sys
import os
import signal
import subprocess
import shutil
import logging
from typing import Optional, List, Any

logger = logging.getLogger("core.process_launcher")

def setup_asyncio_policy() -> None:
    """Sets the event loop policy for Windows to ProactorEventLoop."""
    if sys.platform == "win32":
        try:
            asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
        except AttributeError:
            pass

def get_npm_command(args: List[str]) -> List[str]:
    """
    Constructs a platform-appropriate command list for running npm.

    Args:
        args: List of arguments to pass to npm (e.g. ["run", "dev"]).

    Returns:
        List of strings ready for subprocess execution.
    """
    # Finding npm executable
    npm_path = shutil.which("npm")
    if not npm_path:
        # Fallback: assume it's in path
        npm_path = "npm"

    if sys.platform == "win32":
        # On Windows, npm is typically a batch file (npm.cmd).
        # Executing it directly usually requires 'cmd /c' to work reliably with asyncio/subprocess
        # unless shell=True is used (which we avoid with create_subprocess_exec).
        return ["cmd", "/c", "npm"] + args
    else:
        # On Unix, execute npm directly
        return [npm_path] + args

async def start_async_process(
    cmd: List[str],
    *,
    cwd: Optional[str] = None,
    stdout: Any = asyncio.subprocess.PIPE,
    stderr: Any = asyncio.subprocess.PIPE,
    env: Optional[dict] = None
) -> asyncio.subprocess.Process:
    """
    Starts an async subprocess with platform-specific flags for process group management.
    Ensures that the process can be terminated cleanly later (including children).
    """
    kwargs = {}
    if sys.platform == "win32":
        # Create new process group on Windows to allow CTRL_BREAK signal
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        # Create new session on Unix to group processes
        kwargs["start_new_session"] = True

    logger.debug(f"Starting process: {cmd} (cwd={cwd})")
    return await asyncio.create_subprocess_exec(
        *cmd,
        cwd=cwd,
        stdout=stdout,
        stderr=stderr,
        env=env,
        **kwargs
    )

async def terminate_process_tree(
    proc: asyncio.subprocess.Process,
    timeout: float = 8.0
) -> dict:
    """
    Terminates a process and its children gracefully, forcing kill if necessary.

    Returns:
        Dict with status info (stopped, killed, returncode).
    """
    if proc.returncode is not None:
        return {"stopped": False, "returncode": proc.returncode, "msg": "Already stopped"}

    # 1. Graceful shutdown attempt
    if sys.platform == "win32":
        try:
            proc.send_signal(signal.CTRL_BREAK_EVENT)
        except Exception:
            proc.terminate()
    else:
        try:
            # Send SIGTERM to the process group
            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
        except ProcessLookupError:
            pass # Already gone
        except Exception:
            proc.terminate()

    killed = False
    try:
        await asyncio.wait_for(proc.wait(), timeout=timeout)
    except asyncio.TimeoutError:
        # 2. Force kill
        killed = True
        if sys.platform == "win32":
            try:
                subprocess.call(["taskkill", "/F", "/T", "/PID", str(proc.pid)])
            except Exception:
                proc.kill()
        else:
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            except Exception:
                proc.kill()

        # Final wait
        try:
            await asyncio.wait_for(proc.wait(), timeout=5.0)
        except asyncio.TimeoutError:
            logger.error(f"Process {proc.pid} stuck after kill.")

    return {
        "stopped": True,
        "killed": killed,
        "returncode": proc.returncode
    }
