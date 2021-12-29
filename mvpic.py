#!/usr/bin/python3


# imports

import sys, getopt
import os
import re

import filetype

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

simulate = False
recursive = False
verbose = False
events = False
        
counters = Counter()

def extractExif(meta, imgFile):
    with open(imgFile, 'rb') as ifile:
        thisImg = Image(ifile)

        if(thisImg.has_exif):
            meta['Model'] = thisImg.Model
            meta['datetime_digitized'] = thisImg.datetime_digitized
            if(verbose):
                print(imgFile + ": " + thisImg.Model + "-" + thisImg.datetime_digitized)
                print(thisImg.gps_latitude, thisImg.gps_longitude)

        ifile.close()
    return


# https://bhoey.com/blog/extracting-raw-photo-exif-data-with-python/
def extractExiv2(meta, imgFile):
    md = pyexiv2.ImageMetadata(imgFile)
    md.read()

    # print all exif tags in file
    #if(verbose):
    #    for m in md:
    #        print(m + "=" + str(md[m]))

    # pick model + date
    exifData = {
    'Model': 'Exif.Image.Model',
    'DateTimeDigitized': 'Exif.Photo.DateTimeOriginal' }
    for key in exifData:
        if(exifData[key] in md):
            counters['has:' + key] += 1
            meta[key] = md[exifData[key]].value


    return


def collectMeta(meta, imgFile):
    global counters
    
    counters['total'] += 1
    filebase, fileext = os.path.splitext(imgFile)
    filepath, filename = os.path.split(imgFile)

    # skip anything starting with a . or non interesting filetypes
    myExtensions = {'.jpg', '.jpeg', '.cr2', '.png', '.rw2', '.dng', '.gif', '.tif', '.heic'}
    if(filename[:1]=='.' or fileext.lower() not in myExtensions):
        counters['ignored'] += 1
        return

    counters['toMove'] += 1
    counters[fileext.lower()] += 1

    meta['fullpath']=imgFile
    meta['ext']=fileext.lower()
    meta['filename']=filename
      
    meta['size']=os.path.getsize(imgFile)
    # meta['ctime']=time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(os.path.getctime(imgFile)))
    meta['mtime']=time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(os.path.getmtime(imgFile)))

    # handle: - image files (jpg, png, etc)
    #         - raw files (CR2, ...)
    #      (   - Metadata files (XMP): move together with corresponding image file )
    
    # https://pypi.org/project/filetype/
    kind = filetype.guess(imgFile)
    meta['kind']=kind
    if(kind!=None):
        extractExiv2(meta, imgFile)	
    
    # heuristics
    if('DateTimeDigitized' in meta):
        meta['bestDate']=meta['DateTimeDigitized']
    else:
        meta['bestDate']=meta['mtime']

    meta['year'] = str(meta['bestDate'])[:4]
    counters[str('year:' + meta['year'])] += 1
    meta['day'] = str(meta['bestDate'])[:10]

    if('Model' in meta):
        meta['bestModel']=meta['Model']
    else:
        meta['bestModel']='other'




# look at file, find out, how to extract metadata:
#  1. via Exif data
#      https://pypi.org/project/exif/
#  2. analyze Canon/Nikon RAW files via rawphoto
#      https://gist.github.com/SamWhited/af58edaed66414bded84      
#  3. analyze other RAW files via pi3exiv2
#      https://bhoey.com/blog/extracting-raw-photo-exif-data-with-python/
def handleFile(imgFile):
    global counters
    if(verbose):
        print("entering handleFile: " + imgFile)
    if(not os.path.exists(imgFile)):
        return 

    meta={}

    collectMeta(meta, imgFile)
    # what have we got?
    if(verbose):
        print('extracted Metadata:')
        for x in meta:
            print('meta: ' + x + "=" + str(meta[x]))


# iterate all entries in the directory. walk directory tree, if recursive is set
def handleDir(imgDir):
    if(verbose):
        print("entering handleDir: " + imgDir)

    for entry in os.scandir(imgDir):
        if(entry.is_file()):
            handleFile(entry.path)
        if(recursive):
            if(entry.is_dir(follow_symlinks=False)):
                handleDir(entry.path)


def usage(err):
    print(__file__  + ' -o <output directory> [-r] [-s] [-v] <inputfiles/directory>')
    sys.exit(err)




def main(argv):
   inlist = []
   outp = ''
   global simulate
   global recursive
   global verbose
   global events
   global counters
   try:
      opts, args = getopt.getopt(argv,"ho:srv",["ofile=","simulate","recursive","verbose"])
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
   if(verbose):
       print('Input List is: ', inlist)
       print('Output file is: ', outp)
       print('simulate: ', simulate)
       print('recursive: ', recursive)

   if(len(inlist)<1):
   	   usage(2)
   
   for inp in inlist:
       if(os.path.isfile(inp)):
           handleFile(inp)
       if(os.path.isdir(inp)):
           handleDir(inp)
# output counters
   for item, cnt in counters.items():
       print('counted: ', item, ': ', cnt)

if __name__ == "__main__":
   main(sys.argv[1:])



