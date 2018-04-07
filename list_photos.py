#!/usr/bin/env python
from __future__ import print_function
import click
import os
import sys
import socket
import requests
import time
import pprint

from tqdm import tqdm
from dateutil.parser import parse
from pyicloud import PyiCloudService

# For retrying connection after timeouts and errors
MAX_RETRIES = 5
WAIT_SECONDS = 5


CONTEXT_SETTINGS = dict(help_option_names=['-h', '--help'])
@click.command(context_settings=CONTEXT_SETTINGS, options_metavar='<options>')
@click.argument('directory', type=click.Path(exists=True), metavar='<directory>')
@click.option('--username',
              help='Your iCloud username or email address',
              metavar='<username>',
              prompt='iCloud username/email')
@click.option('--password',
              help='Your iCloud password (leave blank if stored in keyring)',
              metavar='<password>')


def list_photos(directory, username, password):
    """Prints out file path of photos that will be downloaded"""

    icloud = authenticate(username, password)
    all_photos = icloud.photos.all

    directory = directory.rstrip('/')

    for photo in all_photos:
        for _ in range(MAX_RETRIES):
            try:
                #print( "Local Index: [%d]" % photo.local_index )
                print( "Id: [%s]" % photo.id )
                print( "FN: [%s]\nSZ: [%d]\n" % ( photo.filename, photo.size))
                created_date = photo.created
                date_path = '{:%Y/%m/%d}'.format(created_date)
                download_dir = '/'.join((directory, date_path))
                print( "Versions:\n")
                pprint.pprint(photo.versions, depth=5, indent=2)

                # Strip any non-ascii characters.
                filename = photo.filename.encode('utf-8') \
                    .decode('ascii', 'ignore').replace('.', '-original.')

                download_path = '/'.join((download_dir, filename))
                print(download_path)
                print("~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~\n")
                break

            except (requests.exceptions.ConnectionError, socket.timeout):
                time.sleep(WAIT_SECONDS)


def authenticate(username, password):
    if password:
      icloud = PyiCloudService(username, password)
    else:
      icloud = PyiCloudService(username)


    return icloud

if __name__ == '__main__':
    list_photos()
