from testtools import TestCase

from padre import slack_utils as su


class SlackUtilsTests(TestCase):
    def test_parse(self):
        text = "hello <@josh>"
        text_pieces = su.parse(text)
        self.assertEqual(2, len(text_pieces))
        self.assertEqual("josh", text_pieces[1].link)
        self.assertIsNone(text_pieces[1].label)

    def test_parse_with_label(self):
        text = "hello <http://google.com|google>"
        text_pieces = su.parse(text)
        self.assertEqual(2, len(text_pieces))
        self.assertEqual("http://google.com", text_pieces[1].link)
        self.assertEqual("google", text_pieces[1].label)

    def test_targets(self):
        text = "<@josh> <@bob> hi <@joe>"
        text_pieces = su.parse(text)
        targets, leftover = su.extract_targets(text_pieces)
        self.assertIn('josh', targets)
        self.assertIn('bob', targets)
        self.assertNotIn('joe', targets)
        self.assertEqual(" hi <@joe>", "".join(t.text for t in leftover))

    def test_no_targets_leftover(self):
        text = "hi <@joe>"
        text_pieces = su.parse(text)
        targets, leftover = su.extract_targets(text_pieces)
        self.assertEqual(0, len(targets))
        self.assertEqual("hi <@joe>", "".join(t.text for t in leftover))

    def test_drop_links(self):
        text = "hello <http://google.com|google>"
        text_pieces = su.parse(text)
        text = su.drop_links(text_pieces)
        self.assertEqual("hello google", text)

    def test_drop_links_no_label(self):
        text = "hello <http://google.com|google>"
        text_pieces = su.parse(text)
        text = su.drop_links(text_pieces, use_label=False)
        self.assertEqual("hello http://google.com", text)

    def test_channel_check(self):
        self.assertEqual(su.ChannelKind.DIRECTED,
                         su.ChannelKind.convert("D123"))
        self.assertEqual(su.ChannelKind.PUBLIC,
                         su.ChannelKind.convert("C4NC67U3"))
        self.assertEqual(su.ChannelKind.PUBLIC,
                         su.ChannelKind.convert("G4NC67U3"))
        self.assertEqual(su.ChannelKind.UNKNOWN,
                         su.ChannelKind.convert("NC67U3"))
        self.assertEqual(su.ChannelKind.UNKNOWN,
                         su.ChannelKind.convert(""))
