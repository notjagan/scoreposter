#!/usr/bin/python3

import argparse
import asyncio
import webbrowser

import pyperclip
import utils
from colors import color
from post import Post, PostOptions
from score import Score


async def run_interactive_mode(replay_path, options):
    score = await Score.create_score(replay_path)
    post = Post(score, options)
    print(title := post.title)

    actions = ['p', 'm', 'o', 's', 'c', 'b', 'q']
    action_text = "/".join(actions)
    action = ''
    while action != 'q':
        action = ''
        while action not in actions:
            action = input(f"Action ({action_text}): ").lower()

        if action == 'p':
            post.submit()
            print(color("Post submitted!", fg='green'))
        elif action == 'm':
            message = input("Message: ")
            if message == '':
                message = None
            options.message = message
            print(title := post.title)
        elif action == 'o':
            to_toggle = input("Options (p/f/c/u/m): ")
            if 'p' in to_toggle:
                options.show_pp = not options.show_pp
            if 'f' in to_toggle:
                options.show_fc_pp = not options.show_fc_pp
            if 'c' in to_toggle:
                options.show_combo = not options.show_combo
            if 'u' in to_toggle:
                options.show_ur = not options.show_ur
            if 'm' in to_toggle:
                options.show_mapper = not options.show_mapper
            print(title := post.title)
        elif action == 's':
            try:
                sliderbreaks = int(input("Sliderbreaks: "))
            except ValueError:
                continue
            score.sliderbreaks = sliderbreaks
            score.calculate_statistics()
            print(title := post.title)
        elif action == 'c':
            pyperclip.copy(title)
            print(color("Title copied to clipboard!", fg='green'))
        elif action == 'b':
            webbrowser.open(score.beatmap['url'])


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('replay', nargs='?', default=None)
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

    options = PostOptions(
        show_pp=args.show_pp,
        show_fc_pp=args.show_fc_pp,
        show_combo=args.show_combo,
        show_ur=args.show_ur,
        message=args.message
    )

    replay_path = args.replay
    if replay_path is None:
        replays = (utils.OSU_PATH / 'Replays').glob('*.osr')
        replay_path = max(replays, key=lambda path: path.stat().st_mtime)

    asyncio.run(run_interactive_mode(replay_path, options))


if __name__ == '__main__':
    main()
