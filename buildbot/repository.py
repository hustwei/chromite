# Copyright (c) 2011 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""
Repository module to handle different types of repositories the Builders use.
"""

import constants
import logging
import os
import re
import shutil

from chromite.buildbot import configure_repo
from chromite.lib import cros_build_lib
from chromite.lib import osutils
from chromite.lib import rewrite_git_alternates

# File that marks a buildroot as being used by a trybot
_TRYBOT_MARKER = '.trybot'


class SrcCheckOutException(Exception):
  """Exception gets thrown for failure to sync sources"""
  pass


def InARepoRepository(directory, require_project=False):
  """Returns True if directory is part of a repo checkout.

  Args:
    directory: Path to check.
    require_project: Whether to require that directory is inside a valid
     project in the repo root.
  """
  directory = os.path.abspath(directory)
  while not os.path.isdir(directory):
    directory = os.path.dirname(directory)

  if require_project:
    cmd = ['repo', 'forall', '.', '-c', 'true']
  else:
    cmd = ['repo']

  output = cros_build_lib.RunCommand(
      cmd, error_code_ok=True, redirect_stdout=True, redirect_stderr=True,
      cwd=directory, print_cmd=False)
  return output.returncode == 0


def IsARepoRoot(directory):
  """Returns True if directory is the root of a repo checkout."""
  # Check for the underlying git-repo checkout.  If it exists, it's
  # definitely the repo root.  If it doesn't, it may be an aborted
  # checkout- either way it isn't usable.
  repo_dir = os.path.join(directory, '.repo')
  return (os.path.isdir(os.path.join(repo_dir, 'repo')) and
          os.path.isdir(os.path.join(repo_dir, 'manifests')))


def IsInternalRepoCheckout(root):
  """Returns whether root houses an internal 'repo' checkout."""
  manifest_dir = os.path.join(root, '.repo', 'manifests')
  manifest_url = cros_build_lib.RunGitCommand(
      manifest_dir, ['config', 'remote.origin.url']).output.strip()
  return (os.path.splitext(os.path.basename(manifest_url))[0]
          == os.path.splitext(os.path.basename(constants.MANIFEST_INT_URL))[0])


def CloneGitRepo(working_dir, repo_url, reference=None, bare=False):
  """Clone given git repo
  Args:
    repo_url: git repo to clone
    repo_dir: location where it should be cloned to
    reference: If given, pathway to a git repository to access git objects
      from.  Note that the reference must exist as long as the newly created
      repo is to be usable.
    bare: Clone a bare checkout.
  """
  osutils.SafeMakedirs(working_dir)
  cmd = ['git', 'clone', repo_url, working_dir]
  if reference:
    cmd += ['--reference', reference]
  if bare:
    cmd += ['--bare']
  cros_build_lib.RunCommandCaptureOutput(cmd, cwd=working_dir)


def GetTrybotMarkerPath(buildroot):
  """Get path to trybot marker file given the buildroot."""
  return os.path.join(buildroot, _TRYBOT_MARKER)


def CreateTrybotMarker(buildroot):
  """Create the file that identifies a buildroot as being used by a trybot."""
  osutils.WriteFile(GetTrybotMarkerPath(buildroot), '')

def ClearBuildRoot(buildroot, preserve_paths=()):
  """Remove and recreate the buildroot while preserving the trybot marker."""
  trybot_root = os.path.exists(GetTrybotMarkerPath(buildroot))
  if os.path.exists(buildroot):
    cmd = ['find', buildroot, '-mindepth', '1', '-maxdepth', '1']

    ignores = []
    for path in preserve_paths:
      if ignores:
        ignores.append('-a')
      ignores += ['!', '-name', path]
    cmd.extend(ignores)

    cmd += ['-exec', 'rm', '-rf', '{}', '+']
    cros_build_lib.SudoRunCommand(cmd)
  else:
    os.makedirs(buildroot)
  if trybot_root:
    CreateTrybotMarker(buildroot)


class RepoRepository(object):
  """ A Class that encapsulates a repo repository.
  Args:
    repo_url: gitserver URL to fetch repo manifest from.
    directory: local path where to checkout the repository.
    branch: Branch to check out the manifest at.
  """
  DEFAULT_MANIFEST = 'default'
  # Use our own repo, in case android.kernel.org (the default location) is down.
  _INIT_CMD = ['repo', 'init', '--repo-url', constants.REPO_URL]

  def __init__(self, repo_url, directory, branch=None, referenced_repo=None,
               manifest=None, depth=None):
    self.repo_url = repo_url
    self.directory = directory
    self.branch = branch

    # It's perfectly acceptable to pass in a reference pathway that isn't
    # usable.  Detect it, and suppress the setting so that any depth
    # settings aren't disabled due to it.
    if referenced_repo is not None and not IsARepoRoot(referenced_repo):
      referenced_repo = None
    self._referenced_repo = referenced_repo
    self._manifest = manifest

    # If the repo exists already, force a selfupdate as the first step.
    self._repo_update_needed = IsARepoRoot(self.directory)
    if not self._repo_update_needed and InARepoRepository(self.directory):
      raise ValueError('Given directory %s is not the root of a repository.'
                       % self.directory)

    if depth is not None and referenced_repo is None:
      depth = int(depth)
    self._depth = depth

  def _SwitchToLocalManifest(self, local_manifest):
    """Reinitializes the repository if the manifest has changed."""
    logging.debug('Moving to manifest defined by %s', local_manifest)
    # TODO: use upstream repo's manifest logic when we bump repo version.
    manifest_path = self.GetRelativePath('.repo/manifest.xml')
    os.unlink(manifest_path)
    shutil.copyfile(local_manifest, manifest_path)

  def Initialize(self, local_manifest=None, extra_args=()):
    """Initializes a repository.  Optionally forces a local manifest.

    Args:
      local_manifest: The absolute path to a custom manifest to use.  This will
                      replace .repo/manifest.xml.
      extra_args: Extra args to pass to 'repo init'
    """
    # Base command.
    # Force a repo self update first; during reinit, repo doesn't do the
    # update itself, but we could be doing the init on a repo version less
    # then v1.9.4, which didn't have proper support for doing reinit that
    # involved changing the manifest branch in use; thus selfupdate.
    # Additionally, if the self update fails for *any* reason, wipe the repo
    # innards and force repo init to redownload it; same end result, just
    # less efficient.
    # Additionally, note that this method may be called multiple times;
    # thus code appropriately.
    if self._repo_update_needed:
      try:
        cros_build_lib.RunCommand(['repo', 'selfupdate'], cwd=self.directory)
      except cros_build_lib.RunCommandError:
        shutil.rmtree(os.path.join(self.directory, '.repo', 'repo'))
      self._repo_update_needed = False

    init_cmd = self._INIT_CMD + ['--manifest-url', self.repo_url]
    if self._referenced_repo:
      init_cmd.extend(['--reference', self._referenced_repo])
    if self._manifest:
      init_cmd.extend(['--manifest-name', self._manifest])
    if self._depth is not None:
      init_cmd.extend(['--depth', str(self._depth)])
    init_cmd.extend(extra_args)
    # Handle branch / manifest options.
    if self.branch:
      init_cmd.extend(['--manifest-branch', self.branch])

    cros_build_lib.RunCommand(init_cmd, cwd=self.directory, input='\n\ny\n')
    self._FixRepoManifestBugs()
    if local_manifest and local_manifest != self.DEFAULT_MANIFEST:
      self._SwitchToLocalManifest(local_manifest)

  def _FixRepoManifestBugs(self):
    # pylint: disable=C0301
    # Repo v1.9.4 has some known bugs; see
    # https://groups.google.com/forum/?fromgroups#!msg/repo-discuss/4WmUJ2ttN8o/ssYVLO5TCVYJ
    # TODO(ferringb): Remove this, both via upstream fixes, and via running
    # down where/why cbuildbot is stupidly leaving the manifest on a
    # detached HEAD.
    path = os.path.join(self.directory, '.repo', 'manifests')
    branch = ('master' if not self.branch else
              cros_build_lib.StripLeadingRefsHeads(self.branch, False))
    if cros_build_lib.GetCurrentBranch(path) != 'default':
      # This actually isn't a repo bug; something within cbuildbot, or an
      # interaction w/ repo's misbehaviours, results in this occuring.
      logging.warn("Repository %s had it's manifest on a branch other than "
                   "repo's norm of 'default'; fixing it.", self.directory)
      cros_build_lib.RunGitCommand(
        path, ['checkout', '-B', 'default',
               '-t', 'remotes/origin/%s' % branch])
    else:
      # During branch switches, v1.9.4 is known to leave an invalid git
      # configuration in place; thus manually force these settings.
      cros_build_lib.RunGitCommand(
          path, ['config', 'branch.default.origin', 'origin'])
      cros_build_lib.RunGitCommand(
          path, ['config', 'branch.default.merge', branch])

  @property
  def _ManifestConfig(self):
    return os.path.join(self.directory, '.repo', 'manifests.git', 'config')

  def _EnsureMirroring(self, post_sync=False):
    """Ensure git is usable from w/in the chroot if --references is enabled

    repo init --references hardcodes the abspath to parent; this pathway
    however isn't usable from the chroot (it doesn't exist).  As such the
    pathway is rewritten to use relative pathways pointing at the root of
    the repo, which via I84988630 enter_chroot sets up a helper bind mount
    allowing git/repo to access the actual referenced repo.

    This has to be invoked prior to a repo sync of the target trybot to
    fix any pathways that may have been broken by the parent repo moving
    on disk, and needs to be invoked after the sync has completed to rewrite
    any new project's abspath to relative.
    """

    if not self._referenced_repo:
      return

    proj_root = os.path.join(self.directory, '.repo', 'projects')
    if not os.path.exists(proj_root):
      # Not yet synced, nothing to be done.
      return

    rewrite_git_alternates.RebuildRepoCheckout(self.directory,
                                               self._referenced_repo)

    if post_sync:
      chroot_path = os.path.join(self._referenced_repo, '.repo', 'chroot',
                                 'external')
      chroot_path = cros_build_lib.ReinterpretPathForChroot(chroot_path)
      rewrite_git_alternates.RebuildRepoCheckout(
          self.directory, self._referenced_repo, chroot_path)

    # Finally, force the git config marker that enter_chroot looks for
    # to know when to do bind mounting trickery; this normally will exist,
    # but if we're converting a pre-existing repo checkout, it's possible
    # that it was invoked w/out the reference arg.  Note this must be
    # an absolute path to the source repo- enter_chroot uses that to know
    # what to bind mount into the chroot.
    cros_build_lib.RunCommand(
        ['git', 'config', '--file', self._ManifestConfig, 'repo.reference',
         self._referenced_repo])

  def Sync(self, local_manifest=None, jobs=None, cleanup=True):
    """Sync/update the source.  Changes manifest if specified.

    Args:
      local_manifest:  If set, checks out source to manifest.  DEFAULT_MANIFEST
        may be used to set it back to the default manifest.
      jobs: may be set to override the default sync parallelism defined by
        the manifest.
    """
    try:
      # Always re-initialize to the current branch.
      self.Initialize(local_manifest)
      # Fix existing broken mirroring configurations.
      self._EnsureMirroring()

      if cleanup:
        configure_repo.FixBrokenExistingRepos(self.directory)

      cmd = ['repo', '--time', 'sync']
      if jobs:
        cmd += ['--jobs', str(jobs)]
      cros_build_lib.RunCommandWithRetries(2, cmd, cwd=self.directory)

      # Setup gerrit remote for any new repositories.
      configure_repo.SetupGerritRemote(self.directory)

      # We do a second run to fix any new repositories created by repo to
      # use relative object pathways.  Note that cros_sdk also triggers the
      # same cleanup- we however kick it erring on the side of caution.
      self._EnsureMirroring(True)

    except cros_build_lib.RunCommandError, e:
      err_msg = 'Failed to sync sources %s' % e.message
      logging.error(err_msg)
      raise SrcCheckOutException(err_msg)

  def GetRelativePath(self, path):
    """Returns full path including source directory of path in repo."""
    return os.path.join(self.directory, path)

  def ExportManifest(self, mark_revision=False, revisions=True):
    """Export the revision locked manifest

    Args:
      mark_revision: If True, then the sha1 of manifest.git is recorded
        into the resultant manifest tag as a version attribute.
        Specifically, if manifests.git is at 1234, <manifest> becomes
        <manifest revision="1234">.
      revisions: If True, then rewrite all branches/tags into a specific
        sha1 revision.  If False, don't.
    Returns:
      The manifest as a string.
    """
    cmd = ['repo', 'manifest', '-o', '-']
    if revisions:
      cmd += ['-r']
    output = cros_build_lib.RunCommandCaptureOutput(
        cmd, cwd=self.directory, print_cmd=False,
        extra_env={'PAGER':'cat'}).output

    if not mark_revision:
      return output
    modified = cros_build_lib.RunGitCommand(
        os.path.join(self.directory, '.repo/manifests'),
        ['rev-list', '-n1', 'HEAD'])
    assert modified.output
    return output.replace("<manifest>", '<manifest revision="%s">' %
                          modified.output.strip())

  def IsManifestDifferent(self, other_manifest):
    """Checks whether this manifest is different than another.

    May blacklists certain repos as part of the diff.

    Args:
      other_manfiest: Second manifest file to compare against.
    Returns:
      True: If the manifests are different
      False: If the manifests are same
    """
    black_list = ['="chromium/']
    logging.debug('Calling DiffManifests against %s', other_manifest)

    current = self.ExportManifest()
    blacklist_pattern = re.compile(r'|'.join(black_list))
    with open(other_manifest, 'r') as manifest2_fh:
      for (line1, line2) in zip(current.splitlines(), manifest2_fh):
        if blacklist_pattern.search(line1):
          logging.debug('%s ignored %s', line1, line2)
          continue

        if line1 != line2:
          logging.debug('Current and other manifest differ.')
          logging.debug('current: %s', line1)
          logging.debug('other  : %s', line2)
          return True
      return False
