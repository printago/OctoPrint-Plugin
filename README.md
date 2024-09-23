# Printago-Connector

This plugin will authenticate to your Printago account (using cookies if available), and connects your printer server to your Printago account.  All your Octoprint instance needs is access to the internet.

## Setup

Install via the bundled [Plugin Manager](https://docs.octoprint.org/en/master/bundledplugins/pluginmanager.html)
or manually using this URL:

  https://github.com/printago/OctoPrint-Plugin/archive/master.zip

#### Overview
This plugin is forked from OctoPrint's  [MQTT Sample Project](https://github.com/OctoPrint/OctoPrint-MQTT). 
This README provides an overview of the command processing structure for an OctoPrint plugin. The plugin is designed to handle various commands related to 3D printer control, temperature management, movement control, and camera operations within the OctoPrint environment.
See the upstream repository for documentation on the MQTT implementation.

#### Command Structure
Commands are processed by the `CommandHandler` class. Each command comprises three required components:
- **Type**: Specifies the category of the command (e.g., printer control, temperature control).
- **Action**: Defines the specific action to be performed within the command type.
- **Parameters**: Additional data or settings required to execute the action. May be empty.

#### Command Processing
The `process_command` method of the `CommandHandler` class is responsible for parsing and executing commands. It checks for the presence of the `type`, `action`, and `parameters` fields in the received message and delegates the command to the appropriate handler based on the command type.

#### Error Handling
In case of missing information or errors during command processing, appropriate error messages are logged and sent back to the client.

#### Command Categories
- **Printer Control**: Handles actions related to the control of the 3D printer, like starting, pausing, and stopping prints.
- **Temperature Control**: Manages the temperature settings of the printer's hotend and bed.
- **Movement Control**: Deals with the movement of the printer's components, such as jogging and extrusion.
- **Camera Control**: Involves operations related to camera management, like taking snapshots and streaming.

---

### Command Table with Parameter Names

| Command Type       | Action            | Description                                                      | Parameters Required                         |
|--------------------|-------------------|------------------------------------------------------------------|---------------------------------------------|
| `printer_control`  | `download_gcode`  | Downloads GCode from a specified URL.                            | `url`                                       |
|                    | `pause_print`     | Pauses the ongoing print job.                                    | None                                        |
|                    | `resume_print`    | Resumes a paused print job.                                      | None                                        |
|                    | `stop_print`      | Stops the ongoing print job.                                     | None                                        |
|                    | `get_status`      | Retrieves the current status of the printer.                     | None                                        |
|                    | `start_print`     | Starts a print job with a specified file.                        | `file_name`                                 |
|                    | `start_print_bbl` | Special BBL endpoint; download the file and print i              | `url`                                       |
| `temperature_control`| `set_hotend`    | Sets the temperature of the hotend.                              | `temperature`, `tool`                       |
|                    | `set_bed`         | Sets the temperature of the bed.                                 | `temperature`                               |
| `movement_control` | `jog`             | Moves the printer's axes to specified positions.                 | `axes`, `relative`, `speed`, `tags`         |
|                    | `extrude`         | Extrudes a specified amount of filament.                         | `amount`, `speed`, `tags`                   |
|                    | `home`            | Homes the printer on specified axes.                             | `axes`  (none for BBL)                                   |
| `camera_control`   | `get_providers`   | Retrieves information about available webcam providers.          | None                                        |
|                    | `snapshot`        | Takes a snapshot from the specified webcam.                      | `destination`, `destination_url`, `camera_provider_id`, `camera_name` |
|                    | `stream_on`/`stream_off`| Starts or stops streaming from the webcam.                   | Timer Interval, Other Streaming Parameters  |


### Table of Outgoing Messages & Events

Outgoing and response messages are reported back to printago in the following format.  data is mutable based on the message
type.
| Message Type | Description                                                                                   | Key Components                                                                                           |
|--------------|-----------------------------------------------------------------------------------------------|---------------------------------------------------------------------------------------------------------|
| `pairing`    | Indicates messages related to the pairing process of the plugin with a client or system.      | - `type`: 'pairing'<br> - `timestamp`<br> - `printer_id`<br> - `client_type`: 'octoprint' or 'bambu'<br> - `data`: Outcome of pairing process                  |
| `status`     | Provides the current status of the printer.                                                   | - `type`: 'status'<br> - `timestamp`<br> - `printer_id`<br> - `client_type`: 'octoprint' or 'bambu'<br> - `data`: Printer's current state, temperatures, job progress, etc. |
| `event`      | Used to send various event notifications.                                                     | - `type`: 'event'<br> - `timestamp`<br> - `printer_id`<br> - `client_type`: 'octoprint' or 'bambu'<br> - `data`: Details about the specific event                 |
| `error`      | Communicates error messages or issues encountered.                                            | - `type`: 'error'<br> - `timestamp`<br> - `printer_id`<br> - `client_type`: 'octoprint' or 'bambu'<br> - `data`: Error details                                    |
| `success`    | Confirms the successful completion of a requested action or command.                          | - `type`: 'success'<br> - `timestamp`<br> - `printer_id`<br> - `client_type`: 'octoprint' or 'bambu'<br> - `data`: Confirmation details or additional information  |
| `response`   | Contains responses to specific requests or commands.                                          | - `type`: 'response'<br> - `timestamp`<br> - `printer_id`<br> - `client_type`: 'octoprint'  - `data`: Response data related to a specific request   |

## Acknowledgements & Licensing

Printago-Connector is licensed under the terms of the [APGLv3](https://gnu.org/licenses/agpl.html) (also included).

Printago-Connector uses the [Eclipse Paho Python Client](https://www.eclipse.org/paho/clients/python/) under the hood,
which is dual-licensed and used here under the terms of the [EDL v1.0 (BSD)](https://www.eclipse.org/org/documents/edl-v10.php).