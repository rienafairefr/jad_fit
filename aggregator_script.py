#!/usr/bin/env python
from __future__ import print_function
import argparse
import logging
import os
import sys
import threading
import time
import shlex

from iotlabaggregator import common, connections
from iotlabaggregator.serial import SerialConnection as AggregatorSerialConnection
from iotlabcli import auth, rest, experiment
from iotlabcli.experiment import wait_experiment, get_experiment
from iotlabcli.node import node_command
from iotlabcli.parser import common as common_parser
from iotlabcli.helpers import get_current_experiment
from iotlabcli.parser.common import nodes_list_from_str

print('current working directory: ' + os.getcwd())

user, passwd = auth.get_user_credentials()
api = rest.Api(user, passwd)

logger = logging.getLogger('aggregator_script')

home = os.path.expanduser('~')


def setup_logger(experiment_id):
    LOG_FMT = logging.Formatter("%(created)f;%(message)s")
    logger.setLevel(logging.INFO)
    line_logger = logging.StreamHandler(sys.stdout)
    line_logger.setFormatter(LOG_FMT)
    log_file = os.path.join(home, 'results', '%i.aggregator.log' % experiment_id)
    file_logger = logging.FileHandler(log_file)
    print('logging to %s' % log_file)
    file_logger.setFormatter(LOG_FMT)
    logger.addHandler(line_logger)
    logger.addHandler(file_logger)


def get_identifier(host):
    return host.split('.')[0]


def get_experiment_id():
    return get_current_experiment(api, running_only=False)


def get_nodes_dict():
    exp = get_experiment(api, get_experiment_id())
    exp_nodes = exp['nodes']
    return {get_identifier(hostname): hostname for hostname in exp_nodes}


def stop_node(node):
    node_hostname = get_nodes_dict()[node]
    logger.info('>> trying to stop node %s through the API' % node_hostname)
    experiment_id = get_experiment_id()
    logger.info('>> experiment_id %i' % experiment_id)
    logger.info('API command %s' % node_command(api, 'stop', experiment_id, nodes_list=[node_hostname]))
    logger.info('>> STOPPED node %s' % node_hostname)


def get_batteries(value):
    groups = value.split(';')
    batteries = {}
    for group in groups:
        element = group.split(':')
        if len(element) == 2:
            element_nodes_list = nodes_list_from_str(element[0])
            for node in element_nodes_list:
                batteries[get_identifier(node)] = int(element[1])
    return batteries


class ConsumptionAggregator(object):
    CONSUMPTION_DIR = os.path.join(home, ".iot-lab/{experiment_id}/consumption/{node}.oml")

    def __init__(self, experiment_id, nodes_list, batteries):
        self.nodes_list = nodes_list
        self.open_files = {}
        self.accumulated_watt_s = {}
        self.initial_value = {}
        self.times = {}
        self.batteries = batteries
        for node in self.nodes_list:
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
        for node in list(self.nodes_list):
            file = self.open_files[node]
            # schema: 0 _experiment_metadata subject:string key:string value:string
            # schema: 1 control_node_measures_consumption timestamp_s:uint32 timestamp_us:uint32 power:double voltage:double current:double
            initial_value = self.initial_value.get(node)
            lines = file.readlines()
            if lines:
                logger.info('got consumption data for %s, reading...' % node)
                for line in lines:
                    splitted = line.split('\t')
                    if len(splitted) == 8:
                        current_time = float(splitted[3]) + float(splitted[4]) / 1e6
                        dt = current_time - self.times.get(node, current_time)
                        power = float(splitted[5])
                        self.accumulated_watt_s[node] = self.accumulated_watt_s[node] + dt * power
                        self.times[node] = current_time
                        if self.batteries.get(node) and self.accumulated_watt_s[node] > self.batteries[node]:
                            if node in self.nodes_list:
                                logger.info('node %s has exceeded its battery' % node)
                                stop_node(node)
                                self.nodes_list.remove(node)
                                file.close()
                                del self.open_files[node]
                if not initial_value:
                    self.initial_value[node] = self.accumulated_watt_s[node]

                if self.times.get(node) and self.accumulated_watt_s.get(node):
                    logger.info('%u : %s : %g' % (self.times[node], node, self.accumulated_watt_s[node]))
            else:
                logger.info('no new consumption data for %s...' % node)

        time.sleep(5)


class SerialConnection(AggregatorSerialConnection):
    def __init__(self, hostname, aggregator):
        self.consumption_msg_ack = True
        self.time_msg_ack = True
        super(SerialConnection, self).__init__(hostname, aggregator, line_handler=self.line_handler, print_lines=True)

    def line_handler(self, identifier, line):
        # handle incoming messages
        if 'cons ACK' in line:
            # acknowledge the received consumption
            self.consumption_msg_ack = True
            logger.info('>> ACK cons %s' % identifier)
        elif 'time ACK' in line:
            self.time_msg_ack = True
            logger.info('>> ACK time %s' % identifier)
        elif 'stop self' in line:
            # stop the node
            logger.info(">> Trying to stop the node")
            stop_node(identifier)

        logger.info('%s;%s' % (identifier, line))


class SerialAggregator(connections.Aggregator):
    """ Customised Aggregator """

    parser = argparse.ArgumentParser()
    common.add_nodes_selection_parser(parser)
    connection_class = SerialConnection

    def __init__(self, experiment_id, nodes_list, batteries, *args, **kwargs):
        super(SerialAggregator, self).__init__(nodes_list, *args, **kwargs)

        self.consumption = ConsumptionAggregator(experiment_id, nodes_list, batteries)
        self.consumption_msg_ack = {}
        self.zero_time = time.time()

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
            for node in list(self.keys()):
                if node not in self.consumption.nodes_list:
                    logger.info('remove %s from nodes list' % node)
                    del self[node]

            for node, connection in self.items():
                if connection.consumption_msg_ack:
                    cons = self.consumption.accumulated_watt_s.get(node)
                    battery = self.consumption.batteries.get(node)
                    if cons:
                        if battery:
                            msg = 'cons %.2f %.1f' % (cons, 100 * cons/battery)
                        else:
                            msg = 'cons %.2f ---' % cons
                        connection.consumption_msg_ack = False
                        self.send_nodes([node], msg + '\n')
                        logger.info('<< SENT consumption %s %s' % (node, msg))
                    else:
                        logger.info('%s no consumption to send' % node)
                else:
                    logger.info('%s previous consumption msg was not ACKed' % node)

                if connection.time_msg_ack:
                    msg = 'time %f' % (time.time() - self.zero_time)
                    self.send_nodes([node], msg + '\n')
                    logger.info('<< SENT time %s %s' % (node, msg))
                else:
                    logger.info('previous time msg was not ACKed')

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

    scriptconfig = args.pop(0)
    with open(os.path.expanduser(scriptconfig), 'r') as _fd:
        args.extend(shlex.split(_fd.read()))

    logger.info('args %s' % args)

    parser = argparse.ArgumentParser(description='Custom aggregator script for sending consumption and time sync')
    parser.add_argument('--batteries', type=get_batteries)
    args = parser.parse_args(args)

    experiment_id = get_experiment_id()
    setup_logger(experiment_id)
    logger.info('Wait experiment %i' % experiment_id)
    wait_experiment(api, experiment_id)

    try:
        nodes_list = list(get_nodes_dict().keys())
        # Run the aggregator

        with SerialAggregator(experiment_id, nodes_list, args.batteries) as aggregator:
            aggregator.run()

    except (ValueError, RuntimeError) as err:
        sys.stderr.write("%s\n" % err)
        exit(1)


if __name__ == '__main__':
    main()
