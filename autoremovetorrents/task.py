# -*- coding:utf-8 -*-
import os
import time
import re
from . import logger
from .client.qbittorrent import qBittorrent
from .client.transmission import Transmission
from .client.utorrent import uTorrent
from .client.deluge import Deluge
from .exception.nosuchclient import NoSuchClient
from .strategy import Strategy
from autoremovetorrents.torrent import Torrent
from .util.discord_notifier import send_discord_notification

class Task(object):
    def __init__(self, name, conf, remove_torrents = True):
        # Logger
        self._logger = logger.Logger.register(__name__)

        # Save task name
        self._name = name

        # Replace environment variables first
        pattern = re.compile(r'\$\(([^\)]+)\)')
        replace_keys = ['host', 'username', 'password']
        for key in replace_keys:
            if key in conf:
                env = pattern.match(str(conf[key]))
                if env is not None and env.group(1) in os.environ:
                    conf[key] = os.environ[env.group(1)]

        # Read configurations
        self._client_name = conf['client']
        self._client = None
        self._host = conf['host'].rstrip('/')
        self._username = conf['username'] if 'username' in conf else ''
        self._password = conf['password'] if 'password' in conf else ''
        self._enabled_remove = remove_torrents
        self._delete_data = conf['delete_data'] if 'delete_data' in conf else False
        self._strategies = conf['strategies'] if 'strategies' in conf else []
        self._discord_webhook_url = conf.get('discord_webhook_url')

        # Torrents
        self._torrents = set()
        self._remove = set()

        # Client status
        self._client_status = None

        # Allow removing specified torrents(for CI testing only)
        if 'force_delete' in conf:
            for hash_ in conf['force_delete']:
                torrent_obj = Torrent()
                torrent_obj.hash = hash_
                torrent_obj.name = hash_
                self._remove.add(torrent_obj)

        # Print debug logs
        self._logger.debug("Configuration of task '%s':" % self._name)
        self._logger.debug('Client: %s, Host: %s, Username: %s, Password: %s' % (
            self._client_name, self._host, self._username, self._password
        ))
        self._logger.debug('Remove Torrents: %s, Remove Torrents and Data: %s' % (
            self._enabled_remove, self._delete_data
        ))
        self._logger.debug('Strategies: %s' % ', '.join(self._strategies))
        self._logger.debug(f'Discord Webhook URL: {self._discord_webhook_url if self._discord_webhook_url else "Not configured"}')

    # Login client
    def _login(self):
        # Find the type of client
        # Use unicode type for Python 2.7
        clients = {
            u'qbittorrent': qBittorrent,
            u'transmission': Transmission,
            u'μtorrent': uTorrent,
            u'utorrent': uTorrent, # Alias for μTorrent
            u'deluge': Deluge,
        }
        self._client_name = self._client_name.lower() # Set the client name to be case insensitive
        if self._client_name not in clients:
            raise NoSuchClient("The client `%s` doesn't exist." % self._client_name)

        # Initialize client object
        self._client = clients[self._client_name](self._host)

        # Login
        self._logger.info('Logging in...')
        self._client.login(self._username, self._password)
        self._logger.info('Login successfully. The client is %s.' % self._client.version())
        self._logger.info('WebUI API version: %s' % self._client.api_version())

        # Get client status
        self._client_status = self._client.client_status()
        self._logger.info(self._client_status)

    # Get all the torrents and properties
    def _get_torrents(self):
        self._logger.info('Getting all the torrents...')
        last_time = time.time()
        for hash_value in self._client.torrents_list():
            # Append new torrent
            self._torrents.add(self._client.torrent_properties(hash_value))
            # For a long waiting
            if time.time() - last_time > 1:
                self._logger.info('Please wait...We have found %d torrent(s).' %
                    len(self._torrents))
                last_time = time.time()
        self._logger.info('Found %d torrent(s) in the client.' % len(self._torrents))

    # Apply strategies
    def _apply_strategies(self):
        for strategy_name in self._strategies:
            strategy = Strategy(strategy_name, self._strategies[strategy_name])
            strategy.execute(self._client_status, self._torrents)
            self._remove.update(strategy.remove_list)

    # Remove torrents
    def _remove_torrents(self):
        # Bulid a dict to store torrent hashes and names which to be deleted
        delete_map = {torrent.hash: torrent for torrent in self._remove}
        torrent_hashes_to_remove = list(delete_map.keys())

        # Perform pre-remove actions if the client supports it
        if hasattr(self._client, 'pre_remove_actions') and callable(getattr(self._client, 'pre_remove_actions')):
            try:
                self._logger.info("Performing pre-remove actions...")
                self._client.pre_remove_actions(torrent_hashes_to_remove)
            except Exception as e: # Catch any exception during pre-remove actions
                self._logger.error(f"Error during pre-remove actions: {e}. Proceeding with removal attempt.")

        # Run deletion
        success_hashes, failed_torrents = self._client.remove_torrents(torrent_hashes_to_remove, self._delete_data)
        # Output logs and send notifications
        for hash_ in success_hashes:
            removed_torrent_obj = delete_map[hash_]
            removed_torrent_name = removed_torrent_obj.name
            log_message = (
                'The torrent %s and its data have been removed.' if self._delete_data
                else 'The torrent %s has been removed.'
            ) % removed_torrent_name
            self._logger.info(log_message)
            if self._discord_webhook_url:
                send_discord_notification(self._discord_webhook_url, removed_torrent_obj)

        for failed_item in failed_torrents:
            failed_torrent_obj = delete_map[failed_item['hash']]
            failed_torrent_name = failed_torrent_obj.name
            reason = failed_item['reason']
            log_message = (
                'The torrent %s and its data cannot be removed. Reason: %s' if self._delete_data
                else 'The torrent %s cannot be removed. Reason: %s'
            ) % (failed_torrent_name, reason)
            self._logger.error(log_message)

    # Execute
    def execute(self):
        self._logger.info("Running task '%s'..." % self._name)
        self._login()
        self._get_torrents()
        self._apply_strategies()
        if self._enabled_remove:
            self._remove_torrents()

    # Get remaining torrents (for tester)
    def get_remaining_torrents(self):
        return self._torrents

    # Get removed torrents (for tester)
    def get_removed_torrents(self):
        return self._remove