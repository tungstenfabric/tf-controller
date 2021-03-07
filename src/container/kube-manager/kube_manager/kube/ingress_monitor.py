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
        event_type = event['type']
        kind = event['object'].get('kind')

        namespace = event['object']['metadata'].get('namespace')
        name = event['object']['metadata'].get('name')
        if not namespace or not name:
            self.logger.debug(
                "%s - Skipped %s %s ns=%s name=%s (ns or name is empty)"
                % (self.name, event_type, kind, namespace, name))
            return

        event_obj = event['object']
        if self.db:
            uuid = self.db.get_uuid(event_obj)
            if event_type != 'DELETED':
                # Update Ingress DB.
                ingress_obj = self.db.locate(uuid)
                ingress_obj.update(event_obj)
            else:
                # Remove the entry from Ingress DB.
                self.db.delete(uuid)
        else:
            uuid = event['object']['metadata'].get('uid')

        msg = "%s - Got %s %s %s:%s:%s" \
              % (self.name, event_type, kind, namespace, name, uuid)
        print(msg)
        self.logger.debug(msg)
        self.q.put(event)
