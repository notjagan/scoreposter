#!/usr/bin/python3

import asyncio
from copy import deepcopy
from enum import Enum, auto
from pathlib import Path

import cv2
import numpy as np
import requests
from osrparse.enums import Mod
from PIL import Image, ImageDraw, ImageFont
from score import Rank, Score
from utils import MODS, OsuAPI

ASSETS_PATH = Path('../assets')
FONT_PATH = ASSETS_PATH / 'TruenoRg.otf'
RANK_COLORS = {
    Rank.SS_PLUS:   '#cdd0c8ff',
    Rank.SS:        '#f2d469ff',
    Rank.S_PLUS:    '#cdd0c8ff',
    Rank.S:         '#f2d469ff',
    Rank.A:         '#54cc51ff',
    Rank.B:         '#4f79d8ff',
    Rank.C:         '#c55dbfff',
    Rank.D:         '#cb304dff'
}


class Anchor(Enum):
    TOP = auto()
    BOTTOM = auto()
    LEFT = auto()
    RIGHT = auto()
    CENTER = auto()


class Position:

    def __init__(self, x, y, x_anchor, y_anchor):
        if isinstance(x, Anchor):
            if x is Anchor.LEFT:
                self.x = 0
            elif x is Anchor.RIGHT:
                self.x = 1920 - 1
            else:
                self.x = int(1920/2)
        else:
            self.x = x

        if isinstance(y, Anchor):
            if y is Anchor.TOP:
                self.y = 0
            elif y is Anchor.BOTTOM:
                self.y = 1080 - 1
            else:
                self.y = int(1080/2)
        else:
            self.y = y

        self.x_anchor = x_anchor
        self.y_anchor = y_anchor
        self.width = 0
        self.height = 0
        self.offset = 0

    def left(self):
        if self.x_anchor is Anchor.LEFT:
            return self.x + self.offset
        if self.x_anchor is Anchor.RIGHT:
            return self.x - self.width + self.offset
        return int(self.x - self.width/2) + self.offset

    def top(self):
        if self.y_anchor is Anchor.TOP:
            return self.y
        if self.y_anchor is Anchor.BOTTOM:
            return self.y - self.height
        return int(self.y - self.height/2)


RANK_LETTER_POSITION = Position(Anchor.CENTER, 411, Anchor.CENTER, Anchor.BOTTOM)
ACCURACY_POSITION = Position(Anchor.CENTER, 554, Anchor.CENTER, Anchor.TOP)
PP_POSITION = Position(1443, 176, Anchor.CENTER, Anchor.TOP)
STARS_POSITION = Position(282, 672, Anchor.RIGHT, Anchor.BOTTOM)
PFP_POSITION = Position(102, 138, Anchor.LEFT, Anchor.TOP)
USERNAME_POSITION = Position(324, 232, Anchor.LEFT, Anchor.BOTTOM)
COMBO_POSITION = Position(445, 960, Anchor.CENTER, Anchor.CENTER)
RANKS_POSITION = Position(324, 272, Anchor.LEFT, Anchor.CENTER)
TITLE_POSITION = Position(Anchor.CENTER, 494, Anchor.CENTER, Anchor.BOTTOM)
MODS_POSITION = Position(1769, 377, Anchor.RIGHT, Anchor.CENTER)
HITS_POSITION = Position(Anchor.CENTER, 772, Anchor.CENTER, Anchor.CENTER)
UR_POSITION = Position(Anchor.CENTER, 863, Anchor.CENTER, Anchor.BOTTOM)
MISSES_POSITION = Position(1705, 867, Anchor.RIGHT, Anchor.CENTER)
SB_POSITION = Position(1660, 867, Anchor.RIGHT, Anchor.CENTER)

ACCURACY_SIZE = 209
PP_SIZE = 151
STARS_SIZE = 77
USERNAME_MIN_SIZE = 0
USERNAME_MAX_SIZE = 77
USERNAME_MAX_WIDTH = 400
COMBO_SIZE = 82
RANKS_SIZE = 50
TITLE_MIN_SIZE = 30
TITLE_MAX_SIZE = 50
TITLE_MAX_WIDTH = 1665
HITS_SIZE = 42
UR_SIZE = 42
MISS_SIZE = 100
SB_SIZE = 100
PFP_LENGTH = 186
PFP_RADIUS = 20
FLAG_WIDTH = 45
FLAG_HEIGHT = 30
RANKS_SPACE_1 = 15
RANKS_SPACE_2 = 5
MOD_OVERLAP = 22
MOD_WIDTH = 88
MOD_HEIGHT = 62
HITS_SPACE_1 = 13
HITS_SPACE_2 = 33
FG_LAYER = 4

WHITE = '#ffffffff'
BLACK = '#ffffffff'
GOLD = '#f2d469ff'
LIGHT_GRAY = '#545454ff'
DARK_GRAY = '#414141ff'
RED = '#e35353ff'


class Renderable:

    def width(self):
        pass

    def height(self):
        pass

    def render(self, *args):
        pass


class ImageRenderable(Renderable):

    def __init__(self, image):
        self.image = image

    def width(self):
        return self.image.shape[1]

    def height(self):
        return self.image.shape[0]

    def render(self, pos, layers, i):
        left, top = pos.left(), pos.top()
        h, w = self.image.shape[:2]
        layers[i, top:top+h, left:left+w] = self.image


class TextRenderable(Renderable):

    @staticmethod
    def fit_size(text, min_size, max_size, max_width):
        for size in range(max_size, min_size - 1, -1):
            font = ImageFont.truetype(str(FONT_PATH), size)
            width = font.getmask(text).getbbox()[2]
            if width <= max_width:
                return size
        raise OverflowError()

    def __init__(self, text, size, color):
        self.text = text
        self.font = ImageFont.truetype(str(FONT_PATH), size)
        self.color = color

    def width(self):
        return self.font.getmask(self.text).getbbox()[2]

    def height(self):
        return self.font.getmask(self.text).getbbox()[3]

    def _offset(self):
        correction_factor = 1/6
        ascent, descent = self.font.getmetrics()
        return -correction_factor*(ascent - descent)/2

    def render(self, pos, layers, i):
        left = pos.left()
        y = pos.y
        if pos.y_anchor is Anchor.TOP:
            anchor = 'lt'
        elif pos.y_anchor is Anchor.BOTTOM:
            anchor = 'ls'
        else:
            anchor = 'lm'
            y += self._offset()

        image = Image.fromarray(cv2.cvtColor(layers[i], cv2.COLOR_BGRA2RGBA))
        draw = ImageDraw.Draw(image)
        draw.text((left, y), self.text, fill=self.color, anchor=anchor, font=self.font)
        layers[i] = cv2.cvtColor(np.array(image), cv2.COLOR_BGRA2RGBA)


class ShadowOptions:

    def __init__(self, color, opacity, angle, distance, size):
        self.color = color
        self.opacity = opacity
        self.angle = angle
        self.distance = distance
        self.size = size


DEFAULT_SHADOW = ShadowOptions('#000000', 90, np.radians(135), 20, 5)


class TextShadowRenderable(TextRenderable):

    def __init__(self, text, size, color, shadow_options=DEFAULT_SHADOW):
        super().__init__(text, size, color)
        self.text_renderable = TextRenderable(text, size, color)
        self.options = shadow_options
        self.shadow_renderable = TextRenderable(text, size, self.options.color)

    def render(self, pos, layers, i):
        shadow_pos = deepcopy(pos)
        shadow_pos.offset -= self.options.distance*np.cos(self.options.angle)
        shadow_pos.y += self.options.distance*np.sin(self.options.angle)
        self.shadow_renderable.render(shadow_pos, layers, i)
        layers[i] = cv2.blur(
            (layers[i].astype(np.float) * self.options.opacity/255).astype(np.uint8),
            (self.options.size, self.options.size)
        )
        self.text_renderable.render(pos, layers, FG_LAYER)


class SpaceRenderable(Renderable):

    def __init__(self, w):
        self.w = w

    def width(self):
        return self.w


def render_chain(renderables, position, layers, i):
    width = sum(r.width() for r in renderables)
    pos = deepcopy(position)
    pos.width = width
    for renderable in renderables:
        pos.height = renderable.height()
        renderable.render(pos, layers, i)
        pos.offset += renderable.width()


def rounded_rectangle_mask(length, radius, tol=0.01):
    x = np.arange(-length/2, length/2, 1, dtype=np.float)
    y = np.arange(-length/2, length/2, 1, dtype=np.float)
    x_values, y_values = np.meshgrid(x, y)

    def mask(dim):
        nonlocal length, radius
        circles = ((np.abs(dim) - length/2 + radius)/radius)**2
        rectangle = (np.abs(dim) >= length/2 - radius)
        return rectangle * circles

    mask = (mask(x_values) + mask(y_values) <= 1 + tol)[..., None]
    return mask


def download_image(url):
    response = requests.get(url, stream=True)
    if url.endswith('.gif'):
        import imageio
        gif = imageio.mimread(bytes(response.raw.read()))
        return cv2.cvtColor(gif[0], cv2.COLOR_RGBA2BGRA)
    array = np.asarray(bytearray(response.raw.read()), dtype="uint8")
    return cv2.imdecode(array, cv2.IMREAD_UNCHANGED)


def render(func):
    def wrapper(score, position, layers, i=FG_LAYER):
        nonlocal func
        renderables = func(score)
        render_chain(renderables, position, layers, i)

    return wrapper


@render
def render_rank_letter(score):
    image_path = (ASSETS_PATH / 'ranks' / score.rank.name).with_suffix('.png')
    image = cv2.imread(str(image_path), cv2.IMREAD_UNCHANGED)
    return (ImageRenderable(image),)


@render
def render_accuracy(score):
    return (TextShadowRenderable(f'{score.accuracy:.2f}%', ACCURACY_SIZE, RANK_COLORS[score.rank]),)


@render
def render_pp(score):
    return (TextShadowRenderable(f'{score.pp:.0f}pp', PP_SIZE, GOLD),)


@render
def render_stars(score):
    return (TextRenderable(f'{score.stars:.2f}', STARS_SIZE, LIGHT_GRAY),)


@render
def render_pfp(score):
    image = download_image(score.user['avatar_url'])
    if image.shape[2] == 3:
        image = cv2.cvtColor(image, cv2.COLOR_BGR2BGRA)

    mask = rounded_rectangle_mask(PFP_LENGTH, PFP_RADIUS)
    cropped = mask*cv2.resize(image, (PFP_LENGTH, PFP_LENGTH))
    return (ImageRenderable(cropped),)


@render
def render_username(score):
    size = TextRenderable.fit_size(score.player,
                                   USERNAME_MIN_SIZE,
                                   USERNAME_MAX_SIZE,
                                   USERNAME_MAX_WIDTH)
    return (TextRenderable(score.player, size, WHITE),)


@render
def render_combo(score):
    return (TextRenderable(f'{score.combo}×', COMBO_SIZE, DARK_GRAY),)


@render
def render_ranks(score):
    global_rank = score.user['statistics']['global_rank']
    country_rank = score.user['statistics']['rank']['country']
    country_code = score.user['country']['code']
    image = download_image(f'http://osu.ppy.sh/images/flags/{country_code}.png')
    flag = cv2.resize(image, (FLAG_WIDTH, FLAG_HEIGHT))
    return (
        TextRenderable(f'#{global_rank}  (#{country_rank}', RANKS_SIZE, GOLD),
        SpaceRenderable(RANKS_SPACE_1),
        ImageRenderable(flag),
        SpaceRenderable(RANKS_SPACE_2),
        TextRenderable(')', RANKS_SIZE, GOLD)
    )


@render
def render_title(score):
    try:
        size = TextRenderable.fit_size(f'{score.title} [{score.difficulty}]',
                                       TITLE_MIN_SIZE,
                                       TITLE_MAX_SIZE,
                                       TITLE_MAX_WIDTH)
        return (
            TextRenderable(score.title, size, WHITE),
            SpaceRenderable(TextRenderable('t', size, WHITE).width()),
            TextRenderable(f'[{score.difficulty}]', size, GOLD)
        )
    except OverflowError:
        size = TextRenderable.fit_size(score.title,
                                       0,
                                       TITLE_MAX_SIZE,
                                       TITLE_MAX_WIDTH)
        return (TextRenderable(score.title, size, WHITE),)


@render
def render_mods(score):
    n = len(score.mods)
    if n == 0:
        return ()

    layers = np.zeros((n, MOD_HEIGHT, n*MOD_WIDTH - (n - 1)*MOD_OVERLAP, 4))
    offset = 0
    for i, mod in enumerate(score.mods):
        image_path = (ASSETS_PATH / 'mods' / MODS[mod]).with_suffix('.png')
        image = cv2.imread(str(image_path), cv2.IMREAD_UNCHANGED)
        layers[i, :, offset:offset + MOD_WIDTH] = image
        offset += MOD_WIDTH - MOD_OVERLAP
    flattened = flatten(layers)
    return (ImageRenderable(flattened),)


@render
def render_hits(score):
    small_space = SpaceRenderable(HITS_SPACE_1)
    large_space = SpaceRenderable(HITS_SPACE_2)
    path_300 = ASSETS_PATH / 'hits' / '300.png'
    path_100 = ASSETS_PATH / 'hits' / '100.png'
    path_50 = ASSETS_PATH / 'hits' / '50.png'
    image_300 = cv2.imread(str(path_300), cv2.IMREAD_UNCHANGED)
    image_100 = cv2.imread(str(path_100), cv2.IMREAD_UNCHANGED)
    image_50 = cv2.imread(str(path_50), cv2.IMREAD_UNCHANGED)

    return (
        TextRenderable(str(score.hits[0]), HITS_SIZE, WHITE),
        small_space,
        ImageRenderable(image_300),
        large_space,
        TextRenderable(str(score.hits[1]), HITS_SIZE, WHITE),
        small_space,
        ImageRenderable(image_100),
        large_space,
        TextRenderable(str(score.hits[2]), HITS_SIZE, WHITE),
        small_space,
        ImageRenderable(image_50)
    )


@render
def render_ur(score):
    if Mod.DoubleTime in score.mods or Mod.Nightcore in score.mods:
        text = f"{score.ur:.2f} cv.UR"
    else:
        text = f"{score.ur:.2f} UR"
    return (TextRenderable(text, UR_SIZE, GOLD),)


@render
def render_misses(score):
    if score.misses == 0:
        return ()
    return (TextRenderable(str(score.misses), MISS_SIZE, RED),)


@render
def render_sliderbreaks(score):
    if score.sliderbreaks == 0:
        return ()
    return (TextRenderable(str(score.sliderbreaks), SB_SIZE, WHITE),)


def crop_background(image):
    height, width, _ = image.shape
    if width/height >= 1920/1080:
        ratio = 1080/height
        resized = cv2.resize(image, (0, 0), fx=ratio, fy=ratio)
        w = resized.shape[1]
        return resized[:, int(w/2 - 1920/2):int(w/2 + 1920/2)]
    ratio = 1920/width
    resized = cv2.resize(image, (0, 0), fx=ratio, fy=ratio)
    h = resized.shape[0]
    return resized[int(h/2 - 1080/2):int(h/2 + 1080/2)]


def flatten(layers):
    alpha = layers[..., 3]/255
    beta = np.roll(1 - alpha, -1, axis=0)
    beta[-1, ...] = 1
    coeffs = alpha*np.flipud(np.cumprod(np.flipud(beta), 0))
    opaque = np.copy(layers)
    opaque[..., 3] = 255
    return np.einsum('ijkl,ijk->jkl', opaque, coeffs)


def render_results(score, options, output_path=Path('output/results.png')):
    template_dir = ASSETS_PATH / 'templates'
    if score.misses != 0:
        if score.sliderbreaks != 0:
            template_path = template_dir / 'miss+sb.png'
        else:
            template_path = template_dir / 'miss.png'
    elif score.sliderbreaks != 0:
        template_path = template_dir / 'sb.png'
    else:
        template_path = template_dir / 'fc.png'

    background = crop_background(cv2.imread(str(score.bg_path), cv2.IMREAD_COLOR))
    background = cv2.cvtColor(background, cv2.COLOR_BGR2BGRA)
    template = cv2.imread(str(template_path), cv2.IMREAD_UNCHANGED)
    layers = np.zeros([5, 1080, 1920, 4], dtype=np.uint8)
    layers[0] = background
    layers[1] = template

    render_rank_letter(score, RANK_LETTER_POSITION, layers)
    render_accuracy(score, ACCURACY_POSITION, layers, 2)
    render_stars(score, STARS_POSITION, layers)
    render_pfp(score, PFP_POSITION, layers)
    render_username(score, USERNAME_POSITION, layers)
    render_combo(score, COMBO_POSITION, layers)
    render_ranks(score, RANKS_POSITION, layers)
    render_title(score, TITLE_POSITION, layers)
    render_mods(score, MODS_POSITION, layers)
    render_hits(score, HITS_POSITION, layers)
    render_ur(score, UR_POSITION, layers)

    if options.show_pp:
        render_pp(score, PP_POSITION, layers, 3)

    miss_pos = deepcopy(MISSES_POSITION)
    if score.sliderbreaks != 0 and options.show_sliderbreaks:
        miss_pos.x = SB_POSITION.x
    render_misses(score, miss_pos, layers)

    if options.show_sliderbreaks:
        sb_pos = deepcopy(SB_POSITION)
        if score.misses != 0:
            sb_pos.y = 758
        render_sliderbreaks(score, sb_pos, layers)

    flattened = flatten(layers)
    cv2.imwrite(str(output_path), flattened)


async def create_score(replay_path):
    async with OsuAPI() as osu_api:
        score = await Score.from_replay(replay_path, osu_api)
    return score


if __name__ == "__main__":
    from sys import argv

    from post import PostOptions

    replay_path = argv[1]
    score = asyncio.run(create_score(replay_path))
    options = PostOptions()
    render_results(score, options)
