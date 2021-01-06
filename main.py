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
from osrparse.enums import Mod
from osrparse import parse_replay_file
from pytesseract import pytesseract as pt

OSU_PATH = r'/mnt/c/Users/notja/AppData/Local/osu!/'
V1_URL = 'http://osu.ppy.sh/api/'
V2_URL = V1_URL + 'v2/'

with open('api.json') as file:
    data = json.load(file)
    API_KEY = data['key']
    CLIENT_ID = data['id']
    CLIENT_SECRET = data['secret']

with open(OSU_PATH + 'osu!.notja.cfg') as file:
    content = '[header]\n' + file.read()

config = configparser.RawConfigParser()
config.read_string(content)
windows_dir = config['header']['BeatmapDirectory']
BEATMAPS_DIR = check_output(['wslpath', windows_dir]).decode().strip()

MODS = OrderedDict(zip([Mod.Easy, Mod.NoFail, Mod.Hidden, Mod.HalfTime, Mod.DoubleTime, Mod.Nightcore, Mod.HardRock, Mod.SuddenDeath, Mod.Perfect, Mod.Flashlight],
                       ["EZ", "NF", "HD", "HT", "DT", "NC", "HR", "SD", "PF", "FL"]))


def refresh_db(db_path=OSU_PATH + 'osu!.db'):
    from osu_db_tools.osu_to_sqlite import create_db
    create_db(OSU_PATH + 'osu!.db')


def find_ur(screenshot):
    grayscale = cv2.cvtColor(screenshot, cv2.COLOR_BGR2GRAY)
    region = grayscale[864:864 + 144, 363:363 + 663]
    laplacian = cv2.Laplacian(region, cv2.CV_64F)
    ret, thresh = cv2.threshold(laplacian, 100, 255, cv2.THRESH_BINARY)
    dilation = cv2.dilate(thresh, np.ones((3, 3), np.uint8))
    opening = cv2.morphologyEx(dilation, cv2.MORPH_OPEN,
                               np.ones((5, 5), np.uint8))
    mask = region > 220
    y, x = np.min(np.where(opening * mask), axis=1)
    crop = region[y + 38:y + 55, x + 115:x + 174]

    resized = cv2.resize(crop, (0, 0), fx=4, fy=4)
    image = Image.fromarray(resized)
    text = pt.image_to_string(image, config="-c tessedit_char_whitelist=1234567890.")
    ur = float(text.strip())

    return ur


def construct_post_title(replay, screenshot, db, options):
    cur = db.cursor()
    cur.execute("SELECT beatmap_id, folder_name, map_file, artist, title, difficulty FROM maps WHERE md5_hash=?",
                (replay.beatmap_hash,))
    beatmap_id, folder_name, map_file, artist, title, difficulty = cur.fetchone()
    map_path = os.path.join(BEATMAPS_DIR, folder_name, map_file)
    cur.close()

    player = replay.player_name
    accuracy = np.average([1, 1/3, 1/6, 0],
                          weights=[replay.number_300s,
                                   replay.number_100s,
                                   replay.number_50s,
                                   replay.misses]
                          ) * 100
    combo = replay.max_combo
    misses = replay.misses

    mods = set(replay.mod_combination)
    if Mod.Nightcore in mods:
        mods.discard(Mod.DoubleTime)
    if Mod.Perfect in mods:
        mods.discard(Mod.SuddenDeath)
    modstring = "".join(string for mod, string in MODS.items()
                               if mod in mods)

    ez = ezpp_new()
    ezpp_set_autocalc(ez, 1)
    with open(map_path) as file:
        data = file.read()
        ezpp_data_dup(ez, data, len(data.encode('utf-8')))
    ezpp_set_mods(ez, reduce(lambda a, v: a | v.value,
                             mods, 0))

    stars = ezpp_stars(ez)
    max_combo = ezpp_max_combo(ez)

    ezpp_set_combo(ez, combo)
    ezpp_set_nmiss(ez, misses)
    ezpp_set_accuracy_percent(ez, accuracy)
    pp = ezpp_pp(ez)

    ezpp_set_combo(ez, max_combo)
    ezpp_set_nmiss(ez, 0)
    fcpp = ezpp_pp(ez)

    ezpp_free(ez)

    misstext = ""
    if misses != 0:
        misstext += f" {misses}xMiss"
    if options.sbcount != 0:
        misstext += f" {options.sbcount}xSB"

    fc = not (misses or options.sbcount)
    combotext = ""
    if options.combo:
        combotext = f" {combo}/{max_combo}x"
    if fc:
        combotext += " FC"
    if options.loved:
        ranked = False
        combotext += " LOVED"

    play = f"{artist} - {title} [{difficulty}] +{modstring} ({stars:.2f}*) {accuracy:.2f}%{misstext}{combotext}"
    segments = [player, play]

    if options.pp:
        pptext = f"{pp:.0f}pp"
        if not options.ranked:
            pptext += " if ranked"
        if not fc:
            pptext += f" ({fcpp:.0f}pp for FC)"
        segments.append(pptext)

    if options.ur:
        ur = find_ur(screenshot)
        dt = Mod.DoubleTime in mods or Mod.Nightcore in mods
        if dt:
            ur *= 2/3
            segments.append(f"{ur:.2f} cv.UR")
        else:
            segments.append(f"{ur:.2f} UR")

    if options.message is not None:
        segments.append(options.message)

    title = " | ".join(segments)
    return title


def main():
    replays = glob.glob(OSU_PATH + 'Replays/*')
    scs = glob.glob(OSU_PATH + 'Screenshots/*')
    replay_path = max(replays, key=os.path.getctime)
    sc_path = max(scs, key=os.path.getctime)
    db_path = 'cache.db'
    
    replay = parse_replay_file(replay_path)
    screenshot = cv2.imread(sc_path, cv2.IMREAD_COLOR)
    db = sqlite3.connect(db_path)

    parser = argparse.ArgumentParser()
    parser.add_argument('-s', '--sb', dest='sbcount', default=0)
    parser.add_argument('-p', '--nopp', dest='pp', action='store_false')
    parser.add_argument('-c', '--nocombo', dest='combo',
                        action='store_false')
    parser.add_argument('-u', '--nour', dest='ur', action='store_false')
    parser.add_argument('-r', '--unranked', dest='ranked',
                        action='store_false')
    parser.add_argument('-l', '--loved', action='store_true')
    parser.add_argument('-m', '--message', type=str)
    args = parser.parse_args()
    
    title = construct_post_title(replay, screenshot, db, args)
    db.close()
    print(title)
    pyperclip.copy(title)


if __name__ == '__main__':
    main()
