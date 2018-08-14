from testtools import TestCase

from padre import utils


class UtilsTests(TestCase):
    def test_chunking(self):
        d = list(range(0, 100))
        d_chunked = list(utils.iter_chunks(d, 25))
        self.assertEqual(4, len(d_chunked))
        self.assertEqual(list(range(0, 25)), d_chunked[0])
        self.assertEqual(list(range(25, 50)), d_chunked[1])
        self.assertEqual(list(range(50, 75)), d_chunked[2])
        self.assertEqual(list(range(75, 100)), d_chunked[3])

    def test_merge(self):
        a = {
            'a': 'b',
        }
        b = {
            'c': 'd',
        }
        n = utils.merge_dict(a, b)
        self.assertEqual({'a': 'b', 'c': 'd'}, n)

    def test_merge_none(self):
        a = {
            'a': 'b',
        }
        b = None
        n = utils.merge_dict(a, b)
        self.assertEqual({'a': 'b'}, n)

    def test_to_ordinal(self):
        self.assertEqual("1st", utils.to_ordinal(1))
        self.assertEqual("2nd", utils.to_ordinal(2))
        self.assertEqual("3rd", utils.to_ordinal(3))
        self.assertEqual("4th", utils.to_ordinal(4))
        self.assertEqual("5th", utils.to_ordinal(5))
        self.assertEqual("6th", utils.to_ordinal(6))
        self.assertEqual("7th", utils.to_ordinal(7))
        self.assertEqual("8th", utils.to_ordinal(8))
        self.assertEqual("9th", utils.to_ordinal(9))
        self.assertEqual("11th", utils.to_ordinal(11))
        self.assertEqual("12th", utils.to_ordinal(12))
        self.assertEqual("13th", utils.to_ordinal(13))
        self.assertEqual("22nd", utils.to_ordinal(22))
        self.assertRaises(ValueError, utils.to_ordinal, 0)
        self.assertRaises(ValueError, utils.to_ordinal, -1)

    def test_extract(self):
        d = {
            "a": {
                "b": 1,
            },
            "c": True,
        }
        self.assertEqual(1, utils.dict_or_munch_extract(d, "a.b"))
        self.assertEqual(True, utils.dict_or_munch_extract(d, "c"))
        self.assertRaises(ValueError, utils.dict_or_munch_extract, d, "")
        self.assertRaises(TypeError, utils.dict_or_munch_extract, d, "c.e")
        self.assertRaises(TypeError, utils.dict_or_munch_extract, d, "a.b.c")
        self.assertRaises(KeyError, utils.dict_or_munch_extract, d, "a.e")

    def test_elapsed(self):
        secs_elapsed = 0
        self.assertEqual("0 seconds", utils.format_seconds(secs_elapsed))

        secs_elapsed = 1
        self.assertEqual("1 second", utils.format_seconds(secs_elapsed))

        secs_elapsed = 60 * 60 * 24 * 7 * 52
        self.assertEqual("1 year", utils.format_seconds(secs_elapsed))

        secs_elapsed = 60 * 60 * 24 * 7 * 52 * 2
        self.assertEqual("2 years", utils.format_seconds(secs_elapsed))

        secs_elapsed = (60 * 60 * 24 * 7 * 52 * 2) + 1
        self.assertEqual("2 years and 1 second",
                         utils.format_seconds(secs_elapsed))

        secs_elapsed = (60 * 60 * 24 * 7 * 52 * 1) + (60 * 60) + 60 + 1
        self.assertEqual('1 year, 1 hour, 1 minute and 1 second',
                         utils.format_seconds(secs_elapsed))

        secs_elapsed = (60 * 60 * 24 * 7 * 52 * 1) + (60 * 60) + 180 + 1
        self.assertEqual('1 year, 1 hour, 3 minutes and 1 second',
                         utils.format_seconds(secs_elapsed))

        secs_elapsed = (60 * 60 * 24 * 7 * 52 * 2) + (60 * 60) + 180 + 1
        self.assertEqual('2 years, 1 hour, 3 minutes and 1 second',
                         utils.format_seconds(secs_elapsed))

        secs_elapsed = 60 * 60 * 24 * 7
        self.assertEqual("1 week", utils.format_seconds(secs_elapsed))

        secs_elapsed = 60 * 60 * 24 * 7 * 4
        self.assertEqual("4 weeks", utils.format_seconds(secs_elapsed))

        secs_elapsed = (60 * 60 * 24 * 7) + (60 * 60 * 24)
        self.assertEqual("1 week and 1 day",
                         utils.format_seconds(secs_elapsed))

        secs_elapsed = 60 * 60 * 24
        self.assertEqual("1 day", utils.format_seconds(secs_elapsed))

        secs_elapsed = 60 * 60 * 24 * 2
        self.assertEqual("2 days", utils.format_seconds(secs_elapsed))

        secs_elapsed = 60 * 60 * 24 + (60 * 60 * 2 + 61)
        self.assertEqual("1 day, 2 hours, 1 minute and 1 second",
                         utils.format_seconds(secs_elapsed))

        secs_elapsed = 60 * 60
        self.assertEqual("1 hour", utils.format_seconds(secs_elapsed))

        secs_elapsed = 60 * 60 * 2
        self.assertEqual("2 hours", utils.format_seconds(secs_elapsed))

        secs_elapsed = 60
        self.assertEqual("1 minute", utils.format_seconds(secs_elapsed))

        secs_elapsed = 60 * 2
        self.assertEqual("2 minutes", utils.format_seconds(secs_elapsed))

        secs_elapsed = 61
        self.assertEqual("1 minute and 1 second",
                         utils.format_seconds(secs_elapsed))

        secs_elapsed = 60 * 60 + 61
        self.assertEqual("1 hour, 1 minute and 1 second",
                         utils.format_seconds(secs_elapsed))
