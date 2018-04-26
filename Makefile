CONTIKI?=../contiki/examples/ipv6/rpl-udp-multi/
SITE?=lille
CLIENTS?=$(SITE),m3,175-179
SERVERS?=$(SITE),m3,180
DURATION?=60
SITEASSOCIATION?=--site-association $(SITE),script=aggregator_script.py


build:
	make -C $(CONTIKI)

profile:
	iotlab-profile addm3 -n consumption -p dc -current -voltage -power -period 8244 -avg 4

experiment:
	iotlab-experiment submit -d $(DURATION) -l $(CLIENTS),$(CONTIKI)/udp-client.iotlab-m3,consumption \
	-l $(SERVERS),$(CONTIKI)/udp-server.iotlab-m3 $(SITEASSOCIATION)
	iotlab-experiment wait

reflash:
	iotlab-node -up $(CONTIKI)/udp-client.iotlab-m3 -l $(CLIENTS)
	iotlab-node -up $(CONTIKI)/udp-server.iotlab-m3 -l $(SERVERS)