#!/usr/bin/python
#
# Copyright (c) 2014 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import __builtin__  # Used for mocking raw_input().
import mox
import os
import sys
import unittest

import factory_common  # pylint: disable=W0611
from cros.factory.umpire import common
from cros.factory.umpire import umpire
from cros.factory.utils import file_utils
from cros.factory.utils import type_utils


TESTDATA_DIR = os.path.realpath(os.path.join(
    os.path.dirname(__file__), 'testdata'))
DEFAULT_BUNDLE = os.path.join(TESTDATA_DIR, 'init_bundle')


def GetStdout():
  """Gets stdout buffer.

  Needs unittest.main(buffer=True).
  """
  # pylint: disable=E1101
  # getvalue is set when unittest.main has buffer=True arg.
  output = sys.stdout.getvalue()
  # pylint: enable=E1101
  return output.splitlines()


class UpdateTest(unittest.TestCase):
  FIRMWARE_PATH = os.path.join(TESTDATA_DIR, 'firmware.gz')
  TOOLKIT_PATH = os.path.join(TESTDATA_DIR, 'install_factory_toolkit.run')

  def setUp(self):
    self.args = type_utils.Obj(source_id=None, dest_id=None, resources=[])
    self.mox = mox.Mox()
    self.mock_cli = self.mox.CreateMockAnything()

  def tearDown(self):
    self.mox.UnsetStubs()
    self.mox.VerifyAll()

  def testUpdateSingleResource(self):
    # Expect XMLRPC call.
    self.mock_cli.Update([('toolkit', self.TOOLKIT_PATH)], None, None)
    self.mox.ReplayAll()

    self.args.resources.append('toolkit=%s' % self.TOOLKIT_PATH)
    umpire.Update(self.args, self.mock_cli)
    self.assertListEqual(
        ['Updating resources of default bundle in place',
         'Updating resources:',
         '  toolkit  %s' % self.TOOLKIT_PATH,
         'Update successfully.'],
        GetStdout())

  def testUpdateSingleResourceWithSourceDestId(self):
    # Expect XMLRPC call.
    self.mock_cli.Update([('toolkit', self.TOOLKIT_PATH)], 'bundle1',
                         'bundle2')
    self.mox.ReplayAll()

    self.args.resources.append('toolkit=%s' % self.TOOLKIT_PATH)
    self.args.source_id = 'bundle1'
    self.args.dest_id = 'bundle2'
    umpire.Update(self.args, self.mock_cli)
    self.assertListEqual(
        ["Creating a new bundle 'bundle2' based on bundle 'bundle1' with new "
         'resources',
         'Updating resources:',
         '  toolkit  %s' % self.TOOLKIT_PATH,
         'Update successfully.'],
        GetStdout())

  def testUpdateMultipleResources(self):
    # Expect XMLRPC call.
    self.mock_cli.Update([('toolkit', self.TOOLKIT_PATH),
                          ('firmware', self.FIRMWARE_PATH)], None, None)
    self.mox.ReplayAll()

    self.args.resources.append('toolkit=%s' % self.TOOLKIT_PATH)
    self.args.resources.append('firmware=%s' % self.FIRMWARE_PATH)
    umpire.Update(self.args, self.mock_cli)
    self.assertListEqual(
        ['Updating resources of default bundle in place',
         'Updating resources:',
         '  toolkit  %s' % self.TOOLKIT_PATH,
         '  firmware  %s' % self.FIRMWARE_PATH,
         'Update successfully.'],
        GetStdout())

  def testUpdateInvalidResourceType(self):
    self.mox.ReplayAll()

    self.args.resources.append('wrong_res_type=%s' % self.TOOLKIT_PATH)
    self.assertRaisesRegexp(common.UmpireError, 'Unsupported resource type',
                            umpire.Update, self.args, self.mock_cli)

  def testUpdateInvalidResourceFile(self):
    self.mox.ReplayAll()

    self.args.resources.append('release_image=/path/to/nowhere')
    self.assertRaisesRegexp(IOError, 'Missing resource',
                            umpire.Update, self.args, self.mock_cli)


class ImportBundleTest(unittest.TestCase):
  BUNDLE_PATH = os.path.join(TESTDATA_DIR, 'init_bundle')

  def setUp(self):
    self.args = type_utils.Obj(id=None, bundle_path='.', note=None)
    self.mox = mox.Mox()
    self.mock_cli = self.mox.CreateMockAnything()

  def tearDown(self):
    self.mox.UnsetStubs()
    self.mox.VerifyAll()

  def testImportBundle(self):
    # Expect XMLRPC call.
    self.mock_cli.ImportBundle(
        self.BUNDLE_PATH, 'new_bundle', 'new bundle').AndReturn(
            'umpire.yaml##00000000')

    self.mox.ReplayAll()

    self.args.bundle_path = self.BUNDLE_PATH
    self.args.id = 'new_bundle'
    self.args.note = 'new bundle'

    umpire.ImportBundle(self.args, self.mock_cli)
    self.assertListEqual(
        ['Importing bundle %r with specified bundle ID %r' % (
            self.BUNDLE_PATH, 'new_bundle'),
         "Import bundle successfully. Staging config 'umpire.yaml##00000000'"],
        GetStdout())


class DeployTest(unittest.TestCase):
  ACTIVE_CONFIG_PATH = os.path.join(
      TESTDATA_DIR, 'minimal_empty_services_with_enable_update_umpire.yaml')
  STAGING_CONFIG_PATH = os.path.join(TESTDATA_DIR, 'minimal_umpire.yaml')

  def setUp(self):
    self.args = type_utils.Obj()
    self.mox = mox.Mox()
    self.mock_cli = self.mox.CreateMockAnything()

  def tearDown(self):
    self.mox.UnsetStubs()
    self.mox.VerifyAll()

  def testDeployNoStaging(self):
    self.mock_cli.GetStatus().AndReturn({'staging_config': ''})
    self.mox.ReplayAll()

    self.assertRaisesRegexp(common.UmpireError, 'no staging file',
                            umpire.Deploy, self.args, self.mock_cli)

  def testDeploy(self):
    active_config = file_utils.ReadFile(self.ACTIVE_CONFIG_PATH)
    staging_config = file_utils.ReadFile(self.STAGING_CONFIG_PATH)
    self.mox.StubOutWithMock(__builtin__, 'raw_input')

    self.mock_cli.GetStatus().AndReturn(
        {'staging_config': staging_config,
         'staging_config_res': 'mock_staging##00000000',
         'active_config': active_config})
    self.mock_cli.ValidateConfig(staging_config)
    raw_input('Ok to deploy [y/n]? ').AndReturn('Y')
    self.mock_cli.Deploy('mock_staging##00000000')
    self.mox.ReplayAll()

    umpire.Deploy(self.args, self.mock_cli)
    self.assertListEqual(
        ['Getting status...',
         'Validating staging config for deployment...',
         'Changes for this deploy: ', '',
         "Deploying config 'mock_staging##00000000'",
         'Deploy successfully.'],
        GetStdout())

  def testDeployUserSayNo(self):
    active_config = file_utils.ReadFile(self.ACTIVE_CONFIG_PATH)
    staging_config = file_utils.ReadFile(self.STAGING_CONFIG_PATH)
    self.mox.StubOutWithMock(__builtin__, 'raw_input')

    self.mock_cli.GetStatus().AndReturn(
        {'staging_config': staging_config,
         'staging_config_res': 'mock_staging##00000000',
         'active_config': active_config})
    self.mock_cli.ValidateConfig(staging_config)
    raw_input('Ok to deploy [y/n]? ').AndReturn('x')
    # No mock.cli.Deploy is called
    self.mox.ReplayAll()

    umpire.Deploy(self.args, self.mock_cli)
    self.assertListEqual(['Getting status...',
                          'Validating staging config for deployment...',
                          'Changes for this deploy: ', '',
                          'Abort by user.'],
                         GetStdout())


if __name__ == '__main__':
  unittest.main(buffer=True)
