# Copyright 2014 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""A module for creating and interacting with factory test UI."""

from __future__ import print_function

import cgi
import json
import logging
import os
import traceback
import uuid

import factory_common  # pylint: disable=unused-import
from cros.factory.test.env import goofy_proxy
from cros.factory.test import event as test_event
from cros.factory.test import factory
from cros.factory.test import i18n
from cros.factory.test.i18n import _
from cros.factory.test.i18n import html_translator
from cros.factory.test.i18n import test_ui as i18n_test_ui
from cros.factory.test import session
from cros.factory.test import state
from cros.factory.utils import file_utils
from cros.factory.utils import process_utils


# Keycodes
ENTER_KEY = 13
ESCAPE_KEY = 27
SPACE_KEY = 32

_KEY_NAME_MAP = {
    ENTER_KEY: _('Enter'),
    ESCAPE_KEY: _('ESC'),
    SPACE_KEY: _('Space')
}


# HTML for spinner icon.
SPINNER_HTML_16x16 = '<img src="/images/active.gif" width=16 height=16>'


def Escape(text, preserve_line_breaks=True):
  """Escapes HTML.

  Args:
    text: The text to escape.
    preserve_line_breaks: True to preserve line breaks.
  """
  html = cgi.escape(text)
  if preserve_line_breaks:
    html = html.replace('\n', '<br>')
  return html


PASS_KEY_LABEL = i18n_test_ui.MakeI18nLabel('Press Enter to pass.')
FAIL_KEY_LABEL = i18n_test_ui.MakeI18nLabel('Press ESC to fail.')
PASS_FAIL_KEY_LABEL = PASS_KEY_LABEL + FAIL_KEY_LABEL


class UI(object):
  """Web UI for a factory test."""

  def __init__(self, css=None, setup_static_files=True):
    self.event_client = test_event.BlockingEventClient(
        callback=self._HandleEvent)
    self.test = session.GetCurrentTestPath()
    self.invocation = session.GetCurrentTestInvocation()
    self.event_handlers = {}
    self.task_hook = None
    self.static_dir_path = None

    if setup_static_files:
      self._SetupStaticFiles(os.path.realpath(traceback.extract_stack()[-2][0]))
      if css:
        self.AppendCSS(css)
    self.error_msgs = []

  def _SetupStaticFiles(self, py_script):
    # Get path to caller and register static files/directories.
    base = os.path.splitext(py_script)[0]

    # Directories we'll autoload .html and .js files from.
    autoload_bases = [base]

    # Find and register the static directory, if any.
    static_dirs = filter(os.path.exists,
                         [base + '_static',
                          os.path.join(os.path.dirname(py_script), 'static')])
    if len(static_dirs) > 1:
      raise factory.FactoryTestFailure(
          'Cannot have both of %s - delete one!' % static_dirs)
    if static_dirs:
      self.static_dir_path = static_dirs[0]
      goofy_proxy.get_rpc_proxy(url=goofy_proxy.GOOFY_SERVER_URL).RegisterPath(
          '/tests/%s' % self.test, self.static_dir_path)
      autoload_bases.append(
          os.path.join(self.static_dir_path, os.path.basename(base)))

    def GetAutoload(extension, default=''):
      autoloads = filter(os.path.exists,
                         [x + '.' + extension for x in autoload_bases])
      if not autoloads:
        return default
      if len(autoloads) > 1:
        raise factory.FactoryTestFailure(
            'Cannot have both of %s - delete one!' % autoloads)

      autoload_path = autoloads[0]
      goofy_proxy.get_rpc_proxy(url=goofy_proxy.GOOFY_SERVER_URL).RegisterPath(
          '/tests/%s/%s' % (self.test, os.path.basename(autoload_path)),
          autoload_path)
      return file_utils.ReadFile(autoload_path).decode('UTF-8')

    class AddGoofyHeaderTransformer(html_translator.BaseHTMLTransformer):
      def __init__(self, test):
        super(AddGoofyHeaderTransformer, self).__init__()
        self.test = test
        self.goofy_header = (
            '<base href="/tests/%s/">\n'
            '<link rel="stylesheet" type="text/css" href="/css/goofy.css">\n'
            '<link rel="stylesheet" type="text/css" href="/css/i18n.css">\n'
            '<link rel="stylesheet" type="text/css" href="/css/test.css">\n' % (
                self.test))
        self.head_seen = False

      def handle_starttag(self, tag, attrs):
        if tag == 'head':
          attrs = self._AddKeyValueToAttrs(attrs, 'id', 'head')
          self.head_seen = True
        elif tag == 'body' and not self.head_seen:
          self._EmitOutput('<head id="head">%s</head>' % self.goofy_header)
          self.head_seen = True
        super(AddGoofyHeaderTransformer, self).handle_starttag(tag, attrs)
        if tag == 'head':
          self._EmitOutput(self.goofy_header)

    html = GetAutoload('html', '<html><body></body></html>')
    html = AddGoofyHeaderTransformer(self.test).Run(html)
    html = html_translator.TranslateHTML(html)
    # We need to call INIT_TEST_UI instead of SET_HTML, even if the UI is
    # already initialized by goofy.py, since SET_HTML only sets the body of
    # html, and would cause the css set here be overriden by template files.
    # TODO(pihsun): Fix the SET_HTML method so we can use SET_HTML here.
    self.PostEvent(
        test_event.Event(test_event.Event.Type.INIT_TEST_UI, html=html))

    js = GetAutoload('js')
    if js:
      self.RunJS(js)

  def SetHTML(self, html, append=False, id=None):
    """Sets a HTML snippet to the UI in the test pane.

    Note that <script> tags are not allowed in SetHTML() and
    AppendHTML(), since the scripts will not be executed. Use RunJS()
    or CallJSFunction() instead.

    Args:
      html: The HTML snippet to set.
      append: Whether to append the HTML snippet.
      id: If given, writes html to the element identified by id.
    """
    # pylint: disable=redefined-builtin
    self.PostEvent(test_event.Event(test_event.Event.Type.SET_HTML,
                                    html=html, append=append, id=id))

  def AppendHTML(self, html, **kwargs):
    """Append to the UI in the test pane."""
    self.SetHTML(html, append=True, **kwargs)

  def AppendCSS(self, css):
    """Append CSS in the test pane."""
    self.AppendHTML('<style type="text/css">%s</style>' % css,
                    id='head')

  def AppendCSSLink(self, css_link):
    """Append CSS link in the test pane."""
    self.AppendHTML(
        '<link rel="stylesheet" type="text/css" href="%s">' % css_link,
        id='head')

  def RunJS(self, js, **kwargs):
    """Runs JavaScript code in the UI.

    Args:
      js: The JavaScript code to execute.
      kwargs: Arguments to pass to the code; they will be
          available in an "args" dict within the evaluation
          context.

    Example:
      ui.RunJS('alert(args.msg)', msg='The British are coming')
    """
    self.PostEvent(
        test_event.Event(test_event.Event.Type.RUN_JS, js=js, args=kwargs))

  def CallJSFunction(self, name, *args):
    """Calls a JavaScript function in the test pane.

    This is implemented by calling to RunJS, so the 'this' variable in
    JavaScript function would be 'correct'.

    For example, calling CallJSFunction('test.alert', '123') is same as calling
    RunJS('test.alert(args.arg_1)', arg_1='123'), and the 'this' when the
    'test.alert' function is running would be test instead of window.

    Args:
      name: The name of the function to execute.
      args: Arguments to the function.
    """
    keys = ['arg_%d' % i for i in range(len(args))]
    kwargs = dict(zip(keys, args))
    self.RunJS('%s(%s)' % (name, ','.join('arg.%s' % key for key in keys)),
               **kwargs)

  def AddEventHandler(self, subtype, handler):
    """Adds an event handler.

    Args:
      subtype: The test-specific type of event to be handled.
      handler: The handler to invoke with a single argument (the event object).
    """
    self.event_handlers.setdefault(subtype, []).append(handler)

  def PostEvent(self, event):
    """Posts an event to the event queue.

    Adds the test and invocation properties.

    Tests should use this instead of invoking post_event directly.
    """
    event.test = self.test
    event.invocation = self.invocation
    self.event_client.post_event(event)

  def URLForFile(self, path):
    """Returns a URL that can be used to serve a local file.

    Args:
      path: path to the local file

    Returns:
      url: A (possibly relative) URL that refers to the file
    """
    return goofy_proxy.get_rpc_proxy(
        url=goofy_proxy.GOOFY_SERVER_URL).URLForFile(path)

  def GetStaticDirectoryPath(self):
    """Gets static directory os path.

    Returns:
      OS path for static directory; Return None if no static directory.
    """
    return self.static_dir_path

  def Pass(self):
    """Passes the test."""
    self.PostEvent(test_event.Event(test_event.Event.Type.END_TEST,
                                    status=factory.TestState.PASSED))

  def Fail(self, error_msg):
    """Fails the test immediately."""
    self.PostEvent(test_event.Event(test_event.Event.Type.END_TEST,
                                    status=factory.TestState.FAILED,
                                    error_msg=error_msg))

  def FailLater(self, error_msg):
    """Appends a error message to the error message list.

    This would cause the test to fail when Run() finished.
    """
    self.error_msgs.append(error_msg)

  def RunInBackground(self, target):
    """Run a function in background daemon thread.

    Pass the test if the function ends without exception, and fails the test if
    there's any exception raised.
    """
    def _target():
      try:
        target()
        self.Pass()
      except Exception:
        self.Fail(traceback.format_exc())
    process_utils.StartDaemonThread(target=_target)

  def Run(self, on_finish=None):
    """Runs the test UI, waiting until the test completes.

    Args:
      on_finish: Callback function when UI ends. This can be used to notify
          the test for necessary clean-up (e.g. terminate an event loop.)
    """

    event = self.event_client.wait(
        lambda event:
        (event.type == test_event.Event.Type.END_TEST and
         event.invocation == self.invocation and
         event.test == self.test))
    logging.info('Received end test event %r', event)
    if self.task_hook:
      # Let task have a chance to do its clean up work.
      # pylint: disable=protected-access
      self.task_hook._Finish(getattr(event, 'error_msg', ''), abort=True)
    self.event_client.close()

    try:
      if event.status == factory.TestState.PASSED and not self.error_msgs:
        pass
      elif event.status == factory.TestState.FAILED or self.error_msgs:
        error_msg = getattr(event, 'error_msg', '')
        if self.error_msgs:
          error_msg += '\n'.join([''] + self.error_msgs)

        raise factory.FactoryTestFailure(error_msg)
      else:
        raise ValueError('Unexpected status in event %r' % event)
    finally:
      if on_finish:
        on_finish()

  def BindStandardKeys(self, bind_pass_keys=True, bind_fail_keys=True):
    """Binds standard pass and/or fail keys.

    Args:
      bind_pass_keys: True if binding pass keys, including enter, space,
          and 'P'.
      bind_fail_keys: True if binding fail keys, including ESC and 'F'.
    """
    items = []
    virtual_key_items = []
    if bind_pass_keys:
      items.extend([(key, 'window.test.pass()') for key in [SPACE_KEY, 'P']])
      virtual_key_items.extend([(ENTER_KEY, 'window.test.pass()')])
    if bind_fail_keys:
      items.extend([('F', 'window.test.fail()')])
      virtual_key_items.extend([(ESCAPE_KEY, 'window.test.fail()')])
    self.BindKeysJS(items, virtual_key=False)
    self.BindKeysJS(virtual_key_items, virtual_key=True)

  def _GetKeyName(self, key_code):
    """Get i18n names to be displayed for key_code.

    Args:
      key: An integer character code.
    """
    return _KEY_NAME_MAP.get(key_code, i18n.NoTranslation(chr(key_code)))

  def BindKeysJS(self, items, once=False, virtual_key=True):
    """Binds keys to JavaScript code.

    Args:
      items: A list of tuples (key, js), where
        key: The key to bind (if a string), or an integer character code.
        js: The JavaScript to execute when pressed.
      once: If true, the keys would be unbinded after first key press.
      virtual_key: If true, also show a button on screen.
    """
    js_list = []
    for key, js in items:
      key_code = key if isinstance(key, int) else ord(key)
      if chr(key_code).islower():
        logging.warn('Got BindKey with lowercase character key %r, but '
                     "javascript's keycode is always uppercase. Please "
                     'fix it.', chr(key_code))
        key_code = ord(chr(key_code).upper())

      if once:
        js = 'window.test.unbindKey(%d);' % key_code + js
        if virtual_key:
          js = 'window.test.removeVirtualkey(%d);' % key_code + js
      js_list.append('window.test.bindKey(%d, function(event) { %s });' %
                     (key_code, js))
      if virtual_key:
        key_name = self._GetKeyName(key_code)
        js_list.append('window.test.addVirtualkey(%d, %s);' %
                       (key_code, json.dumps(key_name)))
    self.RunJS(''.join(js_list))

  def BindKeyJS(self, key, js, once=False, virtual_key=True):
    """Sets a JavaScript function to invoke if a key is pressed.

    Args:
      key: The key to bind (if a string), or an integer character code.
      js: The JavaScript to execute when pressed.
      once: If true, the key would be unbinded after first key press.
      virtual_key: If true, also show a button on screen.
    """
    self.BindKeysJS([(key, js)], once=once, virtual_key=virtual_key)

  def BindKey(self, key, handler, args=None, once=False, virtual_key=True):
    """Sets a key binding to invoke the handler if the key is pressed.

    Args:
      key: The key to bind.
      handler: The handler to invoke with a single argument (the event
          object).
      args: The arguments to be passed to the handler in javascript,
          which would be json-serialized.
      once: If true, the key would be unbinded after first key press.
      virtual_key: If true, also show a button on screen.
    """
    uuid_str = str(uuid.uuid4())
    args = json.dumps(args) if args is not None else '{}'
    self.AddEventHandler(uuid_str, handler)
    self.BindKeyJS(key, 'test.sendTestEvent("%s", %s);' % (uuid_str, args),
                   once=once, virtual_key=virtual_key)

  def UnbindKey(self, key):
    """Removes a key binding in frontend Javascript.

    Args:
      key: The key to unbind.
    """
    key_code = key if isinstance(key, int) else ord(key)
    self.RunJS('window.test.unbindKey(%d); window.test.removeVirtualkey(%d);' %
               (key_code, key_code))

  def _HandleEvent(self, event):
    """Handles an event sent by a test UI."""
    if (event.type == test_event.Event.Type.TEST_UI_EVENT and
        event.test == self.test and
        event.invocation == self.invocation):
      for handler in self.event_handlers.get(event.subtype, []):
        try:
          handler(event)
        except Exception as e:
          self.Fail(str(e))

  def GetUILocale(self):
    """Returns current enabled locale in UI."""
    return state.get_shared_data('ui_locale')

  def PlayAudioFile(self, audio_file):
    """Plays an audio file in the given path."""
    js = """
        var audio_element = new Audio("%s");
        audio_element.addEventListener(
            "canplaythrough",
            function () {
              audio_element.play();
            });
    """ % os.path.join('/sounds', audio_file)
    self.RunJS(js)

  def SetFocus(self, element_id):
    """Set focus to the element specified by element_id"""
    self.RunJS('document.getElementById("%s").focus()' % element_id)

  def SetSelected(self, element_id):
    """Set the specified element as selected"""
    self.RunJS('document.getElementById("%s").select()' % element_id)

  def Alert(self, text):
    """Show an alert box."""
    self.CallJSFunction('test.invocation.goofy.alert', text)


class DummyUI(object):
  """Dummy UI for offline test."""

  def __init__(self, test):
    self.test = test

  def Run(self):
    pass

  def Pass(self):
    logging.info('ui.Pass called. Wait for the test finishes by itself.')

  def Fail(self, msg):
    self.test.fail(msg)

  def BindKeyJS(self, _key, _js):
    logging.info('Ignore setting JS in dummy UI')

  def AddEventHandler(self, _event, _func):
    logging.info('Ignore setting Event Handler in dummy UI')
