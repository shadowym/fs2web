#!/usr/bin/env python
# coding: utf-8

from debug import debug

from eventsocket import EventProtocol, superdict
from twisted.internet import reactor, protocol
from twisted.web import xmlrpc, server
from Queue import Queue
import pickle
import pprint

# Connect Django ORM
from django.core.management import setup_environ
import settings
setup_environ(settings)
from conference.models import *

port = 1905
unique_id = {}

conferences = {}
channels = {}

class InboundProxy(EventProtocol):
    def __init__(self):
	self.job_uuid = {}
	self.conf_msgs = Queue()
        self.api_type = Queue()
	EventProtocol.__init__(self)

    def queue_api(self,command,type):
        print "Queue ",type
        self.api_type.put(type)
        self.api(command)

    def authSuccess(self, ev):
        self.queue_api("show channels",{"name":"show","subtype":"channels"})
        self.eventplain('CHANNEL_CREATE CHANNEL_DESTROY CUSTOM conference::maintenance conference::dtmf')

    def authFailure(self, failure):
	self.factory.reconnect = False

    def eventplainFailure(self, failure):
	self.factory.reconnect = False
	self.exit()

    def onChannelCreate(self,data):
        pprint.pprint(data)
        channels[data.Unique_ID] = data
        print channels
        self.queue_api("uuid_dump %s"%data.Unique_ID,{"name":"uuid_dump"})

    def onChannelDestroy(self,data):
        pprint.pprint(data)
        del channels[data.Unique_ID]
        print channels

    def apiFailure(self, ev):
        print "Error!", ev
    def apiSuccess(self, ev):
        # Update channel data with uuid_dump result
        type = self.api_type.get()
        raw = ev['data']['rawresponse']
        if '-ERR' == raw[:4]:
            print 'ERROR!'
            return

        print "Type:",type,raw
        if type["name"] == "uuid_dump":
            temp = [line.strip().split(': ',1) for line in raw.strip().split('\n') if line]
            apidata = superdict([(line[0].replace('-','_'),line[1]) for line in temp])
            if apidata.Unique_ID in channels:
                channels[apidata.Unique_ID].update(apidata)
            else:
                channels[apidata.Unique_ID] = apidata
            channel = channels[apidata.Unique_ID]
            kuku = channel.get('variable_kuku',None)
            print "Channel ",channel.Unique_ID,kuku

        elif type["name"] == "show":
            lines = raw.split("\n\n")[0].strip().splitlines()
            headers = [header.strip() for header in lines[0].split(',')]
            response = [superdict(zip(headers,[e.strip() for e in line.split(',')])) for line in lines[1:]]
            self.process_api_response(type,response)

    def process_api_response(self,type,response):
        print response
        if type["subtype"] == "channels":
            for r in response:
                self.queue_api("uuid_dump %s"%r.uuid,{"name":"uuid_dump"})

    def onCustom(self, data):
        #pprint.pprint(data)
        channels[data.Unique_ID].update(data)
        channel = channels[data.Unique_ID]

        if data.Event_Subclass == 'conference::dtmf':
            print data.conference
        elif data.Event_Subclass == 'conference::maintenance':
            print data.Action
            #self.conf_msgs.put({'data':data,'context':'conference'})
            #self.api("uuid_dump %s"%data.Unique_ID)
            if data.Action == 'add-member':
                if not data.Conference_Name in conferences:
                    conferences[data.Conference_Name] = {}
                conferences[data.Conference_Name][channel.Unique_ID]=channel
                pprint.pprint(conferences[data.Conference_Name])
            elif data.Action == 'del-member':
                if data.Conference_Name in conferences and channel.Unique_ID in conferences[data.Conference_Name]:
                    del conferences[data.Conference_Name][channel.Unique_ID]
                    if not conferences[data.Conference_Name]:
                        del conferences[data.Conference_Name]
                print channels
            elif data.Action == 'start-talking':
                print "start talk"
            elif data.Action == 'stop-talking':
                print "stop talk"
            elif data.Action == 'mute-member':
                print "mute"
            elif data.Action == 'unmute-member':
                print "unmute"

class InboundFactory(protocol.ClientFactory):
    protocol = InboundProxy

    def __init__(self, password):
	self.password = password
	self.reconnect = True

    def clientConnectionLost(self, connector, reason):
	if self.reconnect: connector.connect()
	else:
	    print '[inboundfactory] stopping reactor'
	    reactor.stop()

    def clientConnectionFailed(self, connector, reason):
	print '[inboundfactoy] cannot connect: %s' % reason
	reactor.stop()

class XMLRPCInterface(xmlrpc.XMLRPC):
    def xmlrpc_info(self):
        print conferences
        return pickle.dumps(conferences)

if __name__ == '__main__':
    reactor.connectTCP('localhost', 8021, InboundFactory('ClueCon'))
    xmlrpc_interface = XMLRPCInterface()
    reactor.listenTCP(7080,server.Site(xmlrpc_interface))
    reactor.run()
