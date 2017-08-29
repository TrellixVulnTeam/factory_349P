# Copyright 2013 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Probes SIM card information from 'modem status'.

The first usage of this test is to insert sim card, record ICCID (IMSI) value,
then remove sim card.
A 'modem reset' is needed after plugging SIM card.
It is not needed after removing SIM card.
The second usage of this test is to make sure that SIM card is not present.
A 'modem reset' is needed to avoid the case that SIM card is inserted without
a 'modem reset'.
Before running this test, modem carrier should be set to Generic UMTS.
"""

import logging
import re
import threading
import time
import unittest
import uuid

import factory_common  # pylint: disable=unused-import
from cros.factory.test import event
from cros.factory.test import event_log
from cros.factory.test import factory_task
from cros.factory.test.i18n import test_ui as i18n_test_ui
from cros.factory.test import test_ui
from cros.factory.test import ui_templates
from cros.factory.utils.arg_utils import Arg
from cros.factory.utils import process_utils

_SIM_PRESENT_RE = r'IMSI: (\d{14,15})'
_SIM_NOT_PRESENT_RE = r'SIM: /$'

_INSERT_SIM_INSTRUCTION = i18n_test_ui.MakeI18nLabel(
    'Please insert the SIM card')
_REMOVE_SIM_INSTRUCTION = i18n_test_ui.MakeI18nLabel(
    'Detected! Please remove the SIM card')
_CHECK_SIM_INSTRUCTION = i18n_test_ui.MakeI18nLabel(
    'Checking SIM card is present or not...')

_INSERT_CHECK_PERIOD_SECS = 1
_INSERT_CHECK_MAX_WAIT = 60


def ResetModem(reset_commands):
  """Resets modem.

  Args:
    reset_commands: a list of commands to reset modem
  """
  if not reset_commands:
    process_utils.Spawn(['modem', 'reset'], call=True, log=True)
  else:
    for command in reset_commands:
      process_utils.Spawn(command, call=True, log=True)
    time.sleep(_INSERT_CHECK_PERIOD_SECS)


class WaitSIMCardThread(threading.Thread):
  """The thread to wait for SIM card state.

  Args:
    simcard_event: ProbeSIMCardTask.INSERT_SIM_CARD or
        ProbeSIMCardTask.REMOVE_SIM_CARD
    on_success: The callback function to call upon success.
  """

  def __init__(self, simcard_event, on_success, force_stop, test):
    threading.Thread.__init__(self, name='WaitSIMCardThread')
    self._done = threading.Event()
    self._simcard_event = simcard_event
    self._on_success = on_success
    self._re_present = re.compile(_SIM_PRESENT_RE, re.MULTILINE | re.IGNORECASE)
    self._re_not_present = re.compile(_SIM_NOT_PRESENT_RE,
                                      re.MULTILINE | re.IGNORECASE)
    self._force_stop = force_stop
    self._force_stop.clear()
    self._args = test.args

  def run(self):
    while not self._done.is_set() and not self._force_stop.is_set():
      # Only do modem reset when probing for insert event.
      # modem status will not show IMSI if sim card is removed even without
      # modem reset.
      if self._simcard_event == ProbeSIMCardTask.INSERT_SIM_CARD:
        if self._args.enable_modem_reset:
          ResetModem(self._args.modem_reset_commands)
      output = process_utils.SpawnOutput(['modem', 'status'], log=True)
      logging.info(output)
      present = self._re_present.search(output)
      if present:
        logging.info('present')
      not_present = self._re_not_present.search(output)
      if not_present:
        logging.info('not present')

      if self._simcard_event == ProbeSIMCardTask.INSERT_SIM_CARD and present:
        logging.info('ICCID: %s', present.group(1))
        event_log.Log('SIM_CARD_DETECTION', ICCID=present.group(1))
        self.Detected()
      elif (self._simcard_event == ProbeSIMCardTask.REMOVE_SIM_CARD
            and not_present):
        self.Detected()
      else:
        self._done.wait(_INSERT_CHECK_PERIOD_SECS)

  def Detected(self):
    """Reports detected and stops the thread."""
    logging.info('%s detected', self._simcard_event)
    self._on_success()

    # This is needed to avoid race condition that _on_success
    # does not stop this thread before the next iteration.
    self.Stop()

  def Stop(self):
    """Stops the thread."""
    self._done.set()


class ProbeSIMCardTask(factory_task.FactoryTask):
  """Probe SIM card task."""
  INSERT_SIM_CARD = 'Insertion'
  REMOVE_SIM_CARD = 'Removal'

  def __init__(self, test, instruction, simcard_event):
    super(ProbeSIMCardTask, self).__init__()
    self._ui = test.ui
    self._template = test.template
    self._force_stop = test.force_stop
    self._instruction = instruction
    self._wait_sim = WaitSIMCardThread(
        simcard_event, self.PostSuccessEvent, self._force_stop, test)
    self._pass_event = str(uuid.uuid4())

  def PostSuccessEvent(self):
    """Posts an event to trigger self.Pass()"""
    self._ui.PostEvent(event.Event(event.Event.Type.TEST_UI_EVENT,
                                   subtype=self._pass_event))

  def Run(self):
    self._template.SetState(self._instruction)
    self._ui.AddEventHandler(self._pass_event, lambda _: self.Pass())
    self._wait_sim.start()

  def Cleanup(self):
    self._wait_sim.Stop()


class InsertSIMTask(ProbeSIMCardTask):
  """Task to wait for SIM card insertion"""

  def __init__(self, test):
    super(InsertSIMTask, self).__init__(test, _INSERT_SIM_INSTRUCTION,
                                        ProbeSIMCardTask.INSERT_SIM_CARD)


class RemoveSIMTask(ProbeSIMCardTask):
  """Task to wait for SIM card removal"""

  def __init__(self, test):
    super(RemoveSIMTask, self).__init__(test, _REMOVE_SIM_INSTRUCTION,
                                        ProbeSIMCardTask.REMOVE_SIM_CARD)


class CheckSIMTask(factory_task.FactoryTask):
  """Task to check SIM card state"""

  def __init__(self, test):
    super(CheckSIMTask, self).__init__()
    self._template = test.template
    self._args = test.args

  def CheckSIMCardState(self, sim_re, fail_string):
    self._template.SetState(_CHECK_SIM_INSTRUCTION)
    if self._args.enable_modem_reset:
      ResetModem(self._args.modem_reset_commands)
    output = process_utils.SpawnOutput(['modem', 'status'], log=True)
    if self._args.poll_modem_status:
      total_delay = 0
      while not output:
        time.sleep(_INSERT_CHECK_PERIOD_SECS)
        output = process_utils.SpawnOutput(['modem', 'status'], log=True)
        total_delay += _INSERT_CHECK_PERIOD_SECS
        if total_delay >= _INSERT_CHECK_MAX_WAIT:
          self.Fail('Failed to detect sim in ' +
                    str(_INSERT_CHECK_MAX_WAIT) + ' seconds')
          return
    logging.info(output)
    if not re.compile(sim_re, re.MULTILINE | re.IGNORECASE).search(output):
      self.Fail(fail_string)
    else:
      self.Pass()

  def Run(self):
    if self._args.only_check_simcard_present:
      self.CheckSIMCardState(_SIM_PRESENT_RE,
                             'Fail to make sure sim card is present')
    elif self._args.only_check_simcard_not_present:
      self.CheckSIMCardState(_SIM_NOT_PRESENT_RE,
                             'Fail to make sure sim card is not present')


class ProbeSIMCardTest(unittest.TestCase):
  ARGS = [
      Arg('only_check_simcard_not_present', bool,
          'Only checks sim card is not present', default=False),
      Arg('only_check_simcard_present', bool,
          'Only checks sim card is present', default=False),
      Arg('poll_modem_status', bool,
          'Polls modem status until the status is available', default=False),
      Arg('modem_reset_commands', list,
          'A list of commands to reset modem', optional=True),
      Arg('enable_modem_reset', bool,
          'If true, reset modem before check status.', default=True)]

  def setUp(self):
    self.force_stop = threading.Event()

    self.ui = test_ui.UI()
    self.template = ui_templates.OneSection(self.ui)
    self._task_manager = None

  def runTest(self):

    def Done():
      self.force_stop.set()

    if (self.args.only_check_simcard_not_present or
        self.args.only_check_simcard_present):
      task_list = [CheckSIMTask(self)]
    else:
      task_list = [InsertSIMTask(self), RemoveSIMTask(self)]

    self._task_manager = factory_task.FactoryTaskManager(
        self.ui, task_list, on_finish=Done)

    self._task_manager.Run()
