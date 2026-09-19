# -*- coding: utf-8 -*-

import subprocess
import logging
logger = logging.getLogger(__name__)

def subproc_call(cmd, timeout=None):
    """
    Execute a command with timeout, and return STDOUT and STDERR

    Args:
        cmd(str|list[str]): the command to execute. Prefer a list for
            cross-platform quoting, especially on Windows paths with spaces.
        timeout(float): timeout in seconds.

    Returns:
        output(bytes), retcode(int). If timeout, retcode is -1.
    """
    try:
        output = subprocess.check_output(
            cmd,
            stderr=subprocess.STDOUT,
            shell=isinstance(cmd, str),
            timeout=timeout,
        )
        return output, 0
    except subprocess.TimeoutExpired as e:
        logger.warning("Command '%s' timeout!", cmd)
        if e.output:
            logger.warning(e.output.decode('utf-8', errors='replace'))
            return e.output, -1
        else:
            return "", -1
    except subprocess.CalledProcessError as e:
        logger.warning("Command '%s' failed, return code=%s", cmd, e.returncode)
        logger.warning(e.output.decode('utf-8', errors='replace'))
        return e.output, e.returncode
    except Exception:
        logger.warning("Command '%s' failed to run.", cmd)
        return "", -2


def subproc_succ(cmd):
    """
    Like subproc_call, but expect the cmd to succeed.
    """
    output, ret = subproc_call(cmd)
    assert ret == 0
    return output



