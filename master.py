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


@app.route('/openurl', methods=['POST'])
def open_url():
    data = request.form
    parsed_data = data.get('text').split(' ')
    url = parsed_data[-1]

    # Parsing of the Zoom link
    if 'zoom.us' in url:
        meeting_id, password = extract_zoom_info(url)
        url = build_zoommtg_url(meeting_id, password)

    # Opening a link on a correct device
    if len(parsed_data) == 1 or parsed_data[0] in main_meeting_room_names:
        webbrowser.open(url)
        return Response(), 200

    elif parsed_data[0] in secondary_meeting_room_names:
        send_request_to_slave('/openurl', {'url': url})
        return Response(), 200

    else:
        text = "Wrong Meeting Room Name!!\nMain Meeting Room Names: " + str(main_meeting_room_names) +\
               "\nSecondary Meeting Room Names: " + str(secondary_meeting_room_names) + "\n"
        slack_client.chat_postMessage(channel=data.get('channel_id'), text=text)
        return Response(), 200


@app.route('/createzoom', methods=['POST'])
def create_zoom():
    data = request.form
    channel_id = data.get('channel_id')
    selected_meeting_room = data.get('text')

    # Creating a new Zoom meeting on a right device
    if selected_meeting_room == "" or selected_meeting_room in main_meeting_room_names:
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

        return Response(), 200

    elif selected_meeting_room in secondary_meeting_room_names:
        send_request_to_slave('/createzoom', {'channel_id': channel_id})
        return Response(), 200

    else:
        text = "Wrong Meeting Room Name!!\nMain Meeting Room Names: " + str(main_meeting_room_names) +\
               "\nSecondary Meeting Room Names: " + str(secondary_meeting_room_names) + "\n"
        slack_client.chat_postMessage(channel=data.get('channel_id'), text=text)
        return Response(), 200


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=42069)