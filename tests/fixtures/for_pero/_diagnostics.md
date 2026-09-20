# STE fixture export diagnostics

ref: c36e9ad  source: areatu/Sonoforge_data@data/dicom/For_pero

## sizes in data/dicom/For_pero
total 469188
-rw-r--r-- 1 runner runner   9220206 Sep 20 19:02 gold1.dcm
-rw-r--r-- 1 runner runner  11267426 Sep 20 19:02 gold2.dcm
-rw-r--r-- 1 runner runner  18699678 Sep 20 19:02 gold3.dcm
-rw-r--r-- 1 runner runner  20688092 Sep 20 19:02 gold4.dcm
-rw-r--r-- 1 runner runner  20796784 Sep 20 19:02 gold5.dcm
-rw-r--r-- 1 runner runner  21424526 Sep 20 19:02 gold6.dcm
-rw-r--r-- 1 runner runner  16131256 Sep 20 19:02 gold7+ECG.dcm
-rw-r--r-- 1 runner runner  16198284 Sep 20 19:02 gold8+ECG.dcm
-rwxr-xr-x 1 runner runner 109309786 Sep 20 19:02 gold_Ph_ECG1
-rwxr-xr-x 1 runner runner   4994344 Sep 20 19:02 gold_Ph_ECG2
-rwxr-xr-x 1 runner runner   3097202 Sep 20 19:02 strain_ph1
-rwxr-xr-x 1 runner runner  99372788 Sep 20 19:02 strain_ph2
-rwxr-xr-x 1 runner runner  99372846 Sep 20 19:02 strain_ph3
-rw-r--r-- 1 runner runner   4727412 Sep 20 19:02 strain_sams1.dcm
-rw-r--r-- 1 runner runner   6222178 Sep 20 19:02 strain_sams2.dcm
-rw-r--r-- 1 runner runner   3090092 Sep 20 19:02 strain_sams3.dcm
-rw-r--r-- 1 runner runner   6222206 Sep 20 19:02 strain_sams4.dcm
-rw-r--r-- 1 runner runner   6222206 Sep 20 19:02 strain_sams5.dcm
-rw-r--r-- 1 runner runner   3338290 Sep 20 19:02 strain_sams6.dcm

## pointer files remaining (<1024 bytes)

## export log
  ✓ gold1                 55 кадров 1276×800 fps  30.0 ECG=False →  2.53 МБ (q76)
  ✓ gold2                 80 кадров 1276×800 fps  30.0 ECG=False →  2.86 МБ (q76)
  ✓ gold3                105 кадров 1276×800 fps  30.0 ECG=False →  5.28 МБ (q68)
  ✓ gold4                139 кадров 1276×800 fps  30.0 ECG=False →  5.27 МБ (q68)
  ✓ gold5                125 кадров 1276×800 fps  30.0 ECG=False →  5.67 МБ (q68)
  ✓ gold6                120 кадров 1276×800 fps  30.0 ECG=False →  6.03 МБ (q68)
  ✓ gold7+ECG             83 кадров 1276×800 fps  30.0 ECG=False →  4.64 МБ (q68)
  ✓ gold8+ECG             82 кадров 1276×800 fps  30.0 ECG=False →  4.71 МБ (q68)
  ✓ gold_Ph_ECG1         185 кадров 800×600 fps  58.3 ECG=False →  4.21 МБ (q68)
  ✓ gold_Ph_ECG2          46 кадров 800×600 fps  46.5 ECG=False →  2.32 МБ (q92)
  ~ strain_ph1           vendor screen (1600×900, 20 кадров) → 6 PNG в ui_reference/
  ~ strain_ph2           vendor screen (1600×900, 23 кадров) → 6 PNG в ui_reference/
  ~ strain_ph3           vendor screen (1600×900, 23 кадров) → 6 PNG в ui_reference/
  ~ strain_sams1         vendor screen (1280×668, 20 кадров) → 6 PNG в ui_reference/
  ~ strain_sams2         vendor screen (3×1920, 1080 кадров) → 6 PNG в ui_reference/
  ~ strain_sams3         vendor screen (1280×668, 14 кадров) → 6 PNG в ui_reference/
  ~ strain_sams4         vendor screen (3×1920, 1080 кадров) → 6 PNG в ui_reference/
  ~ strain_sams5         vendor screen (3×1920, 1080 кадров) → 6 PNG в ui_reference/
  ~ strain_sams6         vendor screen (1280×668, 14 кадров) → 6 PNG в ui_reference/

индекс: tests/fixtures/for_pero/index.json (19 файлов)
