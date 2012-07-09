import sys
import os
import signal
import struct
import gevent
assert gevent.version_info > (1, 0, 0, 0), "Need gevent 1.0.0+"

from gevent import sleep, spawn, spawn_later, Greenlet
from gevent import select, socket
from gevent.server import StreamServer
from gevent.socket import create_connection, gethostbyname

import logging

logging.basicConfig(level=logging.DEBUG, format="%(asctime)s %(msg)s")
logger = logging.getLogger(__file__)
log = logger.debug


class Socks5Server(StreamServer):

    HOSTCACHE = {}
    HOSTCACHETIME = 1800

    def handle(self, sock, address):
        rfile = sock.makefile('rb', -1)
        try:
            log('socks connection from ' + str(address))

            # 1. Version
            sock.recv(262)
            sock.send(b"\x05\x00")

            # 2. Request
            data = rfile.read(4)
            mode = ord(data[1])
            addrtype = ord(data[3])

            if addrtype == 1:       # IPv4
                addr = socket.inet_ntoa(rfile.read(4))
            elif addrtype == 3:     # Domain name
                domain = rfile.read(ord(sock.recv(1)[0]))
                addr = self.handle_dns(domain)

            port = struct.unpack('>H', rfile.read(2))

            if mode == 1:  # 1. Tcp connect
                try:
                    remote = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                    remote.connect((addr, port[0]))
                    log('TCP connected, %s:%s' % (addr, port[0]))
                    reply = b"\x05\x00\x00\x01" + socket.inet_aton(addr) + \
                                struct.pack(">H", port[0])
                    sock.send(reply)
                except socket.error:
                    log('Conn refused, %s:%s' % (addr, port[0]))
                    # Connection refused
                    reply = b'\x05\x05\x00\x01\x00\x00\x00\x00\x00\x00'
                    sock.send(reply)
                    raise
                else:
                    log('Begin data, %s:%s' % (addr, port[0]))
                    # 3. Transfering
                    l1 = spawn(self.handle_tcp, sock, remote)
                    l2 = spawn(self.handle_tcp, remote, sock)
                    gevent.joinall((l1, l2))
                    remote._sock.close()
                    remote.close()
            else:
                reply = b"\x05\x07\x00\x01"  # Command not supported
                sock.send(reply)

        except socket.error:
            pass
        finally:
            log("Close handle")
            rfile.close()
            sock._sock.close()
            sock.close()

    def handle_dns(self, domain):

        log("Cache len: %d" % len(self.HOSTCACHE))

        if domain not in self.HOSTCACHE:
            log('Resolving ' + domain)
            addr = gethostbyname(domain)
            self.HOSTCACHE[domain] = addr
            spawn_later(self.HOSTCACHETIME,
                    lambda a: self.HOSTCACHE.pop(a, None), domain)
        else:
            addr = self.HOSTCACHE[domain]
            log('Hit resolv %s -> %s in cache' % (domain, addr))

        return addr

    def handle_tcp(self, fr, to):
        try:
            while to.send(fr.recv(4096)) > 0:
                continue
        except socket.error:
            pass


def main():

    listen = ("0.0.0.0", 1080)

    server = Socks5Server(listen)

    def kill():
        log("kill triggered")
        server.close()
        spawn(lambda: (sleep(3) is os.closerange(3, 1024)))

    gevent.signal(signal.SIGTERM, kill)
    gevent.signal(signal.SIGQUIT, kill)
    gevent.signal(signal.SIGINT, kill)
    server.start()
    log("Listening at %s" % str(listen))
    gevent.run()

if __name__ == "__main__":
    main()
