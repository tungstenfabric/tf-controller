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
        service_data = event['object']
        event_type = event['type']
        kind = event['object'].get('kind')

        namespace = service_data['metadata'].get('namespace')
        service_name = service_data['metadata'].get('name')
        if not namespace or not service_name:
            self.logger.debug(
                "%s - Skipped %s %s ns=%s sn=%s(ns or sn is empty)"
                % (self.name, event_type, kind, namespace, service_name))
            return

        if self.db:
            service_uuid = self.db.get_uuid(event['object'])
            if event_type != 'DELETED':
                # Update Service DB.
                service = self.db.locate(service_uuid)
                service.update(service_data)
            else:
                # Remove the entry from Service DB.
                self.db.delete(service_uuid)
        else:
            service_uuid = service_data['metadata'].get('uid')

        msg = "%s - Got %s %s %s:%s:%s" \
              % (self.name, event_type, kind, namespace, service_name, service_uuid)
        print(msg)
        self.logger.debug(msg)
        self.q.put(event)
