import requests
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request

SCOPES = ['https://www.googleapis.com/auth/photoslibrary.readonly']
TOKEN_FILE = 'token.json'

creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)
if creds.expired and creds.refresh_token:
    creds.refresh(Request())

headers = {'Authorization': f'Bearer {creds.token}'}
url = 'https://photoslibrary.googleapis.com/v1/albums'
params = {'pageSize': 50}

print(f"{'ALBUM NAME':<50} {'ID'}")
print('-' * 110)

while url:
    resp = requests.get('https://photoslibrary.googleapis.com/v1/albums', headers=headers, params=params)
    resp.raise_for_status()
    data = resp.json()
    for album in data.get('albums', []):
        print(f"{album.get('title', '(untitled)'):<50} {album['id']}")
    next_page = data.get('nextPageToken')
    params = {'pageSize': 50, 'pageToken': next_page} if next_page else None
    url = next_page
