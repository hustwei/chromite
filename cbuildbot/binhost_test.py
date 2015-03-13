# Copyright 2015 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Tests for verifying prebuilts."""

from __future__ import print_function

import collections
import tempfile
import warnings

from chromite.cbuildbot import binhost
from chromite.cbuildbot import cbuildbot_config
from chromite.lib import cros_build_lib
from chromite.lib import cros_test_lib
from chromite.lib import parallel


class CompatIdFetcher(object):
  """Class for calculating compat ids in parallel."""

  def __init__(self, caching=False):
    """Create a new CompatIdFetcher object.

    Args:
      caching: Whether to cache setup from run to run. See
        PrebuiltCompatibilityTest.CACHING for details.
    """
    self.compat_ids = None
    if caching:
      # This import occurs here rather than at the top of the file because we
      # don't want to force developers to install joblib. The caching argument
      # is only set to True if PrebuiltCompatibilityTest.CACHING is hand-edited
      # (for testing purposes).
      # pylint: disable=import-error
      from joblib import Memory
      memory = Memory(cachedir=tempfile.gettempdir(), verbose=0)
      self._FetchRawCompatIds = memory.cache(self._FetchRawCompatIds)

  def _FetchCompatId(self, board, extra_useflags):
    try:
      self.compat_ids[(board, extra_useflags)] = \
          binhost.CalculateCompatId(board, extra_useflags)
    except cros_build_lib.RunCommandError:
      cros_build_lib.Warning(
          'Ignoring error in board: %s', board, exc_info=True)

  def _FetchRawCompatIds(self):
    # pylint: disable=method-hidden
    cros_build_lib.Info('Fetching CompatId objects. This takes about 30s...')
    with parallel.Manager() as manager:
      self.compat_ids = manager.dict()
      inputs = set()
      for config in cbuildbot_config.config.values():
        for board in config.boards:
          inputs.add(binhost.GetBoardKey(config, board))
      parallel.RunTasksInProcessPool(self._FetchCompatId, inputs)
      return dict(self.compat_ids)

  def FetchAllCompatIds(self):
    """Generate a dict mapping BoardKeys to their associated CompatId."""
    return self._FetchRawCompatIds()


class PrebuiltCompatibilityTest(cros_test_lib.TestCase):
  """Ensure that prebuilts are present for all builders and are compatible."""

  # Whether to cache setup from run to run. If set, requires that you install
  # joblib (sudo easy_install joblib). This is useful for iterating on the
  # unit tests, but note that if you 'repo sync', you'll need to clear out
  # /tmp/joblib and blow away /build in order to update the caches. Note that
  # this is never normally set to True -- if you want to use this feature,
  # you'll need to hand-edit this file.
  # TODO(davidjames): Add a --caching option.
  CACHING = False

  # A dict mapping BoardKeys to their associated compat ids.
  COMPAT_IDS = None

  @classmethod
  def setUpClass(cls):
    assert cros_build_lib.IsInsideChroot()
    cros_build_lib.Info('Generating board configs. This takes 8.5m...')
    for key in sorted(binhost.GetAllBoardKeys()):
      binhost.GenConfigsForBoard(key.board, regen=not cls.CACHING,
                                 error_code_ok=True)
    fetcher = CompatIdFetcher(caching=cls.CACHING)
    cls.COMPAT_IDS = fetcher.FetchAllCompatIds()

  def setUp(self):
    self.complaints = []
    self.fatal_complaints = []

  def tearDown(self):
    if self.complaints:
      warnings.warn('\n' + '\n'.join(self.complaints))
    if self.fatal_complaints:
      self.assertFalse(self.fatal_complaints, '\n'.join(self.fatal_complaints))

  def Complain(self, msg, fatal):
    """Complain about an error when the test exits.

    Args:
      msg: The message to print.
      fatal: Whether the message should be fatal. If not, the message will be
        considered a warning.
    """
    if fatal:
      self.fatal_complaints.append(msg)
    else:
      self.complaints.append(msg)

  def GetCompatIdDiff(self, expected, actual):
    """Return a string describing the differences between expected and actual.

    Args:
      expected: Expected value for CompatId.
      actual: Actual value for CompatId.
    """
    if expected.arch != actual.arch:
      return 'arch differs: %s != %s' % (expected.arch, actual.arch)
    elif expected.useflags != actual.useflags:
      msg = self.GetSequenceDiff(expected.useflags, actual.useflags)
      return msg.replace('Sequences', 'useflags')
    elif expected.cflags != actual.cflags:
      msg = self.GetSequenceDiff(expected.cflags, actual.cflags)
      return msg.replace('Sequences', 'cflags')
    else:
      assert expected == actual
      return 'no differences'

  def AssertChromePrebuilts(self, pfq_by_compat_id, pfq_by_arch_useflags,
                            config):
    """Verify that the specified config has Chrome prebuilts.

    Args:
      pfq_by_compat_id: A dict mapping CompatIds to sets of BoardKey objects.
      pfq_by_arch_useflags: A dict mapping (arch, useflags) tuples to sets of
        BoardKey objects.
      config: The config to check.
    """
    compat_id = self.GetCompatId(config)
    pfqs = pfq_by_compat_id.get(compat_id, set())
    if not pfqs:
      arch_useflags = (compat_id.arch, compat_id.useflags)
      for key in pfq_by_arch_useflags[arch_useflags]:
        # If there wasn't an exact match for this CompatId, but there
        # was an (arch, useflags) match, then we'll be using mismatched
        # Chrome prebuilts. Complain.
        # TODO(davidjames): This should be a fatal error for important
        # builders, but we need to clean up existing cases first.
        pfq_compat_id = self.COMPAT_IDS[key]
        err = self.GetCompatIdDiff(compat_id, pfq_compat_id)
        msg = '%s uses mismatched Chrome prebuilts -- %s'
        self.Complain(msg % (config.name, err), fatal=False)
        pfqs.add(key)

    if not pfqs:
      pre_cq = (config.build_type == cbuildbot_config.CONFIG_TYPE_PRECQ)
      msg = '%s cannot find Chrome prebuilts -- %s'
      self.Complain(msg % (config.name, compat_id),
                    fatal=pre_cq or config.important)
    return pfqs

  def GetCompatId(self, config, board=None):
    """Get the CompatId for a config.

    Args:
      config: A cbuildbot_config._config object.
      board: Board to use. Defaults to the first board in the config.
          Optional if len(config.boards) == 1.
    """
    if board is None:
      assert len(config.boards) == 1
      board = config.boards[0]
    else:
      assert board in config.boards

    board_key = binhost.GetBoardKey(config, board)
    compat_id = self.COMPAT_IDS.get(board_key)
    if compat_id is None:
      compat_id = binhost.CalculateCompatId(board, config.useflags)
      self.COMPAT_IDS[board_key] = compat_id
    return compat_id

  def testChromePrebuiltsPresent(self):
    """Verify Chrome prebuilts exist for all configs that build Chrome."""
    pfq_by_compat_id = collections.defaultdict(set)
    pfq_by_arch_useflags = collections.defaultdict(set)
    for key in binhost.GetChromePrebuiltConfigs():
      compat_id = self.COMPAT_IDS[key]
      pfqs = pfq_by_compat_id[compat_id]
      pfqs.add(key)
      partial_compat_id = (compat_id.arch, compat_id.useflags)
      pfq_by_arch_useflags[partial_compat_id].add(key)

    for compat_id, pfqs in pfq_by_compat_id.items():
      if len(pfqs) > 1:
        msg = 'The following Chrome PFQs produce identical prebuilts: %s -- %s'
        self.Complain(msg % (', '.join(str(x) for x in pfqs), compat_id),
                      fatal=False)

    for _name, config in sorted(cbuildbot_config.config.items()):
      # Skip over configs that don't have Chrome or have >1 board.
      if config.sync_chrome is False or len(config.boards) != 1:
        continue

      # Look for boards with missing prebuilts.
      pre_cq = (config.build_type == cbuildbot_config.CONFIG_TYPE_PRECQ)
      if ((config.usepkg_build_packages and not config.chrome_rev) and
          (config.active_waterfall or pre_cq)):
        self.AssertChromePrebuilts(pfq_by_compat_id, pfq_by_arch_useflags,
                                   config)

  def testReleaseGroupSharing(self):
    """Verify that the boards built in release groups have compatible settings.

    This means that all of the subconfigs in the release group have matching
    use flags, cflags, and architecture.
    """
    for config in cbuildbot_config.config.values():
      # Only test release groups.
      if not config.name.endswith('-release-group'):
        continue

      # Get a list of the compatibility IDs.
      compat_ids_for_config = collections.defaultdict(set)
      for subconfig in config.child_configs:
        if subconfig.sync_chrome is not False:
          for board in subconfig.boards:
            compat_id = self.GetCompatId(subconfig, board)
            compat_ids_for_config[compat_id].add(board)

      if len(compat_ids_for_config) > 1:
        arch_useflags = set(tuple(x[:-1]) for x in compat_ids_for_config)
        if len(arch_useflags) > 1:
          # If two configs in the same group have mismatched Chrome binaries
          # (e.g. different use flags), Chrome may be built twice in parallel
          # and this may result in flaky, slow, and possibly incorrect builds.
          msg = '%s: Child configs have mismatched Chrome binaries -- %s'
          fatal = True
        else:
          # TODO(davidjames): This should be marked fatal once the
          # ivybridge-freon-release-group is cleaned up.
          msg = '%s: Child configs have mismatched cflags -- %s'
          fatal = False
        ids = list(compat_ids_for_config)
        err = self.GetCompatIdDiff(ids[0], ids[1])
        msg %= (config.name, err)
        self.Complain(msg, fatal=fatal)