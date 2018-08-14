import mock
from testtools import TestCase

from padre import exceptions as excp
from padre import handler
from padre import trigger


class NoOpHandler(handler.TriggeredHandler):
    def run(self, **kwargs):
        pass


def make_handler_cls(handles_what, doc="test", type_name="test"):
    job_cls_dct = {
        'handles_what': handles_what,
        '__doc__': doc,
    }
    return type(type_name, (NoOpHandler,), job_cls_dct)


class HandlerTest(TestCase):
    def test_arg_parsing(self):
        handles_what = {
            'args': {
                'triggers': [
                    trigger.Trigger('test', True),
                ],
                'order': ['a', 'b', 'c'],
            },
        }
        h_cls = make_handler_cls(handles_what)
        m = handler.HandlerMatch("1 2 3")
        kwargs, _validated = h_cls.extract_arguments(m)
        self.assertEqual(kwargs, {'a': '1', 'c': '3', 'b': '2'})
        m = handler.HandlerMatch("a=2 b=3 c=4")
        kwargs, _validated = h_cls.extract_arguments(m)
        self.assertEqual(kwargs, {'a': '2', 'c': '4', 'b': '3'})
        m = handler.HandlerMatch()
        kwargs, _validated = h_cls.extract_arguments(m)
        self.assertEqual(kwargs, {})

    def test_same_arg_parsing(self):
        handles_what = {
            'args': {
                'triggers': [
                    trigger.Trigger('test', True),
                ],
                'order': ['a'],
            },
        }
        h_cls = make_handler_cls(handles_what)
        m = handler.HandlerMatch("a=2 a=4 a=5")
        kwargs, _validated = h_cls.extract_arguments(m)
        self.assertEqual(kwargs, {'a': '5'})

    def test_invalid_arg_parsing(self):
        handles_what = {
            'args': {
                'triggers': [
                    trigger.Trigger('test', True),
                ],
                'order': ['a', 'b', 'c'],
            },
        }
        h_cls = make_handler_cls(handles_what)
        m = handler.HandlerMatch("a=2 4 3")
        self.assertRaises(excp.ArgumentError,
                          h_cls.extract_arguments, m)
        m = handler.HandlerMatch("4 a=2 4")
        self.assertRaises(excp.ArgumentError,
                          h_cls.extract_arguments, m)
        m = handler.HandlerMatch("c=3 a=2 4")
        self.assertRaises(excp.ArgumentError,
                          h_cls.extract_arguments, m)
        m = handler.HandlerMatch("c=3 a=2 4")
        self.assertRaises(excp.ArgumentError,
                          h_cls.extract_arguments, m)

    def test_arg_parsing_defaults(self):
        handles_what = {
            'args': {
                'triggers': [
                    trigger.Trigger('test', True),
                ],
                'order': ['a', 'b', 'c'],
                'defaults': {
                    'a': "4",
                },
            },
        }
        h_cls = make_handler_cls(handles_what)
        m = handler.HandlerMatch("b=3 c=4")
        kwargs, _validated = h_cls.extract_arguments(m)
        self.assertEqual(kwargs, {'a': '4', 'c': '4', 'b': '3'})
        m = handler.HandlerMatch()
        kwargs, _validated = h_cls.extract_arguments(m)
        self.assertEqual(kwargs, {"a": "4"})

    def test_get_help(self):
        bot = mock.MagicMock()
        h_cls = make_handler_cls({
            'triggers': [
                trigger.Trigger('stuff', False),
            ]
        })
        summary, details = h_cls.get_help(bot)
        self.assertEqual(summary, "test")
        self.assertEqual(details, ['_Trigger:_ *stuff*'])
