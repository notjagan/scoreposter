#!/usr/bin/python3

import asyncio
import utils
from datetime import datetime, timedelta

from pytz import timezone

EST = timezone('US/Eastern')
mods_inv = {}
for k, v in utils.MODS.items():
    mods_inv[v] = k


class Player:

    def __init__(self, user_id, osu_api):
        self.user_id = user_id
        self.osu_api = osu_api
        self.tracking = False

    async def is_active(self):
        endpoint = f'users/{self.user_id}/scores/recent'
        parameters = {'include_fails': 1, 'limit': 1}
        data = await self.osu_api.request(endpoint, parameters)
        if len(data) != 1:
            return False
        self.username = data[0]['user']['username']
        timestamp = datetime.fromisoformat(data[0]['created_at'])
        if datetime.now(EST) - timestamp > timedelta(hours=1):
            return False
        return True
    
    async def get_latest_play(self):
        endpoint = f'users/{self.user_id}/scores/recent'
        parameters = {'limit': 1}
        data = await self.osu_api.request(endpoint, parameters)
        if len(data) != 1:
            return None
        return data
    
    async def loop(self):
        latest_play = await self.get_latest_play()
        while True:
            self.tracking = await self.is_active()
            if not self.tracking:
                await asyncio.sleep(60)
                continue
            
            new_play = await self.get_latest_play()
            if new_play == latest_play or latest_play == None:
                continue

            latest_play = new_play
            if latest_play['pp'] is not None and latest_play['pp'] >= 800 and latest_play['replay']:
                pass


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
            async with utils.OsuAPI() as osu_api:
                tracker = cls(user_ids, osu_api)
                await asyncio.gather(*asyncio.all_tasks())
        
        asyncio.run(track_async(cls, user_ids))


if __name__ == "__main__":
    with open(utils.WHITELIST_PATH) as whitelist:
        user_ids = [int(line) for line in whitelist.readlines()]
    Tracker.track(user_ids)
