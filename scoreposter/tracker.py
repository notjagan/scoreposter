#!/usr/bin/python3

import asyncio
from datetime import datetime, timedelta

import utils
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

    async def loop(self):
        latest_play = await self.get_latest_play()
        while True:
            await asyncio.sleep(1)
            try:
                self.tracking = await self.is_active()
                if not self.tracking:
                    await asyncio.sleep(60)
                    continue

                new_play = await self.get_latest_play()
                if latest_play is None or new_play['id'] == latest_play['id']:
                    continue

                latest_play = new_play
                if latest_play['pp'] is not None and latest_play['pp'] >= 700 and latest_play['replay']:
                    score_id = latest_play['best_id']
                    replay_path = await self.osu_api.download_replay(score_id)
                    score = Score(replay_path, self.osu_api)
                    await score._init()
                    options = PostOptions()
                    post = Post(score, options)
                    post.submit()
                    print(post.title)

            except Exception:
                import traceback
                traceback.print_exc()


class Tracker:

    def __init__(self, user_ids, osu_api):
        self.players = [Player(user_id, osu_api) for user_id in user_ids]
        event_loop = asyncio.get_event_loop()
        for player in self.players:
            event_loop.create_task(player.loop())
        event_loop.create_task(self.tracking_status())

    async def tracking_status(self):
        await asyncio.sleep(10)
        while True:
            tracking = ", ".join(player.username for player in self.players if player.tracking)
            print(f"Currently tracking: {tracking}")
            await asyncio.sleep(300)

    @classmethod
    def track(cls, user_ids):
        async def track_async(cls, user_ids):
            async with utils.OsuAPI(mode=utils.OsuAuthenticationMode.AUTHORIZATION_CODE) as osu_api:
                cls(user_ids, osu_api)
                await asyncio.gather(*asyncio.all_tasks())

        asyncio.run(track_async(cls, user_ids))


if __name__ == "__main__":
    with open(utils.WHITELIST_PATH) as whitelist:
        user_ids = [int(line) for line in whitelist.readlines()]
    Tracker.track(user_ids)
