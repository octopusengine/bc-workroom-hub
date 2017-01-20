#!/usr/bin/env python3

"""
BigClown plugin for controlling color of an LED strip based on temperature
and relative humidity read from MQTT.

MQTT topic: plugin/led-strip/config

Usage:
  bc-workroom-led-strip [options]
  bc-workroom-led-strip --help

Options:
  -D --debug           Print debug messages.
  -h HOST --host=HOST  MQTT host to connect to (default is localhost).
  -p PORT --port=PORT  MQTT port to connect to (default is 1883).
  -v --version         Print version.
  --help               Show this message.
"""

import base64
import json
import logging as log
from logging import DEBUG, INFO
import os
import sys
import time

from docopt import docopt
import paho.mqtt.client as mqtt

__version__ = '@@VERSION@@'

DEFAULT_MQTT_HOST = 'localhost'
DEFAULT_MQTT_PORT = 1883

DEFAULT_PLUGIN_CONFIG = {
    'rules': [
        {'relative-humidity': {'from': 60}, 'color': [0, 255, 0, 0]},
        {'relative-humidity': {'to': 30}, 'color': [255, 255, 0, 0]},
        {'temperature': {'from': 26}, 'color': [255, 0, 0, 0]},
        {'temperature': {'to': 22}, 'color': [0, 0, 255, 0]},
        {'color': [0, 0, 0, 230]}
    ]
}

DEFAULT_PLUGIN_DATA = {
    'brightness': 255,
    "state": "rules",
    'color': [255, 0, 0, 0]
}

LOG_FORMAT = '%(asctime)s %(levelname)s: %(message)s'


def check_color_format(color):
    if len(color) != 4:
        raise AttributeError('bad define color %s' % color)
    for c in color:
        if not isinstance(c, int) or c < 0 or c > 255:
            raise AttributeError('bad define color %s' % color)
    return color


def check_config(config):
    # compatibility with old implementation
    if 'values' in config:
        config['rules'] = config['values']
        del config['values']
    if 'brightness' in config:
        del config['brightness']

    if tuple(config) != ('rules',):
        raise AttributeError('missing or unknown key')

    if not isinstance(config['rules'], list):
        raise AttributeError('values must be of type list')

    check_row_keys = {'color', 'temperature', 'relative-humidity', 'label'}

    for row in config['rules']:
        if not row:
            raise AttributeError('not allowed empty rule')

        row_keys = set(row.keys())

        if row_keys - check_row_keys:
            raise AttributeError('in rule unknown key: ' + ', '.join(row_keys - check_row_keys))

        if 'color' not in row:
            raise AttributeError('in rule missing key: color')

        check_color_format(row['color'])

        for key in ('relative-humidity', 'temperature'):
            if key in row:
                if not isinstance(row[key], dict):
                    raise AttributeError('key %s is not type object' % key)

                for k, v in row[key].items():
                    if k not in ('from', 'to'):
                        raise AttributeError('in rule unknown key: %s' % k)
                    elif not isinstance(v, (int, float)):
                        raise AttributeError(
                            'in rule: value %s of key %s is not type int or float' % (repr(v), k))
    return config


def make_pixels(red, green, blue, white=None, brightness=255, count=144):
    pixel = [(red * (brightness + 1)) >> 8,
             (green * (brightness + 1)) >> 8,
             (blue * (brightness + 1)) >> 8]
    if white is not None:
        pixel.append((white * (brightness + 1)) >> 8)

    log.debug('Pixel: %s', pixel)

    buf = pixel * count
    pixels = base64.b64encode(bytearray(buf)).decode()

    log.debug('len(base64): %d', len(pixels))

    return pixels


def base_led_strip_set_pixels(client, userdata):
    color = None

    if userdata['data']['state'] == 'rules':
        now = time.time()

        if (now - userdata.get('temperature-ts', 0)) > 180:
            userdata['temperature'] = None

        if (now - userdata.get('relative-humidity-ts', 0)) > 180:
            userdata['relative-humidity'] = None

        for row in userdata['config']['rules']:

            for key in ('relative-humidity', 'temperature'):
                rule = row.get(key, None)
                if rule is None:
                    continue

                measured_value = userdata.get(key, None)
                if measured_value is None:
                    break

                if rule:
                    if 'to' in rule and measured_value > rule['to']:
                        break

                    if 'from' in rule and measured_value < rule['from']:
                        break

            else:
                log.debug(row)
                color = row['color']
                break

    elif userdata['data']['state'] == 'color':
        color = userdata['data']['color']

    if color:
        if userdata['mode'] == 'rgb':
            color = color[:3]
        pixels = make_pixels(*color, brightness=userdata['data']['brightness'], count=userdata['count'])
        client.publish('nodes/base/led-strip/-/set', json.dumps({'pixels': pixels}))


def mgtt_on_connect(client, userdata, flags, rc):
    log.info('Connected to MQTT broker (code %s)', rc)

    for topic in ('plugin/led-strip/config',
                  'plugin/led-strip/data/+',
                  'nodes/remote/+/+',
                  'nodes/base/+/+',
                  'nodes/base/led-strip/-/config/set',
                  # compatibility with old implementation
                  'plugin/led-strip/config/set',
                  'plugin/led-strip/set'):
        log.debug('subscribe %s', topic)
        client.subscribe(topic)


def mgtt_on_message(client, userdata, msg):
    payload = msg.payload.decode('utf-8')

    log.debug('%s: %s', msg.topic, payload)

    if msg.topic == 'plugin/led-strip/config' and not payload:
        # on empty payload load deafault config
        payload = DEFAULT_PLUGIN_CONFIG
    else:
        try:
            payload = json.loads(payload)
        except ValueError as e:
            log.error('Malformed payload: %s', e)
            return

    now = time.time()

    # compatibility with old implementation
    if msg.topic == 'plugin/led-strip/set' and 'color' in payload:
        msg.topic = 'plugin/led-strip/data/set'
    elif msg.topic == 'plugin/led-strip/config/set' and 'brightness' in payload:
        msg.topic = 'plugin/led-strip/data/set'

    if msg.topic == 'nodes/remote/thermometer/i2c0-49' or msg.topic == 'nodes/remote/thermometer/i2c1-49':
        try:
            userdata['temperature'] = float(payload['temperature'][0])
            userdata['temperature-ts'] = now
        except (TypeError, ValueError) as e:
            log.error('Invalid temperature: %s', e)
            client.publish(msg.topic + '/-/error', json.dumps({"msg": 'Invalid temperature: ' + str(e)}))

    elif msg.topic == 'nodes/remote/humidity-sensor/i2c0-40' or msg.topic == 'nodes/remote/humidity-sensor/i2c1-40':
        try:
            userdata['relative-humidity'] = float(payload['relative-humidity'][0])
            userdata['relative-humidity-ts'] = now
        except (TypeError, ValueError) as e:
            log.error('Invalid relative-humidity: %s', e)
            client.publish(msg.topic + '/-/error', json.dumps({"msg": 'Invalid relative-humidity: ' + str(e)}))

    elif msg.topic == 'plugin/led-strip/data/set':
        try:
            ok_payload = {}

            if 'color' in payload:
                ok_payload['color'] = check_color_format(payload['color'])

            if 'brightness' in payload:
                brightness = int(payload['brightness'])
                if brightness < 0 or brightness > 255:
                    raise Exception('brightness out of range')

                ok_payload['brightness'] = brightness

            if 'state' in payload:
                if payload['state'] not in ('rules', 'color', 'disable'):
                    raise ValueError('state values is rules or color')
                ok_payload['state'] = payload['state']

            if ok_payload:
                userdata['data'].update(ok_payload)
                client.publish('plugin/led-strip/data/set/ok', json.dumps(ok_payload))

        except Exception as e:
            log.error('Invalid data: %s', e)
            client.publish(msg.topic + '/error', json.dumps({"msg": 'Invalid data: ' + str(e)}))
            return

    elif msg.topic == 'plugin/led-strip/data/get':
        client.publish('plugin/led-strip/data', json.dumps(userdata['data']))

    elif msg.topic == 'nodes/base/led-strip/-/config/set':
        try:
            if payload.get('mode', None) not in ('rgb', 'rgbw'):
                raise ValueError('mode values is rgb or rgbw')

            userdata['mode'] = payload['mode']
            userdata['count'] = int(payload['count'])
        except (TypeError, ValueError) as e:
            log.error('Invalid led-strip config: %s', e)
            client.publish(msg.topic + '/error', json.dumps({"msg": 'Invalid led-strip config: ' + str(e)}))
            return

    elif msg.topic == 'plugin/led-strip/config':
        try:
            userdata['config'] = check_config(payload)
        except Exception as e:
            log.error('Invalid config: %s', e)
            client.publish(msg.topic + '/-/error', json.dumps({"msg": 'Invalid config: ' + str(e)}))
            return

    base_led_strip_set_pixels(client, userdata)


def main():
    arguments = docopt(__doc__, version='bc-workroom-led-strip %s' % __version__)
    opts = {k.lstrip('-').replace('-', '_'): v
            for k, v in arguments.items() if v}

    log.basicConfig(level=DEBUG if opts.get('debug') else INFO, format=LOG_FORMAT)

    client = mqtt.Client(userdata={'config': check_config(DEFAULT_PLUGIN_CONFIG), 'data': DEFAULT_PLUGIN_DATA, 'count': 144, 'mode': 'rgbw'})
    client.on_connect = mgtt_on_connect
    client.on_message = mgtt_on_message

    client.connect(opts.get('host', DEFAULT_MQTT_HOST),
                   opts.get('port', DEFAULT_MQTT_PORT),
                   keepalive=10)
    client.loop_forever()


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(0)
    except Exception as e:
        log.error(e)
        if os.getenv('DEBUG', False):
            raise e
        sys.exit(1)
