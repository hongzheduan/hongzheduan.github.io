"""
Run this once locally to generate a YouTube OAuth2 refresh token.
Store the printed values as GitHub secrets.
"""

from google_auth_oauthlib.flow import InstalledAppFlow
import json

SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]

flow = InstalledAppFlow.from_client_secrets_file("client_secrets.json", SCOPES)
creds = flow.run_local_server(port=0)

client_data = json.load(open("client_secrets.json"))["installed"]

print("\n=== Add these as GitHub repository secrets ===")
print(f"YOUTUBE_CLIENT_ID:     {client_data['client_id']}")
print(f"YOUTUBE_CLIENT_SECRET: {client_data['client_secret']}")
print(f"YOUTUBE_REFRESH_TOKEN: {creds.refresh_token}")
print("==============================================\n")
