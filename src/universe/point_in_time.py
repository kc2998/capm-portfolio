# src/universe/point_in_time.py

import ssl
import certifi
import requests
import pandas as pd

# Fix SSL certificate verification issues on some systems
ssl._create_default_https_context = lambda: ssl.create_default_context(cafile=certifi.where())

WIKI_URL = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0 Safari/537.36"
    )
}

def fetch_sp500_tables():
    """
    Pulls the two tables off Wikipedia's S&P 500 page.
    Table 0 is the current constituent list.
    Table 1 is the historical changes log.
    """
    # Make a GET request to the Wikipedia page with custom headers
    response = requests.get(WIKI_URL, headers=HEADERS)
    response.raise_for_status()

    tables = pd.read_html(response.text)
    current = tables[0]
    changes = tables[1]
    return current, changes