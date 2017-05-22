# -*- mode: python; coding: utf-8 -*-
# Copyright (c) 2012 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.


"""Manually updates device data."""


import unittest

import factory_common  # pylint: disable=unused-import
from cros.factory.test import state
from cros.factory.utils.arg_utils import Arg


class CallShopfloor(unittest.TestCase):
  ARGS = [
      Arg('data', dict, 'Items to update in device data dict.'),
  ]

  def runTest(self):
    state.UpdateDeviceData(self.args.data)
