import threading
import socket
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
import secrets
from Crypto.PublicKey import RSA
from Crypto.Cipher import PKCS1_v1_5


class ServerThread(threading.Thread):
    """Thread used to handle all communication with the server"""

    def __init__(self, exit_event, thread_output, port, server_key, user_key, user_connected):
        threading.Thread.__init__(self)
        self._port = port
        self._exit_event = exit_event
        self._thread_output = thread_output
        self._server_key = server_key
        self._user_key = user_key
        self._user_connected = user_connected

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

            data = conn.recv(1024)
            if not data:
                self._thread_output.put("Closing connection")
                conn.close()
                continue

            aesgcm = AESGCM(self._server_key[0])
            try:
                self._thread_output.put(
                    "Data Received. IV: "+data[:12].decode())
                message = aesgcm.decrypt(data[:12], data[12:], None).decode()
                self._thread_output.put("Decoded message : "+message)
            except:
                self._thread_output.put("Authentication failed")
                self._thread_output.put("Closing connection")
                conn.close()
                continue

            if(message[:3] == "KEY"):
                if(not self._user_connected.is_set()):
                    key = secrets.token_bytes(16)

                    self._user_key[0] = key
                    self._thread_output.put("Generated new key")

                    # nonce = bytes(message[:12], 'utf-8')
                    # ct = aesgcm.encrypt(nonce, key, None)
                    # conn.sendall(nonce+ct)
                    pubKey = RSA.importKey(message[3:])
                    encryptor = PKCS1_v1_5.new(pubKey)
                    encrypted = encryptor.encrypt(key)
                    conn.sendall(encrypted)
                else:
                    self._thread_output.put(
                        "Another user is connected - not generating key")
            else:
                self._thread_output.put("Unknown request from server")
            self._thread_output.put("Closing connection")
            conn.close()
        self._thread_output.put("Exiting...")
        s.close()