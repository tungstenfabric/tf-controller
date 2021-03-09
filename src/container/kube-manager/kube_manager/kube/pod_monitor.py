#
# Copyright (c) 2017 Juniper Networks, Inc. All rights reserved.
#

from __future__ import print_function

from kube_manager.common.kube_config_db import PodKM
from kube_manager.kube.kube_monitor import KubeMonitor


class PodMonitor(KubeMonitor):

    def __init__(self, args=None, logger=None, q=None):
        super(PodMonitor, self).__init__(
            args, logger, q, PodKM, resource_type='pod')

    def process_event(self, event):
        data = event['object']
        event_type = event['type']
        metadata = data.get('metadata', {})

        if event_type != 'DELETED':
            kind = event['object'].get('kind')
            namespace = metadata.get('namespace')
            name = metadata.get('name')
            msg_obj = "%s:%s" % (namespace, name)
            spec = data['spec']
            if spec.get('hostNetwork'):
                self.logger.debug(
                    "%s - Skipped %s %s %s (hostNetwork=%s)"
                    % (self.name, event_type, kind, msg_obj, spec.get('hostNetwork')))
                return
            if not spec.get('nodeName'):
                self.logger.debug(
                    "%s - Skipped %s %s %s (no nodeName)"
                    % (self.name, event_type, kind, msg_obj))
                return
            if not namespace or not name:
                self.logger.debug(
                    "%s - Skipped %s %s %s (ns or name is empty)"
                    % (self.name, event_type, kind, msg_obj))
                return

        if self.db:
            uuid = self.db.get_uuid(event['object'])
            if event_type != 'DELETED':
                # Update Pod DB.
                obj = self.db.locate(uuid)
                obj.update(data)
            else:
                # Remove the entry from Pod DB.
                self.db.delete(uuid)
        else:
            uuid = metadata.get('uid')

        self.register_event(uuid, event)
