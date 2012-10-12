# Copyright (c) 2012 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Module containing the various stages that a builder runs."""

import cPickle
import functools
import glob
import multiprocessing
import os
import Queue
import shutil
import sys
import tempfile

from chromite.buildbot import builderstage as bs
from chromite.buildbot import cbuildbot_background as background
from chromite.buildbot import cbuildbot_commands as commands
from chromite.buildbot import cbuildbot_config
from chromite.buildbot import configure_repo
from chromite.buildbot import cbuildbot_results as results_lib
from chromite.buildbot import constants
from chromite.buildbot import lkgm_manager
from chromite.buildbot import manifest_version
from chromite.buildbot import patch as cros_patch
from chromite.buildbot import portage_utilities
from chromite.buildbot import repository
from chromite.buildbot import validation_pool
from chromite.lib import cros_build_lib
from chromite.lib import osutils

_FULL_BINHOST = 'FULL_BINHOST'
_PORTAGE_BINHOST = 'PORTAGE_BINHOST'
_CROS_ARCHIVE_URL = 'CROS_ARCHIVE_URL'
_PRINT_INTERVAL = 1
BUILDBOT_ARCHIVE_PATH = '/b/archive'


class NonHaltingBuilderStage(bs.BuilderStage):
  """Build stage that fails a build but finishes the other steps."""
  def Run(self):
    try:
      super(NonHaltingBuilderStage, self).Run()
    except results_lib.StepFailure:
      pass


class ForgivingBuilderStage(NonHaltingBuilderStage):
  """Build stage that turns a build step red but not a build."""
  def _HandleStageException(self, exception):
    """Override and don't set status to FAIL but FORGIVEN instead."""
    return self._HandleExceptionAsWarning(exception)


class BoardSpecificBuilderStage(bs.BuilderStage):

  def __init__(self, options, build_config, board, suffix=None):
    super(BoardSpecificBuilderStage, self).__init__(options, build_config,
                                                    suffix)
    self._current_board = board

    if not isinstance(board, basestring):
      raise TypeError('Expected string, got %r' % (board,))

    # Add a board name suffix to differentiate between various boards (in case
    # more than one board is built on a single builder.)
    if len(self._boards) > 1 or build_config['grouped']:
      self.name = '%s [%s]' % (self.name, board)

  def GetImageDirSymlink(self, pointer='latest-cbuildbot'):
    """Get the location of the current image."""
    buildroot, board = self._options.buildroot, self._current_board
    return os.path.join(buildroot, 'src', 'build', 'images', board, pointer)


class CleanUpStage(bs.BuilderStage):
  """Stages that cleans up build artifacts from previous runs.

  This stage cleans up previous KVM state, temporary git commits,
  clobbers, and wipes tmp inside the chroot.
  """

  option_name = 'clean'

  def _CleanChroot(self):
    commands.CleanupChromeKeywordsFile(self._boards,
                                       self._build_root)
    chroot_tmpdir = os.path.join(self._build_root, 'chroot', 'tmp')
    if os.path.exists(chroot_tmpdir):
      cros_build_lib.SudoRunCommand(['rm', '-rf', chroot_tmpdir],
                                    print_cmd=False)
      cros_build_lib.SudoRunCommand(['mkdir', '--mode', '1777', chroot_tmpdir],
                                    print_cmd=False)

  def _DeleteChroot(self):
    chroot = os.path.join(self._build_root, 'chroot')
    if os.path.exists(chroot):
      cros_build_lib.RunCommand(['cros_sdk', '--delete', '--chroot', chroot],
                                self._build_root,
                                cwd=self._build_root)

  def _DeleteArchivedTrybotImages(self):
    """For trybots, clear all previus archive images to save space."""
    archive_root = ArchiveStage.GetTrybotArchiveRoot(self._build_root)
    shutil.rmtree(archive_root, ignore_errors=True)

  def _PerformStage(self):
    if not self._options.buildbot and self._options.clobber:
      if not commands.ValidateClobber(self._build_root):
        sys.exit(0)

    # If we can't get a manifest out of it, then it's not usable and must be
    # clobbered.
    manifest = None
    if not self._options.clobber:
      try:
        manifest = cros_build_lib.ManifestCheckout.Cached(self._build_root,
                                                          search=False)
      except (KeyboardInterrupt, MemoryError, SystemExit):
        raise
      except Exception, e:
        # Either there is no repo there, or the manifest isn't usable.  If the
        # directory exists, log the exception for debugging reasons.  Either
        # way, the checkout needs to be wiped since it's in an unknown
        # state.
        if os.path.exists(self._build_root):
          cros_build_lib.Warning("ManifestCheckout at %s is unusable: %s",
                                 self._build_root, e)

    if manifest is None:
      self._DeleteChroot()
      repository.ClearBuildRoot(self._build_root, self._options.preserve_paths)
    else:
      # Clean mount points first to be safe about deleting.
      commands.CleanUpMountPoints(self._build_root)

      commands.BuildRootGitCleanup(self._build_root, self._options.debug)
      tasks = [functools.partial(commands.BuildRootGitCleanup,
                                 self._build_root, self._options.debug),
               functools.partial(commands.WipeOldOutput, self._build_root),
               self._DeleteArchivedTrybotImages]
      if self._build_config['chroot_replace'] and self._options.build:
        tasks.append(self._DeleteChroot)
      else:
        tasks.append(self._CleanChroot)
      background.RunParallelSteps(tasks)


class PatchChangesStage(bs.BuilderStage):
  """Stage that patches a set of Gerrit changes to the buildroot source tree."""
  def __init__(self, options, build_config, patch_pool):
    """Construct a PatchChangesStage.

    Args:
      options, build_config: See arguments to bs.BuilderStage.__init__()
      gerrit_patches: A list of GerritPatch objects to apply. Cannot be None.
      local_patches: A list of LocalPatch objects to apply.  Cannot be None.
      remote_patches: A list of UploadedLocalPatch objects to apply. Cannot be
                      None.
    """
    bs.BuilderStage.__init__(self, options, build_config)
    self.patch_pool = patch_pool

  def _CheckForDuplicatePatches(self, _series, changes):
    conflicts = {}
    duplicates = []
    for change in changes:
      if change.id is None:
        cros_build_lib.Warning(
            "Change %s lacks a usable ChangeId; duplicate checking cannot "
            "be done for this change.  If cherry-picking fails, this is a "
            "potential cause.", change)
        continue
      conflicts.setdefault(change.id, []).append(change)

    duplicates = [x for x in conflicts.itervalues() if len(x) > 1]
    if not duplicates:
      return changes

    for conflict in duplicates:
      cros_build_lib.Error(
          "Changes %s conflict with each other- they have same id %s."
          ', '.join(map(str, conflict)), conflict[0].id)

    cros_build_lib.Die("Duplicate patches were encountered: %s", duplicates)

  def _FixIncompleteRemotePatches(self, series, changes):
    """Identify missing remote patches from older cbuildbot instances.

    Cbuildbot, prior to I8ab6790de801900c115a437b5f4ebb9a24db542f, uploaded
    a single patch per project- despite if their may have been a hundred
    patches actually pulled in by that patch.  This method detects when
    we're dealing w/ the old incomplete version, and fills in those gaps."""
    broken = [x for x in changes
              if isinstance(x, cros_patch.UploadedLocalPatch)]
    if not broken:
      return changes

    changes = list(changes)
    known = cros_patch.PatchCache(changes)

    for change in broken:
      git_repo = series.GetGitRepoForChange(change)
      tracking = series.GetTrackingBranchForChange(change)
      branch = getattr(change, 'original_branch', tracking)

      for target in cros_patch.GeneratePatchesFromRepo(
          git_repo, change.project, tracking, branch, change.internal,
          allow_empty=True, starting_ref='%s^' % change.sha1):

        if target in known:
          continue

        known.Inject(target)
        changes.append(target)

    return changes

  def _PatchSeriesFilter(self, series, changes):
    if self._options.remote_version == 3:
      changes = self._FixIncompleteRemotePatches(series, changes)
    return self._CheckForDuplicatePatches(series, changes)

  def _ApplyPatchSeries(self, series, **kwargs):
    kwargs.setdefault('frozen', False)
    # Honor the given ordering, so that if a gerrit/remote patch
    # conflicts w/ a local patch, the gerrit/remote patch are
    # blamed rather than local (patch ordering is typically
    # local, gerrit, then remote).
    kwargs.setdefault('honor_ordering', True)
    kwargs['changes_filter'] = self._PatchSeriesFilter

    _applied, failed_tot, failed_inflight = series.Apply(
        list(self.patch_pool), **kwargs)

    failures = failed_tot + failed_inflight
    if failures:
      cros_build_lib.Die("Failed applying patches: %s",
                         "\n".join(map(str, failures)))

  def _PerformStage(self):

    class NoisyPatchSeries(validation_pool.PatchSeries):
      """Custom PatchSeries that adds links to buildbot logs for remote trys."""

      def ApplyChange(self, change, dryrun=False):
        if isinstance(change, cros_patch.GerritPatch):
          cros_build_lib.PrintBuildbotLink(str(change), change.url)
        elif isinstance(change, cros_patch.UploadedLocalPatch):
          cros_build_lib.PrintBuildbotStepText(str(change))

        return validation_pool.PatchSeries.ApplyChange(self, change,
                                                       dryrun=dryrun)

    self._ApplyPatchSeries(
        NoisyPatchSeries(self._build_root,
                         force_content_merging=True))


class BootstrapStage(PatchChangesStage):
  """Stage that patches a chromite repo and re-executes inside it.

  Attributes:
    returncode - the returncode of the cbuildbot re-execution.  Valid after
                 calling stage.Run().
  """
  option_name = 'bootstrap'

  def __init__(self, options, build_config, patch_pool):
    super(BootstrapStage, self).__init__(
        options, build_config, patch_pool)
    self.returncode = None

  #pylint: disable=E1101
  @osutils.TempDirDecorator
  def _PerformStage(self):

    # The plan for the builders is to use master branch to bootstrap other
    # branches. Now, if we wanted to test patches for both the bootstrap code
    # (on master) and the branched chromite (say, R20), we need to filter the
    # patches by branch.
    filter_branch = self._target_manifest_branch
    if self._options.test_bootstrap:
      filter_branch = 'master'

    self.patch_pool = self.patch_pool.Filter(tracking_branch=filter_branch)

    chromite_dir = os.path.join(self.tempdir, 'chromite')
    reference_repo = os.path.join(constants.SOURCE_ROOT, 'chromite', '.git')
    repository.CloneGitRepo(chromite_dir, constants.CHROMITE_URL,
                            reference=reference_repo)
    cros_build_lib.RunGitCommand(chromite_dir, ['checkout', filter_branch])

    class FilteringSeries(validation_pool.RawPatchSeries):
      def _LookupAndFilterChanges(self, *args, **kwargs):
        changes = validation_pool.RawPatchSeries._LookupAndFilterChanges(
            self, *args, **kwargs)
        return [x for x in changes if x.project == constants.CHROMITE_PROJECT
                and x.tracking_branch == filter_branch]

    self._ApplyPatchSeries(FilteringSeries(chromite_dir))

    extra_params = ['--sourceroot=%s' % self._options.sourceroot]
    extra_params.extend(self._options.bootstrap_args)
    argv = sys.argv[1:]
    if '--test-bootstrap' in argv:
      # We don't want re-executed instance to see this.
      argv = [a for a in argv if a != '--test-bootstrap']
    else:
      # If we've already done the desired number of bootstraps, disable
      # bootstrapping for the next execution.
      extra_params.append('--nobootstrap')

    cbuildbot_path = constants.PATH_TO_CBUILDBOT
    if not os.path.exists(os.path.join(self.tempdir, cbuildbot_path)):
      cbuildbot_path = 'chromite/buildbot/cbuildbot'

    cmd = [cbuildbot_path] + argv + extra_params
    result_obj = cros_build_lib.RunCommand(
        cmd, cwd=self.tempdir, kill_timeout=30, error_code_ok=True)
    self.returncode = result_obj.returncode


class SyncStage(bs.BuilderStage):
  """Stage that performs syncing for the builder."""

  option_name = 'sync'
  output_manifest_sha1 = True

  def __init__(self, options, build_config):
    super(SyncStage, self).__init__(options, build_config)
    self.repo = None
    self.skip_sync = False
    self.internal = self._build_config['internal']

  def _GetManifestVersionsRepoUrl(self, read_only=False):
    return cbuildbot_config.GetManifestVersionsRepoUrl(
        self.internal,
        read_only=read_only)

  def Initialize(self):
    self._InitializeRepo()

  def _InitializeRepo(self, git_url=None, build_root=None, **kwds):
    if build_root is None:
      build_root = self._build_root

    if git_url is None:
      git_url = self._build_config['git_url']

    kwds.setdefault('referenced_repo', self._options.reference_repo)
    kwds.setdefault('branch', self._target_manifest_branch)

    self.repo = repository.RepoRepository(git_url, build_root, **kwds)

  def GetNextManifest(self):
    """Returns the manifest to use."""
    return repository.RepoRepository.DEFAULT_MANIFEST

  def ManifestCheckout(self, next_manifest):
    """Checks out the repository to the given manifest."""
    self._Print('\n'.join(['BUILDROOT: %s' % self.repo.directory,
                           'TRACKING BRANCH: %s' % self.repo.branch,
                           'NEXT MANIFEST: %s' % next_manifest]))

    if not self.skip_sync:
      self.repo.Sync(next_manifest)
    print >> sys.stderr, self.repo.ExportManifest(
        mark_revision=self.output_manifest_sha1)

  def _PerformStage(self):
    self.Initialize()
    self.ManifestCheckout(self.GetNextManifest())

  def HandleSkip(self):
    super(SyncStage, self).HandleSkip()
    # Ensure the gerrit remote is present for backwards compatibility.
    # TODO(davidjames): Remove this.
    configure_repo.SetupGerritRemote(self._build_root)


class LKGMSyncStage(SyncStage):
  """Stage that syncs to the last known good manifest blessed by builders."""

  output_manifest_sha1 = False

  def GetNextManifest(self):
    """Override: Gets the LKGM."""
    # TODO(sosa):  Should really use an initialized manager here.
    if self.internal:
      mv_dir = 'manifest-versions-internal'
    else:
      mv_dir = 'manifest-versions'

    manifest_path = os.path.join(self._build_root, mv_dir)
    manifest_repo = self._GetManifestVersionsRepoUrl(read_only=True)
    manifest_version.RefreshManifestCheckout(manifest_path, manifest_repo)
    return os.path.join(manifest_path, lkgm_manager.LKGMManager.LKGM_PATH)


class ManifestVersionedSyncStage(SyncStage):
  """Stage that generates a unique manifest file, and sync's to it."""

  manifest_manager = None
  output_manifest_sha1 = False

  def __init__(self, options, build_config):
    # Perform the sync at the end of the stage to the given manifest.
    super(ManifestVersionedSyncStage, self).__init__(options, build_config)
    self.repo = None

    # If a builder pushes changes (even with dryrun mode), we need a writable
    # repository. Otherwise, the push will be rejected by the server.
    self.manifest_repo = self._GetManifestVersionsRepoUrl(read_only=False)

    # 1. If we're uprevving Chrome, Chrome might have changed even if the
    #    manifest has not, so we should force a build to double check. This
    #    means that we'll create a new manifest, even if there are no changes.
    # 2. If we're running with --debug, we should always run through to
    #    completion, so as to ensure a complete test.
    self._force = self._chrome_rev or options.debug

  def HandleSkip(self):
    """Initializes a manifest manager to the specified version if skipped."""
    super(ManifestVersionedSyncStage, self).HandleSkip()
    if self._options.force_version:
      self.Initialize()
      self.ForceVersion(self._options.force_version)

  def ForceVersion(self, version):
    """Creates a manifest manager from given version and returns manifest."""
    return ManifestVersionedSyncStage.manifest_manager.BootstrapFromVersion(
        version)

  def Initialize(self):
    """Initializes a manager that manages manifests for associated stages."""
    increment = ('build' if self._target_manifest_branch == 'master'
                 else 'branch')

    dry_run = self._options.debug

    self._InitializeRepo()

    # If chrome_rev is somehow set, fail.
    assert not self._chrome_rev, \
        'chrome_rev is unsupported on release builders.'

    ManifestVersionedSyncStage.manifest_manager = \
        manifest_version.BuildSpecsManager(
            source_repo=self.repo,
            manifest_repo=self.manifest_repo,
            build_name=self._bot_id,
            incr_type=increment,
            force=self._force,
            dry_run=dry_run)

  def GetNextManifest(self):
    """Uses the initialized manifest manager to get the next manifest."""
    assert self.manifest_manager, \
        'Must run GetStageManager before checkout out build.'

    to_return = self.manifest_manager.GetNextBuildSpec()
    previous_version = self.manifest_manager.latest_passed
    target_version = self.manifest_manager.current_version

    # Print the Blamelist here.
    url_prefix = 'http://chromeos-images.corp.google.com/diff/report?'
    url = url_prefix + 'from=%s&to=%s' % (previous_version, target_version)
    cros_build_lib.PrintBuildbotLink('Blamelist', url)

    return to_return

  def _PerformStage(self):
    self.Initialize()
    if self._options.force_version:
      next_manifest = self.ForceVersion(self._options.force_version)
    else:
      next_manifest = self.GetNextManifest()

    if not next_manifest:
      cros_build_lib.Info('Found no work to do.')
      if ManifestVersionedSyncStage.manifest_manager.DidLastBuildSucceed():
        sys.exit(0)
      else:
        cros_build_lib.Die('Last build status was non-passing.')

    # Log this early on for the release team to grep out before we finish.
    if ManifestVersionedSyncStage.manifest_manager:
      self._Print('\nRELEASETAG: %s\n' % (
          ManifestVersionedSyncStage.manifest_manager.current_version))

    self.ManifestCheckout(next_manifest)


class LKGMCandidateSyncStage(ManifestVersionedSyncStage):
  """Stage that generates a unique manifest file candidate, and sync's to it."""

  sub_manager = None

  def __init__(self, options, build_config):
    super(LKGMCandidateSyncStage, self).__init__(options, build_config)
    # lkgm_manager deals with making sure we're synced to whatever manifest
    # we get back in GetNextManifest so syncing again is redundant.
    self.skip_sync = True

  def _GetInitializedManager(self, internal):
    """Returns an initialized lkgm manager."""
    increment = ('build' if self._target_manifest_branch == 'master'
                 else 'branch')
    return lkgm_manager.LKGMManager(
        source_repo=self.repo,
        manifest_repo=cbuildbot_config.GetManifestVersionsRepoUrl(
            internal, read_only=False),
        build_name=self._bot_id,
        build_type=self._build_config['build_type'],
        incr_type=increment,
        force=self._force,
        dry_run=self._options.debug)

  def Initialize(self):
    """Override: Creates an LKGMManager rather than a ManifestManager."""
    self._InitializeRepo()
    ManifestVersionedSyncStage.manifest_manager = self._GetInitializedManager(
        self.internal)
    if (self._build_config['unified_manifest_version'] and
        self._build_config['master']):
      assert self.internal, 'Unified masters must use an internal checkout.'
      LKGMCandidateSyncStage.sub_manager = self._GetInitializedManager(False)

  def ForceVersion(self, version):
    manifest = super(LKGMCandidateSyncStage, self).ForceVersion(version)
    if LKGMCandidateSyncStage.sub_manager:
      LKGMCandidateSyncStage.sub_manager.BootstrapFromVersion(version)

    return manifest

  def GetNextManifest(self):
    """Gets the next manifest using LKGM logic."""
    assert self.manifest_manager, \
        'Must run Initialize before we can get a manifest.'
    assert isinstance(self.manifest_manager, lkgm_manager.LKGMManager), \
        'Manifest manager instantiated with wrong class.'

    if self._build_config['master']:
      manifest = self.manifest_manager.CreateNewCandidate()
      if LKGMCandidateSyncStage.sub_manager:
        LKGMCandidateSyncStage.sub_manager.CreateFromManifest(manifest)

      return manifest

    else:
      return self.manifest_manager.GetLatestCandidate()


class CommitQueueSyncStage(LKGMCandidateSyncStage):
  """Commit Queue Sync stage that handles syncing and applying patches.

  This stage handles syncing to a manifest, passing around that manifest to
  other builders and finding the Gerrit Reviews ready to be committed and
  applying them into its out checkout.
  """

  # Path relative to the buildroot of where to store the pickled validation
  # pool.
  PICKLED_POOL_FILE = 'validation_pool.dump'

  pool = None

  def __init__(self, options, build_config):
    super(CommitQueueSyncStage, self).__init__(options, build_config)
    CommitQueueSyncStage.pool = None
    # Figure out the builder's name from the buildbot waterfall.
    builder_name = build_config['paladin_builder_name']
    self.builder_name = builder_name if builder_name else build_config['name']

  def SaveValidationPool(self):
    """Serializes the validation pool.

    Returns: returns a path to the serialized form of the validation pool.
    """
    path_to_file = os.path.join(self._build_root, self.PICKLED_POOL_FILE)
    with open(path_to_file, 'wb') as p_file:
      cPickle.dump(self.pool, p_file, protocol=cPickle.HIGHEST_PROTOCOL)

    return path_to_file

  def LoadValidationPool(self, path_to_file):
    """Loads the validation pool from the file."""
    with open(path_to_file, 'rb') as p_file:
      CommitQueueSyncStage.pool = cPickle.load(p_file)

  def HandleSkip(self):
    """Handles skip and initializes validation pool from manifest."""
    super(CommitQueueSyncStage, self).HandleSkip()
    if self._options.validation_pool:
      self.LoadValidationPool(self._options.validation_pool)
    else:
      self.SetPoolFromManifest(self.manifest_manager.GetLocalManifest())

  def SetPoolFromManifest(self, manifest):
    """Sets validation pool based on manifest path passed in."""
    CommitQueueSyncStage.pool = \
        validation_pool.ValidationPool.AcquirePoolFromManifest(
            manifest, self._build_config['overlays'],
            self._build_root, self._options.buildnumber, self.builder_name,
            self._build_config['master'], self._options.debug)

  def GetNextManifest(self):
    """Gets the next manifest using LKGM logic."""
    assert self.manifest_manager, \
        'Must run Initialize before we can get a manifest.'
    assert isinstance(self.manifest_manager, lkgm_manager.LKGMManager), \
        'Manifest manager instantiated with wrong class.'

    if self._build_config['master']:
      try:
        # In order to acquire a pool, we need an initialized buildroot.
        if not repository.InARepoRepository(self.repo.directory):
          self.repo.Initialize()

        pool = validation_pool.ValidationPool.AcquirePool(
            self._build_config['overlays'], self._build_root,
            self._options.buildnumber, self.builder_name,
            self._options.debug,
            changes_query=self._options.cq_gerrit_override)

        # We only have work to do if there are changes to try.
        try:
          # Try our best to submit these but may have been overridden and won't
          # let that stop us from continuing the build.
          pool.SubmitNonManifestChanges()
        except validation_pool.FailedToSubmitAllChangesException as e:
          cros_build_lib.Warning(str(e))

        CommitQueueSyncStage.pool = pool

      except validation_pool.TreeIsClosedException as e:
        cros_build_lib.Warning(str(e))
        return None

      manifest = self.manifest_manager.CreateNewCandidate(validation_pool=pool)
      if LKGMCandidateSyncStage.sub_manager:
        LKGMCandidateSyncStage.sub_manager.CreateFromManifest(manifest)

      return manifest
    else:
      manifest = self.manifest_manager.GetLatestCandidate()
      if manifest:
        self.SetPoolFromManifest(manifest)
        self.pool.ApplyPoolIntoRepo()

      return manifest

  # Accessing a protected member.  TODO(sosa): Refactor PerformStage to not be
  # a protected member as children override it.
  # pylint: disable=W0212
  def _PerformStage(self):
    """Performs normal stage and prints blamelist at end."""
    if self._options.force_version:
      self.HandleSkip()
    else:
      ManifestVersionedSyncStage._PerformStage(self)


class ManifestVersionedSyncCompletionStage(ForgivingBuilderStage):
  """Stage that records board specific results for a unique manifest file."""

  option_name = 'sync'

  def __init__(self, options, build_config, success):
    super(ManifestVersionedSyncCompletionStage, self).__init__(
        options, build_config)
    self.success = success
    # Message that can be set that well be sent along with the status in
    # UpdateStatus.
    self.message = None

  def _PerformStage(self):
    if ManifestVersionedSyncStage.manifest_manager:
      ManifestVersionedSyncStage.manifest_manager.UpdateStatus(
         success=self.success, message=self.message)


class ImportantBuilderFailedException(Exception):
  """Exception thrown when an important build fails to build."""
  pass


class LKGMCandidateSyncCompletionStage(ManifestVersionedSyncCompletionStage):
  """Stage that records whether we passed or failed to build/test manifest."""

  def _GetSlavesStatus(self):
    # If debugging or a slave, just check its local status.
    if not self._build_config['master'] or self._options.debug:
      return ManifestVersionedSyncStage.manifest_manager.GetBuildersStatus(
        [self._bot_id], os.path.join(self._build_root, constants.VERSION_FILE))

    if not LKGMCandidateSyncStage.sub_manager:
      return ManifestVersionedSyncStage.manifest_manager.GetBuildersStatus(
          self._GetSlavesForMaster(), os.path.join(self._build_root,
                                                   constants.VERSION_FILE))
    else:
      public_builders, private_builders = self._GetSlavesForUnifiedMaster()
      statuses = {}
      if public_builders:
        statuses.update(
          LKGMCandidateSyncStage.sub_manager.GetBuildersStatus(
              public_builders, os.path.join(self._build_root,
                                            constants.VERSION_FILE)))
      if private_builders:
        statuses.update(
            ManifestVersionedSyncStage.manifest_manager.GetBuildersStatus(
                private_builders, os.path.join(self._build_root,
                                          constants.VERSION_FILE)))
      return statuses

  def HandleSuccess(self):
    # We only promote for the pfq, not chrome pfq.
    # TODO(build): Run this logic in debug mode too.
    if (not self._options.debug and
        cbuildbot_config.IsPFQType(self._build_config['build_type']) and
        self._build_config['master'] and
        self._target_manifest_branch == 'master' and
        ManifestVersionedSyncStage.manifest_manager != None and
        self._build_config['build_type'] != constants.CHROME_PFQ_TYPE):
      ManifestVersionedSyncStage.manifest_manager.PromoteCandidate()
      if LKGMCandidateSyncStage.sub_manager:
        LKGMCandidateSyncStage.sub_manager.PromoteCandidate()

  def HandleValidationFailure(self, failing_statuses):
    cros_build_lib.PrintBuildbotStepWarnings()
    cros_build_lib.Warning('\n'.join([
        'The following builders failed with this manifest:',
        ', '.join(sorted(failing_statuses.keys())),
        'Please check the logs of the failing builders for details.']))

  def HandleValidationTimeout(self, inflight_statuses):
    cros_build_lib.PrintBuildbotStepWarnings()
    cros_build_lib.Warning('\n'.join([
        'The following builders took too long to finish:',
        ', '.join(sorted(inflight_statuses.keys())),
        'Please check the logs of these builders for details.']))

  def _PerformStage(self):
    super(LKGMCandidateSyncCompletionStage, self)._PerformStage()

    if ManifestVersionedSyncStage.manifest_manager:
      statuses = self._GetSlavesStatus()
      failing_build_dict, inflight_build_dict = {}, {}
      for builder, status in statuses.iteritems():
        if status.Failed():
          failing_build_dict[builder] = status
        elif status.Inflight():
          inflight_build_dict[builder] = status

      if failing_build_dict or inflight_build_dict:
        if failing_build_dict:
          self.HandleValidationFailure(failing_build_dict)

        if inflight_build_dict:
          self.HandleValidationTimeout(inflight_build_dict)

      if failing_build_dict or inflight_build_dict:
        raise results_lib.StepFailure()
      else:
        self.HandleSuccess()


class CommitQueueCompletionStage(LKGMCandidateSyncCompletionStage):
  """Commits or reports errors to CL's that failed to be validated."""
  def HandleSuccess(self):
    if self._build_config['master']:
      CommitQueueSyncStage.pool.SubmitPool()
      # After submitting the pool, update the commit hashes for uprevved
      # ebuilds.
      portage_utilities.EBuild.UpdateCommitHashesForChanges(
          CommitQueueSyncStage.pool.changes, self._build_root)
      if cbuildbot_config.IsPFQType(self._build_config['build_type']):
        super(CommitQueueCompletionStage, self).HandleSuccess()

  def HandleValidationFailure(self, failing_statuses):
    """Sends the failure message of all failing builds in one go."""
    super(CommitQueueCompletionStage, self).HandleValidationFailure(
        failing_statuses)

    if self._build_config['master']:
      failing_messages = [x.message for x in failing_statuses.itervalues()]
      CommitQueueSyncStage.pool.HandleValidationFailure(failing_messages)

  def HandleValidationTimeout(self, inflight_builders):
    super(CommitQueueCompletionStage, self).HandleValidationTimeout(
        inflight_builders)
    CommitQueueSyncStage.pool.HandleValidationTimeout()

  def _PerformStage(self):
    if not self.success and self._build_config['important']:
      # This message is sent along with the failed status to the master to
      # indicate a failure.
      self.message = CommitQueueSyncStage.pool.GetValidationFailedMessage()

    super(CommitQueueCompletionStage, self)._PerformStage()


class RefreshPackageStatusStage(bs.BuilderStage):
  """Stage for refreshing Portage package status in online spreadsheet."""
  def _PerformStage(self):
    commands.RefreshPackageStatus(buildroot=self._build_root,
                                  boards=self._boards,
                                  debug=self._options.debug)


class BuildBoardStage(bs.BuilderStage):
  """Stage that is responsible for building host pkgs and setting up a board."""

  option_name = 'build'

  def _PerformStage(self):
    chroot_upgrade = True

    chroot_path = os.path.join(self._build_root, 'chroot')
    if not os.path.isdir(chroot_path) or self._build_config['chroot_replace']:
      env = {}
      if self._options.clobber:
        env['IGNORE_PREFLIGHT_BINHOST'] = '1'

      commands.MakeChroot(
          buildroot=self._build_root,
          replace=self._build_config['chroot_replace'],
          use_sdk=self._build_config['use_sdk'],
          chrome_root=self._options.chrome_root,
          extra_env=env)
      chroot_upgrade = False
    else:
      commands.RunChrootUpgradeHooks(self._build_root)

    # Iterate through boards to setup.
    for board_to_build in self._boards:
      # Only build the board if the directory does not exist.
      board_path = os.path.join(chroot_path, 'build', board_to_build)
      if os.path.isdir(board_path):
        continue

      env = {}

      if self._options.clobber:
        env['IGNORE_PREFLIGHT_BINHOST'] = '1'

      latest_toolchain = self._build_config['latest_toolchain']
      if latest_toolchain and self._build_config['gcc_githash']:
        env['USE'] = 'git_gcc'
        env['GCC_GITHASH'] = self._build_config['gcc_githash']

      commands.SetupBoard(self._build_root,
                          board=board_to_build,
                          usepkg=self._build_config['usepkg_setup_board'],
                          latest_toolchain=latest_toolchain,
                          extra_env=env,
                          profile=self._options.profile or
                            self._build_config['profile'],
                          chroot_upgrade=chroot_upgrade)

      chroot_upgrade = False


class UprevStage(bs.BuilderStage):
  """Stage that uprevs Chromium OS packages that the builder intends to
  validate.
  """

  option_name = 'uprev'

  def _PerformStage(self):
    # Perform chrome uprev.
    chrome_atom_to_build = None
    if self._chrome_rev:
      chrome_atom_to_build = commands.MarkChromeAsStable(
          self._build_root, self._target_manifest_branch,
          self._chrome_rev, self._boards,
          chrome_root=self._options.chrome_root,
          chrome_version=self._options.chrome_version)

    # Perform other uprevs.
    if self._build_config['uprev']:
      overlays, _ = self._ExtractOverlays()
      commands.UprevPackages(self._build_root,
                             self._boards,
                             overlays)
    elif self._chrome_rev and not chrome_atom_to_build:
      # TODO(sosa): Do this in a better way.
      sys.exit(0)


class BuildTargetStage(BoardSpecificBuilderStage):
  """This stage builds Chromium OS for a target.

  Specifically, we build Chromium OS packages and perform imaging to get
  the images we want per the build spec."""

  option_name = 'build'

  def __init__(self, options, build_config, board, archive_stage, version):
    super(BuildTargetStage, self).__init__(options, build_config, board)
    self._env = {}
    if self._build_config.get('useflags'):
      self._env['USE'] = ' '.join(self._build_config['useflags'])

    if self._options.chrome_root:
      self._env['CHROME_ORIGIN'] = 'LOCAL_SOURCE'
    elif self._options.gerrit_chrome:
      self._env['CHROME_ORIGIN'] = 'GERRIT_SOURCE'

    if self._options.clobber:
      self._env['IGNORE_PREFLIGHT_BINHOST'] = '1'

    self._archive_stage = archive_stage
    self._tarball_dir = None
    self._version = version if version else ''

  def _CommunicateVersion(self):
    """Communicates to archive_stage the image path of this stage."""
    verinfo = manifest_version.VersionInfo.from_repo(self._build_root)
    if self._version:
      version = self._version
    else:
      version = verinfo.VersionString()

    version = 'R%s-%s' % (verinfo.chrome_branch, version)

    # Non-versioned builds need the build number to uniquify the image.
    if not self._version:
      version += '-b%s' % self._options.buildnumber

    self._archive_stage.SetVersion(version)

  def HandleSkip(self):
    self._CommunicateVersion()

  def _BuildImages(self):
    # We only build base, dev, and test images from this stage.
    images_can_build = set(['base', 'dev', 'test'])
    images_to_build = set(self._build_config['images']).intersection(
        images_can_build)
    root_boost = None
    if (self._build_config['useflags'] and
        'pgo_generate' in self._build_config['useflags']):
      root_boost = 400

    commands.BuildImage(self._build_root,
                        self._current_board,
                        list(images_to_build),
                        version=self._version,
                        root_boost=root_boost,
                        extra_env=self._env)

    if self._build_config['vm_tests']:
      commands.BuildVMImageForTesting(self._build_root,
                                      self._current_board,
                                      extra_env=self._env)

    # Update link to latest image.
    latest_image = os.readlink(self.GetImageDirSymlink('latest'))
    cbuildbot_image_link = self.GetImageDirSymlink()
    if os.path.lexists(cbuildbot_image_link):
      os.remove(cbuildbot_image_link)

    os.symlink(latest_image, cbuildbot_image_link)
    self._CommunicateVersion()

  def _BuildAutotestTarballs(self):
    # Build autotest tarball, which is used in archive step. This is generated
    # here because the test directory is modified during the test phase, and we
    # don't want to include the modifications in the tarball.
    tarballs = commands.BuildAutotestTarballs(self._build_root,
                                              self._current_board,
                                              self._tarball_dir)
    self._archive_stage.AutotestTarballsReady(tarballs)

  def _BuildFullAutotestTarball(self):
    # Build a full autotest tarball for hwqual image. This tarball is to be
    # archived locally.
    tarball = commands.BuildFullAutotestTarball(self._build_root,
                                                self._current_board,
                                                self._tarball_dir)
    self._archive_stage.FullAutotestTarballReady(tarball)

  def _PerformStage(self):
    build_autotest = (self._build_config['build_tests'] and
                      self._options.tests)

    # If we are using ToT toolchain, don't attempt to update
    # the toolchain during build_packages.
    skip_toolchain_update = self._build_config['latest_toolchain']

    commands.Build(self._build_root,
                   self._current_board,
                   build_autotest=build_autotest,
                   skip_toolchain_update=skip_toolchain_update,
                   usepkg=self._build_config['usepkg_build_packages'],
                   nowithdebug=self._build_config['nowithdebug'],
                   extra_env=self._env)

    # Build images and autotest tarball in parallel.
    steps = []
    if build_autotest and (self._build_config['upload_hw_test_artifacts'] or
                           self._build_config['archive_build_debug']):
      self._tarball_dir = tempfile.mkdtemp(prefix='autotest')
      steps.append(self._BuildAutotestTarballs)
      # Build a full autotest tarball only for chromeos_offical builds
      if self._build_config['chromeos_official']:
        steps.append(self._BuildFullAutotestTarball)
    else:
      self._archive_stage.AutotestTarballsReady(None)

    steps.append(self._BuildImages)
    background.RunParallelSteps(steps)

    # TODO(yjhong): Remove this and instruct archive_hwqual to copy the tarball
    # directly.
    if self._tarball_dir and self._build_config['chromeos_official']:
      shutil.copyfile(os.path.join(self._tarball_dir, 'autotest.tar.bz2'),
                      os.path.join(self.GetImageDirSymlink(),
                                   'autotest.tar.bz2'))

  def _HandleStageException(self, exception):
    # In case of an exception, this prevents any consumer from starving.
    self._archive_stage.AutotestTarballsReady(None)
    return super(BuildTargetStage, self)._HandleStageException(exception)


class ChromeTestStage(BoardSpecificBuilderStage):
  """Run chrome tests in a virtual machine."""

  option_name = 'tests'
  config_name = 'chrome_tests'

  # If the chrome tests take longer than an hour to run, abort. They
  # usually take about 30 minutes to run.
  CHROME_TEST_TIMEOUT = 3600

  def __init__(self, options, build_config, board, archive_stage):
    super(ChromeTestStage, self).__init__(options, build_config, board)
    self._archive_stage = archive_stage

  def _PerformStage(self):
    try:
      test_results_dir = None
      test_results_dir = commands.CreateTestRoot(self._build_root)
      with cros_build_lib.SubCommandTimeout(self.CHROME_TEST_TIMEOUT):
        commands.RunChromeSuite(self._build_root,
                                self._current_board,
                                self.GetImageDirSymlink(),
                                os.path.join(test_results_dir,
                                             'chrome_results'))
    except cros_build_lib.TimeoutError as exception:
      return self._HandleExceptionAsWarning(exception)
    finally:
      test_tarball = None
      if test_results_dir:
        test_tarball = commands.ArchiveTestResults(self._build_root,
                                                   test_results_dir,
                                                   prefix='chrome_')

      self._archive_stage.TestResultsReady(test_tarball)

  def HandleSkip(self):
    self._archive_stage.TestResultsReady(None)


class UnitTestStage(BoardSpecificBuilderStage):
  """Run unit tests."""

  option_name = 'tests'
  config_name = 'unittests'

  # If the unit tests take longer than 30 minutes, abort. They usually take
  # five minutes to run.
  UNIT_TEST_TIMEOUT = 1800

  def _PerformStage(self):
    with cros_build_lib.SubCommandTimeout(self.UNIT_TEST_TIMEOUT):
      commands.RunUnitTests(self._build_root,
                            self._current_board,
                            full=(not self._build_config['quick_unit']),
                            nowithdebug=self._build_config['nowithdebug'])


class VMTestStage(BoardSpecificBuilderStage):
  """Run autotests in a virtual machine."""

  option_name = 'tests'
  config_name = 'vm_tests'

  def __init__(self, options, build_config, board, archive_stage):
    super(VMTestStage, self).__init__(options, build_config, board)
    self._archive_stage = archive_stage

  def _PerformStage(self):
    try:
      # These directories are used later to archive test artifacts.
      test_results_dir = None
      test_results_dir = commands.CreateTestRoot(self._build_root)

      commands.RunTestSuite(self._build_root,
                            self._current_board,
                            self.GetImageDirSymlink(),
                            os.path.join(test_results_dir,
                                         'test_harness'),
                            test_type=self._build_config['vm_tests'],
                            whitelist_chrome_crashes=self._chrome_rev is None,
                            build_config=self._bot_id)

    finally:
      test_tarball = None
      if test_results_dir:
        test_tarball = commands.ArchiveTestResults(self._build_root,
                                                   test_results_dir,
                                                   prefix='')

      self._archive_stage.TestResultsReady(test_tarball)

  def HandleSkip(self):
    self._archive_stage.TestResultsReady(None)


class HWTestStage(BoardSpecificBuilderStage, NonHaltingBuilderStage):
  """Stage that runs tests in the Autotest lab."""

  # If the tests take longer than 2h20m, abort.
  INFRASTRUCTURE_TIMEOUT = 8400
  option_name = 'tests'
  config_name = 'hw_tests'

  def __init__(self, options, build_config, board, archive_stage, suite):
    super(HWTestStage, self).__init__(options, build_config, board,
                                      suffix=' [%s]' % suite)
    self._archive_stage = archive_stage
    self._suite = suite

  # Disable use of calling parents HandleStageException class.
  # pylint: disable=W0212
  def _HandleStageException(self, exception):
    """Override and don't set status to FAIL but FORGIVEN instead."""
    if (isinstance(exception, cros_build_lib.RunCommandError) and
        exception.result.returncode == 2 and
        not self._build_config['hw_tests_critical']):
      return self._HandleExceptionAsWarning(exception)
    else:
      return super(HWTestStage, self)._HandleStageException(exception)

  def _PerformStage(self):
    if not self._archive_stage.WaitForHWTestUploads():
      raise Exception('Missing uploads.')

    if self._options.remote_trybot and self._options.hwtest:
      build = 'trybot-%s/%s' % (self._bot_id,
                                   self._archive_stage.GetVersion())
      debug = self._options.debug_forced
    else:
      build = '%s/%s' % (self._bot_id, self._archive_stage.GetVersion())
      debug = self._options.debug
    try:
      with cros_build_lib.SubCommandTimeout(self.INFRASTRUCTURE_TIMEOUT):
        commands.RunHWTestSuite(build, self._suite, self._current_board,
                                self._build_config['hw_tests_pool'], debug)

    except cros_build_lib.TimeoutError as exception:
      if not self._build_config['hw_tests_critical']:
        return self._HandleExceptionAsWarning(exception)
      else:
        return super(HWTestStage, self)._HandleStageException(exception)


class ASyncHWTestStage(HWTestStage, BoardSpecificBuilderStage,
                       ForgivingBuilderStage):
  """Stage that fires and forgets hw test suites to the Autotest lab."""
  # TODO(sosa):  Major hack alert!!! This is intended to be used to verify
  # test suites work and monitor them on the lab side without adversly affecting
  # a build. Ideally we'd use a fire-and-forget script but none currently
  # exists.
  INFRASTRUCTURE_TIMEOUT = 60

  # Disable use of calling parents _HandleExceptionAsWarning class.
  # pylint: disable=W0212
  def _HandleExceptionAsWarning(self, exception):
    """Override and treat timeout's as success."""
    return self._HandleExceptionAsSuccess(exception)


class PaladinHWTestStage(HWTestStage):
  """Stage that runs tests in the Autotest lab for paladin builders.

  This step differs from the HW Test stage as it has a lower threshold for
  timeouts and does not block changes from being committed.
  """
  # Timeout after 30 minutes if the infrastructure hasn't completed running the
  # tests. We'd rather abort after 30 minutes.
  INFRASTRUCTURE_TIMEOUT = 30 * 60


class SDKTestStage(bs.BuilderStage):
  """Stage that performs testing an SDK created in a previous stage"""
  def _PerformStage(self):
    tarball_location = os.path.join(self._build_root, 'built-sdk.tbz2')
    board_location = os.path.join(self._build_root, 'chroot/build/amd64-host')

    # Create a tarball of the latest SDK.
    cmd = ['tar', '-jcf', tarball_location]
    excluded_paths = ('usr/lib/debug', 'usr/local/autotest', 'packages',
                      'tmp')
    for path in excluded_paths:
      cmd.append('--exclude=%s/*' % path)
    cmd.append('.')
    cros_build_lib.SudoRunCommand(cmd, cwd=board_location)

    # Make sure the regular user has the permission to read.
    cmd = ['chmod', 'a+r', tarball_location]
    cros_build_lib.SudoRunCommand(cmd, cwd=board_location)

    new_chroot_cmd = ['cros_sdk', '--chroot', 'new-sdk-chroot']
    # Build a new SDK using the tarball.
    cmd = new_chroot_cmd + ['--download', '--replace', '--nousepkg',
        '--url', 'file://' + tarball_location]
    cros_build_lib.RunCommand(cmd, cwd=self._build_root)

    for board in cbuildbot_config.SDK_TEST_BOARDS:
      cmd = new_chroot_cmd + ['--', './setup_board',
          '--board', board, '--skip_chroot_upgrade']
      cros_build_lib.RunCommand(cmd, cwd=self._build_root)
      cmd = new_chroot_cmd + ['--', './build_packages',
          '--board', board, '--nousepkg', '--skip_chroot_upgrade']
      cros_build_lib.RunCommand(cmd, cwd=self._build_root)


class NothingToArchiveException(Exception):
  """Thrown if ArchiveStage found nothing to archive."""
  def __init__(self, message='No images found to archive.'):
    super(NothingToArchiveException, self).__init__(message)


class ArchiveStage(BoardSpecificBuilderStage):
  """Archives build and test artifacts for developer consumption."""

  option_name = 'archive'
  _VERSION_NOT_SET = '_not_set_version_'
  _REMOTE_TRYBOT_ARCHIVE_URL = 'gs://chromeos-image-archive'

  @classmethod
  def GetTrybotArchiveRoot(cls, buildroot):
    """Return the location where trybot archive images are kept."""
    return os.path.join(buildroot, 'trybot_archive')

  # This stage is intended to run in the background, in parallel with tests.
  def __init__(self, options, build_config, board):
    super(ArchiveStage, self).__init__(options, build_config, board)
    # Set version is dependent on setting external to class.  Do not use
    # directly.  Use GetVersion() instead.
    self._set_version = ArchiveStage._VERSION_NOT_SET
    if self._options.buildbot and not self._options.debug:
      self._archive_root = BUILDBOT_ARCHIVE_PATH
    else:
      self._archive_root = self.GetTrybotArchiveRoot(self._build_root)

    self._bot_archive_root = os.path.join(self._archive_root, self._bot_id)

    # Queues that are populated during the Archive stage.
    self._breakpad_symbols_queue = multiprocessing.Queue()
    self._hw_test_uploads_status_queue = multiprocessing.Queue()

    # Queues that are populated by other stages.
    self._version_queue = multiprocessing.Queue()
    self._autotest_tarballs_queue = multiprocessing.Queue()
    self._full_autotest_tarball_queue = multiprocessing.Queue()
    self._test_results_queue = multiprocessing.Queue()

  def SetVersion(self, path_to_image):
    """Sets the cros version for the given built path to an image.

    This must be called in order for archive stage to finish.

    Args:
      path_to_image: Path to latest image.""
    """
    self._version_queue.put(path_to_image)

  def AutotestTarballsReady(self, autotest_tarballs):
    """Tell Archive Stage that autotest tarball is ready.

    This must be called in order for archive stage to finish.

    Args:
      autotest_tarballs: The paths of the autotest tarballs.
    """
    self._autotest_tarballs_queue.put(autotest_tarballs)

  def FullAutotestTarballReady(self, full_autotest_tarball):
    """Tell Archive Stage that full autotest tarball is ready.

    This must be called in order for archive stage to finish when
    chromeos_offcial is true.

    Args:
      full_autotest_tarball: The paths of the full autotest tarball.
    """
    self._full_autotest_tarball_queue.put(full_autotest_tarball)


  def TestResultsReady(self, test_results):
    """Tell Archive Stage that test results are ready.

    This must be called twice (with VM test results and Chrome test results)
    in order for archive stage to finish.

    Args:
      test_results: The test results tarball from the tests. If no tests
                    results are available, this should be set to None.
    """
    self._test_results_queue.put(test_results)

  def GetVersion(self):
    """Gets the version for the archive stage."""
    if self._set_version == ArchiveStage._VERSION_NOT_SET:
      version = self._version_queue.get()
      self._set_version = version
      # Put the version right back on the queue in case anyone else is waiting.
      self._version_queue.put(version)

    return self._set_version

  def WaitForHWTestUploads(self):
    """Waits until artifacts needed for HWTest stage are uploaded.

    Returns:
      True if artifacts uploaded successfully.
      False otherswise.
    """
    cros_build_lib.Info('Waiting for uploads...')
    status = self._hw_test_uploads_status_queue.get()
    # Put the status back so other HWTestStage instances don't starve.
    self._hw_test_uploads_status_queue.put(status)
    return status

  def _BreakpadSymbolsGenerated(self, success):
    """Signal that breakpad symbols have been generated.

    Arguments:
      success: True to indicate the symbols were generated, else False.
    """
    self._breakpad_symbols_queue.put(success)

  def _WaitForBreakpadSymbols(self):
    """Wait for the breakpad symbols to be generated.

    Returns:
      True if the breakpad symbols were generated.
      False if the breakpad symbols were not generated within 20 mins.
    """
    success = False
    try:
      # TODO: Clean this up so that we no longer rely on a timeout
      success = self._breakpad_symbols_queue.get(True, 1200)
    except Queue.Empty:
      cros_build_lib.Warning(
          'Breakpad symbols were not generated within timeout period.')
    return success

  def GetDownloadUrl(self):
    """Get the URL where we can download artifacts."""
    version = self.GetVersion()
    if not version:
      return None

    if self._options.buildbot or self._options.remote_trybot:
      upload_location = self.GetGSUploadLocation()
      url_prefix = 'https://sandbox.google.com/storage/'
      return upload_location.replace('gs://', url_prefix)
    else:
      return self._GetArchivePath()

  def _GetGSUtilArchiveDir(self):
    bot_id = self._bot_id
    if self._options.archive_base:
      gs_base = self._options.archive_base
    elif self._options.remote_trybot:
      gs_base = self._REMOTE_TRYBOT_ARCHIVE_URL
      bot_id = 'trybot-' + self._bot_id
    elif self._build_config['gs_path'] == cbuildbot_config.GS_PATH_DEFAULT:
      gs_base = 'gs://chromeos-image-archive'
    else:
      return self._build_config['gs_path']

    return '%s/%s' % (gs_base, bot_id)

  def GetGSUploadLocation(self):
    """Get the Google Storage location where we should upload artifacts."""
    gsutil_archive = self._GetGSUtilArchiveDir()
    version = self.GetVersion()
    if version:
      return '%s/%s' % (gsutil_archive, version)

  def _GetArchivePath(self):
    version = self.GetVersion()
    if version:
      return os.path.join(self._bot_archive_root, version)

  def _GetAutotestTarballs(self):
    """Get the paths of the autotest tarballs."""
    autotest_tarballs = None
    if self._options.build:
      cros_build_lib.Info('Waiting for autotest tarballs ...')
      autotest_tarballs = self._autotest_tarballs_queue.get()
      if autotest_tarballs:
        cros_build_lib.Info('Found autotest tarballs %r ...'
                            % autotest_tarballs)
      else:
        cros_build_lib.Info('No autotest tarballs found.')

    return autotest_tarballs

  def _GetFullAutotestTarball(self):
    """Get the paths of the full autotest tarball."""
    full_autotest_tarball = None
    if self._options.build:
      cros_build_lib.Info('Waiting for the full autotest tarball ...')
      full_autotest_tarball = self._full_autotest_tarball_queue.get()
      if full_autotest_tarball:
        cros_build_lib.Info('Found full autotest tarball %s ...'
                            % full_autotest_tarball)
      else:
        cros_build_lib.Info('No full autotest tarball found.')

    return full_autotest_tarball

  def _GetTestResults(self):
    """Get the path to the test results tarball."""
    for _ in range(2):
      cros_build_lib.Info('Waiting for test results dir...')
      test_tarball = self._test_results_queue.get()
      if test_tarball:
        cros_build_lib.Info('Found test results tarball at %s...'
                            % test_tarball)
        yield test_tarball
      else:
        cros_build_lib.Info('No test results.')

  def _SetupArchivePath(self):
    """Create a fresh directory for archiving a build."""
    archive_path = self._GetArchivePath()
    if not archive_path:
      return None

    if self._options.buildbot:
      # Buildbot: Clear out any leftover build artifacts, if present.
      shutil.rmtree(archive_path, ignore_errors=True)

    os.makedirs(archive_path)

    return archive_path

  def _PerformStage(self):
    if self._options.remote_trybot:
      debug = self._options.debug_forced
    else:
      debug = self._options.debug

    buildroot = self._build_root
    config = self._build_config
    board = self._current_board
    upload_url = self.GetGSUploadLocation()
    archive_path = self._SetupArchivePath()
    image_dir = self.GetImageDirSymlink()
    upload_queue = multiprocessing.Queue()
    upload_symbols_queue = multiprocessing.Queue()
    hw_test_upload_queue = multiprocessing.Queue()
    bg_task_runner = background.BackgroundTaskRunner

    extra_env = {}
    if config['useflags']:
      extra_env['USE'] = ' '.join(config['useflags'])

    if not archive_path:
      raise NothingToArchiveException()

    # The following functions are run in parallel (except where indicated
    # otherwise)
    # \- BuildAndArchiveArtifacts
    #    \- ArchiveArtifactsForHWTesting
    #       \- ArchiveAutotestTarballs
    #       \- ArchivePayloads
    #    \- ArchiveTestResults
    #    \- ArchiveStrippedChrome
    #    \- ArchiveReleaseArtifacts
    #       \- ArchiveDebugSymbols
    #       \- ArchiveFirmwareImages
    #       \- BuildAndArchiveAllImages
    #          (builds recovery image first, then launches functions below)
    #          \- BuildAndArchiveFactoryImages
    #          \- ArchiveRegularImages
    #       \- PushImage

    def ArchiveAutotestTarballs():
      """Archives the autotest tarballs produced in BuildTarget."""
      autotest_tarballs = self._GetAutotestTarballs()
      if autotest_tarballs:
        for tarball in autotest_tarballs:
          hw_test_upload_queue.put([commands.ArchiveFile(tarball,
                                                         archive_path)])

    def ArchivePayloads():
      """Archives update payloads when they are ready."""
      if self._build_config['upload_hw_test_artifacts']:
        update_payloads_dir = tempfile.mkdtemp(prefix='cbuildbot')
        target_image_path = os.path.join(self.GetImageDirSymlink(),
                                         'chromiumos_test_image.bin')
        # For non release builds, we are only interested in generating payloads
        # for the purpose of imaging machines. This means we shouldn't generate
        # delta payloads for n-1->n testing.
        if self._build_config['build_type'] != constants.CANARY_TYPE:
          commands.GenerateFullPayload(
              buildroot, target_image_path, update_payloads_dir)
        else:
          commands.GenerateNPlus1Payloads(
              buildroot, self._bot_id, target_image_path, update_payloads_dir)

        for payload in os.listdir(update_payloads_dir):
          full_path = os.path.join(update_payloads_dir, payload)
          hw_test_upload_queue.put([commands.ArchiveFile(full_path,
                                                         archive_path)])

    def ArchiveTestResults():
      """Archives test results when they are ready."""
      got_symbols = self._WaitForBreakpadSymbols()
      for test_results in self._GetTestResults():
        if got_symbols:
          filenames = commands.GenerateMinidumpStackTraces(buildroot,
                                                           board, test_results,
                                                           archive_path)
          for filename in filenames:
            upload_queue.put([filename])
        upload_queue.put([commands.ArchiveFile(test_results, archive_path)])

    def ArchiveDebugSymbols():
      """Generate debug symbols and upload debug.tgz."""
      if config['archive_build_debug'] or config['vm_tests']:
        success = False
        try:
          commands.GenerateBreakpadSymbols(buildroot, board)
          success = True
        finally:
          self._BreakpadSymbolsGenerated(success)

        # Kick off the symbol upload process in the background.
        if config['upload_symbols']:
          upload_symbols_queue.put([])

        # Generate and upload tarball.
        filename = commands.GenerateDebugTarball(
            buildroot, board, archive_path, config['archive_build_debug'])
        upload_queue.put([filename])
      else:
        self._BreakpadSymbolsGenerated(False)

    def UploadSymbols():
      """Upload generated debug symbols."""
      if not debug:
        commands.UploadSymbols(buildroot, board, config['chromeos_official'])

    def BuildAndArchiveFactoryImages():
      """Build and archive the factory zip file.

      The factory zip file consists of the factory test image and the factory
      install image. Both are built here.
      """

      # Build factory test image and create symlink to it.
      factory_test_symlink = None
      if 'factory_test' in config['images']:
        alias = commands.BuildFactoryTestImage(buildroot, board, extra_env)
        factory_test_symlink = self.GetImageDirSymlink(alias)

      # Build factory install image and create a symlink to it.
      factory_install_symlink = None
      if 'factory_install' in config['images']:
        alias = commands.BuildFactoryInstallImage(buildroot, board, extra_env)
        factory_install_symlink = self.GetImageDirSymlink(alias)
        if config['factory_install_netboot']:
          commands.MakeNetboot(buildroot, board, factory_install_symlink)

      # Build and upload factory zip.
      if factory_install_symlink and factory_test_symlink:
        image_root = os.path.dirname(factory_install_symlink)
        filename = commands.BuildFactoryZip(buildroot, archive_path, image_root)
        upload_queue.put([filename])

    def ArchiveRegularImages():
      """Build and archive regular images.

      This includes the image.zip archive, the recovery image archive, the
      hwqual images, and au-generator.zip used for update payload generation.
      """

      # Zip up everything in the image directory.
      upload_queue.put([commands.BuildImageZip(archive_path, image_dir)])

      # Zip up the recovery image separately.
      # TODO(gauravsh): Remove recovery_image.bin from image.zip once we
      #                 we know for sure there are no users relying on it.
      if 'base' in config['images']:
        upload_queue.put([commands.BuildRecoveryImageZip(
            archive_path,
            os.path.join(image_dir, 'recovery_image.bin'))])

      # TODO(petermayo): This logic needs to be exported from the BuildTargets
      # stage rather than copied/re-evaluated here.
      autotest_built = config['build_tests'] and self._options.tests and (
          config['upload_hw_test_artifacts'] or config['archive_build_debug'])

      if config['chromeos_official'] and autotest_built:
        # Archive the full autotest tarball
        full_autotest_tarball = self._GetFullAutotestTarball()
        filename = commands.ArchiveFile(full_autotest_tarball, archive_path)
        cros_build_lib.Info('Archiving full autotest tarball locally ...')

        # Build hwqual image and upload to Google Storage.
        version = self.GetVersion()
        hwqual_name = 'chromeos-hwqual-%s-%s' % (board, version)
        filename = commands.ArchiveHWQual(buildroot, hwqual_name, archive_path)
        upload_queue.put([filename])

      # Archive au-generator.zip.
      filename = 'au-generator.zip'
      shutil.copy(os.path.join(image_dir, filename), archive_path)
      upload_queue.put([filename])

    def ArchiveFirmwareImages():
      """Archive firmware images built from source if available."""
      archive = commands.BuildFirmwareArchive(buildroot, board, archive_path)
      if archive:
        upload_queue.put([archive])

    def BuildAndArchiveAllImages():
      # Generate the recovery image. To conserve loop devices, we try to only
      # run one instance of build_image at a time. TODO(davidjames): Move the
      # image generation out of the archive stage.
      if 'base' in config['images']:
        commands.BuildRecoveryImage(buildroot, board, image_dir, extra_env)

      background.RunParallelSteps([BuildAndArchiveFactoryImages,
                                   ArchiveRegularImages])

    def UploadArtifact(filename):
      """Upload generated artifact to Google Storage."""
      commands.UploadArchivedFile(archive_path, upload_url, filename, debug)

    def ArchiveArtifactsForHWTesting(num_upload_processes=6):
      """Archives artifacts required for HWTest stage."""
      queue = hw_test_upload_queue
      success = False
      try:
        with bg_task_runner(queue, UploadArtifact, num_upload_processes):
          steps = [ArchiveAutotestTarballs, ArchivePayloads]
          background.RunParallelSteps(steps)
        success = True
      finally:
        self._hw_test_uploads_status_queue.put(success)

    def ArchiveStrippedChrome():
      """Generate and upload stripped Chrome package."""
      cmd = ['strip_package', '--board', board,
             'chromeos-chrome']
      cros_build_lib.RunCommand(cmd, cwd=buildroot, enter_chroot=True)
      chrome_match = os.path.join(buildroot, 'chroot', 'build', board,
                                  'stripped-packages', 'chromeos-base',
                                  'chromeos-chrome-*')

      files = glob.glob(chrome_match)
      files.sort()
      if not files:
        raise Exception('No stripped Chrome found!')
      elif len(files) > 1:
        cros_build_lib.PrintBuildbotStepWarnings()
        cros_build_lib.Warning('Expecting one stripped Chrome package, but '
                               'found multiple in %s.',
                               os.path.dirname(chrome_match))

      chrome_tarball = files[-1]
      filename = os.path.basename(chrome_tarball)
      cros_build_lib.RunCommand(['ln', '-f', chrome_tarball, filename],
                                 cwd=archive_path)
      upload_queue.put([filename])

    def PushImage():
      # Now that all data has been generated, we can upload the final result to
      # the image server.
      # TODO: When we support branches fully, the friendly name of the branch
      # needs to be used with PushImages
      if config['push_image']:
        commands.PushImages(buildroot,
                            board=board,
                            branch_name='master',
                            archive_url=upload_url,
                            dryrun=debug,
                            profile=self._options.profile or config['profile'])


    def ArchiveReleaseArtifacts():
      steps = [ArchiveDebugSymbols, BuildAndArchiveAllImages,
               ArchiveFirmwareImages]
      background.RunParallelSteps(steps)
      PushImage()

    def BuildAndArchiveArtifacts(num_upload_processes=10):
      with bg_task_runner(upload_symbols_queue, UploadSymbols, 1):
        with bg_task_runner(upload_queue, UploadArtifact, num_upload_processes):
          # Run archiving steps in parallel.
          steps = [ArchiveReleaseArtifacts, ArchiveStrippedChrome,
                   ArchiveArtifactsForHWTesting, ArchiveTestResults]
          background.RunParallelSteps(steps)

    def MarkAsLatest():
      # Update and upload LATEST file.
      version = self.GetVersion()
      if version:
        commands.UpdateLatestFile(self._bot_archive_root, version)
        commands.UploadArchivedFile(self._bot_archive_root,
                                    self._GetGSUtilArchiveDir(), 'LATEST',
                                    debug)

    try:
      BuildAndArchiveArtifacts()
      MarkAsLatest()
    finally:
      commands.RemoveOldArchives(self._bot_archive_root,
                                 self._options.max_archive_builds)

  def _HandleStageException(self, exception):
    # Tell the HWTestStage not to wait for artifacts to be uploaded
    # in case ArchiveStage throws an exception.
    self._hw_test_uploads_status_queue.put(False)
    return super(ArchiveStage, self)._HandleStageException(exception)


class UploadPrebuiltsStage(BoardSpecificBuilderStage):
  """Uploads binaries generated by this build for developer use."""

  option_name = 'prebuilts'
  config_name = 'prebuilts'

  def __init__(self, options, build_config, board, archive_stage, suffix=None):
    super(UploadPrebuiltsStage, self).__init__(options, build_config,
                                               board, suffix)
    self._archive_stage = archive_stage

  @classmethod
  def _AddOptionsForSlave(cls, builder, board):
    """Inner helper method to add upload_prebuilts args for a slave builder.

    Returns:
      An array of options to add to upload_prebuilts array that allow a master
      to submit prebuilt conf modifications on behalf of a slave.
    """
    args = []
    builder_config = cbuildbot_config.config[builder]
    if builder_config['prebuilts']:
      for slave_board in builder_config['boards']:
        if builder_config['master'] and slave_board == board:
          # Ignore self.
          continue

        args.extend(['--slave-board', slave_board])
        slave_profile = builder_config['profile']
        if slave_profile:
          args.extend(['--slave-profile', slave_profile])

    return args

  def _PerformStage(self):
    """Uploads prebuilts for master and slave builders."""
    prebuilt_type = self._prebuilt_type
    board = self._current_board
    git_sync = self._build_config['git_sync']
    binhosts = []

    # Common args we generate for all types of builds.
    generated_args = []
    # Args we specifically add for public build types.
    public_args = []
    # Args we specifically add for private build types.
    private_args = []

    # TODO(sosa): Break out devinstaller options into separate stage.
    # Devinstaller configuration options.
    binhost_bucket = self._build_config['binhost_bucket']
    binhost_key = self._build_config['binhost_key']
    binhost_base_url = self._build_config['binhost_base_url']
    # Check if we are uploading dev_installer prebuilts.
    use_binhost_package_file = False
    if self._build_config['dev_installer_prebuilts']:
      use_binhost_package_file = True
      private_bucket = False
    else:
      private_bucket = self._build_config['overlays'] in (
          constants.PRIVATE_OVERLAYS, constants.BOTH_OVERLAYS)

    if self._options.debug:
      generated_args.append('--debug')

    profile = self._options.profile or self._build_config['profile']
    if profile:
      generated_args.extend(['--profile', profile])

    # Distributed builders that use manifest-versions to sync with one another
    # share prebuilt logic by passing around versions.
    unified_master = False
    if self._build_config['manifest_version']:
      assert self._archive_stage, 'Manifest version config needs a version.'
      version = self._archive_stage.GetVersion()
      if version:
        generated_args.extend(['--set-version', version])
      else:
        # Non-debug manifest-versioned builds must actually have versions.
        assert self._options.debug, 'Non-debug builds must have versions'

      if cbuildbot_config.IsPFQType(prebuilt_type):
        # The master builder updates all the binhost conf files, and needs to do
        # so only once so as to ensure it doesn't try to update the same file
        # more than once. As multiple boards can be built on the same builder,
        # we arbitrarily decided to update the binhost conf files when we run
        # upload_prebuilts for the last board. The other boards are treated as
        # slave boards.
        if self._build_config['master'] and board == self._boards[-1]:
          unified_master = self._build_config['unified_manifest_version']
          generated_args.append('--sync-binhost-conf')
          # Difference here is that unified masters upload for both
          # public/private builders which have slightly different rules.
          if not unified_master:
            for builder in self._GetSlavesForMaster():
              generated_args.extend(self._AddOptionsForSlave(builder, board))
          else:
            public_builders, private_builders = \
                self._GetSlavesForUnifiedMaster()
            for builder in public_builders:
              public_args.extend(self._AddOptionsForSlave(builder, board))

            for builder in private_builders:
              private_args.extend(self._AddOptionsForSlave(builder, board))

        # Public pfqs should upload host preflight prebuilts.
        if (cbuildbot_config.IsPFQType(prebuilt_type)
            and prebuilt_type != constants.CHROME_PFQ_TYPE):
          public_args.append('--sync-host')

        # Deduplicate against previous binhosts.
        binhosts.extend(self._GetPortageEnvVar(_PORTAGE_BINHOST, board).split())
        binhosts.extend(self._GetPortageEnvVar(_PORTAGE_BINHOST, None).split())
        for binhost in binhosts:
          if binhost: generated_args.extend(['--previous-binhost-url', binhost])

    if unified_master:
      # Upload the public/private prebuilts sequentially for unified master.
      # Override git-sync to be false for unified masters.
      assert not git_sync, 'This should never be True for pfq-type builders.'
      # We set board to None as the unified master is always internal.
      commands.UploadPrebuilts(
          self._build_root, None, False, prebuilt_type,
          self._chrome_rev, binhost_bucket, binhost_key, binhost_base_url,
          use_binhost_package_file, git_sync, generated_args + public_args)
      commands.UploadPrebuilts(
          self._build_root, board, True, prebuilt_type,
          self._chrome_rev, binhost_bucket, binhost_key, binhost_base_url,
          use_binhost_package_file, git_sync, generated_args + private_args)
    else:
      # Upload prebuilts for all other types of builders.
      extra_args = private_args if private_bucket else public_args
      commands.UploadPrebuilts(
          self._build_root, board, private_bucket, prebuilt_type,
          self._chrome_rev, binhost_bucket, binhost_key, binhost_base_url,
          use_binhost_package_file, git_sync, generated_args + extra_args)


class PublishUprevChangesStage(NonHaltingBuilderStage):
  """Makes uprev changes from pfq live for developers."""
  def _PerformStage(self):
    _, push_overlays = self._ExtractOverlays()
    if push_overlays:
      commands.UprevPush(self._build_root,
                         push_overlays,
                         self._options.debug)
