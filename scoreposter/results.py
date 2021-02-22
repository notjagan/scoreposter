from copy import deepcopy
from enum import Enum, auto
from functools import reduce
from pathlib import Path

import cv2
import numpy as np
import requests
from osrparse.enums import Mod
from PIL import Image, ImageDraw, ImageFont
from score import Rank, Score
import utils


ASSETS_PATH = Path('..') / 'assets'
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
        

class Renderable:
    def width(self):
        pass
    
    def height(self):
        pass
    
    def render(self, pos):
        return []


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
        return [layer]


class TextRenderable(Renderable):
    @staticmethod
    def fit_size(text, min_size, max_size, max_width):
        for size in range(max_size, min_size - 1, -1):
            font = ImageFont.truetype(FONT_PATH, size)
            width = font.getmask(text).getbbox()[2]
            if width <= max_width:
                return size
        raise OverflowError()
        
    def __init__(self, text, size, color):
        self.text = text
        self.font = ImageFont.truetype(FONT_PATH, size)
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
        return [layer]


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
        return [shadow_layer, text_layer]


class SpaceRenderable(Renderable):
    def __init__(self, w):
        self.w = w
    
    def width(self):
        return self.w
