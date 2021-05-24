import asyncio
from enum import Enum, auto
from functools import reduce
from pathlib import Path
from re import search

import aiofiles
import oppai
import utils
from circleguard import ReplayPath
from colors import color
from osrparse import parse_replay_file
from osrparse.enums import Mod
from slider.beatmap import Beatmap
from slider.replay import Replay


class Rank(Enum):
    SS_PLUS = auto()
    SS = auto()
    S_PLUS = auto()
    S = auto()
    A = auto()
    B = auto()
    C = auto()
    D = auto()


class Score:

    def __init__(self, replay_path, osu_api):
        self.replay_path = replay_path
        self.osu_api = osu_api
        self.replay = parse_replay_file(replay_path)
        self.process_replay()
        self.get_mods()

    async def _init(self):
        self.submission = None
        self.ranking = None
        self.cg_replay = None

        needs_bg = self.process_beatmap()
        await self.get_id()
        await self.find_submission()

        user_task = asyncio.create_task(self.get_user())
        status_task = asyncio.create_task(self.get_status())
        ranking_task = asyncio.create_task(self.get_ranking())
        bg_task = asyncio.create_task(self.get_background(needs_bg))
        diff_task = asyncio.create_task(self.get_difficulty())

        await user_task
        await status_task
        await ranking_task
        await bg_task
        await diff_task

        self.calculate_accuracy()
        self.calculate_sliderbreaks()
        self.calculate_statistics()
        self.find_ur()
        self.get_rank()

    def process_replay(self):
        self.player = self.replay.player_name
        self.combo = self.replay.max_combo
        self.misses = self.replay.misses

    def process_beatmap(self):
        cur = utils.osu_db.execute('SELECT beatmap_id, folder_name, map_file, artist, '
                                   'title, difficulty, mapper FROM maps WHERE md5_hash=?',
                                   (self.replay.beatmap_hash,))
        result = cur.fetchone()
        cur.close()

        if result is None:
            print(color("Beatmap not in osu!.db, defaulting to Circleguard version.",
                        fg='red'))
            self.cg_replay = ReplayPath(self.replay_path)
            beatmap = utils.cg.beatmap(self.cg_replay)

            self.beatmap_id = self.cg_replay.map_info.map_id
            if self.beatmap_id is None:
                print(color("Beatmap not found.", fg='red'))
            print(color("Cached beatmap found!", fg='green'))

            folder_name = utils.cg.library.path
            cur = utils.cg.library._db.execute('SELECT path from beatmaps WHERE md5=?',
                                               (self.replay.beatmap_hash,))
            map_file = cur.fetchone()[0]
            self.map_path = folder_name / map_file
            cur.close()

            self.artist = beatmap.artist
            self.title = beatmap.title
            self.difficulty = beatmap.version
            self.mapper = beatmap.creator
            return True

        self.beatmap_id, folder_name, map_file, self.artist, \
            self.title, self.difficulty, self.mapper = result
        map_folder = utils.BEATMAPS_DIR / folder_name
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
        return False

    async def get_background(self, needs_bg):
        if not needs_bg:
            return

        self.bg_path = Path('output/bg')
        data = await self.osu_api.request(f'beatmaps/{self.beatmap_id}')
        cover_url = data['beatmapset']['covers']['cover@2x']

        async with self.osu_api.session.get(cover_url) as response:
            async with aiofiles.open(self.bg_path, 'wb') as image:
                await image.write(await response.read())

    async def get_id(self):
        self.user_id = await self.osu_api.username_to_id(self.player)

    async def get_user(self):
        self.user = await self.osu_api.request(f'users/{self.user_id}/osu')

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
        self.hits = [self.replay.number_300s,
                     self.replay.number_100s,
                     self.replay.number_50s,
                     self.replay.misses]
        weighted_sum = sum(hit * weight for hit, weight in zip(self.hits, weights))
        self.accuracy = weighted_sum / sum(self.hits) * 100

    def calculate_sliderbreaks(self):
        replay = Replay.from_path(
            self.replay_path,
            beatmap=Beatmap.from_path(self.map_path),
            retrieve_beatmap=False)
        self.sliderbreaks = len(replay.hits['slider_breaks'])

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
            set(score['mods']) == {utils.MODS[mod] for mod in self.mods}

    async def find_submission(self):
        endpoint = f'users/{self.user_id}/scores/recent'
        parameters = {'limit': 10}
        data = await self.osu_api.request(endpoint, parameters)
        if 'error' in data or len(data) == 0:
            return

        for score in data:
            if self.matches_score(score):
                self.submission = score
                print(color("Submission found!", fg='green'))
                return

    async def get_status(self):
        self.ranked = False
        self.loved = False
        self.submitted = True

        if self.submission is not None:
            self.beatmap = self.submission['beatmap']
        else:
            self.beatmap = await self.osu_api.request(f'beatmaps/{self.beatmap_id}')

        status = self.beatmap['status']
        if status == 'ranked' or status == 'approved':
            self.ranked = True
            if self.submission is not None and self.submission['pp'] is None:
                self.submitted = False
        elif status == 'loved':
            self.loved = True

    async def get_difficulty(self):
        modnum = 0
        for mod in self.mods:
            if mod in [Mod.Easy, Mod.HalfTime, Mod.DoubleTime, Mod.HardRock]:
                modnum |= mod
            elif mod is Mod.Nightcore:
                modnum |= Mod.DoubleTime

        parameters = {'b': self.beatmap_id, 'mods': modnum}
        data = await self.osu_api.request('get_beatmaps', parameters, utils.OsuAPIVersion.V1)
        self.stars = float(data[0]['difficultyrating'])

    def calculate_statistics(self):
        ez = oppai.ezpp_new()
        oppai.ezpp_set_autocalc(ez, 1)

        with open(self.map_path, encoding='utf-8') as file:
            data = file.read()
        oppai.ezpp_data_dup(ez, data, len(data.encode('utf-8')))
        oppai.ezpp_set_mods(ez, reduce(lambda a, v: a | v.value, self.mods, 0))

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
        self.ur = utils.cg.ur(self.cg_replay)

    async def get_ranking(self):
        if self.ranked or self.loved:
            data = await self.osu_api.request(f'beatmaps/{self.beatmap_id}/scores')
            if 'error' in data:
                return

            scores = data['scores']
            for rank, score in enumerate(scores, start=1):
                if self.matches_score(score):
                    self.ranking = rank
                    break

    def get_rank(self):
        total_hits = sum(self.hits)
        ratio = self.hits[0]/total_hits
        if ratio == 1:
            if Mod.Hidden in self.mods:
                self.rank = Rank.SS_PLUS
            else:
                self.rank = Rank.SS
        elif ratio > 0.9 and self.hits[2]/total_hits < 0.1 and self.misses == 0:
            if Mod.Hidden in self.mods:
                self.rank = Rank.S_PLUS
            else:
                self.rank = Rank.S
        elif ratio > 0.8 and self.misses == 0 or ratio > 0.9:
            self.rank = Rank.A
        elif ratio > 0.7 and self.misses == 0 or ratio > 0.8:
            self.rank = Rank.B
        elif ratio > 0.6:
            self.rank = Rank.C
        else:
            self.rank = Rank.D

    def construct_title(self, options):
        if options.show_mapper:
            parenthetical = f"{self.mapper}, {self.stars:.2f}*"
        else:
            parenthetical = f"{self.stars:.2f}*"

        if self.mods:
            modstring = ''.join(string for mod, string in utils.MODS.items()
                                if mod in self.mods)
            base = f"{self.artist} - {self.title} [{self.difficulty}] +{modstring} ({parenthetical})"
        else:
            base = f"{self.artist} - {self.title} [{self.difficulty}] ({parenthetical})"

        self.fc = self.misses == 0 and self.sliderbreaks == 0

        if self.accuracy == 100:
            base += " SS"
        else:
            base += f" {self.accuracy:.2f}%"
            if self.misses != 0:
                base += f" {self.misses}xMiss"
            if self.sliderbreaks != 0 and options.show_sliderbreaks:
                base += f" {self.sliderbreaks}xSB"
            if options.show_combo or options.show_combo is None and not self.fc:
                base += f" {self.combo}/{self.max_combo}x"
            if self.fc:
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
            if options.show_fc_pp and not self.fc:
                pp_text += f" ({self.fcpp:.0f}pp for FC)"
            segments.append(pp_text)

        if options.show_ur and self.ur is not None:
            dt = Mod.DoubleTime in self.mods or \
                 Mod.Nightcore in self.mods
            if dt:
                segments.append(f"{self.ur:.2f} cv.UR")
            else:
                segments.append(f"{self.ur:.2f} UR")

        if options.message is not None:
            segments.append(options.message)

        title = ' | '.join(segments)
        return title

    @classmethod
    async def create_score(cls, replay_path):
        async with utils.OsuAPI() as osu_api:
            score = cls(replay_path, osu_api)
            await score._init()
        return score
