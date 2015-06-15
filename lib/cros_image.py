# Copyright 2015 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Utilities for manipulating ChromeOS images."""

from __future__ import print_function

import glob
import re

from chromite.lib import cros_build_lib
from chromite.lib import osutils


class LoopbackError(Exception):
  """An exception raised when something went wrong setting up a loopback"""


class LoopbackPartitions(object):
  """Loopback mount a file and provide access to its partitions.

  This class can be used as a context manager with the "with" statement, or
  individual instances of it can be created which will clean themselves up
  when garbage collected or when explicitly closed, ala the tempfile module.

  In either case, the same arguments should be passed to init.

  Args:
    path: Path to the backing file.
    losetup: Path to the losetup utility. The default uses the system PATH.
  """
  def __init__(self, path, util_path=None):
    self._util_path = util_path
    self.path = path
    self.dev = None
    self.parts = {}

    try:
      cmd = ['losetup', '--show', '-f', self.path]
      ret = self._au_safe_sudo(cmd, print_cmd=False, capture_output=True)
      self.dev = ret.output.strip()
      cmd = ['partx', '-d', self.dev]
      self._au_safe_sudo(cmd, quiet=True, error_code_ok=True)
      cmd = ['partx', '-a', self.dev]
      self._au_safe_sudo(cmd, print_cmd=False)

      self.parts = {}
      part_devs = glob.glob(self.dev + 'p*')
      if not part_devs:
        Warning('Didn\'t find partition devices nodes for %s.' % self.path)
        return

      for part in part_devs:
        number = int(re.search(r'p(\d+)$', part).group(1))
        self.parts[number] = part

    except:
      self.close()
      raise

  def _au_safe_sudo(self, cmd, **kwargs):
    """Run a command using sudo in a way that respects the util_path"""
    newcmd = osutils.Which(cmd[0], path=self._util_path)
    if newcmd:
      cmd = [newcmd] + cmd[1:]
    return cros_build_lib.SudoRunCommand(cmd, **kwargs)


  def close(self):
    if self.dev:
      cmd = ['partx', '-d', self.dev]
      self._au_safe_sudo(cmd, quiet=True, error_code_ok=True)
      self._au_safe_sudo(['losetup', '--detach', self.dev])
      self.dev = None
      self.parts = {}

  def __enter__(self):
    return self

  def __exit__(self, exc_type, exc, tb):
    self.close()

  def __del__(self):
    self.close()