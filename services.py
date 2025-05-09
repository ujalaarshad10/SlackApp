# import json
# import os
# from typing import Type
# from dotenv import load_dotenv
# from langchain.pydantic_v1 import BaseModel, Field
# from langchain_core.tools import BaseTool
# from slack_sdk.errors import SlackApiError
# from datetime import datetime
# from google_auth_oauthlib.flow import InstalledAppFlow
# from googleapiclient.discovery import build
# from google.oauth2.credentials import Credentials
# from google.auth.transport.requests import Request
# from config import client
# SCOPES = ['https://www.googleapis.com/auth/calendar']
# TOKEN_DIR = "token_files"
# TOKEN_FILE = f"{TOKEN_DIR}/token.json"
# def create_service(client_secret_file, api_name, api_version, user_id, *scopes):
#     """
#     Create a Google API service instance using stored credentials for a given user.
    
#     Parameters:
#       - client_secret_file (str): Path to your client secrets JSON file.
#       - api_name (str): The Google API service name (e.g., 'calendar').
#       - api_version (str): The API version (e.g., 'v3').
#       - user_id (str): The unique identifier for the user (e.g., Slack user ID).
#       - scopes (tuple): A tuple/list of scopes. (Pass as: [SCOPES])
    
#     Returns:
#       - service: The built Google API service instance, or None if authentication is required.
#     """
#     scopes = list(scopes[0])  # Unpack scopes
#     creds = None
#     user_token_file = os.path.join(TOKEN_DIR, f"token.json")

#     if os.path.exists(user_token_file):
#         try:
#             creds = Credentials.from_authorized_user_file(user_token_file, scopes)
#         except ValueError as e:
#             print(f"Error loading credentials: {e}")
#             # os.remove(user_token_file)
#             creds = None
#         print(creds)
#     # If credentials are absent or invalid, we cannot proceed.
#     if not creds or not creds.valid:
#         if creds and creds.expired and creds.refresh_token:
#             try:
#                 creds.refresh(Request())
#             except Exception as e:
#                 print(f"Error refreshing token: {e}")
#                 return None
#         else:
#             print("No valid credentials available. Please re-authenticate.")
#             return None

#         # Save the refreshed token.
#         with open(user_token_file, 'w') as token_file:
#             token_file.write(creds.to_json())

#     try:
#         service = build(api_name, api_version, credentials=creds, static_discovery=False)
#         return service
#     except Exception as e:
#         print(f"Failed to create service instance for {api_name}: {e}")
#         os.remove(user_token_file)  # Remove the token file if it's causing issues.
#         return None

# def construct_google_calendar_client(user_id):
#     """
#     Constructs a Google Calendar API client for the specified user.
    
#     Parameters:
#       - user_id (str): The unique user identifier (e.g., Slack user ID).
    
#     Returns:
#       - service: The Google Calendar API service instance or None if not authenticated.
#     """
#     API_NAME = 'calendar'
#     API_VERSION = 'v3'
#     return create_service('credentials.json', API_NAME, API_VERSION, user_id, SCOPES)


import json
import os
from datetime import datetime
import psycopg2
from dotenv import load_dotenv
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

# Load environment variables from a .env file
load_dotenv()

# Database helper functions
def load_token(team_id, user_id, service):
    conn = psycopg2.connect(os.getenv('DATABASE_URL'))
    cur = conn.cursor()
    cur.execute('SELECT token_data FROM Tokens WHERE team_id = %s AND user_id = %s AND service = %s', (team_id, user_id, service))
    row = cur.fetchone()
    cur.close()
    conn.close()
    print(f"DB ROW: {row[0]}")
    return json.loads(row[0]) if row else None

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

def create_service(team_id, user_id, api_name, api_version, scopes):
    """
    Create a Google API service instance using stored credentials for a given user.

    Parameters:
        team_id (str): The Slack team ID.
        user_id (str): The Slack user ID.
        api_name (str): The Google API service name (e.g., 'calendar').
        api_version (str): The API version (e.g., 'v3').
        scopes (list): List of scopes required for the API.

    Returns:
        service: The built Google API service instance, or None if authentication fails.
    """
    # Load token data from the database
    token_data = load_token(team_id, user_id, 'google')
    if not token_data:
        print(f"No token found for team {team_id}, user {user_id}. Initial authorization required.")
        return None

    # Fetch client credentials from environment variables
    client_id = os.getenv('GOOGLE_CLIENT_ID')
    client_secret = os.getenv('GOOGLE_CLIENT_SECRET')
    token_uri = os.getenv('GOOGLE_TOKEN_URI', 'https://oauth2.googleapis.com/token')

    if not client_id or not client_secret:
        print("Google client credentials not found in environment variables.")
        return None

    # Create Credentials object using token data and client credentials
    try:
        creds = Credentials(
            token=token_data.get('access_token'),
            refresh_token=token_data.get('refresh_token'),
            token_uri=token_uri,
            client_id=client_id,
            client_secret=client_secret,
            scopes=scopes
        )
    except ValueError as e:
        print(f"Error creating credentials for user {user_id}: {e}")
        return None

    # Refresh token if expired
    if not creds.valid:
        if creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
                # Save refreshed token data to the database
                refreshed_token_data = {
                    'access_token': creds.token,
                    'refresh_token': creds.refresh_token,
                    'expires_at': creds.expiry.timestamp() if creds.expiry else None
                }
                save_token(team_id, user_id, 'google', refreshed_token_data)
                print(f"Token refreshed for user {user_id}.")
            except Exception as e:
                print(f"Error refreshing token for user {user_id}: {e}")
                return None
        else:
            print(f"Credentials invalid and no refresh token available for user {user_id}.")
            return None

    # Build and return the Google API service
    try:
        service = build(api_name, api_version, credentials=creds, static_discovery=False)
        return service
    except Exception as e:
        print(f"Failed to create service instance for {api_name}: {e}")
        return None

def construct_google_calendar_client(team_id, user_id):
    """
    Constructs a Google Calendar API client for the specified user.

    Parameters:
        team_id (str): The Slack team ID.
        user_id (str): The Slack user ID.

    Returns:
        service: The Google Calendar API service instance, or None if not authenticated.
    """
    API_NAME = 'calendar'
    API_VERSION = 'v3'
    SCOPES = ['https://www.googleapis.com/auth/calendar']
    return create_service(team_id, user_id, API_NAME, API_VERSION, SCOPES)