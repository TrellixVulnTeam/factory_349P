#!/usr/bin/python

# Copyright 2015 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""
This is audio utility module to setup tinymix related options.
We don't use original tinymix to get old value.
We use modified version, because the enum value is too hard to know the boundary.
The original one only have start sign before the value.
e.g. >ABC DEF GHI
In this case we don't know the value is 'ABC' or 'ABC DEF' or 'ABC DEF GHI'
So we add end sign for the modified tinymix. The value will be
>ABC DEF< GHI
in the modified version. So we can use '>' and '<' to know the
value.
"""

from __future__ import print_function

import logging
import re

import factory_common  # pylint: disable=W0611
from cros.factory.utils.process_utils import Spawn
from cros.factory.test.audio_control import base

# Configuration file is put under overlay directory and it can be customized
# for each board.
# Configuration file is using YAML nested collections format.
#
# Structure of this configuration file:
# card_index:
#   action:
#     "tinymix configuration name": "value"
#
# =============== Configuration Example ===================
# 0:
#   enable_dmic:
#     "DIGMICL Switch": "on"
#     "DIGMICR Switch": "on"
#   disable_dmic:
#     "DIGMICL Switch": "off"
#     "DIGMICR Switch": "off"
# =========================================================


class TinyalsaAudioControl(base.BaseAudioControl):
  """This class is used for setting audio related configuration.
  It reads audio.conf initially to decide how to enable/disable each
  component by tinymixer.
  """

  _RE_CARD_INDEX = re.compile(r'.*(\d+).*?\[(.+?)\]')

  def __init__(self, dut):
    super(TinyalsaAudioControl, self).__init__(dut)

  def GetCardIndexByName(self, card_name):
    """See BaseAudioControl.GetCardIndexByName"""
    output = self.CheckOutput(['cat', '/proc/asound/cards'])
    for line in output.split('\n'):
      m = self._RE_CARD_INDEX.match(line)
      if m and m.group(2) == card_name:
        return m.group(1)
    raise ValueError('device name %s is incorrect' % card_name)

  def GetMixerControls(self, name, card='0'):
    """See BaseAudioControl.GetMixerControls """
    # It's too hard to specify a name for Enum value.
    # So we provide our tinymix to get value.
    # The output looks like >value<
    command = ['tinymixget', '-D', card, name]
    lines = self.CheckOutput(command)
    # Try Enum value
    m = re.search(r'.*%s:.*>(.*)<.*' % name, lines, re.MULTILINE)
    if m:
      value = m.group(1)
      return value
    # Try Int value
    m = re.search(r'.*%s: (.*) \(range.*' % name, lines, re.MULTILINE)
    if m:
      value = m.group(1)
      return value
    # Try Bool value
    m = re.search(r'.*%s: (On|Off).*' % name, lines, re.MULTILINE)
    if m:
      value = m.group(1)
      # translate value to the control usage.
      # tinymix can't accept On/Off for SetMixer
      if value == 'Off':
        value = '0'
      elif value == 'On':
        value = '1'
      return value

    logging.info('Unable to get value for mixer control \'%s\'', name)
    return None

  def SetMixerControls(self, mixer_settings, card='0', store=True):
    """Sets all mixer controls listed in the mixer settings on card.

    Args:
      mixer_settings: A dict of mixer settings to set.
      card: The index of audio card
      store: Store the current value so it can be restored later using
        RestoreMixerControls.
    """
    logging.info('Setting mixer control values on card %s', card)
    restore_mixer_settings = dict()
    for name, value in mixer_settings.items():
      if store:
        old_value = self.GetMixerControls(name, card)
        restore_mixer_settings[name] = old_value
        logging.info('Save \'%s\' with value \'%s\' on card %s',
                     name, old_value, card)
      logging.info('Set \'%s\' to \'%s\' on card %s', name, value, card)
      command = ['tinymix', '-D', card, name, value]
      self.CheckCall(command)
    if store:
      self._restore_mixer_control_stack.append((restore_mixer_settings, card))

  def CreateAudioLoop(self, in_card, in_dev, out_card, out_dev):
    """Create an audio loop by tinyloop.
    It will put the tinyloop thread to background to prevent block current
    thread.
    Use DestroyAudioLoop to destroy the audio loop

    Args:
      in_card: input card
      in_dev: input device
      out_card: output card
      out_dev: output device
    """
    # TODO(mojahsu): try to figure out why CheckCall will be hang.
    # Now we workaround it by Spawn with ['adb', 'shell'].
    # It will have problem is the dut is not android device
    command = ['adb', 'shell',
               'tinyloop', '-iD', in_card, '-id', in_dev, '-oD', out_card,
               '-od', out_dev, '&']
    logging.info('Create tinyloop for input %s,%s output %s,%s',
                 in_card, in_dev, out_card, out_dev)
    # self.CheckCall(' '.join(command))
    # self.CheckCall(command)
    Spawn(command)

  def DestroyAudioLoop(self):
    lines = self.CheckOutput(['ps'])
    m = re.search(r'\w+\s+(\d+).*tinyloop', lines, re.MULTILINE)
    if m:
      pid = m.group(1)
      logging.info('Destroy audio loop with pid %s', pid)
      command = ['kill', pid]
      self.CheckCall(command)
    else:
      logging.info('Destroy audio loop - not found tinyloop pid')
