CONTIKI?=../contiki/examples/ipv6/rpl-udp-multi/
SITE?=lille
CLIENTS?=$(SITE),m3,175-179
SERVERS?=$(SITE),m3,180
DURATION?=60
SITEASSOCIATION?=--site-association $(SITE),script=aggregator_script.py,scriptconfig=conf
BATTERIES?=$(SITE),m3,175-178:10000;$(SITE),m3,179:5000

build:
	make -C $(CONTIKI)

profile:
	iotlab-profile addm3 -n consumption -p dc -current -voltage -power -period 8244 -avg 4

conf: build
	echo "--batteries $(BATTERIES)" > conf

experiment: conf
	iotlab-experiment submit -d $(DURATION) -l $(CLIENTS),$(CONTIKI)/udp-client.iotlab-m3,consumption \
	-l $(SERVERS),$(CONTIKI)/udp-server.iotlab-m3 $(SITEASSOCIATION)
	iotlab-experiment wait

reflash: build
	iotlab-node -up $(CONTIKI)/udp-client.iotlab-m3 -l $(CLIENTS)
	iotlab-node -up $(CONTIKI)/udp-server.iotlab-m3 -l $(SERVERS)

dev-experiment: conf
	SITEASSOCIATION="" $(MAKE) experiment
