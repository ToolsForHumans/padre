import requests_mock
from testtools import TestCase

from padre import channel as c
from padre import handler
from padre.handlers import stock
from padre.tests import common


class StockHandlerTest(TestCase):
    def test_expected_handled(self):
        bot = common.make_bot()

        m = common.make_message(text="stock", to_me=True)
        self.assertTrue(stock.Handler.handles(m, c.TARGETED, bot.config))

        m = common.make_message(text="stock gddy", to_me=True)
        self.assertTrue(stock.Handler.handles(m, c.TARGETED, bot.config))

        m = common.make_message(text="stocks", to_me=True)
        self.assertEqual(
            stock.Handler.handles(m, c.TARGETED, bot.config), None)

    def test_stock(self):
        bot = common.make_bot()

        m = common.make_message(text="stock",
                                to_me=True, user_id="me")

        h = stock.Handler(bot, m)

        stock_reply = """symbol,price,volume
gddy,100000,33324324
"""

        with requests_mock.mock() as req_m:
            req_m.get(h.stock_url, text=stock_reply)
            h.run(handler.HandlerMatch())

        m.reply_text.assert_called_once_with(
            u'```\nSymbol      Price    Volume\n'
            u'--------  -------  --------\n'
            u'gddy       100000  33324324\n```',
            prefixed=False, threaded=True)
