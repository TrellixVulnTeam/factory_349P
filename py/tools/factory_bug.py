#!/usr/bin/python
#
# Copyright 2012 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import argparse
from collections import namedtuple
from contextlib import contextmanager
from glob import glob
from itertools import chain
import logging
import os
import re
import shutil
import sys
import tempfile

import factory_common  # pylint: disable=unused-import
from cros.factory.test.env import paths as env_paths
from cros.factory.utils import file_utils
from cros.factory.utils.process_utils import Spawn
from cros.factory.utils import sys_utils
from cros.factory.utils import time_utils


# Info about a mounted partition.
#
# Properties:
#   dev: The device that was mounted or re-used.
#   mount_point: The mount point of the device.
#   temporary: Whether the device is being temporarily mounted.
MountUSBInfo = namedtuple('MountUSBInfo',
                          ['dev', 'mount_point', 'temporary'])


@contextmanager
def MountUSB(read_only=False):
  """Mounts (or re-uses) a USB drive, returning the path.

  Acts as a context manager.  If we mount a partition, we will
  unmount it when exiting the context manager.

  First attempts to find a mounted USB drive; if one is found,
  its path is returned (and it will never be unmounted).

  Next attempts to mount partitions 1-9 on any USB drive.
  If this succeeds, the path is returned, and it will be unmounted
  when exiting the context manager.

  Returns:
    A MountUSBInfo object.

  Raises:
    IOError if no mounted or mountable partition is found.
  """
  usb_devices = set(os.path.basename(x)
                    for x in glob('/sys/class/block/sd?')
                    if '/usb' in os.readlink(x))
  if not usb_devices:
    raise IOError('No USB devices available')

  # See if any are already mounted
  mount_output = Spawn(['mount'], read_stdout=True,
                       check_call=True, log=True).stdout_data
  matches = [x for x in re.findall(r'^(/dev/(sd[a-z])\d*) on (\S+)',
                                   mount_output, re.MULTILINE)
             if x[1] in usb_devices]
  if matches:
    dev, _, path = matches[0]
    # Already mounted: yield it and we're done
    logging.info('Using mounted USB drive %s on %s', dev, path)
    yield MountUSBInfo(dev=dev, mount_point=path, temporary=False)

    # Just to be on the safe side, sync once the caller says they're
    # done with it.
    Spawn(['sync'], call=True)
    return

  # Try to mount it (and unmount it later).  We'll try the whole
  # drive first, then each individual partition
  tried = []
  for usb_device in usb_devices:
    for suffix in [''] + [str(x) for x in xrange(1, 10)]:
      mount_dir = tempfile.mkdtemp(
          prefix='usb_mount.%s%s.' % (usb_device, suffix))
      dev = '/dev/%s%s' % (usb_device, suffix)
      tried.append(dev)
      try:
        if Spawn(['mount'] +
                 (['-o', 'ro'] if read_only else []) +
                 [dev, mount_dir],
                 ignore_stdout=True, ignore_stderr=True,
                 call=True).returncode == 0:
          # Success
          logging.info('Mounted %s on %s', dev, mount_dir)
          yield MountUSBInfo(dev=dev, mount_point=mount_dir, temporary=True)
          return
      finally:
        # Always try to unmount, even if we think the mount
        # failed.
        if Spawn(['umount', '-l', mount_dir],
                 ignore_stdout=True, ignore_stderr=True,
                 call=True).returncode == 0:
          logging.info('Unmounted %s', dev)
        try:
          os.rmdir(mount_dir)
        except OSError:
          logging.exception('Unable to remove %s', mount_dir)

  # Oh well
  raise IOError('Unable to mount any of %s' % tried)


@contextmanager
def DummyContext(arg):
  """A context manager that simply yields its argument."""
  yield arg


def SaveLogs(output_dir, include_network_log=False, archive_id=None,
             var='/var', usr_local='/usr/local', etc='/etc'):
  """Saves dmesg and relevant log files to a new archive in output_dir.

  The archive will be named factory_bug.<description>.<timestamp>.tar.bz2,
  where description is the 'description' argument (if provided).

  Args:
    output_dir: The directory in which to create the file.
    include_network_log: Whether to include network related logs or not.
    archive_id: An optional short ID to put in the filename (so
      archives may be more easily differentiated).
    var, usr_local, etc: Paths to the relavant directories.
  """
  output_dir = os.path.realpath(output_dir)
  files = []

  filename = 'factory_bug.'
  if archive_id:
    filename += archive_id.replace('/', '') + '.'
  filename += '%s.tar.bz2' % time_utils.TimeString(time_separator='_',
                                                   milliseconds=False)

  output_file = os.path.join(output_dir, filename)

  if sys_utils.InChroot():
    # Just save a dummy tarball.
    with file_utils.TempDirectory() as d:
      open(os.path.join(os.path.join(d, 'dummy-factory-bug')), 'w').close()
      Spawn(['tar', 'cfj', output_file, '-C', d, 'dummy-factory-bug'],
            check_call=True)
    return output_file

  tmp = tempfile.mkdtemp(prefix='factory_bug.')

  # SuperIO-based platform has no EC chip, check its existence first.
  has_ec = sys_utils.HasEC()

  try:
    with open(os.path.join(tmp, 'crossystem'), 'w') as f:
      Spawn('crossystem', stdout=f, stderr=f, check_call=True)
      if has_ec:
        print >> f, '\nectool version:'
        f.flush()
        Spawn(['ectool', 'version'], stdout=f, check_call=True)

    with open(os.path.join(tmp, 'dmesg'), 'w') as f:
      Spawn('dmesg', stdout=f, check_call=True)

    with open(os.path.join(tmp, 'mosys_eventlog'), 'w') as f:
      Spawn(['mosys', 'eventlog', 'list'],
            stdout=f, stderr=f, call=True)

    if has_ec:
      with open(os.path.join(tmp, 'ec_console'), 'w') as f:
        Spawn(['ectool', 'console'],
              stdout=f, stderr=f, call=True)
      files += ['ec_console']

    files += ['crossystem', 'dmesg', 'mosys_eventlog'] + sum(
        [glob(x) for x in [
            os.path.join(var, 'log'),
            os.path.join(var, 'factory'),
            os.path.join(var, 'spool', 'crash'),
            os.path.join(usr_local, 'factory', 'MD5SUM'),
            os.path.join(usr_local, 'factory', 'hwid'),
            os.path.join(etc, 'lsb-release'),
            os.path.join(usr_local, 'etc', 'lsb-*'),
            # These are hardcoded paths because they are virtual
            # filesystems; the data we want is always in /dev and
            # /sys, never on the SSD.
            '/dev/pstore',
            '/sys/firmware/log',
        ]], [])

    # Name of Chrome data directory within the state directory.
    chrome_data_dir_name = 'chrome-data-dir'

    # Exclude various items from bug reports.
    exclude_files = list(chain.from_iterable(('--exclude', x) for x in [
        os.path.join(env_paths.DATA_STATE_DIR, chrome_data_dir_name),
        'Extensions',
    ]))
    if not include_network_log:
      exclude_files += ['--exclude', os.path.join(var, 'log', 'net.log')]

    file_utils.TryMakeDirs(os.path.dirname(output_file))
    logging.info('Saving %s to %s...', files, output_file)
    process = Spawn(['tar', 'cfj', output_file] + exclude_files + files,
                    cwd=tmp, call=True,
                    ignore_stdout=True,
                    read_stderr=True)
    # 0 = successful termination
    # 1 = non-fatal errors like "some files differ"
    if process.returncode not in [0, 1]:
      logging.error('tar stderr:\n%s', process.stderr_data)
      raise IOError('tar process failed with returncode %d' %
                    process.returncode)

    return output_file
  finally:
    shutil.rmtree(tmp, ignore_errors=True)


# Root directory to use when root partition is USB
USB_ROOT_OUTPUT_DIR = '/mnt/stateful_partition/factory_bug'

# Encrypted var partition mount point.
SSD_STATEFUL_ROOT = '/tmp/sda1'

# Stateful partition mount point
SSD_STATEFUL_MOUNT_POINT = os.path.join(SSD_STATEFUL_ROOT,
                                        'mnt/stateful_partition')

EXAMPLES = """Examples:

  When booting from SSD:

    # Save logs to /tmp
    factory_bug

    # Save logs to a USB drive (using the first one already mounted, or the
    # first mountable on any USB device if none is mounted yet)
    factory_bug --usb

  When booting from a USB drive:

    # Mount sda1, sda3, encrypted stateful partition from SSD,
    # and save logs to the USB drive's stateful partition
    factory_bug

    # Same as above, but don't save the logs
    factory_bug --mount

"""


def main():
  logging.basicConfig(level=logging.INFO)

  # First parse mtab, since that will affect some of our defaults.
  root_is_usb = False
  have_ssd_stateful = False
  mounted_sda1 = None
  mounted_sda3 = None
  for line in open('/etc/mtab'):
    dev, mount_point = line.split()[0:2]
    if ((mount_point == '/mnt/stateful_partition') and
        '/usb' in os.readlink(os.path.join('/sys/class/block',
                                           os.path.basename(dev)))):
      root_is_usb = True
    elif mount_point == os.path.join(SSD_STATEFUL_ROOT, 'var'):
      have_ssd_stateful = True
    elif dev == '/dev/sda1':
      mounted_sda1 = mount_point
    elif dev == '/dev/sda3':
      mounted_sda3 = mount_point

  parser = argparse.ArgumentParser(
      description=('Save logs to a file or USB drive '
                   'and/or mount encrypted SSD partition.'),
      epilog=EXAMPLES,
      formatter_class=argparse.RawDescriptionHelpFormatter)
  parser.add_argument('--output_dir', '-o', dest='output_dir', metavar='DIR',
                      default=(USB_ROOT_OUTPUT_DIR if root_is_usb else '/tmp'),
                      help=('output directory in which to save file. Normally '
                            'default to /tmp, but defaults to ' +
                            USB_ROOT_OUTPUT_DIR + ' when booted '
                            'from USB'))
  parser.add_argument('--mount', action='store_true',
                      help=('when booted from USD, only '
                            "mount encrypted SSD and exit (don't save logs)"))
  parser.add_argument('--usb', action='store_true',
                      help=('save logs to a USB stick (using any mounted '
                            'USB drive partition if available, otherwise '
                            'attempting to temporarily mount one)'))
  parser.add_argument('--net', action='store_true',
                      help=('whether to include network related logs or not. '
                            'Network logs are excluded by default.'))
  parser.add_argument('--id', '-i', metavar='ID',
                      help=('short ID to include in file name to help '
                            'differentiate archives'))
  args = parser.parse_args()

  paths = {}

  if root_is_usb:
    logging.warn('Root partition is a USB drive')
    if not os.path.exists('/dev/sda1'):
      # TODO(jsalz): Make this work on ARM too.
      logging.error('/dev/sda1 does not exist; cannot mount SSD')
      sys.exit(1)
    logging.warn('Saving report to the %s directory', USB_ROOT_OUTPUT_DIR)
    args.usb = False

    def Mount(device, mount_point=None, options=None):
      dev = os.path.join('/dev', device)
      mount_point = mount_point or os.path.join('/tmp', device)

      file_utils.TryMakeDirs(mount_point)
      Spawn(['mount'] + (options or []) + [dev, mount_point],
            log=True, check_call=True)
      return mount_point

    if not have_ssd_stateful:
      if not mounted_sda1:
        file_utils.TryMakeDirs(SSD_STATEFUL_MOUNT_POINT)
        Mount('/dev/sda1', SSD_STATEFUL_MOUNT_POINT)
        mounted_sda1 = SSD_STATEFUL_MOUNT_POINT
      elif mounted_sda1 != SSD_STATEFUL_MOUNT_POINT:
        parser.error('Works only when sda1 is mounted at %s (not %s)' % (
            SSD_STATEFUL_MOUNT_POINT, mounted_sda1))

      new_env = dict(os.environ)
      new_env['MOUNT_ENCRYPTED_ROOT'] = SSD_STATEFUL_ROOT
      for d in ['var', 'home/chronos']:
        file_utils.TryMakeDirs(os.path.join(SSD_STATEFUL_ROOT, d))
      Spawn(['mount-encrypted', 'factory'], env=new_env, log=True,
            check_call=True)

    # Use ext2 to make sure that we don't accidentally use ext4 (which
    # may write to the partition even in read-only mode)
    mounted_sda3 = mounted_sda3 or Mount(
        'sda3', '/tmp/sda3',
        ['-o', 'ro', '-t', 'ext2'])

    paths = dict(var=os.path.join(SSD_STATEFUL_ROOT, 'var'),
                 usr_local=os.path.join(mounted_sda1, 'dev_image'),
                 etc=os.path.join(mounted_sda3, 'etc'))
  elif args.mount:
    parser.error('--mount only applies when root device is USB')

  # When --mount is specified, we only mount and don't actually
  # collect logs.
  if not args.mount:
    with (MountUSB() if args.usb else
          DummyContext(MountUSBInfo(None, args.output_dir, False))) as mount:
      output_file = SaveLogs(mount.mount_point, args.net, args.id, **paths)
      logging.info('Wrote %s (%d bytes)',
                   output_file, os.path.getsize(output_file))

  if root_is_usb:
    logging.info('SSD remains mounted:')
    logging.info(' - sda3 = %s', mounted_sda3)
    logging.info(' - encrypted stateful partition = %s', SSD_STATEFUL_ROOT)

if __name__ == '__main__':
  main()
