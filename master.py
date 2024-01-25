import slack_sdk
import os
from pathlib import Path
from dotenv import load_dotenv
from flask import Flask, request, Response
from slackeventsapi import SlackEventAdapter
import webbrowser
from urllib.parse import urlparse, parse_qs, unquote, urlencode
import json
from zoomus import ZoomClient
import requests

main_meeting_room_names = ['1', 'big', 'main']
secondary_meeting_room_names = ['2', 'small', 'secondary']

env_path = Path('.') / '.env'
load_dotenv(dotenv_path=env_path)

app = Flask(__name__)
slack_event_adapter = SlackEventAdapter(os.environ['SIGNING_SECRET'], '/slack/events', app)

slack_client = slack_sdk.WebClient(token=os.environ['SLACK_TOKEN'])
BOT_ID = slack_client.api_call("auth.test")['user_id']

last_know_url = ""


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


def send_request_to_slave(path, data):
    # Make the POST request
    response = requests.post('http://192.168.1.83:42096' + path, data=data)

    # Check the status code of the response
    if response.status_code == 200:
        print("POST request was successful!")
        print("Response:", response.text)
    else:
        print(f"POST request failed with status code {response.status_code}")
        print("Response:", response.text)


def open_url_local(url):
    webbrowser.open(url)


@app.route('/openurl', methods=['POST'])
def open_url():
    global last_know_url
    data = request.form
    parsed_data = data.get('text').split(' ')
    channel_id = data.get('channel_id')
    url = parsed_data[-1]

    # Parsing of the Zoom link
    if 'zoom.us' in url:
        meeting_id, password = extract_zoom_info(url)
        url = build_zoommtg_url(meeting_id, password)

    last_know_url = url

    message_payload = {
        "channel": channel_id,
        "blocks": [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": "Select a meeting room where you want to open a link\n*Available Meeting Rooms:*"
                }
            },
            {
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {
                            "type": "plain_text",
                            "text": "Main Meeting Room"
                        },
                        "action_id": "open:main"
                    },
                    {
                        "type": "button",
                        "text": {
                            "type": "plain_text",
                            "text": "Secondary Meeting Room"
                        },
                        "action_id": "open:secondary"
                    }
                ]
            }
        ]
    }

    slack_client.chat_postMessage(**message_payload)

    return Response(), 200


def create_zoom_local(channel_id):
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
    webbrowser.open(start_url)

    slack_client.chat_postMessage(channel=channel_id, text="Big Meeting Room URL:\n" + join_url)


def delete_message(channel_id, ts):
    delete_payload = {
        "channel": channel_id,
        "ts": ts,
    }

    slack_client.chat_delete(**delete_payload)


@app.route('/interaction', methods=["POST"])
def slack_interactive():
    global last_know_url
    payload = request.form.get("payload")

    data = json.loads(payload)
    channel_id = data["channel"]["id"]
    action_id = data["actions"][0]["action_id"]
    ts = data["message"]["ts"]

    extracted_command = action_id.split(':')

    if extracted_command[0] == 'create':
        if extracted_command[1] == 'main':
            create_zoom_local(channel_id)
        elif extracted_command[1] == 'secondary':
            send_request_to_slave('/createzoom', {'channel_id': channel_id})
    elif extracted_command[0] == 'open':
        if extracted_command[1] == 'main':
            open_url_local(last_know_url)
        elif extracted_command[1] == 'secondary':
            send_request_to_slave('/openurl', {'url': last_know_url})
        last_know_url = ""

    delete_message(channel_id, ts)

    return Response(), 200


@app.route('/createzoom', methods=['POST'])
def create_zoom():
    data = request.form
    channel_id = data.get('channel_id')

    message_payload = {
        "channel": channel_id,
        "blocks": [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": "Select a meeting room where you want to create a meeting\n*Available Meeting Rooms:*"
                }
            },
            {
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {
                            "type": "plain_text",
                            "text": "Main Meeting Room"
                        },
                        "action_id": "create:main"
                    },
                    {
                        "type": "button",
                        "text": {
                            "type": "plain_text",
                            "text": "Secondary Meeting Room"
                        },
                        "action_id": "create:secondary"
                    }
                ]
            }
        ]
    }

    slack_client.chat_postMessage(**message_payload)
    return Response(), 200


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=42069)