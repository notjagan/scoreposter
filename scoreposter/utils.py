import json
import sqlite3
from collections import OrderedDict
from enum import Enum
from pathlib import Path

import praw
import requests
from circleguard import Circleguard
from osrparse.enums import Mod

KEYS_PATH = 'keys.json'
CONFIG_PATH = 'config.json'
DB_PATH = 'cache.db'

OSU_URL = 'https://osu.ppy.sh'
V1_URL = f'{OSU_URL}/api'
V2_URL = f'{V1_URL}/v2'

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


def get_osu_headers():
    endpoint = f'{OSU_URL}/oauth/token'
    payload = {
        'client_id':        OSU_CLIENT_ID,
        'client_secret':    OSU_CLIENT_SECRET,
        'grant_type':       'client_credentials',
        'scope':            'public'
    }
    response = requests.post(endpoint, data=payload)
    data = json.loads(response.text)
    token_type = data['token_type']
    access_token = data['access_token']

    headers = {'Authorization': f'{token_type} {access_token}'}
    return headers


def request_osu_api(endpoint, parameters={}, version=OsuAPIVersion.V2):
    if version is OsuAPIVersion.V1:
        url = f'{V1_URL}/{endpoint}'
        parameters['k'] = OSU_API_KEY
        response = requests.get(url, params=parameters)
    else:
        url = f'{V2_URL}/{endpoint}'
        response = requests.get(url, params=parameters, headers=osu_headers)

    data = json.loads(response.text)
    return data


def refresh_db(db_path=OSU_PATH / 'osu!.db'):
    from osu_db_tools.osu_to_sqlite import create_db
    create_db(db_path)


osu_headers = get_osu_headers()
