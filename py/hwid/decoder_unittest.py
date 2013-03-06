#!/usr/bin/python -u
# -*- coding: utf-8 -*-
#
# Copyright (c) 2012 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import factory_common # pylint: disable=W0611
import os
import unittest

from cros.factory.hwid import Database
from cros.factory.hwid.decoder import EncodedStringToBinaryString
from cros.factory.hwid.decoder import BinaryStringToBOM, Decode

_TEST_DATA_PATH = os.path.join(os.path.dirname(__file__), 'testdata')


class DecoderTest(unittest.TestCase):
  def setUp(self):
    self.database = Database.LoadFile(os.path.join(_TEST_DATA_PATH,
                                                   'test_db.yaml'))
    self.expected_components_from_db = {
       'audio_codec': [('codec_1', 'Codec 1', None),
                       ('hdmi_1', 'HDMI 1', None)],
       'battery': [('battery_huge', 'Battery Li-ion 10000000', None)],
       'bluetooth': [('bluetooth_0', '0123:abcd 0001', None)],
       'camera': [('camera_0', '4567:abcd Camera', None)],
       'cellular': [(None, None, None)],
       'chipset': [('chipset_0', 'cdef:abcd', None)],
       'cpu': [('cpu_5', 'CPU @ 2.80GHz [4 cores]', None)],
       'display_panel': [('display_panel_0', 'FOO:0123 [1440x900]', None)],
       'dram': [('dram_0', '0|2048|DDR3-800,DDR3-1066,DDR3-1333,DDR3-1600 '
                 '1|2048|DDR3-800,DDR3-1066,DDR3-1333,DDR3-1600', None)],
       'ec_flash_chip': [('ec_flash_chip_0', 'EC Flash Chip', None)],
       'embedded_controller': [('embedded_controller_0', 'Embedded Controller',
                               None)],
       'flash_chip': [('flash_chip_0', 'Flash Chip', None)],
       'hash_gbb': [('hash_gbb_0', 'gv2#aaaaaaaaaaaaaaaaaaaaaaaaaaaa'
                     'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa', None)],
       'key_recovery': [('key_recovery_0', 'kv3#bbbbbbbbbbbbbbbbbbb'
                         'bbbbbbbbbbbbbbbbbbbbb', None)],
       'key_root': [('key_root_0', 'kv3#cccccccccccccccccc'
                     'cccccccccccccccccccccc', None)],
       'keyboard': [('keyboard_us', 'xkb:us::eng', None)],
       'ro_ec_firmware': [('ro_ec_firmware_0',
                           'ev2#dddddddddddddddddddddddddddddddddddd'
                           'dddddddddddddddddddddddddddd#chromebook', None)],
       'ro_main_firmware': [('ro_main_firmware_0',
                             'mv2#eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee'
                             'eeeeeeeeeeeeeeeeeeeeeeeeeee#chromebook', None)],
       'storage': [('storage_0', '16G SSD #123456', None)],
       'touchpad': [('touchpad_0', 'TouchPad', None)],
       'tpm': [('tpm_0', '12340000:1.2.3', None)],
       'usb_hosts': [('usb_host_0', '8086:0000', None),
                     ('usb_host_1', '8086:0001', None)],
       'vga': [('vga_0', '8086:0002', None)],
       'wireless': [('wireless_0', '3210:abcd', None)]}

  def testEncodedStringToBinaryString(self):
    self.assertEquals('00000111010000010100',
                      EncodedStringToBinaryString(
                          # TODO(jcliang): Change back in R27.
                          #self.database, 'CHROMEBOOK A5AU-LU'))
                          self.database, 'CHROMEBOOK A5AU-LU 3324'))

  def testBinaryStringToBOM(self):
    result = open(os.path.join(_TEST_DATA_PATH,
                               'test_probe_result.yaml'), 'r').read()
    reference_bom = self.database.ProbeResultToBOM(result)
    bom = BinaryStringToBOM(self.database, '00000111010000010100')
    self.assertEquals(reference_bom.board, bom.board)
    self.assertEquals(reference_bom.encoding_pattern_index,
                      bom.encoding_pattern_index)
    self.assertEquals(reference_bom.image_id, bom.image_id)
    self.assertEquals(reference_bom.encoded_fields, bom.encoded_fields)
    self.assertEquals(self.expected_components_from_db, bom.components)

  def testDecode(self):
    result = open(os.path.join(_TEST_DATA_PATH,
                               'test_probe_result.yaml'), 'r').read()
    reference_bom = self.database.ProbeResultToBOM(result)
    # TODO(jcliang): Change back in R27.
    #hwid = Decode(self.database, 'CHROMEBOOK A5AU-LU')
    hwid = Decode(self.database, 'CHROMEBOOK A5AU-LU 3324')
    self.assertEquals('00000111010000010100', hwid.binary_string)
    # TODO(jcliang): Change back in R27.
    #self.assertEquals('CHROMEBOOK A5AU-LU', hwid.encoded_string)
    self.assertEquals('CHROMEBOOK A5AU-LU 3324', hwid.encoded_string)
    self.assertEquals(reference_bom.board, hwid.bom.board)
    self.assertEquals(reference_bom.encoding_pattern_index,
                      hwid.bom.encoding_pattern_index)
    self.assertEquals(reference_bom.image_id, hwid.bom.image_id)
    self.assertEquals(reference_bom.encoded_fields, hwid.bom.encoded_fields)
    self.assertEquals(self.expected_components_from_db, hwid.bom.components)


if __name__ == '__main__':
  unittest.main()
