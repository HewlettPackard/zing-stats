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
import zing_stats


def test_helloworld():
        assert 1 == 1


def test_parse_gerrit_change_message():
    messages = [
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
    msg0 = zing_stats.parse_gerrit_change_message(messages[0])
    assert msg0 == {}
    msg1 = zing_stats.parse_gerrit_change_message(messages[1])
    assert msg1 == {}
    msg2 = zing_stats.parse_gerrit_change_message(messages[2])
    assert msg2['date'] == '2017-04-20 17:15:44.000000000'
    assert msg2['num'] == '1'
    assert msg2['status'] == 'succeeded'
    assert msg2['v_score'] == '+1'

    assert len(msg2['jobs']) == 1
    assert msg2['jobs'][0]['name'] == 'test-check'
    assert msg2['jobs'][0]['non_voting'] is None
