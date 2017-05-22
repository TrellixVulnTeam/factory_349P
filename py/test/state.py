#!/usr/bin/env python
# Copyright (c) 2012 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.


"""This module handles factory test states (status) and shared persistent data.
"""


from __future__ import print_function

from jsonrpclib import jsonclass
import logging
import os
import shutil
import threading

import factory_common  # pylint: disable=unused-import
from cros.factory.test.env import paths
from cros.factory.test import event
from cros.factory.test.env import goofy_proxy
from cros.factory.test import factory
from cros.factory.test.rules import privacy
from cros.factory.utils import shelve_utils
from cros.factory.utils import sync_utils
from cros.factory.utils import type_utils


# TODO(shunhsingou): Remove the following legacy code.
# Support legacy code. Now the port and address information is defined in
# goofy_proxy module instead of here.
DEFAULT_FACTORY_STATE_PORT = goofy_proxy.DEFAULT_GOOFY_PORT
DEFAULT_FACTORY_STATE_ADDRESS = goofy_proxy.DEFAULT_GOOFY_ADDRESS

DEFAULT_FACTORY_STATE_FILE_PATH = paths.GetStateRoot()

POST_SHUTDOWN_TAG = '%s.post_shutdown'

# Key for device data.  This is a dictionary of accumulated data usually from
# shopfloor calls with information about the configuration of the device.
KEY_DEVICE_DATA = 'device'

KEY_SERIAL_NUMBER = 'serial_number'


def clear_state(state_file_path=DEFAULT_FACTORY_STATE_FILE_PATH):
  """Clears test state (removes the state file path).

  Args:
    state_file_path: Path to state; uses the default path if None.
  """
  logging.warn('Clearing state file path %s', state_file_path)
  if os.path.exists(state_file_path):
    shutil.rmtree(state_file_path)


# TODO(shunhsingou): move goofy or dut related functions to goofy_rpc so we can
# really separate them.
@type_utils.UnicodeToStringClass
class FactoryState(object):
  """The core implementation for factory state control.

  The major provided features are:
  SHARED DATA
    You can get/set simple data into the states and share between all tests.
    See get_shared_data(name) and set_shared_data(name, value) for more
    information.

  TEST STATUS
    To track the execution status of factory auto tests, you can use
    get_test_state, get_test_states methods, and update_test_state
    methods.

  All arguments may be provided either as strings, or as Unicode strings in
  which case they are converted to strings using UTF-8. All returned values
  are strings (not Unicode).

  This object is thread-safe.

  See help(FactoryState.[methodname]) for more information.
  """

  def __init__(self, state_file_path=None):
    """Initializes the state server.

    Parameters:
      state_file_path:  External file to store the state information.
    """
    state_file_path = state_file_path or DEFAULT_FACTORY_STATE_FILE_PATH
    if not os.path.exists(state_file_path):
      os.makedirs(state_file_path)
    self._tests_shelf = shelve_utils.OpenShelfOrBackup(
        state_file_path + '/tests')
    self._data_shelf = shelve_utils.OpenShelfOrBackup(
        state_file_path + '/data')
    self._lock = threading.RLock()

    if factory.TestState not in jsonclass.supported_types:
      jsonclass.supported_types.append(factory.TestState)

  @sync_utils.Synchronized
  def close(self):
    """Shuts down the state instance."""
    for shelf in [self._tests_shelf,
                  self._data_shelf]:
      try:
        shelf.close()
      except:  # pylint: disable=bare-except
        logging.exception('Unable to close shelf')

  @sync_utils.Synchronized
  def update_test_state(self, path, **kw):
    """Updates the state of a test.

    See factory.TestState.update for the allowable keyword arguments.

    Args:
      path: The path to the test (see FactoryTest for a description
          of test paths).
      kw: See factory.TestState.update for allowable arguments (e.g.,
          status and increment_count).

    Returns:
      A tuple containing the new state, and a boolean indicating whether the
      state was just changed.
    """
    state = self._tests_shelf.get(path)
    old_state_repr = repr(state)
    changed = False

    if not state:
      changed = True
      state = factory.TestState()

    changed = changed | state.update(**kw)  # Don't short-circuit

    if changed:
      logging.debug('Updating test state for %s: %s -> %s',
                    path, old_state_repr, state)
      self._tests_shelf[path] = state
      self._tests_shelf.sync()

    return state, changed

  @sync_utils.Synchronized
  def get_test_state(self, path):
    """Returns the state of a test."""
    return self._tests_shelf[path]

  @sync_utils.Synchronized
  def get_test_paths(self):
    """Returns a list of all tests' paths."""
    return self._tests_shelf.keys()

  @sync_utils.Synchronized
  def get_test_states(self):
    """Returns a map of each test's path to its state."""
    return dict(self._tests_shelf)

  @sync_utils.Synchronized
  def clear_test_state(self):
    """Clears all test state."""
    self._tests_shelf.clear()

  @sync_utils.Synchronized
  def set_shared_data(self, *key_value_pairs):
    """Sets shared data items.

    Args:
      key_value_pairs: A series of alternating keys and values
          (k1, v1, k2, v2...). In the simple case this can just
          be a single key and value.
    """
    assert len(key_value_pairs) % 2 == 0, repr(key_value_pairs)
    for i in range(0, len(key_value_pairs), 2):
      self._data_shelf[key_value_pairs[i]] = key_value_pairs[i + 1]
    self._data_shelf.sync()

  @sync_utils.Synchronized
  def get_shared_data(self, key, optional=False):
    """Retrieves a shared data item.

    Args:
      key: The key whose value to retrieve.
      optional: True to return None if not found; False to raise a KeyError.
    """
    if optional:
      return self._data_shelf.get(key)
    else:
      return self._data_shelf[key]

  @sync_utils.Synchronized
  def has_shared_data(self, key):
    """Returns if a shared data item exists."""
    return key in self._data_shelf

  @sync_utils.Synchronized
  def del_shared_data(self, key, optional=False):
    """Deletes a shared data item.

    Args:
      key: The key whose value to retrieve.
      optional: False to raise a KeyError if not found.
    """
    try:
      del self._data_shelf[key]
    except KeyError:
      if not optional:
        raise

  @sync_utils.Synchronized
  def update_shared_data_dict(self, key, new_data):
    """Updates values a shared data item whose value is a dictionary.

    This is roughly equivalent to

      data = get_shared_data(key) or {}
      data.update(new_data)
      set_shared_data(key, data)
      return data

    except that it is atomic.

    Args:
      key: The key for the data item to update.
      new_data: A dictionary of items to update.

    Returns:
      The updated value.
    """
    data = self._data_shelf.get(key, {})
    data.update(new_data)
    self._data_shelf[key] = data
    return data

  @sync_utils.Synchronized
  def delete_shared_data_dict_item(self, shared_data_key,
                                   delete_keys, optional):
    """Deletes items from a shared data item whose value is a dict.

    This is roughly equivalent to

      data = get_shared_data(shared_data_key) or {}
      for key in delete_keys:
        try:
          del data[key]
        except KeyError:
          if not optional:
            raise
      set_shared_data(shared_data_key, data)
      return data

    except that it is atomic.

    Args:
      shared_data_key: The key for the data item to update.
      delete_keys: A list of keys to delete from the dict.
      optional: False to raise a KeyError if not found.

    Returns:
      The updated value.
    """
    data = self._data_shelf.get(shared_data_key, {})
    for key in delete_keys:
      try:
        del data[key]
      except KeyError:
        if not optional:
          raise
    self._data_shelf[shared_data_key] = data
    return data

  @sync_utils.Synchronized
  def append_shared_data_list(self, key, new_item):
    """Appends an item to a shared data item whose value is a list.

    This is roughly equivalent to

      data = get_shared_data(key) or []
      data.append(new_item)
      set_shared_data(key, data)
      return data

    except that it is atomic.

    Args:
      key: The key for the data item to append.
      new_item: The item to be appended.

    Returns:
      The updated value.
    """
    data = self._data_shelf.get(key, [])
    data.append(new_item)
    self._data_shelf[key] = data
    return data


def get_instance(address=None, port=None):
  """Gets an instance (for client side) to access the state server.

  Args:
    address: Address of the server to be connected.
    port: Port of the server to be connected.

  Returns:
    :rtype: cros.factory.test.state.FactoryState

    An object with all public functions from FactoryState.
    See help(FactoryState) for more information.
  """
  return goofy_proxy.get_rpc_proxy(
      address, port, goofy_proxy.STATE_URL)


# ---------------------------------------------------------------------------
# Helper functions for shared data
def get_shared_data(key, default=None):
  if not get_instance().has_shared_data(key):
    return default
  return get_instance().get_shared_data(key)


def set_shared_data(*key_value_pairs):
  return get_instance().set_shared_data(*key_value_pairs)


def has_shared_data(key):
  return get_instance().has_shared_data(key)


def del_shared_data(key):
  return get_instance().del_shared_data(key)


# ---------------------------------------------------------------------------
# Helper functions for device data
def GetDeviceData():
  """Returns the accumulated dictionary of device data."""
  return get_shared_data(KEY_DEVICE_DATA, {})


def DeleteDeviceData(delete_keys, post_update_event=True, optional=False):
  """Returns the accumulated dictionary of device data.

  Args:
    delete_keys: A list of keys to be deleted.
    post_update_event: If True, posts an UPDATE_SYSTEM_INFO event to
        update the test list.
    optional: False to raise a KeyError if not found.

  Returns:
    The updated dictionary.
  """
  logging.info('Deleting device data: %s', delete_keys)
  data = get_instance().delete_shared_data_dict_item(
      KEY_DEVICE_DATA, delete_keys, optional)
  if 'serial_number' in delete_keys:
    SetSerialNumber(None)
  logging.info('Updated device data; complete device data is now %s',
               privacy.FilterDict(data))
  if post_update_event:
    with event.EventClient() as event_client:
      event_client.post_event(event.Event(event.Event.Type.UPDATE_SYSTEM_INFO))
  return data


def UpdateDeviceData(new_device_data, post_update_event=True):
  """Returns the accumulated dictionary of device data.

  Args:
    new_device_data: A dict with key/value pairs to update.  Old values
        are overwritten.
    post_update_event: If True, posts an UPDATE_SYSTEM_INFO event to
        update the test list.

  Returns:
    The updated dictionary.
  """
  logging.info('Updating device data: setting %s',
               privacy.FilterDict(new_device_data))
  data = get_instance().update_shared_data_dict(
      KEY_DEVICE_DATA, new_device_data)
  logging.info('Updated device data; complete device data is now %s',
               privacy.FilterDict(data))
  if post_update_event:
    with event.EventClient() as event_client:
      event_client.post_event(event.Event(event.Event.Type.UPDATE_SYSTEM_INFO))
  return data


# ---------------------------------------------------------------------------
# Helper functions for serial numbers
def SetSerialNumber(serial_number):
  UpdateDeviceData({KEY_SERIAL_NUMBER: serial_number})


def GetSerialNumber():
  return GetDeviceData().get(KEY_SERIAL_NUMBER)


class StubFactoryState(FactoryState):
  class InMemoryShelf(dict):
    def sync(self):
      pass

    def close(self):
      pass

  def __init__(self):  # pylint: disable=super-init-not-called
    self._tests_shelf = self.InMemoryShelf()
    self._data_shelf = self.InMemoryShelf()

    self._lock = threading.RLock()
