#!/usr/bin/env python2
#
# (c) Copyright 2017 Hewlett Packard Enterprise Development LP
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
from __future__ import division

import argparse
from collections import defaultdict
from datetime import datetime
from datetime import timedelta
import itertools
import jinja2
import json
import logging
import os
import pandas as pd
import plotly
from plotly import graph_objs as go
import re
import requests
import sys

# need to drop last few digits to make microseconds from nanoseconds
# e.g. datetime.strptime(change['created'][:-3], GERRIT_TIMESTAMP)
GERRIT_TIMESTAMP = '%Y-%m-%d %H:%M:%S.%f'

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
               "./zing_stats.py -r 168 -j changes.json\n",
        formatter_class=argparse.RawDescriptionHelpFormatter)
    script_name = __file__
    parser.set_defaults(
        script_dir=os.path.abspath((os.path.dirname(script_name)))
    )
    parser.add_argument('--gerrit-host', dest='gerrit_url',
                        default='https://gerrit.example.net',
                        help='Gerrit host (def: %(default)s).')
    parser.add_argument('--gerrit-user', dest='gerrit_user',
                        default=os.environ['LOGNAME'],
                        help='Auth username (def: %(default)s).')
    parser.add_argument('--gerrit-token', dest='gerrit_token',
                        help='Auth token or password.')
    parser.add_argument('--github-host', dest='github_url',
                        default='https://github.example.net',
                        help='Github host (def: %(default)s).')
    parser.add_argument('--github-user', dest='github_user',
                        default=os.environ['LOGNAME'],
                        help='Auth username (def: %(default)s).')
    parser.add_argument('--github-token', dest='github_token',
                        help='Auth token or password def: %(default)s).')
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
                        help='Show TRACE level output in logfile.')
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
    parser.add_argument('--no-log', dest='no_logfile', action='store_true',
                        help='Do not write log output to file.')
    parser.add_argument('-s', '--secure', dest='verify_https_requests',
                        action='store_true',
                        help='Verify https requests (def: %(default)s).')
    parser.add_argument('-f', '--format', dest='report_format',
                        help='report format (def: %(default)s)',
                        choices=['html', 'json'],
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
    parser.add_argument('--projects-gerrit', dest='proj_gerrit',
                        help='JSON file listing gerrit projects to analyse.')
    parser.add_argument('--projects-github', dest='proj_github',
                        help='JSON file listing github projects to analyse.')
    parser.add_argument('--project-map', dest='proj_map',
                        help='JSON file mapping projects to teams for html'
                             'reports (optional).')
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
    configure_logging(args)
    log.debug("Called with args: %s", args)

    # enable logging multiple columns in output
    pd.set_option('display.width', 1000)

    finish_dt = datetime.now()
    start_dt = finish_dt - timedelta(hours=args.range_hours)
    log.info('Reporting on changes between %s and %s',
             start_dt.strftime('%H:%M:%S %d-%b-%Y'),
             finish_dt.strftime('%H:%M:%S %d-%b-%Y'))

    projects = dict()
    if args.proj_gerrit:
        projects['gerrit'] = read_from_json(args.proj_gerrit)
    else:
        projects['gerrit'] = dict()

    if args.proj_github:
        projects['github'] = read_from_json(args.proj_github)
    else:
        projects['github'] = dict()

    if not (args.proj_gerrit or args.proj_github):
        log.critical('At least one of --projects-gerrit or --projects-github must be specified')
        exit(1)

    # total_gerrit_changes = 0
    # gerrit_changes = dict()
    total_gerrit_changes, gerrit_changes = gather_gerrit_changes(args, start_dt, projects['gerrit'])

    # total_github_prs = 0
    # github_prs = dict()
    total_github_prs, github_prs = gather_github_prs(args, start_dt, projects['github'])

    df = dict()
    for project in sorted(gerrit_changes):
        df[project] = generate_dataframes_gerrit(gerrit_changes[project], start_dt)
        log.debug('%s df:\n%s', project, df[project])

    # TODO see if this can be combined with the above
    for project in sorted(github_prs):
        df[project] = generate_dataframes_github(args, github_prs[project], start_dt)
        log.debug('%s df:\n%s', project, df[project])

    proj_map = None
    if args.proj_map:
        log.info('Reading project/team mappings from %s', args.proj_map)
        proj_map = read_from_json(args.proj_map)

    if args.range_hours <= 24:
        file_prefix = 'last_%dh' % args.range_hours
    else:
        file_prefix = 'last_%gd' % round((args.range_hours / 24), 1)

    if args.report_format == 'html':
        write_html(args, df, file_prefix, total_gerrit_changes,
                   start_dt, finish_dt, projects['gerrit'], proj_map)

    elif args.report_format == 'json':
        write_json(args, df, file_prefix)


def read_from_json(json_file):
    proj_map = None
    with open(json_file, 'r') as f:
        json_data = f.read()
    try:
        proj_map = json.loads(json_data)
    except ValueError:
        log.critical('%s is not well-formed json', json_file)
        exit(1)
    return proj_map


def write_html(args, df, file_prefix, num_changes, start_dt, finish_dt,
               all_projects, proj_map):
    if proj_map:
        # convert project maps to groups into group map to projects
        group_map = dict()
        for group in set(proj_map.values()):
            group_map[group] = list()
            for project in proj_map:
                if proj_map[project] == group:
                    group_map[group].append(project)

        # and add an all group for all projects
        group_map['All'] = proj_map.keys()
        log.debug('group_map: %s', group_map)

        for group in group_map:
            projects = group_map[group]
            groups = group_map.keys()
            html = generate_html(args, df, num_changes, start_dt, finish_dt,
                                 projects, all_projects, group, groups)
            dir_path = os.path.join(args.output_dir, file_prefix)
            if group == 'All':
                file_name = 'index.html'
            else:
                file_name = '%s.html' % group.lower()
            file_path = os.path.join(dir_path, file_name)
            if not os.path.exists(dir_path):
                os.makedirs(dir_path)
            with open(file_path, 'w') as f:
                f.write(html)
            log.info('Wrote %s for %s group', file_path, group)
    else:
        dir_path = os.path.join(args.output_dir, file_prefix)
        file_name = 'index.html'
        file_path = os.path.join(dir_path, file_name)
        if not os.path.exists(dir_path):
            os.makedirs(dir_path)
        html = generate_html(args, df, num_changes, start_dt, finish_dt,
                             df.keys(), all_projects, 'All')
        with open(file_path, 'w') as f:
            f.write(html)
        log.info('Wrote %s', file_path)


def write_json(args, df, file_prefix):
    dir_path = os.path.join(args.output_dir)
    file_name = '%s.json' % file_prefix
    file_path = os.path.join(dir_path, file_name)
    if not os.path.exists(dir_path):
        os.makedirs(dir_path)
    df_as_json = generate_json(df)
    with open(file_path, 'w') as f:
        f.write(df_as_json)
    log.info('Wrote %s', file_path)


def gather_github_prs(args, oldest_timestamp, projects_github):
    if len(projects_github) < 1:
        return 0, dict()

    log.info('Gathering PRs from %s for %s', args.github_url,
             ', '.join(sorted(projects_github)))
    total_prs = 0
    prs = dict()
    for project in projects_github:
        prs[project] = dict()

        project_finished = False
        next_page = True

        payload = {'state': 'all', 'sort': 'updated', 'direction': 'dsc'}
        query = ('%s/api/v3/repos/%s/pulls'
                 % (args.github_url, project))
        while next_page:
            if args.github_user and args.github_token:
                response = requests.get(
                    query, params=payload,
                    verify=args.verify_https_requests,
                    auth=(args.github_user, args.github_token))
            else:
                response = requests.get(query, params=payload,
                                        verify=args.verify_https_requests)
            log.debug(response.url)
            if response.status_code == 404:
                log.error('Skipping %s (404 while listing PRs, try providing '
                          '--github-user and --github-token)')
                break
            results = response.json()
            log.debug(json.dumps(results, sort_keys=True, indent=4,
                                 separators=(',', ': ')))
            for pr in results:
                log.debug(json.dumps(pr, sort_keys=True, indent=4,
                                     separators=(',', ': ')))
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
                payload = None

        log.info('Gathered %d PRs for %s', len(prs[project]), project)
        total_prs += len(prs[project])

    log.info('Gathered %d total PRs', total_prs)

    return total_prs, prs


# TODO add support for gerrit user and password (check if ever useful)
def gather_gerrit_changes(args, oldest_timestamp, projects_gerrit):
    if len(projects_gerrit) < 1:
        return 0, dict()

    log.info('Gathering gerrit changes from %s for %s', args.gerrit_url,
             ', '.join(sorted(projects_gerrit)))
    start = 0
    count = args.gerrit_query_size
    results = [{'_more_changes': True}]
    changes = dict()
    while '_more_changes' in results[-1].keys() and \
            results[-1]['_more_changes']:
        log.debug('Querying %d changes starting at %d', count, start)
        payload = {'q': 'status:open OR status:closed',
                   'o': ['ALL_REVISIONS', 'MESSAGES'],
                   'start': start,
                   'n': count}
        query = ('%s/changes/' % args.gerrit_url)
        response = requests.get(query, params=payload,
                                verify=args.verify_https_requests)
        log.debug(response.url)
        # strip magic junk off the start of the gerrit response
        results = json.loads(response.text[5:])
        log.debug(json.dumps(results, sort_keys=True, indent=4,
                             separators=(',', ': ')))
        for change in results:
            log.debug(json.dumps(change, sort_keys=True, indent=4,
                                 separators=(',', ': ')))
            log.debug('%d changes (start: %d, count=%d)', len(results),
                      start, count)
            if change['project'] not in projects_gerrit:
                log.debug('Skipping %s as %s not in projects of interest',
                          change['id'], change['project'])
                continue
            if change['id'] in changes:
                log.debug(json.dumps(change,
                                     sort_keys=True,
                                     indent=4,
                                     separators=(',', ': ')))
                # TODO when this occurs, investigate further
                log.warn('id %s has already been seen, skipping this change',
                         change['id'])
                continue

            changes[change['id']] = change
            if args.gerrit_max_changes and \
                    len(changes) >= args.gerrit_max_changes:
                log.warn('--gerrit-max-changes specified, not pulling more '
                         'than %d changes', args.gerrit_max_changes)
                results[-1].pop('_more_changes', None)
                break

            current_timestamp = datetime.strptime(change['updated'][:-3],
                                                  GERRIT_TIMESTAMP)
            if current_timestamp < oldest_timestamp:
                log.debug('%s is older than %s, not reading any more changes',
                          current_timestamp, oldest_timestamp)
                results[-1].pop('_more_changes', None)
                break
        start += count

    total_changes = len(changes)
    log.info('Gathered %d total changes', total_changes)

    return total_changes, get_changes_by_project(changes)


def get_changes_by_project(changes):
    """
    Break changes into a dict of dicts keyed by project
    """
    changes_by_project = defaultdict(dict)
    for gerrit_id in changes:
        change = changes[gerrit_id]
        project = change['project']
        changes_by_project[project][gerrit_id] = change
    return changes_by_project


def parse_ci_job_comments(msg):
    """
    Parse gerrit change messages that look like CI job messages,
    extracting CI job data and returning as a dict
    """

    # TODO refactor to take a list of patterns for runs and jobs (ultimately
    # taken from a config parameter/file)
    ci_run_patt = 'Patch Set (?P<num>\d+): Verified(?P<v_score>\S+)\s+Build (?P<status>\S+)\s+(?P<jobs>.+)'  # noqa
    ci_run_re = re.compile(ci_run_patt, re.MULTILINE | re.DOTALL)
    ci_job_v1_patt = '^- (?P<proto>.+)?://(?P<jenkins_path>.+)?/job/(?P<name>\S+)/\d+/ : (?P<result>\S+) in (?P<time_h>\d+h )?(?P<time_m>\d+m )?(?P<time_s>\d+s)(?P<non_voting> \(non\-voting\))?(?P<the_rest>.*)$'  # noqa
    ci_job_v1_re = re.compile(ci_job_v1_patt, re.MULTILINE)
    ci_job_v2_patt = '^- (?P<proto>.+)?://(?P<logs_path>.+)?/(?P<name>\D+) : (?P<result>\S+) in (?P<time_h>\d+h )?(?P<time_m>\d+m )?(?P<time_s>\d+s)(?P<non_voting> \(non\-voting\))?(?P<the_rest>.*)$'  # noqa
    ci_job_v2_re = re.compile(ci_job_v2_patt, re.MULTILINE)

    run = dict()
    ci_run_match = ci_run_re.match(msg['message'])
    if ci_run_match:
        #run['date'] = msg['date']
        run['num'] = ci_run_match.group('num')
        run['v_score'] = ci_run_match.group('v_score')
        run['status'] = ci_run_match.group('status')

        run['jobs'] = list()
        for ci_job_match in itertools.chain(
                ci_job_v1_re.finditer(ci_run_match.group('jobs')),
                ci_job_v2_re.finditer(ci_run_match.group('jobs'))):
            job = dict()
            job['name'] = ci_job_match.group('name')
            job['result'] = ci_job_match.group('result')

            # mash time fields together into total seconds for job
            job['total_sec'] = 0
            ci_job_time_h = ci_job_match.group('time_h')
            ci_job_time_m = ci_job_match.group('time_m')
            ci_job_time_s = ci_job_match.group('time_s')

            if ci_job_time_h:
                job['total_sec'] += \
                    int(str(ci_job_time_h).strip().rstrip('h')) * 3600
            if ci_job_time_m:
                job['total_sec'] += \
                    int(str(ci_job_time_m).strip().rstrip('m')) * 60
            if ci_job_time_s:
                job['total_sec'] += \
                    int(str(ci_job_time_s).strip().rstrip('s'))

            job['non_voting'] = ci_job_match.group('non_voting')
            if len(ci_job_match.group('the_rest')) > 0:
                raise Exception('unexpected content in job: %s'
                                % ci_job_match.group('the_rest'))
            run['jobs'].append(job)
    return run


def parse_pr_message(msg):
    """
    Parse gerrit change messages that look like CI job messages,
    extracting CI job data and returning as a dict
    """

    # TODO refactor to take a list of patterns for runs and jobs (ultimately
    # taken from a config parameter/file)
    ci_run_patt = 'Build (?P<status>\S+)\s+(?P<jobs>.+)'  # noqa
    ci_run_re = re.compile(ci_run_patt, re.MULTILINE | re.DOTALL)
    ci_job_v1_patt = '^- (?P<proto>.+)?://(?P<jenkins_path>.+)?/job/(?P<name>\S+)/\d+/ : (?P<result>\S+) in (?P<time_h>\d+h )?(?P<time_m>\d+m )?(?P<time_s>\d+s)(?P<non_voting> \(non\-voting\))?(?P<the_rest>.*)$'  # noqa
    ci_job_v1_re = re.compile(ci_job_v1_patt, re.MULTILINE)
    ci_job_v2_patt = '^- (?P<proto>.+)?://(?P<logs_path>.+)?/(?P<name>\D+) : (?P<result>\S+) in (?P<time_h>\d+h )?(?P<time_m>\d+m )?(?P<time_s>\d+s)(?P<non_voting> \(non\-voting\))?(?P<the_rest>.*)$'  # noqa
    ci_job_v2_re = re.compile(ci_job_v2_patt, re.MULTILINE)

    run = dict()
    ci_run_match = ci_run_re.match(msg['body'])
    if ci_run_match:
        run['status'] = ci_run_match.group('status')

        run['jobs'] = list()
        for ci_job_match in itertools.chain(
                ci_job_v1_re.finditer(ci_run_match.group('jobs')),
                ci_job_v2_re.finditer(ci_run_match.group('jobs'))):
            job = dict()
            job['name'] = ci_job_match.group('name')
            job['result'] = ci_job_match.group('result')

            # mash time fields together into total seconds for job
            job['total_sec'] = 0
            ci_job_time_h = ci_job_match.group('time_h')
            ci_job_time_m = ci_job_match.group('time_m')
            ci_job_time_s = ci_job_match.group('time_s')

            if ci_job_time_h:
                job['total_sec'] += \
                    int(str(ci_job_time_h).strip().rstrip('h')) * 3600
            if ci_job_time_m:
                job['total_sec'] += \
                    int(str(ci_job_time_m).strip().rstrip('m')) * 60
            if ci_job_time_s:
                job['total_sec'] += \
                    int(str(ci_job_time_s).strip().rstrip('s'))

            job['non_voting'] = ci_job_match.group('non_voting')
            if len(ci_job_match.group('the_rest')) > 0:
                raise Exception('unexpected content in job: %s'
                                % ci_job_match.group('the_rest'))
            run['jobs'].append(job)
    return run


def parse_change_stats(changes, start_dt):
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

    for gerrit_id in changes:
        change = changes[gerrit_id]
        created_ts = change['created']
        created_dt = datetime.strptime(created_ts[:-3], GERRIT_TIMESTAMP)
        updated_ts = change['updated']
        updated_dt = datetime.strptime(updated_ts[:-3], GERRIT_TIMESTAMP)
        if created_dt >= start_dt:
            created[created_ts] += 1
            log.debug(
                'created updated to %d with project|change: '
                '%s|%s',
                created[created_ts],
                change['project'],
                gerrit_id)
        if updated_dt >= start_dt:
            updated[updated_ts] += 1
            log.debug(
                'updated updated to %d with project|change: '
                '%s|%s',
                updated[updated_ts],
                change['project'],
                gerrit_id)

        if change['status'] == 'MERGED':
            log.debug(json.dumps(change,
                                 sort_keys=True,
                                 indent=4,
                                 separators=(',', ': ')))
            merged_ts = get_merged_timestamp(change)
            merged_dt = datetime.strptime(merged_ts[:-3], GERRIT_TIMESTAMP)
            if merged_dt >= start_dt:
                merged[merged_ts] += 1
                log.debug(
                    'merged updated to %d with project|change: '
                    '%s|%s',
                    merged[merged_ts],
                    change['project'],
                    gerrit_id)

            revisions[merged_ts] = len(change['revisions'])

            lifespan_sec[merged_ts] = (
                merged_dt - created_dt).total_seconds()
            log.debug(
                'change lifespan set to %d for project|change: %s|%s',
                lifespan_sec[merged_ts],
                change['project'],
                gerrit_id)

            for message in change['messages']:
                log.debug(message)
                if 'recheck' in message['message'].lower():
                    recheck[merged_ts] += 1
                    log.debug(
                        'recheck updated to %d with project|change|rev: '
                        '%s|%s|%s',
                        recheck[merged_ts],
                        change['project'],
                        gerrit_id,
                        message['_revision_number'])
                elif 'reverify' in message['message'].lower():
                    reverify[merged_ts] += 1
                    log.debug(
                        'reverify updated to %d with project|change|rev: '
                        '%s|%s|%s',
                        reverify[merged_ts],
                        change['project'],
                        gerrit_id,
                        message['_revision_number'])

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


def parse_pr_stats(args, prs, start_dt):
    """
    Returns a pandas DataFrame with
        a count of PRs created
        a count of PRs updated
        a count of PRs merged
        a count of commits for each merged PR
        lifespan of each merged PR (from creation to merging)
        recheck and reverify counts for each merged change
    from the json list of PRs passed

    Updates PR with various additional fields including comments and commits
    """
    created = defaultdict(int)
    updated = defaultdict(int)
    merged = defaultdict(int)
    revisions = dict()
    lifespan_sec = dict()
    recheck = defaultdict(int)
    reverify = defaultdict(int)

    for pr_id in prs:
        pr = prs[pr_id]
        created_ts = pr['created_at']
        created_dt = datetime.strptime(created_ts, GITHUB_TIMESTAMP)
        pr['created_dt'] = created_dt

        updated_ts = pr['updated_at']
        updated_dt = datetime.strptime(updated_ts, GITHUB_TIMESTAMP)
        pr['updated_dt'] = updated_dt

        merged_ts = pr['merged_at']
        merged_dt = datetime.strptime(updated_ts, GITHUB_TIMESTAMP)
        pr['merged_dt'] = merged_dt

        # Assume we won't have more than 250 commits on a PR for now ...
        commits = github_query(args, pr['commits_url'])
        log.debug('commits: %s',
                  json.dumps(commits, sort_keys=True, indent=4,
                             separators=(',', ': ')))
        pr['commits'] = commits

        comments = github_query(args, pr['comments_url'])
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
                    log.info(
                        'recheck updated to %d with %s',
                        recheck[merged_ts],
                        msg_details)
                elif 'reverify' in comment['body'].lower():
                    reverify[merged_ts] += 1
                    log.info(
                        'reverify updated to %d with %s',
                        reverify[merged_ts],
                        msg_details)

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


def github_query(args, query_url):
    if args.github_user and args.github_token:
        response = requests.get(query_url,
                                verify=args.verify_https_requests,
                                auth=(args.github_user, args.github_token))
    else:
        response = requests.get(query_url,
                                verify=args.verify_https_requests)
    log.debug('github query url: %s', response.url)
    return response.json()


def get_merged_timestamp(change):
    """
    Projects renamed in gerrit seem to lose their 'submitted' timestamp,
    handle that gracefully by returning the 'updated' timestamp instead in
    those cases, emitting a warning.
    """
    merged_ts = change.get('submitted', None)
    if not merged_ts:
        log.warn('Warning - merged change %s is missing the submitted'
                 ' timestamp, using updated timestamp instead',
                 change['id'])
        merged_ts = change['updated']
    return merged_ts


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
    for gerrit_id in changes:
        change = changes[gerrit_id]
        log.debug(change)
        for message in change['messages']:
            log.debug('message: %s', message)
            ci_run = parse_ci_job_comments(message)
            log.debug('ci_run: %s', ci_run)
            if ci_run:
                log.debug(ci_run)
                ci_run_ts = message['date']
                ci_run_dt = datetime.strptime(ci_run_ts[:-3], GERRIT_TIMESTAMP)

                # ignore messages on changes that are older than our start time
                if ci_run_dt < start_dt:
                    log.debug('discarding message on proj|change|rev|run: '
                              '%s|%s|%s|%s with date %s',
                              change['project'],
                              change['change_id'],
                              message['_revision_number'],
                              ci_run['num'],
                              ci_run_ts)
                    continue

                updated_ts = change['updated']
                if ci_run['status'] in ('succeeded', 'Successful', 'OK'):
                    ci_success[updated_ts] += 1
                    log.debug(debug_msg('ci_success',
                                        ci_success[updated_ts],
                                        'run',
                                        change,
                                        message,
                                        ci_run['num'],
                                        'status: ' + ci_run['status']))
                elif ci_run['status'] in ('failed', 'Failed'):
                    ci_failure[updated_ts] += 1
                    log.debug(debug_msg('ci_failure',
                                        ci_failure[updated_ts],
                                        'run',
                                        change,
                                        message,
                                        ci_run['num'],
                                        'status: ' + ci_run['status']))
                else:
                    # TODO add extra status to appropriate path above
                    log.warn('Unexpected status %s for %s on %s, skipping',
                             ci_run['status'], ci_run['num'], change['id'])
                    continue

                if change['status'] == 'MERGED':
                    merged_ts = get_merged_timestamp(change)
                    for ci_job in ci_run['jobs']:
                        ci_total_time_sec[merged_ts] += ci_job[
                            'total_sec']
                        log.debug(debug_msg('ci_total_time_sec',
                                            ci_total_time_sec[merged_ts],
                                            'job',
                                            change,
                                            message,
                                            ci_job['name'],
                                            str(ci_job['total_sec']) + 's'))

                        # this could end up being the longest job across
                        # multiple changes if two changes merge at the same
                        # time (to the microsecond), so not going to worry
                        # about that for now but log what we're doing so
                        # someone can debug this in future
                        if (ci_job['total_sec'] >
                                ci_longest_time_sec[merged_ts]):
                            ci_longest_time_sec[merged_ts] = ci_job[
                                'total_sec']
                            log.debug(debug_msg('ci_longest_time_sec',
                                                ci_longest_time_sec[
                                                    merged_ts],
                                                'job',
                                                change,
                                                message,
                                                ci_job['name'],
                                                str(ci_job[
                                                        'total_sec']) + 's'))

    d = {'ci_total_time_sec': ci_total_time_sec,
         'ci_longest_time_sec': ci_longest_time_sec,
         'ci_success': ci_success,
         'ci_failure': ci_failure}

    df = pd.DataFrame(d, columns=['ci_total_time_sec', 'ci_longest_time_sec',
                                  'ci_success', 'ci_failure'])
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
    for pr_id in prs:
        pr = prs[pr_id]
        log.debug("pr %d", pr_id)
        for comment in pr['comments']:
            log.debug('comment: %s', comment)
            ci_run = parse_pr_message(comment)
            log.info('ci_run: %s', ci_run)
            if ci_run:
                log.debug(ci_run)
                ci_run_ts = comment['created_at']
                ci_run_dt = datetime.strptime(ci_run_ts, GITHUB_TIMESTAMP)

                msg_details = 'project|pr|id|comment: %s|%s|%s|%s' % (
                    pr['base']['repo']['full_name'], pr['number'], pr_id,
                    comment['id'])

                # ignore messages on changes that are older than our start time
                if ci_run_dt < start_dt:
                    log.debug('discarding comment on %s with date %s',
                              msg_details, ci_run_ts)
                    continue

                updated_ts = pr['updated_at']
                if ci_run['status'] in ('succeeded', 'Successful', 'OK'):
                    ci_success[updated_ts] += 1
                    log.debug(debug_msg_pr('ci_success',
                                        ci_success[updated_ts],
                                        'run',
                                        pr,
                                        comment,
                                        None,
                                        'status: ' + ci_run['status']))
                elif ci_run['status'] in ('failed', 'Failed'):
                    ci_failure[updated_ts] += 1
                    log.debug(debug_msg_pr('ci_failure',
                                        ci_failure[updated_ts],
                                        'run',
                                        pr,
                                        comment,
                                        None,
                                        'status: ' + ci_run['status']))
                else:
                    # TODO add extra status to appropriate path above
                    log.warn('Unexpected status %s for %s on %s, skipping',
                             ci_run['status'], None, pr['number'])
                    continue

                if pr['merged_at']:
                    merged_ts = pr['merged_at']
                    for ci_job in ci_run['jobs']:
                        ci_total_time_sec[merged_ts] += ci_job[
                            'total_sec']
                        log.debug(debug_msg_pr('ci_total_time_sec',
                                            ci_total_time_sec[merged_ts],
                                            'job',
                                            pr,
                                            comment,
                                            ci_job['name'],
                                            str(ci_job['total_sec']) + 's'))

                        # this could end up being the longest job across
                        # multiple changes if two changes merge at the same
                        # time (to the microsecond), so not going to worry
                        # about that for now but log what we're doing so
                        # someone can debug this in future
                        if (ci_job['total_sec'] >
                                ci_longest_time_sec[merged_ts]):
                            ci_longest_time_sec[merged_ts] = ci_job[
                                'total_sec']
                            log.debug(debug_msg_pr('ci_longest_time_sec',
                                                ci_longest_time_sec[
                                                    merged_ts],
                                                'job',
                                                pr,
                                                comment,
                                                ci_job['name'],
                                                str(ci_job[
                                                        'total_sec']) + 's'))

    d = {'ci_total_time_sec': ci_total_time_sec,
         'ci_longest_time_sec': ci_longest_time_sec,
         'ci_success': ci_success,
         'ci_failure': ci_failure}

    df = pd.DataFrame(d, columns=['ci_total_time_sec', 'ci_longest_time_sec',
                                  'ci_success', 'ci_failure'])
    log.debug('ci time status df:\n%s', df)
    return df


# Looks klunky but the debug message is very useful for verification
def debug_msg(field, counter, job_or_run, change, message, ci_name, ci_val):
    msg = '%s updated to %d with proj|change|rev|%s: %s|%s|%s|%s and %s' % (
        field,
        counter,
        job_or_run,
        change['project'],
        change['change_id'],
        message['_revision_number'],
        ci_name,
        ci_val)
    return msg


# Looks klunky but the debug message is very useful for verification
def debug_msg_pr(field, counter, job_or_run, pr, comment, ci_name, ci_val):
    msg = '%s updated to %d with proj|change|rev|%s: %s|%s|%s|%s and %s' % (
        field,
        counter,
        job_or_run,
        pr['base']['repo']['full_name'],
        pr['id'],
        comment['id'],
        ci_name,
        ci_val)
    return msg


def generate_dataframes_gerrit(changes, start_dt):
    """
    Create pandas dataframes for data of interest for subsequent analysis
    by different time periods. Some data is only recorded for merged changes
    as rolling updates of those changing stats are not useful in the authors
    opinion.
    """
    df_change_stats = parse_change_stats(changes, start_dt)
    df_ci_stats = parse_ci_stats(changes, start_dt)

    df = pd.concat([df_change_stats, df_ci_stats])
    df.index = pd.to_datetime(df.index)
    df.sort_index(inplace=True)
    df.fillna(value=0, inplace=True)

    return df


def generate_dataframes_github(args, prs, start_dt):
    """
    Create pandas dataframes for data of interest for subsequent analysis
    by different time periods.
    """
    df_pr_stats = parse_pr_stats(args, prs, start_dt)
    df_ci_stats = parse_pr_ci_stats(prs, start_dt)

    df = pd.concat([df_pr_stats, df_ci_stats])

    df.index = pd.to_datetime(df.index)
    df.sort_index(inplace=True)
    df.fillna(value=0, inplace=True)

    return df


def generate_html(args, df, num_changes, start_dt, finish_dt,
                  projects, all_projects,
                  group=None, groups=[]):
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
        status_plot=plot_ci_success_failure(df_plot, group))
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
    plot_title = "Changes (%s projects)" % group
    changes_plot = plotly.offline.plot(
        {
            "data": [created_line, submitted_line],
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


def configure_logging(args):
    """Configure logging.

    - Default => INFO
    - log_quietly (-q) => ERROR
    - log_verbosely (-v) => DEBUG
    """

    # requests and urllib3 are very chatty by default, suppress some of this
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("requests").setLevel(logging.WARNING)

    # and suppress InsecurePlatformWarning from urllib3 also
    # see http://stackoverflow.com/questions/29099404 for details
    import requests.packages.urllib3
    requests.packages.urllib3.disable_warnings()

    # Set root logger level to DEBUG, and use the
    # handler level to control verbosity.
    logging.getLogger().setLevel(logging.DEBUG)

    ch = logging.StreamHandler(stream=sys.stderr)
    ch.setLevel(logging.INFO)
    if args.log_quietly:
        ch.setLevel(logging.ERROR)
    elif args.log_verbosely:
        ch.setLevel(logging.DEBUG)

    ch_format = logging.Formatter('%(message)s')
    ch.setFormatter(ch_format)
    logging.getLogger().addHandler(ch)

    if not args.no_logfile:
        fh = logging.FileHandler(args.logfile, delay=True)
        fh.setLevel(logging.DEBUG)
        # TODO, add custom trace level for json dumps
        # if args.log_trace:
        #     fh.setLevel(TRACE_LOGGING_LEVEL)
        log_format = (
            '%(asctime)s: %(process)d:%(thread)d %(levelname)s - %(message)s'
        )
        fh_format = logging.Formatter(log_format)
        fh.setFormatter(fh_format)
        logging.getLogger().addHandler(fh)


if __name__ == "__main__":
    main()
