#!/usr/bin/python
#
# Copyright (c) 2012 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import factory_common  # pylint: disable=W0611
import mox
import unittest

from cros.factory.board.chromeos_ec import ChromeOSEC
from cros.factory.system.ec import EC


class ChromeOSECTest(unittest.TestCase):
  def setUp(self):
    self.mox = mox.Mox()
    self.ec = ChromeOSEC()
    self.mox.StubOutWithMock(self.ec, '_CallECTool')
    self.mox.StubOutWithMock(self.ec, '_Spawn')

  def tearDown(self):
    self.mox.UnsetStubs()

  def testGetTemperatures(self):
    _MOCK_TEMPS = '\n'.join([
        '0: 273',
        '1: 283',
        '2: 293',
        '3: 303',
        '4: 313',
        '5: 323'])
    # pylint: disable=W0212
    self.ec._CallECTool(['temps', 'all']).AndReturn(_MOCK_TEMPS)
    self.mox.ReplayAll()
    self.assertEquals(self.ec.GetTemperatures(), [0, 10, 20, 30, 40, 50])
    self.mox.VerifyAll()

  def testGetTemperatureMainIndex(self):
    _MOCK_TEMPS_INFO = '\n'.join([
        '0: 0 I2C_CPU-Die',
        '1: 255 I2C_CPU-Object',
        '2: 1 I2C_PCH-Die',
        '3: 2 I2C_PCH-Object',
        '4: 1 I2C_DDR-Die',
        '5: 2 I2C_DDR-Object',
        '6: 1 I2C_Charger-Die',
        '7: 2 I2C_Charger-Object',
        '8: 1 ECInternal',
        '9: 0 PECI'
    ])
    # pylint: disable=W0212
    self.ec._CallECTool(['tempsinfo', 'all']).AndReturn(_MOCK_TEMPS_INFO)
    self.mox.ReplayAll()
    self.assertEquals(self.ec.GetMainTemperatureIndex(), 9)
    self.mox.VerifyAll()

  def testGetFanRPM(self):
    _MOCK_FAN_RPM = 'Current fan RPM: 2974\n'
    # pylint: disable=W0212
    self.ec._CallECTool(['pwmgetfanrpm']).AndReturn(_MOCK_FAN_RPM)
    self.mox.ReplayAll()
    self.assertEquals(self.ec.GetFanRPM(), 2974)
    self.mox.VerifyAll()

  def testGetVersion(self):
    _MOCK_VERSION = '\n'.join([
        'vendor               | ti',
        'name                 | lm4fs1gh5bb',
        'fw_version           | link_v1.1.227-3b0e131'])

    class Dummy(object):
      def __init__(self):
        self.stdout_data = None
    dummy = Dummy()
    dummy.stdout_data = _MOCK_VERSION

    # pylint: disable=W0212
    self.ec._Spawn(['mosys', 'ec', 'info', '-l'], ignore_stderr=True,
                   read_stdout=True).AndReturn(dummy)
    self.mox.ReplayAll()
    self.assertEquals(self.ec.GetVersion(), 'link_v1.1.227-3b0e131')
    self.mox.VerifyAll()

  def testCharge(self):
    # pylint: disable=W0212
    self.ec._CallECTool(['chargeforceidle', '0'])
    self.ec._CallECTool(['i2cwrite', '16', '0', '0x12', '0x12', '0xf912'])
    self.mox.ReplayAll()
    self.ec.SetChargeState(EC.ChargeState.CHARGE)
    self.mox.VerifyAll()

  def testDischarge(self):
    # pylint: disable=W0212
    self.ec._CallECTool(['chargeforceidle', '1'])
    self.ec._CallECTool(['i2cwrite', '16', '0', '0x12', '0x12', '0xf952'])
    self.mox.ReplayAll()
    self.ec.SetChargeState(EC.ChargeState.DISCHARGE)
    self.mox.VerifyAll()

  def testStopCharge(self):
    # pylint: disable=W0212
    self.ec._CallECTool(['chargeforceidle', '1'])
    self.ec._CallECTool(['i2cwrite', '16', '0', '0x12', '0x12', '0xf912'])
    self.mox.ReplayAll()
    self.ec.SetChargeState(EC.ChargeState.IDLE)
    self.mox.VerifyAll()


if __name__ == '__main__':
  unittest.main()
