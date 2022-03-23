import json
import os
import threading
import socket
import time
from cryptography.hazmat.primitives.ciphers.aead import AESGCM


class UserThreadRX(threading.Thread):
    """Thread used to handle data from the user.
    Only created when a user is connected.
    """

    def __init__(self, conn, disconnect, thread_output, key, data_from_user):
        threading.Thread.__init__(self)
        self._conn = conn
        self._disconnect = disconnect
        self._aesgcm = AESGCM(key)
        self._data_from_user = data_from_user
        self._thread_output = thread_output

    def run(self):
        while True:
            data = self._conn.recv(1024)
            if not data:
                break
            try:
                message = self._aesgcm.decrypt(
                    data[:12], data[12:], None).decode()
                self._data_from_user.put([time.time(), message])
                self._thread_output.put("<< Valid message received")
            except:
                self._thread_output.put("<< Invalid message")
                break
        self._disconnect.set()


class UserThread(threading.Thread):
    """Thread used to connect to the user, send data and start the RX thread."""

    def __init__(self, exit_event, thread_output, port, user_key,
                 user_connected, gateway_data, gateway_data_lock,
                 data_to_user, data_from_user
                 ):
        threading.Thread.__init__(self)
        self._port = port
        self._exit_event = exit_event
        self._thread_output = thread_output
        self._user_key = user_key
        self._user_connected = user_connected
        self._gateway_data = gateway_data
        self._gateway_data_lock = gateway_data_lock
        self._data_to_user = data_to_user
        self._data_from_user = data_from_user

        self._disconnect = threading.Event()

    def run(self):
        self._thread_output.put("Starting...")
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.bind(('', self._port))
            s.listen(1)
            s.settimeout(1)
        except Exception as e:
            self._thread_output.put("Error binding socket.")
            self._thread_output.put(e.__class__.__name__)
            return

        while True:
            if(self._exit_event.is_set()):
                break
            try:
                conn, addr = s.accept()
            except:
                continue
            self._thread_output.put("Got a connection from %s" % str(addr))
            self._user_connected.set()

            if(self._user_key[0] == None):
                self._thread_output.put("No key was generated. Disconnecting")
                conn.close()
                self._user_connected.clear()
                continue
            
            aesgcm = AESGCM(self._user_key[0])

            nonce = os.urandom(12)
            self._gateway_data_lock.acquire()
            gateway_data_str = json.dumps(
                self._gateway_data, separators=(',', ':')).encode('utf-8')
            self._gateway_data_lock.release()
            ct = aesgcm.encrypt(nonce, gateway_data_str, None)
            conn.sendall(nonce+ct)
            self._thread_output.put("Sent gateway data (structure)")

            user_thread_rx = UserThreadRX(
                conn, self._disconnect, self._thread_output, self._user_key[0], self._data_from_user)
            user_thread_rx.start()
            while True:
                if(self._data_to_user.qsize() != 0):
                    data = self._data_to_user.get()
                    self._thread_output.put("Sending data to user " + data)
                    nonce = os.urandom(12)
                    # data = data + ";"
                    data = data.encode('utf-8')
                    ct = aesgcm.encrypt(nonce, data, None)
                    conn.sendall(nonce+ct)
                if(self._disconnect.is_set()):
                    break
                if(self._exit_event.is_set()):
                    break
                time.sleep(0.1)

            self._thread_output.put("Closing connection")
            conn.close()
            user_thread_rx.join()
            self._user_connected.clear()
            self._disconnect.clear()
