#
# Copyright (c) 2017 Juniper Networks, Inc. All rights reserved.
#

from __future__ import print_function

from kube_manager.common.kube_config_db import ServiceKM
from kube_manager.kube.kube_monitor import KubeMonitor


class ServiceMonitor(KubeMonitor):

    def __init__(self, args=None, logger=None, q=None):
        super(ServiceMonitor, self).__init__(
            args, logger, q, ServiceKM, resource_type='service')

    def process_event(self, event):
        data = event['object']
        event_type = event['type']
        metadata = data['metadata']

        if event_type != 'DELETED':
            kind = data.get('kind')
            namespace = metadata.get('namespace')
            name = metadata.get('name')
            if not namespace or not name:
                self.logger.debug(
                    "%s - Skipped %s %s ns=%s sn=%s(ns or sn is empty)"
                    % (self.name, event_type, kind, namespace, name))
                return

        if self.db:
            uuid = self.db.get_uuid(event['object'])
            if event_type != 'DELETED':
                # Update Service DB.
                obj = self.db.locate(uuid)
                obj.update(data)
            else:
                # Remove the entry from Service DB.
                self.db.delete(uuid)
        else:
            uuid = metadata.get('uid')

        self.register_event(uuid, event)
