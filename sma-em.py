#!/usr/bin/python3
"""
*
*  ----------------------------------------------------------------------------
*  Set of functions to decode the udp telegram messages sent out by the 
*  SMA Energy Meter on port 9522 of the multicast group 239.12.255.254
* 
*
*  Documentation of the protocol is unfortunately only available in German. It 
*  can be downloaded from:
*      https://github.com/ufankhau/sma-empv/documentation/SMA-EM_GE.pdf
*
*  The following code is inspired by the work of david-m-m and
*  datenschuft (https://github.com/datenschuft/SMA-EM)
*
*  2021-May-03
*
*  ----------------------------------------------------------------------------
*/
"""

#  load necessary libraries
import _thread
import socket
import struct
import binascii
import sdnotify
import os, sys
import json
import argparse
import sdnotify
import threading
from configparser import ConfigParser
from uftools import print_line
from smaem_decoder import decode_SMAEM
from tzlocal import get_localzone
from time import time, sleep, localtime, strftime
from datetime import datetime
from collections import OrderedDict
import paho.mqtt.client as mqtt

script_version = '1.0.4'
script_name = 'sma-em.py'
script_info = '{} v{}'.format(script_name, script_version)
project_name = 'SMA Energy Meter Integration into Home Assistant via MQTT'
project_url = 'https://github.com/ufankhau/sma-em'

if False:
    # will be caught by python 2.7 to be illegal syntax
    print_line('Sorry, this script requries a python3 runtime environment.', file=sys.stderr)
    os._exit(1)

# construct the argument parse and parse the arguments
ap = argparse.ArgumentParser(description = project_name)
ap.add_argument("-v", "--verbose", help="increase output verbosity", action="store_true")
ap.add_argument("-d", "--debug", help = "show debug output", action = "store_true")
ap.add_argument("-l", "--logfile", help = "store log in logfile", action = "store_true")
ap.add_argument("-c", "--config_dir", help = "set directory where config.ini is located", default=sys.path[0])
args = vars(ap.parse_args())

opt_verbose = args["verbose"]
opt_debug = args["debug"]
opt_logfile = args["logfile"]
config_dir = args["config_dir"]

#  -------------
#  start logging
print_line(script_info, info=True)
if opt_verbose:
    print_line('Verbose enabled ...', info=True)
if opt_debug:
    print_line('Debug enabled ...', info=True)


#  ------------------
#  set default values
local_tz = get_localzone()
smaserials = ''

def getDatafromSMAEnergyMeter():
    #  --------------------------------------------------------------------
    #  create socket to listen to UDP broadcasting on MCAST_GRP, MCAST_PORT
    ipbind = '0.0.0.0'
    MCAST_GRP = '239.12.255.254'
    MCAST_PORT = 9522
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(('', MCAST_PORT))
    try:
        mreq = struct.pack("4s4s", socket.inet_aton(MCAST_GRP), socket.inet_aton(ipbind))
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
        print_line('Successfully connected to multicast group', info=True)
    except BaseException:
        print_line('* SOCKET: could not connect to multicast group or bind to given interface', error=True)
        sys.exit(1)
    smaeminfo = sock.recv(1024)
    return decode_SMAEM(smaeminfo, opt_debug)

#  ------------
#  MQTT handler
mqtt_client_connected = False
print_line('* INIT mqtt_client_connected = [{}]'.format(mqtt_client_connected), debug=opt_debug)
mqtt_client_should_attempt_reconnect = True

def onConnect(client, userdata, flags, rc):
    global mqtt_client_connected
    if rc == 0:
        print_line('* MQTT connection established', console=True, sd_notify=True)
        print_line('')
        mqtt_client_connected = True
        print_line('on_connect() mqtt_client_connected = [{}]'.format(mqtt_client_connected), debug=opt_debug)
    else:
        print_line('MQTT connection error with result code {} - {}'.format(str(rc), mqtt.connack_string(rc)), error=True, sd_notify=True)
        mqtt_client_connected = False
        print_line('on_connect() mqtt_client_connected = [{}]'.format(mqtt_client_connected), error=True)
        os._exit(1)

def onPublish(client, userdata, mid):
    print_line('* Data successfully published.', info=True)
    pass

#  load configuration file config.ini
config = ConfigParser(delimiters=('=', ), inline_comment_prefixes=('#'))
config.optionxform = str
try:
    with open(os.path.join(config_dir, 'config.ini')) as config_file:
        config.read_file(config_file)
except IOError:
    print_line('No configuration file "config.ini" found in directory {}'.format(config_dir), error=True)
    sys.exit(1)

daemon_enabled = config['Daemon'].getboolean('enabled', True)

default_base_topic = 'home/nodes'
base_topic = config['MQTT'].get('base_topic', default_base_topic).lower()

default_sensor_name = 'smaem'
sensor_name = config['MQTT'].get('sensor_name', default_sensor_name).lower()

default_discovery_prefix = 'homeassistant'
discovery_prefix = config['MQTT'].get('discovery_previx', default_discovery_prefix).lower()

#  requency of reporting data from SMA Energy Meter
min_interval_in_seconds = 20
max_interval_in_seconds = 300
default_interval_in_seconds = 60
interval_in_seconds = config['Daemon'].getint('interval_in_seconds', default_interval_in_seconds)

#  check configuration
if (interval_in_seconds < min_interval_in_seconds) or (interval_in_seconds > max_interval_in_seconds):
    print_line('ERROR: Invalid "interval_in_seconds" found in configuration file "config.ini"! Value must be between [{} - {}]. Fix it and try again ... aborting'.format(min_interval_in_seconds, max_interval_in_seconds), error=True, sd_notify=True)
    sys.exit(1)
if not config['MQTT']:
    print_line('ERROR: No MQTT settings found in configuration file "config.ini"! Fix it and try again ... aborting', error=True, sd_notify=True)
    sys.exit(1)

print_line('MQTT configuration accepted', console=True, sd_notify=True)


#  ---------------------------------------------------------
#  timer and timer functions for ALIVE MQTT Notices handling
ALIVE_TIMEOUT_IN_SECONDS = 60

def publishAliveStatus():
    print_line('- SEND: yes, still alive -', debug=opt_debug)
    mqtt_client.publish(lwt_topic, payload=lwt_online_val, retain=False)

def aliveTimeoutHandler():
    print_line('- MQTT timer interrupt -', debug=opt_debug)
    _thread.start_new_thread(publishAliveStatus, ())
    startAliveTimer()

def startAliveTimer():
    global aliveTimer
    global aliveTimerRunningsStatus
    stopAliveTimer()
    aliveTimer = threading.Timer(ALIVE_TIMEOUT_IN_SECONDS, aliveTimeoutHandler)
    aliveTimer.start()
    aliveTimerRunningStatus = True
    print_line('- started MQTT timer - every {} seconds'.format(ALIVE_TIMEOUT_IN_SECONDS), debug=opt_debug)

def stopAliveTimer():
    global aliveTimer
    global aliveTimerRunningsStatus
    aliveTimer.cancel()
    aliveTimerRunningStatus = False
    print_line('- stopped MQTT timer', debug=opt_debug)

def isAliveTimerRunning():
    global aliveTimerRunningStatus
    return aliveTimerRunningsStatus

#  alive timer
aliveTimer = threading.Timer(ALIVE_TIMEOUT_IN_SECONDS, aliveTimeoutHandler)
# bool tracking state of alive timer
aliveTimerRunningsStatus = False

#  ----------------------
#  MQTT setup and startup
lwt_topic = '{}/sensor/{}/status'.format(base_topic, sensor_name.lower())
lwt_online_val = 'online'
lwt_offline_val = 'offline'

print_line('Connecting to MQTT broker ...', verbose=opt_verbose)
mqtt_client = mqtt.Client()
mqtt_client.on_connect = onConnect
mqtt_client.on_publish = onPublish

mqtt_client.will_set(lwt_topic, payload=lwt_offline_val, retain=True)

if config['MQTT'].getboolean('tls', False):
    mqtt_client.tls_set(
        ca_certs = config['MQTT'].get('tls_ca_cert', None),
        keyfile = config['MQTT'].get('tls_keyfile', None),
        certfile = config['MQTT'].get('tls_certfile', None),
        tls_version = ssl.PROTOCOL_SSLv23
    )

mqtt_username = os.environ.get('MQTT_USERNAME', config['MQTT'].get('username'))
mqtt_password = os.environ.get('MQTT_PASSWROD', config['MQTT'].get('password', None))

if mqtt_username:
    mqtt_client.username_pw_set(mqtt_username, mqtt_password)
try:
    mqtt_client.connect(os.environ.get('MQTT_HOSTNAME', config['MQTT'].get('hostname', 'localhost')), port=int(os.environ.get('MQTT_PORT', config['MQTT'].get('port', '1883'))), keepalive=config['MQTT'].getint('keepalive', 60))
except:
    print_line('MQTT connection error. Please check your settings in the configuration file "config.ini"', error=True, sd_notify=True)
    sys.exit(1)
else:
    mqtt_client.publish(lwt_topic, payload=lwt_online_val, retain=False)
    mqtt_client.loop_start()
    while mqtt_client_connected == False:
        print_line('* Wait on mqtt_client_connected = [{}]'.format(mqtt_client_connected), debug=opt_debug)
        sleep(1.0)   # some c^slack to estabish the connection
    startAliveTimer()

#sd_notifier.notify('READY=1')

#  performe MQTT discovery announcement
#  create uniqID using the unique serial number of the SMA Energy Meter
emdata = {}
emdata = getDatafromSMAEnergyMeter()
serial = str(emdata['serial'])
uniqID = 'SMA-{}EM{}'.format(serial[:5], serial[5:])
print_line('uniqID: {}'.format(uniqID), debug=opt_debug)

#  SMA Energy Meter reporting device
LD_MONITOR = 'monitor'
LD_ENERGY_CONSUME = 'grid_consume_total'
LD_ENERGY_SUPPLY = 'grid_supply_total'
LDS_PAYLOAD_NAME = 'info'

#  table of key items to publish:
detectorValues = OrderedDict([
    (LD_MONITOR, dict(title='SMA Energy Meter Monitor', device_class='timestamp', no_title_prefix='yes', json_value='timestamp', json_attr='yes', icon='mdi:counter', device_ident='SMA-EM-{}'.format(emdata['serial']))),
    (LD_ENERGY_CONSUME, dict(title='Grid Consume', device_class='energy', state_class='total', no_title_prefix='yes', json_value='grid_consume_total', unit='kWh', icon='mdi:counter')),
    (LD_ENERGY_SUPPLY, dict(title='Grid Supply', device_class='energy', state_class='total', no_title_prefix='yes', json_value='grid_supply_total', unit='kWh', icon='mdi:counter')),
])
print_line('Announcing SMA Energy Meter to MQTT broker for auto-discovery ...')

base_topic = '{}/sensor/{}'.format(base_topic, sensor_name.lower())
values_topic_rel = '{}/{}'.format('~', LD_MONITOR)
values_topic = '{}/{}'.format(base_topic, LD_MONITOR)
activity_topic_rel = '{}/status'.format('~')
activity_topic = '{}/status'.format(base_topic)
command_topic_rel = '~/set'

print_line('base topic: {}'.format(base_topic), debug=opt_debug)
print_line('values topic rel: {}'.format(values_topic_rel), debug=opt_debug)
print_line('values topic: {}'.format(values_topic), debug=opt_debug)
print_line('activity topic rel: {}'.format(activity_topic_rel), debug=opt_debug)
print_line('activity topic: {}'.format(activity_topic), debug=opt_debug)

for [sensor, params] in detectorValues.items():
    discovery_topic = '{}/sensor/{}/{}/config'.format(discovery_prefix, sensor_name.lower(), sensor)
    print_line('discovery topic: {}'.format(discovery_topic), debug=opt_debug)
    payload = OrderedDict()
    if 'no_title_prefix' in params:
        payload['name'] = '{}'.format(params['title'].title())
    else:
        payload['name'] = '{} {}'.format(sensor_name.title(), params['title'].title())
    payload['uniq_id'] = '{}_{}'.format(uniqID, sensor.lower())
    if 'device_class' in params:
        payload['dev_cla'] = params['device_class']
    if 'state_class' in params:
        payload['stat_cla'] = params['state_class']
    if 'unit' in params:
        payload['unit_of_measurement'] = params['unit']
    if 'icon' in params:
        payload['ic'] = params['icon']
    if 'json_value' in params:
        payload['stat_t'] = values_topic_rel
        payload['val_tpl'] = '{{{{ value_json.{}.{} }}}}'.format(LDS_PAYLOAD_NAME, params['json_value'])
    payload['~'] = base_topic
    payload['pl_avail'] = lwt_online_val
    payload['pl_not_avail'] = lwt_offline_val
    payload['avty_t'] = activity_topic_rel
    if 'json_attr' in params:
        payload['json_attr_t'] = values_topic_rel
        payload['json_attr_tpl'] = '{{{{ value_json.{} | tojson }}}}'.format(LDS_PAYLOAD_NAME)
    if 'device_ident' in params:
        payload['dev'] = {
            'identifiers' : ['{}'.format(uniqID)],
            'manufacturer' : 'SMA Solar Technology AG',
            'name' : params['device_ident'],
            'model' : 'Energy Meter',
            'sw_version' : '{}'.format(emdata['speedwire_version'])
        }
    else:
        payload['dev'] = {
            'identifiers' : ['{}'.format(uniqID)]
        }
    
    print_line('payload: {}'.format(payload), debug=opt_debug)
    mqtt_client.publish(discovery_topic, json.dumps(payload), 1, retain=True)

#  -------------------------------------------------------
#  timer and timer functions for reporting period handling
TIMER_INTERRUPT = (-1)
TEST_INTERRUPT = (-2)

def periodTimeoutHandler():
    print_line('- PERIOD TIMER INTERRUPT - ', debug=opt_debug)
    handle_interrupt(TIMER_INTERRUPT)
    startPeriodTimer()

def startPeriodTimer():
    global endPeriodTimer
    global periodTimeRunningStatus
    stopPeriodTimer()
    endPeriodTimer = threading.Timer(interval_in_seconds, periodTimeoutHandler)
    endPeriodTimer.start()
    periodTimeRunningStatus = True
    print_line('- started PERIOD timer - every {} seconds'.format(interval_in_seconds), debug=opt_debug)

def stopPeriodTimer():
    global endPeriodTimer
    global periodTimeRunningStatus
    endPeriodTimer.cancel()
    periodTimeRunningStatus = False
    print_line('- stopped PERIOD timer', debug=opt_debug)

def isPeriodTimerRunning():
    global periodTimeRunningStatus
    return periodTimeRunningStatus

#  timer
endPeriodTimer = threading.Timer(interval_in_seconds, periodTimeoutHandler)
#  bool tracking state of timer
periodTimeRunningStatus = False
reported_first_time = False

#  ------------
#  MQTT reporting 
def send_status(timestamp, nothing):
    emdata = {}
    emdata = getDatafromSMAEnergyMeter()
    smaEMData = OrderedDict()
    smaEMData['timestamp'] = timestamp.astimezone().replace(microsecond=0).isoformat()
    smaEMData['grid_consume_total'] = emdata['p_consume_counter']
    smaEMData['grid_supply_total'] = emdata['p_supply_counter']

    smaEMTopDict = OrderedDict()
    smaEMTopDict['info'] = smaEMData

    _thread.start_new_thread(publishMonitorData, (smaEMTopDict, values_topic))

def publishMonitorData(latestData, topic):
    mqtt_client.publish('{}'.format(topic), json.dumps(latestData), 1, retain=False)
    sleep(0.5)

#  --------------
#  interrupt handler
def handle_interrupt(channel):
    global reporting_first_time
    sourceID = '<< INTR(' + str(channel) + ')'
    current_timestamp = datetime.now(local_tz)
    print_line(sourceID + ' >> Time to report! {}'.format(current_timestamp.strftime('%H:%M:%S - %Y/%m/%d')), verbose=opt_verbose)
    _thread.start_new_thread(send_status, (current_timestamp, ''))
    reported_first_time = True

def afterMQTTConnect():
    print_line('* afterMQTTConnect()', verbose=opt_verbose)
    startPeriodTimer()
    handle_interrupt(0)

#  ------------------
#  launch reporting loop
afterMQTTConnect()
try:
    while True:
        sleep(10000)

#  cleanup and exit
finally:
    stopPeriodTimer()
    stopAliveTimer()
    if opt_logfile:
        f.close()

