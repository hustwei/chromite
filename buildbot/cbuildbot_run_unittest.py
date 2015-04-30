#!/usr/bin/python

# Copyright (c) 2013 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Test the cbuildbot_run module."""

import logging
import os
import cPickle
import sys

sys.path.insert(0, os.path.abspath('%s/../..' % os.path.dirname(__file__)))
from chromite.buildbot import cbuildbot_config
from chromite.buildbot import cbuildbot_run
from chromite.lib import cros_test_lib

import mock

DEFAULT_BUILDROOT = '/tmp/foo/bar/buildroot'
DEFAULT_BUILDNUMBER = 12345
DEFAULT_BRANCH = 'TheBranch'
DEFAULT_CHROME_BRANCH = 'TheChromeBranch'
DEFAULT_VERSION_STRING = 'TheVersionString'
DEFAULT_BOARD = 'TheBoard'
DEFAULT_BOT_NAME = 'TheCoolBot'

# Access to protected member.
# pylint: disable=W0212

DEFAULT_OPTIONS = cros_test_lib.EasyAttr(
    buildroot=DEFAULT_BUILDROOT,
    buildnumber=DEFAULT_BUILDNUMBER,
    branch=DEFAULT_BRANCH,
    remote_trybot=False,
)
DEFAULT_CONFIG = cbuildbot_config._config(
    name=DEFAULT_BOT_NAME,
    master=True,
    boards=[DEFAULT_BOARD],
    child_configs=[cros_test_lib.EasyAttr(name='foo'),
                   cros_test_lib.EasyAttr(name='bar'),
                  ])


def _NewBuilderRun(options=None, config=None):
  """Create a BuilderRun objection from options and config values.

  Args:
    options: Specify options or default to DEFAULT_OPTIONS.
    config: Specify build config or default to DEFAULT_CONFIG.

  Returns:
    BuilderRun object.
  """
  options = options or DEFAULT_OPTIONS
  config = config or DEFAULT_CONFIG
  return cbuildbot_run.BuilderRun(options, config)


def _NewChildBuilderRun(child_index, options=None, config=None):
  """Create a ChildBuilderRun objection from options and config values.

  Args:
    child_index: Index of child config to use within config.
    options: Specify options or default to DEFAULT_OPTIONS.
    config: Specify build config or default to DEFAULT_CONFIG.

  Returns:
    ChildBuilderRun object.
  """
  run = _NewBuilderRun(options, config)
  return cbuildbot_run.ChildBuilderRun(run, child_index)


def _ExtendDefaultOptions(**kwargs):
  """Extend DEFAULT_OPTIONS with keys/values in kwargs."""
  options_kwargs = DEFAULT_OPTIONS.copy()
  options_kwargs.update(kwargs)
  return cros_test_lib.EasyAttr(**options_kwargs)


def _ExtendDefaultConfig(**kwargs):
  """Extend DEFAULT_CONFIG with keys/values in kwargs."""
  config_kwargs = DEFAULT_CONFIG.copy()
  config_kwargs.update(kwargs)
  return cbuildbot_config._config(**config_kwargs)


class BuilderRunPickleTest(cros_test_lib.TestCase):
  """Make sure BuilderRun objects can be pickled."""

  def testPickleBuilderRun(self):
    run1 = _NewBuilderRun()
    run1.attrs.release_tag = 'TheReleaseTag'
    run2 = cPickle.loads(cPickle.dumps(run1, cPickle.HIGHEST_PROTOCOL))

    self.assertEquals(run1.buildnumber, run2.buildnumber)
    self.assertEquals(run1.config.boards, run2.config.boards)
    self.assertEquals(run1.options.branch, run2.options.branch)
    self.assertEquals(run1.attrs.release_tag, run2.attrs.release_tag)
    self.assertRaises(AttributeError, getattr, run1.attrs, 'manifest_manager')
    self.assertRaises(AttributeError, getattr, run2.attrs, 'manifest_manager')

  def testPickleChildBuilderRun(self):
    run1 = _NewChildBuilderRun(0)
    run1.attrs.release_tag = 'TheReleaseTag'
    run2 = cPickle.loads(cPickle.dumps(run1, cPickle.HIGHEST_PROTOCOL))

    self.assertEquals(run1.child_index, run2.child_index)
    self.assertEquals(run1.buildnumber, run2.buildnumber)
    self.assertEquals(run1.config.name, run2.config.name)
    self.assertEquals(run1.options.branch, run2.options.branch)
    self.assertEquals(run1.attrs.release_tag, run2.attrs.release_tag)
    self.assertRaises(AttributeError, getattr, run1.attrs, 'manifest_manager')
    self.assertRaises(AttributeError, getattr, run2.attrs, 'manifest_manager')


class BuilderRunTest(cros_test_lib.TestCase):
  """Test the BuilderRun class."""

  def testInit(self):
    run = _NewBuilderRun()
    self.assertEquals(DEFAULT_BUILDROOT, run.buildroot)
    self.assertEquals(DEFAULT_BUILDNUMBER, run.buildnumber)
    self.assertEquals(DEFAULT_BRANCH, run.manifest_branch)
    self.assertEquals(DEFAULT_OPTIONS, run.options)
    self.assertEquals(DEFAULT_CONFIG, run.config)
    self.assertTrue(isinstance(run.attrs, cbuildbot_run.RunAttributes))

  def testOptions(self):
    options = _ExtendDefaultOptions(foo=True, bar=10)
    run = _NewBuilderRun(options=options)

    self.assertEquals(True, run.options.foo)
    self.assertEquals(10, run.options.__getattr__('bar'))
    self.assertRaises(AttributeError, run.options.__getattr__, 'baz')

  def testConfig(self):
    config = _ExtendDefaultConfig(foo=True, bar=10)
    run = _NewBuilderRun(config=config)

    self.assertEquals(True, run.config.foo)
    self.assertEquals(10, run.config.__getattr__('bar'))
    self.assertRaises(AttributeError, run.config.__getattr__, 'baz')

  def testAttrs(self):
    run = _NewBuilderRun()

    # manifest_manager is a valid run attribute.  It gives Attribute error
    # if accessed before being set, but thereafter works fine.
    self.assertRaises(AttributeError, run.attrs.__getattribute__,
                      'manifest_manager')
    run.attrs.manifest_manager = 'foo'
    self.assertEquals('foo', run.attrs.manifest_manager)
    self.assertEquals('foo', run.attrs.__getattribute__('manifest_manager'))

    # foobar is not a valid run attribute.  It gives AttributeError when
    # accessed or changed.
    self.assertRaises(AttributeError, run.attrs.__getattribute__, 'foobar')
    self.assertRaises(AttributeError, run.attrs.__setattr__, 'foobar', 'foo')

  def _RunAccessor(self, method, options_dict, config_dict):
    """Run the given accessor method of the BuilderRun class.

    Create a BuilderRun object with the options and config provided and
    then return the result of calling the given method on it.

    Args:
      method: A BuilderRun method to call.
      options_dict: Extend default options with this.
      config_dict: Extend default config with this.

    Returns:
      Result of calling the given method.
    """
    options = _ExtendDefaultOptions(**options_dict)
    config = _ExtendDefaultConfig(**config_dict)
    run = _NewBuilderRun(options=options, config=config)
    return method(run)

  def testDualEnableSetting(self):
    settings = {
        'prebuilts': cbuildbot_run.BuilderRun.ShouldUploadPrebuilts,
        'postsync_patch': cbuildbot_run.BuilderRun.ShouldPatchAfterSync,
    }

    # Both option and config enabled should result in True.
    # Create truth table with three variables in this order:
    # <key> option value, <key> config value (e.g. <key> == 'prebuilts').
    truth_table = cros_test_lib.TruthTable(inputs=[(True, True)])

    for inputs in truth_table:
      option_val, config_val = inputs
      for key, accessor in settings.iteritems():
        self.assertEquals(
            self._RunAccessor(accessor, {key: option_val}, {key: config_val}),
            truth_table.GetOutput(inputs))

  def testShouldReexecAfterSync(self):
    # If option and config have postsync_reexec enabled, and this file is not
    # in the build root, then we expect ShouldReexecAfterSync to return True.

    # Construct a truth table across three variables in this order:
    # postsync_reexec option value, postsync_reexec config value, same_root.
    truth_table = cros_test_lib.TruthTable(inputs=[(True, True, False)])

    for inputs in truth_table:
      option_val, config_val, same_root = inputs

      if same_root:
        build_root = os.path.dirname(os.path.dirname(__file__))
      else:
        build_root = DEFAULT_BUILDROOT

      result = self._RunAccessor(
          cbuildbot_run.BuilderRun.ShouldReexecAfterSync,
          {'postsync_reexec': option_val, 'buildroot': build_root},
          {'postsync_reexec': config_val})

      self.assertEquals(result, truth_table.GetOutput(inputs))


class GetVersionTest(cros_test_lib.MockTestCase):
  """Test the GetVersion and GetVersionInfo methods of BuilderRun class."""

  def testGetVersionInfo(self):
    verinfo = object()

    with mock.patch('cbuildbot_run.manifest_version.VersionInfo.from_repo',
                    return_value=verinfo) as m:
      result = cbuildbot_run.BuilderRun.GetVersionInfo(DEFAULT_BUILDROOT)
      self.assertEquals(result, verinfo)

      m.assert_called_once_with(DEFAULT_BUILDROOT)

  def _TestGetVersionReleaseTag(self, release_tag):
    with mock.patch.object(cbuildbot_run.BuilderRun, 'GetVersionInfo') as m:
      verinfo_mock = mock.Mock()
      verinfo_mock.chrome_branch = DEFAULT_CHROME_BRANCH
      verinfo_mock.VersionString = mock.Mock(return_value='VS')
      m.return_value = verinfo_mock

      # Prepare a real BuilderRun object with a release tag.
      run = _NewBuilderRun()
      run.attrs.release_tag = release_tag

      # Run the test return the result.
      result = run.GetVersion()
      m.assert_called_once_with(DEFAULT_BUILDROOT)
      if release_tag is None:
        verinfo_mock.VersionString.assert_called_once()

      return result

  def testGetVersionReleaseTag(self):
    result = self._TestGetVersionReleaseTag('RT')
    self.assertEquals('R%s-%s' % (DEFAULT_CHROME_BRANCH, 'RT'), result)

  def testGetVersionNoReleaseTag(self):
    result = self._TestGetVersionReleaseTag(None)
    expected_result = ('R%s-%s-b%s' %
                       (DEFAULT_CHROME_BRANCH, 'VS', DEFAULT_BUILDNUMBER))
    self.assertEquals(result, expected_result)


class ChildBuilderRunTest(cros_test_lib.TestCase):
  """Test the ChildBuilderRun class"""

  def testInit(self):
    crun = _NewChildBuilderRun(0)
    self.assertEquals(DEFAULT_BUILDROOT, crun.buildroot)
    self.assertEquals(DEFAULT_BUILDNUMBER, crun.buildnumber)
    self.assertEquals(DEFAULT_BRANCH, crun.manifest_branch)
    self.assertEquals(DEFAULT_OPTIONS, crun.options)
    self.assertEquals(DEFAULT_CONFIG.child_configs[0], crun.config)
    self.assertEquals('foo', crun.config.name)
    self.assertEquals(0, crun.child_index)
    self.assertTrue(isinstance(crun.attrs, cbuildbot_run.RunAttributes))


if __name__ == '__main__':
  cros_test_lib.main(level=logging.DEBUG)