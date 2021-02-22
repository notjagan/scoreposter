#!/usr/bin/python3

from copy import deepcopy
from enum import Enum, auto
from functools import reduce
from pathlib import Path
from sys import argv

import cv2
import numpy as np
import requests
from osrparse.enums import Mod
from PIL import Image, ImageDraw, ImageFont
from score import Rank, Score
from title import TitleOptions
import utils


ASSETS_PATH = Path('../assets')
FONT_PATH = ASSETS_PATH / 'TruenoRg.otf'


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
        elif self.x_anchor is Anchor.RIGHT:
            return self.x - self.width + self.offset
        else:
            return int(self.x - self.width/2) + self.offset
        
    def top(self):
        if self.y_anchor is Anchor.TOP:
            return self.y
        elif self.y_anchor is Anchor.BOTTOM:
            return self.y - self.height
        else:
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
MODS_POSITION = Position(1582, 377, Anchor.CENTER, Anchor.CENTER)
HITS_POSITION = Position(Anchor.CENTER, 772, Anchor.CENTER, Anchor.CENTER)
UR_POSITION = Position(Anchor.CENTER, 863, Anchor.CENTER, Anchor.BOTTOM)

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
HITS_SIZE = 42
UR_SIZE = 42
PFP_LENGTH = 186
PFP_RADIUS = 20

WHITE = '#ffffffff'
BLACK = '#ffffffff'
GOLD = '#f2d469ff'
LIGHT_GRAY = '#545454ff'
DARK_GRAY = '#414141ff'


class Renderable:
    def width(self):
        pass
    
    def height(self):
        pass
    
    def render(self, pos):
        return ()


class ImageRenderable(Renderable):
    def __init__(self, image):
        self.image = image
    
    def width(self):
        return self.image.shape[1]
    
    def height(self):
        return self.image.shape[0]
    
    def render(self, pos):
        left, top = pos.left(), pos.top()
        h, w = self.image.shape[:2]
        layer = np.zeros((1080, 1920, 4))
        layer[top:top+h, left:left+w] = self.image
        return layer,


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
    
    def render(self, pos):
        left = pos.left()
        image = Image.new('RGBA', (1920, 1080), (0, 0, 0, 0))
        draw = ImageDraw.Draw(image)
        
        y = pos.y
        if pos.y_anchor is Anchor.TOP:
            anchor = 'lt'
        elif pos.y_anchor is Anchor.BOTTOM:
            anchor = 'ls'
        else:
            anchor = 'lm'
            y += self._offset()
        
        draw.text((left, y), self.text, fill=self.color, anchor=anchor, font=self.font)
        layer = cv2.cvtColor(np.array(image), cv2.COLOR_RGBA2BGRA)
        return layer,


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
    
    def render(self, pos):
        shadow_pos = deepcopy(pos)
        shadow_pos.offset -= self.options.distance*np.cos(self.options.angle)
        shadow_pos.y += self.options.distance*np.sin(self.options.angle)
        shadow_layer, = self.shadow_renderable.render(shadow_pos)
        shadow_layer = (shadow_layer.astype(np.float) * self.options.opacity/255).astype(np.uint8)
        shadow_layer = cv2.blur(shadow_layer, (self.options.size, self.options.size))
        
        text_layer, = self.text_renderable.render(pos)
        return shadow_layer, text_layer


class SpaceRenderable(Renderable):
    def __init__(self, w):
        self.w = w
    
    def width(self):
        return self.w


def render_chain(renderables, position):
    width = sum(r.width() for r in renderables)
    pos = deepcopy(position)
    pos.width = width
    layers = []
    for renderable in renderables:
        pos.height = renderable.height()
        layers.extend(renderable.render(pos))
        pos.offset += renderable.width()
    return layers


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
    array = np.asarray(bytearray(response.raw.read()), dtype="uint8")
    return cv2.imdecode(array, cv2.IMREAD_UNCHANGED)


def render(func):
    def wrapper(score, layers, position):
        nonlocal func
        renderables = func(score)
        layers.extend(render_chain(renderables, position))

    return wrapper


@render
def render_rank_letter(score):
    image_path = (ASSETS_PATH / 'ranks' / score.rank.name).with_suffix('.png')
    image = cv2.imread(str(image_path), cv2.IMREAD_UNCHANGED)
    return ImageRenderable(image),


@render
def render_accuracy(score):
    return TextShadowRenderable(f'{score.accuracy:.2f}%', ACCURACY_SIZE, score.rank.value + 'ff'),


@render
def render_pp(score):
    return TextShadowRenderable(f'{score.pp:.0f}pp', PP_SIZE, GOLD),


@render
def render_stars(score):
    return TextRenderable(f'{score.stars:.2f}', STARS_SIZE, LIGHT_GRAY),


@render
def render_pfp(score):
    image = download_image(score.user['avatar_url'])
    if image.shape[2] == 3:
        image = cv2.cvtColor(image, cv2.COLOR_BGR2BGRA)
    
    mask = rounded_rectangle_mask(PFP_LENGTH, PFP_RADIUS)
    cropped = mask*cv2.resize(image, (PFP_LENGTH, PFP_LENGTH))
    return ImageRenderable(cropped),


@render
def render_username(score):
    size = TextRenderable.fit_size(score.player,
                                   USERNAME_MIN_SIZE,
                                   USERNAME_MAX_SIZE,
                                   USERNAME_MAX_WIDTH)
    return TextRenderable(score.player, size, WHITE),


def layer_images(image, overlay):
    bgr = overlay[..., :3]
    alpha = overlay[..., 3]/255
    return bgr*alpha[..., None] + image*(1 - alpha)[..., None]


def crop_background(image):
    height, width, _ = image.shape
    if width/height >= 1920/1080:
        ratio = 1080/height
        resized = cv2.resize(image, (0, 0), fx=ratio, fy=ratio)
        w = resized.shape[1]
        return resized[:, int(np.floor(w/2) - 1920/2):int(np.ceil(w/2) + 1920/2)]
    else:
        ratio = 1920/width
        resized = cv2.resize(image, (0, 0), fx=ratio, fy=ratio)
        h = resized.shape[0]
        return resized[int(np.floor(h/2) - 1080/2):int(np.ceil(h/2) + 1080/2)]


def render_results(score, options, output_path=Path('output/results.png')):   
    template_dir = ASSETS_PATH / 'templates'
    if score.misses != 0:
        if options.sliderbreaks != 0:
            template_path = template_dir / 'miss+sb.png'
        else:
            template_path = template_dir / 'miss.png'
    elif options.sliderbreaks != 0:
        template_path = template_dir / 'sb.png'
    else:
        template_path = template_dir / 'fc.png'
    
    background = crop_background(cv2.imread(str(score.bg_path), cv2.IMREAD_COLOR))
    template = cv2.imread(str(template_path), cv2.IMREAD_UNCHANGED)
    layers = [background, template]

    render_rank_letter(score, layers, RANK_LETTER_POSITION)
    render_accuracy(score, layers, ACCURACY_POSITION)
    render_pp(score, layers, PP_POSITION)
    render_stars(score, layers, STARS_POSITION)
    render_pfp(score, layers, PFP_POSITION)
    render_username(score, layers, USERNAME_POSITION)

    flattened = reduce(layer_images, layers)
    cv2.imwrite(str(output_path), flattened)


if __name__ == "__main__":
    replay_path = argv[1]
    score = Score(replay_path)
    options = TitleOptions()
    render_results(score, options)
