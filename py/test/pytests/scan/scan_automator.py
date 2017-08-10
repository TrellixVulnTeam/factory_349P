# Copyright 2014 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Factory test automator for 'scan' test."""

import factory_common  # pylint: disable=unused-import
from cros.factory.test import device_data
from cros.factory.test.e2e_test.automator import Automator, AutomationFunction
from cros.factory.test.e2e_test.common import AutomationMode
from cros.factory.utils import net_utils


class ScanAutomator(Automator):
  """The 'scan' factory test automator."""
  # pylint: disable=C0322, E1101
  pytest_name = 'scan'

  @AutomationFunction(automation_mode=(AutomationMode.PARTIAL,
                                       AutomationMode.FULL))
  def automateScanDefault(self, mlb_serial_number=None, serial_number=None,
                          operator_id=None):
    data_key = self.args.device_data_key or self.args.check_device_data_key
    # For scanning MLB serial number.
    if data_key == device_data.KEY_MLB_SERIAL_NUMBER:
      self.uictl.SetElementValue(
          'scan-value',
          (mlb_serial_number or 'TESTMLB-%s' % net_utils.GetWLANMACAddress()))

    # For scanning device serial number.
    elif data_key == 'serial_number':
      self.uictl.SetElementValue(
          'scan-value',
          (serial_number or 'TESTDEV-%s' % net_utils.GetWLANMACAddress()))

    # For scanning operator ID.
    elif data_key == 'smt_operator_id':
      self.uictl.SetElementValue('scan-value', (operator_id or 'Automator'))

    self.uictl.PressKey(self.uictl.KEY_ENTER)
