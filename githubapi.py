"""Access to information using the GitHub API."""

from __future__ import print_function

import operator
import pprint

import dateutil.parser
from urlobject import URLObject

from helpers import paginated_get, requests
from models import PullRequestBase


class JsonAttributeHelper(object):
    @classmethod
    def from_json(cls, issues_data):
        for issue_data in issues_data:
            if not cls.want_this_json_object(issue_data):
                continue
            yield cls(issue_data)

    @classmethod
    def want_this_json_object(cls, obj):
        return True

    def attribute_lookup(self, name, field_map, mapped_fields=None):
        obj = None
        for field_names, value in field_map:
            if name in field_names:
                obj = value
                break

        if obj is not None:
            if mapped_fields:
                name = mapped_fields.get(name, name)
            val = self.deep_getitem(obj, name)
            if name.endswith('_at') and val is not None:
                val = dateutil.parser.parse(val)
            return val

        raise AttributeError("Nope: don't have {!r} attribute on {}".format(name, self.__class__.__name__))

    def deep_getitem(self, val, key):
        for k in key.split("."):
            if val is None:
                break
            val = val[k]
        return val


class PullRequest(JsonAttributeHelper, PullRequestBase):
    def __init__(self, issue_data):
        self._issue = issue_data
        if 0:
            print("---< Issue >---------------------------------")
            pprint.pprint(issue_data)
        self._pull = None
        self.labels = [self.short_label(l['name']) for l in self.labels]

    @classmethod
    def want_this_json_object(cls, obj):
        pr_url = obj.get('pull_request', {}).get('url')
        return bool(pr_url)

    ISSUE_FIELDS = {
        'assignee_login',
        'closed_at',
        'comments',
        'comments_url',
        'created_at',
        'labels',
        'number',
        'pull_request_url',
        'pull_request_html_url',
        'state',
        'title',
        'updated_at',
        'user_html_url',
        'user_login',
    }
    PULL_FIELDS = {
        'additions',
        'base_ref',
        'changed_files',
        'commits',
        'deletions',
        'merged_at',
    }
    MAPPED_FIELDS = {
        'assignee_login': 'assignee.login',
        'base_ref': 'base.ref',
        'pull_request_url': 'pull_request.url',
        'pull_request_html_url': 'pull_request.html_url',
        'user_login': 'user.login',
        'user_html_url': 'user.html_url',
    }

    def __getattr__(self, name):
        return self.attribute_lookup(
            name,
            [(self.ISSUE_FIELDS, self._issue), (self.PULL_FIELDS, self._pull)],
            self.MAPPED_FIELDS
        )

    def load_pull_details(self, pulls=None):
        """Get pull request details also.

        `pulls` is a dictionary of pull requests, to perhaps avoid making
        another request.

        """
        if pulls:
            self._pull = pulls.get(self.number)
        if not self._pull:
            self._pull = requests.get(self.pull_request_url).json()

        if 0:
            print("---< Pull Request >--------------------------")
            pprint.pprint(self._pull)


class Comment(JsonAttributeHelper):
    def __init__(self, obj):
        self._comment = obj

    FIELDS = {
        'body',
        'created_at',
        'user_login',
    }

    def __getattr__(self, name):
        return self.attribute_lookup(
            name,
            [(self.FIELDS, self._comment)],
            {'user_login': 'user.login'},
        )


def get_pulls(owner_repo, labels=None, state="open", since=None, org=False, pull_details=None):
    """
    Get a bunch of pull requests (actually issues).

    `pull_details` indicates how much information you want from the associated
    pull request document.  None means just issue information is enough. "list"
    means the information available when listing pull requests is enough. "all"
    means you need all the details.  See the GitHub API docs for the difference:
    https://developer.github.com/v3/pulls/

    """
    url = URLObject("https://api.github.com/repos/{}/issues".format(owner_repo))
    if labels:
        url = url.set_query_param('labels', ",".join(labels))
    if since:
        url = url.set_query_param('since', since.isoformat())
    if state:
        url = url.set_query_param('state', state)
    url = url.set_query_param('sort', 'updated')

    issues = PullRequest.from_json(paginated_get(url))
    if org:
        issues = sorted(issues, key=operator.attrgetter("org"))

    pulls = None
    if pull_details == "list":
        issues = list(issues)
        if issues:
            # Request a bunch of pull details up front, for joining to.  We can't
            # ask for exactly the ones we need, so make a guess.
            limit = int(len(issues) * 1.5)
            pull_url = URLObject("https://api.github.com/repos/{}/pulls".format(owner_repo))
            if state:
                pull_url = pull_url.set_query_param('state', state)
            pulls = { pr['number']: pr for pr in paginated_get(pull_url, limit=limit) }

    for issue in issues:
        if pull_details:
            issue.load_pull_details(pulls=pulls)
        issue.id = "{}.{}".format(owner_repo, issue.number)
        yield issue


def get_comments(pull):
    url = URLObject(pull.comments_url).set_query_param("sort", "created").set_query_param("direction", "desc")
    comments = Comment.from_json(paginated_get(url))
    return comments
