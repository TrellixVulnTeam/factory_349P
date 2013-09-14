# -*- coding: utf-8 -*-
# Copyright (c) 2013 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import json
import os
import serial
import subprocess
import threading
import time
import unittest
import StringIO

from autotest_lib.client.cros.i2c import usb_to_i2c   # pylint: disable=F0401
from cros.factory.test import factory
from cros.factory.test.media_util import MountedMedia
from cros.factory.test.test_ui import UI


_CONF_UPDATE_SCRIPT = '/opt/google/touch/config/chromeos-touch-config-update.sh'

# Temporary file to store stdout for commands executed in this test.
# Note that this file is to be examined only when needed, or just let it
# be overridden.
# Use shopfloor.UploadAuxLogs(_TMP_STDOUT) to upload this file to shopfloor
# server for future process and analyze when needed.
_TMP_STDOUT = '/tmp/stdout.txt'


class DebugDataReader():
  """A class communicates with the touchscreen on system"""
  def __init__(self):
    self.sysfs_entry = '/sys/bus/i2c/devices/2-004a/object'

  def CheckStatus(self):
    """Checks if the touchscreen sysfs object is present"""
    return os.path.exists(self.sysfs_entry)

  def WriteSysfs(self, to_write):
    """Write to sysfs

    @param to_write: the contents to be written to sysfs
    """
    with open(self.sysfs_entry, 'w') as f:
      f.write(to_write)
    time.sleep(0.1)

  def Read(self, delta=False):
    """Reads 32 * 52 touchscreen sensors raw data"""
    debugfs = ('/sys/kernel/debug/atmel_mxt_ts/2-004a/%s' %
               ('deltas' if delta else 'refs'))
    out_data = []
    with open(debugfs) as f:
      # The debug fs content is composed by 32 lines, and each
      # line contains 104 byte of 52 consecutive sensor values.
      for j in range(32):                         # pylint: disable=W0612
        line = f.read(104)
        data = []
        for i in range(52):
          # Correct endianness
          s = line[i * 2 + 1] + line[i * 2]
          val = int(s.encode('hex'), 16)
          # Correct signed values
          if val > 32768:
            val = val - 65535
          data.append(val)
        out_data.append(data)
    return out_data


class ControllerException(Exception):
  """Controller Exception class"""
  pass


class SafeSerialController:
  """A wrapper class for I2CControllerSC18IM700

  SafeSerialController handles unexpected exceptions from
  I2CControllerSC18IM700 with recreate delegate controller and put
  sleeps in between commands to prevent errors.
  """
  def __init__(self):
    self._delegate = None
    self.CreateDelegate()

  def CreateDelegate(self):
    """Create an I2C controller instance."""
    self._delegate = usb_to_i2c.create_i2c_controller('SC18IM700:pl2303')
    factory.console.info('tty_path: %s' % self._delegate.device_path)
    self._delegate.write_register([0x02, 0x03],
                                  [int('0x96', 16), int('0x55', 16)])

  def Sleep(self):
    """Sleep for a while."""
    time.sleep(0.2)

  def WriteRegister(self, data):
    """Write to the registers."""
    # According to SC18IM700 data sheet.
    #
    # Register bits
    # 0x02: GPIO3.1 GPIO3.0 GPIO2.1 GPIO2.0 GPIO1.1 GPIO1.0 GPIO0.1 GPIO0.0
    # 0x03: GPIO7.1 GPIO7.0 GPIO6.1 GPIO6.0 GPIO5.1 GPIO5.0 GPIO4.1 GPIO4.0
    #
    # GPIOx.1 GPIOx.0
    # 0       0       quasi-bidirectional output conﬁguration
    # 0       1       input-only conﬁguration
    # 1       0       push-pull output conﬁguration
    # 1       1       open-drain output conﬁguration
    assert len(data) == 2
    retry = 0
    while retry < 2:
      self.Sleep()
      try:
        self._delegate.write_register([0x02, 0x03], data)
        self.Sleep()
        if data != [ord(ch) for ch in
              self._delegate.read_register([0x02, 0x03])]:
          raise serial.serialutil.SerialException()
        return
      except serial.serialutil.SerialException as e:
        factory.console.info(e)
        self.Sleep()
        self.CreateDelegate()
        retry += 1
    raise ControllerException('Write register fail')

  def ReadRegister(self):
    """Read the register value."""
    retry = 0
    while retry < 2:
      self.Sleep()
      try:
        data = self._delegate.read_register([0x02, 0x03])
        if len(data) != 2:
          raise serial.serialutil.SerialException()
        return data
      except serial.serialutil.SerialException as e:
        factory.console.info(e)
        self.Sleep()
        self.CreateDelegate()
        retry += 1
    raise ControllerException('Read register fail')

  def WriteGpio(self, data):
    """Write GPIO."""
    retry = 0
    while retry < 2:
      self.Sleep()
      try:
        self._delegate.write_gpio(data)
        return
      except serial.serialutil.SerialException as e:
        factory.console.info(e)
        self.Sleep()
        self.CreateDelegate()
        retry += 1
    raise ControllerException('Write gpio fail')

  def ReadGpio(self):
    """Read GPIO."""
    retry = 0
    while retry < 2:
      self.Sleep()
      try:
        data = self._delegate.read_gpio()
        if len(data) != 1:
          raise serial.serialutil.SerialException()
        return ord(data)
      except serial.serialutil.SerialException as e:
        factory.console.info(e)
        self.Sleep()
        self.CreateDelegate()
        retry += 1
    raise ControllerException('Read gpio fail')


class factory_TouchscreenCalibration(unittest.TestCase):
  """factory Touchscreen Calibration class"""
  version = 1

  def setUp(self):
    """Set up the object."""
    self._calibration_thread = None
    self.controller = None
    self.dev_path = None
    self.dump_frames = None
    self.log_to_file = None
    self.reader = DebugDataReader()
    self.ui = UI()

  def WriteReg(self, event):
    """A wrapper for writing to the registers."""
    reg_data = event.data.get('reg_data', None)
    assert reg_data is not None
    reg_data = [int(s, 16) for s in reg_data.split(',')]
    assert len(reg_data) == 2

    for i in range(2):
      factory.console.info('Reg data %d: %s' % (i, bin(reg_data[i])))
    self.controller.WriteRegister(reg_data)

  def ReadReg(self, event):                       # pylint: disable=W0613
    """A wrapper for reading the registers."""
    data = self.controller.ReadRegister()
    data = [ord(char) for char in data]
    factory.console.info('Get register data: %s' % [bin(d) for d in data])

    self.ui.CallJSFunction('showMessage', json.dumps(data))

  def WriteGpio(self, event):
    """A wrapper for writing GPIO."""
    # GPIO pin definations
    # IO0 In/out control
    # IO1 In sensor
    # IO2 Out sensor
    # IO3 Up/down control
    # IO4 Up sensor
    # IO5 Down sensor
    to_write = event.data.get('to_write', None)
    assert to_write is not None
    to_write = int(to_write, 16)
    factory.console.info('To write: %d' % to_write)
    self.controller.WriteGpio(to_write)

  def ReadGpio(self, event):                      # pylint: disable=W0613
    """A wrapper for reading GPIO."""
    if self.controller:
      data = self.controller.ReadGpio()
      factory.console.info('Get data %s' % bin(data))
      self.ui.CallJSFunction('showMessage', data)
    else:
      factory.console.info('No controller found')

  def _IsProbeIn(self):
    """Is the probe at the 'in' position?"""
    data = self.controller.ReadGpio()
    return (data & 2 == 0)

  def _IsProbeOut(self):
    """Is the probe at the 'out' position?"""
    data = self.controller.ReadGpio()
    return (data & 4 == 0)

  def _IsProbeUp(self):
    """Is the probe at the 'up' position?"""
    data = self.controller.ReadGpio()
    return (data & 16 == 0)

  def _IsProbeDown(self):
    """Is the probe at the 'down' position?"""
    data = self.controller.ReadGpio()
    return (data & 32 == 0)

  def ProbeIn(self, *args):                       # pylint: disable=W0613
    """Move the probe to the 'in' position."""
    if not self._IsProbeOut():
      self.ui.CallJSFunction('showMessage',
                             'Probe is not in correct position\n'
                             '治具未就位')
      return
    self.controller.WriteGpio(int('0b000000', 2))
    counter = 0
    while not self._IsProbeIn():
      time.sleep(2)
      counter += 1
      if counter > 10:
        self.ui.CallJSFunction('showMessage',
                               'Timeout - Probe not in correct position\n'
                               '超时 - 治具未就位')
        return

  def ProbeOut(self, *args):                      # pylint: disable=W0613
    """Move the probe to the 'out' position."""
    self.controller.WriteGpio(int('0b000001', 2))
    counter = 0
    while (not self._IsProbeOut() or not self._IsProbeUp()):
      time.sleep(2)
      counter += 1
      if counter > 10:
        self.ui.CallJSFunction('showMessage',
                               'Timeout - Probe not in correct position\n'
                               '超时 - 治具未就位')
        return

  def ProbeDown(self, *args):                     # pylint: disable=W0613
    """Move the probe to the 'down' position."""
    if not self._IsProbeOut():
      self.ui.CallJSFunction('showMessage',
                             'Probe is not in correct position\n'
                             '治具未就位')
      return
    self.controller.WriteGpio(int('0b001001', 2))
    counter = 0
    while not self._IsProbeDown():
      time.sleep(2)
      counter += 1
      if counter > 10:
        self.ui.CallJSFunction('showMessage',
                               'Timeout - Probe not in correct position\n'
                               '超时 - 置具未就位')
        return

  def ReadDebug(self, event):                     # pylint: disable=W0613
    """Read debug information."""
    if self.reader:
      data = self.reader.Read(delta=True)
      factory.console.info('Get data %s' % data)
      data = json.dumps(data)
      self.ui.CallJSFunction('displayDebugData', data)
    else:
      factory.console.info('No reader found')

  def RefreshController(self, event):             # pylint: disable=W0613
    """Refresh the controller status."""
    try:
      self.controller = SafeSerialController()
      reg_data = self.controller.ReadRegister()
      if len(reg_data) != 2:
        raise serial.serialutil.SerialException()
    except Exception as e:
      factory.console.info('Create controller exception, %s' % e)
      self.controller = None
    self.ui.CallJSFunction('setControllerStatus', self.controller is not None)

  def RefreshTouchscreen(self, event):            # pylint: disable=W0613
    """Refresh all possible saved state for old touchscreen

    This functions is called whenever an old touchscreen panel
    removed and a new one attached and awaiting for testing.
    After old states of previous touchscreen panel are cleared and
    new panel detected, show the sign on UI.
    """
    os.system('rmmod atmel_mxt_ts')
    os.system('modprobe atmel_mxt_ts')

    # Update touch-config
    with open(_TMP_STDOUT, 'w') as fd:
      subprocess.call(_CONF_UPDATE_SCRIPT, stdout=fd)

    try:
      if self.reader.CheckStatus():
        factory.console.info('touchscreen exist')
        self.ui.CallJSFunction('setTouchscreenStatus', True)
        return
    except Exception as e:
      factory.console.info('Exception at refreshing touch screen: %s' % e)
    self.ui.CallJSFunction('setTouchscreenStatus', False)

  def _RegisterEvents(self, events):
    """Add event handlers for various events."""
    for event in events:
      assert hasattr(self, event)
      factory.console.info('Registered event %s' % event)
      self.ui.AddEventHandler(event, getattr(self, event))

  def StartCalibration(self, event):
    """Start the calibration thread."""
    if self._calibration_thread and self._calibration_thread.isAlive():
      self.ui.CallJSFunction('showMessage',
                             'Current calibration has not completed yet\n'
                             '目前校正尚未結束')
      return

    sn = event.data.get('sn', '')
    if len(sn) == 0:
      self.ui.CallJSFunction('showMessage',
                             'Please enter SN first\n'
                             '請先輸入序號')
      self.ui.CallJSFunction('displayDebugData', '[]')
      return

    self._calibration_thread = threading.Thread(target=self.Calibrate,
                                                args=[sn])
    self._calibration_thread.start()

  def DumpOneFrameToLog(self, logger):
    """Dump one frame to log."""
    data = self.reader.Read(delta=True)
    logger.write('Dump one frame:\n')
    for row in data:
      logger.write(' '.join([str(val) for val in row]))
      logger.write('\n')

  def Calibrate(self, sn):
    """The actual calibration method."""
    if self.controller is None:
      self.AlertControllerDisconnected()
      return

    if not self._IsProbeIn():
      self.ui.CallJSFunction('showMessage',
                             'Probe not in position, aborted\n'
                             '治具未就位, 捨棄')
      return

    try:
      # Disable passing touch event to upper layer. This is to prevent
      # undesired action happen on UI when moving or touching the panel
      # under test.
      self.reader.WriteSysfs('09000081')

      factory.console.info('Start calibrate SN %s' % sn)
      self.log_to_file = StringIO.StringIO()

      # Baseline the sensors before lowering the test probes.
      self.reader.WriteSysfs('06000201')

      # Dump whole frame a few times before probe touches panel.
      for f in range(self.dump_frames):           # pylint: disable=W0612
        self.DumpOneFrameToLog(self.log_to_file)
        time.sleep(0.1)

      self.ProbeOut()
      self.ProbeDown()
      time.sleep(2)

      data = self.reader.Read(delta=True)
      factory.console.info('Get data %s' % data)

      # The main logic to determine sensor data is good or not.
      test_pass = True

      row_num = 0
      for row in data:
        if row_num == 0:
          m = row[26]
          row_num = 1
        else:
          m = row[25]
          row_num = 0
        # Sensor threshold is derived from previous build data.
        if (m < 300 or m > 1900):
          factory.console.info('Fail at row %s value %d' % (row, m))
          test_pass = False


      # Write log
      self.log_to_file.write('%s %s\n' % (sn, 'Pass' if test_pass else 'Fail'))
      for row in data:
        self.log_to_file.write(' '.join([str(val) for val in row]))
        self.log_to_file.write('\n')
      self.WriteLog(sn, self.log_to_file.getvalue())

      data = json.dumps(data)
      self.ui.CallJSFunction('displayDebugData', data)
      time.sleep(2)

      self.ProbeOut()
      self.ProbeIn()

      # To indicate units are from DVT build, so config updater chooses
      # the correct raw file.
      self.reader.WriteSysfs('26000002')

      # Correct the possibly corrupted 'report interval' value in
      # FW config.
      self.reader.WriteSysfs('070000FF')
      self.reader.WriteSysfs('070001FF')

      # Let firmware backup settings to NV storage.
      self.reader.WriteSysfs('06000155')

      if test_pass:
        self.ui.CallJSFunction('showMessage', 'OK 測試完成')
      else:
        self.ui.CallJSFunction('showMessage', 'NO GOOD 測試失敗')

    except Exception as e:
      self.controller = None
      self.AlertControllerDisconnected()
      raise e

  def AlertControllerDisconnected(self):
    """Alert that the controller is disconnected."""
    self.ui.CallJSFunction('showMessage',
                           'Disconnected from controller\n'
                           '与治具失去联系')
    self.ui.CallJSFunction('setControllerStatus', self.controller is not None)

  def WriteLog(self, filename, content):
    """Write the content to the file and display the message in the log."""
    with MountedMedia(self.dev_path, 1) as mount_dir:
      with open(os.path.join(mount_dir, filename), 'a') as f:
        f.write(content)
    factory.console.info('Log wrote with filename[ %s ].' % filename)

  def runTest(self, dev_path=None, dump_frames=10):
    """The entry method of the test."""
    if dev_path is None:
      # Temp hack to determine it is sdb or sdc
      dev_path = '/dev/sdb' if os.path.exists('/dev/sdb1') else '/dev/sdc'

    self.dev_path = dev_path
    self.dump_frames = dump_frames
    self.log_to_file = StringIO.StringIO()

    self._RegisterEvents(['ReadDebug', 'ReadGpio', 'WriteGpio',
                          'ReadReg', 'WriteReg', 'RefreshController',
                          'RefreshTouchscreen', 'StartCalibration',
                          'ProbeIn', 'ProbeOut', 'ProbeDown'])
    self.ui.Run()
