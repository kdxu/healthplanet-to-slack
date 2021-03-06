#!/usr/bin/env python
# coding:utf-8
from itertools import groupby
import os
import datetime
import json
from datetime import datetime as dt
from logging import basicConfig, getLogger, DEBUG

import requests
from bs4 import BeautifulSoup

HOST = 'www.healthplanet.jp'
CLIENT_ID = os.environ['HEALTHPLANET_CLIENT_ID']
CLIENT_SECRET = os.environ['HEALTHPLANET_CLIENT_SECRET']
USER_ID = os.environ['HEALTHPLANET_USER_ID']
USER_PASSWORD = os.environ['HEALTHPLANET_USER_PASSWORD']
SLACK_POST_URL = os.environ['SLACK_POST_URL']
SLACK_CHANNEL = os.environ['SLACK_CHANNEL']
REDIRECT_URI = 'https://www.healthplanet.jp/success.html'
DEFAULT_SCOPES = 'innerscan'
DEFAULT_RESPONSE_TYPE = 'code'
DEFAULT_GRANT_TYPE = 'authorization_code'
WEIGHT_TAG = '6021'
FAT_PARCENTAGE_TAG = '6022'
SCOPE_DAYS = 1

basicConfig(level=DEBUG)
logger = getLogger(__name__)


def login(session, login_id, password, url):
    payload = {
        'loginId': login_id,
        'passwd': password,
        'send': 1,
        'url': url,
    }
    headers = {'content-type': 'application/x-www-form-urlencoded'}
    return session.post(uri('/login_oauth.do'), data=payload, headers=headers)


def auth(session):
    payload = {
        'client_id': CLIENT_ID,
        'redirect_uri': REDIRECT_URI,
        'scope': DEFAULT_SCOPES,
        'response_type': DEFAULT_RESPONSE_TYPE,
    }
    return session.get(uri('/oauth/auth'), params=payload)


def approval(session, token):
    payload = {
        'approval': True,
        'oauth_token': token,
    }
    headers = {'content-type': 'application/x-www-form-urlencoded'}
    return session.post(uri('/oauth/approval.do'), data=payload, headers=headers)


def get_token(code):
    payload = {
        'client_id': CLIENT_ID,
        'client_secret': CLIENT_SECRET,
        'redirect_uri': REDIRECT_URI,
        'code': code,
        'grant_type': DEFAULT_GRANT_TYPE,
    }
    return requests.post(uri('/oauth/token'), params=payload)


def get_innerscan(token, from_date):
    from_str = from_date.strftime('%Y%m%d%H%M%S')
    payload = {
        'access_token': token,
        'date': 1,
        'tag': '6021,6022',
        'from': from_str,
    }
    return requests.get(uri('/status/innerscan.json'), params=payload)


def uri(path):
    return 'https://{0}{1}'.format(HOST, path)


def get_oauth_token(text):
    soup = BeautifulSoup(text, 'html.parser')
    value = soup.find('input', {'name': 'oauth_token'}).get('value')
    return value


def get_code(text):
    soup = BeautifulSoup(text, 'html.parser')
    value = soup.find('textarea', {'id': 'code'}).getText()
    return value


def get_data():
    session = requests.Session()
    auth_response = auth(session)
    login_response = login(session, USER_ID, USER_PASSWORD, auth_response.url)
    token = get_oauth_token(login_response.text)
    approve_response = approval(session, token)
    code = get_code(approve_response.text)
    token_response = get_token(code)
    access_token = token_response.json()['access_token']
    innerscan_response = get_innerscan(access_token, dt.now() - datetime.timedelta(days=SCOPE_DAYS))
    return innerscan_response.json()


def group_process(date, dept_group):
    weights = filter(lambda m: m['tag'] == WEIGHT_TAG, dept_group)
    fats = filter(lambda m: m['tag'] == FAT_PARCENTAGE_TAG, dept_group)
    weight_formats = ["体重: {0}".format(weight['keydata']) for weight in weights]
    fat_formats = ["体脂肪率: {0}".format(fat['keydata']) for fat in fats]
    return ["日時: {0}".format(date)] + weight_formats + fat_formats


def post_process(data):
    datum = sorted(data['data'], key=lambda x: x['date'])
    dept_emp_groups = groupby(datum, lambda e: e['date'])
    formats = [group_process(date, list(dept_group)) for date, dept_group in dept_emp_groups]
    return '\n'.join(str(e) for e in flatten(list(formats)))


def flatten(alist):
    new_list = []
    for item in alist:
        if isinstance(item, (list, tuple)):
            new_list.extend(flatten(item))
        else:
            new_list.append(item)
    return new_list


def lambda_handler(event, context):
    content = get_data()

    slack_message = {
        'channel': SLACK_CHANNEL,
        'text': post_process(content),
    }
    try:
        logger.info(json.dumps(slack_message))
        requests.post(SLACK_POST_URL, data=json.dumps(slack_message).encode('utf-8'))
        logger.info("Message posted to %s", slack_message['channel'])
    except requests.exceptions.RequestException as e:
        logger.error("Request failed: %s", e)
