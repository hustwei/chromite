#!/usr/bin/python

# Copyright (c) 2012 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""This module tests the init module."""

import glob
import imp
import mox
import os
import sys

sys.path.insert(0, os.path.abspath('%s/../../..' % os.path.dirname(__file__)))

from chromite.lib import cros_test_lib
from chromite.cros import commands


# pylint: disable=W0212
class CommandTest(mox.MoxTestBase):
  """This test class tests that we can load modules correctly."""

  def testFindModules(self):
    """Tests that we can return modules correctly when mocking out glob."""
    self.mox.StubOutWithMock(glob, 'glob')
    fake_command_file = 'cros_command_test.py'
    filtered_file = 'cros_command_unittest.py'
    mydir = 'mydir'

    glob.glob(mox.StrContains(mydir)).AndReturn([fake_command_file,
                                                 filtered_file])

    self.mox.ReplayAll()
    self.assertEqual(commands._FindModules(mydir), [fake_command_file])
    self.mox.VerifyAll()

  def testLoadCommands(self):
    """Tests import commands correctly."""
    self.mox.StubOutWithMock(commands, '_FindModules')
    self.mox.StubOutWithMock(imp, 'load_module')
    self.mox.StubOutWithMock(imp, 'find_module')
    fake_command_file = 'cros_command_test.py'
    fake_module = 'cros_command_test'
    module_tuple = 'file', 'pathname', 'description'
    commands._FindModules(mox.IgnoreArg()).AndReturn([fake_command_file])
    imp.find_module(fake_module, mox.IgnoreArg()).AndReturn(module_tuple)
    imp.load_module(fake_module, *module_tuple)

    self.mox.ReplayAll()
    commands._ImportCommands()
    self.mox.VerifyAll()


if __name__ == '__main__':
  cros_test_lib.main()
