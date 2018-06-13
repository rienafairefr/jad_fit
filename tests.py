import os

from aggregator_script import ConsumptionAggregator, get_batteries

nodes_list = [
    'm3-145',
    'm3-146',
    'm3-147',
    'm3-148',
    'm3-149',
    'm3-150'
]

batteries=get_batteries('lille,m3,145-148:10000;lille,m3,149:5000')

aggregator = ConsumptionAggregator(121632, nodes_list, batteries)
for node in nodes_list:
    aggregator.accumulated_watt_s[node] = 0

for f in os.listdir('test_files/consumption'):
    node = f.split('.')[0]
    with open('test_files/consumption/%s' % f, 'r') as oml_file:
        aggregator.get_send_cons(oml_file, node )

    print('%s %f' % (node, aggregator.accumulated_watt_s.get(node)))
