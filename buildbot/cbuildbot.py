#!/usr/bin/python

# Copyright (c) 2011 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Main builder code for Chromium OS.

Used by Chromium OS buildbot configuration for all Chromium OS builds including
full and pre-flight-queue builds.
"""

import optparse
import os
import pprint
import sys

if __name__ == '__main__':
  import constants
  sys.path.append(constants.SOURCE_ROOT)

import chromite.buildbot.cbuildbot_comm as cbuildbot_comm
import chromite.buildbot.cbuildbot_commands as commands
import chromite.buildbot.cbuildbot_config as cbuildbot_config
import chromite.buildbot.cbuildbot_stages as stages
import chromite.lib.cros_build_lib as cros_lib


def _GetConfig(config_name, options):
  """Gets the configuration for the build"""
  if not cbuildbot_config.config.has_key(config_name):
    print 'Non-existent configuration specified.'
    print 'Please specify one of:'
    config_names = cbuildbot_config.config.keys()
    config_names.sort()
    for name in config_names:
      print '  %s' % name
    sys.exit(1)

  result = cbuildbot_config.config[config_name]

  # Use the config specific url, if not given on command line.
  if options.url:
    result['git_url'] = options.url

  return result


def RunBuildStages(bot_id, options, build_config):
  """Run the requested build stages."""

  completed_stages_file = os.path.join(options.buildroot, '.completed_stages')

  if options.resume and os.path.exists(completed_stages_file):
    with open(completed_stages_file, 'r') as load_file:
      stages.Results.RestoreCompletedStages(load_file)

  # TODO, Remove here and in config after bug chromium-os:14649 is fixed.
  if build_config['chromeos_official']:
    os.environ['CHROMEOS_OFFICIAL'] = '1'

  tracking_branch = commands.GetChromiteTrackingBranch()
  stages.BuilderStage.SetTrackingBranch(tracking_branch)

  build_success = False
  build_and_test_success = False

  try:
    if options.sync:
      if build_config['manifest_version']:
        stages.ManifestVersionedSyncStage(bot_id, options, build_config).Run()
      else:
        stages.SyncStage(bot_id, options, build_config).Run()

    if not options.clobber:
      # If we are doing an incremental checkout, make sure we are running on a
      # buildroot checked out to same branch as chromite.  Use
      # <build_root>/src/scripts as the spot check.
      buildroot_repo = os.path.join(options.buildroot, 'src', 'scripts')
      manifest_branch = commands.GetManifestBranch(buildroot_repo)
      if manifest_branch != tracking_branch:
        cros_lib.Die('Chromite is not on same branch as buildroot checkout\n' +
                     'Chromite is on branch %s.\n' % tracking_branch +
                     'Buildroot checked out to %s\n' % manifest_branch)

    if options.build:
      stages.BuildBoardStage(bot_id, options, build_config).Run()
      if build_config['build_type'] == 'chroot':
        stages.Results.Report(sys.stdout)
        return stages.Results.Success()

    if options.uprev:
      stages.UprevStage(bot_id, options, build_config).Run()

    if options.build:
      stages.BuildTargetStage(bot_id, options, build_config).Run()

    build_success = True

    if options.tests:
      stages.TestStage(bot_id, options, build_config).Run()

    if options.remote_test_status:
      stages.RemoteTestStatusStage(bot_id, options, build_config).Run()

    build_and_test_success = True

  except stages.BuildException:
    # We skipped out of this build block early, all we need to do.
    pass

  # Control master / slave logic here.
  if build_and_test_success and build_config['master']:
    if cbuildbot_comm.HaveSlavesCompleted(cbuildbot_config.config):
      stages.PushChangesStage(bot_id, options, build_config).Run()
    else:
      cros_lib.Die('One of the other slaves failed.')

  if build_config['important']:
    if build_and_test_success:
      cbuildbot_comm.PublishStatus(cbuildbot_comm.STATUS_BUILD_COMPLETE)
    else:
      cbuildbot_comm.PublishStatus(cbuildbot_comm.STATUS_BUILD_FAILED)

  # If the ManifestVersionedSync created a manifest, we need to
  # store off final results for the manifest.
  if stages.ManifestVersionedSyncStage.manifest_manager:
    try:
      stages.ManifestVersionedSyncCompletionStage(
         bot_id,
         options,
         build_config,
         success=build_and_test_success).Run()
    except stages.BuildException:
      pass

  if build_success and options.archive:
    try:
      stages.ArchiveStage(bot_id, options, build_config).Run()
    except stages.BuildException:
      pass

  if os.path.exists(options.buildroot):
    with open(completed_stages_file, 'w+') as save_file:
      stages.Results.SaveCompletedStages(save_file)

  stages.Results.Report(sys.stdout)
  return stages.Results.Success()

def main():
  # Parse options
  usage = "usage: %prog [options] cbuildbot_config"
  parser = optparse.OptionParser(usage=usage)
  parser.add_option('--buildbot', action='store_false', dest='debug',
                    help='This is running on a buildbot')
  parser.add_option('-r', '--buildroot',
                    help='root directory where build occurs', default=".")
  parser.add_option('-n', '--buildnumber',
                    help='build number', type='int', default=0)
  parser.add_option('--chrome_rev', default=None, type='string',
                    dest='chrome_rev',
                    help=('Chrome_rev of type [tot|latest_release|'
                          'sticky_release]'))
  parser.add_option('--clobber', action='store_true', dest='clobber',
                    default=False,
                    help='Clobbers an old checkout before syncing')
  parser.add_option('--debug', action='store_true', dest='debug',
                    default=True,
                    help='Override some options to run as a developer.')
  parser.add_option('--dump_config', action='store_true', dest='dump_config',
                    default=False,
                    help='Dump out build config options, and exit.')
  parser.add_option('--noarchive', action='store_false', dest='archive',
                    default=True,
                    help="Don't run archive stage.")
  parser.add_option('--nobuild', action='store_false', dest='build',
                    default=True,
                    help="Don't actually build (for cbuildbot dev")
  parser.add_option('--noprebuilts', action='store_false', dest='prebuilts',
                    default=True,
                    help="Don't upload prebuilts.")
  parser.add_option('--nosync', action='store_false', dest='sync',
                    default=True,
                    help="Don't sync before building.")
  parser.add_option('--notests', action='store_false', dest='tests',
                    default=True,
                    help='Override values from buildconfig and run no tests.')
  parser.add_option('--remoteteststatus', dest='remote_test_status',
                    default=None, help='List of remote jobs to check status')
  parser.add_option('--resume', action='store_true',
                    default=False,
                    help='Skip stages already successfully completed.')
  parser.add_option('-f', '--revisionfile',
                    help='file where new revisions are stored')
  parser.add_option('-t', '--tracking-branch', dest='tracking_branch_old',
                    default='cros/master', help='Run the buildbot on a branch')
  parser.add_option('--nouprev', action='store_false', dest='uprev',
                    default=True,
                    help='Override values from buildconfig and never uprev.')
  parser.add_option('-u', '--url', dest='url',
                    default=None,
                    help='Override the GIT repo URL from the build config.')

  (options, args) = parser.parse_args()

  if len(args) >= 1:
    bot_id = args[-1]
    build_config = _GetConfig(bot_id, options)
  else:
    parser.error('Invalid usage.  Use -h to see usage.')

  if options.dump_config:
    # This works, but option ordering is bad...
    print 'Configuration %s:' % bot_id
    pp = pprint.PrettyPrinter(indent=2)
    pp.pprint(build_config)
    sys.exit(0)

  if not RunBuildStages(bot_id, options, build_config):
    sys.exit(1)


if __name__ == '__main__':
    main()
