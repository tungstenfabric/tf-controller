from cfgm_common.exceptions import NoIdError
from vnc_api.vnc_api import BaremetalPortInfo
from vnc_api.vnc_api import Fabric
from vnc_api.vnc_api import KeyValuePair
from vnc_api.vnc_api import KeyValuePairs
from vnc_api.vnc_api import LocalLinkConnection
from vnc_api.vnc_api import Node
from vnc_api.vnc_api import PhysicalInterface
from vnc_api.vnc_api import PhysicalRouter
from vnc_api.vnc_api import Port
from vnc_api.vnc_api import Project
from vnc_api.vnc_api import ProviderDetails
from vnc_api.vnc_api import VirtualMachine
from vnc_api.vnc_api import VirtualMachineInterface
from vnc_api.vnc_api import VirtualNetwork
from vnc_api.vnc_api import VirtualRouter

from .test_case import retries, STTestCase, VerifyCommon


class VerifyVPG(VerifyCommon):
    @retries(5)
    def check_vpg_exists(self, vlan_id, physical_interface_uuid):
        vpg_uuids = self.get_uuids(
            self._vnc_lib.virtual_port_groups_list(
                fields=['uuid']))
        for vpg_uuid in vpg_uuids:
            try:
                vpg = self._vnc_lib.virtual_port_group_read(
                    id=vpg_uuid)
            except NoIdError:
                continue
            for vmi_uuid in self.get_uuids(
                    vpg.get_virtual_machine_interface_refs()):
                try:
                    vmi = self._vnc_lib \
                              .virtual_machine_interface_read(id=vmi_uuid)
                except NoIdError:
                    continue
                vmi_properties = vmi.get_virtual_machine_interface_properties()
                if vmi_properties:
                    if vmi_properties.get_sub_interface_vlan_tag() == vlan_id:
                        pi_uuids = self.get_uuids(
                            vpg.get_physical_interface_refs()
                        )
                        if physical_interface_uuid in pi_uuids:
                            return
        raise Exception(
            "virtual_port_group with vlan_id %s, "
            "and physical_interface with id %s not found"
            % (vlan_id, physical_interface_uuid))
    # end check_vpg_exists

    @retries(5)
    def check_vpg_not_exist(self, vlan_id, physical_interface_uuid):
        vpg_uuids = self.get_uuids(
            self._vnc_lib.virtual_port_groups_list(
                fields=['uuid']))
        for vpg_uuid in vpg_uuids:
            try:
                vpg = self._vnc_lib.virtual_port_group_read(
                    id=vpg_uuid)
            except NoIdError:
                continue
            for vmi_uuid in self.get_uuids(
                    vpg.get_virtual_machine_interface_refs()):
                try:
                    vmi = self._vnc_lib \
                              .virtual_machine_interface_read(id=vmi_uuid)
                except NoIdError:
                    continue
                vmi_properties = vmi.get_virtual_machine_interface_properties()
                if vmi_properties:
                    if vmi_properties.get_sub_interface_vlan_tag() == vlan_id:
                        pi_uuids = self.get_uuids(
                            vpg.get_physical_interface_refs()
                        )
                        if physical_interface_uuid in pi_uuids:
                            raise Exception(
                                "virtual_port_group with vlan_id %s, "
                                "and physical_interface with id "
                                "%s found"
                                % (vlan_id,
                                    physical_interface_uuid))
        return
    # end check_vpg_not_exist

    def get_uuids(self, items):
        if items is None:
            return []
        if isinstance(items, list):
            return [item['uuid'] for item in items]
        if isinstance(items, dict) and len(items.keys()) > 0:
            return [item['uuid'] for item in
                    items.get(list(items.keys())[0], [])]
    # end get_uuids

# end VerifyVPG


class TestVPG(STTestCase, VerifyVPG):
    def setUp(self, *args, **kwargs):
        super(TestVPG, self).setUp(*args, **kwargs)
        self._pre_create_fabric()
        self._pre_create_physical_router()
        self._pre_create_node()
        self._pre_create_virtual_router()
        self._pre_create_project()
        self._pre_create_virtual_networks()
        self._pre_create_virtual_machine()

    def tearDown(self):
        self._post_delete_virtual_port_groups()
        self._post_delete_virtual_machine_interfaces()
        self._post_delete_virtual_machine()
        self._post_delete_virtual_networks()
        self._post_delete_project()
        self._post_delete_virtual_router()
        self._post_delete_node()
        self._post_delete_physical_router()
        self._post_delete_fabric()
        super(TestVPG, self).tearDown()

    @property
    def api(self):
        return self._vnc_lib

    def _pre_create_fabric(self):
        fabric = Fabric(name="test-fabric")
        fabric_uuid = self.api.fabric_create(fabric)
        self.fabric = self.api.fabric_read(id=fabric_uuid)

    def _post_delete_fabric(self):
        self.api.fabric_delete(id=self.fabric.uuid)

    def _pre_create_physical_router(self):
        physical_router = PhysicalRouter(name='test-physical-router')
        self.physical_router_hostname = 'test-physical-router-hostname'
        physical_router.set_fabric(self.fabric)
        physical_router.set_physical_router_hostname(
            self.physical_router_hostname)
        physical_router_uuid = self.api.physical_router_create(physical_router)
        self.physical_router = \
            self.api.physical_router_read(id=physical_router_uuid)
        # create physical_interface_red
        physical_interface_red = PhysicalInterface(
            name='test-physical-interface-red',
            parent_obj=self.physical_router)
        self.physical_interface_red_port_id = \
            'test-physical-interface-red-port-id'
        physical_interface_red.set_display_name(
            self.physical_interface_red_port_id)
        physical_interface_red_uuid = \
            self.api.physical_interface_create(physical_interface_red)
        self.physical_interface_red = \
            self.api.physical_interface_read(id=physical_interface_red_uuid)
        # create physical_interface_green
        physical_interface_green = PhysicalInterface(
            name='test-physical-interface-green',
            parent_obj=self.physical_router)
        self.physical_interface_green_port_id = \
            'test-physical-interface-green-port-id'
        physical_interface_green.set_display_name(
            self.physical_interface_green_port_id)
        physical_interface_green_uuid = \
            self.api.physical_interface_create(physical_interface_green)
        self.physical_interface_green = \
            self.api.physical_interface_read(id=physical_interface_green_uuid)
        # create channelized physical_router_blue
        physical_interface_blue = PhysicalInterface(
            name='test-physical-interface-blue',
            parent_obj=self.physical_router)
        self.physical_interface_blue_port_id = \
            'test-physical-interface-blue-port-id_1'
        physical_interface_blue.set_display_name(
            self.physical_interface_blue_port_id.replace("_", ":"))
        physical_interface_blue_uuid = \
            self.api.physical_interface_create(physical_interface_blue)
        self.physical_interface_blue = \
            self.api.physical_interface_read(id=physical_interface_blue_uuid)

    def _post_delete_physical_router(self):
        self.api.physical_interface_delete(
            id=self.physical_interface_red.uuid)
        self.api.physical_interface_delete(
            id=self.physical_interface_green.uuid)
        self.api.physical_interface_delete(
            id=self.physical_interface_blue.uuid)
        self.api.physical_router_delete(
            id=self.physical_router.uuid)

    def _pre_create_node(self):
        # create node_red
        self.node_red_hostname = 'test-node-red-hostname'
        node_red = Node(name='test-node-red')
        node_red.set_hostname(self.node_red_hostname)
        node_red_uuid = self.api.node_create(node_red)
        self.node_red = self.api.node_read(id=node_red_uuid)
        # create port_red
        local_link_connection = LocalLinkConnection(
            switch_info=self.physical_router_hostname,
            port_id=self.physical_interface_red_port_id)
        bm_info = BaremetalPortInfo(
            local_link_connection=local_link_connection)
        port_red = Port(
            name='test-port-red', parent_obj=node_red, bms_port_info=bm_info)
        self.port_red_display_name = 'test-port-red'
        port_red.set_display_name(self.port_red_display_name)
        port_red_uuid = self.api.port_create(port_red)
        self.port_red = self.api.port_read(id=port_red_uuid)
        # create node_green
        self.node_green_hostname = 'test-node-green-hostname'
        node_green = Node(name='test-node-green')
        node_green.set_hostname(self.node_green_hostname)
        node_green_uuid = self.api.node_create(node_green)
        self.node_green = self.api.node_read(id=node_green_uuid)
        # create port_green
        local_link_connection = LocalLinkConnection(
            switch_info=self.physical_router_hostname,
            port_id=self.physical_interface_green_port_id)
        bm_info = BaremetalPortInfo(
            local_link_connection=local_link_connection)
        port_green = Port(
            name='test-port-green',
            parent_obj=node_green,
            bms_port_info=bm_info)
        self.port_green_display_name = 'test-port-green'
        port_green.set_display_name(self.port_green_display_name)
        port_green_uuid = self.api.port_create(port_green)
        self.port_green = self.api.port_read(id=port_green_uuid)
        # create node_blue
        self.node_blue_hostname = 'test-node-blue-hostname'
        node_blue = Node(name='test-node-blue')
        node_blue.set_hostname(self.node_blue_hostname)
        node_blue_uuid = self.api.node_create(node_blue)
        self.node_blue = self.api.node_read(id=node_blue_uuid)
        # create port_blue
        local_link_connection = LocalLinkConnection(
            switch_info=self.physical_router_hostname,
            port_id=self.physical_interface_blue_port_id)
        bm_info = BaremetalPortInfo(
            local_link_connection=local_link_connection)
        port_blue = Port(
            name='test-port-blue',
            parent_obj=node_blue,
            bms_port_info=bm_info)
        self.port_blue_display_name = 'test-port-blue'
        port_blue.set_display_name(self.port_blue_display_name)
        port_blue_uuid = self.api.port_create(port_blue)
        self.port_blue = self.api.port_read(id=port_blue_uuid)

    def _post_delete_node(self):
        self.api.port_delete(id=self.port_red.uuid)
        self.api.node_delete(id=self.node_red.uuid)
        self.api.port_delete(id=self.port_green.uuid)
        self.api.node_delete(id=self.node_green.uuid)
        self.api.port_delete(id=self.port_blue.uuid)
        self.api.node_delete(id=self.node_blue.uuid)

    def _pre_create_virtual_router(self):
        # create virtual_router_red
        virtual_router_red = VirtualRouter(name='test-virtual-router-red')
        virtual_router_red.set_display_name(self.node_red_hostname)
        self.physnet = "test-physnet-red"
        virtual_router_red.set_virtual_router_sriov_physical_networks(
            KeyValuePairs(
                key_value_pair=[
                    KeyValuePair(
                        key=self.physnet,
                        value=self.port_red_display_name)]))
        virtual_router_red_uuid = \
            self.api.virtual_router_create(virtual_router_red)
        self.virtual_router_red = \
            self.api.virtual_router_read(id=virtual_router_red_uuid)
        # create virtual_router_blue
        virtual_router_blue = VirtualRouter(name='test-virtual-router-blue')
        virtual_router_blue.set_display_name(self.node_blue_hostname)
        virtual_router_blue.set_virtual_router_sriov_physical_networks(
            KeyValuePairs(
                key_value_pair=[
                    KeyValuePair(
                        key=self.physnet,
                        value=self.port_blue_display_name)]))
        virtual_router_blue_uuid = \
            self.api.virtual_router_create(virtual_router_blue)
        self.virtual_router_blue = \
            self.api.virtual_router_read(id=virtual_router_blue_uuid)
        # create virtual_router_green
        virtual_router_green = VirtualRouter(name='test-virtual-router-green')
        virtual_router_green.set_display_name(self.node_green_hostname)
        virtual_router_green.set_virtual_router_sriov_physical_networks(
            KeyValuePairs(
                key_value_pair=[
                    KeyValuePair(
                        key=self.physnet,
                        value=self.port_green_display_name)]))
        virtual_router_green_uuid = \
            self.api.virtual_router_create(virtual_router_green)
        self.virtual_router_green = \
            self.api.virtual_router_read(id=virtual_router_green_uuid)

    def _post_delete_virtual_router(self):
        self.api.virtual_router_delete(id=self.virtual_router_green.uuid)
        self.api.virtual_router_delete(id=self.virtual_router_red.uuid)
        self.api.virtual_router_delete(id=self.virtual_router_blue.uuid)

    def _pre_create_project(self):
        project_uuid = self.api.project_create(
            Project(name='test-project'))
        self.project = self.api.project_read(id=project_uuid)

    def _post_delete_project(self):
        self.api.project_delete(id=self.project.uuid)

    def _pre_create_virtual_networks(self):
        # create red VN
        virtual_network_red = VirtualNetwork(
            name='test-virtual-network-red',
            parent_obj=self.project)
        self.vlan_id_red = 100
        virtual_network_red.set_is_provider_network(True)
        virtual_network_red.set_provider_properties(
            ProviderDetails(
                segmentation_id=self.vlan_id_red,
                physical_network=self.physnet))
        virtual_network_red_uuid = \
            self.api.virtual_network_create(virtual_network_red)
        self.virtual_network_red = \
            self.api.virtual_network_read(id=virtual_network_red_uuid)
        # create green VN
        virtual_network_green = VirtualNetwork(
            name='test-virtual-network-green',
            parent_obj=self.project)
        self.vlan_id_green = 200
        virtual_network_green.set_is_provider_network(True)
        virtual_network_green.set_provider_properties(
            ProviderDetails(
                segmentation_id=self.vlan_id_green,
                physical_network=self.physnet))
        virtual_network_green_uuid = \
            self.api.virtual_network_create(virtual_network_green)
        self.virtual_network_green = \
            self.api.virtual_network_read(id=virtual_network_green_uuid)
        # create blue VN
        virtual_network_blue = VirtualNetwork(
            name='test-virtual-network-blue',
            parent_obj=self.project)
        self.vlan_id_blue = 300
        virtual_network_blue.set_is_provider_network(True)
        virtual_network_blue.set_provider_properties(
            ProviderDetails(
                segmentation_id=self.vlan_id_blue,
                physical_network=self.physnet))
        virtual_network_blue_uuid = \
            self.api.virtual_network_create(virtual_network_blue)
        self.virtual_network_blue = \
            self.api.virtual_network_read(id=virtual_network_blue_uuid)

    def _post_delete_virtual_networks(self):
        self.api.virtual_network_delete(id=self.virtual_network_red.uuid)
        self.api.virtual_network_delete(id=self.virtual_network_green.uuid)
        self.api.virtual_network_delete(id=self.virtual_network_blue.uuid)

    def _pre_create_virtual_machine(self):
        virtual_machine = VirtualMachine(
            name='test-virtual-machine',
            parent_obj=self.project
        )
        virtual_machine_uuid = \
            self.api.virtual_machine_create(virtual_machine)
        self.virtual_machine = \
            self.api.virtual_machine_read(id=virtual_machine_uuid)

    def _post_delete_virtual_machine(self):
        self.api.virtual_machine_delete(id=self.virtual_machine.uuid)

    def _post_delete_virtual_port_groups(self):
        vpg_uuids = self.get_uuids(
            self.api.virtual_port_groups_list(
                fields=['uuid']))
        for vpg_uuid in vpg_uuids:
            try:
                vpg = self.api.virtual_port_group_read(
                    id=vpg_uuid)
                for vmi_uuid in self.get_uuids(
                        vpg.get_virtual_machine_interface_refs()):
                    self.api.ref_update(
                        'virtual-port-group', vpg_uuid,
                        'virtual-machine-interface', vmi_uuid, None, 'DELETE')
                self.api.virtual_port_group_delete(id=vpg_uuid)
            except NoIdError:
                continue
    # end _post_delete_virtual_port_groups

    def _post_delete_virtual_machine_interfaces(self):
        vmi_uuids = self.get_uuids(
            self.api.virtual_machine_interfaces_list(
                fields=['uuid']))
        for vmi_uuid in vmi_uuids:
            try:
                self.api.virtual_machine_interface_delete(id=vmi_uuid)
            except NoIdError:
                pass
    # end _post_delete_virtual_machine_interface

    def test_create_vmi(self):
        vmi = VirtualMachineInterface(
            name='test-virtual-machine-interface',
            parent_obj=self.project)
        vmi.set_virtual_machine(self.virtual_machine)
        vmi.set_virtual_network(self.virtual_network_red)
        vmi.set_virtual_machine_interface_bindings(
            KeyValuePairs(
                key_value_pair=[KeyValuePair(key='vnic_type', value='direct'),
                                KeyValuePair(
                                    key='host_id',
                                    value=self.node_red_hostname)]))
        vmi_uuid = self.api.virtual_machine_interface_create(vmi)
        self.check_vpg_exists(
            self.vlan_id_red,
            self.physical_interface_red.get_uuid()
        )
        self.api.virtual_machine_interface_delete(id=vmi_uuid)
    # end test_create_vmi

    def test_create_vmi_with_channelized_pi(self):
        vmi = VirtualMachineInterface(
            name='test-virtual-machine-interface',
            parent_obj=self.project)
        vmi.set_virtual_machine(self.virtual_machine)
        vmi.set_virtual_network(self.virtual_network_blue)
        vmi.set_virtual_machine_interface_bindings(
            KeyValuePairs(
                key_value_pair=[KeyValuePair(key='vnic_type', value='direct'),
                                KeyValuePair(
                                    key='host_id',
                                    value=self.node_blue_hostname)]))
        vmi_uuid = self.api.virtual_machine_interface_create(vmi)
        self.check_vpg_exists(
            self.vlan_id_blue,
            self.physical_interface_blue.get_uuid()
        )
        self.api.virtual_machine_interface_delete(id=vmi_uuid)
    # end test_create_vmi

    def test_create_vmi_and_delete(self):
        vmi = VirtualMachineInterface(
            name='test-virtual-machine-interface-red',
            parent_obj=self.project)
        vmi.set_virtual_machine(self.virtual_machine)
        vmi.set_virtual_network(self.virtual_network_red)
        vmi.set_virtual_machine_interface_bindings(
            KeyValuePairs(
                key_value_pair=[KeyValuePair(key='vnic_type', value='direct'),
                                KeyValuePair(
                                    key='host_id',
                                    value=self.node_red_hostname)]))
        vmi_uuid = self.api.virtual_machine_interface_create(vmi)
        self.check_vpg_exists(
            self.vlan_id_red,
            self.physical_interface_red.get_uuid()
        )
        self.api.virtual_machine_interface_delete(id=vmi_uuid)
        self.check_vpg_not_exist(
            self.vlan_id_red,
            self.physical_interface_red.get_uuid()
        )
    # end test_create_vmi_and_delete

    def test_update_vmi_host(self):
        vmi = VirtualMachineInterface(
            name='test-virtual-machine-interface',
            parent_obj=self.project)
        vmi.set_virtual_machine(self.virtual_machine)
        vmi.set_virtual_network(self.virtual_network_red)
        vmi.set_virtual_machine_interface_bindings(
            KeyValuePairs(
                key_value_pair=[KeyValuePair(key='vnic_type', value='direct'),
                                KeyValuePair(
                                    key='host_id',
                                    value=self.node_red_hostname)]))
        vmi_uuid = self.api.virtual_machine_interface_create(vmi)
        self.check_vpg_exists(
            self.vlan_id_red,
            self.physical_interface_red.get_uuid()
        )
        # update host
        vmi = self.api.virtual_machine_interface_read(id=vmi_uuid)
        vmi.set_virtual_machine_interface_bindings(
            KeyValuePairs(
                key_value_pair=[KeyValuePair(key='vnic_type', value='direct'),
                                KeyValuePair(
                                    key='host_id',
                                    value=self.node_green_hostname)]))
        self.api.virtual_machine_interface_update(vmi)
        self.check_vpg_not_exist(
            self.vlan_id_red,
            self.physical_interface_red.get_uuid()
        )
        self.check_vpg_exists(
            self.vlan_id_red,
            self.physical_interface_green.get_uuid()
        )
        self.api.virtual_machine_interface_delete(id=vmi_uuid)
    # end test_update_vmi_host

    def test_update_vmi_vn(self):
        vmi = VirtualMachineInterface(
            name='test-virtual-machine-interface',
            parent_obj=self.project)
        vmi.set_virtual_machine(self.virtual_machine)
        vmi.set_virtual_network(self.virtual_network_red)
        vmi.set_virtual_machine_interface_bindings(
            KeyValuePairs(
                key_value_pair=[KeyValuePair(key='vnic_type', value='direct'),
                                KeyValuePair(
                                    key='host_id',
                                    value=self.node_red_hostname)]))
        vmi_uuid = self.api.virtual_machine_interface_create(vmi)
        self.check_vpg_exists(
            self.vlan_id_red,
            self.physical_interface_red.get_uuid()
        )
        # update vn
        vmi = self.api.virtual_machine_interface_read(id=vmi_uuid)
        vmi.set_virtual_network(self.virtual_network_green)
        self.api.virtual_machine_interface_update(vmi)
        self.check_vpg_not_exist(
            self.vlan_id_red,
            self.physical_interface_red.get_uuid()
        )
        self.check_vpg_exists(
            self.vlan_id_green,
            self.physical_interface_red.get_uuid()
        )
        self.api.virtual_machine_interface_delete(id=vmi_uuid)
    # end test_update_vmi_vn

    def test_multiple_vn(self):
        vmi_red = VirtualMachineInterface(
            name='test-virtual-machine-interface-red',
            parent_obj=self.project)
        vmi_red.set_virtual_machine(self.virtual_machine)
        vmi_red.set_virtual_network(self.virtual_network_red)
        vmi_red.set_virtual_machine_interface_bindings(
            KeyValuePairs(
                key_value_pair=[KeyValuePair(key='vnic_type', value='direct'),
                                KeyValuePair(
                                    key='host_id',
                                    value=self.node_red_hostname)]))
        vmi_red_uuid = self.api.virtual_machine_interface_create(vmi_red)
        vmi_green = VirtualMachineInterface(
            name='test-virtual-machine-interface-green',
            parent_obj=self.project)
        vmi_green.set_virtual_machine(self.virtual_machine)
        vmi_green.set_virtual_network(self.virtual_network_green)
        vmi_green.set_virtual_machine_interface_bindings(
            KeyValuePairs(
                key_value_pair=[KeyValuePair(key='vnic_type', value='direct'),
                                KeyValuePair(
                                    key='host_id',
                                    value=self.node_red_hostname)]))
        vmi_green_uuid = self.api.virtual_machine_interface_create(vmi_green)
        self.check_vpg_exists(
            self.vlan_id_red,
            self.physical_interface_red.get_uuid()
        )
        self.check_vpg_exists(
            self.vlan_id_green,
            self.physical_interface_red.get_uuid()
        )
        self.api.virtual_machine_interface_delete(id=vmi_red_uuid)
        self.api.virtual_machine_interface_delete(id=vmi_green_uuid)
    # end test_multiple_vn

    def test_single_vn_multiple_pi(self):
        vmi_red = VirtualMachineInterface(
            name='test-virtual-machine-interface-red',
            parent_obj=self.project)
        vmi_red.set_virtual_machine(self.virtual_machine)
        vmi_red.set_virtual_network(self.virtual_network_red)
        vmi_red.set_virtual_machine_interface_bindings(
            KeyValuePairs(
                key_value_pair=[KeyValuePair(key='vnic_type', value='direct'),
                                KeyValuePair(
                                    key='host_id',
                                    value=self.node_red_hostname)]))
        vmi_red_uuid = self.api.virtual_machine_interface_create(vmi_red)
        vmi_green = VirtualMachineInterface(
            name='test-virtual-machine-interface-green',
            parent_obj=self.project)
        vmi_green.set_virtual_machine(self.virtual_machine)
        vmi_green.set_virtual_network(self.virtual_network_red)
        vmi_green.set_virtual_machine_interface_bindings(
            KeyValuePairs(
                key_value_pair=[KeyValuePair(key='vnic_type', value='direct'),
                                KeyValuePair(
                                    key='host_id',
                                    value=self.node_green_hostname)]))
        vmi_green_uuid = self.api.virtual_machine_interface_create(vmi_green)
        self.check_vpg_exists(
            self.vlan_id_red,
            self.physical_interface_red.get_uuid()
        )
        self.check_vpg_exists(
            self.vlan_id_red,
            self.physical_interface_green.get_uuid()
        )
        self.api.virtual_machine_interface_delete(id=vmi_red_uuid)
        self.api.virtual_machine_interface_delete(id=vmi_green_uuid)
    # end test_single_vn_multiple_pi

# end TestVPG
