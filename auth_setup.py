from gmail_auth import get_service

svc = get_service(interactive=True)
print("Authenticated as:", svc.users().getProfile(userId="me").execute()["emailAddress"])
