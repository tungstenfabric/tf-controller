#
# Copyright (c) 2018 Juniper Networks, Inc. All rights reserved.
#

from __future__ import absolute_import

from attrdict import AttrDict
from cfgm_common.tests.test_common import retries
from cfgm_common.tests.test_common import retry_exc_handler
import gevent
from vnc_api.vnc_api import DataCenterInterconnect, FabricNamespace, \
    LogicalRouter, NamespaceValue, VirtualMachineInterface

from .test_dm_ansible_common import TestAnsibleCommonDM
from .test_dm_utils import FakeJobHandler


class TestDCI(TestAnsibleCommonDM):
    def init_fabric_prs(self):
        self.features = {}
        self.role_definitions = {}
        self.feature_configs = []
        self.job_templates = []
        self.fabrics = []
        self.bgp_routers = []
        self.node_profiles = []
        self.role_configs = []
        self.physical_routers = []
        self.set_encapsulation_priorities(['VXLAN', 'MPLSoUDP'])
        project = self._vnc_lib.project_read(fq_name=['default-domain',
                                                      'default-project'])
        project.set_vxlan_routing(True)
        self._vnc_lib.project_update(project)
        self.create_physical_roles(['spine'])
        self.create_features(['overlay-bgp', 'l2-gateway', 'l3-gateway',
                              'vn-interconnect'])
        self.create_overlay_roles(['DCI-Gateway'])
        self.create_role_definitions([
            AttrDict({
                'name': 'dci@spine',
                'physical_role': 'spine',
                'overlay_role': 'DCI-Gateway',
                'features': ['overlay-bgp', 'l2-gateway', 'l3-gateway',
                             'vn-interconnect'],
                'feature_configs': {'l3_gateway': {'use_gateway_ip': 'True'}}
            }),
        ])
    # end _init_fabric_prs

    def test_dci_ibgp(self):
        self.init_fabric_prs()

        jt1 = self.create_job_template('job-template-1' + self.id())

        fabric1 = self.create_fabric('fab1' + self.id())
        asn = 64512
        ns_fq_name = fabric1.fq_name + ["test_dci"]
        fabric_namespace1 = FabricNamespace(
            name='test_dci', fq_name=ns_fq_name, parent_type='fabric',
            fabric_namespace_type='ASN',
            fabric_namespace_value=NamespaceValue(asn={'asn': [asn]}))
        self._vnc_lib.fabric_namespace_create(fabric_namespace1)

        fabric2 = self.create_fabric('fab2' + self.id())
        ns_fq_name2 = fabric2.fq_name + ["test_dci"]
        fabric_namespace2 = FabricNamespace(
            name='test_dci2', fq_name=ns_fq_name2, parent_type='fabric',
            fabric_namespace_type='ASN',
            fabric_namespace_value=NamespaceValue(asn={'asn': [asn]}))
        self._vnc_lib.fabric_namespace_create(fabric_namespace2)

        np1, rc1 = self.create_node_profile(
            'node-profile-dci-1' + self.id(),
            device_family='junos-qfx',
            role_mappings=[
                AttrDict(
                    {
                        'physical_role': 'spine',
                        'rb_roles': ['DCI-Gateway']
                    }
                )],
            job_template=jt1)

        br1, pr1 = self.create_router(
            'device-1' + self.id(), '7.7.7.7', product='qfx10002',
            family='junos-qfx', role='spine', ignore_bgp=False,
            rb_roles=['DCI-Gateway'],
            physical_role=self.physical_roles['spine'],
            overlay_role=self.overlay_roles['DCI-Gateway'],
            fabric=fabric1, node_profile=np1, loopback_ip='30.30.0.22',
            asn_id=asn, set_local_asn=True)
        self._vnc_lib.physical_router_update(pr1)

        br2, pr2 = self.create_router(
            'device-2' + self.id(), '7.7.7.8', product='qfx10002',
            family='junos-qfx', role='spine',
            rb_roles=['DCI-Gateway'],
            physical_role=self.physical_roles['spine'],
            overlay_role=self.overlay_roles['DCI-Gateway'],
            fabric=fabric2, node_profile=np1, loopback_ip='30.30.0.23',
            asn_id=asn, set_local_asn=True)
        self._vnc_lib.physical_router_update(pr2)

        vn1_obj = self.create_vn('1', '1.1.1.0')

        lr_fq_name = ['default-domain', 'default-project',
                      'lr-1' + self.id()]
        lr = LogicalRouter(fq_name=lr_fq_name, parent_type='project',
                           logical_router_type='vxlan-routing',
                           vxlan_network_identifier='3000')
        lr.set_physical_router(pr1)

        fq_name = ['default-domain', 'default-project', 'vmi3-' + self.id()]
        vmi3 = VirtualMachineInterface(fq_name=fq_name, parent_type='project')
        vmi3.set_virtual_network(vn1_obj)
        self._vnc_lib.virtual_machine_interface_create(vmi3)
        lr.add_virtual_machine_interface(vmi3)

        lr_uuid = self._vnc_lib.logical_router_create(lr)
        lr = self._vnc_lib.logical_router_read(id=lr_uuid)

        vn2_obj = self.create_vn('2', '2.2.2.0')

        lr2_fq_name = ['default-domain', 'default-project',
                       'lr-2' + self.id()]
        lr2 = LogicalRouter(fq_name=lr2_fq_name, parent_type='project',
                            logical_router_type='vxlan-routing',
                            vxlan_network_identifier='4000')
        lr2.set_physical_router(pr2)

        fq2_name = ['default-domain', 'default-project', 'vmi4-' + self.id()]
        vmi4 = VirtualMachineInterface(fq_name=fq2_name,
                                       parent_type='project')
        vmi4.set_virtual_network(vn2_obj)
        self._vnc_lib.virtual_machine_interface_create(vmi4)
        lr2.add_virtual_machine_interface(vmi4)

        lr2_uuid = self._vnc_lib.logical_router_create(lr2)
        lr2 = self._vnc_lib.logical_router_read(id=lr2_uuid)

        dci = DataCenterInterconnect("test-dci")
        dci.add_logical_router(lr)
        dci.add_logical_router(lr2)
        self._vnc_lib.data_center_interconnect_create(dci)

        self.validate_abstract_configs_ibgp(pr1, pr2, lr, lr2)

        self._vnc_lib.data_center_interconnect_delete(fq_name=dci.fq_name)
        self._vnc_lib.logical_router_delete(fq_name=lr.fq_name)
        self._vnc_lib.logical_router_delete(fq_name=lr2.fq_name)
        self.delete_objects()

    def test_dci_ebgp(self):
        self.init_fabric_prs()
        jt1 = self.create_job_template('job-template-1' + self.id())
        fabric1 = self.create_fabric('fab1' + self.id())
        asn = 64599
        ns_fq_name = fabric1.fq_name + ["overlay_ibgp_asn"]
        fabric_namespace1 = FabricNamespace(
            name='overlay_ibgp_asn', fq_name=ns_fq_name, parent_type='fabric',
            fabric_namespace_type='ASN',
            fabric_namespace_value=NamespaceValue(asn={'asn': [asn]}))
        self._vnc_lib.fabric_namespace_create(fabric_namespace1)

        fabric2 = self.create_fabric('fab2' + self.id())
        ns_fq_name2 = fabric2.fq_name + ["overlay_ibgp_asn"]
        fabric_namespace2 = FabricNamespace(
            name='overlay_ibgp_asn', fq_name=ns_fq_name2,
            parent_type='fabric', fabric_namespace_type='ASN',
            fabric_namespace_value=NamespaceValue(asn={'asn': ['64598']}))
        self._vnc_lib.fabric_namespace_create(fabric_namespace2)

        np1, rc1 = self.create_node_profile(
            'node-profile-dci-1' + self.id(),
            device_family='junos-qfx',
            role_mappings=[
                AttrDict(
                    {
                        'physical_role': 'spine',
                        'rb_roles': ['DCI-Gateway']
                    }
                )],
            job_template=jt1)

        br1, pr1 = self.create_router(
            'device-1' + self.id(), '7.7.7.7', product='qfx10002',
            family='junos-qfx', role='spine',
            rb_roles=['DCI-Gateway'],
            physical_role=self.physical_roles['spine'],
            overlay_role=self.overlay_roles['DCI-Gateway'],
            fabric=fabric1, node_profile=np1, loopback_ip='30.30.0.22',
            asn_id=asn, set_local_asn=True)
        self._vnc_lib.physical_router_update(pr1)

        br2, pr2 = self.create_router(
            'device-2' + self.id(), '7.7.7.8', product='qfx10002',
            family='junos-qfx', role='spine',
            rb_roles=['DCI-Gateway'],
            physical_role=self.physical_roles['spine'],
            overlay_role=self.overlay_roles['DCI-Gateway'],
            fabric=fabric2, node_profile=np1, loopback_ip='30.30.0.23',
            asn_id='64598', set_local_asn=True)
        self._vnc_lib.physical_router_update(pr2)

        vn1_obj = self.create_vn('1', '1.1.1.0')

        lr_fq_name = ['default-domain', 'default-project', 'lr-1' + self.id()]
        lr = LogicalRouter(fq_name=lr_fq_name, parent_type='project',
                           logical_router_type='vxlan-routing',
                           vxlan_network_identifier='3000')
        lr.set_physical_router(pr1)

        fq_name = ['default-domain', 'default-project', 'vmi3-' + self.id()]
        vmi3 = VirtualMachineInterface(fq_name=fq_name, parent_type='project')
        vmi3.set_virtual_network(vn1_obj)
        self._vnc_lib.virtual_machine_interface_create(vmi3)
        lr.add_virtual_machine_interface(vmi3)

        lr_uuid = self._vnc_lib.logical_router_create(lr)
        lr = self._vnc_lib.logical_router_read(id=lr_uuid)

        vn2_obj = self.create_vn('2', '2.2.2.0')

        lr2_fq_name = ['default-domain', 'default-project',
                       'lr-2' + self.id()]
        lr2 = LogicalRouter(fq_name=lr2_fq_name, parent_type='project',
                            logical_router_type='vxlan-routing',
                            vxlan_network_identifier='4000')
        lr2.set_physical_router(pr2)

        fq2_name = ['default-domain', 'default-project', 'vmi4-' + self.id()]
        vmi4 = VirtualMachineInterface(fq_name=fq2_name,
                                       parent_type='project')
        vmi4.set_virtual_network(vn2_obj)
        self._vnc_lib.virtual_machine_interface_create(vmi4)
        lr2.add_virtual_machine_interface(vmi4)

        lr2_uuid = self._vnc_lib.logical_router_create(lr2)
        lr2 = self._vnc_lib.logical_router_read(id=lr2_uuid)

        dci = DataCenterInterconnect("test-dci")
        dci.add_logical_router(lr)
        dci.add_logical_router(lr2)
        self._vnc_lib.data_center_interconnect_create(dci)

        self.validate_abstract_configs_ebgp(pr1, pr2, lr, lr2)

        self._vnc_lib.data_center_interconnect_delete(fq_name=dci.fq_name)
        self._vnc_lib.logical_router_delete(fq_name=lr.fq_name)
        self._vnc_lib.logical_router_delete(fq_name=lr2.fq_name)
        self.delete_objects()
        self._vnc_lib.virtual_network_delete(fq_name=vn1_obj.fq_name)
        self._vnc_lib.virtual_network_delete(fq_name=vn2_obj.fq_name)

    @retries(5, hook=retry_exc_handler)
    def validate_abstract_configs_ebgp(self, pr1, pr2, lr, lr2):
        ri = []
        ri = self.get_target(lr)
        ri.append(self.get_target(lr2)[0])
        pr1.set_physical_router_product_name('qfx10002a')
        self._vnc_lib.physical_router_update(pr1)

        ac1 = FakeJobHandler.get_dev_job_input(pr1.name)
        dac1 = ac1.get('device_abstract_config')
        bgp_config = dac1.get('features', {}).get(
            'overlay-bgp', {}).get('bgp', [])
        for bgp in bgp_config:
            if 'fab2' in bgp.get('name', ''):
                bgp_config1 = bgp
                break
        bgp_peer1 = bgp_config1.get('peers', [])
        asn_config1 = dac1.get('features', {}).get('vn-interconnect', {}).get(
            'routing_instances', [])
        asn_import = asn_config1[0].get('import_targets')
        asn_import.sort()
        ri.sort()
        self.assertEqual(bgp_config1.get('ip_address'), '30.30.0.22')
        self.assertEqual(bgp_peer1[0].get('ip_address'), '30.30.0.23')
        self.assertEqual(bgp_config1.get('type_'), 'external')
        self.assertEqual(asn_import, ri)

        pr2.set_physical_router_product_name('qfx10002b')
        self._vnc_lib.physical_router_update(pr2)
        ac2 = FakeJobHandler.get_dev_job_input(pr2.name)
        dac2 = ac2.get('device_abstract_config')
        bgp_config = dac2.get('features', {}).get(
            'overlay-bgp', {}).get('bgp', [])
        for bgp in bgp_config:
            if 'fab1' in bgp.get('name', ''):
                bgp_config2 = bgp
                break
        bgp_peer2 = bgp_config2.get('peers', [])
        asn_config2 = dac2.get('features', {}).get('vn-interconnect', {}).get(
            'routing_instances', [])
        asn_import2 = asn_config2[0].get('import_targets')
        asn_import2.sort()
        self.assertEqual(bgp_config2.get('ip_address'), '30.30.0.23')
        self.assertEqual(bgp_config2.get('type_'), 'external')
        self.assertEqual(bgp_peer2[0].get('ip_address'), '30.30.0.22')
        self.assertEqual(asn_import2, ri)

    @retries(5, hook=retry_exc_handler)
    def validate_abstract_configs_ibgp(self, pr1, pr2, lr, lr2):
        ri = []
        ri = self.get_target(lr)
        ri.append(self.get_target(lr2)[0])
        pr1.set_physical_router_product_name('qfx10002a')
        self._vnc_lib.physical_router_update(pr1)

        ac1 = FakeJobHandler.get_dev_job_input(pr1.name)
        dac1 = ac1.get('device_abstract_config')
        bgp_config = dac1.get('features', {}).get(
            'overlay-bgp', {}).get('bgp', [])
        for bgp in bgp_config:
            if 'fab2' in bgp.get('name', ''):
                bgp_config1 = bgp
                break
        bgp_peer1 = bgp_config1.get('peers', [])
        asn_config1 = dac1.get('features', {}).get('vn-interconnect', {}).get(
            'routing_instances', [])
        asn_import = asn_config1[0].get('import_targets')
        asn_import.sort()
        ri.sort()
        self.assertEqual(bgp_config1.get('ip_address'), '30.30.0.22')
        self.assertEqual(bgp_peer1[0].get('ip_address'), '30.30.0.23')
        self.assertEqual(asn_import, ri)

        pr2.set_physical_router_product_name('qfx10002b')
        self._vnc_lib.physical_router_update(pr2)
        ac2 = FakeJobHandler.get_dev_job_input(pr2.name)
        dac2 = ac2.get('device_abstract_config')
        bgp_config = dac2.get('features', {}).get(
            'overlay-bgp', {}).get('bgp', [])
        for bgp in bgp_config:
            if 'fab1' in bgp.get('name', ''):
                bgp_config2 = bgp
                break
        bgp_peer2 = bgp_config2.get('peers', [])
        asn_config2 = dac2.get('features', {}).get('vn-interconnect', {}).get(
            'routing_instances', [])
        asn_import2 = asn_config2[0].get('import_targets')
        asn_import2.sort()
        self.assertEqual(bgp_config2.get('ip_address'), '30.30.0.23')
        self.assertEqual(bgp_peer2[0].get('ip_address'), '30.30.0.22')
        self.assertEqual(asn_import2, ri)

    def get_val(self, my_dict, key_exp):
        for key, value in my_dict.items():
            if key == key_exp:
                return value
        return "value doesn't exist"

    def get_target(self, lr):
        lr_refs = lr.get_virtual_network_refs()
        vn_uuid = self.get_val(lr_refs[0], 'uuid')
        vn = self._vnc_lib.virtual_network_read(id=vn_uuid)
        vn_refs = vn.get_routing_instances()
        ri_uuid = self.get_val(vn_refs[0], 'uuid')
        ri_obj = self._vnc_lib.routing_instance_read(id=ri_uuid)
        ri_refs = ri_obj.get_route_target_refs()
        return self.get_val(ri_refs[0], 'to')

    @retries(5, hook=retry_exc_handler)
    def delete_objects(self):
        vmi_list = self._vnc_lib.virtual_machine_interfaces_list().get(
            'virtual-machine-interfaces', [])
        for vmi in vmi_list:
            self._vnc_lib.virtual_machine_interface_delete(id=vmi['uuid'])
        instance_ip_list = self._vnc_lib.instance_ips_list().get(
            'instance-ips', [])
        for ip in instance_ip_list:
            self._vnc_lib.instance_ip_delete(id=ip['uuid'])
        logical_interfaces_list = self._vnc_lib.logical_interfaces_list().get(
            'logical-interfaces', [])
        for logical_interface in logical_interfaces_list:
            self._vnc_lib.logical_interface_delete(
                id=logical_interface['uuid'])
        pi_list = self._vnc_lib.physical_interfaces_list().get(
            'physical-interfaces', [])
        for pi in pi_list:
            self._vnc_lib.physical_interface_delete(id=pi['uuid'])
        pr_list = self._vnc_lib.physical_routers_list().get(
            'physical-routers', [])
        for pr in pr_list:
            self._vnc_lib.physical_router_delete(id=pr['uuid'])
        bgpr_list = self._vnc_lib.bgp_routers_list().get('bgp-routers', [])
        for br in bgpr_list:
            self._vnc_lib.bgp_router_delete(id=br['uuid'])
        rc_list = self._vnc_lib.role_configs_list().get('role-configs', [])
        for rc in rc_list:
            self._vnc_lib.role_config_delete(id=rc['uuid'])
        nodes_list = self._vnc_lib.nodes_list().get('nodes', [])
        for node in nodes_list:
            self._vnc_lib.node_delete(id=node['uuid'])
        fabric_namespace_list = self._vnc_lib.fabric_namespaces_list().get(
            'fabric-namespaces', [])
        for fabric_namespace in fabric_namespace_list:
            self._vnc_lib.fabric_namespace_delete(id=fabric_namespace['uuid'])
        fab_list = self._vnc_lib.fabrics_list().get('fabrics', [])
        for fab in fab_list:
            self._vnc_lib.fabric_delete(id=fab['uuid'])
        np_list = self._vnc_lib.node_profiles_list().get('node-profiles', [])
        for np in np_list:
            self._vnc_lib.node_profile_delete(id=np['uuid'])
        jt_list = self._vnc_lib.job_templates_list().get('job-templates', [])
        for jt in jt_list:
            self._vnc_lib.job_template_delete(id=jt['uuid'])
        self.delete_role_definitions()
        self.delete_overlay_roles()
        self.delete_physical_roles()
        self.delete_features()
        self.wait_for_features_delete()
