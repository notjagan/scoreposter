from enum import Enum, auto


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
