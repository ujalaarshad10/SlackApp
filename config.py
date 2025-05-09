from slack_sdk.errors import SlackApiError
import os
from dotenv import load_dotenv
from slack_sdk import WebClient
import sqlite3
import json
import psycopg2
import logging
from datetime import datetime
# Load environment variables
load_dotenv()

# Slack credentials
SLACK_BOT_TOKEN = os.environ["SLACK_BOT_TOKEN"]

# Initialize the Slack client
client = WebClient(token=SLACK_BOT_TOKEN)
logger = logging.getLogger(__name__)
def load_preferences(team_id, user_id):
    with preferences_cache_lock:
        if (team_id, user_id) in preferences_cache:
            return preferences_cache[(team_id, user_id)]
    try:
        conn = psycopg2.connect(os.getenv('DATABASE_URL'))
        cur = conn.cursor()
        cur.execute('SELECT zoom_config, calendar_tool FROM Preferences WHERE team_id = %s AND user_id = %s', (team_id, user_id))
        row = cur.fetchone()
        if row:
            zoom_config, calendar_tool = row
            # For jsonb, zoom_config is already a dict; no json.loads needed
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
    with preferences_cache_lock:
        preferences_cache[(team_id, user_id)] = preferences
    return preferences
from threading import Lock
user_cache = {}
preferences_cache = {}
preferences_cache_lock = Lock()
user_cache_lock = Lock()  # Example threading lock for cache

owner_id_cache = {}
owner_id_lock = Lock()
def initialize_workspace_cache(client, team_id):
    conn = psycopg2.connect(os.getenv('DATABASE_URL'))
    cur = conn.cursor()
    cur.execute('SELECT MAX(last_updated) FROM Users WHERE team_id = %s', (team_id,))
    last_updated_row = cur.fetchone()
    last_updated = last_updated_row[0] if last_updated_row and last_updated_row[0] else None
    
    # Check if cache is fresh (e.g., less than 24 hours old)
    if last_updated and (datetime.now() - last_updated).total_seconds() < 86400:
        cur.execute('SELECT user_id, real_name, email, name, is_owner, workspace_name FROM Users WHERE team_id = %s', (team_id,))
        rows = cur.fetchall()
        new_cache = {row[0]: {"real_name": row[1], "email": row[2], "name": row[3], "is_owner": row[4], "workspace_name": row[5]} for row in rows}
        with user_cache_lock:
            user_cache[team_id] = new_cache
        with owner_id_lock:
            owner_id_cache[team_id] = next((user_id for user_id, data in new_cache.items() if data['is_owner']), None)
    else:
        # Fetch user data from Slack and update database
        response = client.users_list()
        users = response["members"]
        workspace_name = client.team_info()["team"]["name"]  # Get workspace name from Slack API
        new_cache = {}
        for user in users:
            user_id = user['id']
            profile = user.get('profile', {})
            real_name = profile.get('real_name', 'Unknown')
            name = user.get('name', '')
            email = f"{name}@gmail.com"  # Placeholder; adjust as needed
            is_owner = user.get('is_owner', False)
            new_cache[user_id] = {"real_name": real_name, "email": email, "name": name, "is_owner": is_owner, "workspace_name": workspace_name}
            cur.execute('''
                INSERT INTO Users (team_id, user_id, workspace_name, real_name, email, name, is_owner, last_updated)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (team_id, user_id) DO UPDATE SET
                    workspace_name = %s, real_name = %s, email = %s, name = %s, is_owner = %s, last_updated = %s
            ''', (team_id, user_id, workspace_name, real_name, email, name, is_owner, datetime.now(),
                  workspace_name, real_name, email, name, is_owner, datetime.now()))
        conn.commit()
        with user_cache_lock:
            user_cache[team_id] = new_cache
        with owner_id_lock:
            owner_id_cache[team_id] = next((user_id for user_id, data in new_cache.items() if data['is_owner']), None)
    cur.close()
    conn.close()
def get_workspace_owner_id_client(client ):
    """Get the workspace owner's user ID."""
    try:
        response = client.users_list()
        members = response["members"]
        for member in members:
            if member.get("is_owner"):
                return member["id"]
    except SlackApiError as e:
        print(f"Error fetching users: {e.response['error']}")
    return None

def get_workspace_owner_id(client, team_id):
    with owner_id_lock:
        if team_id in owner_id_cache and owner_id_cache[team_id]:
            return owner_id_cache[team_id]
    initialize_workspace_cache(client, team_id)
    with owner_id_lock:
        return owner_id_cache.get(team_id)
# def get_workspace_owner_id():
#     conn = sqlite3.connect('workspace_cache.db')
#     c = conn.cursor()
#     c.execute('SELECT user_id FROM workspace_cache WHERE is_owner = 1')
#     owner_id = c.fetchone()
#     conn.close()
#     return owner_id[0] if owner_id else None

owner_id_pref = get_workspace_owner_id_client(client)
def GetAllUsers():
    all_users = {}
    try:
        response = client.users_list()
        print(response)
        members = response['members']
        for member in members:
            user_id = member['id']
            profile = member.get('profile', {})
            user_name = profile.get('real_name', '')  # Use real_name from profile
            # Use actual email if available, otherwise construct one from member['name']
            email = profile.get('email', f"{member.get('name', '')}@gmail.com")
            print(f"User ID: {user_id}, Name: {user_name}, Email: {email}")
            all_users[user_id] = {"Slack Id": user_id, "name": user_name, "email": email}
        return all_users
    except SlackApiError as e:
        print(f"Error fetching users: {e.response['error']}")
        return {}
def load_token(team_id, user_id, service):
    """
    Load token data from the database for a specific team, user, and service.

    Parameters:
        team_id (str): The Slack team ID.
        user_id (str): The Slack user ID.
        service (str): The service name (e.g., 'google').

    Returns:
        dict: The token data as a dictionary, or None if not found.
    """
    conn = psycopg2.connect(os.getenv('DATABASE_URL'))
    cur = conn.cursor()
    cur.execute(
        'SELECT token_data FROM Tokens WHERE team_id = %s AND user_id = %s AND service = %s',
        (team_id, user_id, service)
    )
    row = cur.fetchone()
    cur.close()
    conn.close()
    return row[0] if row else None

def save_token(team_id, user_id, service, token_data):
    """
    Save token data to the database for a specific team, user, and service.

    Parameters:
        team_id (str): The Slack team ID.
        user_id (str): The Slack user ID.
        service (str): The service name (e.g., 'google').
        token_data (dict): The token data to save (e.g., {'access_token', 'refresh_token', 'expires_at'}).
    """
    conn = psycopg2.connect(os.getenv('DATABASE_URL'))
    cur = conn.cursor()
    cur.execute(
        '''
        INSERT INTO Tokens (team_id, user_id, service, token_data, updated_at)
        VALUES (%s, %s, %s, %s, %s)
        ON CONFLICT (team_id, user_id, service) 
        DO UPDATE SET token_data = %s, updated_at = %s
        ''',
        (
            team_id, user_id, service, json.dumps(token_data), datetime.now(),
            json.dumps(token_data), datetime.now()
        )
    )
    conn.commit()
    cur.close()
    conn.close()
all_users_preload = GetAllUsers()
if all_users_preload:
    print("Users Prefection enabled")
# def GetAllUsers():
#     return ""
# all_users_preload = ""
# owner_id_pref = ""