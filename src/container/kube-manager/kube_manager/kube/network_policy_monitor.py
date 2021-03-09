#
# Copyright (c) 2017 Juniper Networks, Inc. All rights reserved.
#

from __future__ import print_function

from kube_manager.common.kube_config_db import NetworkPolicyKM
from kube_manager.kube.kube_monitor import KubeMonitor


class NetworkPolicyMonitor(KubeMonitor):

    def __init__(self, args=None, logger=None, q=None, network_policy_db=None):
        super(NetworkPolicyMonitor, self).__init__(
            args, logger, q,
            NetworkPolicyKM, resource_type='networkpolicy')

    def process_event(self, event):
        data = event['object']
        event_type = event['type']
        metadata = data['metadata']

        if self.db:
            uuid = self.db.get_uuid(data)
            obj = self.db.locate(uuid)
            if event_type != 'DELETED':
                # Update Network Policy DB.
                obj.update(data)
            else:
                # Invoke pre-delete processing for network policy delete.
                obj.remove_entry()
                # Remove the entry from Network Policy DB.
                self.db.delete(uuid)
        else:
            uuid = metadata.get('uid')

        self.register_event(uuid, event)
