#!/usr/bin/env python
# Copyright 2015 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Module to retrieve non-volatile system information."""

from __future__ import print_function

import copy
import logging
import re

import factory_common  # pylint: disable=unused-import
from cros.factory.device import types
from cros.factory.hwid.v3 import common
from cros.factory.hwid.v3 import hwid_utils
from cros.factory.test import device_data
from cros.factory.test.env import paths
from cros.factory.test.rules import phase
from cros.factory.test import testlog_goofy
from cros.factory.utils.sys_utils import MountDeviceAndReadFile


# Static list of known properties in SystemInfo.
_INFO_PROP_LIST = []


def InfoProperty(f):
  """Decoration function for SystemInfo properties."""
  name = f.__name__
  if not name.startswith('_'):
    _INFO_PROP_LIST.append(name)
  @property
  def prop(self):
    # pylint: disable=protected-access
    if name in self._overrides:
      return self._overrides[name]
    if name in self._cached:
      return self._cached[name]
    value = None
    try:
      value = f(self)
    except Exception:
      pass
    self._cached[name] = value
    return value
  return prop


class SystemInfo(types.DeviceComponent):
  """Static information about the system.

  This is mostly static information that changes rarely if ever
  (e.g., version numbers, serial numbers, etc.).

  You can access the information by reading individual properties. However all
  values are cached by default unless you call Invalidate(name). Calling
  Invalidate() without giving particular name will invalidate all properties.

  To get a dictionary object of all properties, use GetAll().
  To refresh, do Invalidate() then GetAll().
  You can also "override" some properties by using Overrides(name, value).
  """

  # Virtual dev switch flag.
  _VBSD_HONOR_VIRT_DEV_SWITCH = 0x400
  _FIRMWARE_NV_INDEX = 0x1007
  _FLAG_VIRTUAL_DEV_MODE_ON = 0x02

  def __init__(self, device=None):
    super(SystemInfo, self).__init__(device)
    self._cached = {}
    self._overrides = {}

  def GetAll(self):
    """Returns all properties in a dictionary object."""
    return copy.deepcopy(
        dict((name, getattr(self, name)) for name in _INFO_PROP_LIST))

  def Invalidate(self, name=None):
    """Invalidates a property in system information object in cache.

    When name is omitted, invalidate all properties.

    Args:
      name: A string for the property to be refreshed.
    """
    if name is not None:
      self._cached.pop(name, None)
    else:
      self._cached.clear()

  def Overrides(self, name, value):
    """Overrides an information property to given value.

    This is useful for setting shared information like update_toolkit_version.

    Args:
      name: A string for the property to override.
      value: The value to return in future for given property.
    """
    self._overrides[name] = value

  @InfoProperty
  def cpu_count(self):
    """Gets number of CPUs on the machine"""
    output = self._device.CallOutput('lscpu')
    match = re.search(r'^CPU\(s\):\s*(\d+)', output, re.MULTILINE)
    return int(match.group(1)) if match else None

  @InfoProperty
  def memory_total_kb(self):
    return self._device.memory.GetTotalMemoryKB()

  @InfoProperty
  def release_image_version(self):
    """Version of the image on release partition."""
    return self._release_lsb_data['GOOGLE_RELEASE']

  @InfoProperty
  def release_image_channel(self):
    """Channel of the image on release partition."""
    return self._release_lsb_data['CHROMEOS_RELEASE_TRACK']

  def ClearSerialNumbers(self):
    """Clears any serial numbers from DeviceData."""
    return device_data.ClearAllSerialNumbers()

  def GetAllSerialNumbers(self):
    """Returns all available serial numbers in a dict."""
    return device_data.GetAllSerialNumbers()

  def GetSerialNumber(self, name=device_data.NAME_SERIAL_NUMBER):
    """Retrieves a serial number from device.

    Tries to load the serial number from DeviceData.  If not found, loads
    from DUT storage, and caches into DeviceData.
    """
    if not device_data.GetSerialNumber(name):
      serial = self._device.storage.LoadDict().get(name)
      device_data.UpdateSerialNumbers({name: serial})
    return device_data.GetSerialNumber(name)

  @InfoProperty
  def serial_number(self):
    """Device serial number (usually printed on device package)."""
    return self.GetSerialNumber()

  @InfoProperty
  def mlb_serial_number(self):
    """Motherboard serial number."""
    return self.GetSerialNumber(device_data.NAME_MLB_SERIAL_NUMBER)

  @InfoProperty
  def stage(self):
    """Manufacturing build stage. Examples: PVT, EVT, DVT."""
    # TODO(hungte) Umpire thinks this should be SMT, FATP, etc. Goofy monitor
    # simply displays this. We should figure out different terms for both and
    # find out the right way to print this value.
    return str(phase.GetPhase())

  @InfoProperty
  def test_image_version(self):
    """Version of the image on factory test partition."""
    lsb_release = self._device.ReadFile('/etc/lsb-release')
    match = re.search('^GOOGLE_RELEASE=(.+)$', lsb_release, re.MULTILINE)
    return match.group(1) if match else None

  @InfoProperty
  def factory_image_version(self):
    """Version of the image on factory test partition.

    This is same as test_image_version.
    """
    return self.test_image_version

  @InfoProperty
  def wlan0_mac(self):
    """MAC address of first wireless network device."""
    for wlan_interface in ['wlan0', 'mlan0']:
      address_path = self._device.path.join(
          '/sys/class/net/', wlan_interface, 'address')
      if self._device.path.exists(address_path):
        return self._device.ReadFile(address_path).strip()

  @InfoProperty
  def eth_macs(self):
    """MAC addresses of ethernet devices."""
    macs = dict()
    eth_paths = self._device.Glob('/sys/class/net/eth*')
    for eth_path in eth_paths:
      address_path = self._device.path.join(eth_path, 'address')
      if self._device.path.exists(address_path):
        interface = self._device.path.basename(eth_path)
        macs[interface] = self._device.ReadSpecialFile(address_path).strip()
    return macs

  @InfoProperty
  def toolkit_version(self):
    """Version of ChromeOS factory toolkit."""
    return self._device.ReadFile(paths.FACTORY_TOOLKIT_VERSION_PATH).rstrip()

  @InfoProperty
  def kernel_version(self):
    """Version of running kernel."""
    return self._device.CallOutput(['uname', '-r']).strip()

  @InfoProperty
  def architecture(self):
    """System architecture."""
    return self._device.CallOutput(['uname', '-m']).strip()

  @InfoProperty
  def root_device(self):
    """The root partition that boots current system."""
    return self._device.CallOutput(['rootdev', '-s']).strip()

  @InfoProperty
  def firmware_version(self):
    """Version of main firmware."""
    return self._device.CallOutput(['crossystem', 'fwid']).strip()

  @InfoProperty
  def ro_firmware_version(self):
    """Version of RO main firmware."""
    return self._device.CallOutput(['crossystem', 'ro_fwid']).strip()

  @InfoProperty
  def mainfw_type(self):
    """Type of main firmware."""
    return self._device.CallOutput(['crossystem', 'mainfw_type']).strip()

  @InfoProperty
  def board_version(self):
    return self._device.CallOutput(['mosys', 'platform', 'version']).strip()

  @InfoProperty
  def ec_version(self):
    """Version of embedded controller."""
    return self._device.ec.GetECVersion().strip()

  @InfoProperty
  def pd_version(self):
    return self._device.usb_c.GetPDVersion().strip()

  @InfoProperty
  def update_toolkit_version(self):
    """Indicates if an update is available on server.

    Usually set by using Overrides after checking shopfloor server.
    """
    # TODO(youcheng) Implement this in another way. Probably move this to goofy
    # state variables.
    return None

  @InfoProperty
  def _release_lsb_data(self):
    """Returns the lsb-release data in dict from release image partition."""
    release_rootfs = self._device.partitions.RELEASE_ROOTFS.path
    lsb_content = MountDeviceAndReadFile(
        release_rootfs, '/etc/lsb-release', dut=self._device)
    return dict(re.findall('^(.+)=(.+)$', lsb_content, re.MULTILINE))

  @InfoProperty
  def hwid_database_version(self):
    """Uses checksum of hwid file as hwid database version."""
    hwid_file_path = self._device.path.join(
        common.DEFAULT_HWID_DATA_PATH, common.ProbeProject().upper())
    # TODO(hungte) Support remote DUT.
    return hwid_utils.ComputeDatabaseChecksum(hwid_file_path)

  @InfoProperty
  def has_virtual_dev_switch(self):
    """Returns true if the device has virtual dev switch."""
    vdat_flags = int(self._device.CheckOutput(['crossystem', 'vdat_flags']), 16)
    return bool(vdat_flags & self._VBSD_HONOR_VIRT_DEV_SWITCH)

  @InfoProperty
  def virtual_dev_mode_on(self):
    """Returns true if the virtual dev mode is on."""

    # We use tpm_nvread to read the virtual dev mode flag stored in TPM.
    # An example output of tpm_nvread looks like:
    #
    # 00000000  02 03 01 00 01 00 00 00 00 7a
    #
    # Where the second field is the version and the third field is flag we
    # need.
    nvdata = self._device.CheckOutput(
        ['tpm_nvread', '-i', '%d' % self._FIRMWARE_NV_INDEX])
    flag = int(nvdata.split()[2], 16)
    return bool(flag & self._FLAG_VIRTUAL_DEV_MODE_ON)

  @InfoProperty
  def pci_device_number(self):
    """Returns number of PCI devices."""
    res = self._device.CheckOutput(['busybox', 'lspci'])
    return len(res.splitlines())

  @InfoProperty
  def device_id(self):
    """Returns the device ID of the device."""
    return self._device.ReadFile(testlog_goofy.DEVICE_ID_PATH).strip()


if __name__ == '__main__':
  import pprint
  from cros.factory.device import device_utils
  logging.basicConfig()
  info = SystemInfo(device_utils.CreateDUTInterface())
  pprint.pprint(info.GetAll())
