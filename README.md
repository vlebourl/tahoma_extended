# tahoma_extended

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://github.com/custom-components/hacs)

Extend the home assistant tahoma integration with new features not yet published to HA.

Add the following to your `configuration.yaml`:

```
tahoma_extended:
  username: 'tahoma login'
  password: 'tahoma password'
```


Currently this extension adds support for the following elements:
- Somfy's smartlock through the Tahoma box (`opendoors:OpenDoorsSmartLockComponent`)
- Atlantic IO pilot wire interface (Somfy ref: 1822452, `io:AtlanticElectricalHeaterIOComponent`)
- Somfy's smart thermostat and related sensors (`somfythermostat:SomfyThermostatThermostatComponent`, `somfythermostat:SomfyThermostatTemperatureSensor`, `somfythermostat:SomfyThermostatHumiditySensor`). 
- Somfy's RTS light switch (`rts:LightRTSComponent`).

Climate integration is a bit of hack. To use it, you need a controller such as the Atlantic IO controller or the Smart 
Thermostat, and a temperature sensor. The temperature sensor can be any sensor added to HA.
Add the following to your `configuration.yaml`:

```
climate:
  platform: tahoma_extended
  sensors:
  - name: Name of the climate device in the Tahoma Box
    entity_id: sensor.associated_temperature_sensor
```

The name of the device _MUST_ be the same as in the Tahoma Box. 
For instance, if your Atlantic IO Controller is called "Radiateur Parents" in the Tahoma Box,
 
 ![Radiateur_Parents](https://github.com/vlebourl/tahoma_extended/blob/master/img/Radiateur_Parents.png)
 
and your temperature sensor is `sensor.netatmo_parents_temperature`, then the corresponding 
configuration section is:

```
climate:
  platform: tahoma_extended
  sensors:
  - name: "Radiateur Parents"
    entity_id: sensor.netatmo_parents_temperature
```

### Contributing

To contribute, run the following python script and PM me on the [Home Assistant Community forum](https://community.home-assistant.io/u/vlebourl) with the output written in `devices.txt` and details on the device you want to be added.

```
import sys
try:
    import pyhoma
except ModuleNotFoundError:
    import subprocess
    subprocess.check_call([sys.executable, "-m", "pip", "install", "pyhoma"])
    import pyhoma

print("Input login: ")
userName=input()
print("Input password: ")
userPassword=input()

orig_stdout = sys.stdout
f = open('devices.txt', 'w')
sys.stdout = f

import pyhoma
api=pyhoma.PyHoma(userName=userName, userPassword=userPassword)

api.login()
api.get_setup()

devices = api.get_devices()

from pprint import pprint
for k,v in devices.items():
    print("****************************************")
    print("Label: " + v.label)
    print("controlableName: " + v.type)
    print("uiClass: " + v.uiclass)
    print("widget: " + v.widget)
    print("=== States ===")
    states = v._Device__states_def
    for s in states:
        pprint(s, indent=4, width=20)
    print(" ")
    print("=== Commands ===")
    commands = v._Device__command_def
    for c in commands:
        pprint(c, indent=4, width=20)
    print(" ")

sys.stdout = orig_stdout
f.close()
```
