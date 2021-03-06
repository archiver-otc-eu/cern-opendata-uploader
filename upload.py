#!/usr/bin/env python3

import configargparse
import shutil
import tempfile
import urllib.request
from urllib.parse import urlparse
import json
import requests
import os
import logging
from http import HTTPStatus

DEFAULT_CONFIG_FILE = 'config.yaml'

parser = configargparse.ArgumentParser(
    formatter_class=configargparse.ArgumentDefaultsHelpFormatter,
    default_config_files=['config.yaml'],
    description='Register files in the Onedata system.')

requiredNamed = parser.add_argument_group('required named arguments')

requiredNamed.add_argument(
    '--host', '-H',
    action='store',
    help='Oneprovider host.',
    dest='host',
    required=True)

requiredNamed.add_argument(
    '--space-id', '-spi',
    action='store',
    help='Id of the space in which the files will be registered.',
    dest='space_id',
    required=True)

requiredNamed.add_argument(
    '--storage-id', '-sti',
    action='store',
    help='Id of the storage on which the files are located. Storage must be created as an `imported` storage with path type equal to `canonical`.',
    dest='storage_id',
    required=True)

requiredNamed.add_argument(
    '--token', '-t',
    action='store',
    help='Onedata access token.',
    dest='token',
    required=True)

requiredNamed.add_argument(
    '--collection-url', '-c',
    action='append',
    help='Open data collection URL. Many collections can be passed (e.g. `-c URL1 -c URL2`).',
    dest='collections',
    required=True)

parser.add_argument(
    '--file-mode', '-m',
    action='store',
    help='POSIX mode with which files will be registered, represented as an octal string.',
    dest='mode',
    default="0664"
)

parser.add_argument(
    '--disable-auto-detection', '-dd',
    action='store_true',
    help='Flag which disables automatic detection of file attributes and verification whether file exists on storage. '
         'Passing this flag results in faster registration of files but there is a risk of registering files that '
         'don\'t exist on storage. Such files will be visible in the space but not accessible.',
    dest='disable_auto_detection',
    default=False
)

parser.add_argument(
    '--logging-frequency', '-lf',
    action='store',
    type=int,
    help='Frequency of logging. Log will occur after registering every logging_freq number of files.',
    dest='logging_freq',
    default=None)

parser.add_argument(
    '--disable-cert-verification', '-dv',
    action='store_true',
    help='Flag which disables verification of SSL certificate.',
    dest='disable_cert_verification',
    default=False)

parser.add_argument(
    '--config-file',
    action='store',
    is_config_file=True,
    help='Path to config file which will override the default {0}'.format(DEFAULT_CONFIG_FILE),
    dest='config_file'
)


REGISTER_FILE_ENDPOINT = "https://{0}/api/v3/oneprovider/data/register"


def strip_server_url(storage_file_id):
    parsed_url = urlparse(storage_file_id)
    if parsed_url.scheme:
        return parsed_url.path
    else:
        return storage_file_id


def register_file(storage_file_id, size, checksum):
    headers = {
        'X-Auth-Token': args.token,
        "content-type": "application/json"
    }
    storage_file_id = strip_server_url(storage_file_id)
    payload = {
        'spaceId': args.space_id,
        'storageId': args.storage_id,
        'storageFileId': storage_file_id,
        'destinationPath': storage_file_id,
        'size': size,
        'mode': args.mode,
        'xattrs': {
            'checksum': checksum
        },
        'autoDetectAttributes': not args.disable_auto_detection
    }
    try:
        response = requests.post(REGISTER_FILE_ENDPOINT.format(args.host), json=payload, headers=headers, verify=(not args.disable_cert_verification))
        if response.status_code == HTTPStatus.CREATED:
            return True
        else:
            logging.error("Registration of {0} failed with HTTP status {1}.\n""Response: {2}"
                          .format(storage_file_id, response.status_code, response.content)),
            return False
    except Exception as e:
        logging.error("Registration of {0} failed due to {1}".format(storage_file_id, e), exc_info=True)


def download_and_load_json(url):
    with urllib.request.urlopen(url) as response:
        with tempfile.NamedTemporaryFile(delete=True) as tmp_file:
            shutil.copyfileobj(response, tmp_file)
            tmp_file.flush()
            with open(tmp_file.name, 'r') as f:
                return json.load(f)


def get_files_and_json_indexes_urls(collection_url):
    collection = download_and_load_json(collection_url)
    index_urls = []
    txt_urls = []
    for index_spec in collection["metadata"]["index_files"]:
        index_url = index_spec['uri_http']
        [_, ext] = os.path.splitext(index_url)
        if ext == ".json":
            index_urls.append(index_url)
        elif ext == ".txt":
            txt_urls.append(txt_urls)
    return collection["metadata"]["files"], index_urls


def register_files_from_index(index_url):
    file_specs = download_and_load_json(index_url)
    size_sum = 0
    count = 0
    for i, file_spec in enumerate(file_specs):
        if args.logging_freq and i % args.logging_freq == 0 and i > 0:
            print("Registered {0} files".format(i))
        if register_file(file_spec['uri'], file_spec['size'], file_spec['checksum']):
            size_sum += file_spec['size']
            count += 1
    return size_sum, count


args = parser.parse_args()
total_size = 0
total_count = 0

for collection_url in args.collections:
    print("Processing collection {0}".format(collection_url))
    file_specs, index_urls = get_files_and_json_indexes_urls(collection_url)

    if file_specs:
        print("Registering files")

    for file_spec in file_specs:
        if register_file(file_spec['uri_root'], file_spec['size'], file_spec['checksum']):
            total_size += file_spec['size']
            total_count += 1

    for index_url in index_urls:
        print("Registering files from index {0}".format(index_url))
        size_sum, count = register_files_from_index(index_url)
        total_size += size_sum
        total_count += count

print("\nTotal registered files count: {0}".format(total_count))
print("Total size: {0}".format(total_size))
