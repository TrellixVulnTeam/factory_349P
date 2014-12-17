# Copyright (c) 2014 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Wrapper of servod interface.

The module provides a simple interface for factory tests to access servod.
Servod is usually running remotely on another device to control Whale fixture.

The ServoClient imitates the logic of dut-control in hdctools. Like dut-control,
ServoClient also uses general string-based interface. So we do not need to
maintain duplicated schema config in both factory and hdctools.

Run 'dut-control -i' to check available attributes of ServoClient for a specific
whale board.

Usage example::

  sc = ServoClient('192.168.0.2', 9999)

  # set attribute
  sc.whale_input_rst = 'on'
  sc.whale_input_rst = 'off'

  # get attribute
  button_state = sc.whale_fixture_start_btn

  # reset servo controls to default values
  sc.hwinit()
"""

from __future__ import print_function
import re
import xmlrpclib

import factory_common  # pylint: disable=W0611
from cros.factory import common
from cros.factory.utils.net_utils import TimeoutXMLRPCServerProxy


# Whale's buttons. Can get its value ('on'/'off').
WHALE_BUTTON = common.AttrDict(dict(
    BUG_FILING = 'whale_bug_filing_btn',
    EC_FLASH = 'whale_ec_flash_btn',
    FIXTURE_START = 'whale_fixture_start_btn',
    FIXTURE_STOP = 'whale_fixture_stop_btn',
    FW_FLASH = 'whale_fw_flash_btn',
    IMAGE_FLASH = 'whale_image_flash_btn',
    RESERVE_1 = 'whale_reserve_btn1',
    RESERVE_2 = 'whale_reserve_btn2',
    RESERVE_3 = 'whale_reserve_btn3',
    USBIMG_FLASH = 'whale_usbimg_flash_btn',
    # Treat three latched feedback as button.
    WHALE_FB1 = 'whale_a_fb1',
    WHALE_FB2 = 'whale_a_fb2',
    WHALE_FB3 = 'whale_a_fb3'))
WHALE_BUTTONS = tuple(WHALE_BUTTON.values())

# Fixture mechanics feedback 1 ~ 14. Can get its value ('on'/'off').
FIXTURE_FEEDBACK = common.AttrDict(
    dict(('FB%d' % i, 'fixture_fb%d' % i) for i in range(1, 15)))
FIXTURE_FEEDBACK.update(dict(
    NEEDLE_CYLINDER_LEFT_RELEASE = 'fixture_fb1',
    NEEDLE_CYLINDER_LEFT_ACTIVE = 'fixture_fb2',
    NEEDLE_CYLINDER_RIGHT_RELEASE = 'fixture_fb3',
    NEEDLE_CYLINDER_RIGHT_ACTIVE = 'fixture_fb4',
    HOOK_CYLINDER_LEFT_ACTIVE = 'fixture_fb5',
    HOOK_CYLINDER_RIGHT_ACTIVE = 'fixture_fb6',
    LATERAL_CYLINDER_LEFT_RELEASE = 'fixture_fb7',
    LATERAL_CYLINDER_LEFT_ACTIVE = 'fixture_fb8',
    LATERAL_CYLINDER_RIGHT_RELEASE = 'fixture_fb9',
    LATERAL_CYLINDER_RIGHT_ACTIVE = 'fixture_fb10',
    COVER_CYLINDER_RELEASE = 'fixture_fb11',
    COVER_CYLINDER_ACTIVE = 'fixture_fb12',
    DUT_SENSOR = 'fixture_fb13',
    NC = 'fixture_fb14'))

# Plankton feedback 1 ~ 8. Can get its value ('on'/'off').
PLANKTON_FEEDBACK = common.AttrDict(
    dict(('FB%d' % i, 'plankton_fb%d' % i) for i in range(1, 9)))

# Tuple of Whale's latchless feedback
WHALE_FEEDBACKS = tuple(set(FIXTURE_FEEDBACK.values() +
                            PLANKTON_FEEDBACK.values()))

# A dip switch to enable debug mode. Can get its value ('on'/'off').
WHALE_DEBUG_MODE_EN = 'whale_debug_mode_en'

# Whale's control components. Can get/set its value ('on'/'off').
WHALE_CONTROL = common.AttrDict(dict(
    ADC = 'whale_adc',
    AUDIO_PLUG = 'whale_audio_plug_det',
    BATTERY = 'whale_battery_on',
    DC = 'whale_dc_in',
    # Note that Whale's 'whale_elctro_magnet' is NC now and use
    # 'whale_fixture_ctrl5' instead.
    ELECTRO_MAGNET = 'whale_fixture_ctrl5',
    FAIL_LED = 'whale_fail_led',
    FIXTURE_PUSH_NEEDLE = 'whale_fixture_ctrl1',
    FIXTURE_HOOK_COVER = 'whale_fixture_ctrl2',
    FIXTURE_PLUG_LATERAL = 'whale_fixture_ctrl3',
    FIXTURE_CLOSE_COVER = 'whale_fixture_ctrl4',
    FIXTURE_RELAY = 'whale_fixture_ctrl5',
    FIXTURE_NC = 'whale_fixture_ctrl6',
    INPUT_RESET = 'whale_input_rst',
    KEYBOARD_SHIFT_REGISTER_CLOCK = 'whale_kb_shfg_clk',
    KEYBOARD_SHIFT_REGISTER_DATA = 'whale_kb_shfg_data',
    KEYBOARD_SHIFT_REGISTER_LATCH = 'whale_kb_shfg_latch',
    KEYBOARD_SHIFT_REGISTER_RESET = 'whale_kb_shfg_rst',
    LCM_CMD = 'whale_lcm_cmd',
    LCM_ROW = 'whale_lcm_row',
    LCM_TEXT = 'whale_lcm_text',
    OUTPUT_RESERVE_1 = 'whale_output_reserve1',
    OUTPUT_RESERVE_2 = 'whale_output_reserve2',
    OUTPUT_RESERVE_3 = 'whale_output_reserve3',
    PASS_LED = 'whale_pass_led',
    USBHUB_RESET = 'whale_usbhub_rst',
    WRITE_PROTECT = 'whale_write_protect',
    EXPANDER_RESET = 'whale_xpander_rst'))

WHALE_INA = common.AttrDict(dict((v.upper(), 'krill_%s_mv' % v) for v in [
    'pp3300_dsw_gated', 'pp3300_pch', 'pp3300_lcd', 'pp1800_codec',
    'pp1200_cpu', 'pp3300_lte', 'pp1050_vccst', 'pp1050_pch_sus', 'pp5000',
    'pp3300_pch_sus', 'pp3300_wlan', 'pp3300_ssd', 'pp3300_ec', 'pp1200_ddr',
    'pp1050_modphy', 'pp1050_pch']))

WHALE_INAS = tuple(WHALE_INA.values())


class ServoClientError(Exception):
  """Exception for ServoClient by filtering out actual error messages."""
  def __init__(self, text, e=None):
    """Constructor for ServoClientError Class

    Args:
      text: A string, error message generated by caller of exception handler
      e: (optional) An Exception object supplied by the caught exception.
          For xmlrpclib.Fault.faultString, it has the following format:
            <type 'exception type'>:'actual error message'
    """
    if e is None:
      message = text
    elif isinstance(e, xmlrpclib.Fault):
      xmlrpc_error = re.sub('^.*>:', '', e.faultString)
      message = '%s :: %s' % (text, xmlrpc_error)
    else:
      message = '%s :: %s' % (text, e)
    # Pass the message to Exception class.
    super(ServoClientError, self).__init__(message)


class ServoClient(object):
  """Class for servod client to interface with servod via XMLRPC.

  You can set/get servo controls by setting/getting the corresponding
  attributes of this class.

  All exceptions happening in ServoClient are raised as ServoClientError.
  """
  def __init__(self, host, port, timeout=10, verbose=False):
    """Constructor.

    Args:
      host: Name or IP address of servo server host.
      port: TCP port on which servod is listening on.
      timeout: Timeout for HTTP connection.
      verbose: Enables verbose messaging across xmlrpclib.ServerProxy.
    """
    remote = 'http://%s:%s' % (host, port)
    # __setattr__ of this class is overriden.
    super(ServoClient, self).__setattr__(
        '_server', TimeoutXMLRPCServerProxy(remote, timeout=timeout,
                                            verbose=verbose, allow_none=True))

  def Get(self, name):
    """Gets the value from servo for control name.

    Args:
      name: String, name of control to get value from.

    Returns:
      Value read from the control.

    Raises:
      ServoClientError: If error occurs when getting value.
    """
    try:
      return self._server.get(name)
    except Exception as e:
      raise ServoClientError('Problem getting %r' % name, e)

  def MultipleGet(self, names):
    """Checks multiple controls' value.

    It uses servod set_get_all() to get multiple controls' value at once.

    Args:
      name: list of controls' names.

    Returns:
      dict of control_name: value

    Raises:
      ServoClientError: If error occurs when getting value.
    """
    try:
      return dict(zip(names, self._server.set_get_all(names)))
    except Exception as e:
      raise ServoClientError('Problem getting controls %s' % repr(names), e)

  @staticmethod
  def _OnOffToBool(name, value):
    """A helper to convert 'on' to True, 'off' to False and raise otherwise.

    Args:
      name: control name.
      value: 'on'/'off'

    Returns:
      True if the control's value is 'on'.
      False if the control's value is 'off'.

    Raises:
      ServoClientError: If error occurs when getting value or value is neither
          'on' or 'off'.
    """
    if value == 'on':
      return True
    elif value == 'off':
      return False
    raise ServoClientError(
        'Control %r value %r is neither "on" nor "off".' % (name, value))

  def IsOn(self, name):
    """Checks if the control's value is 'on'.

    Args:
      name: String, name of control to get value from.

    Returns:
      True if the control's value is 'on'.
      False if the control's value is 'off'.

    Raises:
      ServoClientError: If error occurs when getting value or value is neither
          'on' or 'off'.
    """
    return self._OnOffToBool(name, self.Get(name))

  def MultipleIsOn(self, names):
    """Checks multiple controls' value is 'on'.

    It uses servod set_get_all() to get multiple controls' IsOn values at once.

    Args:
      name: list of controls' names.

    Returns:
      dict of control_name: is_control_on (True/False).

    Raises:
      ServoClientError: If error occurs when getting value.
    """
    return dict((name, self._OnOffToBool(name, value))
                for name, value in self.MultipleGet(names).iteritems())

  def Set(self, name, value):
    """Sets the value from servo for control name.

    Args:
      name: String, name of control to set.
      value: String, value to set control to.

    Raises:
      ServoClientError: If error occurs when setting value.
    """
    try:
      self._server.set(name, value)
    except Exception as e:
      raise ServoClientError('Problem setting %r to %r' % (name, value), e)

  def MultipleSet(self, name_value_pairs):
    """Sets a list of (control_name, value) from servo.

    It uses servod set_get_all() to set multiple controls' value at once to
    boost speed. Note that it sets value in sequence so the two code pieces are
    equivalent:
    A) Set('ctrl_1', 'on')
       Set('ctrl_1', 'off')
    B) MultipleSet([('ctrl_1', 'on'), ('ctrl_1', 'off')])

    Args:
      name_value_pairs: list of (control_name, value_to_set).

    Raises:
      ServoClientError: If error occurs when setting value.
    """
    try:
      self._server.set_get_all(['%s:%s' % (n, v) for n, v in name_value_pairs])
    except Exception as e:
      raise ServoClientError('Problem setting %r' % name_value_pairs, e)

  def Enable(self, name):
    """Sets the control's value to 'on'.

    Args:
      name: String, name of control to set.
    """
    self.Set(name, 'on')

  def Disable(self, name):
    """Sets the control's value to 'off'.

    Args:
      name: String, name of control to set.
    """
    self.Set(name, 'off')

  def Click(self, name):
    """Sets the control's value to 'on' then 'off'.

    Args:
      name: String, name of control to set.
    """
    self.MultipleSet([(name, 'on'), (name, 'off')])

  def __getattr__(self, name):
    """Delegates getter of all unknown attributes to remote servod.

    Raises:
      ServoClientError: If error occurs when getting value.
    """
    # If name is already in self.__dict__, Python will not invoke this method.
    return self.Get(name)

  def __setattr__(self, name, value):
    """Delegates setter of all unknown attributes to remote servod.

    Raises:
      ServoClientError: If error occurs when setting value.
    """
    if name in self.__dict__:  # existing attributes
      super(ServoClient, self).__setattr__(name, value)
    else:
      return self.Set(name, value)

  def HWInit(self):
    """Re-initializes the controls to its initial values.

    Raises:
      ServoClientError: If error occurs when invoking hwinit() on servod.
    """
    try:
      self._server.hwinit()
    except Exception as e:
      raise ServoClientError('Problem on HWInit', e)
