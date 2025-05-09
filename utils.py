from datetime import datetime
from slack_sdk.errors import SlackApiError
import logging
logger  = logging.getLogger(__name__)
def get_user_timezone(client, user_id, default_tz="America/Los_Angeles"):
    try:
        response = client.users_info(user=user_id)
        tz = response["user"].get("tz")
        return tz if tz else default_tz
    except SlackApiError as e:
        logger.error(f"Timezone error: {e.response['error']}")
        return default_tz
    

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
    
from datetime import datetime

# def format_calendar_events(calendar_events):
#     """
#     Formats Google Calendar events from a list of dictionaries into a clean, structured string for an LLM,
#     filtering to include only events starting on or after the current date.

#     Args:
#         calendar_events (list): A list of dictionaries, each representing a Google Calendar event.

#     Returns:
#         str: A formatted string with event details, sorted by start time, for events on or after today.
#     """
#     # Validate input
#     if not isinstance(calendar_events, list):
#         return "Error: Calendar events must be provided as a list."

#     # Get current date (March 20, 2025, as per system context)
#     current_date = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)

#     # Filter events starting on or after current date and sort by start time
#     try:
#         filtered_events = [
#             event for event in calendar_events
#             if datetime.strptime(event['start']['dateTime'], '%Y-%m-%dT%H:%M:%S%z') >= current_date
#         ]
#         filtered_events.sort(key=lambda e: datetime.strptime(e['start']['dateTime'], '%Y-%m-%dT%H:%M:%S%z'))
#     except (KeyError, ValueError, TypeError) as e:
#         return f"Error: Unable to process events due to invalid data - {str(e)}"

#     formatted_events = []
#     for event in filtered_events:
#         # Extract event name
#         event_name = event.get('summary', 'Untitled Event')

#         # Extract date and timezone
#         start_time = event.get('start', {}).get('dateTime', 'Unknown')
#         end_time = event.get('end', {}).get('dateTime', 'Unknown')
#         timezone = event.get('start', {}).get('timeZone', 'Unknown')

#         # Extract meeting members
#         organizer_email = event.get('organizer', {}).get('email', 'Unknown')
#         attendees = event.get('attendees', [])
#         member_emails = set([organizer_email])
#         if isinstance(attendees, list):
#             for attendee in attendees:
#                 member_emails.add(attendee.get('email', 'Unknown'))
#         members_str = ', '.join(sorted(member_emails))

#         # Format the event details
#         formatted = (
#             f"Event: {event_name}\n"
#             f"Start: {start_time}\n"
#             f"End: {end_time}\n"
#             f"Timezone: {timezone}\n"
#             f"Members: {members_str}"
#         )
#         formatted_events.append(formatted)

#     # Combine all events with a separator
#     return "\n---\n".join(formatted_events) if formatted_events else "No upcoming events found after March 20, 2025."
from datetime import datetime
from dateutil import tz

def get_event_datetimes(event):
    """
    Helper function to extract start and end datetimes from a Google Calendar event,
    handling both timed events and all-day events.
    """
    start = event.get('start', {})
    end = event.get('end', {})
    # Handle timed events with 'dateTime'
    # print(f"CalendarStartBa: {start}")
    if 'dateTime' in start:
        try:
            start_dt = datetime.strptime(start['dateTime'], '%Y-%m-%dT%H:%M:%S%z')
            end_dt = datetime.strptime(end['dateTime'], '%Y-%m-%dT%H:%M:%S%z') if 'dateTime' in end else None
            return start_dt, end_dt
        except ValueError:
            return None, None
    # Handle all-day events with 'date'
    elif 'date' in start:
        try:
            start_date = datetime.strptime(start['date'], '%Y-%m-%d').date()
            timezone_str = start.get('timeZone', 'UTC')
            tz_obj = tz.gettz(timezone_str) or tz.gettz('UTC')
            start_dt = datetime.combine(start_date, datetime.min.time(), tzinfo=tz_obj)
            end_dt = None
            if 'date' in end:
                end_date = datetime.strptime(end['date'], '%Y-%m-%d').date()
                end_dt = datetime.combine(end_date, datetime.min.time(), tzinfo=tz_obj)
            return start_dt, end_dt
        except ValueError:
            return None, None
    return None, None

def format_calendar_events(calendar_events, owner_timezone):
    """
    Formats Google Calendar events from a list of dictionaries into a clean, structured string for an LLM,
    filtering to include only events starting on or after the current date and time.

    Args:
        calendar_events (list): A list of dictionaries, each representing a Google Calendar event.

    Returns:
        str: A formatted string with event details, sorted by start time, for events on or after now.
    """
    # Validate input
    if not isinstance(calendar_events, list):
        return "Error: Calendar events must be provided as a list."

    # Get current date and time in local timezone as a timezone-aware object
    local_tz = tz.tzlocal()
    current_datetime = datetime.now(tz.gettz(owner_timezone))

    # Filter events starting on or after current date and time, and sort by start time
    filtered_events = []
    for event in calendar_events:
        start_dt, _ = get_event_datetimes(event)
        # print(f"Current: {current_datetime}, StartT:  {start_dt}")
        if start_dt and start_dt >= current_datetime:
            # print(f"Single Filtered event: {event}")
            filtered_events.append(event)
    filtered_events.sort(key=lambda e: get_event_datetimes(e)[0])

    # Format the filtered events
    formatted_events = []
    for event in filtered_events:
        start_dt, end_dt = get_event_datetimes(event)
        event_name = event.get('summary', 'Untitled Event')
        start_str = start_dt.isoformat() if start_dt else 'Unknown'
        end_str = end_dt.isoformat() if end_dt else 'Unknown'
        timezone = event.get('start', {}).get('timeZone', 'Unknown')
        organizer_email = event.get('organizer', {}).get('email', 'Unknown')
        attendees = event.get('attendees', [])
        member_emails = set([organizer_email])
        if isinstance(attendees, list):
            for attendee in attendees:
                member_emails.add(attendee.get('email', 'Unknown'))
        members_str = ', '.join(sorted(member_emails))
        formatted = (
            f"Event: {event_name}\n"
            f"Start: {start_str}\n"
            f"End: {end_str}\n"
            f"Timezone: {timezone}\n"
            f"Members: {members_str}"
        )
        formatted_events.append(formatted)
        # print(f"Formatted events: {formatted_events}")
    return formatted_events if formatted_events else "No upcoming events found after the current date and time."
from datetime import datetime
import re
from slack_sdk.errors import SlackApiError

# def get_mentions_from_history(client, channel_id, bot_user_id=None, limit=5):
#     """
#     Fetches the last N messages from a Slack channel and extracts mentions from the latest message using regex.

#     Args:
#         client: Slack WebClient instance to interact with Slack API.
#         channel_id (str): The ID of the Slack channel to fetch history from.
#         bot_user_id (str): The bot's user ID to exclude from mentions (optional).
#         limit (int): Number of past messages to retrieve (default is 2).

#     Returns:
#         str: A formatted string of Slack user IDs mentioned in the latest message,
#              e.g., "<@U12345>\n<@U67890>" or "No mentions found."
#     """
#     # Fetch the last N messages from the channel
#     try:
#         history_response = client.conversations_history(channel=channel_id, limit=limit)
#         messages = history_response.get("messages", [])
#     except SlackApiError as e:
#         logger.error(f"Error fetching channel history for channel {channel_id}: {e}")
#         return "No mentions found."

#     if not messages:
#         return "No mentions found."

#     # Clean the history similar to format_channel_history
#     cleaned_history = []
#     for msg in messages:
#         if 'bot_id' in msg and 'Calendar provider updated' in msg.get('text', ''):
#             continue
#         sender = msg.get('user', 'Unknown') if 'bot_id' not in msg else msg.get('bot_profile', {}).get('name', 'Bot')
#         message_text = msg.get('text', '').strip()
#         timestamp = float(msg.get('ts', 0))
#         readable_time = datetime.fromtimestamp(timestamp).strftime('%Y-%m-%d %I:%M %p')
#         user_id = msg.get('user', 'N/A')
#         team_id = msg.get('team', 'N/A')
#         cleaned_history.append({
#             'message': message_text,
#             'from': sender,
#             'timestamp': readable_time,
#             'user_team': f"{user_id}/{team_id}"
#         })

#     # Get the latest message (first in reverse chronological order)
#     latest_message = cleaned_history[0]['message']

#     # Extract mentions using regex
#     mentions = re.findall(r'<@(\w+)>', latest_message)

#     # Filter out the bot's user ID if provided
#     if bot_user_id and mentions:
#         mentions = [m for m in mentions if m != bot_user_id]

#     # Format mentions back into Slack mention syntax
#     if mentions:
#         formatted_mentions = "\n".join([f"<@{mention}>" for mention in mentions])
#         return formatted_mentions
#     return "No mentions found."

def get_mentions_from_history(client, channel_id, bot_user_id=None, limit=5):
    """
    Fetches the last N messages from a Slack channel and extracts mentions from the latest message using regex.

    Args:
        client: Slack WebClient instance to interact with Slack API.
        channel_id (str): The ID of the Slack channel to fetch history from.
        bot_user_id (str): The bot's user ID to exclude from mentions (optional).
        limit (int): Number of past messages to retrieve (default is 5).

    Returns:
        str: A formatted string of Slack user IDs mentioned in the latest message,
             e.g., "<@U12345>\n<@U67890>" or "No mentions found."
    """
    # Fetch the last N messages from the channel
    try:
        history_response = client.conversations_history(channel=channel_id, limit=limit)
        messages = history_response.get("messages", [])
    except SlackApiError as e:
        logger.error(f"Error fetching channel history for channel {channel_id}: {e}")
        return "No mentions found."

    if not messages:
        return "No mentions found."

    # Process messages to find the latest non-excluded message
    for msg in messages:
        # Skip bot messages containing 'Calendar provider updated'
        if 'bot_id' in msg and 'Calendar provider updated' in msg.get('text', ''):
            continue
        # Get the message text from the first non-excluded message
        message_text = msg.get('text', '').strip()

        # Extract mentions using regex (e.g., <@U12345>)
        mentions = re.findall(r'<@\w+>', message_text)

        # Exclude the bot's own mention if bot_user_id is provided
        if bot_user_id:
            bot_mention = f"<@{bot_user_id}>"
            mentions = [m for m in mentions if m != bot_mention]

        # Remove duplicates while preserving order
        unique_mentions = list(dict.fromkeys(mentions))

        # Return formatted mentions or "No mentions found."
        if unique_mentions:
            return "\n".join(unique_mentions)
        else:
            return "No mentions found."

    # If all messages were excluded
    return "No mentions found."
