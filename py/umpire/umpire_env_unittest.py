#!/usr/bin/python
#
# Copyright (c) 2014 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import mox
import os
import sys
import unittest

import factory_common  # pylint: disable=W0611

from cros.factory.umpire import config
from cros.factory.umpire.commands.update import ResourceUpdater
from cros.factory.umpire.common import (
    GetHashFromResourceName, ResourceType, RESOURCE_HASH_DIGITS, UmpireError)
from cros.factory.umpire.umpire_env import UmpireEnv
from cros.factory.utils import file_utils
from cros.factory.utils import get_version


TESTDATA_DIR = os.path.join(os.path.dirname(sys.modules[__name__].__file__),
                            'testdata')
TEST_CONFIG = os.path.join(TESTDATA_DIR,
                           'minimal_empty_services_umpire.yaml')
TOOLKIT_DIR = os.path.join(TESTDATA_DIR, 'install_factory_toolkit.run')


class UmpireEnvTest(unittest.TestCase):

  def setUp(self):
    self.env = UmpireEnv()
    self.env.base_dir = '/test/umpire'
    self.mox = mox.Mox()

  def tearDown(self):
    self.mox.UnsetStubs()
    self.mox.VerifyAll()

  def testGetUmpireBaseDir(self):
    # pylint: disable=W0212
    self.assertEqual(None, UmpireEnv._GetUmpireBaseDir('/foo/bar'))
    self.assertEqual('/foo/bar/umpire',
                     UmpireEnv._GetUmpireBaseDir('/foo/bar/umpire'))
    self.assertEqual('/foo/bar/umpire',
                     UmpireEnv._GetUmpireBaseDir('/foo/bar/umpire/'))
    self.assertEqual('/foo/bar/umpire',
                     UmpireEnv._GetUmpireBaseDir('/foo/bar/umpire/bin'))

  def testLoadConfigDefault(self):
    default_path = os.path.join(self.env.base_dir, 'active_umpire.yaml')
    self.mox.StubOutClassWithMocks(config, 'UmpireConfig')
    config.UmpireConfig(default_path).get('port').AndReturn(8080)
    self.mox.ReplayAll()

    self.env.LoadConfig()
    self.assertEqual(default_path, self.env.config_path)

  def testLoadConfigCustomPath(self):
    custom_path = os.path.join(self.env.base_dir, 'custom_config.yaml')

    self.mox.StubOutClassWithMocks(config, 'UmpireConfig')
    config.UmpireConfig(custom_path).get('port').AndReturn(8080)
    self.mox.ReplayAll()

    self.env.LoadConfig(custom_path=custom_path)
    self.assertEqual(custom_path, self.env.config_path)

  def testLoadConfigStaging(self):
    staging_path = os.path.join(self.env.base_dir, 'staging_umpire.yaml')
    self.mox.StubOutClassWithMocks(config, 'UmpireConfig')
    config.UmpireConfig(staging_path).get('port').AndReturn(8080)
    self.mox.ReplayAll()

    self.env.LoadConfig(staging=True)
    self.assertEqual(staging_path, self.env.config_path)

  def testStageConfigFile(self):
    with file_utils.TempDirectory() as temp_dir:
      self.env.base_dir = temp_dir
      config_to_stage = os.path.join(temp_dir, 'to_stage.yaml')
      file_utils.TouchFile(config_to_stage)

      self.assertFalse(os.path.exists(self.env.staging_config_file))
      self.env.StageConfigFile(config_to_stage)
      self.assertTrue(os.path.exists(self.env.staging_config_file))

  def testStageConfigFileConfigAlreadyExist(self):
    with file_utils.TempDirectory() as temp_dir:
      self.env.base_dir = temp_dir
      # Staging config already exists.
      file_utils.TouchFile(self.env.staging_config_file)
      config_to_stage = os.path.join(temp_dir, 'to_stage.yaml')
      file_utils.TouchFile(config_to_stage)

      self.assertRaisesRegexp(UmpireError, 'already staged',
                              self.env.StageConfigFile, config_to_stage)

  def testStageConfigFileForceStaging(self):
    with file_utils.TempDirectory() as temp_dir:
      self.env.base_dir = temp_dir
      # Staging config already exists.
      file_utils.TouchFile(self.env.staging_config_file)
      config_to_stage = os.path.join(temp_dir, 'to_stage.yaml')
      file_utils.WriteFile(config_to_stage, 'new stage file')

      self.env.StageConfigFile(config_to_stage, force=True)
      self.assertTrue(os.path.exists(self.env.staging_config_file))
      self.assertEqual('new stage file',
                       file_utils.Read(self.env.staging_config_file))

  def testStageConfigFileSourceNotFound(self):
    with file_utils.TempDirectory() as temp_dir:
      self.env.base_dir = temp_dir
      config_to_stage = os.path.join(temp_dir, 'to_stage.yaml')

      self.assertRaisesRegexp(UmpireError, "doesn't exist",
                              self.env.StageConfigFile, config_to_stage)

  def testUnstageConfigFile(self):
    with file_utils.TempDirectory() as temp_dir:
      self.env.base_dir = temp_dir
      file_utils.TouchFile(self.env.staging_config_file)

      self.assertTrue(os.path.exists(self.env.staging_config_file))
      self.env.UnstageConfigFile()
      self.assertFalse(os.path.exists(self.env.staging_config_file))

  def testUnstageConfigFileNoStagingConfig(self):
    with file_utils.TempDirectory() as temp_dir:
      self.env.base_dir = temp_dir

      self.assertRaises(UmpireError, self.env.UnstageConfigFile)

  def testActivateConfigFile(self):
    with file_utils.TempDirectory() as temp_dir:
      self.env.base_dir = temp_dir
      config_to_activate = os.path.join(temp_dir, 'to_activate.yaml')
      file_utils.TouchFile(config_to_activate)

      self.env.ActivateConfigFile(config_path=config_to_activate)
      self.assertTrue(os.path.exists(self.env.active_config_file))
      self.assertEqual(config_to_activate,
                       os.path.realpath(self.env.active_config_file))

  def testActivateConfigFileDefaultStaging(self):
    with file_utils.TempDirectory() as temp_dir:
      self.env.base_dir = temp_dir
      config_to_activate = os.path.join(temp_dir, 'to_activate.yaml')
      file_utils.TouchFile(config_to_activate)
      # First prepare a staging config file.
      self.env.StageConfigFile(config_to_activate)

      self.env.ActivateConfigFile()
      self.assertTrue(os.path.exists(self.env.active_config_file))
      self.assertEqual(config_to_activate,
                       os.path.realpath(self.env.active_config_file))

  def testAddResource(self):
    with file_utils.TempDirectory() as temp_dir:
      self.env.base_dir = temp_dir
      os.mkdir(self.env.resources_dir)

      resource_to_add = os.path.join(temp_dir, 'some_resource')
      file_utils.WriteFile(resource_to_add, 'something')
      resource_md5 = file_utils.Md5sumInHex(resource_to_add)[
          :RESOURCE_HASH_DIGITS]

      resource_path = self.env.AddResource(resource_to_add)
      self.assertTrue(resource_path.endswith(
          'resources/%s##%.8s' % ('some_resource', resource_md5)))
      self.assertTrue(os.path.exists(resource_path))

  def testAddResourceSourceNotFound(self):
    with file_utils.TempDirectory() as temp_dir:
      self.env.base_dir = temp_dir
      os.mkdir(self.env.resources_dir)

      resource_to_add = os.path.join(temp_dir, 'some_resource')

      self.assertRaisesRegexp(IOError, 'Missing source',
                              self.env.AddResource, resource_to_add)

  def testAddResourceSkipDuplicate(self):
    with file_utils.TempDirectory() as temp_dir:
      self.env.base_dir = temp_dir
      os.mkdir(self.env.resources_dir)

      resource_to_add = os.path.join(temp_dir, 'some_resource')
      file_utils.WriteFile(resource_to_add, 'something')

      resource_path = self.env.AddResource(resource_to_add)
      resource_path_duplicate = self.env.AddResource(resource_to_add)
      self.assertEqual(resource_path, resource_path_duplicate)

  def testAddResourceHashCollision(self):
    with file_utils.TempDirectory() as temp_dir:
      self.env.base_dir = temp_dir
      os.mkdir(self.env.resources_dir)

      resource_to_add = os.path.join(temp_dir, 'some_resource')
      file_utils.WriteFile(resource_to_add, 'something')

      resource_path = self.env.AddResource(resource_to_add)

      # Change its content to mimic hash collision case.
      file_utils.WriteFile(resource_path, 'changed')

      self.assertRaisesRegexp(UmpireError, 'Hash collision',
                              self.env.AddResource, resource_to_add)

  def testAddResourceFirmwareOmahaChannel(self):
    with file_utils.TempDirectory() as temp_dir:
      self.env.base_dir = temp_dir
      os.mkdir(self.env.resources_dir)

      file_name = 'firmware.gz'
      resource_to_add = os.path.join(temp_dir, file_name)
      file_utils.WriteFile(resource_to_add, 'firmware')
      resource_md5 = file_utils.Md5sumInHex(resource_to_add)[
          :RESOURCE_HASH_DIGITS]

      # TODO(deanliao): use real firmware.gz in which Umpire can extract
      #     version from.
      self.mox.StubOutWithMock(
          get_version, 'GetFirmwareVersionsFromOmahaChannelFile')
      BIOS_VERSION = 'bios_0.0.1'
      EC_VERSION = 'ec_0.0.2'
      get_version.GetFirmwareVersionsFromOmahaChannelFile(
          resource_to_add).AndReturn((BIOS_VERSION, EC_VERSION))
      self.mox.ReplayAll()

      resource_path = self.env.AddResource(resource_to_add,
                                           res_type=ResourceType.FIRMWARE)
      expected_version = ':'.join([BIOS_VERSION, EC_VERSION])
      self.assertTrue(resource_path.endswith(
          'resources/%s#%s#%.8s' % (file_name, expected_version,
                                    resource_md5)))
      self.assertTrue(os.path.exists(resource_path))

  def testAddResourceFirmware(self):
    with file_utils.TempDirectory() as temp_dir:
      self.env.base_dir = temp_dir
      os.mkdir(self.env.resources_dir)

      file_name = 'chromeos-firmwareupdate'
      resource_to_add = os.path.join(temp_dir, file_name)
      file_utils.WriteFile(resource_to_add, 'firmware')
      resource_md5 = file_utils.Md5sumInHex(resource_to_add)[
          :RESOURCE_HASH_DIGITS]

      # TODO(deanliao): use real chromeos-firmwareupdate in which Umpire can
      # extract version from.
      self.mox.StubOutWithMock(get_version, 'GetFirmwareVersions')
      BIOS_VERSION = 'bios_0.0.1'
      EC_VERSION = 'ec_0.0.2'
      get_version.GetFirmwareVersions(resource_to_add).AndReturn(
          (BIOS_VERSION, EC_VERSION))
      self.mox.ReplayAll()

      resource_path = self.env.AddResource(resource_to_add,
                                           res_type=ResourceType.FIRMWARE)
      expected_version = ':'.join([BIOS_VERSION, EC_VERSION])
      self.assertTrue(resource_path.endswith(
          'resources/%s#%s#%.8s' % (file_name, expected_version,
                                    resource_md5)))
      self.assertTrue(os.path.exists(resource_path))

  def testAddResourceRootfsRelease(self):
    with file_utils.TempDirectory() as temp_dir:
      self.env.base_dir = temp_dir
      os.mkdir(self.env.resources_dir)

      file_name = 'rootfs-test.gz'
      resource_to_add = os.path.join(temp_dir, file_name)
      file_utils.WriteFile(resource_to_add, 'rootfs-test')
      resource_md5 = file_utils.Md5sumInHex(resource_to_add)[
          :RESOURCE_HASH_DIGITS]

      # TODO(deanliao): use real rootfs-test.gz in which Umpire can extract
      #     version from.
      self.mox.StubOutWithMock(
          get_version, 'GetReleaseVersionFromOmahaChannelFile')
      TEST_IMAGE_VERSION = '0.0.1'
      get_version.GetReleaseVersionFromOmahaChannelFile(
          resource_to_add).AndReturn(TEST_IMAGE_VERSION)
      self.mox.ReplayAll()

      resource_path = self.env.AddResource(resource_to_add,
                                           res_type=ResourceType.ROOTFS_TEST)
      self.assertTrue(resource_path.endswith(
          'resources/%s#%s#%.8s' % (file_name, TEST_IMAGE_VERSION,
                                    resource_md5)))
      self.assertTrue(os.path.exists(resource_path))

  def testAddResourceHWID(self):
    with file_utils.TempDirectory() as temp_dir:
      self.env.base_dir = temp_dir
      os.mkdir(self.env.resources_dir)

      # HWID version extracted from testdata/hwid_v3_bundle.sh checksum field.
      file_name = 'hwid_v3_bundle.sh'
      hwid_version = 'a95cd8def470df2e7a8d549af887897e2d095bb0'
      resource_to_add = os.path.join(TESTDATA_DIR, file_name)
      resource_md5 = file_utils.Md5sumInHex(resource_to_add)[
          :RESOURCE_HASH_DIGITS]

      resource_path = self.env.AddResource(resource_to_add,
                                           res_type=ResourceType.HWID)
      print resource_path
      self.assertTrue(resource_path.endswith(
          'resources/%s#%s#%.8s' % (file_name, hwid_version, resource_md5)))
      self.assertTrue(os.path.exists(resource_path))

  def testAddResourceHWIDGzipped(self):
    with file_utils.TempDirectory() as temp_dir:
      self.env.base_dir = temp_dir
      os.mkdir(self.env.resources_dir)

      # HWID version extracted from testdata/hwid.gz checksum field.
      file_name = 'hwid.gz'
      hwid_version = 'a95cd8def470df2e7a8d549af887897e2d095bb0'
      resource_to_add = os.path.join(TESTDATA_DIR, file_name)

      resource_md5 = file_utils.Md5sumInHex(resource_to_add)[
          :RESOURCE_HASH_DIGITS]

      resource_path = self.env.AddResource(resource_to_add,
                                           res_type=ResourceType.HWID)
      self.assertTrue(resource_path.endswith(
          'resources/%s#%s#%.8s' % (file_name, hwid_version, resource_md5)))
      self.assertTrue(os.path.exists(resource_path))

  def testAddResourceToolkitNoVersion(self):
    with file_utils.TempDirectory() as temp_dir:
      self.env.base_dir = temp_dir
      os.mkdir(self.env.resources_dir)

      file_name = 'install_factory_toolkit.run'
      resource_to_add = os.path.join(temp_dir, file_name)
      file_utils.WriteFile(resource_to_add, 'factory_toolkit')
      resource_md5 = file_utils.Md5sumInHex(resource_to_add)[
          :RESOURCE_HASH_DIGITS]

      resource_path = self.env.AddResource(
          resource_to_add, res_type=ResourceType.FACTORY_TOOLKIT)

      expected_version = ''
      self.assertTrue(resource_path.endswith(
          'resources/%s#%s#%.8s' % (file_name, expected_version,
                                    resource_md5)))
      self.assertTrue(os.path.exists(resource_path))

  def testGetResourcePath(self):
    with file_utils.TempDirectory() as temp_dir:
      self.env.base_dir = temp_dir
      os.mkdir(self.env.resources_dir)

      resource_to_add = os.path.join(temp_dir, 'some_resource')
      file_utils.WriteFile(resource_to_add, 'something')
      resource_path = self.env.AddResource(resource_to_add)
      resource_name = os.path.basename(resource_path)

      self.assertTrue(resource_path, self.env.GetResourcePath(resource_name))

  def testGetResourcePathNotFound(self):
    with file_utils.TempDirectory() as temp_dir:
      self.env.base_dir = temp_dir
      os.mkdir(self.env.resources_dir)

      self.assertRaises(IOError, self.env.GetResourcePath, 'foobar')

      # Without check, just output resource_dir/resource_name
      self.assertEqual(os.path.join(self.env.resources_dir, 'foobar'),
                       self.env.GetResourcePath('foobar', check=False))

  def testGetBundleDeviceToolkit(self):
    with file_utils.TempDirectory() as temp_dir:
      self.env.base_dir = temp_dir
      os.makedirs(self.env.device_toolkits_dir)
      os.makedirs(self.env.resources_dir)
      self.env.LoadConfig(custom_path=TEST_CONFIG)

      # Add the toolkit to resources and get hash value.
      updater = ResourceUpdater(self.env)
      updater.Update([('factory_toolkit', TOOLKIT_DIR)])
      # After updating resources, we need to reload the staging config.
      self.env.LoadConfig(staging=True)

      # Get hash value to compose expected toolkit dir.
      bundle = self.env.config.GetDefaultBundle()
      toolkit_resource = bundle['resources']['device_factory_toolkit']
      toolkit_hash = GetHashFromResourceName(toolkit_resource)
      expected_toolkit_dir = os.path.join(self.env.device_toolkits_dir,
                                          toolkit_hash)

      # Create the expected toolkit dir.
      os.makedirs(expected_toolkit_dir)

      self.assertEqual(expected_toolkit_dir,
                       self.env.GetBundleDeviceToolkit(bundle['id']))

  def testGetBundleDeviceToolkitInvalidBundleID(self):
    # Same environment, but looking up an invalid bundle ID.
    with file_utils.TempDirectory() as temp_dir:
      self.env.base_dir = temp_dir
      os.makedirs(self.env.device_toolkits_dir)
      os.makedirs(self.env.resources_dir)
      self.env.LoadConfig(custom_path=TEST_CONFIG)

      # Add the toolkit to resources.
      updater = ResourceUpdater(self.env)
      updater.Update([('factory_toolkit', TOOLKIT_DIR)])
      # After updating resources, we need to reload the staging config.
      self.env.LoadConfig(staging=True)

      # Get hash value to compose expected toolkit dir.
      bundle = self.env.config.GetDefaultBundle()
      toolkit_resource = bundle['resources']['device_factory_toolkit']
      toolkit_hash = GetHashFromResourceName(toolkit_resource)
      expected_toolkit_dir = os.path.join(self.env.device_toolkits_dir,
                                          toolkit_hash)

      # Create the expected toolkit dir.
      os.makedirs(expected_toolkit_dir)

      self.assertIsNone(self.env.GetBundleDeviceToolkit('invalid_bundle'))


  def testGetBundleDeviceToolkitMissingToolkitPath(self):
    # Same environment, but don't create toolkit dir.
    with file_utils.TempDirectory() as temp_dir:
      self.env.base_dir = temp_dir
      os.makedirs(self.env.device_toolkits_dir)
      os.makedirs(self.env.resources_dir)
      self.env.LoadConfig(custom_path=TEST_CONFIG)

      # Add the toolkit to resources.
      updater = ResourceUpdater(self.env)
      updater.Update([('factory_toolkit', TOOLKIT_DIR)])
      # After updating resources, we need to reload the staging config.
      self.env.LoadConfig(staging=True)

      bundle = self.env.config.GetDefaultBundle()
      self.assertIsNone(self.env.GetBundleDeviceToolkit(bundle['id']))



if __name__ == '__main__':
  unittest.main()
