#!/usr/bin/env python

from email.parser import Parser
from fabric.api import local, require, settings, task
from fabric.state import env
from jinja2 import Environment, FileSystemLoader
from termcolor import colored
from datetime import datetime

import app_config

# Other fabfiles
import assets
import boto.ses
import data
import flat
import issues
import os
import pytumblr
import render
import smtplib
import text
import utils

if app_config.DEPLOY_TO_SERVERS:
    import servers

if app_config.DEPLOY_CRONTAB:
    import cron_jobs

# Bootstrap can only be run once, then it's disabled
if app_config.PROJECT_SLUG == '$NEW_PROJECT_SLUG':
    import bootstrap


"""
Base configuration
"""
env.user = app_config.SERVER_USER
env.forward_agent = True
env.hosts = []
env.settings = None

env.tumblr_blog_name = 'stage-lookatthis'
env.twitter_handle = 'lookatthisstory'
env.twitter_timeframe = '7' # days
env.from_email_address = 'NPR Visuals Linklater <nprapps@npr.org>'
env.to_email_addresses = ['sson@npr.org', 'deads@npr.org']
env.email_subject_template = 'Richard Linklater\'s links for %s'

# Jinja env
fab_path = os.path.realpath(os.path.dirname(__file__))
templates_path = os.path.join(fab_path, '../templates')
env.jinja_env = Environment(loader=FileSystemLoader(templates_path))

"""
Environments

Changing environment requires a full-stack test.
An environment points to both a server and an S3
bucket.
"""
@task
def production():
    """
    Run as though on production.
    """
    env.settings = 'production'
    app_config.configure_targets(env.settings)
    env.hosts = app_config.SERVERS
    env.tumblr_blog_name = 'lookatthis'

@task
def staging():
    """
    Run as though on staging.
    """
    env.settings = 'staging'
    app_config.configure_targets(env.settings)
    env.hosts = app_config.SERVERS

"""
Branches

Changing branches requires deploying that branch to a host.
"""
@task
def stable():
    """
    Work on stable branch.
    """
    env.branch = 'stable'

@task
def master():
    """
    Work on development branch.
    """
    env.branch = 'master'

@task
def branch(branch_name):
    """
    Work on any specified branch.
    """
    env.branch = branch_name

"""
Running the app
"""
@task
def app(port='8000'):
    """
    Serve app.py.
    """
    local('gunicorn -b 0.0.0.0:%s --debug --reload app:wsgi_app' % port)

@task
def public_app(port='8001'):
    """
    Serve public_app.py.
    """
    local('gunicorn -b 0.0.0.0:%s --debug --reload public_app:wsgi_app' % port)

@task
def tests():
    """
    Run Python unit tests.
    """
    local('nosetests')

"""
Deployment

Changes to deployment requires a full-stack test. Deployment
has two primary functions: Pushing flat files to S3 and deploying
code to a remote server if required.
"""
@task
def update():
    """
    Update all application data not in repository (copy, assets, etc).
    """
    text.update()
    assets.sync()
    data.update()

@task
def deploy(remote='origin'):
    """
    Deploy the latest app to S3 and, if configured, to our servers.
    """
    require('settings', provided_by=[production, staging])

    if app_config.DEPLOY_TO_SERVERS:
        require('branch', provided_by=[stable, master, branch])

        if (app_config.DEPLOYMENT_TARGET == 'production' and env.branch != 'stable'):
            utils.confirm(
                colored("You are trying to deploy the '%s' branch to production.\nYou should really only deploy a stable branch.\nDo you know what you're doing?" % env.branch, "red")
            )

        servers.checkout_latest(remote)

        servers.fabcast('assets.sync')

        servers.install_crontab()

@task
def linklater():
    """
    Alerts recipients when Tumblr draft with links scraped from Twitter via fetch_tweets() is available.
    """
    now = datetime.now()
    print "%s: Running linklater" % now.isoformat()

    response = deploy_to_tumblr()

    template = env.jinja_env.get_template('notification_email.html')

    context = {
        'blog_name': env.tumblr_blog_name,
        'tumblr_post_id': response['id'],
        'day_range': env.twitter_timeframe,
        'twitter_handle': env.twitter_handle,
    }

    output = template.render(**context)

    subject = env.email_subject_template % now.strftime('%a, %b %d %Y')

    connection = boto.ses.connect_to_region('us-east-1')

    connection.send_email(
        source=env.from_email_address,
        subject=subject,
        body=None,
        html_body=output,
        to_addresses=env.to_email_addresses
    )

@task
def deploy_to_tumblr():
    secrets = app_config.get_secrets()
    tumblr_api = pytumblr.TumblrRestClient(
            secrets['TUMBLR_CONSUMER_KEY'],
            secrets['TUMBLR_CONSUMER_SECRET'],
            secrets['TUMBLR_TOKEN'],
            secrets['TUMBLR_TOKEN_SECRET']
        )

    body = data.make_tumblr_draft_html()

    response = tumblr_api.create_text(env.tumblr_blog_name, state='draft', format='html', body=body.encode('utf8'))

    return response

"""
Destruction

Changes to destruction require setup/deploy to a test host in order to test.
Destruction should remove all files related to the project from both a remote
host and S3.
"""

@task
def shiva_the_destroyer():
    """
    Deletes the app from s3
    """
    require('settings', provided_by=[production, staging])

    utils.confirm(
        colored("You are about to destroy everything deployed to %s for this project.\nDo you know what you're doing?')" % app_config.DEPLOYMENT_TARGET, "red")
    )

    with settings(warn_only=True):
        flat.delete_folder(app_config.PROJECT_SLUG) 

        if app_config.DEPLOY_TO_SERVERS:
            servers.delete_project()

            if app_config.DEPLOY_CRONTAB:
                servers.uninstall_crontab()

            if app_config.DEPLOY_SERVICES:
                servers.nuke_confs()

