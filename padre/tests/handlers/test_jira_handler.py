import mock
import munch
from testtools import TestCase

from padre import channel as c
from padre.handlers import jira
from padre.tests import common


class JiraUnplannedHandlerTest(TestCase):
    def test_expected_handled(self):
        bot = mock.MagicMock()
        bot.config = munch.Munch()
        bot.clients = munch.Munch()

        m = common.make_message(
            text="jira unplanned 'blah blah'", to_me=True)
        self.assertTrue(jira.UnplannedHandler.handles(
            m, c.TARGETED, bot.config))

        m = common.make_message(
            text="jira not unplanned 'blah blah'", to_me=True)
        self.assertFalse(jira.UnplannedHandler.handles(
            m, c.TARGETED, bot.config))

    def test_created_issue_bound_and_resolved(self):
        m = common.make_message(
            text="jira unplanned 'blah blah'", to_me=True,
            user_name="bob")

        jira_client = mock.MagicMock()
        bot = common.make_bot()
        bot.clients.jira_client = jira_client
        mock_issue = mock.MagicMock()
        mock_issue.id = '789'

        jira_client.projects.return_value = [
            munch.Munch({
                'name': 'CAA',
                'key': 'CAA',
                'id': 'CAA',
            }),
        ]
        jira_client.boards.return_value = [
            munch.Munch({
                'name': 'CAA board',
                'id': "abc",
            })
        ]
        jira_client.create_issue.return_value = mock_issue
        jira_client.sprints.return_value = [
            munch.Munch({
                'name': '10-10-11',
                'id': "123",
                'state': 'closed',
            }),
            munch.Munch({
                'name': '10-10-10',
                'id': "124",
                'state': 'active',
            }),
        ]
        jira_client.transitions.return_value = [
            munch.Munch({
                'name': 'resolved',
                'id': 'xyz',
            }),
        ]

        h_m = jira.UnplannedHandler.handles(m, c.TARGETED, bot.config)
        h = jira.UnplannedHandler(bot, m)
        h.run(h_m)

        jira_client.boards.assert_called()
        jira_client.sprints.assert_called()
        jira_client.projects.assert_called()

        jira_client.create_issue.assert_called_with(fields={
            'description': mock.ANY,
            'summary': 'blah blah',
            'project': 'CAA',
            'components': [{'name': 'Unplanned'}],
            'issuetype': {'name': 'Task'},
            'assignee': {'name': 'bob'},
        })

        jira_client.add_issues_to_sprint.assert_called_with('124', mock.ANY)
        jira_client.transition_issue.assert_called_with('789', 'xyz',
                                                        comment=mock.ANY)
