# Copyright 2016 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from __future__ import print_function

from jsonrpclib import SimpleJSONRPCServer

import datetime
import logging
import os
import threading
import time

import instalog_common  # pylint: disable=W0611
from instalog import plugin_sandbox
from instalog import plugin_base


# Possible daemon states.
STARTING = 'STARTING'
UP = 'UP'
STOPPING = 'STOPPING'
DOWN = 'DOWN'


# Fix for bug b/30904731: Access datetime.datetime.strptime.  Otherwise,
# threads may sometimes raise the exception `AttributeError: _strptime_time`.
datetime.datetime.strptime


class Instalog(plugin_sandbox.CoreAPI):

  def __init__(self, node_id, data_dir, cli_hostname, cli_port, buffer_plugin,
               input_plugins=None, output_plugins=None):
    """Constructor.

    Args:
      node_id: ID of this Instalog node.
      data_dir: Path to Instalog's state directory.  Plugin state directories
                will be stored here.
      cli_hostname: Hostname used for the CLI RPC server.
      cli_port: Port used for the CLI RPC server.
      buffer_plugin: Configuration dict for the buffer plugin.  The `plugin`
                     key should point to the plugin filename.
      input_plugins: List of configuration dicts for input plugins.  The
                     `plugin` key should point to the plugin filename.
      output_plugins: List of configuration dicts for output plugins.  The
                      `plugin` key should point to the plugin filename.
    """
    # Ensure that plugin IDs don't overlap across input and output.
    if any([plugin_id in output_plugins for plugin_id in input_plugins]):
      raise ValueError

    self._rpc_lock = threading.Lock()
    self._state = DOWN

    # Store the node ID.
    self._node_id = node_id

    # Ensure we have a working data directory.
    self._data_dir = data_dir
    if not os.path.exists(self._data_dir):
      os.makedirs(self._data_dir)

    # Create plugin sandboxes.
    self._buffer = self._ConfigEntryToSandbox(
        plugin_base.BufferPlugin, 'buffer', buffer_plugin)
    self._plugins = {}
    self._plugins.update(self._ConfigEntriesToSandboxes(
        plugin_base.InputPlugin, input_plugins))
    self._plugins.update(self._ConfigEntriesToSandboxes(
        plugin_base.OutputPlugin, output_plugins))

    # Start the RPC server.
    self._rpc_server = SimpleJSONRPCServer.SimpleJSONRPCServer(
        (cli_hostname, cli_port))
    self._rpc_server.register_function(self.IsRunning)
    self._rpc_server.register_function(self.Stop)
    self._rpc_thread = threading.Thread(target=self._rpc_server.serve_forever)
    self._rpc_thread.start()

  def _ShutdownRPCServer(self):
    def ShutdownThread():
      self._rpc_server.shutdown()
      self._rpc_server.server_close()
    t = threading.Thread(target=ShutdownThread)
    t.start()

  def _ConfigEntryToSandbox(self, superclass, plugin_id, config):
    """Parses configuration for a particular plugin entry.

    Returns:
      PluginSandbox object representing the plugin.

    Raises:
      ConfigError if the config dict does not include the plugin module to load.
    """
    # The plugin type is included along with its configuration.  Extract it.
    if not isinstance(config, dict) or 'plugin' not in config:
      raise plugin_base.ConfigError(
          'Plugin %s must have a config dictionary which includes the key '
          '`plugin` to specify which plugin module to load' % plugin_id)
    plugin_type = config.pop('plugin')

    return plugin_sandbox.PluginSandbox(
        plugin_type=plugin_type,
        plugin_id=plugin_id,
        superclass=superclass,
        config=config,
        core_api=self)

  def _ConfigEntriesToSandboxes(self, superclass, entries):
    plugins = {}
    for plugin_id, plugin_config in entries.iteritems():
      # Parse this particular plugin entry and add to the _plugins map.
      plugin_entry = self._ConfigEntryToSandbox(
          superclass=superclass,
          plugin_id=plugin_id,
          config=plugin_config)
      plugins[plugin_id] = plugin_entry
    return plugins

  def _StartBuffer(self):
    logging.info('Starting buffer...')
    self._buffer.Start(True)
    self._SyncConsumerList()

  def _SyncConsumerList(self):
    """Synchronizes consumer list with buffer."""
    consumers = [plugin.plugin_id for plugin in self._plugins.values()
                 if plugin.GetSuperclass() is plugin_base.OutputPlugin]
    consumers.append('__instalog__')
    buffer_consumers = self._buffer.CallPlugin('ListConsumers')
    logging.info('Syncing consumer lists')
    logging.debug('Our consumer list: %s', consumers)
    logging.debug('Buffer consumer list: %s', buffer_consumers)
    for c in buffer_consumers:
      if c not in consumers:
        self._buffer.CallPlugin('RemoveConsumer', c)
    for c in consumers:
      if c not in buffer_consumers:
        self._buffer.CallPlugin('AddConsumer', c)

  def Run(self):
    try:
      self._state = STARTING
      self._Start()
      plugin_states = {}
      for plugin in self._plugins.values():
        plugin_states[plugin] = plugin.GetState()
      while self._state not in (STOPPING, DOWN):
        for plugin in self._plugins.values():
          plugin.AdvanceState()
          if plugin_states[plugin] != plugin.GetState():
            logging.info('Plugin %s changed state from %s to %s',
                         plugin.plugin_id, plugin_states[plugin],
                         plugin.GetState())
          plugin_states[plugin] = plugin.GetState()
        time.sleep(1)
    except Exception as e:
      logging.exception(e)

    # In case there was some error in the Run function (exception or otherwise),
    # call Stop at the end just in case.
    self.Stop()
    logging.warning('Stopped')

  def _Start(self):
    logging.info('Starting buffer...')
    self._StartBuffer()
    logging.info('Started buffer')

    for plugin in self._plugins.values():
      logging.info('Starting %s...', plugin.plugin_id)
      plugin.Start()
    for plugin in self._plugins.values():
      plugin.AdvanceState(True)
      logging.info('Started %s', plugin.plugin_id)

  def IsRunning(self):
    with self._rpc_lock:
      return self._state in (UP, STOPPING)

  def Stop(self):
    if self._state in (STOPPING, DOWN):
      return
    self._ShutdownRPCServer()
    with self._rpc_lock:
      self._state = STOPPING
      for plugin in self._plugins.values():
        if plugin.IsLoaded():
          logging.info('Stopping %s...', plugin.plugin_id)
          plugin.Stop()

      for plugin in self._plugins.values():
        plugin.AdvanceState(True)
        logging.info('Stopped %s', plugin.plugin_id)

      logging.info('Stopping buffer...')
      self._buffer.Stop()
      logging.info('Stopped buffer')
      self._state = DOWN

  ############################################################
  # Functions below implement plugin_base.CoreAPI.
  ############################################################

  def GetDataDir(self, plugin):
    """Returns the directory used to store plugin data.

    Args:
      plugin: PluginSandbox object requesting plugin data directory.

    Returns:
      Path to plugin data directory.
    """
    data_dir = os.path.join(self._data_dir, plugin.plugin_id)
    if not os.path.exists(data_dir):
      os.makedirs(data_dir)
    return data_dir

  def Emit(self, plugin, events):
    """Emits given events from the specified plugin.

    Args:
      plugin: PluginSandbox object of plugin performing Emit.
      events: List of events to be emitted.

    Returns:
      True if successful, False if any failure occurred.

    Raises:
      PluginCallError if Buffer fails unexpectedly.
    """
    for event in events:
      # For events that originate from this node, add our node ID.
      if '__nodeId__' not in event:
        event['__nodeId__'] = self._node_id
    return self._buffer.CallPlugin('Produce', events)

  def NewStream(self, plugin):
    """Creates a new BufferEventStream for the specified plugin.
    Args:
      plugin: PluginSandbox object requesting BufferEventStream.

    Returns:
      Object implementing plugin_base.BufferEventStream.

    Raises:
      PluginCallError if Buffer fails unexpectedly.
    """
    return self._buffer.CallPlugin('Consume', plugin.plugin_id)
