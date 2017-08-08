# Copyright 2014 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""USB type-C CC line polarity check and operation flip test w/ Plankton-Raiden.

Firstly checks USB type-C cable connected direction is right by CC polarity, and
also be able to show operation instruction for cable flipping to test another
CC line.

For double CC cable, this test can flip CC automatically or you can set Arg
double_cc_flip_target as 'CC1' or 'CC2' to indicate the final CC position.
Moreover, if test scheme can guarantee double CC cable connection is not
twisted, that is, Plankton CC1 is connected to DUT CC1, then it can set Arg
double_cc_quick_check as True to accelerate the test.
"""

import logging
import threading
import time
import unittest

import factory_common  # pylint: disable=unused-import
from cros.factory.device import device_utils
from cros.factory.test import countdown_timer
from cros.factory.test import factory
from cros.factory.test.fixture import bft_fixture
from cros.factory.test.i18n import test_ui as i18n_test_ui
from cros.factory.test import test_ui
from cros.factory.test import ui_templates
from cros.factory.utils.arg_utils import Arg
from cros.factory.utils import process_utils
from cros.factory.utils import sync_utils

_TEST_TITLE = i18n_test_ui.MakeI18nLabel('Plankton USB type-C CC Detect')
_OPERATION = i18n_test_ui.MakeI18nLabel(
    'Flip USB type-C cable and plug in again...')
_NO_TIMER = i18n_test_ui.MakeI18nLabel('And press Enter key to continue...')
_WAIT_CONNECTION = i18n_test_ui.MakeI18nLabel('Wait DUT to reconnect')
_CSS = 'body { font-size: 2em; }'

_ID_OPERATION_DIV = 'operation_div'
_ID_COUNTDOWN_DIV = 'countdown_div'
_STATE_HTML = '<div id="%s"></div><div id="%s"></div>' % (
    _ID_OPERATION_DIV, _ID_COUNTDOWN_DIV)

_CC_UNCONNECT = 'UNCONNECTED'


class PlanktonCCFlipCheck(unittest.TestCase):
  """Plankton USB type-C CC line polarity check and operation flip test."""
  ARGS = [
      Arg('bft_fixture', dict, bft_fixture.TEST_ARG_HELP),
      Arg('adb_remote_test', bool, 'Run test against remote ADB target.',
          default=False),
      Arg('usb_c_index', int, 'Index of DUT USB_C port'),
      Arg('original_enabled_cc', str, 'Set "CC1" or "CC2" if you want to check '
          'what CC pin is enabled now. There is no check if it is not set.',
          optional=True),
      Arg('ask_flip_operation', bool,
          'Determine whether to ask operator to flip cable.',
          default=False),
      Arg('double_cc_flip_target', str,
          'If using double CC cable, set either "CC1" or "CC2" for the target '
          'to flip. Flip anyway if this is not set.',
          optional=True),
      Arg('double_cc_quick_check', bool,
          'If using double CC cable, set True if you guarantee CC pair is not '
          'reversed. CC polarity in Plankton side implies DUT side.',
          default=False),
      Arg('timeout_secs', int,
          'Timeout seconds for operation, set 0 for operator pressing enter '
          'key to finish operation.',
          default=0),
      Arg('state_src_ready', (int, str), 'State number of pd state SRC_READY.',
          default=22),
      Arg('wait_dut_reconnect_secs', int,
          'Wait DUT to reconnect for n seconds after CC flip. This is required '
          'if remote DUT might be disconnected a while after CC flip, e.g. DUT '
          'has no battery and will reboot on CC flip. If n equals to 0, will '
          'wait forever.', default=5),
      Arg('init_cc_state_retry_times', int, 'Retry times for init CC state.',
          default=3)
  ]

  def setUp(self):
    self._dut = device_utils.CreateDUTInterface()
    self._ui = test_ui.UI(css=_CSS)
    self._template = ui_templates.OneSection(self._ui)
    self._template.SetTitle(_TEST_TITLE)
    if self.args.ask_flip_operation and self.args.timeout_secs == 0:
      self._ui.BindKey(test_ui.ENTER_KEY, lambda _: self.OnEnterPressed())
    self._bft_fixture = bft_fixture.CreateBFTFixture(**self.args.bft_fixture)
    self._adb_remote_test = self.args.adb_remote_test
    self._double_cc_quick_check = (
        self._bft_fixture.IsDoubleCCCable() and self.args.double_cc_quick_check)
    if (not self._bft_fixture.IsParallelTest() and
        not self._double_cc_quick_check):
      # No preparation is required for parallel test.
      if self._adb_remote_test:
        # For remote test, keep adb connection enabled.
        self._bft_fixture.SetDeviceEngaged('ADB_HOST', engage=True)
      else:
        self._bft_fixture.SetDeviceEngaged('USB3', engage=True)
        self._bft_fixture.SetFakeDisconnection(1)
        time.sleep(1)
    self._polarity = self.GetCCPolarityWithRetry(
        self.args.init_cc_state_retry_times)
    logging.info('Initial polarity: %s', self._polarity)

  def GetCCPolarity(self):
    """Gets enabled CC line for USB_C port arg.usb_c_index.

    Returns:
      'CC1' or 'CC2', or _CC_UNCONNECT if it doesn't detect SRC_READY.
    """
    if not self._dut.IsReady():
      self._ui.SetHTML(_WAIT_CONNECTION, id=_ID_OPERATION_DIV)
      factory.console.info(
          'Lose connection to DUT, waiting for DUT to reconnect')
      sync_utils.WaitFor(lambda: self._dut.Call(['true']) == 0,
                         self.args.wait_dut_reconnect_secs,
                         poll_interval=1)

    # For double CC cable, if we guarantee CC pair is not reversed, polarity in
    # Plankton side implies DUT side.
    if self._double_cc_quick_check:
      return self._bft_fixture.GetPDState()['polarity']

    port_status = self._dut.usb_c.GetPDStatus(self.args.usb_c_index)
    # For newer version EC, port_status[state] will return string instead of
    # state number.
    if self._adb_remote_test or self._bft_fixture.IsParallelTest():
      # For remote or parallel test, just feedback polarity.
      return port_status['polarity']
    if (port_status['state'] == self.args.state_src_ready or
        port_status['state'] == 'SRC_READY'):
      return port_status['polarity']
    logging.info('Detected port state is not state_src_ready (expect: %s '
                 'or SRC_READY, got: %s).',
                 self.args.state_src_ready, port_status['state'])
    return _CC_UNCONNECT

  def GetCCPolarityWithRetry(self, retry_times):
    """Get the CC Polarity.

    It will retry by retry_times argument to let PD do negotiate.

    Args:
      retry_times: retry times.

    Returns:
      'CC1' or 'CC2', or _CC_UNCONNECT
    """
    # We may need some time for PD negotiate and settle down
    retry_times_left = retry_times
    polarity = self.GetCCPolarity()
    while retry_times_left != 0 and polarity == _CC_UNCONNECT:
      time.sleep(1)
      polarity = self.GetCCPolarity()
      logging.info('[%d]Poll polarity %s', retry_times_left, polarity)
      retry_times_left -= 1
    return polarity

  def tearDown(self):
    self._bft_fixture.Disconnect()

  def _PollCheckCCPolarity(self):
    while True:
      time.sleep(0.5)
      polarity = self.GetCCPolarity()
      if polarity != self._polarity and polarity != _CC_UNCONNECT:
        self._polarity = polarity
        self._ui.Pass()

  def OnEnterPressed(self):
    polarity = self.GetCCPolarity()
    if polarity != self._polarity and polarity != _CC_UNCONNECT:
      self._polarity = polarity
      self._ui.Pass()
    else:
      self._ui.Fail('DUT does not detect cable flipped. Was it really flipped?')

  def runTest(self):
    if (self.args.original_enabled_cc is not None and
        self._polarity != self.args.original_enabled_cc and
        not self._bft_fixture.IsDoubleCCCable()):
      self.fail('Original polarity is wrong (expect: %s, got: %s). '
                'Does Raiden cable connect in correct direction?' %
                (self.args.original_enabled_cc, self._polarity))

    self._template.SetState(_STATE_HTML)
    if self.args.ask_flip_operation:
      self._ui.SetHTML(_OPERATION, id=_ID_OPERATION_DIV)
      if self.args.timeout_secs == 0:
        self._ui.SetHTML(_NO_TIMER, id=_ID_COUNTDOWN_DIV)
      else:
        # Start countdown timer.
        countdown_timer.StartCountdownTimer(
            self.args.timeout_secs,
            lambda: self._ui.Fail('Timeout waiting for test to complete'),
            self._ui,
            _ID_COUNTDOWN_DIV)
        # Start polling thread
        process_utils.StartDaemonThread(target=self._PollCheckCCPolarity)
      self._ui.Run()
    elif (self._bft_fixture.IsDoubleCCCable() and
          (not self.args.double_cc_flip_target or
           self._polarity != self.args.double_cc_flip_target)):
      disable_event = threading.Event()

      if self.args.timeout_secs:
        countdown_timer.StartCountdownTimer(
            self.args.timeout_secs,
            lambda: self._ui.Fail('Timeout waiting for test to complete'),
            self._ui,
            _ID_COUNTDOWN_DIV,
            disable_event=disable_event)

      def do_flip():
        factory.console.info('Double CC test, doing CC flip...')
        #TODO(yllin): Remove this if solve the plankton firmware issue
        def charge_check_flip():
          self._bft_fixture.SetDeviceEngaged('CHARGE_5V', True)
          time.sleep(2)
          new_polarity = self.GetCCPolarityWithRetry(5)
          if new_polarity != self._polarity:
            return
          self._bft_fixture.SetMuxFlip(0)
          time.sleep(2)

        charge_check_flip()
        if self._adb_remote_test and not self._double_cc_quick_check:
          # For remote test, keep adb connection enabled.
          self._bft_fixture.SetDeviceEngaged('ADB_HOST', engage=True)

        new_polarity = self.GetCCPolarityWithRetry(5)
        disable_event.set()

        if new_polarity != self._polarity:
          self._ui.Pass()
        else:
          self._ui.Fail('Unexpected polarity')

      process_utils.StartDaemonThread(target=do_flip)
      self._ui.Run()

    logging.info('Detect polarity: %s', self._polarity)
