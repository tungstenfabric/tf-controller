#
# Copyright (c) 2017 Juniper Networks, Inc. All rights reserved.
#

from __future__ import print_function

from kube_manager.kube.kube_monitor import KubeMonitor


class EndPointMonitor(KubeMonitor):

    def __init__(self, args=None, logger=None, q=None):
        super(EndPointMonitor, self).__init__(
            args, logger, q, resource_type='endpoints')

    def process_event(self, event):
        endpoint_data = event['object']
        event_type = event['type']
        kind = event['object'].get('kind')

        namespace = endpoint_data['metadata'].get('namespace')
        endpoint_name = endpoint_data['metadata'].get('name')
        uid = endpoint_data['metadata'].get('uid')
        if not endpoint_name or not namespace:
            self.logger.debug(
                "%s - Skipped %s %s ns=%s endpoint=%s (ns or endpoint is empty)"
                % (self.name, event_type, kind, namespace, endpoint_name))
            return

        ctrl_plane_endpoints = [
            "kube-controller-manager",
            "kube-scheduler",
            "openshift-master-controllers"
        ]
        if endpoint_name in ctrl_plane_endpoints:
            self.logger.debug(
                "%s - Skipped %s %s ns=%s endpoint=%s (kube endpoint)"
                % (self.name, event_type, kind, namespace, endpoint_name))
            return

        msg = "%s - Got %s %s %s:%s:%s" \
              % (self.name, event_type, kind, namespace, endpoint_name, uid)
        print(msg)
        self.logger.debug(msg)
        self.q.put(event)
