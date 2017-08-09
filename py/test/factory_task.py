# Copyright 2014 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import logging
import threading

import factory_common  # pylint: disable=unused-import
from cros.factory.test import test_ui
from cros.factory.utils import process_utils
from cros.factory.utils import type_utils


TaskState = type_utils.Enum(['NOT_STARTED', 'RUNNING', 'FINISHED'])
FinishReason = type_utils.Enum(['PASSED', 'FAILED', 'STOPPED'])


class FactoryTaskManager(object):
  """Manages the execution of factory tasks in the context of the given UI.

  Args:
    ui: The test UI object that the manager depends on.
    task_list: A list of factory tasks to be executed.
    update_progress: Optional callback to update progress bar. Passing
        percent progress as parameter.
    on_finish: Optional callback to run when ui ends.
        It will be passed to ui.Run().
  """

  def __init__(self, ui, task_list, update_progress=None,
               on_finish=None):
    self._ui = ui
    self._task_list = task_list
    self._update_progress = update_progress
    self.task_finish_event = threading.Event()
    self.task_abort_event = threading.Event()
    self._on_finish = on_finish

  def RunAllTasks(self):
    self.task_abort_event.clear()
    for idx, task in enumerate(self._task_list, 1):
      # pylint: disable=protected-access
      self.task_finish_event.clear()
      task._task_manager = self
      task._ui = self._ui
      task._Start()
      self.task_finish_event.wait()
      if self.task_abort_event.is_set():
        break
      if self._update_progress:
        self._update_progress(100 * idx / len(self._task_list))
    else:
      self._ui.Pass()

  def TaskFinished(self, abort=False):
    if abort:
      self.task_abort_event.set()
    self.task_finish_event.set()

  def Run(self):
    self._ui.RunInBackground(self.RunAllTasks)
    self._ui.Run(on_finish=self._on_finish)


class FactoryTask(object):
  """Base class for factory tasks.

  Subclass should implement Run(), and possibly Cleanup() if the user
  wants to do some cleaning jobs.
  """
  _execution_status = TaskState.NOT_STARTED
  def __init__(self):
    self._ui = None
    self._task_manager = None

  def _Start(self):
    assert self._execution_status == TaskState.NOT_STARTED, (
        'Task %s has been run before.' % self.__class__.__name__)
    logging.info('Start ' + self.__class__.__name__)

    # Hook to the test_ui so that the ui can call _Finish when it
    # receives END_TEST event.
    assert self._ui.task_hook is None, 'Another task is running.'
    self._ui.task_hook = self

    self._execution_status = TaskState.RUNNING
    self.Run()

  def _Finish(self, reason, abort=False):
    """Finishes a task and performs cleanups.

    It is used for Stop, Pass, and Fail operation.

    Args:
      reason: Enum FinishReason.
    """
    logging.info('%s %s.', self.__class__.__name__, reason)
    assert self._IsRunning(), (
        'Trying to finish %s which is not running.' % (self.__class__.__name__))
    self._execution_status = TaskState.FINISHED
    self._ui.task_hook = None
    self._ui.RunJS('window.test.unbindAllKeys();'
                   'window.test.removeAllVirtualkeys();')
    self._ui.event_handlers = {}
    self.Cleanup()
    self._task_manager.TaskFinished(abort)

  def _IsRunning(self):
    return self._execution_status == TaskState.RUNNING

  def Stop(self):
    self._Finish(FinishReason.STOPPED)

  def Pass(self):
    self._Finish(FinishReason.PASSED)

  def Fail(self, error_msg, later=False):
    """Fails the task and perform cleanup.

    Args:
      error_msg: Error message.
      later: If True, it allows subsequent tasks to execute and fails its
          parent test case later.
    """
    logging.warning('%s FAILED. Reason: %s', self.__class__.__name__, error_msg)
    if not self._IsRunning():
      # Prevent multiple call of _Finish().
      return

    if later:
      self._ui.FailLater(error_msg)
      self._Finish(FinishReason.FAILED)
    else:
      self._ui.FailLater(error_msg)
      self._Finish(FinishReason.FAILED, abort=True)

  def Run(self):
    raise NotImplementedError

  def Cleanup(self):
    pass

  def RunCommand(self, command, fail_message=None, fail_later=True):
    """Executes a command and checks if it runs successfully.

    Args:
      command: command list.
      fail_message: optional string. If assigned and the command's return code
          is nonzero, Fail will be called with fail_message.
      fail_later: True to fail the parent test case later when the command
          fails to execute.

    Returns:
      True if command executes successfully; otherwise, False.
    """
    p = process_utils.Spawn(command, call=True, ignore_stdout=True,
                            read_stderr=True, log=True)
    if p.returncode != 0 and fail_message:
      self.Fail(
          '%s\nFailed running: %s\nSTDERR: %s' % (
              fail_message, ' '.join(command), p.stderr_data),
          later=fail_later)
    return p.returncode == 0


class InteractiveFactoryTask(FactoryTask):  # pylint: disable=abstract-method
  """A FactoryTask class for interactive tasks.

  It provides common key binding methods for interactive tasks.

  Args:
    ui: UI object.
  """

  def __init__(self, ui):
    super(InteractiveFactoryTask, self).__init__()
    self._ui = ui

  def BindPassFailKeys(self, pass_key=True, fail_later=True):
    """Binds pass and/or fail keys.

    If pass_key is True, binds Enter key to pass the task; otherwise, pressing
    Enter triggers nothing.
    Always binds Esc key to fail the task.

    Args:
      pass_key: True to bind Enter key to pass the task.
      fail_later: True to fail later when Esc is pressed.
    """
    if pass_key:
      self._ui.BindKey(test_ui.ENTER_KEY, lambda _: self.Pass())

    self._ui.BindKey(test_ui.ESCAPE_KEY,
                     lambda _: self.Fail(
                         '%s failed by operator.' %
                         self.__class__.__name__,
                         later=fail_later))

  def BindDigitKeys(self, pass_digit, max_digit=9, fail_later=True):
    """Binds the pass_digit to pass the task and other digits to fail it.

    To prevent operator's cheating by key swiping, we bind the remaining digit
    keys to fail the task.

    Arg:
      pass_digit: a digit [0, max_digit] to pass the task.
      max_digit: maximum digit to bind. Default 9.
      fail_later: True to fail the parent test case later when the wrong key is
          pressed.
    """
    for i in xrange(0, max_digit + 1):
      if i == pass_digit:
        self._ui.BindKey(str(i), lambda _: self.Pass())
      else:
        self._ui.BindKey(str(i), lambda _: self.Fail('Wrong key pressed.',
                                                     later=fail_later))

  def UnbindDigitKeys(self):
    """Unbinds all digit keys."""
    for i in xrange(0, 10):
      self._ui.UnbindKey(str(i))
