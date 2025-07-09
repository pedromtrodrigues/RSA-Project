import eventlet
eventlet.monkey_patch()

import json
import paho.mqtt.client as mqtt
from os import getenv
import time
import random
import math
import threading
from flask import Flask, render_template
from flask_socketio import SocketIO

flask_app = Flask(__name__, template_folder="templates")
socketio = SocketIO(flask_app, cors_allowed_origins="*")

# Variáveis de ambiente
rsu_id = int(getenv('RSU_ID'))
broker_ip = getenv('BROKER_IP')   # Vanetza local
mqtt_ip = getenv('MQTT_IP')       # Coordenação central

# Estado do sistema
victims = []
ongoing_victims = []
captured_victims = []
boat_positions = {}

# MQTT Clients
client_vanetza = mqtt.Client()
client_vanetza.connect(broker_ip, 1883, 60)

client_coord = mqtt.Client()
client_coord.connect(mqtt_ip, 1883, 60)

def publish_new_victim(victim_data):
    try:
        with open('in_denm.json', 'r') as f:
            m = json.load(f)
    except FileNotFoundError:
        return

    m["management"]["actionID"]["originatingStationID"] = rsu_id
    m["management"]["eventPosition"]["latitude"] = victim_data["position"][0]
    m["management"]["eventPosition"]["longitude"] = victim_data["position"][1]
    m["situation"]["eventType"]["causeCode"] = 2
    m["situation"]["informationQuality"] = 3
    m["management"]["validityDuration"] = 60  # importante para Vanetza transmitir

    payload = json.dumps(m)
    client_vanetza.publish("vanetza/in/denm", payload, retain=True)
    time.sleep(0.1)

def generate_victims():
    global victims
    number_of_victims = 10
    for i in range(number_of_victims):
        lat = random.uniform(40.61601, 40.61801)
        lon = random.uniform(-8.77769, -8.76308)
        victim = {"id": f"v{i+1}", "position": (lat, lon)}
        victims.append(victim)
        publish_new_victim(victim)

def on_message(client, userdata, msg):
    global victims, ongoing_victims, captured_victims, boat_positions
    topic = msg.topic
    data = json.loads(msg.payload.decode())

    if topic == "vanetza/out/cam":
        boat_id = data["stationID"]
        if (boat_id == 1) or (boat_id == 2) or (boat_id == 3):
            boat_positions[boat_id] = (data['latitude'], data['longitude'])
            print(f"[RSU] Position update from Boat {boat_id}")

    elif topic == "boat/claim_victim":
        boat_id = data["id"]
        victim_id = data["victim_id"]
        victim_pos = (data["victim_position"]["lat"], data["victim_position"]["lon"])

        already_claimed = any(v['id'] == victim_id for v, _ in ongoing_victims)
        already_captured = any(v['id'] == victim_id for v in captured_victims)

        if not already_claimed and not already_captured:
            v_data = next((v for v in victims if v['id'] == victim_id), None)
            if v_data:
                ongoing_victims.append((v_data, boat_id))
                print(f"[RSU] Boat {boat_id} claimed victim {victim_id}")
        else:
            print(f"[RSU] Boat {boat_id} tried to claim {victim_id}, but it's taken.")

    elif topic == "boat/found_victim":
        boat_id = data["id"]
        victim_id = data["victim_id"]
        print("Received found from boat",boat_id)

        for vt in list(ongoing_victims):
            v_data, assigned_boat = vt
            if v_data["id"] == victim_id and assigned_boat == boat_id:
                ongoing_victims.remove(vt)
                v_data["captured_by"] = boat_id
                captured_victims.append(v_data)
                print(f"[RSU] Victim {victim_id} captured by Boat {boat_id}")
                break
        else:
            print(f"[RSU] Received 'found_victim' for unknown or unassigned victim {victim_id}")

@flask_app.route('/')
def index():
    return render_template("index.html")

def emit_status():
    while True:
        socketio.emit("update", {
            "boats": boat_positions,
            "victims": [{"id": v["id"], "lat": v["position"][0], "lon": v["position"][1]} for v in victims],
            "ongoing_victims": [{"id": v["id"], "lat": v["position"][0], "lon": v["position"][1], "rescued_by": b} for v, b in ongoing_victims],
            "captured_victims": [{"id": v["id"], "lat": v["position"][0], "lon": v["position"][1], "captured_by": v.get("captured_by")} for v in captured_victims]
        })
        time.sleep(2)

# Subscreve CAM do Vanetza
client_vanetza.subscribe("vanetza/out/cam")
client_vanetza.on_message = on_message
client_vanetza.loop_start()

# Subscreve coordenação (claim, found)
client_coord.subscribe("boat/claim_victim")
client_coord.subscribe("boat/found_victim")
client_coord.on_message = on_message
client_coord.loop_start()

# Iniciar sistema
time.sleep(2)
generate_victims()
socketio.start_background_task(emit_status)
socketio.run(flask_app, host="0.0.0.0", port=8000)

# Loop principal (mantém vivo)
try:
    while True:
        pass
except KeyboardInterrupt:
    print("Exiting...")
    client_vanetza.loop_stop()
    client_coord.loop_stop()
