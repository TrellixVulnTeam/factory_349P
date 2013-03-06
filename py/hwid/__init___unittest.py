#!/usr/bin/python -u
# -*- coding: utf-8 -*-
#
# Copyright (c) 2012 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=W0212

import factory_common # pylint: disable=W0611
import os
import unittest2

from cros.factory.hwid import (
    HWIDException, Database, MakeList, MakeSet, ProbedComponentResult)
from cros.factory.hwid.encoder import Encode

_TEST_DATA_PATH = os.path.join(os.path.dirname(__file__), 'testdata')


class HWIDTest(unittest2.TestCase):
  def setUp(self):
    self.database = Database.LoadFile(os.path.join(_TEST_DATA_PATH,
                                                   'test_db.yaml'))

  def testMakeList(self):
    self.assertEquals(['a'], MakeList('a'))
    self.assertEquals(['abc'], MakeList('abc'))
    self.assertEquals(['a', 'b'], MakeList(['a', 'b']))
    self.assertEquals(['a', 'b'], MakeList({'a': 'foo', 'b': 'bar'}))

  def testMakeSet(self):
    self.assertEquals(set(['ab']), MakeSet('ab'))
    self.assertEquals(set(['a', 'b']), MakeSet(['a', 'b']))
    self.assertEquals(set(['a', 'b']), MakeSet(('a', 'b')))
    self.assertEquals(set(['a', 'b']), MakeSet({'a': 'foo', 'b': 'bar'}))

  def testVerifySelf(self):
    result = open(os.path.join(_TEST_DATA_PATH,
                               'test_probe_result.yaml'), 'r').read()
    bom = self.database.ProbeResultToBOM(result)
    hwid = Encode(self.database, bom)
    self.assertEquals(None, hwid.VerifySelf())

    # The correct binary string: '00000111010000010100'
    original_value = hwid.binary_string
    hwid.binary_string = '000001110100000101100'
    self.assertRaisesRegexp(
        HWIDException, r'Invalid bit string length', hwid.VerifySelf)
    hwid.binary_string = '00000011010000010100'
    self.assertRaisesRegexp(
        HWIDException, r'Binary string .* does not encode to encoded string .*',
        hwid.VerifySelf)
    hwid.binary_string = original_value

    original_value = hwid.encoded_string
    # TODO(jcliang): Change back in R27.
    #hwid.encoded_string = 'ASDF QWER-TY'
    hwid.encoded_string = 'ASDF QWER-TY 1111'
    self.assertRaisesRegexp(
        HWIDException, r'Invalid board name', hwid.VerifySelf)
    hwid.encoded_string = original_value

    original_value = hwid.bom
    hwid.bom.encoded_fields['cpu'] = 10
    self.assertRaisesRegexp(
        HWIDException, r'Encoded fields .* have unknown indices',
        hwid.VerifySelf)
    hwid.bom.encoded_fields['cpu'] = 2
    self.assertRaisesRegexp(
        HWIDException, r'BOM does not encode to binary string .*',
        hwid.VerifySelf)
    hwid.bom = original_value

  def testVerifyProbeResult(self):
    result = open(os.path.join(_TEST_DATA_PATH,
                               'test_probe_result.yaml'), 'r').read()
    bom = self.database.ProbeResultToBOM(result)
    hwid = Encode(self.database, bom)
    fake_result = result.replace('HDMI 1', 'HDMI 0')
    self.assertRaisesRegexp(
        HWIDException, r'Component class .* has extra components: .* and '
        'missing components: .*. Expected values are: .*',
        hwid.VerifyProbeResult, fake_result)
    fake_result = result.replace('CPU @ 2.80GHz [4 cores]',
                                 'CPU @ 2.40GHz [4 cores]')
    self.assertRaisesRegexp(
        HWIDException, r'Component class .* has extra components: .* and '
        'missing components: .*. Expected values are: .*',
        hwid.VerifyProbeResult, fake_result)
    self.assertEquals(None, hwid.VerifyProbeResult(result))
    fake_result = result.replace('4567:abcd Camera', 'woot!')
    self.assertEquals(None, hwid.VerifyProbeResult(fake_result))


class DatabaseTest(unittest2.TestCase):
  def setUp(self):
    self.database = Database.LoadFile(os.path.join(_TEST_DATA_PATH,
                                                   'test_db.yaml'))
  def testProbeResultToBOM(self):
    result = open(os.path.join(_TEST_DATA_PATH,
                               'test_probe_result.yaml'), 'r').read()
    bom = self.database.ProbeResultToBOM(result)
    self.assertEquals('CHROMEBOOK', bom.board)
    self.assertEquals(0, bom.encoding_pattern_index)
    self.assertEquals(0, bom.image_id)
    self.assertEquals({
       'audio_codec': [('codec_1', 'Codec 1', None),
                       ('hdmi_1', 'HDMI 1', None)],
       'battery': [('battery_huge', 'Battery Li-ion 10000000', None)],
       'bluetooth': [('bluetooth_0', '0123:abcd 0001', None)],
       'camera': [(None, '4567:abcd Camera',
                   "component class 'camera' is unprobeable")],
       'cellular': [(None, None, "missing 'cellular' component")],
       'chipset': [('chipset_0', 'cdef:abcd', None)],
       'cpu': [('cpu_5', 'CPU @ 2.80GHz [4 cores]', None)],
       'display_panel': [
          (None, 'FOO:0123 [1440x900]',
           "component class 'display_panel' is unprobeable")],
       'dram': [('dram_0', '0|2048|DDR3-800,DDR3-1066,DDR3-1333,DDR3-1600 '
                 '1|2048|DDR3-800,DDR3-1066,DDR3-1333,DDR3-1600', None)],
       'ec_flash_chip': [('ec_flash_chip_0', 'EC Flash Chip', None)],
       'embedded_controller': [('embedded_controller_0', 'Embedded Controller',
                               None)],
       'ethernet': [(None, None, "missing 'ethernet' component")],
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
       'wireless': [('wireless_0', '3210:abcd', None)]}, bom.components)
    self.assertEquals({
        'audio_codec': 1,
        'battery': 3,
        'bluetooth': 0,
        'camera': 0,
        'cellular': 0,
        'chipset': 0,
        'cpu': 5,
        'display_panel': 0,
        'dram': 0,
        'ec_flash_chip': 0,
        'embedded_controller': 0,
        'firmware': 0,
        'flash_chip': 0,
        'keyboard': 0,
        'storage': 0,
        'touchpad': 0,
        'tpm': 0,
        'usb_hosts': 0,
        'vga': 0,
        'wireless': 0}, bom.encoded_fields)
    result = result.replace('chipset: cdef:abcd', 'chipset: something else')
    self.assertEquals({
        'audio_codec': 1,
        'battery': 3,
        'bluetooth': 0,
        'camera': 0,
        'cellular': 0,
        'chipset': None,
        'cpu': 5,
        'display_panel': 0,
        'dram': 0,
        'ec_flash_chip': 0,
        'embedded_controller': 0,
        'firmware': 0,
        'flash_chip': 0,
        'keyboard': 0,
        'storage': 0,
        'touchpad': 0,
        'tpm': 0,
        'usb_hosts': 0,
        'vga': 0,
        'wireless': 0}, self.database.ProbeResultToBOM(result).encoded_fields)

  def testGetFieldIndexFromComponents(self):
    result = open(os.path.join(_TEST_DATA_PATH,
                               'test_probe_result.yaml'), 'r').read()
    bom = self.database.ProbeResultToBOM(result)
    self.assertEquals(5, self.database._GetFieldIndexFromProbedComponents(
        'cpu', bom.components))
    self.assertEquals(1, self.database._GetFieldIndexFromProbedComponents(
        'audio_codec', bom.components))
    self.assertEquals(3, self.database._GetFieldIndexFromProbedComponents(
        'battery', bom.components))
    self.assertEquals(0, self.database._GetFieldIndexFromProbedComponents(
        'storage', bom.components))
    self.assertEquals(0, self.database._GetFieldIndexFromProbedComponents(
        'cellular', bom.components))
    self.assertEquals(None, self.database._GetFieldIndexFromProbedComponents(
        'wimax', bom.components))

  def testGetAllIndices(self):
    self.assertEquals([0, 1, 2, 3, 4, 5], self.database._GetAllIndices('cpu'))
    self.assertEquals([0, 1], self.database._GetAllIndices('dram'))
    self.assertEquals([0], self.database._GetAllIndices('wireless'))

  def testGetAttributesByIndex(self):
    self.assertEquals({'battery': [{
                          'name': 'battery_large',
                          'value': 'Battery Li-ion 7500000'}]},
                      self.database._GetAttributesByIndex('battery', 2))
    self.assertEquals(
        {'hash_gbb': [{
              'name': 'hash_gbb_0',
              'value': 'gv2#aaaaaaaaaaaaaaaaaaaaaaaaaaaaaa'
                       'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa'}],
         'key_recovery': [{
              'name': 'key_recovery_0',
              'value': 'kv3#bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb'}],
         'key_root': [{
              'name': 'key_root_0',
              'value': 'kv3#cccccccccccccccccccccccccccccccccccccccc'}],
         'ro_ec_firmware': [{
              'name': 'ro_ec_firmware_0',
              'value': 'ev2#ddddddddddddddddddddddddddddddddddd'
                       'ddddddddddddddddddddddddddddd#chromebook'}],
         'ro_main_firmware': [{
              'name': 'ro_main_firmware_0',
              'value': 'mv2#eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee'
                       'eeeeeeeeeeeeeeeeeeeeeeeeeeeee#chromebook'}]},
        self.database._GetAttributesByIndex('firmware', 0))
    self.assertEquals({
        'audio_codec': [
          {'name': 'codec_0', 'value': 'Codec 0'},
          {'name': 'hdmi_0', 'value': 'HDMI 0'}]},
        self.database._GetAttributesByIndex('audio_codec', 0))
    self.assertEquals({'cellular': None},
                      self.database._GetAttributesByIndex('cellular', 0))

  def testVerifyBinaryString(self):
    self.assertEquals(
        None, self.database.VerifyBinaryString('00000101001101101100'))
    self.assertRaisesRegexp(
        HWIDException, r'Invalid binary string: .*',
        self.database.VerifyBinaryString, '020001010011011011000')
    self.assertRaisesRegexp(
        HWIDException, r'Binary string .* does not have stop bit set',
        self.database.VerifyBinaryString, '00000')
    self.assertRaisesRegexp(
        HWIDException, r'Invalid bit string length',
        self.database.VerifyBinaryString, '0000010100110110111000')

  def testVerifyEncodedString(self):
    self.assertEquals(
        # TODO(jcliang): Change back in R27.
        #None, self.database.VerifyEncodedString('CHROMEBOOK AW3L-M7I7-V'))
        None, self.database.VerifyEncodedString('CHROMEBOOK AW3L-M7I7-V 1111'))
    self.assertRaisesRegexp(
        HWIDException, r'Invalid HWID string format',
        self.database.VerifyEncodedString, 'AW3L-M7I5-4')
    self.assertRaisesRegexp(
        HWIDException, r'Length of encoded string .* is less than 2 characters',
        # TODO(jcliang): Change back in R27.
        #self.database.VerifyEncodedString, 'FOO A')
        self.database.VerifyEncodedString, 'FOO A 1111')
    self.assertRaisesRegexp(
        HWIDException, r'Invalid board name', self.database.VerifyEncodedString,
        # TODO(jcliang): Change back in R27.
        #'FOO AW3L-M7IK-W')
        'FOO AW3L-M7IK-W 1111')
    self.assertRaisesRegexp(
        HWIDException, r'Checksum of .* mismatch',
        # TODO(jcliang): Change back in R27.
        #self.database.VerifyEncodedString, 'CHROMEBOOK AW3L-M7IA-B')
        self.database.VerifyEncodedString, 'CHROMEBOOK AW3L-M7IA-B 1111')

  def testVerifyBOM(self):
    result = open(os.path.join(_TEST_DATA_PATH,
                               'test_probe_result.yaml'), 'r').read()
    bom = self.database.ProbeResultToBOM(result)
    self.assertEquals(
        None, self.database.VerifyBOM(bom))

    original_value = bom.components['ec_flash_chip']
    bom.components.pop('ec_flash_chip')
    self.assertRaisesRegexp(
        HWIDException, r'Missing component classes: .*',
        self.database.VerifyBOM, bom)
    bom.components['ec_flash_chip'] = original_value

    original_value = bom.board
    bom.board = 'FOO'
    self.assertRaisesRegexp(
        HWIDException, r'Invalid board name. Expected .*, got .*',
        self.database.VerifyBOM, bom)
    bom.board = original_value

    original_value = bom.encoding_pattern_index
    bom.encoding_pattern_index = 1
    self.assertRaisesRegexp(
        HWIDException, r'Invalid encoding pattern', self.database.VerifyBOM,
        bom)
    bom.encoding_pattern_index = original_value

    original_value = bom.image_id
    bom.image_id = 5
    self.assertRaisesRegexp(
        HWIDException, r'Invalid image id: .*', self.database.VerifyBOM, bom)
    bom.image_id = original_value

    original_value = bom.encoded_fields['cpu']
    bom.encoded_fields['cpu'] = 8
    self.assertRaisesRegexp(
        HWIDException, r'Encoded fields .* have unknown indices',
        self.database.VerifyBOM, bom)
    bom.encoded_fields['cpu'] = original_value

    bom.encoded_fields['foo'] = 1
    self.assertRaisesRegexp(
        HWIDException, r'Extra encoded fields in BOM: .*',
        self.database.VerifyBOM, bom)
    bom.encoded_fields.pop('foo')

    original_value = bom.components['cpu']
    bom.components['cpu'] = [ProbedComponentResult('cpu', 'foo', None)]
    self.assertRaisesRegexp(
        HWIDException, r'Unknown component values: .*', self.database.VerifyBOM,
        bom)
    bom.components['cpu'] = original_value

    original_value = bom.encoded_fields['cpu']
    bom.encoded_fields.pop('cpu')
    self.assertRaisesRegexp(
        HWIDException, r'Missing encoded fields in BOM: .*',
        self.database.VerifyBOM, bom)
    bom.encoded_fields['cpu'] = original_value

  def testVerifyComponents(self):
    result = open(os.path.join(_TEST_DATA_PATH,
                               'test_probe_result.yaml'), 'r').read()
    self.assertRaisesRegexp(
        HWIDException, r'Argument comp_list should be a list',
        self.database.VerifyComponents, result, 'cpu')
    self.assertRaisesRegexp(
        HWIDException, r'.* is not probeable and cannot be verified',
        self.database.VerifyComponents, result, ['camera'])
    self.assertEquals({
        'audio_codec': [
            ('codec_1', 'Codec 1', None),
            ('hdmi_1', 'HDMI 1', None)],
        'cellular': [
            (None, None, 'missing \'cellular\' component')],
        'cpu': [
            ('cpu_5', 'CPU @ 2.80GHz [4 cores]', None)]},
        self.database.VerifyComponents(
            result, ['audio_codec', 'cellular', 'cpu']))
    result = """
        found_probe_value_map:
          audio_codec:
          - Codec 1
          - HDMI 3
        found_volatile_values: {}
        initial_configs: {}
        missing_component_classes: []
    """
    self.assertEquals({
        'audio_codec': [
            ('codec_1', 'Codec 1', None),
            (None, 'HDMI 3', 'unsupported \'audio_codec\' component found with '
             'probe result \'HDMI 3\' (no matching name in the component DB)')
        ]}, self.database.VerifyComponents(result, ['audio_codec']))


class PatternTest(unittest2.TestCase):
  def setUp(self):
    self.database = Database.LoadFile(os.path.join(_TEST_DATA_PATH,
                                                   'test_db.yaml'))
    self.pattern = self.database.pattern

  def testGetFieldsBitLength(self):
    length = self.pattern.GetFieldsBitLength()
    self.assertEquals(1, length['audio_codec'])
    self.assertEquals(2, length['battery'])
    self.assertEquals(0, length['bluetooth'])
    self.assertEquals(0, length['camera'])
    self.assertEquals(1, length['cellular'])
    self.assertEquals(0, length['chipset'])
    self.assertEquals(3, length['cpu'])
    self.assertEquals(0, length['display_panel'])
    self.assertEquals(1, length['dram'])
    self.assertEquals(0, length['ec_flash_chip'])
    self.assertEquals(0, length['embedded_controller'])
    self.assertEquals(0, length['flash_chip'])
    self.assertEquals(1, length['keyboard'])
    self.assertEquals(2, length['storage'])
    self.assertEquals(0, length['touchpad'])
    self.assertEquals(0, length['tpm'])
    self.assertEquals(0, length['usb_hosts'])
    self.assertEquals(0, length['vga'])
    self.assertEquals(0, length['wireless'])
    self.assertEquals(1, length['firmware'])

    original_value = self.pattern.pattern
    self.pattern.pattern = None
    self.assertRaisesRegexp(
        HWIDException, r'Cannot get encoded field bit length with uninitialized'
        ' pattern', self.pattern.GetFieldsBitLength)
    self.pattern.pattern = original_value

  def testGetTotalBitLength(self):
    length = self.database.pattern.GetTotalBitLength()
    self.assertEquals(18, length)

    original_value = self.pattern.pattern
    self.pattern.pattern = None
    self.assertRaisesRegexp(
        HWIDException, r'Cannot get bit length with uninitialized pattern',
        self.pattern.GetTotalBitLength)
    self.pattern.pattern = original_value

  def testGetBitMapping(self):
    mapping = self.pattern.GetBitMapping()
    self.assertEquals('audio_codec', mapping[5].field)
    self.assertEquals(0, mapping[5].bit_offset)
    self.assertEquals('battery', mapping[6].field)
    self.assertEquals(0, mapping[6].bit_offset)
    self.assertEquals('battery', mapping[7].field)
    self.assertEquals(1, mapping[7].bit_offset)
    self.assertEquals('cellular', mapping[8].field)
    self.assertEquals(0, mapping[8].bit_offset)
    self.assertEquals('cpu', mapping[9].field)
    self.assertEquals(0, mapping[9].bit_offset)
    self.assertEquals('cpu', mapping[12].field)
    self.assertEquals(1, mapping[12].bit_offset)
    self.assertEquals('storage', mapping[13].field)
    self.assertEquals(0, mapping[13].bit_offset)
    self.assertEquals('storage', mapping[14].field)
    self.assertEquals(1, mapping[14].bit_offset)
    self.assertEquals('cpu', mapping[15].field)
    self.assertEquals(2, mapping[15].bit_offset)
    self.assertEquals('firmware', mapping[16].field)
    self.assertEquals(0, mapping[16].bit_offset)

    original_value = self.pattern.pattern
    self.pattern.pattern = None
    self.assertRaisesRegexp(
        HWIDException, r'Cannot construct bit mapping with uninitialized '
        'pattern', self.pattern.GetBitMapping)
    self.pattern.pattern = original_value

if __name__ == '__main__':
  unittest2.main()
