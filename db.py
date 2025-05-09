import os
import psycopg2
from dotenv import load_dotenv

load_dotenv()

def init_db():
    """
    Initialize the Neon Postgres database by creating the necessary tables for multi-workspace support:
    - Installations: Stores Slack workspace installation data.
    - Users: Stores Slack user information with team_id, user_id, and workspace_name.
    - Preferences: Stores user-specific preferences with team_id and user_id.
    - Tokens: Stores authentication tokens with team_id, user_id, and service.
    Prerequisites: 'DATABASE_URL' environment variable must be set with Neon Postgres connection string.
    """
    conn = psycopg2.connect(os.getenv('DATABASE_URL'))
    cur = conn.cursor()
    
    # Create Installations table for OAuth installation data
    cur.execute('''
        CREATE TABLE IF NOT EXISTS Installations (
            workspace_id TEXT PRIMARY KEY,         -- Slack workspace ID (team_id)
            installation_data JSONB,               -- Installation data stored as JSON
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP  -- Last update timestamp
        )
    ''')
    
    # Create Users table with composite primary key (team_id, user_id) and workspace_name
    cur.execute('''
        CREATE TABLE IF NOT EXISTS Users (
            team_id TEXT,                         -- Slack workspace ID
            user_id TEXT,                         -- Slack user ID
            workspace_name TEXT,                  -- Name of the workspace
            real_name TEXT,                       -- User's real name from Slack
            email TEXT,                           -- User's email from Slack
            name TEXT,                            -- User's Slack handle
            is_owner BOOLEAN,                     -- Indicates if user is workspace owner
            last_updated TIMESTAMP,               -- Last time user data was updated
            PRIMARY KEY (team_id, user_id)        -- Composite key for uniqueness across workspaces
        )
    ''')
    
    # Create Preferences table with composite primary key and foreign key
    cur.execute('''
        CREATE TABLE IF NOT EXISTS Preferences (
            team_id TEXT,                         -- Slack workspace ID
            user_id TEXT,                         -- Slack user ID
            zoom_config JSONB,                    -- Zoom configuration stored as JSON
            calendar_tool TEXT,                   -- Selected calendar tool (e.g., google, microsoft)
            updated_at TIMESTAMP,                 -- Last update timestamp
            PRIMARY KEY (team_id, user_id),       -- Composite key for uniqueness
            CONSTRAINT fk_user
                FOREIGN KEY(team_id, user_id)     -- References Users table
                REFERENCES Users(team_id, user_id)
                ON DELETE CASCADE                 -- Delete preferences if user is deleted
        )
    ''')
    
    # Create Tokens table with composite primary key and foreign key
    cur.execute('''
        CREATE TABLE IF NOT EXISTS Tokens (
            team_id TEXT,                         -- Slack workspace ID
            user_id TEXT,                         -- Slack user ID
            service TEXT,                         -- Service name (google, microsoft, zoom)
            token_data JSONB,                     -- Token data stored as JSON
            updated_at TIMESTAMP,                 -- Last update timestamp
            PRIMARY KEY (team_id, user_id, service),  -- Composite key ensures one token per service per user per workspace
            CONSTRAINT fk_user
                FOREIGN KEY(team_id, user_id)     -- References Users table
                REFERENCES Users(team_id, user_id)
                ON DELETE CASCADE                 -- Delete tokens if user is deleted
        )
    ''')
    
    conn.commit()
    cur.close()
    conn.close()

if __name__ == '__main__':
    init_db()
    print('Neon Postgres database initialized successfully.')