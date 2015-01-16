# Copyright (c) 2013 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import time

import factory_common  # pylint: disable=W0611
from cros.factory.test import factory
from cros.factory.test.fixture.bft_fixture import (BFTFixture,
                                                   BFTFixtureException)


class DummyBFTFixture(BFTFixture):
  """A dummy class for BFT fixture.

  It is used when we want to verify a BFT test case without BFT fixture.
  For methods asking the fixture to do something, we place a timer for
  tester to act like the fixture.
  For methods getting status, like GetFixtureId, we returns a default value.
  """
  # For EngageDevice/DisengageDevice, it sleeps _delay_secs for user to mimic
  # fixture's action.
  _delay_secs = 3

  def GetSystemStatus(self, unused_probe):
    return BFTFixture.Status.ON

  def Init(self, **kwargs):
    self._Log('connected.')

  def Disconnect(self):
    self._Log('disconnected.')

  def SetDeviceEngaged(self, device, engage):
    self._Prompt(
        'Please %s device: %s' % ('engage' if engage else 'disengage', device))

  def Ping(self):
    self._Log('ping back.')

  def CheckPowerRail(self):
    self._Log('power rail okay.')

  def CheckExtDisplay(self):
    self._Log('external display okay.')

  def GetFixtureId(self):
    self._Log('fixture ID: 1.')
    return 1

  def ScanBarcode(self):
    self._Prompt('Please type a barcode.')

  def SimulateKeystrokes(self):
    self._Prompt('Please input keystoke sequence.')

  def IsLEDColor(self, color):
    self._Log('Sees color: %s' % color)
    return True

  def SetStatusColor(self, color):
    self._Log('Status color is set: %s' % color)

  @property
  def delay_secs(self):
    return self._delay_secs

  @delay_secs.setter
  def delay_secs(self, delay_secs):
    self._delay_secs = delay_secs

  def _Log(self, message):
    factory.console.info('Dummy BFT: ' + message)

  def _Prompt(self, prompt):
    """Asks user to do something to ack like a real fixture.

    It sleeps for _delay_secs for user to complete the action.

    Args:
      prompt: The prompt message.
    """
    self._Log(prompt)
    time.sleep(self._delay_secs)


class SpringDummyBFTFixture(DummyBFTFixture):
  """A dummy class for Spring BFT fixture.

  It mimics Spring specific fixture, like
  GetSystemStatus(BFTFixture.SystemStatus.BACKLIGHT).
  """
  # Will be set when the first GetSystemStatus(SystemStatus.BACKLIGHT) is
  # called. And the value would be: now + _backlight_waiting_off_secs seconds.
  _backlight_off_time = None
  _backlight_waiting_off_secs = 10

  def GetSystemStatus(self, probe):
    if probe == BFTFixture.SystemStatus.BACKLIGHT:
      now = time.time()
      status = BFTFixture.Status.ON
      if not self._backlight_off_time:
        self._backlight_off_time = now + self._backlight_waiting_off_secs
      elif self._backlight_off_time < now:
        status = BFTFixture.Status.OFF
        self._Log('Backlight status: %s' % status)
        return status

      self._Log('Backlight status: %s. Will turn off after %.1f seconds.' %
                (status, self._backlight_off_time - now))
      return status
    else:
      raise BFTFixtureException('Fixture does not support %s' % probe)
