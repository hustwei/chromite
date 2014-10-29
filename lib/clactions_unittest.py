#!/usr/bin/python
# Copyright 2014 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Unit tests for clactions methods."""

from __future__ import print_function

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))

from chromite.cbuildbot import constants
from chromite.cbuildbot import metadata_lib
from chromite.cbuildbot import validation_pool
from chromite.lib import fake_cidb
from chromite.lib import clactions
from chromite.lib import cros_test_lib

class CLActionTest(cros_test_lib.TestCase):
  """Placeholder for clactions unit tests."""
  def runTest(self):
    pass


class TestCLPreCQStatus(cros_test_lib.TestCase):
  """Tests methods related to CL pre-CQ status."""


  def setUp(self):
    self.fake_db = fake_cidb.FakeCIDBConnection()


  def _Act(self, build_id, change, action, reason=None):
    self.fake_db.InsertCLActions(
          build_id,
          [clactions.CLAction.FromGerritPatchAndAction(change, action, reason)]
          )


  def _GetCLStatus(self, change):
    """Helper method to get a CL's pre-CQ status from fake_db."""
    action_history = self.fake_db.GetActionsForChanges([change])
    return clactions.GetCLPreCQStatus(change, action_history)


  def testGetCLPreCQStatus(self):
    change = metadata_lib.GerritPatchTuple(1, 1, False)
    # Initial pre-CQ status of a change is None.
    self.assertEqual(self._GetCLStatus(change), None)

    # Builders can update the CL's pre-CQ status.
    build_id = self.fake_db.InsertBuild(constants.PRE_CQ_LAUNCHER_NAME,
        constants.WATERFALL_INTERNAL, 1, constants.PRE_CQ_LAUNCHER_CONFIG,
        'bot-hostname')

    self._Act(build_id, change, constants.CL_ACTION_PRE_CQ_WAITING)
    self.assertEqual(self._GetCLStatus(change), constants.CL_STATUS_WAITING)

    self._Act(build_id, change, constants.CL_ACTION_PRE_CQ_INFLIGHT)
    self.assertEqual(self._GetCLStatus(change), constants.CL_STATUS_INFLIGHT)

    # Recording a cl action that is not a valid pre-cq status should leave
    # pre-cq status unaffected.
    self._Act(build_id, change, 'polenta')
    self.assertEqual(self._GetCLStatus(change), constants.CL_STATUS_INFLIGHT)

    # Marking the CL as KICKED_OUT should mark it as FAILED, as a workaround
    # for Bug 429777. TODO(davidjames): Remove this.
    self._Act(build_id, change, constants.CL_ACTION_KICKED_OUT)
    self.assertEqual(self._GetCLStatus(change), constants.CL_STATUS_FAILED)


  def testGetCLPreCQProgress(self):
    change = metadata_lib.GerritPatchTuple(1, 1, False)
    s = lambda: clactions.GetCLPreCQProgress(
            change, self.fake_db.GetActionsForChanges([change]))

    self.assertEqual({}, s())

    # Simulate the pre-cq-launcher screening changes for pre-cq configs
    # to test with.
    launcher_build_id = self.fake_db.InsertBuild(
        constants.PRE_CQ_LAUNCHER_NAME, constants.WATERFALL_INTERNAL,
        1, constants.PRE_CQ_LAUNCHER_CONFIG, 'bot hostname 1')

    self._Act(launcher_build_id, change,
              constants.CL_ACTION_VALIDATION_PENDING_PRE_CQ,
              'pineapple-pre-cq')
    self._Act(launcher_build_id, change,
              constants.CL_ACTION_VALIDATION_PENDING_PRE_CQ,
              'banana-pre-cq')

    configs = ['banana-pre-cq', 'pineapple-pre-cq']

    self.assertEqual(configs, sorted(s().keys()))
    for c in configs:
      self.assertEqual(constants.CL_PRECQ_CONFIG_STATUS_PENDING,
                       s()[c][0])

    # Simulate the pre-cq-launcher launching tryjobs for all pending configs.
    for c in configs:
      self._Act(launcher_build_id, change,
                constants.CL_ACTION_TRYBOT_LAUNCHING, c)
    for c in configs:
      self.assertEqual(constants.CL_PRECQ_CONFIG_STATUS_LAUNCHED,
                       s()[c][0])

    # Simulate the tryjobs launching, and picking up the changes.
    banana_build_id = self.fake_db.InsertBuild(
        'banana', constants.WATERFALL_TRYBOT, 12, 'banana-pre-cq',
        'banana hostname')
    pineapple_build_id = self.fake_db.InsertBuild(
        'pineapple', constants.WATERFALL_TRYBOT, 87, 'pineapple-pre-cq',
        'pineapple hostname')

    self._Act(banana_build_id, change, constants.CL_ACTION_PICKED_UP)
    self._Act(pineapple_build_id, change, constants.CL_ACTION_PICKED_UP)
    for c in configs:
      self.assertEqual(constants.CL_PRECQ_CONFIG_STATUS_INFLIGHT,
                       s()[c][0])

    # Simulate the changes being rejected, either by the configs themselves
    # or by the pre-cq-launcher.
    self._Act(banana_build_id, change, constants.CL_ACTION_KICKED_OUT)
    self._Act(launcher_build_id, change, constants.CL_ACTION_KICKED_OUT,
              'pineapple-pre-cq')
    for c in configs:
      self.assertEqual(constants.CL_PRECQ_CONFIG_STATUS_FAILED,
                       s()[c][0])
    # Simulate the tryjobs verifying the changes.
    self._Act(banana_build_id, change, constants.CL_ACTION_VERIFIED)
    self._Act(pineapple_build_id, change, constants.CL_ACTION_VERIFIED)
    for c in configs:
      self.assertEqual(constants.CL_PRECQ_CONFIG_STATUS_VERIFIED,
                       s()[c][0])

  def testGetCLPreCQCategoriesAndPendingCLs(self):
    c1 = metadata_lib.GerritPatchTuple(1, 1, False)
    c2 = metadata_lib.GerritPatchTuple(2, 2, False)
    c3 = metadata_lib.GerritPatchTuple(3, 3, False)
    c4 = metadata_lib.GerritPatchTuple(4, 4, False)

    launcher_build_id = self.fake_db.InsertBuild(
        constants.PRE_CQ_LAUNCHER_NAME, constants.WATERFALL_INTERNAL,
        1, constants.PRE_CQ_LAUNCHER_CONFIG, 'bot hostname 1')
    pineapple_build_id = self.fake_db.InsertBuild(
        'pineapple', constants.WATERFALL_TRYBOT, 87, 'pineapple-pre-cq',
        'pineapple hostname')
    guava_build_id = self.fake_db.InsertBuild(
        'guava', constants.WATERFALL_TRYBOT, 7, 'guava-pre-cq',
        'guava hostname')

    # c1 has 3 pending verifications, but only 1 inflight and 1
    # launching, so it is not busy.
    self._Act(launcher_build_id, c1,
              constants.CL_ACTION_VALIDATION_PENDING_PRE_CQ,
              'pineapple-pre-cq')
    self._Act(launcher_build_id, c1,
              constants.CL_ACTION_VALIDATION_PENDING_PRE_CQ,
              'banana-pre-cq')
    self._Act(launcher_build_id, c1,
              constants.CL_ACTION_VALIDATION_PENDING_PRE_CQ,
              'guava-pre-cq')
    self._Act(launcher_build_id, c1,
              constants.CL_ACTION_TRYBOT_LAUNCHING,
              'banana-pre-cq')
    self._Act(pineapple_build_id, c1, constants.CL_ACTION_PICKED_UP)

    # c2 has 3 pending verifications, 1 inflight and 1 launching, and 1 passed,
    # so it is busy.
    self._Act(launcher_build_id, c2,
              constants.CL_ACTION_VALIDATION_PENDING_PRE_CQ,
              'pineapple-pre-cq')
    self._Act(launcher_build_id, c2,
              constants.CL_ACTION_VALIDATION_PENDING_PRE_CQ,
              'banana-pre-cq')
    self._Act(launcher_build_id, c2,
              constants.CL_ACTION_VALIDATION_PENDING_PRE_CQ,
              'guava-pre-cq')
    self._Act(launcher_build_id, c2, constants.CL_ACTION_TRYBOT_LAUNCHING,
              'banana-pre-cq')
    self._Act(pineapple_build_id, c2, constants.CL_ACTION_PICKED_UP)
    self._Act(guava_build_id, c2, constants.CL_ACTION_VERIFIED)

    # c3 has 2 pending verifications, both passed, so it is passed.
    self._Act(launcher_build_id, c3,
              constants.CL_ACTION_VALIDATION_PENDING_PRE_CQ,
              'pineapple-pre-cq')
    self._Act(launcher_build_id, c3,
              constants.CL_ACTION_VALIDATION_PENDING_PRE_CQ,
              'guava-pre-cq')
    self._Act(pineapple_build_id, c3, constants.CL_ACTION_VERIFIED)
    self._Act(guava_build_id, c3, constants.CL_ACTION_VERIFIED)

    # c4 has not even been screened.

    changes = [c1, c2, c3, c4]
    action_history = self.fake_db.GetActionsForChanges(changes)
    progress_map = clactions.GetPreCQProgressMap(changes, action_history)

    self.assertEqual(({c2}, {c3}), clactions.GetPreCQCategories(progress_map))

    # Among changes c1, c2, c3, only the guava-pre-cq config is pending. The
    # other configs are either inflight, launching, or passed everywhere.
    screened_changes = set(changes).intersection(progress_map)
    self.assertEqual({'guava-pre-cq'},
                     clactions.GetPreCQConfigsToTest(screened_changes,
                                                      progress_map))

class TestCLStatusCounter(cros_test_lib.TestCase):
  """Tests that GetCLActionCount behaves as expected."""

  def setUp(self):
    self.fake_db = fake_cidb.FakeCIDBConnection()

  def testGetCLActionCount(self):
    c1p1 = metadata_lib.GerritPatchTuple(1, 1, False)
    c1p2 = metadata_lib.GerritPatchTuple(1, 2, False)
    precq_build_id = self.fake_db.InsertBuild(constants.PRE_CQ_LAUNCHER_NAME,
        constants.WATERFALL_INTERNAL, 1, constants.PRE_CQ_LAUNCHER_CONFIG,
        'bot-hostname')
    melon_build_id = self.fake_db.InsertBuild('melon builder name',
        constants.WATERFALL_INTERNAL, 1, 'melon-config-name',
        'grape-bot-hostname')

    # Count should be zero before any actions are recorded.

    action_history = self.fake_db.GetActionsForChanges([c1p1])
    self.assertEqual(
        0,
        clactions.GetCLActionCount(
            c1p1, validation_pool.CQ_PIPELINE_CONFIGS,
            constants.CL_ACTION_KICKED_OUT, action_history))

    # Record 3 failures for c1p1, and some other actions. Only count the
    # actions from builders in validation_pool.CQ_PIPELINE_CONFIGS.
    self.fake_db.InsertCLActions(
        precq_build_id,
        [clactions.CLAction.FromGerritPatchAndAction(
            c1p1, constants.CL_ACTION_KICKED_OUT)])
    self.fake_db.InsertCLActions(
        precq_build_id,
        [clactions.CLAction.FromGerritPatchAndAction(
            c1p1, constants.CL_ACTION_PICKED_UP)])
    self.fake_db.InsertCLActions(
        precq_build_id,
        [clactions.CLAction.FromGerritPatchAndAction(
            c1p1, constants.CL_ACTION_KICKED_OUT)])
    self.fake_db.InsertCLActions(
        melon_build_id,
        [clactions.CLAction.FromGerritPatchAndAction(
            c1p1, constants.CL_ACTION_KICKED_OUT)])

    action_history = self.fake_db.GetActionsForChanges([c1p1])
    self.assertEqual(
        2,
        clactions.GetCLActionCount(
            c1p1, validation_pool.CQ_PIPELINE_CONFIGS,
            constants.CL_ACTION_KICKED_OUT, action_history))

    # Record a failure for c1p2. Now the latest patches failure count should be
    # 1 (true weather we pass c1p1 or c1p2), whereas the total failure count
    # should be 3.
    self.fake_db.InsertCLActions(
        precq_build_id,
        [clactions.CLAction.FromGerritPatchAndAction(
            c1p2, constants.CL_ACTION_KICKED_OUT)])

    action_history = self.fake_db.GetActionsForChanges([c1p1])
    self.assertEqual(
        1,
        clactions.GetCLActionCount(
            c1p1, validation_pool.CQ_PIPELINE_CONFIGS,
            constants.CL_ACTION_KICKED_OUT, action_history))
    self.assertEqual(
        1,
        clactions.GetCLActionCount(
            c1p2, validation_pool.CQ_PIPELINE_CONFIGS,
            constants.CL_ACTION_KICKED_OUT, action_history))
    self.assertEqual(
        3,
        clactions.GetCLActionCount(
            c1p2, validation_pool.CQ_PIPELINE_CONFIGS,
            constants.CL_ACTION_KICKED_OUT, action_history,
            latest_patchset_only=False))


if __name__ == '__main__':
  cros_test_lib.main()
