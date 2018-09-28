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

import base64
import json
import logging
import urllib
from datetime import datetime

log = logging.getLogger(__name__)


class Changes(object):
    def __init__(self, url, query, projects, branches, start_dt, finish_dt,
                 session):
        self.url = url
        self.session = session
        self.query = query
        self.projects = projects
        self.branches = branches
        self.start_dt = start_dt
        self.finish_dt = finish_dt
        self.query_start = 0
        self.changes = dict()

    def __iter__(self):
        for long_id in self.changes:
            yield self.changes[long_id]

    def __len__(self):
        return len(self.changes)

    def add(self, change):
        self.changes[change.long_id] = change

    # TODO implement better__getitem__()
    def __getitem__(self, key):
        return self.changes[key]

    @staticmethod
    def pretty_json(json_data):
        """Pretty print JSON data, usually for logging purposes."""
        return json.dumps(json_data, sort_keys=True, indent=4,
                          separators=(',', ': '))


class GerritChanges(Changes):
    def __init__(self, url, query, projects, branches, start_dt, finish_dt,
                 session, query_size=100, max_changes=None):
        super(GerritChanges, self).__init__(url, query, projects, branches,
                                            start_dt, finish_dt, session)
        self.query_size = query_size
        self.max_changes = max_changes

    def gather(self):
        log.info('Gathering changes from %s for projects: %s and branches: %s',
                 self.url,
                 ', '.join(sorted(self.projects)),
                 ', '.join(sorted(self.branches)))

        results = [{'_more_changes': True}]
        while results[-1].get('_more_changes'):
            log.debug('Querying %d changes starting at %d', self.query_size,
                      self.query_start)
            payload = {
                'q': self.query,
                # TODO make ALL_FILES gathering toggleable, it is expensive
                # 'o': ['ALL_REVISIONS', 'MESSAGES', 'ALL_FILES'],
                'o': ['ALL_REVISIONS', 'MESSAGES'],
                'start': self.query_start,
                'n': self.query_size}
            query = ('%s/changes/' % self.url)
            response = self.session.get(query, params=payload)
            log.debug(response.url)

            results = GerritChanges.clean_gerrit_response(response)
            log.debug(GerritChanges.pretty_json(results))
            for change_json in results:
                log.debug(GerritChanges.pretty_json(change_json))
                log.debug('%d changes (start: %d, count=%d)', len(results),
                          self.query_start, self.query_size)
                change = GerritChange(change_json, self.url, self.session)

                if self.projects and change.project not in self.projects:
                    log.debug('Change %s project %s not in projects, skipping',
                              change.long_id, change.project)
                    continue

                if self.branches and change.branch not in self.branches:
                    log.debug('Change %s branch %s not in branches, skipping',
                              change.long_id, change.branch)
                    continue

                if change.long_id in self.changes:
                    log.warn('Change id %s already stored, not storing again',
                             change.long_id)
                    log.warn('cause of this duplicate must be investigated')
                    continue

                if self.max_changes and len(self.changes) >= self.max_changes:
                    log.warn('max changes set to %d, not storing more changes',
                             self.max_changes)
                    results[-1].pop('_more_changes', None)
                    break

                if change.updated_dt < self.start_dt:
                    log.debug('%s is older than %s start, not reading more',
                              change.updated_dt, self.start_dt)
                    results[-1].pop('_more_changes', None)
                    break

                self.add(change)

            self.query_start += self.query_size

        return True

    @staticmethod
    def clean_gerrit_response(response):
        """Strip magic junk off the start of the gerrit response."""
        return json.loads(response.text[5:])


class Change(object):
    def __init__(self, parent_url, session):
        self.parent_url = parent_url
        self.session = session
        self.long_id = None
        self.change_id = None
        self.number = None
        self.project = None
        self.branch = None
        self.status = None
        self.created_dt = None
        self.updated_dt = None
        self.merged_dt = None
        self.url = None
        self.review_url = None
        self._revisions = dict()

    def revisions(self):
        for revision_id in sorted(self._revisions):
            yield self._revisions[revision_id]

    def rev_count(self):
        return len(self._revisions)


class GerritChange(Change):
    GERRIT_FORMAT = '%Y-%m-%d %H:%M:%S.%f'

    def __init__(self, change, parent_url, session):
        super(GerritChange, self).__init__(parent_url, session)
        self.long_id = change['id']
        self.change_id = change['change_id']
        self.number = change['_number']
        self.project = change['project']
        self.branch = change['branch']
        self.status = change['status']
        self.created_dt = GerritChange.ts_to_dt(change['created'][:-3])
        self.updated_dt = GerritChange.ts_to_dt(change['updated'][:-3])
        if 'submitted' in change:
            self.merged_dt = GerritChange.ts_to_dt(change['submitted'][:-3])
        self.url = '%s/changes/%s' % (parent_url, self.long_id)
        self.review_url = '%s/%s' % (parent_url, self.number)

        # TODO move to utility function (for ease of testing and general use)
        for revision_id in change['revisions']:
            revision = GerritRevision(revision_id,
                                      change['revisions'][revision_id],
                                      '%s/revisions/%s' % (
                                          self.url, revision_id),
                                      self.session)
            self._revisions[int(revision.number)] = revision

        # TODO move to utility function (for ease of testing and general use)
        for message_json in change['messages']:
            message = GerritMessage(message_json['id'],
                                    message_json['date'],
                                    message_json['message'])
            self._revisions[int(message_json['_revision_number'])].add_message(
                message)

    @staticmethod
    def ts_to_dt(gerrit_ts):
        """Convert Gerrit format timestamp to datetime."""
        return datetime.strptime(gerrit_ts, GerritChange.GERRIT_FORMAT)


class Revision(object):
    def __init__(self, revision_id, url, session):
        self.revision_id = revision_id
        # revision url is not directly usable, but a base for other queries
        self.url = url
        self.session = session
        self._files = dict()
        self._messages = list()
        self.number = None
        self.created_dt = None

    def files(self):
        for file_name in sorted(self._files):
            yield (file_name, self._files[file_name]['diff'],
                   self._files[file_name]['content'])

    def add_message(self, message):
        self._messages.append(message)

    def messages(self):
        for message in self._messages:
            yield message


class GerritRevision(Revision):
    def __init__(self, revision_id, revision, url, session):
        super(GerritRevision, self).__init__(revision_id, url, session)
        self.number = revision['_number']
        self.created_dt = GerritChange.ts_to_dt(revision['created'][:-3])

        # TODO make ALL_FILES gathering toggleable, it is expensive/slow
        for file_name in revision.get('files', list()):
            self._files[file_name] = dict()
            file_url = '%s/files/%s' % (self.url, urllib.quote_plus(file_name))
            diff_url = '%s/diff' % file_url
            log.debug('diff url: %s', diff_url)
            response = self.session.get(diff_url)
            log.debug(response.url)
            # https://gerrit-review.googlesource.com/Documentation/rest-api-changes.html#diff-info
            diff = GerritChanges.clean_gerrit_response(response)
            log.debug(GerritChanges.pretty_json(diff))
            self._files[file_name]['diff'] = diff

            content_url = '%s/content' % file_url
            log.debug('content url: %s', content_url)
            response = self.session.get(content_url)
            log.debug(response.url)
            # https://gerrit-review.googlesource.com/Documentation/rest-api-changes.html#get-content
            content = base64.b64decode(response.content)
            log.debug(content)
            self._files[file_name]['content'] = content


class Message(object):
    def __init__(self, message_id, message_text):
        self.message_id = message_id
        self.text = message_text


class GerritMessage(Message):
    def __init__(self, message_id, message_date, message_text):
        super(GerritMessage, self).__init__(message_id, message_text)
        self.message_dt = GerritChange.ts_to_dt(message_date[:-3])
