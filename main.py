#!/usr/bin/python3

import os
import sys
import json
import glob
import argparse
import configparser
from functools import reduce
from subprocess import check_output
from collections import OrderedDict

import cv2
import sqlite3
import requests
import pyperclip
import numpy as np
from oppai import *
from PIL import Image
from colors import color
from osrparse.enums import Mod
from osrparse import parse_replay_file
from pytesseract import pytesseract as pt

OSU_PATH = r'/mnt/c/Users/notja/AppData/Local/osu!'
OSU_URL = 'http://osu.ppy.sh'
V1_URL = f'{OSU_URL}/api'
V2_URL = f'{V1_URL}/v2'

with open('api.json') as file:
    data = json.load(file)
    API_KEY = data['key']
    CLIENT_ID = data['id']
    CLIENT_SECRET = data['secret']

with open(f'{OSU_PATH}/osu!.notja.cfg') as file:
    content = '[header]\n' + file.read()

config = configparser.RawConfigParser()
config.read_string(content)
windows_dir = config['header']['BeatmapDirectory']
BEATMAPS_DIR = check_output(['wslpath', windows_dir]).decode().strip()

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

db = sqlite3.connect('cache.db')


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
            self.show_combo = args.show_combo
            self.show_ur = args.show_ur
            self.message = args.message
        elif options is not None:
            for key, value in options.items():
                setattr(self, key, value)


class Score:

    def __init__(self, replay, screenshot):
        self.replay = replay
        self.screenshot = screenshot

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
        cur = db.cursor()
        cur.execute('SELECT beatmap_id, folder_name, map_file, artist, title, difficulty FROM maps WHERE md5_hash=?',
                    (self.replay.beatmap_hash,))
        self.beatmap_id, folder_name, map_file, self.artist, \
            self.title, self.difficulty = cur.fetchone()
        self.map_path = os.path.join(BEATMAPS_DIR, folder_name,
                                     map_file)
        cur.close()

    def get_id(self):
        endpoint = f'{V1_URL}/get_user'
        parameters = {
            'k':        API_KEY,
            'u':        self.player,
            'type':     'string'
        }

        response = requests.get(endpoint, params=parameters)
        data = json.loads(response.text)[0]
        self.user_id = int(data['user_id'])

    def get_mods(self):
        self.mods = set(self.replay.mod_combination)
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
        self.submission = None
        endpoint = f'{V2_URL}/users/{self.user_id}/scores/recent'
        parameters = {'limit': 1}
        response = requests.get(endpoint, params=parameters,
                                headers=headers)
        data = json.loads(response.text)
        if 'error' in data or len(data) != 1:
            return

        score = data[0]
        if self.matches_score(score):
            self.submission = score
            print(color("Submission found!", color='green'))

    def get_status(self):
        self.ranked = False
        self.loved = False
        self.submitted = True

        if self.submission is not None:
            beatmap = submission['beatmap']
        else:
            endpoint = f'{V2_URL}/beatmaps/{self.beatmap_id}'
            response = requests.get(endpoint, headers=headers)
            beatmap = json.loads(response.text)

        status = beatmap['status']
        if status == 'ranked':
            self.ranked = True
            if self.submission is not None and \
               self.submission['pp'] is None:
                self.submitted = False
        elif status == 'loved':
            self.loved = True

    def calculate_statistics(self):
        ez = ezpp_new()
        ezpp_set_autocalc(ez, 1)

        with open(self.map_path) as file:
            data = file.read()
            ezpp_data_dup(ez, data, len(data.encode('utf-8')))
        ezpp_set_mods(ez, reduce(lambda a, v: a | v.value,
                                 self.mods, 0))

        self.stars = ezpp_stars(ez)
        self.max_combo = ezpp_max_combo(ez)

        ezpp_set_combo(ez, self.combo)
        ezpp_set_nmiss(ez, self.misses)
        ezpp_set_accuracy_percent(ez, self.accuracy)

        if self.submission is not None and \
           self.ranked and self.submitted:
            self.pp = submission['pp']
        else:
            self.pp = ezpp_pp(ez)

        ezpp_set_combo(ez, self.max_combo)
        ezpp_set_nmiss(ez, 0)
        self.fcpp = ezpp_pp(ez)

    def find_ur(self):
        grayscale = cv2.cvtColor(self.screenshot, cv2.COLOR_BGR2GRAY)
        region = grayscale[864:864+144, 363:363+663]
        laplacian = cv2.Laplacian(region, cv2.CV_64F)
        ret, thresh = cv2.threshold(laplacian, 100, 255,
                                    cv2.THRESH_BINARY)
        dilation = cv2.dilate(thresh, np.ones((3, 3), np.uint8))
        opening = cv2.morphologyEx(dilation, cv2.MORPH_OPEN,
                                   np.ones((5, 5), np.uint8))
        mask = region > 220
        y, x = np.min(np.where(opening * mask), axis=1)
        crop = region[y+38:y+55, x+115:x+174]

        resized = cv2.resize(crop, (0, 0), fx=4, fy=4)
        image = Image.fromarray(resized)
        whitelist = '-c tessedit_char_whitelist=1234567890.'
        text = pt.image_to_string(image, config=whitelist)
        try:
            self.raw_ur = float(text.strip())
        except:
            print(color("UR could not be read.", fg='red'))
            self.raw_ur = None

    def get_ranking(self):
        self.ranking = None
        if self.ranked or self.loved:
            endpoint = f'{V2_URL}/beatmaps/{self.beatmap_id}/scores'
            response = requests.get(endpoint, headers=headers)
            data = json.loads(response.text)
            if 'error' in data:
                return

            scores = data['scores']
            for rank, score in enumerate(scores, start=1):
                if self.matches_score(score):
                    self.ranking = rank
                    break


def get_oauth_headers():
    payload = {
        'client_id':        CLIENT_ID,
        'client_secret':    CLIENT_SECRET,
        'grant_type':       'client_credentials',
        'scope':            'public'
    }
    response = requests.post(f'{OSU_URL}/oauth/token', data=payload)
    data = json.loads(response.text)
    token_type = data['token_type']
    access_token = data['access_token']

    headers = {'Authorization': f'{token_type} {access_token}'}
    return headers


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('-s', '--sb', dest='sliderbreaks', default=0)
    parser.add_argument('-p', '--no-pp', dest='show_pp',
                        action='store_false')
    parser.add_argument('-c', '--no-combo', dest='show_combo',
                        action='store_false')
    parser.add_argument('-u', '--no-ur', dest='show_ur',
                        action='store_false')
    parser.add_argument('-m', '--message', type=str)
    args = parser.parse_args()
    options = TitleOptions(args=args)

    replays = glob.glob(f'{OSU_PATH}/Replays/*')
    scs = glob.glob(f'{OSU_PATH}/Screenshots/*')
    replay_path = max(replays, key=os.path.getctime)
    sc_path = max(scs, key=os.path.getctime)
    replay = parse_replay_file(replay_path)
    screenshot = cv2.imread(sc_path, cv2.IMREAD_COLOR)

    global headers
    headers = get_oauth_headers()
    score = Score(replay, screenshot)
    title = score.construct_title(options)


if __name__ == '__main__':
    main()

db.close()
