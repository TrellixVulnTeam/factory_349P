# Copyright 2013 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""A factory test to verify the functionality of bluetooth device.

Description
-----------
A bluetooth test to detect adapter, scan bluetooth device, check average RSSI
value, and connect with the bluetooth input device.

To run this bluetooth test, the DUT most have at least one bluetooth adapter.

If argument ``scan_devices`` is set, there should be at least one remote
bluetooth device.

If argument ``pair_with_match`` is set, there should be a bluetooth input
device like a mouse.

Test Procedure
--------------
1. Setup a bluetooth input device (like a mouse) if needed.
2. Enable the connection ability of bluetooth on DUT.
3. A prompt message will be displayed on the UI if ``prompt_scan_message`` and
   ``scan_devices`` is set.
4. The bluetooth test will run automatically.

Dependency
----------
- Device API (``cros.factory.device.chromeos.bluetooth``).
- Bluetooth utility (``cros.factory.test.utils.bluetooth_utils``).

Examples
--------
To detect the specified number of bluetooth adapter on DUT::

  OperatorTest(pytest_name='bluetooth',
               dargs={'expected_adapter_count': 1})

To scan remote bluetooth device and try to find at least one deivce whose name
contains 'KEY_WORD'::

  OperatorTest(pytest_name='bluetooth',
               dargs={'scan_devices': True,
                      'keyword': 'KEY_WORD'})

To check the the largest average RSSI among all scanned devices is bigger than
threshold::

  OperatorTest(pytest_name='bluetooth',
               dargs={'scan_devices': True,
                      'average_rssi_threshold': -65.0})

To pair, connect with, and disconnect with the bluetooth input device::

  OperatorTest(pytest_name='bluetooth',
               dargs={'pair_with_match': True})
"""

import glob
import logging
import os
import sys
import threading
import time
import unittest

import factory_common  # pylint: disable=unused-import
from cros.factory.device import device_utils
from cros.factory.test import event_log
from cros.factory.test import factory
from cros.factory.test.i18n import test_ui as i18n_test_ui
from cros.factory.test import session
from cros.factory.test import state
from cros.factory.test import test_task
from cros.factory.test import test_ui
from cros.factory.test import ui_templates
from cros.factory.test.utils import bluetooth_utils
from cros.factory.testlog import testlog
from cros.factory.utils.arg_utils import Arg
from cros.factory.utils import process_utils
from cros.factory.utils import sync_utils


_MSG_DETECT_ADAPTER = i18n_test_ui.MakeI18nLabel('Detect bluetooth adapter')
_MSG_TURN_ON_DEVICE = i18n_test_ui.MakeI18nLabelWithClass(
    'Enable the connection ability of bluetooth device and press Enter',
    'start-font-size')
_MSG_INTO_FIXTURE = i18n_test_ui.MakeI18nLabelWithClass(
    'Place the base into the fixture, '
    'and press the space key on the test host.', 'start-font-size')
_MSG_RESET_MAGNET = i18n_test_ui.MakeI18nLabelWithClass(
    'Please re-attach the magnet, and press the space key on the test host.',
    'start-font-size')
_MSG_START_CHARGE = i18n_test_ui.MakeI18nLabelWithClass(
    'Turn on charging by pressing the green button, '
    'take the keyboard out and put it back, '
    'and press the space key on the test host.', 'start-font-size')
_MSG_READ_BATTERY_1 = i18n_test_ui.MakeI18nLabelWithClass(
    'Read battery level for the 1st time.', 'start-font-size')
_MSG_READ_BATTERY_2 = i18n_test_ui.MakeI18nLabelWithClass(
    'Read battery level for the 2nd time.', 'start-font-size')
_MSG_BATTERY_CHARGE_TEST = i18n_test_ui.MakeI18nLabelWithClass(
    'Check if the battery has charged to a higher percentage',
    'start-font-size')
_MSG_CHECK_BATTERY_LEVEL = i18n_test_ui.MakeI18nLabelWithClass(
    'Check battery level.', 'start-font-size')
_MSG_STOP_CHARGE = i18n_test_ui.MakeI18nLabelWithClass(
    'Press the green button again to stop charging, '
    'and press the space key on the test host.', 'start-font-size')
_MSG_OUT_OF_FIXTURE = i18n_test_ui.MakeI18nLabelWithClass(
    'Take the base out of the fixture, '
    'and press the space key on the test host.', 'start-font-size')
_MSG_READ_FIRMWARE_REVISION_STRING = i18n_test_ui.MakeI18nLabelWithClass(
    'Read firmware revision string.', 'start-font-size')
_MSG_SCAN_DEVICE = i18n_test_ui.MakeI18nLabelWithClass(
    'Scanning...', 'start-font-size')
_MSG_DETECT_RSSI = lambda count, total: (
    i18n_test_ui.MakeI18nLabelWithClass(
        'Detect RSSI (count {count}/{total})',
        'start-font-size', count=count, total=total))
_MSG_TURN_ON_INPUT_DEVICE = i18n_test_ui.MakeI18nLabelWithClass(
    'Enable the connection ability of input bluetooth device and press Enter',
    'start-font-size')
_MSG_PAIR_INPUT_DEVICE = i18n_test_ui.MakeI18nLabelWithClass(
    'Pairing to input device now...', 'start-font-size')
_MSG_UNPAIR = i18n_test_ui.MakeI18nLabelWithClass(
    'Press shift-p-a-i-r simultaneously on the base.', 'start-font-size')
_MSG_CONNECT_INPUT_DEVICE = i18n_test_ui.MakeI18nLabelWithClass(
    'Connecting to input device now...', 'start-font-size')
_MSG_TEST_INPUT = i18n_test_ui.MakeI18nLabelWithClass(
    'Please test input. Press Escape to fail and Enter to pass',
    'start-font-size')
_MSG_UNPAIRING = i18n_test_ui.MakeI18nLabelWithClass(
    'Unpairing', 'start-font-size')
_MSG_AUTH_FAILED = i18n_test_ui.MakeI18nLabelWithClass(
    'Authentication failed, retrying...', 'start-font-size')


INPUT_MAX_RETRY_TIMES = 10
INPUT_RETRY_INTERVAL = 1
RESET_ADAPTER_SLEEP_TIME = 5
READ_BATTERY_MAX_RETRY_TIMES = 10

BATTERY_LEVEL_KEY = 'battery_level'
READ_BATTERY_STEP_1 = 'read_battery_1'
READ_BATTERY_STEP_2 = 'read_battery_2'


def GetCurrentTime():
  """Get the current time."""
  return time.strftime('%Y-%m-%d %H:%M:%S')


def ColonizeMac(mac):
  """ Given a MAC address, normalize its colons.

  Example: ABCDEF123456 -> AB:CD:EF:12:34:56
  """
  mac_no_colons = ''.join(mac.strip().split(':'))
  groups = [mac_no_colons[x:x+2] for x in range(0, len(mac_no_colons), 2)]
  return ':'.join(groups)


def MakePasskeyLabelPrompt(passkey):
  """Creates a label prompting the operator to enter a passkey"""
  return i18n_test_ui.MakeI18nLabelWithClass(
      'Enter passkey {key} then press enter on the base.',
      'start-font-size',
      key=passkey)


def CheckInputCount():
  """Returns the number of input devices from probing /dev/input/event*."""
  number_input = len(glob.glob('/dev/input/event*'))
  logging.info('Found %d input devices.', number_input)
  return number_input


def WaitForInputCount(task, expected_input_count, timeout=10):
  """ Waits for the number of input devices to reach the given count.

  Returns true if the input count reaches the given amount, false
  otherwise. On failure it fails the task.

  Args:
   task: The task that may be Failed
   expected_input_count: The number of input devices that determines success
   timeout: The maximum time in seconds that we will wait
  """
  end_time = time.time() + timeout
  while time.time() < end_time:
    input_count = CheckInputCount()
    if input_count == expected_input_count:
      return True
    time.sleep(0.2)
  task.Fail('Input device count %d is different than expected %d.' %
            (input_count, expected_input_count))
  return False


def _ResetAdapter():
  """Reset the adapter every time when using the BT device.
  This is because the adapter may be down anytime for some unknown reason.
  """
  cmd = 'hciconfig hci0 reset'
  factory.console.info('Reset adapter and wait 5 seconds....: %s', cmd)
  process_utils.Spawn(cmd.split(), log=True, check_call=True)
  time.sleep(RESET_ADAPTER_SLEEP_TIME)


def _AppendLog(log_file, data):
  """Appends the log file on the local station."""
  if not log_file:
    return

  # Prepend the current timestamp to each line.
  data = ''.join([(GetCurrentTime() + ' ' + line + '\n') if line else '\n'
                  for line in data.splitlines()])
  log_dir = os.path.dirname(log_file)
  if not os.path.isdir(log_dir):
    os.makedirs(log_dir)
  with open(log_file, 'a') as log:
    log.write(str(data))


def RetryWithProgress(template, template_message, action_string,
                      max_retry_times, retry_interval, target, *args, **kwargs):
  """Runs target function with retries and shows retry times on progress bar.

  Args:
    template: an ui_template
    template_message: The message to show when target function is running.
    action_string: The string to describe the action in logging.
    max_retry_times: the maximal retry times
    retry_interval: the interval between retries
    target: The target function. *args and **kwargs will be passed to target.

  Returns:
    Return the return value of the target function.
  """
  def _UpdateProgressBar(retry_time, max_retry_time):
    """Updates the progress bar according to retry_time and max_retry_time."""
    msg = 'Update progress bar with retry time: %d, max retry time: %d.'
    logging.info(msg, retry_time, max_retry_time)
    template.SetProgressBarValue(int(100 * retry_time / max_retry_time))

  template.SetState(template_message)
  template.DrawProgressBar()
  target_result = sync_utils.Retry(max_retry_times, retry_interval,
                                   _UpdateProgressBar, target, *args, **kwargs)
  template.SetProgressBarValue(100)
  log_msg = '%s was done.' if target_result else '%s failed.'
  logging.info(log_msg, action_string)
  return target_result


class DetectAdapterTask(test_task.TestTask):
  """The task checking number of adapters.

  Detects adapters from dbus and checks if the number of adapters matches the
  expected number.

  Args:
     expected_adapter_count: The expected number of bluetooth adapters.
  """

  def __init__(self, test, expected_adapter_count):
    super(DetectAdapterTask, self).__init__()
    self._test = test
    self._expected_adapter_count = expected_adapter_count

  def Run(self):
    self._test.template.SetState(_MSG_DETECT_ADAPTER)
    adapters = self._test.dut.bluetooth.GetAdapters(
        self._test.args.detect_adapters_retry_times,
        self._test.args.detect_adapters_interval_secs)
    if len(adapters) == self._expected_adapter_count:
      self.Pass()
    else:
      self.Fail('DetectAdapter: expect %d and find %d adapter(s).' %
                (self._expected_adapter_count, len(adapters)))


class TurnOnTask(test_task.TestTask):
  """The task to ask operator to turn on bluetooth device and press enter.

  Args:
    message: Html code containing message to show on the screen.
  """

  def __init__(self, test, message, key=test_ui.ENTER_KEY):
    super(TurnOnTask, self).__init__()
    self._test = test
    self._message = message
    self._key = key

  def Cleanup(self):
    """Unbinds the Enter key after this task is done."""
    self._test.ui.UnbindKey(self._key)

  def Run(self):
    self._test.template.SetState(self._message)
    self._test.ui.AppendCSS('.start-font-size {font-size: 2em;}')
    self._test.ui.BindKey(self._key, lambda _: self.Pass())
    logging.info('wait for the user to press a key')


def SetAndStartScanProgressBar(template, timeout_secs, scan_event=None):
  """Control progress bar fo a duration of timeout_secs."""
  def UpdateProgressBar():
    """Updates progress bar for a duration of timeout_secs"""
    start_time = time.time()
    end_time = start_time + timeout_secs
    while time.time() < end_time:
      if scan_event and scan_event.isSet():
        break
      template.SetProgressBarValue(int(
          100 * (time.time() - start_time) / timeout_secs))
      time.sleep(0.2)
    template.SetProgressBarValue(100)
    logging.debug('UpdateProgressBar stopped.')

  template.DrawProgressBar()
  return process_utils.StartDaemonThread(
      target=UpdateProgressBar, name='ProgressThread')


class ScanDevicesTask(test_task.TestTask):
  """The task to scan bluetooth devices around.

  In this task, the test will control the first adapter from BluetoothManager
  and scan devices around for timeout_secs. The task passed if there is at least
  one device.
  If target_addresses is provided, the test will also check if it can find
  at least one device specified in target_addresses list.
  This passes the strongest matching device mac to _test.SetStrongestRssiMac

  Note: this task is intended to be executed on a DUT, i.e., a chromebook,
  to test its bluetooth module. A typical test case is to see if it can detect
  a bluetooth mouse placed around it.
  """

  def __init__(self, test):
    super(ScanDevicesTask, self).__init__()
    self._test = test
    self._keyword = test.args.keyword
    self._average_rssi_threshold = test.args.average_rssi_threshold
    self._mac_to_scan = test.GetInputDeviceMac()
    self._scan_counts = test.args.scan_counts
    self._timeout_secs = test.args.scan_timeout_secs

    self._progress_thread = None

  def FilterByKeyword(self, devices):
    """Returns the devices filtered by self._keyword.

    If self._keyword is None, leave devices as it is.
    """
    if self._keyword is None:
      return devices

    filtered_devices = {}
    for mac, props in devices.iteritems():
      if 'Name' not in props:
        logging.warning('Device %s: %s does not have "Name" property.',
                        mac, props)
        continue

      if self._keyword in props['Name']:
        filtered_devices[mac] = props
        logging.info('Device %s: "Name" property %s matches keyword %s.',
                     mac, props['Name'], self._keyword)
    return filtered_devices

  def UpdateRssi(self, devices_rssis, devices):
    """Updates devices_rssis using RSSI property in devices.

    Args:
      devices_rssis: A dict. Keys are mac addresses and values are lists of
        scanned RSSI value.
      devices: A dict. Keys are mac addresses and values are dicts of
        properties.
    """
    for mac, props in devices.iteritems():
      if 'RSSI' not in props:
        logging.warning('Device %s: %s does not have "RSSI" property.',
                        mac, props)
        continue
      if mac in devices_rssis:
        devices_rssis[mac].append(props['RSSI'])
      else:
        devices_rssis[mac] = [props['RSSI']]
    logging.info('UpdateRssi: %s', devices_rssis)

  def Run(self):
    bluetooth_manager = self._test.dut.bluetooth
    adapter = bluetooth_manager.GetFirstAdapter(self._test.host_mac)

    # Records RSSI of each scan and calculates average rssi.
    candidate_rssis = {}

    # Helper to check if the target MAC has been scanned
    def has_scanned_target_mac():
      return self._mac_to_scan and self._mac_to_scan in candidate_rssis

    for _ in xrange(self._scan_counts):
      self._test.template.SetState(_MSG_SCAN_DEVICE)
      self._progress_thread = SetAndStartScanProgressBar(self._test.template,
                                                         self._timeout_secs)
      devices = bluetooth_manager.ScanDevices(adapter, self._timeout_secs)
      self._progress_thread.join()

      logging.info('Found %d device(s).', len(devices))
      for mac, props in devices.iteritems():
        try:
          logging.info('Device found: %s. Name: %s, RSSI: %d',
                       mac, props['Name'], props['RSSI'])
        except KeyError:
          logging.exception('Name or RSSI is not available in %s', mac)

      self.UpdateRssi(candidate_rssis, self.FilterByKeyword(devices))
      # Optimization: if we are only interested in one particular address,
      # then we can early-out as soon as we find it
      if self._average_rssi_threshold is None and has_scanned_target_mac():
        logging.info("Address found, ending scan early")
        break

    logging.info('Found %d candidate device(s) in %s scans.',
                 len(candidate_rssis), self._scan_counts)
    factory.console.info('Candidate devices scan results: %s',
                         dict((str(k), [int(r) for r in v])
                              for k, v in candidate_rssis.iteritems()))

    if len(candidate_rssis) == 0:
      self.Fail('ScanDevicesTask: Fail to find any candidate device.')
      return

    # Calculates maximum average RSSI.
    max_average_rssi_mac, max_average_rssi = None, -sys.float_info.max
    for mac, rssis in candidate_rssis.iteritems():
      # typecast to str to avoid the weird dbus.String type
      mac = str(mac)
      average_rssi = float(sum(rssis)) / len(rssis)
      logging.info('Device %s has average RSSI: %f', mac, average_rssi)
      event_log.Log('avg_rssi', mac=mac, average_rssi=average_rssi)
      if average_rssi > max_average_rssi:
        max_average_rssi_mac, max_average_rssi = mac, average_rssi

    logging.info('Device %s has the largest average RSSI: %f',
                 max_average_rssi_mac, max_average_rssi)

    event_log.Log('bluetooth_scan_device', mac=str(max_average_rssi_mac),
                  rssi=float(max_average_rssi),
                  meet=max_average_rssi >= self._average_rssi_threshold)

    self._test.SetStrongestRssiMac(max_average_rssi_mac)

    if self._mac_to_scan and not has_scanned_target_mac():
      found_addresses = [str(k) for k in candidate_rssis]
      self.Fail('Failed to find MAC address %s.'
                'Scanned addresses: %s' % (self._mac_to_scan, found_addresses))
      return

    if self._average_rssi_threshold is None:
      # Test is uninterested in RSSI thresholds
      self.Pass()
    elif self._average_rssi_threshold > max_average_rssi:
      factory.console.error('The largest average RSSI %f does not meet'
                            ' threshold %f. Please ensure that the test BT '
                            'device is \'visible\' and close to the DUT '
                            'antenna.',
                            max_average_rssi, self._average_rssi_threshold)
      self.Fail('ScanDeviceTask: The largest average RSSI %f of device %s does'
                ' not meet threshold %f.' % (
                    max_average_rssi, str(max_average_rssi_mac),
                    self._average_rssi_threshold))
    else:
      factory.console.info('The largest average RSSI %f meets threshold %f.',
                           max_average_rssi, self._average_rssi_threshold)
      self.Pass()


class DetectRSSIofTargetMACTask(test_task.TestTask):
  """The task to detect the RSSI strength at a given target MAC address.

  In this task, a generic test host uses the first adapter from
  BluetoothManager and scans devices around for timeout_secs. The task
  passed if it can detect the RSSI strength at the target MAC.

  Note: this task is intended to be executed on a generic test host to test
  if the RSSI of a target device, e.g., a Ryu base, could be detected.
  """

  def __init__(self, test):
    super(DetectRSSIofTargetMACTask, self).__init__()
    self._test = test
    self._mac_to_scan = test.GetInputDeviceMac()
    self._scan_counts = test.args.scan_counts
    self._timeout_secs = test.args.scan_timeout_secs
    self._input_device_rssi_key = test.args.input_device_rssi_key
    self._progress_thread = None
    self._scan_rssi_event = threading.Event()
    self.fail_msg = ''
    self._average_rssi_lower_threshold = None
    self._average_rssi_upper_threshold = None

  def _DeriveRSSIThreshold(self, threshold, fid):
    if isinstance(threshold, (int, float)):
      return threshold
    elif isinstance(threshold, dict):
      if fid in threshold:
        return threshold.get(fid)
      else:
        self.fail_msg += 'Fixture ID "%s" is not legitimate!\n' % fid
    else:
      self.fail_msg += 'Wrong type of RSSI threshold: %s\n' % str(threshold)

  def Run(self):
    fid = session.GetDeviceID()
    self._average_rssi_lower_threshold = self._DeriveRSSIThreshold(
        self._test.args.average_rssi_lower_threshold, fid)
    self._average_rssi_upper_threshold = self._DeriveRSSIThreshold(
        self._test.args.average_rssi_upper_threshold, fid)
    if self.fail_msg:
      factory.console.error(self.fail_msg)
      self.Fail(self.fail_msg)
      return

    bluetooth_manager = self._test.dut.bluetooth
    adapter = bluetooth_manager.GetFirstAdapter(self._test.host_mac)
    logging.info('mac (%s): %s', self._test.host_mac, adapter)

    rssis = []
    for i in xrange(1, 1 + self._scan_counts):
      label = _MSG_DETECT_RSSI(i, self._scan_counts)
      self._test.template.SetState(label)
      self._scan_rssi_event.clear()
      self._progress_thread = SetAndStartScanProgressBar(self._test.template,
                                                         self._timeout_secs,
                                                         self._scan_rssi_event)

      devices = bluetooth_manager.ScanDevices(adapter,
                                              timeout_secs=self._timeout_secs,
                                              match_address=self._mac_to_scan)

      self._scan_rssi_event.set()
      self._progress_thread.join()
      for mac, props in devices.iteritems():
        if mac == self._mac_to_scan and 'RSSI' in props:
          factory.console.info('RSSI of count %d: %.2f', i, props['RSSI'])
          rssis.append(props['RSSI'])

    if len(rssis) == 0:
      self.Fail('DetectRSSIofTargetMACTask: Fail to get RSSI from device %s.' %
                self._mac_to_scan)
    else:
      average_rssi = float(sum(rssis)) / len(rssis)
      state.set_shared_data(self._input_device_rssi_key, average_rssi)
      logging.info('RSSIs at MAC %s: %s', self._mac_to_scan, rssis)
      factory.console.info('Average RSSI: %.2f', average_rssi)

      fail_msg = ''
      if (self._average_rssi_lower_threshold is not None and
          average_rssi < self._average_rssi_lower_threshold):
        fail_msg += ('Average RSSI %.2f less than the lower threshold %.2f\n' %
                     (average_rssi, self._average_rssi_lower_threshold))
      if (self._average_rssi_upper_threshold is not None and
          average_rssi > self._average_rssi_upper_threshold):
        fail_msg += ('Average RSSI %.2f greater than the upper threshold %.2f' %
                     (average_rssi, self._average_rssi_upper_threshold))

      # Convert dbus.Int16 in rssis below to regular integers.
      status = (('pass' if fail_msg == '' else 'fail') +
                ' exp: [%.2f, %.2f]' % (self._average_rssi_lower_threshold,
                                        self._average_rssi_upper_threshold))
      data = ('Average RSSI: %.2f %s  (%s)\n' %
              (average_rssi, map(int, rssis), status))
      _AppendLog(self._test.log_file, data)

      if fail_msg:
        factory.console.error(fail_msg)
        self.Fail(fail_msg)
      else:
        self.Pass()


class UnpairTask(test_task.TestTask):
  """A task to unpair from bluetooth devices.

  Args:
    device_mac: None, or the MAC address of the device to unpair
    name_fragment: None, or a substring of the name of the device(s) to unpair
  """

  def __init__(self, test, device_mac, name_fragment):
    super(UnpairTask, self).__init__()
    self._test = test
    self._device_mac = device_mac
    self._name_fragment = name_fragment

  def _ShouldUnpairDevice(self, device_props):
    """Indicate if a device matches the filter, and so should be unpaired

    If a name fragment or MAC address is given, the corresponding property
    must match. If neither is given, all devices should be unpaired.
    """
    if self._device_mac and device_props["Address"] != self._device_mac:
      return False
    if (self._name_fragment and
        self._name_fragment not in device_props.get('Name', '')):
      return False
    return device_props["Paired"]

  def Run(self):
    self._test.template.SetState(_MSG_UNPAIRING)
    self._test.ui.AppendCSS('.start-font-size {font-size: 2em;}')

    input_count_before_unpair = CheckInputCount()
    bluetooth_manager = self._test.dut.bluetooth
    adapter = bluetooth_manager.GetFirstAdapter(self._test.host_mac)
    devices = bluetooth_manager.GetAllDevices(adapter).values()
    devices_to_unpair = filter(self._ShouldUnpairDevice, devices)
    logging.info('Unpairing %d device(s)', len(devices_to_unpair))
    for device_to_unpair in devices_to_unpair:
      address = device_to_unpair["Address"]
      bluetooth_manager.DisconnectAndUnpairDevice(adapter, address)
      bluetooth_manager.RemovePairedDevice(adapter, address)

    # Check that we unpaired what we thought we did
    expected_input_count = input_count_before_unpair - len(devices_to_unpair)
    if WaitForInputCount(self, expected_input_count):
      self.Pass()


class CheckDisconnectionOfPairedDeviceTask(test_task.TestTask):
  """A task to check whether a paired device has disconnected.

  Args:
    device_mac: None, or the MAC address of the device to unpair
    name_fragment: None, or a substring of the name of the device(s) to unpair
  """

  def __init__(self, test, device_mac):
    super(CheckDisconnectionOfPairedDeviceTask, self).__init__()
    self._test = test
    self._device_mac = device_mac

  def _ConnectedDevice(self, device_props):
    """Indicates if a device matches the filter, and so should be unpaired

    If a name fragment or MAC address is given, the corresponding property
    must match. If neither is given, all devices should be unpaired.
    """
    return (device_props["Address"] == self._device_mac and
            int(device_props["Connected"]) >= 1)

  def _CheckDisconnection(self):
    bluetooth_manager = self._test.dut.bluetooth
    adapter = bluetooth_manager.GetFirstAdapter(self._test.host_mac)
    devices = bluetooth_manager.GetAllDevices(adapter).values()
    connected_devices = filter(self._ConnectedDevice, devices)
    logging.info('Connected and paired %d device(s)', len(connected_devices))
    return len(connected_devices) == 0

  def Run(self):
    flag_disconnection = RetryWithProgress(
        self._test.template, _MSG_UNPAIR,
        'Check disconnection of the paired base',
        INPUT_MAX_RETRY_TIMES, INPUT_RETRY_INTERVAL,
        self._CheckDisconnection)
    if flag_disconnection:
      msg = 'Shift-P-A-I-R: done'
      self.Pass()
    else:
      msg = 'Shift-P-A-I-R: not done'
      self.Fail(msg)
    factory.console.info(msg)
    _AppendLog(self._test.log_file, msg)


def _ExecuteFixtureMethod(fixture, operation, post_sleep=0):
  """Execute a method of the charge test fixture."""
  # An operation is mapped to its corresponding fixture method defined in
  # base_charge_fixture.BaseChargeFixture class.
  FIXTURE_METHOD_DICT = {'START_CHARGING': 'StartCharging',
                         'STOP_CHARGING': 'StopCharging',
                         'ENABLE_MAGNET': 'EnableMagnet',
                         'DISABLE_MAGNET': 'DisableMagnet'}
  fixture_method = getattr(fixture, FIXTURE_METHOD_DICT.get(operation))
  factory.console.info('Executing fixture method: %s', fixture_method.__name__)
  fixture_method()
  time.sleep(post_sleep)


class FixtureControlTask(test_task.TestTask):
  """The task to control the charge test fixture.

  Args:
    operation: the operation to be performed by the test fixture.
  """

  def __init__(self, test, operation, post_sleep=0):
    # pylint: disable=super-init-not-called
    self._fixture = test.fixture
    self._operation = operation
    self._post_sleep = post_sleep

  def Run(self):
    try:
      _ExecuteFixtureMethod(self._fixture, self._operation,
                            post_sleep=self._post_sleep)
      self.Pass()
    except Exception as e:
      self.Fail('error in executing %s (%s)' % (self._operation, e))


def _SaveLocalBatteryLog(base_enclosure_serial_number, mac, step,
                         battery_level, log_filename):
  """Save the battery log on the local test host."""
  with open(log_filename, 'a') as f:
    f.write('%s %s %s [%s]: %s\n' %
            (GetCurrentTime(), base_enclosure_serial_number, mac, step,
             battery_level))


class ReadBatteryLevelTask(test_task.TestTask):
  """A class to read battery level."""

  MSG_DICT = {READ_BATTERY_STEP_1: _MSG_READ_BATTERY_1,
              READ_BATTERY_STEP_2: _MSG_READ_BATTERY_2}

  def __init__(self, test, mac, step):
    super(ReadBatteryLevelTask, self).__init__()
    self._test = test
    self._mac = mac
    self._step = step

  def Run(self):
    self._test.template.SetState(self.MSG_DICT.get(self._step))

    factory.console.info('%s via %s ...', self._step, self._test.hci_device)
    try:
      battery_level = int(RetryWithProgress(
          self._test.template, self.MSG_DICT.get(self._step), self._step,
          INPUT_MAX_RETRY_TIMES, INPUT_RETRY_INTERVAL,
          bluetooth_utils.GattTool.GetDeviceInfo,
          self._mac, 'battery level', hci_device=self._test.hci_device,
          timeout=self._test.args.read_bluetooth_uuid_timeout_secs))
      factory.console.info('%s: %d', self._step, battery_level)
    except bluetooth_utils.BluetoothUtilsError as e:
      self.Fail('%s failed to get battery level: %s' % (self._step, e))
      return

    old_battery_level = state.get_shared_data(self._step)
    if (self._step == READ_BATTERY_STEP_1 and
        (old_battery_level is None or battery_level < old_battery_level)):
      # If the battery level at step 1 becomes higher over different rounds
      # (when the operator keeps retesting it for any reasons),
      # we only keep the lowest one. This is because we want to test if the
      # battery could charge to a higher level at step 2 than step 1.
      state.set_shared_data(self._step, battery_level)
    elif self._step == READ_BATTERY_STEP_2:
      # We keep the latest battery level read at step 2.
      state.set_shared_data(self._step, battery_level)

    if self._step == READ_BATTERY_STEP_1:
      data = ('\nSN: %s\nMAC: %s\n' %
              (self._test.args.base_enclosure_serial_number, self._mac))
    else:
      data = ''
    data += '%s: %s\n' % (self._step, battery_level)
    _AppendLog(self._test.log_file, data)

    if self._test.args.battery_log:
      _SaveLocalBatteryLog(self._test.args.base_enclosure_serial_number,
                           self._mac, self._step, battery_level,
                           self._test.args.battery_log)

    self.Pass()


class CheckBatteryLevelTask(test_task.TestTask):
  """This battery level test checks whether the following condistions
  are satisfied:

  1. The battery levels are read twice.
  2. battery_level_1 < battery_level_2
  3. battery_level_1 >= expected_battery_level
  """

  def __init__(self, test):
    super(CheckBatteryLevelTask, self).__init__()
    self._test = test

  def Run(self):
    self._test.template.SetState(_MSG_BATTERY_CHARGE_TEST)

    battery_level_1 = state.get_shared_data(READ_BATTERY_STEP_1)
    battery_level_2 = state.get_shared_data(READ_BATTERY_STEP_2)
    factory.console.info('%s: %s', READ_BATTERY_STEP_1, str(battery_level_1))
    factory.console.info('%s: %s', READ_BATTERY_STEP_2, str(battery_level_2))

    if not battery_level_1 or not battery_level_2:
      fail_msg = 'Battery levels should be read twice. read_1: %s, read_2: %s'
    elif (battery_level_1 > battery_level_2 or
          (battery_level_1 == battery_level_2 and battery_level_1 < 100)):
      fail_msg = 'Base battery is not charged up. read_1: %s, read_2: %s'
    elif battery_level_1 < self._test.args.expected_battery_level:
      # Note: battery_level_1 instead of battery_level_2 should be larger than
      #       the expected_battery_level since battery_level_2 is read while
      #       charging and its value is usually larger than its actual value.
      fail_msg = 'Measured battery level %s is less than the expected level %s.'
    else:
      self.Pass()
      return
    self.Fail(fail_msg % (battery_level_1, battery_level_2))


class ChargeTestTask(test_task.TestTask):

  def __init__(self, test, mac, step):
    super(ChargeTestTask, self).__init__()
    self._test = test
    self._mac = mac
    self._step = step

  def ReadBatteryLevel(self, step):
    _ResetAdapter()
    if self._test.args.use_charge_fixture:
      _ExecuteFixtureMethod(self._test.fixture, 'ENABLE_MAGNET')
    factory.console.info('Begin reading battery level...')
    value = bluetooth_utils.GattTool.GetDeviceInfo(
        self._mac, 'battery level', hci_device=self._test.hci_device,
        timeout=self._test.args.read_bluetooth_uuid_timeout_secs)
    if self._test.args.use_charge_fixture:
      _ExecuteFixtureMethod(self._test.fixture, 'DISABLE_MAGNET')
    factory.console.info('%s: %s', step, value)
    return int(value)

  def Run(self):
    if self._step == READ_BATTERY_STEP_1:
      self._test.template.SetState(_MSG_READ_BATTERY_1)
      battery_level = self.ReadBatteryLevel(self._step)
      state.set_shared_data(BATTERY_LEVEL_KEY, battery_level)
      self.Pass()

    elif self._step == READ_BATTERY_STEP_2:
      def _ReadAndCheckBatteryLevel():
        battery_level2 = self.ReadBatteryLevel(self._step)
        result = battery_level2 > battery_level1
        if result:
          state.set_shared_data(BATTERY_LEVEL_KEY, battery_level2)
        return result

      self._test.template.SetState(_MSG_READ_BATTERY_2)
      battery_level1 = state.get_shared_data(BATTERY_LEVEL_KEY)

      # Check if the battery is charging for up to READ_BATTERY_MAX_RETRY_TIMES.
      # Note: the magnet needs to be taken away and re-applied each time.
      #       This operation could be performed automatically with a charging
      #       test fixture; otherwise, it must be performed manually. Also
      #       note that there is a 5-second delay at reading the battery level.
      count = 0
      success_increased_level = False
      while (not success_increased_level and
             count < READ_BATTERY_MAX_RETRY_TIMES):
        success_increased_level = _ReadAndCheckBatteryLevel()
        count += 1

      if success_increased_level:
        self.Pass()
      else:
        self.Fail('ChargeTestTask: the battery is not charging!')


class CheckFirmwareRevisionTestTask(test_task.TestTask):
  """A task class to read firmware revision string."""

  def __init__(self, test, mac):
    super(CheckFirmwareRevisionTestTask, self).__init__()
    self._test = test
    self._mac = mac

  def Run(self):
    self._test.template.SetState(_MSG_READ_FIRMWARE_REVISION_STRING)

    factory.console.info('Begin reading firmware revision string via %s...',
                         self._test.hci_device)
    try:
      fw = RetryWithProgress(
          self._test.template, _MSG_READ_FIRMWARE_REVISION_STRING,
          'reading firmware', INPUT_MAX_RETRY_TIMES, INPUT_RETRY_INTERVAL,
          bluetooth_utils.GattTool.GetDeviceInfo, self._mac,
          'firmware revision string', hci_device=self._test.hci_device,
          timeout=self._test.args.read_bluetooth_uuid_timeout_secs)
    except bluetooth_utils.BluetoothUtilsError as e:
      self.Fail('Failed to get firmware revision string: %s' % e)
      return

    factory.console.info('Expected firmware: %s',
                         self._test.args.firmware_revision_string)
    factory.console.info('Actual firmware: %s', fw)
    state.set_shared_data(self._test.args.firmware_revision_string_key, fw)

    data = 'FW: %s\n' % fw
    _AppendLog(self._test.log_file, data)

    if fw == self._test.args.firmware_revision_string:
      self.Pass()
    else:
      self.Fail('Expected firmware: %s, actual firmware: %s' %
                (self._test.args.firmware_revision_string, fw))


class InputTestTask(test_task.TestTask):
  """The task to test bluetooth input device functionality.

  The task will try to pair with the device given by the test,
  and make the connection.
  After the connection, the number of input event should plus one.
  If it does not plus one, the task fails.
  After connection, operator can try to use the input device and press Enter
  to pass checking or Esc to fail the task.
  In the end of test, the task will try to disconnect the device and remove the
  device. If these procedures fail, the task fails.

  Args:
    finish_after_pair: Whether to end the test after pairing. If false,
                       the operator is prompted to test input, and then
                       the device is unpaired

  """

  def __init__(self, test, finish_after_pair):
    super(InputTestTask, self).__init__()
    self._test = test
    self._target_mac = None
    self._bt_manager = None
    self._adapter = None
    self._need_to_cleanup = True
    self._finish_after_pair = finish_after_pair

  def Cleanup(self):
    """Cleans up input device if it was not cleaned"""
    if self._need_to_cleanup:
      success_to_remove = self.RemoveInput()
      if not success_to_remove:
        logging.error('Fail to remove input in Cleanup')

  def RemoveInput(self):
    """Disconnects the input device and removes it.

    Returns:
      If disconnection and removal are both succeeded, return True, return False
      otherwise.
    """
    return_value = True
    try:
      self._bt_manager.SetDeviceConnected(self._adapter, self._target_mac,
                                          False)
      logging.info('Turned off the connection')
    except self._bt_manager.Error:
      logging.exception('Fail to turn off the connection.')
      return_value = False
    try:
      self._bt_manager.RemovePairedDevice(self._adapter, self._target_mac)
      logging.info('Remove the device')
    except self._bt_manager.Error:
      logging.exception('Fail to remove the device.')
      return_value = False
    return return_value

  def RemoveInputAndQuit(self, success):
    """Removes the input device and quits the task.

    Args:
      success: The task is passed by operator or not.

    Returns:
      If the task is passed by operator and input has been removed successfully,
      pass the task, fail the task otherwise.
    """
    success_to_remove = self.RemoveInput()
    # No need to cleanup again after the task does Pass() or Fail() if removal
    # succeeds here.
    self._need_to_cleanup = not success_to_remove
    if success:
      if success_to_remove:
        self.Pass()
      else:
        self.Fail('InputTestTask: Fail to remove input')
    else:
      self.Fail('Failed by operator')

  def OperatorTestInput(self):
    """Lets operator test the input and press key to pass/fail the task."""
    logging.info('InputTestTask: Test the input by operator now')
    self._test.template.SetState(_MSG_TEST_INPUT)
    self._test.ui.BindKey(test_ui.ENTER_KEY,
                          lambda _: self.RemoveInputAndQuit(True))
    self._test.ui.BindKey(test_ui.ESCAPE_KEY,
                          lambda _: self.RemoveInputAndQuit(False))

  def Run(self):
    def SaveLogAndFail(fail_reason):
      """Save the fail log and invoke Fail()."""
      data = 'Pairing fail: %s\n' % fail_reason
      _AppendLog(self._test.log_file, data)
      self.Fail(fail_reason)

    input_count_before_connection = CheckInputCount()
    self._bt_manager = self._test.dut.bluetooth
    self._adapter = self._bt_manager.GetFirstAdapter(self._test.host_mac)
    self._target_mac = self._test.GetInputDeviceMac()
    if not self._target_mac:
      SaveLogAndFail('InputTestTask: No MAC with which to pair')
    logging.info('Attempting pair with %s', self._target_mac)

    self._bt_manager.DisconnectAndUnpairDevice(self._adapter, self._target_mac)

    success_create_device = RetryWithProgress(
        self._test.template, _MSG_PAIR_INPUT_DEVICE, 'create paired device',
        INPUT_MAX_RETRY_TIMES, INPUT_RETRY_INTERVAL,
        self._bt_manager.CreatePairedDevice, self._adapter,
        self._target_mac, self._DisplayPasskey, self._AuthenticationCancelled)
    if not success_create_device:
      SaveLogAndFail('InputTestTask: Fail to create paired device.')
      return

    success_connect_device = RetryWithProgress(
        self._test.template, _MSG_CONNECT_INPUT_DEVICE, 'connect input device',
        INPUT_MAX_RETRY_TIMES, INPUT_RETRY_INTERVAL,
        self._bt_manager.SetDeviceConnected, self._adapter,
        self._target_mac, True)
    if not success_connect_device:
      SaveLogAndFail('InputTestTask: Fail to connect device.')
      return

    if not WaitForInputCount(self, input_count_before_connection + 1):
      return

    if self._finish_after_pair:
      # We leave the device paired
      self._need_to_cleanup = False
      data = 'Pairing finished\n'
      _AppendLog(self._test.log_file, data)
      self.Pass()
      return

    self.OperatorTestInput()

  def _DisplayPasskey(self, passkey):
    logging.info("Displaying passkey %s", passkey)
    label = MakePasskeyLabelPrompt(passkey)
    self._test.template.SetState(label)

  def _AuthenticationCancelled(self):
    self._test.template.SetState(_MSG_AUTH_FAILED)


class BluetoothTest(unittest.TestCase):
  ARGS = [
      Arg('expected_adapter_count', int,
          'Number of bluetooth adapters on the machine.',
          default=0),
      Arg('manufacturer_id', int,
          'ID of the manufacturer.',
          optional=True),
      Arg('detect_adapters_retry_times', int,
          'Maximum retry time to detect adapters.',
          default=10),
      Arg('detect_adapters_interval_secs', int,
          'Interval in seconds between each retry to detect adapters.',
          default=2),
      Arg('read_bluetooth_uuid_timeout_secs', int,
          'Timeout to read bluetooth characteristics via uuid.',
          default=None, optional=True),
      Arg('scan_devices', bool,
          'Scan bluetooth device.',
          default=False),
      Arg('prompt_scan_message', bool,
          'Prompts a message to tell user to enable remote devices discovery '
          'mode.',
          default=True),
      Arg('keyword', str,
          'Only cares remote devices whose "Name" contains keyword.',
          default=None, optional=True),
      Arg('average_rssi_threshold', float,
          'Checks the largest average RSSI among scanned device is equal to or '
          'greater than average_rssi_threshold.',
          default=None, optional=True),
      Arg('scan_counts', int,
          'Number of scans to calculate average RSSI.',
          default=3),
      Arg('scan_timeout_secs', int,
          'Timeout to do one scan.',
          default=5),
      Arg('input_device_mac', str,
          'The mac address of bluetooth input device.',
          default=None, optional=True),
      Arg('input_device_mac_key', str,
          'A key for factory shared data containing the mac address.',
          default=None, optional=True),
      Arg('input_device_rssi_key', str,
          'A key for factory shared data containing the rssi value.',
          default=None, optional=True),
      Arg('firmware_revision_string_key', str,
          'A key of factory shared data containing firmware revision string.',
          optional=True),
      Arg('firmware_revision_string', str,
          'The firmware revision string.',
          optional=True),
      Arg('average_rssi_lower_threshold', (float, dict),
          'Checks the average RSSI of the target mac is equal to or '
          'greater than this threshold.',
          default=None, optional=True),
      Arg('average_rssi_upper_threshold', (float, dict),
          'Checks the average RSSI of the target mac is equal to or '
          'less than this threshold.',
          default=None, optional=True),
      Arg('pair_with_match', bool,
          'Whether to pair with the strongest match.',
          default=False, optional=True),
      Arg('finish_after_pair', bool,
          'Whether the test should end immediately after pairing completes.',
          default=False),
      Arg('unpair', bool,
          'Whether to unpair matching devices instead of pair.',
          default=False, optional=True),
      Arg('check_shift_pair_keys', bool,
          'Check if shift-p-a-i-r keys are pressed.',
          default=False, optional=True),
      Arg('check_battery_charging', bool,
          'Whether to check if the battery is charging.',
          default=False, optional=True),
      Arg('read_battery_level', int,
          'Read the battery level.',
          default=None, optional=True),
      Arg('check_battery_level', bool,
          'Whether to check the battery level.',
          default=False, optional=True),
      Arg('prompt_into_fixture', bool,
          'Prompt the user to place the base into the test fixture.',
          default=False, optional=True),
      Arg('use_charge_fixture', bool,
          'Whether a charge fixture is employed.',
          default=False, optional=True),
      Arg('reset_fixture', bool,
          'Whether to reset the fixture.',
          default=False, optional=True),
      Arg('start_charging', bool,
          'Prompt the user to start charging the base.',
          default=False, optional=True),
      Arg('enable_magnet', bool,
          'Enable the base.',
          default=False, optional=True),
      Arg('reset_magnet', bool,
          'Reset the base.',
          default=False, optional=True),
      Arg('stop_charging', bool,
          'Prompt the user to stop charging the base.',
          default=False, optional=True),
      Arg('base_enclosure_serial_number', unicode,
          'The base enclosure serial number.',
          default=None, optional=True),
      Arg('battery_log', str,
          'The battery log file.',
          default=None, optional=True),
      Arg('expected_battery_level', int,
          'The expected battery level.',
          default=100, optional=True),
      Arg('log_path', str,
          'The directory of the log on the local test host.',
          optional=True),
      Arg('test_host_id_file', str,
          'The file storing the id of the test host.',
          optional=True),
  ]

  def SetStrongestRssiMac(self, mac_addr):
    self._strongest_rssi_mac = mac_addr

  def GetInputDeviceMac(self):
    """Gets the input device MAC to pair with, or None if None

    This may be specified in the arguments, or computed at scan time.
    """
    if self._input_device_mac:
      return self._input_device_mac
    else:
      return self._strongest_rssi_mac

  def setUp(self):
    self.dut = device_utils.CreateDUTInterface()
    self.ui = test_ui.UI()
    self.ui.AppendCSS('.start-font-size {font-size: 2em;}')
    self.template = ui_templates.TwoSections(self.ui)
    self._task_list = []
    self._strongest_rssi_mac = None
    self.fixture = None
    if self.args.input_device_mac_key:
      self._input_device_mac = (
          ColonizeMac(state.get_shared_data(self.args.input_device_mac_key)))
    else:
      self._input_device_mac = self.args.input_device_mac

    self.btmgmt = bluetooth_utils.BtMgmt(self.args.manufacturer_id)
    self.hci_device = self.btmgmt.GetHciDevice()
    self.host_mac = self.btmgmt.GetMac()
    logging.info('manufacturer_id %s: %s %s',
                 self.args.manufacturer_id, self.hci_device, self.host_mac)
    self.log_file = None

    if self.args.base_enclosure_serial_number:
      if (self.args.test_host_id_file and
          os.path.isfile(self.args.test_host_id_file)):
        with open(self.args.test_host_id_file) as f:
          test_host_id = f.read().strip()
      else:
        test_host_id = None

      filename = '.'.join([self.args.base_enclosure_serial_number,
                           str(test_host_id)])
      if self.args.log_path:
        self.log_file = os.path.join(self.args.log_path, filename)

  def tearDown(self):
    """Close the charge test fixture."""
    if self.args.use_charge_fixture:
      self.fixture.Close()
    if self.log_file:
      testlog.AttachFile(
          self.log_file, 'text/plain',
          'bluetooth_%s.txt' % os.path.dirname(self.log_file),
          description='Raw execution logs')

  def runTest(self):
    if self.args.use_charge_fixture:
      # Import this module only when a test station needs it.
      # A base SMT test station does not need to use the charge fixture.
      # pylint: disable=no-name-in-module
      from cros.factory.test.fixture import base_charge_fixture
      # Note: only reset the fixture in InitializeFixture test.
      #       This will stop charging and disable the magnet initially.
      #       For the following tests, do not reset the fixture so that
      #       the charging could be continued across tests in the test list
      #       defined in the base_host. The purpose is to keep charing the
      #       battery while executing other tests.
      self.fixture = base_charge_fixture.BaseChargeFixture(
          reset=self.args.reset_fixture)

    if self.args.expected_adapter_count:
      self._task_list.append(DetectAdapterTask(
          self, self.args.expected_adapter_count))

    if self.args.scan_devices:
      if self.args.prompt_scan_message:
        self._task_list.append(TurnOnTask(self, _MSG_TURN_ON_DEVICE))
      self._task_list.append(ScanDevicesTask(self))

    if self.args.input_device_rssi_key:
      self._task_list.append(DetectRSSIofTargetMACTask(self))

    if self.args.prompt_into_fixture:
      self._task_list.append(
          TurnOnTask(self, _MSG_INTO_FIXTURE, test_ui.SPACE_KEY))

    if self.args.read_battery_level == 1:
      self._task_list.append(
          ReadBatteryLevelTask(self, self._input_device_mac,
                               READ_BATTERY_STEP_1))

    if self.args.enable_magnet and self.args.use_charge_fixture:
      self._task_list.append(FixtureControlTask(self, 'ENABLE_MAGNET'))

    if self.args.reset_magnet:
      if self.args.use_charge_fixture:
        self._task_list.append(
            FixtureControlTask(self, 'DISABLE_MAGNET', post_sleep=1))
        self._task_list.append(FixtureControlTask(self, 'ENABLE_MAGNET'))
      else:
        self._task_list.append(
            TurnOnTask(self, _MSG_RESET_MAGNET, test_ui.SPACE_KEY))

    if self.args.start_charging:
      if self.args.use_charge_fixture:
        self._task_list.append(
            # Let it charge for a little while.
            FixtureControlTask(self, 'START_CHARGING'))
      else:
        self._task_list.append(
            TurnOnTask(self, _MSG_START_CHARGE, test_ui.SPACE_KEY))

    if self.args.check_shift_pair_keys:
      self._task_list.append(
          CheckDisconnectionOfPairedDeviceTask(self, self._input_device_mac))

    if self.args.unpair:
      self._task_list.append(
          UnpairTask(self, self._input_device_mac, self.args.keyword))

    if self.args.firmware_revision_string:
      self._task_list.append(
          CheckFirmwareRevisionTestTask(self, self._input_device_mac))

    if self.args.pair_with_match:
      self._task_list.append(InputTestTask(self, self.args.finish_after_pair))

    if self.args.read_battery_level == 2:
      self._task_list.append(
          ReadBatteryLevelTask(self, self._input_device_mac,
                               READ_BATTERY_STEP_2))

    if self.args.check_battery_level:
      self._task_list.append(CheckBatteryLevelTask(self))

    if self.args.stop_charging:
      if self.args.use_charge_fixture:
        self._task_list.append(FixtureControlTask(self, 'STOP_CHARGING'))
      else:
        self._task_list.append(
            TurnOnTask(self, _MSG_STOP_CHARGE, test_ui.SPACE_KEY))

    test_task.TestTaskManager(self.ui, self._task_list).Run()
