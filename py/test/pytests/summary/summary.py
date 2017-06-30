#!/usr/bin/python
# Copyright (c) 2012 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Displays a status summary for all tests in the current section.

The summary includes tests up to, but not including, this test).

For example, if the test tree is

SMT
  ...
Runin
  A
  B
  C
  report (this test)
  shutdown

...then this test will show the status summary for A, B, and C.

dargs:
  disable_input_on_fail: Disable user input to pass/fail when
    the overall status is not PASSED. If this argument is True and overall
    status is PASSED, user can pass the test by clicking the item or hitting
    space. If this argument is True and overall status is not PASSED,
    the test will hang there while the control menu can still work to
    stop/abort the test.
"""

import logging
import unittest

import factory_common  # pylint: disable=unused-import
from cros.factory.device import device_utils
from cros.factory.test import factory
from cros.factory.test.fixture import bft_fixture
from cros.factory.test.i18n import test_ui as i18n_test_ui
from cros.factory.test import state
from cros.factory.test import test_ui
from cros.factory.test import ui_templates
from cros.factory.utils.arg_utils import Arg

CSS = """
table {
  margin-left: auto;
  margin-right: auto;
  padding-bottom: 1em;
}
th, td {
  padding: 0 1em;
}
"""

_EXTERNAL_DIR = '/run/factory/external'

# The following test states are considered passed
_EXTENED_PASSED_STATE = {
    factory.TestState.PASSED,
    factory.TestState.FAILED_AND_WAIVED,
    factory.TestState.SKIPPED, }


class Report(unittest.TestCase):
  """A factory test to report test status."""
  ARGS = [
      Arg('disable_input_on_fail', bool,
          ('Disable user input to pass/fail when the overall status is not '
           'PASSED'),
          default=False),
      Arg('pass_without_prompt', bool,
          'If all tests passed, pass this test without prompting',
          default=False, optional=True),
      Arg('bft_fixture', dict,
          ('BFT fixture arguments (see bft_fixture test).  If provided, then a '
           'red/green light is lit to indicate failure/success rather than '
           'showing the summary on-screen.  The test does not fail if unable '
           'to connect to the BFT fixture.'),
          optional=True),
      Arg('accessibility', bool,
          'Display bright red background when the overall status is not PASSED',
          default=False, optional=True),
      Arg('run_factory_external_name', str,
          'Notify DUT that external test is over, will use DUT interface to '
          'write result file under /run/factory/external/<NAME>.',
          default=None, optional=True),
  ]

  def _SetFixtureStatusLight(self, all_pass):
    try:
      fixture = bft_fixture.CreateBFTFixture(**self.args.bft_fixture)
      fixture.SetStatusColor(
          fixture.StatusColor.GREEN if all_pass else fixture.StatusColor.RED)
      fixture.Disconnect()
    except bft_fixture.BFTFixtureException:
      logging.exception('Unable to set status color on BFT fixture')

  def setUp(self):
    self.dut = device_utils.CreateDUTInterface()

  def runTest(self):
    test_list = self.test_info.ReadTestList()
    test = test_list.LookupPath(self.test_info.path)
    states = state.get_instance().get_test_states()

    ui = test_ui.UI(css=CSS)
    template = ui_templates.OneSection(ui)

    statuses = []

    table = []
    for t in test.parent.subtests:
      if t == test:
        break

      test_state = states.get(t.path)

      table.append('<tr class="test-status-%s"><th>%s</th><td>%s</td></tr>'
                   % (test_state.status.replace('_', '-'),
                      test_ui.MakeTestLabel(t),
                      test_ui.MakeStatusLabel(test_state.status)))
      statuses.append(test_state.status)

    overall_status = factory.overall_status(statuses)
    all_pass = overall_status in _EXTENED_PASSED_STATE

    if all_pass:
      self.dut.hooks.OnSummaryGood()
    else:
      self.dut.hooks.OnSummaryBad()
    # state.get_instance().UpdateStatus(all_pass) will call UpdateStatus in
    # goofy_rpc.py, and notify ui to update the color of dut's tab.
    state.get_instance().UpdateStatus(all_pass)

    if self.args.bft_fixture:
      self._SetFixtureStatusLight(all_pass)

    if self.args.run_factory_external_name:
      self.dut.CheckCall(['mkdir', '-p', _EXTERNAL_DIR])
      file_path = self.dut.path.join(_EXTERNAL_DIR,
                                     self.args.run_factory_external_name)
      if all_pass:
        self.dut.WriteFile(file_path, 'PASS')
      else:
        report = ''
        for t in test.parent.Walk():
          if not t.IsLeaf():
            continue
          test_state = states.get(t.path)
          report += '%s: %s\n' % (t.path, test_state.status)
        self.dut.WriteFile(file_path, report)

    if all_pass and self.args.pass_without_prompt:
      return

    html = ['<div class="test-vcenter-outer"><div class="test-vcenter-inner">']

    if not self.args.disable_input_on_fail or all_pass:
      html = html + [
          '<a onclick="onclick:window.test.pass()" href="#">',
          i18n_test_ui.MakeI18nLabel('Click or press SPACE to continue'),
          '</a><br>'
      ]
    else:
      html = html + [
          i18n_test_ui.MakeI18nLabel(
              'Unable to proceed, since some previous tests have not passed.')
      ]

    html = html + [
        i18n_test_ui.MakeI18nLabel(
            'Test Status for {test}:', test=test.parent.path),
        '<div class="test-status-%s" style="font-size: 300%%">%s</div>' %
        (overall_status, test_ui.MakeStatusLabel(overall_status)), '<table>'
    ] + table + ['</table>'] + ['</div></div>']

    if self.args.accessibility and not all_pass:
      html = ['<div class="test-vcenter-accessibility">'] + html + ['</div>']

    if not self.args.disable_input_on_fail:
      ui.EnablePassFailKeys()
    # If disable_input_on_fail is True, and overall status is PASSED, user
    # can only pass the test.
    elif all_pass:
      ui.BindStandardKeys(bind_fail_keys=False)

    template.SetState(''.join(html))
    logging.info('starting ui.Run with overall_status %r', overall_status)
    ui.Run()
