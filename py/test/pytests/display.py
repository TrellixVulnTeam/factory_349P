# Copyright 2012 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""A factory test to test the function of display."""

import os

import factory_common  # pylint: disable=unused-import
from cros.factory.test.i18n import _
from cros.factory.test.i18n import translation
from cros.factory.test import test_ui
from cros.factory.utils.arg_utils import Arg
from cros.factory.utils import file_utils


# The _() is necessary for pygettext to get translatable strings correctly.
_ALL_ITEMS = [
    _('solid-gray-170'),
    _('solid-gray-127'),
    _('solid-gray-63'),
    _('solid-red'),
    _('solid-green'),
    _('solid-blue'),
    _('solid-white'),
    _('solid-gray'),
    _('solid-black'),
    _('grid'),
    _('rectangle'),
    _('gradient-red'),
    _('gradient-green'),
    _('gradient-blue'),
    _('gradient-white'),
    _('image-complex'),
    _('image-black'),
    _('image-white'),
    _('image-crosstalk-black'),
    _('image-crosstalk-white'),
    _('image-gray-63'),
    _('image-gray-127'),
    _('image-gray-170'),
    _('image-horizontal-rgbw'),
    _('image-vertical-rgbw')
]
_ALL_ITEMS = [x[translation.DEFAULT_LOCALE] for x in _ALL_ITEMS]
_IMAGE_PREFIX = 'image-'


class DisplayTest(test_ui.TestCaseWithUI):
  """Tests the function of display.

  Properties:
    ui: test ui.
    checked: user has check the display of current subtest.
    fullscreen: the test ui is in fullscreen or not.
    static_dir: string of static file directory.
  """
  ARGS = [
      Arg('items', list,
          'Set items to be shown on screen. Available items are:\n%s\n' %
          '\n'.join('  * ``"%s"``' % x for x in _ALL_ITEMS),
          default=['solid-gray-170', 'solid-gray-127', 'solid-gray-63',
                   'solid-red', 'solid-green', 'solid-blue']),
      Arg('idle_timeout',
          int,
          'If given, the test would be start automatically, run for '
          'idle_timeout seconds, and pass itself. '
          'Note that items should contain exactly one item in this mode.',
          default=None)
  ]

  def setUp(self):
    """Initializes frontend presentation and properties."""
    self.static_dir = self.ui.GetStaticDirectoryPath()

    self.idle_timeout = self.args.idle_timeout
    if self.idle_timeout is not None and len(self.args.items) != 1:
      raise ValueError('items should have exactly one item in idle mode.')

    unknown_items = set(self.args.items) - set(_ALL_ITEMS)
    if unknown_items:
      raise ValueError('Unknown item %r in items.' % list(unknown_items))

    self.items = self.args.items
    self.images = [
        '%s.bmp' % item[len(_IMAGE_PREFIX):] for item in self.items
        if item.startswith(_IMAGE_PREFIX)
    ]
    if self.images:
      self.ExtractTestImages()
    self.ui.CallJSFunction('setupDisplayTest', self.items)
    self.checked = False
    self.fullscreen = False

  def tearDown(self):
    self.RemoveTestImages()

  def runTest(self):
    """Sets the callback function of keys."""
    if self.idle_timeout is None:
      self.ui.BindKey(test_ui.SPACE_KEY, self.OnSpacePressed)
      self.ui.BindKey(test_ui.ENTER_KEY, self.OnEnterPressed)
      self.ui.AddEventHandler('onFullscreenClicked', self.OnSpacePressed)
    else:
      # Automatically enter fullscreen mode in idle mode.
      self.ToggleFullscreen()
      self.ui.AddEventHandler('onFullscreenClicked', self.OnFailPressed)
    self.ui.BindKey(test_ui.ESCAPE_KEY, self.OnFailPressed)
    self.WaitTaskEnd(timeout=self.idle_timeout)

  def ExtractTestImages(self):
    """Extracts selected test images from test_images.tar.bz2."""
    file_utils.ExtractFile(os.path.join(self.static_dir, 'test_images.tar.bz2'),
                           self.static_dir, only_extracts=self.images)

  def RemoveTestImages(self):
    """Removes extracted image files after test finished."""
    for image in self.images:
      file_utils.TryUnlink(os.path.join(self.static_dir, image))

  def OnSpacePressed(self, event):
    """Sets self.checked to True. Calls JS function to switch display on/off."""
    del event  # Unused.
    self.ToggleFullscreen()

  def ToggleFullscreen(self):
    self.checked = True
    self.ui.CallJSFunction('window.displayTest.toggleFullscreen')
    self.fullscreen = not self.fullscreen

  def OnEnterPressed(self, event):
    """Passes the subtest only if self.checked is True."""
    del event  # Unused.
    if self.checked:
      self.ui.CallJSFunction('window.displayTest.judgeSubTest', True)
      # If the next subtest will be in fullscreen mode, checked should be True
      self.checked = self.fullscreen

  def OnFailPressed(self, event):
    """Fails the subtest only if self.checked is True."""
    del event  # Unused.
    if self.checked:
      self.ui.CallJSFunction('window.displayTest.judgeSubTest', False)
      # If the next subtest will be in fullscreen mode, checked should be True
      self.checked = self.fullscreen
