# Copyright 2016 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""System fan controller.

This module provides reading and setting system fan speed.
"""

from __future__ import print_function

import re

import factory_common  # pylint: disable=unused-import
from cros.factory.device import types

from cros.factory.external import numpy


class FanControl(types.DeviceComponent):
  """System module for fan control."""

  AUTO = 'auto'
  """Constant representing automatic fan speed."""

  def GetFanRPM(self, fan_id=None):
    """Gets the fan RPM.

    Args:
      fan_id: The id of the fan.

    Returns:
      A list of int indicating the RPM of each fan.
    """
    raise NotImplementedError

  def SetFanRPM(self, rpm, fan_id=None):
    """Sets the target fan RPM.

    Args:
      rpm: Target fan RPM, or FanControl.AUTO for auto fan control.
      fan_id: The id of the fan.
    """
    raise NotImplementedError


class ECToolFanControl(FanControl):
  """System module for thermal control (temperature sensors, fans).

  Implementation for systems with 'ectool' and able to control thermal with EC.
  """

  # Regular expressions used by thermal component.
  GET_FAN_SPEED_RE = re.compile(r'Fan (\d+) RPM: (\d+)')

  def GetFanRPM(self, fan_id=None):
    """Gets the fan RPM.

    Args:
      fan_id: The id of the fan.

    Returns:
      A list of int indicating the RPM of each fan.
    """
    try:
      ectool_output = self._device.CallOutput(
          ['ectool', 'pwmgetfanrpm'] + (['%d' % fan_id] if fan_id is not None
                                        else []))
      return [int(rpm[1])
              for rpm in self.GET_FAN_SPEED_RE.findall(ectool_output)]
    except Exception as e:  # pylint: disable=broad-except
      raise self.Error('Unable to get fan speed: %s' % e)

  def SetFanRPM(self, rpm, fan_id=None):
    """Sets the target fan RPM.

    Args:
      rpm: Target fan RPM, or FanControl.AUTO for auto fan control.
      fan_id: The id of the fan.
    """
    try:
      # For system with multiple fans, ectool controls all the fans
      # simultaneously in one command.
      if rpm == self.AUTO:
        self._device.CheckCall(
            (['ectool', 'autofanctrl'] +
             (['%d' % fan_id] if fan_id is not None else [])))
      else:
        self._device.CheckCall(
            (['ectool', 'pwmsetfanrpm'] +
             (['%d' % fan_id] if fan_id is not None else []) + ['%d' % rpm]))
    except Exception as e:  # pylint: disable=broad-except
      if rpm == self.AUTO:
        raise self.Error('Unable to set auto fan control: %s' % e)
      else:
        raise self.Error('Unable to set fan speed to %d RPM: %s' % (rpm, e))


class MosysFanControl(FanControl):
  """System module for fan control using ChromeOS 'mosys'.

  This is usually found on Chromebox that does not have ectool.
  """

  _DEFAULT_DUTY_CYCLES = [30, 40, 50, 60, 70, 80, 90, 100]

  def __init__(self, device, rpms, duty_cycles=None):
    """Constructor.

    Args:
      device: a `cros.factory.device.types.DeviceInterface` instance.
      rpms: A list of integers for mapping from RPM to duty cycles (device
          specific), for example [2360, 3040, 3630, 4180, 4655, 5100, 5450,
          5950].
      duty_cycles: A list of integers for duty cycles mapped by argument rpms,
          default to _DEFAULT_DUTY_CYCLES.
    """
    super(MosysFanControl, self).__init__(device)
    self._rpms = rpms
    self._duty_cycles = duty_cycles or self._DEFAULT_DUTY_CYCLES

  def GetFanRPM(self, fan_id=None):
    """Gets the fan RPM.

    Args:
      fan_id: The id of the fan.

    Returns:
      A list of int indicating the RPM of each fan.
    """
    try:
      return [int(self._device.CheckOutput(
          ['mosys', 'sensor', 'print', 'fantach']).split('|')[2].strip())]
    except Exception as e:  # pylint: disable=broad-except
      raise self.Error('Unable to get fan speed: %s' % e)

  def SetFanRPM(self, rpm, fan_id=None):
    """Transfer RPM to PWM duty cycle to set fan speed.

    Args:
      rpm: This parameter should be a number or self.AUTO.
    """
    # xp is RPM table, fp is duty_cycle table.
    min_rpm = self._rpms[0]
    if rpm != self.AUTO:
      if rpm < min_rpm:
        raise self.Error('RPM should be greater than %d' % min_rpm)
      else:
        duty_cycle = str(int(numpy.interp(
            rpm, self._rpms, self._duty_cycles)))
    try:
      self._device.CheckCall(
          ['mosys', 'sensor', 'set', 'fantach', 'system',
           'auto' if rpm == self.AUTO else duty_cycle])
      if rpm == self.AUTO:
        # This is a workaround for fan speed. We need this command
        # when fan mode from manaul to auto.
        # See more details: http://crosbug.com/p/24562.
        self._device.Call(
            'echo 0 > /sys/class/thermal/cooling_device4/cur_state')
    except Exception as e: # pylint: disable=broad-except
      raise self.Error('Unable to set fan speed to RPM %s: %s' % (rpm, e))


class SysFSFanControl(FanControl):
  """System module for fan control using sysfs.

  Implementation for systems which able to control thermal with sysfs API.
  """

  def __init__(self, dut, fans_info=None):
    """Constructor.

    Args:
      fans_info: A sequence of dicts. Each dict contains information of a fan:
      - "fan_id": The id used in SetFanRPM/GetFanRPM.
      - "path": The path containing files for fan operations.
      - "control_mode_filename": The file to switch auto/manual fan control
            mode. default is "pwm1_enable".
      - "get_speed_filename": The file to get fan speed information.
            default is "fan1_input".
      - "get_speed_map": A function (str -> int) that translates the content of
            "get_speed_filename" file to RPM. default is int.
      - "set_speed_filename": The file to set fan speed. default is "pwm1".
      - "set_speed_map": A function (int -> str) that produces corresponding
            content for "set_speed_filename" file with a given RPM. default is
            str.
    """
    super(SysFSFanControl, self).__init__(dut)
    self._fans = []
    if fans_info is not None:
      for fan_info in fans_info:
        complete_info = fan_info.copy()
        assert 'fan_id' in complete_info, "'fan_id' is missing in fans_info"
        assert 'path' in complete_info, "'path' is missing in fans_info"
        complete_info.setdefault('control_mode_filename', 'pwm1_enable')
        complete_info.setdefault('get_speed_filename', 'fan1_input')
        complete_info.setdefault('get_speed_map', int)
        complete_info.setdefault('set_speed_filename', 'pwm1')
        complete_info.setdefault('set_speed_map', str)
        self._fans.append(complete_info)

  def GetFanRPM(self, fan_id=None):
    """See FanControl.GetFanRPM."""
    try:
      ret = []
      for info in self._fans:
        if fan_id is None or info['fan_id'] == fan_id:
          buf = self._device.ReadFile(self._device.path.join(
              info['path'], info['get_speed_filename']))
          ret.append(info['get_speed_map'](buf))
      return ret
    except Exception as e:  # pylint: disable=broad-except
      raise self.Error('Unable to get fan speed: %s' % e)

  def SetFanRPM(self, rpm, fan_id=None):
    """See FanControl.SetFanRPM."""
    try:
      for info in self._fans:
        if fan_id is None or info['fan_id'] == fan_id:
          if rpm == self.AUTO:
            self._device.WriteFile(self._device.path.join(
                info['path'], info['control_mode_filename']), '2')
          else:
            self._device.WriteFile(self._device.path.join(
                info['path'], info['control_mode_filename']), '1')
            buf = info['set_speed_map'](rpm)
            self._device.WriteFile(self._device.path.join(
                info['path'], info['set_speed_filename']), buf)
    except Exception as e:  # pylint: disable=broad-except
      if rpm == self.AUTO:
        raise self.Error('Unable to set auto fan control: %s' % e)
      else:
        raise self.Error('Unable to set fan speed to %d RPM: %s' % (rpm, e))
