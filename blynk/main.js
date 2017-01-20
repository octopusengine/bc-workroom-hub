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
 * virtual pin 5 - zeRGBa widget
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
  var v5 = new blynk.VirtualPin(5);

  var topics = ["nodes/remote/+/+", "nodes/base/light/-", "plugin/led-strip/data/set/ok", "plugin/led-strip/data"];

  function addSubscibe() {
    for(var topic of topics) {
        logging.debug("mqtt subscribe", topic);
        client.subscribe(topic);
    }

    client.publish("nodes/base/light/-/get", "{}");
    client.publish("nodes/base/relay/-/get", "{}");
    client.publish("plugin/led-strip/data/get", "{}");
  }

  v2.on('write', function(value) {
    logging.debug('blynk v2', 'on write', value[0]);
    var brightness = Math.floor(parseInt(value[0]) / 1023 * 255);
    client.publish("plugin/led-strip/data/set", JSON.stringify({ "brightness": brightness}), {retain: true} );
  });

  v3.on('write', function(value) {
    logging.debug('blynk v3', 'on write', value[0]);
    client.publish("nodes/base/light/-/set", JSON.stringify({ "state": value[0] == "1" ? true : false }));
  });

  v4.on('write', function(value) {
    logging.debug('blynk v4', 'on write', value[0]);
    client.publish("nodes/base/relay/-/set", JSON.stringify({ "state": value[0] == "1" ? true : false }));
  });

  v5.on('write', function(value) {
    logging.debug('blynk v5', 'on write', value);

    var payload = {"state": "rules"};

    if ((value[0] !== '1023') || (value[1] !== '1023') && (value[2] !== '1023')) {
      var red = Math.floor((parseInt(value[0]) || 0) / 1023 * 255);
      var green = Math.floor((parseInt(value[1]) || 0) / 1023 * 255);
      var blue = Math.floor((parseInt(value[2]) || 0) / 1023 * 255);
      payload = {"color": [red, green, blue, 0], "state": "color"};
    }

    client.publish("plugin/led-strip/data/set", JSON.stringify(payload));
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

      } else if ((topic === "plugin/led-strip/data/set/ok") || (topic === "plugin/led-strip/data")) {
        if ('brightness' in payload) {
          v2.write(Math.floor(payload['brightness'] / 255 * 1023))
        }
        if ('color' in payload) {
          var red = Math.floor(payload['color'][0] / 255 * 1023);
          var green = Math.floor(payload['color'][1] / 255 * 1023);
          var blue = Math.floor(payload['color'][2] / 255 * 1023);
          v5.write([red, green, blue]);
        }
      }

    } catch (error) {
      logging.error('Error', error, topic, message.toString());
      return;
    }
  }

  client.on('message', clientMessage);
  client.on('connect', addSubscibe);
  blynk.on('connect', addSubscibe);
  blynk.on('error', function(e){
    logging.error('blynk', e);
    client.publish(pluginTopic + "/config/error", JSON.stringify({msg:e}));
  });

  this.destroy = function() {
    blynk.removeListener('connect', addSubscibe);
    clearInterval(blynk.timerConn);
    client.removeListener('connect', addSubscibe);
    client.removeListener('message', clientMessage);
    for(var topic of topics) {
        client.unsubscribe(topic);
    }
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
