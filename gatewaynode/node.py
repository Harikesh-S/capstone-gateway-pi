import curses
from curses import wrapper
from curses.textpad import Textbox
import threading
import queue
import json
import time

from ble import BleThread
from servertcp import ServerThread
from usertcp import UserThread


class Node:
    _PERIPHERALS = [
        {"addr": "78:21:84:87:c5:e6", "id": "1",
            "type": "s1", "key": b"abcdefghijklmnop"},
        {"addr": "78:21:84:89:44:e6", "id": "2",
            "type": "a1", "key": b"ponmlkjihgfedcba"},
    ]
    _exit_event = threading.Event()

    _gateway_data = {"type": "gateway", "options": {
        "Automatic Light Control": True}, "nodes": {}}
    _gateway_data_lock = threading.Lock()

    _user_connected = threading.Event()

    _data_to_peripherals = queue.Queue()
    _data_from_peripherals = queue.Queue()
    _data_to_user = queue.Queue()
    _data_from_user = queue.Queue()

    _ble_thread_output = queue.Queue()
    _server_thread_output = queue.Queue()
    _user_thread_output = queue.Queue()

    _server_key = [b"1234567890123456"]
    _user_key = [None]

    def _main(self, stdscr):
        """Creates threads, handles communication between them,
        listens for user input and displays output from each thread
        """
        # Curses windows setup
        stdscr.clear()
        stdscr.refresh()

        window_cols = max(curses.COLS//2, 5)
        window_lines = max(curses.LINES//2, 5)

        main_window, main_window_text = self._generate_windows(
            window_lines, window_cols, 0, 0, " Main Thread Output ")
        main_window.nodelay(True)  # non blocking input
        main_window_input_box = curses.newwin(
            1, window_cols-2, window_lines-2, 1)
        ble_window, ble_window_text = self._generate_windows(
            window_lines, window_cols, 0, window_cols+1, " BLE Thread Output ")
        server_window, server_window_text = self._generate_windows(
            window_lines, window_cols, window_lines, 0, " Server TCP Output ")
        user_window, user_window_text = self._generate_windows(
            window_lines, window_cols, window_lines, window_cols+1, " User TCP Output ")

        # Starting worker threads
        ble_thread = BleThread(self._exit_event, self._ble_thread_output,
                               self._PERIPHERALS, self._data_to_peripherals, self._data_from_peripherals)
        ble_thread.update_nodes_dict(self._gateway_data)
        ble_thread.start()
        server_thread = ServerThread(
            self._exit_event, self._server_thread_output, 50000, self._server_key, self._user_key, self._user_connected)
        server_thread.start()
        userThread = UserThread(self._exit_event, self._user_thread_output, 50001, self._user_key,
                                self._user_connected, self._gateway_data, self._gateway_data_lock, self._data_to_user, self._data_from_user)
        userThread.start()

        # Main loop
        while True:
            # Checking for keyboard inputs
            try:
                key = main_window.getkey()
                if(key == "q"):
                    main_window_text.addstr("Exiting...\n", curses.A_BOLD)
                    main_window_text.refresh()
                    break
                if(key == "i"):
                    box = Textbox(main_window_input_box)
                    box.edit()
                    data = box.gather().strip().replace("\n", "").split(";")
                    data[1] = int(data[1])
                    self._data_to_peripherals.put(data)
                    main_window_input_box.clear()
                    main_window_input_box.refresh()
                    main_window_text.addstr(
                        "Data to be sent : {}\n".format(str(data)))
                    main_window_text.refresh()
                if(key == 'k'):
                    key_string = "User AES Key :"
                    if self._user_key[0] != None:
                        for byte in self._user_key[0]:
                            key_string += " %02x" % byte
                        key_string += "\nUser AES Key :"
                        for byte in self._user_key[0]:
                            key_string += " %03d" % byte
                    main_window_text.addstr(key_string+"\n")
                    main_window_text.refresh()
                if(key == 's'):
                    self._gateway_data_lock.acquire()
                    gateway_data_str = json.dumps(self._gateway_data)
                    self._gateway_data_lock.release()
                    main_window_text.addstr(gateway_data_str+"\n")
                    main_window_text.refresh()

            except:
                # Check for data from BLE thread
                if(self._data_from_peripherals.qsize() != 0):
                    new_data = self._data_from_peripherals.get()

                    # Updating data stored
                    try:
                        self._gateway_data_lock.acquire()
                        new_data_values = new_data["data"].split(';')
                        if(new_data["field"] == "output-values"):
                            for i in range(len(self._gateway_data["nodes"][new_data["id"]
                                                                           ]["output-values"])):
                                self._gateway_data["nodes"][new_data["id"]
                                                            ]["output-values"][i] = new_data_values[i]

                            # Automatic Light Control from input
                            # TODO improve this later
                            if(self._gateway_data["options"]["Automatic Light Control"]):
                                if(new_data["id"] == "1"):
                                    main_window_text.addstr(
                                        "Automatic light control, data from node 1\n")
                                    light_level = int(new_data_values[3])
                                    led_value = 254-int(light_level * 0.0622)
                                    main_window_text.addstr(
                                        "Light level : %d, Led value : %d\n" % (light_level, led_value))
                                    self._data_to_peripherals.put(
                                        ["2", 0, str(led_value)])

                        if(new_data["field"] == "input-values"):
                            self._gateway_data["nodes"][new_data["id"]
                                                        ]["input-values"][new_data["index"]] = new_data["data"]
                    except Exception as e:
                        main_window_text.addstr(
                            "Error updating new data : %s\n" % (type(e).__name__))
                    finally:
                        self._gateway_data_lock.release()
                    # Update user with new data if connected
                    if(self._user_connected.is_set()):
                        self._data_to_user.put(json.dumps(
                            [new_data["id"], new_data["field"],
                             self._gateway_data["nodes"][new_data["id"]
                                                         ][new_data["field"]]
                             ], separators=(',', ':')))

                    main_window_text.addstr("{} : {} : {} : {}\n".format(new_data["id"],
                                            str(int(new_data["time"])),
                                            new_data["field"], new_data["data"]))
                    main_window_text.refresh()

                # Check for data from User thread
                if(self._data_from_user.qsize() != 0):
                    new_data = self._data_from_user.get()
                    main_window_text.addstr(
                        str(int(new_data[0]))+" : "+str(new_data[1])+"\n")
                    message = json.loads(str(new_data[1]))
                    try:
                        if(message[0] == "set-value"):
                            main_window_text.addstr(
                                "Data to be sent : "+json.dumps(message[1:])+"\n")
                            self._data_to_peripherals.put(message[1:])
                        if(message[0] == "set-option"):
                            try:
                                self._gateway_data_lock.acquire()
                                self._gateway_data["options"][message[1]
                                                              ] = message[2]
                                main_window_text.addstr(
                                    "Option set : "+message[1]+" = "+str(message[2])+". Updating user...\n")
                                self._data_to_user.put(
                                    "[\"options\","+json.dumps(self._gateway_data["options"])+"]")
                            except Exception as e:
                                main_window_text.addstr(e.__class__.__name__)
                            finally:
                                self._gateway_data_lock.release()
                    except Exception as e:
                        main_window_text.addstr(
                            "Error: "+e.__class__.__name__+"\n")
                    main_window_text.refresh()

                # Check for output for the three windows
                while(self._ble_thread_output.qsize() != 0):
                    text = self._ble_thread_output.get()
                    ble_window_text.addstr(text+"\n")
                    ble_window_text.refresh()
                    ble_window.refresh()

                while(self._server_thread_output.qsize() != 0):
                    text = self._server_thread_output.get()
                    server_window_text.addstr(text+"\n")
                    server_window_text.refresh()
                    server_window.refresh()

                while(self._user_thread_output.qsize() != 0):
                    text = self._user_thread_output.get()
                    user_window_text.addstr(text+"\n")
                    user_window_text.refresh()
                    user_window.refresh()

                time.sleep(0.1)

        self._exit_event.set()
        ble_thread.join()
        server_thread.join()
        userThread.join()

    def _generate_windows(self, lines, cols, y, x, title):
        "Function to generate curses windows for output from different threads"
        window = curses.newwin(lines, cols, y, x)
        window.border()
        window.addstr(0, 2, title)
        window.refresh()
        windowText = curses.newwin(lines-2, cols-2, y+1, x+1)
        windowText.scrollok(True)
        return window, windowText

    def run(self):
        wrapper(self._main)


if __name__ == "__main__":
    node = Node()
    node.run()
