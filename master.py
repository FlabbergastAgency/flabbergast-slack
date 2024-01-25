import slack_sdk
import os
from pathlib import Path
from dotenv import load_dotenv
from flask import Flask, request, Response, jsonify
from slackeventsapi import SlackEventAdapter
import webbrowser
from urllib.parse import urlparse, parse_qs, unquote, urlencode
import json
from zoomus import ZoomClient
import requests

env_path = Path('.') / '.env'
load_dotenv(dotenv_path=env_path)

app = Flask(__name__)
slack_event_adapter = SlackEventAdapter(os.environ['SIGNING_SECRET'], '/slack/events', app)

slack_client = slack_sdk.WebClient(token=os.environ['SLACK_TOKEN'])
BOT_ID = slack_client.api_call("auth.test")['user_id']

last_known_url = ""
active_slaves = {}


def ping_slave(ip):
    try:
        response = requests.get(f'http://{ip}:42096/ping', timeout=5)
        return response.status_code == 200
    except requests.RequestException:
        return False


def ping_all_slaves():
    inactive_slaves = []

    for id, data in active_slaves.items():
        ip, name = data
        response = ping_slave(ip)
        print(name, ip)
        if response:
            print(f"Slave {name} is active.")
        else:
            print(f"Slave {name} is not responding. Removing from active list.")
            inactive_slaves.append(id)

    for slave in inactive_slaves:
        del active_slaves[slave]


def create_button(room, action):
    return {
        "type": "button",
        "text": {
            "type": "plain_text",
            "text": room[1][1]
        },
        "action_id": action + ":" + room[0]
    }


def generate_blocks(title, channel_id, meeting_rooms, action):
    main = [
        {
            "type": "button",
            "text": {
                "type": "plain_text",
                "text": "Main Meeting Room"
            },
            "action_id": action + ":main"
        }
    ]
    blocks = [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": title
            }
        },
        {
            "type": "actions",
            "elements":
                main + [create_button(room, action) for room in meeting_rooms.items()]
        }
    ]

    message_payload = {
        "channel": channel_id,
        "blocks": blocks
    }

    return message_payload


@app.route('/slaves', methods=['GET'])
def get_active_slaves():
    ping_all_slaves()
    print(
        generate_blocks(
            "Select a meeting room where you want to open a link\n*Available Meeting Rooms:*",
            "#test",
            active_slaves,
            "open",
        )
    )
    return jsonify(active_slaves)


@app.route('/register', methods=['POST'])
def register_slave():
    data = request.json
    name = data.get('name')
    ip = data.get('ip')
    id = data.get('id')

    if name and ip:
        active_slaves[id] = (ip, name)
        print(active_slaves)
        print(f"Registered slave: {name} at {ip}")
        return "Registration successful", 200
    else:
        return "Invalid registration data", 400


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


def send_request_to_slave(path, data, url):
    # Make the POST request
    response = requests.post('http://' + url + ':42096' + path, data=data)

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


    ping_all_slaves()

    if 'zoom.us' in url:
        meeting_id, password = extract_zoom_info(url)
        url = build_zoommtg_url(meeting_id, password)

    last_know_url = url

    message_payload = generate_blocks(
        "Select a meeting room where you want to open a link\n*Available Meeting Rooms:*",
        channel_id,
        active_slaves,
        "open",
    )

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
        else:
            print(active_slaves[extracted_command[1]][1])
            send_request_to_slave('/createzoom', {'channel_id': channel_id}, active_slaves[extracted_command[1]][0])
    elif extracted_command[0] == 'open':
        if extracted_command[1] == 'main':
            open_url_local(last_know_url)
        else:
            print(active_slaves[extracted_command[1]][1])
            send_request_to_slave('/openurl', {'url': last_know_url}, active_slaves[extracted_command[1]][0])
        last_know_url = ""

    delete_message(channel_id, ts)

    return Response(), 200


@app.route('/createzoom', methods=['POST'])
def create_zoom():
    data = request.form
    channel_id = data.get('channel_id')

    ping_all_slaves()

    message_payload = generate_blocks(
        "Select a meeting room where you want to create a meeting\n*Available Meeting Rooms:*",
        channel_id,
        active_slaves,
        "create",
    )

    slack_client.chat_postMessage(**message_payload)
    return Response(), 200


if __name__ == "__main__":
    app.run(debug=True, host='0.0.0.0', port=42069)