#!/usr/bin/python3


# imports

import sys, getopt
import os
import re

# import filetype

from exif import Image
# from rawphoto.cr2 import Cr2
# from rawphoto.nef import Nef
import pyexiv2

import time

# types

class Counter(dict):
    def __missing__(self, key):
        return 0

# globals

# ext comparisons are done lowercase
myExtensions = {'.jpg', '.jpeg', '.cr2', '.png', '.rw2', '.dng', '.gif', '.tif', '.heic'}

# shorten some EXIF-Model descriptions, as they go into the filename
myCams = {'Canon DIGITAL IXUS 100 IS': 'CanonIXUS100',
        'Canon DIGITAL IXUS 430': 'CanonIXUS430',
        'Canon DIGITAL IXUS 70': 'CanonIXUS70',
        'Canon EOS 350D DIGITAL': 'EOS350D',
        'Canon EOS 6D Mark II': 'EOS6DmkII',
        'Canon EOS 70D': 'EOS70D',
        'Canon PowerShot G5':'CanonG5',
        'KODAK DC280 ZOOM DIGITAL CAMERA':'KodakDC280',
        'PENTAX Optio S ': 'PENTAX-OptioS'
}

folders2ignore = {'Mac OS Wallpaper Pack', 'Fotos Library'}



outp = ''
simulate = False
recursive = False
verbose = False
pmeta = False
pexif = False
events = False

metacollection = {}

counters = Counter()


        


# sub

# https://bhoey.com/blog/extracting-raw-photo-exif-data-with-python/
def extractExiv2(meta, imgFile):
    md = pyexiv2.ImageMetadata(imgFile)
    try:
        md.read()
    except:
        return

    # print all exif tags in file
    if(pexif):
        for m in md:
            if(not re.findall('apple-fi', m)):# skip due to bug in exiv library
                print(m + ": " + str(md[m]))
            else:
                print(m + ': ' + '========== SKIPPED ==========')

    # pick model + date
    exifData = {
    'Model': 'Exif.Image.Model',
    'DateTimeDigitized': 'Exif.Photo.DateTimeOriginal',
    'PixelX': 'Exif.Photo.PixelXDimension',
    'PixelY': 'Exif.Photo.PixelYDimension' }

    for key in exifData:
        if(exifData[key] in md):
            counters['has:' + key] += 1
            meta[key] = md[exifData[key]].value

    return


# look at file and extract metadata:
#  1. via filename and filesystem information
#  2. analyze Canon/Nikon RAW files via rawphoto
#      https://gist.github.com/SamWhited/af58edaed66414bded84      
#  3. analyze other RAW files via pi3exiv2
#      https://bhoey.com/blog/extracting-raw-photo-exif-data-with-python/
def collectMeta(meta, imgFile, filename, fileext):

    meta['origin']=imgFile
    meta['ext']=fileext.lower()
    #meta['filename']=filename
      
    meta['size']=os.path.getsize(imgFile)
    # meta['ctime']=time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(os.path.getctime(imgFile)))
    modtime=time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(os.path.getmtime(imgFile)))

    # handle: - image files (jpg, png, etc)
    #         - raw files (CR2, ...)
    #      (   - Metadata files (XMP): move together with corresponding image file )
    
    # https://pypi.org/project/filetype/
    # kind = filetype.guess(imgFile)
    # meta['kind']=kind
    #if(kind!=None):
    extractExiv2(meta, imgFile)	
    
    # heuristics
    if('DateTimeDigitized' in meta):
        meta['DateTimeUsed']=meta['DateTimeDigitized']
    else:
        meta['DateTimeUsed']=modtime

    # DateTime Format: YYYY-MM-DD HH:mm:ss
    #                  1234567890123456789
    meta['day'] = str(meta['DateTimeUsed'])[:10]     # first 10 chars
    meta['time'] = str(meta['DateTimeUsed'])[11:]    # rest, starting from 12th char
    meta['year'] = str(meta['DateTimeUsed'])[:4]     # first 4 chars
    counters[str('year:' + meta['year'])] += 1

    if('Model' in meta):
        if(meta['Model'] in myCams):
            meta['Model'] = myCams[str(meta['Model'])]
    else:
        meta['Model']='other'

    targetpath = str(meta['year'] + '/' + meta['day'])
    targetname = str(meta['time'] + '_' + meta['Model'] + '_' + filename)

    meta['target'] = str(targetpath + '/' + targetname )


def handleFile(imgFile):
    global counters
    global metacollection
    global myextensions

    #if(verbose):
    #    print("entering handleFile: " + imgFile)
    if(not os.path.exists(imgFile)):
        return 

    counters['total'] += 1
    filebase, fileext = os.path.splitext(imgFile)
    filepath, filename = os.path.split(imgFile)

    # skip anything starting with a . or non interesting filetypes
    if(filename[:1]=='.' or fileext.lower() not in myExtensions):
        counters['ignored'] += 1
        return
    counters['ToDo'] += 1
    counters[fileext.lower()] += 1

    meta={}

    collectMeta(meta, imgFile, filename, fileext)

    # what have we got?
    if(pmeta):
        print('extracted Metadata:')
        for x in meta:
            print('meta: ' + x + "=" + str(meta[x]))

    # do we have already an image at timestamp ?
    if str(meta['DateTimeUsed']) in metacollection:
         prev = metacollection[str(meta['DateTimeUsed'])]
         # is it the same type? raw+jpg will be kept
         if(prev['ext'] == meta['ext']):
             # only keep the largest image
             if meta['size'] > prev['size']:
                 counters['doubled'] += 1
                 metacollection[str(meta['DateTimeUsed'])] = meta
    else:
         metacollection[str(meta['DateTimeUsed'])] = meta

# iterate all entries in the directory. walk directory tree, if recursive is set
def handleDir(imgDir):
    #if(verbose):
    #   print("entering handleDir: " + imgDir)
    # skip ignored dirs
    for pattern in folders2ignore:
        if(re.findall(pattern, imgDir)):
            counters['skipped dir'] += 1
            return 
    for entry in os.scandir(imgDir):
        if(entry.is_file()):
            handleFile(entry.path)
        if(recursive):
            if(entry.is_dir(follow_symlinks=False)):
                handleDir(entry.path)


def usage(err):
    print(__file__  + ' -o <output directory> [-r] [-s] [-m] [-e] [-v] <inputfiles/directory>')
    print('-r: recursive\n-s: simulate only\n-m: print collected image metadata\n-e: print image exif data\n-v: verbose output')
    sys.exit(err)



def main(argv):
    inlist = []
    global outp
    global simulate
    global recursive
    global verbose
    global pmeta
    global pexif
    global events
    global counters

    global metacollection

    try:
        opts, args = getopt.getopt(argv,'ho:srvme',['ofile=','simulate','recursive','verbose','pmeta','exif'])
    except getopt.GetoptError:
        usage(2)
    if(args):
        inlist = args
    for opt, arg in opts:
        if opt == '-h':
            usage(0)
        elif opt in ("-o", "--ofile"):
            outp = arg
        elif opt in ("-s", "--simulate"):
            simulate = True
        elif opt in ("-r", "--recursive"):
            recursive = True
        elif opt in ("-v", "--verbose"):
            verbose = True
        elif opt in ("-e", "--exif"):
            pexif = True
        elif opt in ("-m", "--pmeta"):
            pmeta = True
    if(verbose):
        print('Input List is: ', inlist)
        print('Output dir is: ', outp)
        print('simulate: ', simulate)
        print('recursive: ', recursive)
        print('verbose: ', verbose)
        print('pmeta: ', pmeta)
        print('exif: ', pexif)

    if(len(inlist)<1):
        usage(2)
   
    # traverse inlist and collect data on all images
    for inp in inlist:
        if(os.path.isfile(inp)):
            handleFile(inp)
        if(os.path.isdir(inp)):
            handleDir(inp)

    # output counters
    for item, cnt in counters.items():
        print('counted: ', item, ': ', cnt)

    # output intent what to do
    for img in metacollection:
        meta = metacollection[img]
        if(simulate):
            print("move " + str(meta['origin']) + ' to ' + str(meta['target']))

if __name__ == "__main__":
    main(sys.argv[1:])



