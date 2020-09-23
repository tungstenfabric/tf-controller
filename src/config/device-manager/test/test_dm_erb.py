#
# Copyright (c) 2018 Juniper Networks, Inc. All rights reserved.
#

from __future__ import absolute_import

from attrdict import AttrDict
from cfgm_common.tests.test_common import retries
from cfgm_common.tests.test_common import retry_exc_handler
from vnc_api.vnc_api import *
from .test_dm_ansible_common import TestAnsibleCommonDM
from .test_dm_utils import FakeJobHandler


class TestAnsibleDM(TestAnsibleCommonDM):

    @retries(5, hook=retry_exc_handler)
    def check_erb_content(self, vlans):
        ac = FakeJobHandler.get_job_input()
        self.assertIsNotNone(ac)
        fc = ac.get('device_abstract_config').get('features')
        l2_gateway = fc.get('l2-gateway')
        l3_gateway = fc.get('l3-gateway')
        vn_interconnect = fc.get('vn-interconnect')
        vn_routing_interfaces = vn_interconnect.get('routing_instances')[0].get('routing_interfaces')

        irbs = [ri.get('name') for ri in vn_routing_interfaces]

        l3_logical_interface = l3_gateway.get('physical_interfaces')[0].get('logical_interfaces')
        l2_vlan_object = l2_gateway.get('vlans')
        l3_vlan_object = l3_gateway.get('vlans')

        l2_vlans = [vl.get('vlan_id') for vl in l2_vlan_object]
        l3_vlans = [vl.get('vlan_id') for vl in l3_vlan_object]

        l3_li_units = [str(l3li.get('unit')) for l3li in l3_logical_interface]

        test_irbs = ['irb.' + li for li in l3_li_units]

        l2_ri = l2_gateway.get('routing_instances')
        l3_ri = l3_gateway.get('routing_instances')

        l2_vnis = [ri.get('virtual_network_id') for ri in l2_ri]
        l3_vnis = [ri.get('virtual_network_id') for ri in l3_ri]

        # compare l2 and l3 VLANs
        self.assertEqual(sorted(l2_vlans), sorted(vlans))
        self.assertEqual(sorted(l3_vlans), sorted(vlans))

        # compare l2 and l3 VNIs
        self.assertEqual(sorted(l2_vnis), sorted(l3_li_units))
        self.assertEqual(sorted(l3_vnis), sorted(l3_li_units))

        # compare IRBs
        self.assertEqual(sorted(irbs), sorted(test_irbs))

    @retries(5, hook=retry_exc_handler)
    def check_ri_count(self, no_of_vmi):
        ac = FakeJobHandler.get_job_input()
        self.assertIsNotNone(ac)
        fc = ac.get('device_abstract_config').get('features')
        l2_gateway = fc.get('l2-gateway')
        l3_gateway = fc.get('l3-gateway')
        vn_interconnect = fc.get('vn-interconnect')

        l2_ri = l2_gateway.get('routing_instances', [])
        l2_vlans = l2_gateway.get('vlans', [])
        l2_physical_interfaces = l2_gateway.get('physical_interfaces', [])

        l3_ri = l3_gateway.get('routing_instances', [])
        l3_vlans = l3_gateway.get('vlans', [])
        l3_physical_interfaces = l3_gateway.get('physical_interfaces', [{}])[0].get('logical_interfaces', [])

        vn_routing_interfaces = vn_interconnect.get('routing_instances', [{}])[0].get('routing_interfaces', [])

        self.assertEqual(len(l2_ri), no_of_vmi)
        self.assertEqual(len(l2_vlans), no_of_vmi)
        self.assertEqual(len(l2_physical_interfaces), no_of_vmi)
        self.assertEqual(len(l3_ri), no_of_vmi)
        self.assertEqual(len(l3_vlans), no_of_vmi)
        self.assertEqual(len(l3_physical_interfaces), no_of_vmi)
        self.assertEqual(len(vn_routing_interfaces), no_of_vmi)

    @retries(5, hook=retry_exc_handler)
    def check_no_lr(self, no_of_vpgs, vlans):
        ac = FakeJobHandler.get_job_input()
        self.assertIsNotNone(ac)
        fc = ac.get('device_abstract_config').get('features')
        l2_gateway = fc.get('l2-gateway')
        l3_gateway = fc.get('l3-gateway')
        vn_interconnect = fc.get('vn-interconnect')


        l2_physical_interfaces = l2_gateway.get('physical_interfaces', [])
        l2_vlan_object = l2_gateway.get('vlans')
        l2_vlans = [vl.get('vlan_id') for vl in l2_vlan_object]
        l2_ri = l2_gateway.get('routing_instances')

        l3_ri = l3_gateway.get('routing_instances', [])
        l3_vlans = l3_gateway.get('vlans', [])
        l3_physical_interfaces = l3_gateway.get('physical_interfaces', [{}])[0].get('logical_interfaces', [])

        vn_routing_interfaces = vn_interconnect.get('routing_instances', [{}])[0].get('routing_interfaces', [])


        self.assertEqual(sorted(l2_vlans), sorted(vlans))
        self.assertEqual(len(l2_ri), no_of_vpgs)
        self.assertEqual(len(l2_vlans), no_of_vpgs)
        self.assertEqual(len(l2_physical_interfaces), no_of_vpgs)
        self.assertEqual(len(l3_ri), 0)
        self.assertEqual(len(l3_vlans), 0)
        self.assertEqual(len(l3_physical_interfaces), 0)
        self.assertEqual(len(vn_routing_interfaces), 0)


    def test_erb_config_push_multiple_vmi(self):
        self.set_encapsulation_priorities(['VXLAN', 'MPLSoUDP'])
        project = self._vnc_lib.project_read(fq_name=['default-domain',
                                                      'default-project'])
        project.set_vxlan_routing(True)
        self._vnc_lib.project_update(project)

        self.create_features(['overlay-bgp', 'l2-gateway',
                              'l3-gateway', 'vn-interconnect'])
        self.create_physical_roles(['leaf', 'spine'])
        self.create_overlay_roles(['erb-ucast-gateway', 'crb-mcast-gateway'])
        self.create_role_definitions([
            AttrDict({
                'name': 'erb@leaf',
                'physical_role': 'leaf',
                'overlay_role': 'erb-ucast-gateway',
                'features': ['overlay-bgp', 'l2-gateway',
                             'l3-gateway', 'vn-interconnect'],
                'feature_configs': {'l3_gateway': {'use_gateway_ip': 'True'}}
            })
        ])

        jt = self.create_job_template('job-template-1')
        fabric = self.create_fabric('test-fabric')
        np, rc = self.create_node_profile('node-profile-1',
                                          device_family='junos-qfx',
                                          role_mappings=[
                                              AttrDict(
                                                  {'physical_role': 'leaf',
                                                   'rb_roles': ['erb-ucast-gateway']}
                                              )],
                                          job_template=jt)

        vn1_obj = self.create_vn('1', '1.1.1.0')
        vn2_obj = self.create_vn('2', '2.2.2.0')

        bgp_router, pr = self.create_router('router' + self.id(), '1.1.1.1',
                                            product='qfx5110', family='junos-qfx',
                                            role='leaf', rb_roles=['erb-ucast-gateway'],
                                            physical_role=self.physical_roles['leaf'],
                                            overlay_role=self.overlay_roles['erb-ucast-gateway'], fabric=fabric,
                                            node_profile=np)
        pr.set_physical_router_loopback_ip('10.10.0.1')
        self._vnc_lib.physical_router_update(pr)

        vmi1, vm1, pi1 = self.attach_vmi('1', ['xe-0/0/1'], [pr], vn1_obj, None, fabric, 101)
        vmi2, vm2, pi2 = self.attach_vmi('2', ['xe-0/0/2'], [pr], vn2_obj, None, fabric, 102)

        lr_fq_name = ['default-domain', 'default-project', 'lr-' + self.id()]
        lr = LogicalRouter(fq_name=lr_fq_name, parent_type='project',
                           logical_router_type='vxlan-routing',
                           vxlan_network_identifier='3000')
        lr.set_physical_router(pr)

        fq_name = ['default-domain', 'default-project', 'vmi3-' + self.id()]
        vmi3 = VirtualMachineInterface(fq_name=fq_name, parent_type='project')
        vmi3.set_virtual_network(vn1_obj)
        self._vnc_lib.virtual_machine_interface_create(vmi3)

        fq_name = ['default-domain', 'default-project', 'vmi4-' + self.id()]
        vmi4 = VirtualMachineInterface(fq_name=fq_name, parent_type='project')
        vmi4.set_virtual_network(vn2_obj)
        self._vnc_lib.virtual_machine_interface_create(vmi4)

        lr.add_virtual_machine_interface(vmi3)
        lr.add_virtual_machine_interface(vmi4)

        lr_uuid = self._vnc_lib.logical_router_create(lr)
        lr = self._vnc_lib.logical_router_read(id=lr_uuid)

        # pass the no of vpg's
        self.check_ri_count(2)
        # pass the vlans
        self.check_erb_content([101, 102])

        self._vnc_lib.logical_router_delete(fq_name=lr.get_fq_name())

        self._vnc_lib.virtual_machine_interface_delete(fq_name=vmi3.get_fq_name())
        self._vnc_lib.virtual_machine_interface_delete(fq_name=vmi4.get_fq_name())

        self._vnc_lib.virtual_machine_interface_delete(fq_name=vmi1.get_fq_name())
        self._vnc_lib.virtual_machine_delete(fq_name=vm1.get_fq_name())
        self._vnc_lib.physical_interface_delete(fq_name=pi1[0].get_fq_name())

        self._vnc_lib.virtual_machine_interface_delete(fq_name=vmi2.get_fq_name())
        self._vnc_lib.virtual_machine_delete(fq_name=vm2.get_fq_name())
        self._vnc_lib.physical_interface_delete(fq_name=pi2[0].get_fq_name())

        self.delete_routers(None, pr)
        self.wait_for_routers_delete(None, pr.get_fq_name())
        self._vnc_lib.bgp_router_delete(fq_name=bgp_router.get_fq_name())

        self._vnc_lib.virtual_network_delete(fq_name=vn1_obj.get_fq_name())
        self._vnc_lib.virtual_network_delete(fq_name=vn2_obj.get_fq_name())

        self._vnc_lib.role_config_delete(fq_name=rc.get_fq_name())
        self._vnc_lib.node_profile_delete(fq_name=np.get_fq_name())
        self._vnc_lib.fabric_delete(fq_name=fabric.get_fq_name())
        self._vnc_lib.job_template_delete(fq_name=jt.get_fq_name())

        self.delete_role_definitions()
        self.delete_overlay_roles()
        self.delete_physical_roles()
        self.delete_features()
        self.wait_for_features_delete()

    def test_erb_config_push_single_vmi(self):
        self.set_encapsulation_priorities(['VXLAN', 'MPLSoUDP'])
        project = self._vnc_lib.project_read(fq_name=['default-domain',
                                                      'default-project'])
        project.set_vxlan_routing(True)
        self._vnc_lib.project_update(project)

        self.create_features(['overlay-bgp', 'l2-gateway',
                              'l3-gateway', 'vn-interconnect'])
        self.create_physical_roles(['leaf', 'spine'])
        self.create_overlay_roles(['erb-ucast-gateway', 'crb-mcast-gateway'])
        self.create_role_definitions([
            AttrDict({
                'name': 'erb@leaf',
                'physical_role': 'leaf',
                'overlay_role': 'erb-ucast-gateway',
                'features': ['overlay-bgp', 'l2-gateway',
                             'l3-gateway', 'vn-interconnect'],
                'feature_configs': {'l3_gateway': {'use_gateway_ip': 'True'}}
            })
        ])

        jt = self.create_job_template('job-template-1')
        fabric = self.create_fabric('test-fabric')
        np, rc = self.create_node_profile('node-profile-1',
                                          device_family='junos-qfx',
                                          role_mappings=[
                                              AttrDict(
                                                  {'physical_role': 'leaf',
                                                   'rb_roles': ['erb-ucast-gateway']}
                                              )],
                                          job_template=jt)

        vn1_obj = self.create_vn('1', '1.1.1.0')
        vn2_obj = self.create_vn('2', '2.2.2.0')

        bgp_router, pr = self.create_router('router' + self.id(), '1.1.1.1',
                                            product='qfx5110', family='junos-qfx',
                                            role='leaf', rb_roles=['erb-ucast-gateway'],
                                            physical_role=self.physical_roles['leaf'],
                                            overlay_role=self.overlay_roles['erb-ucast-gateway'], fabric=fabric,
                                            node_profile=np)
        pr.set_physical_router_loopback_ip('10.10.0.1')
        self._vnc_lib.physical_router_update(pr)

        vmi1, vm1, pi1 = self.attach_vmi('1', ['xe-0/0/1'], [pr], vn1_obj, None, fabric, 101)

        lr_fq_name = ['default-domain', 'default-project', 'lr-' + self.id()]
        lr = LogicalRouter(fq_name=lr_fq_name, parent_type='project',
                           logical_router_type='vxlan-routing',
                           vxlan_network_identifier='3000')
        lr.set_physical_router(pr)

        fq_name = ['default-domain', 'default-project', 'vmi3-' + self.id()]
        vmi3 = VirtualMachineInterface(fq_name=fq_name, parent_type='project')
        vmi3.set_virtual_network(vn1_obj)
        self._vnc_lib.virtual_machine_interface_create(vmi3)

        fq_name = ['default-domain', 'default-project', 'vmi4-' + self.id()]
        vmi4 = VirtualMachineInterface(fq_name=fq_name, parent_type='project')
        vmi4.set_virtual_network(vn2_obj)
        self._vnc_lib.virtual_machine_interface_create(vmi4)

        lr.add_virtual_machine_interface(vmi3)
        lr.add_virtual_machine_interface(vmi4)

        lr_uuid = self._vnc_lib.logical_router_create(lr)
        lr = self._vnc_lib.logical_router_read(id=lr_uuid)

        # pass number of vpg
        self.check_ri_count(1)
        # pass the vlans
        self.check_erb_content([101])

        self._vnc_lib.logical_router_delete(fq_name=lr.get_fq_name())

        self._vnc_lib.virtual_machine_interface_delete(fq_name=vmi3.get_fq_name())
        self._vnc_lib.virtual_machine_interface_delete(fq_name=vmi4.get_fq_name())

        self._vnc_lib.virtual_machine_interface_delete(fq_name=vmi1.get_fq_name())
        self._vnc_lib.virtual_machine_delete(fq_name=vm1.get_fq_name())
        self._vnc_lib.physical_interface_delete(fq_name=pi1[0].get_fq_name())

        self.delete_routers(None, pr)
        self.wait_for_routers_delete(None, pr.get_fq_name())
        self._vnc_lib.bgp_router_delete(fq_name=bgp_router.get_fq_name())

        self._vnc_lib.virtual_network_delete(fq_name=vn1_obj.get_fq_name())
        self._vnc_lib.virtual_network_delete(fq_name=vn2_obj.get_fq_name())

        self._vnc_lib.role_config_delete(fq_name=rc.get_fq_name())
        self._vnc_lib.node_profile_delete(fq_name=np.get_fq_name())
        self._vnc_lib.fabric_delete(fq_name=fabric.get_fq_name())
        self._vnc_lib.job_template_delete(fq_name=jt.get_fq_name())

        self.delete_role_definitions()
        self.delete_overlay_roles()
        self.delete_physical_roles()
        self.delete_features()
        self.wait_for_features_delete()

    def test_erb_config_push_no_vmi(self):
        self.set_encapsulation_priorities(['VXLAN', 'MPLSoUDP'])
        project = self._vnc_lib.project_read(fq_name=['default-domain',
                                                      'default-project'])
        project.set_vxlan_routing(True)
        self._vnc_lib.project_update(project)

        self.create_features(['overlay-bgp', 'l2-gateway',
                              'l3-gateway', 'vn-interconnect'])
        self.create_physical_roles(['leaf', 'spine'])
        self.create_overlay_roles(['erb-ucast-gateway', 'crb-mcast-gateway'])
        self.create_role_definitions([
            AttrDict({
                'name': 'erb@leaf',
                'physical_role': 'leaf',
                'overlay_role': 'erb-ucast-gateway',
                'features': ['overlay-bgp', 'l2-gateway',
                             'l3-gateway', 'vn-interconnect'],
                'feature_configs': {'l3_gateway': {'use_gateway_ip': 'True'}}
            })
        ])

        jt = self.create_job_template('job-template-1')
        fabric = self.create_fabric('test-fabric')
        np, rc = self.create_node_profile('node-profile-1',
                                          device_family='junos-qfx',
                                          role_mappings=[
                                              AttrDict(
                                                  {'physical_role': 'leaf',
                                                   'rb_roles': ['erb-ucast-gateway']}
                                              )],
                                          job_template=jt)

        vn1_obj = self.create_vn('1', '1.1.1.0')
        vn2_obj = self.create_vn('2', '2.2.2.0')

        bgp_router, pr = self.create_router('router' + self.id(), '1.1.1.1',
                                            product='qfx5110', family='junos-qfx',
                                            role='leaf', rb_roles=['erb-ucast-gateway'],
                                            physical_role=self.physical_roles['leaf'],
                                            overlay_role=self.overlay_roles['erb-ucast-gateway'], fabric=fabric,
                                            node_profile=np)
        pr.set_physical_router_loopback_ip('10.10.0.1')
        self._vnc_lib.physical_router_update(pr)

        lr_fq_name = ['default-domain', 'default-project', 'lr-' + self.id()]
        lr = LogicalRouter(fq_name=lr_fq_name, parent_type='project',
                           logical_router_type='vxlan-routing',
                           vxlan_network_identifier='3000')
        lr.set_physical_router(pr)

        fq_name = ['default-domain', 'default-project', 'vmi3-' + self.id()]
        vmi3 = VirtualMachineInterface(fq_name=fq_name, parent_type='project')
        vmi3.set_virtual_network(vn1_obj)
        self._vnc_lib.virtual_machine_interface_create(vmi3)

        fq_name = ['default-domain', 'default-project', 'vmi4-' + self.id()]
        vmi4 = VirtualMachineInterface(fq_name=fq_name, parent_type='project')
        vmi4.set_virtual_network(vn2_obj)
        self._vnc_lib.virtual_machine_interface_create(vmi4)

        lr.add_virtual_machine_interface(vmi3)
        lr.add_virtual_machine_interface(vmi4)

        lr_uuid = self._vnc_lib.logical_router_create(lr)
        lr = self._vnc_lib.logical_router_read(id=lr_uuid)

        # pass number of vpg's as argument
        self.check_ri_count(0)

        self._vnc_lib.logical_router_delete(fq_name=lr.get_fq_name())

        self._vnc_lib.virtual_machine_interface_delete(fq_name=vmi3.get_fq_name())
        self._vnc_lib.virtual_machine_interface_delete(fq_name=vmi4.get_fq_name())

        self.delete_routers(None, pr)
        self.wait_for_routers_delete(None, pr.get_fq_name())
        self._vnc_lib.bgp_router_delete(fq_name=bgp_router.get_fq_name())

        self._vnc_lib.virtual_network_delete(fq_name=vn1_obj.get_fq_name())
        self._vnc_lib.virtual_network_delete(fq_name=vn2_obj.get_fq_name())

        self._vnc_lib.role_config_delete(fq_name=rc.get_fq_name())
        self._vnc_lib.node_profile_delete(fq_name=np.get_fq_name())
        self._vnc_lib.fabric_delete(fq_name=fabric.get_fq_name())
        self._vnc_lib.job_template_delete(fq_name=jt.get_fq_name())

        self.delete_role_definitions()
        self.delete_overlay_roles()
        self.delete_physical_roles()
        self.delete_features()
        self.wait_for_features_delete()

    # test for only VPGs and no LR
    def test_erb_config_push_no_lr(self):
        self.set_encapsulation_priorities(['VXLAN', 'MPLSoUDP'])
        project = self._vnc_lib.project_read(fq_name=['default-domain',
                                                      'default-project'])
        project.set_vxlan_routing(True)
        self._vnc_lib.project_update(project)

        self.create_features(['overlay-bgp', 'l2-gateway',
                              'l3-gateway', 'vn-interconnect'])
        self.create_physical_roles(['leaf', 'spine'])
        self.create_overlay_roles(['erb-ucast-gateway', 'crb-mcast-gateway'])
        self.create_role_definitions([
            AttrDict({
                'name': 'erb@leaf',
                'physical_role': 'leaf',
                'overlay_role': 'erb-ucast-gateway',
                'features': ['overlay-bgp', 'l2-gateway',
                             'l3-gateway', 'vn-interconnect'],
                'feature_configs': {'l3_gateway': {'use_gateway_ip': 'True'}}
            })
        ])

        jt = self.create_job_template('job-template-1')
        fabric = self.create_fabric('test-fabric')
        np, rc = self.create_node_profile('node-profile-1',
                                          device_family='junos-qfx',
                                          role_mappings=[
                                              AttrDict(
                                                  {'physical_role': 'leaf',
                                                   'rb_roles': ['erb-ucast-gateway']}
                                              )],
                                          job_template=jt)

        vn1_obj = self.create_vn('1', '1.1.1.0')
        vn2_obj = self.create_vn('2', '2.2.2.0')

        bgp_router, pr = self.create_router('router' + self.id(), '1.1.1.1',
                                            product='qfx5110', family='junos-qfx',
                                            role='leaf', rb_roles=['erb-ucast-gateway'],
                                            physical_role=self.physical_roles['leaf'],
                                            overlay_role=self.overlay_roles['erb-ucast-gateway'], fabric=fabric,
                                            node_profile=np)
        pr.set_physical_router_loopback_ip('10.10.0.1')
        self._vnc_lib.physical_router_update(pr)

        vmi1, vm1, pi1 = self.attach_vmi('1', ['xe-0/0/1'], [pr], vn1_obj, None, fabric, 101)
        vmi2, vm2, pi2 = self.attach_vmi('2', ['xe-0/0/2'], [pr], vn2_obj, None, fabric, 102)

        fq_name = ['default-domain', 'default-project', 'vmi3-' + self.id()]
        vmi3 = VirtualMachineInterface(fq_name=fq_name, parent_type='project')
        vmi3.set_virtual_network(vn1_obj)
        self._vnc_lib.virtual_machine_interface_create(vmi3)

        fq_name = ['default-domain', 'default-project', 'vmi4-' + self.id()]
        vmi4 = VirtualMachineInterface(fq_name=fq_name, parent_type='project')
        vmi4.set_virtual_network(vn2_obj)
        self._vnc_lib.virtual_machine_interface_create(vmi4)

        self.check_no_lr(2, [101, 102])

        self._vnc_lib.virtual_machine_interface_delete(fq_name=vmi3.get_fq_name())
        self._vnc_lib.virtual_machine_interface_delete(fq_name=vmi4.get_fq_name())

        self._vnc_lib.virtual_machine_interface_delete(fq_name=vmi1.get_fq_name())
        self._vnc_lib.virtual_machine_delete(fq_name=vm1.get_fq_name())
        self._vnc_lib.physical_interface_delete(fq_name=pi1[0].get_fq_name())

        self._vnc_lib.virtual_machine_interface_delete(fq_name=vmi2.get_fq_name())
        self._vnc_lib.virtual_machine_delete(fq_name=vm2.get_fq_name())
        self._vnc_lib.physical_interface_delete(fq_name=pi2[0].get_fq_name())

        self.delete_routers(None, pr)
        self.wait_for_routers_delete(None, pr.get_fq_name())
        self._vnc_lib.bgp_router_delete(fq_name=bgp_router.get_fq_name())

        self._vnc_lib.virtual_network_delete(fq_name=vn1_obj.get_fq_name())
        self._vnc_lib.virtual_network_delete(fq_name=vn2_obj.get_fq_name())

        self._vnc_lib.role_config_delete(fq_name=rc.get_fq_name())
        self._vnc_lib.node_profile_delete(fq_name=np.get_fq_name())
        self._vnc_lib.fabric_delete(fq_name=fabric.get_fq_name())
        self._vnc_lib.job_template_delete(fq_name=jt.get_fq_name())

        self.delete_role_definitions()
        self.delete_overlay_roles()
        self.delete_physical_roles()
        self.delete_features()
        self.wait_for_features_delete()

# end Test_dm_erb

