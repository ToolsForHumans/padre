import csv
import logging
from six.moves.urllib import parse as urllib

import requests
import six
import tabulate

from voluptuous import All
from voluptuous import Length
from voluptuous import Required
from voluptuous import Schema

from padre import channel as c
from padre import handler
from padre import matchers
from padre import schema_utils as scu
from padre import trigger
from padre import utils

LOG = logging.getLogger(__name__)


class Handler(handler.TriggeredHandler):
    """Get stock information."""

    stock_url = 'https://www.alphavantage.co/query'

    # NOTE: If more than 100 symbols are included, the API will
    # return quotes for the first 100 symbols.
    #
    # In order to fix that just split into 100 size chunks...
    max_per_call = 100

    handles_what = {
        'message_matcher': matchers.match_or(
            matchers.match_slack("message"),
            matchers.match_telnet("message")
        ),
        'channel_matcher': matchers.match_channel(c.TARGETED),
        'triggers': [
            trigger.Trigger('stock', takes_args=True),
        ],
        'args': {
            'order': ['symbols'],
            'converters': {},
            'schema': Schema({
                Required("symbols"): All(scu.string_types(), Length(min=1)),
            }),
            'help': {
                'symbols': 'symbol(s) to lookup (comma separated)',
            },
            'defaults': {
                'symbols': 'gddy',
            },
        },
    }

    def _run(self, **kwargs):
        symbols = kwargs.get('symbols', "")
        symbols = symbols.split(",")
        symbols = [s.strip() for s in symbols if s.strip()]
        seen_symbols = set()
        headers = ["Symbol", "Price", "Volume"]
        rows = []
        uniq_symbols = []
        for s in symbols:
            tmp_s = s.upper()
            if tmp_s in seen_symbols:
                continue
            else:
                uniq_symbols.append(tmp_s)
                seen_symbols.add(tmp_s)
        for batch in utils.iter_chunks(uniq_symbols, self.max_per_call):
            url = self.stock_url + "?"
            url += urllib.urlencode({
                'function': 'BATCH_STOCK_QUOTES',
                'symbols': ",".join(batch),
                'datatype': 'csv',
                'apikey': self.config.stock.apikey,
            })
            resp = requests.get(url)
            resp.raise_for_status()
            for row in csv.DictReader(
                    six.StringIO(resp.content.decode('utf-8'))):
                rows.append([
                    row['symbol'],
                    row['price'],
                    row['volume'],
                ])
        lines = [
            "```",
            tabulate.tabulate(rows, headers=headers),
            "```",
        ]
        replier = self.message.reply_text
        replier("\n".join(lines), threaded=True, prefixed=False)
