#
# (c) Copyright 2018 Hewlett Packard Enterprise Development LP
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

import logging
from datetime import datetime
from datetime import timedelta

import requests

from zingstats import GerritChanges


# TODO look at betamax for managing test inputs
class TestClass(object):
    def test_empty_changes(self, requests_mock):
        url = 'http://gerrit.example.com/'
        query = 'status:open OR status:closed'
        projects = ['foo/blah']
        branches = ['master']
        finish_dt = datetime.now()
        start_dt = finish_dt - timedelta(hours=24)

        requests_mock.get('http://gerrit.example.com/', text='data')
        session = requests.Session()
        changes = GerritChanges(url, query, projects, branches,
                                start_dt, finish_dt, session)
        assert len(changes) == 0

    def test_nonempty_changes(self, requests_mock, caplog):
        # dumps debug output if the test fails
        caplog.set_level(logging.DEBUG)

        url = 'https://review.openstack.org'
        query = 'status:open OR status:closed'
        projects = ['openstack/cinder', 'openstack/openstack-ansible-ops', 'openstack/networking-calico']
        branches = ['stable/pike', 'master']
        finish_dt = datetime.now()
        start_dt = finish_dt - timedelta(hours=24)

        # TODO move data loading out of test case
        # TODO sanitise test file
        data_file = 'tests/data/test_nonempty_changes.response'
        with open(data_file, 'r') as f:
            test_data = f.read()
        requests_mock.get('https://review.openstack.org/changes/?q=status%3Aopen+OR+status%3Aclosed&start=0&o=ALL_REVISIONS&o=MESSAGES&n=100', text=test_data)
        session = requests.Session()
        changes = GerritChanges(url, query, projects, branches,
                                start_dt, finish_dt, session)
        changes.gather()
        assert len(changes) == 3

    def test_fixture(self, requests_mock):
        requests_mock.get('http://gerrit.example.com/', text='data')
        assert 'data' == requests.get('http://gerrit.example.com/').text
