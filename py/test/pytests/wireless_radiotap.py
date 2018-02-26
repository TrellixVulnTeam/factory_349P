# Copyright 2014 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""A factory test for checking Wifi antenna.

The test accepts a dict of wireless specs.
Each spec contains candidate services and the signal constraints.
For each spec, the test will connect to AP first.
And scan the signal quality to get signal strength for all antennas.
Then the test checks signal quality.

Be sure to set AP correctly.
1. Select one fixed channel instead of auto.
2. Disable the TX power control in AP.
3. Make sure SSID of AP is unique.

This test case can be used for Intel WP2 7260 chip.
"""

import collections
import logging
import re
import struct
import sys
import time

import dbus

import factory_common  # pylint: disable=unused-import
from cros.factory.test import event_log
from cros.factory.test.i18n import _
from cros.factory.test import session
from cros.factory.test import test_ui
from cros.factory.utils.arg_utils import Arg
from cros.factory.utils import net_utils
from cros.factory.utils import process_utils
from cros.factory.utils import sync_utils
from cros.factory.utils import type_utils

try:
  sys.path.append('/usr/local/lib/flimflam/test')
  import flimflam
except ImportError:
  pass


_RE_IWSCAN = re.compile(r'freq: (\d+).*SSID: (.+)$')
_RE_WIPHY = re.compile(r'wiphy (\d+)')
_RE_BEACON = re.compile(r'(\d+) MHz.*Beacon \((.+)\)')

_ANTENNA_CONFIG = ['all', 'main', 'aux']


def FlimGetService(flim, name):
  """Get service by property.

  Args:
    flim: flimflam object
    name: property name
  """
  return sync_utils.PollForCondition(
      lambda: flim.FindElementByPropertySubstring('Service', 'Name', name),
      timeout_secs=10, poll_interval_secs=0.5)


def FlimGetServiceProperty(service, prop):
  """Get property from a service.

  Args:
    service: flimflam service object
    prop: property name
  """
  timeout = time.time() + 10
  while time.time() < timeout:
    try:
      properties = service.GetProperties()
    except dbus.exceptions.DBusException as e:
      logging.exception('Error reading service property')
      time.sleep(1)
    else:
      return properties[prop]
  raise e


def FlimConfigureService(flim, ssid, password):
  """Config wireless ssid and password.

  Args:
    ssid: ssid name
    password: wifi key to authenticate
  """
  wlan_dict = {
      'Type': dbus.String('wifi', variant_level=1),
      'Mode': dbus.String('managed', variant_level=1),
      'AutoConnect': dbus.Boolean(False, variant_level=1),
      'SSID': dbus.String(ssid, variant_level=1)}
  if password:
    wlan_dict['Security'] = dbus.String('psk', variant_level=1)
    wlan_dict['Passphrase'] = dbus.String(password, variant_level=1)

  flim.manager.ConfigureService(wlan_dict)


def IwScan(devname, sleep_retry_time_secs=2, max_retries=10):
  """Scans on device.

  Args:
    devname: device name.
    sleep_retry_time_secs: The sleep time before a retry.
    max_retries: The maximum retry time to scan.
  Returns:
    A list of (ssid, frequency) tuple.

  Raises:
    IwException if fail to scan for max_retries tries,
    or fail because of reason other than device or resource busy (-16)
  """
  cmd = r"iw %s scan | grep -e 'freq\|SSID' | sed 'N;s/\n/ /'" % devname
  for unused_try_count in xrange(max_retries):
    process = process_utils.Spawn(
        cmd, read_stdout=True, log_stderr_on_error=True, log=True, shell=True)
    stdout, stderr = process.communicate()
    retcode = process.returncode
    event_log.Log('iw_scaned', retcode=retcode, stderr=stderr)
    if retcode == 0:
      scan_result = []
      for line in stdout.splitlines():
        m = _RE_IWSCAN.search(line)
        if m:
          scan_result.append((m.group(2), m.group(1)))
      if scan_result:
        logging.info('IwScan success.')
        return scan_result
    elif retcode == 234:  # Invalid argument (-22)
      raise Exception('Failed to iw scan, ret code: %d. stderr: %s'
                      'Frequency might be wrong.' %
                      (retcode, stderr))
    elif retcode != 240:  # Device or resource busy (-16)
      raise Exception('Failed to iw scan, ret code: %d. stderr: %s' %
                      (retcode, stderr))
    time.sleep(sleep_retry_time_secs)
  raise Exception('Failed to iw scan for %s tries' % max_retries)


class RadiotapPacket(object):
  FIELD = collections.namedtuple('Field', ['name', 'struct', 'align'])
  ANTENNA_SIGNAL_FIELD = FIELD('Antenna Signal', struct.Struct('b'), 0)
  ANTENNA_INDEX_FIELD = FIELD('Antenna Index', struct.Struct('B'), 0)
  EXTENDED_BIT = 31
  FIELDS = [
      FIELD('TSFT', struct.Struct('Q'), 8),
      FIELD('Flags', struct.Struct('B'), 0),
      FIELD('Rate', struct.Struct('B'), 0),
      FIELD('Channel', struct.Struct('HH'), 2),
      FIELD('FHSS', struct.Struct('BB'), 0),
      ANTENNA_SIGNAL_FIELD,
      FIELD('Antenna Noise', struct.Struct('b'), 0),
      FIELD('Lock Quality', struct.Struct('H'), 2),
      FIELD('TX Attenuation', struct.Struct('H'), 2),
      FIELD('dB TX Attenuation', struct.Struct('H'), 2),
      FIELD('dBm TX Power', struct.Struct('b'), 1),
      ANTENNA_INDEX_FIELD,
      FIELD('dB Antenna Signal', struct.Struct('B'), 0),
      FIELD('dB Antenna Noise', struct.Struct('B'), 0),
      FIELD('RX Flags', struct.Struct('H'), 2),
      FIELD('TX Flags', struct.Struct('H'), 2),
      FIELD('RTS Retries', struct.Struct('B'), 0),
      FIELD('Data Retries', struct.Struct('B'), 0),
      None,
      FIELD('MCS', struct.Struct('BBB'), 1),
      FIELD('AMPDU status', struct.Struct('IHBB'), 4),
      FIELD('VHT', struct.Struct('HBBBBBBBBH'), 2),
      FIELD('Timestamp', struct.Struct('QHBB'), 8),
      None,
      None,
      None,
      None,
      None,
      None]
  MAIN_HEADER_FORMAT = struct.Struct('BBhI')
  PARSE_INFO = collections.namedtuple('AntennaData', ['header_size',
                                                      'data_bytes',
                                                      'antenna_offsets'])

  # This is a variable-length header, but this is what we want to see.
  EXPECTED_HEADER_FORMAT = struct.Struct(MAIN_HEADER_FORMAT.format + 'II')

  @staticmethod
  def Decode(packet_bytes):
    """Returns signal strength data for each antenna.

    Format is {all_signal, {antenna_index, antenna_signal}}.
    """
    if len(packet_bytes) < RadiotapPacket.EXPECTED_HEADER_FORMAT.size:
      return None
    parts = RadiotapPacket.EXPECTED_HEADER_FORMAT.unpack_from(packet_bytes)
    present0, present1, present2 = parts[3:]
    parse_info = RadiotapPacket.ParseHeader([present0, present1, present2])
    required_bytes = parse_info.header_size + parse_info.data_bytes
    if len(packet_bytes) < required_bytes:
      return None
    antenna_data = []
    for datum in filter(bool, parse_info.antenna_offsets):
      signal = datum.get(RadiotapPacket.ANTENNA_SIGNAL_FIELD)
      if RadiotapPacket.ANTENNA_SIGNAL_FIELD not in datum:
        continue
      signal_offset = datum[RadiotapPacket.ANTENNA_SIGNAL_FIELD]
      signal, = RadiotapPacket.ANTENNA_SIGNAL_FIELD.struct.unpack_from(
          packet_bytes[(signal_offset + parse_info.header_size):])
      if RadiotapPacket.ANTENNA_INDEX_FIELD in datum:
        index_offset = datum[RadiotapPacket.ANTENNA_INDEX_FIELD]
        index, = RadiotapPacket.ANTENNA_SIGNAL_FIELD.struct.unpack_from(
            packet_bytes[(index_offset + parse_info.header_size):])
        antenna_data.append((index, signal))
      else:
        antenna_data.append(signal)
    return antenna_data

  @staticmethod
  def ParseHeader(field_list):
    """Returns packet information of the radiotap header should have."""
    header_size = RadiotapPacket.MAIN_HEADER_FORMAT.size
    data_bytes = 0
    antenna_offsets = []

    for bitmask in field_list:
      antenna_offsets.append({})
      for bit, field in enumerate(RadiotapPacket.FIELDS):
        if bitmask & (1 << bit):
          if field is None:
            logging.warning('Unknown field at bit %d is given in radiotap '
                            'packet, the result would probably be wrong...')
            continue
          if field.align and (data_bytes % field.align):
            data_bytes += field.align - (data_bytes % field.align)
          if (field == RadiotapPacket.ANTENNA_SIGNAL_FIELD or
              field == RadiotapPacket.ANTENNA_INDEX_FIELD):
            antenna_offsets[-1][field] = data_bytes
          data_bytes += field.struct.size

      if not bitmask & (1 << RadiotapPacket.EXTENDED_BIT):
        break
      header_size += 4
    else:
      raise NotImplementedError('Packet has too many extensions for me!')

    # Offset the antenna fields by the header size.
    return RadiotapPacket.PARSE_INFO(header_size, data_bytes, antenna_offsets)


class Capture(object):
  """Context for a live tcpdump packet capture for beacons."""

  def __init__(self, device_name, phy):
    self.monitor_process = None
    self.created_device = None
    self.parent_device = device_name
    self.phy = phy

  def CreateDevice(self, monitor_device='antmon0'):
    """Creates a monitor device to monitor beacon."""
    process_utils.Spawn(['iw', self.parent_device, 'interface', 'add',
                         monitor_device, 'type', 'monitor'], check_call=True)
    self.created_device = monitor_device

  def RemoveDevice(self, device_name):
    """Removes monitor device."""
    process_utils.Spawn(['iw', device_name, 'del'], check_call=True)

  def GetSignal(self):
    """Gets signal from tcpdump."""
    while True:
      line = self.monitor_process.stdout.readline()
      m = _RE_BEACON.search(line)
      if m:
        freq = int(m.group(1))
        ssid = m.group(2)
        break
    packet_bytes = ''
    while True:
      line = self.monitor_process.stdout.readline()
      if not line.startswith('\t0x'):
        break

      # Break up lines of the form "\t0x0000: abcd ef" into a string
      # "\xab\xcd\xef".
      parts = line[3:].split()
      for part in parts[1:]:
        packet_bytes += chr(int(part[:2], 16))
        if len(part) > 2:
          packet_bytes += chr(int(part[2:], 16))
      packet = RadiotapPacket.Decode(packet_bytes)
      if packet:
        return {'ssid': ssid, 'freq': freq, 'signal': packet}

  def set_beacon_filter(self, value):
    """Sets beacon filter.

    This function may only for Intel WP2 7260 chip.
    """
    with open('/sys/kernel/debug/ieee80211/%s/netdev:%s/iwlmvm/bf_params' %
              (self.phy, self.parent_device), 'w') as f:
      f.write('bf_enable_beacon_filter=%d\n' % value)

  def __enter__(self):
    if not self.created_device:
      self.CreateDevice()
    process_utils.Spawn(
        ['ip', 'link', 'set', self.created_device, 'up'], check_call=True)
    process_utils.Spawn(
        ['iw', self.parent_device, 'set', 'power_save', 'off'], check_call=True)
    self.set_beacon_filter(0)
    self.monitor_process = process_utils.Spawn(
        ['tcpdump', '-nUxxi', self.created_device, 'type', 'mgt',
         'subtype', 'beacon'], stdout=process_utils.PIPE)
    return self

  def __exit__(self, exception, value, traceback):
    self.monitor_process.kill()
    self.set_beacon_filter(1)
    if self.created_device:
      self.RemoveDevice(self.created_device)


class WirelessRadiotapTest(test_ui.TestCaseWithUI):
  """Basic wireless test class.

  Properties:
    _antenna: current antenna config.
    _phy_name: wireless phy name to test.
  """
  ARGS = [
      Arg('device_name', str,
          'Wireless device name to test. '
          'Set this correctly if check_antenna is True.', default='wlan0'),
      Arg('services', list,
          'A list of (service_ssid, freq, password) tuples like '
          '``[(SSID1, FREQ1, PASS1), (SSID2, FREQ2, PASS2), '
          '(SSID3, FREQ3, PASS3)]``. The test will only check the service '
          'whose antenna_all signal strength is the largest. For example, if '
          '(SSID1, FREQ1, PASS1) has the largest signal among the APs, '
          'then only its results will be checked against the spec values.'),
      Arg('strength', dict,
          'A dict of minimal signal strengths. For example, a dict like '
          '``{"main": strength_1, "aux": strength_2, "all": strength_all}``. '
          'The test will check signal strength according to the different '
          'antenna configurations in this dict.'),
      Arg('scan_count', int,
          'Number of scans to get average signal strength.', default=5),
      Arg('switch_antenna_sleep_secs', int,
          'The sleep time after switchingantenna and ifconfig up. Need to '
          'decide this value carefully since itdepends on the platform and '
          'antenna config to test.', default=10),
      Arg('press_space_to_start', bool,
          'Press space to start the test.', default=True)]

  def setUp(self):
    self.ui.ToggleTemplateClass('font-large', True)

    self._phy_name = self.DetectPhyName()
    logging.info('phy name is %s.', self._phy_name)

    net_utils.Ifconfig(self.args.device_name, True)
    self._flim = flimflam.FlimFlam(dbus.SystemBus())
    self._connect_service = None

  def tearDown(self):
    self.DisconnectService()

  def ConnectService(self, service_name, password):
    """Associates a specified wifi AP.

    Password can be '' or None.
    """
    try:
      self._connect_service = FlimGetService(self._flim, service_name)
    except type_utils.TimeoutError:
      session.console.info('Unable to find service %s', service_name)
      return False
    if FlimGetServiceProperty(self._connect_service, 'IsActive'):
      logging.warning('Already connected to %s', service_name)
    else:
      logging.info('Connecting to %s', service_name)
      FlimConfigureService(self._flim, service_name, password)
      success, diagnostics = self._flim.ConnectService(
          service=self._connect_service)
      if not success:
        session.console.info('Unable to connect to %s, diagnostics %s',
                             service_name, diagnostics)
        return False
      else:
        session.console.info(
            'Successfully connected to service %s', service_name)
    return True

  def DisconnectService(self):
    """Disconnect wifi AP."""
    if self._connect_service:
      self._flim.DisconnectService(service=self._connect_service)
      session.console.info(
          'Disconnect to service %s',
          FlimGetServiceProperty(self._connect_service, 'Name'))
      self._connect_service = None

  def DetectPhyName(self):
    """Detects the phy name for device_name device.

    Returns:
      The phy name for device_name device.
    """
    output = process_utils.CheckOutput(
        ['iw', 'dev', self.args.device_name, 'info'])
    logging.info('info output: %s', output)
    m = _RE_WIPHY.search(output)
    return ('phy' + m.group(1)) if m else None

  def ChooseMaxStrengthService(self, services, service_strengths):
    """Chooses the service that has the largest signal strength among services.

    Args:
      services: A list of services.
      service_strengths: A dict of strengths of each service.

    Returns:
      The service that has the largest signal strength among services.
    """
    max_strength_service, max_strength = None, -sys.float_info.max
    for service in services:
      strength = service_strengths[service]['all']
      if strength:
        session.console.info('Service %s signal strength %f.', service,
                             strength)
        event_log.Log('service_signal', service=service, strength=strength)
        if strength > max_strength:
          max_strength_service, max_strength = service, strength
      else:
        session.console.info('Service %s has no valid signal strength.',
                             service)

    if max_strength_service:
      logging.info('Service %s has the highest signal strength %f among %s.',
                   max_strength_service, max_strength, services)
      return max_strength_service
    else:
      logging.warning('Services %s are not valid.', services)
      return None

  def ScanSignal(self, service, times=3):
    """Scans antenna signal strengths for a specified service.

    Device should connect to the service before starting to capture signal.
    Signal result only includes antenna information of this service
    (ssid, freq).

    Args:
      service: (service_ssid, freq, password) tuple.
      times: Number of times to scan to get average.

    Returns:
      A list of signal result.
    """
    signal_list = []
    ssid, freq, password = service
    self.ui.SetState(_('Switching to AP {ap}: ', ap=ssid))
    if not self.ConnectService(ssid, password):
      return []

    self.ui.SetState(
        _('Scanning on device {device} frequency {freq}...',
          device=self.args.device_name,
          freq=freq))
    with Capture(self.args.device_name, self._phy_name) as capture:
      capture_times = 0
      while capture_times < times:
        signal_result = capture.GetSignal()
        if signal_result['ssid'] == ssid and signal_result['freq'] == freq:
          logging.info('%s', signal_result)
          signal_list.append(signal_result['signal'])
          capture_times += 1
    self.ui.SetState(
        _('Done scanning on device {device} frequency {freq}...',
          device=self.args.device_name,
          freq=freq))
    self.DisconnectService()
    return signal_list

  def AverageSignals(self, antenna_info):
    """Averages signal strengths for each antenna of a service.

    The dividend is the sum of signal strengths during all scans.
    The divisor is the number of times in the scan result.
    If a service is not scannable, its average value will be None.

    Args:
      antenna_info: A dict of each antenna information of a service.

    Returns:
      A dict of average signal strength of each antenna.
      {antenna1: signal1, antenna2: signal2}
    """
    # keys are services and values are averages
    average_results = {}
    # Averages the scanned strengths
    for antenna in _ANTENNA_CONFIG:
      average_results[antenna] = 0
    for signal in antenna_info:
      average_results['all'] += signal[0]
      average_results['main'] += signal[1][1]
      average_results['aux'] += signal[2][1]
    for antenna in _ANTENNA_CONFIG:
      average_results[antenna] = (
          float(average_results[antenna]) / len(antenna_info)
          if len(antenna_info) else None)
    return average_results

  def CheckSpec(self, service, spec_antenna_strength, average_signal):
    """Checks if the scan result of antenna config can meet test spec.

    Args:
      service: (service_ssid, freq, password) tuple.
      spec_antenna_strength: A dict of minimal signal strengths.
      average_signal: A dict of average signal strength of each service in
          service. {service: {antenna1: signal1, antenna2: signal2}}
    """
    for antenna in _ANTENNA_CONFIG:
      if spec_antenna_strength.get(antenna) is None:
        continue
      spec_strength = spec_antenna_strength[antenna]
      scanned_strength = average_signal[service][antenna]

      event_log.Log(
          'antenna_%s' % antenna, freq=service[1], rssi=scanned_strength,
          meet=(scanned_strength and scanned_strength > spec_strength))
      if not scanned_strength:
        self.FailTask(
            'Antenna %s, service: %s: Can not scan signal strength.' %
            (antenna, service))
      if scanned_strength < spec_strength:
        self.FailTask(
            'Antenna %s, service: %s: The scanned strength %f < spec strength'
            ' %f' % (antenna, service, scanned_strength, spec_strength))
      else:
        session.console.info(
            'Antenna %s, service: %s: The scanned strength %f > spec strength'
            ' %f', antenna, service, scanned_strength, spec_strength)

  def PreCheck(self, services):
    """Checks each service only has one frequency.

    Args:
      services: A list of (service_ssid, freq) tuples to scan.
    """
    wireless_services = {}
    self.ui.SetState(_('Checking frequencies...'))

    scan_result = IwScan(self.args.device_name)
    set_all_ssids = set(service[0] for service in services)

    for ssid, freq in scan_result:
      if ssid in set_all_ssids:
        if ssid not in wireless_services:
          wireless_services[ssid] = freq
        elif freq != wireless_services[ssid]:
          self.FailTask(
              'There are more than one frequencies for ssid %s.' % ssid)

  def runTest(self):
    if self.args.press_space_to_start:
      self.ui.SetState(_('Press space to start scanning.'))
      self.ui.WaitKeysOnce(test_ui.SPACE_KEY)

    self.PreCheck(self.args.services)

    average_signal = {}
    services = type_utils.MakeTuple(self.args.services)
    for service in services:
      signals = self.ScanSignal(service, self.args.scan_count)
      average_signal[service] = self.AverageSignals(signals)

    # Gets the service with the largest strength to test for each spec.
    test_service = self.ChooseMaxStrengthService(services,
                                                 average_signal)
    if test_service is None:
      self.FailTask('Services %s are not valid.' % self.args.services)
    else:
      self.CheckSpec(test_service, self.args.strength, average_signal)
