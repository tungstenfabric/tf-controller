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
        data = event['object']
        event_type = event['type']
        metadata = data['metadata']

        kind = event['object'].get('kind')
        namespace = metadata.get('namespace')
        name = metadata.get('name')

        if not name or not namespace:
            self._log(
                "%s - Skipped %s %s ns=%s endpoint=%s (ns or endpoint is empty)"
                % (self.name, event_type, kind, namespace, name),
                level='debug')
            return

        ctrl_plane_endpoints = [
            "kube-controller-manager",
            "kube-scheduler",
            "openshift-master-controllers"
        ]
        if name in ctrl_plane_endpoints:
            self._log(
                "%s - Skipped %s %s ns=%s endpoint=%s (kube endpoint)"
                % (self.name, event_type, kind, namespace, name),
                level='debug')
            return

        uuid = metadata.get('uid')

        self.register_event(uuid, event)
