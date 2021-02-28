import asyncio
import json
import sqlite3
import webbrowser
from collections import OrderedDict
from enum import Enum
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from time import time
from urllib.parse import parse_qs, urlparse

import aiofiles
import aiohttp
import numpy as np
import praw
import requests
from circleguard import Circleguard
from osrparse.enums import Mod

KEYS_PATH = 'keys.json'
CONFIG_PATH = 'config.json'
DB_PATH = 'cache.db'
WHITELIST_PATH = 'players.list'

OSU_URL = 'https://osu.ppy.sh'
V1_URL = f'{OSU_URL}/api'
V2_URL = f'{V1_URL}/v2'
OSU_RATE_LIMIT = 1200

with open(KEYS_PATH) as file:
    data = json.load(file)
OSU_API_KEY = data['osu_key']
OSU_CLIENT_ID = data['osu_id']
OSU_CLIENT_SECRET = data['osu_secret']
REDDIT_CLIENT_ID = data['reddit_id']
REDDIT_CLIENT_SECRET = data['reddit_secret']
REDDIT_USERNAME = data['username']
REDDIT_PASSWORD = data['password']

cg = Circleguard(OSU_API_KEY)
reddit = praw.Reddit(client_id=REDDIT_CLIENT_ID,
                     client_secret=REDDIT_CLIENT_SECRET,
                     username=REDDIT_USERNAME,
                     password=REDDIT_PASSWORD,
                     user_agent='windows:scoreposter:v1.1.0 (by /u/notjagan)')
reddit.validate_on_submit = True
subreddit = reddit.subreddit("osugame")
osu_db = sqlite3.connect(DB_PATH)

with open(CONFIG_PATH) as file:
    data = json.load(file)
OSU_PATH = Path(data['osu_path'])
BEATMAPS_DIR = Path(data['beatmaps_dir'])

MODS = OrderedDict([(Mod.Easy,          "EZ"),
                    (Mod.NoFail,        "NF"),
                    (Mod.Hidden,        "HD"),
                    (Mod.HalfTime,      "HT"),
                    (Mod.DoubleTime,    "DT"),
                    (Mod.Nightcore,     "NC"),
                    (Mod.HardRock,      "HR"),
                    (Mod.SuddenDeath,   "SD"),
                    (Mod.Perfect,       "PF"),
                    (Mod.Flashlight,    "FL")])


class OsuAPIVersion(Enum):
    V1 = 1
    V2 = 2


class OsuAuthenticationMode(Enum):
    CLIENT_CREDENTIALS = 1
    AUTHORIZATION_CODE = 2


class OsuAPI:

    def __init__(self, key=OSU_API_KEY, client_id=OSU_CLIENT_ID, client_secret=OSU_CLIENT_SECRET,
                 mode=OsuAuthenticationMode.CLIENT_CREDENTIALS):
        self.key = key
        self.client_id = client_id
        self.client_secret = client_secret
        self.headers = self._headers(mode)
        self.times = np.full(OSU_RATE_LIMIT, -np.inf)
        self.index = 0

    async def __aenter__(self):
        self.session = aiohttp.ClientSession()
        return self

    async def __aexit__(self, *args):
        await self.session.close()
        self.session = None

    def _headers(self, mode):
        endpoint = f'{OSU_URL}/oauth/token'
        payload = {
            'client_id':        self.client_id,
            'client_secret':    self.client_secret,
            'grant_type':       'client_credentials',
            'scope':            'public',
        }

        if mode is OsuAuthenticationMode.AUTHORIZATION_CODE:
            endpoint_2 = f'{OSU_URL}/oauth/authorize'
            params = {
                'client_id':        self.client_id,
                'scope':            'public',
                'response_type':    'code',
                'redirect_uri':     'http://localhost:7270'
            }
            request = requests.Request('GET', url=endpoint_2, params=params)
            url = request.prepare().url
            webbrowser.open(url)
            code = get_code()
            payload = {
                'client_id':        self.client_id,
                'client_secret':    self.client_secret,
                'grant_type':       'authorization_code',
                'code':             code,
                'redirect_uri':     'http://localhost:7270'
            }

        response = requests.post(endpoint, data=payload)
        data = json.loads(response.text)
        token_type = data['token_type']
        access_token = data['access_token']

        headers = {'Authorization': f'{token_type} {access_token}'}
        return headers

    async def request(self, endpoint, parameters={}, version=OsuAPIVersion.V2):
        self.index = (self.index + 1) % OSU_RATE_LIMIT
        difference = time() - self.times[self.index]
        if difference < 60:
            await asyncio.sleep(60 - difference)
        self.times[self.index] = time()

        if version is OsuAPIVersion.V1:
            url = f'{V1_URL}/{endpoint}'
            parameters['k'] = self.key
            async with self.session.get(url, params=parameters) as response:
                data = json.loads(await response.text())

        else:
            url = f'{V2_URL}/{endpoint}'
            async with self.session.get(url, params=parameters, headers=self.headers) as response:
                data = json.loads(await response.text())

        return data


def refresh_db(db_path=OSU_PATH / 'osu!.db'):
    from osu_db_tools.osu_to_sqlite import create_db
    create_db(db_path)


def get_code():
    code = None
    running = True

    class Server(BaseHTTPRequestHandler):
        def do_GET(self):
            nonlocal code, running
            components = urlparse(self.path)
            values = parse_qs(components.query)
            code = values['code'][0]
            running = False

    server = HTTPServer(('localhost', 7270), Server)
    while running:
        server.handle_request()

    return code
