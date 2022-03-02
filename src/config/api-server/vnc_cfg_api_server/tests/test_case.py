from builtins import range
from vnc_api import vnc_api
from cfgm_common.tests import test_common

import mock
import logging
logger = logging.getLogger(__name__)

from cfgm_common.utils import _DEFAULT_ZK_DB_RESYNC_PATH_PREFIX
from cfgm_common.utils import _DEFAULT_ZK_DB_SYNC_COMPLETE_ZNODE_PATH_PREFIX
from cfgm_common.utils import _DEFAULT_ZK_LOCK_TIMEOUT

from cfgm_common.utils import (
    _DEFAULT_ZK_DB_SYNC_COMPLETE_ZNODE_PATH_PREFIX
    as PATH_SYNC
)

class ApiServerTestCase(test_common.TestCase):
    def setUp(self):
        super(ApiServerTestCase, self).setUp()
        self.ignore_err_in_log = False

    def tearDown(self):
        try:
            if self.ignore_err_in_log:
                return

            with open('api_server_%s.log' %(self.id())) as f:
                lines = f.read()
                self.assertIsNone(
                    re.search('SYS_ERR', lines), 'Error in log file')
        except IOError:
            # vnc_openstack.err not created, No errors.
            pass
        finally:
            super(ApiServerTestCase, self).tearDown()

    def _create_vn_ri_vmi(self, obj_count=1):
        vn_objs = []
        ipam_objs = []
        ri_objs = []
        vmi_objs = []
        for i in range(obj_count):
            vn_obj = vnc_api.VirtualNetwork('%s-vn-%s' %(self.id(), i))

            ipam_obj = vnc_api.NetworkIpam('%s-ipam-%s' % (self.id(), i))
            vn_obj.add_network_ipam(ipam_obj, vnc_api.VnSubnetsType())
            self._vnc_lib.network_ipam_create(ipam_obj)
            ipam_objs.append(ipam_obj)

            self._vnc_lib.virtual_network_create(vn_obj)
            vn_objs.append(vn_obj)

            ri_obj = vnc_api.RoutingInstance('%s-ri-%s' %(self.id(), i),
                                     parent_obj=vn_obj)
            self._vnc_lib.routing_instance_create(ri_obj)
            ri_objs.append(ri_obj)

            vmi_obj = vnc_api.VirtualMachineInterface('%s-vmi-%s' %(self.id(), i),
                                              parent_obj=vnc_api.Project())
            vmi_obj.add_virtual_network(vn_obj)
            self._vnc_lib.virtual_machine_interface_create(vmi_obj)
            vmi_objs.append(vmi_obj)

        return vn_objs, ipam_objs, ri_objs, vmi_objs
    # end _create_vn_ri_vmi

    def assert_vnc_db_doesnt_have_ident(self, test_obj):
        self.assertTill(self.vnc_db_doesnt_have_ident, obj=test_obj)

    def assert_vnc_db_has_ident(self, test_obj):
        self.assertTill(self.vnc_db_has_ident, obj=test_obj)
# end class ApiServerTestCase

class TestAPIServerDBresync(ApiServerTestCase):
    @classmethod
    def setUpClass(cls, *args, **kwargs):
        cls.console_handler = logging.StreamHandler()
        cls.console_handler.setLevel(logging.DEBUG)
        logger.addHandler(cls.console_handler)
        kwargs = {'extra_config_knobs': [('DEFAULTS', 'contrail_version',
                                         '2011')]}
        super(TestAPIServerDBresync, cls).setUpClass(*args, **kwargs)

    @classmethod
    def tearDownClass(cls, *args, **kwargs):
        logger.removeHandler(cls.console_handler)
        super(TestAPIServerDBresync,
              cls).tearDownClass(*args, **kwargs)

    def test_verify_db_walk_dbe_resync_on_reinit(self):
        DB_RESYNC=self._api_server._db_conn
        DBE_RESYNC_original=self._api_server._db_conn._dbe_resync
        DB_WALK=self._api_server._db_conn._object_db
        DB_WALK_original=self._api_server._db_conn._object_db.walk

        self._api_server._args.contrail_version = '2011'
        """ _dbe_resync is not ran even though we have restarted api-server
        since zk_sync_node  is not NONE
        also only DB_walk will be executed
        """
        mock_zk = self._api_server._db_conn._zk_db
        zk_sync_node = mock_zk._zk_client.read_node(_DEFAULT_ZK_DB_SYNC_COMPLETE_ZNODE_PATH_PREFIX)
        self.assertIsNotNone(zk_sync_node)

        #mocking dbe_resync
        def mock_db_resync( obj_type, obj_uuids):
            mock_db_resync.has_been_called = True
            return DBE_RESYNC_original(obj_type, obj_uuids)

        #Mocking db_walk
        def mock_db_walk():
            mock_db_walk.has_been_called = True
            return DB_WALK_original()

        mock_db_walk.has_been_called = False
        mock_db_resync.has_been_called = False

        with mock.patch.object(DB_WALK, 'walk',
                               side_effect=mock_db_walk):

            with mock.patch.object(DB_RESYNC, '_dbe_resync',
                                   side_effect=mock_db_resync):
                self._api_server._db_conn._db_resync_done.clear()
                # API server DB reinit
                self._api_server._db_init_entries()
                self._api_server._db_conn.wait_for_resync_done()
        if zk_sync_node and mock_db_walk.has_been_called and not mock_db_resync.has_been_called:
            self.assertEqual(zk_sync_node, '2011')
            logger.info('PASS - test_db_resync_db_walk_verify')
        else:
            logger.info('FAIL - test_db_resync_db_walk_verify')
            self.fail("test_verify_db_resync_db_walk_on_reinit Test case failed")


    def test_verify_db_resync_on_reinit_upgrade_scenario(self):
        DB_RESYNC = self._api_server._db_conn
        DB_RESYNC_original = self._api_server._db_conn._dbe_resync

        mock_zk = self._api_server._db_conn._zk_db
        #zk_sync_node data before upgrade
        znode1 = mock_zk._zk_client.read_node(_DEFAULT_ZK_DB_SYNC_COMPLETE_ZNODE_PATH_PREFIX)


        #Mocking _dbe_resync
        def mock_db_resync( obj_type, obj_uuids):
            mock_db_resync.has_been_called = True
            logger.info('MOCK _DBE_RESYNC RUNNING SUCCESSFULLY')
            return DB_RESYNC_original(obj_type, obj_uuids)

        self._api_server._args.contrail_version = '21.4'

        """contrail_version  is set manually so  _dbe_resync ,
        is  running as part of this UT
        once  api-server is restarted"""

        mock_db_resync.has_been_called = False
        with mock.patch.object(DB_RESYNC, '_dbe_resync',
                               side_effect=mock_db_resync):

            self._api_server._db_conn._db_resync_done.clear()
            # API server DB reinit
            self._api_server._db_init_entries()
            self._api_server._db_conn.wait_for_resync_done()

        #zk_sync_node data after upgrade
        znode2 = mock_zk._zk_client.read_node(_DEFAULT_ZK_DB_SYNC_COMPLETE_ZNODE_PATH_PREFIX)
        if znode1 and znode2 and mock_db_resync.has_been_called:
            self.assertEqual(znode1,'2011')
            self.assertEqual(znode2, '21.4')
            logger.info('PASS - test_verify_db_resync_on_reinit_upgrade_scenario')
        else:
            logger.info('FAIL - test_verify_db_resync_on_reinit_upgrade_scenario')
            self.fail("test_verify_db_resync_on_reinit_upgrade_scenario Test case failed")

        # adding back zknode to original version
        # so other test cases runs from the begining
        mock_zk._zk_client.update_node(PATH_SYNC, '2011')

#END of TestAPIServerDBresync
