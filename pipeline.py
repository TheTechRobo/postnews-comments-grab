# Based heavily off of ArchiveTeam/urls-grab

with open("authorization") as file:
    auth: str = file.read().rstrip()
assert auth.startswith("{") and auth.endswith("}")

import seesaw
from seesaw.project import *
from seesaw.tracker import *
from seesaw.util import *
from seesaw.pipeline import Pipeline
from seesaw.externalprocess import WgetDownload
from seesaw.item import ItemInterpolation, ItemValue
from seesaw.task import SimpleTask

import hashlib
import shutil
import socket
import sys
import json
import time
import os

project = Project()

###########################################################################
# The version number of this pipeline definition.
#
# Update this each time you make a non-cosmetic change.
# It will be added to the WARC files and reported to the tracker.
VERSION = '20240530.01'
#USER_AGENT = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/86.0.4240.183 Safari/537.36'
TRACKER_ID = 'postnews'
TRACKER_HOST = 'host.docker.internal:2600'

class HigherVersion:
    def __init__(self, expression, min_version):
        self._expression = re.compile(expression)
        self._min_version = min_version

    def search(self, text):
        for result in self._expression.findall(text):
            if result >= self._min_version:
                print('Found version {}.'.format(result))
                return True

WGET_AT = find_executable(
    'Wget+AT',
    HigherVersion(
        r'(GNU Wget 1\.[0-9]{2}\.[0-9]{1}-at\.[0-9]{8}\.[0-9]{2})[^0-9a-zA-Z\.-_]',
        'GNU Wget 1.21.3-at.20230623.01'
    ),
    [
        './wget-at',
        '/home/warrior/data/wget-at'
    ]
)

if not WGET_AT:
    raise Exception('No usable Wget+At found.')

class CheckIP(SimpleTask):
    def __init__(self):
        SimpleTask.__init__(self, 'CheckIP')
        self._counter = 0

    def process(self, item):
        # NEW for 2014! Check if we are behind firewall/proxy

        if self._counter <= 0:
            item.log_output('Checking IP address.')
            ip_set = set()

            ip_set.add(socket.gethostbyname('twitter.com'))
            #ip_set.add(socket.gethostbyname('facebook.com'))
            ip_set.add(socket.gethostbyname('youtube.com'))
            ip_set.add(socket.gethostbyname('microsoft.com'))
            ip_set.add(socket.gethostbyname('icanhas.cheezburger.com'))
            ip_set.add(socket.gethostbyname('archiveteam.org'))

            if len(ip_set) != 5:
                item.log_output('Got IP addresses: {0}'.format(ip_set))
                item.log_output(
                    'Are you behind a firewall/proxy? That is a big no-no!')
                raise Exception(
                    'Are you behind a firewall/proxy? That is a big no-no!')

        # Check only occasionally
        if self._counter <= 0:
            self._counter = 10
        else:
            self._counter -= 1

import requests

class Authenticate(SimpleTask):
    def __init__(self):
        SimpleTask.__init__(self, 'Authenticate')
        self._counter = 0
        self.ltime = 0

    def _request(self):
        headers = {
            "Accept": "*/*",
            "Accept-Language": "en-US;q=0.5",
            "Content-Type": "application/x-amz-json-1.1",
            "Origin": "https://post.news",
            "Priority": "u=4",
            "Referer": "https://post.news",
            "Sec-Fetch-Dest": "empty",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Site": "cross-site",
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64; rv:127.0) Gecko/20100101 Firefox/127.0",
            "X-Amz-Target": "AWSCognitoIdentityProviderService.InitiateAuth",
            "X-Amz-User-Agent": "aws-amplify/5.0.4 js"
        }
        res = requests.post(
            "https://cognito-idp.us-east-1.amazonaws.com/",
            headers=headers,
            data=auth
        )
        if res.status_code != 200:
            raise Exception("Failed to authenticate")
        r = res.json()
        self.r = r
        self.ltime = int(time.time())
        print("Got auth response", r)

    def process(self, item):
        ctime = int(time.time())
        diff = ctime - self.ltime
        if self._counter <= 0:
            print("Redoing authentication")
            self._request()
            self._counter = 5
        elif diff > 100:
            print("Stale authentication")
            self._request()
            self._counter = 5
        item['token'] = self.r['AuthenticationResult']['AccessToken']
        self._counter -= 1

class PrepareDirectories(SimpleTask):
    def __init__(self, warc_prefix):
        SimpleTask.__init__(self, 'PrepareDirectories')
        self.warc_prefix = warc_prefix

    def process(self, item):
        item_name = item['item_name']
        item_name_hash = hashlib.sha1(item_name.encode('utf8')).hexdigest()
        escaped_item_name = item_name_hash
        dirname = '/'.join((item['data_dir'], escaped_item_name))

        if os.path.isdir(dirname):
            shutil.rmtree(dirname)

        os.makedirs(dirname)

        item['item_dir'] = dirname
        item['warc_file_base'] = '-'.join([
            self.warc_prefix,
            item_name_hash,
            time.strftime('%Y%m%d-%H%M%S')
        ])

        open('%(item_dir)s/%(warc_file_base)s.warc.gz' % item, 'w').close()
        open('%(item_dir)s/%(warc_file_base)s_retry-urls.txt' % item, 'w').close()

def get_hash(filename):
    with open(filename, 'rb') as in_file:
        return hashlib.sha1(in_file.read()).hexdigest()

CWD = os.getcwd()
PIPELINE_SHA1 = get_hash(os.path.join(CWD, 'pipeline.py'))
LUA_SHA1 = get_hash(os.path.join(CWD, 'grab.lua'))

def stats_id_function(item):
    d = {
        'pipeline_hash': PIPELINE_SHA1,
        'lua_hash': LUA_SHA1,
        'python_version': sys.version,
    }

    return d

class MoveFiles(SimpleTask):
    def __init__(self):
        SimpleTask.__init__(self, 'MoveFiles')

    def process(self, item):
        item["ts"] = time.time()
        item["dd"] = item["data_dir"].lstrip("grab/data/")
        shutil.move('%(item_dir)s/' % item,
            '/finished/%(dd)s_%(item_name)s_%(ts)s/' % item)

class WgetArgs(object):
    def realize(self, item):
        wget_args = [
            'timeout', '3600',
            WGET_AT,
            '-v',
            '--content-on-error',
            '--lua-script', 'grab.lua',
            '-o', ItemInterpolation('%(item_dir)s/wget.log'),
            #'--no-check-certificate',
            '--output-document', ItemInterpolation('%(item_dir)s/wget.tmp'),
            '--truncate-output',
            '-e', 'robots=off',
            '--rotate-dns',
            '--page-requisites',
            '--timeout', '10',
            '--tries', '10',
            '--span-hosts',
            '--waitretry', '0',
            '-w', '1',
            '--random-wait',
            '--warc-file', ItemInterpolation('%(item_dir)s/%(warc_file_base)s'),
            '--warc-header', 'operator: TheTechRobo <thetechrobo@proton.me>',
            '--warc-header', json.dumps(stats_id_function(item)),
            '--warc-header', 'x-wget-at-project-version: ' + VERSION,
            '--warc-header', 'x-wget-at-project-name: postnews-comments',
            '--warc-dedup-url-agnostic',
            '--header', 'Contact: thetechrobo@proton.me',
            '--header', 'Connection: keep-alive',
            '--header', 'Accept: application/json',
            '--header', 'Accept-Language: en-US,en;q=0.5',
            '--header', 'Origin: https://post.news',
            '--header', 'Priority: u=4',
            '--header', 'Referer: https://post.news/',
            '--header', 'Sec-Fetch-Dest: empty',
            '--header', 'Sec-Fetch-Mode: cors',
            '--header', 'Sec-Fetch-Site: cross-site',
            '--header', f"Authorization: Bearer {item['token']}",
            '-U', 'Mozilla/5.0 (Linux x86_64; rv:100.0) Gecko/20100101 Firefox/100.0 ; Operator: TheTechRobo thetechrobo@proton.me',
        ]

        item['item_name_newline'] = item['item_name'].replace('\0', '\n')
        item_urls = []
        custom_items = {}

        assert len(item['item_name'].split("\0")) == 1
        for item_name in item['item_name'].split('\0'):
            wget_args.extend(['--warc-header', 'x-wget-at-project-item-name: '+item_name])
            wget_args.append('item-name://'+item_name)
            itemType, itemValue = item_name.split(':', 1)
            item['post_id'] = itemValue
            if itemType == "post":
                url = 'https://n1nzo2oxji.execute-api.us-east-1.amazonaws.com/prod/private/posts/%s/comments?limit=10' % itemValue
            else:
                raise TypeError("bad item type")
            item_urls.append(url)
            wget_args.append(url)
        #print(wget_args)

        item['item_urls'] = item_urls
        item['custom_items'] = json.dumps(custom_items)

        if 'bind_address' in globals():
            wget_args.extend(['--bind-address', globals()['bind_address']])
            print('')
            print('*** Wget will bind address at {0} ***'.format(
                globals()['bind_address']))
            print('')

        return realize(wget_args, item)

pipeline = Pipeline(
        CheckIP(),
        GetItemFromTracker('http://{}/{}'
            .format(TRACKER_HOST, TRACKER_ID),
            downloader, VERSION),
        Authenticate(),
        PrepareDirectories(warc_prefix='postnews-comments'),
        WgetDownload(
            WgetArgs(),
            max_tries=1,
            accept_on_exit_code=[0, 4, 8],
            env={
                'item_dir': ItemValue('item_dir'),
                'item_name': ItemValue('item_name_newline'),
                'custom_items': ItemValue('custom_items'),
                'warc_file_base': ItemValue('warc_file_base')
            }
        ),
        PrepareStatsForTracker(
            defaults={'downloader': downloader, 'version': VERSION},
            file_groups={
                'data': [
                    ItemInterpolation('%(item_dir)s/%(warc_file_base)s.warc.gz')
                ]
            },
            id_function=stats_id_function,
            ),
        MoveFiles(),
        SendDoneToTracker(
            tracker_url='http://%s/%s' % (TRACKER_HOST, TRACKER_ID),
            stats=ItemValue('stats')
            )
        )
