#!/usr/bin/python
#
# Copyright (c) 2012 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.


import argparse
import glob
import logging
import os
import pipes
import re
import shutil
import subprocess
import sys
import time
import urlparse
import yaml

import factory_common  # pylint: disable=W0611
from cros.factory.test import utils
from cros.factory.tools.make_update_bundle import MakeUpdateBundle
from cros.factory.tools.mount_partition import MountPartition
from cros.factory.utils.file_utils import UnopenedTemporaryFile
from cros.factory.utils.process_utils import Spawn


GSUTIL_CACHE_DIR = os.path.join(os.environ['HOME'], 'gsutil_cache')

REQUIRED_GSUTIL_VERSION = [3, 18]  # 3.18


def CheckDictHasOnlyKeys(dict_to_check, keys):
  """Makes sure that a dictionary's keys are valid.

  Args:
    dict_to_check: A dictionary.
    keys: The set of allowed keys in the dictionary.
  """
  if not isinstance(dict_to_check, dict):
    raise TypeError('Expected dict but found %s' % type(dict_to_check))

  extra_keys = set(dict_to_check) - set(keys)
  if extra_keys:
    raise ValueError('Found extra keys: %s' % list(extra_keys))


def GSDownload(url):
  """Downloads a file from Google storage, returning the path to the file.

  Downloads are cached in GSUTIL_CACHE_DIR.

  Args:
    url: URL to download.

  Returns:
    Path to the downloaded file.  The returned path may have an arbitrary
    filename.
  """
  utils.TryMakeDirs(os.path.dirname(GSUTIL_CACHE_DIR))

  cached_path = os.path.join(GSUTIL_CACHE_DIR, url.replace('/', '!'))
  if os.path.exists(cached_path):
    logging.info('Using cached %s (%.1f MiB)',
                 url, os.path.getsize(cached_path) / (1024.*1024.))
    return cached_path

  in_progress_path = cached_path + '.INPROGRESS'
  Spawn(['gsutil', '-m', 'cp', url, 'file://' + in_progress_path],
        check_call=True, log=True)
  shutil.move(in_progress_path, cached_path)
  return cached_path


def GetReleaseVersion(mount_point):
  """Returns the release version of an image mounted at mount_point."""
  match = re.search(
      '^CHROMEOS_RELEASE_VERSION=(.+)$',
      open(os.path.join(mount_point, 'etc', 'lsb-release')).read(),
      re.MULTILINE)
  if not match:
    sys.exit('Unable to read lsb-release from %s' % mount_point)
  return match.group(1)


def GetFirmwareVersions(updater):
  """Returns the firmware versions in an updater.

  Args:
    updater: Path to a firmware updater.

  Returns:
    A tuple (bios_version, ec_version)
  """
  stdout = Spawn(
      [updater, '-V'], log=True, check_output=True).stdout_data

  versions = []
  for label in ['BIOS version', 'EC version']:
    match = re.search(
        '^' + label + ':\s+(.+)$', stdout, re.MULTILINE)
    if not match:
      sys.exit(
        'Unable to read %s from chromeos-firmwareupdater output %r' % (
            label, stdout))
    versions.append(match.group(1))
  return tuple(versions)


USAGE = """
Finalizes a factory bundle.  This script checks to make sure that the
bundle is valid, outputs version information into the README file, and
tars up the bundle.

The bundle directory (the DIR argument) must have a MANIFEST.yaml file
like the following:

  board: link
  self.bundle_name: 20121115_pvt
  mini_omaha_ip: 192.168.4.1
  # Files to download and add to the bundle.
  add_files:
  - install_into: release
    source: "gs://.../chromeos_recovery_image.bin"
  - install_into: firmware
    extract_files: [ec.bin, nv_image-link.bin]
    source: 'gs://.../ChromeOS-firmware-...tar.bz2'
  # Files to delete if present.
  delete_files:
  - install_shim/factory_install_shim.bin
  # Files that are expected to be in the bundle.
  files:
  - MANIFEST.yaml  # This file!
  - README
  - ...

The bundle must be in a directory named
factory_bundle_${board}_${self.bundle_name} (where board and self.bundle_name
are the same as above).
"""


class FinalizeBundle(object):
  """Finalizes a factory bundle (see USAGE).

  Properties:
    args: Command-line arguments from argparse.
    bundle_dir: Path to the bundle directory.
    bundle_name: Name of the bundle (e.g., 20121115_proto).
    factory_image_path: Path to the factory image in the bundle.
    board: Board name (e.g., link).
    simple_board: For board name like "base_variant", simple_board is "variant".
      simple_board == board if board is not a variant board.
      This name is used in firmware and hwid.
    manifest: Parsed YAML manifest.
    expected_files: List of files expected to be in the bundle (relative paths).
    all_files: Set of files actually present in the bundle (relative paths).
    readme_path: Path to the README file within the bundle.
    factory_image_base_version: Build of the factory image (e.g., 3004.100.0)
    release_image_path: Path to the release image.
    mini_omaha_script_path: Path to the script used to start the mini-Omaha
      server.
  """
  args = None
  bundle_dir = None
  bundle_name = None
  factory_image_path = None
  board = None
  simple_board = None
  manifest = None
  expected_files = None
  all_files = None
  readme_path = None
  factory_image_base_version = None
  release_image_path = None
  mini_omaha_script_path = None

  def Main(self):
    if not utils.in_chroot():
      sys.exit('Please run this script from within the chroot.')

    self.ParseArgs()
    self.LoadManifest()
    self.Download()
    self.DeleteFiles()
    self.UpdateMiniOmahaURL()
    self.ModifyFactoryImage()
    self.MakeUpdateBundle()
    self.MakeFactoryPackages()
    self.FixFactoryParSymlinks()
    self.CheckFiles()
    self.UpdateReadme()
    self.Archive()

  def ParseArgs(self):
    parser = argparse.ArgumentParser(
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=USAGE)
    parser.add_argument(
        '--no-download', dest='download', action='store_false',
        help="Don't download files from Google Storage (for testing only)")
    parser.add_argument(
        '--no-updater', dest='updater', action='store_false',
        help="Don't make an update bundle (for testing only)")
    parser.add_argument(
        '--no-archive', dest='archive', action='store_false',
        help="Don't make a tarball (for testing only)")
    parser.add_argument(
        '--no-make-factory-packages', dest='make_factory_package',
        action='store_false',
        help="Don't call make_factory_package (for testing only)")
    parser.add_argument(
        'dir', metavar='DIR',
        help="Directory containing the bundle")
    self.args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    self.bundle_dir = os.path.realpath(self.args.dir)

  def LoadManifest(self):
    self.manifest = yaml.load(open(
        os.path.join(self.args.dir, 'MANIFEST.yaml')))
    CheckDictHasOnlyKeys(
        self.manifest, ['board', 'bundle_name', 'add_files', 'delete_files',
                        'add_files_to_image', 'site_tests',
                        'files', 'mini_omaha_url'])

    self.board = self.manifest['board']
    self.simple_board = self.board.split('_')[-1]

    self.bundle_name = self.manifest['bundle_name']
    if not re.match(r'^\d{8}_', self.bundle_name):
      sys.exit("The self.bundle_name (currently %r) should be today's date, "
               "plus an underscore, plus a description of the build, e.g.: %r" %
               (self.bundle_name, time.strftime("%Y%m%d_proto")))

    expected_dir_name = 'factory_bundle_' + self.board + '_' + self.bundle_name
    if expected_dir_name != os.path.basename(self.bundle_dir):
      sys.exit(
        'bundle_name in manifest is %s, so directory name should be %s, '
        'but it is %s' % (
            self.bundle_name, expected_dir_name,
            os.path.basename(self.bundle_dir)))

    self.expected_files = set(map(self._SubstVars, self.manifest['files']))
    self.factory_image_path = os.path.join(
        self.bundle_dir, 'factory_test', 'chromiumos_factory_image.bin')
    with MountPartition(self.factory_image_path, 3) as mount:
      self.factory_image_base_version = GetReleaseVersion(mount)
    self.readme_path = os.path.join(self.bundle_dir, 'README')

  def CheckGSUtilVersion(self):
    # Check for gsutil >= 3.18.
    process = Spawn(['gsutil', 'version'],
                    read_stderr=True, read_stdout=True)
    if ("No such file or directory: '/usr/lib64/gsutil/CHECKSUM'" in
        process.stderr_data):
      # Sigh... workaround install bug
      version = open('/usr/lib/gsutil/VERSION').read()
    else:
      match = re.search('^gsutil version (.+)', process.stderr_data,
                        re.MULTILINE)
      assert match, ('Unable to parse "gsutil version" output: %r' %
                     process.stderr_data)
      version = match.group(1)

    version_split = [int(x) for x in version.split('.')]
    if version_split < REQUIRED_GSUTIL_VERSION:
      sys.exit(
          'gsutil version >=%s is required; you seem to have %s.\n'
          'Please download and install gsutil ('
          'https://developers.google.com/storage/docs/gsutil_install), and '
          'make sure this is in your PATH before the system gsutil.'  % (
              '.'.join(str(x) for x in REQUIRED_GSUTIL_VERSION), version))

  def Download(self):
    # Make sure gsutil is up to date; older versions are pretty broken.
    self.CheckGSUtilVersion()

    for f in self.manifest['add_files']:
      CheckDictHasOnlyKeys(f, ['install_into', 'source', 'extract_files'])
      dest_dir = os.path.join(self.bundle_dir, f['install_into'])
      utils.TryMakeDirs(dest_dir)

      source = self._SubstVars(f['source'])

      if self.args.download:
        cached_file = GSDownload(source)

      if f.get('extract_files'):
        install_into = os.path.join(self.bundle_dir, f['install_into'])
        if self.args.download:
          if cached_file.endswith('.zip'):
            Spawn(['unzip', '-o', cached_file,
                   '-d', install_into] +
                  f['extract_files'],
                  log=True, check_call=True)
          else:
            Spawn(['tar', '-xvvf', cached_file,
                   '-C', install_into] +
                  f['extract_files'],
                  log=True, check_call=True)
        for f in f['extract_files']:
          self.expected_files.add(os.path.relpath(os.path.join(install_into, f),
                                             self.bundle_dir))
      else:
        dest_path = os.path.join(dest_dir, os.path.basename(source))
        if self.args.download:
          shutil.copyfile(cached_file, dest_path)
        self.expected_files.add(os.path.relpath(dest_path, self.bundle_dir))

  def DeleteFiles(self):
    for f in self.manifest['delete_files']:
      path = os.path.join(self.bundle_dir, f)
      if os.path.exists(path):
        os.unlink(path)

  def ModifyFactoryImage(self):
    add_files_to_image = self.manifest.get('add_files_to_image', [])
    if add_files_to_image:
      with MountPartition(self.factory_image_path, 1, rw=True) as mount:
        for f in add_files_to_image:
          dest_dir = os.path.join(mount, 'dev_image', f['install_into'])
          Spawn(['mkdir', '-p', dest_dir], log=True, sudo=True, check_call=True)
          Spawn(['cp', '-a', os.path.join(self.bundle_dir, f['source']),
                 dest_dir], log=True, sudo=True, check_call=True)

    # Removes unused site_tests
    # suite_Factory must be preserved for /usr/local/factory/custom symlink.
    site_tests = self.manifest.get('site_tests', []) + ['suite_Factory']
    with MountPartition(self.factory_image_path, 1, rw=True) as mount:
      site_tests_dir = os.path.join(mount, 'dev_image', 'autotest',
                                    'site_tests')
      for name in os.listdir(site_tests_dir):
        path = os.path.join(site_tests_dir, name)
        if name not in site_tests:
          Spawn(['rm', '-rf', path], log=True, sudo=True, check_call=True)

  def MakeUpdateBundle(self):
    # Make the factory update bundle
    if self.args.updater:
      updater_path = os.path.join(
          self.bundle_dir, 'shopfloor', 'shopfloor_data', 'update',
          'factory.tar.bz2')
      utils.TryMakeDirs(os.path.dirname(updater_path))
      MakeUpdateBundle(self.factory_image_path, updater_path)

  def UpdateMiniOmahaURL(self):
    mini_omaha_url = self.manifest.get('mini_omaha_url')
    if not mini_omaha_url:
      return

    def PatchLSBFactory(mount):
      """Patches lsb-factory in an image.

      Returns:
        True if there were any changes.
      """
      lsb_factory_path = os.path.join(
          mount, 'dev_image', 'etc', 'lsb-factory')
      logging.info('Patching URLs in %s', lsb_factory_path)
      orig_lsb_factory = open(lsb_factory_path).read()
      lsb_factory, number_of_subs = re.subn(
          '(?m)^(CHROMEOS_(AU|DEV)SERVER=).+$', r'\1' + mini_omaha_url,
          orig_lsb_factory)
      if number_of_subs != 2:
        sys.exit('Unable to set mini-Omaha server in %s' % lsb_factory_path)
      if lsb_factory == orig_lsb_factory:
        return False  # No changes

      # Write with sudo, since only root can write this.
      process = Spawn('cat > %s' % pipes.quote(lsb_factory_path),
                      sudo=True, stdin=subprocess.PIPE, shell=True)
      process.stdin.write(lsb_factory)
      process.stdin.close()
      if process.wait():
        sys.exit('Unable to write %s' % lsb_factory_path)
      return True

    # Patch in the install shim, if present.
    shims = glob.glob(os.path.join(self.bundle_dir, 'factory_shim',
                                   'chromeos_*_factory*.bin'))
    if len(shims) > 1:
      sys.exit('Expected to find 1 shim but found %d' % len(shims))
    elif len(shims) == 1:
      with MountPartition(shims[0], 1, rw=True) as mount:
        PatchLSBFactory(mount)
    else:
      logging.warning('There is no install shim in the bundle.')

    # Take care of the netboot initrd as well, if present.
    netboot_image = os.path.join(self.bundle_dir, 'factory_shim',
                                 'netboot', 'initrd.uimg')
    if os.path.exists(netboot_image):
      with UnopenedTemporaryFile(prefix='rootfs.') as rootfs:
        with open(netboot_image) as netboot_image_in:
          with open(rootfs, 'w') as rootfs_out:
            logging.info('Unpacking initrd rootfs')
            netboot_image_in.seek(64)
            Spawn(
                ['gunzip', '-c'],
                stdin=netboot_image_in, stdout=rootfs_out, check_call=True)
        with MountPartition(rootfs, rw=True) as mount:
          lsb_factory_changed = PatchLSBFactory(
              os.path.join(mount, 'mnt', 'stateful_partition'))

        if lsb_factory_changed:
          # Success!  Zip it back up.
          with UnopenedTemporaryFile(prefix='rootfs.') as rootfs_gz:
            with open(rootfs_gz, 'w') as out:
              Spawn(['pigz', '-9c', rootfs], stdout=out, log=True, call=True)

            new_netboot_image = netboot_image + '.INPROGRESS'
            Spawn(['mkimage', '-A', 'x86', '-O', 'linux', '-T', 'ramdisk',
                   '-a', '0x12008000', '-n', 'Factory Install RootFS',
                   '-C', 'gzip', '-d', rootfs_gz, new_netboot_image],
                  check_call=True, log=True)
            shutil.move(new_netboot_image, netboot_image)

    # Take care of netboot firmware, if present.
    netboot_firmware_image = os.path.join(self.bundle_dir, 'netboot_firmware',
        'nv_image-%s.bin' % self.simple_board)
    if os.path.exists(netboot_firmware_image):
      update_firmware_vars = os.path.join(self.bundle_dir, 'factory_setup',
                                         'update_firmware_vars.py')
      new_netboot_firmware_image = netboot_firmware_image + '.INPROGRESS'
      Spawn([update_firmware_vars,
             '--force',
             '-i', netboot_firmware_image,
             '-o', new_netboot_firmware_image,
             '--omahaserver=%s' % mini_omaha_url,
             '--tftpserverip=%s' % urlparse.urlparse(mini_omaha_url).hostname],
             check_call=True, log=True)
      shutil.move(new_netboot_firmware_image, netboot_firmware_image)

  def MakeFactoryPackages(self):
    release_images = glob.glob(os.path.join(self.bundle_dir, 'release/*.bin'))
    if len(release_images) != 1:
      sys.exit("Expected one release image but found %d" % len(release_images))
    self.release_image_path = release_images[0]

    factory_setup_dir = os.path.join(self.bundle_dir, 'factory_setup')
    make_factory_package = [
        './make_factory_package.sh',
        '--board', self.board,
        '--complete_script', 'complete_script.sh',
        '--release', os.path.relpath(self.release_image_path,
                                     factory_setup_dir),
        '--factory', '../factory_test/chromiumos_factory_image.bin',
        '--hwid_updater', '../hwid/hwid_v3_bundle_%s.sh' %
                          self.simple_board.upper()]

    firmware_updater = os.path.join(
        self.bundle_dir, 'firmware', 'chromeos-firmwareupdate')
    if os.path.exists(firmware_updater):
      make_factory_package += [
          '--firmware_updater', os.path.relpath(
              firmware_updater, factory_setup_dir)]

    if self.args.make_factory_package:
      Spawn(make_factory_package, cwd=factory_setup_dir,
            check_call=True, log=True)

    # Build the mini-Omaha startup script.
    self.mini_omaha_script_path = os.path.join(
        self.bundle_dir, 'start_download_server.sh')
    if os.path.exists(self.mini_omaha_script_path):
      os.unlink(self.mini_omaha_script_path)
    with open(self.mini_omaha_script_path, 'w') as f:
      f.write('\n'.join([
          '#!/bin/bash',
          'set -e',  # Fail on error
          'cd $(dirname $(readlink -f "$0"))/factory_setup',
          'cat miniomaha.conf',
          'echo Miniomaha configuration MD5SUM: $(md5sum miniomaha.conf)',
          'echo Validating configuration...',
          ('python miniomaha.py --validate_factory_config'),
          'echo Starting download server.',
          'python miniomaha.py',
          ''  # Add newline at EOF
          ]))
      os.fchmod(f.fileno(), 0555)

  def FixFactoryParSymlinks(self):
    """Fix symlinks to factory.par.

    These may have been turning into real files by the buildbots.
    """
    factory_par_path = os.path.join(self.bundle_dir,
                                    'shopfloor', 'factory.par')
    with open(factory_par_path) as f:
      factory_par_data = f.read()

    # Look for files that are identical copies of factory.par.
    for root, dummy_dirs, files in os.walk(self.bundle_dir):
      for f in files:
        path = os.path.join(root, f)
        if path == factory_par_path:
          # Don't replace it with itself!
          continue
        if (os.path.islink(path) or
            os.path.getsize(path) != len(factory_par_data)):
          # It's not a real file, or not the right size.  Skip.
          continue
        with open(path) as fobj:
          data = fobj.read()
        if data != factory_par_data:
          # Data isn't the same.  Skip.
          continue

        # Replace the file with a symlink.
        logging.info('Replacing %s with a symlink', path)
        os.unlink(path)
        os.symlink(os.path.relpath(factory_par_path,
                                   os.path.dirname(path)),
                   path)

  def CheckFiles(self):
    # Check that the set of files is correct
    self.all_files = set()
    for root, dirs, files in os.walk(self.bundle_dir):
      for f in files:
        # Remove backup files and compiled Python files.
        if f.endswith('~') or f.endswith('.pyc'):
          os.unlink(os.path.join(root, f))
          continue
        self.all_files.add(
            os.path.relpath(os.path.join(root, f), self.bundle_dir))
      for d in dirs:
        # Remove any empty directories
        try:
          os.rmdir(d)
        except OSError:
          pass

    missing_files = self.expected_files - self.all_files
    extra_files = self.all_files - self.expected_files
    if missing_files:
      logging.error('Missing files in bundle: %s',
                    ' '.join(sorted(missing_files)))
      logging.error("If the files really shouldn't be there, remove them from "
                    'the "files" section in MANIFEST.yaml')
    if extra_files:
      logging.error('Unexpected extra files in bundle: %s',
                    ' '.join(sorted(extra_files)))
      logging.error('If the files are really expected, '
                    'add them to the "files" section of MANIFEST.yaml')
    if missing_files or extra_files:
      sys.exit('Incorrect file set; terminating')

  def UpdateReadme(self):
    # Grok the README file; we'll be modifying it.
    readme_sections = re.findall(
        # Section header
        r'(\*\*\*\n\*\n\* (.+?)\n\*\n\*\*\*\n)'
        # Anything up to (but not including) the next section header
        r'((?:(?!\*\*\*).)+)', open(self.readme_path).read(), re.DOTALL)
    # This results in a list of tuples (a, b, c), where a is the whole
    # section header string; b is the name of the section; and c is the
    # contents of the section.  Turn each tuple into a list; we'll be
    # modifying some of them.
    readme_sections = [list(x) for x in readme_sections]

    readme_section_index = {}  # Map of section name to index
    for i, s in enumerate(readme_sections):
      readme_section_index[s[1]] = i
    for k in ['VITAL INFORMATION', 'CHANGES']:
      if k not in readme_section_index:
        sys.exit("README is missing %s section" % k)

    # Make sure that the CHANGES section contains this version.
    expected_str = '%s changes:' % self.bundle_name
    if expected_str not in readme_sections[readme_section_index['CHANGES']][2]:
      sys.exit('The string %r was not found in the CHANGES section. '
               'Please add a section for it (if this is the first '
               'version, just say "initial release").' % expected_str)

    # Get some vital information
    vitals = [
        ('Board', self.board),
        ('Bundle', '%s (created by %s, %s)' % (
            self.bundle_name, os.environ['USER'],
            time.strftime('%a %Y-%m-%d %H:%M:%S %z')))]
    vitals.append(('Factory image base', self.factory_image_base_version))
    with MountPartition(self.factory_image_path, 1) as f:
      vitals.append(('Factory updater MD5SUM', open(
          os.path.join(f, 'dev_image/factory/MD5SUM')).read().strip()))
    with MountPartition(self.release_image_path, 3) as f:
      vitals.append(('Release (FSI)', GetReleaseVersion(f)))
      bios_version, ec_version = GetFirmwareVersions(
          os.path.join(f, 'usr/sbin/chromeos-firmwareupdate'))
      vitals.append(('Release (FSI) BIOS', bios_version))
      vitals.append(('Release (FSI) EC', ec_version))

    # If we have any firmware in the tree, add them to the vitals.
    firmwareupdates = []
    for f in self.all_files:
      path = os.path.join(self.bundle_dir, f)
      if os.path.basename(f) == 'chromeos-firmwareupdate':
        firmwareupdates.append(path)
        bios_version, ec_version = GetFirmwareVersions(path)
        vitals.append(('%s BIOS' % f, bios_version))
        vitals.append(('%s EC' % f, ec_version))
      elif os.path.basename(f) == 'ec.bin':
        # This is tricky, but it's the best we can do for now.  Look for a
        # line like "link_v1.2.34-56789a 2012-10-01 12:34:56 @build70-m2"
        strings = Spawn(['strings', path], check_output=True).stdout_data
        match = re.search('^(' + self.simple_board + '.+@.+)$',
                          strings, re.MULTILINE)
        if not match:
          sys.exit('Unable to find EC version in %s' % path)
        vitals.append((f, match.group(1)))
      elif os.path.basename(f).startswith('nv_image'):
        strings = Spawn(['strings', path], check_output=True).stdout_data
        match = re.search('^(Google_' + self.simple_board +
                          r'\.\d+\.\d+\.\d+)$',
                          strings, re.MULTILINE | re.IGNORECASE)
        if not match:
          sys.exit('Unable to find BIOS version in %s' % path)
        vitals.append((f, match.group(1)))

    vital_lines = []
    max_key_length = max(len(k) for k, v in vitals)
    for k, v in vitals:
      vital_lines.append("%s:%s %s" % (k, ' ' * (max_key_length - len(k)), v))
    vital_contents = '\n'.join(vital_lines)
    readme_sections[readme_section_index['VITAL INFORMATION']][2] = (
        vital_contents + '\n\n')

    index = readme_section_index.get('MINI-OMAHA SERVER')
    if index is not None:
      instructions = [
          'To start a mini-Omaha server:',
          '',
          '  ./start_download_server.sh'
          ]
      readme_sections[index][2] = (
          '\n'.join(instructions) + '\n\n')

    with open(self.readme_path, 'w') as f:
      for header, _, contents in readme_sections:
        f.write(header)
        f.write(contents)
    logging.info('\n\nUpdated %s; vital information:\n%s\n',
                 self.readme_path, vital_contents)

  def Archive(self):
    if self.args.archive:
      # Done! tar it up, and encourage the poor shmuck who has to build
      # the bundle to take a little break.
      logging.info('Just works! Creating the tarball. '
                   'This will take a while... meanwhile, go get %s. '
                   'You deserve it.',
                   (['some rest'] * 5 +
                    ['a cup of coffee'] * 7 +
                    ['some lunch', 'some fruit'] +
                    ['an afternoon snack'] * 2 +
                    ['a beer'] * 8)[time.localtime().tm_hour])

      for mini in [True, False]:
        output_file = self.bundle_dir + ('.mini' if mini else '') + '.tar.bz2'
        Spawn(['tar', '-cf', output_file,
               '-I', 'pbzip2',
               '-C', os.path.dirname(self.bundle_dir)] +
              (['--exclude', '*.bin', '--exclude', '*.uimg'] if mini else []) +
              [os.path.basename(self.bundle_dir)],
              log=True, check_call=True)
        logging.info(
            'Created %s (%.1f GiB).',
            output_file, os.path.getsize(output_file) / (1024.*1024.*1024.))

    logging.info('The README file (%s) has been updated.  Make sure to check '
                 'that it is correct!', self.readme_path)
    logging.info(
        "IMPORTANT: If you modified the README or MANIFEST.yaml, don't forget "
        "to check your changes into %s.",
        os.path.join(os.environ['CROS_WORKON_SRCROOT'],
                     'src', 'private-overlays', 'overlay-link-private',
                     'chromeos-base', 'chromeos-factory-board',
                     'files', 'bundle'))

  def _SubstVars(self, input_str):
    """Substitutes variables into a string.

    The following substitutions are made:
      ${BOARD} -> the simple board name (in uppercase)
      ${FACTORY_IMAGE_BASE_VERSION} -> the factory image version
    """
    subst_vars = {
        'BOARD': self.simple_board.upper(),
        'FACTORY_IMAGE_BASE_VERSION': self.factory_image_base_version
        }
    return re.sub(r'\$\{(\w+)\}', lambda match: subst_vars[match.group(1)],
                  input_str)


if __name__ == '__main__':
  FinalizeBundle().Main()
