#!/usr/bin/env python
import argparse
import sys

from iotlabaggregator import common, connections
from iotlabaggregator.serial import SerialConnection
from iotlabcli.parser import common as common_parser


class SerialAggregator(connections.Aggregator):
    """ Customised Aggregator """
    connection_class = SerialConnection

    parser = argparse.ArgumentParser()
    common.add_nodes_selection_parser(parser)

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
            self.read_input()
        except (KeyboardInterrupt, EOFError):
            pass

    def read_input(self):
        """ Read input and sends the messages to the given nodes """
        while True:
            line = raw_input()

            # send/receive message

            nodes, message = self.extract_nodes_and_message(line)

            if (None, '') != (nodes, message):
                self.send_nodes(nodes, message + '\n')
            # else: Only hitting 'enter' to get spacing

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
        print('')
        with SerialAggregator(nodes_list, print_lines=True) as aggregator:
            aggregator.run()
    except (ValueError, RuntimeError) as err:
        sys.stderr.write("%s\n" % err)
        exit(1)

if __name__ == '__main__':
    main()