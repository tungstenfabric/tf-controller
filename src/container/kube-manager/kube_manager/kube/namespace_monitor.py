#
# Copyright (c) 2017 Juniper Networks, Inc. All rights reserved.
#

from __future__ import print_function

from kube_manager.common.kube_config_db import NamespaceKM
from kube_manager.kube.kube_monitor import KubeMonitor


class NamespaceMonitor(KubeMonitor):

    def __init__(self, args=None, logger=None, q=None):
        super(NamespaceMonitor, self).__init__(
            args, logger, q, NamespaceKM, resource_type='namespace')

    def process_event(self, event):
        data = event['object']
        event_type = event['type']
        metadata = data['metadata']

        if self.db:
            uuid = self.db.get_uuid(data)
            if event_type != 'DELETED':
                # Update Namespace DB.
                obj = self.db.locate(uuid)
                obj.update(data)
            else:
                # Remove the entry from Namespace DB.
                self.db.delete(uuid)
        else:
            uuid = metadata.get('uid')

        self.register_event(uuid, event)
