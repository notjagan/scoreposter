import shutil
from enum import Enum, auto
from functools import reduce
from re import search
from tempfile import NamedTemporaryFile

import oppai
import requests
import utils
from circleguard import ReplayPath
from colors import color
from osrparse import parse_replay_file
from osrparse.enums import Mod
from slider.beatmap import Beatmap


class Rank(Enum):
    SS_PLUS = '#cdd0c8'
    SS = '#f2d469'
    S_PLUS = '#cdd0c8'
    S = '#f2d469'
    A = '#54cc51'
    B = '#4f79d8'
    C = '#c55dbf'
    D = '#cb304d'


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
        self.get_user()
        self.get_mods()
        self.calculate_accuracy()
        self.find_submission()
        self.get_status()
        self.calculate_statistics()
        self.find_ur()
        self.get_ranking()
        self.get_rank()

    def process_replay(self):
        self.player = self.replay.player_name
        self.combo = self.replay.max_combo
        self.misses = self.replay.misses

    def process_beatmap(self):
        cur = utils.osu_db.execute('SELECT beatmap_id, folder_name, map_file, artist, '
                                   'title, difficulty FROM maps WHERE md5_hash=?',
                                   (self.replay.beatmap_hash,))
        result = cur.fetchone()
        cur.close()

        if result is not None:
            self.beatmap_id, folder_name, map_file, self.artist, \
                self.title, self.difficulty = result
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
        else:
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

            data = utils.request_osu_api(f'beatmaps/{self.beatmap_id}')
            cover_url = data['beatmapset']['covers']['cover@2x']

            response = requests.get(cover_url, stream=True)
            response.raw_decode_content = True
            with NamedTemporaryFile(mode='wb', delete=False) as image:
                shutil.copyfileobj(response.raw, image)
                self.bg_path = image.name

    def get_id(self):
        parameters = {
            'u':        self.player,
            'type':     'string'
        }

        data = utils.request_osu_api('get_user', parameters,
                                     utils.OsuAPIVersion.V1)[0]
        self.user_id = int(data['user_id'])
    
    def get_user(self):
        self.user = utils.request_osu_api(f'users/{self.user_id}/osu')

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

    def find_submission(self):
        endpoint = f'users/{self.user_id}/scores/recent'
        parameters = {'limit': 1}
        data = utils.request_osu_api(endpoint, parameters)
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
            self.beatmap = utils.request_osu_api(f'beatmaps/{self.beatmap_id}')

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
        self.ur = utils.cg.ur(self.cg_replay)

    def get_ranking(self):
        if self.ranked or self.loved:
            data = utils.request_osu_api(f'beatmaps/{self.beatmap_id}/scores')
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
