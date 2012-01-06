#!/usr/bin/python

# Copyright (c) 2011 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Unittests for manifest_version. Needs to be run inside of chroot for mox."""

import mox
import os
import shutil
import sys
import tempfile
import unittest

if __name__ == '__main__':
  import constants
  sys.path.append(constants.SOURCE_ROOT)

from chromite.buildbot import cbuildbot_config
from chromite.buildbot import manifest_version
from chromite.buildbot import repository
from chromite.lib import cros_build_lib as cros_lib

# pylint: disable=W0212,R0904
FAKE_VERSION = """
CHROMEOS_BUILD=1
CHROMEOS_BRANCH=2
CHROMEOS_PATCH=3
CHROME_BRANCH=13
"""

FAKE_VERSION_STRING = '1.2.3'
FAKE_VERSION_STRING_NEXT = '1.2.4'
CHROME_BRANCH = '13'

# Dir to use to sync repo for git testing.
GIT_DIR = '/tmp/repo_for_manifest_version_unittest'

# Use the chromite repo to actually test git changes.
GIT_TEST_PATH = 'chromite'

def TouchFile(file_path):
  """Touches a file specified by file_path"""
  if not os.path.exists(os.path.dirname(file_path)):
    os.makedirs(os.path.dirname(file_path))

  touch_file = open(file_path, 'w+')
  touch_file.close()


class HelperMethodsTest(unittest.TestCase):
  """Test methods associated with methods not in a class."""

  def setUp(self):
    self.tmpdir = tempfile.mkdtemp()

  def testCreateSymlink(self):
    """Tests that we can create symlinks and remove a previous one."""
    (unused_fd, srcfile) = tempfile.mkstemp(dir=self.tmpdir)
    destfile1 = tempfile.mktemp(dir=os.path.join(self.tmpdir, 'other_dir1'))
    destfile2 = tempfile.mktemp(dir=os.path.join(self.tmpdir, 'other_dir2'))

    manifest_version.CreateSymlink(srcfile, destfile1, remove_file=None)
    self.assertTrue(os.path.lexists(destfile1),
                    'Unable to create symlink to %s' % destfile1)

    manifest_version.CreateSymlink(srcfile, destfile2, remove_file=destfile1)
    self.assertTrue(os.path.lexists(destfile2),
                    'Unable to create symlink to %s' % destfile2)
    self.assertFalse(os.path.lexists(destfile1),
                    'Unable to remove symlink %s' % destfile1)

  def testRemoveDirs(self):
    """Tests if _RemoveDirs works with a recursive directory structure."""
    otherdir1 = tempfile.mkdtemp(dir=self.tmpdir)
    tempfile.mkdtemp(dir=otherdir1)
    manifest_version._RemoveDirs(otherdir1)
    self.assertFalse(os.path.exists(otherdir1), 'Failed to rmdirs.')

  def testPushGitChanges(self):
    """Tests if we can append to an authors file and push it using dryrun."""
    if not os.path.exists(GIT_DIR): os.makedirs(GIT_DIR)
    init_cmd = ['repo', 'init', '-u', constants.MANIFEST_URL, '--repo-url',
                constants.REPO_URL, '-m', 'minilayout.xml']
    cros_lib.RunCommand(init_cmd, cwd=GIT_DIR, input='\n\ny\n')
    cros_lib.RunCommand(('repo sync --jobs 8').split(), cwd=GIT_DIR)
    git_dir = os.path.join(GIT_DIR, GIT_TEST_PATH)
    cros_lib.RunCommand(['git',
                         'config',
                         'url.%s.insteadof' % constants.GERRIT_SSH_URL,
                         constants.GIT_HTTP_URL], cwd=git_dir)

    manifest_version.PrepForChanges(git_dir, dry_run=True)

    # Change something.
    cros_lib.RunCommand(('tee --append %s/AUTHORS' % git_dir).split(),
                        input='TEST USER <test_user@chromium.org>')

    # Push the change with dryrun.
    manifest_version._PushGitChanges(git_dir, 'Test appending user.',
                                     dry_run=True)

  def testPushGitChangesWithRealPrep(self):
    """Another push test that tests push but on non-repo does it on a branch."""
    git_dir = tempfile.mktemp('manifest_dir')
    manifest_versions_url = cbuildbot_config.GetManifestVersionsRepoUrl(
        internal_build=False, read_only=True)
    cros_lib.RunCommand(['git', 'clone', manifest_versions_url, git_dir])
    try:
      cros_lib.RunCommand(['git',
                           'config',
                           'url.%s.insteadof' % constants.GERRIT_SSH_URL,
                           constants.GIT_HTTP_URL], cwd=git_dir)

      manifest_version.PrepForChanges(git_dir, dry_run=False)

      # This should not error out if we are running with dry_run=False for
      # prep for changes.
      cros_lib.RunCommand(['git', 'show', manifest_version.PUSH_BRANCH],
                          cwd=git_dir)

      # Change something.
      cros_lib.RunCommand(('tee --append %s/AUTHORS' % git_dir).split(),
                          input='TEST USER <test_user@chromium.org>')

      # Push the change with dryrun.
      manifest_version._PushGitChanges(git_dir, 'Test appending user.',
                                       dry_run=True)

      # This should not error out if we are running with dry_run=False for
      # prep for changes.
      cros_lib.RunCommand(['git', 'show', manifest_version.PUSH_BRANCH],
                          cwd=git_dir)
    finally:
      shutil.rmtree(git_dir)

  def tearDown(self):
    shutil.rmtree(self.tmpdir)


class VersionInfoTest(mox.MoxTestBase):
  """Test methods testing methods in VersionInfo class."""

  def setUp(self):
    mox.MoxTestBase.setUp(self)
    self.tmpdir = tempfile.mkdtemp()

  @classmethod
  def CreateFakeVersionFile(cls, tmpdir):
    """Helper method to create a version file from FAKE_VERSION."""
    (version_file_fh, version_file) = tempfile.mkstemp(dir=tmpdir)
    os.write(version_file_fh, FAKE_VERSION)
    os.close(version_file_fh)
    return version_file

  def testLoadFromFile(self):
    """Tests whether we can load from a version file."""
    version_file = self.CreateFakeVersionFile(self.tmpdir)
    info = manifest_version.VersionInfo(version_file=version_file)
    self.assertEqual(info.VersionString(), FAKE_VERSION_STRING)

  def testLoadFromString(self):
    """Tests whether we can load from a string."""
    info = manifest_version.VersionInfo(FAKE_VERSION_STRING, CHROME_BRANCH)
    self.assertEqual(info.VersionString(), FAKE_VERSION_STRING)

  def CommonTestIncrementVersion(self, incr_type):
    """Common test increment.  Returns path to new incremented file."""
    message = 'Incrementing cuz I sed so'
    self.mox.StubOutWithMock(manifest_version, 'PrepForChanges')
    self.mox.StubOutWithMock(manifest_version, '_PushGitChanges')

    manifest_version.PrepForChanges(self.tmpdir, False)

    version_file = self.CreateFakeVersionFile(self.tmpdir)

    manifest_version._PushGitChanges(self.tmpdir, message, dry_run=False)

    self.mox.ReplayAll()
    info = manifest_version.VersionInfo(version_file=version_file,
                                        incr_type=incr_type)
    info.IncrementVersion(message, dry_run=False)
    self.mox.VerifyAll()
    return version_file

  def testIncrementVersionPatch(self):
    """Tests whether we can increment a version file by patch number."""
    version_file = self.CommonTestIncrementVersion('patch')
    new_info = manifest_version.VersionInfo(version_file=version_file,
                                            incr_type='patch')
    self.assertEqual(new_info.VersionString(), FAKE_VERSION_STRING_NEXT)

  def testIncrementVersionBranch(self):
    """Tests whether we can increment a version file by branch number."""
    version_file = self.CommonTestIncrementVersion('branch')
    new_info = manifest_version.VersionInfo(version_file=version_file,
                                            incr_type='branch')
    self.assertEqual(new_info.VersionString(), '1.3.0')

  def testIncrementVersionBuild(self):
    """Tests whether we can increment a version file by build number."""
    version_file = self.CommonTestIncrementVersion('build')
    new_info = manifest_version.VersionInfo(version_file=version_file,
                                            incr_type='build')
    self.assertEqual(new_info.VersionString(), '2.0.0')

  def tearDown(self):
    shutil.rmtree(self.tmpdir)


class BuildSpecsManagerTest(mox.MoxTestBase):
  """Tests for the BuildSpecs manager."""

  def setUp(self):
    mox.MoxTestBase.setUp(self)

    self.tmpdir = tempfile.mkdtemp()
    os.makedirs(os.path.join(self.tmpdir, '.repo'))
    self.source_repo = 'ssh://source/repo'
    self.manifest_repo = 'ssh://manifest/repo'
    self.version_file = 'version-file.sh'
    self.branch = 'master'
    self.build_name = 'x86-generic'
    self.incr_type = 'patch'

    # Change default to something we clean up.
    self.tmpmandir = tempfile.mkdtemp()
    manifest_version.BuildSpecsManager._TMP_MANIFEST_DIR = self.tmpmandir

    repo = repository.RepoRepository(
      self.source_repo, self.tmpdir, self.branch)
    self.manager = manifest_version.BuildSpecsManager(
      repo, self.manifest_repo, self.build_name, self.incr_type, dry_run=True)

  def testLoadSpecs(self):
    """Tests whether we can load specs correctly."""
    self.mox.StubOutWithMock(manifest_version, '_RemoveDirs')
    self.mox.StubOutWithMock(repository, 'CloneGitRepo')
    info = manifest_version.VersionInfo(
        FAKE_VERSION_STRING, CHROME_BRANCH, incr_type='patch')
    m1 = os.path.join(self.manager._TMP_MANIFEST_DIR, 'buildspecs',
                      CHROME_BRANCH, '1.2.2.xml')
    m2 = os.path.join(self.manager._TMP_MANIFEST_DIR, 'buildspecs',
                      CHROME_BRANCH, '1.2.3.xml')
    m3 = os.path.join(self.manager._TMP_MANIFEST_DIR, 'buildspecs',
                      CHROME_BRANCH, '1.2.4.xml')
    m4 = os.path.join(self.manager._TMP_MANIFEST_DIR, 'buildspecs',
                      CHROME_BRANCH, '1.2.5.xml')
    for_build = os.path.join(self.manager._TMP_MANIFEST_DIR, 'build-name',
                             self.build_name)

    # Create fake buildspecs.
    TouchFile(m1)
    TouchFile(m2)
    TouchFile(m3)
    TouchFile(m4)

    # Fail 1, pass 2, leave 3,4 unprocessed.
    manifest_version.CreateSymlink(m1, os.path.join(
        for_build, 'fail', CHROME_BRANCH, os.path.basename(m1)))
    manifest_version.CreateSymlink(m1, os.path.join(
        for_build, 'pass', CHROME_BRANCH, os.path.basename(m2)))
    manifest_version._RemoveDirs(self.manager._TMP_MANIFEST_DIR)
    repository.CloneGitRepo(self.manager._TMP_MANIFEST_DIR,
                            self.manifest_repo)
    self.mox.StubOutWithMock(self.manager, '_GetSpecAge')
    self.manager._GetSpecAge('1.2.5').AndReturn(100)
    self.mox.ReplayAll()
    self.manager._LoadSpecs(info)
    self.mox.VerifyAll()
    self.assertEqual(self.manager.latest_unprocessed, '1.2.5')

  def testLatestSpecFromDir(self):
    """Tests whether we can get sorted specs correctly from a directory."""
    self.mox.StubOutWithMock(manifest_version, '_RemoveDirs')
    self.mox.StubOutWithMock(repository, 'CloneGitRepo')
    info = manifest_version.VersionInfo(
        '99.1.2', CHROME_BRANCH, incr_type='branch')

    specs_dir = os.path.join(self.manager._TMP_MANIFEST_DIR, 'buildspecs',
                             CHROME_BRANCH)
    m1 = os.path.join(specs_dir, '100.0.0.xml')
    m2 = os.path.join(specs_dir, '99.3.3.xml')
    m3 = os.path.join(specs_dir, '99.1.10.xml')
    m4 = os.path.join(specs_dir, '99.1.5.xml')

    # Create fake buildspecs.
    TouchFile(m1)
    TouchFile(m2)
    TouchFile(m3)
    TouchFile(m4)

    self.mox.ReplayAll()
    spec = self.manager._LatestSpecFromDir(info, specs_dir)
    self.mox.VerifyAll()
    # Should be the latest on the 99.1 branch
    self.assertEqual(spec, '99.3.3')

  def testCreateNewBuildSpecNoCopy(self):
    """Tests whether we can create a new build spec correctly.

    Tests without pre-existing version file in manifest dir.
    """
    self.mox.StubOutWithMock(repository.RepoRepository, 'ExportManifest')
    self.mox.StubOutWithMock(manifest_version, 'PrepForChanges')
    self.mox.StubOutWithMock(manifest_version, '_PushGitChanges')
    info = manifest_version.VersionInfo(
        FAKE_VERSION_STRING, CHROME_BRANCH, incr_type='patch')

    self.manager.all_specs_dir = os.path.join(self.manager._TMP_MANIFEST_DIR,
                                              'buildspecs', '1.2')

    repository.RepoRepository.ExportManifest(mox.IgnoreArg())

    self.mox.ReplayAll()
    version = self.manager._CreateNewBuildSpec(info)
    self.mox.VerifyAll()
    self.assertEqual(FAKE_VERSION_STRING, version)

  def testCreateNewBuildIncrement(self):
    """Tests that we create a new version if a previous one exists."""
    self.mox.StubOutWithMock(manifest_version.VersionInfo, 'IncrementVersion')
    self.mox.StubOutWithMock(repository.RepoRepository, 'ExportManifest')
    self.mox.StubOutWithMock(repository.RepoRepository, 'Sync')
    self.mox.StubOutWithMock(repository.RepoRepository, 'IsManifestDifferent')

    version_file = VersionInfoTest.CreateFakeVersionFile(self.tmpdir)
    info = manifest_version.VersionInfo(version_file=version_file,
                                         incr_type='patch')
    self.manager.all_specs_dir = os.path.join(self.manager._TMP_MANIFEST_DIR,
                                              'buildspecs', '1.2')
    info.IncrementVersion(
        'Automatic: %s - Updating to a new version number from %s' % (
            self.build_name, FAKE_VERSION_STRING),
        dry_run=True).AndReturn(FAKE_VERSION_STRING_NEXT)

    # TODO(ferringb): Gut the cleanup=False added for 24709.
    repository.RepoRepository.Sync('default', cleanup=False)
    repository.RepoRepository.ExportManifest(mox.IgnoreArg())
    repository.RepoRepository.IsManifestDifferent(mox.IgnoreArg()
       ).AndReturn(True)

    self.mox.ReplayAll()
    self.manager.latest = FAKE_VERSION_STRING
    version = self.manager._CreateNewBuildSpec(info)
    self.mox.VerifyAll()
    self.assertEqual(FAKE_VERSION_STRING_NEXT, version)

  def NotestGetNextBuildSpec(self):
    """Meta test.  Re-enable if you want to use it to do a big test."""
    print self.manager.GetNextBuildSpec(retries=0)
    print self.manager.UpdateStatus('pass')

  def tearDown(self):
    if os.path.exists(self.tmpdir): shutil.rmtree(self.tmpdir)
    shutil.rmtree(self.tmpmandir)


if __name__ == '__main__':
  unittest.main()
