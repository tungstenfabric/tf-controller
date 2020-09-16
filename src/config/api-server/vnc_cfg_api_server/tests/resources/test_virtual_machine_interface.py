#
# Copyright (c) 2017 Juniper Networks, Inc. All rights reserved.
#
import logging

from cfgm_common.exceptions import BadRequest
import six
from vnc_api.gen.resource_xsd import MacAddressesType
from vnc_api.vnc_api import AllowedAddressPair
from vnc_api.vnc_api import AllowedAddressPairs
from vnc_api.vnc_api import Project
from vnc_api.vnc_api import SubnetType
from vnc_api.vnc_api import VirtualMachineInterface
from vnc_api.vnc_api import VirtualMachineInterfacePropertiesType
from vnc_api.vnc_api import VirtualNetwork
from vnc_api.vnc_api import VirtualPortGroup

from vnc_cfg_api_server.tests import test_case

logger = logging.getLogger(__name__)
VMIPT = VirtualMachineInterfacePropertiesType


class TestVirtualMachineInterface(test_case.ApiServerTestCase):
    def setUp(self):
        super(TestVirtualMachineInterface, self).setUp()
        if six.PY3:
            self.assertItemsEqual = self.assertCountEqual

    @classmethod
    def setUpClass(cls, *args, **kwargs):
        cls.console_handler = logging.StreamHandler()
        cls.console_handler.setLevel(logging.DEBUG)
        logger.addHandler(cls.console_handler)
        super(TestVirtualMachineInterface, cls).setUpClass(*args, **kwargs)

    @classmethod
    def tearDownClass(cls, *args, **kwargs):
        logger.removeHandler(cls.console_handler)
        super(TestVirtualMachineInterface, cls).tearDownClass(*args, **kwargs)

    @property
    def api(self):
        return self._vnc_lib

    def test_valid_sub_interface_vlan_tag_id(self):
        project = Project('%s-project' % self.id())
        self.api.project_create(project)
        vn = VirtualNetwork('%s-vn' % self.id(), parent_obj=project)
        self.api.virtual_network_create(vn)

        test_suite = [
            (None, None),
            (VMIPT(None), None),
            (VMIPT(sub_interface_vlan_tag=None), None),
            (VMIPT(sub_interface_vlan_tag=-42), BadRequest),
            (VMIPT(sub_interface_vlan_tag=4095), BadRequest),
            (VMIPT(sub_interface_vlan_tag='fo'), BadRequest),
            (VMIPT(sub_interface_vlan_tag='42'), None),
            (VMIPT(sub_interface_vlan_tag=42), None),
        ]

        for (vmipt, result) in test_suite:
            vmi = VirtualMachineInterface('%s-vmi' % self.id(),
                                          parent_obj=project)
            vmi.set_virtual_network(vn)
            vmi.set_virtual_machine_interface_properties(vmipt)
            if result and issubclass(result, Exception):
                self.assertRaises(result,
                                  self.api.virtual_machine_interface_create,
                                  vmi)
            else:
                self.api.virtual_machine_interface_create(vmi)
                self.api.virtual_machine_interface_delete(id=vmi.uuid)

    def test_cannot_update_sub_interface_vlan_tag(self):
        project = Project('%s-project' % self.id())
        self.api.project_create(project)
        vn = VirtualNetwork('%s-vn' % self.id(), parent_obj=project)
        self.api.virtual_network_create(vn)
        parent_vmi = VirtualMachineInterface(
            '%s-parent-vmi' % self.id(), parent_obj=project)
        parent_vmi.set_virtual_network(vn)
        self.api.virtual_machine_interface_create(parent_vmi)

        vmi = VirtualMachineInterface('%s-vmi' % self.id(), parent_obj=project)
        vmi.set_virtual_network(vn)
        vmi.set_virtual_machine_interface(parent_vmi)
        self.api.virtual_machine_interface_create(vmi)
        vmi42 = VirtualMachineInterface('%s-vmi42' % self.id(),
                                        parent_obj=project)
        vmi42.set_virtual_machine_interface_properties(
            VMIPT(sub_interface_vlan_tag=42))
        vmi42.set_virtual_network(vn)
        vmi42.set_virtual_machine_interface(parent_vmi)
        self.api.virtual_machine_interface_create(vmi42)

        # if we don't touch VMI props, we can update the VMI with or without
        # VLAN ID
        vmi.set_display_name('new vmi name')
        self.api.virtual_machine_interface_update(vmi)
        vmi42.set_display_name('new vmi42 name')
        self.api.virtual_machine_interface_update(vmi42)

        # if we change VMI props without specifying anything, we can update the
        # VMI if VLAN ID is not set or 0
        vmi.set_virtual_machine_interface_properties(None)
        self.api.virtual_machine_interface_update(vmi)
        vmi.set_virtual_machine_interface_properties(
            VMIPT(sub_interface_vlan_tag=None))
        self.api.virtual_machine_interface_update(vmi)

        # if we change VMI props without specifying anything, we cannot update
        # the VMI if VLAN ID is not 0
        vmi42.set_virtual_machine_interface_properties(None)
        self.assertRaises(BadRequest,
                          self.api.virtual_machine_interface_update,
                          vmi42)
        vmi42.set_virtual_machine_interface_properties(
            VMIPT(sub_interface_vlan_tag=None))
        self.assertRaises(BadRequest,
                          self.api.virtual_machine_interface_update,
                          vmi42)

        # if we update VMI VLAN ID to the same VLAN ID, no error raised
        vmi.set_virtual_machine_interface_properties(
            VMIPT(sub_interface_vlan_tag=0))
        self.api.virtual_machine_interface_update(vmi)
        vmi42.set_virtual_machine_interface_properties(
            VMIPT(sub_interface_vlan_tag=42))
        self.api.virtual_machine_interface_update(vmi42)

    def test_port_security_and_allowed_address_pairs(self):
        project = Project('%s-project' % self.id())
        self.api.project_create(project)
        vn = VirtualNetwork('vn-%s' % self.id(), parent_obj=project)
        self.api.virtual_network_create(vn)
        addr_pair = AllowedAddressPairs(
            allowed_address_pair=[
                AllowedAddressPair(ip=SubnetType('1.1.1.0', 24),
                                   mac='02:ce:1b:d7:a6:e7')])
        msg = (r"^Allowed address pairs are not allowed when port security is "
               "disabled$")

        vmi = VirtualMachineInterface(
            'vmi-%s' % self.id(),
            parent_obj=project,
            port_security_enabled=False,
            virtual_machine_interface_allowed_address_pairs=addr_pair)
        vmi.set_virtual_network(vn)
        with self.assertRaisesRegexp(BadRequest, msg):
            self.api.virtual_machine_interface_create(vmi)

        vmi = VirtualMachineInterface('vmi-%s' % self.id(), parent_obj=project,
                                      port_security_enabled=False)
        vmi.set_virtual_network(vn)
        self.api.virtual_machine_interface_create(vmi)

        # updating a port with allowed address pair should throw an exception
        # when port security enabled is set to false
        vmi.virtual_machine_interface_allowed_address_pairs = addr_pair
        with self.assertRaisesRegexp(BadRequest, msg):
            self.api.virtual_machine_interface_update(vmi)

    def test_disable_port_security_with_empty_allowed_address_pair_list(self):
        project = Project('%s-project' % self.id())
        self.api.project_create(project)
        vn = VirtualNetwork('vn-%s' % self.id(), parent_obj=project)
        self.api.virtual_network_create(vn)
        addr_pair = AllowedAddressPairs()

        vmi1 = VirtualMachineInterface(
            'vmi1-%s' % self.id(),
            parent_obj=project,
            port_security_enabled=False,
            virtual_machine_interface_allowed_address_pairs=addr_pair)
        vmi1.set_virtual_network(vn)
        self.api.virtual_machine_interface_create(vmi1)

        addr_pair = AllowedAddressPairs(
            allowed_address_pair=[
                AllowedAddressPair(ip=SubnetType('1.1.1.0', 24),
                                   mac='02:ce:1b:d7:a6:e7')])
        vmi2 = VirtualMachineInterface(
            'vmi2-%s' % self.id(),
            parent_obj=project,
            port_security_enabled=True,
            virtual_machine_interface_allowed_address_pairs=addr_pair)
        vmi2.set_virtual_network(vn)
        self.api.virtual_machine_interface_create(vmi2)

        addr_pair = AllowedAddressPairs()
        vmi2.set_virtual_machine_interface_allowed_address_pairs(addr_pair)
        self.api.virtual_machine_interface_update(vmi2)

        vmi2.set_port_security_enabled(False)
        self.api.virtual_machine_interface_update(vmi2)

    def test_mac_address_always_allocated(self):
        project = Project(name='p-{}'.format(self.id()))
        p_uuid = self.api.project_create(project)
        project.set_uuid(p_uuid)

        vn = VirtualNetwork(name='vn-{}'.format(self.id()), parent_obj=project)
        vn_uuid = self.api.virtual_network_create(vn)
        vn.set_uuid(vn_uuid)

        mac_addr_test_cases = [
            ['02:ce:1b:d7:a6:e7'],
            ['02-ce-1b-d7-a6-e8'],
            ['02:ce:1b:d7:a6:e9', '02-ce-1b-d7-a6-f1', '02:ce:1b:d7:a6:f2'],
            [],
            None,
        ]

        for i, macs_test_case in enumerate(mac_addr_test_cases):
            vmi = VirtualMachineInterface(name='vmi{}-{}'.format(i, self.id()),
                                          parent_obj=project)
            vmi.set_virtual_network(vn)
            vmi.set_virtual_machine_interface_mac_addresses(
                MacAddressesType(macs_test_case))

            vmi_uuid = self.api.virtual_machine_interface_create(vmi)
            vmi = self.api.virtual_machine_interface_read(id=vmi_uuid)

            vmi_macs = vmi.get_virtual_machine_interface_mac_addresses() \
                .get_mac_address()
            if macs_test_case:
                # check if vmi_macs len is the same as input len
                self.assertItemsEqual(vmi_macs, [mac.replace('-', ':')
                                                 for mac in macs_test_case])
            else:
                # if input was empty or None, check if vmi_macs has been alloc
                self.assertEqual(len(vmi_macs), 1)

            for m in vmi_macs:
                # check if any of mac is not zero
                self.assertNotEqual(m, '00:00:00:00:00:00')

    def _create_vpg_prerequisites(
            self, enterprise_style_flag=True, create_second_pr=False,
            disable_vlan_vn_uniqueness_check=False):
        # Create project first
        proj_obj = Project('%s-project' % (self.id()))
        self.api.project_create(proj_obj)

        # Create Fabric with enterprise style flag set to false
        fabric_obj = Fabric('%s-fabric' % (self.id()))
        fabric_obj.set_fabric_enterprise_style(enterprise_style_flag)
        fabric_obj.set_disable_vlan_vn_uniqueness_check(
            disable_vlan_vn_uniqueness_check)
        fabric_uuid = self.api.fabric_create(fabric_obj)
        fabric_obj = self.api.fabric_read(id=fabric_uuid)

        # Create physical router
        pr_name = self.id() + '_physical_router'
        pr = PhysicalRouter(pr_name)
        pr_uuid = self._vnc_lib.physical_router_create(pr)
        pr_obj = self._vnc_lib.physical_router_read(id=pr_uuid)

        # Create physical interface
        esi_id = '00:11:22:33:44:55:66:77:88:99'
        pi_name = self.id() + '__phy_intf_1'
        pi = PhysicalInterface(name=pi_name,
                               parent_obj=pr_obj,
                               ethernet_segment_identifier=esi_id)
        pi_uuid = self.api.physical_interface_create(pi)
        pi_obj = self.api.physical_interface_read(id=pi_uuid)

        # Create VN
        vn_name = 'vn-%s-1' % self.id()
        vn = VirtualNetwork(vn_name, parent_obj=proj_obj)
        vn_uuid = self.api.virtual_network_create(vn)
        vn_obj = self.api.virtual_network_read(id=vn_uuid)

        return proj_obj, fabric_obj, pr_obj, pi_obj, vn_obj

    def _create_kv_pairs(self, fabric_name, pi_fq_name):
        binding_profile = {'local_link_information': []}
        binding_profile['local_link_information'].append(
            {
                'port_id': pi_fq_name[2],
                'switch_id': pi_fq_name[2],
                'fabric': fabric_name[-1],
                'switch_info': pi_fq_name[1]
            }
        )
        kv_pairs = KeyValuePairs([
            KeyValuePair(key='vif_type', value='vrouter'),
            KeyValuePair(key='vnic_type', value='baremetal'),
            KeyValuePair(key='profile',
                         value=json.dumps(binding_profile))])
        return kv_pairs

    def test_context_undo_fail_db_create(self):
        proj_obj, fabric_obj, pr_obj, pi_obj, vn_obj = \
            self._create_vpg_prerequisites()

        mock_zk = self._api_server._db_conn._zk_db
        zk_alloc_count_before = mock_zk._vpg_id_allocator.get_alloc_count()

        # Create vmi obj
        vmi_name = '%s-1' % self.id()
        vmi_obj = VirtualMachineInterface(vmi_name, parent_obj=proj_obj)
        vmi_obj.set_virtual_network(vn_obj)

        # Create KV_Pairs for this VMI
        pi_fq_name = pi_obj.get_fq_name()
        fabric_name = fabric_obj.get_fq_name()
        kv_pairs = self._create_kv_pairs(fabric_name, pi_fq_name)

        vmi_obj.set_virtual_machine_interface_bindings(kv_pairs)

        def stub(*args, **kwargs):
            return False, (500, "Fake error")

        with ExpectedException(HttpError):
            with test_common.flexmocks(
                    [(self._api_server._db_conn, 'dbe_create', stub)]):
                self.api.virtual_machine_interface_create(vmi_obj)
        zk_alloc_count_after = mock_zk._vpg_id_allocator.get_alloc_count()
        self.assertEqual(zk_alloc_count_before, zk_alloc_count_after)

    def test_context_undo_fail_db_delete(self):
        project = Project(name='p-{}'.format(self.id()))
        self.api.project_create(project)
        vn = VirtualNetwork(name='vn-{}'.format(self.id()), parent_obj=project)
        self.api.virtual_network_create(vn)
        vmi_obj = VirtualMachineInterface('vmi-{}'.format(self.id()),
                                          parent_obj=project)
        vmi_obj.set_virtual_network(vn)
        self.api.virtual_machine_interface_create(vmi_obj)
        vmi_obj = self.api.virtual_machine_interface_read(id=vmi_obj.uuid)

        mock_zk = self._api_server._db_conn._zk_db
        zk_alloc_count_before = mock_zk._vpg_id_allocator.get_alloc_count()

        def stub(*args, **kwargs):
            return False, (500, "Fake error")

        with ExpectedException(HttpError):
            with test_common.flexmocks(
                    [(self._api_server._db_conn, 'dbe_delete', stub)]):
                self.api.virtual_machine_interface_delete(
                    fq_name=vmi_obj.fq_name)

        zk_alloc_count_after = mock_zk._vpg_id_allocator.get_alloc_count()
        self.assertEqual(zk_alloc_count_before, zk_alloc_count_after)

    def test_context_undo_fail_db_update(self):
        project = Project(name='p-{}'.format(self.id()))
        self.api.project_create(project)
        vn_og = VirtualNetwork(name='og-vn-{}'.format(self.id()),
                               parent_obj=project)
        self.api.virtual_network_create(vn_og)
        vmi_obj = VirtualMachineInterface('vmi-{}'.format(self.id()),
                                          parent_obj=project)
        vmi_obj.set_virtual_network(vn_og)
        self.api.virtual_machine_interface_create(vmi_obj)
        vmi_obj = self.api.virtual_machine_interface_read(id=vmi_obj.uuid)

        # change virtual network for VMI
        vn_next = VirtualNetwork(name='next-vn-{}'.format(self.id()),
                                 parent_obj=project)
        vn_next.uuid = self.api.virtual_network_create(vn_next)
        vmi_obj.set_virtual_network(vn_next)

        def stub(*args, **kwargs):
            return False, (500, "Fake error")

        with ExpectedException(HttpError):
            with test_common.flexmocks(
                    [(self._api_server._db_conn, 'dbe_update', stub)]):
                self.api.virtual_machine_interface_update(vmi_obj)
        vmi_obj = self.api.virtual_machine_interface_read(id=vmi_obj.uuid)
        vn_ref_fq_names = [n['to'] for n in vmi_obj.get_virtual_network_refs()]

        self.assertEqual(len(vn_ref_fq_names), 1)
        self.assertEqual(vn_ref_fq_names[0], vn_og.get_fq_name())

    def test_context_undo_vpg_fail_db_update(self):
        proj_obj, fabric_obj, pr_obj, pi_obj, vn_obj = \
            self._create_vpg_prerequisites()

        mock_zk = self._api_server._db_conn._zk_db
        zk_alloc_count_before = mock_zk._vpg_id_allocator.get_alloc_count()

        # Create vmi obj
        vmi_name = '%s-1' % self.id()
        vmi_obj = VirtualMachineInterface(vmi_name, parent_obj=proj_obj)
        vmi_obj.set_virtual_network(vn_obj)
        self.api.virtual_machine_interface_create(vmi_obj)
        vmi_obj = self.api.virtual_machine_interface_read(id=vmi_obj.uuid)

        # Create KV_Pairs for this VMI
        pi_fq_name = pi_obj.get_fq_name()
        fabric_name = fabric_obj.get_fq_name()
        kv_pairs = self._create_kv_pairs(fabric_name, pi_fq_name)

        vmi_obj.set_virtual_machine_interface_bindings(kv_pairs)

        def stub(*args, **kwargs):
            return False, (500, "Fake error")

        with ExpectedException(HttpError):
            with test_common.flexmocks(
                    [(self._api_server._db_conn, 'dbe_update', stub)]):
                self.api.virtual_machine_interface_update(vmi_obj)
        zk_alloc_count_after = mock_zk._vpg_id_allocator.get_alloc_count()
        self.assertEqual(zk_alloc_count_before, zk_alloc_count_after)


class TestVMIVirtualPortGroupRelation(test_case.ApiServerTestCase):
    @classmethod
    def setUpClass(cls, *args, **kwargs):
        cls.console_handler = logging.StreamHandler()
        cls.console_handler.setLevel(logging.DEBUG)
        logger.addHandler(cls.console_handler)
        super(TestVMIVirtualPortGroupRelation, cls).setUpClass(*args, **kwargs)

    @classmethod
    def tearDownClass(cls, *args, **kwargs):
        logger.removeHandler(cls.console_handler)
        super(TestVMIVirtualPortGroupRelation,
              cls).tearDownClass(*args, **kwargs)

    @property
    def api(self):
        return self._vnc_lib

    def setUp(self):
        super(TestVMIVirtualPortGroupRelation, self).setUp()
        if six.PY3:
            self.assertItemsEqual = self.assertCountEqual

        # Create project
        self.proj_obj = Project('%s-project' % (self.id()))
        self.api.project_create(self.proj_obj)

        # Create Fabric
        self.fabric_obj = Fabric('%s-fabric' % (self.id()))
        _ = self.api.fabric_create(self.fabric_obj)
        self.fabric_name = self.fabric_obj.get_fq_name()

        # Create physical router
        pr_name = self.id() + '_physical_router'
        pr = PhysicalRouter(pr_name)
        pr_uuid = self.api.physical_router_create(pr)
        self.pr_obj = self.api.physical_router_read(id=pr_uuid)

        # Create Physical interface
        esi_id = '00:11:22:33:44:55:66:77:88:99'
        pi_name = self.id() + '_physical_interface1'
        pi = PhysicalInterface(name=pi_name,
                               parent_obj=self.pr_obj,
                               ethernet_segment_identifier=esi_id)
        self.pi_uuid = self.api.physical_interface_create(pi)
        pi_obj = self.api.physical_interface_read(id=self.pi_uuid)
        self.pi_fq_name = pi_obj.get_fq_name()

        # Create VN
        self.vn = VirtualNetwork(
            'vn-%s' % (self.id()), parent_obj=self.proj_obj)
        self.vn_uuid = self.api.virtual_network_create(self.vn)

        # Create VPG
        self.vpg_name = "vpg-%s" % self.id()
        vpg = VirtualPortGroup(self.vpg_name, parent_obj=self.fabric_obj)
        self.vpg_uuid = self.api.virtual_port_group_create(vpg)
        vpg_obj = self.api.virtual_port_group_read(id=self.vpg_uuid)
        self.vpg_name = vpg_obj.get_fq_name()

    def tearDown(self):
        self.api.physical_interface_delete(id=self.pi_uuid)
        self.api.physical_router_delete(id=self.pr_obj.uuid)
        self.api.virtual_port_group_delete(id=self.vpg_uuid)
        self.api.fabric_delete(id=self.fabric_obj.uuid)
        self.api.virtual_network_delete(id=self.vn_uuid)
        self.api.project_delete(id=self.proj_obj.uuid)
        super(TestVMIVirtualPortGroupRelation, self).tearDown()

    def create_vmi_bindings(self, pi_fq_name, fabric_name, vpg_name,
                            tor_port_vlan_id=0):
        # Populate binding profile to be used in VMI create
        binding_profile = {'local_link_information': []}
        if isinstance(pi_fq_name[0], type([])):
            for pi_name in pi_fq_name:
                binding_profile['local_link_information'].append(
                    {'port_id': pi_name[2],
                     'switch_id': pi_name[2],
                     'fabric': fabric_name[-1],
                     'switch_info': pi_name[1]})
        else:
            binding_profile['local_link_information'].append(
                {'port_id': pi_fq_name[2],
                 'switch_id': pi_fq_name[2],
                 'fabric': fabric_name[-1],
                 'switch_info': pi_fq_name[1]})

        if tor_port_vlan_id != 0:
            kv_pairs = KeyValuePairs(
                [KeyValuePair(key='vpg', value=vpg_name[-1]),
                 KeyValuePair(key='vif_type', value='vrouter'),
                 KeyValuePair(key='tor_port_vlan_id', value=tor_port_vlan_id),
                 KeyValuePair(key='vnic_type', value='baremetal'),
                 KeyValuePair(key='profile',
                              value=json.dumps(binding_profile))])
        else:
            kv_pairs = KeyValuePairs(
                [KeyValuePair(key='vpg', value=vpg_name[-1]),
                 KeyValuePair(key='vif_type', value='vrouter'),
                 KeyValuePair(key='vnic_type', value='baremetal'),
                 KeyValuePair(key='profile',
                              value=json.dumps(binding_profile))])

        return kv_pairs

    def test_untagged_vmi_to_vpg_ref_create_during_vmi_create(self):
        # Create vmi with bindings
        vmi_obj = VirtualMachineInterface(
            'vmi' + self.id(), parent_obj=self.proj_obj)
        vmi_obj.set_virtual_network(self.vn)
        bindings = self.create_vmi_bindings(self.pi_fq_name,
                                            self.fabric_name,
                                            self.vpg_name,
                                            tor_port_vlan_id='4094')
        vmi_obj.set_virtual_machine_interface_bindings(bindings)
        vmi_uuid = self.api.virtual_machine_interface_create(vmi_obj)

        # Validate
        vmi_obj = self.api.virtual_machine_interface_read(id=vmi_uuid)
        vpg_refs = vmi_obj.get_virtual_port_group_refs()
        self.assertEqual(len(vpg_refs), 1)
        self.assertEqual(vpg_refs[0]['attr'].native_vlan_tag, '4094')
        self.assertIsNone(vpg_refs[0]['attr'].vlan_tag)

        # Cleanup
        self.api.virtual_machine_interface_delete(id=vmi_uuid)

    def test_tagged_vmi_to_vpg_ref_create_during_vmi_update(self):
        # Create vmi without bindings
        vmi_obj = VirtualMachineInterface(
            'vmi' + self.id(), parent_obj=self.proj_obj)
        vmi_obj.set_virtual_network(self.vn)
        vmi_uuid = self.api.virtual_machine_interface_create(vmi_obj)

        # Validate
        db_vmi_obj = self.api.virtual_machine_interface_read(id=vmi_uuid)
        vpg_refs = db_vmi_obj.get_virtual_port_group_refs()
        self.assertIsNone(vpg_refs)

        # update VMI with bindings
        bindings = self.create_vmi_bindings(self.pi_fq_name,
                                            self.fabric_name,
                                            self.vpg_name)
        vmi_obj.set_virtual_machine_interface_bindings(bindings)
        vmi_obj.set_virtual_machine_interface_properties(
            VMIPT(sub_interface_vlan_tag='4094'))
        self.api.virtual_machine_interface_update(vmi_obj)

        # Validate
        db_vmi_obj = self.api.virtual_machine_interface_read(id=vmi_uuid)
        vpg_refs = db_vmi_obj.get_virtual_port_group_refs()
        self.assertEqual(len(vpg_refs), 1)
        self.assertIsNone(vpg_refs[0]['attr'].native_vlan_tag)
        self.assertEqual(vpg_refs[0]['attr'].vlan_tag, 4094)

        # Cleanup
        self.api.virtual_machine_interface_delete(id=vmi_uuid)

    def test_vmi_to_vpg_ref_create_during_dbe_resync(self):
        # Create vmi with bindings
        vmi_obj = VirtualMachineInterface(
            'vmi' + self.id(), parent_obj=self.proj_obj)
        vmi_obj.set_virtual_network(self.vn)
        bindings = self.create_vmi_bindings(self.pi_fq_name,
                                            self.fabric_name,
                                            self.vpg_name,
                                            tor_port_vlan_id='4094')
        vmi_obj.set_virtual_machine_interface_bindings(bindings)
        vmi_uuid = self.api.virtual_machine_interface_create(vmi_obj)

        # Validate
        vmi_obj = self.api.virtual_machine_interface_read(id=vmi_uuid)
        vpg_refs = vmi_obj.get_virtual_port_group_refs()
        self.assertEqual(len(vpg_refs), 1)
        self.assertEqual(vpg_refs[0]['attr'].native_vlan_tag, '4094')
        self.assertIsNone(vpg_refs[0]['attr'].vlan_tag)

        # Remove VMI to VPG ref, to mock upgrade case
        self.api.ref_update("virtual-machine-interface",
                            vmi_uuid,
                            "virtual-port-group",
                            self.vpg_uuid,
                            None,
                            "DELETE",
                            None)
        # Validate, make sure rhe vmi--->vpg ref is removed
        vmi_obj = self.api.virtual_machine_interface_read(id=vmi_uuid)
        vpg_refs = vmi_obj.get_virtual_port_group_refs()
        self.assertIsNone(vpg_refs)

        # Simulate api-server restart by DB reinit
        self._api_server._db_init_entries()

        # Validate, Make sure vmi--->vpg ref is created
        vmi_obj = self.api.virtual_machine_interface_read(id=vmi_uuid)
        vpg_refs = vmi_obj.get_virtual_port_group_refs()
        self.assertEqual(len(vpg_refs), 1)
        self.assertEqual(vpg_refs[0]['attr'].native_vlan_tag, '4094')
        self.assertIsNone(vpg_refs[0]['attr'].vlan_tag)

        # Cleanup
        self.api.virtual_machine_interface_delete(id=vmi_uuid)
