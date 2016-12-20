#!/usr/bin/env nodejs
"use strict";
/**
 * Plugin: for http://www.blynk.cc/
 *
 * virtual pin 0 - temperature
 * virtual pin 1 - relative-humidity
 * virtual pin 2 - set brightness range 0 .. 255
 * virtual pin 3 - light
 * virtual pin 4 - relay
 *
 * Example config:
 * mosquitto_pub -t "plugin/blynk/config" -m '{"token":"your token id"}' -r
 */

var doc = "BigClown plugin for http://www.blynk.cc/.\n\
\n\
Usage:\n\
  bc-workroom-blynk [options]\n\
  bc-workroom-blynk --help\n\
\n\
Options:\n\
  -D --debug                   Print debug messages.\n\
  -h HOST --host=HOST          MQTT host to connect to (default is localhost).\n\
  -p PORT --port=PORT          MQTT port to connect to (default is 1883).\n\
  -t TOPIC --base-topic=TOPIC  Base MQTT topic (default is nodes).\n\
  -v --version                 Print version.\n\
  --help                       Show this message.\n\
";
var VERSION = require('./package.json').version;

var mqtt = require('mqtt');
var blynkLib = require('blynk-library');
var docopt = require('docopt');
var Log = require('log');

var options = docopt.docopt(doc, {version: 'bc-workroom-blynk ' + VERSION});

var logging = new Log(options['--debug'] ? 'debug' : 'info');

var DEFAULT_MQTT_HOST = 'localhost';
var DEFAULT_MQTT_PORT = 1883;
var DEFAULT_MQTT_TOPIC = 'blynk';

var brokerUrl = "mqtt://" + (options['--host'] || DEFAULT_MQTT_HOST) + ":" + (options['--port'] || DEFAULT_MQTT_PORT)
var client = mqtt.connect(brokerUrl);
var blynkClient = null;
var pluginTopic = "plugin/" + (options['--base-topic'] || DEFAULT_MQTT_TOPIC);

function BlynkClient(token, client) {
  this.token = token;
  var blynk = new blynkLib.Blynk(token);

  var v0 = new blynk.VirtualPin(0);
  var v1 = new blynk.VirtualPin(1);
  var v2 = new blynk.VirtualPin(2);
  var v3 = new blynk.VirtualPin(3);
  var v4 = new blynk.VirtualPin(4);

  function addSubscibe() {
    logging.debug("mqtt subscribe", "nodes/remote/+/+");
    client.subscribe("nodes/remote/+/+");
    logging.debug("mqtt subscribe", "nodes/base/light/-");
    client.subscribe("nodes/base/light/-");

    client.publish("nodes/base/light/-/get", "{}");
    client.publish("nodes/base/relay/-/get", "{}");
  }

  v2.on('write', function(value) {
    logging.debug('blynk v2', 'on write', value[0]);
    client.publish("plugin/led-strip/config/set", JSON.stringify({ "brightness": parseInt(value[0]) }));
  });

  v3.on('write', function(value) {
    logging.debug('blynk v3', 'on write', value[0]);
    client.publish("nodes/base/light/-/set", JSON.stringify({ "state": value[0] == "1" ? true : false }));
  });

  v4.on('write', function(value) {
    logging.debug('blynk v4', 'on write', value[0]);
    client.publish("nodes/base/relay/-/set", JSON.stringify({ "state": value[0] == "1" ? true : false }));
  });

  function clientMessage(topic, message) {
    logging.debug("BlynkClient message", topic, message.toString());

    if (!message) return;

    try {
      var payload = JSON.parse(message.toString());

      if ((topic === "nodes/remote/thermometer/i2c0-49") || topic === "nodes/remote/thermometer/i2c1-49") {
        if (payload['temperature']) {
          v0.write(payload['temperature'][0]);
        }
        
      } else if ((topic === "nodes/remote/humidity-sensor/i2c0-40") || (topic === "nodes/remote/humidity-sensor/i2c1-40") ) {
        if (payload['relative-humidity']) {
          v1.write(payload['relative-humidity'][0]);
        }

      } else if (topic === "nodes/base/light/-") {
        v3.write(payload['state'] ? "1" : "0");

      } else if (topic === "nodes/base/relay/-") {
        v4.write(payload['state'] ? "1" : "0");

      }

    } catch (error) {
      logging.error('Error', error, topic, message.toString());
      return;
    }
  }

  client.on('message', clientMessage);
  client.on('connect', addSubscibe);
  blynk.on('connect', addSubscibe);

  this.destroy = function() {
    blynk.removeListener('connect', addSubscibe);
    clearInterval(blynk.timerConn);
    client.removeListener('connect', addSubscibe);
    client.removeListener('message', clientMessage);
    client.unsubscribe(v0_topic);
    client.unsubscribe(v1_topic);
    blynk.disconnect(false);
  }
}

client.on('connect', function() {
  logging.info("mqtt connect");
  logging.debug("mqtt subscribe", pluginTopic + "/config");
  client.subscribe(pluginTopic + "/config")
});

client.on('message', function(topic, message) {

  if (topic === pluginTopic + "/config") {
    var payload = JSON.parse(message.toString());
    logging.debug(topic, payload);

    if (payload.token) {
      if (!blynkClient) {
        logging.info("start BlynkClient");
        blynkClient = new BlynkClient(payload.token, client);

      } else if (blynkClient.token !== payload.token) {
        logging.info("destroy BlynkClient");
        blynkClient.destroy();
        logging.info("start BlynkClient");
        blynkClient = new BlynkClient(payload.token, client);

      }
    }
  }

});

client.on('disconnect', function() {
  logging.info("mqtt disconnect");
})
