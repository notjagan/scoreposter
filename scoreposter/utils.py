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
        self.times = np.full(OSU_RATE_LIMIT - 1, -np.inf)
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

    async def ensure_rate_limit(self):
        self.index = (self.index + 1) % (OSU_RATE_LIMIT - 1)
        difference = time() - self.times[self.index]
        if difference < 60:
            await asyncio.sleep(60 - difference)
        self.times[self.index] = time()

    def get_current_rate(self):
        previous_minute = np.where(time() - self.times <= 60)[0]
        indices = (self.index - previous_minute) % (OSU_RATE_LIMIT - 1)
        if len(indices) > 0:
            return indices.max() + 1

    async def request(self, endpoint, parameters={}, version=OsuAPIVersion.V2):
        await self.ensure_rate_limit()

        if version is OsuAPIVersion.V1:
            url = f'{V1_URL}/{endpoint}'
            parameters['k'] = self.key
            async with self.session.get(url, params=parameters) as response:
                data = json.loads(await response.text())

        else:
            url = f'{V2_URL}/{endpoint}'
            try:
                async with self.session.get(url, params=parameters, headers=self.headers) as response:
                    data = json.loads(await response.text())
            except json.JSONDecodeError:
                return None

        return data

    async def download_replay(self, score_id):
        await self.ensure_rate_limit()

        replay_path = (Path('output') / str(score_id)).with_suffix('.osr')
        endpoint = f'{V2_URL}/scores/osu/{score_id}/download'
        async with self.session.get(endpoint, headers=self.headers) as response:
            async with aiofiles.open(replay_path, 'wb') as replay:
                await replay.write(await response.read())
        return replay_path

    async def username_to_id(self, username):
        parameters = {
            'u':        username,
            'type':     'string'
        }

        data = await self.request('get_user', parameters, OsuAPIVersion.V1)
        return int(data[0]['user_id'])


def refresh_db(db_path=OSU_PATH / 'osu!.db'):
    from osu_db_tools.osu_to_sqlite import create_db
    create_db(db_path)


def get_code():
    code = None
    running = True

    class Server(BaseHTTPRequestHandler):
        def do_GET(self):
            nonlocal code, running

            response = b'<body onload="window.close()" />'
            self.send_response(200)
            self.send_header("Content-type", "text/html")
            self.send_header("Content-length", len(response))
            self.end_headers()
            self.wfile.write(response)

            components = urlparse(self.path)
            values = parse_qs(components.query)
            code = values['code'][0]
            running = False

        def log_message(self, *args):
            return

    server = HTTPServer(('localhost', 7270), Server)
    while running:
        server.handle_request()

    return code
