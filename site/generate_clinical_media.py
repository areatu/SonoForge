#!/usr/bin/env python3
"""Synthetic application-style previews, not recordings or clinical evidence.

Authoring dependencies: Pillow >= 10, NumPy. No patient data or model inference.
Run: python site/generate_clinical_media.py
The landing page publishes the six GIF/poster pairs from this output folder.
"""
from pathlib import Path
import math
import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageFilter

OUT = Path(__file__).resolve().parent / 'media/features/clinical'
NAMES = ('cardiac', 'doppler', 'calibration', 'segmentation', 'pacs', 'reports')
FONT_DIR = Path('/usr/share/fonts/truetype/dejavu')
BG, PANEL, EDGE = '#0b0f14', '#151c24', '#293440'
INK, MUTED, CYAN, GOLD = '#e4eaf0', '#8595a5', '#6cdad0', '#edcf83'


def font(size, bold=False):
    path = FONT_DIR / ('DejaVuSans-Bold.ttf' if bold else 'DejaVuSans.ttf')
    return ImageFont.truetype(str(path), size) if path.exists() else ImageFont.load_default(size=size)


# Fixed synthetic speckle field: stable texture rather than random frame flicker.
rng = np.random.default_rng(42)
noise = rng.rayleigh(.65, (300, 540))
noise = np.asarray(Image.fromarray(np.uint8(np.clip(noise*95, 0, 255))).filter(ImageFilter.GaussianBlur(.65))) / 95
spectral_noise = rng.rayleigh(.65, (300, 540))
Y, X = np.mgrid[:300, :540]


def bezier(a, b, c, e, n=40):
    return [(float((1-t)**3*a[0]+3*(1-t)**2*t*b[0]+3*(1-t)*t*t*c[0]+t**3*e[0]),
             float((1-t)**3*a[1]+3*(1-t)**2*t*b[1]+3*(1-t)*t*t*c[1]+t**3*e[1]))
            for t in np.linspace(0, 1, n)]


# Smooth anatomical redraw guided by the supplied A4C reference, not a raster copy.
A4C_SCALE = 278 / 384
A4C_ORIGIN = (105, 2)


def reference_point(x, y):
    return (A4C_ORIGIN[0]+x*A4C_SCALE, A4C_ORIGIN[1]+y*A4C_SCALE)


def path(*segments):
    return sum((bezier(*segment) for segment in segments), [])


# Septal MV annulus -> apex -> lateral MV annulus, without trabecular notches.
REFERENCE_CONTOUR = path(
    ((226,239),(239,205),(204,109),(211,68)),
    ((211,68),(219,39),(244,68),(260,94)),
    ((260,94),(279,126),(291,129),(307,157)),
    ((307,157),(328,183),(346,207),(326,207)),
)
LV_CONTOUR = [reference_point(x,y) for x,y in REFERENCE_CONTOUR]

# All curves are open strokes: no white chamber fill, no labels or callout leaders.
A4C_PATHS = [
    # Epicardial silhouette.
    path(((174,17),(208,-7),(244,4),(273,39)),
         ((273,39),(325,92),(371,157),(365,230)),
         ((365,230),(367,292),(324,356),(276,375)),
         ((276,375),(235,399),(162,384),(135,345)),
         ((135,345),(102,306),(85,251),(94,174)),
         ((94,174),(94,112),(124,47),(174,17))),
    REFERENCE_CONTOUR,
    # RV: a narrower crescent, sharing a long septum with the LV.
    path(((132,250),(108,224),(108,174),(119,137)),
         ((119,137),(124,99),(143,69),(170,53)),
         ((170,53),(174,97),(187,140),(196,172)),
         ((196,172),(207,204),(219,237),(205,240))),
    # Tricuspid leaflets, offset toward the apex relative to the MV.
    path(((132,250),(148,250),(131,216),(130,198)),
         ((130,198),(132,228),(148,250),(132,269))),
    path(((205,240),(185,239),(174,211),(175,187)),
         ((175,187),(171,216),(184,243),(205,240))),
    # Mitral leaflets: preserve their long, smooth shape without small internal detail.
    path(((226,239),(245,259),(277,227),(253,177)),
         ((253,177),(278,192),(278,229),(255,250))),
    path(((326,207),(303,211),(288,182),(288,164)),
         ((288,164),(293,189),(306,216),(331,216))),
    # RA and LA plus interatrial septum.
    path(((132,269),(114,292),(124,342),(153,361)),
         ((153,361),(181,389),(222,378),(229,351)),
         ((229,351),(234,322),(231,283),(225,259)),
         ((225,259),(212,251),(192,250),(181,247))),
    path(((255,250),(237,276),(235,310),(240,341)),
         ((240,341),(245,376),(277,380),(303,361)),
         ((303,361),(339,333),(351,288),(347,252)),
         ((347,252),(347,228),(336,218),(315,216))),
]


def wall_intersections(y):
    """Intersections with both LV walls at one reference-image height."""
    hits=[]
    for (x1,y1),(x2,y2) in zip(REFERENCE_CONTOUR,REFERENCE_CONTOUR[1:]):
        if (y1 <= y < y2) or (y2 <= y < y1):
            hits.append(x1+(x2-x1)*(y-y1)/(y2-y1))
    return min(hits),max(hits)


def a4c_schematic():
    # Grain belongs only to myocardial bands; cavities remain fully transparent.
    scale=3
    mask=Image.new('L',(540*scale,300*scale))
    draw=ImageDraw.Draw(mask)
    for index,points in enumerate(A4C_PATHS):
        mapped=[reference_point(x,y) for x,y in points]
        width=6 if index in (0,1,2,7,8) else 2
        draw.line([(round(x*scale),round(y*scale)) for x,y in mapped],
                  fill=255,width=width*scale,joint='curve')
    mask=mask.resize((540,300),Image.Resampling.LANCZOS)
    grain_rng=np.random.default_rng(71)
    grain=grain_rng.rayleigh(.65,(300,540))
    values=np.uint8(np.clip(45+100*grain,0,220))
    pixels=np.zeros((300,540,4),dtype=np.uint8)
    pixels[:,:,:3]=values[:,:,None]
    pixels[:,:,3]=np.asarray(mask)
    return Image.fromarray(pixels)


def ultrasound(phase=0):
    # Frozen frame; composite the same transparent line drawing into every scene.
    canvas=Image.new('RGB',(540,300),'#020304')
    anatomy=a4c_schematic()
    canvas.paste(anatomy,(0,0),anatomy)
    return canvas


def render(name, i, count=36):
    p=i/count
    progress=min(1,max(0,(p-.12)/.55))
    im=Image.new('RGB',(800,450),BG)
    d=ImageDraw.Draw(im)

    def text(x,y,s,color=INK,size=12,bold=False):
        d.text((x,y),s,font=font(size,bold),fill=color)

    def line(points,color=EDGE,width=1):
        d.line(points,fill=color,width=width,joint='curve')

    def box(rect,fill=PANEL,outline=None,r=5):
        d.rounded_rectangle(rect,r,fill,outline,width=1)

    def cursor(x,y):
        d.polygon([(x,y),(x+3,y+17),(x+7,y+12),(x+14,y+12)],fill='#f6f9fc',outline='#0a111a')
        if .32<p<.42:
            d.ellipse((x-9,y-9,x+9,y+9),outline=CYAN,width=1)

    titles={'cardiac':'Linear measurements', 'doppler':'Spectral Doppler',
            'calibration':'Scale calibration', 'segmentation':'LV contour',
            'pacs':'Study archive', 'reports':'Study report'}
    box((0,0,799,35),PANEL,r=0)
    text(16,9,'SonoForge',size=14,bold=True)
    text(125,11,'/  '+titles[name],MUTED)
    box((635,8,784,28),'#293022')
    text(645,11,'SYNTHETIC DEMO',GOLD,9)
    text(18,48,'DEMO-001  /  Echo',size=12,bold=True)
    text(18,68,'Teaching example · no patient data',MUTED,10)
    for j,s in enumerate(('Viewer','Measurements','Report')):
        x=414+j*120
        text(x,53,s,CYAN if (j==2 if name=='reports' else j==1) else MUTED,11)
    line([(16,88),(784,88)])
    box((16,100,562,405),'#020304')
    box((575,100,784,405))
    text(590,113,'WORKSPACE',MUTED,10,bold=True)

    def rows(items, active=-1):
        for j,(label,value) in enumerate(items):
            y=149+j*49
            if j==active:
                box((585,y-5,774,y+35),'#213332')
            text(593,y,label,MUTED,10)
            text(593,y+16,value,CYAN if j==active else INK,14)

    def status(s):
        box((588,366,771,392),'#223432')
        text(599,373,s,CYAN,10)

    if name in ('cardiac','segmentation'):
        im.paste(ultrasound(),(19,102))
        d=ImageDraw.Draw(im)
        text(31,111,'A4C / ANATOMY',size=11,bold=True)
        text(31,129,'REFERENCE ILLUSTRATION',MUTED,9)
        if name=='cardiac':
            left,right=wall_intersections(140)
            x1,y1=reference_point(left,140)
            x2,y2=reference_point(right,140)
            x1+=19; x2+=19; y1+=102; y2+=102
            if p>.18:
                end=x1+(x2-x1)*progress
                line([(x1,y1),(end,y2)],GOLD,1)
                for x in (x1,end):
                    line([(x-4,y1),(x+4,y1)],GOLD)
                    line([(x,y1-5),(x,y1+5)],GOLD)
                if progress>.95:
                    text(280,214,'48.0 mm',GOLD,11,bold=True)
                cursor(end+3,y2+4)
            rows([('Tool','Linear caliper'),('Distance','48.0 mm' if progress==1 else '—'),('Frame','12 / 64')],1)
            status('Measurement saved' if progress==1 else 'Place two points')
        else:
            pts=[(x+19,y+102) for x,y in LV_CONTOUR]
            if p>.12:
                pts=pts[:max(2,int(len(pts)*progress))]
                line(pts,CYAN,2)
                for x,y in pts[::10]:
                    box((x-2,y-2,x+2,y+2),CYAN,r=1)
                cursor(*pts[-1])
            rows([('View','A4C'),('Stage','Contour review'),('Editor','Control points')],1)
            status('Review boundaries' if progress==1 else 'Drawing contour')
        # Compact, synthetic ECG strip; not a patient signal.
        ecg=[]
        for x in range(29,550):
            c=((x-29)/130)%1
            v=18*math.exp(-((c-.23)/.016)**2)-7*math.exp(-((c-.26)/.025)**2)+3*math.exp(-((c-.55)/.1)**2)
            ecg.append((x,390-v))
        line(ecg,'#6da891')
    elif name in ('doppler','calibration'):
        text(31,111,'CW / AORTIC FLOW',size=10,bold=True)
        text(31,127,'5.0 MHz  /  100 mm/s',MUTED,9)
        # Reference-style CW display: ECG above a high baseline, negative flow.
        baseline=180 if name=='doppler' else 168+12*progress
        curve=[]
        for x in range(33,508):
            c=((x-33)/119)%1
            z=(c-.09)/.70
            peak=170*max(0,math.sin(math.pi*z))**.72 if 0<z<1 else 0
            curve.append((x,baseline+peak))
        for j,(x,y) in enumerate(curve):
            depth=y-baseline
            for yy in range(int(baseline),int(y)+1):
                rel=(yy-baseline)/max(1,depth)
                gain=35+95*rel
                g=int(9+gain*spectral_noise[(yy-100)%300,j%540])
                d.point((x,yy),fill=(min(g,230),)*3)
        line(curve,'#a5a9ab')
        # Bright zero-velocity clutter band, with the velocity ruler on the right.
        line([(33,baseline),(508,baseline)],GOLD if name=='calibration' else '#e3dfcf',2)
        for v in (0,-2,-4,-6):
            y=baseline+(-v)*27
            line([(510,y),(517,y)],MUTED)
            text(523,y-5,str(v),MUTED,10)
        text(521,baseline-22,'m/s',MUTED,9)
        ecg=[]
        for x in range(33,508):
            c=((x-33)/119)%1
            v=17*math.exp(-((c-.04)/.017)**2)-5*math.exp(-((c-.075)/.025)**2)
            ecg.append((x,159-v))
        line(ecg,'#73a484')
        if name=='doppler':
            pts=curve[11:94]
            if p>.12:
                pts=pts[:max(2,int(len(pts)*progress))]
                line(pts,GOLD,2); cursor(*pts[-1])
            rows([('Mode','CW envelope'),('Vmax','6.0 m/s' if progress==1 else '—'),('Action','Review / accept')],1)
            status('Review traced envelope' if progress==1 else 'Select one cycle')
        else:
            line([(515,baseline),(515,baseline+162)],GOLD,2)
            for y in (baseline,baseline+162):
                line([(511,y),(520,y)],GOLD,2)
            cursor(509,baseline)
            rows([('Units','m/s'),('Velocity scale','0 to -6.0'),('Baseline','Set' if progress==1 else 'Adjusting')],2)
            status('Verify calibration')
        for x in range(40,505,95):
            text(x,378,f'{(x-40)/475:.1f}',MUTED,9)
        text(499,378,'s',MUTED,9)
    elif name=='pacs':
        # Match the real loader: filters above, studies left, series right, actions below.
        box((16,100,784,405),'#242424',EDGE,r=2)
        text(28,110,'Load from Server',size=11,bold=True)
        text(158,111,'● Server available',CYAN,10)
        text(640,111,'DEMO CONNECTION',GOLD,9)
        box((28,136,346,162),'#303030',EDGE)
        text(38,144,'Patient name / study ID',MUTED,10)
        box((354,136,402,162),'#163a50')
        text(366,144,'Find','#75caff',10)
        text(419,144,'Query: DICOMweb',size=10)
        text(605,144,'Sort: Date (newest)',size=10)
        text(28,178,'Period:',MUTED,10)
        for j,label in enumerate(('All','Last 1 day','7 days','Last 30 days','90 days')):
            x=70+j*88
            box((x,172,x+80,195),'#086c9f' if j==0 else '#343434')
            text(x+8,179,label,size=9)
        text(28,210,'Modes:   2D    Color    M    PW    CW',MUTED,10)
        text(427,210,'Device: All       Modality: US',MUTED,10)
        text(28,237,'STUDIES (3)',size=10,bold=True)
        text(451,237,'SERIES (1)     All series     None',size=10)
        line([(437,234),(437,363)],EDGE)
        for j in range(3):
            y=255+j*35
            box((27,y,427,y+32),'#293b3c' if j==0 else '#202020',EDGE,r=1)
            box((34,y+10,44,y+20),CYAN if j==0 and p>.15 else '#303030',r=2)
            im.paste(ultrasound().resize((55,30)),(53,y+1))
            d=ImageDraw.Draw(im)
            text(119,y+3,f'DEMO-00{j+1} · Echo',size=10)
            text(119,y+18,'US   1 series   64 frames   2D',MUTED,8)
        box((450,255,771,320),'#202020',EDGE,r=1)
        im.paste(ultrasound().resize((92,58)),(472,258))
        d=ImageDraw.Draw(im)
        box((456,278,466,288),CYAN if p>.3 else '#303030',r=2)
        text(578,268,'1. Apical four-chamber',size=10)
        text(578,288,'US · 64 frames',MUTED,9)
        text(28,376,'Ready to open' if progress==1 else f'Retrieving series: {int(progress*100)}%',CYAN,10)
        box((451,337,768,341),EDGE,r=2)
        box((451,337,452+316*progress,341),CYAN,r=2)
        for x,w,label in ((464,62,'Cancel'),(534,96,'Save to Disk'),(638,134,'Download and open')):
            box((x,367,x+w,393),'#174861' if x==638 else '#383838')
            text(x+9,376,label,size=9)
        cursor(694,382)
    else:
        box((88,110,491,395),'#e8eaeb',r=1)
        text(111,126,'ECHOCARDIOGRAPHY','#24333e',15,True)
        text(111,150,'DEMO-001 · teaching report','#596b76',10)
        line([(111,176),(468,176)],'#b6c2ca')
        text(111,190,'Parameter','#596b76',10)
        text(377,190,'Value','#596b76',10)
        for j,(s,v) in enumerate((('LVEDD','48 mm'),('LVEDV','120 ml'),('LVESV','48 ml'),('LVEF','60 %'))):
            y=220+j*31
            text(111,y,s,'#24333e',11)
            if progress>(j+.5)/4:
                text(382,y,v,'#24333e',11,True)
            line([(111,y+24),(468,y+24)],'#d0d8dd')
        text(111,367,'Illustrative values · not for diagnosis','#657680',8)
        rows([('Template','Echo'),('Measurements',f'{min(4,int(progress*4))} / 4 transferred'),('Export','PDF  /  CSV  /  JSON')],1)
        cursor(693,292)
        status('Document preview')
    # One meaningful sequence followed by a hold; reset is explicit via cine bar.
    line([(19,421),(558,421)],EDGE,2)
    line([(19,421),(19+539*p,421)],CYAN,2)
    text(18,431,'▶   WORKFLOW DEMONSTRATION',MUTED,8)
    text(576,427,'UI simulation, not an application recording',MUTED,8)
    return im


def main():
    OUT.mkdir(parents=True,exist_ok=True)
    a4c_schematic().save(OUT/'a4c-schematic.png')
    for name in NAMES:
        frames=[render(name,i) for i in range(36)]
        # Shared palette derived from several workflow states, to avoid flicker.
        atlas=Image.new('RGB',(800,450*3))
        for j,k in enumerate((0,18,30)):
            atlas.paste(frames[k],(0,450*j))
        palette=atlas.quantize(colors=96)
        indexed=[f.quantize(palette=palette,dither=Image.Dither.NONE) for f in frames]
        indexed[0].save(OUT/f'{name}.gif',save_all=True,append_images=indexed[1:],
                        duration=110,loop=0,optimize=True,disposal=2)
        frames[30].save(OUT/f'{name}-poster.jpg',quality=92,optimize=True)
        print(name,(OUT/f'{name}.gif').stat().st_size)


if __name__=='__main__':
    main()
