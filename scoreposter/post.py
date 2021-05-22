from pathlib import Path

from results import render_results
from utils import subreddit

RESULTS_PATH = Path('output/results.png')


class PostOptions:

    def __init__(self, show_pp=True, show_fc_pp=True, show_combo=None,
                 show_ur=True, show_sliderbreaks=True, show_mapper=False,
                 message=None):
        self.show_pp = show_pp
        self.show_fc_pp = show_fc_pp
        self.show_combo = show_combo
        self.show_ur = show_ur
        self.show_sliderbreaks = show_sliderbreaks
        self.show_mapper = show_mapper
        self.message = message


class Post:

    def __init__(self, score, options):
        self.score = score
        self.options = options

    @property
    def title(self):
        return self.score.construct_title(self.options)

    def submit(self):
        render_results(self.score, self.options)
        subreddit.submit_image(self.title, RESULTS_PATH)
