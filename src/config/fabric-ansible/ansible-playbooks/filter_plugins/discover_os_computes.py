#!/usr/bin/python

#
# Copyright (c) 2020 Juniper Networks, Inc. All rights reserved.
#

from builtins import object
import collections
import logging
import sys
import traceback

sys.path.append('/opt/contrail/fabric_ansible_playbooks/filter_plugins')  # noga
sys.path.append('/opt/contrail/fabric_ansible_playbooks/common')  # noqa
from contrail_command import CreateCCNode
from import_server import FilterModule as FilterModuleImportServer

from job_manager.job_utils import JobVncApi

DOCUMENTATION = '''
---
Discover OS ML2 Computes.

This file contains implementation of identifying all leaf switches  # noqa: E501
in provided fabric network and creating OS ML2 computes.

find_leaf_devices filter:

Collect all devices which are added to a given fabric network.
Identify physical_router_role for each device and collect data only for leaf devices.
If device is leaf, credentials are gathered and returned to run "show lldp neighbors detail" command.

create_os_ml2_node_filter filter:

For output data from command "show lldp neighbors detail" collect needed data to create os node object.
Then return list of all objects founded in network in format:
nodes:
  - name: node-1
    node_type: ovs-compute
    ports:
      - name: ens224
        mac_address: 00:0c:29:13:37:bb
        switch_name: VM283DD71D00
        tags:
            - physnet1

ML2 OS computes' LLDP information should contain custom TLVs which are set during deployment.
Accepted TLVs have OUI of 0x009069 (Juniper Specific). There are two Subtypes of custom TLVs.
Subtype 123 TLV's Info field contains a list of names of interfaces that are
connected to a management network. Subtype 124 TLV's Info field contains
a list of physnet_name:interface_name mappings for interfaces connected to a physical network
(indicating an SR-IOV port).

Note: These two TLVs are always expected to be present.
Since "show lldp neighbors detail" command doesn't show TLVs with empty
INFO field, if there are no management or sriov interfaces, this field should
be set to "none" for the node to be recognized by this script as an ML2 OS compute.

Based on TLVs' info, tags may be added to a port.
For management port, a 'management' tag will be added.
For SRIOV port, the name of physical network that it's connected to will be added.
'''

LEAF = 'leaf'
OVS = "ovs"
SRIOV = "sriov"
OVS_COMPUTE = "ovs-compute"
SRIOV_COMPUTE = "sriov-compute"
REGEX_NODE_TYPE = r"node_type: (\w+)"
FAILURE = 'failure'
SUCCESS = 'success'
STATUS = 'status'
ERRMSG = 'errmsg'
LEAF_DEVICES = 'leaf_devices'
OS_COMPUTE_NODES = 'os_compute_nodes'
MANAGEMENT_PORT_TAG = 'management'
MANAGEMENT_TLV_SUBTYPE = '(123)'
SRIOV_TLV_SUBTYPE = '(124)'
TLV_INFO_NOT_SET = 'none'


class FilterModule(object):
    """Fabric filter plugins."""

    @staticmethod
    def _init_logging():
        """Initialize logging.

        :return: type=<logging.Logger>
        """
        logger = logging.getLogger('ML2ComputesDiscoveryFilter')

        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.WARN)

        formatter = logging.Formatter(
            '%(asctime)s %(levelname)-8s %(message)s',
            datefmt='%Y/%m/%d %H:%M:%S'
        )
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)

        return logger

    def __init__(self):
        """Initialize Fabric Filter Module."""
        self.tags = {}
        self._logger = FilterModule._init_logging()

    def filters(self):
        """Return filters that will be used."""
        return {
            'find_leaf_devices_filter': self.find_leaf_devices_filter,
            'create_os_ml2_node_filter': self.create_os_ml2_node_filter
        }

    @staticmethod
    def _validate_job_ctx(job_ctx):
        """Validate input params."""
        job_input = job_ctx.get('input')
        if not job_input:
            raise ValueError('Invalid job_ctx: missing job_input')
        if not job_ctx.get('job_template_fqname'):
            raise ValueError('Invalid job_ctx: missing job_template_fqname')
        if not job_input.get('fabric_fq_name'):
            raise ValueError('Invalid job_ctx: missing fabric_fq_name')

    @staticmethod
    def _get_password(device_obj):
        """Get and return decrypted password."""
        password = device_obj.physical_router_user_credentials.get_password()
        return JobVncApi.decrypt_password(encrypted_password=password,
                                          pwd_key=device_obj.uuid)

    @staticmethod
    def get_fabric_name(fabric):
        """
        Get and return fabric_name.

        :param fabric: string
        :return fabric_name: string
        """
        return fabric.get_fq_name_str()

    @staticmethod
    def get_physical_router_devices(fabric):
        """
        Get and return list of physical routers in provided fabric.

        :param fabric: string
        :return physical_router_refs: list
        """
        physical_router_refs = fabric.get_physical_router_back_refs()
        if physical_router_refs is None:
            physical_router_refs = []
        return physical_router_refs

    # ***************** find_leaf_devices filter *****************************

    def find_leaf_devices(self, fabric_fq_name, vnc_api):
        """
        Find and return all Leaf devices for given Fabric Network.

        For found devices, collect and return authentication data.
        Credentials data will be used to run commands directly on a device.

        :param fabric_fq_name: list
        :param vnc_api: vnc_api established connection
        :return:
            # example
            # [
            #     {
            #         "host": "10.10.10.2",
            #         "password": "admin",
            #         "username": "admin"
            #     },
            #     {
            #         "host": "10.10.10.4",
            #         "password": "admin",
            #         "username": "admin"
            #     }
            # ]
        """
        fabric = vnc_api.fabric_read(fabric_fq_name)
        fabric_name = FilterModule.get_fabric_name(fabric)
        self._logger.info("Begin process of discovering leaf devices in fabric network %s" % fabric_name)  # noqa: E501
        physical_router_refs = FilterModule.get_physical_router_devices(fabric)
        self._logger.info(
            "In fabric %s Found the following list of physical routers %s" % (fabric_name, physical_router_refs))  # noqa: E501
        results = []
        for p_router in physical_router_refs:
            physical_router = vnc_api.physical_router_read(id=p_router['uuid'])
            if physical_router.physical_router_role != LEAF:
                continue
            host_details = {
                'username': physical_router.physical_router_user_credentials.username,  # noqa: E501
                'password': (FilterModule._get_password(physical_router)),
                'host': physical_router.physical_router_management_ip
            }
            results.append(host_details)
            self._logger.\
                info("In fabric %s Found the following leaf device %s "
                     "On this device 'show lldp neighbor details' command "
                     "will be applied"
                     % (fabric_name, physical_router.physical_router_management_ip))  # noqa: E501
        return results

    def find_leaf_devices_filter(self, job_ctx):
        """
        Validate input and call method to find leaf devices in provided fabric.

        :param job_ctx: Dictionary
            # example:
            #  {
            #     'job_transaction_descr': 'Discover OS Computes',
            #     'fabric_fq_name': ['default-global-system-config',
            #                        '123412341234-123412341234'],
            #     'contrail_command_host': '10.10.10.10:9091',
            #     'cc_username': 'root',
            #     'cc_password': "root"
            # }
        :return: Dictionary
            # if success, returns
            # {
            #     'status': 'success',
            #     'leaf_devices': [
            #             {
            #                 'username': u'admin',
            #                 'host': '10.10.10.4',
            #                 'password': 'admin'
            #             }
            #         ]
            # }
            # if failure, returns
            # {
            #     'status': 'failure',
            #     'error_msg': <string: error message>
            # }
        """
        try:
            FilterModule._validate_job_ctx(job_ctx)
            job_input = job_ctx.get('input')
            vnc_api = JobVncApi.vnc_init(job_ctx)
            fabric_fq_name = job_input['fabric_fq_name']
            leaf_devices = self.find_leaf_devices(fabric_fq_name, vnc_api)
        except Exception as e:
            errmsg = "Unexpected error: %s\n%s" % (
                str(e), traceback.format_exc()
            )
            return {
                STATUS: FAILURE,
                ERRMSG: errmsg,
            }

        return {
            STATUS: SUCCESS,
            LEAF_DEVICES: leaf_devices,
        }

    # ***************** create_os_ml2_node_filter filter **********************

    def get_mapping_ip_to_hostname(self, vnc_api, fabric_fq_name):
        """
        Create a dictionary with mapping IP address to device Hostname.

        :param vnc_api: vnc_api class established connection
        :param fabric_fq_name: list
        :return: Dictionary
            # example:
            #     {
            #     '10.10.10.4': 'Router_1',
            #     '10.10.10.7': 'Router_2'
            # }
        """
        fabric = vnc_api.fabric_read(fabric_fq_name)
        physical_router_refs = FilterModule.get_physical_router_devices(fabric)
        ip_to_hostname = {}
        for dev in physical_router_refs:
            physical_router = vnc_api.physical_router_read(id=dev['uuid'])
            device_ip_address = physical_router.physical_router_management_ip
            device_hostname = physical_router.get_physical_router_hostname()
            ip_to_hostname[device_ip_address] = device_hostname
        self._logger.debug(
            "Found the following IP to Hostname mapping dictionary:  %s" %
            ip_to_hostname
        )
        return ip_to_hostname

    def calculate_tags(self, device_neighbor_details):
        """
        Calculate tags to be added to ports, based on device_neighbor_details.
        """
        node_name = str(device_neighbor_details['lldp-remote-system-name'])
        self.tags[node_name] = collections.defaultdict(list)

        management_tlv, sriov_tlv = FilterModule.get_custom_ml2_tlvs(
            device_neighbor_details
        )
        management_ifaces = FilterModule.extract_management_ifaces_names(
            management_tlv
        )
        sriov_mappings = FilterModule.extract_sriov_mappings(sriov_tlv)

        for interface_name in management_ifaces:
            self.tags[node_name][interface_name].append(MANAGEMENT_PORT_TAG)

        for interface_name, network_name in sriov_mappings.items():
            self.tags[node_name][interface_name].append(network_name)

    def get_tags_for_port(self, node_name, port_name):
        return self.tags.get(node_name, {}).get(port_name, [])

    @staticmethod
    def get_node_type(sriov_tlv):
        """
        Based on provided sriov_tlv verify and return node_type of OS compute.

        If specified sriov_tlv is None, then the node won't be recognized as neither
        OVS nor SRIOV compute.

        :param sriov_tlv: dict
            # example:
            #     {
            #         "lldp-remote-index": "4",
            #         "lldp-remote-oui-juniper": "009069",
            #         "lldp-remote-subtype": "(124)",
            #         "lldp-remote-value": "4E6F6E65"
            #     }
        :return: string or None
            example: "ovs-compute"
        """
        if not sriov_tlv:
            return None

        if FilterModule.decode_tlv_info(sriov_tlv).lower() == TLV_INFO_NOT_SET:
            return OVS_COMPUTE
        else:
            return SRIOV_COMPUTE

    @staticmethod
    def create_node_properties(self,
                               device_neighbor_details,
                               node_type,
                               device_display_name):
        """
        Create and return node properties.

        :param device_neighbor_details: Dictionary
            # example:
            #  {
            #     'lldp-remote-system-name': 'node-4',
            #     'lldp-local-interface': 'xe-0/0/3',
            #     'lldp-remote-port-description': u'ens224',
            #     'lldp-remote-port-id': '00:0c:29:8b:ef:26',
            #     (...)
            # }
        :param node_type: String
        :param device_display_name: String
        :return: Dictionary
            # example:
            # {
            #     'nodes_type': 'ovs-compute',
            #     'name': u'node-1',
            #     'ports':
            #         [{
            #             'mac_address': u'00:0c:29:13:37:bb',
            #             'port_name': u'xe-0/0/0',
            #             'switch_name': u'VM283DD71D00',
            #             'name': u'ens224'
            #             'tags': ['management']
            #         }]
            # }
        """
        node_name = str(device_neighbor_details['lldp-remote-system-name'])
        port_name = str(device_neighbor_details['lldp-remote-port-description']) # noqa: E501
        port = {
            'port_name': str(device_neighbor_details['lldp-local-interface']),  # noqa: E501
            'switch_name': device_display_name,
            'name': port_name,
            'mac_address': str(device_neighbor_details['lldp-remote-port-id']),
            'tags': self.get_tags_for_port(node_name, port_name)
        }
        node = {
            'node_type': node_type,
            'name': node_name,
            'ports': [port]
        }

        return node

    @staticmethod
    def import_nodes_to_contrail(all_nodes, cc_node_obj):
        """
        Import nodes to CC using import_server job trigger.

        :param all_nodes: Dictionary
        :param cc_node_obj: CreateCCNode object class
        :return: None
        """
        logging.info("Begin adding nodes {} to Contrail Command".format(str(all_nodes)))  # noqa: E501
        FilterModuleImportServer().import_nodes(all_nodes, cc_node_obj)

    @staticmethod
    def get_switch_name(node):
        """
        Get and return switch_name.

        There is always only one element in a list.
        """
        return node['ports'][0]['switch_name']

    @staticmethod
    def get_ip_address(device_command_output):
        """
        Get and return IP address of a device.

        The structure of input Dictionary is gathered directly from Juniper device.  # noqa: E501
        """
        return device_command_output['item']['host']

    @staticmethod
    def get_dev_neighbors_details(device_command_output):
        """
        Get and return LLDP neighbor details.

        The structure of input Dictionary is gathered directly from Juniper device.  # noqa: E501
        """
        parsed_output = device_command_output['parsed_output']
        lldp_neighbors_information = parsed_output.get('lldp-neighbors-information')  # noqa: E501
        if (not lldp_neighbors_information
                or not isinstance(lldp_neighbors_information, collections.Mapping)):  # noqa: E501
            return []

        return lldp_neighbors_information.get('lldp-neighbor-information', [])

    @staticmethod
    def get_custom_ml2_tlvs(device_neighbor_details):
        """
        Get and return LLDP neighbor custom TLVs.

        The structure of input Dictionary is gathered directly from Juniper device.  # noqa: E501
        """
        custom_tlvs = device_neighbor_details.get('lldp-org-specific-tlv', [])
        management_tlv = None
        sriov_tlv = None
        for tlv in custom_tlvs:
            oui = tlv.get('lldp-remote-oui-juniper')
            if oui != '009069':
                continue

            subtype = tlv.get('lldp-remote-subtype')
            if subtype == MANAGEMENT_TLV_SUBTYPE:
                management_tlv = tlv
            if subtype == SRIOV_TLV_SUBTYPE:
                sriov_tlv = tlv

        return management_tlv, sriov_tlv

    @staticmethod
    def get_hostname(ip_to_hostname_mapping, device_ip_address):
        """Get and return hostname."""
        return ip_to_hostname_mapping[device_ip_address]

    @staticmethod
    def decode_tlv_info(custom_tlv):
        """
        Decode Custom TLV's Info field.

        Information in custom TLV's is formatted as a string containing
        hexadecimal values of ASCII characters.
        This methods extracts the info field, converts those values
        back to ASCII characters, and returns them as a string.

        :param custom_tlv: Custom TLV dict
        :return: string
        """
        info_value = custom_tlv.get('lldp-remote-value', '')
        hex_values = [info_value[i:i+2]
                      for i in range(0, len(info_value) - 1, 2)]
        return ''.join(chr(int(hex_value, 16)) for hex_value in hex_values)

    @staticmethod
    def extract_management_ifaces_names(management_tlv):
        if not management_tlv:
            return []

        info = FilterModule.decode_tlv_info(management_tlv)
        iface_names = info.split(',')

        if len(iface_names) == 1 and iface_names[0] == TLV_INFO_NOT_SET:
            return []

        return iface_names

    @staticmethod
    def extract_sriov_mappings(sriov_tlv):
        sriov_mappings = dict()

        if not sriov_tlv:
            return sriov_mappings

        info = FilterModule.decode_tlv_info(sriov_tlv)
        kv_strings = info.split(',')

        if len(kv_strings) == 1 and kv_strings[0].lower() == TLV_INFO_NOT_SET:
            return sriov_mappings

        for kv_string in kv_strings:
            key, value = kv_string.split(':')
            sriov_mappings[key] = value

        return sriov_mappings

    def create_os_node(self,
                       vnc_api,
                       devices_command_output,
                       fabric_fq_name,
                       cc_node_obj):
        """
        Create and return list of OS Object nodes and its properties.

        Nodes are created basing on devices_command_output.
        Device that is going to be created as a node in Autodiscovery process
        must contain custom management and SR-IOV TLVs in its LLDP information.
        If the TLVs are not added, the device will be skipped.

        :param cc_node_obj: CreateCCNode object class
        :param fabric_uuid: String
        :param fabric_fq_name: List
        :param vnc_api: vnc_api class established connection:
        :param devices_command_output: Dictionary

        :return: list
            # example:
            # [
            #     {
            #         'nodes_type': 'ovs-compute',
            #         'name': u'node-1',
            #         'ports':
            #             [{
            #                 'mac_address': u'00:0c:29:13:37:bb',
            #                 'port_name': u'xe-0/0/0',
            #                 'switch_name': u'VM283DD71D00',
            #                 'name': u'ens224'
            #                 'tags': [u'physnet1']
            #             }]
            #     }
            # ]
        """
        self._logger.info(
            "Begin process of creating OS ML2 nodes object in fabric network"
        )

        nodes = []
        ip_to_hostname = self.get_mapping_ip_to_hostname(vnc_api, fabric_fq_name)
        for device_command_output in devices_command_output['results']:
            device_ip_address = FilterModule.get_ip_address(device_command_output)  # noqa: E501
            device_hostname = FilterModule.get_hostname(ip_to_hostname, device_ip_address)  # noqa: E501
            devices_neighbors_details = FilterModule.get_dev_neighbors_details(device_command_output)  # noqa: E501
            for device_neighbor_details in devices_neighbors_details:
                _, sriov_tlv = FilterModule.get_custom_ml2_tlvs(
                    device_neighbor_details
                )
                node_type = FilterModule.get_node_type(sriov_tlv)
                if node_type is None:
                    continue
                self.calculate_tags(device_neighbor_details)
                node = self.create_node_properties(
                    device_neighbor_details, node_type, device_hostname
                )
                nodes.append(node)
                switch_name = FilterModule.get_switch_name(node)
                self._logger.info(
                    "On device %s found node: %s connected to %s" % (
                        device_hostname, node, switch_name
                    ))
        created_nodes = {
            'nodes': nodes
        }
        self._logger.info("Nodes found and created: %s" % created_nodes)
        FilterModule.import_nodes_to_contrail(created_nodes, cc_node_obj)
        return created_nodes

    def create_os_ml2_node_filter(self, job_ctx, devices_command_outputs):
        """
        Param (devices_command_outputs) is a result from "show lldp neighbors detail" command.  # noqa: E501

        This param was gathered automatically in previous task, when above command was run on all
        leaf devices in fabric.

        :param devices_command_outputs: Dictionary
            # example:
            # {
            #     'msg': u'All items completed',
            #     'changed': False,
            #     'results': [
            #         {
            #             "parsed_output": {
            #                 "lldp-neighbors-information": {
            #                     "lldp-neighbor-information": [
            #                         {
            #                             (...)
            #                             "lldp-local-interface": "xe-0/0/0",
            #                             (...)
            #                             "lldp-remote-management-address": "10.5.5.5",
            #                            (...)
            #                             "lldp-remote-port-description": "ens256",
            #                             "lldp-remote-port-id": "00:0c:29:13:37:c5"
            #                         }
            #                     ]
            #                 }
            #             }
            #         }
            #     ]
            # }
        :param job_ctx: Dictionary
            # example:
            # {
            #     'job_transaction_descr': 'Discover OS Computes',
            #     'fabric_uuid': '123412341234-123412341234',
            #     'contrail_command_host': '10.10.10.10:9091',
            #     'cc_username': 'root',
            #     'cc_password': "root"
            # }
        :return: Dictionary
            # if success, returns
            # {
            #     'status': 'success'
            #     'os_compute_nodes':
            #         {
            #             'nodes':
            #             [
            #                 {
            #                     'name': 'node-1'
            #                     'node_type': 'ovs-compute',
            #                     'ports': [{
            #                         'address': '00:0c:29:13:37:c5',
            #                         'port_name': 'xe-0/0/0',
            #                         'switch_name': 'VM283DF6BA00',
            #                         'name': 'ens256'
            #                         'tags': ['physnet1']
            #                     }]
            #                 }
            #             ]
            #         }
            # }
            # if failure, returns
            # {
            #     'status': 'failure',
            #     'error_msg': <string: error message>
            # }
        """
        try:
            FilterModule._validate_job_ctx(job_ctx)
            job_input = job_ctx.get('input')
            vnc_api = JobVncApi.vnc_init(job_ctx)
            fabric_fq_name = job_input['fabric_fq_name']
            cluster_id = job_ctx.get('contrail_cluster_id')
            cluster_token = job_ctx.get('auth_token')
            cc_host = job_input['contrail_command_host']
            cc_username = job_input['cc_username']
            cc_password = job_input['cc_password']
            cc_node_obj = CreateCCNode(cc_host,
                                       cluster_id,
                                       cluster_token,
                                       cc_username,
                                       cc_password)
            os_compute_nodes = self.create_os_node(vnc_api,
                                                   devices_command_outputs,
                                                   fabric_fq_name,
                                                   cc_node_obj)
        except Exception as e:
            errmsg = "Unexpected error: %s\n%s" % (
                str(e), traceback.format_exc()
            )
            return {
                STATUS: FAILURE,
                ERRMSG: errmsg,
            }

        return {
            STATUS: SUCCESS,
            OS_COMPUTE_NODES: os_compute_nodes,
        }
