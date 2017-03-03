# Copyright (c) 2013 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Probes SIM card tray

Detects SIM card tray by GPIO.

Args:
  tray_already_present:SIM card tray is in machine before test starts.
  tray_detection_gpio: SIM card tray detection gpio number.
"""

import logging
import os
import threading
import time
import unittest
import uuid

import factory_common  # pylint: disable=unused-import
from cros.factory.test import countdown_timer
from cros.factory.test import event
from cros.factory.test import factory
from cros.factory.test import factory_task
from cros.factory.test.i18n import test_ui as i18n_test_ui
from cros.factory.test import test_ui
from cros.factory.test import ui_templates
from cros.factory.utils.arg_utils import Arg
from cros.factory.utils import file_utils


_TEST_TITLE = i18n_test_ui.MakeI18nLabel('SIM Card Tray Test')
_INSERT_TRAY_INSTRUCTION = i18n_test_ui.MakeI18nLabelWithClass(
    'Please insert the SIM card tray', 'instruction-font-size')
_REMOVE_TRAY_INSTRUCTION = i18n_test_ui.MakeI18nLabelWithClass(
    'Detected! Please remove the SIM card tray', 'instruction-font-size')

_ID_INSTRUCTION = 'sim-card-tray-test-container'
_ID_COUNTDOWN_TIMER = 'sim-card-tray-test-timer'

_CSS = """
.instruction-font-size {
  font-size: 2em;
}
"""

_HTML_SIM_CARD_TRAY = """
<div id="%s" style="position: relative; width: 100%%; height: 60%%;"></div>
<div id="%s"></div>
""" % (_ID_INSTRUCTION, _ID_COUNTDOWN_TIMER)

_INSERT_CHECK_PERIOD_SECS = 1
_GPIO_PATH = os.path.join('/sys', 'class', 'gpio')


class WaitTrayThread(threading.Thread):
  """The thread to wait for SIM card tray state.

  Args:
    get_detect: function to probe sim card tray. Returns ProbeTrayTask.INSERTED
      or ProbeTrayTask.REMOVED.
    tray_event: The target tray event. ProbeTrayTask.INSERTED or
      ProbeTrayTask.REMOVED.
    on_success: The callback function when tray_event is detected.
  """

  def __init__(self, get_detect, tray_event, on_success):
    threading.Thread.__init__(self, name='WaitTrayThread')
    self._get_detect = get_detect
    self._tray_event = tray_event
    self._on_success = on_success
    self.daemon = True

  def run(self):
    logging.info('wait for %s event', self._tray_event)
    while True:
      ret = self._get_detect()
      if self._tray_event == ret:
        self.Detected()
        return
      time.sleep(_INSERT_CHECK_PERIOD_SECS)

  def Detected(self):
    """Reports detected and stops the thread."""
    logging.info('%s detected', self._tray_event)
    factory.console.info('%s detected', self._tray_event)
    self._on_success()


class ProbeTrayTask(factory_task.FactoryTask):
  """Probe SIM card tray task."""
  INSERTED = 'Inserted'
  REMOVED = 'Removed'

  def __init__(self, test, instruction, tray_event):
    super(ProbeTrayTask, self).__init__()
    self._ui = test.ui
    self._template = test.template
    self._instruction = instruction
    self._tray_event = tray_event
    self._timeout_secs = test.args.timeout_secs
    self._wait_tray = WaitTrayThread(test.GetDetection,
                                     self._tray_event, self.PostSuccessEvent)
    self._pass_event = str(uuid.uuid4())
    self._disable_timer = threading.Event()

  def Timeout(self):
    """Callback function for CountDownTimer"""
    self.Fail('Timeout after %s seconds' % self._timeout_secs)

  def PostSuccessEvent(self):
    """Posts an event to trigger self.Pass()

    It is called by another thread. It ensures that self.Pass() is called
    via event queue to prevent race condition.
    """
    self._disable_timer.set()
    self._ui.PostEvent(event.Event(event.Event.Type.TEST_UI_EVENT,
                                   subtype=self._pass_event))

  def Run(self):
    self._ui.SetHTML(self._instruction, id=_ID_INSTRUCTION)
    self._ui.AddEventHandler(self._pass_event, lambda _: self.Pass())
    self._wait_tray.start()
    countdown_timer.StartCountdownTimer(
        self._timeout_secs, self.Timeout,
        self._ui, _ID_COUNTDOWN_TIMER, self._disable_timer)

  def Cleanup(self):
    self._disable_timer.set()


class InsertTrayTask(ProbeTrayTask):
  """Task to wait for SIM card tray insertion"""

  def __init__(self, test):
    super(InsertTrayTask, self).__init__(test, _INSERT_TRAY_INSTRUCTION,
                                         ProbeTrayTask.INSERTED)


class RemoveTrayTask(ProbeTrayTask):
  """Task to wait for SIM card tray removal"""

  def __init__(self, test):
    super(RemoveTrayTask, self).__init__(test, _REMOVE_TRAY_INSTRUCTION,
                                         ProbeTrayTask.REMOVED)


class ProbeTrayException(Exception):
  pass


class ProbeSimCardTrayTest(unittest.TestCase):
  """Test to probe sim card tray.

  Usage examples:
    1.Just check presence or absence:
      tray_already_present=True/False
    2.Ask user to insert tray:
      tray_already_present=False,
      insert=True,
      only_check_presence=False
    3.Ask user to remove tray:
      tray_already_present=True,
      remove=True,
      only_check_presence=False
    4.Ask user to insert then remove tray.
      tray_already_present=False,
      insert=True,
      remove=True,
      only_check_presence=False
    5.Ask user to remove then insert tray.
      tray_already_present=True,
      insert=True,
      remove=True,
      only_check_presence=False
  """
  ARGS = [
      Arg('timeout_secs', int,
          'timeout in seconds for insertion/removal', default=10),
      Arg('tray_already_present', bool,
          'SIM card tray is in machine before test starts', default=False),
      Arg('tray_detection_gpio', int,
          'SIM card tray detection gpio number', default=159),
      Arg('insert', bool, 'Check sim card tray insertion', default=False),
      Arg('remove', bool, 'Check sim card tray removal', default=False),
      Arg('only_check_presence', bool,
          'Only checks sim card tray presence matches tray_already_present. '
          'No user interaction required', default=True),
      Arg('gpio_active_high', bool, 'Whether GPIO is active high.',
          default=True)]

  def setUp(self):
    self.ui = test_ui.UI()
    self.template = ui_templates.OneSection(self.ui)
    self.template.SetState(_HTML_SIM_CARD_TRAY)
    self.ui.AppendCSS(_CSS)
    self._task_manager = None
    self._detection_gpio_path = os.path.join(
        _GPIO_PATH, 'gpio%d' % self.args.tray_detection_gpio)

  def ExportGPIO(self):
    """Exports GPIO of tray detection pin.

    Raises:
      ProbeTrayException if gpio can not be exported.
    """
    if os.path.exists(self._detection_gpio_path):
      logging.info('gpio %s was exported before', self._detection_gpio_path)
      return
    export_path = os.path.join(_GPIO_PATH, 'export')
    try:
      file_utils.WriteFile(export_path, str(self.args.tray_detection_gpio),
                           log=True)
    except IOError:
      logging.exception('Can not write %s into %s',
                        str(self.args.tray_detection_gpio), export_path)
      raise ProbeTrayException('Can not export detection gpio %s' %
                               self.args.tray_detection_gpio)
    direction_path = os.path.join(self._detection_gpio_path, 'direction')
    try:
      file_utils.WriteFile(direction_path, 'out', log=True)
    except IOError:
      logging.exception('Can not write "out" into %s', direction_path)
      raise ProbeTrayException('Can set detection gpio direction to out')

  def GetDetection(self):
    """Returns tray status ProbeTrayTask.INSERTED or ProbeTrayTask.REMOVED."""
    value_path = os.path.join(self._detection_gpio_path, 'value')
    lines = file_utils.ReadLines(value_path)
    if not lines:
      raise ProbeTrayException('Can not get detection result from %s' %
                               value_path)
    ret = lines[0].strip()
    if ret not in ['0', '1']:
      raise ProbeTrayException('Get invalid detection %s from %s',
                               ret, value_path)
    if self.args.gpio_active_high:
      return ProbeTrayTask.INSERTED if ret == '1' else ProbeTrayTask.REMOVED
    else:
      return ProbeTrayTask.INSERTED if ret == '0' else ProbeTrayTask.REMOVED

  def CheckPresence(self):
    self.assertEquals(
        self.args.tray_already_present,
        self.GetDetection() == ProbeTrayTask.INSERTED,
        ('Unexpected tray %s' % (
            'absence. ' if self.args.tray_already_present else 'presence. ') +
         'Please %s SIM card tray and retest.' % (
             'insert' if self.args.tray_already_present else 'remove')))

  def runTest(self):
    self.template.SetTitle(_TEST_TITLE)
    self._detection_gpio_path = os.path.join(
        _GPIO_PATH, 'gpio%d' % self.args.tray_detection_gpio)
    self.ExportGPIO()
    self.CheckPresence()

    if self.args.only_check_presence:
      factory.console.info('Passes the test that only checks presence is %s.',
                           self.args.tray_already_present)
      return

    task_list = []
    if self.args.tray_already_present:
      self.assertTrue(self.args.remove, 'Must set remove to Ture '
                      'since tray_already_present is True')
      task_list.append(RemoveTrayTask(self))
      if self.args.insert:
        task_list.append(InsertTrayTask(self))
    else:
      self.assertTrue(self.args.insert, 'Must set insert to Ture '
                      'since tray_already_present is False')
      task_list.append(InsertTrayTask(self))
      if self.args.remove:
        task_list.append(RemoveTrayTask(self))

    self._task_manager = factory_task.FactoryTaskManager(self.ui, task_list)
    self._task_manager.Run()
