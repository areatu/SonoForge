#!/usr/bin/env python3
"""Create six schematic, patient-free feature animations; no screenshots required.

Optional authoring dependency: Pillow >= 10. Run: python site/generate_feature_media.py
The committed assets are used directly by the static build.
"""
from math import cos, pi, sin
from pathlib import Path

from PIL import Image, ImageDraw

OUT = Path(__file__).resolve().parent / 'media' / 'features'
W, H = 480, 224
BG, GRID, BLUE, TEAL, WHITE, DIM, AMBER = (
    '#0c1723', '#1a2d3b', '#47c5f5', '#55e0b5', '#e6f6ff', '#7290a0', '#ffc578'
)


def base():
    im = Image.new('RGB', (W, H), BG)
    d = ImageDraw.Draw(im)
    for x in range(0, W, 32):
        d.line((x, 0, x, H), fill=GRID, width=1)
    for y in range(0, H, 32):
        d.line((0, y, W, y), fill=GRID, width=1)
    return im, d


def dot(d, xy, r=5, fill=TEAL):
    x, y = xy
    d.ellipse((x-r, y-r, x+r, y+r), fill=fill)


def line(d, points, color=BLUE, width=4):
    d.line(points, fill=color, width=width, joint='curve')


def diagram(name, phase):
    im, d = base()
    t = (1 - cos(phase * 2*pi)) / 2
    if name == 'cardiac':
        # Chamber contour and movable caliper, not an ultrasound image.
        d.polygon([(134, 53), (156, 38), (185, 52), (207, 91), (204, 134), (181, 177), (161, 187), (141, 177), (117, 134), (115, 91)], fill='#133549')
        line(d, [(134,53),(156,38),(185,52),(207,91),(204,134),(181,177),(161,187),(141,177),(117,134),(115,91),(134,53)], BLUE, 4)
        y = int(92 + 25*t)
        line(d, [(118,y),(205,y)], TEAL, 3)
        for x in (118,205):
            line(d, [(x,y-10),(x,y+10)], TEAL, 3); dot(d, (x,y), 4)
        d.rounded_rectangle((268,63,377,75), 6, fill=GRID)
        d.rounded_rectangle((268,63, int(315+45*t),75), 6, fill=TEAL)
        for y0, length in ((101, 95), (130, 74), (159, 110)):
            d.rounded_rectangle((268,y0,268+length,y0+6),3,fill=DIM)
    elif name == 'doppler':
        line(d, [(70,161),(408,161)], DIM, 2)
        points=[]
        for x in range(70, 409, 3):
            cycle = ((x-70)/92) % 1
            peak = max(0, 1-abs(cycle-0.35)/0.31)**1.5
            points.append((x, int(157 - 95*peak)))
        d.polygon([(70,161)]+points+[(408,161)], fill='#154858')
        line(d, points, BLUE, 4)
        x=int(72+330*t); dot(d, (x,161), 5)
        line(d, [(x,157),(x,60)], TEAL, 2)
        d.arc((188,41,260,113), 180, 320, fill=AMBER, width=3)
    elif name == 'calibration':
        line(d, [(94,40),(94,184)], DIM, 3); line(d, [(94,161),(396,161)], DIM, 3)
        for y in range(48, 176, 25):
            line(d, [(85,y),(104,y)], BLUE, 3)
        for x in range(125, 392, 45):
            line(d, [(x,155),(x,168)], BLUE, 3)
        y=int(58+100*t); line(d, [(83,y),(389,y)], TEAL, 3)
        dot(d,(94,y),6); dot(d,(345,y),6)
        d.arc((235,57,309,131), 0, 300, fill=AMBER, width=4)
    elif name == 'segmentation':
        cx, cy = 166, 112
        points=[]
        for i in range(33):
            a=2*pi*i/32
            rx=62+3*sin(phase*2*pi); ry=80+4*sin(phase*2*pi)
            points.append((int(cx+rx*cos(a)),int(cy+ry*sin(a))))
        d.polygon(points, fill='#164353'); line(d, points, TEAL, 4)
        for i in range(0,32,4): dot(d, points[i], 4, BLUE)
        for j in range(3):
            x=286+j*29
            h=int(25+38*(0.5+0.5*sin(phase*2*pi+j)))
            d.rounded_rectangle((x,150-h,x+16,150),5,fill=[BLUE,TEAL,AMBER][j])
        line(d,[(268,160),(375,160)],DIM,2)
    elif name == 'pacs':
        d.rounded_rectangle((65,66,156,153),10,outline=BLUE,width=4)
        for y in (86,107,128):
            line(d,[(81,y),(138,y)],DIM,3); dot(d,(84,y),3,TEAL)
        d.rounded_rectangle((321,56,414,158),10,outline=BLUE,width=4)
        line(d,[(337,86),(398,86)],DIM,3); line(d,[(337,106),(384,106)],DIM,3)
        line(d,[(168,110),(306,110)],DIM,3)
        x=int(170+134*phase); d.rounded_rectangle((x-8,102,x+8,118),3,fill=TEAL)
        line(d,[(295,98),(308,110),(295,122)],TEAL,3)
    elif name == 'reports':
        d.rounded_rectangle((127,34,253,190),8,fill='#18394b',outline=BLUE,width=3)
        for y in (69,91,113,135,157): line(d, [(145,y),(231,y)], DIM, 3)
        for i in range(3):
            y=70+i*36
            line(d,[(300,y),(309,y+8),(326,y-9)], TEAL if t > i/4 else DIM,4)
            line(d,[(341,y),(382,y)],DIM,3)
        d.ellipse((220,139,266,185),fill=BG,outline=TEAL,width=3)
        line(d,[(231,161),(241,171),(256,152)],TEAL,4)
    return im


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    for name in ('cardiac', 'doppler', 'calibration', 'segmentation', 'pacs', 'reports'):
        frames = [diagram(name, i/24) for i in range(24)]
        frames[0].save(OUT / f'{name}-poster.jpg', quality=88, optimize=True)
        frames[0].save(OUT / f'{name}.gif', save_all=True, append_images=frames[1:], duration=100, loop=0, optimize=True, disposal=2)


if __name__ == '__main__':
    main()
