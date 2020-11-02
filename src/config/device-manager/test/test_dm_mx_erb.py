#
# Copyright (c) 2018 Juniper Networks, Inc. All rights reserved.
#

from __future__ import absolute_import

import uuid
import gevent
from attrdict import AttrDict
from cfgm_common.tests.test_common import retries
from cfgm_common.tests.test_common import retry_exc_handler
from vnc_api.vnc_api import *
from .test_dm_ansible_common import TestAnsibleCommonDM
from .test_dm_utils import FakeJobHandler

class TestAnsibleMXERBDM(TestAnsibleCommonDM):

    def create_feature_objects_and_params(self):
        self.create_features(['overlay-bgp', 'l2-gateway', 'l3-gateway',
                              'vn-interconnect', 'firewall', 'port-profile'])
        self.create_physical_roles(['leaf', 'spine'])
        self.create_overlay_roles(['erb-ucast-gateway'])
        self.create_role_definitions([
            AttrDict({
                'name': 'erb@leaf',
                'physical_role': 'leaf',
                'overlay_role': 'erb-ucast-gateway',
                'features': ['overlay-bgp', 'l2-gateway', 'l3-gateway',
                             'vn-interconnect', 'firewall', 'port-profile'],
                'feature_configs': {}
            })
        ])
    
    def create_vpg_dependencies(self,enterprise_style):
        jt = self.create_job_template('job-template-' + self.id())

        fabric = self.create_fabric('test-fabric',
                    fabric_enterprise_style = enterprise_style)

        np, rc = self.create_node_profile('node-profile-1',
                                          device_family='junos',
                                          role_mappings=[
                                              AttrDict(
                                                  {'physical_role': 'leaf',
                                                   'rb_roles': ['erb-ucast-gateway']}
                                              )],
                                          job_template=jt)
        

        bgp_router, pr = self.create_router('router' + self.id(), '1.1.1.1',
                                            product='mx240', family='junos',
                                            role='leaf', rb_roles=['erb-ucast-gateway'],
                                            physical_role=self.physical_roles['leaf'],
                                            overlay_role=self.overlay_roles['erb-ucast-gateway'], fabric=fabric,
                                            node_profile=np)
        pr.set_physical_router_loopback_ip('10.10.0.1')
        self._vnc_lib.physical_router_update(pr)

        pi_name = "xe-0/0/1"
        pi_obj = PhysicalInterface(pi_name, parent_obj=pr)
        self._vnc_lib.physical_interface_create(pi_obj)

        vn1_obj = self.create_vn(str(100), '1.1.1.0',vxlan_id=2010)
        vn2_obj = self.create_vn(str(200), '2.2.2.0',vxlan_id=2020)

        return pr,fabric,pi_obj,vn1_obj,vn2_obj
    
    def create_security_group(self,sg_name,project_fq_name):
        project_obj = self._vnc_lib.project_read(project_fq_name)
        sg_obj = SecurityGroup(name=sg_name, parent_obj=project_obj)
        self._vnc_lib.security_group_create(sg_obj)
        gevent.sleep(2)
        return sg_obj
    
    def security_group_rule_append(self, sg_obj, sg_rule):
        rules = sg_obj.get_security_group_entries()
        if rules is None:
            rules = PolicyEntriesType([sg_rule])
        else:
            for sgr in rules.get_policy_rule() or []:
                sgr_copy = copy.copy(sgr)
                sgr_copy.rule_uuid = sg_rule.rule_uuid
                if sg_rule == sgr_copy:
                    raise Exception('SecurityGroupRuleExists %s' % sgr.rule_uuid)
            rules.add_policy_rule(sg_rule)

        sg_obj.set_security_group_entries(rules)
    #end security_group_rule_append

    def security_group_rule_build(self, rule_info, sg_fq_name_str):
        protocol = rule_info['protocol']
        port_min = rule_info['port_min'] or 0
        port_max = rule_info['port_max'] or 65535
        direction = rule_info['direction'] or 'egress'
        ip_prefix = rule_info['ip_prefix']
        ether_type = rule_info['ether_type']

        if ip_prefix:
            cidr = ip_prefix.split('/')
            pfx = cidr[0]
            pfx_len = int(cidr[1])
            endpt = [AddressType(subnet=SubnetType(pfx, pfx_len))]
        else:
            endpt = [AddressType(security_group=sg_fq_name_str)]

        local = None
        remote = None
        if direction == 'ingress':
            dir = '>'
            local = endpt
            remote = [AddressType(security_group='local')]
        else:
            dir = '>'
            remote = endpt
            local = [AddressType(security_group='local')]

        if not protocol:
            protocol = 'any'
        if protocol.isdigit():
            protocol = int(protocol)
            if protocol < 0 or protocol > 255:
                raise Exception('SecurityGroupRuleInvalidProtocol-%s' % protocol)
        else:
            if protocol not in ['any', 'tcp', 'udp', 'icmp']:
                raise Exception('SecurityGroupRuleInvalidProtocol-%s' % protocol)

        if not ip_prefix and not sg_fq_name_str:
            if not ether_type:
                ether_type = 'IPv4'

        sgr_uuid = str(uuid.uuid4())
        rule = PolicyRuleType(rule_uuid=sgr_uuid, direction=dir,
                                  protocol=protocol,
                                  src_addresses=local,
                                  src_ports=[PortType(0, 65535)],
                                  dst_addresses=remote,
                                  dst_ports=[PortType(port_min, port_max)],
                                  ethertype=ether_type)
        return rule
    #end security_group_rule_build

    def build_sg_rule(self, pmin, pmax, direction,ip_prefix, proto, etype):
        rule = {}
        rule['port_min'] = pmin
        rule['port_max'] = pmax
        rule['direction'] = direction
        rule['ip_prefix'] = ip_prefix
        rule['protocol'] = proto
        rule['ether_type'] = etype
        return rule
    #end build_sg_rule

    def wait_for_get_sg_id(self, sg_fq_name):
        sg_obj = self._vnc_lib.security_group_read(sg_fq_name)
        if sg_obj.get_security_group_id() is None:
            raise Exception('Security Group Id is none %s' % str(sg_fq_name))
    
    def test_sp_style_mx_device(self):
        self.set_encapsulation_priorities(['VXLAN', 'MPLSoUDP'])
        project = self._vnc_lib.project_read(fq_name=['default-domain',
                                                      'default-project'])
        project.set_vxlan_routing(True)
        self._vnc_lib.project_update(project)

        #create Strom control
        sc_name = 'strm_ctrl_sp_style_erb'
        bw_percent = 47
        traffic_type = ['no-broadcast', 'no-multicast']
        actions = ['interface-shutdown']

        self.create_feature_objects_and_params()

        sc_obj = self.create_storm_control_profile(sc_name, bw_percent, traffic_type, actions, recovery_timeout=None)
        
        #create port profile
        pp_obj = self.create_port_profile('port_profile1', sc_obj)

        pr,fabric,pi_obj,vn1_obj,vn2_obj = self.create_vpg_dependencies(enterprise_style=False)

        # create security group sg1
        sg1_obj = self.create_security_group("sg1",['default-domain',
                                                'default-project'])
        self.wait_for_get_sg_id(sg1_obj.get_fq_name())
        sg1_obj = self._vnc_lib.security_group_read(sg1_obj.get_fq_name())
        rule1 = self.build_sg_rule(0, 65535, 'egress','10.10.10.0/24','any', 'IPv4')
        sg_rule1 = self.security_group_rule_build(rule1,
                                                   sg1_obj.get_fq_name_str())
        self.security_group_rule_append(sg1_obj, sg_rule1)
        self._vnc_lib.security_group_update(sg1_obj)
        sg1_obj = self._vnc_lib.security_group_read(sg1_obj.get_fq_name())

        #create security group sg2
        sg2_obj = self.create_security_group("sg2",['default-domain',
                                                'default-project'])
        self.wait_for_get_sg_id(sg2_obj.get_fq_name())
        sg2_obj = self._vnc_lib.security_group_read(sg2_obj.get_fq_name())
        rule2 = self.build_sg_rule(0, 65535, 'egress','20.20.10.0/24','any', 'IPv4')
        sg_rule2 = self.security_group_rule_build(rule2,
                                                   sg2_obj.get_fq_name_str())
        self.security_group_rule_append(sg2_obj, sg_rule2)
        self._vnc_lib.security_group_update(sg2_obj)
        sg2_obj = self._vnc_lib.security_group_read(sg2_obj.get_fq_name())

        #create Logical Router
        lr_fq_name = ['default-domain', 'default-project', 'lr-' + self.id()]
        lr = LogicalRouter(fq_name=lr_fq_name, parent_type='project',
                           logical_router_type='vxlan-routing')
        lr.add_physical_router(pr)

        #In SP style Fabric,we assign Security group for each individual VN 
        #VN1 is getting assigned sg1 and VN2 is getting assigned sg1 and sg2
        fq_name = ['default-domain', 'default-project', 'vmi3-' + self.id()]
        vmi3 = VirtualMachineInterface(fq_name=fq_name, parent_type='project')
        vmi3_properties = {
                "sub_interface_vlan_tag": 100
            }
        vmi3.set_virtual_machine_interface_properties(vmi3_properties)
        vmi3.set_virtual_network(vn1_obj)
        vmi3.set_security_group(sg1_obj)
        self._vnc_lib.virtual_machine_interface_create(vmi3)
        lr.add_virtual_machine_interface(vmi3)

        fq_name = ['default-domain', 'default-project', 'vmi4-' + self.id()]
        vmi4 = VirtualMachineInterface(fq_name=fq_name, parent_type='project')
        vmi4_properties = {
                "sub_interface_vlan_tag": 200
            }
        vmi4.set_virtual_machine_interface_properties(vmi4_properties)
        vmi4.set_virtual_network(vn2_obj)
        vmi4.set_security_group(sg1_obj)
        vmi4.add_security_group(sg2_obj)
        self._vnc_lib.virtual_machine_interface_create(vmi4)
        lr.add_virtual_machine_interface(vmi4)

        lr_uuid = self._vnc_lib.logical_router_create(lr)
        lr = self._vnc_lib.logical_router_read(id=lr_uuid)

        # create vpg
        vpg_obj = VirtualPortGroup('vpg-1', parent_obj=fabric)
        self._vnc_lib.virtual_port_group_create(vpg_obj)
        vpg_obj.add_physical_interface(pi_obj)

        #Currently VPG UI only supports port profile at VPG level. 
        vpg_obj.set_port_profile(pp_obj)
        vpg_obj.set_virtual_machine_interface_list([{'uuid': vmi3.get_uuid()},
                                                    {'uuid': vmi4.get_uuid()}])
        self._vnc_lib.virtual_port_group_update(vpg_obj)

        gevent.sleep(1)
        self.validate_config(enterprise_style=False)
        self.delete_objects()
    #end test_sp_style_mx_device

    def test_ep_style_mx_device(self):
        self.set_encapsulation_priorities(['VXLAN', 'MPLSoUDP'])
        project = self._vnc_lib.project_read(fq_name=['default-domain',
                                                      'default-project'])
        project.set_vxlan_routing(True)
        self._vnc_lib.project_update(project)

        sc_name = 'strm_ctrl_sp_style_erb'
        bw_percent = 47
        traffic_type = ['no-broadcast', 'no-multicast']
        actions = ['interface-shutdown']

        self.create_feature_objects_and_params()

        sc_obj = self.create_storm_control_profile(sc_name, bw_percent, traffic_type, actions, recovery_timeout=None)
        pp_obj = self.create_port_profile('port_profile1', sc_obj)

        pr,fabric,pi_obj,vn1_obj,vn2_obj = self.create_vpg_dependencies(enterprise_style=True)

        # create security group
        sg1_obj = self.create_security_group("sg1",['default-domain',
                                                'default-project'])
        self.wait_for_get_sg_id(sg1_obj.get_fq_name())
        sg1_obj = self._vnc_lib.security_group_read(sg1_obj.get_fq_name())
        rule1 = self.build_sg_rule(0, 65535, 'egress','10.10.10.0/24','any', 'IPv4')
        sg_rule1 = self.security_group_rule_build(rule1,
                                                   sg1_obj.get_fq_name_str())
        self.security_group_rule_append(sg1_obj, sg_rule1)
        self._vnc_lib.security_group_update(sg1_obj)
        sg1_obj = self._vnc_lib.security_group_read(sg1_obj.get_fq_name())

        #create Logical Router
        lr_fq_name = ['default-domain', 'default-project', 'lr-' + self.id()]
        lr = LogicalRouter(fq_name=lr_fq_name, parent_type='project',
                           logical_router_type='vxlan-routing')
        lr.add_physical_router(pr)

        fq_name = ['default-domain', 'default-project', 'vmi3-' + self.id()]
        vmi3 = VirtualMachineInterface(fq_name=fq_name, parent_type='project')
        vmi3_properties = {
                "sub_interface_vlan_tag": 100
            }
        vmi3.set_virtual_machine_interface_properties(vmi3_properties)
        vmi3.set_virtual_network(vn1_obj)
        self._vnc_lib.virtual_machine_interface_create(vmi3)
        lr.add_virtual_machine_interface(vmi3)

        fq_name = ['default-domain', 'default-project', 'vmi4-' + self.id()]
        vmi4 = VirtualMachineInterface(fq_name=fq_name, parent_type='project')
        vmi4_properties = {
                "sub_interface_vlan_tag": 200
            }
        vmi4.set_virtual_machine_interface_properties(vmi4_properties)
        vmi4.set_virtual_network(vn2_obj)
        self._vnc_lib.virtual_machine_interface_create(vmi4)
        lr.add_virtual_machine_interface(vmi4)

        lr_uuid = self._vnc_lib.logical_router_create(lr)
        lr = self._vnc_lib.logical_router_read(id=lr_uuid)

        # create vpg
        vpg_obj = VirtualPortGroup('vpg-1', parent_obj=fabric)
        self._vnc_lib.virtual_port_group_create(vpg_obj)
        vpg_obj.add_physical_interface(pi_obj)

        vpg_obj.set_port_profile(pp_obj)
        vpg_obj.set_security_group(sg1_obj)
        vpg_obj.set_virtual_machine_interface_list([{'uuid': vmi3.get_uuid()},
                                                    {'uuid': vmi4.get_uuid()}])
        self._vnc_lib.virtual_port_group_update(vpg_obj)

        gevent.sleep(1)
        self.validate_config(enterprise_style=True)
        self.delete_objects()
    #end test_ep_style_mx_device

    @retries(5, hook=retry_exc_handler)
    def validate_config(self,enterprise_style):
        ac = FakeJobHandler.get_job_input()
        self.assertIsNotNone(ac)
        device_abstract_config = ac.get('device_abstract_config')
        pp_phy_interface = device_abstract_config.get(
            'features', {}).get('port-profile', {}).get('physical_interfaces', [])[0]
        pp_logical_interfaces = pp_phy_interface.get('logical_interfaces',None)

        l2_phy_interface = device_abstract_config.get(
            'features', {}).get('l2-gateway', {}).get('physical_interfaces', [])[0]
        l2_logical_interfaces = l2_phy_interface.get('logical_interfaces',{})

        sg_phy_interface = device_abstract_config.get(
            'features', {}).get('firewall').get('physical_interfaces', [])[0]
        fw_logical_interfaces = sg_phy_interface.get('logical_interfaces',{})

        if enterprise_style == False:
            test_li_name=['xe-0/0/1.100','xe-0/0/1.200']

            li_name_list=[]
            self.assertIsNotNone(pp_logical_interfaces)
            for logical_int in pp_logical_interfaces:
                li_name_list.append(logical_int.get('name',''))

            self.assertEqual(sorted(li_name_list),test_li_name)

            li_name_list=[]
            for logical_int in l2_logical_interfaces:
                self.assertIsNone(logical_int.get('vlan_id_list',None))
                li_name_list.append(logical_int.get('name',''))
            self.assertEqual(sorted(li_name_list),test_li_name)

            for logical_int in fw_logical_interfaces:
                firewall_filters = logical_int.get('firewall_filters')
                if logical_int.get('unit','') == 100:
                    #for unit vmi with unit 100 we only have 1 firewall filter
                    self.assertEqual(len(firewall_filters),1)
                elif logical_int.get('unit','') == 200:
                    #for vmi with unit 200 we have 2 firewall filter
                    self.assertEqual(len(firewall_filters),2)
        else:
            vlan_id_list=['100','200']
            #LogicalInterfaces should not be created in PortProfile in EP style
            self.assertIsNone(pp_logical_interfaces)
            self.assertIsNotNone(l2_logical_interfaces[0].get('vlan_id_list',None))
            self.assertEqual(sorted(l2_logical_interfaces[0].get('vlan_id_list','')),vlan_id_list)
            
            #In EP style we will only have one LogicalInterface with unit 0
            self.assertEqual(l2_logical_interfaces[0].get('name'),'xe-0/0/1.0')
            self.assertEqual(fw_logical_interfaces[0].get('name'),'xe-0/0/1.0')
    #end validate_config

    @retries(5, hook=retry_exc_handler)
    def delete_objects(self):
        vpg_list = self._vnc_lib.virtual_port_groups_list().get('virtual-port-groups')
        for vpg in vpg_list:
            vpg_obj = self._vnc_lib.virtual_port_group_read(id=vpg['uuid'])
            vpg_obj.set_virtual_machine_interface_list([])
            vpg_obj.set_physical_interface_list([])
            self._vnc_lib.virtual_port_group_update(vpg_obj)
        
        logical_routers_list = self._vnc_lib.logical_routers_list().get('logical-routers')
        for logical_router in logical_routers_list:
            self._vnc_lib.logical_router_delete(id=logical_router['uuid'])

        vmi_list = self._vnc_lib.virtual_machine_interfaces_list().get(
            'virtual-machine-interfaces')
        for vmi in vmi_list:
            self._vnc_lib.virtual_machine_interface_delete(id=vmi['uuid'])

        pi_list = self._vnc_lib.physical_interfaces_list().get('physical-interfaces')
        for pi in pi_list:
            self._vnc_lib.physical_interface_delete(id=pi['uuid'])

        for vpg in vpg_list:
            self._vnc_lib.virtual_port_group_delete(id=vpg['uuid'])

        pr_list = self._vnc_lib.physical_routers_list().get('physical-routers')
        for pr in pr_list:
            self._vnc_lib.physical_router_delete(id=pr['uuid'])

        vn_list = self._vnc_lib.virtual_networks_list().get('virtual-networks')
        for vn in vn_list:
            self._vnc_lib.virtual_network_delete(id=vn['uuid'])

        rc_list = self._vnc_lib.role_configs_list().get('role-configs')
        for rc in rc_list:
            self._vnc_lib.role_config_delete(id=rc['uuid'])

        np_list = self._vnc_lib.node_profiles_list().get('node-profiles')
        for np in np_list:
            self._vnc_lib.node_profile_delete(id=np['uuid'])

        fab_list = self._vnc_lib.fabrics_list().get('fabrics')
        for fab in fab_list:
            self._vnc_lib.fabric_delete(id=fab['uuid'])

        jt_list = self._vnc_lib.job_templates_list().get('job-templates')
        for jt in jt_list:
            self._vnc_lib.job_template_delete(id=jt['uuid'])

        pp_list = self._vnc_lib.port_profiles_list().get('port-profiles')
        for pp in pp_list:
            self._vnc_lib.port_profile_delete(id=pp['uuid'])

        sg_list = self._vnc_lib.security_groups_list().get('security-groups')
        for sg in sg_list:
            self._vnc_lib.security_group_delete(id=sg['uuid'])

        sc_list = self._vnc_lib.storm_control_profiles_list().get('storm-control-profiles')
        for sc in sc_list:
            self._vnc_lib.storm_control_profile_delete(id=sc['uuid'])

        self.delete_role_definitions()
        self.delete_overlay_roles()
        self.delete_physical_roles()
        self.delete_features()
        self.wait_for_features_delete()
    #end delete_objects
