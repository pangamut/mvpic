#!/usr/bin/python3
“””
mvpic.py - Photo organizer with smart deduplication and event detection
Usage: mvpic.py -o <output_dir> [options] <input_dir>

Organizes photos into: YYYY/[MM_Ereignis/][Kamera/]datei.jpg
“””

import sys
import getopt
import os
import re
import shutil
import hashlib
import json
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
import logging

try:
import pyexiv2
from PIL import Image as PilImage
except ImportError as e:
print(f”Missing required module: {e}”)
print(“Install with: pip install pyexiv2 Pillow”)
sys.exit(1)

# —————————————————————————

# Constants

# —————————————————————————

SUPPORTED_EXTENSIONS = {
‘.jpg’, ‘.jpeg’, ‘.cr2’, ‘.cr3’, ‘.png’, ‘.rw2’,
‘.dng’, ‘.gif’, ‘.tif’, ‘.tiff’, ‘.heic’, ‘.heif’, ‘.nef’, ‘.arw’
}

CAMERA_SHORTCUTS = {
‘Canon DIGITAL IXUS 100 IS’: ‘CanonIXUS100’,
‘Canon DIGITAL IXUS 430’:    ‘CanonIXUS430’,
‘Canon DIGITAL IXUS 70’:     ‘CanonIXUS70’,
‘Canon EOS 350D DIGITAL’:    ‘EOS350D’,
‘Canon EOS 6D Mark II’:      ‘EOS6DmkII’,
‘Canon EOS 70D’:             ‘EOS70D’,
‘Canon PowerShot G5’:        ‘CanonG5’,
‘KODAK DC280 ZOOM DIGITAL CAMERA’: ‘KodakDC280’,
’PENTAX Optio S ’:           ‘PENTAX-OptioS’,
}

FOLDERS_TO_IGNORE = {
‘Mac OS Wallpaper Pack’, ‘Fotos Library’, ‘.DS_Store’,
‘Thumbs.db’, ‘@eaDir’, ‘#recycle’
}

# Mindestabstand in Tagen für ein neues Ereignis (zeitliche Cluster)

EVENT_GAP_DAYS = 3

# Datei im Zielverzeichnis, die migrierte Quellen protokolliert

SOURCES_LOG_FILE = ‘.mvpic_sources.json’

# —————————————————————————

# Logging

# —————————————————————————

logging.basicConfig(
level=logging.INFO,
format=’%(asctime)s %(levelname)-8s %(message)s’,
datefmt=’%H:%M:%S’
)
logger = logging.getLogger(‘mvpic’)

# —————————————————————————

# Config

# —————————————————————————

class Config:
output_dir: str = ‘’
simulate:   bool = False
recursive:  bool = True   # Default an, da wir Verzeichnisbäume scannen
verbose:    bool = False
print_meta: bool = False
list_sources: bool = False
source_label: str = ‘’    # Optionaler Name für die Quelle im Log

config = Config()

# —————————————————————————

# Source tracking

# —————————————————————————

def load_sources_log(output_dir: str) -> dict:
“”“Lade das Quell-Log aus dem Zielverzeichnis.”””
log_path = os.path.join(output_dir, SOURCES_LOG_FILE)
if os.path.exists(log_path):
try:
with open(log_path, ‘r’, encoding=‘utf-8’) as f:
return json.load(f)
except Exception as e:
logger.warning(f”Konnte Quell-Log nicht lesen: {e}”)
return {}

def save_sources_log(output_dir: str, log: dict) -> None:
“”“Speichere das Quell-Log im Zielverzeichnis.”””
log_path = os.path.join(output_dir, SOURCES_LOG_FILE)
try:
os.makedirs(output_dir, exist_ok=True)
with open(log_path, ‘w’, encoding=‘utf-8’) as f:
json.dump(log, f, indent=2, ensure_ascii=False)
except Exception as e:
logger.error(f”Konnte Quell-Log nicht speichern: {e}”)

def source_already_migrated(output_dir: str, source_path: str) -> bool:
“”“Prüfe ob diese Quelle bereits migriert wurde.”””
log = load_sources_log(output_dir)
canonical = str(Path(source_path).resolve())
return canonical in log

def mark_source_migrated(output_dir: str, source_path: str, label: str,
stats: dict) -> None:
“”“Markiere Quelle als migriert im Log.”””
log = load_sources_log(output_dir)
canonical = str(Path(source_path).resolve())
log[canonical] = {
‘label’:      label or os.path.basename(source_path),
‘migrated_at’: datetime.now().isoformat(timespec=‘seconds’),
‘stats’:       stats,
}
save_sources_log(output_dir, log)

def print_sources(output_dir: str) -> None:
“”“Zeige alle migrierten Quellen an.”””
log = load_sources_log(output_dir)
if not log:
print(“Keine migrierten Quellen im Log gefunden.”)
return
print(f”\nMigrierte Quellen in: {output_dir}”)
print(”-” * 70)
for path, info in sorted(log.items(), key=lambda x: x[1].get(‘migrated_at’,’’)):
print(f”  {info.get(‘label’,’?’):30s}  {info.get(‘migrated_at’,’?’)}”)
print(f”    Pfad: {path}”)
stats = info.get(‘stats’, {})
if stats:
print(f”    Kopiert: {stats.get(‘copied’,0)}, “
f”Dubletten: {stats.get(‘duplicates’,0)}, “
f”Ersetzt: {stats.get(‘replaced’,0)}, “
f”Fehler: {stats.get(‘errors’,0)}”)
print()

# —————————————————————————

# EXIF extraction

# —————————————————————————

def extract_exif(img_file: str) -> dict:
“””
Lese EXIF-Metadaten aus einer Bilddatei.
Gibt ein Dict mit den gefundenen Feldern zurück.
“””
meta = {}
try:
md = pyexiv2.ImageMetadata(img_file)
md.read()
except Exception as e:
logger.debug(f”EXIF-Lesefehler bei {img_file}: {e}”)
return meta

```
mappings = {
    'make':       'Exif.Image.Make',
    'model':      'Exif.Image.Model',
    'datetime':   'Exif.Photo.DateTimeOriginal',
    'datetime2':  'Exif.Image.DateTime',
    'width':      'Exif.Photo.PixelXDimension',
    'height':     'Exif.Photo.PixelYDimension',
    'gps_lat':    'Exif.GPSInfo.GPSLatitude',
    'gps_lat_ref':'Exif.GPSInfo.GPSLatitudeRef',
    'gps_lon':    'Exif.GPSInfo.GPSLongitude',
    'gps_lon_ref':'Exif.GPSInfo.GPSLongitudeRef',
}
for key, tag in mappings.items():
    if tag in md:
        try:
            meta[key] = md[tag].value
        except Exception:
            pass
return meta
```

def get_image_dimensions(img_file: str) -> Tuple[int, int]:
“”“Lese Bildabmessungen via Pillow (Fallback wenn EXIF fehlt).”””
try:
with PilImage.open(img_file) as im:
return im.size  # (width, height)
except Exception:
return (0, 0)

def parse_exif_datetime(value) -> Optional[datetime]:
“”“Wandle EXIF-Datum in datetime-Objekt.”””
if isinstance(value, datetime):
return value
if isinstance(value, str):
for fmt in (’%Y:%m:%d %H:%M:%S’, ‘%Y-%m-%d %H:%M:%S’, ‘%Y:%m:%d’):
try:
return datetime.strptime(value.strip(), fmt)
except ValueError:
pass
return None

def camera_name(exif: dict) -> str:
“”“Erzeuge einen kurzen Kameranamen aus Make/Model.”””
model = str(exif.get(‘model’, ‘’)).strip()
if not model:
return ‘’
# Versuche Abkürzung
if model in CAMERA_SHORTCUTS:
return CAMERA_SHORTCUTS[model]
# Kürze langen Namen: letztes Wort oder max 20 Zeichen
clean = re.sub(r’[^\w-]’, ‘_’, model)
return clean[:24]

# —————————————————————————

# Deduplication

# —————————————————————————

def file_hash(path: str, algo=‘md5’) -> str:
“”“Berechne Hash einer Datei.”””
h = hashlib.new(algo)
try:
with open(path, ‘rb’) as f:
for chunk in iter(lambda: f.read(65536), b’’):
h.update(chunk)
return h.hexdigest()
except OSError:
return ‘’

def pixel_count(exif: dict, path: str) -> int:
“”“Gesamtpixelzahl aus EXIF oder Pillow.”””
w = exif.get(‘width’, 0)
h = exif.get(‘height’, 0)
try:
w, h = int(w), int(h)
except (TypeError, ValueError):
w, h = 0, 0
if w and h:
return w * h
pw, ph = get_image_dimensions(path)
return pw * ph

class PhotoRecord:
“”“Repräsentiert ein zu verarbeitendes Foto.”””
def **init**(self, path: str, exif: dict):
self.path    = path
self.exif    = exif
self.size    = os.path.getsize(path)
self.pixels  = pixel_count(exif, path)
self._hash   = None  # lazy

```
@property
def hash(self) -> str:
    if self._hash is None:
        self._hash = file_hash(self.path)
    return self._hash

def is_better_than(self, other: 'PhotoRecord') -> bool:
    """
    True wenn self die bessere Version als other ist.
    Kriterien (absteigend):
      1. Mehr Pixel
      2. Größere Datei (weniger Komprimierung)
    """
    if self.pixels != other.pixels:
        return self.pixels > other.pixels
    return self.size > other.size
```

def deduplicate_key(record: PhotoRecord) -> Optional[str]:
“””
Erzeuge einen Deduplizierungsschlüssel.
Primär: EXIF-Datum + Kamera (identifiziert dasselbe Foto aus verschiedenen
Quellen / Auflösungen).
Fallback: Hash (für Fotos ohne EXIF-Datum).
“””
dt_raw = record.exif.get(‘datetime’) or record.exif.get(‘datetime2’)
dt = parse_exif_datetime(dt_raw)
cam = camera_name(record.exif)
if dt:
return f”dt:{dt.strftime(’%Y%m%d_%H%M%S’)}|cam:{cam}”
# Kein Datum → Hash als Schlüssel
return f”hash:{record.hash}”

# —————————————————————————

# Event / directory name detection

# —————————————————————————

def clean_dir_name(name: str) -> str:
“”“Bereinige Verzeichnisnamen für Ereignisbezeichnung.”””
# Entferne typische Foto-App-Präfixe und Sonderzeichen
name = re.sub(r’^(IMG|DSC|DCIM|photos?|bilder?|pictures?)[*-\s]*’,
‘’, name, flags=re.IGNORECASE)
name = re.sub(r’[^\w-äöüÄÖÜß ]’, ’*’, name)
name = name.strip(’_ ’)
return name[:40]  # max Länge

def extract_event_from_path(source_path: str, root_source: str) -> str:
“””
Versuche Ereignisname aus Verzeichnisstruktur zu extrahieren.
Nimmt den aussagekräftigsten Verzeichnisnamen relativ zur Quelle.
“””
try:
rel = Path(source_path).relative_to(Path(root_source))
parts = list(rel.parts)
# Letztes Verzeichnis (nicht Dateiname) verwenden
if len(parts) > 1:
candidate = parts[-2]  # Elternverzeichnis der Datei
elif len(parts) == 1:
candidate = ‘’
else:
candidate = ‘’
cleaned = clean_dir_name(candidate)
# Ignoriere generische Namen
generic = {‘fotos’, ‘bilder’, ‘photos’, ‘pictures’, ‘images’,
‘camera’, ‘kamera’, ‘dcim’, ‘’}
if cleaned.lower() in generic:
return ‘’
return cleaned
except ValueError:
return ‘’

def detect_events(records: List[PhotoRecord], root_source: str) -> Dict[str, str]:
“””
Weise jedem Foto einen Ereignisnamen zu.
Kombination aus:
- Verzeichnisnamen aus Quellpfad
- Zeitlichen Clustern (Lücke > EVENT_GAP_DAYS = neues Ereignis)

```
Gibt ein Dict {record.path: event_name} zurück.
"""
# Sortiere nach Datum
dated   = []
undated = []
for r in records:
    dt_raw = r.exif.get('datetime') or r.exif.get('datetime2')
    dt = parse_exif_datetime(dt_raw)
    if dt:
        dated.append((dt, r))
    else:
        undated.append(r)

dated.sort(key=lambda x: x[0])

result = {}

# --- Datierte Fotos: zeitliche Cluster ---
cluster_start  = None
cluster_label  = ''
prev_dt        = None

for dt, r in dated:
    dir_event = extract_event_from_path(r.path, root_source)

    # Neues Cluster wenn Lücke zu groß
    if prev_dt is None or (dt - prev_dt) > timedelta(days=EVENT_GAP_DAYS):
        cluster_start = dt
        cluster_label = dir_event  # Verzeichnisname des ersten Fotos im Cluster
    else:
        # Cluster läuft weiter — wenn aktuelles Foto einen Verzeichnisnamen hat
        # und das Cluster noch keinen hat, übernehmen
        if not cluster_label and dir_event:
            cluster_label = dir_event

    result[r.path] = cluster_label
    prev_dt = dt

# --- Undatierte Fotos: nur Verzeichnisname ---
for r in undated:
    result[r.path] = extract_event_from_path(r.path, root_source)

return result
```

# —————————————————————————

# Target path construction

# —————————————————————————

def build_target_path(record: PhotoRecord, event: str,
all_cameras_in_event: set, root_source: str) -> str:
“””
Erzeuge den relativen Zielpfad für ein Foto.

```
Struktur:
  YYYY/[MM_Ereignis/][Kamera/]dateiname.ext

Kameraordner nur wenn mehr als eine Kamera im Ereignis.
Ohne EXIF-Datum: Quellverzeichnisstruktur relativ zur Quelle.
"""
filename = os.path.basename(record.path)
ext      = os.path.splitext(filename)[1].lower()
cam      = camera_name(record.exif)

dt_raw = record.exif.get('datetime') or record.exif.get('datetime2')
dt     = parse_exif_datetime(dt_raw)

if dt:
    year  = dt.strftime('%Y')
    month = dt.strftime('%m')
    # Zeitstempel als Dateiname-Präfix (Sortierung)
    ts_prefix = dt.strftime('%Y%m%d_%H%M%S')
    safe_filename = f"{ts_prefix}_{filename}"

    # Ereignisordner
    if event:
        event_dir = f"{month}_{event}"
    else:
        event_dir = month

    # Kameraordner nur wenn mehrere Kameras
    use_cam_dir = len(all_cameras_in_event) > 1 and bool(cam)

    if use_cam_dir:
        rel = os.path.join(year, event_dir, cam, safe_filename)
    else:
        rel = os.path.join(year, event_dir, safe_filename)

else:
    # Kein EXIF-Datum → Quellverzeichnisstruktur übernehmen
    try:
        rel_src = Path(record.path).relative_to(Path(root_source))
    except ValueError:
        rel_src = Path(filename)
    rel = os.path.join('_undatiert', str(rel_src))

return rel
```

# —————————————————————————

# File scanning

# —————————————————————————

def scan_directory(source_dir: str) -> List[str]:
“”“Scanne Verzeichnis rekursiv und sammle unterstützte Bilddateien.”””
found = []
for root, dirs, files in os.walk(source_dir):
# Ignorierte Ordner überspringen
dirs[:] = [d for d in dirs
if d not in FOLDERS_TO_IGNORE and not d.startswith(’.’)]
for fname in files:
if fname.startswith(’.’):
continue
ext = os.path.splitext(fname)[1].lower()
if ext in SUPPORTED_EXTENSIONS:
found.append(os.path.join(root, fname))
return found

# —————————————————————————

# Main organization logic

# —————————————————————————

def organize(source_dir: str, output_dir: str, simulate: bool,
source_label: str) -> dict:
“””
Hauptfunktion: Scanne Quelle, erkenne Ereignisse, kopiere Dateien.
Gibt Statistik-Dict zurück.
“””
stats = {‘copied’: 0, ‘duplicates’: 0, ‘replaced’: 0,
‘errors’: 0, ‘skipped’: 0}

```
# 1. Alle Dateien scannen
logger.info(f"Scanne: {source_dir}")
paths = scan_directory(source_dir)
logger.info(f"  {len(paths)} Bilddateien gefunden")

if not paths:
    return stats

# 2. EXIF laden, PhotoRecord-Objekte erzeugen
records = []
for p in paths:
    exif = extract_exif(p)
    records.append(PhotoRecord(p, exif))

# 3. Deduplizierung: bestes Exemplar je Schlüssel ermitteln
#    (innerhalb dieser Quelle)
best: Dict[str, PhotoRecord] = {}
for r in records:
    key = deduplicate_key(r)
    if key not in best:
        best[key] = r
    else:
        if r.is_better_than(best[key]):
            logger.info(f"  Bessere Version: {r.path} "
                        f"({r.pixels}px > {best[key].pixels}px)")
            best[key] = r
            stats['replaced'] += 1
        else:
            stats['duplicates'] += 1

unique_records = list(best.values())
logger.info(f"  {len(unique_records)} eindeutige Fotos nach Deduplizierung")

# 4. Ereignisse erkennen
event_map = detect_events(unique_records, source_dir)

# 5. Kameras pro Ereignis ermitteln (für Kameraordner-Entscheidung)
cameras_per_event: Dict[str, set] = {}
for r in unique_records:
    ev  = event_map.get(r.path, '')
    cam = camera_name(r.exif)
    cameras_per_event.setdefault(ev, set())
    if cam:
        cameras_per_event[ev].add(cam)

# 6. Bereits im Ziel vorhandene Fotos laden (quellübergreifende Deduplikation)
existing: Dict[str, PhotoRecord] = {}  # dedup_key → Record im Ziel
if os.path.exists(output_dir):
    logger.info("  Lade vorhandene Fotos im Ziel für Deduplizierung …")
    for ep in scan_directory(output_dir):
        er = PhotoRecord(ep, extract_exif(ep))
        ek = deduplicate_key(er)
        existing[ek] = er

# 7. Dateien kopieren
for r in unique_records:
    key = deduplicate_key(r)
    ev  = event_map.get(r.path, '')
    cams_in_ev = cameras_per_event.get(ev, set())

    rel_target = build_target_path(r, ev, cams_in_ev, source_dir)
    abs_target = os.path.join(output_dir, rel_target)

    # Quellübergreifende Deduplizierung
    if key in existing:
        incumbent = existing[key]
        if r.is_better_than(incumbent):
            # Bessere Version ersetzen
            if not simulate:
                try:
                    os.remove(incumbent.path)
                except OSError as e:
                    logger.warning(f"  Konnte alte Version nicht löschen: {e}")
            logger.info(f"  ERSETZT (bessere Auflösung): {incumbent.path}")
            logger.info(f"    → {abs_target}")
            stats['replaced'] += 1
        else:
            logger.debug(f"  DUPLIKAT übersprungen: {r.path}")
            stats['duplicates'] += 1
            continue
    
    # Zieldatei auf Kollision prüfen (gleicher Name, anderer Inhalt)
    if os.path.exists(abs_target):
        if file_hash(abs_target) == r.hash:
            logger.debug(f"  Identisch vorhanden, übersprungen: {r.path}")
            stats['duplicates'] += 1
            continue
        # Umbenennen um Kollision zu vermeiden
        base, ext = os.path.splitext(abs_target)
        counter = 1
        while os.path.exists(f"{base}_{counter}{ext}"):
            counter += 1
        abs_target = f"{base}_{counter}{ext}"

    if simulate:
        print(f"  COPY {r.path}")
        print(f"    → {abs_target}")
        stats['copied'] += 1
        continue

    try:
        os.makedirs(os.path.dirname(abs_target), exist_ok=True)
        shutil.copy2(r.path, abs_target)
        logger.debug(f"  Kopiert: {os.path.basename(r.path)} → {rel_target}")
        stats['copied'] += 1
        # Für weitere Fotos dieser Session als vorhanden merken
        new_r = PhotoRecord(abs_target, r.exif)
        existing[key] = new_r
    except Exception as e:
        logger.error(f"  Fehler bei {r.path}: {e}")
        stats['errors'] += 1

return stats
```

# —————————————————————————

# CLI

# —————————————————————————

def print_usage(exit_code: int = 0) -> None:
print(f”Usage: {sys.argv[0]} -o <zielordner> [Optionen] <quellordner>”)
print()
print(“Optionen:”)
print(”  -o, –output DIR      Zielverzeichnis (Pflicht)”)
print(”  -l, –label NAME      Bezeichnung der Quelle im Log”)
print(”  -s, –simulate        Simulation (keine Dateien kopieren)”)
print(”  -m, –meta            Metadaten ausgeben”)
print(”  -v, –verbose         Ausführliche Ausgabe”)
print(”  –list-sources        Migrierte Quellen anzeigen”)
print(”  -h, –help            Diese Hilfe”)
print()
print(“Beispiel:”)
print(f”  {sys.argv[0]} -o /Fotos/Archiv -l ‘NAS_Backup’ /mnt/nas/fotos”)
sys.exit(exit_code)

def main(argv):
source_dir = ‘’

```
try:
    opts, args = getopt.getopt(
        argv, 'ho:l:smv',
        ['help', 'output=', 'label=', 'simulate', 'meta',
         'verbose', 'list-sources']
    )
except getopt.GetoptError as e:
    print(f"Fehler: {e}")
    print_usage(2)

for opt, arg in opts:
    if opt in ('-h', '--help'):
        print_usage(0)
    elif opt in ('-o', '--output'):
        config.output_dir = arg
    elif opt in ('-l', '--label'):
        config.source_label = arg
    elif opt in ('-s', '--simulate'):
        config.simulate = True
    elif opt in ('-m', '--meta'):
        config.print_meta = True
    elif opt in ('-v', '--verbose'):
        config.verbose = True
        logger.setLevel(logging.DEBUG)
    elif opt == '--list-sources':
        config.list_sources = True

# --list-sources: nur anzeigen, kein weiterer Input nötig
if config.list_sources:
    if not config.output_dir:
        print("Fehler: -o <zielordner> erforderlich für --list-sources")
        sys.exit(1)
    print_sources(config.output_dir)
    sys.exit(0)

if args:
    source_dir = args[0]

if not source_dir:
    print("Fehler: Kein Quellverzeichnis angegeben.")
    print_usage(2)

if not config.output_dir:
    print("Fehler: Kein Zielverzeichnis angegeben (-o).")
    print_usage(2)

source_dir   = str(Path(source_dir).resolve())
output_dir   = str(Path(config.output_dir).resolve())
source_label = config.source_label or os.path.basename(source_dir)

# Prüfen ob diese Quelle schon migriert wurde
if not config.simulate:
    if source_already_migrated(output_dir, source_dir):
        print(f"Quelle bereits migriert: {source_dir}")
        print("Erneut ausführen? Mit --list-sources vorhandene Quellen anzeigen.")
        print("(Simulation mit -s ist trotzdem möglich)")
        sys.exit(0)

print(f"\nmvpic: {source_label}")
print(f"  Quelle : {source_dir}")
print(f"  Ziel   : {output_dir}")
print(f"  Modus  : {'SIMULATION' if config.simulate else 'KOPIEREN'}")
print()

stats = organize(source_dir, output_dir, config.simulate, source_label)

print()
print("Ergebnis:")
print(f"  Kopiert   : {stats['copied']}")
print(f"  Dubletten : {stats['duplicates']}")
print(f"  Ersetzt   : {stats['replaced']} (bessere Auflösung übernommen)")
print(f"  Fehler    : {stats['errors']}")

# Quelle im Log vermerken (nicht bei Simulation)
if not config.simulate and stats['errors'] == 0:
    mark_source_migrated(output_dir, source_dir, source_label, stats)
    print(f"\nQuelle als migriert gespeichert: {source_label}")
```

if **name** == “**main**”:
main(sys.argv[1:])
