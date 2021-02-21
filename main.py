#!/usr/bin/python3

import argparse
import json
import shutil
import sqlite3
import webbrowser
from collections import OrderedDict
from functools import reduce
from pathlib import Path
from re import search
from tempfile import NamedTemporaryFile

import numpy as np
import oppai
import praw
import pyperclip
import requests
from circleguard import Circleguard, ReplayPath
from colors import color
from osrparse import parse_replay_file
from osrparse.enums import Mod
from slider.beatmap import Beatmap

KEYS_PATH = 'keys.json'
CONFIG_PATH = 'config.json'

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


class TitleOptions:

    def __init__(self, *, args=None, options=None):
        self.sliderbreaks = 0
        self.show_pp = True
        self.show_combo = True
        self.show_ur = True
        self.message = None

        if args is not None:
            self.sliderbreaks = args.sliderbreaks
            self.show_pp = args.show_pp
            self.show_fc_pp = args.show_fc_pp
            self.show_combo = args.show_combo
            self.show_ur = args.show_ur
            self.message = args.message
        elif options is not None:
            for key, value in options.items():
                setattr(self, key, value)


class Score:

    def __init__(self, replay_path):
        self.replay_path = replay_path
        self.replay = parse_replay_file(replay_path)

        self.submission = None
        self.ranking = None
        self.cg_replay = None

        self.process_replay()
        self.process_beatmap()
        self.get_id()
        self.get_mods()
        self.calculate_accuracy()
        self.find_submission()
        self.get_status()
        self.calculate_statistics()
        self.find_ur()
        self.get_ranking()

    def process_replay(self):
        self.player = self.replay.player_name
        self.combo = self.replay.max_combo
        self.misses = self.replay.misses

    def process_beatmap(self):
        cur = db.execute('SELECT beatmap_id, folder_name, map_file, artist, '
                         'title, difficulty FROM maps WHERE md5_hash=?',
                         (self.replay.beatmap_hash,))
        result = cur.fetchone()
        cur.close()

        if result is not None:
            self.beatmap_id, folder_name, map_file, self.artist, \
                self.title, self.difficulty = result
            map_folder = BEATMAPS_DIR / folder_name
            self.map_path = map_folder / map_file

            with open(self.map_path) as file:
                lines = file.readlines()
            groups = Beatmap._find_groups(lines)
            events = groups['Events']
            for line in events:
                if any(ext in line for ext in ['.jpg', '.jpeg', '.png']):
                    bg_file = search('"(.+?)"', line).group(1)
                    break
            self.bg_path = map_folder / bg_file
        else:
            print(color("Beatmap not in osu!.db, defaulting to Circleguard version.",
                        fg='red'))
            self.cg_replay = ReplayPath(self.replay_path)
            beatmap = cg.beatmap(self.cg_replay)

            self.beatmap_id = self.cg_replay.map_info.map_id
            if self.beatmap_id is None:
                print(color("Beatmap not found.", fg='red'))
            print(color("Cached beatmap found!", fg='green'))

            folder_name = cg.library.path
            cur = cg.library._db.execute('SELECT path from beatmaps WHERE md5=?',
                                         (self.replay.beatmap_hash,))
            map_file = cur.fetchone()[0]
            self.map_path = folder_name / map_file
            cur.close()

            self.artist = beatmap.artist
            self.title = beatmap.title
            self.difficulty = beatmap.version

            endpoint = f'{V2_URL}/beatmaps/{self.beatmap_id}'
            response = requests.get(endpoint, headers=osu_headers)
            data = json.loads(response.text)
            cover_url = data['beatmapset']['covers']['cover@2x']

            response = requests.get(cover_url, stream=True)
            response.raw_decode_content = True
            with NamedTemporaryFile(mode='wb', delete=False) as image:
                shutil.copyfileobj(response.raw, image)
                self.bg_path = image.name

    def get_id(self):
        endpoint = f'{V1_URL}/get_user'
        parameters = {
            'k':        OSU_API_KEY,
            'u':        self.player,
            'type':     'string'
        }

        response = requests.get(endpoint, params=parameters)
        data = json.loads(response.text)[0]
        self.user_id = int(data['user_id'])

    def get_mods(self):
        self.mods = {mod for mod in Mod
                     if mod & self.replay.mod_combination}
        self.mods.discard(Mod.NoMod)
        if Mod.Nightcore in self.mods:
            self.mods.discard(Mod.DoubleTime)
        if Mod.Perfect in self.mods:
            self.mods.discard(Mod.SuddenDeath)

    def calculate_accuracy(self):
        weights = [300/300, 100/300, 50/300, 0/300]
        hits = [self.replay.number_300s,
                self.replay.number_100s,
                self.replay.number_50s,
                self.replay.misses]
        self.accuracy = np.average(weights, weights=hits) * 100

    def matches_score(self, score):
        stats = score['statistics']
        beatmap = score['beatmap']
        return beatmap['id'] == self.beatmap_id and                 \
            score['user_id'] == self.user_id and                    \
            stats['count_300'] == self.replay.number_300s and       \
            stats['count_100'] == self.replay.number_100s and       \
            stats['count_50'] == self.replay.number_50s and         \
            stats['count_miss'] == self.misses and                  \
            score['max_combo'] == self.combo and                    \
            set(score['mods']) == {MODS[mod] for mod in self.mods}

    def find_submission(self):
        endpoint = f'{V2_URL}/users/{self.user_id}/scores/recent'
        parameters = {'limit': 1}
        response = requests.get(endpoint, params=parameters,
                                headers=osu_headers)
        data = json.loads(response.text)
        if 'error' in data or len(data) != 1:
            return

        score = data[0]
        if self.matches_score(score):
            self.submission = score
            print(color("Submission found!", fg='green'))

    def get_status(self):
        self.ranked = False
        self.loved = False
        self.submitted = True

        if self.submission is not None:
            self.beatmap = self.submission['beatmap']
        else:
            endpoint = f'{V2_URL}/beatmaps/{self.beatmap_id}'
            response = requests.get(endpoint, headers=osu_headers)
            self.beatmap = json.loads(response.text)

        status = self.beatmap['status']
        if status == 'ranked' or status == 'approved':
            self.ranked = True
            if self.submission is not None and self.submission['pp'] is None:
                self.submitted = False
        elif status == 'loved':
            self.loved = True

    def calculate_statistics(self):
        ez = oppai.ezpp_new()
        oppai.ezpp_set_autocalc(ez, 1)

        with open(self.map_path, encoding='utf-8') as file:
            data = file.read()
        oppai.ezpp_data_dup(ez, data, len(data.encode('utf-8')))
        oppai.ezpp_set_mods(ez, reduce(lambda a, v: a | v.value, self.mods, 0))

        self.stars = oppai.ezpp_stars(ez)
        self.max_combo = max(self.combo, oppai.ezpp_max_combo(ez))

        oppai.ezpp_set_combo(ez, self.combo)
        oppai.ezpp_set_nmiss(ez, self.misses)
        oppai.ezpp_set_accuracy_percent(ez, self.accuracy)

        if self.submission is not None and self.ranked and self.submitted:
            self.pp = self.submission['pp']
        else:
            self.pp = oppai.ezpp_pp(ez)

        oppai.ezpp_set_combo(ez, self.max_combo)
        oppai.ezpp_set_nmiss(ez, 0)
        self.fcpp = oppai.ezpp_pp(ez)

        oppai.ezpp_free(ez)

    def find_ur(self):
        if self.cg_replay is None:
            self.cg_replay = ReplayPath(self.replay_path)
        self.ur = cg.ur(self.cg_replay)

    def get_ranking(self):
        if self.ranked or self.loved:
            endpoint = f'{V2_URL}/beatmaps/{self.beatmap_id}/scores'
            response = requests.get(endpoint, headers=osu_headers)
            data = json.loads(response.text)
            if 'error' in data:
                return

            scores = data['scores']
            for rank, score in enumerate(scores, start=1):
                if self.matches_score(score):
                    self.ranking = rank
                    break

    def construct_title(self, options):
        if self.mods:
            modstring = ''.join(string for mod, string in MODS.items()
                                if mod in self.mods)
            base = f"{self.artist} - {self.title} [{self.difficulty}] +{modstring} ({self.stars:.2f}*)"
        else:
            base = f"{self.artist} - {self.title} [{self.difficulty}] ({self.stars:.2f}*)"

        fc = self.misses == 0 and options.sliderbreaks == 0

        if self.accuracy == 100:
            base += " SS"
        else:
            base += f" {self.accuracy:.2f}%"
            if self.misses != 0:
                base += f" {self.misses}xMiss"
            if options.sliderbreaks != 0:
                base += f" {options.sliderbreaks}xSB"
            if options.show_combo or not fc:
                base += f" {self.combo}/{self.max_combo}x"
            if fc:
                base += " FC"

        if self.ranking is not None:
            base += f" #{self.ranking}"
        if self.loved:
            base += " LOVED"

        segments = [self.player, base]

        if options.show_pp:
            pp_text = f"{self.pp:.0f}pp"
            if not self.ranked:
                pp_text += " if ranked"
            elif not self.submitted:
                pp_text += " if submitted"
            if options.show_fc_pp and not fc:
                pp_text += f" ({self.fcpp:.0f}pp for FC)"
            segments.append(pp_text)

        if options.show_ur and self.ur is not None:
            dt = Mod.DoubleTime in self.mods or Mod.Nightcore in self.mods
            if dt:
                segments.append(f"{self.ur:.2f} cv.UR")
            else:
                segments.append(f"{self.ur:.2f} UR")

        if options.message is not None:
            segments.append(options.message)

        title = ' | '.join(segments)
        return title


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


def post_score(title, screenshot_path):
    subreddit.submit_image(title, image_path=screenshot_path)
    print(color("Post submitted!", fg='green'))


def refresh_db(db_path=OSU_PATH / 'osu!.db'):
    from osu_db_tools.osu_to_sqlite import create_db
    create_db(db_path)


db = sqlite3.connect('cache.db')
osu_headers = get_osu_headers()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('-s', '--sb', dest='sliderbreaks', default=0)
    parser.add_argument('-p', '--no-pp', dest='show_pp',
                        action='store_false')
    parser.add_argument('-f', '--no-fc-pp', dest='show_fc_pp',
                        action='store_false')
    parser.add_argument('-c', '--no-combo', dest='show_combo',
                        action='store_true')
    parser.add_argument('-u', '--no-ur', dest='show_ur',
                        action='store_false')
    parser.add_argument('-m', '--message', type=str)
    parser.add_argument('-r', '--refresh-db', dest='refresh',
                        action='store_true')
    args = parser.parse_args()

    if args.refresh:
        refresh_db()
        print('Database refreshed.')
        return

    options = TitleOptions(args=args)

    replays = (OSU_PATH / 'Replays').glob('*.osr')
    screenshots = (OSU_PATH / 'Screenshots').glob('*.jpg')
    replay_path = max(replays, key=lambda path: path.stat().st_mtime)
    screenshot_path = max(screenshots, key=lambda path: path.stat().st_mtime)

    score = Score(replay_path)
    title = score.construct_title(options)
    print(title)

    actions = ['p', 'm', 'o', 'r', 's', 'c', 'b', 't', 'q']
    action_text = "/".join(actions)
    action = ''
    while action != 'q':
        action = ''
        while action not in actions:
            action = input(f"Action ({action_text}): ").lower()

        if action == 'p':
            post_score(title, screenshot_path)
        elif action == 'm':
            message = input("Message: ")
            if message == '':
                message = None
            options.message = message
            title = score.construct_title(options)
            print(title)
        elif action == 'o':
            to_toggle = input("Options (p/f/c/u): ")
            if 'p' in to_toggle:
                options.show_pp = not options.show_pp
            if 'f' in to_toggle:
                options.show_fc_pp = not options.show_fc_pp
            if 'c' in to_toggle:
                options.show_combo = not options.show_combo
            if 'u' in to_toggle:
                options.show_ur = not options.show_ur
            title = score.construct_title(options)
            print(title)
        elif action == 'r':
            print("Checking for submission...")
            score.find_submission()
            if score.submission is not None:
                score.get_status()
                score.calculate_statistics()
                score.get_ranking()
            else:
                print(color("Submission not found.", fg='red'))
        elif action == 's':
            try:
                sliderbreaks = int(input("Sliderbreaks: "))
            except ValueError:
                continue
            options.sliderbreaks = sliderbreaks
            score.calculate_statistics()
            title = score.construct_title(options)
            print(title)
        elif action == 'c':
            pyperclip.copy(title)
            print(color("Title copied to clipboard!", fg='green'))
        elif action == 'b':
            webbrowser.open(score.beatmap['url'])
        elif action == 't':
            title = input("Title: ")

    db.close()


if __name__ == '__main__':
    main()
