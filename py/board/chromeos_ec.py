#!/usr/bin/python
#
# Copyright (c) 2012 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import factory_common  # pylint: disable=W0611
import re

from cros.factory.system.ec import EC, ECException
from cros.factory.utils.process_utils import Spawn


class ChromeOSEC(EC):
  '''EC interface for ChromeOS EC. Uses ectool to access EC.'''
  # pylint: disable=W0223
  GET_FAN_SPEED_RE = re.compile('Current fan RPM: ([0-9]*)')
  TEMPERATURE_RE = re.compile('^(\d+): (\d+)$', re.MULTILINE)
  TEMPERATURE_INFO_RE = re.compile('^(\d+): \d+ (.+)$', re.MULTILINE)
  EC_VERSION_RE = re.compile('^fw_version\s+\|\s+(.+)$', re.MULTILINE)

  # Charger option bytes
  CHARGER_OPTION_NORMAL = "0xf912"
  CHARGER_OPTION_DISCHARGE = "0xf952"

  _Spawn = staticmethod(Spawn)

  # Cached main temperature index. Set at the first call to GetTemperature.
  _main_temperature_index = None

  def __init__(self):
    super(ChromeOSEC, self).__init__()

  def _CallECTool(self, cmd):
    return Spawn(['ectool'] + cmd, read_stdout=True,
                 ignore_stderr=True).stdout_data

  def GetTemperatures(self):
    try:
      ectool_output = self._CallECTool(['temps', 'all'])
      temps = []
      for match in self.TEMPERATURE_RE.finditer(ectool_output):
        sensor = int(match.group(1))
        while len(temps) < sensor + 1:
          temps.append(None)
        # Convert Kelvin to Celsius and add
        temps[sensor] = int(match.group(2)) - 273 if match.group(2) else None
      return temps
    except Exception as e: # pylint: disable=W0703
      raise ECException('Unable to get temperatures: %s' % e)

  def GetMainTemperatureIndex(self):
    if self._main_temperature_index is None:
      try:
        ectool_output = self._CallECTool(['tempsinfo', 'all'])
        for match in self.TEMPERATURE_INFO_RE.finditer(
            ectool_output):
          if match.group(2) == 'PECI':
            self._main_temperature_index = int(match.group(1))
            break
        else:
          raise ECException('The expected index of PECI cannot be found')
      except Exception as e: # pylint: disable=W0703
        raise ECException('Unable to get main temperature index: %s' % e)
    return self._main_temperature_index

  def GetFanRPM(self):
    try:
      ectool_output = self._CallECTool(['pwmgetfanrpm'])
      return int(self.GET_FAN_SPEED_RE.findall(ectool_output)[0])
    except Exception as e: # pylint: disable=W0703
      raise ECException('Unable to get fan speed: %s' % e)

  def SetFanRPM(self, rpm):
    try:
      self._Spawn(
          ['ectool'] +
          (['autofanctrl', 'on'] if rpm == self.AUTO else
           ['pwmsetfanrpm', str(rpm)]),
          check_call=True,
          ignore_stdout=True,
          log_stderr_on_error=True)
    except Exception as e: # pylint: disable=W0703
      raise ECException('Unable to set fan speed: %s' % e)

  def GetVersion(self):
    response = self._Spawn(['mosys', 'ec', 'info', '-l'],
                           read_stdout=True,
                           ignore_stderr=True).stdout_data
    return self.EC_VERSION_RE.search(response).group(1)

  def GetConsoleLog(self):
    return self._CallECTool(['console'])

  def SetChargeState(self, state):
    try:
      if state == EC.ChargeState.CHARGE:
        self._CallECTool(['chargeforceidle', '0'])
        self._CallECTool(['i2cwrite', '16', '0', '0x12', '0x12',
                          self.CHARGER_OPTION_NORMAL])
      elif state == EC.ChargeState.IDLE:
        self._CallECTool(['chargeforceidle', '1'])
        self._CallECTool(['i2cwrite', '16', '0', '0x12', '0x12',
                          self.CHARGER_OPTION_NORMAL])
      elif state == EC.ChargeState.DISCHARGE:
        self._CallECTool(['chargeforceidle', '1'])
        self._CallECTool(['i2cwrite', '16', '0', '0x12', '0x12',
                          self.CHARGER_OPTION_DISCHARGE])
      else:
        raise ECException('Unknown EC charge state: %s' % state)
    except Exception as e:
      raise ECException('Unable to set charge state: %s' % e)
