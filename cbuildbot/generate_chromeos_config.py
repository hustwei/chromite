# Copyright (c) 2012 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Configuration options for various cbuildbot builders."""

# pylint: disable=bad-continuation

from __future__ import print_function

import copy
import json

from chromite.cbuildbot import config_lib
from chromite.cbuildbot import constants


# Enumeration of valid settings; any/all config settings must be in this.
# All settings must be documented.
_settings = dict(
    # The name of the config.
    name=None,

    # A list of boards to build.
    boards=None,

    # The profile of the variant to set up and build.
    profile=None,

    # This bot pushes changes to the overlays.
    master=False,

    # If False, this flag indicates that the CQ should not check whether
    # this bot passed or failed. Set this to False if you are setting up a
    # new bot. Once the bot is on the waterfall and is consistently green,
    # mark the builder as important=True.
    important=False,

    # An integer. If this builder fails this many times consecutively, send
    # an alert email to the recipients health_alert_recipients. This does
    # not apply to tryjobs. This feature is similar to the ERROR_WATERMARK
    # feature of upload_symbols, and it may make sense to merge the features
    # at some point.
    health_threshold=0,

    # List of email addresses to send health alerts to for this builder. It
    # supports automatic email address lookup for the following sheriff
    # types:
    #     'tree': tree sheriffs
    #     'chrome': chrome gardeners
    health_alert_recipients=[],

    # Whether this is an internal build config.
    internal=False,

    # Whether this is a branched build config. Used for pfq logic.
    branch=False,

    # The name of the manifest to use. E.g., to use the buildtools manifest,
    # specify 'buildtools'.
    manifest=constants.DEFAULT_MANIFEST,

    # The name of the manifest to use if we're building on a local trybot.
    # This should only require elevated access if it's really needed to
    # build this config.
    dev_manifest=constants.DEFAULT_MANIFEST,

    # Applies only to paladin builders. If true, Sync to the manifest
    # without applying any test patches, then do a fresh build in a new
    # chroot. Then, apply the patches and build in the existing chroot.
    build_before_patching=False,

    # Applies only to paladin builders. If True, Sync to the master manifest
    # without applying any of the test patches, rather than running
    # CommitQueueSync. This is basically ToT immediately prior to the
    # current commit queue run.
    do_not_apply_cq_patches=False,

    # Applies only to master builders. List of the names of slave builders
    # to be treated as sanity checkers. If only sanity check builders fail,
    # then the master will ignore the failures. In a CQ run, if any of the
    # sanity check builders fail and other builders fail as well, the master
    # will treat the build as failed, but will not reset the ready bit of
    # the tested patches.
    sanity_check_slaves=None,

    # emerge use flags to use while setting up the board, building packages,
    # making images, etc.
    useflags=[],

    # Set the variable CHROMEOS_OFFICIAL for the build. Known to affect
    # parallel_emerge, cros_set_lsb_release, and chromeos_version.sh. See
    # bug chromium-os:14649
    chromeos_official=False,

    # Use binary packages for building the toolchain. (emerge --getbinpkg)
    usepkg_toolchain=True,

    # Use binary packages for build_packages and setup_board.
    usepkg_build_packages=True,

    # If set, run BuildPackages in the background and allow subsequent
    # stages to run in parallel with this one.
    #
    # For each release group, the first builder should be set to run in the
    # foreground (to build binary packages), and the remainder of the
    # builders should be set to run in parallel (to install the binary
    # packages.)
    build_packages_in_background=False,

    # Only use binaries in build_packages for Chrome itself.
    chrome_binhost_only=False,

    # Does this profile need to sync chrome?  If None, we guess based on
    # other factors.  If True/False, we always do that.
    sync_chrome=None,

    # Use the newest ebuilds for all the toolchain packages.
    latest_toolchain=False,

    # This is only valid when latest_toolchain is True. If you set this to a
    # commit-ish, the gcc ebuild will use it to build the toolchain
    # compiler.
    gcc_githash=None,

    # Wipe and replace the board inside the chroot.
    board_replace=False,

    # Wipe and replace chroot, but not source.
    chroot_replace=False,

    # Uprevs the local ebuilds to build new changes since last stable.
    # build.  If master then also pushes these changes on success. Note that
    # we uprev on just about every bot config because it gives us a more
    # deterministic build system (the tradeoff being that some bots build
    # from source more frequently than if they never did an uprev). This way
    # the release/factory/etc... builders will pick up changes that devs
    # pushed before it runs, but after the correspoding PFQ bot ran (which
    # is what creates+uploads binpkgs).  The incremental bots are about the
    # only ones that don't uprev because they mimic the flow a developer
    # goes through on their own local systems.
    uprev=True,

    # Select what overlays to look at for revving and prebuilts. This can be
    # any constants.VALID_OVERLAYS.
    overlays=constants.PUBLIC_OVERLAYS,

    # Select what overlays to push at. This should be a subset of overlays
    # for the particular builder.  Must be None if not a master.  There
    # should only be one master bot pushing changes to each overlay per
    # branch.
    push_overlays=None,

    # Uprev Chrome, values of 'tot', 'stable_release', or None.
    chrome_rev=None,

    # Exit the builder right after checking compilation.
    # TODO(mtennant): Should be something like "compile_check_only".
    compilecheck=False,

    # Test CLs to verify they're ready for the commit queue.
    pre_cq=False,

    # Runs the tests that the signer would run. This should only be set if
    # 'recovery' is in images.
    signer_tests=False,

    # Runs unittests for packages.
    unittests=True,

    # If unittests is true, only run the unit tests for packages which have
    # changed since the previous build.
    quick_unit=False,

    # A list of the packages to blacklist from unittests.
    unittest_blacklist=[],

    # Builds autotest tests.  Must be True if vm_tests is set.
    build_tests=True,

    # Generates AFDO data. Will capture a profile of chrome using a hwtest
    # to run a predetermined set of benchmarks.
    afdo_generate=False,

    # Generates AFDO data, builds the minimum amount of artifacts and
    # assumes a non-distributed builder (i.e.: the whole process in a single
    # builder).
    afdo_generate_min=False,

    # Update the Chrome ebuild with the AFDO profile info.
    afdo_update_ebuild=False,

    # Uses AFDO data. The Chrome build will be optimized using the AFDO
    # profile information found in the chrome ebuild file.
    afdo_use=False,

    # A list of vm tests to run.
    vm_tests=[constants.SMOKE_SUITE_TEST_TYPE,
            constants.SIMPLE_AU_TEST_TYPE],

    # The number of times to run the VMTest stage. If this is >1, then we
    # will run the stage this many times, stopping if we encounter any
    # failures.
    vm_test_runs=1,

    # A list of HWTestConfig objects to run.
    hw_tests=[],

    # If true, uploads artifacts for hw testing. Upload payloads for test
    # image if the image is built. If not, dev image is used and then base
    # image.
    upload_hw_test_artifacts=True,

    # If true, uploads individual image tarballs.
    upload_standalone_images=True,

    # Google Storage path to offload files to.
    #   None - No upload
    #   GS_PATH_DEFAULT - 'gs://chromeos-image-archive/' + bot_id
    #   value - Upload to explicit path
    gs_path=config_lib.GS_PATH_DEFAULT,

    # TODO(sosa): Deprecate binary.
    # Type of builder.  Check constants.VALID_BUILD_TYPES.
    build_type=constants.PFQ_TYPE,

    # The class name used to build this config.  See the modules in
    # cbuildbot / builders/*_builders.py for possible values.  This should
    # be the name in string form -- e.g. "simple_builders.SimpleBuilder" to
    # get the SimpleBuilder class in the simple_builders module.  If not
    # specified, we'll fallback to legacy probing behavior until everyone
    # has been converted (see the scripts/cbuildbot.py file for details).
    builder_class_name=None,

    # Whether the tests for the board we are building can be run on the
    # builder. Normally, we wouldn't be able to run unit and VM tests form
    # non-x86 boards.
    tests_supported=True,

    # List of images we want to build -- see build_image for more details.
    images=['test'],

    # Image from which we will build update payloads.  Must either be None
    # or name one of the images in the 'images' list, above.
    payload_image=None,

    # Whether to build a netboot image.
    factory_install_netboot=True,

    # Whether to build the factory toolkit.
    factory_toolkit=True,

    # Whether to build factory packages in BuildPackages.
    factory=True,

    # Tuple of specific packages we want to build.  Most configs won't
    # specify anything here and instead let build_packages calculate.
    packages=[],

    # Do we push a final release image to chromeos-images.
    push_image=False,

    # Do we upload debug symbols.
    upload_symbols=False,

    # Whether we upload a hwqual tarball.
    hwqual=False,

    # Run a stage that generates release payloads for signed images.
    paygen=False,

    # If the paygen stage runs, generate tests, and schedule auto-tests for
    # them.
    paygen_skip_testing=False,

    # If the paygen stage runs, don't generate any delta payloads. This is
    # only done if deltas are broken for a given board.
    paygen_skip_delta_payloads=False,

    # Run a stage that generates and uploads package CPE information.
    cpe_export=True,

    # Run a stage that generates and uploads debug symbols.
    debug_symbols=True,

    # Do not package the debug symbols in the binary package. The debug
    # symbols will be in an archive with the name cpv.debug.tbz2 in
    # /build/${BOARD}/packages and uploaded with the prebuilt.
    separate_debug_symbols=True,

    # Include *.debug files for debugging core files with gdb in debug.tgz.
    # These are very large. This option only has an effect if debug_symbols
    # and archive are set.
    archive_build_debug=False,

    # Run a stage that archives build and test artifacts for developer
    # consumption.
    archive=True,

    # git repository URL for our manifests.
    #  https://chromium.googlesource.com/chromiumos/manifest
    #  https://chrome-internal.googlesource.com/chromeos/manifest-internal
    manifest_repo_url=constants.MANIFEST_URL,

    # Whether we are using the manifest_version repo that stores per-build
    # manifests.
    manifest_version=False,

    # Use the Last Known Good Manifest blessed by Paladin.
    use_lkgm=False,

    # If we use_lkgm -- What is the name of the manifest to look for?
    lkgm_manifest=constants.LKGM_MANIFEST,

    # LKGM for Chrome OS generated for Chrome builds that are blessed from
    # canary runs.
    use_chrome_lkgm=False,

    # True if this build config is critical for the chrome_lkgm decision.
    critical_for_chrome=False,

    # Upload prebuilts for this build. Valid values are PUBLIC, PRIVATE, or
    # False.
    prebuilts=False,

    # Use SDK as opposed to building the chroot from source.
    use_sdk=True,

    # List this config when user runs cbuildbot with --list option without
    # the --all flag.
    trybot_list=False,

    # The description string to print out for config when user runs --list.
    description=None,

    # Boolean that enables parameter --git-sync for upload_prebuilts.
    git_sync=False,

    # A list of the child config groups, if applicable. See the AddGroup
    # method.
    child_configs=[],

    # Set shared user password for "chronos" user in built images. Use
    # "None" (default) to remove the shared user password. Note that test
    # images will always set the password to "test0000".
    shared_user_password=None,

    # Whether this config belongs to a config group.
    grouped=False,

    # layout of build_image resulting image. See
    # scripts/build_library/legacy_disk_layout.json or
    # overlay-<board>/scripts/disk_layout.json for possible values.
    disk_layout=None,

    # If enabled, run the PatchChanges stage.  Enabled by default. Can be
    # overridden by the --nopatch flag.
    postsync_patch=True,

    # Reexec into the buildroot after syncing.  Enabled by default.
    postsync_reexec=True,

    # Create delta sysroot during ArchiveStage. Disabled by default.
    create_delta_sysroot=False,

    # Run the binhost_test stage. Only makes sense for builders that have no
    # boards.
    binhost_test=False,

    # TODO(sosa): Collapse to one option.
    # ========== Dev installer prebuilts options =======================

    # Upload prebuilts for this build to this bucket. If it equals None the
    # default buckets are used.
    binhost_bucket=None,

    # Parameter --key for upload_prebuilts. If it equals None, the default
    # values are used, which depend on the build type.
    binhost_key=None,

    # Parameter --binhost-base-url for upload_prebuilts. If it equals None,
    # the default value is used.
    binhost_base_url=None,

    # Upload dev installer prebuilts.
    dev_installer_prebuilts=False,

    # Enable rootfs verification on the image.
    rootfs_verification=True,

    # Build the Chrome SDK.
    chrome_sdk=False,

    # If chrome_sdk is set to True, this determines whether we attempt to
    # build Chrome itself with the generated SDK.
    chrome_sdk_build_chrome=True,

    # If chrome_sdk is set to True, this determines whether we use goma to
    # build chrome.
    chrome_sdk_goma=False,

    # Run image tests. This should only be set if 'base' is in our list of
    # images.
    image_test=False,

    # ==================================================================
    # The documentation associated with the config.
    doc=None,

    # ==================================================================
    # Hints to Buildbot master UI

    # If set, tells buildbot what name to give to the corresponding builder
    # on its waterfall.
    buildbot_waterfall_name=None,

    # If not None, the name (in constants.CIDB_KNOWN_WATERFALLS) of the
    # waterfall that this target should be active on.
    active_waterfall=None,
)


# Set to 'True' if this is a release branch.
IS_RELEASE_BRANCH = True


_CONFIG = config_lib.Config(defaults=_settings)

def GetConfig():
  """Get the full build configuration."""
  return _CONFIG


def OverrideConfigForTrybot(build_config, options):
  """Apply trybot-specific configuration settings.

  Args:
    build_config: The build configuration dictionary to override.
      The dictionary is not modified.
    options: The options passed on the commandline.

  Returns:
    A build configuration dictionary with the overrides applied.
  """
  copy_config = copy.deepcopy(build_config)
  for my_config in [copy_config] + copy_config['child_configs']:
    # For all builds except PROJECT_SDK, force uprev. This is so patched in
    # changes are always built. PROEJCT_SDK_TYPE uses a minilayout, and uprev
    # doesn't work for minilayout (crbug.com/458661).
    if my_config['build_type'] != constants.PROJECT_SDK_TYPE:
      my_config['uprev'] = True
      if my_config['internal']:
        my_config['overlays'] = constants.BOTH_OVERLAYS

    # Most users don't have access to the internal repositories so disable
    # them so that we use the external chromium prebuilts.
    useflags = my_config['useflags']
    if not options.remote_trybot and useflags:
      for chrome_use in official_chrome['useflags']:
        if chrome_use in useflags:
          useflags.remove(chrome_use)

    # Use the local manifest which only requires elevated access if it's really
    # needed to build.
    if not options.remote_trybot:
      my_config['manifest'] = my_config['dev_manifest']

    my_config['push_image'] = False

    if my_config['build_type'] != constants.PAYLOADS_TYPE:
      my_config['paygen'] = False

    if options.hwtest:
      if not my_config['hw_tests']:
        my_config['hw_tests'] = HWTestDefaultList(
            num=constants.HWTEST_TRYBOT_NUM, pool=constants.HWTEST_TRYBOT_POOL,
            file_bugs=False)
      else:
        for hw_config in my_config['hw_tests']:
          hw_config.num = constants.HWTEST_TRYBOT_NUM
          hw_config.pool = constants.HWTEST_TRYBOT_POOL
          hw_config.file_bugs = False
          hw_config.priority = constants.HWTEST_DEFAULT_PRIORITY
      # TODO: Fix full_release_test.py/AUTest on trybots, crbug.com/390828.
      my_config['hw_tests'] = [hw_config for hw_config in my_config['hw_tests']
                               if hw_config.suite != constants.HWTEST_AU_SUITE]

    # Default to starting with a fresh chroot on remote trybot runs.
    if options.remote_trybot:
      my_config['chroot_replace'] = True

    # In trybots, we want to always run VM tests and all unit tests, so that
    # developers will get better testing for their changes.
    if (my_config['build_type'] == constants.PALADIN_TYPE and
        my_config['tests_supported'] and
        all(x not in _arm_boards for x in my_config['boards']) and
        all(x not in _brillo_boards for x in my_config['boards'])):
      my_config['vm_tests'] = [constants.SMOKE_SUITE_TEST_TYPE,
                               constants.SIMPLE_AU_TEST_TYPE,
                               constants.CROS_VM_TEST_TYPE]
      my_config['quick_unit'] = False

  return copy_config


def GetDefaultWaterfall(build_config):
  if not (build_config['important'] or build_config['master']):
    return None
  if build_config['branch']:
    return None
  b_type = build_config['build_type']

  if config_lib.IsCanaryType(b_type):
    # If this is a canary build, it may fall on different waterfalls:
    # - If we're building for a release branch, it belongs on a release
    #   waterfall.
    # - Otherwise, it belongs on the internal waterfall.
    if IS_RELEASE_BRANCH:
      return constants.WATERFALL_RELEASE
    else:
      return constants.WATERFALL_INTERNAL
  elif config_lib.IsCQType(b_type):
    # A Paladin can appear on the public or internal waterfall depending on its
    # 'internal' status.
    return (constants.WATERFALL_INTERNAL if build_config['internal'] else
            constants.WATERFALL_EXTERNAL)
  elif config_lib.IsPFQType(b_type) or b_type == constants.PRE_CQ_LAUNCHER_TYPE:
    # These builder types belong on the internal waterfall.
    return constants.WATERFALL_INTERNAL
  else:
    # No default active waterfall.
    return None


# pylint: disable=W0102
def GetCanariesForChromeLKGM(configs=GetConfig()):
  """Grabs a list of builders that are important for the Chrome LKGM."""
  builders = []
  for build_name, conf in configs.iteritems():
    if (conf['build_type'] == constants.CANARY_TYPE and
        conf['critical_for_chrome'] and not conf['child_configs']):
      builders.append(build_name)

  return builders


def FindFullConfigsForBoard(board=None):
  """Returns full builder configs for a board.

  Args:
    board: The board to match. By default, match all boards.

  Returns:
    A tuple containing a list of matching external configs and a list of
    matching internal release configs for a board.
  """
  ext_cfgs = []
  int_cfgs = []

  for name, c in GetConfig().iteritems():
    if c['boards'] and (board is None or board in c['boards']):
      if (name.endswith('-%s' % config_lib.CONFIG_TYPE_RELEASE) and
          c['internal']):
        int_cfgs.append(c.deepcopy())
      elif (name.endswith('-%s' % config_lib.CONFIG_TYPE_FULL) and
            not c['internal']):
        ext_cfgs.append(c.deepcopy())

  return ext_cfgs, int_cfgs


def FindCanonicalConfigForBoard(board):
  """Get the canonical cbuildbot builder config for a board."""
  ext_cfgs, int_cfgs = FindFullConfigsForBoard(board)
  # If both external and internal builds exist for this board, prefer the
  # internal one.
  both = int_cfgs + ext_cfgs
  if not both:
    raise ValueError('Invalid board specified: %s.' % board)
  return both[0]


def GetSlavesForMaster(master_config, options=None):
  """Gets the important slave builds corresponding to this master.

  A slave config is one that matches the master config in build_type,
  chrome_rev, and branch.  It also must be marked important.  For the
  full requirements see the logic in code below.

  The master itself is eligible to be a slave (of itself) if it has boards.

  Args:
    master_config: A build config for a master builder.
    options: The options passed on the commandline. This argument is optional,
             and only makes sense when called from cbuildbot.

  Returns:
    A list of build configs corresponding to the slaves for the master
      represented by master_config.

  Raises:
    AssertionError if the given config is not a master config or it does
      not have a manifest_version.
  """
  # This is confusing.  "config" really should be capitalized in this file.
  all_configs = GetConfig()

  assert master_config['manifest_version']
  assert master_config['master']

  slave_configs = []
  if options is not None and options.remote_trybot:
    return slave_configs

  # TODO(davidjames): In CIDB the master isn't considered a slave of itself, so
  # we probably shouldn't consider it a slave here either.
  for build_config in all_configs.itervalues():
    if (build_config['important'] and
        build_config['manifest_version'] and
        (not build_config['master'] or build_config['boards']) and
        build_config['build_type'] == master_config['build_type'] and
        build_config['chrome_rev'] == master_config['chrome_rev'] and
        build_config['branch'] == master_config['branch']):
      slave_configs.append(build_config)

  return slave_configs


class _JSONEncoder(json.JSONEncoder):
  """Json Encoder that encodes objects as their dictionaries."""
  # pylint: disable=E0202
  def default(self, obj):
    return self.encode(obj.__dict__)


def HWTestDefaultList(**kwargs):
  """Returns a default list of HWTestConfig's for a build

  Args:
    *kwargs: overrides for the configs
  """
  # Number of tests running in parallel in the AU suite.
  AU_TESTS_NUM = 2
  # Number of tests running in parallel in the asynchronous canary
  # test suite
  ASYNC_TEST_NUM = 2

  # Set the number of machines for the au and qav suites. If we are
  # constrained in the number of duts in the lab, only give 1 dut to each.
  if (kwargs.get('num', constants.HWTEST_DEFAULT_NUM) >=
      constants.HWTEST_DEFAULT_NUM):
    au_dict = dict(num=AU_TESTS_NUM)
    async_dict = dict(num=ASYNC_TEST_NUM)
  else:
    au_dict = dict(num=1)
    async_dict = dict(num=1)

  au_kwargs = kwargs.copy()
  au_kwargs.update(au_dict)

  async_kwargs = kwargs.copy()
  async_kwargs.update(async_dict)
  async_kwargs['priority'] = constants.HWTEST_POST_BUILD_PRIORITY
  async_kwargs['retry'] = False
  async_kwargs['max_retries'] = None
  async_kwargs['async'] = True
  async_kwargs['suite_min_duts'] = 1

  # BVT + AU suite.
  return [config_lib.HWTestConfig(constants.HWTEST_BVT_SUITE,
                                  blocking=True, **kwargs),
          config_lib.HWTestConfig(constants.HWTEST_AU_SUITE,
                                  blocking=True, **au_kwargs),
          config_lib.HWTestConfig(constants.HWTEST_COMMIT_SUITE,
                                  **async_kwargs),
          config_lib.HWTestConfig(constants.HWTEST_CANARY_SUITE,
                                  **async_kwargs)]


def HWTestDefaultListCanary(**kwargs):
  """Returns a default list of config_lib.HWTestConfig's for a canary build.

  Args:
    *kwargs: overrides for the configs
  """
  # Set minimum_duts default to 4, which means that lab will check the
  # number of available duts to meet the minimum requirement before creating
  # the suite job for canary builds.
  kwargs.setdefault('minimum_duts', 4)
  kwargs.setdefault('file_bugs', True)
  return HWTestDefaultList(**kwargs)


def HWTestAFDOList(**kwargs):
  """Returns a default list of HWTestConfig's for a AFDO build.

  Args:
    *kwargs: overrides for the configs
  """
  afdo_dict = dict(pool=constants.HWTEST_SUITES_POOL,
                   timeout=120 * 60, num=1, async=True, retry=False,
                   max_retries=None)
  afdo_dict.update(kwargs)
  return [config_lib.HWTestConfig('perf_v2', **afdo_dict)]


def HWTestDefaultListNonCanary(**kwargs):
  """Return a default list of HWTestConfig's for a non-canary build.

  Optional arguments may be overridden in `kwargs`, except that
  the `blocking` setting cannot be provided.
  """
  return [config_lib.HWTestConfig(constants.HWTEST_BVT_SUITE, **kwargs),
          config_lib.HWTestConfig(constants.HWTEST_COMMIT_SUITE, **kwargs)]


def HWTestDefaultListCQ(**kwargs):
  """Return a default list of HWTestConfig's for a CQ build.

  Optional arguments may be overridden in `kwargs`, except that
  the `blocking` setting cannot be provided.
  """
  default_dict = dict(pool=constants.HWTEST_PALADIN_POOL, timeout=120 * 60,
                      file_bugs=False, priority=constants.HWTEST_CQ_PRIORITY,
                      minimum_duts=4)
  # Allows kwargs overrides to default_dict for cq.
  default_dict.update(kwargs)
  return HWTestDefaultListNonCanary(**default_dict)


def HWTestDefaultListPFQ(**kwargs):
  """Return a default list of HWTestConfig's for a PFQ build.

  Optional arguments may be overridden in `kwargs`, except that
  the `blocking` setting cannot be provided.
  """
  default_dict = dict(pool=constants.HWTEST_PFQ_POOL, file_bugs=True,
                      priority=constants.HWTEST_PFQ_PRIORITY,
                      retry=False, max_retries=None, minimum_duts=4)
  # Allows kwargs overrides to default_dict for pfq.
  default_dict.update(kwargs)
  return HWTestDefaultListNonCanary(**default_dict)


def HWTestSharedPoolPFQ(**kwargs):
  """Return a list of HWTestConfigs for PFQ which uses a shared pool.

  The returned suites will run in pool:critical by default, which is
  shared with other types of builders (canaries, cq). The first suite in the
  list is a blocking sanity suite that verifies the build will not break dut.
  """
  sanity_dict = dict(pool=constants.HWTEST_MACH_POOL,
                     file_bugs=True, priority=constants.HWTEST_PFQ_PRIORITY,
                     retry=False, max_retries=None)
  sanity_dict.update(kwargs)
  sanity_dict.update(dict(num=1, minimum_duts=1, suite_min_duts=1,
                          blocking=True))
  default_dict = dict(pool=constants.HWTEST_MACH_POOL,
                      suite_min_duts=3)
  default_dict.update(kwargs)
  suite_list = [config_lib.HWTestConfig(constants.HWTEST_SANITY_SUITE,
                                        **sanity_dict)]
  suite_list.extend(HWTestDefaultListPFQ(**default_dict))
  return suite_list


def HWTestSharedPoolCQ(**kwargs):
  """Return a list of HWTestConfigs for CQ which uses a shared pool.

  The returned suites will run in pool:critical by default, which is
  shared with other types of builder (canaries, pfq). The first suite in the
  list is a blocking sanity suite that verifies the build will not break dut.
  """
  sanity_dict = dict(pool=constants.HWTEST_MACH_POOL, timeout=120 * 60,
                     file_bugs=False, priority=constants.HWTEST_CQ_PRIORITY)
  sanity_dict.update(kwargs)
  sanity_dict.update(dict(num=1, minimum_duts=1, suite_min_duts=1,
                          blocking=True))
  default_dict = dict(pool=constants.HWTEST_MACH_POOL,
                      suite_min_duts=10)
  default_dict.update(kwargs)
  suite_list = [config_lib.HWTestConfig(constants.HWTEST_SANITY_SUITE,
                                        **sanity_dict)]
  suite_list.extend(HWTestDefaultListCQ(**default_dict))
  return suite_list


def HWTestSharedPoolCanary(**kwargs):
  """Return a list of HWTestConfigs for Canary which uses a shared pool.

  The returned suites will run in pool:critical by default, which is
  shared with CQs. The first suite in the list is a blocking sanity suite
  that verifies the build will not break dut.
  """
  sanity_dict = dict(pool=constants.HWTEST_MACH_POOL, file_bugs=True)
  sanity_dict.update(kwargs)
  sanity_dict.update(dict(num=1, minimum_duts=1, suite_min_duts=1,
                          blocking=True))
  default_dict = dict(pool=constants.HWTEST_MACH_POOL,
                      suite_min_duts=6)
  default_dict.update(kwargs)
  suite_list = [config_lib.HWTestConfig(constants.HWTEST_SANITY_SUITE,
                                        **sanity_dict)]
  suite_list.extend(HWTestDefaultListCanary(**default_dict))
  return suite_list


def HWTestAFDORecordTest(**kwargs):
  default_dict = dict(pool=constants.HWTEST_SUITES_POOL,
                      warn_only=True, num=1, file_bugs=True,
                      timeout=constants.AFDO_GENERATE_TIMEOUT)
  # Allows kwargs overrides to default_dict for cq.
  default_dict.update(kwargs)
  return config_lib.HWTestConfig(constants.HWTEST_AFDO_SUITE, **default_dict)


def append_useflags(useflags):
  """Used to append a set of useflags to existing useflags.

  Useflags that shadow prior use flags will cause the prior flag to be removed.
  (e.g. appending '-foo' to 'foo' will cause 'foo' to be removed)

  Usage:
    new_config = base_config.derive(useflags=append_useflags(['foo', '-bar'])

  Args:
    useflags: List of string useflags to append.
  """
  assert isinstance(useflags, (list, set))
  shadowed_useflags = {'-' + flag for flag in useflags
                       if not flag.startswith('-')}
  shadowed_useflags.update({flag[1:] for flag in useflags
                            if flag.startswith('-')})
  def handler(old_useflags):
    new_useflags = set(old_useflags or [])
    new_useflags.update(useflags)
    new_useflags.difference_update(shadowed_useflags)
    return sorted(list(new_useflags))

  return handler


# Arch-specific mixins.

# Config parameters for builders that do not run tests on the builder. Anything
# non-x86 tests will fall under this category.
non_testable_builder = config_lib.BuildConfig(
  tests_supported=False,
  unittests=False,
  vm_tests=[],
)


# Builder-specific mixins

binary = config_lib.BuildConfig(
  # Full builds that build fully from binaries.
  build_type=constants.BUILD_FROM_SOURCE_TYPE,
  archive_build_debug=True,
  images=['test', 'factory_install'],
  git_sync=True,
)

full = config_lib.BuildConfig(
  # Full builds are test builds to show that we can build from scratch,
  # so use settings to build from scratch, and archive the results.

  usepkg_build_packages=False,
  chrome_sdk=True,
  chroot_replace=True,

  build_type=constants.BUILD_FROM_SOURCE_TYPE,
  archive_build_debug=True,
  images=['base', 'recovery', 'test', 'factory_install'],
  git_sync=True,
  trybot_list=True,
  description='Full Builds',
  image_test=True,
  doc='http://www.chromium.org/chromium-os/build/builder-overview#'
      'TOC-Continuous',
)

# Full builders with prebuilts.
full_prebuilts = full.derive(
  prebuilts=constants.PUBLIC,
)

pfq = config_lib.BuildConfig(
  build_type=constants.PFQ_TYPE,
  important=True,
  uprev=True,
  overlays=constants.PUBLIC_OVERLAYS,
  manifest_version=True,
  trybot_list=True,
  doc='http://www.chromium.org/chromium-os/build/builder-overview#'
      'TOC-Chrome-PFQ',
)

paladin = config_lib.BuildConfig(
  important=True,
  build_type=constants.PALADIN_TYPE,
  overlays=constants.PUBLIC_OVERLAYS,
  prebuilts=constants.PUBLIC,
  manifest_version=True,
  trybot_list=True,
  description='Commit Queue',
  upload_standalone_images=False,
  images=['test'],
  chrome_sdk=True,
  chrome_sdk_build_chrome=False,
  doc='http://www.chromium.org/chromium-os/build/builder-overview#TOC-CQ',
)

# Incremental builders are intended to test the developer workflow.
# For that reason, they don't uprev.
incremental = config_lib.BuildConfig(
  build_type=constants.INCREMENTAL_TYPE,
  uprev=False,
  overlays=constants.PUBLIC_OVERLAYS,
  description='Incremental Builds',
  doc='http://www.chromium.org/chromium-os/build/builder-overview#'
      'TOC-Continuous',
)

# This builds with more source available.
internal = config_lib.BuildConfig(
  internal=True,
  overlays=constants.BOTH_OVERLAYS,
  manifest_repo_url=constants.MANIFEST_INT_URL,
)

brillo = config_lib.BuildConfig(
  sync_chrome=False,
  chrome_sdk=False,
  afdo_use=False,
  dev_installer_prebuilts=False,
  # TODO(gauravsh): crbug.com/356414 Start running tests on Brillo configs.
  vm_tests=[],
  hw_tests=[],
)

moblab = config_lib.BuildConfig(
  vm_tests=[],
)

# Builds for the Project SDK.
project_sdk = config_lib.BuildConfig(
  build_type=constants.PROJECT_SDK_TYPE,
  description='Produce Project SDK build artifacts.',

  # These are test builds, they shouldn't break anything (yet).
  important=False,

  usepkg_build_packages=False,
  sync_chrome=False,
  chrome_sdk=False,
  uprev=False,

  # Proper manifest for TOT builds. Not used, outside of tryjobs.
  manifest=constants.PROJECT_MANIFEST,

  # Use the SDK manifest published by the Canary master for most builds.
  lkgm_manifest=constants.LATEST_PROJECT_SDK_MANIFEST,
  use_lkgm=True,

  # Tests probably don't work yet.
  vm_tests=[],
  hw_tests=[],

  # Factory stuff not needed here.
  factory_install_netboot=False,
  factory_toolkit=False,
  factory=False,
)

_project_sdk_boards = frozenset([
    'panther_embedded',
    'gizmo',
])

beaglebone = brillo.derive(non_testable_builder, rootfs_verification=False)

# This adds Chrome branding.
official_chrome = config_lib.BuildConfig(
  useflags=[constants.USE_CHROME_INTERNAL],
)

# This sets chromeos_official.
official = official_chrome.derive(
  chromeos_official=True,
)

_cros_sdk = _CONFIG.AddConfig(full_prebuilts, 'chromiumos-sdk',
  # The amd64-host has to be last as that is when the toolchains
  # are bundled up for inclusion in the sdk.
  boards=['x86-generic', 'arm-generic', 'amd64-generic', 'mipsel-o32-generic'],
  build_type=constants.CHROOT_BUILDER_TYPE,
  builder_class_name='sdk_builders.ChrootSdkBuilder',
  use_sdk=False,
  trybot_list=True,
  description='Build the SDK and all the cross-compilers',
  doc='http://www.chromium.org/chromium-os/build/builder-overview#'
      'TOC-Continuous',
)

asan = config_lib.BuildConfig(
  chroot_replace=True,
  profile='asan',
  disk_layout='2gb-rootfs',
  # TODO(deymo): ASan builders generate bigger files, in particular a bigger
  # Chrome binary, that update_engine can't handle in delta payloads due to
  # memory limits. Remove the following line once crbug.com/329248 is fixed.
  vm_tests=[constants.SMOKE_SUITE_TEST_TYPE],
  doc='http://www.chromium.org/chromium-os/build/builder-overview#'
      'TOC-ChromiumOS-SDK',
)

telemetry = config_lib.BuildConfig(
  build_type=constants.INCREMENTAL_TYPE,
  uprev=False,
  overlays=constants.PUBLIC_OVERLAYS,
  vm_tests=[constants.TELEMETRY_SUITE_TEST_TYPE],
  description='Telemetry Builds',
)

chromium_pfq = config_lib.BuildConfig(
  build_type=constants.CHROME_PFQ_TYPE,
  important=True,
  uprev=False,
  overlays=constants.PUBLIC_OVERLAYS,
  manifest_version=True,
  chrome_rev=constants.CHROME_REV_LATEST,
  chrome_sdk=True,
  chroot_replace=True,
  description='Preflight Chromium Uprev & Build (public)',
)

# TODO(davidjames): Convert this to an external config once the unified master
# logic is ready.
internal_chromium_pfq = internal.derive(
  chromium_pfq,
  description='Preflight Chromium Uprev & Build (internal)',
  overlays=constants.BOTH_OVERLAYS,
  prebuilts=constants.PUBLIC,
)

_CONFIG.AddConfig(internal_chromium_pfq, 'master-chromium-pfq',
  boards=[],
  master=True,
  binhost_test=True,
  push_overlays=constants.BOTH_OVERLAYS,
  afdo_update_ebuild=True,
  chrome_sdk=False,
)

chrome_pfq = internal_chromium_pfq.derive(
  official,
  important=True,
  overlays=constants.BOTH_OVERLAYS,
  description='Preflight Chrome Uprev & Build (internal)',
  prebuilts=constants.PRIVATE,
)

chrome_try = config_lib.BuildConfig(
  build_type=constants.CHROME_PFQ_TYPE,
  chrome_rev=constants.CHROME_REV_TOT,
  use_lkgm=True,
  important=False,
  manifest_version=False,
)

chromium_info = chromium_pfq.derive(
  chrome_try,
  vm_tests=[constants.SMOKE_SUITE_TEST_TYPE],
  chrome_sdk=False,
  description='Informational Chromium Uprev & Build (public)',
)

telemetry_info = telemetry.derive(
  chrome_try,
)

chrome_info = chromium_info.derive(
  internal, official,
  description='Informational Chrome Uprev & Build (internal)',
)

chrome_perf = chrome_info.derive(
  description='Chrome Performance test bot',
  vm_tests=[],
  unittests=False,
  hw_tests=[config_lib.HWTestConfig(
      'perf_v2', pool=constants.HWTEST_CHROME_PERF_POOL,
      timeout=90 * 60, critical=True, num=1)],
  use_chrome_lkgm=True,
  use_lkgm=False,
  useflags=append_useflags(['-cros-debug']),
)

# Base per-board configuration.
# Every board must appear in exactly 1 of the following sets.

_arm_internal_release_boards = frozenset([
  'beaglebone',
  'beaglebone_servo',
  'cosmos',
  'daisy',
  'daisy_skate',
  'daisy_spring',
  'daisy_winter',
  'kayle',
  'nyan',
  'nyan_big',
  'nyan_blaze',
  'nyan_freon',
  'nyan_kitty',
  'oak',
  'peach_pi',
  'peach_pit',
  'purin',
  'smaug',
  'storm',
  'rush',
  'rush_ryu',
  'veyron_brain',
  'veyron_danger',
  'veyron_gus',
  'veyron_jaq',
  'veyron_jerry',
  'veyron_mighty',
  'veyron_minnie',
  'veyron_pinky',
  'veyron_rialto',
  'veyron_speedy',
  'veyron_thea',
  'whirlwind',
])

_arm_external_boards = frozenset([
  'arm-generic',
  'arm-generic_freon',
  'arm64-generic',
])

_x86_internal_release_boards = frozenset([
  'auron',
  'auron_paine',
  'auron_yuna',
  'bayleybay',
  'banjo',
  'beltino',
  'bobcat',
  'butterfly',
  'butterfly_freon',
  'candy',
  'cid',
  'clapper',
  'cranky',
  'cyan',
  'enguarde',
  'expresso',
  'falco',
  'falco_li',
  'gandof',
  'glimmer',
  'gnawty',
  'guado',
  'jecht',
  'kip',
  'lakitu',
  'leon',
  'link',
  'lulu',
  'lumpy',
  'lumpy_freon',
  'mccloud',
  'monroe',
  'ninja',
  'orco',
  'panther',
  'panther_embedded',
  'panther_moblab',
  'parrot',
  'parrot_freon',
  'parrot_ivb',
  'parry',
  'peppy',
  'quawks',
  'quawks_freon',
  'rambi',
  'rikku',
  'samus',
  'slippy',
  'squawks',
  'stout',
  'stout_freon',
  'strago',
  'stumpy',
  'stumpy_freon',
  'stumpy_moblab',
  'sumo',
  'swanky',
  'tidus',
  'tricky',
  'winky',
  'wolf',
  'x86-alex',
  'x86-alex_freon',
  'x86-alex_he',
  'x86-alex_he-freon',
  'x86-mario',
  'x86-mario_freon',
  'x86-zgb',
  'x86-zgb_freon',
  'x86-zgb_he',
  'x86-zgb_he-freon',
  'zako',
])

_x86_external_boards = frozenset([
  'amd64-generic',
  'amd64-generic_freon',
  'gizmo',
  'x32-generic',
  'x86-generic',
])

_mips_internal_release_boards = frozenset([
])

_mips_external_boards = frozenset([
  'mipseb-n32-generic',
  'mipseb-n64-generic',
  'mipseb-o32-generic',
  'mipsel-n32-generic',
  'mipsel-n64-generic',
  'mipsel-o32-generic',
])

# Every board should be in only 1 of the above sets.
_distinct_board_sets = [
    _arm_internal_release_boards,
    _arm_external_boards,
    _x86_internal_release_boards,
    _x86_external_boards,
    _mips_internal_release_boards,
    _mips_external_boards,
]

_arm_full_boards = (_arm_internal_release_boards |
                    _arm_external_boards)
_x86_full_boards = (_x86_internal_release_boards |
                    _x86_external_boards)
_mips_full_boards = (_mips_internal_release_boards |
                     _mips_external_boards)

_arm_boards = _arm_full_boards
_x86_boards = _x86_full_boards
_mips_boards = _mips_full_boards

_all_release_boards = (
    _arm_internal_release_boards |
    _x86_internal_release_boards |
    _mips_internal_release_boards
)
_all_full_boards = (
    _arm_full_boards |
    _x86_full_boards |
    _mips_full_boards
)
_all_boards = (
    _x86_boards |
    _arm_boards |
    _mips_boards
)

# Every board should be in exactly one of the distinct board sets.
def _EnforceDistinctSets():
  for board in _all_boards:
    found = False
    for s in _distinct_board_sets:
      if board in s:
        if found:
          assert False, '%s in multiple board sets.' % board
        else:
          found = True
    if not found:
      assert False, '%s in no board sets' % board
  for s in _distinct_board_sets:
    for board in s - _all_boards:
      assert False, '%s in _distinct_board_sets but not in _all_boards' % board

_EnforceDistinctSets()

_arm_release_boards = _arm_internal_release_boards
_x86_release_boards = _x86_internal_release_boards
_mips_release_boards = _mips_internal_release_boards

_internal_boards = _all_release_boards

# Board can appear in 1 or more of the following sets.
_brillo_boards = frozenset([
  'cosmos',
  'gizmo',
  'kayle',
  'lakitu',
  'panther_embedded',
  'purin',
  'storm',
  'whirlwind',
])

_moblab_boards = frozenset([
  'stumpy_moblab',
  'panther_moblab',
])

_minimal_profile_boards = frozenset([
  'bobcat',
])

_nofactory_boards = frozenset([
  'daisy_winter',
])

_toolchains_from_source = frozenset([
  'mipseb-n32-generic',
  'mipseb-n64-generic',
  'mipseb-o32-generic',
  'mipsel-n32-generic',
  'mipsel-n64-generic',
  'x32-generic',
])

_noimagetest_boards = frozenset([
    'lakitu',
])

_nohwqual_boards = frozenset([
    'lakitu',
])

_norootfs_verification_boards = frozenset([
    'lakitu',
])

_base_layout_boards = frozenset([
    'lakitu',
])

# A base config for each board.
_base_configs = dict()

def _CreateBaseConfigs():
  for board in _all_boards:
    base = config_lib.BuildConfig()
    if board in _internal_boards:
      base.update(internal)
      base.update(official_chrome)
      base.update(manifest=constants.OFFICIAL_MANIFEST)
    if board not in _x86_boards:
      base.update(non_testable_builder)
    if board in _brillo_boards:
      base.update(brillo)
    if board in _moblab_boards:
      base.update(moblab)
    if board in _minimal_profile_boards:
      base.update(profile='minimal')
    if board in _nofactory_boards:
      base.update(factory=False)
    if board in _toolchains_from_source:
      base.update(usepkg_toolchain=False)
    if board in _noimagetest_boards:
      base.update(image_test=False)
    if board in _nohwqual_boards:
      base.update(hwqual=False)
    if board in _norootfs_verification_boards:
      base.update(rootfs_verification=False)
    if board in _base_layout_boards:
      base.update(disk_layout='base')

    # TODO(akeshet) Eliminate or clean up this special case.
    # kayle board has a lot of kayle-specific config changes.
    if board == 'kayle':
      base.update(manifest='kayle.xml',
                  dev_manifest='kayle.xml',
                  factory_toolkit=False,
                  # TODO(namnguyen): Cannot build factory net install (no
                  # usbnet).
                  factory_install_netboot=False,
                  # TODO(namngyuyen) Cannot build dev or test images due to
                  # #436523.
                  images=['base'])

    board_config = base.derive(boards=[board])
    # Note: base configs should not specify a useflag list. Convert any useflags
    # that this base config has accrued (for instance, 'chrome_internal', via
    # official_chrome) into an append_useflags callable. This
    # is because the board base config is the last config to be derived from
    # when creating a board-specific config,
    if 'useflags' in board_config:
      board_config['useflags'] = append_useflags(board_config['useflags'])
    _base_configs[board] = board_config

_CreateBaseConfigs()

def _CreateConfigsForBoards(config_base, boards, name_suffix, **kwargs):
  """Create configs based on |config_base| for all boards in |boards|.

  Note: Existing configs will not be overwritten.

  Args:
    config_base: A BuildConfig instance to inherit from.
    boards: A set of boards to create configs for.
    name_suffix: A naming suffix. Configs will have names of the form
                 board-name_suffix.
    **kwargs: Additional keyword arguments to be used in AddConfig.
  """
  for board in boards:
    config_name = '%s-%s' % (board, name_suffix)
    if config_name not in _CONFIG:
      base = config_lib.BuildConfig()
      _CONFIG.AddConfig(config_base, config_name, base, _base_configs[board],
                         **kwargs)

_chromium_pfq_important_boards = frozenset([
  'arm-generic_freon',
  'arm-generic',
  'daisy',
  'mipsel-o32-generic',
  'x86-generic',
  ])

def _AddFullConfigs():
  """Add x86 and arm full configs."""
  external_overrides = config_lib.BuildConfig.delete_keys(internal)
  external_overrides.update(manifest=config_lib.BuildConfig.delete_key())
  external_overrides.update(
    useflags=append_useflags(['-%s' % constants.USE_CHROME_INTERNAL]))
  _CreateConfigsForBoards(full_prebuilts, _all_full_boards,
                          config_lib.CONFIG_TYPE_FULL,
                          **external_overrides)
  _CreateConfigsForBoards(chromium_info, _all_full_boards,
                          'tot-chromium-pfq-informational', important=False,
                          **external_overrides)
  # Create important configs, then non-important configs.
  _CreateConfigsForBoards(internal_chromium_pfq, _chromium_pfq_important_boards,
                          'chromium-pfq', **external_overrides)
  _CreateConfigsForBoards(internal_chromium_pfq, _all_full_boards,
                          'chromium-pfq', important=False,
                          **external_overrides)

_AddFullConfigs()


# These remaining chromium pfq configs have eccentricities that are easier to
# create manually.

_CONFIG.AddConfig(internal_chromium_pfq, 'amd64-generic-chromium-pfq',
  _base_configs['amd64-generic'],
  disk_layout='2gb-rootfs',
)

_CONFIG.AddConfig(internal_chromium_pfq, 'amd64-generic_freon-chromium-pfq',
  _base_configs['amd64-generic_freon'],
  disk_layout='2gb-rootfs',
  vm_tests=[],
)

_chrome_pfq_important_boards = frozenset([
  'peppy',
  'rush_ryu',
  'veyron_pinky',
  'x86-alex_freon',
  ])


# TODO(akeshet): Replace this with a config named x86-alex-chrome-pfq.
_CONFIG.AddConfig(chrome_pfq, 'alex-chrome-pfq',
  _base_configs['x86-alex'],
)

_CONFIG.AddConfig(chrome_pfq, 'lumpy-chrome-pfq',
  _base_configs['lumpy'],
  afdo_generate=True,
  hw_tests=[HWTestAFDORecordTest()] + HWTestSharedPoolPFQ(),
)

_CONFIG.AddConfig(chrome_pfq, 'daisy_skate-chrome-pfq',
  _base_configs['daisy_skate'],
  hw_tests=HWTestSharedPoolPFQ(),
)

_CONFIG.AddConfig(chrome_pfq, 'falco-chrome-pfq',
  _base_configs['falco'],
  hw_tests=HWTestSharedPoolPFQ(),
)

_CONFIG.AddConfig(chrome_pfq, 'peach_pit-chrome-pfq',
  _base_configs['peach_pit'],
  hw_tests=HWTestSharedPoolPFQ(),
  important=False,
)

_CONFIG.AddConfig(chrome_pfq, 'tricky-chrome-pfq',
  _base_configs['tricky'],
  hw_tests=HWTestSharedPoolPFQ(),
  important=False,
)

_telemetry_boards = frozenset([
    'amd64-generic',
    'arm-generic',
    'x86-generic',
])

_CreateConfigsForBoards(telemetry, _telemetry_boards, 'telemetry')

_toolchain_major = _CONFIG.AddConfig(_cros_sdk, 'toolchain-major',
  latest_toolchain=True,
  prebuilts=False,
  trybot_list=False,
  gcc_githash='svn-mirror/google/main',
  description='Test next major toolchain revision',
)

_toolchain_minor = _CONFIG.AddConfig(_cros_sdk, 'toolchain-minor',
  latest_toolchain=True,
  prebuilts=False,
  trybot_list=False,
  gcc_githash='svn-mirror/google/gcc-4_9',
  description='Test next minor toolchain revision',
)

_CONFIG.AddConfig(incremental, 'x86-generic-asan',
  asan,
  boards=['x86-generic'],
  description='Build with Address Sanitizer (Clang)',
  trybot_list=True,
)

_CONFIG.AddConfig(chromium_info, 'x86-generic-tot-asan-informational',
  asan,
  boards=['x86-generic'],
  description='Full build with Address Sanitizer (Clang) on TOT',
)

_CONFIG.AddConfig(incremental, 'amd64-generic-asan',
  asan,
  boards=['amd64-generic'],
  description='Build with Address Sanitizer (Clang)',
  trybot_list=True,
)

_CONFIG.AddConfig(chromium_info, 'amd64-generic-tot-asan-informational',
  asan,
  boards=['amd64-generic'],
  description='Build with Address Sanitizer (Clang) on TOT',
)

incremental_beaglebone = incremental.derive(beaglebone)
_CONFIG.AddConfig(incremental_beaglebone, 'beaglebone-incremental',
  boards=['beaglebone'],
  trybot_list=True,
  description='Incremental Beaglebone Builder',
)

_CONFIG.AddRawConfig('refresh-packages',
  boards=['x86-generic', 'arm-generic'],
  builder_class_name='misc_builders.RefreshPackagesBuilder',
  description='Check upstream Gentoo for package updates',
)

_CONFIG.AddConfig(incremental, 'x86-generic-incremental',
  _base_configs['x86-generic'],
)

_CONFIG.AddConfig(incremental, 'daisy-incremental',
  _base_configs['daisy'],
  config_lib.BuildConfig.delete_keys(internal),
  manifest=config_lib.BuildConfig.delete_key(),
  useflags=append_useflags(['-chrome_internal']),
)

_CONFIG.AddConfig(incremental, 'amd64-generic-incremental',
  _base_configs['amd64-generic'],
  # This builder runs on a VM, so it can't run VM tests.
  vm_tests=[],
)

_CONFIG.AddConfig(incremental, 'x32-generic-incremental',
  _base_configs['x32-generic'],
  # This builder runs on a VM, so it can't run VM tests.
  vm_tests=[],
)

_CONFIG.AddConfig(paladin, 'x86-generic-asan-paladin',
  _base_configs['x86-generic'],
  asan,
  description='Paladin build with Address Sanitizer (Clang)',
  important=False,
)

_CONFIG.AddConfig(incremental, 'amd64-generic-asan-paladin',
  _base_configs['amd64-generic'],
  asan,
  description='Paladin build with Address Sanitizer (Clang)',
  important=False,
)

_chrome_perf_boards = frozenset([
  'daisy',
  'lumpy',
  'parrot',
])

_CreateConfigsForBoards(chrome_perf, _chrome_perf_boards, 'chrome-perf',
                        trybot_list=True)

chromium_info_x86 = \
_CONFIG.AddConfig(chromium_info, 'x86-generic-tot-chrome-pfq-informational',
  boards=['x86-generic'],
)

chromium_info_daisy = \
_CONFIG.AddConfig(chromium_info, 'daisy-tot-chrome-pfq-informational',
  non_testable_builder,
  boards=['daisy'],
)

chromium_info_amd64 = \
_CONFIG.AddConfig(chromium_info, 'amd64-generic-tot-chrome-pfq-informational',
  boards=['amd64-generic'],
)

_CONFIG.AddConfig(chromium_info, 'x32-generic-tot-chrome-pfq-informational',
  boards=['x32-generic'],
)

_CreateConfigsForBoards(telemetry_info, ['x86-generic', 'amd64-generic'],
                        'telem-chrome-pfq-informational')

_CONFIG.AddConfig(chrome_info, 'alex-tot-chrome-pfq-informational',
  boards=['x86-alex'],
)

_CONFIG.AddConfig(chrome_info, 'lumpy-tot-chrome-pfq-informational',
  boards=['lumpy'],
)

# WebRTC configurations.
_CONFIG.AddConfig(chrome_info, 'alex-webrtc-chrome-pfq-informational',
  boards=['x86-alex'],
)
_CONFIG.AddConfig(chrome_info, 'lumpy-webrtc-chrome-pfq-informational',
  boards=['lumpy'],
)
_CONFIG.AddConfig(chrome_info, 'daisy-webrtc-chrome-pfq-informational',
  non_testable_builder,
  boards=['daisy'],
)
_CONFIG.AddConfig(chromium_info_x86, 'x86-webrtc-chromium-pfq-informational',
  archive_build_debug=True,
)
_CONFIG.AddConfig(chromium_info_amd64,
                   'amd64-webrtc-chromium-pfq-informational',
  archive_build_debug=True,
)
_CONFIG.AddConfig(chromium_info_daisy,
                   'daisy-webrtc-chromium-pfq-informational',
  archive_build_debug=True,
)


#
# Internal Builds
#

internal_pfq = internal.derive(official_chrome, pfq,
  overlays=constants.BOTH_OVERLAYS,
  prebuilts=constants.PRIVATE,
)

# Because branch directories may be shared amongst builders on multiple
# branches, they must delete the chroot every time they run.
# They also potentially need to build [new] Chrome.
internal_pfq_branch = internal_pfq.derive(
    branch=True,
    chroot_replace=True,
    trybot_list=False,
    sync_chrome=True,
    active_waterfall=constants.WATERFALL_RELEASE)

internal_paladin = internal.derive(official_chrome, paladin,
  manifest=constants.OFFICIAL_MANIFEST,
  overlays=constants.BOTH_OVERLAYS,
  prebuilts=constants.PRIVATE,
  vm_tests=[],
  description=paladin['description'] + ' (internal)',
)

# Used for paladin builders with nowithdebug flag (a.k.a -cros-debug)
internal_nowithdebug_paladin = internal_paladin.derive(
  useflags=append_useflags(['-cros-debug']),
  description=paladin['description'] + ' (internal, nowithdebug)',
  prebuilts=False,
)

_CreateConfigsForBoards(internal_nowithdebug_paladin,
  ['x86-generic', 'amd64-generic'],
  'nowithdebug-paladin',
  important=False,
)

_CONFIG.AddConfig(internal_nowithdebug_paladin,
                   'x86-mario-nowithdebug-paladin',
                   boards=['x86-mario'])

# Used for builders which build completely from source except Chrome.
full_compile_paladin = paladin.derive(
  board_replace=True,
  chrome_binhost_only=True,
  chrome_sdk=False,
  cpe_export=False,
  debug_symbols=False,
  prebuilts=False,
  unittests=False,
  upload_hw_test_artifacts=False,
  vm_tests=[],
)

_CreateConfigsForBoards(full_compile_paladin,
  ['falco', 'nyan'],
  'full-compile-paladin',
)

pre_cq = paladin.derive(
  build_type=constants.INCREMENTAL_TYPE,
  build_packages_in_background=True,
  pre_cq=True,
  archive=False,
  chrome_sdk=False,
  chroot_replace=True,
  debug_symbols=False,
  prebuilts=False,
  cpe_export=False,
  vm_tests=[constants.SMOKE_SUITE_TEST_TYPE],
  description='Verifies compilation, building an image, and vm/unit tests '
              'if supported.',
  doc='http://www.chromium.org/chromium-os/build/builder-overview#TOC-Pre-CQ',
  health_alert_recipients=['chromeos-infra-eng@grotations.appspotmail.com'],
  health_threshold=3,
)

# Pre-CQ targets that only check compilation and unit tests.
unittest_only_pre_cq = pre_cq.derive(
  description='Verifies compilation and unit tests only',
  compilecheck=True,
  vm_tests=[],
)

# Pre-CQ targets that don't run VMTests.
no_vmtest_pre_cq = pre_cq.derive(
  description='Verifies compilation, building an image, and unit tests '
              'if supported.',
  vm_tests=[],
)

# Pre-CQ targets that only check compilation.
compile_only_pre_cq = unittest_only_pre_cq.derive(
  description='Verifies compilation only',
  unittests=False,
)

_CONFIG.AddConfig(internal_paladin, constants.BRANCH_UTIL_CONFIG,
  boards=[],
  # Disable postsync_patch to prevent conflicting patches from being applied -
  # e.g., patches from 'master' branch being applied to a branch.
  postsync_patch=False,
  # Disable postsync_reexec to continue running the 'master' branch chromite
  # for all stages, rather than the chromite in the branch buildroot.
  postsync_reexec=False,
  # Need to reset the paladin build_type we inherited.
  build_type=None,
  builder_class_name='release_builders.CreateBranchBuilder',
  description='Used for creating/deleting branches (TPMs only)',
)

# Internal incremental builders don't use official chrome because we want
# to test the developer workflow.
internal_incremental = internal.derive(
  incremental,
  overlays=constants.BOTH_OVERLAYS,
  description='Incremental Builds (internal)',
)

_CONFIG.AddConfig(internal_pfq_branch, 'lumpy-pre-flight-branch',
  master=True,
  push_overlays=constants.BOTH_OVERLAYS,
  boards=['lumpy'],
  afdo_generate=True,
  afdo_update_ebuild=True,
  hw_tests=[HWTestAFDORecordTest()],
)

# A test-ap image is just a test image with a special profile enabled.
# Note that each board enabled for test-ap use has to have the testbed-ap
# profile linked to from its private overlay.
_test_ap = internal.derive(
  description='WiFi AP images used in testing',
  profile='testbed-ap',
  vm_tests=[],
)

_CONFIG.AddGroup('test-ap-group',
  _CONFIG.AddConfig(_test_ap, 'stumpy-test-ap', boards=['stumpy']),
  _CONFIG.AddConfig(_test_ap, 'panther-test-ap', boards=['panther']),
)

### Master paladin (CQ builder).

_CONFIG.AddConfig(internal_paladin, 'master-paladin',
  boards=[],
  master=True,
  binhost_test=True,
  push_overlays=constants.BOTH_OVERLAYS,
  description='Commit Queue master (all others are slaves)',

  # This name should remain synced with with the name used in
  # build_internals/masters/master.chromeos/board_config.py.
  # TODO(mtennant): Fix this.  There should be some amount of auto-
  # configuration in the board_config.py code.
  health_threshold=3,
  health_alert_recipients=['chromeos-infra-eng@grotations.appspotmail.com',
                           'tree'],
  sanity_check_slaves=['wolf-tot-paladin'],
  trybot_list=False,
)

### Other paladins (CQ builders).
# These are slaves of the master paladin by virtue of matching
# in a few config values (e.g. 'build_type', 'branch', etc).  If
# they are not 'important' then they are ignored slaves.
# TODO(mtennant): This master-slave relationship should be specified
# here in the configuration, rather than GetSlavesForMaster().
# Something like the following:
# master_paladin = _CONFIG.AddConfig(internal_paladin, ...)
# master_paladin.AddSlave(_CONFIG.AddConfig(internal_paladin, ...))

# Old sanity check builder. This has been replaced by wolf-tot-paladin.
# TODO(dnj): Remove this once wolf-tot-paladin is removed from the waterfall.
_CONFIG.AddConfig(internal_paladin, 'link-tot-paladin',
  boards=['link'],
  do_not_apply_cq_patches=True,
  prebuilts=False,
  important=False,
)

# Sanity check builder, part of the CQ but builds without the patches
# under test.
_CONFIG.AddConfig(internal_paladin, 'wolf-tot-paladin',
  boards=['wolf'],
  do_not_apply_cq_patches=True,
  prebuilts=False,
  hw_tests=HWTestSharedPoolCQ(),
)

_paladin_boards = _all_boards

# List of paladin boards where the regular paladin config is important.
_paladin_important_boards = frozenset([
  'amd64-generic',
  'arm-generic',
  'auron',
  'beaglebone',
  'butterfly',
  'daisy',
  'daisy_skate',
  'daisy_spring',
  'falco',
  'gizmo',
  'kayle',
  'leon',
  'link',
  'lumpy',
  'mipsel-o32-generic',
  'monroe',
  'nyan',
  'oak',
  'panther',
  'panther_moblab',
  'parrot',
  'peach_pit',
  'peppy',
  'rambi',
  'rush_ryu',
  'samus',
  'storm',
  'stout',
  'stumpy',
  'stumpy_moblab',
  'veyron_pinky',
  'wolf',
  'x86-alex',
  'x86-generic',
  'x86-mario',
  'x86-zgb',
])

_paladin_simple_vmtest_boards = frozenset([
  'rambi',
  'x86-mario',
])

_paladin_devmode_vmtest_boards = frozenset([
  'parrot',
])

_paladin_cros_vmtest_boards = frozenset([
  'stout',
])

_paladin_smoke_vmtest_boards = frozenset([
  'amd64-generic',
  'x86-generic',
])

_paladin_default_vmtest_boards = frozenset([
  'x32-generic',
])

_paladin_hwtest_boards = frozenset([
  'daisy_skate',
  'link',
  'lumpy',
  'peach_pit',
  'peppy',
  'stumpy',
  'wolf',
  'x86-alex',
  'x86-zgb',
])

_paladin_moblab_hwtest_boards = frozenset([
  'stumpy_moblab',
])

_paladin_chroot_replace_boards = frozenset([
  'butterfly',
  'daisy_spring',
])

_paladin_separate_symbols = frozenset([
  'amd64-generic',
  'gizmo',
])

def _CreatePaladinConfigs():
  for board in _paladin_boards:
    assert board in _base_configs, '%s not in _base_configs' % board
    config_name = '%s-%s' % (board, constants.PALADIN_TYPE)
    customizations = config_lib.BuildConfig()
    base_config = _base_configs[board]
    if board in _paladin_hwtest_boards:
      customizations.update(hw_tests=HWTestDefaultListCQ())
    if board in _paladin_moblab_hwtest_boards:
      customizations.update(
          hw_tests=[config_lib.HWTestConfig(
                        constants.HWTEST_MOBLAB_QUICK_SUITE,
                        blocking=True, num=1, timeout=120*60,
                        pool=constants.HWTEST_PALADIN_POOL)])
    if board not in _paladin_important_boards:
      customizations.update(important=False)
    if board in _paladin_chroot_replace_boards:
      customizations.update(chroot_replace=True)
    if board in _internal_boards:
      customizations = customizations.derive(
          internal, official_chrome,
          manifest=constants.OFFICIAL_MANIFEST)
    if board in _paladin_separate_symbols:
      customizations.update(separate_debug_symbols=True)

    if board not in _paladin_default_vmtest_boards:
      vm_tests = []
      if board in _paladin_simple_vmtest_boards:
        vm_tests.append(constants.SIMPLE_AU_TEST_TYPE)
      if board in _paladin_cros_vmtest_boards:
        vm_tests.append(constants.CROS_VM_TEST_TYPE)
      if board in _paladin_devmode_vmtest_boards:
        vm_tests.append(constants.DEV_MODE_TEST_TYPE)
      if board in _paladin_smoke_vmtest_boards:
        vm_tests.append(constants.SMOKE_SUITE_TEST_TYPE)
      customizations.update(vm_tests=vm_tests)

    if base_config.get('internal'):
      customizations.update(prebuilts=constants.PRIVATE,
                            description=paladin['description'] + ' (internal)')
    else:
      customizations.update(prebuilts=constants.PUBLIC)
    _CONFIG.AddConfig(paladin, config_name,
                      customizations,
                      base_config)

_CreatePaladinConfigs()


_CONFIG.AddConfig(internal_paladin, 'lumpy-incremental-paladin',
  boards=['lumpy'],
  build_before_patching=True,
  chroot_replace=False,
  prebuilts=False,
  compilecheck=True,
  unittests=False,
)

### Paladins (CQ builders) which do not run VM or Unit tests on the builder
### itself.
external_brillo_paladin = paladin.derive(brillo)

_CONFIG.AddConfig(external_brillo_paladin, 'panther_embedded-minimal-paladin',
  boards=['panther_embedded'],
  profile='minimal',
  trybot_list=True,
)

internal_beaglebone_paladin = internal_paladin.derive(beaglebone)

_CONFIG.AddConfig(internal_beaglebone_paladin, 'beaglebone-paladin',
  boards=['beaglebone'],
  trybot_list=True,
)

_CONFIG.AddConfig(internal_beaglebone_paladin, 'beaglebone_servo-paladin',
  boards=['beaglebone_servo'],
  important=False,
)


def ShardHWTestsBetweenBuilders(*args):
  """Divide up the hardware tests between the given list of config names.

  Each of the config names must have the same hardware test suites, and the
  number of suites must be equal to the number of config names.

  Args:
    *args: A list of config names.
  """
  # List of config names.
  names = args
  # Verify sanity before sharding the HWTests.
  for name in names:
    assert len(_CONFIG[name].hw_tests) == len(names), \
      '%s should have %d tests, but found %d' % (
          name, len(names), len(_CONFIG[name].hw_tests))
  for name in names[1:]:
    for test1, test2 in zip(_CONFIG[name].hw_tests, _CONFIG[names[0]].hw_tests):
      assert test1.__dict__ == test2.__dict__, \
          '%s and %s have different hw_tests configured' % (names[0], name)

  # Assign each config the Nth HWTest.
  for i, name in enumerate(names):
    _CONFIG[name]['hw_tests'] = [_CONFIG[name].hw_tests[i]]

# Shard the bvt-inline and bvt-cq hw tests between similar builders.
# The first builder gets bvt-inline, and the second builder gets bvt-cq.
# bvt-cq takes longer, so it usually makes sense to give it the faster board.
ShardHWTestsBetweenBuilders('x86-zgb-paladin', 'x86-alex-paladin')
ShardHWTestsBetweenBuilders('wolf-paladin', 'peppy-paladin')
ShardHWTestsBetweenBuilders('daisy_skate-paladin', 'peach_pit-paladin')
ShardHWTestsBetweenBuilders('lumpy-paladin', 'stumpy-paladin')

# Add a pre-cq config for every board.
_CreateConfigsForBoards(pre_cq, _all_boards, 'pre-cq')
_CreateConfigsForBoards(no_vmtest_pre_cq, _all_boards, 'no-vmtest-pre-cq')
_CreateConfigsForBoards(compile_only_pre_cq, _all_boards, 'compile-only-pre-cq')

_CONFIG.AddConfig(no_vmtest_pre_cq, constants.BINHOST_PRE_CQ,
  internal,
  boards=[],
  binhost_test=True,
)

# TODO(davidjames): Add peach_pit, nyan, and beaglebone to pre-cq.
# TODO(davidjames): Update daisy_spring to build images again.
_CONFIG.AddGroup('mixed-a-pre-cq',
  # daisy_spring w/kernel 3.8.
  _CONFIG['daisy_spring-compile-only-pre-cq'],
  # lumpy w/kernel 3.8.
  _CONFIG['lumpy-compile-only-pre-cq'],
)

_CONFIG.AddGroup('mixed-b-pre-cq',
  # arm64 w/kernel 3.14.
  _CONFIG['rush_ryu-compile-only-pre-cq'],
  # samus w/kernel 3.14.
  _CONFIG['samus-compile-only-pre-cq'],
)

_CONFIG.AddGroup('mixed-c-pre-cq',
  # brillo
  _CONFIG['storm-compile-only-pre-cq'],
)

_CONFIG.AddGroup('external-mixed-pre-cq',
  _CONFIG['x86-generic-no-vmtest-pre-cq'],
  _CONFIG['amd64-generic-no-vmtest-pre-cq'],
)

_CONFIG.AddGroup('kernel-3_14-a-pre-cq',
  _CONFIG['x86-generic-no-vmtest-pre-cq'],
  _CONFIG['arm-generic-no-vmtest-pre-cq']
)

_CONFIG.AddGroup('kernel-3_14-b-pre-cq',
  _CONFIG['storm-no-vmtest-pre-cq'],
)

_CONFIG.AddGroup('kernel-3_14-c-pre-cq',
  _CONFIG['veyron_pinky-no-vmtest-pre-cq'],
  _CONFIG['rush_ryu-no-vmtest-pre-cq']
)

# TODO (crbug.com/438839): pre-cq-group has been replaced by multiple
# configs. Remove this config when no active CL has been screened
# with this config.
_CONFIG.AddGroup(constants.PRE_CQ_GROUP_CONFIG,
  # amd64 w/kernel 3.10. This builder runs VMTest so it's going to be
  # the slowest one.
  _CONFIG['rambi-pre-cq'],

  # daisy_spring w/kernel 3.8.
  _CONFIG['daisy_spring-compile-only-pre-cq'],

  # brillo config. We set build_packages_in_background=False here, so
  # that subsequent boards (samus, lumpy, parrot) don't get launched until
  # after duck finishes BuildPackages.
  _CONFIG.AddConfig(unittest_only_pre_cq, 'storm-pre-cq',
                    _base_configs['storm'],
                    build_packages_in_background=False),

  # samus w/kernel 3.14.
  _CONFIG['samus-compile-only-pre-cq'],

  # lumpy w/kernel 3.8.
  _CONFIG['lumpy-compile-only-pre-cq'],

  # arm64 w/kernel 3.4.
  _CONFIG['rush_ryu-compile-only-pre-cq'],
)

_CONFIG.AddConfig(internal_paladin, 'pre-cq-launcher',
  boards=[],
  build_type=constants.PRE_CQ_LAUNCHER_TYPE,
  description='Launcher for Pre-CQ builders',
  trybot_list=False,
  manifest_version=False,
  # Every Pre-CQ launch failure should send out an alert.
  health_threshold=1,
  health_alert_recipients=['chromeos-infra-eng@grotations.appspotmail.com',
                           'tree'],
  doc='http://www.chromium.org/chromium-os/build/builder-overview#TOC-Pre-CQ',
)


_CONFIG.AddConfig(internal_incremental, 'mario-incremental',
  boards=['x86-mario'],
)

_CONFIG.AddConfig(internal_incremental, 'lakitu-incremental',
  _base_configs['lakitu'],
)

_CONFIG.AddConfig(
  _toolchain_major, 'internal-toolchain-major', internal, official,
  boards=['x86-alex', 'stumpy', 'daisy'],
  build_tests=True,
  description=_toolchain_major['description'] + ' (internal)',
)

_CONFIG.AddConfig(
  _toolchain_minor, 'internal-toolchain-minor', internal, official,
  boards=['x86-alex', 'stumpy', 'daisy'],
  build_tests=True,
  description=_toolchain_minor['description'] + ' (internal)',
)

_release = full.derive(official, internal,
  build_type=constants.CANARY_TYPE,
  useflags=append_useflags(['-cros-debug']),
  build_tests=True,
  afdo_use=True,
  manifest=constants.OFFICIAL_MANIFEST,
  manifest_version=True,
  images=['base', 'recovery', 'test', 'factory_install'],
  push_image=True,
  upload_symbols=True,
  binhost_bucket='gs://chromeos-dev-installer',
  binhost_key='RELEASE_BINHOST',
  binhost_base_url=
    'https://commondatastorage.googleapis.com/chromeos-dev-installer',
  dev_installer_prebuilts=True,
  git_sync=False,
  vm_tests=[constants.SMOKE_SUITE_TEST_TYPE, constants.DEV_MODE_TEST_TYPE,
            constants.CROS_VM_TEST_TYPE],
  hw_tests=HWTestSharedPoolCanary(),
  paygen=True,
  signer_tests=True,
  trybot_list=True,
  hwqual=True,
  description="Release Builds (canary) (internal)",
  chrome_sdk=True,
  image_test=True,
  doc='http://www.chromium.org/chromium-os/build/builder-overview#TOC-Canaries',
)

_grouped_config = config_lib.BuildConfig(
  build_packages_in_background=True,
  chrome_sdk_build_chrome=False,
  unittests=None,
  vm_tests=[],
)

_grouped_variant_config = _grouped_config.derive(
  chrome_sdk=False,
)

_grouped_variant_release = _release.derive(_grouped_variant_config)

### Master release config.

_CONFIG.AddConfig(_release, 'master-release',
  boards=[],
  master=False,
  sync_chrome=False,
  chrome_sdk=False,
  health_alert_recipients=['chromeos-infra-eng@grotations.appspotmail.com',
                           'tree'],
  afdo_use=False,
)

### Release config groups.

_CONFIG.AddGroup('x86-alex-release-group',
  _CONFIG.AddConfig(_release, 'x86-alex-release',
    boards=['x86-alex'],
  ),
  _CONFIG.AddConfig(_grouped_variant_release, 'x86-alex_he-release',
    boards=['x86-alex_he'],
    hw_tests=[],
    upload_hw_test_artifacts=False,
    paygen_skip_testing=True,
  ),
)

_CONFIG.AddGroup('x86-zgb-release-group',
  _CONFIG.AddConfig(_release, 'x86-zgb-release',
    boards=['x86-zgb'],
  ),
  _CONFIG.AddConfig(_grouped_variant_release, 'x86-zgb_he-release',
    boards=['x86-zgb_he'],
    hw_tests=[],
    upload_hw_test_artifacts=False,
    paygen_skip_testing=True,
  ),
)

### Release AFDO configs.

release_afdo = _release.derive(
  trybot_list=False,
  hw_tests=HWTestDefaultList(pool=constants.HWTEST_SUITES_POOL,
                                    num=4) +
           HWTestAFDOList(),
  push_image=False,
  paygen=False,
  dev_installer_prebuilts=False,
)

# Now generate generic release-afdo configs if we haven't created anything more
# specific above already. release-afdo configs are builders that do AFDO profile
# collection and optimization in the same builder. Used by developers that
# want to measure performance changes caused by their changes.
def _AddAFDOConfigs():
  for board in _all_release_boards:
    if board in _x86_release_boards:
      base = {}
    else:
      base = non_testable_builder
    generate_config = config_lib.BuildConfig(
        base,
        boards=[board],
        afdo_generate_min=True,
        afdo_use=False,
        afdo_update_ebuild=True,
    )
    use_config = config_lib.BuildConfig(
        base,
        boards=[board],
        afdo_use=True,
    )

    config_name = '%s-%s' % (board, config_lib.CONFIG_TYPE_RELEASE_AFDO)
    if config_name not in _CONFIG:
      generate_config_name = '%s-%s-%s' % (board,
                                           config_lib.CONFIG_TYPE_RELEASE_AFDO,
                                           'generate')
      use_config_name = '%s-%s-%s' % (board,
                                      config_lib.CONFIG_TYPE_RELEASE_AFDO,
                                      'use')
      _CONFIG.AddGroup(
          config_name,
          _CONFIG.AddConfig(release_afdo, generate_config_name,
                            generate_config),
          _CONFIG.AddConfig(release_afdo, use_config_name, use_config))

_AddAFDOConfigs()

### Release configs.

_critical_for_chrome_boards = frozenset([
    'daisy',
    'lumpy',
    'parrot',
])

# bayleybay-release does not enable vm_tests or unittests due to the compiler
# flags enabled for baytrail.
_CONFIG.AddConfig(_release, 'bayleybay-release',
  boards=['bayleybay'],
  hw_tests=[],
  vm_tests=[],
  unittests=False,
)

_CONFIG.AddConfig(_release, 'beltino-release',
  boards=['beltino'],
  hw_tests=[],
  vm_tests=[],
)

# bayleybay-release does not enable vm_tests or unittests due to the compiler
# flags enabled for baytrail.
_CONFIG.AddConfig(_release, 'bobcat-release',
  boards=['bobcat'],
  hw_tests=[],
  profile='minimal',
  # This build doesn't generate signed images, so don't try to release them.
  paygen=False,
  signer_tests=False,
)

_CONFIG.AddConfig(_release, 'gizmo-release',
  _base_configs['gizmo'],
  important=False,
  paygen=False,
  signer_tests=False,
)

_CONFIG.AddConfig(_release, 'samus-release',
  _base_configs['samus'],
  important=True,
)

# Builder for non-freon 'quawks' for test coverage.
_CONFIG.AddConfig(_release, 'quawks-release',
  _base_configs['quawks'],
  important=False,
)

### Arm release configs.

_CONFIG.AddConfig(_release, 'veyron_rialto-release',
  _base_configs['veyron_rialto'],
  # rialto does not use Chrome.
  sync_chrome=False,
  chrome_sdk=False,
)


# Now generate generic release configs if we haven't created anything more
# specific above already.
def _AddReleaseConfigs():
  # We have to mark all autogenerated PFQs as not important so the master
  # does not wait for them.  http://crbug.com/386214
  # If you want an important PFQ, you'll have to declare it yourself.
  _CreateConfigsForBoards(
    chrome_info, _all_release_boards, 'tot-chrome-pfq-informational',
    important=False)
  _CreateConfigsForBoards(
    chrome_pfq, _chrome_pfq_important_boards, 'chrome-pfq')
  _CreateConfigsForBoards(
    chrome_pfq, _all_release_boards, 'chrome-pfq', important=False)
  _CreateConfigsForBoards(
    _release, _critical_for_chrome_boards, config_lib.CONFIG_TYPE_RELEASE,
    critical_for_chrome=True)
  _CreateConfigsForBoards(_release, _all_release_boards,
                          config_lib.CONFIG_TYPE_RELEASE)


_AddReleaseConfigs()

_CONFIG.AddConfig(_release, 'panther_embedded-minimal-release',
  _base_configs['panther_embedded'],
  profile='minimal',
  important=False,
  paygen=False,
  signer_tests=False,
)

# beaglebone build doesn't generate signed images, so don't try to release them.
_beaglebone_release = _release.derive(beaglebone, paygen=False,
                                      signer_tests=False,
                                      images=['base', 'test'])

_CONFIG.AddGroup('beaglebone-release-group',
  _CONFIG.AddConfig(_beaglebone_release, 'beaglebone-release',
    boards=['beaglebone'],
  ),
  _CONFIG.AddConfig(_beaglebone_release, 'beaglebone_servo-release',
    boards=['beaglebone_servo'],
    payload_image='base'
  ).derive(_grouped_variant_config),
  important=False,
)

_CONFIG.AddConfig(_release, 'kayle-release',
  _base_configs['kayle'],
  paygen=False,
  signer_tests=False,
)

_CONFIG.AddConfig(_release, 'cosmos-release',
  _base_configs['cosmos'],

  paygen_skip_testing=True,
  important=False,
  signer_tests=False,
)

_CONFIG.AddConfig(_release, 'storm-release',
  _base_configs['storm'],

  # Hw Lab can't test storm, yet.
  paygen_skip_testing=True,
  important=True,
  signer_tests=False
)

_CONFIG.AddConfig(_release, 'mipsel-o32-generic-release',
  _base_configs['mipsel-o32-generic'],
  paygen_skip_delta_payloads=True,
  afdo_use=False,
  hw_tests=[],
)

_CONFIG.AddConfig(_release, 'stumpy_moblab-release',
  _base_configs['stumpy_moblab'],
  images=['base', 'recovery', 'test'],
  paygen_skip_delta_payloads=True,
  # TODO: re-enable paygen testing when crbug.com/386473 is fixed.
  paygen_skip_testing=True,
  important=True,
  afdo_use=False,
  signer_tests=False,
  hw_tests=[
      config_lib.HWTestConfig(constants.HWTEST_MOBLAB_SUITE, blocking=True,
                              num=1, timeout=120*60),
      config_lib.HWTestConfig(constants.HWTEST_BVT_SUITE, blocking=True,
                              warn_only=True, num=1),
      config_lib.HWTestConfig(constants.HWTEST_AU_SUITE, blocking=True,
                              warn_only=True, num=1)],
)

_CONFIG.AddConfig(_release, 'panther_moblab-release',
  _base_configs['panther_moblab'],
  images=['base', 'recovery', 'test'],
  paygen_skip_delta_payloads=True,
  # TODO: re-enable paygen testing when crbug.com/386473 is fixed.
  paygen_skip_testing=True,
  important=True,
  afdo_use=False,
  signer_tests=False,
  hw_tests=[config_lib.HWTestConfig(constants.HWTEST_BVT_SUITE, blocking=True,
                                    warn_only=True, num=1),
            config_lib.HWTestConfig(constants.HWTEST_AU_SUITE, blocking=True,
                                    warn_only=True, num=1)],
)

_CONFIG.AddConfig(_release, 'rush-release',
  _base_configs['rush'],
  hw_tests=[],
  # This build doesn't generate signed images, so don't try to release them.
  paygen=False,
  signer_tests=False,
)

_CONFIG.AddConfig(_release, 'rush_ryu-release',
  _base_configs['rush_ryu'],
  hw_tests=[],
)

_CONFIG.AddConfig(_release, 'whirlwind-release',
  _base_configs['whirlwind'],
  important=True,
  afdo_use=True,
  dev_installer_prebuilts=True,
)

### Per-chipset release groups

def _AddGroupConfig(name, base_board, group_boards=None,
                    group_variant_boards=None, **kwargs):
  """Generate full & release group configs."""
  def _boards_list(x):
    # Make sure _boards_list is a valid list (not None or tuple)
    return [] if x is None else list(x)

  group_boards = _boards_list(group_boards)
  group_variant_boards = _boards_list(group_variant_boards)

  for group in ('release', 'full'):
    configs = []

    all_boards = [base_board] + group_boards + group_variant_boards
    desc = '%s; Group config (boards: %s)' % (
        _CONFIG['%s-%s' % (base_board, group)].description,
        ', '.join(all_boards))

    for board in all_boards:
      if board in group_boards:
        subconfig = _grouped_config
      elif board in group_variant_boards:
        subconfig = _grouped_variant_config
      else:
        subconfig = {}
      board_config = '%s-%s' % (board, group)
      configs.append(_CONFIG[board_config].derive(subconfig, **kwargs))

      config_name = '%s-%s-group' % (name, group)
      important = group == 'release' and kwargs.get('important', True)
    _CONFIG.AddGroup(config_name, *configs, description=desc,
                     important=important)

# pineview chipset boards
_AddGroupConfig('pineview', 'x86-alex', (
    'x86-zgb',
), (
    'x86-alex_he',
    'x86-zgb_he',
))

# pineview chipset boards (freon variant)
_AddGroupConfig('pineview-freon', 'x86-mario_freon', (
    'x86-alex_freon',
    'x86-zgb_freon',
), (
    'x86-alex_he-freon',
    'x86-zgb_he-freon',
))

# sandybridge chipset boards
_AddGroupConfig('sandybridge', 'parrot', (
    'lumpy',
    'butterfly',
    'stumpy',
))

# sandybridge chipset boards (freon variant)
_AddGroupConfig('sandybridge-freon', 'parrot_freon', (
    'lumpy_freon',
    'butterfly_freon',
    'stumpy_freon',
))

# ivybridge chipset boards
_AddGroupConfig('ivybridge-freon', 'stout', (
  'link',
), (
    'parrot_ivb',
))

# slippy-based haswell boards
# TODO(davidjames): Combine slippy and beltino into haswell canary, once we've
# optimized our builders more.
# slippy itself is deprecated in favor of the below boards, so we don't bother
# building it.
# TODO(dnj): Re-add peppy canary once builders are allocated.
_AddGroupConfig('slippy', 'peppy', (
    'falco',
    'leon',
    'wolf',
), (
    'falco_li',
))

# beltino-based haswell boards
# beltino itself is deprecated in favor of the below boards, so we don't bother
# building it.

_AddGroupConfig('beltino-a', 'panther', (
    'mccloud',
))

_AddGroupConfig('beltino-b', 'monroe', (
    'tricky',
    'zako',
))

# rambi-based boards
_AddGroupConfig('rambi-a', 'rambi', (
    'clapper',
    'enguarde',
    'expresso',
))

_AddGroupConfig('rambi-b', 'glimmer', (
    'gnawty',
    'kip',
    'quawks',
))

_AddGroupConfig('rambi-c', 'squawks', (
    'swanky',
    'winky',
    'candy',
))

_AddGroupConfig('rambi-d', 'banjo', (
    'ninja',
    'sumo',
    'orco',
))

# daisy-based boards
_AddGroupConfig('daisy', 'daisy', (
    'daisy_spring',
    'daisy_skate',
))

# peach-based boards
_AddGroupConfig('peach', 'peach_pit', (
    'peach_pi',
))

# nyan-based boards
_AddGroupConfig('nyan', 'nyan', (
    'nyan_big',
    'nyan_blaze',
    'nyan_kitty',
))

# auron-based boards
_AddGroupConfig('auron', 'auron', (
    'auron_yuna',
    'auron_paine',
))

_AddGroupConfig('auron-b', 'lulu', (
    'gandof',
))

# veyron-based boards
_AddGroupConfig('veyron', 'veyron_pinky', (
    'veyron_jerry',
    'veyron_mighty',
    'veyron_speedy'
    ),
)

_AddGroupConfig('veyron-b', 'veyron_jaq', (
    'veyron_minnie',
    'veyron_rialto',
    'veyron_thea'
    ),
)

# jecht-based boards
_AddGroupConfig('jecht', 'jecht', (
    'guado',
    'tidus',
    'rikku',
))

# strago-based boards
_AddGroupConfig('strago', 'strago', (
    'cyan',
    ),
    vm_tests=[],
)

# oak-based boards
_AddGroupConfig('oak', 'oak', (
    ),
    important=False,
)

# Factory and Firmware releases much inherit from these classes.  Modifications
# for these release builders should go here.

# Naming conventions also must be followed.  Factory and firmware branches must
# end in -factory or -firmware suffixes.

_factory_release = _release.derive(
  upload_hw_test_artifacts=False,
  upload_symbols=False,
  hw_tests=[],
  chrome_sdk=False,
  description='Factory Builds',
  paygen=False,
  afdo_use=False,
)

_firmware = config_lib.BuildConfig(
  images=[],
  factory_toolkit=False,
  packages=['virtual/chromeos-firmware'],
  usepkg_build_packages=True,
  sync_chrome=False,
  build_tests=False,
  chrome_sdk=False,
  unittests=False,
  vm_tests=[],
  hw_tests=[],
  dev_installer_prebuilts=False,
  upload_hw_test_artifacts=False,
  upload_symbols=False,
  signer_tests=False,
  trybot_list=False,
  paygen=False,
  image_test=False,
)

_firmware_release = _release.derive(_firmware,
  description='Firmware Canary',
  manifest=constants.DEFAULT_MANIFEST,
  afdo_use=False,
)

_depthcharge_release = _firmware_release.derive(
  useflags=append_useflags(['depthcharge']))

_depthcharge_full_internal = full.derive(
  internal,
  _firmware,
  useflags=append_useflags(['depthcharge']),
  description='Firmware Informational',
)

_firmware_boards = frozenset([
  'auron',
  'banjo',
  'bayleybay',
  'beltino',
  'butterfly',
  'candy',
  'clapper',
  'cyan',
  'daisy',
  'daisy_skate',
  'daisy_spring',
  'enguarde',
  'expresso',
  'falco',
  'glimmer',
  'gnawty',
  'jecht',
  'kip',
  'leon',
  'link',
  'lumpy',
  'monroe',
  'ninja',
  'orco',
  'panther',
  'parrot',
  'parry',
  'peach_pi',
  'peach_pit',
  'peppy',
  'quawks',
  'rambi',
  'rikku',
  'samus',
  'slippy',
  'smaug',
  'squawks',
  'storm',
  'stout',
  'strago',
  'stumpy',
  'sumo',
  'swanky',
  'winky',
  'wolf',
  'x86-mario',
  'zako',
])

_x86_depthcharge_firmware_boards = frozenset([
  'auron',
  'banjo',
  'bayleybay',
  'candy',
  'clapper',
  'cyan',
  'enguarde',
  'expresso',
  'glimmer',
  'gnawty',
  'jecht',
  'kip',
  'leon',
  'link',
  'ninja',
  'orco',
  'parry',
  'quawks',
  'rambi',
  'rikku',
  'samus',
  'squawks',
  'strago',
  'sumo',
  'swanky',
  'winky',
  'zako',
])


def _AddFirmwareConfigs():
  """Add x86 and arm firmware configs."""
  for board in _firmware_boards:
    _CONFIG.AddConfig(_firmware_release,
        '%s-%s' % (board, config_lib.CONFIG_TYPE_FIRMWARE),
        _base_configs[board],
    )

  for board in _x86_depthcharge_firmware_boards:
    _CONFIG.AddConfig(_depthcharge_release,
        '%s-%s-%s' % (board, 'depthcharge', config_lib.CONFIG_TYPE_FIRMWARE),
        _base_configs[board],
    )
    _CONFIG.AddConfig(_depthcharge_full_internal,
        '%s-%s-%s-%s' % (board, 'depthcharge', config_lib.CONFIG_TYPE_FULL,
                         config_lib.CONFIG_TYPE_FIRMWARE),
        _base_configs[board],
    )

_AddFirmwareConfigs()


# This is an example factory branch configuration for x86.
# Modify it to match your factory branch.
_CONFIG.AddConfig(_factory_release, 'x86-mario-factory',
  boards=['x86-mario'],
)

# This is an example factory branch configuration for arm.
# Modify it to match your factory branch.
_CONFIG.AddConfig(_factory_release, 'daisy-factory',
  non_testable_builder,
  boards=['daisy'],
)

_payloads = internal.derive(
  build_type=constants.PAYLOADS_TYPE,
  builder_class_name='release_builders.GeneratePayloadsBuilder',
  description='Regenerate release payloads.',
  vm_tests=[],

  # Sync to the code used to do the build the first time.
  manifest_version=True,

  # This is the actual work we want to do.
  paygen=True,

  upload_hw_test_artifacts=False,
)

def _AddPayloadConfigs():
  """Create <board>-payloads configs for all payload generating boards.

  We create a config named 'board-payloads' for every board which has a
  config with 'paygen' True. The idea is that we have a build that generates
  payloads, we need to have a tryjob to re-attempt them on failure.
  """
  payload_boards = set()

  def _search_config_and_children(search_config):
    # If paygen is enabled, add it's boards to our list of payload boards.
    if search_config['paygen']:
      for board in search_config['boards']:
        payload_boards.add(board)

    # Recurse on any child configs.
    for child in search_config['child_configs']:
      _search_config_and_children(child)

  # Search all configs for boards that generate payloads.
  for _, search_config in _CONFIG.iteritems():
    _search_config_and_children(search_config)

  # Generate a payloads trybot config for every board that generates payloads.
  for board in payload_boards:
    name = '%s-payloads' % board
    _CONFIG.AddConfig(_payloads, name, boards=[board])

_AddPayloadConfigs()

def _AddProjectSdkConfigs():
  for board in _project_sdk_boards:
    name = '%s-project-sdk' % board
    _CONFIG.AddConfig(project_sdk, name, boards=[board])

_AddProjectSdkConfigs()

# LKGM builds don't work for tryjobs. Add this as a workaround, for now.
_CONFIG.AddConfig(project_sdk,
  'trybot-project-sdk',
  boards=['panther_embedded'],

  # Don't use LKGM
  use_lkgm=False,
)

def GetDisplayPosition(config_name,
                       type_order=config_lib.CONFIG_TYPE_DUMP_ORDER):
  """Given a config_name, return display position specified by suffix_order.

  Args:
    config_name: Name of config to look up.
    type_order: A tuple/list of config types in the order they are to be
                displayed.

  Returns:
    If |config_name| does not contain any of the suffixes, returns the index
    position after the last element of suffix_order.
  """
  for index, config_type in enumerate(type_order):
    if config_name.endswith('-' + config_type) or config_name == config_type:
      return index

  return len(type_order)


# On release branches, x86-mario is the release master.
#
# TODO(dnj): This should go away once the boardless release master is complete
# (crbug.com/458675)
if IS_RELEASE_BRANCH:
  _CONFIG['x86-mario-release']['master'] = True


# This is a list of configs that should be included on the main waterfall, but
# aren't included by default (see IsDefaultMainWaterfall). This loosely
# corresponds to the set of experimental or self-standing configs.
_waterfall_config_map = {
}

def _SetupWaterfalls():
  for name, c in _CONFIG.iteritems():
    if not c.get('active_waterfall'):
      c['active_waterfall'] = GetDefaultWaterfall(c)

  # Apply manual configs.
  for waterfall, names in _waterfall_config_map.iteritems():
    for name in names:
      _CONFIG[name]['active_waterfall'] = waterfall

_SetupWaterfalls()
