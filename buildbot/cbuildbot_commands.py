# Copyright (c) 2011 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Module containing the various individual commands a builder can run."""

import constants
import os
import shutil

from chromite.buildbot import repository
from chromite.lib import cros_build_lib as cros_lib


_DEFAULT_RETRIES = 3
_PACKAGE_FILE = '%(buildroot)s/src/scripts/cbuildbot_package.list'
CHROME_KEYWORDS_FILE = ('/build/%(board)s/etc/portage/package.keywords/chrome')
_PREFLIGHT_BINHOST = 'PREFLIGHT_BINHOST'
_CHROME_BINHOST = 'CHROME_BINHOST'
_CROS_ARCHIVE_URL = 'CROS_ARCHIVE_URL'
_FULL_BINHOST = 'FULL_BINHOST'
_PRIVATE_BINHOST_CONF_DIR = ('src/private-overlays/chromeos-overlay/'
                             'chromeos/binhost')
_GSUTIL_PATH = '/b/scripts/slave/gsutil'
_GS_GEN_INDEX = '/b/scripts/gsd_generate_index/gsd_generate_index.py'
_GS_ACL = '/home/chrome-bot/slave_archive_acl'


# =========================== Command Helpers =================================


def _BuildRootGitCleanup(buildroot):
  """Put buildroot onto manifest branch. Delete branches created on last run."""
  manifest_branch = 'remotes/m/' + cros_lib.GetManifestDefaultBranch(buildroot)
  project_list = cros_lib.RunCommand(['repo', 'forall', '-c', 'pwd'],
                                     redirect_stdout=True,
                                     cwd=buildroot).output.splitlines()
  for project in project_list:
    # The 'git clean' command below might remove some repositories.
    if not os.path.exists(project):
      continue

    cros_lib.RunCommand(['git', 'am', '--abort'], print_cmd=False,
                        redirect_stdout=True, redirect_stderr=True,
                        error_ok=True, cwd=project)
    cros_lib.RunCommand(['git', 'rebase', '--abort'], print_cmd=False,
                        redirect_stdout=True, redirect_stderr=True,
                        error_ok=True, cwd=project)
    cros_lib.RunCommand(['git', 'reset', '--hard', 'HEAD'], print_cmd=False,
                        redirect_stdout=True, cwd=project)
    cros_lib.RunCommand(['git', 'checkout', manifest_branch], print_cmd=False,
                        redirect_stdout=True, redirect_stderr=True,
                        cwd=project)
    cros_lib.RunCommand(['git', 'clean', '-f', '-d'], print_cmd=False,
                        redirect_stdout=True, cwd=project)

    for branch in constants.CREATED_BRANCHES:
      if cros_lib.DoesLocalBranchExist(project, branch):
        cros_lib.RunCommand(['repo', 'abandon', branch, '.'], cwd=project)


def _CleanUpMountPoints(buildroot):
  """Cleans up any stale mount points from previous runs."""
  mount_output = cros_lib.OldRunCommand(['mount'], redirect_stdout=True,
                                        print_cmd=False)
  mount_pts_in_buildroot = cros_lib.OldRunCommand(
      ['grep', buildroot], input=mount_output, redirect_stdout=True,
      error_ok=True, print_cmd=False)

  for mount_pt_str in mount_pts_in_buildroot.splitlines():
    mount_pt = mount_pt_str.rpartition(' type ')[0].partition(' on ')[2]
    cros_lib.OldRunCommand(['sudo', 'umount', '-l', mount_pt], error_ok=True,
                           print_cmd=False)


def _GetVMConstants(buildroot):
  """Returns minimum (vdisk_size, statefulfs_size) recommended for VM's."""
  cwd = os.path.join(buildroot, 'src', 'scripts', 'lib')
  source_cmd = 'source %s/cros_vm_constants.sh' % cwd
  vdisk_size = cros_lib.OldRunCommand([
      '/bin/bash', '-c', '%s && echo $MIN_VDISK_SIZE_FULL' % source_cmd],
       redirect_stdout=True)
  statefulfs_size = cros_lib.OldRunCommand([
      '/bin/bash', '-c', '%s && echo $MIN_STATEFUL_FS_SIZE_FULL' % source_cmd],
       redirect_stdout=True)
  return (vdisk_size.strip(), statefulfs_size.strip())


def _WipeOldOutput(buildroot):
  """Wipes out build output directories."""
  cros_lib.OldRunCommand(['rm', '-rf', 'src/build/images'], cwd=buildroot)


def GetInput(prompt):
  """Helper function to grab input from a user.   Makes testing easier."""
  return raw_input(prompt)


def ValidateClobber(buildroot):
  """Do due diligence if user wants to clobber buildroot.

    buildroot: buildroot that's potentially clobbered.
  Returns: True if the clobber is ok.
  """
  cwd = os.path.dirname(os.path.realpath(__file__))
  if cwd.startswith(buildroot):
    cros_lib.Die('You are trying to clobber this chromite checkout!')

  if os.path.exists(buildroot):
    cros_lib.Warning('This will delete %s' % buildroot)
    prompt = ('\nDo you want to continue (yes/NO)? ')
    response = GetInput(prompt).lower()
    if response != 'yes':
      return False

    return True


# =========================== Main Commands ===================================


def PreFlightRinse(buildroot):
  """Cleans up any leftover state from previous runs."""
  _BuildRootGitCleanup(buildroot)
  _CleanUpMountPoints(buildroot)
  cros_lib.OldRunCommand(['sudo', 'killall', 'kvm'], error_ok=True)


def ManifestCheckout(buildroot, tracking_branch, next_manifest, url):
  """Performs a manifest checkout and clobbers any previous checkouts."""

  print "BUILDROOT: %s" % buildroot
  print "TRACKING BRANCH: %s" % tracking_branch
  print "NEXT MANIFEST: %s" % next_manifest

  repo = repository.RepoRepository(url, buildroot, branch=tracking_branch)
  repo.Sync(next_manifest)
  repo.ExportManifest('/dev/stderr')


def MakeChroot(buildroot, replace, fast, usepkg):
  """Wrapper around make_chroot."""
  # TODO(zbehan): Remove this hack. crosbug.com/17474
  if os.environ.get('USE_CROS_SDK') == '1':
    # We assume these two are on for cros_sdk. Fail out if they aren't.
    assert usepkg
    assert fast
    cwd = os.path.join(buildroot, 'chromite', 'bin')
    cmd = ['./cros_sdk']
  else:
    cwd = os.path.join(buildroot, 'src', 'scripts')
    cmd = ['./make_chroot']

    if not usepkg:
      cmd.append('--nousepkg')

    if fast:
      cmd.append('--fast')
    else:
      cmd.append('--nofast')

  if replace:
    cmd.append('--replace')

  cros_lib.OldRunCommand(cmd, cwd=cwd)


def RunChrootUpgradeHooks(buildroot):
  """Run the chroot upgrade hooks in the chroot."""
  cwd = os.path.join(buildroot, 'src', 'scripts')
  cros_lib.RunCommand(['./run_chroot_version_hooks'], cwd=cwd,
                      enter_chroot=True)


def SetupBoard(buildroot, board, fast, usepkg, latest_toolchain,
               extra_env=None, profile=None):
  """Wrapper around setup_board."""
  cwd = os.path.join(buildroot, 'src', 'scripts')
  cmd = ['./setup_board', '--board=%s' % board]

  if profile:
    cmd.append('--profile=%s' % profile)

  if not usepkg:
    cmd.append('--nousepkg')

  if fast:
    cmd.append('--fast')
  else:
    cmd.append('--nofast')

  if latest_toolchain:
    cmd.append('--latest_toolchain')

  cros_lib.RunCommand(cmd, cwd=cwd, enter_chroot=True, extra_env=extra_env)


def Build(buildroot, board, build_autotest, fast, usepkg, skip_toolchain_update,
          nowithdebug, extra_env=None):
  """Wrapper around build_packages."""
  cwd = os.path.join(buildroot, 'src', 'scripts')
  cmd = ['./build_packages', '--board=%s' % board]
  if extra_env is None:
    env = {}
  else:
    env = extra_env.copy()

  if fast:
    cmd.append('--fast')
  else:
    cmd.append('--nofast')

  if not build_autotest: cmd.append('--nowithautotest')

  if skip_toolchain_update: cmd.append('--skip_toolchain_update')

  if usepkg:
    key = 'EXTRA_BOARD_FLAGS'
    prev = env.get(key)
    env[key] = (prev and prev + ' ' or '') + '--rebuilt-binaries'
  else:
    cmd.append('--nousepkg')

  if nowithdebug:
    cmd.append('--nowithdebug')

  cros_lib.RunCommand(cmd, cwd=cwd, enter_chroot=True, extra_env=env)


def BuildImage(buildroot, board, mod_for_test, extra_env=None):
  _WipeOldOutput(buildroot)

  cwd = os.path.join(buildroot, 'src', 'scripts')
  cmd = ['./build_image', '--board=%s' % board, '--replace']
  if mod_for_test:
    cmd.append('--test')

  cros_lib.RunCommand(cmd, cwd=cwd, enter_chroot=True, extra_env=extra_env)


def BuildVMImageForTesting(buildroot, board, extra_env=None):
  (vdisk_size, statefulfs_size) = _GetVMConstants(buildroot)
  cwd = os.path.join(buildroot, 'src', 'scripts')
  cros_lib.RunCommand(['./image_to_vm.sh',
                       '--board=%s' % board,
                       '--test_image',
                       '--full',
                       '--vdisk_size=%s' % vdisk_size,
                       '--statefulfs_size=%s' % statefulfs_size,
                      ], cwd=cwd, enter_chroot=True, extra_env=extra_env)


def RunUnitTests(buildroot, board, full, nowithdebug):
  cwd = os.path.join(buildroot, 'src', 'scripts')

  cmd = ['cros_run_unit_tests', '--board=%s' % board]

  if nowithdebug:
    cmd.append('--nowithdebug')

# If we aren't running ALL tests, then restrict to just the packages
  #   uprev noticed were changed.
  if not full:
    cmd += ['--package_file=%s' %
            cros_lib.ReinterpretPathForChroot(_PACKAGE_FILE %
                                              {'buildroot': buildroot})]

  cros_lib.OldRunCommand(cmd, cwd=cwd, enter_chroot=True)


def RunChromeSuite(buildroot, board, image_dir, results_dir):
  results_dir_in_chroot = os.path.join(buildroot, 'chroot',
                                       results_dir.lstrip('/'))
  if os.path.exists(results_dir_in_chroot):
    shutil.rmtree(results_dir_in_chroot)

  image_path = os.path.join(image_dir, 'chromiumos_test_image.bin')

  cwd = os.path.join(buildroot, 'src', 'scripts')
  # TODO(cmasone): make this look for ALL desktopui_BrowserTest control files.
  cros_lib.OldRunCommand(['bin/cros_run_parallel_vm_tests',
                          '--board=%s' % board,
                          '--quiet',
                          '--image_path=%s' % image_path,
                          '--results_dir_root=%s' % results_dir,
                          'desktopui_BrowserTest.control$',
                          'desktopui_BrowserTest.control.one',
                          'desktopui_BrowserTest.control.two',
                          'desktopui_BrowserTest.control.three',
                         ], cwd=cwd, error_ok=True, enter_chroot=False)


def RunTestSuite(buildroot, board, image_dir, results_dir, full=True):
  """Runs the test harness suite."""
  results_dir_in_chroot = os.path.join(buildroot, 'chroot',
                                       results_dir.lstrip('/'))
  if os.path.exists(results_dir_in_chroot):
    shutil.rmtree(results_dir_in_chroot)

  cwd = os.path.join(buildroot, 'src', 'scripts')
  image_path = os.path.join(image_dir, 'chromiumos_test_image.bin')

  if full:
    cmd = ['bin/ctest',
           '--board=%s' % board,
           '--channel=dev-channel',
           '--zipbase=http://chromeos-images.corp.google.com',
           '--type=vm',
           '--no_graphics',
           '--target_image=%s' % image_path,
           '--test_results_root=%s' % results_dir_in_chroot, ]
  else:
    cmd = ['bin/cros_au_test_harness',
           '--no_graphics',
           '--no_delta',
           '--board=%s' % board,
           '--test_prefix=SimpleTest',
           '--verbose',
           '--base_image=%s' % image_path,
           '--target_image=%s' % image_path,
           '--test_results_root=%s' % results_dir_in_chroot, ]

  cros_lib.OldRunCommand(cmd, cwd=cwd, error_ok=False)


def UpdateRemoteHW(buildroot, board, image_dir, remote_ip):
  """Reimage the remote machine using the image modified for test."""

  cwd = os.path.join(buildroot, 'src', 'scripts')
  test_image_path = os.path.join(image_dir, 'chromiumos_test_image.bin')
  cmd = ['./image_to_live.sh',
         '--remote=%s' % remote_ip,
         '--image=%s' % test_image_path, ]

  cros_lib.OldRunCommand(cmd, cwd=cwd, enter_chroot=False, error_ok=False,
                         print_cmd=True)


def RunRemoteTest(buildroot, board, remote_ip, test_name, args=None):
  """Execute an autotest on a remote machine."""

  cwd = os.path.join(buildroot, 'src', 'scripts')

  cmd = ['./run_remote_tests.sh',
         '--board=%s' % board,
         '--remote=%s' % remote_ip]

  if args and len(args) > 0:
    cmd.append('--args="%s"' % ' '.join(args))

  cmd.append(test_name)

  cros_lib.OldRunCommand(cmd, cwd=cwd, enter_chroot=True, error_ok=False,
                         print_cmd=True)


def ArchiveTestResults(buildroot, test_results_dir):
  """Archives the test results into a tarball.

  Arguments:
    buildroot: Root directory where build occurs
    test_results_dir: Path from buildroot/chroot to find test results.
      This must a subdir of /tmp.

  Returns the path to the tarball.
  """
  try:
    test_results_dir = test_results_dir.lstrip('/')
    results_path = os.path.join(buildroot, 'chroot', test_results_dir)
    cros_lib.OldRunCommand(['sudo', 'chmod', '-R', 'a+rw', results_path],
                           print_cmd=False)

    test_tarball = os.path.join(buildroot, 'test_results.tgz')
    if os.path.exists(test_tarball): os.remove(test_tarball)
    cros_lib.OldRunCommand(['tar',
                            'czf',
                            test_tarball,
                            '--directory=%s' % results_path,
                            '.'])
    shutil.rmtree(results_path)

    return test_tarball

  except Exception, e:
    cros_lib.Warning('========================================================')
    cros_lib.Warning('------>  We failed to archive test results. <-----------')
    cros_lib.Warning(str(e))
    cros_lib.Warning('========================================================')


def UploadTestTarball(test_tarball, local_archive_dir, upload_url, debug):
  """Uploads the test results tarball.

  Arguments:
    test_tarball: Path to test tarball.
    upload_url: Google Storage location for test tarball.
    local_archive_dir: Local directory for archive tarball.
    debug: Whether we're in debug mode.
  """
  if local_archive_dir:
    archived_tarball = os.path.join(local_archive_dir, 'test_results.tgz')
    shutil.copy(test_tarball, archived_tarball)
    os.chmod(archived_tarball, 0644)

  if upload_url and not debug:
    tarball_url = '%s/%s' % (upload_url, 'test_results.tgz')
    cros_lib.OldRunCommand([_GSUTIL_PATH,
                            'cp',
                            test_tarball,
                            tarball_url])
    cros_lib.OldRunCommand([_GSUTIL_PATH,
                            'setacl',
                            _GS_ACL,
                            tarball_url])


def MarkChromeAsStable(buildroot, tracking_branch, chrome_rev, board):
  """Returns the portage atom for the revved chrome ebuild - see man emerge."""
  cwd = os.path.join(buildroot, 'src', 'scripts')
  portage_atom_string = cros_lib.OldRunCommand(
      ['../../chromite/buildbot/cros_mark_chrome_as_stable',
       '--tracking_branch=%s' % tracking_branch,
       '--board=%s' % board,
       chrome_rev],
      cwd=cwd, redirect_stdout=True, enter_chroot=True).rstrip()
  if not portage_atom_string:
    cros_lib.Info('Found nothing to rev.')
    return None
  else:
    chrome_atom = portage_atom_string.splitlines()[-1].split('=')[1]
    keywords_file = CHROME_KEYWORDS_FILE % {'board': board}
    cros_lib.OldRunCommand(
        ['sudo', 'mkdir', '-p', os.path.dirname(keywords_file)],
        enter_chroot=True, cwd=cwd)
    cros_lib.OldRunCommand(
        ['sudo', 'tee', keywords_file], input='=%s\n' % chrome_atom,
        enter_chroot=True, cwd=cwd)
    return chrome_atom


def CleanupChromeKeywordsFile(board, buildroot):
  """Cleans chrome uprev artifact if it exists."""
  keywords_path_in_chroot = CHROME_KEYWORDS_FILE % {'board': board}
  keywords_file = '%s/chroot%s' % (buildroot, keywords_path_in_chroot)
  if os.path.exists(keywords_file):
    cros_lib.RunCommand(['sudo', 'rm', '-f', keywords_file])


def UprevPackages(buildroot, board, overlays):
  """Uprevs non-browser chromium os packages that have changed."""
  cwd = os.path.join(buildroot, 'src', 'scripts')
  chroot_overlays = [
      cros_lib.ReinterpretPathForChroot(path) for path in overlays ]
  cros_lib.OldRunCommand(
      ['../../chromite/buildbot/cros_mark_as_stable', '--all',
       '--board=%s' % board,
       '--overlays=%s' % ':'.join(chroot_overlays),
       '--drop_file=%s' % cros_lib.ReinterpretPathForChroot(
           _PACKAGE_FILE % {'buildroot': buildroot}),
       'commit'], cwd=cwd, enter_chroot=True)


def UprevPush(buildroot, board, overlays, dryrun):
  """Pushes uprev changes to the main line."""
  cwd = os.path.join(buildroot, 'src', 'scripts')
  cmd = ['../../chromite/buildbot/cros_mark_as_stable',
         '--srcroot=%s' % os.path.join(buildroot, 'src'),
         '--board=%s' % board,
         '--overlays=%s' % ':'.join(overlays)
        ]
  if dryrun:
    cmd.append('--dryrun')

  cmd.append('push')
  cros_lib.OldRunCommand(cmd, cwd=cwd)


def UploadPrebuilts(buildroot, board, overlay_config, category,
                    chrome_rev, buildnumber,
                    binhost_bucket=None,
                    binhost_key=None,
                    binhost_base_url=None,
                    git_sync=False,
                    extra_args=[]):
  """Upload prebuilts.

  Args:
    buildroot: The root directory where the build occurs.
    board: Board type that was built on this machine
    overlay_config: A string describing which overlays you want.
                    'private': Just the private overlay.
                    'public': Just the public overlay.
                    'both': Both the public and private overlays.
    category: Build type. Can be [binary|full|chrome].
    chrome_rev: Chrome_rev of type constants.VALID_CHROME_REVISIONS.
    buildnumber:  self explanatory.
    binhost_bucket: bucket for uploading prebuilt packages. If it equals None
                    then the default bucket is used.
    binhost_key: key parameter to pass onto prebuilt.py. If it equals None then
                 chrome_rev is used to select a default key.
    binhost_base_url: base url for prebuilt.py. If None the parameter
                      --binhost-base-url is absent.
    git_sync: boolean that enables --git-sync prebuilt.py parameter.
    extra_args: Extra args to send to prebuilt.py.
  """
  cwd = os.path.dirname(__file__)
  cmd = ['./prebuilt.py',
         '--build-path', buildroot,
         '--prepend-version', category]

  if binhost_base_url is not None:
    cmd.extend(['--binhost-base-url', binhost_base_url])
  if binhost_bucket is not None:
    cmd.extend(['--upload', binhost_bucket])
  elif overlay_config == 'public':
    cmd.extend(['--upload', 'gs://chromeos-prebuilt'])
  else:
    assert overlay_config in ('private', 'both')
    bucket_board = 'chromeos-%s' % board
    upload_bucket = 'gs://%s/%s/%d/prebuilts/' % (bucket_board, category,
                    buildnumber)
    cmd.extend(['--upload', upload_bucket])
  if overlay_config in ('private', 'both'):
    cmd.extend(['--private', '--binhost-conf-dir', _PRIVATE_BINHOST_CONF_DIR])

  if category == 'chroot':
    cmd.extend(['--sync-host',
                '--board', 'amd64-host',
                '--upload-board-tarball'])
  else:
    cmd.extend(['--board', board])

  if binhost_key is not None:
    cmd.extend(['--key', binhost_key])
  elif category == constants.CHROME_PFQ_TYPE:
    assert chrome_rev
    key = '%s_%s' % (chrome_rev, _CHROME_BINHOST)
    cmd.extend(['--key', key.upper()])
  elif category == constants.PFQ_TYPE:
    cmd.extend(['--key', _PREFLIGHT_BINHOST])
  else:
    assert category in (constants.BUILD_FROM_SOURCE_TYPE,
                        constants.CHROOT_BUILDER_TYPE)
    cmd.extend(['--key', _FULL_BINHOST])

  if category == constants.CHROME_PFQ_TYPE:
    cmd.extend(['--packages=chromeos-chrome'])

  if git_sync:
    cmd.extend(['--git-sync'])
  cmd.extend(extra_args)
  cros_lib.OldRunCommand(cmd, cwd=cwd)


def LegacyArchiveBuild(buildroot, bot_id, buildconfig, gsutil_archive,
                       set_version, archive_path, debug=False):
  """Archives build artifacts and returns URL to archived location."""

  # Fixed properties
  keep_max = 3

  cwd = os.path.join(buildroot, 'src', 'scripts')
  cmd = ['./archive_build.sh',
         '--set_version', str(set_version),
         '--to', os.path.join(archive_path, bot_id),
         '--keep_max', str(keep_max),
         '--board', buildconfig['board'],
         ]

  # If we archive to Google Storage
  if gsutil_archive:
    cmd += ['--gsutil_archive', gsutil_archive,
            '--acl', _GS_ACL,
            '--gsutil', _GSUTIL_PATH,
            ]

  # Give the right args to archive_build.
  if buildconfig.get('chromeos_official'): cmd.append('--official_build')
  if buildconfig.get('factory_test_mod', True): cmd.append('--factory_test_mod')
  cmd.append('--noarchive_debug')
  if not buildconfig.get('test_mod'): cmd.append('--notest_mod')
  if debug: cmd.append('--debug')
  if buildconfig.get('factory_install_mod', True):
    cmd.append('--factory_install_mod')

  useflags = buildconfig.get('useflags')
  if useflags: cmd.extend(['--useflags', ' '.join(useflags)])

  cros_lib.RunCommand(cmd, cwd=cwd)

def UpdateIndex(upload_url):
  """Update _index.html page in Google Storage.

  upload_url: Google Storage location where we want an updated index.
  """
  cros_lib.RunCommand([_GS_GEN_INDEX,
                       '--gsutil', _GSUTIL_PATH,
                       '-a', _GS_ACL,
                       upload_url])


def GenerateBreakpadSymbols(buildroot, board):
  """Generate breakpad symbols.

  Args:
    buildroot: The root directory where the build occurs.
    board: Board type that was built on this machine
  """
  cwd = os.path.join(buildroot, 'src', 'scripts')
  cmd = ['./cros_generate_breakpad_symbols',
         '--board=%s' % board]
  cros_lib.RunCommand(cmd, cwd=cwd, enter_chroot=True)


def GenerateDebugTarball(buildroot, board, archive_path):
  """Generates a debug tarball in the archive_dir.

  Args:
    buildroot: The root directory where the build occurs.
    board: Board type that was built on this machine
    archive_dir: Directory where tarball should be stored.

  Returns the path to the debug tarball.
  """

  # Generate debug tarball. This needs to run as root because some of the
  # symbols are only readable by root.
  board_dir = os.path.join(buildroot, 'chroot', 'build', board, 'usr', 'lib')
  debug_tgz = os.path.join(archive_path, 'debug.tgz')
  cmd = ['sudo', 'tar', 'czf', debug_tgz,
         '--checkpoint=10000', '--exclude', 'debug/usr/local/autotest',
         '--exclude', 'debug/tests', 'debug']
  tar_cmd = cros_lib.RunCommand(cmd, cwd=board_dir, error_ok=True,
                                exit_code=True)

  # Emerging the factory kernel while this is running installs different debug
  # symbols. When tar spots this, it flags this and returns status code 1.
  # The tarball is still OK, although the kernel debug symbols might be garbled.
  # If tar fails in a different way, it'll return an error code other than 1.
  # TODO(davidjames): Remove factory kernel emerge from archive_build.
  if tar_cmd.returncode not in (0, 1):
    raise Exception('%r failed with exit code %s' % (cmd, tar_cmd.returncode))

  # Fix permissions and ownership on debug tarball.
  cros_lib.RunCommand(['sudo', 'chown', str(os.getuid()), debug_tgz])
  os.chmod(debug_tgz, 0644)

  return debug_tgz


def UploadDebugTarball(debug_tgz, upload_url, debug):
  """Upload the debug tarball from the archive dir to Google Storage.

  Args:
    debug_tgz: Path to debug tarball in archive dir.
    upload_url: Location where tarball should be uploaded.
    debug: Whether we are in debug mode.
  """

  if upload_url and not debug:
    debug_tgz_url = '%s/%s' % (upload_url, 'debug.tgz')
    cros_lib.RunCommand([_GSUTIL_PATH,
                         'cp',
                         debug_tgz,
                         debug_tgz_url])
    cros_lib.RunCommand([_GSUTIL_PATH,
                         'setacl',
                         _GS_ACL,
                         debug_tgz_url])


def UploadSymbols(buildroot, board, official):
  """Upload debug symbols for this build."""
  cmd = ['./upload_symbols',
        '--board=%s' % board,
        '--yes',
        '--verbose']

  if official:
    cmd += ['--official_build']

  cwd = os.path.join(buildroot, 'src', 'scripts')

  cros_lib.RunCommand(cmd, cwd=cwd, error_ok=True, enter_chroot=True)


def PushImages(buildroot, board, branch_name, archive_dir):
  """Push the generated image to http://chromeos_images."""
  cmd = ['./pushimage',
        '--board=%s' % board,
        '--branch=%s' % branch_name,
        archive_dir]

  cros_lib.RunCommand(cmd, cwd=os.path.join(buildroot, 'crostools'))
