# How To Write a ChromeOS Factory Test List
Test lists are defined by **python files** under this
( `platform/factory/py/test/test_lists` ) directory.  Each of these files
should have a module level `CreateTestLists` function, this function will be
called
when Goofy starts.  Here is an example of a test list file:

```python
import factory_common  # pylint: disable=unused-import
from cros.factory.test.test_lists import test_lists


def CreateTestLists():
  # create a test list with ID 'main'
  with test_lists.TestList(id='main') as test_list:
    # setup test list options
    test_list.options.xxx = ...
    # you can also put them into a function, e.g. SetOptions
    SetOptions(test_list.options)

    with test_lists.FactoryTest(
        label=_('SMT Tests'),
        action_on_failure='STOP'):
      with test_lists.FactoryTest(
          label=_('Probe Components'),
          parallel=True):
        test_lists.FactoryTest(
            label=_('Probe Accelerometer'),
            pytest_name='i2c_probe',
            dargs={
                'bus': 1,
                'addr': 0x30,
            })
        test_lists.FactoryTest(
            label=_('Probe Camera'),
            pytest_name='i2c_probe',
            dargs={
                'bus': 1,
                'addr': 0x45,
            })
      test_lists.RebootStep(label=_('Reboot'))
      test_lists.FactoryTest(
          label=_('LED Test'),
          pytest_name='led',
          action_on_failure='PARENT',
          dargs={
              'colors': ['RED', 'BLUE', 'GREEN']
          })
      test_lists.ShutdownStep(label=_('Shutdown'))

    with test_lists.FactoryTest(
        label=_('RunIn Tests'),
        action_on_failure='STOP'):
      test_lists.FactoryTest(
          label=_('StressAppTest'),
          pytest_name='stressapptest',
          dargs=dict(seconds=30 * 60,
                     memory_ratio=0.75,
                     free_memory_only=True,
                     wait_secs=5,
                     disk_thread=True))
```

This will create a test list named `main`, with the following structure:

```text
main
 |-- SMT
 |    |-- ProbeComponents
 |    |    |-- ProbeAccelerometer
 |    |    `-- ProbeCamera
 |    |
 |    |-- Reboot
 |    |-- LED
 |    `-- Shutdown
 |
 `-- RunIn
      `-- StressAppTest
```

Where:
* `ProbeAccelerometer` and `ProbeCamera` will be run in **parallel**.
* the device will be rebooted on `Reboot` test.
* the user interface of `LED` (if any) will be shown when running.
* the device will be shutdown on `Shutdown` test.
* If any of the tests under `SMT` fails, Goofy will stop testing, `RunIn` won't
    be run.
* StressAppTest will be run for 30 minutes.

Detail explanation of each attributes are available in the following sections.

## ID
Each test item must have an ID, ID will be used to define the **path** of a
test.  **path** is defined as:

`test.path = test.parent.path + '.' + test.ID`

For example, the test group `SMT` will have test path `SMT`, and the test item
`ProbeCamera` will have test path `SMT.ProbeComponents.ProbeCamera`.

**Each test path must be unique in a test list.**  That is, you can have several
test with ID `Shutdown`, but they have to have different test path.

## label
`label` is a string that will be shown on UI. Remember to use `u'中文'` for
Chinese.

## pytest_name and dargs
Leaf nodes (the test items have no subtests) of test list should be a
**pytest**.  A pytest is a test written in python and place under
`py/test/pytests/` in public or private factory source tree.

Each pytest can define their arguments, the `ARGS` variable in the class.  And
the `dargs` is used to assign values to these arguments.  As you can see on the
sample code above, `dargs` is a dictionary of key value pairs where keys are
mapped to the name of each arguments in `ARGS`.

## Subtests
To create a group of tests, you just need to

```python
  with test_lists.FactoryTest(label=_('TestGroupID')):
    # add subtests here
    ...
```

## Locals
Each `FactoryTest` object can have a `locals` attribute, which is a dictionary
of key value pairs.  `locals` will be available when Goofy is resolving `dargs`
that will be passed to pytest.

## never_fails
Set `never_fails=True` if you don't want this test to fail in any case.
The test will still be run, but when it fails, it will not be marked as failed.

## Parallel Tests
To make two or more tests run in the same time, you need to group them under a
`FactoryTest`, and add attribute `parallel=True` to this FactoryTest.
You can see `ProbeComponents` in above as an example.

## Action On Failure
The `action_on_failure` attribute allows you to decide what the next test should
be when this test fails.  There are three possible values:
* `NEXT`: this is the default value, the test list will continue on next test
    item.
* `PARENT`: stop running other tests under current parent, let parent to decide
    what the next test should be.
* `STOP`: stop running other tests.

## Teardown
Sometimes, you want a test be run after some tests are finished, no matter
those tests success or not.  For example, a test item that uploads log files to
shopfloor server should always be run despite the status of previous tests.

```python
  with test_lists.FactoryTest(label=_('TestGroupID')):
    # add subtests here
    ...
    with test_lists.Teardowns():
      # add teardown test items here
      ...

  # or, if you care about symmetry
  with test_lists.FactoryTest(label=_('TestGroupID')):
    with test_lists.Subtests():
      # add subtests here
      ...
    with test_lists.Teardowns():
      # add teardown test items here
      ...
```

Tests in teardowns can have their subtests as well.  Those tests will become
teardown tests as well.  We assume that teardowns will never fail, if a teardown
test fails, Goofy will ignore the failure, and continue on next teardown test.
Therefore, for teardown tests, `action_on_failure` will always be set to `NEXT`.

## Test List Options
The `test_list.options` object will be a `cros.factory.test.factory.Options`
instance, please refer to the class definition to know the usage of each
options.
