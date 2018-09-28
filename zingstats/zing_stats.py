#!/usr/bin/env python2
#
# (c) Copyright 2017,2018 Hewlett Packard Enterprise Development LP
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#
"""
Zing stats reporter

Tool for generating summary stat reports and graphs from Zing data. Initially
using Gerrit data, will consider adding Zuul and Jenkins data also if
necessary.

Terminology:
- A change consists of 1 or more revisions (aka patches)
- Each time CI is triggered on a change, a CI run occurs
- A CI run consists of one or CI jobs e.g. ncs-copyright, ncs-check and so on

"""
# TODO remove duplication in parsing
# TODO add in generic check for CI (user to specify list of files to check for)
from __future__ import division

import argparse
import json
import logging
import os
import re

from collections import defaultdict
from datetime import datetime
from datetime import timedelta

import jinja2
import pandas as pd
import plotly
import requests
from plotly import graph_objs as go

import zingstats.parser
import zingstats.util
import zingstats.changes

CI_FAILURE_STATUSES = ['failed']
CI_SUCCESS_STATUSES = ['succeeded', 'successful', 'ok']

GITHUB_TIMESTAMP = '%Y-%m-%dT%H:%M:%SZ'

ISSUES_URL = 'https://github.com/HewlettPackard/zing-stats/issues'


log = logging.getLogger(__name__)


def main():
    parser = argparse.ArgumentParser(
        description=__doc__,
        epilog="examples:\n"
               "# report stats for last 24 hours in html outputting to\n"
               "/var/www/html/zing/stats\n"
               "./zing_stats.py\n"
               "# report stats for last 24 hours in html (verbose output)\n"
               "# retrieving 100 changes at a time and a max of 100 changes\n"
               "./zing_stats.py -v -n 100 -m 100 -r 24\n"
               "# report stats for last 24 hours in html\n"
               "# retrieve stats for last 24 hours and dump to changes.json\n"
               "./zing_stats.py -r 168 -c > changes.json\n"
               "# analyse stats previously gathered in changes.json\n"
               "./zing_stats.py -r 168 -j changes.json\n"
               "# analyse a set of gerrit and github projects with github auth\n"  # noqa
               "./zing_stats.py --github-host https://github.example.com --github-user username --github-token 3ec57a --gerrit-host https://gerrit.example.com --projects projects.json\n"  # noqa
               "# analyse a set of projects with specified branches (master and devel only)\n"  # noqa
               "./zing_stats.py --github-host https://github.example.com --gerrit-host https://gerrit.example.com --projects projects.json --branch master --branch devel\n",  # noqa
        formatter_class=argparse.RawDescriptionHelpFormatter)
    script_name = __file__
    parser.set_defaults(
        script_dir=os.path.abspath((os.path.dirname(script_name)))
    )
    parser.add_argument('-b', '--branch', dest='branches',
                        action='append',
                        help='Restrict reporting to specified branches ('
                             'defaulting to all branches).')
    parser.add_argument('--gerrit-url', dest='gerrit_url',
                        default=os.getenv('GERRIT_URL',
                                          'https://gerrit.example.net'),
                        help='URL to Gerrit server ('
                             'defaults to GERRIT_URL if set: %(default)s).')
    parser.add_argument('--gerrit-user', dest='gerrit_user',
                        default=os.getenv('GERRIT_USER'),
                        help='Gerrit username ('
                             'defaults to GERRIT_USER if set: %(default)s).')
    parser.add_argument('--gerrit-token', dest='gerrit_token',
                        default=os.getenv('GERRIT_TOKEN'),
                        help='Gerrit auth token or password ('
                             'defaults to GERRIT_TOKEN if set: %(default)s).')
    parser.add_argument('--github-url', dest='github_url',
                        default=os.getenv('GITHUB_URL',
                                          'https://github.example.net'),
                        help='URL to GitHub Enterprise server ('
                             'defaults to GITHUB_URL if set: %(default)s).')
    parser.add_argument('--github-token', dest='github_token',
                        default=os.getenv('GITHUB_TOKEN'),
                        help='GitHub Enterprise auth token or password ('
                             'defaults to GITHUB_TOKEN if set: %(default)s).')
    parser.add_argument('-n', '--gerrit-query-size', dest='gerrit_query_size',
                        type=int, default=100,
                        help='Changes per request (def: %(default)s).')
    parser.add_argument('-m', '--gerrit-max-changes',
                        dest='gerrit_max_changes',
                        type=int,
                        help='Total max changes to pull (optional, no def).')
    parser.add_argument('-v', '--verbose', dest='log_verbosely',
                        action='store_true',
                        help='Show DEBUG level log output on stderr.')
    parser.add_argument('-q', '--quiet', dest='log_quietly',
                        action='store_true',
                        help='Show only ERROR log messages on stderr.')
    parser.add_argument('-t', '--trace', dest='log_trace',
                        action='store_true',
                        help='Show DEBUG level log output on logfile.')
    parser.add_argument('-l', '--logfile',
                        help='''
                        Name of the file to log messages to
                        (def: %(default)s).
                        ''',
                        default='%s.log' %
                        os.path.splitext(os.path.basename(script_name))[0])
    parser.add_argument('-o', '--output-dir', dest='output_dir',
                        default='/var/www/html/zing/stats/',
                        help='Path to output files to (def: %(default)s).')
    parser.add_argument('-s', '--secure', dest='verify_https_requests',
                        action='store_true',
                        help='Verify https requests (def: %(default)s).')
    parser.add_argument('-f', '--format', dest='report_format',
                        help='report format (def: %(default)s)',
                        choices=['html'],
                        default='html')
    parser.add_argument('--report-issue-link', dest='report_issue_link',
                        default=ISSUES_URL,
                        help='Link to defect tracker (def: %(default)s).')
    parser.add_argument('--contact-email', dest='contact_email',
                        default='zing-stats@hpe.com',
                        help='Email address for author (def: %(default)s).')
    parser.add_argument('--report-title', dest='report_title',
                        default='Zing stats',
                        help='Title for html report (def: %(default)s).')
    parser.add_argument('-r', '--report-range-hours', dest='range_hours',
                        type=int, default=168,
                        help='Range for report in hours (def: %(default)s).')
    parser.add_argument('--projects', dest='projects',
                        required=True,
                        help='JSON file listing projects to analyse.')
    parser.add_argument('--html-template', dest='html_template',
                        default=os.path.join(parser.get_default('script_dir'),
                                             'zing_stats.html.j2'),
                        help='Jinja2 template to use for html reports '
                             '(def: %(default)s).')
    parser.add_argument('--system-capacity-daily-ci-hours',
                        dest='system_capacity_daily_ci_hours',
                        type=int, default=504,
                        help='CI system capacity measured in total CI hours'
                             ' available per day e.g. a system with a single '
                             ' slave which can run one job at a time has a '
                             'of 24 hours (def: %(default)s).')
    parser.add_argument('--ci-job-recommended-max-minutes',
                        dest='ci_job_recommended_max_minutes',
                        type=int, default=15,
                        help='Recommended maximum duration for a CI job in '
                             'minutes (def: %(default)s).')
    args = parser.parse_args()

    zingstats.util.configure_logging(args)
    log.debug("Called with args: %s", args)

    if args.branches:
        log.info('Reporting only on changes to these branches: %s',
                 ','.join(args.branches))

    # enable logging multiple columns in output
    pd.set_option('display.width', 1000)

    finish_dt = datetime.now()
    start_dt = finish_dt - timedelta(hours=args.range_hours)
    log.info('Reporting on changes between %s and %s',
             start_dt.strftime('%H:%M:%S %d-%b-%Y'),
             finish_dt.strftime('%H:%M:%S %d-%b-%Y'))

    projects = read_from_json(args.projects)

    gerrit_projects = [x['name'] for x in projects.get('gerrit', dict())]
    gerrit_query = 'status:open OR status:closed'
    session = requests.Session()
    session.verify = args.verify_https_requests
    if len(gerrit_projects) > 0:
        gerrit_changes = zingstats.changes.GerritChanges(args.gerrit_url,
                                                         gerrit_query,
                                                         gerrit_projects,
                                                         args.branches,
                                                         start_dt,
                                                         finish_dt,
                                                         session,
                                                         args.gerrit_query_size,  # noqa
                                                         args.gerrit_max_changes)  # noqa
        if gerrit_changes.gather():
            log.info('Gathered %d total changes', len(gerrit_changes))
        else:
            log.critical('Failed to gather changes, aborting')
            exit(1)
    else:
        gerrit_changes = list()

    if len(projects.get('github')) > 0:
        github_pr_count, github_prs, not_found_proj = \
            gather_github_prs(args, start_dt, projects)
    else:
        github_pr_count = 0
        github_prs = list()
        not_found_proj = list()

    change_count = len(gerrit_changes) + github_pr_count
    df = generate_dataframes(args, get_changes_by_project(gerrit_changes),
                             github_prs, start_dt)

    if args.report_format == 'html':
        write_html(args, df, change_count, start_dt, finish_dt, projects,
                   not_found_proj)


def read_from_json(json_file):
    with open(json_file, 'r') as f:
        data = f.read()
    try:
        json_data = json.loads(data)
    except ValueError:
        log.critical('%s is not well-formed json', json_file)
        exit(1)
    return json_data


def generate_dataframes(args, changes, prs, start_dt):
    """
    Create pandas dataframes for data of interest for subsequent analysis
    by different time periods.
    """

    df = dict()
    for project in sorted(changes):
        df_change_stats = parse_change_stats(args, changes[project], start_dt,
                                             zingstats.changes.GerritChange.GERRIT_FORMAT,  # noqa
                                             parse_change)
        df_ci_stats = parse_ci_stats(changes[project], start_dt)
        project_dataframe(df, df_change_stats, df_ci_stats, project)

    for project in sorted(prs):
        df_change_stats = parse_change_stats(args, prs[project], start_dt,
                                             GITHUB_TIMESTAMP, parse_pr)
        df_ci_stats = parse_pr_ci_stats(prs[project], start_dt)
        project_dataframe(df, df_change_stats, df_ci_stats, project)

    return df


def project_dataframe(df, df_change_stats, df_ci_stats, project):
    if project in df:
        log.error(
            'Already processed %s, is the same project in gerrit and github?',
            project)
        exit(1)
    df[project] = pd.concat([df_change_stats, df_ci_stats])
    df[project].index = pd.to_datetime(df[project].index)
    df[project].sort_index(inplace=True)
    df[project].fillna(value=0, inplace=True)
    log.debug('df[%s]:\n%s', project, df[project])


def write_html(args, df, num_changes, start_dt, finish_dt, projects,
               not_found_proj):
    teams_map = dict()
    teams_map['All'] = list()
    for project in projects['gerrit'] + projects['github']:
        team = project['team']
        name = project['name']
        if team not in teams_map:
            teams_map[team] = list()
        if name not in teams_map['All']:
            teams_map['All'].append(name)
        if name not in teams_map[team]:
            teams_map[team].append(name)

    projects_map = dict()
    for system in ['gerrit', 'github']:
        teams_map[system] = list()
        for project in projects[system]:
            name = project['name']
            projects_map[name] = system
            if name not in teams_map[system]:
                teams_map[system].append(name)
    log.debug('teams map: %s', teams_map)

    if args.range_hours <= 24:
        file_prefix = 'last_%dh' % args.range_hours
    else:
        file_prefix = 'last_%gd' % round((args.range_hours / 24), 1)
    all_projects = teams_map['All']
    for team in sorted(teams_map):
        team_projects = teams_map[team]
        teams = sorted(teams_map.keys())
        # Explicit ordering of some items, better done in the template
        # but not clear how to easily do it
        all_index = teams.index('All')
        teams.insert(0, teams.pop(all_index))
        gerrit_index = teams.index('gerrit')
        teams.insert(1, teams.pop(gerrit_index))
        github_index = teams.index('github')
        teams.insert(2, teams.pop(github_index))

        html = generate_html(args, df, num_changes, start_dt, finish_dt,
                             team_projects, all_projects, projects_map,
                             not_found_proj, team, teams)
        dir_path = os.path.join(args.output_dir, file_prefix)
        if team == 'All':
            file_name = 'index.html'
        else:
            file_name = '%s.html' % re.sub(r'\W+', '_', team.lower())
        file_path = os.path.join(dir_path, file_name)
        if not os.path.exists(dir_path):
            os.makedirs(dir_path)
        with open(file_path, 'w') as f:
            f.write(html)
        log.info('Wrote %s for team: "%s"', file_path, team)


def gather_github_prs(args, oldest_timestamp, projects):
    projects_github = [x['name'] for x in projects.get('github', dict())]

    if len(projects_github) < 1:
        return 0, dict()

    log.info('Gathering PRs from %s for %s', args.github_url,
             ', '.join(sorted(projects_github)))
    total_prs = 0
    prs = dict()
    not_found_proj = list()
    session = requests.Session()
    for project in projects_github:
        prs[project] = dict()

        project_finished = False
        next_page = True

        payload = {'state': 'all', 'sort': 'updated', 'direction': 'dsc'}
        query = ('%s/api/v3/repos/%s/pulls'
                 % (args.github_url, project))
        while next_page:
            if args.github_token:
                payload['access_token'] = args.github_token
                response = session.get(
                    query, params=payload,
                    verify=args.verify_https_requests)
            else:
                response = session.get(query, params=payload,
                                       verify=args.verify_https_requests)
            log.debug(response.url)
            if response.status_code == 404:
                if args.github_token:
                    log.error('Skipping %s (404 while listing PRs, the '
                              '--github-token specified '
                              'does not have access to this project)', project)
                else:
                    log.error('Skipping %s (404 while listing PRs, try '
                              'providing a --github-token '
                              'with access to this project)', project)
                prs.pop(project)
                not_found_proj.append(project)
                break
            results = response.json()
            # TODO use functools and helper function to have log.debug() only
            # resolve the json.dumps() if needed (all usages of this pattern)
            log.debug(json.dumps(results, sort_keys=True, indent=4,
                                 separators=(',', ': ')))
            for pr in results:
                log.debug(json.dumps(pr, sort_keys=True, indent=4,
                                     separators=(',', ': ')))
                if args.branches and pr['base']['ref'] not in args.branches:
                    log.debug(
                        'Skipping %s on %s (not in branches to analyse - %s)',
                        pr['id'], pr['base']['ref'], ','.join(args.branches))
                    continue
                current_timestamp = datetime.strptime(pr['updated_at'],
                                                      GITHUB_TIMESTAMP)
                if current_timestamp < oldest_timestamp:
                    log.debug('%s is older than %s, skip further PRs for %s',
                              current_timestamp, oldest_timestamp, project)
                    results[-1].pop('_more_changes', None)

                    project_finished = True
                    break
                prs[project][pr['id']] = pr

            if project_finished:
                break

            next_page = response.links.get('next', False)
            if next_page:
                query = next_page['url']
                payload['access_token'] = None

        if project in prs:
            log.info('Gathered %d PRs for %s', len(prs[project]), project)
            total_prs += len(prs[project])

    log.info('Gathered %d total PRs', total_prs)

    return total_prs, prs, not_found_proj


def get_changes_by_project(changes):
    """
    Break changes into a dict of dicts keyed by project
    """
    changes_by_project = defaultdict(dict)
    for change in changes:
        changes_by_project[change.project][change.long_id] = change
    return changes_by_project


def parse_change_stats(args, changes, start_dt, ts_format, change_parser):
    """
    Returns a pandas DataFrame with
        a count of changes created
        a count of changes updated
        a count of changes merged
        a count of revisions for each merged change
        lifespan of each merged change (from creation to merging)
        recheck and reverify counts for each merged change
    from the json list of changes passed
    """
    created = defaultdict(int)
    updated = defaultdict(int)
    merged = defaultdict(int)
    revisions = dict()
    lifespan_sec = dict()
    recheck = defaultdict(int)
    reverify = defaultdict(int)

    for change_id in changes:
        session = requests.Session()
        change_parser(args, change_id, changes, created, lifespan_sec, merged,
                      recheck, reverify, revisions, start_dt, ts_format,
                      updated, session)

    d = {'created': created,
         'updated': updated,
         'merged': merged,
         'revisions': revisions,
         'lifespan_sec': lifespan_sec,
         'recheck': recheck,
         'reverify': reverify}

    # specify columns to enforce order, easier for debugging
    df = pd.DataFrame(d,
                      columns=['created',
                               'updated',
                               'merged',
                               'revisions',
                               'lifespan_sec',
                               'recheck',
                               'reverify'])
    log.debug('activity df:\n%s', df)
    return df


def parse_change(args, change_id, changes, created, lifespan_sec, merged,
                 recheck, reverify, revisions, start_dt, ts_format, updated,
                 session):
    change = changes[change_id]
    msg = 'project|change: %s|%s' % (change.project, change.number)
    if change.created_dt >= start_dt:
        created[change.created_dt] += 1
        log.debug('created set to %d for %s', created[change.created_dt], msg)
    if change.updated_dt >= start_dt:
        updated[change.updated_dt] += 1
        log.debug('updated set to %d for %s', updated[change.updated_dt], msg)
    if change.status == 'MERGED' and change.merged_dt >= start_dt:
        merged[change.merged_dt] += 1
        log.debug('merged set to %d for %s', merged[change.merged_dt], msg)
        revisions[change.merged_dt] = change.rev_count()
        lifespan = (change.merged_dt - change.created_dt).total_seconds()
        lifespan_sec[change.merged_dt] = lifespan
        log.debug('age set to %d s for %s', lifespan_sec[change.merged_dt],
                  msg)

        for revision in change.revisions():
            for message in revision.messages():
                msg = 'project|change|rev: %s|%s|%s' %\
                      (change.project, change.number, revision.number)
                if 'recheck' in message.text.lower():
                    recheck[change.merged_dt] += 1
                    log.debug('recheck set to %d for %s',
                              recheck[change.merged_dt], msg)
                elif 'reverify' in message.text.lower():
                    reverify[change.merged_dt] += 1
                    log.debug('reverify set to %d for %s',
                              reverify[change.merged_dt], msg)


def parse_pr(args, pr_id, prs, created, lifespan_sec, merged, recheck,
             reverify, revisions, start_dt, ts_format, updated, session):
    pr = prs[pr_id]
    created_ts = pr['created_at']
    created_dt = datetime.strptime(created_ts, ts_format)
    pr['created_dt'] = created_dt
    updated_ts = pr['updated_at']
    updated_dt = datetime.strptime(updated_ts, ts_format)
    pr['updated_dt'] = updated_dt
    merged_ts = pr['merged_at']
    if pr['merged_at']:
        merged_dt = datetime.strptime(merged_ts, ts_format)
        pr['merged_dt'] = merged_dt
    # Assume we won't have more than 250 commits on a PR for now ...
    commits = github_query(args, pr['commits_url'], session)
    log.debug('commits: %s',
              json.dumps(commits, sort_keys=True, indent=4,
                         separators=(',', ': ')))
    pr['commits'] = commits
    comments = github_query(args, pr['comments_url'], session)
    log.debug('comments: %s',
              json.dumps(comments, sort_keys=True, indent=4,
                         separators=(',', ': ')))
    pr['comments'] = comments
    msg_details = 'project|pr|id: %s|%s|%s' % (
        pr['base']['repo']['full_name'], pr['number'], pr_id)
    if created_dt >= start_dt:
        created[created_ts] += 1
        log.debug('created set to %d with %s',
                  created[created_ts],
                  msg_details)
    if updated_dt >= start_dt:
        updated[updated_ts] += 1
        log.debug('updated set to %d with %s',
                  updated[updated_ts],
                  msg_details)
    if pr['merged_at'] and merged_dt >= start_dt:
        merged[merged_ts] += 1
        log.debug('merged set to %d with %s',
                  merged[merged_ts],
                  msg_details)

        revisions[merged_ts] = len(commits)

        lifespan_sec[merged_ts] = (
            merged_dt - created_dt).total_seconds()
        log.debug('pr lifespan set to %d with %s',
                  lifespan_sec[merged_ts],
                  msg_details)

        for comment in comments:
            msg_details = 'project|pr|id|comment: %s|%s|%s|%s' % (
                pr['base']['repo']['full_name'], pr['number'], pr_id,
                comment['id'])

            if 'recheck' in comment['body'].lower():
                recheck[merged_ts] += 1
                log.debug(
                    'recheck updated to %d with %s',
                    recheck[merged_ts],
                    msg_details)
            elif 'reverify' in comment['body'].lower():
                reverify[merged_ts] += 1
                log.debug(
                    'reverify updated to %d with %s',
                    reverify[merged_ts],
                    msg_details)


def github_query(args, query_url, session):
    if args.github_token:
        payload = {'access_token': args.github_token}
        response = session.get(query_url,
                               verify=args.verify_https_requests,
                               params=payload)
    else:
        response = session.get(query_url,
                               verify=args.verify_https_requests)
    log.debug('github query url: %s', response.url)
    return response.json()


def parse_ci_stats(changes, start_dt):
    """
    Returns a pandas DataFrame with
        sum of the ci time for all ci jobs for each merged change
        the time for the longest job for each merged change
        success and failure counts for each ci run of each updated change
    from the json list of changes passed
    """
    ci_total_time_sec = defaultdict(int)
    ci_longest_time_sec = defaultdict(int)
    ci_success = defaultdict(int)
    ci_failure = defaultdict(int)
    promotion_success = defaultdict(int)
    promotion_failure = defaultdict(int)
    for gerrit_id in changes:
        change = changes[gerrit_id]
        log.debug('change: %s', change.long_id)
        for revision in change.revisions():
            for message in revision.messages():
                log.debug('message: %s', message.text)

                # TODO refactor injection of custom parsing in a generic way
                # e.g. using a plugins structure, promotions may be very
                # specific to some systems (as are the promotion messages)
                promotion_succeeded = \
                    zingstats.parser.parse_promotion_success(message.text)
                if promotion_succeeded and message.message_dt > start_dt:
                    log.debug('%s %s (%s): promotion succeeded',
                              change.project, change.number,
                              message.message_dt)
                    promotion_success[message.message_dt] += 1
                promotion_failed = \
                    zingstats.parser.parse_promotion_failure(message.text)
                if promotion_failed and message.message_dt > start_dt:
                    log.debug('%s %s (%s): promotion failed', change.project,
                              change.number, message.message_dt)
                    promotion_failure[message.message_dt] += 1

                ci_run = zingstats.parser.parse_ci_job_comments(message)
                log.debug('ci_run: %s', ci_run)
                if ci_run:
                    # ignore messages on changes that are older than start time
                    if message.message_dt < start_dt:
                        log.debug('discarding message on proj|change|rev|run: '
                                  '%s|%s|%s|%s with date %s',
                                  change.project,
                                  change.long_id,
                                  revision.number,
                                  ci_run['num'],
                                  message.message_dt)
                        continue

                    status = re.sub(r'\W+', '', ci_run['status'].lower())
                    if status in CI_SUCCESS_STATUSES:
                        ci_success[change.updated_dt] += 1
                        log.debug(
                            debug_msg_gerrit('ci_success',
                                             ci_success[change.updated_dt],
                                             'run',
                                             change,
                                             revision,
                                             ci_run['num'],
                                             'status: ' + ci_run['status']))
                    elif status in CI_FAILURE_STATUSES:
                        ci_failure[change.updated_dt] += 1
                        log.debug(
                            debug_msg_gerrit('ci_failure',
                                             ci_failure[change.updated_dt],
                                             'run',
                                             change,
                                             revision,
                                             ci_run['num'],
                                             'status: ' + ci_run['status']))
                    else:
                        # TODO add extra status to appropriate path above
                        log.warn('Unexpected status %s for %s on %s, skipping',
                                 ci_run['status'], ci_run['num'],
                                 change.change_id)
                        continue

                    if change.status == 'MERGED':
                        for ci_job in ci_run['jobs']:
                            ci_total_time_sec[change.merged_dt] += ci_job[
                                'total_sec']
                            log.debug(
                                debug_msg_gerrit('ci_total_time_sec',
                                                 ci_total_time_sec[change.merged_dt],  # noqa
                                                 'job',
                                                 change,
                                                 revision,
                                                 ci_job['name'],
                                                 str(ci_job['total_sec']) + 's'))  # noqa

                            # this could end up being the longest job across
                            # multiple changes if two changes merge at the same
                            # time (to the microsecond), so not going to worry
                            # about that for now but log what we're doing so
                            # someone can debug this in future
                            if (ci_job['total_sec'] >
                                    ci_longest_time_sec[change.merged_dt]):
                                ci_longest_time_sec[change.merged_dt] = ci_job[
                                    'total_sec']
                                log.debug(
                                    debug_msg_gerrit('ci_longest_time_sec',
                                                     ci_longest_time_sec[change.merged_dt],  # noqa
                                                     'job',
                                                     change,
                                                     revision,
                                                     ci_job['name'],
                                                     str(ci_job['total_sec']) + 's'))  # noqa

    d = {'ci_total_time_sec': ci_total_time_sec,
         'ci_longest_time_sec': ci_longest_time_sec,
         'ci_success': ci_success,
         'ci_failure': ci_failure,
         'promotion_success': promotion_success,
         'promotion_failure': promotion_failure}

    df = pd.DataFrame(d, columns=['ci_total_time_sec', 'ci_longest_time_sec',
                                  'ci_success', 'ci_failure',
                                  'promotion_success', 'promotion_failure'])
    log.debug('ci time status df:\n%s', df)
    return df


def parse_pr_ci_stats(prs, start_dt):
    """
    Returns a pandas DataFrame with
        sum of the ci time for all ci jobs for each merged pr
        the time for the longest job for each merged pr
        success and failure counts for each ci run of each updated pr
    from the list of prs passed
    """
    ci_total_time_sec = defaultdict(int)
    ci_longest_time_sec = defaultdict(int)
    ci_success = defaultdict(int)
    ci_failure = defaultdict(int)
    promotion_success = defaultdict(int)
    promotion_failure = defaultdict(int)
    for pr_id in prs:
        pr = prs[pr_id]
        log.debug("pr %d", pr_id)
        for comment in pr['comments']:
            log.debug('comment: %s', comment)
            comment_ts = comment['created_at']
            comment_dt = datetime.strptime(comment_ts, GITHUB_TIMESTAMP)

            # TODO refactor for injection of custom parsing in a generic way
            # e.g. using some kind of plugins structure, promotions may be very
            # specific to some systems (as are the promotion messages)
            promotion_succeeded = \
                zingstats.parser.parse_promotion_success(comment['body'])
            if promotion_succeeded and comment_dt > start_dt:
                log.debug('%s %s (%s): promotion success',
                          pr['base']['repo']['full_name'], pr['number'],
                          comment_dt)
                promotion_success[comment_ts] += 1
            promotion_failed = \
                zingstats.parser.parse_promotion_failure(comment['body'])
            if promotion_failed and comment_dt > start_dt:
                log.debug('%s %s (%s): promotion failure',
                          pr['base']['repo']['full_name'], pr['number'],
                          comment_dt)
                promotion_failure[comment_ts] += 1

            ci_run = zingstats.parser.parse_pr_message(comment)
            log.debug('ci_run: %s', ci_run)
            if ci_run:
                log.debug(ci_run)
                ci_run_ts = comment['created_at']
                ci_run_dt = datetime.strptime(ci_run_ts, GITHUB_TIMESTAMP)

                msg_details = 'project|pr|id|comment: %s|%s|%s|%s' % (
                    pr['base']['repo']['full_name'], pr['number'], pr_id,
                    comment['id'])

                # ignore messages on changes that are older than our start time
                # TODO (use comment_dt here and retire ci_run_ts and ci_run_dt)
                if ci_run_dt < start_dt:
                    log.debug('discarding comment on %s with date %s',
                              msg_details, ci_run_ts)
                    continue

                updated_ts = pr['updated_at']

                status = re.sub(r'\W+', '', ci_run['status'].lower())
                if status in CI_SUCCESS_STATUSES:
                    ci_success[updated_ts] += 1
                    log.debug(
                        debug_msg_github('ci_success', ci_success[updated_ts],
                                         'run', pr, comment, None,
                                         'status: ' + ci_run['status']))
                elif status in CI_FAILURE_STATUSES:
                    ci_failure[updated_ts] += 1
                    log.debug(
                        debug_msg_github('ci_failure', ci_failure[updated_ts],
                                         'run', pr, comment, None,
                                         'status: ' + ci_run['status']))
                else:
                    # TODO add extra status to appropriate path above
                    log.warn('Unexpected status %s for %s on %s, skipping',
                             ci_run['status'], pr['number'],
                             pr['base']['repo']['full_name'])
                    continue

                if pr['merged_at']:
                    merged_ts = pr['merged_at']
                    for ci_job in ci_run['jobs']:
                        ci_total_time_sec[merged_ts] += ci_job[
                            'total_sec']
                        log.debug(
                            debug_msg_github('ci_total_time_sec',
                                             ci_total_time_sec[merged_ts],
                                             'job', pr, comment,
                                             ci_job['name'],
                                             str(ci_job['total_sec']) + 's'))  # noqa

                        # this could end up being the longest job across
                        # multiple changes if two changes merge at the same
                        # time (to the microsecond), so not going to worry
                        # about that for now but log what we're doing so
                        # someone can debug this in future
                        if (ci_job['total_sec'] >
                                ci_longest_time_sec[merged_ts]):
                            ci_longest_time_sec[merged_ts] = ci_job[
                                'total_sec']
                            log.debug(
                                debug_msg_github('ci_longest_time_sec',
                                                 ci_longest_time_sec[merged_ts],  # noqa
                                                 'job', pr, comment,
                                                 ci_job['name'],
                                                 str(ci_job['total_sec']) + 's'))  # noqa

    d = {'ci_total_time_sec': ci_total_time_sec,
         'ci_longest_time_sec': ci_longest_time_sec,
         'ci_success': ci_success,
         'ci_failure': ci_failure,
         'promotion_success': promotion_success,
         'promotion_failure': promotion_failure}

    df = pd.DataFrame(d, columns=['ci_total_time_sec', 'ci_longest_time_sec',
                                  'ci_success', 'ci_failure',
                                  'promotion_success', 'promotion_failure'])
    log.debug('ci time status df:\n%s', df)
    return df


def debug_msg_gerrit(field, counter, job_or_run, change, revision, name,
                     value):
    return debug_msg(field, counter, job_or_run, change.project,
                     change.number, revision.number, name, value)


def debug_msg_github(field, counter, job_or_run, pr, comment,
                     ci_name, ci_val):
    return debug_msg(field, counter, job_or_run,
                     pr['base']['repo']['full_name'], pr['id'], comment['id'],
                     ci_name, ci_val)


def debug_msg(field, counter, job_or_run, project_name, change_id, message_id,
              ci_name, ci_val):
    msg = '%s updated to %d with proj|change|rev|%s: %s|%s|%s|%s and %s' % (
        field,
        counter,
        job_or_run,
        project_name,
        change_id,
        message_id,
        ci_name,
        ci_val)
    return msg


def generate_html(args, df, num_changes, start_dt, finish_dt,
                  projects, all_projects, projects_map,
                  not_found_proj, group=None, groups=[]):
    """
    Returns html report from a dataframe for a specific project
    """
    log.debug('Generating %s report for %s', args.report_format, group)

    frames = list()
    log.debug(projects)
    if group:
        # we want to report on the projects that are common to projects and df
        projects_to_report = list(set(projects).intersection(df))
    else:
        projects_to_report = projects

    for project in projects_to_report:
        log.debug('%s df:\n%s', project, df[project])
        frames.append(df[project])

    # TODO wrap this in proper html or a template
    if len(frames) <= 0:
        return 'No projects in this group'
    df['total'] = pd.concat(frames)
    df['total'].sort_index(inplace=True)
    log.debug('total df:\n%s', df['total'])

    # resample data for plots
    # for 24 hours or less, use units of 1 hours, otherwise use units of 1 day
    if args.range_hours <= 24:
        sample_window = '1H'
    else:
        sample_window = '1D'
    df_plot = df['total'][df['total'].index > start_dt]
    df_plot = df_plot.resample(sample_window).agg(({
        'created': 'sum',
        'merged': 'sum',
        'updated': 'sum',
        'ci_total_time_sec': 'sum',
        'ci_longest_time_sec': 'max',
        'ci_success': 'sum',
        'ci_failure': 'sum',
        'promotion_success': 'sum',
        'promotion_failure': 'sum',
        'lifespan_sec': 'max',
        'recheck': 'sum',
        'reverify': 'sum',
        'revisions': 'mean',
    })).fillna(0)
    df_plot['pct_success'] = (df_plot['ci_success'] /
                              (df_plot['ci_failure'] +
                               df_plot['ci_success'])) * 100
    df_plot['pct_failure'] = (df_plot['ci_failure'] /
                              (df_plot['ci_failure'] +
                               df_plot['ci_success'])) * 100
    df_plot['ci_total_time_min'] = df_plot['ci_total_time_sec'] / 60
    df_plot['ci_longest_time_min'] = df_plot['ci_longest_time_sec'] / 60
    df_plot.fillna(value=0, inplace=True)
    log.debug('df plot= %s', df_plot)

    with open(args.html_template, 'r') as f:
        html_template = f.read()
    template = jinja2.Template(html_template)
    if args.range_hours <= 24:
        title_units = '%d hours' % args.range_hours
    else:
        title_units = '%g days' % (args.range_hours / 24)
    html = template.render(
        title='%s for last %s' % (args.report_title, title_units),
        group_list=groups,
        current_group=group,
        df=df,
        projects_to_report=projects_to_report,
        all_projects=all_projects,
        num_changes=num_changes,
        start_dt=start_dt,
        finish_dt=finish_dt,
        report_issue_link=args.report_issue_link,
        contact_email=args.contact_email,
        changes_plot=plot_changes(df_plot, group),
        ci_capacity_plot=plot_ci_capacity(args, df_plot, group),
        ci_job_time_plot=plot_ci_job_time(args, df_plot, group),
        status_plot=plot_ci_success_failure(df_plot, group),
        projects_map=projects_map,
        not_found_proj=not_found_proj,
        zs_ver=os.getenv('TAG', ''))
    return html


def plot_ci_success_failure(df_plot, group):
    # https://plot.ly/python/filled-area-plots/#stacked-area-chart-with-cumulative-values
    # Add data to create cumulative stacked values
    y0_stck = df_plot['pct_success']
    y1_stck = [y0 + y1 for y0, y1 in
               zip(df_plot['pct_success'],
                   df_plot['pct_failure'])]
    # Make original values strings and add % for hover text
    y0_txt = [str(y0) + '%' for y0 in df_plot['pct_success']]
    y1_txt = [str(y1) + '%' for y1 in df_plot['pct_failure']]
    ci_success_line = go.Scatter(
        name='Success',
        x=df_plot.index,
        y=y0_stck,
        text=y0_txt,
        hoverinfo='x+text',
        mode='lines',
        line=dict(width=0.5,
                  color='rgb(170, 255, 217)'),
        fill='tonexty')
    ci_failure_line = go.Scatter(
        name='Failure',
        x=df_plot.index,
        y=y1_stck,
        text=y1_txt,
        hoverinfo='x+text',
        mode='lines',
        line=dict(width=0.5,
                  color='rgb(255, 174, 170)'),
        fill='tonexty')
    plot_title = "CI Success/Fail Rates (%s projects)" % group
    status_plot = plotly.offline.plot(
        {
            "data": [ci_success_line, ci_failure_line],
            "layout": go.Layout(
                title=plot_title,
                showlegend=True,
                yaxis=dict(
                    type='linear',
                    range=[1, 100],
                    dtick=10,
                    ticksuffix='%'
                )
            )
        },
        show_link=False,
        output_type='div',
        include_plotlyjs='False')
    return status_plot


def plot_ci_job_time(args, df_plot, group):
    ci_job_recommended_max_line = {
        'type': 'line',
        'x0': df_plot.index.min(),
        'y0': args.ci_job_recommended_max_minutes,
        'x1': df_plot.index.max(),
        'y1': args.ci_job_recommended_max_minutes,
        'line': {
            'color': 'rgb(230, 126, 34)',
            'width': 2,
            'dash': 'dot'}}
    ci_job_recommended_max_label = go.Scatter(
        x=[df_plot.index.min() + 1],
        y=[args.ci_job_recommended_max_minutes +
           (args.ci_job_recommended_max_minutes * 0.05)],
        mode='text',
        text=['Recommended maximum (%d min)' %
              args.ci_job_recommended_max_minutes],
        textposition='top',
        textfont=dict(color='#e67e22'))
    ci_longest_job_line = go.Scatter(
        name='Longest CI job',
        marker=dict(
            color='rgb(142, 68, 173)'
        ),
        x=df_plot.index,
        y=df_plot['ci_longest_time_min'])
    plot_title = "CI Longest Job Duration (%s projects)" % group
    ci_job_time_plot = plotly.offline.plot(
        {
            "data": [ci_longest_job_line, ci_job_recommended_max_label],
            "layout": go.Layout(
                title=plot_title,
                shapes=[ci_job_recommended_max_line],
                yaxis=dict(title='Duration (min)'),
                showlegend=False)
        },
        show_link=False,
        output_type='div',
        include_plotlyjs='False')
    return ci_job_time_plot


def plot_ci_capacity(args, df_plot, group):
    system_capacity_max_ci_minutes = args.system_capacity_daily_ci_hours * 24
    ci_75pct_capacity_line = {
        'type': 'line',
        'x0': df_plot.index.min(),
        'y0': system_capacity_max_ci_minutes,
        'x1': df_plot.index.max(),
        'y1': system_capacity_max_ci_minutes,
        'line': {
            'color': 'rgb(231, 76, 60)',
            'width': 2,
            'dash': 'dot'}}
    ci_75pct_capacity_line_label = go.Scatter(
        x=[df_plot.index.min() + 1],
        y=[system_capacity_max_ci_minutes +
           (system_capacity_max_ci_minutes * 0.05)],
        mode='text',
        text=['75% of CI Capacity'],
        textposition='top',
        textfont=dict(color='#e74c3c'))
    ci_total_time_bar = go.Bar(
        name='Total CI time',
        marker=dict(color='rgb(55, 83, 109)'),
        x=df_plot.index,
        y=df_plot['ci_total_time_min'])
    plot_title = "CI system capacity (%s projects)" % group
    ci_capacity_plot = plotly.offline.plot(
        {
            "data": [ci_total_time_bar, ci_75pct_capacity_line_label],
            "layout": go.Layout(
                title=plot_title,
                shapes=[ci_75pct_capacity_line],
                yaxis=dict(title='CI time (min)'),
                showlegend=False)
        },
        show_link=False,
        output_type='div',
        include_plotlyjs='False')
    return ci_capacity_plot


def plot_changes(df_plot, group):
    created_line = go.Scatter(
        name='Created',
        x=df_plot.index,
        y=df_plot['created'])
    submitted_line = go.Scatter(
        name='Merged',
        x=df_plot.index,
        y=df_plot['merged'])
    updated_line = go.Scatter(
        name='Updated',
        x=df_plot.index,
        y=df_plot['updated'])
    plot_title = "Changes/PRs (%s projects)" % group
    changes_plot = plotly.offline.plot(
        {
            "data": [created_line, submitted_line, updated_line],
            "layout": go.Layout(title=plot_title)
        },
        show_link=False,
        output_type='div',
        include_plotlyjs='False')
    return changes_plot


def generate_json(df_changes_by_project):
    """
    Returns pretty printed json of combined dataframes for all projects
    """
    frames = list()
    for project in sorted(df_changes_by_project):
        df = df_changes_by_project[project]
        frames.append(df)
    df = pd.concat(frames)
    df = df.resample('1H').apply(({
        'created': 'sum',
        'merged': 'sum',
        'updated': 'sum',
        'ci_total_time_sec': 'sum',
        'ci_longest_time_sec': 'max',
        'ci_success': 'sum',
        'ci_failure': 'sum',
        'lifespan_sec': 'max',
        'recheck': 'sum',
        'reverify': 'sum',
        'revisions': 'mean',
    })).fillna(0)
    df_as_json = json.loads(df.to_json(orient='index', date_format='iso'))
    return(json.dumps(df_as_json,
                      sort_keys=True,
                      indent=4,
                      separators=(',', ': ')))


if __name__ == "__main__":
    main()
