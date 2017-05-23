# -*- coding: utf-8 -*-
#
# Copyright (c) 2012 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Tests audio playback and record."""

from __future__ import print_function

import logging
import os
import random
import unittest

import factory_common  # pylint: disable=unused-import
from cros.factory.device import device_utils
from cros.factory.test import factory_task
from cros.factory.test.i18n import _
from cros.factory.test.i18n import arg_utils as i18n_arg_utils
from cros.factory.test.i18n import test_ui as i18n_test_ui
from cros.factory.test import test_ui
from cros.factory.test import ui_templates
from cros.factory.utils.arg_utils import Arg
from cros.factory.utils import file_utils
from cros.factory.utils import process_utils
from cros.factory.utils import sync_utils

_TEST_TITLE = i18n_test_ui.MakeI18nLabel('Audio Test')

_DIV_CENTER_INSTRUCTION = """
<div id='instruction-center' class='template-instruction'></div>"""
_CSS = '#pass_key {font-size:36px; font-weight:bold;}'

_INSTRUCTION_AUDIO_RANDOM_TEST = lambda device, key: i18n_test_ui.MakeI18nLabel(
    'Press the number you hear from {device} to pass the test.<br>'
    'Press "{key}" to replay.',
    device=device, key=key)

_PLAYBACK_IS_RUNNING = lambda device: i18n_test_ui.MakeI18nLabel(
    'Please wait for the {device} playback to finish.', device=device)

_SOUND_DIRECTORY = os.path.join(
    os.path.dirname(os.path.realpath(__file__)), '..', '..', 'goofy',
    'static', 'sounds')


class AudioDigitPlaybackTask(factory_task.InteractiveFactoryTask):
  """Task to verify audio playback function.

  It randomly picks a digit to play and checks if the operator presses the
  correct digit. It also prevents key-swiping cheating.
  Note: ext_display.py uses this class to test HDMI audio.

  Args:
    _dut: dut instance
    ui: cros.factory.test.test_ui object.
    port_label: Label name of audio port to output. It should be generated
        using i18n_test_ui.MakeI18nLabel to have internationalized version.
    title_id: HTML id for placing testing title.
    instruction_id: HTML id for placing instruction.
    card: audio card to output.
    device: audio device to output.
    channel: target channel. Value of 'left', 'right', 'all'. Default 'all'.
  """

  def __init__(self, _dut, ui, port_label, title_id, instruction_id, card,
               device, channel='all', sample_rate=None):
    super(AudioDigitPlaybackTask, self).__init__(ui)
    self._dut = _dut
    self._pass_digit = random.randint(0, 9)
    self._out_card = card
    self._out_device = device
    self._port_label = port_label
    self._title_id = title_id
    self._instruction_id = instruction_id
    self._channel = channel
    self._sample_rate = sample_rate

    if channel == 'left':
      self._port_label += i18n_test_ui.MakeI18nLabel(' (Left Channel)')
    elif channel == 'right':
      self._port_label += i18n_test_ui.MakeI18nLabel(' (Right Channel)')

  def _InitUI(self):
    self._ui.SetHTML(self._port_label, id=self._title_id)
    self.BindPassFailKeys(pass_key=False)

  def Run(self):
    def _PlayDigit(num, channel):
      """Plays digit sound with language from UI.

      Args:
        num: digit number to play.
      """
      self.UnbindDigitKeys()
      self._ui.SetHTML(_PLAYBACK_IS_RUNNING(self._port_label),
                       id=self._instruction_id)

      lang = self._ui.GetUILanguage()
      base_name = '%d_%s.ogg' % (num, lang)
      with file_utils.UnopenedTemporaryFile(suffix='.wav') as wav_path:
        # Prepare played .wav file
        with file_utils.UnopenedTemporaryFile(suffix='.wav') as temp_wav_path:
          # We genereate stereo sound by default. and mute one channel by sox
          # if needed.
          cmd = ['sox', os.path.join(_SOUND_DIRECTORY, base_name), '-c2']
          if self._sample_rate is not None:
            cmd += ['-r %d' % self._sample_rate]
          cmd += [temp_wav_path]
          process_utils.Spawn(cmd, log=True, check_call=True)
          if channel == 'left':
            process_utils.Spawn(
                ['sox', temp_wav_path, wav_path, 'remix', '1', '0'],
                log=True, check_call=True)
          elif channel == 'right':
            process_utils.Spawn(
                ['sox', temp_wav_path, wav_path, 'remix', '0', '1'],
                log=True, check_call=True)
          else:
            process_utils.Spawn(['mv', temp_wav_path, wav_path],
                                log=True, check_call=True)

        with self._dut.temp.TempFile() as dut_wav_path:
          self._dut.link.Push(wav_path, dut_wav_path)
          self._dut.audio.PlaybackWavFile(dut_wav_path, self._out_card,
                                          self._out_device)

      self._ui.SetHTML(
          '%s<br>%s' % (_INSTRUCTION_AUDIO_RANDOM_TEST(self._port_label, 'R'),
                        test_ui.MakePassFailKeyLabel(pass_key=False)),
          id=self._instruction_id)
      self._ui.BindKey(
          'R', lambda _: _PlayDigit(self._pass_digit, self._channel),
          once=True)
      self.BindDigitKeys(self._pass_digit)

    self._InitUI()

    _PlayDigit(self._pass_digit, self._channel)

  def Cleanup(self):
    self.UnbindDigitKeys()


class DetectHeadphoneTask(factory_task.InteractiveFactoryTask):
  """Task to wait for headphone connect/disconnect.

  Args:
    _dut: dut instance
    card: output audio card
    ui: cros.factory.test.test_ui object.
    wait_for_connect: True to wait for headphone connect. Otherwise,
        wait for disconnect.
    title_id: HTML id for placing testing title.
    instruction_id: HTML id for placing instruction.
  """

  def __init__(self, _dut, card, ui, wait_for_connect,
               title_id, instruction_id):
    super(DetectHeadphoneTask, self).__init__(ui)
    self._dut = _dut
    self._out_card = card
    self._title_id = title_id
    self._instruction_id = instruction_id
    self._wait_for_connect = wait_for_connect
    if wait_for_connect:
      self._title = i18n_test_ui.MakeI18nLabel('Connect Headphone')
      self._instruction = i18n_test_ui.MakeI18nLabel(
          'Please plug headphone in.')
    else:
      self._title = i18n_test_ui.MakeI18nLabel('Disconnect Headphone')
      self._instruction = i18n_test_ui.MakeI18nLabel('Please unplug headphone.')

  def _InitUI(self):
    self._ui.SetHTML(self._title, id=self._title_id)
    self._ui.SetHTML(
        '%s<br>%s' % (self._instruction,
                      test_ui.MakePassFailKeyLabel(pass_key=False)),
        id=self._instruction_id)
    self.BindPassFailKeys(pass_key=False, fail_later=False)

  def _CheckHeadphone(self):
    headphone_status = self._dut.audio.GetHeadphoneJackStatus(self._out_card)
    logging.info('Headphone status %s, Requre Headphone %s', headphone_status,
                 self._wait_for_connect)
    return headphone_status == self._wait_for_connect

  def Run(self):
    self._InitUI()
    sync_utils.PollForCondition(
        poll_method=self._CheckHeadphone, poll_interval_secs=0.5,
        condition_name='CheckHeadphone', timeout_secs=10)
    self.Pass()


class AudioTest(unittest.TestCase):
  """Tests audio playback

  It randomly picks a digit to play and checks if the operator presses the
  correct digit. It also prevents key-swiping cheating.
  """
  ARGS = [
      Arg('audio_conf', str, 'Audio config file path', optional=True),
      Arg('initial_actions', list, 'List of tuple (card_name, actions)', []),
      Arg('output_dev', tuple,
          'Onput ALSA device. (card_name, sub_device).'
          'For example: ("audio_card", "0").', ('0', '0')),
      i18n_arg_utils.I18nArg(
          'port_label', 'Label of audio.', default=_('Internal Speaker')),
      Arg('test_left_right', bool, 'Test left and right channel.',
          default=True),
      Arg('require_headphone', bool, 'Require headphone option', False),
      Arg('check_headphone', bool,
          'Check headphone status whether match require_headphone', False),
      Arg('sample_rate', int,
          'Required sample rate to be played by the device.',
          optional=True)
  ]

  def setUp(self):
    i18n_arg_utils.ParseArg(self, 'port_label')
    self._dut = device_utils.CreateDUTInterface()
    if self.args.audio_conf:
      self._dut.audio.ApplyConfig(self.args.audio_conf)
    # Tansfer output device format
    self._out_card = self._dut.audio.GetCardIndexByName(self.args.output_dev[0])
    self._out_device = self.args.output_dev[1]

    self._ui = test_ui.UI()
    self._template = ui_templates.TwoSections(self._ui)
    self._task_manager = None

    for card, action in self.args.initial_actions:
      card = self._dut.audio.GetCardIndexByName(card)
      self._dut.audio.ApplyAudioConfig(action, card)

  def InitUI(self):
    """Initializes UI.

    Sets test title and draw progress bar.
    """
    self._template.SetTitle(_TEST_TITLE)
    self._template.SetState(_DIV_CENTER_INSTRUCTION)
    self._template.DrawProgressBar()
    self._ui.AppendCSS(_CSS)

  def ComposeTasks(self):
    """Composes subtasks based on dargs.

    Returns:
      A list of AudioDigitPlaybackTask.
    """
    def _ComposeLeftRightTasks(tasks, args):
      kwargs = {}
      if self.args.sample_rate is not None:
        kwargs['sample_rate'] = self.args.sample_rate
      if self.args.test_left_right:
        for c in ['left', 'right']:
          kwargs['channel'] = c
          tasks.append(AudioDigitPlaybackTask(*args, **kwargs))
      else:
        tasks.append(AudioDigitPlaybackTask(*args, **kwargs))

    _TITLE_ID = 'instruction'
    _INSTRUCTION_ID = 'instruction-center'

    tasks = []
    if self.args.check_headphone:
      tasks.append(DetectHeadphoneTask(self._dut, self._out_card, self._ui,
                                       self.args.require_headphone, _TITLE_ID,
                                       _INSTRUCTION_ID))
    args = (self._dut, self._ui,
            i18n_test_ui.MakeI18nLabel(self.args.port_label),
            _TITLE_ID, _INSTRUCTION_ID, self._out_card, self._out_device)
    _ComposeLeftRightTasks(tasks, args)

    return tasks

  def tearDown(self):
    self._dut.audio.RestoreMixerControls()

  def runTest(self):
    self.InitUI()
    self._task_manager = factory_task.FactoryTaskManager(
        self._ui, self.ComposeTasks(),
        update_progress=self._template.SetProgressBarValue)
    self._task_manager.Run()
