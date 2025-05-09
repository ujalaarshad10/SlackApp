import os
import secrets
import time
import json
import base64
from flask_talisman import Talisman
from flask import Flask, request, jsonify, render_template, session
from werkzeug.datastructures import CallbackDict
from flask.sessions import SessionInterface, SessionMixin
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError
from utils import format_calendar_events,get_mentions_from_history
from slack_bolt import App
from slack_bolt.adapter.flask import SlackRequestHandler
from slack_bolt.oauth.oauth_settings import OAuthSettings
from dotenv import find_dotenv, load_dotenv
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from psycopg2.extras import Json
from googleapiclient.discovery import build
from slack_sdk.oauth import InstallationStore
from slack_sdk.oauth.installation_store.models.installation import Installation
from slack_bolt.authorization import AuthorizeResult
from msal import ConfidentialClientApplication
import psycopg2
from apscheduler.schedulers.background import BackgroundScheduler
from datetime import datetime, timedelta
from collections import defaultdict
import hashlib
from utils import get_user_timezone
import re
import logging
from threading import Lock
from urllib.parse import quote_plus
from langchain.chains import LLMChain
from langchain.prompts import ChatPromptTemplate
from agents.all_agents import (
    create_schedule_agent, create_update_agent, create_delete_agent, llm,
    create_schedule_group_agent, create_update_group_agent, create_schedule_channel_agent
)
from all_tools import tools, calendar_prompt_tools
from db import init_db
import requests

# Load environment variables
load_dotenv(find_dotenv())
os.environ['OAUTHLIB_INSECURE_TRANSPORT'] = '1'
os.environ['OAUTHLIB_RELAX_TOKEN_SCOPE'] = '1'
os.environ['OAUTHLIB_IGNORE_SCOPE_CHANGE'] = '1'

# Configuration
SLACK_CLIENT_ID = os.getenv('SLACK_CLIENT_ID', '')
SLACK_CLIENT_SECRET = os.getenv('SLACK_CLIENT_SECRET', '')
SLACK_SIGNING_SECRET = os.getenv('SLACK_SIGNING_SECRET', '')
SLACK_SCOPES = [
    "app_mentions:read", "channels:history", "chat:write", "users:read", "im:write",
    "groups:write", "mpim:write", "commands", "team:read", "channels:read",
    "groups:read", "im:read", "mpim:read", "groups:history", "im:history", "mpim:history"
]
SLACK_BOT_USER_ID = os.getenv("SLACK_BOT_USER_ID")
ZOOM_REDIRECT_URI = os.getenv('ZOOM_REDIRECT_URI')
CLIENT_ID = os.getenv("ZOOM_CLIENT_ID")
CLIENT_SECRET = os.getenv("ZOOM_CLIENT_SECRET")
ZOOM_TOKEN_API = "https://zoom.us/oauth/token"
ZOOM_OAUTH_AUTHORIZE_API = os.getenv("ZOOM_OAUTH_AUTHORIZE_API", "https://zoom.us/oauth/authorize")
OAUTH_REDIRECT_URI = os.getenv("OAUTH_REDIRECT_URI", "https://clear-muskox-grand.ngrok-free.app/oauth2callback")
MICROSOFT_CLIENT_ID = os.getenv("MICROSOFT_CLIENT_ID")
MICROSOFT_CLIENT_SECRET = os.getenv("MICROSOFT_CLIENT_SECRET")
MICROSOFT_AUTHORITY = "https://login.microsoftonline.com/common"
MICROSOFT_SCOPES = ["User.Read", "Calendars.ReadWrite"]
MICROSOFT_REDIRECT_URI = os.getenv("MICROSOFT_REDIRECT_URI", "https://clear-muskox-grand.ngrok-free.app/microsoft_callback")

# Initialize Flask app
app = Flask(__name__)
app.secret_key = secrets.token_hex(16)
talisman = Talisman(
    app,
    content_security_policy={
        'default-src': "'self'",
        'script-src': "'self'",
        'object-src': "'none'"
    },
    force_https=True,
    strict_transport_security=True,
    strict_transport_security_max_age=31536000,
    x_content_type_options=True,
    referrer_policy='no-referrer-when-downgrade'
)

# Custom In-Memory Session Interface
class InMemorySession(dict, SessionMixin):
    def __init__(self, sid):
        self.sid = sid
        super().__init__()

class InMemorySessionInterface(SessionInterface):
    def __init__(self):
        self.sessions = {}

    def generate_sid(self):
        return secrets.token_urlsafe(32)

    def open_session(self, app, request):
        cookie_name = app.config.get('SESSION_COOKIE_NAME', 'session')
        sid = request.cookies.get(cookie_name)
        if sid and sid in self.sessions:
            return self.sessions[sid]
        sid = self.generate_sid()
        return InMemorySession(sid=sid)

    def save_session(self, app, session, response):
        cookie_name = app.config.get('SESSION_COOKIE_NAME', 'session')
        domain = app.config.get('SESSION_COOKIE_DOMAIN')
        path = app.config.get('SESSION_COOKIE_PATH', '/')
        secure = app.config.get('SESSION_COOKIE_SECURE', False)
        httponly = app.config.get('SESSION_COOKIE_HTTPONLY', True)
        samesite = app.config.get('SESSION_COOKIE_SAMESITE', None)
        max_age = app.config.get('PERMANENT_SESSION_LIFETIME', 31_536_000)

        if session is None:
            response.delete_cookie(cookie_name, domain=domain, path=path)
            return

        if not session:
            if session.sid in self.sessions:
                del self.sessions[session.sid]
            response.delete_cookie(cookie_name, domain=domain, path=path)
            return

        self.sessions[session.sid] = session
        response.set_cookie(
            cookie_name, session.sid, max_age=max_age, secure=secure,
            httponly=httponly, domain=domain, path=path, samesite=samesite
        )

app.session_interface = InMemorySessionInterface()
app.config['SESSION_COOKIE_NAME'] = 'custom_session'
app.config['SESSION_COOKIE_SECURE'] = True
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=1).total_seconds()

# Installation Store for OAuth
class DatabaseInstallationStore:
    def __init__(self):
        self._logger = logging.getLogger(__name__)

    def save(self, installation):
        try:
            conn = psycopg2.connect(os.getenv('DATABASE_URL'))
            cur = conn.cursor()
            workspace_id = installation.team_id
            installed_at = datetime.fromtimestamp(installation.installed_at) if installation.installed_at else None
            installation_data = {
                "team_id": installation.team_id,
                "enterprise_id": installation.enterprise_id,
                "user_id": installation.user_id,
                "bot_token": installation.bot_token,
                "bot_id": installation.bot_id,
                "bot_user_id": installation.bot_user_id,
                "bot_scopes": installation.bot_scopes,
                "user_token": installation.user_token,
                "user_scopes": installation.user_scopes,
                "incoming_webhook_url": installation.incoming_webhook_url,
                "incoming_webhook_channel": installation.incoming_webhook_channel,
                "incoming_webhook_channel_id": installation.incoming_webhook_channel_id,
                "incoming_webhook_configuration_url": installation.incoming_webhook_configuration_url,
                "app_id": installation.app_id,
                "token_type": installation.token_type,
                "installed_at": installed_at.isoformat() if installed_at else None
            }
            current_time = datetime.now()
            cur.execute('''
                INSERT INTO Installations (workspace_id, installation_data, updated_at)
                VALUES (%s, %s, %s)
                ON CONFLICT (workspace_id) DO UPDATE SET
                    installation_data = %s, updated_at = %s
            ''', (workspace_id, Json(installation_data), current_time, Json(installation_data), current_time))
            conn.commit()
            self._logger.info(f"Saved installation for workspace {workspace_id}")
        except Exception as e:
            self._logger.error(f"Failed to save installation for workspace {workspace_id}: {e}")
            raise
        finally:
            cur.close()
            conn.close()

    def find_installation(self, enterprise_id=None, team_id=None, user_id=None, is_enterprise_install=False):
        if not team_id:
            self._logger.warning("No team_id provided for find_installation")
            return None
        
        # Initialize variables to None
        conn = None
        cur = None
        
        try:
            # Attempt to connect to the database
            conn = psycopg2.connect(os.getenv('DATABASE_URL'))
            cur = conn.cursor()
            
            # Query the database
            cur.execute('SELECT installation_data FROM Installations WHERE workspace_id = %s', (team_id,))
            row = cur.fetchone()
            
            if row:
                installation_data = row[0]
                installed_at = (datetime.fromisoformat(installation_data["installed_at"])
                                if installation_data.get("installed_at") else None)
                return Installation(
                    app_id=installation_data["app_id"],
                    enterprise_id=installation_data.get("enterprise_id"),
                    team_id=installation_data["team_id"],
                    bot_token=installation_data["bot_token"],
                    bot_id=installation_data["bot_id"],
                    bot_user_id=installation_data["bot_user_id"],
                    bot_scopes=installation_data["bot_scopes"],
                    user_id=installation_data["user_id"],
                    user_token=installation_data.get("user_token"),
                    user_scopes=installation_data.get("user_scopes"),
                    incoming_webhook_url=installation_data.get("incoming_webhook_url"),
                    incoming_webhook_channel=installation_data.get("incoming_webhook_channel"),
                    incoming_webhook_channel_id=installation_data.get("incoming_webhook_channel_id"),
                    incoming_webhook_configuration_url=installation_data.get("incoming_webhook_configuration_url"),
                    token_type=installation_data["token_type"],
                    installed_at=installed_at
                )
            else:
                self._logger.info(f"No installation found for team_id {team_id}")
                return None
        
        except Exception as e:
            self._logger.error(f"Error retrieving installation for team_id {team_id}: {e}")
            return None
        
        finally:
            # Only close if they were created
            if cur is not None:
                cur.close()
            if conn is not None:
                conn.close()

    def find_bot(self, enterprise_id=None, team_id=None, is_enterprise_install=False):
        if not team_id:
            self._logger.warning("No team_id provided for find_bot")
            return None
        try:
            conn = psycopg2.connect(os.getenv('DATABASE_URL'))
            cur = conn.cursor()
            cur.execute('SELECT installation_data FROM Installations WHERE workspace_id = %s', (team_id,))
            row = cur.fetchone()
            if row:
                installation_data = row[0]
                return AuthorizeResult(
                    enterprise_id=installation_data.get("enterprise_id"),
                    team_id=installation_data["team_id"],
                    bot_token=installation_data["bot_token"],
                    bot_id=installation_data["bot_id"],
                    bot_user_id=installation_data["bot_user_id"]
                )
            else:
                self._logger.info(f"No bot installation found for team_id {team_id}")
                return None
        except Exception as e:
            self._logger.error(f"Error retrieving bot for team_id {team_id}: {e}")
            return None
        finally:
            cur.close()
            conn.close()

installation_store = DatabaseInstallationStore()

def get_client_for_team(team_id):
    installation = installation_store.find_installation(None, team_id)
    if installation:
        token = installation.bot_token
        return WebClient(token=token)
    return None

# Initialize Slack Bolt app
oauth_settings = OAuthSettings(
    client_id=SLACK_CLIENT_ID,
    client_secret=SLACK_CLIENT_SECRET,
    scopes=SLACK_SCOPES,
    redirect_uri=os.getenv("SLACK_OAuth"),
    installation_store=installation_store
)
bolt_app = App(signing_secret=SLACK_SIGNING_SECRET, oauth_settings=oauth_settings)
slack_handler = SlackRequestHandler(bolt_app)

# Logging setup
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Google Calendar API Scopes
SCOPES = [
    'https://www.googleapis.com/auth/calendar',
    'https://www.googleapis.com/auth/calendar.readonly',
    'https://www.googleapis.com/auth/userinfo.email',
    'https://www.googleapis.com/auth/userinfo.profile'
]

# Initialize database
init_db()

# State Management Classes
class StateManager:
    def __init__(self):
        self._states = {}
        self._lock = Lock()

    def create_state(self, user_id):
        with self._lock:
            state_token = secrets.token_urlsafe(32)
            self._states[state_token] = {"user_id": user_id, "timestamp": datetime.now(), "used": False}
            return state_token

    def validate_and_consume_state(self, state_token):
        with self._lock:
            if state_token not in self._states:
                return None
            state_data = self._states[state_token]
            if state_data["used"] or (datetime.now() - state_data["timestamp"]).total_seconds() > 600:
                del self._states[state_token]
                return None
            state_data["used"] = True
            return state_data["user_id"]

    def cleanup_expired_states(self):
        with self._lock:
            current_time = datetime.now()
            expired = [s for s, d in self._states.items() if (current_time - d["timestamp"]).total_seconds() > 600]
            for state in expired:
                del self._states[state]

state_manager = StateManager()

class EventDeduplicator:
    def __init__(self, expiration_minutes=5):
        self.processed_events = defaultdict(list)
        self.expiration_minutes = expiration_minutes

    def clean_expired_events(self):
        current_time = datetime.now()
        for event_id in list(self.processed_events.keys()):
            events = [(t, h) for t, h in self.processed_events[event_id]
                      if current_time - t < timedelta(minutes=self.expiration_minutes)]
            if events:
                self.processed_events[event_id] = events
            else:
                del self.processed_events[event_id]

    def is_duplicate_event(self, event_payload):
        self.clean_expired_events()
        event_id = event_payload.get('event_id', '')
        payload_hash = hashlib.md5(str(event_payload).encode('utf-8')).hexdigest()
        if 'challenge' in event_payload:
            return False
        if event_id in self.processed_events and payload_hash in [h for _, h in self.processed_events[event_id]]:
            return True
        self.processed_events[event_id].append((datetime.now(), payload_hash))
        return False

event_deduplicator = EventDeduplicator()

class SessionStore:
    def __init__(self):
        self._store = {}
        self._lock = Lock()

    def set(self, user_id, key, value):
        with self._lock:
            if user_id not in self._store:
                self._store[user_id] = {}
            self._store[user_id][key] = {"value": value, "expires_at": datetime.now() + timedelta(hours=1)}

    def get(self, user_id, key, default=None):
        with self._lock:
            if user_id not in self._store or key not in self._store[user_id]:
                return default
            session_data = self._store[user_id][key]
            if datetime.now() > session_data["expires_at"]:
                del self._store[user_id][key]
                return default
            return session_data["value"]

    def clear(self, user_id, key):
        with self._lock:
            if user_id in self._store and key in self._store[user_id]:
                del self._store[user_id][key]

session_store = SessionStore()

def store_in_session(user_id, key_type, data):
    session_store.set(user_id, key_type, data)

def get_from_session(user_id, key_type, default=None):
    return session_store.get(user_id, key_type, default)

# Database Helper Functions
def save_preference(team_id, user_id, zoom_config=None, calendar_tool=None):
    conn = psycopg2.connect(os.getenv('DATABASE_URL'))
    cur = conn.cursor()
    cur.execute('SELECT zoom_config, calendar_tool FROM Preferences WHERE team_id = %s AND user_id = %s', (team_id, user_id))
    existing = cur.fetchone()
    if existing:
        current_zoom_config, current_calendar_tool = existing
        new_zoom_config = zoom_config if zoom_config is not None else current_zoom_config
        new_calendar_tool = calendar_tool if calendar_tool is not None else current_calendar_tool
        cur.execute('''
            UPDATE Preferences 
            SET zoom_config = %s, calendar_tool = %s, updated_at = %s
            WHERE team_id = %s AND user_id = %s
        ''', (json.dumps(new_zoom_config) if new_zoom_config else None, 
              new_calendar_tool, datetime.now(), team_id, user_id))
    else:
        new_zoom_config = zoom_config or {"mode": "manual", "link": None}
        new_calendar_tool = calendar_tool or "google"
        cur.execute('''
            INSERT INTO Preferences (team_id, user_id, zoom_config, calendar_tool, updated_at)
            VALUES (%s, %s, %s, %s, %s)
        ''', (team_id, user_id, json.dumps(new_zoom_config), new_calendar_tool, datetime.now()))
    conn.commit()
    cur.close()
    conn.close()

def load_preferences(team_id, user_id):
    try:
        conn = psycopg2.connect(os.getenv('DATABASE_URL'))
        cur = conn.cursor()
        cur.execute('SELECT zoom_config, calendar_tool FROM Preferences WHERE team_id = %s AND user_id = %s', (team_id, user_id))
        row = cur.fetchone()
        if row:
            zoom_config, calendar_tool = row
            preferences = {
                "zoom_config": zoom_config if zoom_config else {"mode": "manual", "link": None},
                "calendar_tool": calendar_tool or "none"
            }
        else:
            preferences = {"zoom_config": {"mode": "manual", "link": None}, "calendar_tool": "none"}
        cur.close()
        conn.close()
    except Exception as e:
        logger.error(f"Failed to load preferences for team {team_id}, user {user_id}: {e}")
        preferences = {"zoom_config": {"mode": "manual", "link": None}, "calendar_tool": "none"}
    return preferences

def save_token(team_id, user_id, service, token_data):
    conn = psycopg2.connect(os.getenv('DATABASE_URL'))
    cur = conn.cursor()
    cur.execute('''
        INSERT INTO Tokens (team_id, user_id, service, token_data, updated_at)
        VALUES (%s, %s, %s, %s, %s)
        ON CONFLICT (team_id, user_id, service) DO UPDATE SET token_data = %s, updated_at = %s
    ''', (team_id, user_id, service, json.dumps(token_data), datetime.now(), json.dumps(token_data), datetime.now()))
    conn.commit()
    cur.close()
    conn.close()

def load_token(team_id, user_id, service):
    conn = psycopg2.connect(os.getenv('DATABASE_URL'))
    cur = conn.cursor()
    cur.execute('SELECT token_data FROM Tokens WHERE team_id = %s AND user_id = %s AND service = %s', (team_id, user_id, service))
    row = cur.fetchone()
    cur.close()
    conn.close()
    return row[0] if row else None

# Utility Functions
def get_all_users(client, channel_id, team_id):
    try:
        response = client.conversations_members(channel=channel_id)
        if response["ok"]:
            channel_user_ids = set(response["members"])
            users_response = client.users_list()
            if users_response["ok"]:
                users = users_response["members"]
                return {
                    user["id"]: {
                        "Slack Id": user["id"],
                        "real_name": user.get("real_name", "Unknown"),
                        "email": user["profile"].get("email", "unknown@gmail.com"),
                        "name": user.get("name", "Unknown"),
                        "email_":f"{user.get('name', 'Unknown')}@gmail.com"
                    }
                    for user in users if user["id"] in channel_user_ids
                }
            else:
                logger.error(f"Failed to fetch users_list: {users_response['error']}")
        else:
            logger.error(f"Failed to fetch channel members: {response['error']}")
    except Exception as e:
        logger.error(f"Error fetching users from Slack: {e}")

    try:
        channel_info = client.conversations_info(channel=channel_id)
        if not channel_info["ok"]:
            logger.error(f"Failed to fetch channel info: {channel_info['error']}")
            return {}
        

        conn = psycopg2.connect(os.getenv('DATABASE_URL'))
        cur = conn.cursor()
        cur.execute('SELECT user_id, real_name, email, name FROM Users WHERE team_id = %s', (team_id,))
        rows = cur.fetchall()
        users = {
            row[0]: {
                "Slack Id": row[0],
                "real_name": row[1] if row[1] else "Unknown",
                "email": row[2] if row[2] else "unknown@example.com",
                "name": row[3] if row[3] else "Unknown"
            }
            for row in rows
        }
        cur.close()
        conn.close()
        return users
    except Exception as e:
        logger.error(f"Error fetching users from database: {e}")
        return {}

def get_workspace_owner_id(client, team_id):
    try:
        response = client.users_list()
        if response["ok"]:
            for user in response["members"]:
                if user.get("is_owner", False):
                    return user["id"]
        else:
            logger.error(f"Failed to fetch users_list for owner: {response['error']}")
    except Exception as e:
        logger.error(f"Error fetching users_list for owner: {e}")
    
    try:
        conn = psycopg2.connect(os.getenv('DATABASE_URL'))
        cur = conn.cursor()
        cur.execute('SELECT user_id FROM Users WHERE team_id = %s AND is_owner = TRUE', (team_id,))
        row = cur.fetchone()
        cur.close()
        conn.close()
        return row[0] if row else None
    except Exception as e:
        logger.error(f"Error fetching owner from database: {e}")
        return None

def get_channel_owner_id(client, channel_id):
    try:
        response = client.conversations_info(channel=channel_id)
        return response["channel"].get("creator")
    except SlackApiError as e:
        logger.error(f"Error fetching channel info: {e.response['error']}")
        return None

def get_team_id_from_owner_id(owner_id):
    conn = psycopg2.connect(os.getenv('DATABASE_URL'))
    cur = conn.cursor()
    cur.execute("SELECT workspace_id FROM Installations WHERE installation_data->>'user_id' = %s", (owner_id,))
    row = cur.fetchone()
    cur.close()
    conn.close()
    return row[0] if row else None

def get_owner_selected_calendar(client, team_id):
    owner_id = get_workspace_owner_id(client, team_id)
    if not owner_id:
        return None
    prefs = load_preferences(team_id, owner_id)
    return prefs.get("calendar_tool", "none")

def get_zoom_link(client, team_id):
    owner_id = get_workspace_owner_id(client, team_id)
    if not owner_id:
        return None
    prefs = load_preferences(team_id, owner_id)
    return prefs.get('zoom_config', {}).get('link')

def create_home_tab(client, team_id, user_id):
    logger.info(f"Creating home tab for user {user_id}, team {team_id}")
    workspace_owner_id = get_workspace_owner_id(client, team_id)
    if not workspace_owner_id:
        blocks = [
            {"type": "header", "text": {"type": "plain_text", "text": "🤖 Welcome to AI Assistant!", "emoji": True}},
            {"type": "section", "text": {"type": "mrkdwn", "text": "Unable to determine workspace owner. Please contact support."}}
        ]
        return {"type": "home", "blocks": blocks}
    is_owner = user_id == workspace_owner_id
    blocks = [
        {"type": "header", "text": {"type": "plain_text", "text": "🤖 Welcome to AI Assistant!", "emoji": True}}
    ]
    if not is_owner:
        blocks.extend([
            {"type": "section", "text": {"type": "mrkdwn", "text": "I help manage schedules and meetings! Please wait for the workspace owner to configure the settings."}},
            {"type": "section", "text": {"type": "mrkdwn", "text": "Only the workspace owner can configure the calendar and Zoom settings."}}
        ])
        return {"type": "home", "blocks": blocks}
    blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": "I help manage schedules and meetings! Your settings are below."}})
    blocks.append({"type": "divider"})
    prefs = load_preferences(team_id, workspace_owner_id)
    selected_provider = prefs.get("calendar_tool", "none")
    zoom_config = prefs.get("zoom_config", {"mode": "manual", "link": None})
    mode = zoom_config["mode"]
    calendar_token = load_token(team_id, workspace_owner_id, selected_provider) if selected_provider != "none" else None
    zoom_token = load_token(team_id, workspace_owner_id, "zoom") if mode == "automatic" else None
    zoom_token_expired = False
    if zoom_token and mode == "automatic":
        expires_at = zoom_token.get("expires_at", 0)
        current_time = time.time()
        zoom_token_expired = current_time >= expires_at
    calendar_provider_set = selected_provider != "none"
    calendar_configured = calendar_token is not None if calendar_provider_set else False
    zoom_configured = (zoom_token is not None and not zoom_token_expired) if mode == "automatic" else True
    if not calendar_provider_set or not calendar_configured or not zoom_configured:
        prompt_text = "To start using the app, please complete the following setups:"
        if not calendar_provider_set:
            prompt_text += "\n- Select a calendar provider."
        if calendar_provider_set and not calendar_configured:
            prompt_text += f"\n- Configure your {selected_provider.capitalize()} calendar."
        if mode == "automatic" and not zoom_configured:
            if zoom_token_expired:
                prompt_text += "\n- Your Zoom token has expired. Please refresh it."
            else:
                prompt_text += "\n- Authenticate with Zoom for automatic mode."
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": prompt_text}})
    blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": "*🗓️ Calendar Configuration*"}})
    blocks.append({
        "type": "section",
        "block_id": "calendar_provider_block",
        "text": {"type": "mrkdwn", "text": "Select your calendar provider:"},
        "accessory": {
            "type": "static_select",
            "action_id": "calendar_provider_dropdown",
            "placeholder": {"type": "plain_text", "text": "Select provider"},
            "options": [
                {"text": {"type": "plain_text", "text": "Select calendar"}, "value": "none"},
                {"text": {"type": "plain_text", "text": "Google Calendar"}, "value": "google"},
                {"text": {"type": "plain_text", "text": "Microsoft Calendar"}, "value": "microsoft"}
            ],
            "initial_option": {
                "text": {"type": "plain_text", "text": "Select calendar" if selected_provider == "none" else
                        "Google Calendar" if selected_provider == "google" else "Microsoft Calendar"},
                "value": selected_provider
            }
        }
    })
    if selected_provider == "none":
        blocks.append({"type": "context", "elements": [{"type": "mrkdwn", "text": "Please select a calendar provider to begin configuration."}]})
    elif not calendar_configured:
        blocks.append({"type": "context", "elements": [{"type": "mrkdwn", "text": f"Please configure your {selected_provider.capitalize()} calendar."}]})
    if selected_provider != "none":
        status = "⚠️ Not Configured" if not calendar_configured else (
            f":white_check_mark: Connected ({calendar_token.get('google_email', 'unknown')})" if selected_provider == "google" else (
                f":white_check_mark: Connected (expires: {datetime.fromtimestamp(int(calendar_token.get('expires_at', 0))).strftime('%Y-%m-%d %H:%M')})" if calendar_token and calendar_token.get('expires_at') else ":white_check_mark: Connected"
            )
        )
        blocks.extend([
            {
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {
                            "type": "plain_text",
                            "text": f"✨ Configure {selected_provider.capitalize()}" if not calendar_configured else f"✅ Reconfigure {selected_provider.capitalize()}",
                            "emoji": True
                        },
                        "action_id": "configure_gcal" if selected_provider == "google" else "configure_mscal"
                    }
                ]
            },
            {"type": "context", "elements": [{"type": "mrkdwn", "text": status}]}
        ])
    status = ("⌛ Token Expired" if zoom_token_expired else
              "⚠️ Not Configured" if mode == "automatic" and not zoom_configured else
              "✅ Configured")
    blocks.extend([
        {"type": "divider"},
        {"type": "section", "text": {"type": "mrkdwn", "text": f"*🔗 Zoom Configuration*\nCurrent mode: {mode}\n{status}"}},
        {
            "type": "actions",
            "elements": [
                {"type": "button", "text": {"type": "plain_text", "text": "Configure Zoom Settings", "emoji": True}, "action_id": "open_zoom_config_modal"}
            ]
        }
    ])
    if mode == "automatic":
        if not zoom_configured and not zoom_token_expired:
            blocks[-1]["elements"].append({
                "type": "button",
                "text": {"type": "plain_text", "text": "Authenticate with Zoom", "emoji": True},
                "action_id": "configure_zoom"
            })
        elif zoom_token_expired:
            blocks[-1]["elements"].append({
                "type": "button",
                "text": {"type": "plain_text", "text": "Refresh Zoom Token", "emoji": True},
                "action_id": "configure_zoom"
            })
    return {"type": "home", "blocks": blocks}

# Intent Classification
intent_prompt = ChatPromptTemplate.from_template("""
You are an intent classification assistant. Based on the user's message and the conversation history, determine the intent of the user's request. The possible intents are: "schedule meeting", "update event", "delete event", or "other". Provide only the intent as your response.
- By looking at the history if someone is confirming or denying the schedule , also categorize it as a "schedule meeting"
- If someone is asking about update the schedule then its "update event"
- If someone is asking about delete the schedule then its "delete event"                                                 
Conversation History:
{history}

User's Message:
{input}
""")
from prompt import calender_prompt, general_prompt
intent_chain = LLMChain(llm=llm, prompt=intent_prompt)
# intent_chain = LLMChain(llm=llm, prompt=intent_prompt)
# intent_chain = LLMChain(llm=llm, prompt=intent_prompt)

mentioned_users_prompt = ChatPromptTemplate.from_template("""
Given the following chat history, identify the Slack user IDs, Names and emails of the users who are mentioned. Mentions can be in the form of <@user_id> (e.g., <@U12345>) or by their names (e.g., "Alice" or "Alice Smith").
- Do not give 'Bob'<@{bob_id}> in mentions
- Exclude the {bob_id}.                                        
# See the history if there is a request for new meeting or request for new schedule just ignore the mentions in the old messages and consider the new mentions in the new request.
All users in the channel:
{user_information}
Format: Slack Id: U3234234 , Name: Alice , Email: alice@gmail.com (map slack ids to the names)
Chat history:
{chat_history}
# Only output the users which are mentioned not all the users from the user-information.
# Only see the latest message for mention information ignore previous ones.                                                        
Please output the user slack IDs of the mentioned users , their names and emails . If no users are mentioned, output "None".
CURRENT_INPUT: {current_input}                                                          
Example: [[SlackId1 , Name1 , Email@gmal.com], [SlackId2, Name2, Email@gmail.com]...]
""")
mentioned_users_chain = LLMChain(llm=llm, prompt=mentioned_users_prompt)

# Slack Event Handlers
@bolt_app.event("app_home_opened")
def handle_app_home_opened(event, client, context):
    user_id = event.get("user")
    team_id = context['team_id']
    if not user_id:
        return
    try:
        client.views_publish(user_id=user_id, view=create_home_tab(client, team_id, user_id))
    except Exception as e:
        logger.error(f"Error publishing home tab: {e}")

@bolt_app.action("calendar_provider_dropdown")
def handle_calendar_provider(ack, body, client, logger):
    ack()
    selected_provider = body["actions"][0]["selected_option"]["value"]
    user_id = body["user"]["id"]
    team_id = body["team"]["id"]
    owner_id = get_workspace_owner_id(client, team_id)
    if user_id != owner_id:
        client.chat_postMessage(channel=user_id, text="Only the workspace owner can configure the calendar.")
        return
    save_preference(team_id, owner_id, calendar_tool=selected_provider)
    client.views_publish(user_id=owner_id, view=create_home_tab(client, team_id, owner_id))
    if selected_provider != "none":
        client.chat_postMessage(channel=owner_id, text=f"Calendar provider updated to {selected_provider.capitalize()}.")
    else:
        client.chat_postMessage(channel=owner_id, text="Calendar provider reset.")
    logger.info(f"Calendar provider updated to {selected_provider} for owner {owner_id}")

@bolt_app.action("configure_gcal")
def handle_gcal_config(ack, body, client, logger):
    ack()
    user_id = body["user"]["id"]
    team_id = body["team"]["id"]
    owner_id = get_workspace_owner_id(client, team_id)
    if user_id != owner_id:
        client.chat_postMessage(channel=user_id, text="Only the workspace owner can configure the calendar.")
        return
    state = state_manager.create_state(owner_id)
    store_in_session(owner_id, "gcal_state", state)
    client_config = {
        "web": {
            "client_id": os.getenv("GOOGLE_CLIENT_ID"),
            "client_secret": os.getenv("GOOGLE_CLIENT_SECRET"),
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
            "redirect_uris": [OAUTH_REDIRECT_URI]
        }
    }
    flow = Flow.from_client_config(client_config, scopes=SCOPES, redirect_uri=OAUTH_REDIRECT_URI)
    auth_url, _ = flow.authorization_url(
        access_type='offline',
        prompt='consent',
        include_granted_scopes='true',
        state=state
    )
    try:
        client.views_open(
            trigger_id=body["trigger_id"],
            view={
                "type": "modal",
                "title": {"type": "plain_text", "text": "Google Calendar Auth"},
                "close": {"type": "plain_text", "text": "Cancel"},
                "blocks": [
                    {"type": "section", "text": {"type": "mrkdwn", "text": "Click below to connect Google Calendar:"}},
                    {"type": "actions", "elements": [{"type": "button", "text": {"type": "plain_text", "text": "Connect Google Calendar"}, "url": auth_url, "action_id": "launch_auth"}]}
                ]
            }
        )
    except Exception as e:
        logger.error(f"Error opening modal: {e}")

@bolt_app.action("configure_mscal")
def handle_mscal_config(ack, body, client, logger):
    ack()
    user_id = body["user"]["id"]
    team_id = body["team"]["id"]
    owner_id = get_workspace_owner_id(client, team_id)
    if user_id != owner_id:
        client.chat_postMessage(channel=user_id, text="Only the workspace owner can configure the calendar.")
        return
    msal_app = ConfidentialClientApplication(MICROSOFT_CLIENT_ID, authority=MICROSOFT_AUTHORITY, client_credential=MICROSOFT_CLIENT_SECRET)
    state = state_manager.create_state(owner_id)
    auth_url = msal_app.get_authorization_request_url(scopes=MICROSOFT_SCOPES, redirect_uri=MICROSOFT_REDIRECT_URI, state=state)
    try:
        client.views_open(
            trigger_id=body["trigger_id"],
            view={
                "type": "modal",
                "title": {"type": "plain_text", "text": "Microsoft Calendar Auth"},
                "close": {"type": "plain_text", "text": "Close"},
                "blocks": [
                    {"type": "section", "text": {"type": "mrkdwn", "text": "Click below to authenticate with Microsoft:"}},
                    {"type": "actions", "elements": [{"type": "button", "text": {"type": "plain_text", "text": "Connect Microsoft Calendar"}, "url": auth_url, "action_id": "ms_auth_button"}]}
                ]
            }
        )
    except Exception as e:
        logger.error(f"Error opening Microsoft auth modal: {e}")

@bolt_app.event("app_mention")
def handle_mentions(event, say, client, context):
    if event_deduplicator.is_duplicate_event(event):
        logger.info("Duplicate event detected, skipping processing")
        return
    if event.get("bot_id"):
        logger.info("Ignoring message from bot")
        return
    user_id = event.get("user")
    channel_id = event.get("channel")
    
    text = event.get("text", "").strip()
    thread_ts = event.get("thread_ts")
    team_id = context['team_id']
    calendar_tool = get_owner_selected_calendar(client, team_id)
    if not calendar_tool or calendar_tool == "none":
        say("The workspace owner has not configured a calendar yet.", thread_ts=thread_ts)
        return
    installation = installation_store.find_installation(team_id=team_id)
    if not installation or not installation.bot_user_id:
        logger.error(f"No bot_user_id found for team {team_id}")
        say("Error: Could not determine bot user ID.", thread_ts=thread_ts)
        return
    bot_user_id = installation.bot_user_id
    mention = f"<@{bot_user_id}>"
    mentions = list(set(re.findall(r'<@(\w+)>', text)))
    if bot_user_id in mentions:
        mentions.remove(bot_user_id)
    text = text.replace(mention, "").strip()
    workspace_owner_id = get_workspace_owner_id(client, team_id)
    timezone = get_user_timezone(client, user_id)
    zoom_link = get_zoom_link(client, team_id)
    zoom_mode = load_preferences(team_id, workspace_owner_id).get("zoom_config", {}).get("mode", "manual")
    channel_history = client.conversations_history(channel=channel_id, limit=2).get("messages", [])
    channel_history = format_channel_history(channel_history)
    intent = intent_chain.run({
    "history": channel_history,
    "input": text
})
    relevant_user_ids = get_relevant_user_ids(client, channel_id)
    all_users = get_all_users(client, channel_id,team_id)
    relevant_users = {uid: all_users.get(uid, {"real_name": "Unknown", "email": "unknown@example.com", "name": "Unknown"})
                      for uid in relevant_user_ids}
    user_information = "\n".join([f"{uid}: Name={info['real_name']}, Email={info['email']}, Slack Name={info['name']}"
                                  for uid, info in relevant_users.items() if uid != bot_user_id])
    mentioned_users_output = mentioned_users_chain.run({"user_information": user_information, "chat_history": channel_history, "current_input": text, 'bob_id': bot_user_id})
    import pytz
    owner_timezone = get_user_timezone(client, workspace_owner_id, default_tz="America/Los_Angeles")
    pst = pytz.timezone(owner_timezone)
    current_time_pst = datetime.now(pst)
    formatted_time = current_time_pst.strftime("%Y-%m-%d | %A | %I:%M %p | %Z")
    from all_tools import GoogleCalendarEvents, MicrosoftListCalendarEvents
    if calendar_tool == "google":
        calendar_events = GoogleCalendarEvents()._run(team_id, workspace_owner_id)
        formatted_cal_output = format_calendar_events(calendar_events, owner_timezone)
        # print(f"Formatted Calendars: {formatted_cal_output}")
        
        schedule_indices = [0, 4, 6, 12] if zoom_mode == "manual" else [0, 1, 4, 6, 12]
        update_tools = [tools[i] for i in [0, 7, 12]]
        delete_tools = [tools[i] for i in [0, 8, 12]]
        schedule_tools = [tools[i] for i in schedule_indices]
    elif calendar_tool == "microsoft":
        calendar_events = MicrosoftListCalendarEvents()._run(team_id, workspace_owner_id)
        schedule_indices = [0, 4, 6, 12] if zoom_mode == "manual" else [0, 1, 4, 6, 12]
        update_tools = [tools[i] for i in [0, 10, 12]]
        delete_tools = [tools[i] for i in [0, 11, 12]]
        schedule_tools = [tools[i] for i in schedule_indices]
    else:
        say("Invalid calendar tool configured.", thread_ts=thread_ts)
        return
    calendar_formatting_chain = LLMChain(llm=llm, prompt=calender_prompt)
    output = calendar_formatting_chain.run({'input': formatted_cal_output, 'admin_id': workspace_owner_id, 'date_time': formatted_time, 'timezone':timezone})
    mentions_history = get_mentions_from_history(client, channel_id, bot_user_id=bot_user_id, limit=5)
    print(f"Calendar_events: {mentions_history}")

    agent_input = {
        'input': f"Here is the input by user: {text} and do not mention <@{bot_user_id}> even tho mentioned in history",
        'event_details': str(event),
        'target_user_id': user_id,
        'timezone': timezone,
        'user_id': user_id,
        'admin': workspace_owner_id,
        'zoom_link': zoom_link,
        'zoom_mode': zoom_mode,
        'channel_history': channel_history,
        'user_information': user_information,
        'calendar_tool': calendar_tool,
        'date_time': formatted_time,
        'formatted_calendar': output,
        'team_id': team_id,
        'raw_events':formatted_cal_output,
        'calendar_events':formatted_cal_output, 
        "current_date":formatted_time
    }
    schedule_group_exec = create_schedule_channel_agent(schedule_tools)
    update_group_exec = create_update_group_agent(update_tools)
    delete_exec = create_delete_agent(delete_tools)
    print(f"INTENT: {intent}")
    if intent == "not authorized":
        say(f"<@{user_id}> You are not authorized to schedule meetings. I've notified the workspace owner.", thread_ts=thread_ts)
        admin_dm = client.conversations_open(users=workspace_owner_id)
        prompt = ChatPromptTemplate.from_template("""
        Hi <@{workspace_owner_id}>, <@{user_id}> attempted to schedule a meeting: {text}
        Please review and proceed if needed.
        """)
        response = LLMChain(llm=llm, prompt=prompt)
        client.chat_postMessage(
            channel=admin_dm["channel"]["id"],
            text=response.run({'text': text, 'workspace_owner_id': workspace_owner_id, 'user_id': user_id})
        )
        return
    if intent == "schedule meeting":
        group_agent_input = agent_input.copy()
        group_agent_input['mentioned_users'] = mentions_history
        response = schedule_group_exec.invoke(group_agent_input)
        say(response['output'])
    elif intent == "update event":
        group_agent_input = agent_input.copy()
        group_agent_input['mentioned_users'] = mentions_history
        response = update_group_exec.invoke(group_agent_input)
        say(response['output'])
    elif intent == "delete event":
        response = delete_exec.invoke(agent_input)
        say(response['output'])
    elif intent == "other":
        response = llm.predict(general_prompt.format(input=text, channel_history=channel_history))
        say(response)
    else:
        say("I'm not sure how to handle that request.")

def format_channel_history(raw_history):
    cleaned_history = []
    for msg in raw_history:
        if 'bot_id' in msg and 'Calendar provider updated' in msg.get('text', ''):
            continue
        sender = msg.get('user', 'Unknown') if 'bot_id' not in msg else msg.get('bot_profile', {}).get('name', 'Bot')
        message_text = msg.get('text', '').strip()
        timestamp = float(msg.get('ts', 0))
        readable_time = datetime.fromtimestamp(timestamp).strftime('%Y-%m-%d %I:%M %p')
        user_id = msg.get('user', 'N/A')
        team_id = msg.get('team', 'N/A')
        cleaned_history.append({
            'message': message_text,
            'from': sender,
            'timestamp': readable_time,
            'user_team': f"{user_id}/{team_id}"
        })
    formatted_output = ""
    for i, entry in enumerate(cleaned_history, 1):
        formatted_output += f"Message {i}: {entry['message']}\nFrom: {entry['from']}\nTimestamp: {entry['timestamp']}\nUserId/TeamId: {entry['user_team']}\n\n"
    return formatted_output.strip()

def get_relevant_user_ids(client, channel_id):
    try:
        members = []
        cursor = None
        while True:
            response = client.conversations_members(channel=channel_id, limit=10, cursor=cursor)
            if not response["ok"]:
                logger.error(f"Failed to get members for channel {channel_id}: {response['error']}")
                break
            members.extend(response["members"])
            cursor = response.get("response_metadata", {}).get("next_cursor")
            if not cursor:
                break
        return members
    except SlackApiError as e:
        logger.error(f"Error getting conversation members: {e}")
        return []

calendar_formatting_chain = LLMChain(llm=llm, prompt=calender_prompt)

@bolt_app.event("message")
def handle_messages(body, say, client, context):
    if event_deduplicator.is_duplicate_event(body):
        logger.info("Duplicate event detected, skipping processing")
        return
    event = body.get("event", {})
    if event.get("bot_id"):
        logger.info("Ignoring message from bot")
        return
    
    user_id = event.get("user")
    text = event.get("text", "").strip()
    channel_id = event.get("channel")
    thread_ts = event.get("thread_ts")
    team_id = context['team_id']
    calendar_tool = get_owner_selected_calendar(client, team_id)
    channel_info = client.conversations_info(channel=channel_id)
    channel = channel_info["channel"]
    installation = installation_store.find_installation(team_id=team_id)
    if not installation or not installation.bot_user_id:
        logger.error(f"No bot_user_id found for team {team_id}")
        say("Error: Could not determine bot user ID.", thread_ts=thread_ts)
        return
    bot_user_id = installation.bot_user_id
    if not channel.get("is_im") and f"<@{bot_user_id}>" in text:
        logger.info("Message contains bot mention in non-IM channel, skipping in message handler")
        return
    if not channel.get("is_im") and "thread_ts" not in event:
        logger.info("Message contains bot mention in non-IM channel (not a thread), skipping in message handler")
    if not calendar_tool or calendar_tool == "none":
        say("The workspace owner has not configured a calendar yet.", thread_ts=thread_ts)
        return
    if f"<@{bot_user_id}>" in text and not (channel.get("is_im") or channel.get("is_mpim")):
        logger.info("Message contains bot mention in non-DM channel, skipping in message handler")
        return
    workspace_owner_id = get_workspace_owner_id(client, team_id)
    is_owner = user_id == workspace_owner_id
    timezone = get_user_timezone(client, user_id)
    zoom_link = get_zoom_link(client, team_id)
    zoom_mode = load_preferences(team_id, workspace_owner_id).get("zoom_config", {}).get("mode", "manual")
    channel_history = client.conversations_history(channel=channel_id, limit=2).get("messages", [])
    channel_history = format_channel_history(channel_history)
    intent = intent_chain.run({
    "history": channel_history,
    "input": text,
})
    if intent == "schedule meeting" and not is_owner and not channel.get("is_group") and not channel.get("is_mpim") and 'thread_ts' not in event:
        admin_dm = client.conversations_open(users=workspace_owner_id)
        prompt = ChatPromptTemplate.from_template("""
        You have this text: {text} and your job is to mention @{workspace_owner_id} and say following in 2 scenarios:
        if message history confirms about scheduling meeting then format below text and return only that response with no other explanation
        "Hi {workspace_owner_id} you wanted to schedule a meeting with {user_id}, {user_id} has proposed these slots [Time slots from the text] , Are you comfortable with these slots ? Confirm so I can fix the meeting."
        else:
            Format the text : {text}
        MESSAGE HISTORY: {channel_history}
        """)
        response = LLMChain(llm=llm, prompt=prompt)
        client.chat_postMessage(channel=admin_dm["channel"]["id"],
                                text=response.run({'text': text, 'workspace_owner_id': workspace_owner_id, 'user_id': user_id, 'channel_history': channel_history}))
        say(f"<@{user_id}> I've notified the workspace owner about your meeting request.", thread_ts=thread_ts)
        return
    mentions = list(set(re.findall(r'<@(\w+)>', text)))
    if bot_user_id in mentions:
        mentions.remove(bot_user_id)
    import pytz
    owner_timezone = get_user_timezone(client, workspace_owner_id, default_tz="America/Los_Angeles")
    pst = pytz.timezone(owner_timezone)
    current_time_pst = datetime.now(pst)
    formatted_time = current_time_pst.strftime("%Y-%m-%d | %A | %I:%M %p | %Z")
    from all_tools import MicrosoftListCalendarEvents, GoogleCalendarEvents
    if calendar_tool == "google":
        schedule_indices = [0, 4, 6, 12] if zoom_mode == "manual" else [0, 1, 4, 6, 12]
        
        schedule_tools = [tools[i] for i in schedule_indices]
        update_tools = [tools[i] for i in [0, 7, 12]]
        delete_tools = [tools[i] for i in [0, 8, 12]]
        calendar_events = GoogleCalendarEvents()._run(team_id, workspace_owner_id)
        formatted_cal_output = format_calendar_events(calendar_events, owner_timezone)
        # print(f"Formatted Calendars: {formatted_cal_output}")
        output = calendar_formatting_chain.run({'input': formatted_cal_output, 'admin_id': workspace_owner_id, 'date_time': formatted_time, 'timezone':timezone})
    elif calendar_tool == "microsoft":
        schedule_indices = [0, 4, 6, 12] if zoom_mode == "manual" else [0, 1, 4, 6, 12]
        
        schedule_tools = [tools[i] for i in schedule_indices]
        update_tools = [tools[i] for i in [0, 10, 12]]
        delete_tools = [tools[i] for i in [0, 11, 12]]
        calendar_events = MicrosoftListCalendarEvents()._run(team_id, workspace_owner_id)
        output = calendar_formatting_chain.run({'input':calendar_events, 'admin_id': workspace_owner_id, 'date_time': formatted_time, 'timezone':timezone})
    else:
        say("Invalid calendar tool configured.", thread_ts=thread_ts)
        return
    relevant_user_ids = get_relevant_user_ids(client, channel_id)
    all_users = get_all_users(client, channel_id,team_id)
    relevant_users = {uid: all_users.get(uid, {"real_name": "Unknown", "email": "unknown@example.com", "name": "Unknown"})
                      for uid in relevant_user_ids}
    user_information = "\n".join([f"{uid}: Name={info['real_name']}, Email={info['email']}, Slack Name={info['name']}"
                                  for uid, info in relevant_users.items() if uid != bot_user_id])
    mentioned_users_output = mentioned_users_chain.run({"user_information": user_information, "chat_history": channel_history, "current_input": text, 'bob_id': bot_user_id})
    schedule_exec = create_schedule_agent(schedule_tools)
    update_exec = create_update_agent(update_tools)
    delete_exec = create_delete_agent(delete_tools)
    schedule_group_exec = create_schedule_group_agent(schedule_tools)
    update_group_exec = create_update_group_agent(update_tools)
    channel_type = channel.get("is_group", False) or channel.get("is_mpim", False)
    mentions_history = get_mentions_from_history(client, channel_id, bot_user_id=bot_user_id, limit=5)
    print(f"Calendar_events: {mentions_history}")
    agent_input = {
        'input': f"Here is the input by user: {text} and do not mention <@{bot_user_id}> even tho mentioned in history",
        'event_details': str(event),
        'target_user_id': user_id,
        'timezone': timezone,
        'user_id': user_id,
        'admin': workspace_owner_id,
        'zoom_link': zoom_link,
        'zoom_mode': zoom_mode,
        'channel_history': channel_history,
        'user_information': user_information,
        'calendar_tool': calendar_tool,
        'date_time': formatted_time,
        'formatted_calendar': output,
        'team_id': team_id,
        'raw_events':formatted_cal_output,
        'calendar_events':formatted_cal_output, 
        "current_date":formatted_time
    }
    if intent == "not authorized":
        say(f"<@{user_id}> You are not authorized to schedule meetings. I've notified the workspace owner.", thread_ts=thread_ts)
        admin_dm = client.conversations_open(users=workspace_owner_id)
        prompt = ChatPromptTemplate.from_template("""
        Hi <@{workspace_owner_id}>, <@{user_id}> attempted to schedule a meeting: {text}
        Please review and proceed if needed.
        """)
        response = LLMChain(llm=llm, prompt=prompt)
        client.chat_postMessage(
            channel=admin_dm["channel"]["id"],
            text=response.run({'text': text, 'workspace_owner_id': workspace_owner_id, 'user_id': user_id})
        )
        return
    elif intent == "schedule meeting":
        if not channel_type and len(mentions) >= 1:
            mentions.append(user_id)
            dm_channel_id = open_group_dm(client, mentions)
            if dm_channel_id:
                group_agent_input = agent_input.copy()
                group_agent_input['mentioned_users'] = mentions_history
                group_agent_input['channel_history'] = channel_history
                group_agent_input['formatted_calendar'] = output
                response = schedule_group_exec.invoke(group_agent_input)
                client.chat_postMessage(channel=dm_channel_id, text=f"Group conversation started by <@{user_id}>\n\n{response['output']}")
            else:
                say(f"Sorry, I couldn't create the group conversation", thread_ts=thread_ts)
        else:
            if channel_type or 'thread_ts' in event:
                group_agent_input = agent_input.copy()
                if 'thread_ts' in event:
                    schedule_group_exec = create_schedule_channel_agent(schedule_tools)
                    history_response = client.conversations_replies(channel=channel_id, ts=thread_ts, limit=2)
                    channel_history = format_channel_history(history_response.get("messages", []))
                else:
                    channel_history = format_channel_history(client.conversations_history(channel=channel_id, limit=2).get("messages", []))
                group_agent_input['mentioned_users'] = mentions_history
                group_agent_input['channel_history'] = channel_history
                group_agent_input['formatted_calendar'] = output
                response = schedule_group_exec.invoke(group_agent_input)
                say(response['output'], thread_ts=thread_ts)
                return
            response = schedule_exec.invoke(agent_input)
            say(response['output'], thread_ts=thread_ts)
    elif intent == "update event":
        agent_input['current_date'] = formatted_time
        agent_input['calendar_events'] = MicrosoftListCalendarEvents()._run(team_id, workspace_owner_id) if calendar_tool == "microsoft" else GoogleCalendarEvents()._run(team_id, workspace_owner_id)
        if channel_type or 'thread_ts' in event:
            group_agent_input = agent_input.copy()
            channel_history = format_channel_history(client.conversations_history(channel=channel_id, limit=2).get("messages", []))
            group_agent_input['mentioned_users'] = mentions_history
            group_agent_input['channel_history'] = channel_history
            group_agent_input['formatted_calendar'] = output
            response = update_group_exec.invoke(group_agent_input)
            say(response['output'], thread_ts=thread_ts)
            return
        response = update_exec.invoke(agent_input)
        say(response['output'], thread_ts=thread_ts)
    elif intent == "delete event":
        agent_input['current_date'] = formatted_time
        agent_input['calendar_events'] = MicrosoftListCalendarEvents()._run(team_id, workspace_owner_id) if calendar_tool == "microsoft" else GoogleCalendarEvents()._run(team_id, workspace_owner_id)
        response = delete_exec.invoke(agent_input)
        say(response['output'], thread_ts=thread_ts)
    elif intent == "other":
        response = llm.predict(general_prompt.format(input=text, channel_history=channel_history))
        say(response, thread_ts=thread_ts)
    else:
        say("I'm not sure how to handle that request.", thread_ts=thread_ts)

@bolt_app.event("subteam_updated")
def handle_subteam_updated_events(body, logger, context):
    event = body.get("event", {})
    subteam = event.get("subteam", {})
    subteam_id = subteam.get("id")
    team_id = context.get("team_id")
    current_users = set(subteam.get("users", []))
    date_delete = subteam.get("date_delete", 0)

    logger.info(f"Subteam updated: {subteam_id}, users: {current_users}")

    if date_delete > 0:
        logger.info(f"Subteam {subteam_id} deactivated")
        return

    try:
        conn = psycopg2.connect(os.getenv('DATABASE_URL'))
        cur = conn.cursor()
        cur.execute("SELECT user_id FROM SubteamMembers WHERE subteam_id = %s AND team_id = %s", 
                   (subteam_id, team_id))
        previous_users = set(row[0] for row in cur.fetchall())
        removed_users = previous_users - current_users
        for user_id in removed_users:
            cur.execute("DELETE FROM SubteamMembers WHERE subteam_id = %s AND user_id = %s AND team_id = %s", 
                       (subteam_id, user_id, team_id))
            logger.info(f"Removed user {user_id} from subteam {subteam_id}")
        for user_id in current_users:
            cur.execute("""
                INSERT INTO SubteamMembers (subteam_id, user_id, team_id, last_updated)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (subteam_id, user_id, team_id) DO UPDATE SET last_updated = %s
            """, (subteam_id, user_id, team_id, datetime.now(), datetime.now()))
        conn.commit()
    except psycopg2.Error as e:
        logger.error(f"Database error: {e}")
    finally:
        cur.close()
        conn.close()

@bolt_app.event("team_join")
def handle_team_join(event, client, context, logger):
    try:
        user_info = event['user']
        team_id = context.team_id
        try:
            team_info = client.team_info()
            workspace_name = team_info['team']['name']
        except SlackApiError as e:
            logger.error(f"Error fetching team info: {e.response['error']}")
            workspace_name = "Unknown Workspace"
        user_id = user_info['id']
        real_name = user_info.get('real_name', 'Unknown')
        profile = user_info.get('profile', {})
        email = profile.get('email', f"{user_info.get('name', 'user')}@gmail.com")
        name = user_info.get('name', '')
        is_owner = user_info.get('is_owner', False)
        conn = psycopg2.connect(os.getenv('DATABASE_URL'))
        cur = conn.cursor()
        cur.execute('''
            INSERT INTO Users (team_id, user_id, workspace_name, real_name, email, name, is_owner, last_updated)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (team_id, user_id) DO UPDATE SET
                workspace_name = EXCLUDED.workspace_name,
                real_name = EXCLUDED.real_name,
                email = EXCLUDED.email,
                name = EXCLUDED.name,
                is_owner = EXCLUDED.is_owner,
                last_updated = EXCLUDED.last_updated
        ''', (team_id, user_id, workspace_name, real_name, email, name, is_owner, datetime.now()))
        conn.commit()
        cur.close()
        conn.close()
        logger.info(f"Processed team_join event for user {user_id} in team {team_id}")
    except KeyError as e:
        logger.error(f"Missing key in event data: {e}")
    except psycopg2.Error as e:
        logger.error(f"Database error: {e}")
    except Exception as e:
        logger.error(f"Unexpected error handling team_join: {e}")

def open_group_dm(client, users):
    try:
        response = client.conversations_open(users=",".join(users))
        return response["channel"]["id"] if response["ok"] else None
    except SlackApiError as e:
        logger.error(f"Error opening group DM: {e.response['error']}")
        return None

# Flask Routes
@app.route("/slack/events", methods=["POST"])
def slack_events():
    return slack_handler.handle(request)

@app.route("/slack/install", methods=["GET"])
def slack_install():
    return slack_handler.handle(request)

@app.route("/slack/oauth_redirect", methods=["GET"])
def slack_oauth_redirect():
    return slack_handler.handle(request)

@app.route("/oauth2callback")
def oauth2callback():
    state = request.args.get('state', '')
    user_id = state_manager.validate_and_consume_state(state)
    stored_state = get_from_session(user_id, "gcal_state") if user_id else None
    if not user_id or stored_state != state:
        return "Invalid state", 400
    team_id = get_team_id_from_owner_id(user_id)
    if not team_id:
        return "Workspace not found", 404
    client = get_client_for_team(team_id)
    if not client:
        return "Client not found", 500
    client_config = {
        "web": {
            "client_id": os.getenv("GOOGLE_CLIENT_ID"),
            "client_secret": os.getenv("GOOGLE_CLIENT_SECRET"),
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
            "redirect_uris": [OAUTH_REDIRECT_URI]
        }
    }
    flow = Flow.from_client_config(client_config, scopes=SCOPES, redirect_uri=OAUTH_REDIRECT_URI)
    flow.fetch_token(authorization_response=request.url)
    credentials = flow.credentials
    service = build('oauth2', 'v2', credentials=credentials)
    user_info = service.userinfo().get().execute()
    google_email = user_info.get('email', 'unknown@example.com')
    token_data = json.loads(credentials.to_json())
    token_data['google_email'] = google_email
    save_token(team_id, user_id, 'google', token_data)
    client.views_publish(user_id=user_id, view=create_home_tab(client, team_id, user_id))
    return "Google Calendar connected successfully! You can close this window."

@bolt_app.action("launch_auth")
def handle_launch_auth(ack, body, logger):
    ack()
    logger.info(f"Launch auth triggered by user {body['user']['id']}")

@app.route("/microsoft_callback")
def microsoft_callback():
    code = request.args.get("code")
    state = request.args.get("state")
    if not code or not state:
        return "Missing parameters", 400
    user_id = state_manager.validate_and_consume_state(state)
    if not user_id:
        return "Invalid or expired state parameter", 403
    team_id = get_team_id_from_owner_id(user_id)
    if not team_id:
        return "Workspace not found", 404
    client = get_client_for_team(team_id)
    if not client:
        return "Client not found", 500
    if user_id != get_workspace_owner_id(client, team_id):
        return "Unauthorized", 403
    msal_app = ConfidentialClientApplication(MICROSOFT_CLIENT_ID, authority=MICROSOFT_AUTHORITY, client_credential=MICROSOFT_CLIENT_SECRET)
    result = msal_app.acquire_token_by_authorization_code(code, scopes=MICROSOFT_SCOPES, redirect_uri=MICROSOFT_REDIRECT_URI)
    if "access_token" not in result:
        return "Authentication failed", 400
    token_data = {"access_token": result["access_token"], "refresh_token": result.get("refresh_token", ""), "expires_at": result["expires_in"] + time.time()}
    save_token(team_id, user_id, 'microsoft', token_data)
    client.views_publish(user_id=user_id, view=create_home_tab(client, team_id, user_id))
    return "Microsoft Calendar connected successfully! You can close this window."

@app.route("/zoom_callback")
def zoom_callback():
    code = request.args.get("code")
    state = request.args.get("state")
    user_id = state_manager.validate_and_consume_state(state)
    if not user_id:
        return "Invalid or expired state", 403
    team_id = get_team_id_from_owner_id(user_id)
    if not team_id:
        return "Workspace not found", 404
    client = get_client_for_team(team_id)
    if not client:
        return "Client not found", 500
    params = {"grant_type": "authorization_code", "code": code, "redirect_uri": ZOOM_REDIRECT_URI}
    try:
        response = requests.post(ZOOM_TOKEN_API, params=params, auth=(CLIENT_ID, CLIENT_SECRET))
    except Exception as e:
        return jsonify({"error": f"Token request failed: {str(e)}"}), 500
    if response.status_code == 200:
        token_data = response.json()
        token_data["expires_at"] = time.time() + token_data["expires_in"]
        save_token(team_id, user_id, 'zoom', token_data)
        client.views_publish(user_id=user_id, view=create_home_tab(client, team_id, user_id))
        return "Zoom connected successfully! You can close this window."
    return "Failed to retrieve token", 400

@bolt_app.action("open_zoom_config_modal")
def handle_open_zoom_config_modal(ack, body, client, logger):
    ack()
    user_id = body["user"]["id"]
    team_id = body["team"]["id"]
    owner_id = get_workspace_owner_id(client, team_id)
    if user_id != owner_id:
        client.chat_postMessage(channel=user_id, text="Only the workspace owner can configure Zoom.")
        return
    prefs = load_preferences(team_id, user_id)
    zoom_config = prefs.get("zoom_config", {"mode": "manual", "link": None})
    mode = zoom_config["mode"]
    link = zoom_config.get("link", "")
    try:
        client.views_open(
            trigger_id=body["trigger_id"],
            view={
                "type": "modal",
                "callback_id": "zoom_config_submit",
                "title": {"type": "plain_text", "text": "Configure Zoom"},
                "submit": {"type": "plain_text", "text": "Save"},
                "close": {"type": "plain_text", "text": "Cancel"},
                "blocks": [
                    {
                        "type": "input",
                        "block_id": "zoom_mode",
                        "label": {"type": "plain_text", "text": "Zoom Mode"},
                        "element": {
                            "type": "static_select",
                            "action_id": "mode_select",
                            "placeholder": {"type": "plain_text", "text": "Select mode"},
                            "options": [
                                {"text": {"type": "plain_text", "text": "Automatic"}, "value": "automatic"},
                                {"text": {"type": "plain_text", "text": "Manual"}, "value": "manual"}
                            ],
                            "initial_option": {"text": {"type": "plain_text", "text": "Automatic" if mode == "automatic" else "Manual"}, "value": mode} if mode else None
                        }
                    },
                    {
                        "type": "input",
                        "block_id": "zoom_link",
                        "label": {"type": "plain_text", "text": "Manual Zoom Link"},
                        "element": {
                            "type": "plain_text_input",
                            "action_id": "link_input",
                            "placeholder": {"type": "plain_text", "text": "Enter Zoom link"},
                            "initial_value": link if isinstance(link, str) else ""
                        },
                        "optional": True
                    }
                ]
            }
        )
    except Exception as e:
        logger.error(f"Error opening Zoom config modal: {e}")

@bolt_app.action("configure_zoom")
def handle_zoom_config(ack, body, client, logger):
    ack()
    user_id = body["user"]["id"]
    team_id = body["team"]["id"]
    owner_id = get_workspace_owner_id(client, team_id)
    if user_id != owner_id:
        client.chat_postMessage(channel=user_id, text="Only the workspace owner can configure Zoom.")
        return
    zoom_token = load_token(team_id, owner_id, "zoom")
    is_refresh = zoom_token is not None
    state = state_manager.create_state(owner_id)
    auth_url = f"{ZOOM_OAUTH_AUTHORIZE_API}?response_type=code&client_id={CLIENT_ID}&redirect_uri={quote_plus(ZOOM_REDIRECT_URI)}&state={state}"
    modal_title = "Refresh Zoom Token" if is_refresh else "Authenticate with Zoom"
    button_text = "Refresh Zoom Token" if is_refresh else "Authenticate with Zoom"
    try:
        client.views_open(
            trigger_id=body["trigger_id"],
            view={
                "type": "modal",
                "title": {"type": "plain_text", "text": modal_title},
                "close": {"type": "plain_text", "text": "Cancel"},
                "blocks": [
                    {
                        "type": "section",
                        "text": {"type": "mrkdwn", "text": f"Click below to {button_text.lower()}:"}
                    },
                    {
                        "type": "actions",
                        "elements": [
                            {
                                "type": "button",
                                "text": {"type": "plain_text", "text": button_text},
                                "url": auth_url,
                                "action_id": "launch_zoom_auth"
                            }
                        ]
                    }
                ]
            }
        )
    except Exception as e:
        logger.error(f"Error opening Zoom auth modal: {e}")

@bolt_app.view("zoom_config_submit")
def handle_zoom_config_submit(ack, body, client, logger):
    ack()
    user_id = body["user"]["id"]
    team_id = body["team"]["id"]
    owner_id = get_workspace_owner_id(client, team_id)
    if user_id != owner_id:
        return
    values = body["view"]["state"]["values"]
    mode = values["zoom_mode"]["mode_select"]["selected_option"]["value"]
    link = values["zoom_link"]["link_input"]["value"] if "zoom_link" in values and "link_input" in values["zoom_link"] else None
    zoom_config = {"mode": mode, "link": link if mode == "manual" else None}
    save_preference(team_id, user_id, zoom_config=zoom_config)
    client.views_publish(user_id=user_id, view=create_home_tab(client, team_id, user_id))

@bolt_app.action("launch_zoom_auth")
def handle_some_action(ack, body, logger):
    ack()

scheduler = BackgroundScheduler()
scheduler.add_job(state_manager.cleanup_expired_states, 'interval', minutes=5)
scheduler.start()

@app.route('/')
def home():
    return "Hello"

port = int(os.getenv('PORT', 10000))
if __name__ == '__main__':
    app.run(port=port)
