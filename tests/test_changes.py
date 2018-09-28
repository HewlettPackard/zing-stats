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
# flake8: noqa

import logging
import os.path
from datetime import datetime
from datetime import timedelta

import requests

from zingstats.changes import GerritChanges


# TODO look at betamax for managing test inputs
class TestClass(object):
    CHANGES_DATA_FILE = 'test_nonempty_changes.response'
    MOCKED_CHANGES_URL = 'https://review.openstack.org/changes/?q=status%3Aopen+OR+status%3Aclosed&start=0&o=ALL_REVISIONS&o=MESSAGES&n=100'  # noqa

    def test_changes_empty(self, requests_mock):
        url = 'http://gerrit.example.com/'
        query = 'status:open OR status:closed'
        projects = ['foo/blah']
        branches = ['master']
        finish_dt = datetime(2018, 9, 26, 10, 0, 0)
        start_dt = finish_dt - timedelta(hours=24)

        requests_mock.get('http://gerrit.example.com/', text='data')
        session = requests.Session()
        changes = GerritChanges(url, query, projects, branches,
                                start_dt, finish_dt, session)
        assert len(changes) == 0

    # TODO test handling of "_more_changes": true
    def test_changes_gather(self, requests_mock, caplog):
        # dumps debug output if the test fails
        caplog.set_level(logging.DEBUG)

        changes = self.prep_test_changes(requests_mock)
        changes.gather()
        assert len(changes) == 3

    def test_changes_change(self, requests_mock, caplog):
        # dumps debug output if the test fails
        caplog.set_level(logging.DEBUG)

        changes = self.prep_test_changes(requests_mock)
        changes.gather()
        change = list(changes)[0]
        assert change.parent_url == 'https://review.openstack.org'
        assert change.long_id == 'openstack%2Fcinder~stable%2Fpike~Id5dd71a785c4cd72ba44f9b4d26319be53079c39'  # noqa
        assert change.change_id == 'Id5dd71a785c4cd72ba44f9b4d26319be53079c39'
        assert change.number == 604103
        assert change.project == 'openstack/cinder'
        assert change.branch == 'stable/pike'
        assert change.status == 'MERGED'
        assert change.created_dt == datetime(2018, 9, 20, 14, 15, 56)
        assert change.updated_dt == datetime(2018, 9, 25, 16, 24, 13)
        assert change.merged_dt == datetime(2018, 9, 21, 15, 50, 45)
        assert change.url == 'https://review.openstack.org/changes/openstack%2Fcinder~stable%2Fpike~Id5dd71a785c4cd72ba44f9b4d26319be53079c39'  # noqa
        assert change.review_url == 'https://review.openstack.org/604103'
        assert change.rev_count() == 1

    def test_changes_change_revision(self, requests_mock, caplog):
        # dumps debug output if the test fails
        caplog.set_level(logging.DEBUG)

        changes = self.prep_test_changes(requests_mock)
        changes.gather()
        change = list(changes)[0]
        revision = list(change.revisions())[0]

        assert revision.url == 'https://review.openstack.org/changes/openstack%2Fcinder~stable%2Fpike~Id5dd71a785c4cd72ba44f9b4d26319be53079c39/revisions/a5e86c387e67650451d957c5ef525b452203c2fd'  # noqa
        assert revision.number == 1
        assert revision.created_dt == datetime(2018, 9, 20, 14, 15, 56)
        messages = list(revision.messages())
        assert len(messages) == 29

    def test_changes_change_revision_message(self, requests_mock, caplog):
        # dumps debug output if the test fails
        # caplog.set_level(logging.DEBUG)

        changes = self.prep_test_changes(requests_mock)
        changes.gather()
        change = list(changes)[0]
        revision = list(change.revisions())[0]
        messages = list(revision.messages())

        assert messages[0].message_id == '3f79a3b5_0fd64428'
        assert messages[0].text == 'Patch Set 1: Cherry Picked from branch master.'  # noqa

    def prep_test_changes(self, requests_mock):
        url = 'https://review.openstack.org'
        query = 'status:open OR status:closed'
        projects = ['openstack/cinder', 'openstack/openstack-ansible-ops',
                    'openstack/networking-calico']
        branches = ['stable/pike', 'master']
        finish_dt = datetime(2018, 9, 26, 10, 0, 0)
        start_dt = finish_dt - timedelta(hours=24)
        # TODO move data loading out of test case
        # TODO sanitise test file
        session = requests.Session()
        test_data = self.__class__.load_test_changes_data(
            self.__class__.CHANGES_DATA_FILE)
        requests_mock.get(self.__class__.MOCKED_CHANGES_URL, text=test_data)
        changes = GerritChanges(url, query, projects, branches,
                                start_dt, finish_dt, session)
        return changes

    def test_changes_gather_multipage(self, requests_mock, caplog):
        # dumps debug output if the test fails
        caplog.set_level(logging.DEBUG)

        url = 'https://review.openstack.org'
        query = 'status:open OR status:closed'
        projects = ['openstack/cinder', 'openstack/openstack-ansible-ops',
                    'openstack/networking-calico']
        branches = ['stable/pike', 'master']
        finish_dt = datetime(2018, 9, 26, 10, 0, 0)
        start_dt = finish_dt - timedelta(hours=24)

        session = requests.Session()

        test_data_page1 = 'test_changes_page1.response'
        mocked_url_1 = 'https://review.openstack.org/changes/?q=status%3Aopen+OR+status%3Aclosed&start=0&o=ALL_REVISIONS&o=MESSAGES&n=1'  # noqa
        test_data1 = self.__class__.load_test_changes_data(test_data_page1)
        requests_mock.get(mocked_url_1, text=test_data1)

        test_data_page2 = 'test_changes_page2.response'
        mocked_url_2 = 'https://review.openstack.org/changes/?q=status%3Aopen+OR+status%3Aclosed&start=1&o=ALL_REVISIONS&o=MESSAGES&n=1'  # noqa
        test_data2 = self.__class__.load_test_changes_data(test_data_page2)
        requests_mock.get(mocked_url_2, text=test_data2)

        test_data_page3 = 'test_changes_page3.response'
        mocked_url_3 = 'https://review.openstack.org/changes/?q=status%3Aopen+OR+status%3Aclosed&start=2&o=ALL_REVISIONS&o=MESSAGES&n=1'  # noqa
        test_data3 = self.__class__.load_test_changes_data(test_data_page3)
        requests_mock.get(mocked_url_3, text=test_data3)

        changes = GerritChanges(url, query, projects, branches,
                                start_dt, finish_dt, session, query_size=1)
        changes.gather()
        assert len(changes) == 3





    @staticmethod
    def load_test_changes_data(data_file):
        test_data_path = os.path.join('tests', 'data', data_file)
        with open(test_data_path, 'r') as f:
            test_data = f.read()
        return test_data

    def test_fixture(self, requests_mock):
        requests_mock.get('http://gerrit.example.com/', text='data')
        assert 'data' == requests.get('http://gerrit.example.com/').text
