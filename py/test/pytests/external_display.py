# Copyright 2014 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Test external display with optional audio playback test.

Description
-----------
Verify the external display is functional.

The test is defined by a list ``[display_label, display_id,
audio_info, usbpd_port]``. Each item represents an external port:

- ``display_label``: I18n display name seen by operator, e.g. ``_('VGA')``.
- ``display_id``: (str) ID used to identify display in xrandr or modeprint,
  e.g. VGA1.
- ``audio_info``: A list of ``[audio_card, audio_device, init_actions]``,
  or None:

  - ``audio_card`` is either the card's name (str), or the card's index (int).
  - ``audio_device`` is the device's index (int).
  - ``init_actions`` is a list of ``[card_name, action]`` (list).
    action is a dict key defined in audio.json (ref: audio.py) to be passed
    into dut.audio.ApplyAudioConfig.

  e.g. ``[["rt5650", "init_audio"], ["rt5650", "enable_hdmi"]]``.
  This argument is optional. If set, the audio playback test is added.
- ``usbpd_port``: (int) Verify the USB PD TypeC port status, or None.

It can also be configured to run automatically by specifying ``bft_fixture``
argument, and skip some steps by setting ``connect_only``,
``start_output_only`` and ``stop_output_only``.

Test Procedure
--------------
This test can be manual or automated depends on whether ``bft_fixture``
is specified. The test loops through all items in ``display_info`` and:

1. Plug an external monitor to the port specified in dargs.
2. (Optional) If ``audio_info.usbpd_port`` is specified, verify usbpd port
   status automatically.
3. Main display will automatically switch to the external one.
4. Press the number shown on the display to verify display works.
5. (Optional) If ``audio_info`` is specified, the speaker will play a random
   number, and operator has to press the number to verify audio functionality.
6. Unplug the external monitor to finish the test.

Dependency
----------
- Python evdev library <https://github.com/gvalkov/python-evdev>.
- ``display`` component in device API.
- Optional ``audio`` and ``usb_c`` components in device API.
- Optional fixture can be used to support automated test.

Examples
--------
To manual checking external display at USB Port 0, add this in test list::

  {
    "pytest_name": "external_display",
    "args": {
      "display_info": [
        ["i18n! Left HDMI External Display", "HDMI-A-1", null, 0]
      ]
    }
  }
"""

from __future__ import print_function

import collections
import logging
import random
import time

import factory_common  # pylint: disable=unused-import
from cros.factory.device import device_utils
from cros.factory.external import evdev
from cros.factory.test.fixture import bft_fixture
from cros.factory.test.i18n import _
from cros.factory.test.pytests import audio
from cros.factory.test import state
from cros.factory.test import test_case
from cros.factory.test.utils import evdev_utils
from cros.factory.utils.arg_utils import Arg


# Interval (seconds) of probing connection state.
_CONNECTION_CHECK_PERIOD_SECS = 1


ExtDisplayTaskArg = collections.namedtuple('ExtDisplayTaskArg', [
    'display_label', 'display_id', 'audio_card', 'audio_device', 'init_actions',
    'usbpd_port'
])


class ExtDisplayTest(test_case.TestCase):
  """Main class for external display test."""
  ARGS = [
      Arg('main_display', str,
          "xrandr/modeprint ID for ChromeBook's main display."),
      Arg('display_info', list,
          'A list of tuples (display_label, display_id, audio_info, '
          'usbpd_port) represents an external port to test.'),
      Arg('bft_fixture', dict, bft_fixture.TEST_ARG_HELP,
          default=None),
      Arg('connect_only', bool,
          'Just detect ext display connection. This is for a hack that DUT '
          'needs reboot after connect to prevent X crash.',
          default=False),
      Arg('start_output_only', bool,
          'Only start output of external display. This is for bringing up '
          'the external display for other tests that need it.',
          default=False),
      Arg('stop_output_only', bool,
          'Only stop output of external display. This is for bringing down '
          'the external display that other tests have finished using.',
          default=False),
      Arg('already_connect', bool,
          'Also for the reboot hack with fixture. With it set to True, DUT '
          'does not issue plug ext display command.',
          default=False)
  ]

  def setUp(self):
    self._dut = device_utils.CreateDUTInterface()
    self._fixture = None
    if self.args.bft_fixture:
      self._fixture = bft_fixture.CreateBFTFixture(**self.args.bft_fixture)

    self.assertLessEqual(
        [self.args.start_output_only, self.args.connect_only,
         self.args.stop_output_only].count(True),
        1,
        'Only one of start_output_only, connect_only '
        'and stop_output_only can be true.')

    self.do_connect, self.do_output, self.do_disconnect = False, False, False

    if self.args.start_output_only:
      self.do_connect = True
      self.do_output = True
    elif self.args.connect_only:
      self.do_connect = True
    elif self.args.stop_output_only:
      self.do_disconnect = True
    else:
      self.do_connect = True
      self.do_output = True
      self.do_disconnect = True

    self._toggle_timestamp = 0

    # Setup tasks
    for info in self.args.display_info:
      args = self.ParseDisplayInfo(info)

      if self.do_connect:
        self.AddTask(self.WaitConnect, args)

      if self.do_output:
        self.AddTask(self.CheckVideo, args)
        if args.audio_card:
          self.AddTask(self.SetupAudio, args)
          audio_label = _(
              '{display_label} Audio', display_label=args.display_label)
          self.AddTask(
              audio.TestAudioDigitPlayback, self.ui, self._dut, audio_label,
              card=args.audio_card, device=args.audio_device)

      if self.do_disconnect:
        self.AddTask(self.WaitDisconnect, args)

  def ParseDisplayInfo(self, info):
    """Parses lists from args.display_info.

    Args:
      info: a list in args.display_info. Refer display_info definition.

    Returns:
      Parsed ExtDisplayTaskArg.

    Raises:
      ValueError if parse error.
    """
    # Sanity check
    if len(info) not in [2, 3, 4]:
      raise ValueError('ERROR: invalid display_info item: ' + str(info))

    display_label, display_id = info[:2]
    audio_card, audio_device, init_actions, usbpd_port = None, None, None, None
    if len(info) >= 3 and info[2] is not None:
      if (not isinstance(info[2], list) or
          not isinstance(info[2][2], list)):
        raise ValueError('ERROR: invalid display_info item: ' + str(info))
      audio_card = self._dut.audio.GetCardIndexByName(info[2][0])
      audio_device = info[2][1]
      init_actions = info[2][2]

    if len(info) == 4:
      if not isinstance(info[3], int):
        raise ValueError('USB PD Port should be an integer')
      usbpd_port = info[3]

    return ExtDisplayTaskArg(
        display_label=display_label,
        display_id=display_id,
        audio_card=audio_card,
        audio_device=audio_device,
        init_actions=init_actions,
        usbpd_port=usbpd_port)

  def CheckVideo(self, args):
    self.ui.BindStandardFailKeys()
    original_primary_id = self._GetPrimaryDisplayId()
    self.SetMainDisplay(original_primary_id, False)
    try:
      if self._fixture:
        self.CheckVideoFixture(args)
      else:
        self.CheckVideoManual(args)
    finally:
      self.SetMainDisplay(original_primary_id, True)

  def CheckVideoManual(self, args):
    pass_digit = random.randrange(10)
    self.ui.SetState([
        _('Do you see video on {display}?', display=args.display_label),
        _('Press {key} to pass the test.',
          key=('<span id="pass_key">%s</span>' % pass_digit))
    ])

    key = int(self.ui.WaitKeysOnce([str(i) for i in xrange(10)]))
    if key != pass_digit:
      self.FailTask('Wrong key pressed. pressed: %d, correct: %d' %
                    (key, pass_digit))

  def CheckVideoFixture(self, args):
    """Use fixture to check display.

    When expected connection state is observed, it pass the task.
    It probes display state every second.

    Args:
      args: ExtDisplayTaskArg instance.
    """
    check_interval_secs = 1
    retry_times = 10
    # Show light green background for Fixture's light sensor checking.
    self.ui.RunJS(
        'window.template.classList.add("green-background")')
    self.ui.SetState(
        _('Fixture is checking if video is displayed on {display}?',
          display=args.display_label))
    for num_tries in xrange(1, retry_times + 1):
      try:
        self._fixture.CheckExtDisplay()
        self.PassTask()
      except bft_fixture.BFTFixtureException:
        if num_tries < retry_times:
          logging.info(
              'Cannot see screen on external display. Wait for %.1f seconds.',
              check_interval_secs)
          self.Sleep(check_interval_secs)
        else:
          self.FailTask(
              'Failed to see screen on external display after %d retries.' %
              retry_times)

  def _GetPrimaryDisplayId(self):
    for info in state.get_instance().DeviceGetDisplayInfo():
      if info['isPrimary']:
        return info['id']
    raise ValueError('Fail to get display ID')

  def SetMainDisplay(self, original_primary_id, recover_original=True):
    """Sets the main display.

    If there are two displays, this method can switch main display based on
    recover_original. If there is only one display, it returns if the only
    display is an external display (e.g. on a chromebox).

    Args:
      original_primary_id: The original primary display id.
      recover_original: True to set the original display as main;  False to
          set the other (external) display as main.
    """
    display_info = state.get_instance().DeviceGetDisplayInfo()
    if len(display_info) == 1:
      # Fail the test if we see only one display and it's the internal one.
      if display_info[0]['isInternal']:
        self.FailTask('Fail to detect external display')
      return

    # Try to switch main display for at most 5 times.
    for unused_i in range(5):
      is_original = self._GetPrimaryDisplayId() == original_primary_id
      if is_original == recover_original:
        return
      evdev_utils.SendKeys([evdev.ecodes.KEY_LEFTALT, evdev.ecodes.KEY_F4])
      self.Sleep(2)

    self.FailTask('Fail to switch main display')

  def SetupAudio(self, args):
    for card, action in args.init_actions:
      card = self._dut.audio.GetCardIndexByName(card)
      self._dut.audio.ApplyAudioConfig(action, card)

  def WaitConnect(self, args):
    self.ui.BindStandardFailKeys()
    self.ui.SetState(_('Connect external display: {display} and wait until '
                       'it becomes primary.',
                       display=args.display_label))

    self._WaitDisplayConnection(args, True)

  def WaitDisconnect(self, args):
    self.ui.BindStandardFailKeys()
    self.ui.SetState(
        _('Disconnect external display: {display}', display=args.display_label))
    self._WaitDisplayConnection(args, False)

  def _SetExtendMode(self):
    """Simulate pressing Ctrl+F4 to switch to extend mode from mirror mode."""
    t = time.time()
    # Ctrl+F4 actually toggles the mode, while what we want is extend mode.
    # It takes about 0.5 seconds to switch the mode. We should avoid pressing
    # them again in a short time or it might get back to mirror mode, so we
    # wait for 2 seconds for the previous transition to be completed.
    if self._toggle_timestamp < t - 2:
      evdev_utils.SendKeys([evdev.ecodes.KEY_LEFTCTRL, evdev.ecodes.KEY_F4])
      self._toggle_timestamp = t

  def _WaitDisplayConnection(self, args, connect):
    if self._fixture and not (connect and self.args.already_connect):
      try:
        self._fixture.SetDeviceEngaged(
            bft_fixture.BFTFixture.Device.EXT_DISPLAY, connect)
      except bft_fixture.BFTFixtureException as e:
        self.FailTask('Detect display failed: %s' % e)

    while True:
      # Check USBPD status before display info
      if (args.usbpd_port is None or
          self._dut.usb_c.GetPDStatus(args.usbpd_port)['connected'] == connect):
        port_info = self._dut.display.GetPortInfo()
        if port_info[args.display_id].connected == connect:
          display_info = state.get_instance().DeviceGetDisplayInfo()
          # In the case of connecting an external display, make sure there
          # is an item in display_info with 'isInternal' False.
          # On the other hand, in the case of disconnecting an external display,
          # we can not check display info has no display with 'isInternal' False
          # because any display for chromebox has 'isInternal' False.
          if connect and all(x['isInternal'] for x in display_info):
            self._SetExtendMode()
          else:
            logging.info('Get display info %r', display_info)
            break
      self.Sleep(_CONNECTION_CHECK_PERIOD_SECS)
