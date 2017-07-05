# Copyright (c) 2014 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.


"""A test_list for TSAB (TouchScreen calibration on AB panel) station."""


import factory_common  # pylint: disable=unused-import
from cros.factory.test.i18n import _
from cros.factory.test.test_lists.test_lists import AutomatedSequence
from cros.factory.test.test_lists.test_lists import OperatorTest
from cros.factory.test.test_lists.test_lists import TestList


_SHOPFLOOR_IP = '10.3.0.11'
_SHOPFLOOR_PORT = '8080'


def CreateTestLists():
  """Creates test list.

  This is the external interface to test list creation (called by the
  test list builder).  This function is required and its name cannot
  be changed.
  """
  with TestList('tsab_station',
                'Generic touchscreen calibration on AB panel') as tlist:
    tlist.options.shopfloor_server_url = 'http://%s:%s' % (
        _SHOPFLOOR_IP, _SHOPFLOOR_PORT)
    with AutomatedSequence(label=_('Touchscreen Calibration Sequence')):
      OperatorTest(
          label=_('Touchscreen Calibration'),
          pytest_name='touchscreen_calibration',
          dargs={'shopfloor_ip': _SHOPFLOOR_IP})

      OperatorTest(
          label=_('Sync Factory Server'),
          pytest_name='sync_factory_server',
          dargs={'update_toolkit': False})
