#!/usr/bin/env python
from __future__ import print_function
import click
import os
import sys
import socket
import requests
import time
import itertools
import io
import pprint
from tinydb import TinyDB, Query
from tqdm import tqdm
from dateutil.parser import parse

from authentication import authenticate

# For retrying connection after timeouts and errors
MAX_RETRIES = 5
WAIT_SECONDS = 5



logHandle = io.open("./icloud.log", mode="a", encoding="utf-8" )


CONTEXT_SETTINGS = dict(help_option_names=['-h', '--help'])
@click.command(context_settings=CONTEXT_SETTINGS, options_metavar='<options>')
@click.argument('directory', type=click.Path(exists=True), metavar='<directory>')
@click.option('--username',
              help='Your iCloud username or email address',
              metavar='<username>',
              prompt='iCloud username/email')
@click.option('--password',
              help='Your iCloud password',
              metavar='<password>')
@click.option('--force',
              help='Force download',
              metavar='<force>',
              is_flag=True)
@click.option('--recent',
              help='Number of recent photos to download (default: download all photos)',
              type=click.IntRange(0))
@click.option('--until-found',
              help='Download most recently added photos until we find x number of previously downloaded consecutive photos (default: download all photos)',
              type=click.IntRange(0))
@click.option('--smtp-username',
              help='Your SMTP username, for sending email notifications when two-step authentication expires.',
              metavar='<smtp_username>')
@click.option('--smtp-password',
              help='Your SMTP password, for sending email notifications when two-step authentication expires.',
              metavar='<smtp_password>')
@click.option('--smtp-host',
              help='Your SMTP server host. Defaults to: smtp.gmail.com',
              metavar='<smtp_host>',
              default='smtp.gmail.com')
@click.option('--smtp-port',
              help='Your SMTP server port. Default: 587 (Gmail)',
              metavar='<smtp_port>',
              type=click.IntRange(0),
              default=587)
@click.option('--smtp-no-tls',
              help='Pass this flag to disable TLS for SMTP (TLS is required for Gmail)',
              metavar='<smtp_no_tls>',
              is_flag=True)
@click.option('--notification-email',
              help='Email address where you would like to receive email notifications. Default: SMTP username',
              metavar='<notification_email>')


def download(directory, username, password, recent, \
    until_found, force,\
    smtp_username, smtp_password, smtp_host, smtp_port, smtp_no_tls, \
    notification_email
    ):
    """Download all iCloud photos to a local directory"""

    icloud = authenticate(username, password, \
        smtp_username, smtp_password, smtp_host, smtp_port, smtp_no_tls, notification_email)

    if hasattr(directory, 'decode'):
        directory = directory.decode('utf-8')

    directory = os.path.normpath(directory)

    db = TinyDB( os.path.join(directory, 'icloud.db' ))

    albums = icloud.photos.albums
    albums_count = len(albums)
    total_item_count = 0
    total_downloads = 0
    
        
    for album_index, this_album in enumerate(albums):
         
        photos = icloud.photos.albums[ this_album ]
        photos_count = len(photos)
        photo_index = 0
        total_item_count += photos_count

        print("Album[%d/%d]: %s (%d)" % (album_index, albums_count, this_album, photos_count) )
        logHandle.write("Album[%d/%d]: %s (%d)\n" % (album_index, albums_count, this_album, photos_count) )
    
        kwargs = {'total': photos_count}

        consecutive_files_found = 0
        
        progress_bar = tqdm(photos, **kwargs)

        for photo in progress_bar:
            photo_index += 1

            for _ in range(MAX_RETRIES):
                try:
                    if not force and not need_to_download( db, this_album, photo ):
                        progress_bar.set_description(
                            "Skipping [%d] %s" % (photo_index, photo.filename) )
                        continue
                    
                    if this_album == 'All Photos':
                        created_date = photo.created
                        date_path = '{:%Y/%m}'.format(created_date)
                        download_dir = os.path.join(directory, "All Photos", date_path ).strip()
                    else:
                        download_dir = os.path.join(directory, this_album ).strip()

                    if not os.path.exists(download_dir):
                        os.makedirs(download_dir)

                    download_path = local_download_path(photo, download_dir)
                    if not force and os.path.isfile(download_path):
                        if until_found is not None:
                            consecutive_files_found += 1
                        
                        logHandle.write("[%d] %s already downloaded.\n" % (photo_index, truncate_middle(download_path, 96)) )
                        progress_bar.set_description("[%d] %s already downloaded." % (photo_index, truncate_middle(download_path, 96)))
                        break

                    download_photo(photo, download_path, progress_bar, photo_index, db, this_album)

                    if until_found is not None:
                        consecutive_files_found = 0
                    break

                except (requests.exceptions.ConnectionError, socket.timeout):
                    
                    tqdm.write('Connection failed, retrying after %d seconds...' % WAIT_SECONDS)
                    time.sleep(WAIT_SECONDS)

            # else:
            #     tqdm.write("Could not process %s! Maybe try again later." % photo.filename)

            if until_found is not None and consecutive_files_found >= until_found:
                
                tqdm.write('Found %d consecutive previusly downloaded photos. Exiting' % until_found)
                logHandle.write('Found %d consecutive previusly downloaded photos. Exiting\n' % until_found)
                progress_bar.close()
                break


def need_to_download( db, album, photo ):
    Q = Query()
    res = db.search( (Q.filename == photo.filename ) & (Q.album == album ) )
    if len( res ) != 0:
        return False
    return True

def truncate_middle(s, n):
    if len(s) <= n:
        return s
    n_2 = int(n) // 2 - 2
    n_1 = n - n_2 - 4
    if n_2 < 1: n_2 = 1
    return '{0}...{1}'.format(s[:n_1], s[-n_2:])

def make_filename(photo):
    remove_punctuation_map = dict((ord(char), None) for char in '\/*?:"+<>|')

    return photo.filename.encode('utf-8') \
        .decode('ascii', 'ignore').replace('.', '-%s.' % photo.id.translate(remove_punctuation_map))

def local_download_path(photo, download_dir):
    # Strip any non-ascii characters.
    filename = make_filename(photo)
    download_path = os.path.join(download_dir, filename)
    return download_path

def download_photo(photo, download_path, progress_bar, photo_index, db, this_album):

    filename = photo.filename
    #filesize = photo.size

    if photo.filename.endswith('.HEIC'):
        logHandle.write("HEIC file detected\n")
        size = 'medium'
        if photo.versions['medium']['type'] == 'com.apple.quicktime-movie':
            filename = os.path.splitext(filename)[0]+".MOV"
            download_path = os.path.splitext(download_path)[0]+".MOV"    
        else:
            filename = os.path.splitext(filename)[0]+".jpg"
            download_path = os.path.splitext(download_path)[0]+".jpg"

        logHandle.write("Changing name from [%s] to [%s] and download path to [%s]\n" % ( photo.filename, filename, download_path ))
    else:
        size = 'original'

    
    logHandle.write("Will download [%d] %s (%d) from\n%s\n" % ( photo_index, filename, photo.size, photo.download(size).url))
    progress_bar.set_description("Downloading [%d] %s" % ( photo_index, filename))

    download_url = photo.download(size)
    if not os.path.exists( download_path ):
        for _ in range(MAX_RETRIES):
            try:            
                if download_url:                    
                    logHandle.write( 'cURLing [%d] %s to %s\n' % (photo_index, filename, download_path ))
                    with open(download_path, 'wb') as file:
                        for chunk in download_url.iter_content(chunk_size=1024):
                            if chunk:
                                file.write(chunk)
                    logHandle.write('Success!\n')
                    db.insert({ 'filename': filename, 'album': this_album, 'size': photo.size })
                    break
                else:
                    tqdm.write(
                        "Could not find URL to download %s for size %s!" %
                        (photo.filename, size))
                    logHandle.write(
                        "Could not find URL to download %s for size %s!\n" %
                        (photo.filename, size))
            except (requests.exceptions.ConnectionError, socket.timeout):
                tqdm.write(
                    '%s download failed, retrying after %d seconds...' %
                    (photo.filename, WAIT_SECONDS))
                logHandle.write(
                    '%s download failed, retrying after %d seconds...\n' %
                    (photo.filename, WAIT_SECONDS))
                time.sleep(WAIT_SECONDS)
        else:
            tqdm.write("Could not download %s! Maybe try again later." % photo.filename)
            logHandle.write("Could not download %s! Maybe try again later.\n" % photo.filename)

    else:
        tqdm.write("[%d] %s exists" % ( photo_index, photo.filename ))
        logHandle.write("[%d] %s exists\n" % ( photo_index, photo.filename ))
    

if __name__ == '__main__':
    download()
