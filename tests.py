import os

from aggregator_script import ConsumptionAggregator


aggregator = ConsumptionAggregator(121632, [], {})

test_dir = 'test_files/jad/122213/consumption'
for f in os.listdir(test_dir):
    node = f.split('.')[0]
    aggregator.accumulated_watt_s[node] = 0
    aggregator.batteries[node] = 9999999
    with open(os.path.join(test_dir,f), 'r') as oml_file:
        aggregator.read_consumption_file(oml_file, node)

    print('%s %f' % (node, aggregator.accumulated_watt_s.get(node)))
