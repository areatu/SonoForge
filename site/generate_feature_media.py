#!/usr/bin/env python3
"""Reproducible patient-free illustrations, NOT application recordings.

Authoring only: Pillow >= 10. Run: python site/generate_feature_media.py
Variant A (dark) is published; variant B (light) is available for review.
All values and contours are illustrative, not clinical results.
"""
from math import cos, pi, sin
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

OUT = Path(__file__).resolve().parent / 'media' / 'features'
NAMES = ('cardiac', 'doppler', 'calibration', 'segmentation', 'pacs', 'reports')
W, H, SCALE = 480, 224, 2
FONT = ImageFont.load_default(size=22)
SMALL = ImageFont.load_default(size=18)


def diagram(name, phase, light=False):
    bg, panel, grid, ink, dim, accent = (
        ('#f0f5fa', '#ffffff', '#dce7f0', '#20354c', '#647b91', '#087c91') if light else
        ('#0b1421', '#111f30', '#213349', '#e5effb', '#8196af', '#5ce1c4'))
    blue = '#267bc4' if light else '#63b8ff'
    im = Image.new('RGB', (W*SCALE, H*SCALE), bg)
    d = ImageDraw.Draw(im)

    def line(pts, color=grid, width=1):
        d.line([(round(x*SCALE), round(y*SCALE)) for x, y in pts], fill=color, width=width*SCALE, joint='curve')

    def box(xy, fill=panel, outline=None, radius=8):
        d.rounded_rectangle(tuple(round(v*SCALE) for v in xy), radius*SCALE, fill=fill, outline=outline, width=SCALE)

    def text(xy, value, color=ink, small=False):
        d.text(tuple(v*SCALE for v in xy), value, fill=color, font=SMALL if small else FONT)

    def dot(x, y, color=accent, r=3):
        d.ellipse(((x-r)*SCALE, (y-r)*SCALE, (x+r)*SCALE, (y+r)*SCALE), fill=color)

    def check(x, y):
        line([(x,y), (x+4,y+4), (x+12,y-6)], accent, 2)

    titles = dict(cardiac='01 / CARDIAC MEASUREMENTS', doppler='02 / DOPPLER ENVELOPE',
                  calibration='03 / SCALE CALIBRATION', segmentation='04 / CONTOUR REFINEMENT',
                  pacs='05 / DICOM TRANSFER', reports='06 / STRUCTURED REPORT')
    text((18,12), titles[name], small=True)
    text((18,204), 'SCHEMATIC / NO PATIENT DATA', dim, True)
    box((16,36,464,194), outline=grid)
    t = (1-cos(2*pi*phase))/2
    if name in ('cardiac', 'segmentation'):
        for x in range(32,260,24):
            line([(x,48),(x,181)])
        for y in range(55,182,24):
            line([(30,y),(258,y)])
        pts = []
        for i in range(65):
            a = 2*pi*i/64
            # Stylised chamber, with a flat base and a rounded apex.
            x = 146 + (49-5*t)*sin(a)*(0.85+0.15*cos(a))
            y = 111 + (62-5*t)*cos(a)
            pts.append((x,y))
        line(pts, blue, 2)
        if name == 'cardiac':
            y = 108
            line([(102,y),(190,y)], accent, 2)
            for x in (102,190):
                line([(x,y-7),(x,y+7)], accent, 2)
                dot(x,y)
            box((279,62,445,107), bg)
            text((291,69), 'LV diameter', dim, True)
            text((291,84), '48 mm', accent)
            text((291,125), 'Two-point caliper', small=True)
            text((291,145), 'Frame / measure / save', dim, True)
            # Focus ring, not a falsely changing measurement.
            r = 6+int(5*t)
            d.ellipse(((190-r)*2,(y-r)*2,(190+r)*2,(y+r)*2), outline=accent, width=2)
        else:
            end = int(64*min(1,phase*1.5))+1
            line(pts[:max(2,end)], accent, 3)
            for x,y in pts[:end:8]:
                dot(x,y)
            text((284,65), 'LV / A4C', accent)
            text((284,94), 'Suggest contour', small=True)
            text((284,116), 'Review boundaries', dim, True)
            text((284,138), 'Adjust and confirm', dim, True)
            box((284,165,439,169), grid, radius=2)
            box((284,165,285+154*min(1,phase*1.5),169), accent, radius=2)
    elif name in ('doppler','calibration'):
        for y in (65,95,125,155):
            line([(50,y),(328,y)])
        pts=[]
        for x in range(51,329):
            c=((x-51)/88)%1
            peak=max(0,1-abs(c-.28)/.25)**1.4
            pts.append((x,157-87*peak-8*sin(c*pi)))
        line(pts, blue, 2)
        line([(50,166),(330,166)], dim)
        if name == 'doppler':
            end=int(277*min(1,phase*1.5))+1
            line(pts[:max(2,end)], accent, 3)
            x,y=pts[min(end-1,277)]
            dot(x,y)
            text((349,67),'VTI',dim)
            text((349,88),'20 cm',accent)
            text((349,125),'Trace',small=True)
            text((349,142),'Review',small=True)
            text((349,159),'Confirm',small=True)
        else:
            for y,label in ((65,'100'),(110,'50'),(157,'0')):
                line([(39,y),(49,y)],accent,2)
                text((21,y-5),label,dim,True)
            y=157-12*(1-t)
            line([(50,y),(329,y)],accent,2)
            dot(50,y)
            text((345,65),'cm/s',accent)
            text((345,95),'Scale',small=True)
            text((345,119),'Baseline',small=True)
            text((345,151),'Verify',dim,True)
    elif name == 'pacs':
        for y in (69,99,129):
            box((43,y,140,y+23),bg,grid,4)
            dot(56,y+12)
            line([(68,y+11),(124,y+11)],dim,2)
        text((62,163),'PACS',dim,True)
        line([(153,111),(310,111)],grid,2)
        for i in range(3):
            x=158+((phase+i/3)%1)*140
            box((x,104,x+12,118),accent,radius=3)
        box((325,60,437,146),bg,blue)
        for i in range(3):
            box((337+i*30,74,361+i*30,100),grid,radius=3)
        line([(381,147),(381,157),(351,157),(410,157)],blue,2)
        text((342,167),'WORKSTATION',dim,True)
        text((175,66),'DICOM',accent)
        text((174,143),'Query / retrieve',dim,True)
    else:
        box((45,52,203,180),bg,grid)
        text((58,61),'MEASUREMENTS',dim,True)
        for i,(label,value) in enumerate((('LVEDD','48 mm'),('EDV','120 ml'),('LVEF','60 %'))):
            y=89+i*25
            text((58,y),label,small=True)
            text((133,y),value,accent,True)
        line([(217,115),(258,115)],accent,2)
        line([(250,108),(258,115),(250,122)],accent,2)
        box((277,49,433,182),bg,blue)
        text((291,61),'STUDY REPORT',small=True)
        for i in range(4):
            y=88+i*18
            line([(291,y),(394,y)],grid,2)
            if phase*5>i:
                check(406,y)
        text((291,163),'PDF / CSV / JSON',accent,True)
    return im.resize((W,H), Image.Resampling.LANCZOS)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    for light in (False, True):
        folder = OUT / 'alternatives' if light else OUT
        folder.mkdir(exist_ok=True)
        for name in NAMES:
            frames = [diagram(name,i/24,light) for i in range(24)]
            # One palette for the entire loop prevents temporal colour flicker.
            palette = frames[12].quantize(colors=48)
            indexed = [f.quantize(palette=palette, dither=Image.Dither.NONE) for f in frames]
            frames[12].save(folder / f'{name}-poster.jpg', quality=90, optimize=True)
            indexed[0].save(folder / f'{name}.gif', save_all=True, append_images=indexed[1:],
                            duration=130, loop=0, optimize=True, disposal=2)


if __name__ == '__main__':
    main()
