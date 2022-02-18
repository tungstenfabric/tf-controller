#
# Copyright (c) 2017 Juniper Networks, Inc. All rights reserved.
#

from __future__ import print_function

from kube_manager.common.kube_config_db import IngressKM
from kube_manager.kube.kube_monitor import KubeMonitor


class IngressMonitor(KubeMonitor):

    def __init__(self, args=None, logger=None, q=None):
        super(IngressMonitor, self).__init__(
            args, logger, q, IngressKM, resource_type='ingress')

    def process_event(self, event):
        data = event['object']
        event_type = event['type']
        metadata = data['metadata']

        if event_type != 'DELETED':
            namespace = metadata.get('namespace')
            name = metadata.get('name')
            if not namespace or not name:
                kind = data.get('kind')
                self._log(
                    "%s - Skipped %s %s ns=%s name=%s (ns or name is empty)"
                    % (self.name, event_type, kind, namespace, name),
                    level='debug')
                return

        if self.db:
            uuid = self.db.get_uuid(data)
            if event_type != 'DELETED':
                # Update Ingress DB.
                obj = self.db.locate(uuid)
                obj.update(data)
            else:
                # Remove the entry from Ingress DB.
                self.db.delete(uuid)
        else:
            uuid = metadata.get('uid')

        self.register_event(uuid, event)
