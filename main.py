import slack_sdk
import os
from pathlib import Path
from dotenv import load_dotenv
from flask import Flask, request, Response
from slackeventsapi import SlackEventAdapter
import webbrowser
from urllib.parse import urlparse, parse_qs, unquote, urlencode
import datetime
import json
from zoomus import ZoomClient

env_path = Path('.') / '.env'
load_dotenv(dotenv_path=env_path)

app = Flask(__name__)
slack_event_adapter = SlackEventAdapter(os.environ['SIGNING_SECRET'], '/slack/events', app)

slack_client = slack_sdk.WebClient(token=os.environ['SLACK_TOKEN'])
BOT_ID = slack_client.api_call("auth.test")['user_id']


def extract_zoom_info(zoom_url):
    parsed_url = urlparse(zoom_url)

    # If the URL is a Google link, extract the actual Zoom link from the 'q' parameter
    if parsed_url.netloc == 'www.google.com' and 'q' in parse_qs(parsed_url.query):
        zoom_url = unquote(parse_qs(parsed_url.query)['q'][0])

    parsed_zoom_url = urlparse(zoom_url)
    query_params = parse_qs(parsed_zoom_url.query)

    meeting_id_index = zoom_url.find('zoom.us/j/') + 10
    meeting_id = zoom_url[meeting_id_index:].split('?')[0]

    password = query_params.get('pwd', [''])[0]

    return meeting_id, password


def build_zoommtg_url(meeting_number, password):
    base_url = "zoommtg://zoom.us/join"
    params = {
        "action": "join",
        "confno": meeting_number,
        "pwd": password
    }

    zoommtg_url = f"{base_url}?{urlencode(params)}"
    return zoommtg_url


@app.route('/openurl', methods=['POST'])
def open_url():
    data = request.form
    url = data.get('text')
    webbrowser.open(url)
    return Response(), 200


@app.route('/openzoom', methods=['POST'])
def open_zoom():
    data = request.form
    meeting_id, password = extract_zoom_info(data.get('text'))
    url = build_zoommtg_url(meeting_id, password)
    webbrowser.open(url)
    return Response(), 200


@app.route('/createzoom', methods=['POST'])
def create_zoom():
    data = request.form

    # Replace with your actual Zoom credentials
    client_id = os.environ['client_id']
    client_secret = os.environ['client_secret']
    account_id = os.environ['account_id']

    # Create a client
    client = ZoomClient(client_id, client_secret, account_id)

    # List all users
    user_list_response = client.user.list()
    user_list = json.loads(user_list_response.content)

    # Selecta a user
    user_id = user_list['users'][1]['id']

    # Create the meeting
    meeting_response = client.meeting.create(user_id=user_id, type=1)
    meeting_info = json.loads(meeting_response.content)

    # Print the meeting information
    print(meeting_info)

    # Get the meeting join url
    join_url = meeting_info['join_url']
    start_url = meeting_info['start_url']

    # Start a Zoom and paste a link in channel
    open_zoom(start_url)
    slack_client.chat_postMessage(channel=data.get('channel_id'), text=join_url)

    return Response(), 200


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=42069)