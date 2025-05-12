#-*- coding:utf-8 -*-
import requests
import json
from .. import logger
from ..util.convertbytes import convert_bytes
from ..util.convertseconds import convert_seconds

def send_discord_notification(webhook_url, torrent):
    """
    Sends a notification to the provided Discord webhook URL about a removed torrent.
    """
    # Get logger instance inside the function
    lg = logger.Logger.register(__name__)
    if not lg: # Add a guard in case register still returns None
        print("Error: Logger not available in discord_notifier.")
        return

    if not webhook_url:
        return

    try:
        torrent_name = getattr(torrent, 'name', 'N/A')
        ratio = getattr(torrent, 'ratio', 0.0)
        # Ensure numeric types for formatting, default to 0 if not present or not convertible
        try:
            uploaded_val = float(getattr(torrent, 'uploaded', 0))
        except (ValueError, TypeError):
            uploaded_val = 0.0
        try:
            size_val = float(getattr(torrent, 'size', 0))
        except (ValueError, TypeError):
            size_val = 0.0
        try:
            seeding_time_val = int(getattr(torrent, 'seeding_time', 0))
        except (ValueError, TypeError):
            seeding_time_val = 0
        # ADDED: Get and convert last_activity
        try:
            last_activity_val = int(getattr(torrent, 'last_activity', 0))
        except (ValueError, TypeError):
            last_activity_val = 0

        uploaded_str = convert_bytes(uploaded_val)
        total_size_str = convert_bytes(size_val)
        seeding_time_str = convert_seconds(seeding_time_val)
        last_activity_str = convert_seconds(last_activity_val) # ADDED
        category_list = getattr(torrent, 'category', [])
        category = ', '.join(category_list) if category_list else 'N/A'

        trackers_list = getattr(torrent, 'tracker', [])
        tracker_hosts = []
        if trackers_list:
            from ..compatibility.urlparse_ import urlparse_
            for t_url in trackers_list:
                host = urlparse_(t_url).hostname
                if host:
                    tracker_hosts.append(host)
                elif t_url:
                    tracker_hosts.append(t_url)
        trackers_str = ', '.join(tracker_hosts) if tracker_hosts else 'N/A'

        payload = {
            "embeds": [
                {
                    "title": f"Torrent Removed: {torrent_name}",
                    "color": 15158332, # Red color
                    "fields": [
                        {"name": "Ratio", "value": f"{ratio:.2f}", "inline": True},
                        {"name": "Uploaded", "value": uploaded_str, "inline": True},
                        {"name": "Total Size", "value": total_size_str, "inline": True},
                        {"name": "Seeding Time", "value": seeding_time_str, "inline": True},
                        {"name": "Last Activity", "value": last_activity_str, "inline": True}, # ADDED
                        {"name": "Category", "value": category, "inline": True},
                        {"name": "Trackers", "value": trackers_str, "inline": False}
                    ],
                    "footer": {
                        "text": "Auto Remove Torrents"
                    }
                }
            ]
        }

        response = requests.post(webhook_url, data=json.dumps(payload), headers={'Content-Type': 'application/json'}, timeout=10)
        response.raise_for_status()
        lg.debug(f"Successfully sent Discord notification for torrent: {torrent_name}")
    except requests.exceptions.RequestException as e:
        lg.error(f"Failed to send Discord notification for {torrent_name}: {e}")
    except Exception as e:
        lg.error(f"An unexpected error occurred while sending Discord notification for {torrent_name}: {e}")
        lg.debug('Exception Logged', exc_info=True)
