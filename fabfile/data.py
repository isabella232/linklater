#!/usr/bin/env python

"""
Commands that update or process the application data.
"""
from datetime import datetime
import json

from bs4 import BeautifulSoup
from flask import render_template
from fabric.api import task
from facebook import GraphAPI
from hypchat import HypChat
from PIL import Image
from twitter import Twitter, OAuth
from selenium import webdriver
from selenium.webdriver.support.ui import WebDriverWait
from jinja2 import Environment, FileSystemLoader

import app_config
import copytext
import os
import requests

env = Environment(loader=FileSystemLoader('templates'))
current_time = datetime.now()

@task(default=True)
def update():
    """
    Stub function for updating app-specific data.
    """
    #update_featured_social()

@task
def make_draft_html():
    links = fetch_tweets('lookatthisstory')
    template = env.get_template('tumblr.html')
    output = template.render(links=links)
    return output

@task
def fetch_tweets(username, days):
    """
    Get tweets of a specific user
    """
    secrets = app_config.get_secrets()

    twitter_api = Twitter(
        auth=OAuth(
            secrets['TWITTER_API_OAUTH_TOKEN'],
            secrets['TWITTER_API_OAUTH_SECRET'],
            secrets['TWITTER_API_CONSUMER_KEY'],
            secrets['TWITTER_API_CONSUMER_SECRET']
        )
    )

    tweets = twitter_api.statuses.user_timeline(screen_name=username, count=30)

    out = []

    for tweet in tweets:

        created_time_raw = tweet['created_at']

        created_time = datetime.strptime(created_time_raw, '%a %b %d %H:%M:%S +0000 %Y')

        time_difference = (current_time - created_time).days

        if time_difference > int(days):
            break

        urls = tweet['entities']['urls']
        for url in urls:
            if not url['display_url'].startswith('pic.twitter.com'):
                row = _grab_url(url['expanded_url'])
            if row:
                row['tweet_text'] = tweet['text']
                if tweet.get('retweeted_status'):
                    row['tweet_url'] = 'http://twitter.com/%s/status/%s' % (tweet['retweeted_status']['user']['screen_name'], tweet['id'])
                    row['tweeted_by'] = tweet['retweeted_status']['user']['screen_name']
                    out.append(row)  
                else:
                    row['tweet_url'] = 'http://twitter.com/%s/status/%s' % (username, tweet['id'])
                    out.append(row)                    

    out = _dedupe_links(out)

    return out

def _grab_url(url):
    """
    Returns data of the form:
    {
        'title': <TITLE>,
        'description': <DESCRIPTION>,
        'type': <page/image/download>,
        'image': <IMAGE_URL>,
        'tweet_url': <TWEET_URL>.
        'tweet_text': <TWEET_TEXT>,
        'tweeted_by': <USERNAME>
    }
    """
    data = None

    resp = requests.get(url)
    real_url = resp.url

    if resp.status_code == 200 and resp.headers.get('content-type').startswith('text/html'):
        data = {}
        data['url'] = real_url

        soup = BeautifulSoup(resp.content)

        og_tags = ('image', 'title', 'description')
        for og_tag in og_tags:
            match = soup.find(attrs={'property': 'og:%s' % og_tag})
            if match and match.attrs.get('content'):
                data[og_tag] = match.attrs.get('content')

    else:
        print "There was an error accessing %s (%s)" % (real_url, resp.status_code)

    return data

def _dedupe_links(links):
    """
    Get rid of duplicate URLs
    """
    out = []
    urls_seen = []
    for link in links:
        if link['url'] not in urls_seen:
            urls_seen.append(link['url'])
            out.append(link)
        else:
            print "%s is a duplicate, skipping" % link['url']

    return out

@task
def fetch_hipchat_logs(room):
    """
    Get hipchat logs of a room
    """

    secrets = app_config.get_secrets()

    hipchat_api = HypChat(secrets['HIPCHAT_API_OAUTH_TOKEN']) 

    room_data_dict = hipchat_api.get_room(room)

    room_id = room_data_dict['id']

    chat_history = list(hipchat_api.get_room(room_id).history().contents())

    # print chat_history

    from pprint import pprint
    
    for message in chat_history:

        if 'message_links' in message:
            print message

@task
def update_featured_social():
    """
    Update featured tweets
    """
    COPY = copytext.Copy(app_config.COPY_PATH)
    secrets = app_config.get_secrets()

    # Twitter
    print 'Fetching tweets...'

    twitter_api = Twitter(
        auth=OAuth(
            secrets['TWITTER_API_OAUTH_TOKEN'],
            secrets['TWITTER_API_OAUTH_SECRET'],
            secrets['TWITTER_API_CONSUMER_KEY'],
            secrets['TWITTER_API_CONSUMER_SECRET']
        )
    )

    tweets = []

    for i in range(1, 4):
        tweet_url = COPY['share']['featured_tweet%i' % i]

        if isinstance(tweet_url, copytext.Error) or unicode(tweet_url).strip() == '':
            continue

        tweet_id = unicode(tweet_url).split('/')[-1]

        tweet = twitter_api.statuses.show(id=tweet_id)

        creation_date = datetime.strptime(tweet['created_at'],'%a %b %d %H:%M:%S +0000 %Y')
        creation_date = '%s %i' % (creation_date.strftime('%b'), creation_date.day)

        tweet_url = 'http://twitter.com/%s/status/%s' % (tweet['user']['screen_name'], tweet['id'])

        photo = None
        html = tweet['text']
        subs = {}

        for media in tweet['entities'].get('media', []):
            original = tweet['text'][media['indices'][0]:media['indices'][1]]
            replacement = '<a href="%s" target="_blank" onclick="_gaq.push([\'_trackEvent\', \'%s\', \'featured-tweet-action\', \'link\', 0, \'%s\']);">%s</a>' % (media['url'], app_config.PROJECT_SLUG, tweet_url, media['display_url'])

            subs[original] = replacement

            if media['type'] == 'photo' and not photo:
                photo = {
                    'url': media['media_url']
                }

        for url in tweet['entities'].get('urls', []):
            original = tweet['text'][url['indices'][0]:url['indices'][1]]
            replacement = '<a href="%s" target="_blank" onclick="_gaq.push([\'_trackEvent\', \'%s\', \'featured-tweet-action\', \'link\', 0, \'%s\']);">%s</a>' % (url['url'], app_config.PROJECT_SLUG, tweet_url, url['display_url'])

            subs[original] = replacement

        for hashtag in tweet['entities'].get('hashtags', []):
            original = tweet['text'][hashtag['indices'][0]:hashtag['indices'][1]]
            replacement = '<a href="https://twitter.com/hashtag/%s" target="_blank" onclick="_gaq.push([\'_trackEvent\', \'%s\', \'featured-tweet-action\', \'hashtag\', 0, \'%s\']);">%s</a>' % (hashtag['text'], app_config.PROJECT_SLUG, tweet_url, '#%s' % hashtag['text'])

            subs[original] = replacement

        for original, replacement in subs.items():
            html =  html.replace(original, replacement)

        # https://dev.twitter.com/docs/api/1.1/get/statuses/show/%3Aid
        tweets.append({
            'id': tweet['id'],
            'url': tweet_url,
            'html': html,
            'favorite_count': tweet['favorite_count'],
            'retweet_count': tweet['retweet_count'],
            'user': {
                'id': tweet['user']['id'],
                'name': tweet['user']['name'],
                'screen_name': tweet['user']['screen_name'],
                'profile_image_url': tweet['user']['profile_image_url'],
                'url': tweet['user']['url'],
            },
            'creation_date': creation_date,
            'photo': photo
        })

    # Facebook
    print 'Fetching Facebook posts...'

    fb_api = GraphAPI(secrets['FACEBOOK_API_APP_TOKEN'])

    facebook_posts = []

    for i in range(1, 4):
        fb_url = COPY['share']['featured_facebook%i' % i]

        if isinstance(fb_url, copytext.Error) or unicode(fb_url).strip() == '':
            continue

        fb_id = unicode(fb_url).split('/')[-1]

        post = fb_api.get_object(fb_id)
        user  = fb_api.get_object(post['from']['id'])
        user_picture = fb_api.get_object('%s/picture' % post['from']['id'])
        likes = fb_api.get_object('%s/likes' % fb_id, summary='true')
        comments = fb_api.get_object('%s/comments' % fb_id, summary='true')
        #shares = fb_api.get_object('%s/sharedposts' % fb_id)

        creation_date = datetime.strptime(post['created_time'],'%Y-%m-%dT%H:%M:%S+0000')
        creation_date = '%s %i' % (creation_date.strftime('%b'), creation_date.day)

        # https://developers.facebook.com/docs/graph-api/reference/v2.0/post
        facebook_posts.append({
            'id': post['id'],
            'message': post['message'],
            'link': {
                'url': post['link'],
                'name': post['name'],
                'caption': (post['caption'] if 'caption' in post else None),
                'description': post['description'],
                'picture': post['picture']
            },
            'from': {
                'name': user['name'],
                'link': user['link'],
                'picture': user_picture['url']
            },
            'likes': likes['summary']['total_count'],
            'comments': comments['summary']['total_count'],
            #'shares': shares['summary']['total_count'],
            'creation_date': creation_date
        })

    # Render to JSON
    output = {
        'tweets': tweets,
        'facebook_posts': facebook_posts
    }

    with open('data/featured.json', 'w') as f:
        json.dump(output, f)
