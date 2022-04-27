#
# Copyright (c) 2018 Juniper Networks, Inc. All rights reserved.
#

from __future__ import print_function

import json
from kube_manager.common.kube_config_db import NetworkKM
from kube_manager.kube.kube_monitor import KubeMonitor


class NetworkMonitor(KubeMonitor):
    def __init__(self, args=None, logger=None, q=None):
        self.resource_type = 'networkattachmentdefinition'
        self.crd_resource_type = 'customresourcedefinition'
        super(NetworkMonitor, self).__init__(
            args, logger, q,
            NetworkKM, resource_type=self.resource_type,
            api_group='apis/k8s.cni.cncf.io', api_version='v1')

    def init_monitor(self):
        if not self.resource_version:
            # create crds first init
            self._create_crds()
        super(NetworkMonitor, self).init_monitor()

    def _create_crds(self):
        # Check if Network CustomResourceDefinition is already created,
        # If not create it internally
        (crd_info) = self.get_resource(
            resource_type=self.crd_resource_type,
            resource_name="network-attachment-definitions.k8s.cni.cncf.io")
        if crd_info is None:
            self.logger.error(
                "%s - Could not get CRD list.  CRD INFO = %s"
                % (self.name, crd_info))
            return
        else:
            self.logger.debug(
                "%s - Retrieved following CRD info = %s"
                % (self.name, crd_info))
            if not crd_info or \
                    'metadata' not in crd_info or \
                    'network-attachment-definitions.k8s.cni.cncf.io' \
                    not in crd_info['metadata']['name']:
                # Create Networks CRD - networks.kubernetes.cni.cncf.io
                self.logger.debug("%s - Creating Network CRD" % (self.name))
                network_crd_body = self.create_network_crd_yaml()
                resp = self.post_resource(
                    resource_type=self.crd_resource_type,
                    resource_name='', body_params=network_crd_body)
                if not resp:
                    return
                msg = ""
                try:
                    while True:
                        line = next(resp)
                        if not line:
                            break
                        msg += line
                except StopIteration:
                    pass
                self.logger.debug("%s - Creating Network CRD response - %s" % (self.name, msg))

    def create_network_crd_yaml(self):
        api_group = self.k8s_api_resources[self.crd_resource_type]['group']
        api_version = self.k8s_api_resources[self.crd_resource_type]['version']
        kind = self.k8s_api_resources[self.crd_resource_type]['kind']
        network_crd_dict = dict(
            apiVersion=api_group + '/' + api_version,
            kind=kind,
            metadata=dict(
                name='network-attachment-definitions.k8s.cni.cncf.io'
            ),
            spec=dict(
                group='k8s.cni.cncf.io',
                versions=[dict(
                    name='v1',
                    served=bool(1),
                    storage=bool(1),
                    schema=dict(
                        openAPIV3Schema=dict(
                            type='object',
                            properties=dict(
                                spec=dict(
                                    type='object',
                                    properties=dict(
                                        config=dict(
                                            type='string'
                                        )
                                    )
                                )
                            )
                        )
                    )
                )],
                scope='Namespaced',
                names=dict(
                    plural='network-attachment-definitions',
                    singular='network-attachment-definition',
                    kind='NetworkAttachmentDefinition',
                    shortNames=['net-attach-def']
                )
            )
        )

        return network_crd_dict

    def key_exists(self, dict, *nested_keys):
        _dict = dict
        for key in nested_keys:
            try:
                _dict = _dict[key]
                if not _dict:
                    return False
            except KeyError:
                return False
        return True

    def process_event(self, event):
        data = event['object']
        event_type = event['type']
        metadata = data['metadata']

        kind = event['object'].get('kind')
        namespace = metadata.get('namespace')
        name = metadata.get('name')

        # if network is not designated to contrail-k8s-cni, dont process
        nested_keys = ['object', 'spec', 'config']
        if not self.key_exists(event, *nested_keys):
            self._log(
                "%s - Skipped %s %s ns=%s name=%s (not for contrail-k8s-cni)"
                % (self.name, event_type, kind, namespace, name),
                level='debug')
            return
        config_json = json.loads(event['object']['spec']['config'])
        if ('type' not in config_json.keys() or
                config_json['type'] != 'contrail-k8s-cni'):
            self._log(
                "%s - Skipped %s %s ns=%s config_json=%s (not for contrail-k8s-cni)"
                % (self.name, event_type, kind, namespace, config_json),
                level='debug')
            return

        if self.db:
            uuid = self.db.get_uuid(data)
            if event_type != 'DELETED':
                # Update Network DB.
                obj = self.db.locate(uuid)
                obj.update(data)
            else:
                # Remove the entry from Network DB.
                self.db.delete(uuid)
        else:
            uuid = metadata.get('uid')

        self.register_event(uuid, event)
