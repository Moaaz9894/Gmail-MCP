"""Gmail OAuth helper. Run `python auth_setup.py` once to create token.json."""
from pathlib import Path
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

SCOPES = [
    "https://www.googleapis.com/auth/gmail.modify",          # read, search, send, label
    "https://www.googleapis.com/auth/gmail.settings.basic",  # create Gmail filters
]
BASE = Path(__file__).parent
TOKEN = BASE / "token.json"
CREDS = BASE / "credentials.json"


def get_service(interactive: bool = False):
    creds = None
    if TOKEN.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN), SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        elif interactive:
            flow = InstalledAppFlow.from_client_secrets_file(str(CREDS), SCOPES)
            creds = flow.run_local_server(port=0)
        else:
            raise RuntimeError("Not authenticated. Run: python auth_setup.py")
        TOKEN.write_text(creds.to_json())
    return build("gmail", "v1", credentials=creds, cache_discovery=False)
