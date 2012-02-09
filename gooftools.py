# Copyright (c) 2010 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.


"""Wrapper for Google Factory Tools (gooftool).

This module provides fast access to "gooftool".
"""


import os
import glob
import subprocess
import sys
import tempfile

import factory_common
from autotest_lib.client.common_lib import error
from autotest_lib.client.cros import factory


GOOFTOOL_HOME = '/usr/local/gooftool'


def run(command, ignore_status=False):
    """Runs a gooftool command.

    Args:
        command: Shell command to execute.
        ignore_status: False to raise exectopion when execution result is not 0.

    Returns:
        (stdout, stderr, return_code) of the execution results.

    Raises:
        error.TestError: The error message in "ERROR:.*" form by command.
    """

    factory.log("Running gooftool: " + command)

    # We want the stderr goes to CONSOLE_LOG_PATH immediately, but tee only
    # works with stdout; so here's a tiny trick to swap the handles.
    swap_stdout_stderr = '3>&1 1>&2 2>&3'

    # When using pipes, return code is from the last command; so we need to use
    # a temporary file for the return code of first command.
    return_code_file = tempfile.NamedTemporaryFile()
    system_cmd = ('(PATH=%s:$PATH %s %s || echo $? >"%s") | tee -a "%s"' %
                  (GOOFTOOL_HOME, command, swap_stdout_stderr,
                   return_code_file.name, factory.CONSOLE_LOG_PATH))
    proc = subprocess.Popen(system_cmd,
                            stderr=subprocess.PIPE,
                            stdout=subprocess.PIPE,
                            shell=True)

    # The order of output is reversed because we swapped stdout and stderr.
    (err, out) = proc.communicate()

    # normalize output data
    out = out or ''
    err = err or ''
    if out.endswith('\n'):
        out = out[:-1]
    if err.endswith('\n'):
        err = err[:-1]

    # build return code and log results
    return_code_file.seek(0)
    return_code = int(return_code_file.read() or '0')
    return_code_file.close()
    return_code = proc.wait() or return_code
    message = ('gooftool result: %s (%s), message: %s' %
               (('FAILED' if return_code else 'SUCCESS'),
                return_code, '\n'.join([out,err]) or '(None)'))
    factory.log(message)

    if return_code and (not ignore_status):
        # try to parse "ERROR.*" from err & out.
        exception_message = '\n'.join(
                [error_message for error_message in err.splitlines()
                 if error_message.startswith('ERROR')]) or message
        raise error.TestError(exception_message)

    return (out, err, return_code)
