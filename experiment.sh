#!/bin/bash

make -C contiki/examples/ipv6/rpl-udp-multi

CLIENTS=180-182
SERVERS=179
DURATION=60

CONTIKI=contiki/examples/ipv6/rpl-udp-multi/

iotlab-profile addm3 -n consumption -p dc -current -voltage -power -period 8244 -avg 4

iotlab-experiment submit -d $DURATION -l lille,m3,$CLIENTS,$CONTIKI/udp-client.iotlab-m3,consumption \
-l lille,m3,$SERVERS,$CONTIKI/udp-server.iotlab-m3 \
--site-association lille,script=aggregator_script.py