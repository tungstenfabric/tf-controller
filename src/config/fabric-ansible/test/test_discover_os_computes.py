#
# Copyright (c) 2020 Juniper Networks, Inc. All rights reserved.
#
import copy
import logging
import sys
try:
    from unittest.mock import MagicMock
except ImportError:
    from mock import MagicMock
from vnc_cfg_api_server.tests import test_case

sys.path.append('/opt/contrail/fabric_ansible_playbooks/filter_plugins')
sys.path.append('/opt/contrail/fabric_ansible_playbooks/common')
sys.path.append('../fabric-ansible/ansible-playbooks/module_utils')
sys.modules['import_server'] = MagicMock()
sys.modules['contrail_command'] = MagicMock()
from discover_os_computes import FilterModule


logger = logging.getLogger(__name__)


class TestDiscoverOsComputes(test_case.ApiServerTestCase):
    DEVICE_NEIGHBOR_FULL_DETAILS = {
        u'lldp-remote-chassis-id': u'00:0c:29:8b:ef:1c',
        u'lldp-remote-management-address': u'10.7.64.124',
        u'lldp-remote-system-capabilities-enabled': u'Bridge Router',
        u'lldp-local-parent-interface-name': u'ae3',
        u'lldp-remote-management-addr-oid': u'', u'lldp-remote-system-name': u'node-4',
        u'lldp-remote-chassis-id-subtype': u'Mac address',
        u'lldp-remote-system-capabilities-supported': u'Bridge WLAN Access Point '
                                                      u'Router Station Only',
        u'lldp-index': u'1', u'lldp-remote-port-id-subtype': u'Mac address',
        u'lldp-timemark': u'Sun May 24 21:35:11 2020',
        u'lldp-remote-management-address-type': u'IPv4(1)',
        u'lldp-remote-management-address-interface-subtype': u'ifIndex(2)',
        u'lldp-local-port-id': u'522',
        u'lldp-org-specific-tlv': [
            {
                u'lldp-remote-index': u'1',
                u'lldp-remote-oui-juniper': u'009069',
                u'lldp-remote-subtype': u'(123)',
                u'lldp-remote-value': u'656E73323234',
            },
            {
                u'lldp-remote-index': u'2',
                u'lldp-remote-oui-juniper': u'009069',
                u'lldp-remote-subtype': u'(124)',
                u'lldp-remote-value': u'656E733139323A706879736E657431',
            }
        ],
        u'lldp-system-description': {
            u'lldp-remote-system-description': u'node_type: OVS CentOS Linux 7 (Core)'},
        u'lldp-ttl': u'120', u'lldp-local-port-ageout-count': u'0',
        u'lldp-local-interface': u'xe-0/0/3',
        u'lldp-remote-management-address-port-id': u'2',
        u'lldp-remote-port-description': u'ens224', u'lldp-age': u'10',
        u'lldp-remote-port-id': u'00:0c:29:8b:ef:26'
    }

    @classmethod
    def setUpClass(cls, *args, **kwargs):
        cls.cli_filter = FilterModule
        cls.console_handler = logging.StreamHandler()
        cls.console_handler.setLevel(logging.DEBUG)
        logger.addHandler(cls.console_handler)
        super(TestDiscoverOsComputes, cls).setUpClass(*args, **kwargs)

    @classmethod
    def tearDownClass(cls, *args, **kwargs):
        logger.removeHandler(cls.console_handler)
        super(TestDiscoverOsComputes, cls).tearDownClass(*args, **kwargs)

    def test_get_custom_ml2_tlvs(self):
        expected_mgmt_tlv = {
            u'lldp-remote-index': u'1',
            u'lldp-remote-oui-juniper': u'009069',
            u'lldp-remote-subtype': u'(123)',
            u'lldp-remote-value': u'656E73323234',
        }
        expected_sriov_tlv = {
            u'lldp-remote-index': u'2',
            u'lldp-remote-oui-juniper': u'009069',
            u'lldp-remote-subtype': u'(124)',
            u'lldp-remote-value': u'656E733139323A706879736E657431',
        }

        mgmt_tlv, sriov_tlv = self.cli_filter.get_custom_ml2_tlvs(self.DEVICE_NEIGHBOR_FULL_DETAILS)

        self.assertEqual(mgmt_tlv, expected_mgmt_tlv)
        self.assertEqual(sriov_tlv, expected_sriov_tlv)

    def test_decode_tlv_info(self):
        custom_tlv = {
            u'lldp-remote-index': u'1',
            u'lldp-remote-oui-juniper': u'009069',
            u'lldp-remote-subtype': u'(123)',
            u'lldp-remote-value': u'656E73323234',
        }

        result = self.cli_filter.decode_tlv_info(custom_tlv)

        self.assertEqual(result, 'ens224')

    def test_calculate_tags(self):
        filter_module = FilterModule()

        expected_tags = {
            'node-4': {
                'ens192': ['physnet1'],
                'ens224': ['management'],
            },
        }

        filter_module.calculate_tags(self.DEVICE_NEIGHBOR_FULL_DETAILS)

        self.assertEqual(filter_module.tags, expected_tags)

    def generate_test_node_type_general(self, description, expected):
        node_type = self.cli_filter.get_node_type(description)
        self.assertEqual(expected, node_type)

    def test_get_node_type_ovs(self):
        sriov_tlv = {
            u'lldp-remote-index': u'2',
            u'lldp-remote-oui-juniper': u'009069',
            u'lldp-remote-subtype': u'(124)',
            u'lldp-remote-value': u'4E6F6E65',
        }
        expected = "ovs-compute"
        self.generate_test_node_type_general(sriov_tlv, expected)

    def test_get_node_type_sriov(self):
        sriov_tlv = {
            u'lldp-remote-index': u'2',
            u'lldp-remote-oui-juniper': u'009069',
            u'lldp-remote-subtype': u'(124)',
            u'lldp-remote-value': u'656E733139323A706879736E657431',
        }
        expected = "sriov-compute"
        self.generate_test_node_type_general(sriov_tlv, expected)

    def test_get_node_type_none(self):
        sriov_tlv = None
        expected = None
        self.generate_test_node_type_general(sriov_tlv, expected)

    def test_extract_management_ifaces_names(self):
        management_tlv = {
            u'lldp-remote-index': u'1',
            u'lldp-remote-oui-juniper': u'009069',
            u'lldp-remote-subtype': u'(123)',
            u'lldp-remote-value': u'656E733139322C656E73323234',
        }

        result = self.cli_filter.extract_management_ifaces_names(management_tlv)

        self.assertEqual(result, ['ens192', 'ens224'])

    def test_extract_no_management_ifaces_names(self):
        management_tlv = {
            u'lldp-remote-index': u'1',
            u'lldp-remote-oui-juniper': u'009069',
            u'lldp-remote-subtype': u'(123)',
            u'lldp-remote-value': u'6E6F6E65',
        }

        result = self.cli_filter.extract_management_ifaces_names(management_tlv)

        self.assertEqual(result, [])

    def test_extract_sriov_mappings(self):
        sriov_tlv = {
            u'lldp-remote-index': u'2',
            u'lldp-remote-oui-juniper': u'009069',
            u'lldp-remote-subtype': u'(124)',
            u'lldp-remote-value': u'656E733139323A706879736E6574312C656E733232343A706879736E657432',
        }
        expected = {'ens192': 'physnet1', 'ens224': 'physnet2'}

        result = self.cli_filter.extract_sriov_mappings(sriov_tlv)

        self.assertEqual(result, expected)

    def test_extract_no_sriov_mappings(self):
        sriov_tlv = {
            u'lldp-remote-index': u'2',
            u'lldp-remote-oui-juniper': u'009069',
            u'lldp-remote-subtype': u'(124)',
            u'lldp-remote-value': u'6E6F6E65',
        }

        result = self.cli_filter.extract_sriov_mappings(sriov_tlv)

        self.assertEqual(result, {})

    def generate_test_create_node_properties(self, device_neighbor_data, node_type, device_display_name,
                                             expected_output):
        filter_module = self.cli_filter()
        filter_module.calculate_tags(device_neighbor_data)
        node_properties = filter_module.create_node_properties(device_neighbor_data, node_type, device_display_name)
        self.assertDictEqual(expected_output, node_properties)

    def test_create_node_properties_with_full_input_mgmt(self):
        node_type = 'sriov-compute'
        device_display_name = 'Router_1'
        expected_output = {'node_type': 'sriov-compute', 'name': 'node-4', 'ports': [
            {'mac_address': '00:0c:29:8b:ef:26', 'port_name': 'xe-0/0/3', 'switch_name': 'Router_1',
             'name': 'ens224', 'tags': ['management']}]}

        self.generate_test_create_node_properties(self.DEVICE_NEIGHBOR_FULL_DETAILS, node_type, device_display_name,
                                                  expected_output)

    def test_create_node_properties_with_full_input_sriov(self):
        test_input = copy.deepcopy(self.DEVICE_NEIGHBOR_FULL_DETAILS)
        test_input['lldp-remote-port-description'] = 'ens192'
        node_type = 'sriov-compute'
        device_display_name = 'Router_1'
        expected_output = {'node_type': 'sriov-compute', 'name': 'node-4', 'ports': [
            {'mac_address': '00:0c:29:8b:ef:26', 'port_name': 'xe-0/0/3', 'switch_name': 'Router_1',
             'name': 'ens192', 'tags': ['physnet1']}]}

        self.generate_test_create_node_properties(test_input, node_type, device_display_name,
                                                  expected_output)

    def test_create_node_properties_with_full_input_no_tags(self):
        test_input = copy.deepcopy(self.DEVICE_NEIGHBOR_FULL_DETAILS)
        test_input['lldp-org-specific-tlv'][0]['lldp-remote-value'] = '6E6F6E65'
        test_input['lldp-org-specific-tlv'][1]['lldp-remote-value'] = '6E6F6E65'

        node_type = 'ovs-compute'
        device_display_name = 'Router_1'
        expected_output = {'node_type': 'ovs-compute', 'name': 'node-4', 'ports': [
            {'mac_address': '00:0c:29:8b:ef:26', 'port_name': 'xe-0/0/3', 'switch_name': 'Router_1',
             'name': 'ens224', 'tags': []}]}

        self.generate_test_create_node_properties(test_input, node_type, device_display_name,
                                                  expected_output)

    def test_create_node_properties_missing_one_value(self):
        device_neighbor_details_without_port_desc = {
            u'lldp-remote-system-name': u'node-4',
            u'lldp-local-interface': u'xe-0/0/3',
            u'lldp-remote-port-description': u'',
            u'lldp-remote-port-id': u'00:0c:29:8b:ef:26'}
        node_type = 'ovs-compute'
        device_display_name = 'Router_1'
        expected_output = {'node_type': 'ovs-compute', 'name': 'node-4', 'ports': [
            {'mac_address': '00:0c:29:8b:ef:26', 'port_name': 'xe-0/0/3', 'switch_name': 'Router_1',
             'name': '', 'tags': []}]}
        self.generate_test_create_node_properties(device_neighbor_details_without_port_desc, node_type,
                                                  device_display_name, expected_output)
