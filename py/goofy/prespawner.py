# Copyright (c) 2012 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.


"""A library to prespawn pytest processes to minimize startup overhead.
"""

import cPickle as pickle
import logging
import os
from Queue import Queue
import subprocess
import threading

import factory_common  # pylint: disable=unused-import
from cros.factory.test.env import paths
from cros.factory.utils.process_utils import Spawn


NUM_PRESPAWNED_PROCESSES = 1
PYTEST_PRESPAWNER_PATH = os.path.join(paths.FACTORY_DIR,
                                      'py/goofy/invocation.py')


class Prespawner(object):

  def __init__(self, prespawner_path, prespawner_args, pipe_stdout=False):
    self.prespawned = Queue(NUM_PRESPAWNED_PROCESSES)
    self.thread = None
    self.terminated = False
    self.prespawner_path = prespawner_path
    assert isinstance(prespawner_args, list)
    self.prespawner_args = prespawner_args
    self.pipe_stdout = pipe_stdout

  def spawn(self, args, env_additions=None):
    """Spawns a new process (reusing an prespawned process if available).

    @param args: A list of arguments (sys.argv)
    @param env_additions: Items to add to the current environment
    """
    new_env = dict(os.environ)
    if env_additions:
      new_env.update(env_additions)

    process = self.prespawned.get()
    # Write the environment and argv to the process's stdin; it will launch
    # test once these are received.
    pickle.dump((new_env, args), process.stdin, protocol=2)
    process.stdin.close()
    return process

  def start(self):
    """Starts a thread to pre-spawn pytests.
    """
    def run():
      while not self.terminated:
        if self.pipe_stdout:
          pipe_stdout_args = {'stdout': subprocess.PIPE,
                              'stderr': subprocess.STDOUT}
        else:
          pipe_stdout_args = {}

        process = Spawn(
            ['python', '-u', self.prespawner_path] + self.prespawner_args,
            cwd=os.path.dirname(self.prespawner_path),
            stdin=subprocess.PIPE,
            **pipe_stdout_args)
        logging.debug('Pre-spawned a test process %d', process.pid)
        self.prespawned.put(process)

      # Let stop() know that we are done
      self.prespawned.put(None)

    if not self.thread and os.path.exists(self.prespawner_path):
      self.thread = threading.Thread(target=run, name='Prespawner')
      self.thread.start()

  def stop(self):
    """Stops the pre-spawn thread gracefully.
    """
    self.terminated = True
    if self.thread:
      # Wait for any existing prespawned processes.
      while True:
        process = self.prespawned.get()
        if not process:
          break
        if process.poll() is None:
          # Send a 'None' environment and arg list to tell the prespawner
          # processes to exit.
          pickle.dump((None, None), process.stdin, protocol=2)
          process.stdin.close()
          process.wait()
      self.thread = None


#TODO(yllin): Drop PytestPrespawner. (see http://crbug.com/677368#c5)
class PytestPrespawner(Prespawner):

  def __init__(self):
    super(PytestPrespawner, self).__init__(
        PYTEST_PRESPAWNER_PATH, ['--prespawn-pytest'], pipe_stdout=True)
