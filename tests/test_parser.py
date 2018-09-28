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
# flake8: noqa

import zingstats.parser
from zingstats.changes import GerritMessage


def test_parse_gerrit_change_message():
    msgs = [
        {
            '_revision_number': 1,
            'author': {
                '_account_id': 12
            },
            'date': '2017-04-20 17:15:24.000000000',
            'id': '9a5c5d37_e7c9a25b',
            'message': 'Uploaded patch set 1.'
        },
        {
            '_revision_number': 1,
            'author': {
                '_account_id': 6
            },
            'date': '2017-04-20 17:15:35.000000000',
            'id': '9a5c5d37_a7c3aa37',
            'message': 'Patch Set 1:\n\nStarting check jobs.'
        },
        {
            '_revision_number': 1,
            'author': {
                '_account_id': 6
            },
            'date': '2017-04-20 17:15:44.000000000',
            'id': '9a5c5d37_67ddb214',
            'message': 'Patch Set 1: Verified+1\n\nBuild succeeded\n\n- https://zing.example.net/jenkins/job/test-check/6/ : SUCCESS in 7s'  # noqa
        },
    ]

    msg = GerritMessage(msgs[0]['id'], msgs[0]['date'], msgs[0]['message'])
    ci_run = zingstats.parser.parse_ci_job_comments(msg)
    assert ci_run == {}

    msg = GerritMessage(msgs[1]['id'], msgs[1]['date'], msgs[1]['message'])
    ci_run = zingstats.parser.parse_ci_job_comments(msg)
    assert ci_run == {}

    msg = GerritMessage(msgs[2]['id'], msgs[2]['date'], msgs[2]['message'])
    ci_run = zingstats.parser.parse_ci_job_comments(msg)
    assert ci_run['num'] == '1'
    assert ci_run['status'] == 'succeeded'
    assert ci_run['v_score'] == '+1'

    assert len(ci_run['jobs']) == 1
    assert ci_run['jobs'][0]['name'] == 'test-check'
    assert ci_run['jobs'][0]['non_voting'] is None


def test_parse_github_change_message():
    msgs = [
        {
            "body": "@aaaa @bbbb @ccccc xxxxxxxx",
            "created_at": "2017-12-06T10:49:06Z",
            "html_url": "https://github.example.com/foo/api/pull/1153#issuecomment-429779",
            "id": 429779,
            "issue_url": "https://github.example.com/api/v3/repos/foo/api/issues/1153",
            "updated_at": "2017-12-06T10:49:06Z",
            "url": "https://github.example.com/api/v3/repos/foo/api/issues/comments/429779",
            "user": {
                "avatar_url": "https://avatars.github.example.com/u/19638?",
                "events_url": "https://github.example.com/api/v3/users/a_user/events{/privacy}",
                "followers_url": "https://github.example.com/api/v3/users/a_user/followers",
                "following_url": "https://github.example.com/api/v3/users/a_user/following{/other_user}",
                "gists_url": "https://github.example.com/api/v3/users/a_user/gists{/gist_id}",
                "gravatar_id": "",
                "html_url": "https://github.example.com/a_user",
                "id": 19638,
                "login": "a_user",
                "organizations_url": "https://github.example.com/api/v3/users/a_user/orgs",
                "received_events_url": "https://github.example.com/api/v3/users/a_user/received_events",
                "repos_url": "https://github.example.com/api/v3/users/a_user/repos",
                "site_admin": "false",
                "starred_url": "https://github.example.com/api/v3/users/a_user/starred{/owner}{/repo}",
                "subscriptions_url": "https://github.example.com/api/v3/users/a_user/subscriptions",
                "type": "User",
                "url": "https://github.example.com/api/v3/users/a_user"
            }
        },
        {
            "body": "Build succeeded\n\n- http://logs.example.net/check-github/foo/api/111153/151255557209.72/foo-example-check : SUCCESS in 2m 38s\n- http://logs.example.net/check-github/foo/api/111153/151112557209.72/foo-sec-scan : SUCCESS in 4s (non-voting)\n- http://logs.example.net/check-github/foo/api/122153/151332557209.72/another-scan : SUCCESS in 4s (non-voting)\n",
            "created_at": "2017-12-06T10:49:06Z",
            "html_url": "https://github.example.com/foo/api/pull/1153#issuecomment-429779",
            "id": 429779,
            "issue_url": "https://github.example.com/api/v3/repos/foo/api/issues/1153",
            "updated_at": "2017-12-06T10:49:06Z",
            "url": "https://github.example.com/api/v3/repos/foo/api/issues/comments/429779",
            "user": {
                "avatar_url": "https://avatars.github.example.com/u/19638?",
                "events_url": "https://github.example.com/api/v3/users/a_user/events{/privacy}",
                "followers_url": "https://github.example.com/api/v3/users/a_user/followers",
                "following_url": "https://github.example.com/api/v3/users/a_user/following{/other_user}",
                "gists_url": "https://github.example.com/api/v3/users/a_user/gists{/gist_id}",
                "gravatar_id": "",
                "html_url": "https://github.example.com/a_user",
                "id": 19638,
                "login": "a_user",
                "organizations_url": "https://github.example.com/api/v3/users/a_user/orgs",
                "received_events_url": "https://github.example.com/api/v3/users/a_user/received_events",
                "repos_url": "https://github.example.com/api/v3/users/a_user/repos",
                "site_admin": "false",
                "starred_url": "https://github.example.com/api/v3/users/a_user/starred{/owner}{/repo}",
                "subscriptions_url": "https://github.example.com/api/v3/users/a_user/subscriptions",
                "type": "User",
                "url": "https://github.example.com/api/v3/users/a_user"
            }
        },
    ]
    ci_run = zingstats.parser.parse_pr_message(msgs[0])
    assert ci_run == {}
    ci_run = zingstats.parser.parse_pr_message(msgs[1])
    assert ci_run['num'] is None
    assert ci_run['status'] == 'succeeded'
    assert ci_run['v_score'] is None
    assert len(ci_run['jobs']) == 3
    assert ci_run['jobs'][0]['name'] == 'foo-example-check'
    assert ci_run['jobs'][0]['non_voting'] is None
    assert ci_run['jobs'][1]['name'] == 'foo-sec-scan'
    assert ci_run['jobs'][1]['non_voting'] == ' (non-voting)'
    assert ci_run['jobs'][2]['name'] == 'another-scan'
    assert ci_run['jobs'][2]['non_voting'] == ' (non-voting)'


def test_parse_promotion_success():
    msg_pass = 'Patch Set 1:\n\nPromotion review https://review.example.net/1234 has brought into alpha channel following artifacts that contain code from this change:\n - Docker image foo/blah'  # noqa
    msg_fail = 'test test test'

    promotion_success = zingstats.parser.parse_promotion_success(msg_pass)
    assert promotion_success is not None

    promotion_success = zingstats.parser.parse_promotion_success(msg_fail)
    assert promotion_success is None


def test_parse_promotion_failure():
    msg_pass = 'Patch Set 1:\n\nPROMOTION FAILURE\n\nPromotion of artifacts from this change into Alpha channel has failed and will require action to resolve.\n\nPromotion Review: https://review.example.net/1234'  # noqa
    msg_fail = 'test test test'

    promotion_success = zingstats.parser.parse_promotion_failure(msg_pass)
    assert promotion_success is not None

    promotion_success = zingstats.parser.parse_promotion_failure(msg_fail)
    assert promotion_success is None
