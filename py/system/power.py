#!/usr/bin/python
#
# Copyright (c) 2012 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import glob
import numpy
import os
import time

import factory_common  # pylint: disable=W0611
from cros.factory.test.utils import Enum, ReadOneLine

class PowerException(Exception):
  pass


class Power(object):
  # Power source types
  PowerSource = Enum(['BATTERY', 'AC'])

  _sys = '/sys'

  def __init__(self):
    self._battery_path = None
    self._current_state = None

  def FindPowerPath(self, power_source):
    '''Find battery path in sysfs.'''
    if power_source == self.PowerSource.BATTERY:
      for p in glob.glob(os.path.join(self._sys, 'class/power_supply/*/type')):
        if ReadOneLine(p) == 'Battery':
          return os.path.dirname(p)
    else:
      ac_path = os.path.join(self._sys, 'class/power_supply/%s/online')
      if os.path.exists(ac_path % 'AC'):
        return os.path.dirname(ac_path % 'AC')
      p = glob.glob(ac_path % '*')
      if len(p) > 1:
        raise PowerException('Found multiple power with "online" property')
      elif len(p) == 1:
        return os.path.dirname(p[0])
    raise PowerException('Cannot find %s' % power_source)

  def CheckACPresent(self):
    '''Check if AC power is present.'''
    try:
      p = self.FindPowerPath(self.PowerSource.AC)
      return ReadOneLine(os.path.join(p, 'online')) == '1'
    except (PowerException, IOError):
      return False

  def GetACType(self):
    '''Get AC power type.'''
    try:
      p = self.FindPowerPath(self.PowerSource.AC)
      return ReadOneLine(os.path.join(p, 'type'))
    except (PowerException, IOError):
      return 'Unknown'

  def CheckBatteryPresent(self):
    '''Check if battery is present and also set battery path.'''
    try:
      self._battery_path = self.FindPowerPath(self.PowerSource.BATTERY)
      return True
    except PowerException:
      return False

  def GetBatteryAttribute(self, attribute_name):
    '''Get a battery attribute.

    Args:
      attribute_name: The name of attribute in sysfs.

    Returns:
      Content of the attribute in str.
    '''
    try:
      return ReadOneLine(os.path.join(self._battery_path, attribute_name))
    except IOError:
      # Battery driver is not fully initialized
      return None

  def GetCharge(self):
    '''Get current charge level in mAh.'''
    charge_now = self.GetBatteryAttribute('charge_now')
    if charge_now:
      return int(charge_now) / 1000
    else:
      return None

  def GetChargeMedian(self, read_count=10):
    '''Read charge level several times and return the median.'''
    charge_nows = []
    for _ in xrange(read_count):
      charge_now = self.GetCharge()
      if charge_now:
        charge_nows.append(charge_now)
      time.sleep(0.1)
    return numpy.median(charge_nows)

  def GetChargeFull(self):
    '''Get full charge level in mAh.'''
    charge_full = self.GetBatteryAttribute('charge_full')
    if charge_full:
      return int(charge_full) / 1000
    else:
      return None

  def GetChargePct(self, get_float=False):
    '''Get current charge level in percentage.

    Args:
      get_float: Returns charge percentage in float.

    Returns:
      Charge percentage in int/float.
    '''
    now = self.GetBatteryAttribute('charge_now')
    full = self.GetBatteryAttribute('charge_full')
    if now is None or full is None:
      now = self.GetBatteryAttribute('energy_now')
      full = self.GetBatteryAttribute('energy_full')
      if now is None or full is None:
        return None

    if float(full) <= 0:
      return None # Something wrong with the battery
    charge_pct = float(now) * 100.0 / float(full)
    if get_float:
      return charge_pct
    else:
      return round(charge_pct)

  def GetWearPct(self):
    '''Get current battery wear in percentage of new capacity.'''
    capacity = self.GetBatteryAttribute('charge_full')
    design_capacity = self.GetBatteryAttribute('charge_full_design')

    if capacity is None or design_capacity is None:
      # No charge values, check for energy-reporting batteries
      capacity = self.GetBatteryAttribute('energy_full')
      design_capacity = self.GetBatteryAttribute('energy_full_design')
      if capacity is None or design_capacity is None:
        # Battery driver is not fully initialized
        return None

    if float(design_capacity) <= 0:
      return None #Something wrong with the battery
    return 100 - (round(float(capacity) * 100 / float(design_capacity)))
