#!/usr/bin/python3

import argparse
import webbrowser

import pyperclip
from colors import color

import utils
from score import Score
from title import TitleOptions, construct_title

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
    utils.refresh_db()
    print('Database refreshed.')
    exit()

options = TitleOptions(args=args)

replays = (utils.OSU_PATH / 'Replays').glob('*.osr')
screenshots = (utils.OSU_PATH / 'Screenshots').glob('*.jpg')
replay_path = max(replays, key=lambda path: path.stat().st_mtime)
screenshot_path = max(screenshots, key=lambda path: path.stat().st_mtime)

score = Score(replay_path)
title = construct_title(score, options)
print(title)

actions = ['p', 'm', 'o', 'r', 's', 'c', 'b', 't', 'q']
action_text = "/".join(actions)
action = ''
while action != 'q':
    action = ''
    while action not in actions:
        action = input(f"Action ({action_text}): ").lower()

    if action == 'p':
        utils.subreddit.submit_image(title, screenshot_path)
    elif action == 'm':
        message = input("Message: ")
        if message == '':
            message = None
        options.message = message
        title = construct_title(score, options)
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
        title = construct_title(score, options)
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
        title = construct_title(score, options)
        print(title)
    elif action == 'c':
        pyperclip.copy(title)
        print(color("Title copied to clipboard!", fg='green'))
    elif action == 'b':
        webbrowser.open(score.beatmap['url'])
    elif action == 't':
        title = input("Title: ")
