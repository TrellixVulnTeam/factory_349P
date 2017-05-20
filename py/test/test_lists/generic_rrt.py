# Copyright 2015 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=W0613,W0622


"""Rolling Reliability Test (RRT).

This test list can also be used to verify the software stability of base image
(kernel/firmware) before deploying at factory.
"""


import re

import factory_common  # pylint: disable=unused-import
from cros.factory.device import device_utils
from cros.factory.goofy.plugins import plugin
from cros.factory.test import i18n
from cros.factory.test.i18n import _
from cros.factory.test.test_lists.test_lists import FactoryTest
from cros.factory.test.test_lists.test_lists import HaltStep
from cros.factory.test.test_lists.test_lists import OperatorTest
from cros.factory.test.test_lists.test_lists import RebootStep
from cros.factory.test.test_lists.test_lists import TestGroup
from cros.factory.test.test_lists.test_lists import TestList
from cros.factory.utils.net_utils import GetWLANInterface
from cros.factory.utils import sys_utils

HOURS = 60 * 60
MINUTES = 60


class TestListArgs(object):
  """A helper object used to construct a single test list.

  This may contain:

  - arguments used when constructing the test list
  - common dargs or values that are shared across different tests
  - helper methods use to construct tests based on test arguments

  Nothing in this class is used by the test harness directly, rather
  only used by this file when constructing the test list.
  """
  # Enable options that apply only in a real factory environment.
  factory_environment = True

  # Password for engineering mode (only used if factory_environment is
  # true). This password is 'cros'.
  engineering_password_sha1 = '8c19cad459f97de3f8c836c794d9a0060a795d7b'

  # Host/port for shopfloor communication.
  shopfloor_host = '10.3.0.11'
  shopfloor_port = 8082

  # Minimum/maximum target battery charge.
  # Set to None to disable charging manager.
  # (Otherwise, it may running out of battery after too many rebooting.)
  min_charge_pct = None
  max_charge_pct = None

  wlan_iface = GetWLANInterface()
  bluetooth_iface = 'hci0'

  # Enable periodic ping test over WLAN connection during stress test.
  wlan_periodic_ping_test = True
  wlan_ping_host = '192.168.0.1'
  wlan_ping_interval_secs = 10
  # Checks that ping success percentage is > 60% within the moving 20 pings.
  wlan_ping_success_percent = 60
  wlan_ping_window_size = 20

  # Some form factors (ex: desktop) has no EC, so we cannot trigger
  # cold reset from EC.
  @property
  def has_ec(self):
    return sys_utils.HasEC()

  # Need to enlarge stateful partition size for long-run stress tests.
  desired_stateful_size_gb = 4

  #####
  #
  # Parameter for warm reboot, warm/cold reboot and clear TPM stress tests.
  #
  #####
  warm_reboot_iterations = 1500
  warm_cold_reboot_iterations = 100
  clear_tpm_iterations = 100

  reboot_warning = _(
      'This RRT will start reboot stress test and it might take 24+ hours.<br>'
      'Please press space to start the test.')

  #####
  #
  # Parameters for RunIn stress tests.  Please notice that stressapptest
  # might wear out internal storage.  You can disable it by set
  # run_in_stress_test_disk = False.
  #
  #####
  run_in_stress_iterations = 20

  run_in_warning = _(
      'This RRT will have heavy testing on disk and might wear it out.<br>'
      'Please avoid shipping those devices after running RRT.<br>'
      'You can either set run_in_stress_test_disk=False or <br>'
      'rework a new disk after test.<br><br>'
      'Please press space to start the test.')

  # Stress test parameters for each iteration.
  run_in_sat_duration_secs = int(8 * HOURS)
  # Whether to enable disk thread in stressapptest test.
  run_in_stress_test_disk = True

  # The interval of logging events in seconds during run-in.
  run_in_countdown_log_interval_secs = 10
  # Grace period before starting abnormal status detection
  run_in_countdown_grace_secs = 8 * MINUTES
  # Allowed difference between current and last temperature of a sensor
  run_in_countdown_temp_max_delta = 10
  # The duration of stress test during run-in (suggested 10+ mins).

  # A list of rules to check that temperature is under the given range
  # rule format: (name, temp_sensor, warning_temp, critical_temp)
  @property
  def run_in_countdown_temp_criteria(self):
    return [('CPU', None, 90, 100)]

  # Number of suspend/resume tests for each iteration.
  run_in_resume_iterations = 15
  # Allowed auto-retry times for suspend/resume test.
  # If the software has 0.1% fail rate for a single suspend, it will cause
  # 1.5% fail rate at factory (it's bad!). So we'd like to do auto retry.
  # (The purpose of factory test is to verify hardware, not software.)
  run_in_resume_auto_retries = 2
  # Duration of stress test + repeated suspend/resume during run-in.
  # This may detect bit flips between suspend/resume.
  run_in_dozing_sat_duration_secs = int(10 * MINUTES)

  # Number of warm reboots for each run.
  run_in_reboot_iterations = 15

  #####
  #
  # Helper methods.
  # Some helper methods can be used in run_if test argument.
  #
  #####
  def NeedEnlargeStateful(self, env):
    """Helper function to check if need to enlarge stateful partition.

    During the long-running stress test, the log files might make stateful
    partition full.  We need to enlarge stateful partition to before
    the test starts.  This function is used to check the current size of
    stateful partition and decide whether the enlargement is needed or not.

    Args:
      env: The TestArgEnv object passed by goofy when evaluating
        run_if argument.

    Returns:
      Returns True if need to enlarge stateful partition, else returns False.
    """
    # Skip enlarge stateful partition if it has been done before.
    if env.GetDeviceData().get('resize_complete', False):
      return False

    dut_instance = device_utils.CreateDUTInterface()
    df_output_gb = dut_instance.CallOutput(
        ['df', '-BG', dut_instance.partitions.STATEFUL.path])
    match = re.search(
        r'^%s\s+(\d+)G' % dut_instance.partitions.STATEFUL.path,
        df_output_gb,
        re.MULTILINE)
    current_size_gb = int(match.group(1)) if match else None
    if current_size_gb and current_size_gb < self.desired_stateful_size_gb:
      return True
    else:
      return False


def SetOptions(test_list, args):
  """Sets test list options for goofy.

  The options in this function will be used by test harness(goofy).
  Note that this function is shared by different test lists so
  users can set default options here for their need.
  For details on available options, see the Options class in
  py/test/factory.py.
  After calling this function, user can still modify options for different
  test list. For example, set options.engineering_password_sha1 to None to
  enable engineering mode in experiment test list.

  Args:
    test_list: The test_list object to be constructed.
    args: A TestListArgs object which contains argument that are used commonly
      by tests and options. Fox example min_charge_pct, max_charge_pct,
      shopfloor_host.
  """

  options = test_list

  # Require explicit IDs for each test
  options.strict_ids = True

  # Disable CPUFreqManager
  test_list.exclusive_resources = [plugin.RESOURCE.CPU]

  if args.factory_environment:
    # echo -n 'passwordgoeshere' | sha1sum
    # - Use operator mode by default and require a password to enable
    #   engineering mode
    options.engineering_password_sha1 = args.engineering_password_sha1
    # - Default to Chinese language
    options.ui_locale = 'zh-CN'

    options.shopfloor_server_url = 'http://%s:%d/' % (
        args.shopfloor_host, args.shopfloor_port)

    # - Enable background event log syncing
    options.sync_event_log_period_secs = None
    options.update_period_secs = None

    options.disable_cros_shortcut_keys = True

    options.plugin_config_name = 'goofy_plugin_chromeos_rrt'


def Barrier(id_suffix='', pass_without_prompt=False,
            accessibility=True):
  """Test barrier to display test summary.

  Args:
    pass_without_prompt: Pass barrier without prompt.
    accessibility: Display bright red background when the overall status is
                   not PASSED.
  """
  OperatorTest(
      id='Barrier' + str(id_suffix),
      label=i18n.StringFormat(_('Barrier{suffix}'), suffix=id_suffix),
      pytest_name='summary',
      never_fails=True,
      disable_abort=True,
      dargs=dict(
          disable_input_on_fail=True,
          bft_fixture=None,
          pass_without_prompt=pass_without_prompt,
          accessibility=accessibility))


def PressToStart(id_suffix='',
                 message=_('Please press space to start the test.')):
  """Display warning messages and ask user to press space to start test."""
  OperatorTest(
      id='PressToStart' + str(id_suffix),
      label=i18n.StringFormat(_('PressToStart{suffix}'), suffix=id_suffix),
      pytest_name='message',
      never_fails=True,
      dargs=dict(
          html=message,
          text_size='200',
          text_color='black',
          background_color='red'))


def EnlargeStatefulPartition(args):
  """Enlarge stateful partition to prevent disk full during long run tests."""
  with TestGroup(id='EnlargeStatefulPartition',
                 label=_('Enlarge Stateful Partition')):
    FactoryTest(
        id='ResizeFileSystem',
        label=_('Resize File System'),
        pytest_name='line_check_item',
        run_if=args.NeedEnlargeStateful,
        dargs=dict(
            title=_('Resize File System'),
            items=[
                (_('Resize File System'),
                 'resize2fs %s %dG' % (
                     device_utils.CreateDUTInterface().partitions.STATEFUL.path,
                     args.desired_stateful_size_gb),
                 False)]))
    # Writes 'resize_complete' into device_data to mark this DUT has finished
    # EnlargeStatefulPartition.
    OperatorTest(
        id='UpdateDeviceData',
        label=_('Update Device Data'),
        pytest_name='update_device_data',
        dargs=dict(data=dict(resize_complete=True)))


def Idle(id_suffix='', wait_secs=1):
  """Sleep for seconds."""
  FactoryTest(
      id='Idle' + str(id_suffix),
      label=_('Idle'),
      pytest_name='line_check_item',
      dargs=dict(
          title=_('Sleep'),
          items=[(_('Sleep'),
                  'sleep %d' % wait_secs, False)]))


def ColdReset():
  """Triggers a cold reset via embedded controller (EC)."""
  with TestGroup(id='ColdReset', label=_('Cold Reset')):
    FactoryTest(
        id='ECReset',
        label=_('EC Cold Reset'),
        pytest_name='line_check_item',
        dargs=dict(
            title=_('Cold Reset at Shutdown'),
            items=[(_('EC Reboot'),
                    'ectool reboot_ec cold at-shutdown', False)]))

    HaltStep(
        id='Halt',
        label=_('Halt'))


def WarmReboot(id_suffix='', iterations=1):
  """Tests warm reboot for multiple iterations."""
  RebootStep(
      id='Reboot' + str(id_suffix),
      label=i18n.StringFormat(_('Reboot ({count} times)'), count=iterations),
      iterations=iterations)


def WarmColdReboot(args):
  """Tests Warm reboot and cold reboot alternately.

  This test triggers a cold reboot and then a warm reboot for multiple
  iterations.  After a reboot, it also checks the existence of WiFi and
  Bluetooth devices.  This tests will be skipped if the device has no EC
  because it relies on EC to trigger cold reset.
  """
  if not args.has_ec:
    return
  iterations = args.warm_cold_reboot_iterations
  with TestGroup(id='WarmColdReboot',
                 label=i18n.StringFormat(_('WarmColdReboot ({count} times)'),
                                         count=iterations)):
    for i in range(iterations):
      with TestGroup(id='WarmColdReboot%d' % i,
                     label=i18n.StringFormat(_('WarmColdReboot{i}'), i=i)):
        if i % 2 == 0:
          ColdReset()
        else:
          Idle(wait_secs=60)
          WarmReboot()

        FactoryTest(
            id='CheckWLAN',
            label=_('Check WLAN'),
            pytest_name='line_check_item',
            dargs=dict(
                title=_('Check WLAN'),
                items=[(_('WLAN command'),
                        'ifconfig %s' % args.wlan_iface, False)]))

        FactoryTest(
            id='CheckBT',
            label=_('Check Bluetooth'),
            pytest_name='line_check_item',
            dargs=dict(
                title=_('Check Bluetooth'),
                items=[(_('BT command'),
                        'hciconfig %s' % args.bluetooth_iface, False)]))

        Barrier(pass_without_prompt=True)


def ClearTPM(args):
  """Tests clear TPM for multiple iterations."""
  iterations = args.clear_tpm_iterations
  with TestGroup(id='ClearTPM',
                 label=i18n.StringFormat(_('Clear TPM ({count} times)'),
                                         count=iterations)):
    for i in range(iterations):
      with TestGroup(id='ClearTPM%d' % i,
                     label=i18n.StringFormat(_('Clear TPM {i}'), i=i)):
        FactoryTest(
            id='TPMVerifyEK',
            label=_('TPM Verify EK'),
            pytest_name='tpm_verify_ek')

        FactoryTest(
            id='RequestClearTPM',
            label=_('Request Clear TPM'),
            pytest_name='clear_tpm_owner_request')

        WarmReboot(id_suffix='RebootAfterClearTPM')
        Idle(wait_secs=30)

        FactoryTest(
            id='VerifyTPM',
            label=_('Verify TPM'),
            pytest_name='line_check_item',
            dargs=dict(
                title=_('Verify TPM'),
                items=[(_('verify TPM command'),
                        'gooftool verify_tpm', False)]))

        WarmReboot(id_suffix='RebootAfterVerifyTPM')
        Barrier('ClearTPM', pass_without_prompt=True)


def StressTest(args):
  """StressAppTest, graphics and camera tests for each RunIn iteration."""
  with FactoryTest(id='Stress', label=_('Stress'), parallel=True):
    OperatorTest(
        id='Graphics',
        label=_('Graphics'),
        pytest_name='webgl_aquarium',
        dargs=dict(
            duration_secs=args.run_in_sat_duration_secs))

    # Watch if the LED light of camera is on.
    FactoryTest(
        id='Camera',
        label=_('Camera'),
        pytest_name='camera',
        dargs=dict(
            timeout_secs=args.run_in_sat_duration_secs,
            show_image=False,
            do_capture_timeout=True))

    FactoryTest(
        id='RandomNumberGen',
        label=_('Random Number Generation'),
        pytest_name='urandom',
        dargs=dict(
            duration_secs=args.run_in_sat_duration_secs))

    FactoryTest(
        id='StressAppTest',
        label=_('Stress App Test'),
        pytest_name='stressapptest',
        dargs=dict(
            seconds=args.run_in_sat_duration_secs,
            # Wait for memory usage of other tests to stablize.
            wait_secs=60,
            disk_thread=args.run_in_stress_test_disk))

    FactoryTest(
        id='Countdown',
        label=_('Countdown'),
        pytest_name='countdown',
        dargs=dict(
            title=_('Run-In Tests'),
            duration_secs=args.run_in_sat_duration_secs,
            log_interval=args.run_in_countdown_log_interval_secs,
            grace_secs=args.run_in_countdown_grace_secs,
            temp_max_delta=args.run_in_countdown_temp_max_delta,
            temp_criteria=args.run_in_countdown_temp_criteria))

    if args.wlan_periodic_ping_test:
      FactoryTest(
          id='WLANPingTest',
          label=_('WLAN Ping Test'),
          pytest_name='ping_test',
          dargs=dict(
              host=args.wlan_ping_host,
              interface=args.wlan_iface,
              interval_secs=args.wlan_ping_interval_secs,
              duration_secs=args.run_in_sat_duration_secs,
              ping_success_percent=args.wlan_ping_success_percent,
              moving_window_size=args.wlan_ping_window_size))


def DozingStress(args):
  """Suspend/resume test for each RunIn iteration."""
  with FactoryTest(id='DozingStress', label=_('Dozing Stress'),
                   parallel=True):
    # if StressAppTest fails here, it's likely memory issue.
    FactoryTest(
        id='StressAppTest',
        label=_('Stress App Test'),
        pytest_name='stressapptest',
        dargs=dict(
            seconds=args.run_in_dozing_sat_duration_secs,
            disk_thread=args.run_in_stress_test_disk))

    # Takes about 30 minutes for 60 iterations
    FactoryTest(
        id='SuspendResume',
        label=i18n.StringFormat(_('SuspendResume ({count} times)'),
                                count=args.run_in_resume_iterations),
        pytest_name='suspend_resume',
        retries=args.run_in_resume_auto_retries,
        dargs=dict(
            cycles=args.run_in_resume_iterations,
            suspend_delay_min_secs=28,
            suspend_delay_max_secs=30,
            resume_early_margin_secs=1))

    OperatorTest(
        id='Countdown',
        label=_('Countdown'),
        pytest_name='countdown',
        dargs=dict(
            title=_('Dozing Stress Tests'),
            duration_secs=args.run_in_dozing_sat_duration_secs,
            log_interval=args.run_in_countdown_log_interval_secs,
            grace_secs=args.run_in_countdown_grace_secs,
            temp_max_delta=args.run_in_countdown_temp_max_delta,
            temp_criteria=args.run_in_countdown_temp_criteria))


def RunInStress(args):
  """RunIn Stress tests for multiple iterations."""
  iterations = args.run_in_stress_iterations
  with TestGroup(id='RunInStress',
                 label=i18n.StringFormat(_('RunInStress ({count} times)'),
                                         count=iterations)):
    for i in range(iterations):
      with TestGroup(id='RunInStress%d' % i,
                     label=i18n.StringFormat(_('RunInStress{i}'), i=i)):
        StressTest(args)
        Barrier('Stress', pass_without_prompt=True)
        WarmReboot(id_suffix='AfterStress')

        DozingStress(args)
        Barrier('DozingStress', pass_without_prompt=True)

        WarmReboot(iterations=args.run_in_reboot_iterations)
        if args.has_ec:
          ColdReset()
        Barrier('RunInStress', pass_without_prompt=True)


def CreateRebootStressTestList():
  """Creates a test list for long run reboot test."""
  args = TestListArgs()
  with TestList('generic_rrt_reboot',
                'Generic Rolling Reliability (Reboot)') as test_list:
    SetOptions(test_list, args)
    PressToStart(id_suffix='RebootStress',
                 message=args.reboot_warning)
    EnlargeStatefulPartition(args)
    WarmReboot('StressChrome', args.warm_reboot_iterations)
    WarmColdReboot(args)
    ClearTPM(args)


def CreateRunInStressTestList():
  """Creates a test list for long run stress test."""
  args = TestListArgs()
  with TestList('generic_rrt_stress',
                'Generic Rolling Reliability (Stress)') as test_list:
    SetOptions(test_list, args)
    PressToStart(id_suffix='RunInStress',
                 message=args.run_in_warning)
    EnlargeStatefulPartition(args)
    RunInStress(args)


def CreateTestLists():
  """Creates test list.

  This is the external interface to test list creation (called by the
  test list builder).  This function is required and its name cannot
  be changed.
  """

  # This test list is created in a very dynamic way. However, error occurs if
  # DUT is not local. Add a check here to generate test list only when link
  # is local.
  # TODO (shunhsingou): fixed this test list in the future.
  if device_utils.CreateDUTInterface().link.IsLocal():
    CreateRebootStressTestList()
    CreateRunInStressTestList()
  else:
    with TestList('generic_rrt', 'Generic Rolling Reliability'):
      OperatorTest(
          id='MessageNotSupport',
          label=_('Not Supported'),
          pytest_name='message',
          dargs={'html': _('This test list does not support station mode.')})
