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

import itertools
import logging
import re

log = logging.getLogger(__name__)


def parse_ci_job_comments(msg):
    """
    Parse gerrit change messages that look like CI job messages,
    extracting CI job data and returning as a dict
    """
    log.debug('Parsing %s', msg)

    ci_run_patt = 'Patch Set (?P<num>\d+): Verified(?P<v_score>\S+)\s+Build (?P<status>\S+)\s+(?P<jobs>.+)'  # noqa

    return __parse_change_messages(msg.text, ci_run_patt)


def parse_pr_message(msg):
    """
    Parse PR messages that look like CI job messages,
    extracting CI job data and returning as a dict
    """
    ci_run_patt = 'Build (?P<status>\S+)\s+(?P<jobs>.+)'  # noqa

    return __parse_change_messages(msg['body'], ci_run_patt)


# TODO Should you do the initial matching in the caller and pass the resulting
# matcher object and initial dict down to this method?
def __parse_change_messages(message, ci_run_patt):
    """
    Parse change messages that look like CI job messages,
    extracting CI job data and returning as a dict
    """

    # TODO refactor to take a list of patterns for runs/jobs from a file
    ci_run_re = re.compile(ci_run_patt, re.MULTILINE | re.DOTALL)
    ci_job_v1_patt = '^- (?P<proto>.+)?://(?P<jenkins_path>.+)?/job/(?P<name>\S+)/\d+/ : (?P<result>\S+) in (?P<time_h>\d+h )?(?P<time_m>\d+m )?(?P<time_s>\d+s)(?P<non_voting> \(non\-voting\))?(?P<the_rest>.*)$'  # noqa
    ci_job_v1_re = re.compile(ci_job_v1_patt, re.MULTILINE)
    ci_job_v2_patt = '^- (?P<proto>.+)?://(?P<logs_path>.+)?/(?P<name>\D+) : (?P<result>\S+) in (?P<time_h>\d+h )?(?P<time_m>\d+m )?(?P<time_s>\d+s)(?P<non_voting> \(non\-voting\))?(?P<the_rest>.*)$'  # noqa
    ci_job_v2_re = re.compile(ci_job_v2_patt, re.MULTILINE)

    run = dict()
    ci_run_match = ci_run_re.match(message)
    if ci_run_match:
        try:
            run['num'] = ci_run_match.group('num')
        except IndexError:
            run['num'] = None

        try:
            run['v_score'] = ci_run_match.group('v_score')
        except IndexError:
            run['v_score'] = None

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


def parse_promotion_success(msg):
    promotion_success_patt = '(Patch Set \d+:\n\n)?Promotion review .+ has brought into alpha channel' # noqa
    promotion_success_re = re.compile(promotion_success_patt)
    return promotion_success_re.match(msg)


def parse_promotion_failure(msg):
    promotion_failure_patt = '(Patch Set \d+:\n\n)?PROMOTION FAILURE\n\nPromotion of artifacts from this change into Alpha channel has failed' # noqa
    promotion_failure_re = re.compile(promotion_failure_patt)
    return promotion_failure_re.match(msg)
