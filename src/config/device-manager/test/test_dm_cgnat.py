#
# Copyright (c) 2020 Juniper Networks, Inc. All rights reserved.
#

from __future__ import absolute_import

from attrdict import AttrDict
from cfgm_common.tests.test_common import retries
from cfgm_common.tests.test_common import retry_exc_handler
from vnc_api.vnc_api import *
from .test_dm_ansible_common import TestAnsibleCommonDM
from vnc_api.gen.resource_xsd import LogicalRouterVirtualNetworkType
from device_manager.device_manager import DeviceManager
import json


class TestAnsibleCGNATDM(TestAnsibleCommonDM):

    def test_mx_public_lr_cgnat(self):
        self._create_basic_object()

        attr_obj = LogicalRouterVirtualNetworkType('NAPTSourcePool')

        self.pr.set_physical_router_junos_service_ports({
            'service_port': [
                "ms-0/0/0"
            ]
        })
        self._vnc_lib.physical_router_update(self.pr)

        self._vnc_lib.ref_update("logical_router", self.lr.uuid,
                                 "virtual_network", self.vn2_obj.uuid,
                                 self.vn2_obj.fq_name, "ADD", attr_obj)

        # validate the CGNAT specific details.
        self._validate_cgnat('ms-0/0/0',
                             self.vn2_obj.get_virtual_network_network_id(),
                             subnet='2.2.2.0/24', check_source_pool=True)

        # Start the clean up
        self._delete_objects()

    def _delete_objects(self):
        self._vnc_lib.logical_router_delete(id=self.lr.uuid)
        self._vnc_lib.virtual_machine_interface_delete(
            fq_name=self.vmi1.get_fq_name())
        self._vnc_lib.virtual_machine_delete(fq_name=self.vm1.get_fq_name())
        self._vnc_lib.physical_interface_delete(fq_name=self.pi1[
            0].get_fq_name())

        self.delete_routers(None, self.pr)
        self.wait_for_routers_delete(None, self.pr.get_fq_name())
        self._vnc_lib.bgp_router_delete(fq_name=self.bgp_router.get_fq_name())

        self._vnc_lib.virtual_network_delete(
            fq_name=self.vn1_obj.get_fq_name())
        self._vnc_lib.virtual_network_delete(
            fq_name=self.vn2_obj.get_fq_name())

        self._vnc_lib.role_config_delete(fq_name=self.rc.get_fq_name())
        self._vnc_lib.node_profile_delete(fq_name=self.np.get_fq_name())
        self._vnc_lib.fabric_delete(fq_name=self.fabric.get_fq_name())
        self._vnc_lib.job_template_delete(fq_name=self.jt.get_fq_name())

        self.delete_role_definitions()
        self.delete_overlay_roles()
        self.delete_physical_roles()
        self.delete_features()
        self.wait_for_features_delete()

    def _create_basic_object(self):
        self.set_encapsulation_priorities(['VXLAN', 'MPLSoUDP'])
        project = self._vnc_lib.project_read(fq_name=['default-domain',
                                                      'default-project'])
        project.set_vxlan_routing(True)
        self._vnc_lib.project_update(project)

        self.create_features(['overlay-bgp', 'l2-gateway',
                              'l3-gateway', 'vn-interconnect', 'dc-gateway'])
        self.create_physical_roles(['leaf', 'spine'])
        self.create_overlay_roles(['dc-gateway'])
        self.create_role_definitions([
            AttrDict({
                'name': 'dc@leaf',
                'physical_role': 'leaf',
                'overlay_role': 'dc-gateway',
                'features': ['overlay-bgp', 'l2-gateway',
                             'l3-gateway', 'vn-interconnect', 'dc-gateway'],
                'feature_configs': {'l3_gateway': {'use_gateway_ip': 'True'}}
            })
        ])

        self.jt = self.create_job_template('job-template-1')
        self.fabric = self.create_fabric('test-fabric')
        self.np, self.rc = self.create_node_profile('node-profile-1',
                                          device_family='junos',
                                          role_mappings=[
                                              AttrDict(
                                                  {'physical_role': 'leaf',
                                                   'rb_roles': [
                                                       'dc-gateway']}
                                              )],
                                          job_template=self.jt)

        self.vn1_obj = self.create_vn('1', '1.1.1.0')
        self.vn2_obj = self.create_vn('2', '2.2.2.0')

        self.bgp_router, self.pr = self.create_router('router' + self.id(),
                                                '1.1.1.1',
                                            product='mx240', family='junos',
                                            role='leaf',
                                            rb_roles=['dc-gateway'],
                                            physical_role=self.physical_roles[
                                                'leaf'],
                                            overlay_role=self.overlay_roles[
                                                'dc-gateway'],
                                            fabric=self.fabric,
                                            node_profile=self.np)
        self.pr.set_physical_router_loopback_ip('10.10.0.1')

        self.vmi1, self.vm1, self.pi1 = self.attach_vmi('1', ['xe-0/0/1'],
                                                       [self.pr], self.vn1_obj,
                                         None,
                                         self.fabric, 100)

        lr_fq_name = ['default-domain', 'default-project', 'lr-' + self.id()]
        lr = LogicalRouter(fq_name=lr_fq_name, parent_type='project',
                           logical_router_type='vxlan-routing',
                           vxlan_network_identifier='3000',
                           logical_router_gateway_external=True)
        self.lr = lr
        lr.set_physical_router(self.pr)
        lr.add_virtual_machine_interface(self.vmi1)
        self._vnc_lib.logical_router_create(lr)

    @retries(5, hook=retry_exc_handler)
    def _validate_cgnat(self, nat_ifc, vn_network_id,
                        check_source_pool=False, subnet=None):
        ac = self.check_dm_ansible_config_push()
        self.assertIsNotNone(ac)
        fc = ac.get('device_abstract_config').get('features')
        dc_gateway_ri = fc.get('dc-gateway').get('routing_instances', [])
        self.assertNotEqual(len(dc_gateway_ri), 0)
        DeviceManager.get_instance().logger.warning("Job Input: %s" %
                                                  json.dumps(ac, indent=4))
        egress_ifc = "{}.{}".format(nat_ifc, 2*vn_network_id)
        inress_ifc = "{}.{}".format(nat_ifc, 2*vn_network_id-1)
        for ri in dc_gateway_ri:
            if 'nat_rules' in ri:
                nat_rules = ri['nat_rules']
                self.assertEquals(nat_rules['outside_interface'], egress_ifc)
                self.assertEquals(nat_rules['inside_interface'], inress_ifc)
                if check_source_pool:
                    self.assertEquals(nat_rules['address_pool'][
                                             'address'], subnet)
            if 'egress_interfaces' in ri:
                self.assertEquals(ri['egress_interfaces'][0]['name'],
                                  egress_ifc)
            if 'ingress_interfaces' in ri:
                self.assertEquals(ri['ingress_interfaces'][0]['name'],
                                  inress_ifc)
            if 'routing_interfaces' in ri:
                self.assertIsNotNone(ri['routing_interfaces'])
