import json
import paho.mqtt.client as mqtt
from os import getenv
import time
import threading
import math
# variaveis

boat_id = int(getenv('BOAT_ID'))
broker_ip =  getenv('BROKER_IP')
mqtt_ip = getenv('MQTT_IP')
raw_position = getenv('START_POINT') 
lat_str, lon_str = raw_position.split(',')
position = (float(lat_str), float(lon_str))
rsu_id = 4

known_victims = {}              # Vitimas ainda por "procurar"
other_boats_positions = {}      # Posições dos outros barcos
victims_claimed_by_others = {}  # Vitimas que os outros já "procuraram"

pos_thread = False
stop_thread = False
current_victim = None

client = mqtt.Client()
client.connect(broker_ip, 1883, 60)


client_coord = mqtt.Client()
client_coord.connect(mqtt_ip, 1883, 60)
     
def haversine(coord1, coord2):
    R = 6371000  # Raio da Terra em metros
    lat1, lon1 = coord1
    lat2, lon2 = coord2
    
    # Convertendo de graus para radianos
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)
    
    # Calculando a fórmula Haversine
    a = math.sin(delta_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    
    return R * c

def on_message(client, userdata, msg):
    global current_victim, stop_thread, known_victims, other_boats_positions, victims_claimed_by_others
    topic = msg.topic
    data = json.loads(msg.payload.decode())

    if topic == "vanetza/out/denm":
        #print("new victim",data) 
        denm = data["fields"]["denm"]
        management = denm["management"]
        position = management["eventPosition"]
        origin_id = management["actionID"]["originatingStationID"]

        lat = position["latitude"]
        lon = position["longitude"]
        victim_id = f"v{len(known_victims) + 1}"
        
        if(len(known_victims)==10):
            print(known_victims)

        if origin_id == rsu_id:
            if victim_id not in known_victims and victim_id not in victims_claimed_by_others:   
                known_victims[victim_id] = (lat, lon)
                # print(f"[Boat {boat_id}] Got new victim {victim_id} from RSU at {(lat, lon)}")
    
    elif topic == "vanetza/out/cam":
        other_boat_id = data["stationID"]
        if other_boat_id != boat_id:
            other_boats_positions[other_boat_id] = (data['latitude'],data['longitude'])

    elif topic == "boat/claim_victim":
        print("Claimed")
        claimed_victim_id = data["victim_id"]
        claiming_boat_id = data["id"]

        # para ver o que que os outros estão à procura
        if claiming_boat_id != boat_id:
            # Se a vitima a ser reclamada ainda está na lista de procuradas retira-a
            if claimed_victim_id in known_victims:
                del known_victims[claimed_victim_id]

            victims_claimed_by_others[claimed_victim_id] = claiming_boat_id
            #print(victims_claimed_by_others)
              
            if current_victim is not None and current_victim[1] ==  claimed_victim_id:
                print(f"[Boat {boat_id}] My assigned victim {claimed_victim_id} was claimed by {claiming_boat_id}. Stopping current movement.")
                current_victim = None 


def find_victims():

    global current_victim, known_victims, victims_claimed_by_others, position, stop_thread

    time.sleep(1)

    while not stop_thread:
        # se nao está a procura e ainda há vitimas 
        if current_victim is None and len(known_victims) > 0:
            best_victim_candidate = None
            min_dis_candidate = float('inf')

            for v in list(known_victims.keys()):
                lat = known_victims[v][0]
                long = known_victims[v][1]

                # se a vitima ja esta a ser procurada por outros passa para a proxima
                if v in victims_claimed_by_others:
                    continue
                    
                distance = haversine(position,(lat,long))

                if distance < min_dis_candidate:
                    best_victim_candidate = v
                    min_dis_candidate =  distance
            
           
            if (best_victim_candidate != None):
                candidate = known_victims[best_victim_candidate]
                
                lat = candidate[0]
                long = candidate[1]

                # Ver se é o mais proximo
                boat_id_closest,_ = find_closest_boat_to_victim((lat,long),boat_id,position,other_boats_positions)

                # se for o proprio avisa os outros
                if (boat_id_closest == boat_id):
                    claim_payload = json.dumps({
                        "id": boat_id, 
                        "victim_id": best_victim_candidate,
                        "victim_position": {"lat": lat, "lon": long}
                    })
                    client_coord.publish("boat/claim_victim", claim_payload)

                    # move
                    current_victim = ((lat,long),best_victim_candidate)
                    threading.Thread(target=boat_movement, args=(position, (lat,long), best_victim_candidate)).start()
                
                # elimina a vitima da propria lista de pessoas a procurar
                if best_victim_candidate in known_victims:
                    del known_victims[best_victim_candidate]

        
        time.sleep(5) # Intervalo para reavaliar a busca por vítimas

def find_closest_boat_to_victim(victim_pos, my_boat_id, my_position, all_other_boat_positions):
    closest_boat_id = None
    min_distance = float('inf')

    dist_to_my_boat = haversine(my_position, victim_pos)
    closest_boat_id = my_boat_id
    min_distance = dist_to_my_boat

    for other_id, other_pos in all_other_boat_positions.items():

        dist_to_other_boat = haversine(other_pos, victim_pos)

        if dist_to_other_boat < min_distance:
            min_distance = dist_to_other_boat
            closest_boat_id = other_id
        elif dist_to_other_boat == min_distance:
            if other_id < closest_boat_id:
                closest_boat_id = other_id
            
    return closest_boat_id, min_distance

# Enviar a posição à RSU e aos outros barcos
def send_position():
    global stop_thread
    while not stop_thread:
        #print(f"[Boat {boat_id}] Sending position {position}")
        with open('in_cam.json') as f:
            m = json.load(f)
        m["latitude"] = position[0]
        m["longitude"] = position[1]
        m["stationID"] = boat_id
        m = json.dumps(m)
        client.publish("vanetza/in/cam", m, retain=True)
        time.sleep(2)

def boat_movement(start_pos, target_pos, victim_id):
    global position, current_victim, stop_thread
    lat1, lon1 = start_pos
    lat2, lon2 = target_pos

    steps = 50 
    
    total_distance = haversine(start_pos, target_pos)
    sleep_per_step = (total_distance / 10.0) / steps if total_distance > 0 else 0.1
    sleep_per_step = max(0.1, min(sleep_per_step, 1.0)) 

    lat_step = (lat2 - lat1) / steps
    lon_step = (lon2 - lon1) / steps

    for i in range(steps):
        
        lat1 += lat_step
        lon1 += lon_step
        position = (lat1, lon1)
        time.sleep(sleep_per_step)  

    with open('in_cam.json') as f:
        cam_message = json.load(f)
        cam_message["latitude"] = position[0]
        cam_message["longitude"] = position[1]
        cam_message["stationID"] = boat_id
        client.publish("vanetza/in/cam", json.dumps(cam_message), retain=True)

    # Apenas publica se realmente chegou ao destino pretendido e a missão não foi interrompida
    payload = json.dumps({
        "victim_id": victim_id,
        "id": boat_id,
        "victim_position": {
            "lat": target_pos[0],
            "lon": target_pos[1]
        }
    })
    print("Sent found to RSU")
    client_coord.publish("boat/found_victim", payload) # Informa a RSU que encontrou
    print(f"[Boat {boat_id}] Reached and confirmed capture of victim {victim_id} at {target_pos}")
    
    current_victim = None # Resgate concluído ou interrompido, está livre para nova missão


client.subscribe("vanetza/out/denm") 

client.on_message = on_message
client.loop_start()     


client_coord.subscribe("boat/claim_victim")
client_coord.subscribe("boat/found_victim")

client_coord.on_message = on_message
client_coord.loop_start()


time.sleep(3)

# enviar a posição constatemente
position_thread = threading.Thread(target=send_position)
position_thread.daemon = True
position_thread.start()

coordination_thread = threading.Thread(target=find_victims)
coordination_thread.daemon = True
coordination_thread.start()

try:
    while True:
        pass
except KeyboardInterrupt:
    print("Exiting...")
    client.loop_stop()  # Stop the loop when exiting