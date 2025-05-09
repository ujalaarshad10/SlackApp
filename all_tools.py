# import json
# import os
# import requests
# import base64
# import msal
# import time
# from typing import Type, Optional, List

# from dotenv import load_dotenv
# from pydantic.v1 import BaseModel, Field
# from msal import ConfidentialClientApplication

# from langchain_core.tools import BaseTool
# from slack_sdk.errors import SlackApiError
# from datetime import datetime
# from google_auth_oauthlib.flow import InstalledAppFlow
# from googleapiclient.discovery import build
# from google.oauth2.credentials import Credentials
# from google.auth.transport.requests import Request
# from services import construct_google_calendar_client
# from config import client
# from datetime import datetime, timedelta
# import pytz
# from typing import List, Dict, Optional
# from collections import defaultdict
# from slack_sdk.errors import SlackApiError
# from config import owner_id_pref, all_users_preload, GetAllUsers
# load_dotenv()
# calendar_service = None
# MICROSOFT_CLIENT_SECRET = os.getenv("MICROSOFT_CLIENT_SECRET")
# MICROSOFT_AUTHORITY = "https://login.microsoftonline.com/common"
# MICROSOFT_SCOPES = ["User.Read", "Calendars.ReadWrite"]
# MICROSOFT_REDIRECT_URI = os.getenv("MICROSOFT_REDIRECT_URI", "https://clear-muskox-grand.ngrok-free.app/microsoft_callback")
# # Enhanced GetAllUsers function (not a tool) to fetch email as well
# MICROSOFT_CLIENT_ID = "855e4571-d92a-4d51-802e-e712a879c00b"


# # Pydantic models for tool arguments
# class DirectDMArgs(BaseModel):
#     message: str = Field(description="The message to be sent to the Slack user")
#     user_id: str = Field(description="The Slack user ID")

# class DateTimeTool(BaseTool):
#     name: str = "current_date_time"
#     description: str = "Provides the current date and time."

#     def _run(self):
#         return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

# # Tool to get a single user's Slack ID based on their name
# class GetSingleUserSlackIDArgs(BaseModel):
#     name: str = Field(description="The real name of the user whose Slack ID is needed")

# class GetSingleUserSlackID(BaseTool):
#     name: str = "gets_slack_id_single_user"
#     description: str = "Gets the Slack ID of a user based on their real name"
#     args_schema: Type[BaseModel] = GetSingleUserSlackIDArgs

#     def _run(self, name: str):
#         if not all_users_preload:
#             print("Getting the users")
#             all_users = GetAllUsers()  # Fetch all users again
#         else:
#             print("Fetching the users")
#             all_users = all_users_preload

#         # Iterate through all_users to find a matching name
#         for uid, info in all_users.items():
#             if info["name"].lower() == name.lower():
#                 return uid, info['email']
        
#         return "User not found"

# # Tool to get a single user's Slack name based on their ID
# class GetSingleUserSlackNameArgs(BaseModel):
#     id: str = Field(description="The Slack user ID")

# class GetSingleUserSlackName(BaseTool):
#     name: str = "gets_slack_name_single_user"
#     description: str = "Gets the Slack real name of a user based on their slack ID"
#     args_schema: Type[BaseModel] = GetSingleUserSlackNameArgs

#     def _run(self, id: str):  

#         # Check if preload returns empty dict or "User not found"
#         if not all_users_preload or all_users_preload == {}:
#             all_users = GetAllUsers()  # Fetch all users again
#         else:
#             all_users = all_users_preload

#         user = all_users.get(id)
#         print(all_users)
        
#         if user:
#             return user["name"], user['email']
        
#         return "User not found"

# class MultiDMArgs(BaseModel):
#     message: str
#     user_ids: List[str]

# class MultiDirectDMTool(BaseTool):
#     name: str = "send_multiple_dms"
#     description: str = "Sends direct messages to multiple Slack users"
#     args_schema: Type[BaseModel] = MultiDMArgs

#     def _run(self, message: str, user_ids: List[str]):
#         results = {}
#         for user_id in user_ids:
#             try:
#                 client.chat_postMessage(channel=user_id, text=message)
#                 results[user_id] = "Message sent successfully"
#             except SlackApiError as e:
#                 results[user_id] = f"Error: {e.response['error']}"
#         return results
# # Direct DM tool for sending messages within Slack
# class DirectDMTool(BaseTool):
#     name: str = "send_direct_dm"
#     description: str = "Sends direct messages to Slack users"
#     args_schema: Type[BaseModel] = DirectDMArgs

#     def _run(self, message: str, user_id: str):
#         try:
#             client.chat_postMessage(channel=user_id, text=message)
#             return "Message sent successfully"
#         except SlackApiError as e:
#             return f"Error sending message: {e.response['error']}"
# def send_dm(user_id: str, message: str) -> bool:
#     """Send a direct message to a user"""
#     try:
#         client.chat_postMessage(channel=user_id, text=message)
#         return True
#     except SlackApiError as e:
#         print(f"Error sending DM: {e.response['error']}")
#         return False

# def handle_event_modification(event_id: str, action: str) -> str:
#     """Handle event modification (update/delete)"""
#     # You'll need to implement the actual modification logic
#     if action == "delete":
#         result = GoogleDeleteCalendarEvent().run(event_id=event_id)
#     else:
#         result = GoogleUpdateCalendarEvent().run(event_id=event_id)
    
#     if result.get("status") == "success":
#         return f"Event {action}d successfully!"
#     return f"Failed to {action} event: {result.get('message', 'Unknown error')}"
# # Google Calendar Tools
# PT = pytz.timezone('America/Los_Angeles')

# def convert_to_pt(dt: datetime) -> datetime:
#     """Convert a datetime object to PT timezone"""
#     if dt.tzinfo is None:
#         dt = pytz.utc.localize(dt)
#     return dt.astimezone(PT)
# class GoogleCalendarList(BaseTool):
#     name: str = "list_calendar_list"
#     description: str = "Lists available calendars in the user's Google Calendar account"
    
#     def _run(self, user_id: str, max_capacity: int = 200):
#         if not calendar_service:
#             calendar_service = construct_google_calendar_client(user_id)
#         else:
#             return "Token should be refreshed in Google Calendar"

#         all_calendars = []
#         next_page_token = None
#         capacity_tracker = 0

#         while capacity_tracker < max_capacity:
#             results = calendar_service.calendarList().list(
#                 maxResults=min(200, max_capacity - capacity_tracker),
#                 pageToken=next_page_token
#             ).execute()
#             calendars = results.get('items', [])
#             all_calendars.extend(calendars)
#             capacity_tracker += len(calendars)
#             next_page_token = results.get('nextPageToken')
#             if not next_page_token:
#                 break

#         return [{
#             'id': cal['id'],
#             'name': cal['summary'],
#             'description': cal.get('description', '')
#         } for cal in all_calendars]

# class GoogleCalendarEvents(BaseTool):
#     name: str = "list_calendar_events"
#     description: str = "Lists and gets events from a specific Google Calendar"
    
#     def _run(self, user_id: str, calendar_id: str = "primary", max_capacity: int = 20):
        
#         calendar_service = construct_google_calendar_client(user_id)

#         all_events = []
#         next_page_token = None
#         capacity_tracker = 0

#         while capacity_tracker < max_capacity:
#             results = calendar_service.events().list(
#                 calendarId=calendar_id,
#                 maxResults=min(250, max_capacity - capacity_tracker),
#                 pageToken=next_page_token
#             ).execute()
#             events = results.get('items', [])
#             all_events.extend(events)
#             capacity_tracker += len(events)
#             next_page_token = results.get('nextPageToken')
#             if not next_page_token:
#                 break

#         return all_events

# class GoogleCreateCalendar(BaseTool):
#     name: str = "create_calendar_list"
#     description: str = "Creates a new calendar in Google Calendar"
    
#     def _run(self, user_id: str, calendar_name: str):
        
#         calendar_service = construct_google_calendar_client(user_id)

#         calendar_body = {'summary': calendar_name}
#         created_calendar = calendar_service.calendars().insert(body=calendar_body).execute()
#         return f"Created calendar: {created_calendar['id']}"

# # Updated Event Creation Tool with guest options, meeting agenda, and invite link support
# class GoogleAddCalendarEventArgs(BaseModel):
#     calendar_id: str = Field(default="primary", description="Calendar ID (default 'primary')")
#     summary: str = Field(description="Event title (should include meeting agenda if needed)")
#     user_id: str = Field(default="user", description="User slack Id which should be matched to name")
#     description: str = Field(default="", description="Event description or agenda")
#     start_time: str = Field(description="Start time in ISO 8601 format")
#     end_time: str = Field(description="End time in ISO 8601 format")
#     location: str = Field(default="", description="Event location")
#     invite_link: str = Field(default="", description="Invite link for the meeting")
#     guests: List[str] = Field(default=None, description="List of guest emails to invite")

# class GoogleAddCalendarEvent(BaseTool):
#     name: str = "google_add_calendar_event"
#     description: str = "Creates an event in a Google Calendar with comprehensive meeting details and guest options"
#     args_schema: Type[BaseModel] = GoogleAddCalendarEventArgs

#     def _run(self, user_id: str, summary: str, start_time: str, end_time: str, 
#              description: str = "", calendar_id: str = 'primary', location: str = "", 
#              invite_link: str = "", guests: List[str] = None):
#         calendar_service = construct_google_calendar_client(user_id)

#         # Append invite link to description if provided
#         if invite_link:
#             description = f"{description}\nInvite Link: {invite_link}"
        
#         event = {
#             'summary': summary,
#             'description': description,
#             'start': {'dateTime': start_time, 'timeZone': 'America/Los_Angeles'},
#             'end': {'dateTime': end_time, 'timeZone': 'America/Los_Angeles'},
#             'location': location,
#         }

#         # Add guests if provided
#         if guests:
#             event['attendees'] = [{'email': guest} for guest in guests]

#         try:
#             print("I am here registering the event")
#             created_event = calendar_service.events().insert(
#                 calendarId=calendar_id,
#                 body=event,
#                 sendUpdates='all'  # Send invitations to guests
#             ).execute()
#             return {
#                 "status": "success",
#                 "event_id": created_event['id'],
#                 "link": created_event.get('htmlLink', '')
#             }
#         except Exception as e:
#             return {"status": "error", "message": str(e)}

# # Updated Tool: Update an existing calendar event including guest options
# class GoogleUpdateCalendarEventArgs(BaseModel):
#     calendar_id: str = Field(default="primary", description="Calendar ID (default 'primary')")
#     user_id: str = Field(default="user", description="User slack Id which should be matched to name")
#     event_id: str = Field(description="The event ID to update")
#     summary: str = Field(default=None, description="Updated event title or agenda")
#     description: Optional[str] = Field(default=None, description="Updated event description or agenda")
#     start_time: Optional[str] = Field(default=None, description="Updated start time in ISO 8601 format")
#     end_time: Optional[str] = Field(default=None, description="Updated end time in ISO 8601 format")
#     location: Optional[str] = Field(default=None, description="Updated event location")
#     invite_link: str = Field(default=None, description="Updated invite link for the meeting")
#     guests: List[str] = Field(default=None, description="Updated list of guest emails")

# class GoogleUpdateCalendarEvent(BaseTool):
#     name: str = "google_update_calendar_event"
#     description: str = "Updates an existing event in a Google Calendar, including guest options"
#     args_schema: Type[BaseModel] = GoogleUpdateCalendarEventArgs

#     def _run(self, user_id: str, event_id: str, calendar_id: str = "primary", 
#              summary: Optional[str] = None, description: Optional[str] = None,
#              start_time: Optional[str] = None, end_time: Optional[str] = None,
#              location: Optional[str] = None, invite_link: Optional[str] = None,
#              guests: Optional[List[str]] = None):
        
#         calendar_service = construct_google_calendar_client(user_id)
        
#         # Retrieve the existing event
#         try:
#             event = calendar_service.events().get(calendarId=calendar_id, eventId=event_id).execute()
#         except Exception as e:
#             return {"status": "error", "message": f"Event retrieval failed: {str(e)}"}

#         # Update fields if provided
#         if summary:
#             event['summary'] = summary
#         if description:
#             event['description'] = description
#         if invite_link:
#             # Append invite link to the description
#             current_desc = event.get('description', '')
#             event['description'] = f"{current_desc}\nInvite Link: {invite_link}"
#         if start_time:
#             event['start'] = {'dateTime': start_time, 'timeZone': 'UTC'}
#         if end_time:
#             event['end'] = {'dateTime': end_time, 'timeZone': 'UTC'}
#         if location:
#             event['location'] = location
#         if guests is not None:
#             event['attendees'] = [{'email': guest} for guest in guests]

#         try:
#             updated_event = calendar_service.events().update(
#                 calendarId=calendar_id,
#                 eventId=event_id,
#                 body=event
#             ).execute()
#             return {"status": "success", "event_id": updated_event['id']}
#         except Exception as e:
#             return {"status": "error", "message": f"Update failed: {str(e)}"}

# # New Tool: Delete a calendar event
# class GoogleDeleteCalendarEventArgs(BaseModel):
#     calendar_id: str = Field(default="primary", description="Calendar ID (default 'primary')")
#     event_id: str = Field(description="The event ID to delete")
#     user_id: str = Field(default="user", description="User slack Id which should be matched to name")

# class GoogleDeleteCalendarEvent(BaseTool):
#     name: str = "google_delete_calendar_event"
#     description: str = "Deletes an event from a Google Calendar"
#     args_schema: Type[BaseModel] = GoogleDeleteCalendarEventArgs

#     def _run(self, user_id: str, event_id: str, calendar_id: str = "primary"):
        
#         calendar_service = construct_google_calendar_client(user_id)
#         try:
#             calendar_service.events().delete(calendarId=calendar_id, eventId=event_id).execute()
#             return {"status": "success", "message": f"Deleted event {event_id}"}
#         except Exception as e:
#             return {"status": "error", "message": f"Deletion failed: {str(e)}"}


# # New Tool: Search Events by User
# class SearchUserEventsArgs(BaseModel):
#     user_id: str
#     lookback_days: int = Field(default=30)
# class SearchUserEventsTool(BaseTool):
#     name: str = "search_events_by_user"
#     description: str = "Finds calendar events associated with a specific user"
#     args_schema: Type[BaseModel] = SearchUserEventsArgs

#     def _run(self, user_id: str, lookback_days: int = 30):
#         # Get user info which may be a tuple (name, email) or "User not found"
#         user_info = GetSingleUserSlackName().run(user_id)
        
#         # Handle case where user is not found
#         if user_info == "User not found":
#             return []
        
#         # Extract user_name from tuple
#         user_name, user_email = user_info
        
#         # Fetch events for the user
#         events = GoogleCalendarEvents().run(user_id)
        
#         # Ensure 'now' is timezone-aware (using UTC)
#         now = datetime.now(pytz.UTC)
        
#         relevant_events = []
#         for event in events:
#             # Ensure event_time is timezone-aware
#             event_time_str = event['start'].get('dateTime')
#             if not event_time_str:
#                 continue  # Skip events without a valid start time
            
#             event_time = datetime.fromisoformat(event_time_str)
#             if event_time.tzinfo is None:
#                 # If event_time is naive, make it timezone-aware (assuming UTC)
#                 event_time = pytz.UTC.localize(event_time)
            
#             # Check if the event is within the lookback period
#             if (now - event_time).days > lookback_days:
#                 continue
            
#             # Check if the user's name is in the event summary or description
#             if user_name in event.get('summary', '') or user_name in event.get('description', ''):
#                 relevant_events.append({
#                     'id': event['id'],
#                     'title': event['summary'],
#                     'time': event_time.strftime("%Y-%m-%d %H:%M"),
#                     'calendar_id': event['organizer']['email']
#                 })
        
#         return relevant_events
# # Enhanced Agent Logic
# def handle_update_delete(user_id, text):
#     events = SearchUserEventsTool().run(user_id)
    
#     if not events:
#         return "No recent events found for you."
        
#     if len(events) > 1:
#         options = [{"text": f"{e['title']} ({e['time']})", "value": e['id']} for e in events]
#         return {
#             "response_type": "ephemeral",
#             "blocks": [{
#                 "type": "section",
#                 "text": {"type": "mrkdwn", "text": "Multiple events found:"},
#                 "accessory": {
#                     "type": "static_select",
#                     "options": options,
#                     "action_id": "select_event_to_modify"
#                 }
#             }]
#         }
    
#     # If single event, proceed directly
#     return handle_event_modification(events[0]['id'])


# # State Management
# from collections import defaultdict
# meeting_coordination = defaultdict(dict)

# class CreatePollArgs(BaseModel):
#     time_slots: List[str]
#     channel_id: str
#     initiator_id: str

# class CoordinateDMsArgs(BaseModel):
#     user_ids: List[str]
#     time_slots: List[str]
# # Poll Creation Tool
# class CoordinateDMsTool(BaseTool):
#     name:str = "coordinate_dm_responses"
#     description:str = "Manages DM responses for meeting coordination"
#     args_schema: Type[BaseModel] = CoordinateDMsArgs
#     def _run(self, user_ids: List[str], time_slots: List[str]) -> Dict:
#         session_id = f"dm_coord_{datetime.now().timestamp()}"
#         message = "Please choose a time slot by replying with the number:\n" + \
#                  "\n".join([f"{i+1}. {slot}" for i, slot in enumerate(time_slots)])
        
#         for uid in user_ids:
#             if not send_dm(uid, message):
#                 return {"status": "error", "message": f"Failed to send DM to user {uid}"}
        
#         meeting_coordination[session_id] = {
#             "responses": {},
#             "required": len(user_ids),
#             "slots": time_slots,
#             "participants": user_ids,
#             "created_at": datetime.now()
#         }
        
#         return {
#             "status": "success",
#             "session_id": session_id,
#             "message": "DMs sent to all participants"
#         }

# # Poll Management



# # Zoom Meeting Tool
# # class ZoomCreateMeetingArgs(BaseModel):
# #     topic: str = Field(description="Meeting topic")
# #     start_time: str = Field(description="Start time in ISO 8601 format and PT timezone")
# #     duration: int = Field(description="Duration in minutes")
# #     agenda: Optional[str] = Field(default="", description="Meeting agenda")
# #     timezone: str = Field(default="UTC", description="Timezone for the meeting")

# # class ZoomCreateMeetingTool(BaseTool):
# #     name:str = "create_zoom_meeting"
# #     description:str = "Creates a Zoom meeting using configured credentials"
# #     args_schema: Type[BaseModel] = ZoomCreateMeetingArgs

# #     def _run(self, topic: str, start_time: str, duration: int = 30, 
# #             agenda: str = "", timezone: str = "UTC"):
# #         # Get owner's credentials
# #         owner_id = "owner_id_pref"
# #         if not owner_id:
# #             return "Workspace owner not found"
            
# #         prefs_path = os.path.join('preferences', f'preferences_{owner_id}.json')
# #         if not os.path.exists(prefs_path):
# #             return "Zoom credentials not configured"
            
# #         with open(prefs_path) as f:
# #             prefs = json.load(f)
            
# #         if prefs['zoom_config']['mode'] == 'manual':
# #             return {"link": prefs.get('zoom_link'), "message": "Using manual Zoom link"}
            
# #         # Automatic Zoom creation
# #         auth_str = f"{prefs['zoom_config']['client_id']}:{prefs['zoom_config']['client_secret']}"
# #         auth_bytes = base64.b64encode(auth_str.encode()).decode()
        
# #         headers = {
# #             "Authorization": f"Basic {auth_bytes}",
# #             "Content-Type": "application/x-www-form-urlencoded"
# #         }
        
# #         data = {
# #             "grant_type": "account_credentials",
# #             "account_id": prefs['zoom_config']['account_id']
# #         }
        
# #         # Get access token
# #         token_res = requests.post(
# #             "https://zoom.us/oauth/token", 
# #             headers=headers, 
# #             data=data
# #         )
        
# #         if token_res.status_code != 200:
# #             return "Zoom authentication failed"
            
# #         access_token = token_res.json()["access_token"]
        
# #         # Create meeting
# #         meeting_data = {
# #             "topic": topic,
# #             "type": 2,
# #             "start_time": start_time,
# #             "duration": duration,
# #             "timezone": timezone,
# #             "agenda": agenda,
# #             "settings": {
# #                 "host_video": True,
# #                 "participant_video": True,
# #                 "join_before_host": False
# #             }
# #         }
        
# #         headers = {
# #             "Authorization": f"Bearer {access_token}",
# #             "Content-Type": "application/json"
# #         }
        
# #         meeting_res = requests.post(
# #             "https://api.zoom.us/v2/users/me/meetings",
# #             headers=headers,
# #             json=meeting_data
# #         )
        
# #         if meeting_res.status_code == 201:
# #             return {
# #                 "meeting_id": meeting_res.json()["id"],
# #                 "join_url": meeting_res.json()["join_url"],
# #                 'passcode':meeting_res.json()["password"],
# #                 'duration':duration
# #             }
# #         return f"Zoom meeting creation failed: {meeting_res.text}"
# from langchain.tools import BaseTool
# from pydantic import BaseModel, Field
# from typing import Optional, Type
# import os
# import json
# import time
# import requests
# import base64

# class ZoomCreateMeetingArgs(BaseModel):
#     topic: str = Field(description="Meeting topic")
#     start_time: str = Field(description="Start time in ISO 8601 format and PT timezone")
#     duration: int = Field(description="Duration in minutes")
#     agenda: Optional[str] = Field(default="", description="Meeting agenda")
#     timezone: str = Field(default="UTC", description="Timezone for the meeting")

# from config import get_workspace_owner_id, load_preferences
# import os
# # ZOOM_REDIRECT_URI = os.environ['ZOOM_REDIRECT_URI']
# CLIENT_SECRET = os.environ['ZOOM_CLIENT_SECRET']
# CLIENT_ID = os.environ['ZOOM_CLIENT_ID']
# ZOOM_TOKEN_API = os.environ['ZOOM_TOKEN_API']
# # ZOOM_OAUTH_AUTHORIZE_API = os.environ['ZOOM_OAUTH_AUTHORIZE_API']
# class ZoomCreateMeetingTool(BaseTool):
#     name: str = "create_zoom_meeting"
#     description: str = "Creates a Zoom meeting using configured credentials"
#     args_schema: Type[BaseModel] = ZoomCreateMeetingArgs

#     def _run(self, topic: str, start_time: str, duration: int = 30, 
#          agenda: str = "", timezone: str = "UTC"):
#     # Get workspace owner's ID
#         owner_id = get_workspace_owner_id()
#         if not owner_id:
#             return "Workspace owner not found"

#         # Load preferences to check Zoom mode
#         prefs = load_preferences(owner_id)
#         zoom_config = prefs.get("zoom_config", {"mode": "manual", "link": None})

#         # Handle manual mode
#         if zoom_config["mode"] == "manual":
#             link = zoom_config.get("link")
#             if link:
#                 return f"Please join the meeting using this link: {link}"
#             else:
#                 return "Manual Zoom link not configured"

#         # Automatic mode
#         token_path = f'token_files/zoom_{owner_id}.json'
#         if not os.path.exists(token_path):
#             return "Zoom not configured for automatic mode"

#         with open(token_path) as f:
#             token_data = json.load(f)

#         access_token = token_data.get("access_token")
#         if not access_token:
#             return "Invalid Zoom token"

#         # Check if token is expired and refresh if necessary
#         expires_at = token_data.get("expires_at")
#         if expires_at and time.time() > expires_at:
#             refresh_token = token_data.get("refresh_token")
#             if not refresh_token:
#                 return "Zoom token expired and no refresh token available"
#             params = {
#                 "grant_type": "refresh_token",
#                 "refresh_token": refresh_token
#             }
#             auth_str = f"{CLIENT_ID}:{CLIENT_SECRET}"
#             auth_bytes = base64.b64encode(auth_str.encode()).decode()
#             headers = {
#                 "Authorization": f"Basic {auth_bytes}",
#                 "Content-Type": "application/x-www-form-urlencoded"
#             }
#             response = requests.post(ZOOM_TOKEN_API, data=params, headers=headers)
#             if response.status_code == 200:
#                 new_token_data = response.json()
#                 token_data.update(new_token_data)
#                 token_data["expires_at"] = time.time() + new_token_data["expires_in"]
#                 with open(token_path, 'w') as f:
#                     json.dump(token_data, f)
#                 access_token = new_token_data["access_token"]
#             else:
#                 return "Failed to refresh Zoom token"

#         # Create Zoom meeting
#         meeting_data = {
#             "topic": topic,
#             "type": 2,  # Scheduled meeting
#             "start_time": start_time,
#             "duration": duration,
#             "timezone": timezone,
#             "agenda": agenda,
#             "settings": {
#                 "host_video": True,
#                 "participant_video": True,
#                 "join_before_host": False
#             }
#         }
#         headers = {
#             "Authorization": f"Bearer {access_token}",
#             "Content-Type": "application/json"
#         }
#         meeting_res = requests.post(
#             "https://api.zoom.us/v2/users/me/meetings",
#             headers=headers,
#             json=meeting_data
#         )
#         if meeting_res.status_code == 201:
#             meeting_info = meeting_res.json()
            
#             # Extract meeting details
#             meeting_id = meeting_info["id"]
#             join_url = meeting_info["join_url"]
#             password = meeting_info.get("password", "")
#             dial_in_numbers = meeting_info["settings"].get("global_dial_in_numbers", [])
#             print(meeting_info['settings'])
#             print(dial_in_numbers)
#             # Format one-tap mobile numbers (up to 2 US numbers)
#             us_numbers = [num for num in dial_in_numbers if num["country"] == "US"]
#             one_tap_strs = []
#             for num in us_numbers[:2]:
#                 clean_number = ''.join(num["number"].split())  # Remove spaces, e.g., "+1 305 224 1968" -> "+13052241968"
#                 one_tap = f"{clean_number},,{meeting_id}#,,,,*{password}# US"
#                 one_tap_strs.append(one_tap)

#             # Format dial-in numbers
#             dial_in_strs = []
#             for num in dial_in_numbers:
#                 country = num["country"]
#                 city = num.get("city", "")
#                 number = num["number"]
#                 if city:
#                     dial_in_strs.append(f"• {number} {country} ({city})")
#                 else:
#                     dial_in_strs.append(f"• {number} {country}")

#             # Construct the invitation text
#             invitation = "Citrusbug Technolabs is inviting you to a scheduled Zoom meeting.\n\n"
#             invitation += f"Join Zoom Meeting\n{join_url}\n\n"
#             invitation += f"Meeting ID: {meeting_id}\nPasscode: {password}\n\n"
#             invitation += "---\n\n"
#             if one_tap_strs:
#                 invitation += "One tap mobile\n"
#                 invitation += "\n".join(one_tap_strs) + "\n\n"
#             invitation += "---\n\n"
#             invitation += "Dial by your location\n"
#             invitation += "\n".join(dial_in_strs) + "\n\n"
#             invitation += f"Meeting ID: {meeting_id}\nPasscode: {password}\n"
#             invitation += "Find your local number: https://zoom.us/zoomconference"

#             return invitation
#         else:
#             return f"Zoom meeting creation failed: {meeting_res.text}"
# class MicrosoftBaseTool(BaseTool):
#     """Base class for Microsoft tools with common auth handling"""

#     def get_microsoft_client(self, user_id: str):
#         """Get authenticated Microsoft client for a user"""
#         token_path = os.path.join('token_files', f'microsoft_{user_id}.json')
#         if not os.path.exists(token_path):
#             return None, "Microsoft credentials not configured"

#         with open(token_path) as f:
#             token_data = json.load(f)

#         if time.time() > token_data['expires_at']:
#             # Handle token refresh
#             app = ConfidentialClientApplication(
#                 MICROSOFT_CLIENT_ID,
#                 authority=MICROSOFT_AUTHORITY,
#                 client_credential=MICROSOFT_CLIENT_SECRET
#             )
#             result = app.acquire_token_by_refresh_token(
#                 token_data['refresh_token'],
#                 scopes=MICROSOFT_SCOPES
#             )
#             if "access_token" not in result:
#                 return None, "Token refresh failed"

#             token_data.update(result)
#             with open(token_path, 'w') as f:
#                 json.dump(token_data, f)

#         headers = {
#             "Authorization": f"Bearer {token_data['access_token']}",
#             "Content-Type": "application/json"
#         }
#         return headers, None

# # Pydantic models for Microsoft tools
# class MicrosoftAddCalendarEventArgs(BaseModel):
#     user_id: str = Field(description="Slack user ID of the calendar owner")
#     subject: str = Field(description="Event title/subject")
#     start_time: str = Field(description="Start time in ISO 8601 format")
#     end_time: str = Field(description="End time in ISO 8601 format")
#     content: str = Field(default="", description="Event description/content")
#     location: str = Field(default="", description="Event location")
#     attendees: List[str] = Field(default=[], description="List of attendee emails")

# class MicrosoftUpdateCalendarEventArgs(MicrosoftAddCalendarEventArgs):
#     event_id: str = Field(description="Microsoft event ID to update")

# class MicrosoftDeleteCalendarEventArgs(BaseModel):
#     user_id: str = Field(description="Slack user ID of the calendar owner")
#     event_id: str = Field(description="Microsoft event ID to delete")

# # Microsoft Calendar Tools
# class MicrosoftListCalendarEvents(MicrosoftBaseTool):
#     name:str = "microsoft_calendar_list_events"
#     description:str = "Lists events from Microsoft Calendar"

#     def _run(self, user_id: str, max_results: int = 10):
#         headers, error = self.get_microsoft_client(user_id)
#         if error:
#             return error

#         endpoint = "https://graph.microsoft.com/v1.0/me/events"
#         params = {
#             "$top": max_results,
#             "$orderby": "start/dateTime desc"
#         }

#         response = requests.get(endpoint, headers=headers, params=params)
#         if response.status_code != 200:
#             return f"Error fetching events: {response.text}"

#         events = response.json().get('value', [])
#         return [{
#             'id': e['id'],
#             'subject': e.get('subject'),
#             'start': e['start'].get('dateTime'),
#             'end': e['end'].get('dateTime'),
#             'webLink': e.get('webUrl')
#         } for e in events]

# class MicrosoftAddCalendarEvent(MicrosoftBaseTool):
#     name:str = "microsoft_calendar_add_event"
#     description:str = "Creates an event in Microsoft Calendar"
#     args_schema: Type[BaseModel] = MicrosoftAddCalendarEventArgs

#     def _run(self, user_id: str, subject: str, start_time: str, end_time: str,
#              content: str = "", location: str = "", attendees: List[str] = []):
#         headers, error = self.get_microsoft_client(user_id)
#         if error:
#             return error

#         event_payload = {
#             "subject": subject,
#             "body": {
#                 "contentType": "HTML",
#                 "content": content
#             },
#             "start": {
#                 "dateTime": start_time,
#                 "timeZone": "America/Los_Angeles"
#             },
#             "end": {
#                 "dateTime": end_time,
#                 "timeZone": "America/Los_Angeles"
#             },
#             "location": {"displayName": location},
#             "attendees": [{"emailAddress": {"address": email}} for email in attendees]
#         }

#         response = requests.post(
#             "https://graph.microsoft.com/v1.0/me/events",
#             headers=headers,
#             json=event_payload
#         )

#         if response.status_code == 201:
#             return {
#                 "status": "success",
#                 "event_id": response.json()['id'],
#                 "link": response.json().get('webUrl')
#             }
#         return f"Error creating event: {response.text}"

# class MicrosoftUpdateCalendarEvent(MicrosoftBaseTool):
#     name:str = "microsoft_calendar_update_event"
#     description:str = "Updates an existing Microsoft Calendar event"
#     args_schema: Type[BaseModel] = MicrosoftUpdateCalendarEventArgs

#     def _run(self, user_id: str, event_id: str, **kwargs):
#         headers, error = self.get_microsoft_client(user_id)
#         if error:
#             return error

#         get_response = requests.get(
#             f"https://graph.microsoft.com/v1.0/me/events/{event_id}",
#             headers=headers
#         )
#         if get_response.status_code != 200:
#             return f"Error finding event: {get_response.text}"

#         existing_event = get_response.json()

#         update_payload = {
#             "subject": kwargs.get('subject', existing_event.get('subject')),
#             "body": {
#                 "content": kwargs.get('content', existing_event.get('body', {}).get('content')),
#                 "contentType": "HTML"
#             },
#             "start": {
#                 "dateTime": kwargs.get('start_time', existing_event['start']['dateTime']),
#                 "timeZone": "UTC"
#             },
#             "end": {
#                 "dateTime": kwargs.get('end_time', existing_event['end']['dateTime']),
#                 "timeZone": "UTC"
#             },
#             "location": {"displayName": kwargs.get('location', existing_event.get('location', {}).get('displayName'))},
#             "attendees": [{"emailAddress": {"address": email}} for email in
#                            kwargs.get('attendees', [a['emailAddress']['address'] for a in existing_event.get('attendees', [])])]
#         }

#         response = requests.patch(
#             f"https://graph.microsoft.com/v1.0/me/events/{event_id}",
#             headers=headers,
#             json=update_payload
#         )

#         if response.status_code == 200:
#             return {"status": "success", "event_id": event_id}
#         return f"Error updating event: {response.text}"

# class MicrosoftDeleteCalendarEvent(MicrosoftBaseTool):
#     name:str = "microsoft_calendar_delete_event"
#     description:str = "Deletes an event from Microsoft Calendar"
#     args_schema: Type[BaseModel] = MicrosoftDeleteCalendarEventArgs

#     def _run(self, user_id: str, event_id: str):
#         headers, error = self.get_microsoft_client(user_id)
#         if error:
#             return error

#         response = requests.delete(
#             f"https://graph.microsoft.com/v1.0/me/events/{event_id}",
#             headers=headers
#         )

#         if response.status_code == 204:
#             return {"status": "success", "message": f"Deleted event {event_id}"}
#         return f"Error deleting event: {response.text}"




# tools = [
#     DirectDMTool(),
#     ZoomCreateMeetingTool(),
#     # GetSingleUserSlackName(),
#     # GetSingleUserSlackID(),
# # CoordinateDMsTool(),
#     SearchUserEventsTool(),
#     # DateTimeTool(),
#     GoogleCalendarList(),
#     GoogleCalendarEvents(),
#     GoogleCreateCalendar(),
#     GoogleAddCalendarEvent(),
#     GoogleUpdateCalendarEvent(),
#     GoogleDeleteCalendarEvent(),
#     # MicrosoftListCalendarEvents(),
#     MicrosoftAddCalendarEvent(),
#     MicrosoftUpdateCalendarEvent(),
#     MicrosoftDeleteCalendarEvent(),
#     MultiDirectDMTool()
# ]
# calendar_prompt_tools = [
#   MicrosoftListCalendarEvents(), 
#   GoogleCalendarEvents()

# ]
# dm_tools = [
#     DirectDMTool(),
#     ZoomCreateMeetingTool(),
#     # CoordinateDMsTool(),
#     SearchUserEventsTool(),
#     GetSingleUserSlackName(),
#     GetSingleUserSlackID(),
#     # DateTimeTool(),
#     GoogleCalendarList(),
#     GoogleCalendarEvents(),
#     GoogleCreateCalendar(),
#     GoogleAddCalendarEvent(),
#     GoogleUpdateCalendarEvent(),
#     GoogleDeleteCalendarEvent(),
#     MicrosoftListCalendarEvents(),
#     MicrosoftAddCalendarEvent(),
#     MicrosoftUpdateCalendarEvent(),
#     MicrosoftDeleteCalendarEvent()
# ]

# dm_group_tools = [
#     GoogleCalendarEvents(),
#     MicrosoftListCalendarEvents(),
#     DateTimeTool(),
    
# ]
import json
import os
import requests
import base64
import msal
import time
from typing import Type, Optional, List

from dotenv import load_dotenv
from pydantic.v1 import BaseModel, Field
from msal import ConfidentialClientApplication

from langchain_core.tools import BaseTool
from slack_sdk.errors import SlackApiError
from datetime import datetime
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from config import client, get_workspace_owner_id, load_preferences, load_token, save_token
from datetime import datetime, timedelta
import pytz
from collections import defaultdict
from config import all_users_preload, GetAllUsers

load_dotenv()

# Load credentials from environment variables
MICROSOFT_CLIENT_SECRET = os.getenv("MICROSOFT_CLIENT_SECRET")
MICROSOFT_AUTHORITY = "https://login.microsoftonline.com/common"
MICROSOFT_SCOPES = ["User.Read", "Calendars.ReadWrite"]
MICROSOFT_REDIRECT_URI = os.getenv("MICROSOFT_REDIRECT_URI", "https://clear-muskox-grand.ngrok-free.app/microsoft_callback")
MICROSOFT_CLIENT_ID = "855e4571-d92a-4d51-802e-e712a879c00b"
ZOOM_CLIENT_SECRET = os.getenv("ZOOM_CLIENT_SECRET")
ZOOM_CLIENT_ID = os.getenv("ZOOM_CLIENT_ID")
ZOOM_TOKEN_API = os.getenv("ZOOM_TOKEN_API", "https://zoom.us/oauth/token")

# Pydantic models for tool arguments
class DirectDMArgs(BaseModel):
    message: str = Field(description="The message to be sent to the Slack user")
    user_id: str = Field(description="The Slack user ID")

class DateTimeTool(BaseTool):
    name: str = "current_date_time"
    description: str = "Provides the current date and time."

    def _run(self):
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

# Slack Tools
class GetSingleUserSlackIDArgs(BaseModel):
    name: str = Field(description="The real name of the user whose Slack ID is needed")

class GetSingleUserSlackID(BaseTool):
    name: str = "gets_slack_id_single_user"
    description: str = "Gets the Slack ID of a user based on their real name"
    args_schema: Type[BaseModel] = GetSingleUserSlackIDArgs

    def _run(self, name: str):
        if not all_users_preload:
            all_users = GetAllUsers()
        else:
            all_users = all_users_preload

        for uid, info in all_users.items():
            if info["name"].lower() == name.lower():
                return uid, info['email']
        return "User not found"

class GetSingleUserSlackNameArgs(BaseModel):
    id: str = Field(description="The Slack user ID")

class GetSingleUserSlackName(BaseTool):
    name: str = "gets_slack_name_single_user"
    description: str = "Gets the Slack real name of a user based on their Slack ID"
    args_schema: Type[BaseModel] = GetSingleUserSlackNameArgs

    def _run(self, id: str):
        if not all_users_preload or all_users_preload == {}:
            all_users = GetAllUsers()
        else:
            all_users = all_users_preload

        user = all_users.get(id)
        if user:
            return user["name"], user['email']
        return "User not found"

class MultiDMArgs(BaseModel):
    message: str
    user_ids: List[str]

class MultiDirectDMTool(BaseTool):
    name: str = "send_multiple_dms"
    description: str = "Sends direct messages to multiple Slack users"
    args_schema: Type[BaseModel] = MultiDMArgs

    def _run(self, message: str, user_ids: List[str]):
        results = {}
        for user_id in user_ids:
            try:
                client.chat_postMessage(channel=user_id, text=message)
                results[user_id] = "Message sent successfully"
            except SlackApiError as e:
                results[user_id] = f"Error: {e.response['error']}"
        return results

class DirectDMTool(BaseTool):
    name: str = "send_direct_dm"
    description: str = "Sends direct messages to Slack users"
    args_schema: Type[BaseModel] = DirectDMArgs

    def _run(self, message: str, user_id: str):
        try:
            client.chat_postMessage(channel=user_id, text=message)
            return "Message sent successfully"
        except SlackApiError as e:
            return f"Error sending message: {e.response['error']}"

def send_dm(user_id: str, message: str) -> bool:
    try:
        client.chat_postMessage(channel=user_id, text=message)
        return True
    except SlackApiError as e:
        print(f"Error sending DM: {e.response['error']}")
        return False

# Google Calendar Tools
PT = pytz.timezone('America/Los_Angeles')

def construct_google_calendar_client(team_id: str, user_id: str):
    token_data = load_token(team_id, user_id, 'google')
    if not token_data:
        return None
    creds = Credentials(
        token=token_data.get('access_token'),
        refresh_token=token_data.get('refresh_token'),
        token_uri="https://oauth2.googleapis.com/token",
        client_id=os.getenv("GOOGLE_CLIENT_ID"),
        client_secret=os.getenv("GOOGLE_CLIENT_SECRET"),
        scopes=["https://www.googleapis.com/auth/calendar"]
    )
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        token_data.update({
            "access_token": creds.token,
            "refresh_token": creds.refresh_token,
            "expires_at": creds.expiry.timestamp()
        })
        save_token(team_id, user_id, 'google', token_data)
    return build('calendar', 'v3', credentials=creds)

class GoogleCalendarList(BaseTool):
    name: str = "list_calendar_list"
    description: str = "Lists available calendars in the user's Google Calendar account"

    def _run(self, team_id: str, user_id: str, max_capacity: int = 200):
        calendar_service = construct_google_calendar_client(team_id, user_id)
        if not calendar_service:
            return "Google Calendar not configured or token invalid."

        all_calendars = []
        next_page_token = None
        capacity_tracker = 0

        while capacity_tracker < max_capacity:
            results = calendar_service.calendarList().list(
                maxResults=min(200, max_capacity - capacity_tracker),
                pageToken=next_page_token
            ).execute()
            calendars = results.get('items', [])
            all_calendars.extend(calendars)
            capacity_tracker += len(calendars)
            next_page_token = results.get('nextPageToken')
            if not next_page_token:
                break

        return [{
            'id': cal['id'],
            'name': cal['summary'],
            'description': cal.get('description', '')
        } for cal in all_calendars]

class GoogleCalendarEvents(BaseTool):
    name: str = "list_calendar_events"
    description: str = "Lists and gets events from a specific Google Calendar"

    def _run(self, team_id: str, user_id: str, calendar_id: str = "primary", max_capacity: int = 20):
        calendar_service = construct_google_calendar_client(team_id, user_id)
        if not calendar_service:
            return "Google Calendar not configured or token invalid."

        all_events = []
        next_page_token = None
        capacity_tracker = 0

        while capacity_tracker < max_capacity:
            results = calendar_service.events().list(
                calendarId=calendar_id,
                maxResults=min(250, max_capacity - capacity_tracker),
                pageToken=next_page_token
            ).execute()
            events = results.get('items', [])
            all_events.extend(events)
            capacity_tracker += len(events)
            next_page_token = results.get('nextPageToken')
            if not next_page_token:
                break

        return all_events

class GoogleCreateCalendar(BaseTool):
    name: str = "create_calendar_list"
    description: str = "Creates a new calendar in Google Calendar"

    def _run(self, team_id: str, user_id: str, calendar_name: str):
        calendar_service = construct_google_calendar_client(team_id, user_id)
        if not calendar_service:
            return "Google Calendar not configured or token invalid."

        calendar_body = {'summary': calendar_name}
        created_calendar = calendar_service.calendars().insert(body=calendar_body).execute()
        return f"Created calendar: {created_calendar['id']}"

class GoogleAddCalendarEventArgs(BaseModel):
    team_id: str = Field(description="Team id here")
    user_id: str = Field(description="User id here")

    calendar_id: str = Field(default="primary", description="Calendar ID (default 'primary')")
    summary: str = Field(description="Event title")
    description: str = Field(default="", description="Event description or agenda")
    start_time: str = Field(description="Start time in ISO 8601 format")
    end_time: str = Field(description="End time in ISO 8601 format")
    location: str = Field(default="", description="Event location")
    invite_link: str = Field(default="", description="Invite link for the meeting")
    guests: List[str] = Field(default=None, description="List of guest emails to invite")

class GoogleAddCalendarEvent(BaseTool):
    name: str = "google_add_calendar_event"
    description: str = "Creates an event in a Google Calendar"
    args_schema: Type[BaseModel] = GoogleAddCalendarEventArgs

    def _run(self, team_id: str, user_id: str, summary: str, start_time: str, end_time: str,
             description: str = "", calendar_id: str = 'primary', location: str = "",
             invite_link: str = "", guests: List[str] = None):
        calendar_service = construct_google_calendar_client(team_id, user_id)
        if not calendar_service:
            return "Google Calendar not configured or token invalid."

        if invite_link:
            description = f"{description}\nInvite Link: {invite_link}"

        event = {
            'summary': summary,
            'description': description,
            'start': {'dateTime': start_time, 'timeZone': 'America/Los_Angeles'},
            'end': {'dateTime': end_time, 'timeZone': 'America/Los_Angeles'},
            'location': location,
        }

        if guests:
            event['attendees'] = [{'email': guest} for guest in guests]

        try:
            created_event = calendar_service.events().insert(
                calendarId=calendar_id,
                body=event,
                sendUpdates='all'
            ).execute()
            return {
                "status": "success",
                "event_id": created_event['id'],
                "link": created_event.get('htmlLink', '')
            }
        except Exception as e:
            return {"status": "error", "message": str(e)}

class GoogleUpdateCalendarEventArgs(BaseModel):
    team_id: str = Field(description="Team id here")
    user_id: str = Field(description="User id here")
    calendar_id: str = Field(default="primary", description="Calendar ID (default 'primary')")
    event_id: str = Field(description="The event ID to update")
    summary: str = Field(default=None, description="Updated event title")
    description: Optional[str] = Field(default=None, description="Updated event description")
    start_time: Optional[str] = Field(default=None, description="Updated start time in ISO 8601 format")
    end_time: Optional[str] = Field(default=None, description="Updated end time in ISO 8601 format")
    location: Optional[str] = Field(default=None, description="Updated event location")
    invite_link: str = Field(default=None, description="Updated invite link")
    guests: List[str] = Field(default=None, description="Updated list of guest emails")

class GoogleUpdateCalendarEvent(BaseTool):
    name: str = "google_update_calendar_event"
    description: str = "Updates an existing event in a Google Calendar"
    args_schema: Type[BaseModel] = GoogleUpdateCalendarEventArgs

    def _run(self, team_id: str, user_id: str, event_id: str, calendar_id: str = "primary",
             summary: Optional[str] = None, description: Optional[str] = None,
             start_time: Optional[str] = None, end_time: Optional[str] = None,
             location: Optional[str] = None, invite_link: Optional[str] = None,
             guests: Optional[List[str]] = None):
        calendar_service = construct_google_calendar_client(team_id, user_id)
        if not calendar_service:
            return "Google Calendar not configured or token invalid."

        try:
            event = calendar_service.events().get(calendarId=calendar_id, eventId=event_id).execute()
        except Exception as e:
            return {"status": "error", "message": f"Event retrieval failed: {str(e)}"}

        if summary:
            event['summary'] = summary
        if description:
            event['description'] = description
        if invite_link:
            current_desc = event.get('description', '')
            event['description'] = f"{current_desc}\nInvite Link: {invite_link}"
        if start_time:
            event['start'] = {'dateTime': start_time, 'timeZone': 'America/Los_Angeles'}
        if end_time:
            event['end'] = {'dateTime': end_time, 'timeZone': 'America/Los_Angeles'}
        if location:
            event['location'] = location
        if guests is not None:
            event['attendees'] = [{'email': guest} for guest in guests]

        try:
            updated_event = calendar_service.events().update(
                calendarId=calendar_id,
                eventId=event_id,
                body=event
            ).execute()
            return {"status": "success", "event_id": updated_event['id']}
        except Exception as e:
            return {"status": "error", "message": f"Update failed: {str(e)}"}

class GoogleDeleteCalendarEventArgs(BaseModel):
    team_id: str = Field(description="Team id here")
    user_id: str = Field(description="User id here")
    calendar_id: str = Field(default="primary", description="Calendar ID (default 'primary')")
    event_id: str = Field(description="The event ID to delete")

class GoogleDeleteCalendarEvent(BaseTool):
    name: str = "google_delete_calendar_event"
    description: str = "Deletes an event from a Google Calendar"
    args_schema: Type[BaseModel] = GoogleDeleteCalendarEventArgs

    def _run(self, team_id: str, user_id: str, event_id: str, calendar_id: str = "primary"):
        calendar_service = construct_google_calendar_client(team_id, user_id)
        if not calendar_service:
            return "Google Calendar not configured or token invalid."
        try:
            calendar_service.events().delete(calendarId=calendar_id, eventId=event_id).execute()
            return {"status": "success", "message": f"Deleted event {event_id}"}
        except Exception as e:
            return {"status": "error", "message": f"Deletion failed: {str(e)}"}

# Search Events Tool
class SearchUserEventsArgs(BaseModel):
    user_id: str
    lookback_days: int = Field(default=30)

class SearchUserEventsTool(BaseTool):
    name: str = "search_events_by_user"
    description: str = "Finds calendar events associated with a specific user"
    args_schema: Type[BaseModel] = SearchUserEventsArgs

    def _run(self, team_id: str, user_id: str, lookback_days: int = 30):
        user_info = GetSingleUserSlackName().run(user_id)
        if user_info == "User not found":
            return []

        user_name, user_email = user_info
        events = GoogleCalendarEvents().run(team_id, user_id)

        now = datetime.now(pytz.UTC)
        relevant_events = []
        for event in events:
            event_time_str = event['start'].get('dateTime')
            if not event_time_str:
                continue

            event_time = datetime.fromisoformat(event_time_str)
            if event_time.tzinfo is None:
                event_time = pytz.UTC.localize(event_time)

            if (now - event_time).days > lookback_days:
                continue

            if user_name in event.get('summary', '') or user_name in event.get('description', ''):
                relevant_events.append({
                    'id': event['id'],
                    'title': event['summary'],
                    'time': event_time.strftime("%Y-%m-%d %H:%M"),
                    'calendar_id': event['organizer']['email']
                })
        return relevant_events

# Zoom Meeting Tool
class ZoomCreateMeetingArgs(BaseModel):
    team_id:str = Field(description="Team Id here")
    topic: str = Field(description="Meeting topic with all names not slack ids starting with U--")
    start_time: str = Field(description="Start time in ISO 8601 format")
    duration: int = Field(description="Duration in minutes")
    agenda: Optional[str] = Field(default="", description="Meeting agenda")
    timezone: str = Field(default="UTC", description="Timezone for the meeting")

class ZoomCreateMeetingTool(BaseTool):
    name: str = "create_zoom_meeting"
    description: str = "Creates a Zoom meeting using configured credentials"
    args_schema: Type[BaseModel] = ZoomCreateMeetingArgs

    def _run(self, team_id: str, topic: str, start_time: str, duration: int = 30,
             agenda: str = "", timezone: str = "UTC"):
        owner_id = get_workspace_owner_id(client,team_id)
        if not owner_id:
            return "Workspace owner not found"

        prefs = load_preferences(team_id, owner_id)
        zoom_config = prefs.get("zoom_config", {"mode": "manual", "link": None})

        if zoom_config["mode"] == "manual":
            link = zoom_config.get("link")
            if link:
                return f"Please join the meeting using this link: {link}"
            else:
                return "Manual Zoom link not configured"

        token_data = load_token(team_id, owner_id, 'zoom')
        if not token_data:
            return "Zoom token not found in database"

        access_token = token_data.get("access_token")
        if not access_token:
            return "Invalid Zoom token"

        expires_at = token_data.get("expires_at")
        if expires_at and time.time() > expires_at:
            refresh_token = token_data.get("refresh_token")
            if not refresh_token:
                return "Zoom token expired and no refresh token available"
            params = {
                "grant_type": "refresh_token",
                "refresh_token": refresh_token
            }
            auth_str = f"{ZOOM_CLIENT_ID}:{ZOOM_CLIENT_SECRET}"
            auth_bytes = base64.b64encode(auth_str.encode()).decode()
            headers = {
                "Authorization": f"Basic {auth_bytes}",
                "Content-Type": "application/x-www-form-urlencoded"
            }
            response = requests.post(ZOOM_TOKEN_API, data=params, headers=headers)
            if response.status_code == 200:
                new_token_data = response.json()
                token_data.update(new_token_data)
                token_data["expires_at"] = time.time() + new_token_data["expires_in"]
                save_token(team_id, owner_id, 'zoom', token_data)
                access_token = new_token_data["access_token"]
            else:
                return "Failed to refresh Zoom token"

        meeting_data = {
            "topic": topic,
            "type": 2,
            "start_time": start_time,
            "duration": duration,
            "timezone": timezone,
            "agenda": agenda,
            "settings": {
                "host_video": True,
                "participant_video": True,
                "join_before_host": False
            }
        }
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json"
        }
        meeting_res = requests.post(
            "https://api.zoom.us/v2/users/me/meetings",
            headers=headers,
            json=meeting_data
        )
        if meeting_res.status_code == 201:
            meeting_info = meeting_res.json()
            invitation = f"Join Zoom Meeting\n{meeting_info['join_url']}\nMeeting ID: {meeting_info['id']}\nPasscode: {meeting_info.get('password', '')}"
            return invitation
        else:
            return f"Zoom meeting creation failed: {meeting_res.text}"

# Microsoft Calendar Tools
class MicrosoftBaseTool(BaseTool):
    def get_microsoft_client(self, team_id: str, user_id: str):
        token_data = load_token(team_id, user_id, 'microsoft')
        if not token_data:
            return None, "Microsoft token not found in database"

        if time.time() > token_data['expires_at']:
            app = ConfidentialClientApplication(
                MICROSOFT_CLIENT_ID,
                authority=MICROSOFT_AUTHORITY,
                client_credential=MICROSOFT_CLIENT_SECRET
            )
            result = app.acquire_token_by_refresh_token(
                token_data['refresh_token'],
                scopes=MICROSOFT_SCOPES
            )
            if "access_token" not in result:
                return None, "Token refresh failed"
            token_data.update(result)
            save_token(team_id, user_id, 'microsoft', token_data)

        headers = {
            "Authorization": f"Bearer {token_data['access_token']}",
            "Content-Type": "application/json"
        }
        return headers, None

class MicrosoftListCalendarEvents(MicrosoftBaseTool):
    name: str = "microsoft_calendar_list_events"
    description: str = "Lists events from Microsoft Calendar"

    def _run(self, team_id: str, user_id: str, max_results: int = 10):
        headers, error = self.get_microsoft_client(team_id, user_id)
        if error:
            return error

        endpoint = "https://graph.microsoft.com/v1.0/me/events"
        params = {"$top": max_results, "$orderby": "start/dateTime desc"}
        response = requests.get(endpoint, headers=headers, params=params)
        if response.status_code != 200:
            return f"Error fetching events: {response.text}"

        events = response.json().get('value', [])
        return [{
            'id': e['id'],
            'subject': e.get('subject'),
            'start': e['start'].get('dateTime'),
            'end': e['end'].get('dateTime'),
            'webLink': e.get('webUrl')
        } for e in events]

class MicrosoftAddCalendarEventArgs(BaseModel):
    team_id: str = Field(description="Team id here")
    user_id: str = Field(description="User id here")
    subject: str = Field(description="Event title/subject")
    start_time: str = Field(description="Start time in ISO 8601 format")
    end_time: str = Field(description="End time in ISO 8601 format")
    content: str = Field(default="", description="Event description/content")
    location: str = Field(default="", description="Event location")
    attendees: List[str] = Field(default=[], description="List of attendee emails")

class MicrosoftAddCalendarEvent(MicrosoftBaseTool):
    name: str = "microsoft_calendar_add_event"
    description: str = "Creates an event in Microsoft Calendar"
    args_schema: Type[BaseModel] = MicrosoftAddCalendarEventArgs

    def _run(self, team_id: str, user_id: str, subject: str, start_time: str, end_time: str,
             content: str = "", location: str = "", attendees: List[str] = []):
        headers, error = self.get_microsoft_client(team_id, user_id)
        if error:
            return error

        event_payload = {
            "subject": subject,
            "body": {"contentType": "HTML", "content": content},
            "start": {"dateTime": start_time, "timeZone": "America/Los_Angeles"},
            "end": {"dateTime": end_time, "timeZone": "America/Los_Angeles"},
            "location": {"displayName": location},
            "attendees": [{"emailAddress": {"address": email}} for email in attendees]
        }

        response = requests.post(
            "https://graph.microsoft.com/v1.0/me/events",
            headers=headers,
            json=event_payload
        )
        if response.status_code == 201:
            return {
                "status": "success",
                "event_id": response.json()['id'],
                "link": response.json().get('webUrl')
            }
        return f"Error creating event: {response.text}"

class MicrosoftUpdateCalendarEventArgs(MicrosoftAddCalendarEventArgs):
    team_id: str = Field(description="Team id here")
    user_id: str = Field(description="User id here")
    event_id: str = Field(description="Microsoft event ID to update")

class MicrosoftUpdateCalendarEvent(MicrosoftBaseTool):
    name: str = "microsoft_calendar_update_event"
    description: str = "Updates an existing Microsoft Calendar event"
    args_schema: Type[BaseModel] = MicrosoftUpdateCalendarEventArgs

    def _run(self, team_id: str, user_id: str, event_id: str, **kwargs):
        headers, error = self.get_microsoft_client(team_id, user_id)
        if error:
            return error

        get_response = requests.get(
            f"https://graph.microsoft.com/v1.0/me/events/{event_id}",
            headers=headers
        )
        if get_response.status_code != 200:
            return f"Error finding event: {get_response.text}"

        existing_event = get_response.json()
        update_payload = {
            "subject": kwargs.get('subject', existing_event.get('subject')),
            "body": {
                "content": kwargs.get('content', existing_event.get('body', {}).get('content')),
                "contentType": "HTML"
            },
            "start": {
                "dateTime": kwargs.get('start_time', existing_event['start']['dateTime']),
                "timeZone": "America/Los_Angeles"
            },
            "end": {
                "dateTime": kwargs.get('end_time', existing_event['end']['dateTime']),
                "timeZone": "America/Los_Angeles"
            },
            "location": {"displayName": kwargs.get('location', existing_event.get('location', {}).get('displayName'))},
            "attendees": [{"emailAddress": {"address": email}} for email in
                          kwargs.get('attendees', [a['emailAddress']['address'] for a in existing_event.get('attendees', [])])]
        }

        response = requests.patch(
            f"https://graph.microsoft.com/v1.0/me/events/{event_id}",
            headers=headers,
            json=update_payload
        )
        if response.status_code == 200:
            return {"status": "success", "event_id": event_id}
        return f"Error updating event: {response.text}"

class MicrosoftDeleteCalendarEventArgs(BaseModel):
    team_id: str = Field(description="Team id here")
    user_id: str = Field(description="User id here")
    event_id: str = Field(description="Microsoft event ID to delete")

class MicrosoftDeleteCalendarEvent(MicrosoftBaseTool):
    name: str = "microsoft_calendar_delete_event"
    description: str = "Deletes an event from Microsoft Calendar"
    args_schema: Type[BaseModel] = MicrosoftDeleteCalendarEventArgs

    def _run(self, team_id: str, user_id: str, event_id: str):
        headers, error = self.get_microsoft_client(team_id, user_id)
        if error:
            return error

        response = requests.delete(
            f"https://graph.microsoft.com/v1.0/me/events/{event_id}",
            headers=headers
        )
        if response.status_code == 204:
            return {"status": "success", "message": f"Deleted event {event_id}"}
        return f"Error deleting event: {response.text}"

# Tool Lists
tools = [
    DirectDMTool(),
    ZoomCreateMeetingTool(),
    SearchUserEventsTool(),
    GoogleCalendarList(),
    GoogleCalendarEvents(),
    GoogleCreateCalendar(),
    GoogleAddCalendarEvent(),
    GoogleUpdateCalendarEvent(),
    GoogleDeleteCalendarEvent(),
    MicrosoftListCalendarEvents(),
    MicrosoftAddCalendarEvent(),
    MicrosoftUpdateCalendarEvent(),
    MicrosoftDeleteCalendarEvent(),
    MultiDirectDMTool()
]

calendar_prompt_tools = [
    MicrosoftListCalendarEvents(),
    GoogleCalendarEvents()
]

dm_tools = [
    DirectDMTool(),
    ZoomCreateMeetingTool(),
    SearchUserEventsTool(),
    GetSingleUserSlackName(),
    GetSingleUserSlackID(),
    GoogleCalendarList(),
    GoogleCalendarEvents(),
    GoogleCreateCalendar(),
    GoogleAddCalendarEvent(),
    GoogleUpdateCalendarEvent(),
    GoogleDeleteCalendarEvent(),
    MicrosoftListCalendarEvents(),
    MicrosoftAddCalendarEvent(),
    MicrosoftUpdateCalendarEvent(),
    MicrosoftDeleteCalendarEvent()
]

dm_group_tools = [
    GoogleCalendarEvents(),
    MicrosoftListCalendarEvents(),
    DateTimeTool(),
]