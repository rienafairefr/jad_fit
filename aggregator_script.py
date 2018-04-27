#!/usr/bin/env python
from __future__ import print_function
import argparse
import logging
import os
import sys
import threading
import time

from iotlabaggregator import common, connections
from iotlabaggregator.serial import SerialAggregator as AggregatorSerialAggregator
from iotlabaggregator.serial import SerialConnection as AggregatorSerialConnection
from iotlabcli import auth, rest, experiment
from iotlabcli.experiment import wait_experiment
from iotlabcli.node import node_command
from iotlabcli.parser import common as common_parser
from iotlabcli.helpers import get_current_experiment

print('current working directory: ' + os.getcwd())

user, passwd = auth.get_user_credentials()
api = rest.Api(user, passwd)
experiment_id = get_current_experiment(api, running_only=False)

home = os.path.expanduser('~')

LOG_FMT = logging.Formatter("%(created)f;%(message)s")
logger = logging.getLogger('aggregator_script')
logger.setLevel(logging.INFO)
line_logger = logging.StreamHandler(sys.stdout)
line_logger.setFormatter(LOG_FMT)
file_logger = logging.FileHandler(os.path.join(home, '%i.aggregator.log' % experiment_id))
file_logger.setFormatter(LOG_FMT)
logger.addHandler(line_logger)
logger.addHandler(file_logger)

print('Wait experiment %i'%experiment_id)
wait_experiment(api, experiment_id)

_print = print

def print(msg):
    logger.info(msg)


class ConsumptionAggregator(object):
    CONSUMPTION_DIR = os.path.join(home, ".iot-lab/{experiment_id}/consumption/{node}.oml")

    def __init__(self, nodes_list, *args, **kwargs):
        self.nodes_list = nodes_list
        self.open_files = {}
        self.accumulated_watt_s = {}
        self.times = {}
        for node in nodes_list:
            consumption_node_file = self.CONSUMPTION_DIR.format(node=node, experiment_id=experiment_id)
            if os.path.exists(consumption_node_file):
                self.open_files[node] = open(consumption_node_file, 'r')
                self.accumulated_watt_s[node] = 0
        self.thread = threading.Thread(target=self._loop)

    def start(self):
        """ Read node consumption OML files """
        self.thread.start()

    def _loop(self):
        """ Read node consumption OML files """
        try:
            while True:
                self.read_consumption_file()
        except (KeyboardInterrupt, EOFError):
            exit(0)

    def read_consumption_file(self):
        # schema: 0 _experiment_metadata subject:string key:string value:string
        # schema: 1 control_node_measures_consumption timestamp_s:uint32 timestamp_us:uint32 power:double voltage:double current:double

        for node, file in self.open_files.items():
            lines = file.readlines()
            if lines:
                print('Reading consumption data for %s...' % node)
            else:
                print('no new consumption data for %s...' % node)
            for line in lines:
                splitted = line.split('\t')
                if len(splitted) == 8:
                    current_time = float(splitted[3]) + float(splitted[4]) / 1000
                    dt = current_time - self.times.get(node, current_time)
                    power = float(splitted[5])
                    self.accumulated_watt_s[node] = self.accumulated_watt_s[node] + dt * power
                    self.times[node] = current_time

            if lines:
                if self.times.get(node) and self.accumulated_watt_s.get(node):
                    print('%u : %s : %g' % (self.times[node], node, self.accumulated_watt_s[node]))

        time.sleep(5)
        pass


class SerialConnection(AggregatorSerialConnection):
    def __init__(self, hostname, aggregator):
        self.consumption_msg_ack = True
        super(SerialConnection, self).__init__(hostname, aggregator, line_handler=self.line_handler, print_lines=True)

    def line_handler(self, identifier, line):
        # handle incoming messages
        if 'cons ACK' in line:
            # acknowledge the received consumption
            self.consumption_msg_ack = True
            print('>> ACK cons %s' % identifier)
        elif 'stop self' in line:
            # stop the node
            node_command(api, 'stop', experiment_id, nodes_list=[identifier])
            print('>> STOPPED node %s' %identifier)
        print('%s;%s' % (identifier, line))



class SerialAggregator(connections.Aggregator):
    """ Customised Aggregator """

    parser = argparse.ArgumentParser()
    common.add_nodes_selection_parser(parser)
    connection_class = SerialConnection

    def __init__(self, nodes_list, *args, **kwargs):
        super(SerialAggregator, self).__init__(nodes_list, *args, **kwargs)

        self.consumption = ConsumptionAggregator(nodes_list)
        self.consumption_msg_ack = {}

    @staticmethod
    def select_nodes(opts):
        """ Select all gateways and open-a8 if `with_a8` """
        nodes = common.get_nodes_selection(**vars(opts))

        # all gateways urls except A8
        nodes_list = [n for n in nodes if not n.startswith('a8')]

        return nodes_list

    def run(self):  # overwrite original function
        """ Read standard input while aggregator is running """
        try:
            self.consumption.start()
            self.read_input()
        except (KeyboardInterrupt, EOFError):
            exit(0)

    def read_input(self):
        """ Read input and sends the messages to the given nodes """
        while True:
            # line = raw_input()

            # send messages

            # nodes, message = self.extract_nodes_and_message(line)

            # if (None, '') != (nodes, message):
            #    self.send_nodes(nodes, message + '\n')
            # else: Only hitting 'enter' to get spacing
            for node, connection in self.items():
                if connection.consumption_msg_ack:
                    cons = self.consumption.accumulated_watt_s.get(node)
                    if cons:
                        msg = 'cons %.2f' % cons
                        connection.consumption_msg_ack = False
                        self.send_nodes([node], msg + '\n')
                        print('<< SENT consumption %s %s' % (node, msg))
            time.sleep(10)


    @staticmethod
    def extract_nodes_and_message(line):
        """
        >>> SerialAggregator.extract_nodes_and_message('node-a8-1;message')
        (['node-a8-1'], 'message')

        """
        try:
            nodes_str, message = line.split(';')
            if nodes_str == '-':
                # -
                return None, message

            if ',' in nodes_str:
                # m3,1-5+4
                archi, list_str = nodes_str.split(',')
            else:
                # m3-1 , a8-2, node-a8-3, wsn430-4
                # convert it as if it was with a comma
                archi, list_str = nodes_str.rsplit('-', 1)
                int(list_str)  # ValueError if not int

            # normalize archi
            archi = archi.lower()
            archi = 'node-a8' if archi == 'a8' else archi

            # get nodes list
            nodes = common_parser.nodes_id_list(archi, list_str)

            return nodes, message
        except (IndexError, ValueError):
            return None, line


def main(args=None):
    """ Aggregate all nodes sniffer """
    args = args or sys.argv[1:]
    opts = SerialAggregator.parser.parse_args(args)
    try:
        # Parse arguments
        nodes_list = SerialAggregator.select_nodes(opts)
        # Run the aggregator

        with SerialAggregator(nodes_list) as aggregator:
            aggregator.run()

    except (ValueError, RuntimeError) as err:
        sys.stderr.write("%s\n" % err)
        exit(1)


if __name__ == '__main__':
    main()
