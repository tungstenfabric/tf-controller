#
# Copyright (c) 2019 Juniper Networks, Inc. All rights reserved.
#

from builtins import str
import copy

from cfgm_common.exceptions import NoIdError
import jsonpickle
from vnc_api.gen.resource_xsd import AddressType, MatchConditionType
from vnc_api.gen.resource_xsd import PortType, SubnetType
from vnc_api.gen.resource_xsd import KeyValuePair, KeyValuePairs
from vnc_api.gen.resource_xsd import VrfAssignRuleType, VrfAssignTableType

from vnc_api.vnc_api import VirtualMachineInterface
from vnc_api.vnc_api import VirtualPortGroup

from schema_transformer.resources._resource_base import ResourceBaseST
from schema_transformer.sandesh.st_introspect import ttypes as sandesh


class VirtualMachineInterfaceST(ResourceBaseST):
    _dict = {}
    obj_type = 'virtual_machine_interface'
    ref_fields = ['virtual_network', 'virtual_machine', 'port_tuple',
                  'logical_router', 'bgp_as_a_service', 'routing_instance']
    prop_fields = ['virtual_machine_interface_bindings',
                   'virtual_machine_interface_properties']

    def __init__(self, name, obj=None):
        self.name = name
        self.service_interface_type = None
        self.interface_mirror = None
        self.virtual_network = None
        self.virtual_machine = None
        self.virtual_machine_interface_bindings = None
        self.virtual_port_group = None
        self.port_tuples = set()
        self.logical_router = None
        self.bgp_as_a_service = None
        self.uuid = None
        self.instance_ips = set()
        self.floating_ips = set()
        self.alias_ips = set()
        self.routing_instances = {}
        self.update(obj)
        self.uuid = self.obj.uuid
        self.update_multiple_refs('instance_ip', self.obj)
        self.update_multiple_refs('floating_ip', self.obj)
        self.update_multiple_refs('alias_ip', self.obj)
        self.vrf_table = jsonpickle.encode(self.obj.get_vrf_assign_table())
        self.vlan_id = None
        self.physical_interface_uuid = None
    # end __init__

    def update(self, obj=None):
        changed = self.update_vnc_obj(obj)
        if 'virtual_machine_interface_bindings' in changed:
            self.set_bindings()
        if 'virtual_machine_interface_properties' in changed:
            self.set_properties()
        if 'routing_instance' in changed:
            self.update_routing_instances(self.obj.get_routing_instance_refs())
        return changed
    # end update

    def delete_obj(self):
        self.update_single_ref('virtual_network', {})
        self.update_single_ref('virtual_machine', {})
        self.update_single_ref('logical_router', {})
        self.update_multiple_refs('instance_ip', {})
        self.update_multiple_refs('port_tuple', {})
        self.update_multiple_refs('floating_ip', {})
        self.update_multiple_refs('alias_ip', {})
        self.update_single_ref('bgp_as_a_service', {})
        self.update_routing_instances([])
        # delete attributes used by VPG
        self.vlan_id = None
        self.physical_interface_uuid = None
    # end delete_obj

    def evaluate(self, **kwargs):
        self.set_virtual_network()
        self._add_pbf_rules()
        self.process_analyzer()
        self.recreate_vrf_assign_table()
        self.process_vpg()
    # end evaluate

    def process_vpg(self):
        import pdb; pdb.set_trace()
        if self.vlan_id is None or self.physical_interface_uuid is None:
            self.create_vpg()
        else:
            self.update_vpg()

    def create_vpg(self):
        import pdb; pdb.set_trace()
        vlan_id, physical_interface = \
            self.collect_vlan_id_and_physical_interface()
        if vlan_id is None or physical_interface is None:
            return
        physical_interface_uuid = physical_interface.get_uuid()
        # check if desired VPG exists
        virtual_port_group_st = self.get_virtual_port_group(
            vlan_id, physical_interface_uuid)
        if virtual_port_group_st is not None:
            # update VPG
            self.update_vpg_object(
                virtual_port_group_st, physical_interface_uuid)
            return
        # create new VPG
        self.create_vpg_object(vlan_id, physical_interface)
        # update vlan_id and physical_interface_uuid
        self.update_vlan_id_and_physical_interface_uuid(
            vlan_id, physical_interface_uuid)
        return

    def update_vpg(self):
        import pdb; pdb.set_trace()
        vlan_id, physical_interface = \
            self.collect_vlan_id_and_physical_interface()
        if vlan_id is None or physical_interface is None:
            return
        physical_interface_uuid = physical_interface.get_uuid()
        # check if desired VPG exists
        virtual_port_group_st = self.get_virtual_port_group(
            vlan_id, physical_interface_uuid)
        if virtual_port_group_st is None:
            # create new VPG
            self.create_vpg_object(vlan_id, physical_interface)
            return
        # update VPG
        self.update_vpg_object(
            virtual_port_group_st, physical_interface_uuid)
        # update vlan_id and physical_interface_uuid
        self.update_vlan_id_and_physical_interface_uuid(
            vlan_id, physical_interface_uuid)
        return

    def get_virtual_port_group(self, vlan_id, physical_interface_uuid):
        import pdb; pdb.set_trace()
        for virtual_port_group_st in \
                ResourceBaseST.get_obj_type_map().get('virtual_port_group'):
            if virtual_port_group_st.vlan_id == vlan_id and \
                physical_interface_uuid in \
                    virtual_port_group_st.pi_uuid_to_vmi_st_names.keys():
                return virtual_port_group_st
        return None
    # end get_virtual_port_group

    def collect_vlan_id_and_physical_interface(self):
        import pdb; pdb.set_trace()
        # get hostname
        hostname = self.get_hostname()
        if hostname == "":
            return (None, None)
        # get physnet name and vlan_id
        physnet, vlan_id = self.get_physnet_and_vlan_id()
        if physnet == "" or vlan_id is None:
            return (None, None)
        # get port name
        switch_id, switch_port_id = \
            self.get_switch_id_and_switch_port_id(hostname, physnet)
        if switch_id == "" or switch_port_id == "":
            return (None, None)
        # get physical interface
        physical_interface = \
            self.get_physical_interface(switch_id, switch_port_id)
        return (vlan_id, physical_interface)
    # end collect_vlan_id_and_physical_interface

    def get_hostname(self):
        import pdb; pdb.set_trace()
        if self.uuid is None or \
           self.virtual_machine_interface_bindings is None:
            return ""
        if self.virtual_machine_interface_bindings.get('vnic_type', "") \
           != "direct":
            return ""
        return self.virtual_machine_interface_bindings.get('hostname', "")
    # end get_hostname

    def get_physnet_and_vlan_id(self):
        import pdb; pdb.set_trace()
        if self.virtual_network is None or \
           self.virtual_network.provider_properties is None or \
           self.virtual_network.uuid is None:
            return ("", None)
        physnet = self.virtual_network \
                      .provider_properties \
                      .get_physical_network()
        if physnet == "":
            return ("", None)
        vlan_id = self.virtual_network \
                      .provider_properties \
                      .get_segmentation_id()
        return (physnet, vlan_id)
    # end get_physnet_and_vlan_id

    def get_switch_id_and_switch_port_id(self, hostname, physnet):
        import pdb; pdb.set_trace()
        virtual_router_dicts = self._vnc_lib.virtual_routers_list(
            filters={'display_name': hostname},
            fields=['uuid', 'virtual_router_sriov_physical_networks']
        )
        virtual_router_uuids = [virtual_router_dict['uuid'] for
                                virtual_router_dict in
                                virtual_router_dicts['virtual-routers']]
        for virtual_router_uuid in virtual_router_uuids:
            virtual_router = self._vnc_lib.virtual_router_read(
                id=virtual_router_uuid)
            virtual_router_sriov_physical_networks = \
                self.kvps_to_dict(virtual_router.get_virtual_router_sriov_physical_networks())
            port_name = virtual_router_sriov_physical_networks.get(physnet, "")
            if port_name == "":
                return ("", "")
            # get switch_id
            node_dicts = self._vnc_lib.nodes_list(
                filters={'hostname': hostname},
                fields=['uuid', 'ports'])
            node_uuids = \
                [node_dict['uuid'] for node_dict in node_dicts['nodes']]
            for node_uuid in node_uuids:
                node = self._vnc_lib.node_read(id=node_uuid)
                ports = node.get_ports()
                if ports is None:
                    return ("", "")
                switch_id = ""
                switch_port_id = ""
                for port in ports:
                    if port.get_display_name() == port_name:
                        switch_id = port.get_bms_port_info() \
                                        .get_local_link_connection() \
                                        .get_switch_id()
                        switch_port_id = port.get_bms_port_info() \
                                             .get_local_link_connection() \
                                             .get_port_id()
                return (switch_id, switch_port_id)
        return ("", "")
    # end get_switch_id_and_switch_port_id

    def get_physical_interface(self, switch_id, switch_port_id):
        import pdb; pdb.set_trace()
        physical_router_dicts = self._vnc_lib.physical_routers_list(
            filters={'physical_router_hostname': switch_id},
            fields=['uuid', 'physical_interfaces'])
        physical_router_uuids = [physical_router_dict['uuid'] for
                                 physical_router_dict in
                                 physical_router_dicts['physical-routers']]
        for physical_router_uuid in physical_router_uuids:
            physical_router = self._vnc_lib.physical_router_read(
                id=physical_router_uuid)
            for physical_interface in \
                    physical_router.get_physical_interfaces():
                if physical_interface.get_physical_interface_port_id() == \
                        switch_port_id:
                    return physical_interface
        return None
    # end get_physical_interface

    def create_vpg_object(self, vlan_id, physical_interface):
        # TODO(dji): VPG object creation raises asyncronous vpg evaluate,
        # TODO(dji): this might cause trouble
        import pdb; pdb.set_trace()
        # create a VPG object to refer to placeholder VMI and PI
        if self.virtual_network is None:
            return
        vpg = VirtualPortGroup('vpg-' + self.virtual_network)
        # VPG refers to placeholder VMI
        vmi = VirtualMachineInterface("vmi-" + self.virtual_network)
        vmi.set_virtual_machine_interface_bindings(
            KeyValuePairs(
                key_value_pair=[
                    KeyValuePair(
                        key='vlan_id', value=vlan_id)]))
        vmi_uuid = self._vnc_lib.virtual_machine_interface_create(vmi)
        vpg.set_virtual_machine_interface(vmi)
        # VPG refers to PI
        vpg.set_physical_interface(physical_interface)
        # create VPG object
        self._vnc_lib.virtual_port_group_create(vpg)
        # get VPGST object
        virtual_port_group_st = None
        count = 0
        while virtual_port_group_st is None and count < 10:
            virtual_port_group_st = self.get_virtual_port_group(
                vlan_id, physical_interface.get_uuid())
            count += 1
        if virtual_port_group_st is None:
            return
        virtual_port_group_st.update_virtual_machine_uuid(vmi_uuid)
        virtual_port_group_st.update_vlan_id(vlan_id)
        virtual_port_group_st.update_pi_uuid_to_vmi_st_name(
            physical_interface.get_uuid(), self.name)
        self.virtual_port_group = virtual_port_group_st.name
        return
    # end create_vpg_object

    def update_vpg_object(
            self, virtual_port_group_st, physical_interface_uuid):
        import pdb; pdb.set_trace()
        virtual_port_group_st.update_pi_uuid_to_vmi_st_name(
            physical_interface_uuid, self.name)
        self.virtual_port_group = virtual_port_group_st.name
        return
    # end update_vpg_object

    def update_vlan_id_and_physical_interface_uuid(
            self, vlan_id, physical_interface_uuid):
        import pdb; pdb.set_trace()
        self.vlan_id = vlan_id
        self.physical_interface_uuid = physical_interface_uuid
        return
    # end update_vlan_id_and_pi_uuid

    def is_left(self):
        return (self.service_interface_type == 'left')

    def is_right(self):
        return (self.service_interface_type == 'right')

    def get_any_instance_ip_address(self, ip_version=0):
        for ip_name in self.instance_ips:
            ip = ResourceBaseST.get_obj_type_map().get(
                'instance_ip').get(ip_name)
            if ip is None or ip.instance_ip_address is None:
                continue
            if not ip.service_instance_ip:
                continue
            if not ip_version or ip.ip_version == ip_version:
                return ip.instance_ip_address
        return None
    # end get_any_instance_ip_address

    def get_primary_instance_ip_address(self, ip_version=4):
        for ip_name in self.instance_ips:
            ip = ResourceBaseST.get_obj_type_map().get(
                'instance_ip').get(ip_name)
            if ip.is_primary() and ip.instance_ip_address and \
                    ip_version == ip.ip_version:
                return ip.instance_ip_address
        return None
    # end get_primary_instance_ip_address

    def set_bindings(self):
        self.virtual_machine_interface_bindings = \
            self.kvps_to_dict(self.obj.get_virtual_machine_interface_bindings())
        return
    # end set_bindings

    def kvps_to_dict(self, kvps):
        dictionary = dict()
        if not kvps:
            return dictionary
        for kvp in kvps.get_key_value_pair():
            dictionary[kvp.get_key()] = kvp.get_value()
        return dictionary

    def set_properties(self):
        props = self.obj.get_virtual_machine_interface_properties()
        if props:
            service_interface_type = props.service_interface_type
            interface_mirror = props.interface_mirror
        else:
            service_interface_type = None
            interface_mirror = None
        ret = False
        if service_interface_type != self.service_interface_type:
            self.service_interface_type = service_interface_type
            ret = True
        if interface_mirror != self.interface_mirror:
            self.interface_mirror = interface_mirror
            ret = True
        return ret
    # end set_properties

    def update_routing_instances(self, ri_refs):
        routing_instances = dict((':'.join(ref['to']), ref['attr'])
                                 for ref in ri_refs or [])
        old_ri_set = set(self.routing_instances.keys())
        new_ri_set = set(routing_instances.keys())
        for ri_name in old_ri_set - new_ri_set:
            ri = ResourceBaseST.get_obj_type_map().get(
                'routing_instance').get(ri_name)
            if ri:
                ri.virtual_machine_interfaces.discard(self.name)
        for ri_name in new_ri_set - old_ri_set:
            ri = ResourceBaseST.get_obj_type_map().get(
                'routing_instance').get(ri_name)
            if ri:
                ri.virtual_machine_interfaces.add(self.name)
        self.routing_instances = routing_instances
    # end update_routing_instances

    def add_routing_instance(self, ri, pbf):
        if self.routing_instances.get(ri.name) == pbf:
            return
        self._vnc_lib.ref_update(
            'virtual-machine-interface', self.uuid, 'routing-instance',
            ri.obj.uuid, None, 'ADD', pbf)
        self.routing_instances[ri.name] = pbf
        ri.virtual_machine_interfaces.add(self.name)
    # end add_routing_instance

    def delete_routing_instance(self, ri):
        if ri.name not in self.routing_instances:
            return
        try:
            self._vnc_lib.ref_update(
                'virtual-machine-interface', self.uuid, 'routing-instance',
                ri.obj.uuid, None, 'DELETE')
        except NoIdError:
            # NoIdError could happen if RI is deleted while we try to remove
            # the link from VMI
            pass
        del self.routing_instances[ri.name]
        ri.virtual_machine_interfaces.discard(self.name)
    # end delete_routing_instance

    def get_virtual_machine_or_port_tuple(self):
        if self.port_tuples:
            pt_list = [ResourceBaseST.get_obj_type_map().get(
                'port_tuple').get(x) for x in self.port_tuples
                if x is not None]
            return pt_list
        elif self.virtual_machine:
            vm = ResourceBaseST.get_obj_type_map().get(
                'virtual_machine').get(self.virtual_machine)
            return [vm] if vm is not None else []
        return []
    # end get_service_instance

    def _add_pbf_rules(self):
        if not (self.is_left() or self.is_right()):
            return

        vm_pt_list = self.get_virtual_machine_or_port_tuple()
        for vm_pt in vm_pt_list:
            if vm_pt.get_service_mode() != 'transparent':
                return
            for service_chain in list(ResourceBaseST.get_obj_type_map().get(
                    'service_chain').values()):
                if vm_pt.service_instance not in service_chain.service_list:
                    continue
                if not service_chain.created:
                    continue
                if self.is_left():
                    vn_obj = ResourceBaseST.get_obj_type_map().get(
                        'virtual_network').locate(service_chain.left_vn)
                    vn1_obj = vn_obj
                else:
                    vn1_obj = ResourceBaseST.get_obj_type_map().get(
                        'virtual_network').locate(service_chain.left_vn)
                    vn_obj = ResourceBaseST.get_obj_type_map().get(
                        'virtual_network').locate(service_chain.right_vn)

                service_name = vn_obj.get_service_name(service_chain.name,
                                                       vm_pt.service_instance)
                service_ri = ResourceBaseST.get_obj_type_map().get(
                    'routing_instance').get(service_name)
                v4_address, v6_address = vn1_obj.allocate_service_chain_ip(
                    service_name)
                vlan = self._object_db.allocate_service_chain_vlan(
                    vm_pt.uuid, service_chain.name)

                service_chain.add_pbf_rule(self, service_ri, v4_address,
                                           v6_address, vlan)
            # end for service_chain
        # end for vm_pt
    # end _add_pbf_rules

    def set_virtual_network(self):
        lr = ResourceBaseST.get_obj_type_map().get(
            'logical_router').get(self.logical_router)
        if lr is not None:
            lr.update_virtual_networks()
    # end set_virtual_network

    def process_analyzer(self):
        if (self.interface_mirror is None or
                self.interface_mirror.mirror_to is None or
                self.virtual_network is None):
            return
        vn = ResourceBaseST.get_obj_type_map().get(
            'virtual_network').get(self.virtual_network)
        if vn is None:
            return

        old_mirror_to = copy.deepcopy(self.interface_mirror.mirror_to)

        vn.process_analyzer(self.interface_mirror)

        if old_mirror_to == self.interface_mirror.mirror_to:
            return

        self.obj.set_virtual_machine_interface_properties(
            self.obj.get_virtual_machine_interface_properties())
        try:
            self._vnc_lib.virtual_machine_interface_update(self.obj)
        except NoIdError:
            self._logger.error("NoIdError while updating interface " +
                               self.name)
    # end process_analyzer

    def recreate_vrf_assign_table(self):
        if not (self.is_left() or self.is_right()):
            self._set_vrf_assign_table(None)
            return
        vn = ResourceBaseST.get_obj_type_map().get(
            'virtual_network').get(self.virtual_network)
        if vn is None:
            self._set_vrf_assign_table(None)
            return
        vm_pt_list = self.get_virtual_machine_or_port_tuple()
        if not vm_pt_list:
            self._set_vrf_assign_table(None)
            return

        policy_rule_count = 0
        vrf_table = VrfAssignTableType()
        for vm_pt in vm_pt_list:
            smode = vm_pt.get_service_mode()
            if smode not in ['in-network', 'in-network-nat']:
                self._set_vrf_assign_table(None)
                return

            ip_list = []
            for ip_name in self.instance_ips:
                ip = ResourceBaseST.get_obj_type_map().get(
                    'instance_ip').get(ip_name)
                if ip and ip.instance_ip_address:
                    ip_list.append((ip.ip_version, ip.instance_ip_address))
            for ip_name in self.floating_ips:
                ip = ResourceBaseST.get_obj_type_map().get(
                    'floating_ip').get(ip_name)
                if ip and ip.floating_ip_address:
                    ip_list.append((ip.ip_version, ip.floating_ip_address))
            for ip_name in self.alias_ips:
                ip = ResourceBaseST.get_obj_type_map().get(
                    'alias_ip').get(ip_name)
                if ip and ip.alias_ip_address:
                    ip_list.append((ip.ip_version, ip.alias_ip_address))
            for (ip_version, ip_address) in ip_list:
                if ip_version == 6:
                    address = AddressType(subnet=SubnetType(ip_address, 128))
                else:
                    address = AddressType(subnet=SubnetType(ip_address, 32))

                mc = MatchConditionType(src_address=address,
                                        protocol='any',
                                        src_port=PortType(),
                                        dst_port=PortType())

                vrf_rule = VrfAssignRuleType(
                    match_condition=mc,
                    routing_instance=vn._default_ri_name,
                    ignore_acl=False)
                vrf_table.add_vrf_assign_rule(vrf_rule)

            si_name = vm_pt.service_instance
            for service_chain_list in list(vn.service_chains.values()):
                for service_chain in service_chain_list:
                    if not service_chain.created:
                        continue
                    service_list = service_chain.service_list
                    if si_name not in service_chain.service_list:
                        continue
                    if ((si_name == service_list[0] and self.is_left()) or
                            (si_name == service_list[-1] and self.is_right())):
                        # Do not generate VRF assign rules for 'book-ends'
                        continue
                    ri_name = vn.get_service_name(service_chain.name, si_name)
                    for sp in service_chain.sp_list:
                        for dp in service_chain.dp_list:
                            if self.is_left():
                                mc = MatchConditionType(
                                    src_port=dp,
                                    dst_port=sp,
                                    protocol=service_chain.protocol)
                            else:
                                mc = MatchConditionType(
                                    src_port=sp,
                                    dst_port=dp,
                                    protocol=service_chain.protocol)
                            vrf_rule = VrfAssignRuleType(
                                match_condition=mc,
                                routing_instance=ri_name,
                                ignore_acl=True)
                            vrf_table.add_vrf_assign_rule(vrf_rule)
                            policy_rule_count += 1
                        # end for dp
                    # end for sp
                # end for service_chain
            # end for service_chain_list
        # end for vm_pt_list
        if policy_rule_count == 0:
            vrf_table = None
        self._set_vrf_assign_table(vrf_table)
    # end recreate_vrf_assign_table

    def _set_vrf_assign_table(self, vrf_table):
        vrf_table_pickle = jsonpickle.encode(vrf_table)
        if vrf_table_pickle != self.vrf_table:
            self.obj.set_vrf_assign_table(vrf_table)
            try:
                self._vnc_lib.virtual_machine_interface_update(self.obj)
                self.vrf_table = vrf_table_pickle
            except NoIdError as e:
                if e._unknown_id == self.uuid:
                    VirtualMachineInterfaceST.delete(self.name)
    # _set_vrf_assign_table

    def handle_st_object_req(self):
        resp = super(VirtualMachineInterfaceST, self).handle_st_object_req()
        resp.obj_refs.extend([
            self._get_sandesh_ref_list('instance_ip'),
            self._get_sandesh_ref_list('floating_ip'),
            self._get_sandesh_ref_list('alias_ip'),
        ])
        resp.properties = [
            sandesh.PropList('service_interface_type',
                             self.service_interface_type),
            sandesh.PropList('interface_mirror', str(self.interface_mirror)),
        ]
        return resp
    # end handle_st_object_req

    def get_v4_default_gateway(self):
        if not self.virtual_network:
            return None
        vn = ResourceBaseST.get_obj_type_map().get(
            'virtual_network').get(self.virtual_network)
        if not vn:
            return None
        v4_address = self.get_primary_instance_ip_address(ip_version=4)
        if not v4_address:
            return None
        return vn.get_gateway(v4_address)
    # end get_v4_default_gateway

    def get_v6_default_gateway(self):
        if not self.virtual_network:
            return None
        vn = ResourceBaseST.get_obj_type_map().get(
            'virtual_network').get(self.virtual_network)
        if not vn:
            return None
        v6_address = self.get_primary_instance_ip_address(ip_version=6)
        if not v6_address:
            return None
        return vn.get_gateway(v6_address)
    # end get_v6_default_gateway

    def get_ipv4_mapped_ipv6_gateway(self):
        return '::ffff:%s' % self.get_v4_default_gateway()
    # end get_ipv4_mapped_ipv6_gateway
# end VirtualMachineInterfaceST
