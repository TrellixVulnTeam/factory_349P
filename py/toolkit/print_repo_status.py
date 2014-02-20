#!/usr/bin/python -Bu
#
# Copyright (c) 2014 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Print the status of factory-related repositories.

This is used to generate the file containing the status of each repositories
in the factory toolkit.
"""


import argparse
import os

import factory_common  # pylint: disable=W0611
from cros.factory.tools.build_board import BuildBoard
from cros.factory.utils.process_utils import CheckOutput


NUM_COMMITS_PER_REPO = 50

SRC = os.path.join(os.environ['CROS_WORKON_SRCROOT'], 'src')
REPOS = ['platform/factory',
         'third_party/autotest/files',
         '%OVERLAY%/chromeos-base/chromeos-factory-board/files']
MERGED_MSG = ['Reviewed-on', 'Marking set of ebuilds as stable']

def GitLog(repo, skip=0, max_count=NUM_COMMITS_PER_REPO, extra_args=None):
  cmd = ['git', 'log', '--max-count', '%d' % max_count, '--skip', '%d' % skip]
  if extra_args:
    cmd.extend(extra_args)
  return CheckOutput(cmd, cwd=repo).strip()

def GetCommitList(repo, skip=0, max_count=NUM_COMMITS_PER_REPO):
  if not max_count:
    return []
  return GitLog(repo, skip=skip, max_count=max_count,
                extra_args=['--oneline']).split('\n')

def GetUncommittedFiles(repo):
  files = CheckOutput(['git', 'status', '--porcelain'], cwd=repo)
  if not files:
    return []
  return files.strip().split('\n')

def GetUnmergedCommits(repo):
  for idx in xrange(NUM_COMMITS_PER_REPO):
    commit_log = GitLog(repo, skip=idx, max_count=1)
    for msg in MERGED_MSG:
      if msg in commit_log:
        return GetCommitList(repo, skip=0, max_count=idx)
  return GetCommitList(repo, skip=0, max_count=NUM_COMMITS_PER_REPO)


def main():
  parser = argparse.ArgumentParser(
      description='Prints the status of factory-related repositories.')
  parser.add_argument('--board', '-b', required=True,
      help='The board to check overlay repositories for.')
  args = parser.parse_args()

  overlay_root = BuildBoard(args.board).overlay_relpath
  for repo in REPOS:
    if '%OVERLAY%' in repo and overlay_root is None:
      raise ValueError('No overlay available for %s!' % args.board)
    repo_path = repo.replace('%OVERLAY%', overlay_root)
    print 'Repository %s' % repo_path
    repo_full_path = os.path.join(SRC, repo_path)

    if not os.path.exists(repo_full_path):
      print '  >>> Repository does not exist'
      continue

    uncommitted = GetUncommittedFiles(repo_full_path)
    if uncommitted:
      print '  >>> Repository contains uncommited changes:'
      for changed_file in uncommitted:
        print '\t%s' % changed_file

    unmerged = GetUnmergedCommits(repo_full_path)
    if unmerged:
      print '  >>> Repository contains %d unmerged commits:' % len(unmerged)
      for commit in unmerged:
        print '\t%s' % commit

    commit_list = GetCommitList(repo_full_path)
    print '  >>> Last %d commits in the repository:' % len(commit_list)
    for commit in commit_list:
      print '\t%s' % commit

    print '\n'


if __name__ == '__main__':
  main()
