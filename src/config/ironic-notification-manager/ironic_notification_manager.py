#
# Copyright (c) 2017 Juniper Networks, Inc. All rights reserved.
#

"""
This file contains implementation of managing ironic notifications
"""

from gevent import monkey
monkey.patch_all()
import sys
import argparse
import ConfigParser
import socket
import hashlib
import random
import six

from keystoneauth1.identity import ks_v3
from keystoneauth1 import ks_session
from ironicclient import client as ironicclient

from sandesh_common.vns.ttypes import Module
from sandesh_common.vns.constants import ModuleNames, Module2NodeType, \
    NodeTypeNames, INSTANCE_ID_DEFAULT, ServiceHttpPortMap
from pysandesh.sandesh_base import Sandesh, SandeshConfig, sandesh_global

from .sandesh.ironic_notification_manager.ttypes import \
    IronicNode, IronicNodeInfo, LocalLinkConnection, \
    PortInfo, InternalPortInfo, NodeProperties, DriverInfo, \
    InstanceInfo

from ironic_notification_manager.ironic_kombu import IronicKombuClient


class IronicNotificationManager(object):

    _ironic_kombu_client = None

    IronicNoeDictKeyMap = {
        'uuid': 'name',
        'provision_state': 'provision_state',
        'power_state': 'power_state',
        'driver': 'driver',
        'instance_uuid': 'instance_uuid',
        'name': 'host_name',
        'network_interface': 'network_interface',
        'event_type': 'event_type',
        'publisher_id': 'publisher_id',
        'maintenance': 'maintenance',
        'provision_updated_at': 'provision_update_timestamp',
        'updated_at': 'update_timestamp',
        'created_at': 'create_timestamp',
        'driver_info': 'driver_info',
        'port_info': 'port_info',
        'instance_info': 'instance_info',
        'properties': 'properties'}
    PortInfoDictKeyMap = {
        'uuid': 'port_uuid',
        'pxe_enabled': 'pxe_enabled',
        'address': 'mac_address',
        'created_at': 'create_timestamp'
    }
    SubDictKeys = ['driver_info', 'instance_info', 'properties', 'port_info']
    SubDictKeyMap = {
        'driver_info': [
            'ipmi_address', 'ipmi_password', 'ipmi_username',
            'ipmi_terminal_port', 'deploy_kernel', 'deploy_ramdisk'],
        'instance_info': [
            'display_name', 'nova_host_id', 'configdrive', 'root_gb',
            'memory_mb', 'vcpus', 'local_gb', 'image_checksum',
            'image_source', 'image_type', 'image_url'],
        'properties': [
            'cpu_arch', 'cpus', 'local_gb', 'memory_mb', 'capabilities'],
        'port_info': [
            'port_uuid', 'pxe_enabled', 'mac_address',
            'local_link_connection', 'internal_info']
    }

    def __init__(self, args):
        self._args = args

    def get_ironic_client(self):
        if self._args.auth_url:
            auth_url = self._args.auth_url
        else:
            auth_url = '%s://%s:%s/%s' % (
                self._args.auth_protocol,
                self._args.auth_host,
                self._args.auth_port,
                self._args.auth_version.strip('/'))

        auth = ks_v3.Password(
            auth_url=auth_url,
            username=self._args.admin_user,
            password=self._args.admin_password,
            project_name=self._args.admin_tenant_name,
            user_domain_name=self._args.user_domain_name,
            project_domain_name=self._args.project_domain_name
        )
        verify = self._args.cafile if self._args.cafile else not self._args.insecure
        session = ks_session.Session(auth=auth, verify=verify)

        return ironicclient.get_client(
            1, os_ironic_api_version="1.19", session=session, region_name=self._args.region_name)

    def resync_with_ironic(self):
        ironic_client = self.get_ironic_client()

        # Get and process Ironic Nodes
        node_dict_list = ironic_client.node.list(detail=True)
        new_node_dict_list = []
        node_port_map = {}
        for node_dict in node_dict_list:
            new_node_dict_list.append(node_dict.to_dict())
            node_port_map[node_dict.to_dict()["uuid"]] = []
        self.process_ironic_node_info(new_node_dict_list)

        # Get and process Ports for all Ironic Nodes
        port_dict_list = ironic_client.port.list(detail=True)
        for port_dict in port_dict_list:
            ironic_node_with_port_info = self.process_ironic_port_info(port_dict.to_dict())
            node_port_map[ironic_node_with_port_info["name"]] += ironic_node_with_port_info["port_info"]
        for node_uuid in node_port_map.keys():
            ironic_node_data = {
                "name": str(node_uuid),
                "port_info": node_port_map[node_uuid]}
            ironic_node_sandesh = IronicNode(**ironic_node_data)
            ironic_node_sandesh.name = ironic_node_data["name"]
            ironic_sandesh_object = IronicNodeInfo(data=ironic_node_sandesh)
            ironic_sandesh_object.send()

    def sandesh_init(self):
        # Inventory node module initialization part
        __import__(
            'ironic_notification_manager.sandesh.ironic_notification_manager'
        )
        module = Module.IRONIC_NOTIF_MANAGER

        module_name = ModuleNames[module]
        node_type = Module2NodeType[module]
        node_type_name = NodeTypeNames[node_type]
        instance_id = INSTANCE_ID_DEFAULT
        sandesh_package_list = [
            'ironic_notification_manager.sandesh.ironic_notification_manager'
        ]

        # In case of multiple collectors, use a randomly chosen one
        self.random_collectors = self._args.collectors
        if self._args.collectors:
            self._chksum = \
                hashlib.md5("".join(self._args.collectors)).hexdigest()
            self.random_collectors = \
                random.sample(self._args.collectors, len(self._args.collectors))
        if 'host_ip' in self._args:
            host_ip = self._args.host_ip
        else:
            host_ip = socket.gethostbyname(socket.getfqdn())
        sandesh_global.init_generator(
            module_name,
            socket.getfqdn(host_ip),
            node_type_name,
            instance_id,
            self.random_collectors,
            module_name,
            self._args.introspect_port,
            sandesh_package_list)
        sandesh_global.set_logging_params(
            enable_local_log=self._args.log_local,
            category=self._args.log_category,
            level=self._args.log_level,
            file=self._args.log_file,
            enable_syslog=self._args.use_syslog,
            syslog_facility=self._args.syslog_facility)
        self._sandesh_logger = sandesh_global._logger

    def process_ironic_port_info(self, data_dict, ironic_node_data=None):
        PortInfoDict = dict()
        PortList = []
        if not ironic_node_data:
            ironic_node_data = dict()

        for key in self.PortInfoDictKeyMap.keys():
            if key in data_dict:
                PortInfoDict[self.PortInfoDictKeyMap[key]] = \
                    data_dict[key]

        if "event_type" in data_dict and str(data_dict["event_type"]) == "baremetal.port.delete.end":
            if "node_uuid" in data_dict:
                ironic_node_data["name"] = data_dict["node_uuid"]
            ironic_node_data["port_info"] = []
            return ironic_node_data

        if "local_link_connection" in data_dict:
            local_link_connection = LocalLinkConnection(**data_dict["local_link_connection"])
            data_dict.pop("local_link_connection")
            PortInfoDict["local_link_connection"] = local_link_connection

        if "internal_info" in data_dict:
            internal_info = InternalPortInfo(**data_dict["internal_info"])
            data_dict.pop("internal_info")
            PortInfoDict["internal_info"] = internal_info

        if "node_uuid" in data_dict:
            ironic_node_data["name"] = data_dict["node_uuid"]
            PortInfoDict["name"] = PortInfoDict["port_uuid"]
            PortList.append(PortInfo(**PortInfoDict))
            ironic_node_data["port_info"] = PortList

        return ironic_node_data

    def process_ironic_node_info(self, node_dict_list):
        for node_dict in node_dict_list:
            if not isinstance(node_dict, dict):
                node_dict = node_dict.to_dict()

            ironic_node_data = dict()
            driver_info_data = dict()
            instance_info_data = dict()
            node_properties_data = dict()

            for key in self.IronicNoeDictKeyMap.keys():
                if key in node_dict and key not in self.SubDictKeys:
                    ironic_node_data[self.IronicNoeDictKeyMap[key]] = \
                        node_dict[key]

            for sub_dict in self.SubDictKeys:
                ironic_node_data[sub_dict] = {}
                if sub_dict in node_dict.keys():
                    for key in node_dict[sub_dict]:
                        if key in self.SubDictKeyMap[sub_dict]:
                            ironic_node_data[sub_dict][key] = \
                                node_dict[sub_dict][key]

            if "event_type" in node_dict:
                if str(node_dict["event_type"]) == "baremetal.node.delete.end":
                    ironic_node_sandesh = IronicNode(**ironic_node_data)
                    ironic_node_sandesh.deleted = True
                    ironic_node_sandesh.name = ironic_node_data["name"]
                    ironic_sandesh_object = IronicNodeInfo(data=ironic_node_sandesh)
                    ironic_sandesh_object.send()
                    continue
                if "port" in str(node_dict["event_type"]):
                    ironic_node_data = self.process_ironic_port_info(node_dict, ironic_node_data)

            driver_info_data = ironic_node_data.pop("driver_info", None)
            instance_info_data = ironic_node_data.pop("instance_info", None)
            node_properties_data = ironic_node_data.pop("properties", None)
            port_info_list = ironic_node_data.pop("port_info", None)

            ironic_node_sandesh = IronicNode(**ironic_node_data)
            ironic_node_sandesh.name = ironic_node_data["name"]

            if driver_info_data:
                driver_info = DriverInfo(**driver_info_data)
                ironic_node_sandesh.driver_info = driver_info
            if instance_info_data:
                instance_info = InstanceInfo(**instance_info_data)
                ironic_node_sandesh.instance_info = instance_info
            if node_properties_data:
                node_properties = NodeProperties(**node_properties_data)
                ironic_node_sandesh.node_properties = node_properties
            if port_info_list:
                port_list = []
                for item in port_info_list:
                    port_info = PortInfo(**item)
                    port_list.append(port_info)
                ironic_node_sandesh.port_info = port_list

            self._sandesh_logger.info('\nIronic Node Info: %s' % ironic_node_data)
            self._sandesh_logger.info('\nIronic Driver Info: %s' % driver_info_data)
            self._sandesh_logger.info('\nIronic Instance Info: %s' % instance_info_data)
            self._sandesh_logger.info('\nNode Properties: %s' % node_properties_data)
            self._sandesh_logger.info('\nIronic Port Info: %s' % port_info_list)

            ironic_sandesh_object = IronicNodeInfo(data=ironic_node_sandesh)
            ironic_sandesh_object.send()

    def start(self):
        ironic_kombu_client = IronicKombuClient(self, self._sandesh_logger, self._args)
        ironic_kombu_client._start()


def parse_args(args_str):
    '''
    Eg. python ironic_notification_manager.py \
        -c ironic-notification-manager.conf \
        -c contrail-keystone-auth.conf
    '''

    # Source any specified config/ini file
    # Turn off help, so we      all options in response to -h
    conf_parser = argparse.ArgumentParser(add_help=False)

    conf_parser.add_argument("-c", "--conf_file", action='append',
                             help="Specify config file", metavar="FILE")
    args, remaining_argv = conf_parser.parse_known_args(args_str.split())

    defaults = {
        'collectors': '127.0.0.1:8086',
        'introspect_port': int(
            ServiceHttpPortMap[ModuleNames[Module.IRONIC_NOTIF_MANAGER]]),
        'log_level': 'SYS_INFO',
        'log_local': False,
        'log_category': '',
        'log_file': Sandesh._DEFAULT_LOG_FILE,
        'use_syslog': False,
        'syslog_facility': Sandesh._DEFAULT_SYSLOG_FACILITY,
        # rabbitmq section
        'rabbit_servers': None,
        'rabbit_user': None,
        'rabbit_password': None,
        'rabbit_vhost': None,
        'rabbit_use_ssl': None,
        'kombu_ssl_version': None,
        'kombu_ssl_certfile': None,
        'kombu_ssl_keyfile': None,
        'kombu_ssl_ca_certs': None,
    }
    ksopts = {
        'auth_url': '',
        'auth_host': '127.0.0.1',
        'auth_port': '35357',
        'auth_protocol': 'http',
        'auth_version': 'v2.0',
        'admin_user': '',
        'admin_password': '',
        'admin_tenant_name': '',
        'user_domain_name': None,
        'project_domain_name': None,
        'insecure': False,
        'cafile': None,
        'region_name': 'RegionOne',
    }
    defaults.update(SandeshConfig.get_default_options(['DEFAULTS']))
    sandesh_opts = SandeshConfig.get_default_options()

    if args.conf_file:
        config = ConfigParser.SafeConfigParser()
        config.read(args.conf_file)
        defaults.update(dict(config.items("DEFAULTS")))
        if 'KEYSTONE' in config.sections():
            ksopts.update(dict(config.items("KEYSTONE")))
        SandeshConfig.update_options(sandesh_opts, config)

    # Override with CLI options
    # Don't surpress add_help here so it will handle -h
    parser = argparse.ArgumentParser(
        # Inherit options from config_parser
        parents=[conf_parser],
        # print script description with -h/--help
        description=__doc__,
        # Don't mess with format of description
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    defaults.update(ksopts)
    defaults.update(sandesh_opts)
    parser.set_defaults(**defaults)

    args = parser.parse_args(remaining_argv)
    if isinstance(args.collectors, six.string_types):
        args.collectors = args.collectors.split()
    if isinstance(args.introspect_port, six.string_types):
        args.introspect_port = int(args.introspect_port)
    if isinstance(args.insecure, six.string_types):
        args.insecure = args.insecure.lower() == 'true'
    return args
# end parse_args


def main(args_str=None):
    if not args_str:
        args_str = ' '.join(sys.argv[1:])
    args = parse_args(args_str)

    # Create Ironic Notification Daemon and sync with Ironic
    ironic_notification_manager = IronicNotificationManager(args)
    ironic_notification_manager.sandesh_init()
    ironic_notification_manager.resync_with_ironic()

    # start listening
    ironic_notification_manager.start()


if __name__ == '__main__':
    main()
