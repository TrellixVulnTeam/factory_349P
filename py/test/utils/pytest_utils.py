# Copyright 2016 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import logging
import os
import unittest

import factory_common  # pylint: disable=unused-import
from cros.factory.utils import type_utils


def LoadPytestModule(pytest_name):
  """Loads the given pytest module.

  This function tries to load the module

      :samp:`cros.factory.test.pytests.{pytest_name}`.

  For backward compatibility, this function also tries to load

      :samp:`cros.factory.test.pytests.{pytest_base_name}.{pytest_name}`

  if either

      - :samp:`cros.factory.test.pytests.{pytest_name}` doesn't exist
      - :samp:`cros.factory.test.pytests.{pytest_name}` is a package.

  If both :samp:`{pytest_name}` and :samp:`{pytest_base_name}.{pytest_name}`
  exist, :samp:`{pytest_base_name}.{pytest_name}` is returned.

  Examples:

  =============  ==================  ==================
   pytest_name   what will be searched (in order)
  =============  ======================================
   x             x                   x.x [1]_
   x_automator   x_automator         x.x_automator [1]_
   x_e2etest     x_e2etest           x.x_e2etest [1]_
   x.y.z         x.y.z
  =============  ==================  ==================

  .. [1] this is for backward compatibility, will be deprecated, use ``x.y.z``
     instead.

  Args:
    pytest_name: The name of the pytest module.

  Returns:
    The loaded pytest module object.
  """

  from cros.factory.test import pytests

  if '.' in pytest_name:
    __import__('cros.factory.test.pytests.%s' % pytest_name)
    return reduce(getattr, pytest_name.split('.'), pytests)
  else:

    try:
      __import__('cros.factory.test.pytests.%s' % pytest_name)
      module = getattr(pytests, pytest_name)

      if not os.path.basename(module.__file__).startswith('__init__.py'):
        # <pytest_name> is not a package.
        return module
    except ImportError:
      pass

    # Cannot find <pytest_name> or <pytest_name> is a package,
    # fallback to <pytest_base_name>.<pytest_name>.
    pytest_base_name = pytest_name
    for suffix in ('_e2etest', '_automator', '_automator_private'):
      if pytest_base_name.endswith(suffix):
        pytest_base_name = pytest_base_name[:-len(suffix)]

    try:
      __import__('cros.factory.test.pytests.%s.%s' %
                 (pytest_base_name, pytest_name))
      logging.debug('recommend to use pytest_name=%r instead of pytest_name=%r',
                    ('%s.%s' % (pytest_base_name, pytest_name)), pytest_name)
      return getattr(getattr(pytests, pytest_base_name), pytest_name)
    except ImportError:
      logging.error('cannot find any pytest module named %s or %s.%s',
                    pytest_name, pytest_base_name, pytest_name)
      raise


def FindTestCase(pytest_module):
  """Find the TestCase class in the given module.

  There should be one and only one TestCase in the module.
  """
  # To simplify things, we only allow one TestCase per pytest, and the method
  # must be runTest.
  test_case_types = []
  for name in dir(pytest_module):
    obj = getattr(pytest_module, name)
    if isinstance(obj, type) and issubclass(obj, unittest.TestCase):
      test_case_types.append(obj)

  if len(test_case_types) != 1:
    raise type_utils.TestFailure(
        'Only exactly one TestCase per pytest is supported, but found %r. '
        'Use test.AddTask if multiple tasks need to be done in a single pytest.'
        % test_case_types)

  return test_case_types[0]


def LoadPytest(pytest_name):
  """Load pytest type from pytest_name.

  See `LoadPytestModule` to know how pytest_name is resolved.  Also notice that
  there should be one and only one test case in each pytest.
  """
  return FindTestCase(LoadPytestModule(pytest_name))


def RelpathToPytestName(relpath):
  """Convert a pytest relpath to dotted pytest name."""
  return os.path.splitext(relpath)[0].replace('/', '.')
