# Copyright 2014 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""YAML utilities."""

import collections
import yaml


class BaseYAMLTagMetaclass(type):
  """Base metaclass for creating YAML tags."""
  YAML_TAG = None

  @classmethod
  def YAMLConstructor(mcs, loader, node):
    raise NotImplementedError

  @classmethod
  def YAMLRepresenter(mcs, dumper, data):
    raise NotImplementedError

  def __init__(cls, name, bases, attrs):
    yaml.add_constructor(cls.YAML_TAG, cls.YAMLConstructor)
    yaml.add_representer(cls, cls.YAMLRepresenter)
    super(BaseYAMLTagMetaclass, cls).__init__(name, bases, attrs)


def ParseMappingAsOrderDict():
  """Treat OrderDict as the default mapping instance.

  While we load a yaml file to a object, modify the object, and dump to a yaml
  file, we hope to keep the order of the mapping instance. Therefore, we should
  parse the mapping to the Python OrderedDict object, and dump the OrderedDict
  instance to yaml just like a dict object.
  """
  def OrderDictRepresenter(dumper, data):
    return dumper.represent_dict(data.iteritems())

  def OrderDictConstructor(loader, node):
    return collections.OrderedDict(loader.construct_pairs(node))

  yaml.add_representer(collections.OrderedDict, OrderDictRepresenter)
  yaml.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
                       OrderDictConstructor)
