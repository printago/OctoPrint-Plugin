import os
import json
import requests
import datetime
from octoprint.filemanager import FileDestinations
from io import BytesIO
from urllib.parse import urlparse
from PIL import Image


class FileWrapper:
    def __init__(self, obj):
        self.obj = obj

    def save(self, path):
        with open(path, 'wb') as f:
            f.write(self.obj.getvalue())


class CommandHandler:
    def __init__(self, plugin_instance):
        self.plugin = plugin_instance
        self._logger = plugin_instance._logger
        self._printer = plugin_instance._printer
        self._file_manager = plugin_instance._file_manager
        self._plugin_manager = plugin_instance._plugin_manager
        self._settings = plugin_instance._settings

        self._currentCommandType = None
        self._currentCommandAction = None
        self._currentCommandParameters = None

        # Subscribe to incoming MQTT commands
        self.subscribe_to_mqtt_commands()

    def subscribe_to_mqtt_commands(self):
        command_topic = self._settings.get(["mqtt", "command_topic"])
        if not command_topic:
            command_topic = "octoprint/commands"
        self.plugin.mqtt_subscribe(command_topic, self.process_command)

    def process_command(self, topic, payload, **kwargs):
        try:
            message_data = json.loads(payload)

            if 'type' not in message_data:
                self._logger.error("No command type specified in the received message.")
                self.send_error_message("No command type specified in the received message.")
                return
            self._currentCommandType = message_data["type"]

            if 'action' not in message_data:
                self._logger.error(f"No action specified for {self._currentCommandType} command.")
                self.send_error_message(f"No action specified for {self._currentCommandType} command.")
                return
            self._currentCommandAction = message_data["action"]

            if 'parameters' not in message_data:
                self._logger.error(f"No parameters specified for {self._currentCommandAction} action.")
                self.send_error_message(f"No parameters specified for {self._currentCommandAction} action.")
                return
            self._currentCommandParameters = message_data["parameters"]

            if self._currentCommandType == "printer_control":
                self._logger.info("Processing Printago Printer Control Command")
                self._handle_printer_control(message_data)
        
            elif self._currentCommandType == "temperature_control":
                self._logger.info("Processing Printago Temperature Control Command")
                self._handle_temperature_control(message_data)
            
            elif self._currentCommandType == "movement_control":
                self._logger.info("Processing Printago Movement Control Command")
                self._handle_movement_control(message_data)

            elif self._currentCommandType == "camera_control":
                self._logger.info("Processing Printago Webcam Control Command")
                self._handle_camera_control(message_data)

            else:
                self._logger.warning(f"Unknown command type: {self._currentCommandType}")
                self.send_error_message(f"Unknown Printago command type: {self._currentCommandType}")

        except Exception as e:
            self._logger.error(f"Error processing message: {e}")
            self.send_error_message(f"Error processing message {str(e)}")

    def _handle_printer_control(self, message_data):
        self._logger.info(f"Processing Printago command - printer_control::{self._currentCommandAction}")

        if self._currentCommandAction == "download_gcode":
            if "url" in self._currentCommandParameters:
                self.download_file(self._currentCommandParameters.get["url"], None)
            else:
                self._logger.error("No URL provided for downloading file.")
                self.send_error_message("No URL provided for downloading file.")

        elif self._currentCommandAction == "pause_print":
            try:
                self._printer.pause_print()
                self.send_success_message("Print paused command issued successfully.")
            except Exception as e:
                self._logger.error(f"Error pausing print: {e}")
                self.send_error_message(f"Error pausing print: {e}")
            
        elif self._currentCommandAction == "resume_print":
            try:
                self._printer.resume_print()
                self.send_success_message("Print resumed command issued successfully.")
            except Exception as e:
                self._logger.error(f"Error resuming print: {e}")
                self.send_error_message(f"Error resuming print: {e}")

        elif self._currentCommandAction == "stop_print":
            try:
                self._printer.cancel_print()
                self.send_success_message("Print stop command issued successfully.")
            except Exception as e:
                self._logger.error(f"Error stopping print: {e}")
                self.send_error_message(f"Error stopping print: {e}")

        elif self._currentCommandAction == "get_status":
            self.send_printer_status()
            
        elif self._currentCommandAction == "start_print":
            file_path = 'Printago/'
            file_name = message_data["parameters"].get("file_name", None) 
            if not file_name.startswith(file_path):
                file_name = file_path + file_name
            if self._file_manager.file_exists(FileDestinations.LOCAL, file_name): 
                try:
                    self._printer.select_file(file_name, sd=False, printAfterSelect=True)
                    self.send_success_message("Print start command issued successfully.")
                except Exception as e:
                    self._logger.error(f"Error starting print: {e}")
                    self.send_error_message(f"Error starting print: {e}")
            else:
                self._logger.info(f"File does not exist: {file_name}")
                self.send_error_message(f"File does not exist: {file_name}")

        else:
            self._logger.warning(f"Unknown action for printer_control: {self._currentCommandAction}")
            self.send_error_message(f"Unknown action for printer_control: {self._currentCommandAction}")

    def _handle_temperature_control(self, message_data):
        self._logger.info(f"Processing Printago command - temperature_control::{self._currentCommandAction}")
        if self._currentCommandAction == "set_hotend":
            target_temp = self._currentCommandParameters.get("temperature", None)
            tool = self._currentCommandParameters.get("tool", 0)  # Default to the first tool if not specified

            if target_temp is not None:
                try:
                    toolText = "tool" + str(tool)
                    self._printer.set_temperature(toolText, target_temp)
                    self.send_success_message("Hotend temperature command issued successfully.")
                except Exception as e:
                    self._logger.error(f"Error setting hotend temperature: {e}")
                    self.send_error_message(f"Error setting hotend temperature: {e}")
                self._logger.info(f"Setting hotend {tool} temperature to {target_temp}°C.")
            else:
                self._logger.error("Target temperature not provided for setting hotend temperature.")
                self.send_error_message("Target temperature not provided for setting hotend temperature.")

        elif self._currentCommandAction == "set_bed":
            target_temp = self._currentCommandParameters.get("temperature", None)
            
            if target_temp is not None:
                try:
                    self._printer.set_temperature("bed", target_temp)
                    self.send_success_message("Bed temperature command issued successfully.")
                except Exception as e:
                    self._logger.error(f"Error setting bed temperature: {e}")
                    self.send_error_message(f"Error setting bed temperature: {e}")
                self._logger.info(f"Setting bed temperature to {target_temp}°C.")
            else:
                self._logger.error("Target temperature not provided for setting bed temperature.")
                self.send_error_message("Target temperature not provided for setting bed temperature.")

        else:
            self._logger.warning(f"Unknown action for temperature_control: {self._currentCommandAction}")
            self.send_error_message(f"Unknown action for temperature_control: {self._currentCommandAction}")

    def _handle_movement_control(self, message_data):
        self._logger.info(f"Processing Printago command - movement_control::{self._currentCommandAction}")
        if self._currentCommandAction == "jog":
            axes_data = self._currentCommandParameters.get("axes", None)
            relative = self._currentCommandParameters.get("relative", True)
            speed = self._currentCommandParameters.get("speed", None)
            tags = self._currentCommandParameters.get("tags", set())

            if axes_data:
                try:
                    self._printer.jog(axes=axes_data, relative=relative, speed=speed, tags=tags)
                    self.send_success_message("Jogging axes command issued successfully.")
                except Exception as e:
                    self._logger.error(f"Error jogging axes: {e}")
                    self.send_error_message(f"Error jogging axes: {e}")
                axes_str = ', '.join([f"{k}={v}" for k, v in axes_data.items()])
                self._logger.info(f"Jogging axes: {axes_str} with relative={relative} and speed={speed}.")
            else:
                self._logger.error("Invalid axes data provided for jogging.")
                self.send_error_message("Invalid axes data provided for jogging.")
    
        elif self._currentCommandAction == "extrude":
            amount = self._currentCommandParameters.get("amount", None)
            speed = self._currentCommandParameters.get("speed", None)
            tags = self._currentCommandParameters.get("used", set())
            
            if amount is not None:  
                try:
                    self._printer.extrude(amount=amount, speed=speed, tags=tags)
                    self.send_success_message("Extruding filament command issued successfully.")
                except Exception as e:
                    self._logger.error(f"Error extruding: {e}")
                    self.send_error_message(f"Error extruding: {e}")
                self._logger.info(f"Extruding {amount}mm of filament at speed={speed}.")
            else:
                self._logger.error("Invalid amount provided for extrusion.")
                self.send_error_message("Invalid amount provided for extrusion.")

        elif self._currentCommandAction == "home":
            axes = self._currentCommandParameters.get("axes", None)

            if isinstance(axes, str):
                axes = [axis.strip().lower() for axis in axes.split(",")]

            if axes:
                try:
                    self._printer.home(axes=axes)
                    self.send_success_message("Homing axes command issued successfully.")
                except Exception as e:
                    self._logger.error(f"Error homing axes: {e}")
                    self.send_error_message(f"Error homing axes: {e}")
                self._logger.info(f"Homing axes: {', '.join(axes)}.")
            else:
                self._logger.error(f"Invalid axes specified for homing: {axes}")
                self.send_error_message(f"Invalid axes specified for homing: {axes}")
        
        else:
            self._logger.warning(f"Unknown action for movement_control: {self._currentCommandAction}")
            self.send_error_message(f"Unknown action for movement_control: {self._currentCommandAction}")

    def _handle_camera_control(self, message_data):
        self._logger.info(f"Processing Printago command - webcam_control::{self._currentCommandAction}")
        if self._currentCommandAction == "get_providers":
            try:
                provider_info = self._get_webcam_provider_info()
                self.send_response_message(provider_info)

                self._logger.info(f"Webcam providers sent to Printago: {len(provider_info)}")
            except Exception as e:
                self._logger.error(f"Error getting webcam providers: {e}")
                self.send_error_message(f"Error getting webcam providers: {e}")
        
        elif self._currentCommandAction == "snapshot":
            params = self._currentCommandParameters
            
            if 'camera_provider_id' not in params or 'camera_name' not in params:
                self._logger.error("No webcam provider or name specified for webcam snapshot.")
                self.send_error_message("No webcam provider or name specified for webcam snapshot.")
                return
            
            camera_provider_id = params['camera_provider_id']
            camera_name = params['camera_name']

            try:
                camPlugin = self._plugin_manager.get_plugin(camera_provider_id).implementation
                self._logger.info(f"Taking webcam snapshot from {type(camPlugin)} - {camera_name}")
                jpeg_bytes = camPlugin.take_webcam_snapshot(camera_name)
                jpeg_image = Image.open(io.BytesIO(b"".join(jpeg_bytes)))
                png_buffer = io.BytesIO()
                jpeg_image.save(png_buffer, format="PNG")
                png_bytes = png_buffer.getvalue()

                self.send_success_message("Webcam snapshot command issued successfully.")
            except Exception as e:
                self._logger.error(f"Error capturing webcam snapshot: {e}")
                self.send_error_message(f"Error capturing webcam snapshot: {e}")
        
        else:
            self._logger.warning(f"Unknown action for webcam_control: {self._currentCommandAction}")
            self.send_error_message(f"Unknown action for webcam_control: {self._currentCommandAction}")

    ## Various helper functions like _get_webcam_provider_info, download_file, etc. remain unchanged

    def send_outgoing_message(self, msg_type, data):
        topic = f"octoprint/{msg_type}"
        printer_id = self._settings.get(["printago_id"])
        message = {
            "type": msg_type,
            "timestamp": datetime.datetime.utcnow().isoformat() + 'Z',
            "printer_id": printer_id,
            "client_type": 'octoprint',
            "data": data
        }
        self.plugin.mqtt_publish(topic, json.dumps(message))
        return json.dumps(message)

    # Helper methods for sending messages via MQTT
    def send_printer_status(self, storage=None, path=None, progress=None):
        stateId = self._printer.get_state_id()
        stateString = self._printer.get_state_string()
        stateData = self._printer.get_current_data()
        temperatures = self._printer.get_current_temperatures()
        job = self._printer.get_current_job()

        message_data = {
            "printer_state_id": stateId,
            "printer_state_string": stateString,
            "current_state_data": stateData,
            "temperatures": temperatures,
            "current_job": job,
            "storage": storage,
            "path": path,
            "progress": progress
        }

        # Remove None values from the message_data
        message_data = {k: v for k, v in message_data.items() if v is not None}
        self.send_outgoing_message("status", message_data)

    def send_error_message(self, error_data):
        error_message = {"error": error_data}
        self.send_outgoing_message("error", error_message)

    def send_success_message(self, successdata):
        self.send_outgoing_message("success", successdata)

    def send_response_message(self, response_data):
        self.send_outgoing_message("response", response_data)
