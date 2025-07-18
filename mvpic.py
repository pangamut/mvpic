#!/usr/bin/python3

import sys
import getopt
import os
import re
import shutil
from pathlib import Path
from datetime import datetime
import logging
from typing import Dict, Set, Optional, Tuple

# Third-party imports
try:
    from geopy.geocoders import Nominatim
    from exif import Image
    import pyexiv2
except ImportError as e:
    print(f"Missing required module: {e}")
    print("Install with: pip install geopy exif pyexiv2")
    sys.exit(1)

# Type definitions
class Counter(dict):
    def __missing__(self, key):
        return 0

# Configuration
SUPPORTED_EXTENSIONS = {'.jpg', '.jpeg', '.cr2', '.png', '.rw2', '.dng', '.gif', '.tif', '.heic'}

CAMERA_SHORTCUTS = {
    'Canon DIGITAL IXUS 100 IS': 'CanonIXUS100',
    'Canon DIGITAL IXUS 430': 'CanonIXUS430',
    'Canon DIGITAL IXUS 70': 'CanonIXUS70',
    'Canon EOS 350D DIGITAL': 'EOS350D',
    'Canon EOS 6D Mark II': 'EOS6DmkII',
    'Canon EOS 70D': 'EOS70D',
    'Canon PowerShot G5': 'CanonG5',
    'KODAK DC280 ZOOM DIGITAL CAMERA': 'KodakDC280',
    'PENTAX Optio S ': 'PENTAX-OptioS'
}

FOLDERS_TO_IGNORE = {'Mac OS Wallpaper Pack', 'Fotos Library', '.DS_Store', 'Thumbs.db'}

# Global configuration
class Config:
    def __init__(self):
        self.output_dir = ''
        self.simulate = False
        self.recursive = False
        self.verbose = False
        self.print_meta = False
        self.print_exif = False
        self.copy_mode = False  # Copy instead of move
        self.dry_run = False
        
config = Config()
counters = Counter()
metacollection = {}

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def get_decimal_from_dms(dms, ref: str) -> float:
    """Convert DMS coordinates to decimal degrees."""
    try:
        degrees = float(dms[0])
        minutes = float(dms[1]) / 60.0
        seconds = float(dms[2]) / 3600.0

        if ref in ['S', 'W']:
            degrees = -degrees
            minutes = -minutes
            seconds = -seconds

        return round(degrees + minutes + seconds, 5)
    except (IndexError, ValueError, TypeError):
        return 0.0

def get_coordinates(lat_coords, lat_ref: str, lon_coords, lon_ref: str) -> Tuple[float, float, str]:
    """Get coordinates and location name from GPS data."""
    try:
        lat = get_decimal_from_dms(lat_coords, lat_ref)
        lon = get_decimal_from_dms(lon_coords, lon_ref)
        
        if lat == 0.0 and lon == 0.0:
            return (0.0, 0.0, "Unknown")
        
        geoLoc = Nominatim(user_agent="PhotoOrganizer")
        location = geoLoc.reverse(f"{lat}, {lon}")
        
        return (lat, lon, location.address if location else "Unknown")
    except Exception as e:
        logger.warning(f"Failed to get coordinates: {e}")
        return (0.0, 0.0, "Unknown")

def extract_exif_data(meta: Dict, img_file: str) -> None:
    """Extract EXIF data from image file."""
    try:
        md = pyexiv2.ImageMetadata(img_file)
        md.read()
    except Exception as e:
        logger.warning(f"Failed to read EXIF data from {img_file}: {e}")
        return

    if config.print_exif:
        for tag in md:
            if not re.search('apple-fi', tag):  # Skip problematic tags
                print(f"{tag}: {md[tag]}")
            else:
                print(f"{tag}: ========== SKIPPED ==========")

    # Extract relevant EXIF data
    exif_mappings = {
        'Model': 'Exif.Image.Model',
        'DateTimeDigitized': 'Exif.Photo.DateTimeOriginal',
        'PixelX': 'Exif.Photo.PixelXDimension',
        'PixelY': 'Exif.Photo.PixelYDimension',
        'GPSLatitudeRef': 'Exif.GPSInfo.GPSLatitudeRef',
        'GPSLatitude': 'Exif.GPSInfo.GPSLatitude',
        'GPSLongitudeRef': 'Exif.GPSInfo.GPSLongitudeRef',
        'GPSLongitude': 'Exif.GPSInfo.GPSLongitude'
    }

    for key, exif_key in exif_mappings.items():
        if exif_key in md:
            counters[f'has:{key}'] += 1
            meta[key] = md[exif_key].value

def collect_metadata(meta: Dict, img_file: str, filename: str, file_ext: str) -> None:
    """Collect metadata from image file."""
    meta['origin'] = img_file
    meta['ext'] = file_ext.lower()
    meta['size'] = os.path.getsize(img_file)
    
    # Get modification time as fallback
    mod_time = datetime.fromtimestamp(os.path.getmtime(img_file))
    mod_time_str = mod_time.strftime('%Y-%m-%d %H:%M:%S')
    
    # Extract EXIF data
    extract_exif_data(meta, img_file)
    
    # Determine best date/time to use
    if 'DateTimeDigitized' in meta:
        meta['DateTimeUsed'] = str(meta['DateTimeDigitized'])
    else:
        meta['DateTimeUsed'] = mod_time_str
    
    # Parse date components
    date_time = meta['DateTimeUsed']
    meta['day'] = date_time[:10]
    meta['time'] = date_time[11:] if len(date_time) > 10 else "00:00:00"
    meta['year'] = date_time[:4]
    counters[f'year:{meta["year"]}'] += 1
    
    # Process camera model
    if 'Model' in meta:
        model = str(meta['Model']).strip()
        meta['Model'] = CAMERA_SHORTCUTS.get(model, model)
    else:
        meta['Model'] = 'unknown'
    
    # Process GPS data
    if all(key in meta for key in ['GPSLatitude', 'GPSLatitudeRef', 'GPSLongitude', 'GPSLongitudeRef']):
        lat, lon, location = get_coordinates(
            meta['GPSLatitude'], meta['GPSLatitudeRef'],
            meta['GPSLongitude'], meta['GPSLongitudeRef']
        )
        meta['lat'] = lat
        meta['lon'] = lon
        meta['location'] = location
    
    # Generate target path and filename
    target_path = f"{meta['year']}/{meta['day']}"
    # Clean up filename for filesystem safety
    safe_filename = re.sub(r'[^\w\-_.]', '_', filename)
    target_name = f"{meta['time'].replace(':', '-')}_{meta['Model']}_{safe_filename}"
    meta['target'] = f"{target_path}/{target_name}"

def handle_file(img_file: str) -> None:
    """Process a single image file."""
    if not os.path.exists(img_file):
        logger.warning(f"File not found: {img_file}")
        return
    
    counters['total'] += 1
    file_base, file_ext = os.path.splitext(img_file)
    file_path, filename = os.path.split(img_file)
    
    # Skip hidden files and unsupported extensions
    if filename.startswith('.') or file_ext.lower() not in SUPPORTED_EXTENSIONS:
        counters['ignored'] += 1
        return
    
    counters['todo'] += 1
    counters[file_ext.lower()] += 1
    
    meta = {}
    collect_metadata(meta, img_file, filename, file_ext)
    
    if config.print_meta:
        print(f"\nMetadata for {filename}:")
        for key, value in meta.items():
            print(f"  {key}: {value}")
    
    # Handle duplicates (same timestamp)
    datetime_key = meta['DateTimeUsed']
    if datetime_key in metacollection:
        prev = metacollection[datetime_key]
        if prev['ext'] == meta['ext']:
            # Keep the larger file
            if meta['size'] > prev['size']:
                counters['duplicates_replaced'] += 1
                metacollection[datetime_key] = meta
            else:
                counters['duplicates_skipped'] += 1
        else:
            # Different extensions, keep both with suffix
            counter = 1
            new_key = f"{datetime_key}_{counter}"
            while new_key in metacollection:
                counter += 1
                new_key = f"{datetime_key}_{counter}"
            metacollection[new_key] = meta
    else:
        metacollection[datetime_key] = meta

def handle_directory(img_dir: str) -> None:
    """Process directory recursively if configured."""
    if not os.path.exists(img_dir):
        logger.warning(f"Directory not found: {img_dir}")
        return
    
    # Skip ignored directories
    dir_name = os.path.basename(img_dir)
    if any(pattern in img_dir for pattern in FOLDERS_TO_IGNORE):
        counters['skipped_dirs'] += 1
        return
    
    try:
        for entry in os.scandir(img_dir):
            if entry.is_file():
                handle_file(entry.path)
            elif entry.is_dir(follow_symlinks=False) and config.recursive:
                handle_directory(entry.path)
    except PermissionError:
        logger.warning(f"Permission denied accessing: {img_dir}")
        counters['permission_errors'] += 1

def execute_organization() -> None:
    """Execute the file organization based on collected metadata."""
    if not config.output_dir:
        logger.error("No output directory specified")
        return
    
    success_count = 0
    error_count = 0
    
    for datetime_key, meta in metacollection.items():
        source_path = meta['origin']
        target_path = os.path.join(config.output_dir, meta['target'])
        target_dir = os.path.dirname(target_path)
        
        if config.simulate:
            action = "COPY" if config.copy_mode else "MOVE"
            print(f"{action}: {source_path} -> {target_path}")
            continue
        
        try:
            # Create target directory if it doesn't exist
            os.makedirs(target_dir, exist_ok=True)
            
            # Handle file conflicts
            if os.path.exists(target_path):
                base, ext = os.path.splitext(target_path)
                counter = 1
                while os.path.exists(f"{base}_{counter}{ext}"):
                    counter += 1
                target_path = f"{base}_{counter}{ext}"
            
            # Copy or move file
            if config.copy_mode:
                shutil.copy2(source_path, target_path)
                logger.info(f"Copied: {source_path} -> {target_path}")
            else:
                shutil.move(source_path, target_path)
                logger.info(f"Moved: {source_path} -> {target_path}")
            
            success_count += 1
            
        except Exception as e:
            logger.error(f"Failed to process {source_path}: {e}")
            error_count += 1
    
    print(f"\nOrganization complete: {success_count} files processed, {error_count} errors")

def print_usage(exit_code: int = 0) -> None:
    """Print usage information."""
    print(f"Usage: {sys.argv[0]} -o <output_dir> [options] <input_files_or_dirs>")
    print("\nOptions:")
    print("  -o, --output DIR     Output directory (required)")
    print("  -r, --recursive      Process directories recursively")
    print("  -s, --simulate       Simulate only (don't actually move files)")
    print("  -c, --copy           Copy files instead of moving them")
    print("  -m, --meta           Print collected metadata")
    print("  -e, --exif           Print EXIF data")
    print("  -v, --verbose        Verbose output")
    print("  -h, --help           Show this help message")
    sys.exit(exit_code)

def main(argv):
    """Main function."""
    input_list = []
    
    try:
        opts, args = getopt.getopt(
            argv, 'ho:srcmev', 
            ['help', 'output=', 'simulate', 'recursive', 'copy', 'meta', 'exif', 'verbose']
        )
    except getopt.GetoptError as e:
        print(f"Error: {e}")
        print_usage(2)
    
    if args:
        input_list = args
    
    for opt, arg in opts:
        if opt in ('-h', '--help'):
            print_usage(0)
        elif opt in ('-o', '--output'):
            config.output_dir = arg
        elif opt in ('-s', '--simulate'):
            config.simulate = True
        elif opt in ('-r', '--recursive'):
            config.recursive = True
        elif opt in ('-c', '--copy'):
            config.copy_mode = True
        elif opt in ('-m', '--meta'):
            config.print_meta = True
        elif opt in ('-e', '--exif'):
            config.print_exif = True
        elif opt in ('-v', '--verbose'):
            config.verbose = True
            logger.setLevel(logging.DEBUG)
    
    if config.verbose:
        print(f"Input files/dirs: {input_list}")
        print(f"Output directory: {config.output_dir}")
        print(f"Simulate: {config.simulate}")
        print(f"Recursive: {config.recursive}")
        print(f"Copy mode: {config.copy_mode}")
        print(f"Print metadata: {config.print_meta}")
        print(f"Print EXIF: {config.print_exif}")
    
    if not input_list:
        print("Error: No input files or directories specified")
        print_usage(2)
    
    if not config.simulate and not config.output_dir:
        print("Error: Output directory required when not simulating")
        print_usage(2)
    
    # Process input files/directories
    for inp in input_list:
        if os.path.isfile(inp):
            handle_file(inp)
        elif os.path.isdir(inp):
            handle_directory(inp)
        else:
            logger.warning(f"Input not found: {inp}")
    
    # Print statistics
    print(f"\nProcessing Statistics:")
    for item, count in sorted(counters.items()):
        print(f"  {item}: {count}")
    
    # Execute organization if not just simulating
    if not config.simulate:
        execute_organization()
    else:
        print(f"\nSimulation mode - showing intended operations:")
        execute_organization()

if __name__ == "__main__":
    main(sys.argv[1:])
