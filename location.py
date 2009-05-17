#!/usr/bin/env python
# encoding: utf-8
"""
location.py

Created by Adam on 2009-05-16.
Copyright (c) 2009 . All rights reserved.
"""

import sys
sys.path.append('gen-py')
import socket 
from collections import defaultdict
from math import sqrt

from thrift import Thrift
from thrift.transport import TSocket
from thrift.transport import TTransport
from thrift.protocol import TBinaryProtocol
from thrift.server import TServer

from locator.ttypes import *
from locator import Locator
from hash_ring import HashRing

class NodeNotFound(Thrift.TException):
    def __init__(self, location, message=None):
        self.location = location
        self.message = message

def loc2str(location):
    "Give the canonical string representation"
    return "%s:%d" % (location.address, location.port)

def str2loc(location):
    comp = location.rsplit(':', 1)
    return Location(comp[0], int(comp[1]))

def remote_call(destination, method, *args):
    transport = TSocket.TSocket(destination.address, destination.port)
    transport = TTransport.TBufferedTransport(transport)
    protocol = TBinaryProtocol.TBinaryProtocol(transport)
    client = Locator.Client(protocol)
    try:
        transport.open()
    except Thrift.TException, tx:
        raise NodeNotFound(destination)
    out = getattr(client, method)(*args)
    transport.close()
    return out

def select_peers(in_set):
    lst = sorted(in_set)
    ii = int(sqrt(len(lst)))+1
    return [b for a, b in enumerate(lst) if (a % ii == 0)]

class LocatorHandler(Locator.Iface):
    def __init__(self, peer=None, port=9900):
        self.address = socket.gethostbyname(socket.gethostname())
        self.port = port
        self.peer = peer
        self.ring = HashRing()
        self.addnews = defaultdict(set)
        self.removenews = defaultdict(set)
        try:
            remote_call(self.location, 'ping')
            print 'Uh-oh. Our location responded to a ping!'
            raise socket.error(43, 'Address already in use')
        except NodeNotFound:
            pass
        
    
    @property
    def here(self):
        "Give the canonical string representation"
        return loc2str(self)
    
    @property
    def location(self):
        "Give the canonical Location"
        return Location(address=self.address, port=self.port)
    
    def join(self, location):
        """
        Parameters:
         - location
        """
        self.add(location, [self.location])
        return self.get_all()

    def remove(self, location, authorities):
        """
        Parameters:
         - location
         - authorities
        """
        key = loc2str(location)
        self.ring.remove(loc2str(location))
        self.removenews[key].add(self.here)
        self.removenews[key].update(map(loc2str, authorities))
        self.addnews[key] = set()
        destinations = select_peers(self.ring.nodes.difference(self.removenews[key]))
        self.removenews[key].update(destinations)        
        for destination in destinations:
            try:
                remote_call(str2loc(destination), 'remove', location, map(str2loc, self.removenews[key]))
            except NodeNotFound, tx:
                # enter all nodes as authorities to avoid race conditions
                # lazy invalidation
                self.remove(tx.location, map(str2loc, self.ring.nodes))
        print "removed %s:%d" % (location.address, location.port)

    def add(self, location, authorities):
        """
        Parameters:
         - location
         - authorities
        """
        key = loc2str(location)
        self.addnews[key].add(self.here)
        self.addnews[key].update(map(loc2str, authorities))
        self.removenews[key] = set()
        destinations = select_peers(self.ring.nodes.difference(self.addnews[key]))
        self.addnews[key].update(destinations)        
        for destination in destinations:
            try:
                remote_call(str2loc(destination), 'add', location, map(str2loc, self.addnews[key]))
            except NodeNotFound, tx:
                # enter all nodes as authorities to avoid race conditions
                # lazy invalidation
                self.remove(tx.location, map(str2loc, self.ring.nodes))
        self.ring.append(loc2str(location))
        print "added %s:%d" % (location.address, location.port)
        
    def get_all(self):
        return map(str2loc, self.ring.nodes)

    def get_node(self, key):
        return self.ring.get_node(key)
    
    def ping(self):
        print 'ping()'
        
    def debug(self):
        a = "self.location: %r\n" % self.location
        a += "self.ring.nodes:\n%r\n" % self.ring.nodes
        a += "self.addnews:\n%r\n" % self.addnews
        a += "self.removenews:\n%r\n" % self.removenews
        print a
    

if __name__ == '__main__':
    inputargs = {}
    try:
        inputargs['port'] = int(sys.argv[-1])
        inputargs['peer'] = str2loc(sys.argv[-2])
    except:
        pass
    handler = LocatorHandler(**inputargs)
    processor = Locator.Processor(handler)
    transport = TSocket.TServerSocket(handler.port)
    tfactory = TTransport.TBufferedTransportFactory()
    pfactory = TBinaryProtocol.TBinaryProtocolFactory()
    server = TServer.TSimpleServer(processor, transport, tfactory, pfactory)
    
    if handler.peer:
        nodes = remote_call(handler.peer, 'join', handler.location)
        if nodes:
            handler.ring.extend(map(loc2str, nodes))
        print 'Joining the network...'
    else:
        handler.ring.append(handler.here)
        print 'Initiating the network...'
    
    print 'Starting the server at %s...' % (handler.here)
    try:
        server.serve()
    
    finally:
        handler.ring.remove(handler.here)
        for node in select_peers(handler.ring.nodes):
            remote_call(str2loc(node), 'remove', handler.location, [handler.location])
    print 'done.'
