import unittest
import mock
import signal
from attrdict import AttrDict
from cfgm_common.exceptions import ResourceExistsError
from job_manager.job_exception import JobException
from device_manager.job_handler import JobStatus
from device_manager.device_job_manager import DeviceJobManager


class TestDeviceJobManager(unittest.TestCase):

    def setUp(self):
        super(TestDeviceJobManager, self).setUp()
        self.amqp_client = mock.Mock()
        self.db_conn = mock.Mock()
        self.logger = mock.Mock()
        self.args = AttrDict({
            'admin_user': 'AzureDiamond',
            'admin_password': 'hunter2',
            'admin_tenant_name': 'admin',
            'api_server_port': '8082',
            'api_server_use_ssl': 'False',
            'collectors': None,
            'fabric_ansible_conf_file': '/fa/ke.conf',
            'host_ip': '127.0.0.1',
            'zk_server_ip': '127.0.0.1',
            'cluster_id': 0,
            'max_job_count': 42,
            'zookeeper_ssl_enable': False,
            'zookeeper_ssl_keyfile': '',
            'zookeeper_ssl_certificate': '',
            'zookeeper_ssl_ca_cert': ''
        })
        self.djm = None
        self.zk_patch = mock.patch(
            'device_manager.device_job_manager.ZookeeperClient')
        self.zk_mock = self.zk_patch.start().return_value
        self.djm = DeviceJobManager(self.amqp_client, self.db_conn, self.args,
                                    self.logger)

    def tearDown(self):
        super(TestDeviceJobManager, self).tearDown()
        self.zk_patch.stop()

    def test_job_status_notification(self):
        '''
        Verifies DeviceJobManager.publish_job_status_notification()
        '''
        self.djm.publish_job_status_notification('42',
                                                 JobStatus.STARTING.value)
        self.amqp_client.publish.assert_called_once()
        args, kwargs = self.amqp_client.publish.call_args_list[0]
        job_payload = args[0]
        self.assertEqual(job_payload['job_execution_id'], '42')
        self.assertEqual(job_payload['job_status'], JobStatus.STARTING.value)

    def test_job_abort_request(self):
        '''
        Verifies DeviceJobManager.handle_abort_job_request()
        '''
        # Mock objects
        message = mock.Mock()
        os_patch = mock.patch('device_manager.device_job_manager.os')
        os_mock = os_patch.start()

        # Create a fake running job instance
        fake_job_exec_id = "1603391733538_0f567ded-2fc4-41fe-b168-f5e951a9f0db"
        fake_job_pid = '99'
        fake_job_info = {'exec_id': fake_job_exec_id}
        self.djm._job_mgr_running_instances[fake_job_pid] = fake_job_info

        # Send an abort message with abort mode force
        body = {
            "input": {
                "job_execution_ids": [fake_job_exec_id],
                "abort_mode": "force"
            }
        }
        self.djm.handle_abort_job_request(body, message)

        # Verify the pid and abort mode
        args, kwargs = os_mock.kill.call_args_list[0]
        os_mock.kill.assert_called_once()
        self.assertEqual(args[0], int(fake_job_pid))
        # Signal is SIGABRT since we used force abort
        self.assertEqual(args[1], signal.SIGABRT)
        os_patch.stop()

        # Now send an abort message with a different mode
        os_mock = os_patch.start()
        body = {
            "input": {
                "job_execution_ids": [fake_job_exec_id],
                "abort_mode": "graceful"
            }
        }
        self.djm.handle_abort_job_request(body, message)

        # Verify the pid and abort mode
        args, kwargs = os_mock.kill.call_args_list[0]
        os_mock.kill.assert_called_once()
        self.assertEqual(args[0], int(fake_job_pid))
        # Signal should be SIGUSR1 since we are not forcing abort
        self.assertEqual(args[1], signal.SIGUSR1)
        os_patch.stop()

    def test_job_execute_request(self):
        '''
        Verifies DeviceJobManager.handle_execute_job_request()
        '''
        message = mock.Mock()
        # Sample request from UI
        body = {
            'job_transaction_descr':
                'Docker Init',
            'job_transaction_id':
                '1607368880532_7cd98608-c815-4a10-89d9-f242591f5154',
            'job_execution_id':
                '1607368900423_f3797c7d-53fc-4d7b-ae60-469f51bc26a6',
            'job_template_fq_name': [
                'default-global-system-config', 'fabric_config_template'
            ],
            'cluster_id':
                '',
            'input': {
                'fabric_uuid': '6244cc48-2a88-4171-bf6a-149eb5235f39',
                'is_delete': False,
                'fabric_fq_name': ['default-global-system-config', 'ZTP'],
                'device_management_ip': '10.87.12.4',
                'enterprise_style': True,
                'manage_underlay': True
            },
            'api_server_host': ['10.87.3.81'],
            'device_json': {
                'c589e830-503c-46c6-a99b-1c2ca929d353': {
                    'device_fqname': ['fake', 'name']
                }
            }
        }

        # Mock db_read
        db_read_patch = mock.patch('device_manager.device_job_manager.'
                                   'DeviceJobManager.db_read')
        db_read_mock = db_read_patch.start()
        db_read_mock.return_value = (True, {})

        self.db_conn.fq_name_to_uuid.return_value = '22821559-c1e8-4a05-9e2f-57f9951ad585'

        # Mock FabricJobUve.send()
        fab_job_uve_patch = mock.patch('device_manager.device_job_manager.'
                                       'FabricJobUve.send')
        fab_job_uve_mock = fab_job_uve_patch.start()

        # Mock this function out so we don't perform file writes
        save_abs_cfg_patch = mock.patch(
            'device_manager.device_job_manager.'
            'DeviceJobManager.save_abstract_config')
        save_abs_cfg_mock = save_abs_cfg_patch.start()

        # Mock subprocess.Popen()
        subprocess_patch = mock.patch('device_manager.device_job_manager.'
                                      'subprocess.Popen')
        subprocess_mock = subprocess_patch.start()
        subprocess_mock.return_value = AttrDict({'pid': 42})

        # Make the call to handle_execute_job_request()
        self.djm.handle_execute_job_request(body, message)

        # Verify that we send UVE
        fab_job_uve_mock.assert_called_once()
        # Verify that we save abstract config to a file
        save_abs_cfg_mock.assert_called_once()
        # Verify that job manager subprocess is created
        subprocess_mock.assert_called_once()
        # Verify that there is a running instance of job manager
        self.assertIsNotNone(self.djm._job_mgr_running_instances)
        job_mgr_running_instances = self.djm._job_mgr_statistics[
            'running_job_count']
        self.assertEqual(job_mgr_running_instances, 1)

        # Verify job properties
        signal_var = self.djm._job_mgr_running_instances['42']
        self.assertEqual(signal_var['fabric_fq_name'],
                         'default-global-system-config:ZTP')
        self.assertEqual(signal_var['exec_id'],
                         '1607368900423_f3797c7d-53fc-4d7b-ae60-469f51bc26a6')

        # Stop mocking
        subprocess_patch.stop()
        save_abs_cfg_mock.stop()
        fab_job_uve_patch.stop()
        db_read_patch.stop()

    def test_job_mgr_signal_handler(self):
        '''
            Verifies DeviceJobManager.job_mgr_signal_handler()
        '''
        # Create a fake running job instance
        fake_job_exec_id = "1603391733538_0f567ded-2fc4-41fe-b168-f5e951a9f0db"
        fake_job_pid = '137'
        fake_job_info = {
            'exec_id': fake_job_exec_id,
            'device_fqnames': ['really:fake_device'],
            'fabric_name': 'fake_fabric',
            'fabric_fq_name': 'really:fake_fabric',
            'start_time': 1,
            'job_concurrency': 'fabric'
        }

        self.djm._job_mgr_running_instances[fake_job_pid] = fake_job_info

        # Mock os
        os_patch = mock.patch('device_manager.device_job_manager.os')
        os_mock = os_patch.start()
        os_mock.waitpid.return_value = [int(fake_job_pid)]

        # Mock Extracted File Output
        efo_patch = mock.patch('device_manager.device_job_manager.'
                               'DeviceJobManager._extracted_file_output')
        efo_mock = efo_patch.start()
        efo_mock.return_value = ('FAILURE', {
            'fake_device': 'FAILURE'
        }, {}, ['fake_device'])

        # Mock PhysicalRouterJobUve.send()
        pr_job_uve_patch = mock.patch('device_manager.device_job_manager.'
                                      'PhysicalRouterJobUve.send')
        pr_job_uve_mock = pr_job_uve_patch.start()

        # Make the call to the signal handler
        self.djm.job_mgr_signal_handler(signalnum=signal.SIGCHLD, frame=None)

        # Verify that we received the child pid
        os_mock.waitpid.assert_called_once()
        # Verify that we extracted output from file
        efo_mock.assert_called_once()
        # Verify that prouter uve is sent twice
        self.assertEqual(pr_job_uve_mock.call_count, 2)
        # Verify that there are no more job_mgr running instances with our pid
        self.assertIsNone(
            self.djm._job_mgr_running_instances.get(fake_job_pid))
        # Verify that job and fabric lock has been cleared
        self.zk_mock.get_children.assert_called_once()
        self.zk_mock.delete_node.assert_called_once()

        # Stop mocking
        pr_job_uve_patch.stop()
        efo_mock.stop()
        os_patch.stop()

    def test_abstract_config_write(self):
        fake_job_params = {
            'input': {
                'device_abstract_config': {
                    'system': {
                        'management_ip': '127.0.0.1'
                    }
                }
            }
        }

        # Mock os
        os_patch = mock.patch('device_manager.device_job_manager.os')
        os_mock = os_patch.start()

        # Force directory exists check to False
        os_mock.path.exists.return_value = False

        # Mock open
        open_patch = mock.patch('device_manager.device_job_manager.open')
        open_mock = open_patch.start()

        # Make the call to save abstract config
        self.djm.save_abstract_config(fake_job_params)

        # Verify that we check if directory exists
        os_mock.path.exists.assert_called_once()
        # Verify that we create the directory
        os_mock.makedirs.assert_called_once()
        # Verify that we open the file
        open_mock.assert_called_once()

        expected_file_name = ("/opt/contrail/fabric_ansible_playbooks/config/"
                              "127.0.0.1/abstract_cfg.json")
        expected_file_open_mode = "w"
        args, _ = open_mock.call_args_list[0]
        file_name = args[0]
        open_mode = args[1]

        # Verify the file that we are writing to
        self.assertEqual(file_name, expected_file_name)
        # Verify that we are writing to file
        self.assertEqual(open_mode, expected_file_open_mode)

        # Verify that device_abstract_config no longer exists
        self.assertIsNone(
            fake_job_params.get('input').get('device_abstract_config'))

        # Stop mocking
        open_patch.stop()
        os_patch.stop()

    def test_read_fabric_data(self):
        job_exec_id = '1607467889885_1ee9127c-88c2-4ff7-95d6-cee24139b0eb'

        # Case 1. fq name present in input
        request_params = {
            'input': {
                'fabric_fq_name': ['fake', 'fabric'],
            },
        }
        # Make the call to read_fabric_data
        self.djm.read_fabric_data(request_params, job_exec_id)
        # Verify modified fq_name
        self.assertEqual(request_params['fabric_fq_name'], 'fake:fabric')

        # Case 2. uuid present in input
        request_params = {
            'input': {
                'fabric_uuid': '6244cc48-2a88-4171-bf6a-149eb5235f39',
            },
        }
        # Force return value of db_conn
        self.db_conn.uuid_to_fq_name.return_value = ['fake', 'fabric']
        # Make the call to read_fabric_data
        self.djm.read_fabric_data(request_params, job_exec_id)
        # Verify that we make a call to uuid_to_fq_name
        self.db_conn.uuid_to_fq_name.assert_called_once()
        # Verify modified fq_name
        self.assertEqual(request_params['fabric_fq_name'], 'fake:fabric')

        # Case 3. device_deletion_template
        request_params = {
            'input': {
                'fake': 'input',
            },
            'job_template_fq_name': ['fake', 'device_deletion_template'],
        }
        # Make the call to read_fabric_data
        self.djm.read_fabric_data(request_params, job_exec_id)
        # Verify modified fq_name
        self.assertEqual(request_params['fabric_fq_name'], '__DEFAULT__')

        # Case 4. No input
        request_params = {}
        # Verify JobException
        self.assertRaises(JobException, self.djm.read_fabric_data,
                          request_params, job_exec_id)

        # Case 5. improper template
        request_params = {
            'input': {
                'fake': 'input',
            },
            'job_template_fq_name': ['fake', 'template'],
        }
        # Verify JobException
        self.assertRaises(JobException, self.djm.read_fabric_data,
                          request_params, job_exec_id)

    def test_read_device_data(self):
        request_params = {
            'input': {
                'fabric_uuid': '6244cc48-2a88-4171-bf6a-149eb5235f39',
                'is_delete': False,
                'fabric_fq_name': ['default-global-system-config', 'ZTP'],
                'device_management_ip': '10.87.12.4',
                'device_abstract_config': {
                    'system': {
                        'name': '5a11-qfx3',
                        'device_family': 'junos-qfx',
                        'management_ip': '10.87.12.4',
                        'credentials': {
                            'authentication_method':
                                'PasswordBasedAuthentication',
                            'password':
                                'RYj5LWMgRZhgxbYLvKZfng==',
                            'user_name':
                                'root'
                        },
                        'vendor_name': 'Juniper',
                        'product_name': 'qfx5110-48s-4c',
                        'uuid': 'c589e830-503c-46c6-a99b-1c2ca929d353'
                    }
                },
            },
        }
        device_list = ['c589e830-503c-46c6-a99b-1c2ca929d353']
        job_exec_id = '1607467889885_1ee9127c-88c2-4ff7-95d6-cee24139b0eb'

        # Mock db_read
        db_read_patch = mock.patch('device_manager.device_job_manager.'
                                   'DeviceJobManager.db_read')
        db_read_mock = db_read_patch.start()
        db_read_result = {
            'physical_router_device_family': 'junos-qfx',
            'physical_router_management_ip': '10.87.12.4',
            'fq_name': ['default-global-system-config', '5a11-qfx3'],
            'uuid': 'c589e830-503c-46c6-a99b-1c2ca929d353',
            'physical_router_vendor_name': 'Juniper',
            'physical_router_product_name': 'qfx5110-48s-4c',
            'fabric_refs': [{
                'to': ['default-global-system-config', 'ZTP'],
                'attr': None,
                'uuid': '6244cc48-2a88-4171-bf6a-149eb5235f39'
            }],
            'physical_router_user_credentials': {
                'username': 'root',
                'password': 'RYj5LWMgRZhgxbYLvKZfng=='
            },
        }
        db_read_mock.return_value = (True, db_read_result)

        def verify_parameters(request_params):
            # Verify that we have device_json in our request_params
            self.assertIsNotNone(request_params.get('device_json'))
            device_json = request_params.get('device_json').get(device_list[0])
            # Verify username
            self.assertEqual(device_json.get('device_username'), 'root')
            # Verify the password
            self.assertEqual(device_json.get('device_password'), b'Embe1mpls')
            # Verify fq_name
            self.assertEqual(device_json.get('device_fqname'),
                             ['default-global-system-config', '5a11-qfx3'])
            # Verify the mgmnt ip
            self.assertEqual(device_json.get('device_management_ip'),
                             '10.87.12.4')
            # Verify the vendor
            self.assertEqual(device_json.get('device_vendor'), 'Juniper')
            # Verify device family
            self.assertEqual(device_json.get('device_family'), 'junos-qfx')
            # Verify product
            self.assertEqual(device_json.get('device_product'),
                             'qfx5110-48s-4c')

        # Make the call to read_device_data
        self.djm.read_device_data(device_list, request_params, job_exec_id)
        # Verify that we make the db_read call
        db_read_mock.assert_called_once()
        # Verify that parameters are properly filled
        verify_parameters(request_params)
        # Stop mocking db_read
        db_read_patch.stop()

        # Mock read_fabric_data
        read_fab_data_patch = mock.patch('device_manager.device_job_manager.'
                                         'DeviceJobManager.read_fabric_data')
        read_fab_data_mock = read_fab_data_patch.start()

        # Make the call to read_device_data with is_delete set to True
        self.djm.read_device_data(device_list,
                                  request_params,
                                  job_exec_id,
                                  is_delete=True)
        # Verify that read_fabric_data is called
        read_fab_data_mock.assert_called_once()
        # Verify that parameters are properly filled
        verify_parameters(request_params)
        # Stop mocking read_fabric_data
        read_fab_data_patch.stop()

    def test_extracted_file_output(self):
        gdo_line = ("GENERIC_DEVICE##{'device_name': u'5a11-qfx4',"
                    "'command_output': 'fake_output' }GENERIC_DEVICE##*EOL*\n")
        job_summary_line = ("job_summaryJOB_LOG##{'job_status': 'FAILURE',"
                            "'failed_devices_list': ['fake']}JOB_LOG##*EOL*\n")
        prouter_line = (
            'PROUTER_LOG##{"onboarding_state": "ONBOARDED", "prouter_fqname":'
            '["fake", "name"],}PROUTER_LOG##*EOL*\n')
        lines_to_write = [prouter_line, job_summary_line, gdo_line]
        fake_exec_id = '09c1f45c-c387-4278-9acb-062d20db3d09'

        with open("/tmp/" + fake_exec_id, "w") as f:
            f.writelines(lines_to_write)

        status, prouter_info, device_op_results, failed_devices_list = (
            self.djm._extracted_file_output(fake_exec_id))

        self.assertEqual(status, 'FAILURE')
        self.assertEqual(prouter_info, {'fake:name': 'ONBOARDED'})
        self.assertEqual(device_op_results, {'5a11-qfx4': 'fake_output'})
        self.assertEqual(failed_devices_list, ['fake'])

    def test_existing_fabric_job(self):
        fake_exec_id = '09c1f45c-c387-4278-9acb-062d20db3d09'
        fake_fabric_name = "fake_fabric"

        # Force a ResourceExistsError
        def side_effect(*args, **kwargs):
            raise ResourceExistsError(fake_fabric_name, fake_exec_id)

        self.zk_mock.create_node.side_effect = side_effect

        # Make the call to check if there is an existing job
        is_fabric_job_running = self.djm._is_existing_job_for_fabric(
            fake_fabric_name, fake_exec_id)
        # We should receive a true
        self.assertTrue(is_fabric_job_running)
        # Clear the side effect that raises ResourceExistsError
        self.zk_mock.create_node.side_effect = None

        # Since we are not forcibly raising a ResourceExistsError
        # we should receive a false here
        is_fabric_job_running = self.djm._is_existing_job_for_fabric(
            fake_fabric_name, fake_exec_id)
        self.assertFalse(is_fabric_job_running)

    def test_create_pr_uve(self):
        fake_input_params = {
            'device_json': {
                'c589e830-503c-46c6-a99b-1c2ca929d353': {
                    'device_fqname': ['fake', 'device']
                }
            }
        }
        fake_device_list = ['c589e830-503c-46c6-a99b-1c2ca929d353']
        fake_fabric_job_uve_name = 'fake:fabric'
        fake_job_status = JobStatus.FAILURE.value
        fake_percentage_completed = 100

        # Mock PhysicalRouterJobUve.send()
        pr_job_uve_patch = mock.patch('device_manager.device_job_manager.'
                                      'PhysicalRouterJobUve.send')
        pr_job_uve_mock = pr_job_uve_patch.start()

        # Make the call to create and send pr uve
        prouter_fqname = self.djm.create_physical_router_job_uve(
            fake_device_list, fake_input_params, fake_fabric_job_uve_name,
            fake_job_status, fake_percentage_completed)

        # Verify the call to PhysicalRouterJobUve.send()
        pr_job_uve_mock.assert_called_once()
        # Verify that the proper name was created and returned
        self.assertEqual(prouter_fqname, ['fake:device:fake:fabric'])

        # Stop mocking
        pr_job_uve_patch.stop()
