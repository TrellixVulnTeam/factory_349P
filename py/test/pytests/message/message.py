# Copyright 2014 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Displays a message.

Description
-----------
This test displays a HTML message to the operator, and wait for the operator
pressing space key to pass the test.

If ``manual_check`` is True, the operator can also press escape key to fail the
test.

If ``seconds`` is given, the test would pass automatically after ``seconds``
seconds.

Test Procedure
--------------
When started, the test will show a message and wait for operator to press space
to pass the test, or press escape to fail the test (if ``manual_check`` is set).

Dependency
----------
None.

Examples
--------
To show a message, add this into test list::

  OperatorTest(pytest_name='message', dargs={'html': _('Hello world!')})

To show a message with some formatting, and give operator ability to fail the
test, add this into test list::

  OperatorTest(pytest_name='message', dargs={
      'html': _('Please check if the result is <b>correct</b>.'),
      'manual_check': True,
      'show_press_button_hint': True,
      'text_size': 300,
      'text_color': 'red'
  })

To show a message for 20 seconds, and automatically pass, add this into test
list::

  OperatorTest(pytest_name='message', dargs={
      'html': _('Waiting for something...'),
      'seconds': 20
  })
"""


from __future__ import print_function
import time
import unittest

import factory_common  # pylint: disable=unused-import
from cros.factory.test.i18n import arg_utils as i18n_arg_utils
from cros.factory.test.i18n import test_ui as i18n_test_ui
from cros.factory.test import test_task
from cros.factory.test import test_ui
from cros.factory.test import ui_templates
from cros.factory.utils.arg_utils import Arg


CSS_TEMPLATE = """
.message { font-size: %(text_size)s%%; color: %(text_color)s; }
.state { background-color: %(background_color)s; }
"""
_HTML_REMAIN = '<br><div id="remain"></div>'


class ShowingTask(test_task.TestTask):
  """The task to show message for seconds """
  def __init__(self, ui, seconds, manual_check):
    super(ShowingTask, self).__init__()
    self._ui = ui
    self._seconds = seconds
    self._done = False

    self._ui.BindKey(test_ui.SPACE_KEY, lambda _: self.Done())
    self._ui.BindKey(test_ui.ENTER_KEY, lambda _: self.Done())
    if manual_check:
      self._ui.BindKey(test_ui.ESCAPE_KEY, lambda _: self.Fail(None))

  def Done(self):
    self._done = True

  def Run(self):
    seconds = self._seconds
    while seconds != 0 and not self._done:
      self._ui.SetHTML(str(seconds), id='remain')
      time.sleep(1)
      seconds = seconds - 1
    self.Pass()


class MessageTest(unittest.TestCase):
  """A factory test to display a message."""
  ARGS = [
      i18n_arg_utils.I18nArg('html', 'Message in HTML'),
      Arg('text_size', str, 'size of message in percentage', default='200'),
      Arg('text_color', str, 'color of message (in CSS)', default='black'),
      Arg('background_color', str, 'background color (in CSS)',
          default='white'),
      Arg('seconds', int, 'duration to display message. '
          'Specify None to show until key press.',
          default=None, optional=True),
      Arg('manual_check', bool, 'If set to true, operator can press ESC to '
          'fail the test case.', default=False, optional=True),
      Arg('show_press_button_hint', bool, 'If set to true, will show '
          'addition message to ask operators to press the button.',
          default=False, optional=True)
  ]

  def runTest(self):
    i18n_arg_utils.ParseArg(self, 'html')

    css = (CSS_TEMPLATE %
           dict(text_size=self.args.text_size,
                text_color=self.args.text_color,
                background_color=self.args.background_color))
    ui = test_ui.UI(css=css)
    template = ui_templates.OneSection(ui)

    press_button_hint = ''
    if self.args.show_press_button_hint:
      if self.args.manual_check:
        press_button_hint = i18n_test_ui.MakeI18nLabel(
            '<div>Press <strong>Enter</strong> to continue, '
            'or <strong>ESC</strong> if things are not going right.</div>')
      else:
        press_button_hint = i18n_test_ui.MakeI18nLabel(
            '<div>Press <strong>Enter</strong> to continue.</div>')

    template.SetState(
        '<div class="state">' +
        i18n_test_ui.MakeI18nLabelWithClass(self.args.html, 'message') +
        press_button_hint +
        _HTML_REMAIN +
        '</div>')
    if self.args.seconds:
      task = ShowingTask(ui, self.args.seconds, self.args.manual_check)
      test_task.TestTaskManager(ui, [task]).Run()
    else:
      ui.BindStandardKeys(bind_fail_keys=self.args.manual_check)
      ui.Run()
