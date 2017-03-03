# Copyright (c) 2014 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Tests keyboard pin connectivity in SMT factory test.

Unlike keyboard test, it only expects a key sequence where keys are the keyboard
scan lines' row-column crossing points. It also can trigger a SMT testing
fixture to send out signals to simulate key presses on the key sequence.
"""

from __future__ import print_function
import evdev
import unittest

import factory_common  # pylint: disable=unused-import
from cros.factory.test import countdown_timer
from cros.factory.test import factory
from cros.factory.test.fixture import bft_fixture
from cros.factory.test.i18n import test_ui as i18n_test_ui
from cros.factory.test import test_ui
from cros.factory.test import ui_templates
from cros.factory.test.utils import evdev_utils
from cros.factory.utils.arg_utils import Arg
from cros.factory.utils import process_utils


_ID_CONTAINER = 'keyboard-test-container'
_ID_EXPECTED_SEQUENCE = 'expected-sequence'
_ID_MATCHED_SEQUENCE = 'matched-sequence'
_ID_COUNTDOWN_TIMER = 'keyboard-test-timer'

_MSG_EXPECTED_SEQUENCE = i18n_test_ui.MakeI18nLabelWithClass(
    'Expected keycode sequence:', 'test-info')

_HTML_KEYBOARD = '<br>\n'.join([
    '<div>%s <span id="%s"></span><span id="%s"></span></div>' % (
        _MSG_EXPECTED_SEQUENCE, _ID_MATCHED_SEQUENCE, _ID_EXPECTED_SEQUENCE),
    '<div id="%s" class="test-info"></div>' % _ID_COUNTDOWN_TIMER])

_KEYBOARD_TEST_DEFAULT_CSS = (
    '.test-info { font-size: 1.4em; }\n'
    '#expected-sequence { color: grey; font-size: 1.4em }\n'
    '#matched-sequence { color: black; font-size: 1.4em }\n')


class KeyboardSMTTest(unittest.TestCase):
  """Tests each keyboard scan lines are connected.

  It triggers akeyboard scan module by sending 0xC1 to fixture via RS-232.
  The keyboard scan module will send a sequence of keycodes. This test checks
  if the upcoming keyup events matche the expected keycode sequence.
  """
  ARGS = [
      Arg(
          'keyboard_event_id', int, 'Keyboard input event id.', default=None,
          optional=True),
      Arg('timeout_secs', int, 'Timeout for the test.', default=30),
      Arg(
          'keycode_sequence', tuple,
          'Expected keycode sequence generated by a keyboard scan module in '
          'the fixture.'),
      Arg('bft_fixture', dict, bft_fixture.TEST_ARG_HELP, optional=True),
      Arg(
          'debug', bool,
          'True to disable timeout and never fail. Used to observe keystrokes.',
          default=False)]

  def setUp(self):
    self.ui = test_ui.UI()
    self.template = ui_templates.OneSection(self.ui)
    self.ui.AppendCSS(_KEYBOARD_TEST_DEFAULT_CSS)

    # Initialize frontend presentation.
    self.template.SetState(_HTML_KEYBOARD)
    self.ui.CallJSFunction('setUpKeyboardTest', self.args.keycode_sequence,
                           self.args.debug)

    self.fixture = None
    if self.args.bft_fixture:
      self.fixture = bft_fixture.CreateBFTFixture(**self.args.bft_fixture)

    # Get the keyboard input device.
    if self.args.keyboard_event_id is None:
      keyboard_devices = evdev_utils.GetKeyboardDevices()
      assert len(keyboard_devices) == 1, 'Multiple keyboards detected.'
      self.event_dev = keyboard_devices[0]
    else:
      self.event_dev = evdev.InputDevice(
          '/dev/input/event%d' % self.args.keyboard_event_id)

    # Monitor keyboard event within specified time period.
    self.event_dev.grab()
    process_utils.StartDaemonThread(target=self.PollEvdevEvent)
    if not self.args.debug:
      countdown_timer.StartCountdownTimer(
          self.args.timeout_secs, self.TimeoutHandler, self.ui,
          _ID_COUNTDOWN_TIMER)

  def tearDown(self):
    self.event_dev.ungrab()

  def TimeoutHandler(self):
    """Called to fail the test when a timeout is reached."""
    self.ui.CallJSFunction(
        'failTest',
        'Timeout after %d seconds.' % self.args.timeout_secs)

  def PollEvdevEvent(self):
    """Polls evdev event."""
    for event in self.event_dev.read_loop():
      self.HandleEvdevEvent(event)

  def HandleEvdevEvent(self, event):
    """Handles evdev event.

    Notifies JS if a keyup event is received.

    Args:
      event: evdev event.
    """
    if event.type == evdev.ecodes.EV_KEY and event.value == 0:
      if self.args.debug:
        factory.console.info('keycode: %s', event.code)
      self.ui.CallJSFunction('markKeyup', event.code)

  def runTest(self):
    if self.fixture:
      self.fixture.SimulateKeystrokes()
    self.ui.Run()
