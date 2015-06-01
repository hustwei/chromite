# Copyright 2015 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Utility for setting the /etc/lsb-release file of an image."""

from __future__ import print_function

import getpass
import os

from chromite.lib import commandline
from chromite.lib import cros_build_lib
from chromite.lib import image_lib


# LSB keys:
# Set google-specific version numbers:
# CHROMEOS_RELEASE_BOARD is the target board identifier.
# CHROMEOS_RELEASE_BRANCH_NUMBER is the Chrome OS branch number
# CHROMEOS_RELEASE_BUILD_NUMBER is the Chrome OS build number
# CHROMEOS_RELEASE_BUILD_TYPE is the type of build (official, from developers,
# etc..)
# CHROMEOS_RELEASE_CHROME_MILESTONE is the Chrome milestone (also named Chrome
#   branch).
# CHROMEOS_RELEASE_DESCRIPTION is the version displayed by Chrome; see
#   chrome/browser/chromeos/chromeos_version_loader.cc.
# CHROMEOS_RELEASE_NAME is a human readable name for the build.
# CHROMEOS_RELEASE_PATCH_NUMBER is the patch number for the current branch.
# CHROMEOS_RELEASE_TRACK and CHROMEOS_RELEASE_VERSION are used by the software
#   update service.
# TODO(skrul):  Remove GOOGLE_RELEASE once Chromium is updated to look at
#   CHROMEOS_RELEASE_VERSION for UserAgent data.
LSB_KEY_NAME = 'CHROMEOS_RELEASE_NAME'
LSB_KEY_AUSERVER = 'CHROMEOS_AUSERVER'
LSB_KEY_DEVSERVER = 'CHROMEOS_DEVSERVER'
LSB_KEY_TRACK = 'CHROMEOS_RELEASE_TRACK'
LSB_KEY_BUILD_TYPE = 'CHROMEOS_RELEASE_BUILD_TYPE'
LSB_KEY_DESCRIPTION = 'CHROMEOS_RELEASE_DESCRIPTION'
LSB_KEY_BOARD = 'CHROMEOS_RELEASE_BOARD'
LSB_KEY_BRANCH_NUMBER = 'CHROMEOS_RELEASE_BRANCH_NUMBER'
LSB_KEY_BUILD_NUMBER = 'CHROMEOS_RELEASE_BUILD_NUMBER'
LSB_KEY_CHROME_MILESTONE = 'CHROMEOS_RELEASE_CHROME_MILESTONE'
LSB_KEY_PATCH_NUMBER = 'CHROMEOS_RELEASE_PATCH_NUMBER'
LSB_KEY_VERSION = 'CHROMEOS_RELEASE_VERSION'
LSB_KEY_GOOGLE_RELEASE = 'GOOGLE_RELEASE'
LSB_KEY_APPID_RELEASE = 'CHROMEOS_RELEASE_APPID'
LSB_KEY_APPID_BOARD = 'CHROMEOS_BOARD_APPID'
LSB_KEY_APPID_CANARY = 'CHROMEOS_CANARY_APPID'

CANARY_APP_ID = "{90F229CE-83E2-4FAF-8479-E368A34938B1}"

def _ParseArguments(argv):
  parser = commandline.ArgumentParser(description=__doc__)

  parser.add_argument('--app_id', default=None,
                      help='The APP_ID to install.')
  parser.add_argument('--board', help='The board name.', required=True)
  parser.add_argument('--sysroot', required=True, type='path',
                      help='The sysroot to install the lsb-release file into.')
  parser.add_argument('--version_string', required=True,
                      help='The image\'s version string.')
  parser.add_argument('--auserver', default=None,
                      help='The auserver url to use.')
  parser.add_argument('--devserver', default=None,
                      help='The devserver url to use.')
  parser.add_argument('--official', action='store_true',
                      help='Whether or not to populate with fields for an '
                      'official image.')
  parser.add_argument('--buildbot_build', default='N/A',
                      help='The build number, for use with the continuous '
                      'builder.')
  parser.add_argument('--track', default='developer-build',
                      help='The type of release track.')
  parser.add_argument('--branch_number', default='0',
                      help='The branch number.')
  parser.add_argument('--build_number', default='0',
                      help='The build number.')
  parser.add_argument('--chrome_milestone', default='0',
                      help='The Chrome milestone.')
  parser.add_argument('--patch_number', default='0',
                      help='The patch number for the given branch.')

  opts = parser.parse_args(argv)

  # If the auserver or devserver isn't specified or is set to blank, set it
  # to the host's hostname.
  hostname = cros_build_lib.GetHostName(fully_qualified=True)

  if not opts.auserver:
    opts.auserver = 'http://%s:8080/update' % hostname

  if not opts.devserver:
    opts.devserver = 'http://%s:8080' % hostname

  opts.Freeze()

  if not os.path.isdir(opts.sysroot):
    cros_build_lib.Die('The target sysroot does not exist: %s' % opts.sysroot)

  if not opts.version_string:
    cros_build_lib.Die('version_string must not be empty.  Was '
                       'chromeos_version.sh sourced correctly in the calling '
                       'script?')

  return opts


def main(argv):
  opts = _ParseArguments(argv)

  fields = {
      LSB_KEY_NAME: 'Chromium OS',
      LSB_KEY_AUSERVER: opts.auserver,
      LSB_KEY_DEVSERVER: opts.devserver,
  }

  if opts.app_id is not None:
    fields.update({
        LSB_KEY_APPID_RELEASE: opts.app_id,
        LSB_KEY_APPID_BOARD: opts.app_id,
        LSB_KEY_APPID_CANARY: CANARY_APP_ID,
    })

  if opts.official:
    # Official builds (i.e. buildbot).
    track = 'dev-channel'
    build_type = 'Official Build'
    fields.update({
        LSB_KEY_TRACK: track,
        LSB_KEY_NAME: 'Chrome OS',
        LSB_KEY_BUILD_TYPE: build_type,
        LSB_KEY_DESCRIPTION: ('%s (%s) %s %s test' %
                              (opts.version_string,
                               build_type,
                               track,
                               opts.board)),
        LSB_KEY_AUSERVER: 'https://tools.google.com/service/update2',
        LSB_KEY_DEVSERVER: '',
    })
  elif getpass.getuser() == 'chrome-bot':
    # Continuous builder.
    build_type = 'Continuous Builder - Builder: %s' % opts.buildbot_build
    fields.update({
        LSB_KEY_TRACK: 'buildbot-build',
        LSB_KEY_BUILD_TYPE: build_type,
        LSB_KEY_DESCRIPTION: '%s (%s) %s' % (opts.version_string,
                                             build_type,
                                             opts.board),
    })
  else:
    # Developer manual builds.
    build_type = 'Developer Build - %s' % getpass.getuser()
    fields.update({
        LSB_KEY_TRACK: opts.track,
        LSB_KEY_BUILD_TYPE: build_type,
        LSB_KEY_DESCRIPTION: '%s (%s) %s %s' % (opts.version_string,
                                                build_type,
                                                opts.track,
                                                opts.board),
    })

  fields.update({
      LSB_KEY_BOARD: opts.board,
      LSB_KEY_BRANCH_NUMBER: opts.branch_number,
      LSB_KEY_BUILD_NUMBER: opts.build_number,
      LSB_KEY_CHROME_MILESTONE: opts.chrome_milestone,
      LSB_KEY_PATCH_NUMBER: opts.patch_number,
      LSB_KEY_VERSION: opts.version_string,
      LSB_KEY_GOOGLE_RELEASE: opts.version_string,
  })

  image_lib.WriteLsbRelease(opts.sysroot, fields)
