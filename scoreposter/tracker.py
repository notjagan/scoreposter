#!/usr/bin/python3

import argparse
import asyncio
from datetime import datetime, timedelta

import utils
from interactive import run_interactive_mode
from post import Post, PostOptions
from pytz import timezone
from score import Score

EST = timezone('US/Eastern')


class Player:

    def __init__(self, user_id, osu_api):
        self.user_id = user_id
        self.osu_api = osu_api
        self.tracking = False

    async def is_active(self):
        endpoint = f'users/{self.user_id}/scores/recent'
        parameters = {'include_fails': 1, 'limit': 1}
        data = await self.osu_api.request(endpoint, parameters)
        if not isinstance(data, list) or len(data) != 1:
            return False
        self.username = data[0]['user']['username']
        timestamp = datetime.fromisoformat(data[0]['created_at'])
        if datetime.now(EST) - timestamp > timedelta(minutes=30):
            return False
        return True

    async def get_latest_play(self):
        endpoint = f'users/{self.user_id}/scores/recent'
        parameters = {'limit': 1}
        data = await self.osu_api.request(endpoint, parameters)
        if not isinstance(data, list) or len(data) != 1:
            return None
        return data[0]

    async def iter_plays(self):
        latest_play = await self.get_latest_play()
        last_yielded = latest_play
        while True:
            await asyncio.sleep(0.25)
            try:
                new_play = await self.get_latest_play()
                if new_play is None or new_play == latest_play or \
                   last_yielded is not None and last_yielded['id'] == new_play['id']:
                    continue

                latest_play = new_play
                if latest_play['replay']:
                    last_yielded = latest_play
                    yield latest_play

            except Exception:
                import traceback
                traceback.print_exc()

    async def loop(self):
        latest_play = await self.get_latest_play()
        last_posted = latest_play
        while True:
            await asyncio.sleep(1)
            try:
                self.tracking = await self.is_active()
                if not self.tracking:
                    await asyncio.sleep(60)
                    continue

                new_play = await self.get_latest_play()
                if new_play is None or new_play == latest_play or \
                   last_posted is not None and last_posted['id'] == new_play['id']:
                    continue

                latest_play = new_play
                if latest_play['pp'] is not None and latest_play['pp'] >= 700 and latest_play['replay']:
                    last_posted = latest_play
                    score = Score.from_submission(latest_play, self.osu_api)
                    options = PostOptions(show_combo=False)
                    post = Post(score, options)
                    post.submit()
                    print(post.title)

            except Exception:
                import traceback
                traceback.print_exc()


class Tracker:

    def __init__(self, user_ids, osu_api):
        self.osu_api = osu_api
        self.players = [Player(user_id, self.osu_api) for user_id in user_ids]
        event_loop = asyncio.get_event_loop()
        for player in self.players:
            event_loop.create_task(player.loop())
        event_loop.create_task(self.tracking_status())

    async def tracking_status(self):
        await asyncio.sleep(10)
        while True:
            tracking = ", ".join(player.username for player in self.players if player.tracking)
            print(f"Currently tracking: {tracking}")
            rate = self.osu_api.get_current_rate()
            if rate is not None:
                print(f"API call load: {rate:.0f}/{utils.OSU_RATE_LIMIT} per minute")
            await asyncio.sleep(300)

    @classmethod
    def track(cls, user_ids):
        async def track_async(cls, user_ids):
            async with utils.OsuAPI(mode=utils.OsuAuthenticationMode.AUTHORIZATION_CODE) as osu_api:
                cls(user_ids, osu_api)
                await asyncio.gather(*asyncio.all_tasks())

        asyncio.run(track_async(cls, user_ids))


async def loop_plays(user_id=None, username=None):
    async with utils.OsuAPI(mode=utils.OsuAuthenticationMode.AUTHORIZATION_CODE) as osu_api:
        print("Awaiting replays.")
        if user_id is None:
            user_id = await osu_api.username_to_id(username)
        player = Player(user_id, osu_api)
        async for submission in player.iter_plays():
            print("Replay found!")
            await run_interactive_mode(PostOptions(), osu_api, submission=submission)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument('--id', type=int)
    parser.add_argument('--username', type=str)
    args = parser.parse_args()

    if args.id is not None:
        asyncio.run(loop_plays(user_id=args.id))
    elif args.username is not None:
        asyncio.run(loop_plays(username=args.username))
    else:
        with open(utils.WHITELIST_PATH) as whitelist:
            user_ids = [int(line) for line in whitelist.readlines()]
        Tracker.track(user_ids)
