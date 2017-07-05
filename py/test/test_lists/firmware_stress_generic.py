# Copyright (c) 2013 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.


"""A small set of firmware stress tests."""


import factory_common  # pylint: disable=unused-import
from cros.factory.goofy.plugins import plugin
from cros.factory.test import i18n
from cros.factory.test.i18n import _
from cros.factory.test.test_lists.test_lists import AutomatedSequence
from cros.factory.test.test_lists.test_lists import FactoryTest
from cros.factory.test.test_lists.test_lists import OperatorTest
from cros.factory.test.test_lists.test_lists import RebootStep
from cros.factory.test.test_lists.test_lists import TestGroup


HOURS = 60 * 60


def RunIn(args, group_suffix='FirmwareStress'):
  """Creates RunIn test list.

  Args:
    args: A TestListArgs object.
    group_suffix: Suffix for this TestGroup.
  """
  group_id = 'RunIn' + group_suffix
  with TestGroup(id=group_id):
    OperatorTest(
        label=_('Start'),
        has_automator=True,
        pytest_name='start',
        never_fails=True,
        dargs=dict(
            # Requires pressing space to quickly check keyboard because RunIn
            # starts after full assembly and keyboard may fail on a few DUTs.
            press_to_continue=True,
            require_external_power=True,
            require_shop_floor='defer' if args.enable_shopfloor else False))

    # Checks storage using badblocks command. If DUT is fully imaged, we can use
    # free space in stateful partition. If DUT is installed by
    # chromeos-install, there will be no free space in stateful partition,
    # and we have to use 'file' mode.
    OperatorTest(
        label=_('Bad Blocks'),
        pytest_name='bad_blocks',
        # When run alone, this takes ~.5s/MiB (for four passes).  We'll do a
        # gigabyte, which takes about about 9 minutes.
        dargs=dict(
            timeout_secs=120,
            log_threshold_secs=10,
            max_bytes=1024 * 1024 * 1024,
            mode=('stateful_partition_free_space' if args.fully_imaged
                  else 'file')))

    # Runs stress tests in parallel.
    # TODO(bhthompson): add in video and audio tests
    with FactoryTest(label=_('Stress'), parallel=True):
      # Runs WebGL operations to check graphic chip.
      OperatorTest(
          label=_('Graphics'),
          pytest_name='webgl_aquarium',
          dargs=dict(duration_secs=args.run_in_stress_duration_secs))

      # Runs camera in parallel with other stress tests so it is easier
      # to trigger other possible hardware/software error.
      # Watch if the LED light of camera is on to check if camera is in
      # operation.
      FactoryTest(
          label=_('Camera'),
          pytest_name='camera',
          dargs=dict(
              do_capture_timeout=True,
              capture_resolution=(640, 480),
              timeout_secs=args.run_in_stress_duration_secs,
              show_image=False))

      # Runs StressAppTest to stresses CPU and checks memory and storage.
      FactoryTest(
          label=_('Stress App Test'),
          dargs=dict(
              seconds=args.run_in_stress_duration_secs,
              wait_secs=60))

      # Logs system status and monitors temperature, AC status.
      # If AC is unplugged for more than args.run_in_countdown_ac_secs,
      # The test will fail and stop all tests.
      FactoryTest(
          label=_('Countdown'),
          pytest_name='countdown',
          dargs=dict(
              title=_('Run-In Tests'),
              duration_secs=args.run_in_stress_duration_secs,
              log_interval=args.run_in_countdown_log_interval_secs,
              grace_secs=args.run_in_countdown_grace_secs,
              temp_max_delta=args.run_in_countdown_temp_max_delta_deg_c,
              temp_criteria=args.run_in_countdown_temp_criteria))

    args.Barrier('RunInStress',
                 pass_without_prompt=True,
                 accessibility=True)

    # Runs StressAppTest in parallel with suspend/resume so it will be easier
    # to detect bad memory.
    with AutomatedSequence(label=_('Dozing Stress'), parallel=True):
      # if StressAppTest fails here, it's likely memory issue.
      FactoryTest(
          label=_('Stress App Test'),
          pytest_name='stressapptest',
          dargs=dict(
              seconds=args.run_in_dozing_stress_duration_secs))

      # Takes about 30 minutes for 60 iterations
      FactoryTest(
          label=i18n.StringFormat(_('SuspendResume ({count} times)'),
                                  count=args.run_in_resume_iterations),
          pytest_name='suspend_resume',
          retries=1,  # workaround for premature awake failure
          dargs=dict(
              cycles=args.run_in_resume_iterations,
              suspend_delay_min_secs=28,
              suspend_delay_max_secs=30,
              resume_early_margin_secs=1))

      # Logs system status and monitors temperature, AC status.
      # If AC is unplugged for more than args.run_in_countdown_ac_secs,
      # The test will fail and stop all tests.
      OperatorTest(
          label=_('Countdown'),
          pytest_name='countdown',
          dargs=dict(
              title=_('Dozing Stress Tests'),
              duration_secs=args.run_in_dozing_stress_duration_secs,
              log_interval=args.run_in_countdown_log_interval_secs,
              grace_secs=args.run_in_countdown_grace_secs,
              temp_max_delta=args.run_in_countdown_temp_max_delta_deg_c,
              temp_criteria=args.run_in_countdown_temp_criteria))

    args.Barrier('RunInDozingStress',
                 pass_without_prompt=True,
                 accessibility=True)

    # Stress test for reboot.
    RebootStep(
        label=i18n.StringFormat(_('Reboot ({count} times)'),
                                count=args.run_in_reboot_seq_iterations),
        iterations=args.run_in_reboot_seq_iterations)

    # Charges battery to args.run_in_blocking_charge_pct.
    OperatorTest(
        label=_('Charge'),
        pytest_name='blocking_charge',
        exclusive_resources=[plugin.RESOURCE.POWER],
        dargs=dict(
            timeout_secs=7200,
            target_charge_pct=args.run_in_blocking_charge_pct))

    if args.run_in_prompt_at_finish:
      # Disables charge manager here so we can have more charge when we
      # leave RunIn.
      OperatorTest(
          label=_('Finish'),
          has_automator=True,
          pytest_name='message',
          exclusive_resources=[plugin.RESOURCE.POWER],
          never_fails=True,
          dargs=dict(
              html=_('RunIn tests finished, press SPACE to continue.\n')))
