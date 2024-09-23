# coding=utf-8
from __future__ import absolute_import

import json
import six
import time
from collections import deque

import octoprint.plugin

from octoprint.events import Events
from octoprint.util import dict_minimal_mergediff, RepeatedTimer
from .command_handler import CommandHandler


class PrintagoMqttConnector(octoprint.plugin.SettingsPlugin,
                 octoprint.plugin.StartupPlugin,
                 octoprint.plugin.ShutdownPlugin,
                 octoprint.plugin.EventHandlerPlugin,
                 octoprint.plugin.ProgressPlugin,
                 octoprint.plugin.TemplatePlugin,
                 octoprint.plugin.AssetPlugin,
                 octoprint.printer.PrinterCallback):

    EVENT_CLASS_TO_EVENT_LIST = dict(server   = (Events.STARTUP, Events.SHUTDOWN, Events.CLIENT_OPENED,
                                                 Events.CLIENT_CLOSED, Events.CONNECTIVITY_CHANGED),
                                     comm     = (Events.CONNECTING, Events.CONNECTED, Events.DISCONNECTING,
                                                 Events.DISCONNECTED, Events.ERROR, Events.PRINTER_STATE_CHANGED),
                                     files    = (Events.UPLOAD, Events.FILE_ADDED, Events.FILE_REMOVED,
                                                 Events.FOLDER_ADDED, Events.FOLDER_REMOVED, Events.UPDATED_FILES,
                                                 Events.METADATA_ANALYSIS_STARTED, Events.METADATA_ANALYSIS_FINISHED,
                                                 Events.FILE_SELECTED, Events.FILE_DESELECTED, Events.TRANSFER_STARTED,
                                                 Events.TRANSFER_FAILED, Events.TRANSFER_DONE),
                                     printjob = (Events.PRINT_STARTED, Events.PRINT_FAILED, Events.PRINT_DONE,
                                                 Events.PRINT_CANCELLED, Events.PRINT_PAUSED, Events.PRINT_RESUMED),
                                     gcode    = (Events.POWER_ON, Events.POWER_OFF, Events.HOME, Events.DWELL,
                                                 Events.WAITING, Events.COOLING, Events.ALERT, Events.CONVEYOR,
                                                 Events.EJECT, Events.E_STOP, Events.TOOL_CHANGE),
                                     position = (Events.Z_CHANGE, Events.POSITION_UPDATE),
                                     timelapse= (Events.CAPTURE_START, Events.CAPTURE_FAILED, Events.CAPTURE_DONE,
                                                 Events.MOVIE_RENDERING, Events.MOVIE_FAILED, Events.MOVIE_FAILED),
                                     slicing  = (Events.SLICING_STARTED, Events.SLICING_DONE, Events.SLICING_CANCELLED,
                                                 Events.SLICING_FAILED, Events.SLICING_PROFILE_ADDED,
                                                 Events.SLICING_PROFILE_DELETED, Events.SLICING_PROFILE_MODIFIED),
                                     settings = (Events.SETTINGS_UPDATED,))

    LWT_CONNECTED = "connected"
    LWT_DISCONNECTED = "disconnected"

    def __init__(self):
        self._mqtt = None
        self._mqtt_connected = False
        self._mqtt_reset_state = True

        self._mqtt_subscriptions = []

        self._mqtt_publish_queue = deque()
        self._mqtt_subscribe_queue = deque()

        self.lastTemp = {}

        self.progress_timer = None
        self.last_progress = {"storage": "", "path": "", "progress": -1}

    def initialize(self):
        self._printer.register_callback(self)

        if self._settings.get(["broker", "url"]) is None:
            self._logger.error("No broker URL defined, MQTT plugin won't be able to work")
            return False
        
        self.command_handler = CommandHandler(self)

    ##~~ TemplatePlugin API

    def get_template_configs(self):
        return [
            dict(type="settings", name="MQTT")
        ]

    ##~~ AssetPlugin API

    def get_assets(self):
        return dict(js=["js/mqtt.js"])

    ##~~ StartupPlugin API

    def on_startup(self, host, port):
        self.mqtt_connect()

    ##~~ ShutdownPlugin API

    def on_shutdown(self):
        self.mqtt_disconnect(force=True)

    ##~~ SettingsPlugin API

    def get_settings_defaults(self):

        return dict(
            broker=dict(
                url=None,
                port=1883,
                username=None,
                password=None,
                keepalive=60,
                tls_active=False,
                tls=dict(),
                tls_insecure=False,
                protocol="MQTTv31",
                retain=True,
                lwRetain=True,
                clean_session=True
            ),
            publish=dict(
                baseTopic="octoPrint/",
                eventTopic="event/{event}",
                eventActive=True,
                printerData=False,
                events=dict(server=True,
                            comm=True,
                            files=True,
                            printjob=True,
                            gcode=True,
                            position=True,
                            timelapse=True,
                            slicing=True,
                            settings=True,
                            unclassified=True),

                progressTopic="progress/{progress}",
                progressActive=True,

                temperatureTopic="temperature/{temp}",
                temperatureActive=True,
                temperatureThreshold=1.0,

                metadataTopic="metadata/{key}",
                metadataActive=False,
                metadataKeys="",

                lwTopic="mqtt",
                lwActive=True
            ),
            client=dict(
                client_id=None
            ),
            printago=dict(
                _private_key=None,             # Private key (hidden)
                _public_key=None,              # Public key (hidden)
                reconnect_interval=5,
                max_printago_files=10,
                stream_while_printing=False,
                camera_name=None,
                printer_id="",
                pairing_status=False,
                printago_account_name=""
                # Add other settings as needed
            ),
            timestamp_fieldname="_timestamp"
        )

    def on_settings_save(self, data):
        old_broker_data = self._settings.get(["broker"])
        old_lw_active = self._settings.get_boolean(["publish", "lwActive"])
        old_lw_topic = self._get_topic("lw")
        old_client_data = self._settings.get(["client"])

        octoprint.plugin.SettingsPlugin.on_settings_save(self, data)

        new_broker_data = self._settings.get(["broker"])
        new_lw_active = self._settings.get_boolean(["publish", "lwActive"])
        new_lw_topic = self._get_topic("lw")
        new_client_data = self._settings.get(["client"])

        broker_diff = dict_minimal_mergediff(old_broker_data, new_broker_data)
        client_diff = dict_minimal_mergediff(old_client_data, new_client_data)
        lw_diff = dict_minimal_mergediff(dict(lw_active=old_lw_active,
                                              lw_topic=old_lw_topic),
                                         dict(lw_active=new_lw_active,
                                              lw_topic=new_lw_topic))
        if len(broker_diff) or len(lw_diff) or len(client_diff):
            # something changed
            self._logger.info("Settings changed (broker_diff={!r}, lw_diff={!r}), reconnecting to broker".format(broker_diff, lw_diff))
            self.mqtt_disconnect(force=True, incl_lwt=old_lw_active, lwt=old_lw_topic)
            self.mqtt_connect()

    ##~~ EventHandlerPlugin API

    def on_event(self, event, payload):
        if event in [Events.PRINT_STARTED, Events.PRINT_DONE, Events.FILE_SELECTED, Events.FILE_DESELECTED]:
            if self.progress_timer is None:
                self.progress_timer = RepeatedTimer(5, self._update_progress, [payload["origin"], payload["path"]])
                self.progress_timer.start()


        if event in [Events.PRINT_STARTED, Events.PRINT_DONE, Events.PRINT_FAILED, Events.PRINT_CANCELLED]:
            self.on_additional_metadata(payload["origin"], payload["path"], event)

        topic = self._get_topic("event")

        if topic:
            if self._is_event_active(event):
                if payload is None:
                    data = dict()
                else:
                    data = dict(payload)
                data["_event"] = event

                _retained = self._settings.get_boolean(["broker", "retain"])
                if not _retained or event not in ["ZChange", "FirmwareData"]:
                    _retained = False

                self.mqtt_publish_with_timestamp(topic.format(event=event), data, retained=_retained)

    ##~~ ProgressPlugin API

    def _update_progress(self, storage, path):
        topic = self._get_topic("progress")

        if topic:
            printer_data = self._printer.get_current_data()
            print_job_progress = printer_data["progress"]
            progress = 0

            if "completion" in print_job_progress and print_job_progress["completion"] is not None:
                progress = round(float(print_job_progress["completion"]))
            if "printTimeLeftOrigin" in print_job_progress and print_job_progress["printTimeLeftOrigin"] == "genius":
                progress = round(float(print_job_progress["printTime"] or 0) / (float(print_job_progress["printTime"] or 0) + float(print_job_progress["printTimeLeft"])) * 100)

            if print_job_progress.get("completion") in [None, 100]:
                if self.progress_timer is not None:
                    self.progress_timer.cancel()
                    self.progress_timer = None

            data = dict(location=storage,
                        path=path,
                        progress=progress)

            if self._settings.get_boolean(["publish", "printerData"]):
                data['printer_data'] = printer_data

            if self.last_progress["progress"] != data["progress"] or self.last_progress["path"] != data["path"]:
                self.mqtt_publish_with_timestamp(topic.format(progress="printing"), data, retained=True)
                self.last_progress = data

    def on_slicing_progress(self, slicer, source_location, source_path, destination_location, destination_path, progress):
        topic = self._get_topic("progress")

        if topic:
            data = dict(slicer=slicer,
                        source_location=source_location,
                        source_path=source_path,
                        destination_location=destination_location,
                        destination_path=destination_path,
                        progress=progress)
            self.mqtt_publish_with_timestamp(topic.format(progress="slicing"), data)

    ##~~ Additional Metadata

    def on_additional_metadata(self, origin, path, event):
        if not self._settings.get_boolean(["publish", "metadataActive"]):
            return

        keys = list(set([key.strip() for key in self._settings.get(["publish", "metadataKeys"]).split(",") if key.strip() != ""]))

        if not keys:
            self._logger.warn("No metadata keys defined, can't publish metadata")
            return

        topic = self._get_topic("metadata")

        if not topic:
            self._logger.warn("No metadata topic defined, can't publish metadata")
            return

        if event == Events.PRINT_STARTED:
            storage = self._file_manager._storage(origin)
            file = storage.path_on_disk(path)

            def _get_nested_value(data, key):
                first, _, rest = key.partition(".")
                value = data.get(first)

                if rest:
                    return _get_nested_value(value, rest) if isinstance(value, dict) else None
                else:
                    return value

            for key in keys:
                if "." not in key:
                    value = storage.get_additional_metadata(file, key)
                else:
                    first, _, rest = key.partition(".")
                    data = storage.get_additional_metadata(file, first)
                    value = _get_nested_value(data, rest) if isinstance(data, dict) else None

                if isinstance(value, (dict, list)):
                    value = json.dumps(value)

                if not isinstance(value, (six.string_types, six.integer_types, float, bytearray, type(None))):
                    self._logger.warn("Metadata key {key} is not a simple type, can't publish".format(key=key))
                    continue

                self.mqtt_publish(topic.format(key=key), value, raw_data=True)
        elif event in [Events.PRINT_DONE, Events.PRINT_FAILED, Events.PRINT_CANCELLED]:
            for key in keys:
                self.mqtt_publish(topic.format(key=key), None, raw_data=True)

    ##~~ PrinterCallback

    def on_printer_add_temperature(self, data):
        topic = self._get_topic("temperature")
        threshold = self._settings.get_float(["publish", "temperatureThreshold"])

        if topic:
            for key, value in data.items():
                if key == "time":
                    continue

                # skip any entries that are none or zero.
                if not (value.get("actual") or value.get("target")):
                    continue

                # in issue #42 the problem wasn't a failure to get the key, but
                # the last_temp value was None. Hence "or 0". However by pulling
                # lastTemp we risk failing on the dict navigation, so we'll be careful.
                safe_actual_temp = value.get("actual") or 0
                safe_actual_target_temp = value.get("target") or 0
                safe_last_temp = 0
                safe_last_target_temp = 0
                if key in self.lastTemp:
                    safe_last_temp = self.lastTemp[key].get("actual") or 0
                    safe_last_target_temp = self.lastTemp[key].get("target") or 0

                # some pedantry on the target temp to keep away from float math problems
                if not safe_last_temp \
                    or abs(safe_actual_temp - safe_last_temp) >= threshold \
                    or abs(safe_actual_target_temp - safe_last_target_temp) >= 0.1:
                    # unknown key, new actual or new target -> update mqtt topic!
                    dataset = dict(actual=value["actual"],
                                   target=value["target"])
                    self.mqtt_publish_with_timestamp(topic.format(temp=key), dataset,
                                                     allow_queueing=True,
                                                     timestamp=data["time"])
                    self.lastTemp.update({key: data[key]})

    ##~~ Softwareupdate hook

    def get_update_information(self):
        return dict(
            mqtt=dict(
                displayName=self._plugin_name,
                displayVersion=self._plugin_version,

                # version check: github repository
                type="github_release",
                user="OctoPrint",
                repo="OctoPrint-MQTT",
                current=self._plugin_version,

                # update method: pip
                pip="https://github.com/OctoPrint/OctoPrint-MQTT/archive/{target_version}.zip"
            )
        )

    ##~~ helpers

    def mqtt_connect(self):
        broker_url = self._settings.get(["broker", "url"])
        broker_port = self._settings.get_int(["broker", "port"])
        broker_username = self._settings.get(["broker", "username"])
        broker_password = self._settings.get(["broker", "password"])
        broker_keepalive = self._settings.get_int(["broker", "keepalive"])
        broker_tls_active = self._settings.get(["broker", "tls_active"])
        broker_tls = self._settings.get(["broker", "tls"], asdict=True)
        broker_tls_insecure = self._settings.get_boolean(["broker", "tls_insecure"])
        broker_protocol = self._settings.get(["broker", "protocol"])
        client_id = self._settings.get(["client", "client_id"])
        clean_session = self._settings.get_boolean(["broker", "clean_session"])

        lw_active = self._settings.get_boolean(["publish", "lwActive"])
        lw_retain = self._settings.get_boolean(["broker", "lwRetain"])
        lw_topic = self._get_topic("lw")

        if broker_url is None:
            self._logger.warn("Broker URL is None, can't connect to broker")
            return

        import paho.mqtt.client as mqtt

        protocol_map = dict(MQTTv31=mqtt.MQTTv31, MQTTv311=mqtt.MQTTv311)
        if broker_protocol in protocol_map:
            protocol = protocol_map[broker_protocol]
        else:
            protocol = mqtt.MQTTv31

        if self._mqtt is None:
            self._mqtt = mqtt.Client(client_id=client_id, protocol=protocol, clean_session=clean_session)
        else:
            self._mqtt.reinitialise() #otherwise tls_set might be called again causing the plugin to crash

        if broker_username is not None:
            self._mqtt.username_pw_set(broker_username, password=broker_password)

        if broker_tls_active:
            tls_args = dict((key, value) for key, value in broker_tls.items() if value)
            self._mqtt.tls_set(**tls_args)

        if broker_tls_insecure and broker_tls_active:
            self._mqtt.tls_insecure_set(broker_tls_insecure)

        if lw_active and lw_topic:
            self._mqtt.will_set(lw_topic, self.LWT_DISCONNECTED, qos=1, retain=lw_retain)

        self._mqtt.on_connect = self._on_mqtt_connect
        self._mqtt.on_disconnect = self._on_mqtt_disconnect
        self._mqtt.on_message = self._on_mqtt_message

        self._mqtt.connect_async(broker_url, broker_port, keepalive=broker_keepalive)
        if self._mqtt.loop_start() == mqtt.MQTT_ERR_INVAL:
            self._logger.error("Could not start MQTT connection, loop_start returned MQTT_ERR_INVAL")

    def mqtt_disconnect(self, force=False, incl_lwt=True, lwt=None):
        if self._mqtt is None:
            return

        if incl_lwt:
            if lwt is None:
                lwt = self._get_topic("lw")
            if lwt:
                _retain = self._settings.get_boolean(["broker", "lwRetain"])
                self._mqtt.publish(lwt, self.LWT_DISCONNECTED, qos=1, retain=_retain)

        self._mqtt.loop_stop()

        if force:
            time.sleep(1)
            self._mqtt.loop_stop(force=True)

    def mqtt_publish_with_timestamp(self, topic, payload, retained=None, qos=0, allow_queueing=False, timestamp=None):
        if not payload:
            payload = dict()
        if not isinstance(payload, dict):
            raise ValueError("payload must be a dict")

        if timestamp is None:
            timestamp = time.time()

        timestamp_fieldname = self._settings.get(["timestamp_fieldname"])
        payload[timestamp_fieldname] = int(timestamp)

        if retained is None:
            retained = self._settings.get_boolean(["broker", "retain"])

        return self.mqtt_publish(topic, payload, retained=retained, qos=qos, allow_queueing=allow_queueing)

    def mqtt_publish(self, topic, payload, retained=None, qos=0, allow_queueing=False, raw_data=False):
        if not (isinstance(payload, six.string_types) or raw_data):
            payload = json.dumps(payload)

        if not self._mqtt_connected:
            if allow_queueing:
                self._logger.debug("Not connected, enqueuing message: {topic} - {payload}".format(**locals()))
                self._mqtt_publish_queue.append((topic, payload, qos))
                return True
            else:
                return False

        _retain = retained
        if retained is None:
            _retain = self._settings.get_boolean(["broker", "retain"])

        self._mqtt.publish(topic, payload=payload, retain=_retain, qos=qos)
        self._logger.debug("Sent message: {topic} - {payload}, retain={_retain}".format(**locals()))
        return True

    def mqtt_subscribe(self, topic, callback, args=None, kwargs=None):
        if args is None:
            args = []
        if kwargs is None:
            kwargs = dict()

        self._mqtt_subscriptions.append((topic, callback, args, kwargs))

        if not self._mqtt_connected:
            self._mqtt_subscribe_queue.append(topic)
        else:
            self._mqtt.subscribe(topic)

    def mqtt_unsubscribe(self, callback, topic=None):
        subbed_topics = [subbed_topic for subbed_topic, subbed_callback, _, _ in self._mqtt_subscriptions if callback == subbed_callback and (topic is None or topic == subbed_topic)]

        def remove_sub(entry):
            subbed_topic, subbed_callback, _, _ = entry
            return not (callback == subbed_callback and (topic is None or subbed_topic == topic))

        self._mqtt_subscriptions = list(filter(remove_sub, self._mqtt_subscriptions))

        if self._mqtt_connected and subbed_topics:
            self._mqtt.unsubscribe(*subbed_topics)

    ##~~ mqtt client callbacks

    def _on_mqtt_connect(self, client, userdata, flags, rc):
        if not client == self._mqtt:
            return

        if not rc == 0:
            reasons = [
                None,
                "Connection to mqtt broker refused, wrong protocol version",
                "Connection to mqtt broker refused, incorrect client identifier",
                "Connection to mqtt broker refused, server unavailable",
                "Connection to mqtt broker refused, bad username or password",
                "Connection to mqtt broker refused, not authorised"
            ]

            if rc < len(reasons):
                reason = reasons[rc]
            else:
                reason = None

            self._logger.error(reason if reason else "Connection to mqtt broker refused, unknown error")
            return

        self._logger.info("Connected to mqtt broker")
        lw_active = self._settings.get_boolean(["publish", "lwActive"])
        lw_topic = self._get_topic("lw")
        lw_retain = self._settings.get_boolean(["broker", "lwRetain"])
        if lw_active and lw_topic:
            self._mqtt.publish(lw_topic, self.LWT_CONNECTED, qos=1, retain=lw_retain)

        _retain = self._settings.get_boolean(["broker", "retain"])
        if self._mqtt_publish_queue:
            try:
                while True:
                    topic, payload, qos = self._mqtt_publish_queue.popleft()
                    self._mqtt.publish(topic, payload=payload, retain=_retain, qos=qos)
            except IndexError:
                # that's ok, queue is just empty
                pass

        subbed_topics = list(map(lambda t: (t, 0), {topic for topic, _, _, _ in self._mqtt_subscriptions}))
        if subbed_topics:
            self._mqtt.subscribe(subbed_topics)
            self._logger.debug("Subscribed to topics")

        self._mqtt_connected = True

        if self._mqtt_reset_state:
            self._update_progress("", "")
            self.on_slicing_progress("", "", "", "", "", 0)
            self._mqtt_reset_state = False

    def _on_mqtt_disconnect(self, client, userdata, rc):
        if not client == self._mqtt:
            return

        if not rc == 0:
            self._logger.error("Disconnected from mqtt broker for unknown reasons (network error?), rc = {}".format(rc))
        else:
            self._logger.info("Disconnected from mqtt broker")

        self._mqtt_connected = False

    def _on_mqtt_message(self, client, userdata, msg):
        if not client == self._mqtt:
            return

        from paho.mqtt.client import topic_matches_sub
        for subscription in self._mqtt_subscriptions:
            topic, callback, args, kwargs = subscription
            if topic_matches_sub(topic, msg.topic):
                args = [msg.topic, msg.payload] + args
                kwargs.update(dict(retained=msg.retain, qos=msg.qos))
                try:
                    callback(*args, **kwargs)
                except:
                    self._logger.exception("Error while calling mqtt callback")

    def _get_topic(self, topic_type):
        sub_topic = self._settings.get(["publish", topic_type + "Topic"])
        topic_active = self._settings.get(["publish", topic_type + "Active"])

        if not sub_topic or not topic_active:
            return None

        return self._settings.get(["publish", "baseTopic"]) + sub_topic

    def _is_event_active(self, event):
        for event_class, events in self.EVENT_CLASS_TO_EVENT_LIST.items():
            if event in events:
                return self._settings.get_boolean(["publish", "events", event_class])
        return self._settings.get_boolean(["publish", "events", "unclassified"])

    def on_gcode_received(self, comm, line, *args, **kwargs):
        if line.startswith('echo:busy: paused for user'):
            topic = self._get_topic("event")
            event = 'PausedForUser'
            payload = dict()
            payload["_event"] = event
            self.mqtt_publish_with_timestamp(topic.format(event=event), payload)
        return line


__plugin_name__ = "Printago Connector"
__plugin_pythoncompat__ = ">=2.7,<4"

def __plugin_load__():
    plugin = PrintagoMqttConnector()

    global __plugin_helpers__
    __plugin_helpers__ = dict(
        mqtt_publish=plugin.mqtt_publish,
        mqtt_publish_with_timestamp=plugin.mqtt_publish_with_timestamp,
        mqtt_subscribe=plugin.mqtt_subscribe,
        mqtt_unsubscribe=plugin.mqtt_unsubscribe
    )

    global __plugin_implementation__
    __plugin_implementation__ = plugin

    global __plugin_hooks__
    __plugin_hooks__ = {
        "octoprint.plugin.softwareupdate.check_config": __plugin_implementation__.get_update_information,
        "octoprint.comm.protocol.gcode.received": __plugin_implementation__.on_gcode_received,
    }
