# Copyright (c) 2011 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""
Repository module to handle different types of repositories the Builders use.
"""

import constants
import filecmp
import logging
import os
import re
import shutil
import tempfile

from chromite.lib import cros_build_lib as cros_lib

class SrcCheckOutException(Exception):
  """Exception gets thrown for failure to sync sources"""
  pass


class RepoRepository(object):
  """ A Class that encapsulates a repo repository.
  Args:
    repo_url: gitserver URL to fetch repo manifest from.
    directory: local path where to checkout the repository.
    branch: Branch to check out the manifest at.
    clobber: Clobbers the directory as part of initialization.
  """
  DEFAULT_MANIFEST = 'default'
  # Use our own repo, in case android.kernel.org (the default location) is down.
  _INIT_CMD = ['repo', 'init', '--repo-url', constants.REPO_URL]

  def __init__(self, repo_url, directory, branch=None, clobber=False):
    self.repo_url = repo_url
    self.directory = directory
    self.branch = branch

    if clobber or not os.path.exists(os.path.join(self.directory, '.repo')):
      cros_lib.RunCommand(['sudo', 'rm', '-rf', self.directory], error_ok=True)

  def Initialize(self):
    """Initializes a repository."""
    assert not os.path.exists(os.path.join(self.directory, '.repo')), \
        'Repo already initialized.'
    # Base command.
    init_cmd = self._INIT_CMD + ['--manifest-url', self.repo_url]

    # Handle branch / manifest options.
    if self.branch: init_cmd.extend(['--manifest-branch', self.branch])
    cros_lib.RunCommand(init_cmd, cwd=self.directory, input='\n\ny\n')

  def _ReinitializeIfNecessary(self, local_manifest):
    """Reinitializes the repository if the manifest has changed."""
    def _ShouldReinitialize():
      if local_manifest != self.DEFAULT_MANIFEST:
        return not filecmp.cmp(local_manifest, manifest_path)
      else:
        return not filecmp.cmp(default_manifest_path, manifest_path)

    manifest_path = self.GetRelativePath('.repo/manifest.xml')
    default_manifest_path = self.GetRelativePath('.repo/manifests/default.xml')
    if not (local_manifest and _ShouldReinitialize()):
      return

    # If no manifest passed in, assume default.
    if local_manifest == self.DEFAULT_MANIFEST:
      cros_lib.RunCommand(self._INIT_CMD + ['--manifest-name=default.xml'],
                          cwd=self.directory, input='\n\ny\n')
    else:
      # The 10x speed up magic.
      os.unlink(manifest_path)
      shutil.copyfile(local_manifest, manifest_path)

  def Sync(self, local_manifest=None):
    """Sync/update the source.  Changes manifest if specified.

    local_manifest:  If set, checks out source to manifest.  DEFAULT_MANIFEST
    may be used to set it back to the default manifest.
    """
    try:
      if not os.path.exists(self.directory):
        os.makedirs(self.directory)
        self.Initialize()

      self._ReinitializeIfNecessary(local_manifest)

      cros_lib.OldRunCommand(['repo', 'sync', '--jobs', '8'],
                             cwd=self.directory, num_retries=2)
    except cros_lib.RunCommandError, e:
      err_msg = 'Failed to sync sources %s' % e.message
      logging.error(err_msg)
      raise SrcCheckOutException(err_msg)

  def GetRelativePath(self, path):
    """Returns full path including source directory of path in repo."""
    return os.path.join(self.directory, path)

  def ExportManifest(self, output_file):
    """Export current manifest to a file.

    Args:
      output_file: Self explanatory.
    """
    cros_lib.RunCommand(['repo', 'manifest', '-r', '-o', output_file],
                        cwd=self.directory, print_cmd=False)


  def IsManifestDifferent(self, other_manifest):
    """Checks whether this manifest is different than another.

    May blacklists certain repos as part of the diff.

    Args:
      other_manfiest: Second manifest file to compare against.
    Returns:
      True: If the manifests are different
      False: If the manifests are same
    """
    black_list = ['manifest-versions']
    logging.debug('Calling DiffManifests against %s', other_manifest)

    temp_manifest_file = tempfile.mktemp()
    try:
      self.ExportManifest(temp_manifest_file)
      blacklist_pattern = re.compile(r'|'.join(black_list))
      with open(temp_manifest_file, 'r') as manifest1_fh:
        with open(other_manifest, 'r') as manifest2_fh:
          for (line1, line2) in zip(manifest1_fh, manifest2_fh):
            if blacklist_pattern.search(line1):
              logging.debug('%s ignored %s', line1, line2)
              continue

            if line1 != line2:
              return True
          return False
    finally:
      os.remove(temp_manifest_file)
