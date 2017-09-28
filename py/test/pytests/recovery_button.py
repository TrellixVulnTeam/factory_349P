# Copyright 2014 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Test if the recovery button works properly.

Description
-----------
For Chromebooks or Chromeboxes with a physical recovery button,
this test can be used to make sure the recovery button status
can be fetched properly.

Test Procedure
--------------
1. Press spacebar to start.
2. Press down the recovery button.

If the recovery button works properly, the test passes.
Otherwise, the test will fail after `timeout_secs` seconds.

Dependency
----------
Use `crossystem recoverysw_cur` to get recovery button status.

Examples
--------
To test recovery button with default parameters, add this in test list::

  {
    "pytest_name": "recovery_button"
  }

One can also set the timeout to 100 seconds by::

  {
    "pytest_name": "recovery_button",
    "args": {
      "timeout_secs": 100
    }
  }
"""

import time
import unittest

import factory_common  # pylint: disable=unused-import
from cros.factory.test.i18n import test_ui as i18n_test_ui
from cros.factory.test import test_ui
from cros.factory.test import ui_templates
from cros.factory.utils.arg_utils import Arg
from cros.factory.utils import process_utils

_MSG_PRESS_SPACE = i18n_test_ui.MakeI18nLabelWithClass(
    'Hit SPACE to start test...', 'recovery-button-info')

_MSG_RECOVERY_BUTTON_TEST = lambda secs, remain_secs: (
    i18n_test_ui.MakeI18nLabelWithClass(
        'Please press recovery button for {secs:.1f} seconds '
        '({remain_secs} seconds remaining).',
        'recovery-button-info', secs=secs, remain_secs=remain_secs))

_HTML_RECOVERY_BUTTON = """
<table style="width: 70%; margin: auto;">
  <tr>
    <td align="center"><div id="recovery_button_title"></div></td>
  </tr>
</table>
"""

_CSS_RECOVERY_BUTTON = """
  .recovery-button-info { font-size: 2em; }
"""


class RecoveryButtonTest(unittest.TestCase):
  """Tests Recovery Button."""
  ARGS = [
      Arg('timeout_secs', int, 'Timeout to press recovery button.',
          default=10),
      Arg('polling_interval_secs', float,
          'Interval between checking whether recovery buttion is pressed or '
          'not. Valid values: 0.2, 0.5 and 1.0', default=0.5)]

  def setUp(self):
    self.ui = test_ui.UI()
    self.template = ui_templates.OneSection(self.ui)
    self.ui.AppendCSS(_CSS_RECOVERY_BUTTON)
    self.template.SetState(_HTML_RECOVERY_BUTTON)
    self.ui.BindKey(test_ui.SPACE_KEY, self.StartTest, once=True)
    self.ui.SetHTML(_MSG_PRESS_SPACE, id='recovery_button_title')
    if self.args.polling_interval_secs not in (0.2, 0.5, 1.0):
      raise ValueError('The value of polling_interval_secs is invalid: %f' %
                       self.args.polling_interval_secs)

  def StartTest(self, event):
    del event  # Unused.
    polling_iterations_per_second = int(1 / self.args.polling_interval_secs)
    for i in xrange(self.args.timeout_secs):
      self.ui.SetHTML(
          _MSG_RECOVERY_BUTTON_TEST(
              self.args.polling_interval_secs, self.args.timeout_secs - i),
          id='recovery_button_title')
      for _ in xrange(polling_iterations_per_second):
        time.sleep(self.args.polling_interval_secs)
        if '1' == process_utils.SpawnOutput(['crossystem', 'recoverysw_cur'],
                                            log=True):
          self.ui.Pass()
          return

    self.ui.Fail('Recovery button test failed.')

  def runTest(self):
    self.ui.Run()
