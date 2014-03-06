#!/usr/bin/python
#
# Copyright (c) 2014 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import mox
import os
import unittest

import factory_common  # pylint: disable=W0611

from cros.factory.umpire import config
from cros.factory.umpire.common import UmpireError, RESOURCE_HASH_DIGITS
from cros.factory.umpire.umpire_env import UmpireEnv
from cros.factory.utils import file_utils


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
    config.UmpireConfig(default_path)
    self.mox.ReplayAll()

    self.env.LoadConfig()
    self.assertEqual(default_path, self.env.config_path)

  def testLoadConfigCustomPath(self):
    custom_path = os.path.join(self.env.base_dir, 'custom_config.yaml')

    self.mox.StubOutClassWithMocks(config, 'UmpireConfig')
    config.UmpireConfig(custom_path)
    self.mox.ReplayAll()

    self.env.LoadConfig(custom_path=custom_path)
    self.assertEqual(custom_path, self.env.config_path)

  def testLoadConfigStaging(self):
    staging_path = os.path.join(self.env.base_dir, 'staging_umpire.yaml')
    self.mox.StubOutClassWithMocks(config, 'UmpireConfig')
    config.UmpireConfig(staging_path)
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

  def testStageConfigFile_ConfigAlreadyExist(self):
    with file_utils.TempDirectory() as temp_dir:
      self.env.base_dir = temp_dir
      # Staging config already exists.
      file_utils.TouchFile(self.env.staging_config_file)
      config_to_stage = os.path.join(temp_dir, 'to_stage.yaml')
      file_utils.TouchFile(config_to_stage)

      self.assertRaisesRegexp(UmpireError, 'already staged',
                              self.env.StageConfigFile, config_to_stage)

  def testStageConfigFile_SourceNotFound(self):
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

  def testUnstageConfigFile_NoStagingConfig(self):
    with file_utils.TempDirectory() as temp_dir:
      self.env.base_dir = temp_dir

      self.assertRaises(UmpireError, self.env.UnstageConfigFile)

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


if __name__ == '__main__':
  unittest.main()
