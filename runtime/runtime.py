import subprocess, multiprocessing, time
from threading import Thread
import memcache, ansible, hibike
from grizzly import *
import usb
import os

#####
# Connect to memcached
#####
memcache_port = 12357
mc = memcache.Client(['127.0.0.1:%d' % memcache_port])
mc.set('gamepad', {'0': {'axes': [0,0,0,0], 'buttons': [0]*17, 'connected': None, 'mapping': None}})
mc.set('motor_values', [])
mc.set('servo_values', {})
mc.set('flag_values', [False, False, False, False])
mc.set('PID_constants',[("P", 0.5), ("I", 0), ("D", 0)])
mc.set('control_mode', ["default", "all"])
mc.set('drive_mode', ["brake", "all"])
mc.set('drive_distance', [])
mc.set('metal_detector_calibrate', [False,False])
mc.set('toggle_light', None)
mc.set("spec_pid", [])
mc.set("encoder_distance", {})
mc.set('game', {'autonomous': False, 'enabled': True})

#####
# Connect to hibike
#####
if 'HIBIKE_SIMULATOR' in os.environ and os.environ['HIBIKE_SIMULATOR'] in ['1', 'True', 'true']:
    import hibike_simulator
    h = hibike_simulator.Hibike()
else:
    h = hibike.Hibike()

#####
# Global variables
#####
student_proc, console_proc = None, None
robot_status = 0 # a boolean for whether or not the robot is executing
naming_map_filename = 'student_code/CustomID.txt'

#####
# Constant mappings for student code info
#####
gear_to_tick = {19: 1200.0/360, 67: 4480.0/360}
all_modes = {
    "default": ControlMode.NO_PID,
    "speed": ControlMode.SPEED_PID,
    "position": ControlMode.POSITION_PID,
    "brake": DriveMode.DRIVE_BRAKE,
    "coast": DriveMode.DRIVE_COAST
    }
PID_constants = {"P": 1, "I": 0, "D": 0}

#####
# Hibike device code
#####
connectedDevices = [] #list of tuples, first val of tuple is UID, second is int Devicetype
uid_to_type = {}
id_to_name = {}

def enumerate_hibike():
    global connectedDevices, uid_to_type
    connectedDevices = h.getEnumeratedDevices()
    uid_to_type = {uid: device_type for (uid, device_type) in connectedDevices}
    h.subToDevices([(device, 50) for (uid, device_type) in connectedDevices])
    print("Connected to", connectedDevices)

    init_battery() # Battery is mandatory!
    init_flag()

def update_hibike():
    global connectedDevices, uid_to_type, id_to_name
    connectedDevices = h.getEnumeratedDevices()

    for uid in uid_to_type.keys():  #check for disconnect
        if not (uid, uid_to_type[uid]) in connectedDevices:
            del uid_to_type[uid]
            del id_to_name[uid]

    for (uid, device_type) in connectedDevices: #check for connect
        if not uid in uid_to_type:
            uid_to_type[uid] = device_type
            h.subToDevices([(uid, 50)])
            print("Connected to", (uid, device_type))
            
    #battery and flag?
    
def uid_to_device_id(uid, num_devices):
    return [ str(uid)+str(device_index) for device_index in range(1,1+num_devices)]

def device_id_to_uid(device_id):
    return int(device_id[:-1])

def device_id_to_index(device_id):
    return int(device_id[-1:]) - 1

def read_naming_map():
    global id_to_name, naming_map_filename

    if not os.path.exists(naming_map_filename):
        return

    with open(naming_map_filename, "r") as f:
        for line in f.readlines():
            line = line.strip()
            device_id, name = line.split(" ", 1)
            id_to_name[device_id] = name

def write_naming_map():
    global id_to_name, naming_map_filename
    if not os.path.exists(os.path.dirname(naming_map_filename)):
        try:
            os.makedirs(os.path.dirname(naming_map_filename))
        except OSError as exc: # Guard against race condition
            if exc.errno != errno.EEXIST:
                raise

    with open(naming_map_filename, "w") as f:
        for id, name in id_to_name.items():
            f.write(id + " " + name + "\n")

def device_id_set_name(device_id, name):
    id_to_name[device_id] = name
    write_naming_map()

def device_id_get_name(device_id):
    if device_id not in id_to_name:
        if device_id.startswith('motor'):
            device_id_set_name(device_id, device_id)
        else:
            device_id_set_name(device_id, 'sensor_' + device_id)

    return id_to_name[device_id]

def get_all_data(connectedDevices):
    global all_servos
    all_data = {}
    for uid, device_type in connectedDevices:
        if uid == battery_UID: # battery value testing is special-cased
            continue
        tup_nest = h.getData(uid, "dataUpdate")
        if h.getDeviceName(int(device_type)) == "ColorSensor":
            #special case for color sensors
            color_data = h.getData(uid, "dataUpdate")[0]
            lum = max(float(color_data[3]), 1)
            red = int(color_data[0] / lum * 256)
            green = int(color_data[1] / lum * 256)
            blue = int(color_data[2] / lum * 256)
            all_data[str(uid) + "1"] = [red, green, blue, lum, get_hue(red, green, blue)]
            continue
        if h.getDeviceName(int(device_type)) == "ServoControl":
            for device_id in uid_to_device_id(uid, 4):
                if device_id not in all_servos:
                    all_servos[device_id] = 90
                    h.writeValue(device_id_to_uid(device_id), "servo" + str(device_id_to_index(device_id)), 0)
        if not tup_nest:
            continue
        values, timestamps = tup_nest
        for value, device_id in zip(values, uid_to_device_id(uid, len(values))):
            all_data[device_id] = value
    all_data.update(all_servos)
    return all_data

def get_hue(r, g, b):
    denom = max(r, g, b) - min(r, g, b)
    if denom == 0:
        return 0
    L, M, H = sorted([r, g, b])
    preucilHueError = 1.0 * (M - L) / (H - L)
    if r >= g and g >= b:
        return 60 * preucilHueError
    elif g > r and r >= b:
        return 60 * (2 - preucilHueError)
    elif g >= b and b > r:
        return 60 * (2 + preucilHueError)
    elif b > g and g > r:
        return 60 * (4 - preucilHueError)
    elif b > r and r >= g:
        return 60 * (4 + preucilHueError)
    elif r >= b and b > g:
        return 60 * (6 - preucilHueError)
    else:
        # Should never be here
        return -1


#####
# Battery
#####
battery_UID = None
battery_safe = False
def init_battery():
    global battery_UID
    for UID, dev in connectedDevices:
        if h.getDeviceName(int(dev)) == "BatteryBuzzer":
            battery_UID = UID
    test_battery() #TODO Calls test_battery to send alert once for no battery buzzer

def test_battery():
    global battery_UID
    if battery_UID is None or battery_UID not in [x[0] for x in connectedDevices]:
        ansible.send_message('ADD_ALERT', {
        'payload': {
            'heading': "Battery Error",
            'message': "Battery buzzer not connected. Please connect and restart the robot"
            }
        })
        ansible.send_message('UPDATE_BATTERY', {
            'battery': {
                'value': 0
                }
        })
        return False

    try:
        (safe, connected, c0, c1, c2, voltage), timestamp = h.getData(battery_UID,"dataUpdate")
    except:
        safe, voltage = False, 0.0

    ansible.send_message('UPDATE_BATTERY', {
       'battery': {
            'value': voltage
            }
    })

    if not safe:
        ansible.send_message('ADD_ALERT', {
        'payload': {
            'heading': "Battery Error",
            'message': "Battery level critical. Reconnect a safe battery and restart the robot"
            }
        })
        return False
    else:
        return True

#####
# Hibike actuators
#####
all_servos = {}
def set_servos(data):
    global all_servos
    for device_id in data:
        value = data[device_id]
        all_servos[device_id] = value
        h.writeValue(device_id_to_uid(device_id),
                     "servo" + str(device_id_to_index(device_id)),
                     value)
    mc.set('servo_values', {})

flag_UID = None
def init_flag():
    global flag_UID
    for UID, dev in connectedDevices:
        if h.getDeviceName(int(dev)) == "TeamFlag":
            flag_UID = UID
    if flag_UID is None:
        print("WARNING: no team flag found")


flag_debounce = None
def set_flag(values):
    global flag_debounce
    if flag_UID is None:
        return

    if values == flag_debounce:
        return
    flag_debounce = values

    for field, value in zip(["s1", "s2", "s3", "s4"], values):
        h.writeValue(flag_UID, field, int(value))

calibrate_val = 1
def metal_d_calibrate(metalID):
    global calibrate_val
    for i in range(10):
    #while h.getData(metalID, "calibrate") != calibrate_val:
        h.writeValue(metalID, "calibrate", calibrate_val)
    calibrate_val += 1
    mc.set("metal_detector_calibrate", [False,False])

def set_light(value):
    device_id = value[0]
    write_value = value[1]
    h.writeValue(device_id_to_uid(device_id), "Toggle", write_value)
    mc.set("toggle_light", None)

#####
# Motors
#####
name_to_grizzly, name_to_modes, addrs_to_name = {}, {}, {}
next_index = 0

# Called on start of student code, finds and configures all the connected motors
def enumerate_motors():
    global next_index
    try:
        addrs = Grizzly.get_all_ids()
    except usb.USBError:
        print("WARNING: no Grizzly Bear devices found")
        addrs = []

    # Brute force to find all
    name_to_values = {}
    for index in range(len(addrs)):
        # default name for motors is motor0, motor1, motor2, getEnumeratedDevices
        grizzly_motor = Grizzly(addrs[index])
        grizzly_motor.set_mode(ControlMode.NO_PID, DriveMode.DRIVE_BRAKE)
        grizzly_motor.set_target(0)

        # enable usb mode disables timeouts, so we have to disable it to enable timeouts.
        #grizzly_motor._set_as_int(Addr.EnableUSB, 0, 1)

        # set the grizzly timeout to 500 ms
        #grizzly_motor._set_as_int(Addr.Timeout, 500, 2)
        name_to_grizzly['motor' + str(index)] = grizzly_motor
        addrs_to_name[addrs[index]] = 'motor' + str(index)
        name_to_values['motor' + str(index)] = 0
        name_to_modes['motor' + str(index)] = (ControlMode.NO_PID, DriveMode.DRIVE_BRAKE)

    mc.set('motor_values', name_to_values)
    next_index = len(addrs)

def update_motors():
    global next_index, name_to_grizzly, name_to_values, addrs_to_name, name_to_modes
    try:
        addrs = Grizzly.get_all_ids()
    except usb.USBError:
        print("WARNING: no Grizzly Bear devices found")
        addrs = []

    #connect motors
    for id_addrs in addrs:
        if not id_addrs in addrs_to_name:
            #create grizzly
            grizzly_motor = Grizzly(id_addrs)
            grizzly_motor.set_mode(ControlMode.NO_PID, DriveMode.DRIVE_BRAKE)
            grizzly_motor.set_target(0)
            #add to dictionaries
            name = 'motor' + str(next_index)
            addrs_to_name[id_addrs] = name
            name_to_grizzly[name] = grizzly_motor
            name_to_values[name] = 0
            name_to_modes[name] = (ControlMode.NO_PID, DriveMode.DRIVE_BRAKE)
            next_index += 1

    #disconnect motors
    for id_addrs in addrs_to_name:
        if not id_addrs in addrs:
            name = addrs_to_name[id_addrs]
            del addrs_to_name[id_addrs]
            del name_to_grizzly[name]
            del name_to_values[name]
            del name_to_modes[name]

def set_motors(data):
    for name, value in data.items():
        grizzly = name_to_grizzly[name]
        if (value == None):
            continue
        try:
            grizzly.set_mode(ControlMode.NO_PID, DriveMode.DRIVE_BRAKE)
            grizzly.set_target(value)
        except:
            stop_motors()
            return


# Called on end of student code, sets all motor values to zero
def stop_motors():
    motor_values = mc.get('motor_values')
    for name, grizzly in name_to_grizzly.iteritems():
        try:
            grizzly.set_mode(ControlMode.NO_PID, DriveMode.DRIVE_BRAKE)
            grizzly.set_target(0)
        except:
            print("WARNING: failed to stop grizzly")
        motor_values[name] = 0

    mc.set('motor_values', motor_values)

def drive_set_distance(list_tuples):
    for item in list_tuples:
        grizzly = name_to_grizzly[item[0]]
        try:
            grizzly.write_encoder(0)
            grizzly.set_target(0)
            grizzly.set_mode(ControlMode.POSITION_PID, DriveMode.DRIVE_BRAKE)
            grizzly.set_target(item[1] * gear_to_tick[item[2]])
            motor_vals = mc.get("motor_values")
            motor_vals[item[0]] = None
            mc.set("motor_values", motor_vals)
            #reset target number.
        except:
            stop_motors()
    mc.set("drive_distance", [])

def set_control_mode(mode):
    new_mode = all_modes[mode[0]]
    if mode[1] == "all":
        for motor, old_mode in name_to_modes.items():
            grizzly = name_to_grizzly[motor]
            try:
                grizzly.set_mode(new_mode, old_mode[1])
            except:
                pass
    else:
        grizzly = name_to_grizzly[motor]
        try:
            grizzly.set_mode(new_mode, old_mode[1])
        except:
            pass
    mc.set("control_mode", [])

def set_drive_mode(mode):
    new_mode = all_modes[mode[0]]
    if mode[1] == "all":
        for motor, old_mode in name_to_modes.items():
            grizzly = name_to_grizzly[motor]
            try:
                grizzly.set_mode(old_mode[0], new_mode)
            except:
                pass
    else:
        grizzly = name_to_grizzly[motor]
        try:
            grizzly.set_mode(old_mode[0], new_mode)
        except:
            pass
    mc.set("drive_mode", [])

def set_PID(constants):
    PID_constants[constants[0]] = constants[1]
    p = PID_constants["P"]
    i = PID_constants["I"]
    d = PID_constants["D"]
    for motor, grizzly in name_to_grizzly.items():
        try:
            grizzly.init_pid(p, i, d)
        except:
            print("pid set failed");
    mc.set("PID_constants", [])

def set_spec_PID(data):
    motor_name = data[0]
    p = data[1]
    i = data[2]
    d = data[3]
    grizzy = name_to_grizzly[motor_name]
    try:
        grizzly.init_pid(p, i, d)
    except:
        print("tried to set pid and failed")
    mc.set("spec_pid", [])

def update_motor_distance():
    for motor, grizzly in name_to_grizzly.items():
        try:
            name_to_distance[motor] = grizzly.read_encoder()
        except:
            print("tried and failed to read grizzly")

# A process for sending the output of student code to the UI
def log_output(stream):
    #TODO: figure out a way to limit speed of sending messages, so
    # ansible is not overflowed by printing too fast
    for line in stream:
        if robot_status == 0:
            return
        time.sleep(0.005)
        ansible.send_message('UPDATE_CONSOLE', {
            'console_output': {
                'value': line
            }
        })

def upload_file(filename, msg):
    if not os.path.exists(os.path.dirname(filename)):
        try:
            os.makedirs(os.path.dirname(filename))
        except OSError as exc: # Guard against race condition
            if exc.errno != errno.EEXIST:
                raise
    with open(filename, 'w+') as f:
        f.write(msg['content']['code'])

def msg_handling(msg):
    global robot_status, student_proc, console_proc
    msg_type, content = msg['header']['msg_type'], msg['content']
    if msg_type == 'upload' and not robot_status:
        filename = "student_code/student_code.py"
        upload_file(filename, msg)
        #enumerate_motors() TODO Unable to restart motors that already exist
    elif msg_type == 'execute' and not robot_status:
        filename = "student_code/student_code.py"
        # Field Control: if content has key 'code' and it is not None, then upload+execute
        # otherwise, don't upload, just execute
        if 'code' in content and content['code']:
            upload_file(filename, msg)
        student_proc = subprocess.Popen(['python', '-u', 'student_code/student_code.py'],
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        # turns student process stdout into a stream for sending to frontend
        lines_iter = iter(student_proc.stdout.readline, b'')
        # start process for watching for student code output
        robot_status= 1
        console_proc = Thread(target=log_output,
                              args=(lines_iter,))
        console_proc.start()
    elif msg_type == 'stop' and robot_status:
        student_proc.terminate()
        # console_proc.terminate()
        stop_motors()
        robot_status = 0
    elif msg_type == 'update':
        #initiate necessary shutdown procedures
        if robot_status:
            student_proc.terminate()
            # console_proc.terminate()
            stop_motors()

        os.system('sudo restart runtime')
    elif msg_type == 'custom_names':
        device_id_set_name(msg['content']['id'], msg['content']['name'])
    elif msg_type == 'game':
        mc.set('game', msg['content'])
        if 'blue' in msg['content'] and flag_UID is not None:
            h.writeValue(flag_UID, 'blue', int(msg['content']['blue']))
            h.writeValue(flag_UID, 'yellow', int(not msg['content']['blue']))

peripheral_data_last_sent = 0
def send_peripheral_data(data):
    global peripheral_data_last_sent
    # TODO: This is a hack. Should put this into a separate process
    if time.time() < peripheral_data_last_sent + 1:
        return
    peripheral_data_last_sent = time.time()

    # Send sensor data
    for device_id, value in data.items():
        ansible.send_message('UPDATE_PERIPHERAL', {
            'peripheral': {
                'name': device_id_get_name(device_id),
                'peripheralType':h.getDeviceName(uid_to_type[device_id_to_uid(device_id)]),
                'value': value,
                'id': device_id
                }
            })

motor_data_last_sent = 0
def send_motor_data(data):
    global motor_data_last_sent
    if time.time() < motor_data_last_sent + 1:
        return
    motor_data_last_sent = time.time()

    for name, value in data.items():
        ansible.send_message('UPDATE_PERIPHERAL', {
            'peripheral': {
                'name': device_id_get_name(name),
                'peripheralType':'MOTOR_SCALAR',
                'value': value,
                'id': name
            }
        })

read_naming_map()
enumerate_hibike()
enumerate_motors()
while True:
    if battery_UID: #TODO Only tests battery safety if battery buzzer is connected
        battery_safe = test_battery()
    if not battery_safe and battery_UID: #TODO Disables sending alert if battery buzzer is not connected
        if robot_status:
            student_proc.terminate()
            stop_motors()
            robot_status = 0
        for _ in range(10):
            ansible.send_message('UPDATE_STATUS', {
                'status': {'value': False}
            })
            time.sleep(0.1)
        continue

    msg = ansible.recv()
    # Handle any incoming  commands from the UI
    if msg:
        msg_handling(msg)

    # Send whether or not robot is executing code
    ansible.send_message('UPDATE_STATUS', {
        'status': {'value': robot_status}
    })

    # Update sensor values, and send to UI
    update_hibike()
    all_sensor_data = get_all_data(connectedDevices)
    send_peripheral_data(all_sensor_data)
    mc.set('sensor_values', all_sensor_data)

    md_calibrate = mc.get('metal_detector_calibrate')
    if md_calibrate[1]:
        metal_d_calibrate(device_id_to_uid(md_calibrate[0]))

    # Update motor values, and send to UI
    motor_values = mc.get('motor_values') or {}
    send_motor_data(motor_values)
    if robot_status and mc.get('game')['enabled']:
        set_motors(motor_values)
    elif not mc.get('game')['enabled']:
        stop_motors()
        mc.set('gamepad', {'0': {'axes': [0,0,0,0], 'buttons': [0]*17, 'connected': None, 'mapping': None}})

    #Set Servos
    servo_values = mc.get('servo_values') 
    if servo_values and mc.get('game')['enabled']:
        set_servos(servo_values)

    #Set Team Flag
    flag_values = mc.get('flag_values') or [False, False, False, False]
    if flag_values:
        set_flag(flag_values)

    #Drive distance for grizzlies
    drive_distance = mc.get('drive_distance')
    if drive_distance:
        drive_set_distance(drive_distance)

    #set control mode
    control_mode = mc.get("control_mode")
    if control_mode:
        set_control_mode(control_mode)

    #set drive mode
    drive_mode = mc.get("drive_mode")
    if drive_mode:
        set_drive_mode(drive_mode)

    #rebind PID constants
    PID_rebind= mc.get("PID_constants")
    if PID_rebind:
        set_PID(PID_rebind)

    #toggle light on or off
    toggle_value = mc.get("toggle_light")
    if toggle_value != None:
        set_light(toggle_value)

    spec_pid = mc.get("spec_pid")
    if spec_pid:
        set_spec_PID(spec_pid)

    update_motor_distance()
    mc.set("encoder_distance", name_to_distance)

    time.sleep(0.05)
