import threading
import time
import os
from bluepy import btle
from cryptography.hazmat.primitives.ciphers.aead import AESGCM


class BleThread(threading.Thread):
    """Thread used to handle all communication with BLE local nodes"""

    def __init__(self, exit_event, thread_output, PERIPHERALS, data_to_peripherals, data_from_peripherals):
        threading.Thread.__init__(self)
        self._exit_event = exit_event
        self._thread_output = thread_output
        self._PERIPHERALS = PERIPHERALS
        self._data_to_peripherals = data_to_peripherals
        self._data_from_peripherals = data_from_peripherals

        self._scanner = btle.Scanner().withDelegate(btle.DefaultDelegate())
        self._data_to_be_sent = []

    def run(self):
        self._thread_output.put("Starting...")
        while(True):
            if(self._exit_event.is_set()):
                break
            # Check if there is any new data to be sent to local nodes
            # and store it in an instance attribute
            while self._data_to_peripherals.qsize() != 0:
                data = self._data_to_peripherals.get()
                self._thread_output.put(
                    "Data to be sent : {}".format(str(data)))
                self._data_to_be_sent.append(data)

            # Scan for nearbly BLE Servers and get their addresses
            self._thread_output.put("Scanning...")
            try:
                devices = self._scanner.scan(1)
            except btle.BTLEManagementError:
                self._thread_output.put(
                    "Insufficient permissions to scan for BLE devices.")
                return
            devices_addr = [d.addr for d in devices]

            # Check if known peripherals are present in the address list
            for p in self._PERIPHERALS:
                if p["addr"] in devices_addr:
                    # Perform different actions based on the type of local node
                    if p["type"] == "s1":
                        # Sensor node 1 - gives sensor readings and enters deep sleep after connection ends
                        # The deep sleep time can be set using a characteristic

                        self._thread_output.put(
                            "Connecting to sensor {}".format(p["id"]))
                        try:
                            peripheral = btle.Peripheral(p["addr"])
                            peripheral.setMTU(100)
                            svc = peripheral.getServiceByUUID(
                                "86df3990-4bdf-442e-8eb7-04bbd173e4a7")
                            temp_char = svc.getCharacteristics(
                                "1c70ab2e-c645-4853-b46a-fd4cd0b7f538")[0]
                            light_char = svc.getCharacteristics(
                                "2a47596d-8402-4359-952a-a956c84b0f41")[0]
                            sleep_char = svc.getCharacteristics(
                                "cac889a0-4436-489b-ba6c-0e4f9b2d47ca")[0]
                            aesgcm = AESGCM(p["key"])

                            # Try to read data from the node (max 5 tries)
                            for _ in range(5):
                                data = ""
                                temp_valid, light_valid = False, False
                                try:
                                    self._thread_output.put("Reading data...")

                                    temperature = temp_char.read()
                                    try:
                                        message = aesgcm.decrypt(
                                            temperature[:12], temperature[12:], None).split(b'\x00')[0].decode()
                                        self._thread_output.put(
                                            "Valid temperature data received")
                                        data = data + message
                                        temp_valid = True
                                    except:
                                        self._thread_output.put(
                                            "Invalid temperature data received")

                                    light = light_char.read()
                                    try:
                                        message = aesgcm.decrypt(light[:12], light[12:], None).split(b'\x00')[
                                            0].decode()
                                        self._thread_output.put(
                                            "Valid light data received")
                                        data = data + message
                                        light_valid = True
                                    except:
                                        self._thread_output.put(
                                            "Invalid light data received")
                                    if(light_valid and temp_valid):
                                        self._data_from_peripherals.put(
                                            {"id": p["id"], "field": "output-values", "time": time.time(), "data": data})
                                    break
                                except:
                                    self._thread_output.put(
                                        "Failed to read data")

                            # If there is any data to be sent to this node, encrypt it and send it
                            for d in self._data_to_be_sent:
                                if(d[0] == p["id"]):
                                    if(d[1] == 0):
                                        try:
                                            self._thread_output.put(
                                                "Setting deep sleep time of node {} to {}".format(d[0], d[2]))
                                            nonce = os.urandom(12)
                                            data = d[2] + ";"
                                            data = data.ljust(
                                                16, ';').encode('utf-8')
                                            ct = aesgcm.encrypt(
                                                nonce, data, None)
                                            sleep_char.write(nonce+ct)
                                            self._data_to_be_sent.remove(d)

                                        except:
                                            self._thread_output.put(
                                                "Error sending data")

                                        # Reading the value again to get the actual value stored in the node
                                        time.sleep(0.1)
                                        try:
                                            sleepCharRead = sleep_char.read()
                                            message = aesgcm.decrypt(sleepCharRead[:12], sleepCharRead[12:], None).split(b'\x00')[
                                                0].decode()
                                            self._thread_output.put("Valid sleep time data read")
                                            sleepVal = message.split(';')[0]
                                            self._data_from_peripherals.put(
                                                {"id": p["id"], "field": "input-values", "time": time.time(), 
                                                "index": 0, "data": sleepVal})
                                        except:
                                            self._thread_output.put("Invalid sleep time data read")
                                    else:
                                        self._thread_output.put(
                                            "Invalid index - not sending data")
                            self._thread_output.put(
                                "Disconnecting from sensor {}".format(p["id"]))
                            peripheral.disconnect()

                        except:
                            self._thread_output.put("Failed to connect")
                    
                    if p["type"] == "a1":
                        # Actuator node 1 - has one input char, stays awake
                        connect = False
                        for d in self._data_to_be_sent:
                            if(d[0] == p["id"]):
                                connect = True
                                break
                        if connect:
                            self._thread_output.put(
                                "Connecting to sensor {}".format(p["id"]))
                            try:
                                peripheral = btle.Peripheral(p["addr"])
                                peripheral.setMTU(100)
                                svc = peripheral.getServiceByUUID(
                                    "86df3990-4bdf-442e-8eb7-04bbd173e4a7")
                                led_char = svc.getCharacteristics(
                                    "8a7a1f1d-3cc0-4fe7-ab8a-d75fbcfb1a7b")[0]
                                aesgcm = AESGCM(p["key"])

                                # Send all data that is queued up for this node
                                for d in self._data_to_be_sent:
                                    if(d[0] == p["id"]):
                                        if(d[1] == 0):
                                            try:
                                                self._thread_output.put(
                                                    "Setting led value time of node {} to {}".format(d[0], d[2]))
                                                nonce = os.urandom(12)
                                                data = d[2] + ";"
                                                data = data.ljust(
                                                    16, ';').encode('utf-8')
                                                ct = aesgcm.encrypt(
                                                    nonce, data, None)
                                                led_char.write(nonce+ct)
                                                self._data_to_be_sent.remove(d)
                                                
                                            except:
                                                self._thread_output.put(
                                                    "Error sending data")

                                            # Reading the value again to get the actual value stored in the node
                                            time.sleep(0.1)
                                            try:
                                                ledCharRead = led_char.read()
                                                message = aesgcm.decrypt(ledCharRead[:12], ledCharRead[12:], None).split(b'\x00')[
                                                    0].decode()
                                                self._thread_output.put(
                                                    "Valid led value data read")
                                                ledVal = message.split(';')[0]
                                                self._data_from_peripherals.put(
                                                    {"id": p["id"], "field": "input-values", "time": time.time(), 
                                                    "index": 0, "data": ledVal})
                                            except:
                                                self._thread_output.put("Invalid led data read")
                                        else:
                                            self._thread_output.put(
                                                "Invalid index - not sending data")
                                self._thread_output.put(
                                    "Disconnecting from sensor {}".format(p["id"]))
                                peripheral.disconnect()

                            except:
                                self._thread_output.put("Failed to connect")
                    

        self._thread_output.put("Exiting")

    def update_nodes_dict(self, gateway_data):
        """Updates the gateway data with fields for the connected nodes.
        Assumes no other thread is using the data. Returns a string.
        """
        _ret = "Generating dictionary from PERIPHERALS...\n"
        for p in self._PERIPHERALS:
            if p["type"] == "s1":
                _ret += "Adding sensor node with Temp, Light sensor and deep sleep timer\n"
                gateway_data["nodes"][p["id"]] = {"output-tags": ["Temperature (°C)", "Relative Humidity (%)", "Heat Index (°C)", "Light (0-4095)"],
                                                  "output-values": ["Loading", "Loading", "Loading", "Loading"],
                                                  "input-tags": ["Sleep time (seconds)"], "input-values": ["10"]}
            elif p["type"] == "a1":
                _ret += "Adding actuator node with one LED sensor\n"
                gateway_data["nodes"][p["id"]] = {"output-tags": [],
                                                  "output-values": [],
                                                  "input-tags": ["LED value"], "input-values": ["0"]}
            else:
                _ret += "Invlaid peripheral type\n"
        return _ret
