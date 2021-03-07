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
        pod_data = event['object']
        event_type = event['type']
        kind = event['object'].get('kind')
        metadata = pod_data.get('metadata', {})
        namespace = metadata.get('namespace')
        pod_name = metadata.get('name')
        msg_obj = "%s:%s" % (namespace, pod_name)

        if event_type != 'DELETED':
            spec = pod_data['spec']
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

        if not namespace or not pod_name:
            self.logger.debug(
                "%s - Skipped %s %s %s (ns or name is empty)"
                % (self.name, event_type, kind, msg_obj))
            return

        if self.db:
            pod_uuid = self.db.get_uuid(event['object'])
            if event_type != 'DELETED':
                # Update Pod DB.
                pod = self.db.locate(pod_uuid)
                pod.update(pod_data)
            else:
                # Remove the entry from Pod DB.
                self.db.delete(pod_uuid)
        else:
            pod_uuid = pod_data['metadata'].get('uid')

        msg = "%s - Got %s %s %s:%s:%s" \
              % (self.name, event_type, kind, namespace, pod_name, pod_uuid)
        print(msg)
        self.logger.debug(msg)
        self.q.put(event)
