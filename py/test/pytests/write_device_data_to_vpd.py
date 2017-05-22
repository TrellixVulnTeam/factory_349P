# Copyright (c) 2012 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.


"""Writes a subset device data to the RW VPD.

Data is all written as strings."""


import unittest


import factory_common  # pylint: disable=unused-import
from cros.factory.device import device_utils
from cros.factory.test.i18n import test_ui as i18n_test_ui
from cros.factory.test import state
from cros.factory.test import test_ui
from cros.factory.test import ui_templates
from cros.factory.utils.arg_utils import Arg

_MSG_WRITING_VPD = lambda vpd_section: i18n_test_ui.MakeI18nLabel(
    'Writing device data to {vpd_section} VPD...',
    vpd_section=vpd_section.upper())


class CallShopfloor(unittest.TestCase):
  ARGS = [
      Arg('device_data_keys', list,
          ('List of keys for device_data we want to write into RW_VPD.'
           'Each key is a tuple of (prefix, key) meaning that the pair '
           '(prefix + key, value) should be added into RW_VPD if there is '
           'a pair (key, value) in device_data.')),
      Arg('vpd_section', str,
          'It should be rw or ro which means RW_VPD or RO_VPD to write.',
          default='rw', optional=True),
  ]

  def setUp(self):
    self.dut = device_utils.CreateDUTInterface()

  def runTest(self):
    if self.args.vpd_section not in ['ro', 'rw']:
      self.fail('Invalid vpd_section:% r, should be %r or %r.' %
                (self.args.vpd_section, 'ro', 'rw'))

    ui = test_ui.UI()
    template = ui_templates.OneSection(ui)
    template.SetState(_MSG_WRITING_VPD(self.args.vpd_section))

    device_data = state.GetDeviceData()
    data_to_write = {}
    for prefix, key in self.args.device_data_keys:
      data_to_write[prefix + key] = device_data.get(key)

    missing_keys = [k for k, v in data_to_write.iteritems() if v is None]
    if missing_keys:
      self.fail('Missing device data keys: %r' % sorted(missing_keys))

    vpd = self.dut.vpd
    getattr(vpd, self.args.vpd_section).Update(
        dict((k, str(v)) for k, v in data_to_write.iteritems()))
