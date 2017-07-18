#!/usr/bin/env python
#
# Copyright 2016 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Utility module to load and validate a configuration file in JSON.

Usage:
 # test.json ----------------------------------------------------------------

 {"some_config": 1}

 # test.schema.json, created from jsonschema.net ----------------------------

 {"$schema":"http://json-schema.org/draft-04/schema#","type":"object",
  "properties":{"some_config":{"type":"integer"}},"required":["some_config"]}

 # test.py ------------------------------------------------------------------

 import factory_common
 from cros.factory.utils import config_utils

 # This example will load test.json and validate using test.schema.json.

 def test_config():
   # Load the config having same name as current module.
   config = config_utils.LoadConfig()
   print(config['some_config'])

   # To override additional settings, use OverrideConfig.
   config_utils.OverrideConfig(config, {'some_config': 2})

   # To use config in dot.notation, convert with GetNamedTuple
   config_nt = config_utils.GetNamedTuple(config)
   print(config_nt.some_config)

 test_config()

 # Execution result ---------------------------------------------------------

 # python ./test.py
 1
 2
"""

from __future__ import print_function

import collections
import inspect
import json
import logging
import os
import zipimport

from . import type_utils

# To simplify portability issues, validating JSON schema is optional.
try:
  import jsonschema
  _CAN_VALIDATE_SCHEMA = True
except ImportError:
  _CAN_VALIDATE_SCHEMA = False


# Constants defined.
_CONFIG_FILE_EXT = '.json'
_SCHEMA_FILE_EXT = '.schema.json'
_CONFIG_BUILD_DIR = 'config'

# Config names in config_utils.json
_CONFIG_NAME_BUILD_DIR = 'BuildConfigDirectory'
_CONFIG_NAME_RUNTIME_DIR = 'RuntimeConfigDirectory'
_CONFIG_NAME_LOGGING = 'Logging'

# Cache of configuration for config_utils itself.
_CACHED_CONFIG_UTILS_CONFIG = None

# Dummy cache for loop dependency detection.
_DUMMY_CACHE = object()

# Special key to delete a value when overriding config.
_OVERRIDE_DELETE_KEY = '__delete__'

# Special key to replace a dict value completely without merging with base when
# overriding config.
_OVERRIDE_REPLACE_KEY = '__replace__'


def _DummyLogger(*unused_arg, **unused_kargs):
  """A dummy log function."""
  pass


def OverrideConfig(base, overrides):
  """Recursively overrides non-mapping values inside a mapping object.

  Args:
    base: A mapping object with existing data.
    overrides: A mapping to override values in base.

  Returns:
    The new mapping object with values overridden.
  """
  for k, v in overrides.iteritems():
    if isinstance(v, collections.Mapping):
      v = v.copy()
      if v.pop(_OVERRIDE_DELETE_KEY, False):
        base.pop(k, None)
      elif v.pop(_OVERRIDE_REPLACE_KEY, False):
        base[k] = OverrideConfig({}, v)
      else:
        base[k] = OverrideConfig(base.get(k, {}), v)
    else:
      base[k] = overrides[k]
  return base


def GetNamedTuple(mapping):
  """Converts a mapping object into Named Tuple recursively.

  Args:
    mapping: A mapping object to be converted.

  Returns:
    A named tuple generated from argument.
  """
  if not isinstance(mapping, collections.Mapping):
    return mapping
  new_mapping = dict((k, GetNamedTuple(v)) for k, v in mapping.iteritems())
  return collections.namedtuple('Config', new_mapping.iterkeys())(**new_mapping)


def _LoadJsonFile(file_path, logger):
  """Loads a JSON file from specified path.

  Supports loading JSON file from real file system, or a virtual path inside
  python archive (PAR).

  Returns:
    A parsed JSON object for contents in file_path argument, or None if file
    can't be found.
  """
  if os.path.exists(file_path):
    logger('config_utils: Loading from %s', file_path)
    with open(file_path) as f:
      return json.load(f)

  # file_path does not exist, but it may be a PAR virtual path.
  if '.par' in file_path.lower():
    try:
      file_dir = os.path.dirname(file_path)
      file_name = os.path.basename(file_path)
      importer = zipimport.zipimporter(file_dir)
      zip_path = os.path.join(importer.prefix, file_name)
      logger('config_utils: Loading from %s!%s', importer.archive, zip_path)
      return json.loads(importer.get_data(zip_path))
    except zipimport.ZipImportError:
      logger('config_utils: No PAR/ZIP in %s. Ignore.', file_path)
    except IOError:
      logger('config_utils: PAR path %s does not exist. Ignore.', file_path)

  return None


def _LoadRawConfig(config_dir, config_name, logger=_DummyLogger):
  """Internal function to load JSON config from specified path.

  Returns:
    A configuration object.
  """
  config_path = os.path.join(config_dir, config_name + _CONFIG_FILE_EXT)
  logger('config_utils: Checking %s', config_path)
  return _LoadJsonFile(config_path, logger)


def _LoadRawSchema(config_dir, config_name, schema_name=None,
                   logger=_DummyLogger):
  """Internal function to load JSON schema from specified path.

  Returns:
    A schema object.
  """
  if schema_name is None:
    schema_name = config_name
  schema_path = os.path.join(config_dir, schema_name + _SCHEMA_FILE_EXT)
  return _LoadJsonFile(schema_path, logger)


def _LoadConfigUtilsConfig():
  """Internal function to load the config for config_utils itself."""
  global _CACHED_CONFIG_UTILS_CONFIG  # pylint: disable=global-statement

  if _CACHED_CONFIG_UTILS_CONFIG:
    return _CACHED_CONFIG_UTILS_CONFIG

  def _NormalizePath(config, key, base):
    if not os.path.isabs(config[key]):
      config[key] = os.path.normpath(os.path.join(base, config[key]))

  def _ApplyConfig(config, key):
    config_dir = config[key] if key else module_dir
    new_config = _LoadRawConfig(config_dir, module_name)
    OverrideConfig(config, new_config or {})
    _NormalizePath(config, _CONFIG_NAME_BUILD_DIR, module_dir)
    _NormalizePath(config, _CONFIG_NAME_RUNTIME_DIR, module_dir)
    return _LoadRawSchema(config_dir, module_name)

  module_dir = os.path.realpath(os.path.dirname(__file__))
  module_name = os.path.splitext(os.path.basename(__file__))[0]

  config = {}
  schema = _ApplyConfig(config, None)
  build_schema = _ApplyConfig(config, _CONFIG_NAME_BUILD_DIR)
  runtime_schema = _ApplyConfig(config, _CONFIG_NAME_RUNTIME_DIR)

  schema = runtime_schema or build_schema or schema
  if _CAN_VALIDATE_SCHEMA:
    jsonschema.validate(config, schema)

  _CACHED_CONFIG_UTILS_CONFIG = config
  return config


def GetDefaultConfigInfo(module, module_file=None):
  """Gets the information of where is the default configuration data.

  Args:
    module: A module instance to find configuration name and path.
    module_file: fallback for module file name if module.__file__ cannot be
        retrieved.

  Returns:
    A pair of strings (name, directory) that name is the config name and
    directory is where the config should exist.
  """
  default_name = None
  default_dir = '.'

  path = (module.__file__ if module and getattr(module, '__file__') else
          module_file)

  if path:
    default_dir = os.path.dirname(path)
    default_name = os.path.splitext(os.path.basename(path))[0]
  return default_name, default_dir


def GetRuntimeConfigDirectory():
  """Returns a string for directory of runtime configuration data."""
  return _LoadConfigUtilsConfig()[_CONFIG_NAME_RUNTIME_DIR]


def GetBuildConfigDirectory():
  """Returns a string for directory of pre-build configuration data."""
  return _LoadConfigUtilsConfig()[_CONFIG_NAME_BUILD_DIR]


def _GetLogger():
  """Returns a function for logging debug messages.

  Returns logging.debug if the config_util's default config "Logging" is true,
  otherwise _DummyLogger.
  """
  return (logging.debug if _LoadConfigUtilsConfig()[_CONFIG_NAME_LOGGING] else
          _DummyLogger)


def LoadConfig(config_name=None, schema_name=None, validate_schema=True,
               default_config_dir=None, convert_to_str=True,
               allow_inherit=False, generate_depend=False):
  """Loads a configuration as mapping by given file name.

  The config files are retrieved and overridden in order:
   1. Default config directory: The arg 'default_config_dir' or the directory of
      caller module (or current folder if no caller module). If the caller
      module is a symbolic link, we search its original path first, and
      override it with the config beside the symbolic link if exists.
   2. Build config directory: The 'BuildConfigDirectory' in config_utils.json,
      should be set to 'root of project files'. Defaults to
      /usr/local/factory/py/config.
   3. Runtime config directory: The 'RuntimeConfigDirectory' in
      config_utils.json. Defaults to /var/factory/config.

  Args:
    config_name: a string for config file name (without extension) to read.
    schema_name: a string for schema file name (without extension) to read.
    validate_schema: boolean to indicate if schema should be checked.
    convert_to_str: True to convert the result from unicode to str.
    allow_inherit: if set to True, try to read 'inherit' from the
        config loaded. It should be the name of the parent config to be loaded,
        and will then be overrided by the current config. It can also be a list
        of parent config names, and will be overrided in reversed order.

        For example, if we're loading config "A" with:
        1. {"inherit": "B"}
           "B" will be loaded and overrided by "A".
        2. {"inherit": ["B", "C", "D"]},
           "D" will be loaded first, overrided by "C", and by "B",
           and then by "A".

        Note that this is done after all the directory-based overriding is
        finished.

        Schema check is performed after overriding if validate_schema is True.

    generate_depend: if allow_inherit is True and this is set to True, will
        collect all dependencies of the config file, and put into "depend"
        field.

        For example, if we're loading config "A" with: {"inherit": "B"}, then

           A['depend'] = ['A', 'B', <what B depends on ...>]

        The order in the list is same as the result of C3 linearization of the
        inherited config names.

  Returns:
    The config as mapping object.
  """
  caller = inspect.stack()[1]
  module_file = caller[1]
  # When running as pyc inside ZIP(PAR), getmodule() will fail.
  default_name, default_dir = GetDefaultConfigInfo(
      inspect.getmodule(caller[0]), module_file)
  config_dirs = [
      GetRuntimeConfigDirectory(),
      GetBuildConfigDirectory(),
      default_config_dir or default_dir,
  ]

  # If the file is a symbolic link, we also search it's original path.
  if not default_config_dir and os.path.islink(module_file):
    config_dirs.append(os.path.dirname(os.path.realpath(module_file)))

  if config_name is None:
    config_name = default_name
  assert config_name, 'LoadConfig() requires a config name.'

  logger = _GetLogger()
  raw_config_list = _LoadRawConfigList(config_name, config_dirs, allow_inherit,
                                       logger, {})
  config = raw_config_list.Resolve()

  # Ideally we should enforce validating schema, but currently many environments
  # where our factory software needs to live (i.e., old ChromeOS test images,
  # Windows, Ubuntu, or Android) may not have jsonschema library installed, so
  # we'd like to make _CAN_VALIDATE_SCHEMA optional and enforce it once we have
  # completed migration for config API.
  if validate_schema:
    schema = {}
    for config_dir in config_dirs:
      new_schema = _LoadRawSchema(config_dir, config_name, schema_name, logger)

      if new_schema is not None:
        # Config data can be extended, but schema must be self-contained.
        schema = new_schema
        break
    assert schema, 'Need JSON schema file defined for %s.' % config_name
    if _CAN_VALIDATE_SCHEMA:
      jsonschema.validate(config, schema)
    else:
      logger('Configuration schema <%s> not validated because jsonschema '
             'Python library not installed.', config_name)
  else:
    logger('Skip validating schema for config <%s>.', config_name)

  if generate_depend:
    config['depend'] = list(raw_config_list)

  if convert_to_str:
    config = type_utils.UnicodeToString(config)

  return config


class _ConfigList(collections.OrderedDict):
  """Internal structure to store a list of raw configs."""
  def Resolve(self):
    """Returns the final config after overriding."""
    ret = {}
    # collections.OrderedDict does support reversed().
    for key in reversed(self):  # pylint: disable=bad-reversed-sequence
      for unused_config_dir, config in reversed(self[key]):
        ret = OverrideConfig(ret, config)
    return ret


def _C3Linearization(parent_configs, config_name):
  """C3 superclass linearization for inherited configs.

  This is the same as the algorithm used for Python new style class multiple
  inheritance.
  """
  def FirstKey(odict):
    return next(odict.iterkeys())
  # We collect all configs into all_configs, and only use keys in parent_configs
  # as OrderedSet afterward.
  all_configs = {}
  parents = collections.OrderedDict()
  for config_list in parent_configs:
    all_configs.update(config_list)
    # Only key is used, value is not important.
    parents[FirstKey(config_list)] = None

  parent_lists = [l.copy() for l in parent_configs]
  parent_lists.append(parents)

  def GoodHead(x):
    return all(x not in l or x == FirstKey(l) for l in parent_lists)

  ret = _ConfigList()
  while any(parent_lists):
    head = next((head for head in (FirstKey(l) for l in parent_lists if l)
                 if GoodHead(head)), None)
    if head is None:
      raise RuntimeError('C3 linearization failed for %s' % config_name)
    ret[head] = all_configs[head]
    for l in parent_lists:
      if l and FirstKey(l) == head:
        l.popitem(last=False)
  return ret


def _LoadRawConfigList(config_name, config_dirs, allow_inherit,
                       logger, cached_configs):
  """Internal function to load the config list."""
  if config_name in cached_configs:
    assert cached_configs[config_name] != _DUMMY_CACHE, (
        'Detected loop inheritance dependency of %s' % config_name)
    return cached_configs[config_name]

  # Mark the current config in loading.
  cached_configs[config_name] = _DUMMY_CACHE

  config_list = _ConfigList()

  found_configs = []
  for config_dir in config_dirs:
    new_config = _LoadRawConfig(config_dir, config_name, logger)

    if new_config is not None:
      found_configs.append((config_dir, new_config))
  assert found_configs, 'No configuration files found for %s.' % config_name
  config_list[config_name] = found_configs

  # Get the current config dict.
  config = config_list.Resolve()

  if allow_inherit and isinstance(config, dict):
    parents = config.get('inherit')
    if isinstance(parents, basestring):
      parents = [parents]

    # Ignore if 'inherit' is not a list of parent names.
    if isinstance(parents, list):
      parent_configs = []
      for parent in parents:
        current_config = _LoadRawConfigList(
            config_name=parent,
            config_dirs=config_dirs,
            allow_inherit=allow_inherit,
            cached_configs=cached_configs,
            logger=logger)
        parent_configs.append(current_config)
      config_list.update(_C3Linearization(parent_configs, config_name))

  cached_configs[config_name] = config_list
  return config_list
