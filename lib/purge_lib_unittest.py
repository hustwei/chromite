# Copyright (c) 2012 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Unit tests for the deploy_chrome script."""

from __future__ import print_function

from chromite.lib import cros_test_lib
from chromite.lib import gs
from chromite.lib import gs_unittest
from chromite.lib import purge_lib


# pylint: disable=W0212

class TestHelperMethods(cros_test_lib.TestCase):
  """Main tests."""

  def testKnownCases(self):
    """The stats upload path."""
    CASES = (
        ('cros/factory-veyron-7505.B', '7505'),
        ('origin/factory-2723.14.B', '2723.14'),
        ('remote/firmware-falco_peppy-4389.B', '4389'),
        ('factory-veyron-7505.B', '7505'),
        ('factory-2723.14.B', '2723.14'),
        ('firmware-falco_peppy-4389.B', '4389'),
    )

    for branch, expected in CASES:
      self.assertEqual(purge_lib.ParseBranchName(branch), expected)

  def testListRemoteBranches(self):
    branches = purge_lib.ListRemoteBranches()
    # We know there are more than 300 remote branches for chromite.
    self.assertGreater(len(branches), 300)

  def testProtectedBranchVersions(self):
    branch_names = [
        'cros/factory-veyron-7505.B',
        'origin/factory-2723.14.B',
        'remote/firmware-falco_peppy-4389.B',
    ]
    branch_versions = purge_lib.ProtectedBranchVersions(branch_names)
    # We know there are more than 100 firmware/factory branches.
    self.assertEqual(branch_versions, ['7505', '2723.14', '4389'])

  def testProtectedBranchVersionsLive(self):
    branches = purge_lib.ListRemoteBranches()
    branch_versions = purge_lib.ProtectedBranchVersions(branches)
    # We know there are more than 100 firmware/factory branches.
    self.assertGreater(len(branch_versions), 100)

    # cros/firmware-snow-2695.90.B is a known branch. Ensure it's listed.
    self.assertIn('2695.90', branch_versions)

  def testParseChromeosReleasesBuildUri(self):
    """Test parseChromeosReleasesBuildUri."""
    self.assertEqual(
        purge_lib.ParseChromeosReleasesBuildUri(
            'gs://chromeos-releases/canary-channel/duck/6652.0.0/'),
        '6652.0.0')

  def testVersionBranchMatch(self):
    """Test versionBranchMatch."""
    self.assertTrue(purge_lib.VersionBranchMatch('1.2.3', '1'))
    self.assertTrue(purge_lib.VersionBranchMatch('1.2.3', '1.2'))
    self.assertTrue(purge_lib.VersionBranchMatch('1.2.357', '1.2'))

    self.assertFalse(purge_lib.VersionBranchMatch('12.24.37', '1.2'))
    self.assertFalse(purge_lib.VersionBranchMatch('1.0.0', '1'))
    self.assertFalse(purge_lib.VersionBranchMatch('1.2.0', '1.2'))

  def testInBranches(self):
    """Test versionBranchMatch."""
    branches = ('1', '2.2', '5.3')
    self.assertTrue(purge_lib.InBranches('1.2.3', branches))
    self.assertTrue(purge_lib.InBranches('1.2.3', branches))
    self.assertTrue(purge_lib.InBranches('1.2.357', branches))
    self.assertTrue(purge_lib.InBranches('5.3.23', branches))

    self.assertFalse(purge_lib.InBranches('12.24.37', branches))
    self.assertFalse(purge_lib.InBranches('1.0.0', branches))
    self.assertFalse(purge_lib.InBranches('2.1.0', branches))
    self.assertFalse(purge_lib.InBranches('5.3.0', branches))


class TestBucketSearches(gs_unittest.AbstractGSContextTest):
  """Test GS interactions in purge_lib."""
  def mockResult(self, url):
    return gs.GSListResult(url, None, None, None, None)

  def testLocateChromeosReleasesProtectedPrefixes(self):
    """Test locateChromeosReleasesProtectedPrefixes."""
    protected_versions = ('6301', '7000.2')

    listResults = {
        'gs://chromeos-releases/canary-channel/': [
            self.mockResult(
                'gs://chromeos-releases/canary-channel/arkham/'),
            self.mockResult(
                'gs://chromeos-releases/canary-channel/x86-alex/'),
        ],
        'gs://chromeos-releases/canary-channel/arkham/': [
            self.mockResult(
                'gs://chromeos-releases/canary-channel/arkham/6301.1.0/'),
            self.mockResult(
                'gs://chromeos-releases/canary-channel/arkham/7023.0.0/'),
        ],
        'gs://chromeos-releases/canary-channel/x86-alex/': [
            self.mockResult(
                'gs://chromeos-releases/canary-channel/x86-alex/1.2.3/'),
            self.mockResult(
                'gs://chromeos-releases/canary-channel/x86-alex/1.2.4/'),
        ],
    }

    self.PatchObject(purge_lib, 'SafeList',
                     side_effect=lambda _, url: listResults[url])

    result = purge_lib.LocateChromeosReleasesProtectedPrefixes(
        self.ctx, protected_versions)

    self.assertEqual(result, [
        'gs://chromeos-releases/Attic',
        'gs://chromeos-releases/stable-channel',
        'gs://chromeos-releases/beta-channel',
        'gs://chromeos-releases/dev-channel',
        'gs://chromeos-releases/logs',
        'gs://chromeos-releases/tobesigned',
        'gs://chromeos-releases/canary-channel/arkham/6301.1.0/',
    ])

  def testLocateChromeosImageArchiveProtectedPrefixes(self):
    listResults = {
        'gs://chromeos-image-archive/': [
            self.mockResult(
                'gs://chromeos-image-archive/foo-paladin/'),
            self.mockResult(
                'gs://chromeos-image-archive/trybot-foo-paladin/'),
            self.mockResult(
                'gs://chromeos-image-archive/foo-factory/'),
            self.mockResult(
                'gs://chromeos-image-archive/trybot-foo-factory/'),
            self.mockResult(
                'gs://chromeos-image-archive/foo-firmware/'),
            self.mockResult(
                'gs://chromeos-image-archive/trybot-foo-firmware/'),
            self.mockResult(
                'gs://chromeos-image-archive/bar-firmware/'),
        ],
    }

    self.PatchObject(purge_lib, 'SafeList',
                     side_effect=lambda _, url: listResults[url])

    result = purge_lib.LocateChromeosImageArchiveProtectedPrefixes(self.ctx)

    self.assertEqual(result, [
        'gs://chromeos-image-archive/foo-firmware/',
        'gs://chromeos-image-archive/bar-firmware/',
    ])

  def testProduceFilteredCandidatesArchive(self):
    self.maxDiff = None

    protected_prefixes = (
        'gs://chromeos-image-archive/foo-firmware',
        'gs://chromeos-image-archive/bar-firmware',
    )

    listResults = {
        'gs://chromeos-image-archive/': [
            self.mockResult(
                'gs://chromeos-image-archive/foo-paladin/'),
            self.mockResult(
                'gs://chromeos-image-archive/trybot-foo-paladin/'),
            self.mockResult(
                'gs://chromeos-image-archive/foo-factory/'),
            self.mockResult(
                'gs://chromeos-image-archive/trybot-foo-factory/'),
            self.mockResult(
                'gs://chromeos-image-archive/foo-firmware/'),
            self.mockResult(
                'gs://chromeos-image-archive/trybot-foo-firmware/'),
            self.mockResult(
                'gs://chromeos-image-archive/bar-firmware/'),
        ],
        'gs://chromeos-image-archive/foo-paladin/': [
            self.mockResult(
                'gs://chromeos-image-archive/foo-paladin/plain_file'),
            self.mockResult(
                'gs://chromeos-image-archive/foo-paladin/1.2.3/'),
        ],
        'gs://chromeos-image-archive/foo-paladin/1.2.3/**': [
            self.mockResult(
                'gs://chromeos-image-archive/foo-paladin/1.2.3/a'),
            self.mockResult(
                'gs://chromeos-image-archive/foo-paladin/1.2.3/b'),
            self.mockResult(
                'gs://chromeos-image-archive/foo-paladin/1.2.3/nested/c'),
        ],
        'gs://chromeos-image-archive/trybot-foo-paladin/': [
        ],
        'gs://chromeos-image-archive/foo-factory/': [
        ],
        'gs://chromeos-image-archive/trybot-foo-factory/': [
        ],
        'gs://chromeos-image-archive/trybot-foo-firmware/': [
        ],
    }

    self.PatchObject(purge_lib, 'SafeList',
                     side_effect=lambda _, url: listResults[url])

    result = purge_lib.ProduceFilteredCandidates(
        self.ctx, 'gs://chromeos-image-archive/', protected_prefixes, 2)

    self.assertEqual(list(result), [
        self.mockResult(
            'gs://chromeos-image-archive/foo-paladin/plain_file'),
        self.mockResult(
            'gs://chromeos-image-archive/foo-paladin/1.2.3/a'),
        self.mockResult(
            'gs://chromeos-image-archive/foo-paladin/1.2.3/b'),
        self.mockResult(
            'gs://chromeos-image-archive/foo-paladin/1.2.3/nested/c'),
    ])

  def testProduceFilteredCandidatesReleases(self):
    self.maxDiff = None

    protected_prefixes = (
        'gs://chromeos-releases/stable-channel',
        'gs://chromeos-releases/beta-channel',
        'gs://chromeos-releases/dev-channel',
        'gs://chromeos-releases/logs',
        'gs://chromeos-releases/canary-channel/auron/6301.18.0/',
    )

    listResults = {
        'gs://chromeos-releases/': [
            self.mockResult(
                'gs://chromeos-releases/stable-channel/'),
            self.mockResult(
                'gs://chromeos-releases/beta-channel/'),
            self.mockResult(
                'gs://chromeos-releases/dev-channel/'),
            self.mockResult(
                'gs://chromeos-releases/canary-channel/'),
            self.mockResult(
                'gs://chromeos-releases/logs/'),
            self.mockResult(
                'gs://chromeos-releases/top-level-file'),
        ],
        'gs://chromeos-releases/canary-channel/': [
            self.mockResult(
                'gs://chromeos-releases/canary-channel/plain_file'),
            self.mockResult(
                'gs://chromeos-releases/canary-channel/foo-board/'),
            self.mockResult(
                'gs://chromeos-releases/canary-channel/auron/'),
        ],
        'gs://chromeos-releases/canary-channel/foo-board/': [
            self.mockResult(
                'gs://chromeos-releases/canary-channel/foo-board/6301.18.0/'),
        ],
        'gs://chromeos-releases/canary-channel/foo-board/6301.18.0/**': [
            self.mockResult(
                'gs://chromeos-releases/canary-channel/foo-board/6301.18.0/a'),
            self.mockResult(
                'gs://chromeos-releases/canary-channel/foo-board/6301.18.0/b'),
        ],
        'gs://chromeos-releases/canary-channel/auron/': [
            self.mockResult(
                'gs://chromeos-releases/canary-channel/auron/6301.18.0/'),
            self.mockResult(
                'gs://chromeos-releases/canary-channel/auron/7301.18.0/'),
        ],
        'gs://chromeos-releases/canary-channel/auron/7301.18.0/**': [
            self.mockResult(
                'gs://chromeos-releases/canary-channel/auron/7301.18.0/a'),
            self.mockResult(
                'gs://chromeos-releases/canary-channel/auron/7301.18.0/b'),
        ],
    }

    self.PatchObject(purge_lib, 'SafeList',
                     side_effect=lambda _, url: listResults[url])

    result = purge_lib.ProduceFilteredCandidates(
        self.ctx, 'gs://chromeos-releases/', protected_prefixes, 3)

    self.assertEqual(list(result), [
        self.mockResult(
            'gs://chromeos-releases/canary-channel/plain_file'),
        self.mockResult(
            'gs://chromeos-releases/canary-channel/foo-board/6301.18.0/a'),
        self.mockResult(
            'gs://chromeos-releases/canary-channel/foo-board/6301.18.0/b'),
        self.mockResult(
            'gs://chromeos-releases/canary-channel/auron/7301.18.0/a'),
        self.mockResult(
            'gs://chromeos-releases/canary-channel/auron/7301.18.0/b'),
        self.mockResult(
            'gs://chromeos-releases/top-level-file'),
    ])