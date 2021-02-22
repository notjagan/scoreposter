from copy import deepcopy
from enum import Enum, auto
from functools import reduce

import cv2
import numpy as np
import requests
from osrparse.enums import Mod
from PIL import Image, ImageDraw, ImageFont
from score import Rank, Score
import utils


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
