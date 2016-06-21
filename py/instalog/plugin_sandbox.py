# Copyright 2016 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Instalog plugin sandbox.

Loads the plugin class instance (using plugin_loader), manages the plugin's
state, and implements PluginAPI functions for the plugin.
"""

from __future__ import print_function

import inspect
import logging
import threading
import time

import instalog_common  # pylint: disable=W0611
from instalog import datatypes
from instalog import plugin_base
from instalog import plugin_loader


# The maximum number of unexpected accesses to store for debugging purposes.
# This is for both unittests and debugging purposes (assuming that the
# PluginSandbox instance can be accessed during runtime).
_UNEXPECTED_ACCESSES_MAX = 5

# Possible plugin states.
STARTING = 'STARTING'
UP = 'UP'
STOPPING = 'STOPPING'
DOWN = 'DOWN'
PAUSING = 'PAUSING'
PAUSED = 'PAUSED'
UNPAUSING = 'UNPAUSING'


# TODO(kitching): Find a better home for this class definition.
class CoreAPI(object):
  """Defines the API a sandbox should use interact with Instalog core."""

  def GetStateDir(self, plugin):
    """See Core.GetStateDir."""
    raise NotImplementedError

  def Emit(self, plugin, events):
    """See Core.Emit."""
    raise NotImplementedError

  def NewStream(self, plugin):
    """See Core.NewStream."""
    raise NotImplementedError


class PluginSandbox(plugin_base.PluginAPI):
  """Represents a running instance of a particular plugin.

  Implementation for non-PluginAPI functions is not thread-safe.  I.e., you
  should not give multiple threads access to a PluginSandbox object, and run
  Stop() and Pause() simultaneously.  Bad things will happen.  Plugins, however,
  are expected to be able to run multiple threads, and run multiple PluginAPI
  functions simultaneously.  This is expected behaviour.
  """

  # Different actions to take when a call is made into PluginAPI functions.  See
  # the _AskGatekeeper function.
  _ALLOW = 'allow'
  _WAIT = 'wait'
  _ERROR = 'error'

  # Commonly-used sets of Gatekeeper permissions.
  _GATEKEEPER_ALLOW_ALL = {
      STARTING: _ALLOW,
      UP: _ALLOW,
      STOPPING: _ALLOW,
      DOWN: _ERROR,
      PAUSING: _ALLOW,
      PAUSED: _ALLOW,
      UNPAUSING: _ALLOW}
  _GATEKEEPER_ALLOW_UP = {
      STARTING: _WAIT,
      UP: _ALLOW,
      STOPPING: _WAIT,
      DOWN: _ERROR,
      PAUSING: _WAIT,
      PAUSED: _WAIT,
      UNPAUSING: _WAIT}
  _GATEKEEPER_ALLOW_UP_PAUSING_STOPPING = {
      STARTING: _WAIT,
      UP: _ALLOW,
      STOPPING: _ALLOW,
      DOWN: _ERROR,
      PAUSING: _ALLOW,
      PAUSED: _WAIT,
      UNPAUSING: _WAIT}

  def __init__(self, plugin_type, plugin_id=None, superclass=None, config=None,
               core_api=None, _plugin_class=None):
    """Initializes the PluginSandbox.

    Args:
      plugin_type: The plugin type of this entry.  Corresponds to the filename
                   of the plugin.
      plugin_id: The unique identifier of this plugin entry.  One plugin type
                 may have multiple plugin entries with different IDs.  If
                 unspecified, will default to the same as plugin_type.
      superclass: The superclass of this plugin.  Can be one of:
                  BufferPlugin, InputPlugin, OutputPlugin.  If unspecified,
                  will allow any of the three types to be created.
      config: Configuration dict of the plugin entry.  Defaults to an empty
              dict.
      core_api: Reference to an object that implements CoreAPI, usually Core.
                Defaults to an instance of the CoreAPI interface, which will
                throw NotImplementedError when any method is called.  This may
                be acceptible for testing.
      _plugin_class: A "pre-loaded" plugin class for the plugin in question.
                     If provided, the module "loading" and "unloading" steps are
                     skipped, and the plugin class is directly initialized.  For
                     testing purposes.
    """
    self.plugin_type = plugin_type
    self.plugin_id = plugin_id or plugin_type
    self.superclass = superclass or plugin_base.Plugin
    self.config = config or {}
    self._core_api = core_api or CoreAPI()
    if not isinstance(self._core_api, CoreAPI):
      raise TypeError('Invalid CoreAPI object provided')

    # Create a logger this class to use.
    self.logger = logging.getLogger('%s.plugin_sandbox' % self.plugin_id)

    self._loader = plugin_loader.PluginLoader(
        self.plugin_type, plugin_id=self.plugin_id, superclass=self.superclass,
        config=self.config, plugin_api=self, _plugin_class=_plugin_class)
    self._plugin = None
    self._state = DOWN
    self._event_stream_map = {}

    # Store information about the last _UNEXPECTED_ACCESSES_MAX unexpected
    # accesses.
    self._unexpected_accesses = []

    self._start_thread = None
    self._main_thread = None
    self._stop_thread = None

  def _RecordUnexpectedAccess(self, plugin_ref, caller_name, stack):
    """Record an unexpected access from the plugin (i.e. in a stopped state).

    At most _UNEXPECTED_ACCESSES_MAX entries are stored in
    self._unexpected_accesses for debugging purposes.  This function is not
    thread-safe, so it is possible that unexpected accesses may be inserted
    out-of-order, or more than _UNEXPECTED_ACCESSES_MAX entries will be removed
    in the while loop.
    """
    self._unexpected_accesses.insert(0, {
        'caller_name': caller_name,
        'plugin_id': self.plugin_id,
        'plugin_ref': plugin_ref,
        'plugin_type': self.plugin_type,
        'stack': stack,
        'state': self._state,
        'timestamp': time.time()})
    while len(self._unexpected_accesses) > _UNEXPECTED_ACCESSES_MAX:
      self._unexpected_accesses.pop()

  def _AskGatekeeper(self, plugin, state_map):
    """Ensure a plugin is properly registered and in the correct state.

    Args:
      plugin: The plugin that has made the call to core.
      state_map: A map of states to their actions.  Actions can be one of:
                 self._ALLOW, self._WAIT, self._ERROR.

    Raises:
      WaitException if the plugin is currently unable to perform the
      requested operation (action is self._WAIT).

      UnexpectedAccess if the plugin instance is in some unexpected state and
      is trying to access core functionality that it should not
      (action is self._ERROR).
    """
    caller_name = inspect.stack()[1][3]
    self.logger.debug('_AskGatekeeper for plugin %s (%s) on function %s',
                      self.plugin_id, self._state, caller_name)

    # Ensure that the plugin instance is currently registered.  If the plugin
    # has previously been restarted, and some remaining threads are still
    # attempting to access core, we need to record the access for debugging
    # purposes.
    if plugin is not self._plugin:
      self._RecordUnexpectedAccess(plugin, caller_name, inspect.stack())
      self.logger.critical(
          'Plugin %s (%s) called core %s: Unexpected plugin instance',
          self.plugin_id, self._state, caller_name)
      raise plugin_base.UnexpectedAccess

    # Map the plugin's state to our action (default self._ERROR).
    action = state_map.get(self._state, self._ERROR)

    if action is self._WAIT:
      self.logger.info(
          'Plugin %s (%s) called core %s: Currently in a paused state',
          self.plugin_id, self._state, caller_name)
      raise plugin_base.WaitException

    if action is self._ERROR:
      self._RecordUnexpectedAccess(plugin, caller_name, inspect.stack())
      self.logger.info(
          'Plugin %s (%s) called core %s: Unexpected access',
          self.plugin_id, self._state, caller_name)
      raise plugin_base.UnexpectedAccess

  def _CheckStateCommand(self, allowed_states):
    """Checks to see whether a state command may be run.

    Args:
      allowed_states: A list of allowed states for this state command.

    Raises:
      StateCommandError if not allowed to use the given transition state
      command.
    """
    if not isinstance(allowed_states, list):
      allowed_states = [allowed_states]
    caller_name = inspect.stack()[1][3]
    self.logger.debug(
        '_CheckStateCommand for plugin %s (%s) on function %s',
        self.plugin_id, self._state, caller_name)
    if self._state not in allowed_states:
      raise plugin_base.StateCommandError(
          'Plugin %s (%s) called %s, but only allowed for %s'
          % (self.plugin_id, self._state, caller_name, allowed_states))

  def GetState(self):
    """Returns the current state of the plugin."""
    self.logger.debug('GetState called: %s', self._state)
    return self._state

  def IsLoaded(self):
    """Returns whether the plugin is currently loaded (not DOWN)."""
    self.logger.debug('IsLoaded called: %s', self._state)
    return self._state is not DOWN

  def _Load(self):
    """Asks the PluginLoader factory to give us a new plugin instance."""
    assert self._plugin is None
    self._plugin = self._loader.Create()

  def Start(self, sync=False):
    """Starts the plugin."""
    self._CheckStateCommand(DOWN)
    self._Load()
    self._state = STARTING
    if sync:
      self.AdvanceState(sync)

  def Stop(self, sync=False):
    """Stops the plugin."""
    self._CheckStateCommand([UP, PAUSED])
    self._state = STOPPING
    if sync:
      self.AdvanceState(sync)

  def Pause(self, sync=False):
    """Pauses the plugin."""
    self._CheckStateCommand(UP)
    self._state = PAUSING
    if sync:
      self.AdvanceState(sync)

  def Unpause(self, sync=False):
    """Unpauses the plugin."""
    self._CheckStateCommand(PAUSED)
    self._state = UNPAUSING
    if sync:
      self.AdvanceState(sync)

  def TogglePause(self, sync=False):
    """Toggles the paused state on the plugin."""
    self._CheckStateCommand([UP, PAUSED])
    if self._state is UP:
      self.Pause(sync)
    elif self._state is PAUSED:
      self.Unpause(sync)

  def AdvanceState(self, sync=False):
    """Runs state machine transitions.

    Needs an external thread to periodically run AdvanceState to run any pending
    actions to take the plugin into its next requested state.  For example, if
    the state has been set to STOPPING, AdvanceState takes care of running the
    appropriate actions and taking the plugin into the STOPPED state.

    Args:
      sync: Whether or not the call should be synchronous.  E.g. if the state
            has been set to STOPPING, AdvanceState won't return until the plugin
            has been stopped.
    """
    def SpawnFn(fn, sync=False):
      t = threading.Thread(target=fn)
      t.start()
      if sync:
        t.join()
      return t

    # If we are in a stage where the main thread should be running, but it has
    # stopped, something must have gone wrong.  Force the plugin into a
    # STOPPING state.
    # TODO(kitching): Come up with a better way of differentiating plugins which
    #                 Main, and those which do not.
    if (self._state in (UP, PAUSING, PAUSED) and
        'Main' in self._plugin.__class__.__dict__ and
        not self._main_thread.is_alive()):
      self.logger.debug('AdvanceState unexpected main thread dead')
      self._state = STOPPING

    if self._state is STARTING:
      self.logger.debug('AdvanceState on STARTING')
      if not self._start_thread:
        self._start_thread = SpawnFn(self._plugin.Start, sync)
      if self._start_thread and not self._start_thread.is_alive():
        self._start_thread = None
        self._main_thread = SpawnFn(self._plugin.Main)
        self._state = UP

    elif self._state is STOPPING:
      self.logger.debug('AdvanceState on STOPPING')
      if self._main_thread and sync:
        self._main_thread.join()
      if self._main_thread and not self._main_thread.is_alive():
        self._main_thread = None
        self._stop_thread = SpawnFn(self._plugin.Stop, sync)
      if self._stop_thread and not self._stop_thread.is_alive():
        self._stop_thread = None
        self._plugin = None
        self._state = DOWN

    elif self._state is PAUSING:
      self.logger.debug('AdvanceState on PAUSING')
      if not self._event_stream_map:
        self._state = PAUSED

    elif self._state is UNPAUSING:
      self.logger.debug('AdvanceState on UNPAUSING')
      self._state = UP

  ############################################################
  # Functions below implement plugin_base.PluginAPI.
  ############################################################

  def GetStateDir(self, plugin):
    """See PluginAPI.GetStateDir."""
    self._AskGatekeeper(plugin, self._GATEKEEPER_ALLOW_ALL)
    self.logger.debug('GetStateDir called with state=%s', self._state)
    return self._core_api.GetStateDir(self)

  def IsStopping(self, plugin):
    """See PluginAPI.IsStopping."""
    self._AskGatekeeper(plugin, self._GATEKEEPER_ALLOW_ALL)
    self.logger.debug('IsStopping called with state=%s', self._state)
    return self._state is STOPPING

  def Emit(self, plugin, events):
    """See PluginAPI.Emit."""
    self._AskGatekeeper(plugin, self._GATEKEEPER_ALLOW_UP)
    self.logger.debug('Emit called with state=%s', self._state)
    self._core_api.Emit(self, events)
    return self._state is UP

  def NewStream(self, plugin):
    """See PluginAPI.NewStream."""
    self._AskGatekeeper(plugin, self._GATEKEEPER_ALLOW_UP_PAUSING_STOPPING)
    self.logger.debug('NewStream called with state=%s', self._state)
    buffer_stream = self._core_api.NewStream(self)
    plugin_stream = datatypes.EventStream(plugin, self)
    self._event_stream_map[plugin_stream] = buffer_stream
    return plugin_stream

  def EventStreamNext(self, plugin, plugin_stream):
    """See PluginAPI.EventStreamNext."""
    self._AskGatekeeper(plugin, self._GATEKEEPER_ALLOW_UP)
    self.logger.debug('EventStreamNext called with state=%s', self._state)
    if plugin_stream not in self._event_stream_map:
      raise plugin_base.UnexpectedAccess
    buffer_stream = self._event_stream_map[plugin_stream]
    return buffer_stream.Next()

  def EventStreamCommit(self, plugin, plugin_stream):
    """See PluginAPI.EventStreamCommit."""
    self._AskGatekeeper(plugin, self._GATEKEEPER_ALLOW_UP_PAUSING_STOPPING)
    self.logger.debug('EventStreamCommit called with state=%s', self._state)
    self._RecordUnexpectedAccess(plugin, 'EventStreamAbort', inspect.stack())
    if plugin_stream not in self._event_stream_map:
      raise plugin_base.UnexpectedAccess
    return self._event_stream_map.pop(plugin_stream).Commit()

  def EventStreamAbort(self, plugin, plugin_stream):
    """See PluginAPI.EventStreamAbort."""
    self._AskGatekeeper(plugin, self._GATEKEEPER_ALLOW_UP_PAUSING_STOPPING)
    self.logger.debug('EventStreamAbort called with state=%s', self._state)
    self._RecordUnexpectedAccess(plugin, 'EventStreamAbort', inspect.stack())
    if plugin_stream not in self._event_stream_map:
      raise plugin_base.UnexpectedAccess
    del self._event_stream_map[plugin_stream]
    return self._event_stream_map.pop(plugin_stream).Abort()
