#!/usr/bin/env python3

"""
BigClown plugin for controlling color of an LED strip based on temperature
and relative humidity read from MQTT.

MQTT topic: plugin/led-strip/config

Usage:
  bc-workroom-ledstrip [options]
  bc-workroom-ledstrip --help

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
    'values': [
        {'relative-humidity': {'from': 60}, 'color': [0, 255, 0, 0]},
        {'relative-humidity': {'to': 30}, 'color': [255, 255, 0, 0]},
        {'temperature': {'from': 26}, 'color': [255, 0, 0, 0]},
        {'temperature': {'to': 22}, 'color': [0, 0, 255, 0]},
        {'color': [255, 255, 255, 255]},
    ],
    'brightness': 255,
}

LOG_FORMAT = '%(asctime)s %(levelname)s: %(message)s'


# TODO: refactor!
def check_config(config):
    check_config_key = {'values', 'brightness'}
    config_key = set(config.keys())
    if config_key - check_config_key:
        raise AttributeError('unknown key(s): ' + ', '.join(config_key - check_config_key))
    if check_config_key - config_key:
        raise AttributeError('missing key(s): ' + ', '.join(check_config_key - config_key))

    if config['brightness'] < 0 or config['brightness'] > 255:
        raise AttributeError('brightness must be in range 0..255')

    if not isinstance(config['values'], list):
        raise AttributeError('values must be of type list')

    check_row_keys = {'color', 'temperature', 'relative-humidity', 'label'}

    for row in config['values']:
        row_keys = set(row.keys())

        if len(row_keys) == 0:
            raise AttributeError('%s is empty' % row)

        if row_keys - check_row_keys:
            raise AttributeError('unknown key: ' + ', '.join(row_keys - check_row_keys))

        if 'color' not in row:
            raise AttributeError('missing key: color')

        if len(row['color']) != 4 or len(list(filter(lambda x: x >= 0 <= 255, row['color']))) != 4:
            raise AttributeError('bad define color %s' % row['color'])

        for key in ('relative-humidity', 'temperature'):
            if key in row:
                if not isinstance(row[key], dict):
                    raise AttributeError('key %s is not type object' % key)

                for k, v in row[key].items():
                    if k not in ('from', 'to'):
                        raise AttributeError('unknown key: %s' % k)
                    elif not isinstance(v, (int, float)):
                        raise AttributeError(
                            'value %s of key %s is not type int or float' % (repr(v), k))


def make_pixels(red, green, blue, white, brightness=255, nums=144):
    pixel = [(red * (brightness + 1)) >> 8,
             (green * (brightness + 1)) >> 8,
             (blue * (brightness + 1)) >> 8,
             (white * (brightness + 1)) >> 8]
    log.debug('Pixel: %s', pixel)

    buf = pixel * nums
    pixels = base64.b64encode(bytearray(buf)).decode()
    assert(len(pixels) == 768)

    return pixels


# TODO: refactor!
def set_led_strip(client, userdata):
    now = time.time()

    if (now - userdata.get('temperature-ts', 0)) > 180:
        userdata['temperature'] = None

    if (now - userdata.get('relative-humidity-ts', 0)) > 180:
        userdata['relative-humidity'] = None

    color = None

    for row in userdata['config']['values']:
        valid = True

        for key in ('relative-humidity', 'temperature'):
            if valid and key in row:

                measured_value = userdata.get(key, None)
                if measured_value is None:
                    valid = False
                    break

                for key, value in row[key].items():
                    if key == 'to' and measured_value <= value:
                        pass
                    elif key == 'from' and measured_value >= value:
                        pass
                    else:
                        valid = False

        if valid:
            log.debug(row)
            color = row['color']
            break

    if color:
        pixels = make_pixels(*color, brightness=userdata['config']['brightness'])
        client.publish('nodes/base/led-strip/-/set', json.dumps({'pixels': pixels}))


def mgtt_on_connect(client, userdata, flags, rc):
    log.info('Connected to MQTT broker (code %s)', rc)

    for topic in ('plugin/led-strip/config',
                  'plugin/led-strip/config/set',
                  'nodes/remote/+/+',
                  'nodes/base/push-button/-'):
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

    if msg.topic == 'nodes/remote/thermometer/i2c0-49':
        try:
            userdata['temperature'] = float(payload['temperature'][0])
            userdata['temperature-ts'] = now
        except (TypeError, ValueError) as e:
            log.error('Invalid temperature: %s', e)

    elif msg.topic == 'nodes/remote/humidity-sensor/i2c0-40':
        try:
            userdata['relative-humidity'] = float(payload['relative-humidity'][0])
            userdata['relative-humidity-ts'] = now
        except (TypeError, ValueError) as e:
            log.error('Invalid relative-humidity: %s', e)

    elif msg.topic == 'plugin/led-strip/config':
        try:
            check_config(payload)
            userdata['config'] = payload
        except Exception as e:
            log.error('Invalid config: %s', e)

    elif msg.topic == 'plugin/led-strip/config/set':
        if 'brightness' in payload:
            config = userdata['config']
            config['brightness'] = payload['brightness']
            try:
                check_config(config)
                client.publish('plugin/led-strip/config', json.dumps(config), retain=True)
            except Exception as e:
                log.error('Invalid config: %s', e)
            return

    set_led_strip(client, userdata)


def main():
    arguments = docopt(__doc__, version='bc-workroom-ledstrip %s' % __version__)
    opts = {k.lstrip('-').replace('-', '_'): v
            for k, v in arguments.items() if v}

    log.basicConfig(level=DEBUG if opts.get('debug') else INFO, format=LOG_FORMAT)

    check_config(DEFAULT_PLUGIN_CONFIG)

    client = mqtt.Client(userdata={'config': DEFAULT_PLUGIN_CONFIG})
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
