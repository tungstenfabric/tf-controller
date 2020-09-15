#
# Copyright (c) 2020 Juniper Networks, Inc. All rights reserved.
#

from __future__ import absolute_import

from attrdict import AttrDict
from cfgm_common.tests.test_common import retries
from cfgm_common.tests.test_common import retry_exc_handler
import gevent
import mock
from vnc_api.vnc_api import DataCenterInterconnect, \
    IpamSubnetType, LogicalRouter, NetworkIpam, \
    SubnetType, VirtualMachineInterface, VirtualNetwork, \
    VirtualNetworkType, VnSubnetsType

from .test_dm_ansible_common import TestAnsibleCommonDM


class TestAnsibleDciGateway(TestAnsibleCommonDM):

    def setUp(self, extra_config_knobs=None):
        super(TestAnsibleDciGateway, self).setUp(
            extra_config_knobs=extra_config_knobs)
        self.idle_patch = mock.patch('gevent.idle')
        self.idle_mock = self.idle_patch.start()

    def tearDown(self):
        self.idle_patch.stop()
        super(TestAnsibleDciGateway, self).tearDown()

    def _delete_objects(self):
        for obj in self.physical_routers:
            self._vnc_lib.physical_router_delete(id=obj.get_uuid())
        for obj in self.bgp_routers:
            self._vnc_lib.bgp_router_delete(id=obj.get_uuid())
        for obj in self.role_configs:
            self._vnc_lib.role_config_delete(id=obj.get_uuid())
        for obj in self.node_profiles:
            self._vnc_lib.node_profile_delete(id=obj.get_uuid())
        for obj in self.fabrics:
            self._vnc_lib.fabric_delete(id=obj.get_uuid())
        for obj in self.job_templates:
            self._vnc_lib.job_template_delete(id=obj.get_uuid())

        self.delete_role_definitions()
        self.delete_features()
        self.delete_overlay_roles()
        self.delete_physical_roles()
    # end _delete_objects

    @retries(5, hook=retry_exc_handler)
    def check_lr_internal_vn_state(self, lr_obj):
        internal_vn_name = '__contrail_lr_internal_vn_' + lr_obj.uuid + '__'
        vn_fq = lr_obj.get_fq_name()[:-1] + [internal_vn_name]
        vn_obj = None
        vn_obj = self._vnc_lib.virtual_network_read(fq_name=vn_fq)
        vn_obj_properties = vn_obj.get_virtual_network_properties()
        if not vn_obj_properties:
            raise Exception("LR Internal VN properties are not set")
        fwd_mode = vn_obj_properties.get_forwarding_mode()
        if fwd_mode != 'l3':
            raise Exception("LR Internal VN Forwarding mode is not set to L3")
        return vn_obj
    # end check_lr_internal_vn_state

    def _init_fabric_prs(self):
        self.features = {}
        self.role_definitions = {}
        self.feature_configs = []

        self.job_templates = []
        self.fabrics = []
        self.bgp_routers = []
        self.node_profiles = []
        self.role_configs = []
        self.physical_routers = []
    # end _init_fabric_prs

    def _create_node_profile(self, name, device_family, role, rb_roles,
                             job_temp):
        np1, rc1 = self.create_node_profile(
            'node-profile-' + name,
            device_family=device_family,
            role_mappings=[
                AttrDict({
                    'physical_role': role,
                    'rb_roles': rb_roles
                })
            ],
            job_template=job_temp)
        self.node_profiles.append(np1)
        self.role_configs.append(rc1)
        return np1, rc1
    # end _create_node_profile

    def _create_fabrics_prs(self, dict_fabrics, dict_prs, name="DCI"):
        self._init_fabric_prs()
        self.create_features(['overlay-bgp'])
        self.create_physical_roles(['leaf', 'spine'])
        ov_roles = ['DCI-Gateway']

        self.create_overlay_roles(ov_roles)

        self.create_role_definitions([
            AttrDict({
                'name': 'dci-gateway@spine',
                'physical_role': 'spine',
                'overlay_role': 'DCI-Gateway',
                'features': ['overlay-bgp'],
                'feature_configs': None
            }),
            AttrDict({
                'name': 'dci-gateway@leaf',
                'physical_role': 'leaf',
                'overlay_role': 'DCI-Gateway',
                'features': ['overlay-bgp'],
                'feature_configs': None
            })
        ])

        jt = self.create_job_template('job-template-' + name + self.id())
        self.job_templates.append(jt)
        np_spine, rc_spine = self._create_node_profile(
            name + '-spine' + self.id(), 'junos-qfx',
            'spine', ['DCI-Gateway'], jt)
        np_leaf, rc_leaf = self._create_node_profile(
            name + '-leaf' + self.id(), 'junos-qfx',
            'leaf', ['DCI-Gateway'], jt)

        num = 32
        for f_name in dict_fabrics.keys():
            fabric = self.create_fabric(f_name + self.id())
            self.fabrics.append(fabric)
            dict_fabrics[f_name] = fabric
            for prname in dict_prs.keys():
                if f_name not in prname:
                    continue
                role = 'spine' if 'PR1_' in prname else 'leaf'
                np = np_spine if 'PR1_' in prname else np_leaf
                br, pr = self.create_router(
                    prname + self.id(), '7.7.7.%s' % num,
                    product='qfx10002' if 'PR1_' in prname else 'mx240',
                    family='junos-qfx' if 'PR1_' in prname else 'junos',
                    role=role,
                    rb_roles=['DCI-Gateway'],
                    physical_role=self.physical_roles[role],
                    overlay_role=self.overlay_roles['DCI-Gateway'],
                    fabric=fabric, node_profile=np)
                pr.set_physical_router_loopback_ip('30.30.0.%s' % num)
                num += 1
                self._vnc_lib.physical_router_update(pr)

                self.physical_routers.append(pr)
                self.bgp_routers.append(br)
                dict_prs[prname]["br"] = br
                dict_prs[prname]["pr"] = pr
        return
    # end _create_fabrics_prs

    def create_vn_ipam(self, id):
        ipam1_obj = NetworkIpam('ipam' + '-' + id)
        ipam1_uuid = self._vnc_lib.network_ipam_create(ipam1_obj)
        return self._vnc_lib.network_ipam_read(id=ipam1_uuid)
    # end create_vn_ipam

    def create_vn_with_subnets(self, id, vn_name, ipam_obj, subnet,
                               subnetmask=24):
        vn_obj = VirtualNetwork(vn_name)
        vn_obj_properties = VirtualNetworkType()
        vn_obj_properties.set_vxlan_network_identifier(2000 + id)
        vn_obj_properties.set_forwarding_mode('l2_l3')

        vn_obj.set_virtual_network_properties(vn_obj_properties)
        vn_obj.add_network_ipam(ipam_obj, VnSubnetsType(
            [IpamSubnetType(SubnetType(subnet, subnetmask))]))
        vn_uuid = self._vnc_lib.virtual_network_create(vn_obj)
        vn_obj_rd = self._vnc_lib.virtual_network_read(id=vn_uuid)
        # make sure RT for vn is created
        rt = []
        try:
            rt = self._get_route_target(vn_obj_rd)
        except Exception:
            pass
        return vn_obj, self._vnc_lib.virtual_network_read(id=vn_uuid), rt
    # end create_vn_with_subnets

    def make_vn_name(self, subnet):
        return "VN_%s" % subnet

    def make_lr_name(self, subnet1, pr_name):
        return "LR_%s_%s" % (subnet1, pr_name)

    def create_lr(self, lrname, vns, prs, vmis):
        lr_fq_name = ['default-domain', 'default-project', lrname]
        lr = LogicalRouter(fq_name=lr_fq_name, parent_type='project',
                           logical_router_type='vxlan-routing')
        for pr in prs:
            probj = self._vnc_lib.physical_router_read(id=pr.get_uuid())
            lr.add_physical_router(probj)
        for vn in vns:
            vminame = 'vmi-lr-to-vn' + vn.get_display_name()
            fq_name1 = ['default-domain', 'default-project', vminame]
            vmi = VirtualMachineInterface(fq_name=fq_name1,
                                          parent_type='project')
            vmi.set_virtual_network(vn)
            self._vnc_lib.virtual_machine_interface_create(vmi)
            vmis[vminame] = vmi
            lr.add_virtual_machine_interface(vmi)
        lr.set_logical_router_type('vxlan-routing')
        lr_uuid = self._vnc_lib.logical_router_create(lr)

        # make sure internal is created
        try:
            self.check_lr_internal_vn_state(lr)
        except Exception:
            pass
        return lr, self._vnc_lib.logical_router_read(id=lr_uuid)
    # end create_lr

    def _make_ri_comments(self, vn_obj, vrf_mode, fwd_mode="L2-L3",
                          prefix=' Public'):
        return "/*%s Virtual Network: %s, UUID: %s, VRF Type: %s, " \
               "Forwarding Mode: %s */" % \
               (prefix, vn_obj.get_fq_name()[-1], vn_obj.get_uuid(),
                vrf_mode, fwd_mode)
    # end _make_ri_comments

    @retries(4, hook=retry_exc_handler)
    def _get_route_target(self, vn_obj):
        ri_list = vn_obj.get_routing_instances() or []
        if len(ri_list) == 0:
            raise Exception("RI of vn %s is empty!!" %
                            vn_obj.get_fq_name()[-1])
        for ri in ri_list:
            ri_uuid = ri.get('uuid')
            riobj = self._vnc_lib.routing_instance_read(id=ri_uuid)
            if not riobj:
                continue
            rt_refs = riobj.get_route_target_refs() or []
            if len(rt_refs) == 0:
                raise Exception("RT of vn %s RI %s is empty!! Retrying..." %
                                (vn_obj.get_fq_name()[-1],
                                 riobj.get_fq_name()[-1]))
            for rt in rt_refs:
                return rt.get('to')[0]
        print("vn %s RT Empty!! Retrying..." % (vn_obj.get_fq_name()[-1]))
        return ''
    # end _get_route_target

    def get_dci_policy_name(self, obj):
        return "__contrail_%s_%s-import" % (
            obj.get_fq_name()[-1], obj.get_uuid())

    def get_dci_policy_comment(self, dci):
        return "/* %s DataCenter InterConnect: %s, UUID: %s */" % (
            dci.get_data_center_interconnect_mode(), dci.get_fq_name()[-1],
            dci.get_uuid())

    def get_asn_and_addr(self, obj):
        rd_obj = self._vnc_lib.bgp_router_read(id=obj.get_uuid())
        return rd_obj._bgp_router_parameters.autonomous_system, \
            rd_obj._bgp_router_parameters.address, \
            rd_obj._bgp_router_parameters.address_families.family, \
            rd_obj._bgp_router_parameters.hold_time

    def get_bgp_name(self, dci_name, l_asn, p_asn):
        return "_contrail_%s-%s" % (
            dci_name, 'e' if l_asn != p_asn else 'i')

    def create_bgp_policy(self, name, comment, import_targets):
        return {'name': name, 'comment': comment,
                'import_targets': import_targets}

    def create_bgp_config(self, name, l_addr, l_asn, l_family, l_hold_time):
        return {'name': name,
                'type_': 'external' if name.endswith('-e') else 'internal',
                'ip_address': l_addr,
                'autonomous_system': l_asn,
                'families': l_family,
                'hold_time': l_hold_time,
                'import_policy': [],
                'peers': [],
                'policies': []}

    def add_peers_to_bgp_config(self, config, p_address, p_asn):
        config['peers'].append({'ip_address': p_address,
                                'autonomous_system': p_asn})

    def _create_bgp_abstract_cfg(self, pr_name, dict_prs,
                                 dci_names, dict_dcis, dict_lrs,
                                 vnlist, dict_vns, dict_vn_rt):
        bgp_cfgs = {}
        l2 = False
        l3 = False
        l2_dci_name = ''
        l3_dci_name = ''
        l2_import_policy = []
        l3_import_policy = []
        l2_policies = []
        for name in dci_names:
            if 'l2' in name:
                l2 = True
                l2_dci_name = name
                for vn_name in vnlist:
                    policy_name = self.get_dci_policy_name(dict_vns[vn_name])
                    l2_policies.append(self.create_bgp_policy(
                        name=policy_name,
                        comment=self.get_dci_policy_comment(dict_dcis[name]),
                        import_targets=[dict_vn_rt[vn_name]]))
                    l2_import_policy.append(policy_name)
            elif 'l3' in name:
                l3 = True
                l3_dci_name = name
                for lr_name, obj in dict_lrs.items():
                    if pr_name in lr_name:
                        policy_name = self.get_dci_policy_name(obj)
                        l3_import_policy.append(policy_name)

        peer_fabric = 'fabric2' if 'fabric1' in pr_name else 'fabric1'
        peer_prs = []
        for name in dict_prs.keys():
            if peer_fabric in name:
                peer_prs.append(name)
        l_asn, l_addr, l_family, l_hold_time = \
            self.get_asn_and_addr(dict_prs[pr_name]['br'])
        if l2 == True and l3 == True:
            dci_names.sort()
            for peer_name in peer_prs:
                p_asn, p_addr, _, _ = self.get_asn_and_addr(
                    dict_prs[peer_name]['br'])
                import_policy = []
                # combination of mix peering policy are:
                # pr_name       L3_L2           L2
                # p1_f1         p1_f2           p2_f2
                # p2_f1         None            p1_f2, p2_f2
                # p1_f2         p1_f1           p2_f1
                # p2_f2         None            p1_f1, p2_f1
                if 'PR1_' in pr_name:
                    if 'PR1_' in peer_name:
                        bgp_name = self.get_bgp_name("-".join(dci_names),
                                                     l_asn, p_asn)
                        import_policy.extend(l3_import_policy)
                    else:
                        bgp_name = self.get_bgp_name(l2_dci_name, l_asn, p_asn)
                else:
                    bgp_name = self.get_bgp_name(l2_dci_name, l_asn, p_asn)
                import_policy.extend(l2_import_policy)
                policies = l2_policies
                if bgp_name not in bgp_cfgs:
                    bgp_cfgs[bgp_name] = self.create_bgp_config(
                        bgp_name, l_addr, l_asn, l_family, l_hold_time)
                    bgp_cfgs[bgp_name]['import_policy'].extend(import_policy)
                    bgp_cfgs[bgp_name]['policies'].extend(policies)
                self.add_peers_to_bgp_config(bgp_cfgs[bgp_name],
                                             p_addr, p_asn)
        elif l3 == True:
            if len(l3_import_policy) == 0:
                return bgp_cfgs
            for peer_name in peer_prs:
                if 'PR1_' not in peer_name:
                    continue
                p_asn, p_addr, _, _ = self.get_asn_and_addr(
                    dict_prs[peer_name]['br'])
                bgp_name = self.get_bgp_name(l3_dci_name, l_asn, p_asn)
                if bgp_name not in bgp_cfgs:
                    bgp_cfgs[bgp_name] = self.create_bgp_config(
                        bgp_name, l_addr, l_asn, l_family, l_hold_time)
                    bgp_cfgs[bgp_name]['import_policy'] = l3_import_policy
                self.add_peers_to_bgp_config(bgp_cfgs[bgp_name],
                                             p_addr, p_asn)
        elif l2 == True:
            for peer_name in peer_prs:
                p_asn, p_addr, _, _ = self.get_asn_and_addr(
                    dict_prs[peer_name]['br'])
                bgp_name = self.get_bgp_name(l2_dci_name, l_asn, p_asn)
                if bgp_name not in bgp_cfgs:
                    bgp_cfgs[bgp_name] = self.create_bgp_config(
                        bgp_name, l_addr, l_asn, l_family, l_hold_time)
                    bgp_cfgs[bgp_name]['import_policy'] = l2_import_policy
                    bgp_cfgs[bgp_name]['policies'] = l2_policies
                self.add_peers_to_bgp_config(bgp_cfgs[bgp_name],
                                             p_addr, p_asn)
        return bgp_cfgs
    # end _create_bgp_abstract_cfg

    def _get_abstract_cfg_bgp(self, a_bgp, bgp_name):
        for bgp in a_bgp:
            if bgp.get('name', '') == bgp_name:
                return bgp
        return None

    def _validate_abstract_cfg_bgp_dci(self, e_bgps, a_bgp):
        for bgp_name, e_bgp in e_bgps.items():
            bgp = self._get_abstract_cfg_bgp(a_bgp, bgp_name)
            self.assertIsNotNone(bgp)
            self.assertEqual(bgp.get('name'), e_bgp['name'])
            self.assertEqual(bgp.get('type_'), e_bgp['type_'])
            self.assertEqual(bgp.get('ip_address'), e_bgp['ip_address'])
            self.assertEqual(bgp.get('hold_time'), e_bgp['hold_time'])
            self.assertEqual(bgp.get('autonomous_system'),
                             e_bgp['autonomous_system'])
            if len(e_bgp['families']) > 0:
                families = bgp.get('families')
                self.assertIsNotNone(families)
                self.assertEqual(len(families),
                                 len(e_bgp['families']))
                for e_families in e_bgp['families']:
                    if e_families == 'e-vpn':
                        self.assertIn('evpn', families)
                    else:
                        self.assertIn(e_families, families)
            peers = bgp.get('peers')
            self.assertIsNotNone(peers)
            self.assertEqual(len(peers), len(e_bgp['peers']))
            for e_peer in e_bgp['peers']:
                for peer in peers:
                    if peer.get('ip_address') == e_peer['ip_address']:
                        self.assertEqual(peer.get('autonomous_system'),
                                         e_peer['autonomous_system'])
                        break

            if len(e_bgp['import_policy']) > 0:
                import_policy = bgp.get('import_policy')
                self.assertIsNotNone(import_policy)
                self.assertEqual(len(import_policy),
                                 len(e_bgp['import_policy']))
                for import_p in e_bgp['import_policy']:
                    self.assertIn(import_p, import_policy)
            if len(e_bgp['policies']) > 0:
                policies = bgp.get('policies')
                self.assertIsNotNone(policies)
                self.assertEqual(len(policies),
                                 len(e_bgp['policies']))
                for e_policy in e_bgp['policies']:
                    for policy in policies:
                        if policy.get('name', '') == e_policy['name']:
                            self.assertEqual(policy.get('comment'),
                                             e_policy['comment'])
                            import_targets = policy.get('import_targets')
                            self.assertIsNotNone(import_targets)
                            self.assertEqual(len(import_targets),
                                             len(e_policy['import_targets']))
                            for e_i_target in e_policy['import_targets']:
                                self.assertIn(e_i_target, import_targets)
                            break
    # end _validate_abstract_cfg_bgp_dci

    @retries(4, hook=retry_exc_handler)
    def _validate_abstract_cfg_dci_gateway(self, pr_name, dict_prs,
                                           dci_names, dict_dcis, dict_lrs,
                                           vnlist, dict_vns, dict_vn_rt):
        pr_obj = dict_prs[pr_name]['pr']
        pr_new_name = ''
        if 'PR1_' in pr_name:
            pr_new_name = 'qfx10008' if \
                pr_obj.get_physical_router_product_name() == 'qfx10002' \
                else 'qfx10002'
        else:
            pr_new_name = 'mx240' if \
                pr_obj.get_physical_router_product_name() == 'mx80' \
                else 'mx80'

        pr_obj.set_physical_router_product_name(pr_new_name)
        self._vnc_lib.physical_router_update(pr_obj)
        gevent.sleep(2)

        ac1 = self.check_dm_ansible_config_push()
        dac = ac1.get('device_abstract_config')
        self.assertIsNotNone(dac.get('features'))
        o_bgp = dac.get('features').get('overlay-bgp')
        self.assertIsNotNone(o_bgp)
        o_bgp = dac.get('features').get('overlay-bgp')
        self.assertIsNotNone(o_bgp)
        self.assertEqual(o_bgp.get('name'), 'overlay-bgp')
        a_bgp = o_bgp.get('bgp')
        self.assertIsNotNone(a_bgp)

        if pr_name not in dac.get('system', {}).get('name', ''):
            error = "Looking for Abstract config for %s But " \
                    "recieved config for %s, retrying..." % \
                    (pr_name, dac.get('system', {}).get('name', ''))
            raise Exception(error)
        # now create expected dci_bgp group for each PR of other fabric
        e_bgp = self._create_bgp_abstract_cfg(
            pr_name, dict_prs, dci_names, dict_dcis, dict_lrs, vnlist,
            dict_vns, dict_vn_rt)
        self._validate_abstract_cfg_bgp_dci(e_bgp, a_bgp)
    # end _validate_abstract_cfg_dci_gateway

    def create_dci_interfabric(self, dci_name, l2mode, vn_list,
                               dict_vns, dict_fabrics, dict_lrs):
        dci_fq_name = ["default-global-system-config", dci_name]
        dci = DataCenterInterconnect(
            fq_name=dci_fq_name, parent_type='global-system-config',
            data_center_interconnect_type='inter_fabric')
        if l2mode:
            dci.set_data_center_interconnect_mode('l2')
            for name in vn_list:
                dci.add_virtual_network(dict_vns[name])
            for name, obj in dict_fabrics.items():
                dci.add_fabric(dict_fabrics[name])
        else:
            dci.set_data_center_interconnect_mode('l3')
            for name, obj in dict_lrs.items():
                dci.add_logical_router(dict_lrs[name])
        dci_uuid = self._vnc_lib.data_center_interconnect_create(dci)
        return dci, self._vnc_lib.data_center_interconnect_read(
            id=dci_uuid)
    # end create_dci_interfabric

    def _create_and_validate_dci_l3_l2(self):
        """Validate dci L3 mode, L2 mode and mix mode abstract config.

        It executes following steps in sequences
        - create two fabric with 2 PR (QFX and MX) each fabric. All PRs is
        dci-gw role.
        - create 4 tenant VN with different subnets. Wait till RT being
        created for each VN.
        - create LR1 with VN1 for fabric1 extended to PR1_fabric1. Wait till
        RT created for this LR1.
        - create LR2 with VN2 for fabric2 extended to PR1_fabric2. Wait till
        RT created for this LR2.
        - create dci_l3 for LR1 of fabric1 to LR2 of fabric2.
        - Validate on PR1_fabric1 bgp abstract config for dci l3
        - Validate on PR1_fabric2 bgp abstract config for dci l3
        - create dci_l2 for VN3 and VN4 for fabric1 and fabric2.
        - validate PR1_fabric1 has __contrail-dci_l2-dci_l3-i bgp group exist
        with peering of PR1_fabric2 and __contrail-dci_l2-i bgp group exist
        with peering of PR2_fabric2 only.
        - validate PR2_fabric1 has __contrail-dci_l2-i bgp group exist
        with peering of PR1_fabric2 and PR2_fabric2.
        - validate PR1_fabric2 has __contrail-dci_l2-dci_l3-i bgp group exist
        with peering of PR1_fabric1 and __contrail-dci_l2-i bgp group exist
        with peering of PR2_fabric1 only.
        - validate PR2_fabric2 has __contrail-dci_l2-i bgp group exist
        with peering of PR1_fabric1 and PR2_fabric1.
        - delete dci_l3 and verify that only dci_l2 config gets generated.
        - delete all dci, all LR and all VN
        - cleanup all config (fabric, pr, etc).
        : Args:
        : self: current instance of class
        : return: None
        :
        """
        dict_vns = {}
        dict_vmis = {}
        dict_lrs = {}
        dict_dcis = {}
        dict_vn_rt = {}

        dict_prs = {"PR1_fabric1": {"br": None, "pr": None},
                    "PR2_fabric1": {"br": None, "pr": None},
                    "PR1_fabric2": {"br": None, "pr": None},
                    "PR2_fabric2": {"br": None, "pr": None}}
        dict_fabrics = {"fabric1": None, "fabric2": None}
        vn_starting_index = 76

        ipam_obj = self.create_vn_ipam(self.id())
        self._create_fabrics_prs(dict_fabrics, dict_prs)

        # create 4 VN and 2 LRs, one lr for each fabric
        for i in range(vn_starting_index, vn_starting_index + 4):
            subnet = "%s.1.1.0" % i
            vn_name = self.make_vn_name(i)
            _, dict_vns[vn_name], dict_vn_rt[vn_name] = \
                self.create_vn_with_subnets(i, vn_name, ipam_obj, subnet,
                                            24)
        pr_name = 'PR1_fabric1'
        for i in range(vn_starting_index, vn_starting_index + 2):
            _, lr_obj = self.create_lr(
                self.make_lr_name(i, pr_name),
                [dict_vns[self.make_vn_name(i)]],
                [dict_prs[pr_name]['pr']], dict_vmis)
            dict_lrs[self.make_lr_name(i, pr_name)] = lr_obj
            pr_name = 'PR1_fabric2'

        # create dci_l3 object and validate abstract cfg
        vnlist = []
        dci_name = 'dci_l3'
        _, dict_dcis[dci_name] = self.create_dci_interfabric(
            dci_name, False, vnlist, dict_vns, dict_fabrics, dict_lrs)
        for pr_name in dict_prs.keys():
            if "PR1_" not in pr_name:
                continue
            print("Verifying only dci l3 Config on %s" % (pr_name))
            self._validate_abstract_cfg_dci_gateway(
                pr_name, dict_prs, ['dci_l3'], dict_dcis, dict_lrs, vnlist,
                dict_vns, dict_vn_rt)

        # create dci_l2 object and validate abstract cfg for mix l3 and l2
        dci_name = 'dci_l2'
        vnlist = [self.make_vn_name(vn_starting_index + 2),
                  self.make_vn_name(vn_starting_index + 3)]
        _, dict_dcis[dci_name] = self.create_dci_interfabric(
            dci_name, True, vnlist, dict_vns, dict_fabrics, dict_lrs)
        for pr_name in dict_prs.keys():
            print("Verifying dci l3 and dci l2 mix Config on %s" % (pr_name))
            self._validate_abstract_cfg_dci_gateway(
                pr_name, dict_prs, ['dci_l2', 'dci_l3'], dict_dcis, dict_lrs,
                vnlist, dict_vns, dict_vn_rt)

        # delete dci_l3 and validate abstract cfg for l2 only
        self._vnc_lib.data_center_interconnect_delete(
            id=dict_dcis['dci_l3'].get_uuid())
        dict_dcis['dci_l3'] = None
        for pr_name in dict_prs.keys():
            print("Verifying only dci l2 Config on %s" % (pr_name))
            self._validate_abstract_cfg_dci_gateway(
                pr_name, dict_prs, ['dci_l2'], dict_dcis, dict_lrs,
                vnlist, dict_vns, dict_vn_rt)

        # cleanup
        for name, obj in dict_dcis.items():
            if obj is not None:
                self._vnc_lib.data_center_interconnect_delete(
                    id=obj.get_uuid())
        for name, obj in dict_lrs.items():
            if obj is not None:
                self._vnc_lib.logical_router_delete(
                    id=obj.get_uuid())
        for vminame, vmiobj in dict_vmis.items():
            self._vnc_lib.virtual_machine_interface_delete(
                id=vmiobj.get_uuid())
        for name, obj in dict_vns.items():
            if obj is not None:
                self._vnc_lib.virtual_network_delete(
                    fq_name=obj.get_fq_name())
        self._vnc_lib.network_ipam_delete(id=ipam_obj.uuid)
        self._delete_objects()
    # end _create_and_validate_dci_l3_l2

    def test_dci_gateway_interfabric(self):
        self._create_and_validate_dci_l3_l2()
    # end test_dci_gateway_interfabric

# end TestAnsibleDciGateway
