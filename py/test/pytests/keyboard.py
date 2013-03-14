# -*- coding: utf-8 -*-
#
# Copyright (c) 2012 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
"""
A factory test to test the functionality of keyboard.

dargs:
  layout: Use specified layout other than derived from VPD. (default: get from
      VPD)
  keyboard_device_name: Device name of keyboard. (default: 'AT Translated Set 2
      keyboard')
  keyboard_event_id: Keyboard input event id. (default: 6)
  timeout_secs: Timeout for the test. (default: 30 seconds)
  sequential_press (optional): Indicate whether keycodes need to be
      pressed sequentially or not.
"""

import os
import re
import subprocess
import unittest

from cros.factory.test import test_ui
from cros.factory.test.args import Arg
from cros.factory.test.countdown_timer import StartCountdownTimer
from cros.factory.test.ui_templates import OneSection
from cros.factory.test.utils import StartDaemonThread
from cros.factory.utils.process_utils import CheckOutput, Spawn


_RE_EVTEST_EVENT = re.compile(
    r'^Event: time .*?, type .*? \((.*?)\), code (.*?) \(.*?\), value (.*?)$')

_ID_IMAGE = 'keyboard-test-image'
_ID_COUNTDOWN_TIMER = 'keyboard-test-timer'
_HTML_KEYBOARD = (
    '<div id="%s" style="position: relative"></div>\n<div id="%s"></div>\n' %
        (_ID_IMAGE, _ID_COUNTDOWN_TIMER))

_KEYBOARD_TEST_DEFAULT_CSS = (
    '#keyboard-test-timer { font-size: 2em; }\n'
    '.keyboard-test-key-untested { display: none; }\n'
    '.keyboard-test-keydown { background-color: yellow; opacity: 0.5; }\n'
    '.keyboard-test-keyup { background-color: green; opacity: 0.5; }\n')

_POWER_KEY_CODE = 116

class KeyboardTest(unittest.TestCase):
  """Tests if all the keys on a keyboard are functioning. The test checks for
  keydown and keyup events for each key, following certain order if required,
  and passes if both events of all keys are received."""
  ARGS = [
    Arg('layout', (str, unicode), 'Use specified layout other than derived '
        'from VPD.', default=None, optional=True),
    Arg('keyboard_device_name', (str, unicode), 'Device name of keyboard.',
        default='AT Translated Set 2 keyboard'),
    Arg('keyboard_event_id', int, 'Keyboard input event id.',
        default=6),
    Arg('timeout_secs', int, 'Timeout for the test.', default=30),
    Arg('sequential_press', bool, 'Indicate whether keycodes need to be '
        'pressed sequentially or not.', default=False, optional=True),
    Arg('board', str,
        'If presents, in filename, the board name is appended after layout. ',
        default=''),
    Arg('skip_power_key', bool, 'Skip power button testing', default=False),
  ]

  def setUp(self):
    self.ui = test_ui.UI()
    self.template = OneSection(self.ui)
    self.ui.AppendCSS(_KEYBOARD_TEST_DEFAULT_CSS)

    # Initialize keyboard layout and bindings
    self.layout = self.GetKeyboardLayout()
    if self.args.board:
      self.layout += '_%s' % self.args.board
    self.bindings = self.ReadBindings(self.layout)
    if self.args.skip_power_key:
      self.bindings.pop(_POWER_KEY_CODE)

    self.key_order_list = None
    if self.args.sequential_press:
      self.key_order_list = self.ReadKeyOrder(self.layout)

    # Initialize frontend presentation
    self.template.SetState(_HTML_KEYBOARD)
    self.ui.CallJSFunction('setUpKeyboardTest', self.layout, self.bindings,
                           _ID_IMAGE, self.key_order_list)

    self.monitor_process = None
    self.EnableXKeyboard(False)
    StartDaemonThread(target=self.MonitorEvtest)
    StartCountdownTimer(self.args.timeout_secs,
                        lambda: self.ui.CallJSFunction('failTest'),
                        self.ui,
                        _ID_COUNTDOWN_TIMER)

  def tearDown(self):
    """Terminates the running process or we'll have trouble stopping the
    test."""
    if self.monitor_process.poll() is None:
      self.monitor_process.terminate()
    self.EnableXKeyboard(True)

  def GetKeyboardLayout(self):
    """Uses the given keyboard layout or auto-detect from VPD."""
    if self.args.layout:
      return self.args.layout
    vpd_layout = CheckOutput(['vpd', '-g', 'initial_locale']).strip()
    return vpd_layout if vpd_layout else 'en-US'

  def ReadBindings(self, layout):
    """Reads in key bindings and their associates figure regions."""
    bindings = None
    base = os.path.splitext(os.path.realpath(__file__))[0] + '_static'
    bindings_filename = os.path.join(base, layout + '.bindings')
    with open(bindings_filename, 'r') as f:
      bindings = eval(f.read())
    for k in bindings:
      # Convert single tuple to list of tuples
      if not isinstance(bindings[k], list):
        bindings[k] = [bindings[k],]
    return bindings

  def ReadKeyOrder(self, layout):
    """Reads in key order that must be followed when press key."""
    key_order_list = None
    base = os.path.splitext(os.path.realpath(__file__))[0] + '_static'
    key_order_list_filename = os.path.join(base, layout + '.key_order')
    with open(key_order_list_filename, 'r') as f:
      key_order_list = eval(f.read())
    return key_order_list

  def EnableXKeyboard(self, enable):
    """Enables/Disables keyboard at the X server."""
    CheckOutput(['xinput', 'set-prop', self.args.keyboard_device_name,
                 'Device Enabled', '1' if enable else '0'])

  def MonitorEvtest(self):
    """Monitors keyboard events from output of evtest."""
    self.monitor_process = Spawn(['evtest', '/dev/input/event%d' % (
                                  self.args.keyboard_event_id)],
                                 stdout=subprocess.PIPE)
    while True:
      re_obj = _RE_EVTEST_EVENT.search(self.monitor_process.stdout.readline())
      if re_obj:
        ev_type, ev_code, value = re_obj.group(1, 2, 3)
        if ev_type == 'EV_KEY' and value == '1':
          self.MarkKeydown(int(ev_code))
        elif ev_type == 'EV_KEY' and value == '0':
          self.MarkKeyup(int(ev_code))

  def MarkKeydown(self, keycode):
    """Calls Javascript to mark the given keycode as keydown."""
    if not keycode in self.bindings:
      return True
    self.ui.CallJSFunction('markKeydown', keycode)

  def MarkKeyup(self, keycode):
    """Calls Javascript to mark the given keycode as keyup."""
    if not keycode in self.bindings:
      return True
    self.ui.CallJSFunction('markKeyup', keycode)

  def runTest(self):
    self.ui.Run()
