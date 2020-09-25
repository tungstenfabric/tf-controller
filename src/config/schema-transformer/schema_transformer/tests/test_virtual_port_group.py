import time

from vnc_api.vnc_api import BaremetalPortInfo
from vnc_api.vnc_api import KeyValuePair
from vnc_api.vnc_api import KeyValuePairs
from vnc_api.vnc_api import LocalLinkConnection
from vnc_api.vnc_api import ProviderDetails
from vnc_api.vnc_api import Node
from vnc_api.vnc_api import Port
from vnc_api.vnc_api import VirtualRouter
from vnc_api.vnc_api import PhysicalInterface
from vnc_api.vnc_api import PhysicalRouter
from vnc_api.vnc_api import VirtualNetwork
from vnc_api.vnc_api import VirtualMachineInterface

from .test_case import STTestCase


class TestVPG(STTestCase):
    def setUp(self, *args, **kwargs):
        super(TestVPG, self).setUp(*args, **kwargs)
        self._pre_create_physical_router()
        self._pre_create_node()
        self._pre_create_virtual_router()
        self._pre_create_virtual_networks()

    def tearDown(self):
        self._post_delete_virtual_networks()
        self._post_delete_virtual_router()
        self._post_delete_node()
        self._post_delete_physical_router()
        super(TestVPG, self).tearDown()

    @property
    def api(self):
        return self._vnc_lib

    def _pre_create_physical_router(self):
        physical_router = PhysicalRouter('physical-router')
        self.physical_router_hostname = 'physical-router-hostname'
        physical_router.set_physical_router_hostname(
            self.physical_router_hostname)
        physical_router_uuid = self.api.physical_router_create(physical_router)
        self.physical_router = \
            self.api.physical_router_read(id=physical_router_uuid)
        # create physical_interface_red
        physical_interface_red = \
            PhysicalInterface(
                'physical-interface-red',
                parent_obj=self.physical_router)
        self.physical_interface_red_port_id = 'physical-interface-red-port-id'
        physical_interface_red.set_physical_interface_port_id(
            self.physical_interface_red_port_id)
        physical_interface_red_uuid = \
            self.api.physical_interface_create(physical_interface_red)
        self.physical_interface_red = \
            self.api.physical_interface_read(id=physical_interface_red_uuid)
        # create physical_interface_green
        physical_interface_green = PhysicalInterface(
            'physical-interface-green', parent_obj=self.physical_router)
        self.physical_interface_green_port_id = \
            'physical-interface-green-port-id'
        physical_interface_green.set_physical_interface_port_id(
            self.physical_interface_green_port_id)
        physical_interface_green_uuid = \
            self.api.physical_interface_create(physical_interface_green)
        self.physical_interface_green = \
            self.api.physical_interface_read(id=physical_interface_green_uuid)

    def _post_delete_physical_router(self):
        self.api.physical_interface_delete(
            id=self.physical_interface_red.uuid)
        self.api.physical_interface_delete(
            id=self.physical_interface_green.uuid)
        self.api.physical_router_delete(
            id=self.physical_router.uuid)

    def _pre_create_node(self):
        # create node_red
        self.node_red_hostname = 'node-red-hostname'
        node_red = Node('node-red', node_hostname=self.node_red_hostname)
        node_red_uuid = self.api.node_create(node_red)
        self.node_red = self.api.node_read(id=node_red_uuid)
        # create port_red
        local_link_connection = LocalLinkConnection(
            switch_id=self.physical_router_hostname,
            port_id=self.physical_interface_red_port_id)
        bm_info = BaremetalPortInfo(
            local_link_connection=local_link_connection)
        port_red = Port('port-red', node_red, bms_port_info=bm_info)
        self.port_red_display_name = 'port-red'
        port_red.set_display_name(self.port_red_display_name)
        port_red_uuid = self.api.port_create(port_red)
        self.port_red = self.api.port_read(id=port_red_uuid)
        # create node_green
        self.node_green_hostname = 'node-green-hostname'
        node_green = Node('node-green', node_hostname=self.node_green_hostname)
        node_green_uuid = self.api.node_create(node_green)
        self.node_green = self.api.node_read(id=node_green_uuid)
        # create port_green
        local_link_connection = LocalLinkConnection(
            switch_id=self.physical_router_hostname,
            port_id=self.physical_interface_green_port_id)
        bm_info = BaremetalPortInfo(
            local_link_connection=local_link_connection)
        port_green = Port('port-green', node_green, bms_port_info=bm_info)
        self.port_green_display_name = 'port-green'
        port_green.set_display_name(self.port_green_display_name)
        port_green_uuid = self.api.port_create(port_green)
        self.port_green = self.api.port_read(id=port_green_uuid)

    def _post_delete_node(self):
        self.api.port_delete(id=self.port_red.uuid)
        self.api.node_delete(ud=self.node_red.uuid)
        self.api.port_delete(id=self.port_green.uuid)
        self.api.node_delete(ud=self.node_green.uuid)

    def _pre_create_virtual_router(self):
        # create virtual_router_red
        virtual_router_red = VirtualRouter('virtual-router-red')
        virtual_router_red.set_display_name(self.node_red_hostname)
        self.physnet = "physnet-red"
        virtual_router_red.set_virtual_router_sriov_physical_networks(
            KeyValuePair(key=self.physnet, value=self.port_red_display_name))
        virtual_router_red_uuid = \
            self.api.virtual_router_create(virtual_router_red)
        self.virtual_router_red = \
            self.api.virtual_router_read(id=virtual_router_red_uuid)
        # create virtual_router_green
        virtual_router_green = VirtualRouter('virtual-router-green')
        virtual_router_green.set_display_name(self.node_green_hostname)
        virtual_router_green.set_virtual_router_sriov_physical_networks(
            KeyValuePair(key=self.physnet, value=self.port_green_display_name))
        virtual_router_green_uuid = \
            self.api.virtual_router_create(virtual_router_green)
        self.virtual_router_green = \
            self.api.virtual_router_read(id=virtual_router_green_uuid)

    def _post_delete_virtual_router(self):
        self.api.virtual_router_delete(id=self.virtual_router_green.uuid)
        self.api.virtual_router_delete(id=self.virtual_router_red.uuid)

    def _pre_create_virtual_networks(self):
        # red ang green VN are the provider VNs
        virtual_network_red = VirtualNetwork('virtual-network-red')
        self.vlan_id_red = 100
        virtual_network_red.set_provider_properties(
            ProviderDetails(
                segmentation_id=self.vlan_id_red,
                physical_network=self.physnet))
        virtual_network_red_uuid = \
            self.api.virtual_network_create(virtual_network_red)
        self.virtual_network_red = \
            self.api.virtual_network_read(id=virtual_network_red_uuid)
        virtual_network_green = VirtualNetwork('virtual-network-green')
        self.vlan_id_green = 200
        virtual_network_green.set_provider_properties(
            ProviderDetails(
                segmentation_id=self.vlan_id_green,
                physical_network=self.physnet))
        virtual_network_green_uuid = \
            self.api.virtual_network_create(virtual_network_green)
        self.virtual_network_green = \
            self.api.virtual_network_read(id=virtual_network_green_uuid)
        # blue VN is the non-provider VN
        virtual_network_blue = VirtualNetwork('virtual-network-blue')
        virtual_network_blue_uuid = \
            self.api.virtual_network_create(virtual_network_blue)
        self.virtual_network_blue = \
            self.api.virtual_network_read(id=virtual_network_blue_uuid)

    def _post_delete_virtual_networks(self):
        self.api.virtual_network_delete(id=self.virtual_network_red.uuid)
        self.api.virtual_network_delete(id=self.virtual_network_green.uuid)

    def _vpg_exists(self, vlan_id, physical_interface_port_id):
        vpgs = self.api.virtual_port_group_list()
        for vpg in vpgs:
            for vmi in vpg.get_virtual_machine_interface_refs():
                vmi_bindings = vmi.get_virtual_machine_interface_bindings()
                if vmi_bindings:
                    for kvp in vmi_bindings.get_key_value_pair():
                        if kvp.key == 'vlan_id' and kvp.value == vlan_id:
                            for pi, _ in vpg.get_physical_interface_refs():
                                if pi.get_display_name() == \
                                        physical_interface_port_id:
                                    return True
        return False

    def test_create_vmi(self):
        vmi = VirtualMachineInterface('tvirtual-machine-interface')
        vmi.set_virtual_network(self.virtual_network_red)
        vmi.set_virtual_machine_interface_bindings(
            KeyValuePairs(
                key_value_pair=[KeyValuePair(key='vnic_type', value='direct'),
                                KeyValuePair(
                                    key='hostname',
                                    value=self.node_red_hostname)]))
        self.api.virtual_machine_interface_create(vmi)
        time.sleep(5)
        self.assertTrue(
            self._vpg_exists(
                self.vlan_id_red,
                self.physical_interface_red_port_id))
    # end test_create_vmi

    def test_create_vmi_and_delete(self):
        vmi = VirtualMachineInterface('tvirtual-machine-interface-red')
        vmi.set_virtual_network(self.virtual_network_red)
        vmi.set_virtual_machine_interface_bindings(
            KeyValuePairs(
                key_value_pair=[KeyValuePair(key='vnic_type', value='direct'),
                                KeyValuePair(
                                    key='hostname',
                                    value=self.node_red_hostname)]))
        vmi_uuid = self.api.virtual_machine_interface_create(vmi)
        time.sleep(5)
        self.assertTrue(
            self._vpg_exists(
                self.vlan_id_red,
                self.physical_interface_red_port_id))
        self.api.virtual_machine_interface_delete(id=vmi_uuid)
        time.sleep(5)
        self.assertFalse(
            self._vpg_exists(
                self.vlan_id_red,
                self.physical_interface_red_port_id))
    # end test_create_vmi

    def test_update_vmi_host(self):
        vmi = VirtualMachineInterface('tvirtual-machine-interface')
        vmi.set_virtual_network(self.virtual_network_red)
        vmi.set_virtual_machine_interface_bindings(
            KeyValuePairs(
                key_value_pair=[KeyValuePair(key='vnic_type', value='direct'),
                                KeyValuePair(
                                    key='hostname',
                                    value=self.node_red_hostname)]))
        vmi_uuid = self.api.virtual_machine_interface_create(vmi)
        time.sleep(5)
        self.assertTrue(
            self._vpg_exists(
                self.vlan_id_red,
                self.physical_interface_red_port_id))
        # update host
        vmi = self.api.virtual_machine_interface_read(id=vmi_uuid)
        vmi.set_virtual_machine_interface_bindings(
            KeyValuePairs(
                key_value_pair=[KeyValuePair(key='vnic_type', value='direct'),
                                KeyValuePair(
                                    key='hostname',
                                    value=self.node_green_hostname)]))
        self.api.virtual_machine_interface_update(vmi)
        time.sleep(5)
        self.assertFalse(
            self._vpg_exists(
                self.vlan_id_red,
                self.physical_interface_red_port_id))
        self.assertTrue(
            self._vpg_exists(
                self.vlan_id_red,
                self.physical_interface_green_port_id))
    # end test_update_vmi_host

    def test_update_vmi_vn(self):
        vmi = VirtualMachineInterface('tvirtual-machine-interface')
        vmi.set_virtual_network(self.virtual_network_red)
        vmi.set_virtual_machine_interface_bindings(
            KeyValuePairs(
                key_value_pair=[KeyValuePair(key='vnic_type', value='direct'),
                                KeyValuePair(
                                    key='hostname',
                                    value=self.node_red_hostname)]))
        vmi_uuid = self.api.virtual_machine_interface_create(vmi)
        time.sleep(5)
        self.assertTrue(
            self._vpg_exists(
                self.vlan_id_red,
                self.physical_interface_red_port_id))
        # update vn
        vmi = self.api.virtual_machine_interface_read(id=vmi_uuid)
        vmi.set_virtual_network(self.virtual_network_green)
        self.api.virtual_machine_interface_update(vmi)
        time.sleep(5)
        self.assertFalse(
            self._vpg_exists(
                self.vlan_id_red,
                self.physical_interface_red_port_id))
        self.assertTrue(
            self._vpg_exists(
                self.vlan_id_red,
                self.physical_interface_green_port_id))
    # end test_update_vmi_vn

    def test_update_vn_to_provider_network(self):
        vmi = VirtualMachineInterface('tvirtual-machine-interface')
        vmi.set_virtual_network(self.virtual_network_blue)
        vmi.set_virtual_machine_interface_bindings(
            KeyValuePairs(
                key_value_pair=[KeyValuePair(key='vnic_type', value='direct'),
                                KeyValuePair(
                                    key='hostname',
                                    value=self.node_red_hostname)]))
        self.api.virtual_machine_interface_create(vmi)
        time.sleep(5)
        self.virtual_network_blue.set_provider_properties(
            ProviderDetails(
                segmentation_id=self.vlan_id_red,
                physical_network=self.physnet))
        time.sleep(5)
        self.assertTrue(
            self._vpg_exists(
                self.vlan_id_red,
                self.physical_interface_red_port_id))
    # end test_update_vn_to_provider_network

# end TestVPG
