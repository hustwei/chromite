# Copyright 2015 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Script to summarize stats for different builds in prod."""

from __future__ import print_function

import collections
import datetime
import numpy
import re
import sys

from chromite.cbuildbot import cbuildbot_config
from chromite.cbuildbot import constants
from chromite.cbuildbot import metadata_lib
from chromite.lib import cidb
from chromite.lib import clactions
from chromite.lib import commandline
from chromite.lib import cros_logging as logging


# These are the preferred base URLs we use to canonicalize bugs/CLs.
BUGANIZER_BASE_URL = 'b/'
GUTS_BASE_URL = 't/'
CROS_BUG_BASE_URL = 'crbug.com/'
INTERNAL_CL_BASE_URL = 'crosreview.com/i/'
EXTERNAL_CL_BASE_URL = 'crosreview.com/'

class CLStatsEngine(object):
  """Engine to generate stats about CL actions taken by the Commit Queue."""

  def __init__(self, db):
    self.db = db
    self.actions = []
    self.builds = []
    self.per_patch_actions = {}
    self.per_cl_actions = {}
    self.reasons = {}
    self.blames = {}
    self.summary = {}
    self.builds_by_build_id = {}

  def GatherBuildAnnotations(self):
    """Gather the failure annotations for builds from cidb."""
    annotations_by_builds = self.db.GetAnnotationsForBuilds(
        [b['id'] for b in self.builds])
    for b in self.builds:
      build_id = b['id']
      build_number = b['build_number']
      annotations = annotations_by_builds.get(build_id, [])
      if not annotations:
        self.reasons[build_number] = ['None']
        self.blames[build_number] = []
      else:
        # TODO(pprabhu) crbug.com/458275
        # We currently squash together multiple annotations into one to ease
        # co-existence with the spreadsheet based logic. Once we've moved off of
        # using the spreadsheet, we should update all uses of the annotations to
        # expect one or more annotations.
        self.reasons[build_number] = [
            a['failure_category'] for a in annotations]
        self.blames[build_number] = []
        for annotation in annotations:
          self.blames[build_number] += self.ProcessBlameString(
              annotation['blame_url'])

  def CollateActions(self, actions):
    """Collates a list of actions into per-patch and per-cl actions.

    Returns a tuple (per_patch_actions, per_cl_actions) where each are
    a dictionary mapping patches or cls to a list of CLActionWithBuildTuple
    sorted in order of ascending timestamp.
    """
    per_patch_actions = {}
    per_cl_actions = {}
    for action in actions:
      change_with_patch = action.patch
      change_no_patch = metadata_lib.GerritChangeTuple(
          action.change_number, change_with_patch.internal
      )

      per_patch_actions.setdefault(change_with_patch, []).append(action)
      per_cl_actions.setdefault(change_no_patch, []).append(action)

    for actions_map in [per_cl_actions, per_patch_actions]:
      for key, value in actions_map.iteritems():
        actions_map[key] = sorted(value, key=lambda x: x.timestamp)

    return (per_patch_actions, per_cl_actions)

  @staticmethod
  def ProcessBlameString(blame_string):
    """Parse a human-created |blame_string| from the spreadsheet.

    Returns:
      A list of canonicalized URLs for bugs or CLs that appear in the blame
      string. Canonicalized form will be 'crbug.com/1234',
      'crosreview.com/1234', 'b/1234', 't/1234', or 'crosreview.com/i/1234' as
      applicable.
    """
    urls = []
    tokens = blame_string.split()

    # Format to generate the regex patterns. Matches one of provided domain
    # names, followed by lazy wildcard, followed by greedy digit wildcard,
    # followed by optional slash and optional comma.
    general_regex = r'^.*(%s).*?([0-9]+)/?,?$'

    crbug = general_regex % r'crbug.com|code.google.com'
    internal_review = general_regex % (
        r'chrome-internal-review.googlesource.com|crosreview.com/i')
    external_review = general_regex % (
        r'crosreview.com|chromium-review.googlesource.com')
    guts = general_regex % r't/|gutsv\d.corp.google.com/#ticket/'

    # Buganizer regex is different, as buganizer urls do not end with the bug
    # number.
    buganizer = r'^.*(b/|b.corp.google.com/issue\?id=)([0-9]+).*$'

    # Patterns need to be tried in a specific order -- internal review needs
    # to be tried before external review, otherwise urls like crosreview.com/i
    # will be incorrectly parsed as external.
    patterns = [crbug,
                internal_review,
                external_review,
                buganizer,
                guts]
    url_patterns = [CROS_BUG_BASE_URL,
                    INTERNAL_CL_BASE_URL,
                    EXTERNAL_CL_BASE_URL,
                    BUGANIZER_BASE_URL,
                    GUTS_BASE_URL]

    for t in tokens:
      for p, u in zip(patterns, url_patterns):
        m = re.match(p, t)
        if m:
          urls.append(u + m.group(2))
          break

    return urls

  def Gather(self, start_date, end_date, sort_by_build_number=True,
             starting_build_number=None):
    """Fetches build data and failure reasons.

    Args:
      start_date: A datetime.date instance for the earliest build to
          examine.
      end_date: A datetime.date instance for the latest build to
          examine.
      sort_by_build_number: Optional boolean. If True, builds will be
          sorted by build number.
      starting_build_number: (optional) The lowest build number from the CQ to
          include in the results.
    """
    logging.info('Gathering data for %s from %s until %s', constants.CQ_MASTER,
                 start_date, end_date)
    self.builds = self.db.GetBuildHistory(
        constants.CQ_MASTER,
        start_date=start_date,
        end_date=end_date,
        starting_build_number=starting_build_number,
        num_results=self.db.NUM_RESULTS_NO_LIMIT)
    if self.builds:
      logging.info('Fetched %d builds (build_id: %d to %d)', len(self.builds),
                   self.builds[0]['id'], self.builds[-1]['id'])
    else:
      logging.info('Fetched no builds.')
    if sort_by_build_number:
      logging.info('Sorting by build number.')
      self.builds.sort(key=lambda x: x['build_number'])

    self.actions = self.db.GetActionHistory(start_date, end_date)
    self.GatherBuildAnnotations()

    self.builds_by_build_id.update(
        {b['id'] : b for b in self.builds})

  def GetSubmittedPatchNumber(self, actions):
    """Get the patch number of the final patchset submitted.

    This function only makes sense for patches that were submitted.

    Args:
      actions: A list of actions for a single change.
    """
    submit = [a for a in actions if a.action == constants.CL_ACTION_SUBMITTED]
    assert len(submit) > 0, 'Expected change to be submitted, got %r' % actions
    if len(submit) > 1:
      # Patches may be submitted more than once if we mark the patch as
      # submitted when it is still in "SUBMITTING" state and Gerrit later bumps
      # it back to "NEW". This should only happen due to Gerrit bugs.
      logging.info('Change %s was submitted more than once: %r',
                   submit[-1].patch, submit)

    return submit[-1].patch_number

  def ClassifyRejections(self, submitted_changes):
    """Categorize rejected CLs, deciding whether the rejection was incorrect.

    We figure out what patches were falsely rejected by looking for patches
    which were later submitted unmodified after being rejected. These patches
    are considered to be likely good CLs.

    Args:
      submitted_changes: A dict mapping submitted GerritChangeTuple objects to
        a list of associated actions.

    Yields:
      change: The GerritChangeTuple that was rejected.
      actions: A list of actions applicable to the CL.
      a: The reject action that kicked out the CL.
      falsely_rejected: Whether the CL was incorrectly rejected. A CL rejection
        is considered incorrect if the same patch is later submitted, with no
        changes. It's a heuristic.
    """
    for change, actions in submitted_changes.iteritems():
      submitted_patch_number = self.GetSubmittedPatchNumber(actions)
      picked_up_builds = set(x.build_id for x in actions
                             if x.action == constants.CL_ACTION_PICKED_UP)
      for a in actions:
        if a.action == constants.CL_ACTION_KICKED_OUT:
          # If the patch wasn't picked up in the run, this means that it "failed
          # to apply" rather than "failed to validate". Ignore it.
          picked_up = [x for x in actions if x.build_id == a.build_id and
                       x.patch == a.patch and
                       x.action == constants.CL_ACTION_PICKED_UP]
          falsely_rejected = a.patch_number == submitted_patch_number
          if picked_up:
            patch_actions = [x for x in actions if
                             a.patch_number == x.patch_number
                             and x.build_id in picked_up_builds]
            # Check whether the patch was updated after submission.
            yield change, patch_actions, a, falsely_rejected

  def _PrintCounts(self, reasons, fmt):
    """Print a sorted list of reasons in descending order of frequency.

    Args:
      reasons: A key/value mapping mapping the reason to the count.
      fmt: A format string for our log message, containing %(cnt)d
        and %(reason)s.
    """
    d = reasons
    for cnt, reason in sorted(((v, k) for (k, v) in d.items()), reverse=True):
      logging.info(fmt, dict(cnt=cnt, reason=reason))
    if not d:
      logging.info('  None')

  def BotType(self, action):
    """Return whether |action| applies to the CQ or PRE_CQ."""
    build_config = action.build_config
    if build_config.endswith('-%s' % cbuildbot_config.CONFIG_TYPE_PALADIN):
      return constants.CQ
    else:
      return constants.PRE_CQ

  def GoodPatchRejections(self, submitted_changes):
    """Find good patches that were incorrectly rejected.

    Args:
      submitted_changes: A dict mapping submitted GerritChangeTuple objects to
        a list of associated actions.

    Returns:
      A dict, where d[patch] = reject_actions for each good patch that was
      incorrectly rejected.
    """
    # falsely_rejected_changes maps GerritChangeTuple objects to their actions.
    # bad_cl_builds is a set of builds that contain a bad patch.
    falsely_rejected_changes = {}
    bad_cl_builds = set()
    for x in self.ClassifyRejections(submitted_changes):
      _, actions, a, falsely_rejected = x
      if falsely_rejected:
        falsely_rejected_changes[a.patch] = actions
      elif self.BotType(a) == constants.PRE_CQ:
        # If a developer writes a bad patch and it fails the Pre-CQ, it
        # may cause many other patches from the same developer to be
        # rejected. This is expected and correct behavior. Treat all of
        # the patches in the Pre-CQ run as bad so that they don't skew our
        # our statistics.
        #
        # Since we don't have a spreadsheet for the Pre-CQ, we guess what
        # CLs were bad by looking at what patches needed to be changed
        # before submission.
        #
        # NOTE: We intentionally only apply this logic to the Pre-CQ here.
        # The CQ is different because it may have many innocent patches in
        # a single run which should not be treated as bad.
        bad_cl_builds.add(a.build_id)

    # Make a list of candidate patches that got incorrectly rejected. We track
    # them in a dict, setting good_patch_rejections[patch] = rejections for
    # each patch.
    good_patch_rejections = collections.defaultdict(list)
    for v in falsely_rejected_changes.itervalues():
      for a in v:
        if (a.action == constants.CL_ACTION_KICKED_OUT and
            a.build_id not in bad_cl_builds):
          good_patch_rejections[a.patch].append(a)

    return good_patch_rejections

  def FalseRejectionRate(self, good_patch_count, good_patch_rejection_count):
    """Calculate the false rejection ratio.

    This is the chance that a good patch will be rejected by the Pre-CQ or CQ
    in a given run.

    Args:
      good_patch_count: The number of good patches in the run.
      good_patch_rejection_count: A dict containing the number of false
        rejections for the CQ and PRE_CQ.

    Returns:
      A dict containing the false rejection ratios for CQ, PRE_CQ, and combined.
    """
    false_rejection_rate = dict()
    for bot, rejection_count in good_patch_rejection_count.iteritems():
      false_rejection_rate[bot] = (
          rejection_count * 100 / (rejection_count + good_patch_count)
      )
    false_rejection_rate['combined'] = 0
    if good_patch_count:
      rejection_count = sum(good_patch_rejection_count.values())
      false_rejection_rate['combined'] = (
          rejection_count * 100. / (good_patch_count + rejection_count)
      )
    return false_rejection_rate

  def Summarize(self):
    """Process, print, and return a summary of cl action statistics.

    As a side effect, save summary to self.summary.

    Returns:
      A dictionary summarizing the statistics.
    """
    if self.builds:
      logging.info('%d total runs included, from build %d to %d.',
                   len(self.builds), self.builds[-1]['build_number'],
                   self.builds[0]['build_number'])
      total_passed = len([b for b in self.builds
                          if b['status'] == constants.BUILDER_STATUS_PASSED])
      logging.info('%d of %d runs passed.', total_passed, len(self.builds))
    else:
      logging.info('No runs included.')

    (self.per_patch_actions,
     self.per_cl_actions) = self.CollateActions(self.actions)

    submit_actions = [a for a in self.actions
                      if a.action == constants.CL_ACTION_SUBMITTED]
    reject_actions = [a for a in self.actions
                      if a.action == constants.CL_ACTION_KICKED_OUT]
    sbfail_actions = [a for a in self.actions
                      if a.action == constants.CL_ACTION_SUBMIT_FAILED]

    build_reason_counts = {}
    for reasons in self.reasons.values():
      for reason in reasons:
        if reason != 'None':
          build_reason_counts[reason] = build_reason_counts.get(reason, 0) + 1

    unique_blames = set()
    for blames in self.blames.itervalues():
      unique_blames.update(blames)

    unique_cl_blames = {blame for blame in unique_blames if
                        EXTERNAL_CL_BASE_URL in blame}

    submitted_changes = {k: v for k, v, in self.per_cl_actions.iteritems()
                         if any(a.action == constants.CL_ACTION_SUBMITTED
                                for a in v)}

    # Count changes that were submitted, unless they were non-manifest changes
    # which were submitted with no testing.
    submitted_patches = {
        k: v for k, v, in self.per_patch_actions.iteritems()
        if any(a.action == constants.CL_ACTION_SUBMITTED and
               a.reason != constants.STRATEGY_NONMANIFEST for a in v)}

    patch_handle_times = [
        clactions.GetCLHandlingTime(patch, actions) for
        (patch, actions) in submitted_patches.iteritems()]

    pre_cq_handle_times = [
        clactions.GetPreCQTime(patch, actions) for
        (patch, actions) in submitted_patches.iteritems()]

    cq_wait_times = [
        clactions.GetCQWaitTime(patch, actions) for
        (patch, actions) in submitted_patches.iteritems()]

    cq_handle_times = [
        clactions.GetCQRunTime(patch, actions) for
        (patch, actions) in submitted_patches.iteritems()]

    # Count CLs that were rejected, then a subsequent patch was submitted.
    # These are good candidates for bad CLs. We track them in a dict, setting
    # submitted_after_new_patch[bot_type][patch] = actions for each bad patch.
    submitted_after_new_patch = {}
    for x in self.ClassifyRejections(submitted_changes):
      change, actions, a, falsely_rejected = x
      if not falsely_rejected:
        d = submitted_after_new_patch.setdefault(self.BotType(a), {})
        d[change] = actions

    # Sort the candidate bad CLs in order of submit time.
    bad_cl_candidates = {}
    for bot_type, patch_actions in submitted_after_new_patch.items():
      bad_cl_candidates[bot_type] = [
          k for k, _ in sorted(patch_actions.items(),
                               key=lambda x: x[1][-1].timestamp)]

    # Calculate how many good patches were falsely rejected and why.
    # good_patch_rejections maps patches to the rejection actions.
    # patch_reason_counts maps failure reasons to counts.
    # patch_blame_counts maps blame targets to counts.
    good_patch_rejections = self.GoodPatchRejections(submitted_changes)
    patch_reason_counts = {}
    patch_blame_counts = {}
    for k, v in good_patch_rejections.iteritems():
      for a in v:
        if a.action == constants.CL_ACTION_KICKED_OUT:
          build = self.builds_by_build_id.get(a.build_id)
          if self.BotType(a) == constants.CQ and build is not None:
            build_number = build['build_number']
            reasons = self.reasons.get(build_number, ['None'])
            blames = self.blames.get(build_number, ['None'])
            for x in reasons:
              patch_reason_counts[x] = patch_reason_counts.get(x, 0) + 1
            for x in blames:
              patch_blame_counts[x] = patch_blame_counts.get(x, 0) + 1

    # good_patch_count: The number of good patches.
    # good_patch_rejection_count maps the bot type (CQ or PRE_CQ) to the number
    #   of times that bot has falsely rejected good patches.
    good_patch_count = len(submit_actions)
    good_patch_rejection_count = collections.defaultdict(int)
    for k, v in good_patch_rejections.iteritems():
      for a in v:
        good_patch_rejection_count[self.BotType(a)] += 1
    false_rejection_rate = self.FalseRejectionRate(good_patch_count,
                                                   good_patch_rejection_count)

    # This list counts how many times each good patch was rejected.
    rejection_counts = [0] * (good_patch_count - len(good_patch_rejections))
    rejection_counts += [len(x) for x in good_patch_rejections.values()]

    # Break down the frequency of how many times each patch is rejected.
    good_patch_rejection_breakdown = []
    if rejection_counts:
      for x in range(max(rejection_counts) + 1):
        good_patch_rejection_breakdown.append((x, rejection_counts.count(x)))

    summary = {
        'total_cl_actions': len(self.actions),
        'unique_cls': len(self.per_cl_actions),
        'unique_patches': len(self.per_patch_actions),
        'submitted_patches': len(submit_actions),
        'rejections': len(reject_actions),
        'submit_fails': len(sbfail_actions),
        'good_patch_rejections': sum(rejection_counts),
        'mean_good_patch_rejections': numpy.mean(rejection_counts),
        'good_patch_rejection_breakdown': good_patch_rejection_breakdown,
        'good_patch_rejection_count': dict(good_patch_rejection_count),
        'false_rejection_rate': false_rejection_rate,
        'median_handling_time': numpy.median(patch_handle_times),
        'patch_handling_time': patch_handle_times,
        'bad_cl_candidates': bad_cl_candidates,
        'unique_blames_change_count': len(unique_cl_blames),
    }

    logging.info('CQ committed %s changes', summary['submitted_patches'])
    logging.info('CQ correctly rejected %s unique changes',
                 summary['unique_blames_change_count'])
    logging.info('pre-CQ and CQ incorrectly rejected %s changes a total of '
                 '%s times (pre-CQ: %s; CQ: %s)',
                 len(good_patch_rejections),
                 sum(good_patch_rejection_count.values()),
                 good_patch_rejection_count[constants.PRE_CQ],
                 good_patch_rejection_count[constants.CQ])

    logging.info('      Total CL actions: %d.', summary['total_cl_actions'])
    logging.info('    Unique CLs touched: %d.', summary['unique_cls'])
    logging.info('Unique patches touched: %d.', summary['unique_patches'])
    logging.info('   Total CLs submitted: %d.', summary['submitted_patches'])
    logging.info('      Total rejections: %d.', summary['rejections'])
    logging.info(' Total submit failures: %d.', summary['submit_fails'])
    logging.info(' Good patches rejected: %d.',
                 len(good_patch_rejections))
    logging.info('   Mean rejections per')
    logging.info('            good patch: %.2f',
                 summary['mean_good_patch_rejections'])
    logging.info(' False rejection rate for CQ: %.1f%%',
                 summary['false_rejection_rate'].get(constants.CQ, 0))
    logging.info(' False rejection rate for Pre-CQ: %.1f%%',
                 summary['false_rejection_rate'].get(constants.PRE_CQ, 0))
    logging.info(' Combined false rejection rate: %.1f%%',
                 summary['false_rejection_rate']['combined'])

    for x, p in summary['good_patch_rejection_breakdown']:
      logging.info('%d good patches were rejected %d times.', p, x)
    logging.info('')
    logging.info('Good patch handling time:')
    logging.info('  10th percentile: %.2f hours',
                 numpy.percentile(patch_handle_times, 10) / 3600.0)
    logging.info('  25th percentile: %.2f hours',
                 numpy.percentile(patch_handle_times, 25) / 3600.0)
    logging.info('  50th percentile: %.2f hours',
                 summary['median_handling_time'] / 3600.0)
    logging.info('  75th percentile: %.2f hours',
                 numpy.percentile(patch_handle_times, 75) / 3600.0)
    logging.info('  90th percentile: %.2f hours',
                 numpy.percentile(patch_handle_times, 90) / 3600.0)
    logging.info('')
    logging.info('Time spent in Pre-CQ:')
    logging.info('  10th percentile: %.2f hours',
                 numpy.percentile(pre_cq_handle_times, 10) / 3600.0)
    logging.info('  25th percentile: %.2f hours',
                 numpy.percentile(pre_cq_handle_times, 25) / 3600.0)
    logging.info('  50th percentile: %.2f hours',
                 numpy.percentile(pre_cq_handle_times, 50) / 3600.0)
    logging.info('  75th percentile: %.2f hours',
                 numpy.percentile(pre_cq_handle_times, 75) / 3600.0)
    logging.info('  90th percentile: %.2f hours',
                 numpy.percentile(pre_cq_handle_times, 90) / 3600.0)
    logging.info('')
    logging.info('Time spent waiting for CQ:')
    logging.info('  10th percentile: %.2f hours',
                 numpy.percentile(cq_wait_times, 10) / 3600.0)
    logging.info('  25th percentile: %.2f hours',
                 numpy.percentile(cq_wait_times, 25) / 3600.0)
    logging.info('  50th percentile: %.2f hours',
                 numpy.percentile(cq_wait_times, 50) / 3600.0)
    logging.info('  75th percentile: %.2f hours',
                 numpy.percentile(cq_wait_times, 75) / 3600.0)
    logging.info('  90th percentile: %.2f hours',
                 numpy.percentile(cq_wait_times, 90) / 3600.0)
    logging.info('')
    logging.info('Time spent in CQ:')
    logging.info('  10th percentile: %.2f hours',
                 numpy.percentile(cq_handle_times, 10) / 3600.0)
    logging.info('  25th percentile: %.2f hours',
                 numpy.percentile(cq_handle_times, 25) / 3600.0)
    logging.info('  50th percentile: %.2f hours',
                 numpy.percentile(cq_handle_times, 50) / 3600.0)
    logging.info('  75th percentile: %.2f hours',
                 numpy.percentile(cq_handle_times, 75) / 3600.0)
    logging.info('  90th percentile: %.2f hours',
                 numpy.percentile(cq_handle_times, 90) / 3600.0)
    logging.info('')

    for bot_type, patches in summary['bad_cl_candidates'].items():
      logging.info('%d bad patch candidates were rejected by the %s',
                   len(patches), bot_type)
      for k in patches:
        logging.info('Bad patch candidate in: %s', k)

    fmt_fai = '  %(cnt)d failures in %(reason)s'
    fmt_rej = '  %(cnt)d rejections due to %(reason)s'

    logging.info('Reasons why good patches were rejected:')
    self._PrintCounts(patch_reason_counts, fmt_rej)

    logging.info('Bugs or CLs responsible for good patches rejections:')
    self._PrintCounts(patch_blame_counts, fmt_rej)

    logging.info('Reasons why builds failed:')
    self._PrintCounts(build_reason_counts, fmt_fai)

    return summary


def _CheckOptions(options):
  # Ensure that specified start date is in the past.
  now = datetime.datetime.now()
  if options.start_date and now.date() < options.start_date:
    logging.error('Specified start date is in the future: %s',
                  options.start_date)
    return False

  return True


def GetParser():
  """Creates the argparse parser."""
  parser = commandline.ArgumentParser(description=__doc__)

  ex_group = parser.add_mutually_exclusive_group(required=True)
  ex_group.add_argument('--start-date', action='store', type='date',
                        default=None,
                        help='Limit scope to a start date in the past.')
  ex_group.add_argument('--past-month', action='store_true', default=False,
                        help='Limit scope to the past 30 days up to now.')
  ex_group.add_argument('--past-week', action='store_true', default=False,
                        help='Limit scope to the past week up to now.')
  ex_group.add_argument('--past-day', action='store_true', default=False,
                        help='Limit scope to the past day up to now.')

  parser.add_argument('--cred-dir', action='store', required=True,
                      metavar='CIDB_CREDENTIALS_DIR',
                      help='Database credentials directory with certificates '
                           'and other connection information. Obtain your '
                           'credentials at go/cros-cidb-admin .')
  parser.add_argument('--starting-build', action='store', type=int,
                      default=None, help='Filter to builds after given number'
                                         '(inclusive).')
  parser.add_argument('--end-date', action='store', type='date', default=None,
                      help='Limit scope to an end date in the past.')
  return parser


def main(argv):
  parser = GetParser()
  options = parser.parse_args(argv)

  if not _CheckOptions(options):
    sys.exit(1)

  db = cidb.CIDBConnection(options.cred_dir)

  if options.end_date:
    end_date = options.end_date
  else:
    end_date = datetime.datetime.now().date()

  # Determine the start date to use, which is required.
  if options.start_date:
    start_date = options.start_date
  else:
    assert options.past_month or options.past_week or options.past_day
    if options.past_month:
      start_date = end_date - datetime.timedelta(days=30)
    elif options.past_week:
      start_date = end_date - datetime.timedelta(days=7)
    else:
      start_date = end_date - datetime.timedelta(days=1)

  cl_stats_engine = CLStatsEngine(db)
  cl_stats_engine.Gather(start_date, end_date,
                         starting_build_number=options.starting_build)
  cl_stats_engine.Summarize()
