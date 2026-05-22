"""
Run this script ONCE locally to get your YouTube refresh token.

Usage:
    pip install google-auth-oauthlib
    python video/get_refresh_token.py --secrets path/to/client_secrets.json

A browser window will open. Log in with the Google account that owns your
YouTube channel, then grant permission. The script prints the three values
you need to add as GitHub repository secrets.
"""

import argparse
import sys

def main():
    try:
        from google_auth_oauthlib.flow import InstalledAppFlow
    except ImportError:
        print("Missing dependency. Run:  pip install google-auth-oauthlib")
        sys.exit(1)

    ap = argparse.ArgumentParser()
    ap.add_argument("--secrets", default="client_secrets.json",
                    help="Path to client_secrets.json downloaded from Google Cloud Console")
    args = ap.parse_args()

    SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]

    flow = InstalledAppFlow.from_client_secrets_file(args.secrets, SCOPES)
    creds = flow.run_local_server(port=0)

    print("\n" + "=" * 60)
    print("Add these three values as GitHub repository secrets:")
    print("  Settings → Secrets and variables → Actions → New secret")
    print("=" * 60)
    print(f"\nYOUTUBE_CLIENT_ID\n{creds.client_id}")
    print(f"\nYOUTUBE_CLIENT_SECRET\n{creds.client_secret}")
    print(f"\nYOUTUBE_REFRESH_TOKEN\n{creds.refresh_token}")
    print("\n" + "=" * 60)

if __name__ == "__main__":
    main()
