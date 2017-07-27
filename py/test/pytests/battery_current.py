# Copyright 2013 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""A factory test to test battery charging/discharging current.

Description
-----------
Test battery charging and discharging current.

If `usbpd_info` is set, also prompt operator to insert a power adapter of given
voltage to the given USB type C port.

The `usbpd_info` is a sequence `(usbpd_port, min_millivolt, max_millivolt)`,
represent the USB type C port to insert power adapter:

- ``usbpd_port``: (int) usbpd_port number. Specify which port to insert power
  line.
- ``min_millivolt``: (int) The minimum millivolt the power must provide.
- ``max_millivolt``: (int) The maximum millivolt the power must provide.

Test Procedure
--------------
1. If `max_battery_level` is set, check that initial battery level is lower
   than the value.
2. If `usbpd_info` is set, prompt the operator to insert a power adapter of
   given voltage to the given USB type C port, and pass this step when one is
   detected.
3. If `min_charging_current` is set, force the power into charging mode, and
   check if the charging current is larger than the value.
4. If `min_discharging_current` is set, force the power into discharging mode,
   and check if the discharging current is larger than the value.

Each step would fail after `timeout_secs` seconds.

Dependency
----------
Device API cros.factory.device.power.

If `usbpd_info` is set, device API cros.factory.device.usb_c.GetPDPowerStatus
is also used.

Examples
--------
To check battery can charge and discharge, add this in test list::

  OperatorTest(
      pytest_name='battery_current',
      dargs={
          'min_charging_current': 250,
          'min_discharging_current': 400
      })

To check that a 15V USB type C power adapter is connected to port 0, add this
in test list::

  OperatorTest(
      pytest_name='battery_current',
      dargs={
          'usbpd_info': [0, 14500, 15500],
          'usbpd_prompt': _('USB TypeC')
      })
"""

import logging
import time
import unittest

import factory_common  # pylint: disable=unused-import
from cros.factory.device import device_utils
from cros.factory.test.i18n import _
from cros.factory.test.i18n import arg_utils as i18n_arg_utils
from cros.factory.test.i18n import test_ui as i18n_test_ui
from cros.factory.test import test_ui
from cros.factory.test import ui_templates
from cros.factory.utils.arg_utils import Arg
from cros.factory.utils import sync_utils

_TEST_TITLE = i18n_test_ui.MakeI18nLabel('Battery Current Test')


def _PROMPT_TEXT(charge, current, target):
  return i18n_test_ui.MakeI18nLabel(
      'Waiting for {target_status} current to meet {target_current} mA.'
      ' (Currently {status} at {current} mA)',
      target_status=_('charging') if charge else _('discharging'),
      target_current=target,
      status=_('charging') if current >= 0 else _('discharging'),
      current=abs(current))

_CHARGE_TEXT = lambda c, t: _PROMPT_TEXT(True, c, t)
_DISCHARGE_TEXT = lambda c, t: _PROMPT_TEXT(False, c, t)
_USBPDPORT_PROMPT = (lambda prompt, v: i18n_test_ui.MakeI18nLabel(
    'Insert power to {prompt}({voltage}mV)', prompt=prompt, voltage=v))


class BatteryCurrentTest(unittest.TestCase):
  """A factory test to test battery charging/discharging current.
  """
  ARGS = [
      Arg('min_charging_current', int,
          'minimum allowed charging current', optional=True),
      Arg('min_discharging_current', int,
          'minimum allowed discharging current', optional=True),
      Arg('timeout_secs', int,
          'Test timeout value', default=10, optional=True),
      Arg('max_battery_level', int,
          'maximum allowed starting battery level', optional=True),
      Arg('usbpd_info', (list, tuple),
          'A sequence (usbpd_port, min_millivolt, max_millivolt) used to '
          'select a particular port from a multi-port DUT.',
          optional=True),
      i18n_arg_utils.I18nArg('usbpd_prompt',
                             'prompt operator which port to insert',
                             default='')
  ]

  def setUp(self):
    """Sets the test ui, template and the thread that runs ui. Initializes
    _power."""
    i18n_arg_utils.ParseArg(self, 'usbpd_prompt')

    self._dut = device_utils.CreateDUTInterface()
    self._power = self._dut.power
    self._ui = test_ui.UI()
    self._template = ui_templates.OneSection(self._ui)
    self._template.SetTitle(_TEST_TITLE)
    if self.args.usbpd_info:
      self._CheckUSBPDInfoArg(self.args.usbpd_info)
      self._usbpd_port = self.args.usbpd_info[0]
      self._usbpd_min_millivolt = self.args.usbpd_info[1]
      self._usbpd_max_millivolt = self.args.usbpd_info[2]
    self._usbpd_prompt = self.args.usbpd_prompt

  def _CheckUSBPDInfoArg(self, info):
    if len(info) == 5:
      check_types = (int, basestring, basestring, int, int)
    elif len(info) == 3:
      check_types = (int, int, int)
    else:
      raise ValueError('ERROR: invalid usbpd_info item: ' + str(info))

    for i in xrange(len(info)):
      if not isinstance(info[i], check_types[i]):
        logging.error('(%s)usbpd_info[%d] type is not %s', type(info[i]), i,
                      check_types[i])
        raise ValueError('ERROR: invalid usbpd_info[%d]: ' % i + str(info))

  def _LogCurrent(self, current):
    if current >= 0:
      logging.info('Charging current = %d mA', current)
    else:
      logging.info('Discharging current = %d mA', -current)

  def _CheckUSBPD(self):
    for unused_i in range(10):
      status = self._dut.usb_c.GetPDPowerStatus()
      self._template.SetState(_USBPDPORT_PROMPT(self._usbpd_prompt, 0))
      if 'millivolt' not in status[self._usbpd_port]:
        logging.info('No millivolt detected in port %d', self._usbpd_port)
        return False
      millivolt = status[self._usbpd_port]['millivolt']
      logging.info('millivolt %d, acceptable range (%d, %d)', millivolt,
                   self._usbpd_min_millivolt, self._usbpd_max_millivolt)
      self._template.SetState(_USBPDPORT_PROMPT(self._usbpd_prompt, millivolt))
      if not (self._usbpd_min_millivolt <= millivolt and
              millivolt <= self._usbpd_max_millivolt):
        return False
      time.sleep(0.1)
    return True

  def _CheckCharge(self):
    current = self._power.GetBatteryCurrent()
    target = self.args.min_charging_current
    self._LogCurrent(current)
    self._template.SetState(_CHARGE_TEXT(current, target))
    return current >= target

  def _CheckDischarge(self):
    current = self._power.GetBatteryCurrent()
    target = self.args.min_discharging_current
    self._LogCurrent(current)
    self._template.SetState(_DISCHARGE_TEXT(current, target))
    return -current >= target

  def runTest(self):
    self._ui.RunInBackground(self._runTest)
    self._ui.Run()

  def _runTest(self):
    """Main entrance of charger test."""
    self.assertTrue(self._power.CheckBatteryPresent())
    if self.args.max_battery_level:
      self.assertLessEqual(self._power.GetChargePct(),
                           self.args.max_battery_level,
                           'Starting battery level too high')
    if self.args.usbpd_info is not None:
      sync_utils.PollForCondition(
          poll_method=self._CheckUSBPD, poll_interval_secs=0.5,
          condition_name='CheckUSBPD',
          timeout_secs=self.args.timeout_secs)
    if self.args.min_charging_current:
      self._power.SetChargeState(self._power.ChargeState.CHARGE)
      sync_utils.PollForCondition(
          poll_method=self._CheckCharge, poll_interval_secs=0.5,
          condition_name='ChargeCurrent',
          timeout_secs=self.args.timeout_secs)
    if self.args.min_discharging_current:
      self._power.SetChargeState(self._power.ChargeState.DISCHARGE)
      sync_utils.PollForCondition(
          poll_method=self._CheckDischarge, poll_interval_secs=0.5,
          condition_name='DischargeCurrent',
          timeout_secs=self.args.timeout_secs)

  def tearDown(self):
    # Must enable charger to charge or we will drain the battery!
    self._power.SetChargeState(self._power.ChargeState.CHARGE)
