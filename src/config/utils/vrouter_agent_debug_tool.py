#!/usr/bin/python
#
# Copyright (c) 2018 Juniper Networks, Inc. All rights reserved.
#

"""
Synopsis:
    Collect logs, gcore(optional), introspect logs, sandesh traces and
    docker logs from vrouter node.
    Collect logs specific to control node.
Usage:
    python vrouter_agent_debug_info.py -i <input_file>
Options:
    -h, --help          Display this help information.
    -i                  Input file which has vrouter and control node details.
                        This file should be a yaml file.
                        Template and a sample input_file is shown below.
                        You need to mention ip, ssh_user and ssh_pwd/ssh_key_file
                        required to login to vrouter/control node.
                        Specify deployment_method from rhosp_director'/'ansible'/'kubernetes'
                        Specify vim from from 'rhosp'/'openstack'/'kubernetes'
                        You can add multiple vrouter or control node details.
                        Specify gcore_needed as true if you want to collect gcore.
Template for input file:
------------------------
provider_config:
  deployment_method: 'rhosp_director'/'ansible'/'kubernetes'
  vim: 'rhosp'/'openstack'/'kubernetes'
  vrouter:
    node1:
      ip: <ip-address>
      ssh_user: <username>
      ssh_pwd: <password>
      ssh_key_file: <ssh key file>
      gcore_needed: <true/false>
    node2:
    .
    .
    .
    noden:
  control:
    node1:
      ip: <ip-address>
      ssh_user: <username>
      ssh_pwd: <password>
      ssh_key_file: <ssh key file>
      gcore_needed: <true/false>
    node2:
    .
    .
    .
    noden:
  config:
    node1:
      ip: <ip-address>
      ssh_user: <username>
      ssh_pwd: <password>
      db_manage: <true/false>
      object_port: port-number  #config object port
      cache_count: number       #object cache count
    node2:
    .
    .
    .
    noden:

sample_input.yaml
-----------------
provider_config:
  #deployment_method: 'rhosp_director'/'ansible'/'kubernetes'
  deployment_method: 'rhosp_director'
  #vim: 'rhosp'/'openstack'/'kubernetes'
  vim: 'rhosp'
  vrouter:
    node1:
      ip: 192.168.24.7
      ssh_user: heat-admin
      # if deployment_method is rhosp then ssh_key_file is mandatory
      ssh_key_file: '/home/stack/.ssh/id_rsa'
      gcore_needed: true
    node2:
      ip: 192.168.24.8
      ssh_user: heat-admin
      # if deployment_method is rhosp then ssh_key_file is mandatory
      ssh_key_file: '/home/stack/.ssh/id_rsa'
      gcore_needed: true
  control:
    node1:
      ip: 192.168.24.9
      ssh_user: heat-admin
      ssh_key_file: '/home/stack/.ssh/id_rsa'
      gcore_needed: true
    node2:
      ip: 192.168.24.23
      ssh_user: heat-admin
      ssh_key_file: '/home/stack/.ssh/id_rsa'
      gcore_needed: true
  config:
    node1:
      ip: 192.168.24.10
      ssh_user: heat-admin
      ssh_key_file: '/home/stack/.ssh/id_rsa'
      db_manage: true/false
      object_port: 8082
      cache_count: 10000
    node2:
      ip: 192.168.24.11
      ssh_user: heat-admin
      ssh_key_file: '/home/stack/.ssh/id_rsa'
      db_manage: true
      object_port: 8082
      cache_count: 10000

"""
from __future__ import print_function

from future import standard_library
standard_library.install_aliases()
from builtins import str
from builtins import range
from builtins import object
import subprocess
import time
import sys
import warnings

warnings.filterwarnings(action='ignore', module='.*paramiko.*')
from urllib.request import urlopen
from urllib.error import URLError, HTTPError
import paramiko
import yaml
import xml.etree.ElementTree as ET
import stat
import itertools
import json

sudo_prefix = 'sudo '
deployment_map = {
        'rhosp_director': {
            'rhosp': {
                'vrouter': {
                    'process_name': ['contrail-vrouter-agent'],
                    'container_name': ['contrail_vrouter_agent'],
                    'gcore_container_name': ['contrail_vrouter_agent']
                    },
                'control': {
                    'process_name': ['contrail-control', 'contrail-dns'],
                    'container_name': ['contrail_control_control', 'contrail_control_named', 'contrail_control_nodemgr', 'contrail_control_dns'],
                    'gcore_container_name': ['contrail_control_control', 'contrail_control_dns']
                    },
                'analytics': {
                    'process_name': ['contrail-collector', 'contrail-query-engine'],
                    'container_name': ['contrail_analytics_collector', 'contrail_analytics_queryengine', 'contrail_analytics_database_nodemgr', 'contrail_analytics_database', 'contrail_analytics_api', 'contrail_analytics_topology', 'contrail_analytics_snmp_collector', 'contrail_analytics_snmp_nodemgr', 'contrail_analytics_kafka', 'contrail_analytics_zookeeper'],
                    'gcore_container_name': ['contrail_analytics_collector', 'contrail_analytics_queryengine'],
                    'kafka_container_name': 'contrail_analytics_kafka',
                    'contrail_stats_container_name': 'contrail_analytics_api'
                    },
                'config': {
                    'container_name': ['config_api','config_nodemgr','config_devicemgr','config_schema','config_svcmonitor','config_provisioner','config_dnsmasq','config_database_nodemgr','config_database_provisioner','config_database_zookeeper', 'config_database_rabbitmq','config_database_cassandra'],
                    },
                'lib_path': '/usr/lib64/',
                'log_path': '/var/log/containers/contrail/'
                }
            },
        'ansible': {
            'openstack': {
                'vrouter': {
                    'process_name': ['contrail-vrouter-agent'],
                    'container_name': ['vrouter_vrouter-agent_1'],
                    'gcore_container_name': ['vrouter_vrouter-agent_1']
                    },
                'control': {
                    'process_name': ['contrail-control', 'contrail-dns'],
                    'container_name': ['control_control_1', 'control_named_1', 'control_provisioner_1', 'control_nodemgr_1', 'control_dns_1'],
                    'gcore_container_name': ['control_control_1', 'control_dns_1']
                    },
                'analytics': {
                    'process_name': ['contrail-collector', 'contrail-query-engine'],
                    'container_name': ['analytics_collector_1', 'analytics_database_query-engine_1', 'analytics_database_nodemgr_1', 'analytics_database_provisioner_1', 'analytics_database_cassandra_1', 'analytics_nodemgr_1', 'analytics_provisioner_1', 'analytics_api_1', 'analytics_snmp_provisioner_1', 'analytics_snmp_topology_1', 'analytics_snmp_snmp-collector_1', 'analytics_snmp_nodemgr_1', 'analytics_alarm_alarm-gen_1', 'analytics_alarm_provisioner_1', 'analytics_alarm_nodemgr_1', 'analytics_alarm_kafka_1'],
                    'gcore_container_name': ['analytics_collector_1', 'analytics_database_query-engine_1'],
                    'kafka_container_name': 'analytics_alarm_kafka_1',
                    'contrail_stats_container_name': 'analytics_api_1'
                    },
                'config': {
                    'container_name': ['config_api_1','config_nodemgr_1','config_devicemgr_1','config_schema_1','config_svcmonitor_1','config_provisioner_1','config_dnsmasq_1','config_database_nodemgr_1','config_database_provisioner_1','config_database_zookeeper_1','config_database_rabbitmq_1','config_database_cassandra_1'],
                    },
                'lib_path': '/usr/lib64/',
                'log_path': '/var/log/contrail/'
                },
            'kubernetes': {
                'vrouter': {
                    'process_name': ['contrail-vrouter-agent'],
                    'container_name': ['vrouter_vrouter-agent_1'],
                    'gcore_container_name': ['vrouter_vrouter-agent_1']
                    },
                'control': {
                    'process_name': ['contrail-control', 'contrail-dns'],
                    'container_name': ['control_control_1', 'control_named_1', 'control_provisioner_1', 'control_nodemgr_1', 'control_dns_1'],
                    'gcore_container_name': ['control_control_1', 'control_dns_1']
                    },
                'analytics': {
                    'process_name': ['contrail-collector', 'contrail-query-engine'],
                    'container_name': ['analytics_collector_1', 'analytics_database_query-engine_1', 'analytics_database_nodemgr_1', 'analytics_database_provisioner_1', 'analytics_database_cassandra_1', 'analytics_nodemgr_1', 'analytics_provisioner_1', 'analytics_api_1', 'analytics_snmp_provisioner_1', 'analytics_snmp_topology_1', 'analytics_snmp_snmp-collector_1', 'analytics_snmp_nodemgr_1', 'analytics_alarm_alarm-gen_1', 'analytics_alarm_provisioner_1', 'analytics_alarm_nodemgr_1', 'analytics_alarm_kafka_1'],
                    'gcore_container_name': ['analytics_collector_1', 'analytics_database_query-engine_1'],
                    'kafka_container_name': 'analytics_alarm_kafka_1'
                    },
                'config': {
                    'container_name': ['config_api_1','config_nodemgr_1','config_devicemgr_1','config_schema_1','config_svcmonitor_1','config_provisioner_1','config_dnsmasq_1','config_database_nodemgr_1','config_database_provisioner_1','config_database_zookeeper_1','config_database_rabbitmq_1','config_database_cassandra_1'],
                    },
                'lib_path': '/usr/lib64/',
                'log_path': '/var/log/contrail/'
                }
            }
        }


class Debug(object):
    _base_dir = None
    _compress_file = None

    def __init__(self, dir_name, sub_dirs, process_name, container_name,
                 gcore_container_name, kafka_container_name,
                 contrail_stats_container_name, log_path, lib_path, cli,
                 host, port, user, pw, ssh_key_file):
        self._dir_name = dir_name
        self._tmp_dir = None
        self._process_name = process_name
        self._container = container_name
        self._gcore_container = gcore_container_name
        self._kafka_container = kafka_container_name
        self._contrail_stats_container = contrail_stats_container_name
        self._log_path = log_path
        self._lib_path = lib_path
        self._cli = cli
        self._host = host
        self._port = port
        self._introspect = Introspect(host, port)
        self._user = user
        self._pwd = pw
        self._ssh_key_file = ssh_key_file
        self._sub_dirs = sub_dirs
        self._core_file_name = []
        self._parent_dir = None
        self._ssh_client = self.create_ssh_connection(self._host, self._user,
                                                      self._pwd, self._ssh_key_file)
        if self._ssh_client is None:
            # Ssh connection to agent node failed. Hence terminate script.
            print('Could not create ssh connection with host: %s' % self._host)
            sys.exit()
    # end __init__

    @staticmethod
    def create_base_dir(name):
        Debug._base_dir = '/var/log/%s-%s' % (name,
                                              time.strftime("%Y%m%d-%H%M%S"))
        cmd = sudo_prefix + 'mkdir %s' % (Debug._base_dir)
        subprocess.call(cmd, shell=True)
    # end create_base_dir

    def create_sub_dirs(self):
        timestr = time.strftime("%Y%m%d-%H%M%S")
        self._dir_name = '%s-%s-%s' % (self._dir_name, self._host,
                                       timestr)
        self._tmp_dir = '/tmp/%s' % (self._dir_name)
        self._parent_dir = '%s/%s' % (Debug._base_dir, self._dir_name)
        cmd = sudo_prefix + 'mkdir %s' % (self._tmp_dir)
        ssh_stdin, ssh_stdout, ssh_stderr = self._ssh_client.exec_command(cmd)
        cmd = sudo_prefix + 'mkdir %s' % (self._parent_dir)
        subprocess.call(cmd, shell=True)
        # create sub-directories
        for item in self._sub_dirs:
            cmd = sudo_prefix + 'mkdir %s/%s' % (self._parent_dir, item)
            subprocess.call(cmd, shell=True)
    # end create_directories

    def get_log_files(self, sftp_client, remote_dir, dest_dir):
        try:
            sftp_client.stat(remote_dir)
        except IOError, e:
            print('\nCopying logs: Failed (no file exists)')
            return

        for filename in sftp_client.listdir(remote_dir):
            if stat.S_ISDIR(sftp_client.stat(remote_dir + filename).st_mode):
                new_dest_dir = '%s/%s' % (dest_dir, filename)
                new_remote_dir = '%s/%s/' % (remote_dir, filename)
                cmd = sudo_prefix + 'mkdir %s' % new_dest_dir
                subprocess.call(cmd, shell=True)
                # recursive retrieval
                self.get_log_files(sftp_client, new_remote_dir, new_dest_dir)
            else:
                src_file = '%s%s' % (remote_dir, filename)
                dest_file = '%s/%s' % (dest_dir, filename)
                sftp_client.get(src_file, dest_file)
    # end get_log_files

    def copy_docker_logs(self):
        print('\nTASK : copy docker logs')
        for container in self._container:
            file_path = '%s/docker_logs/docker_logs_%s.txt' % (self._parent_dir, container)
            try:
                f = open(file_path, 'a')
            except Exception as e:
                print('\nError opening file %s: %s' % (file_path, e))
                print('\nCopying docker logs from container %s : Failed' % (container))
                continue
            # run below commands in node where agent is running
            # and append the logs to file
            cmd = sudo_prefix + 'docker logs %s' % container
            if not cmd:
                print('\nError creating command docker logs %s' % (container))
                print('\nCopying docker logs from container %s : Failed' % (container))
                continue

            cmd_op = self.get_ssh_cmd_output(cmd)
            if 'Error: No such container:' in cmd_op:
                print('\nError getting the output of command %s' % (cmd))
                print('\nCopying docker logs from container %s : Failed' % (container))
                continue

            f.write(cmd_op)

        print('\nCopying docker logs : Success')
        file_path = '%s/logs/docker_images.txt' % (self._parent_dir)
        try:
            f = open(file_path, 'a')
        except Exception as e:
            print('\nError opening file %s: %s' % (file_path, e))
            print('\nCopying docker images %s : Failed')
            return

        cmd = sudo_prefix + 'docker images'
        if not cmd:
            print('\nError creating command docker images')
            print('\nCopying docker images : Failed')
            return

        f.write(cmd)
        cmd_op = self.get_ssh_cmd_output(cmd)
        if not cmd_op:
            print('\nError getting the output of command %s' % (cmd))
            print('\nCopying docker images : Failed')
            return

        f.write(cmd_op)
        f.close()
        print('\nCopying docker images : Success')
    # end copy_docker_logs

    def copy_contrail_status(self):
        print('\nTASK : copy contrail status')
        file_path = '%s/logs/contrail_status.txt' % (self._parent_dir)
        try:
            f = open(file_path, 'a')
        except Exception as e:
            print('\nError opening file %s: %s' % (file_path, e))
            print('\nCopying contrail status : Failed')
            return
        # run 'contrail-status' on current node and copy the output
        cmd = sudo_prefix + 'contrail-status'
        cmd_op = self.get_ssh_cmd_output(cmd)
        if not cmd_op:
            print('\nEmpty output after running the command: %s' % (cmd))
            print('\nCopying contrail status : Failed')
            return
        f.write(cmd_op)
        f.close()
        print('\nCopying contrail status : Success')
    # end copy_contrail_status

    def generate_gcore(self):
        print('\nTASK : generate gcore')
        ret = 0
        for gcore_container, process in itertools.izip(self._gcore_container, self._process_name):
            cmd = sudo_prefix + 'docker exec %s pidof %s' % (gcore_container,
                                                             process)
            ssh_stdin, ssh_stdout, ssh_stderr = self._ssh_client.exec_command(cmd)
            pid = ssh_stdout.readline().strip()
            prefix = 'core.%s' % (gcore_container)
            gcore_name = 'core.%s.%s' % (gcore_container, pid)

            cmd = sudo_prefix + 'docker exec %s gcore -o %s %s' % (gcore_container, prefix, pid)
            ssh_stdin, ssh_stdout, ssh_stderr = self._ssh_client.exec_command(cmd)
            exit_status = ssh_stdout.channel.recv_exit_status()
            if not exit_status == 0:
                print('\nGenerating %s gcore for container %s : Failed. Error %s' \
                      % (process, gcore_container, exit_status))
                continue

            cmd = sudo_prefix + 'docker exec %s ls %s' % (gcore_container, gcore_name)
            ssh_stdin, ssh_stdout, ssh_stderr = self._ssh_client.exec_command(cmd)
            core_name = ssh_stdout.readline().strip('\n')
            if 'core' not in core_name:
                print('\nGenerating %s gcore for container %s : Failed. Gcore not found' \
                      % (gcore_container, process))
                continue

            self._core_file_name.append(core_name)
            print('\nGenerating %s gcore for container %s : Success' % (gcore_container, process))
            ret = 1
        return ret
    # end generate_gcore

    def copy_gcore(self):
        print('\nTASK : copy gcore')
        merged_dir_paths = self.get_merged_dir_path('gcore')
        for core_file_name, merged_dir_path in itertools.izip(self._core_file_name, merged_dir_paths):
            cmd = sudo_prefix + 'cp %s/%s %s' % (merged_dir_path, core_file_name, self._tmp_dir)
            ssh_stdin, ssh_stdout, ssh_stderr = self._ssh_client.exec_command(cmd)
            exit_status = ssh_stdout.channel.recv_exit_status()
            if not exit_status == 0:
                print('\nCopying gcore failed')
                continue

            src_file = '%s/%s' % (self._tmp_dir, core_file_name)
            dest_file = '%s/gcore/%s' % (self._parent_dir, core_file_name)
            if self.do_ftp(src_file, dest_file):
                print('\nCopying gcore file %s : Success' % (core_file_name))
                cmd = sudo_prefix + 'rm -rf %s/%s' % (merged_dir_path, core_file_name)
                ssh_stdin, ssh_stdout, ssh_stderr = self._ssh_client.exec_command(cmd)
            else:
                print('\nCopying gcore file : Failed')
    # end copy_gcore

    def get_merged_dir_path(self, container_type):
        # get merged directory path between container and host
        merged_dir_paths = []
        if container_type == 'gcore':
            containers_list = self._gcore_container
        else:
            containers_list = self._container
        for container in containers_list:
            cmd = sudo_prefix + 'docker inspect %s | grep merge' % container
            ssh_stdin, ssh_stdout, ssh_stderr = self._ssh_client.exec_command(cmd)
            output = ssh_stdout.readline().strip()
            if not output:
                print('\nEmpty output after running command: %s' \
                      % (cmd))
                continue
            try:
                merged_dir_path = output.split(':')[1][2:-2]
                merged_dir_paths.append(merged_dir_path)
            except Exception as e:
                print('\nError retrieving path to container file %s: %s' % (container, e))
                continue
        return merged_dir_paths
    # end get_merged_dir_path

    def copy_libraries(self, lib_list):
        print('\nTASK : copy libraries')
        merged_dir_paths = self.get_merged_dir_path('container')
        for lib_name in lib_list:
            for container, merged_dir_path in itertools.izip(self._container, merged_dir_paths):
                cmd = sudo_prefix + 'docker exec %s echo $(readlink %s%s.so*)' \
                      % (container, self._lib_path, lib_name)
                # get exact library name
                ssh_stdin, ssh_stdout, ssh_stderr = self._ssh_client.exec_command(cmd)
                exit_status = ssh_stdout.channel.recv_exit_status()
                if not exit_status == 0:
                    print('\nCopying library %s  : Failed. Error %s' \
                          % (lib_name, exit_status))
                    continue
                lib_name = ssh_stdout.readline().rstrip('\n')
                # copy library to tmp directory
                src_file = '%s/usr/lib64/%s' % (merged_dir_path, lib_name)
                cmd = sudo_prefix + 'cp %s %s' % (src_file, self._tmp_dir)
                ssh_stdin, ssh_stdout, ssh_stderr = self._ssh_client.exec_command(cmd)
                exit_status = ssh_stdout.channel.recv_exit_status()
                if not exit_status == 0:
                    print('\nCopying library %s  : Failed. Error %s' \
                          % (lib_name, exit_status))
                    continue
                # do ftp to copy the library
                src_file = '%s/%s' % (self._tmp_dir, lib_name)
                dest_file = '%s/libraries/%s' % (self._parent_dir, lib_name)
                if self.do_ftp(src_file, dest_file):
                    print('\nCopying library %s : Success' % lib_name)
                else:
                    print('\nCopying library %s : Failed' % lib_name)
    # end copy_libraries

    def copy_introspect(self):
        print('\nTASK : Copy introspect logs')
        # for vrouter, we have only one container
        container = self._container[0]
        cmd = 'docker exec %s %s read' % (container, self._cli)
        cmd = sudo_prefix + cmd
        # executing above command will return list of all
        # the sub-commands which we will run in loop to
        # collect all the agent introspect logs
        cmd_list = self.get_ssh_cmd_output(cmd).split('\n')
        # delete first and last element as they are not commands
        del cmd_list[0]
        if len(cmd_list) > 0:
            del cmd_list[-1]
        if not cmd_list:
            print('\nError running cmd: %s' % cmd)
            print('Copying introspect logs : Failed')
            return
        for i in range(len(cmd_list)):
            # remove leading and trailing white spaces if any
            cmd_list[i] = cmd_list[i].strip()
            cmd = sudo_prefix + 'docker exec %s %s %s' % (container,
                                                          self._cli, cmd_list[i])
            print('Collecting output of command [%s %s]' % (self._cli, cmd_list[i]))
            cmd_op = self.get_ssh_cmd_output(cmd)
            if not cmd_op:
                continue
            # create file name for for each command
            tmp_str = cmd_list[i].split()
            file_name = '_'.join(tmp_str)
            file_path = self._parent_dir + '/introspect/' + file_name
            try:
                f = open(file_path, 'a')
            except Exception as e:
                print('\nError opening file %s: %s' % (file_path, e))
                continue
            f.write(cmd_op)
            f.close()
        print('\nCopying introspect logs : Success')
    # end copy_introspect

    def copy_nested_hyperlink_info(self, linkLists):
        print('\nTASK : Copy config nested hyperlinks with "detail=true"')

        # create temp file
        dest_path = '%s/introspect/configNestedHyperLinkFile.txt' \
                    % (self._parent_dir)

        with open(dest_path, 'a') as f:
            for ll in linkLists[1:]:
                f.write(ll['link']['href'])
                f.write("\n")
                myCmd = 'curl -udamin:%s %s?detail=true | python -m json.tool' %(self._pwd,ll['link']['href'])
                cmd_op = self.get_ssh_cmd_output(myCmd)
                f.write(cmd_op)
                f.write("\n")
            f.close()
        print('\nCopying config nested hyperlinks to file: Success')
    # end copy_nested_hyperlink_info

    def copy_config_object_info(self,port):
        print('\nTASK : Copy config object hyperlinks port: %d' %port)
        myCmd = 'curl -udamin:%s %s:%s | python -m json.tool' %(self._pwd,self._host,str(port))
        print(myCmd)
        cmd_op = self.get_ssh_cmd_output(myCmd)

        if not cmd_op:
            print('\nNo output for command %s' % myCmd)
            print('\nCopying config object hyperlinks: Failed')
            return

        # create temp file
        dest_path = '%s/introspect/configHyperLinkFile.txt' \
                    % (self._parent_dir)

        with open(dest_path, 'a') as f:
            f.write(cmd_op)
            f.close()
        print('\nCopying config object hyperlinks to file: Success')

        allLinks = json.loads(cmd_op)
        self.copy_nested_hyperlink_info(allLinks['links'])
    # end copy_config_object_info

    def copy_cached_object_info(self,port,count):
        print('\nTASK : Copy cached object of API-SERVER')

        myCmd = 'curl -udamin:%s -q -g -X POST http://%s:%s/obj-cache -H "Content-Type: application/json" -d \'{"count": %s}\' | python -m json.tool' %(self._pwd,self._host,str(port),str(count))
        print(myCmd)
        cmd_op = self.get_ssh_cmd_output(myCmd)

        if not cmd_op:
            print('\nNo output for command %s' % myCmd)
            print('\nCopying cached object of API-SERVERs: Failed')
            return

        # create temp file
        dest_path = '%s/logs/configCachedObjectDump.txt' \
                    % (self._parent_dir)

        with open(dest_path, 'a') as f:
            f.write(cmd_op)
            f.close()
        print('\nCopying cached object of API-SERVER: Success')
    # end copy_cached_object_info

    def copy_db_manage_dry_run(self,str):
        print('\nTASK : Copy db_manage %s dry run'%(str))

        container = self._container[0]
        myCmd = sudo_prefix + 'docker exec %s /bin/sh -c " find -name db_manage.py"'%(container)
        find_db = self.get_ssh_cmd_output(myCmd)

        if not find_db:
            print('\nNo output for command %s' % myCmd)
            return

        myCmd = sudo_prefix + 'docker exec %s /bin/sh -c " find /etc/contrail/ -name contrail-api* "'%(container)
        conf_api = self.get_ssh_cmd_output(myCmd)

        if not conf_api:
            print('\nNo output for command %s' % myCmd)
            return

        myCmd = sudo_prefix + 'docker exec %s /bin/sh -c " python %s %s --api-conf %s --log_file dbManage%s.txt" '%(container,find_db,str,conf_api,str)
        print(myCmd)
        cmd_op = self.get_ssh_cmd_output(myCmd)

        myCmd = sudo_prefix + 'docker cp %s:dbManage%s.txt %s/logs/' %(container,str,self._parent_dir)
        print(myCmd)
        cmd_op = self.get_ssh_cmd_output(myCmd)

        print('\nCopying db_manage %s dry run: Success' %(str))
    # end copy_db_manage_dry_run

    def copy_sandesh_traces(self, path):
        print('\nTASK : copy sandesh traces')
        if self._introspect.get(path) == 0:
            print('\nCopying sandesh traces : Failed')
            return
        trace_buffer_list = self._introspect.getTraceBufferList('trace_buf_name')
        for i in range(len(trace_buffer_list)):
            tmp_str = trace_buffer_list[i].split()
            file_name = '_'.join(tmp_str)
            file_path = self._parent_dir + '/sandesh_trace/' + file_name
            try:
                f = open(file_path, 'a')
            except Exception as e:
                print('\nError opening file %s: %s' % (file_path, e))
                print('\nCopying sandesh traces : Failed')
                return
            print('Collecting sandesh trace [%s]' % trace_buffer_list[i])
            self._introspect.get('Snh_SandeshTraceRequest?x=' \
                                 + trace_buffer_list[i])
            if self._introspect.output_etree is not None:
                for element in \
                        self._introspect.output_etree.iter('element'):
                    f.write( \
                        Introspect.elementToStr('', element).rstrip())
                    f.write('\n')
            f.close()
        print('\nCopying sandesh traces : Success')
    # end copy_sandesh_traces

    def copy_analytics_node_cassandra_db_storage_space(self):
        print('\nTASK : analytics Cassandra DB volumes storage space')
        myCmd = sudo_prefix + 'du -smx \
                /var/lib/docker/volumes/analytics_database_analytics_cassandra/_data/ContrailAnalyticsCql/*'
        cmd_op = self.get_ssh_cmd_output(myCmd)

        if not cmd_op:
            print('\nNo output for command %s' % myCmd)
            print('\nCopying analytics Cassandra DB volumes storage space: Failed')
            return

        # create temp file
        dest_path = '%s/logs/ContrailAnalyticsCql_File.txt' \
                    % (self._parent_dir)
        try:
            f = open(dest_path, 'a')
        except Exception as e:
            print('\nError opening file %s: %s' % (dest_path, e))
            print('\nCopying analytics Cassandra DB volumes storage space: Failed')
            return

        f.write(cmd_op)
        f.close()
        print('\nCopying analytics Cassandra DB volumes storage space: Success')
    # end copy_analytics_node_cassandra_db_storage_space

    def copy_config_node_cassandra_db(self):
        print('\nTASK : config Cassandra DB volumes storage space')
        myCmd = sudo_prefix + 'du -sh \
                /var/lib/docker/volumes/config_database_config_cassandra/_data/*'
        cmd_op = self.get_ssh_cmd_output(myCmd)

        if not cmd_op:
            print('\nNo output for command %s' % myCmd)
            print('\nCopying config Cassandra DB volumes storage space: Failed')
            return

        # create temp file
        dest_path = '%s/logs/ContrailConfigCassandraData_File.txt' \
                    % (self._parent_dir)
        with open(dest_path, 'a') as f:
            f.write(cmd_op)
            f.close()

        print('\nCopying config Cassandra DB volumes storage space: Success')
    # end copy_config_node_cassandra_db

    def copy_analytics_node_contrail_stats(self):
        print('\nTASK : contrail-stats SandeshMessageStat')
        myCmd = sudo_prefix + 'docker exec %s /bin/sh -c "contrail-stats --table SandeshMessageStat.msg_info --select Source msg_info.type \'SUM(msg_info.messages)\' \'SUM(msg_info.bytes)\' --start-time now-180m --end-time now" ' % (self._contrail_stats_container)
        print(myCmd)
        cmd_op = self.get_ssh_cmd_output(myCmd)
        if not cmd_op:
            print('\nNo output for command %s' % myCmd)
            print('\nCopying contrail-stats SandeshMessageStat: Failed')
            return

        # create temp file
        dest_path = '%s/logs/ContrailStats_File.txt' \
                    % (self._parent_dir)
        try:
            f = open(dest_path, 'a')
        except Exception as e:
            print('\nCopying contrail-stats SandeshMessageStat: Failed')
            return

        f.write(cmd_op)
        f.close()
        print('\nCopying contrail-stats SandeshMessageStat: Success')
    # end copy_analytics_node_contrail_stats

    def copy_analytics_node_kafka_topics(self):
        print('\nTASK : Copy kafka-topics list')
        myCmd = sudo_prefix + "docker exec %s /bin/sh -c 'bin/kafka-topics.sh --list --zookeeper $ZOOKEEPER_NODES:$ZOOKEEPER_PORT' " % (self._kafka_container)
        print(myCmd)
        cmd_op = self.get_ssh_cmd_output(myCmd)
        if not cmd_op:
            print('\nNo output for command %s' % myCmd)
            print('\nCopying kafka-topics list: Failed')
            return

        # create temp file
        dest_path = '%s/logs/KafkaTopics_File.txt' \
                    % (self._parent_dir)
        try:
            f = open(dest_path, 'a')
        except Exception as e:
            print('\nError opening file %s: %s' % (dest_path, e))
            print('\nCopying kafka-topic list: Failed')
            return

        f.write(cmd_op)
        f.close()
        print('\nCopying kafka-topic list: Success')
        lines = cmd_op.splitlines()
        for line in lines:
            if 'uve' in line:
                myCmd = sudo_prefix + "docker exec %s /bin/sh -c 'bin/kafka-topics.sh --zookeeper $ZOOKEEPER_NODES:$ZOOKEEPER_PORT --describe --topic %s' " % (self._kafka_container, line)
                print(myCmd)
                cmd_op = self.get_ssh_cmd_output(myCmd)
                if not cmd_op:
                    print('\nNo output for command %s' % myCmd)
                    print('\nCopying kafka-topic describe %s: Failed' % (line))
                    continue

                # create temp file
                dest_path = '%s/logs/KafkaTopics_File%s.txt' \
                            % (self._parent_dir, line)
                try:
                    f = open(dest_path, 'a')
                except Exception as e:
                    print('\nError opening file %s: %s' % (dest_path, e))
                    print('\nCopying kafka-topic describe %s: Failed' % (line))
                    return

                f.write(cmd_op)
                f.close()
                print('\nCopying kafka-topic describe %s: Success' % (line))
    # end copy_analytics_node_kafka_topics

    def copy_contrail_logs(self, node_type):
        print('\nTASK : Copy %s contrail logs' % (node_type))
        if self._ssh_client is None:
            print('\nCopying %s contrail logs: Failed' % (node_type))
            return

        # open ftp connection and copy logs
        sftp_client = self._ssh_client.open_sftp()
        remote_dir = self._log_path
        dest_dir = '%s/logs/' % self._parent_dir
        self.get_log_files(sftp_client, remote_dir, dest_dir)
        print('\nCopying %s contrail logs: Success' % (node_type))

        sftp_client.close()
    # end copy_contrail_logs

    def copy_docker_inspect_info(self):
        print('\nTASK : Copy docker inspect info')
        for container in self._container:
            file_path = '%s/docker_inspect/docker_inspect_%s.txt' % (self._parent_dir, container)
            try:
                f = open(file_path, 'a')
            except Exception as e:
                print('\nError opening file %s: %s' % (file_path, e))
                print('\nCopying docker inspect info from container %s : Failed' % (container))
                continue
            # run below commands in node where agent is running
            # and append the logs to file
            cmd = sudo_prefix + 'docker inspect %s' % container
            if not cmd:
                print('\nError creating command docker inspect %s' % (container))
                print('\nCopying docker inspect info from container %s : Failed' % (container))
                continue

            cmd_op = self.get_ssh_cmd_output(cmd)
            if 'Error: No such container:' in cmd_op:
                print('\nError getting the output of command %s' % (cmd))
                print('\nCopying docker inspect info from container %s : Failed' % (container))
                continue

            f.write(cmd_op)

        print('\nCopying docker inspect info : Success')
    # end copy_docker_inspect_info

    def create_ssh_connection(self, ip, user, pw, key_file):
        try:
            client = paramiko.SSHClient()
            client.load_system_host_keys()
            client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            if key_file:
                client.connect(ip, username=user, key_filename=key_file)
            else:
                client.connect(ip, username=user, password=pw)
            return client
        except Exception as e:
            print('\nError: ssh connection failed for ip %s: %s' % (ip, e))
            return None
    # end create_ssh_connection

    def get_ssh_cmd_output(self, cmd):
        ssh_stdin, ssh_stdout, ssh_stderr = self._ssh_client.exec_command(cmd)
        output = ssh_stdout.read().decode().strip()
        return output
    # end get_ssh_cmd_output

    def do_ftp(self, src_file, dest_file):
        sftp_client = self._ssh_client.open_sftp()
        max_count = 10
        count = 0
        while count < max_count:
            count = count + 1
            try:
                sftp_client.get(src_file, dest_file)
            except Exception as e:
                print('\n%s while copying file %s. Retry attempt %s of %s ' \
                      % (e, src_file, count, max_count))
                time.sleep(5)
                continue
            else:
                sftp_client.close()
                return 1
        sftp_client.close()
        return 0
    # end do_ftp

    def get_vrouter_logs(self):
        print('\nTASK : copy vrouter logs')
        print("\nDumping the output of commands to files")
        commands = ['nh --list', 'vrouter --info', 'dropstats',
                    'dropstats -l 0', 'vif --list', 'mpls --dump',
                    'vxlan --dump', 'vrfstats --dump', 'vrmemstats',
                    'qosmap --dump-fc',
                    'qosmap --dump-qos', 'mirror --dump', 'virsh list',
                    'ip ad', 'ip r', 'flow -s']

        myCmd = sudo_prefix + 'mkdir /tmp/vrouter_logs'
        cmd_op = self.get_ssh_cmd_output(myCmd)

        for i in range(len(commands)):
            str_value = commands[i]
            if str_value == "dropstats" or str_value == "dropstats -l 0":
                self.run_command_interval_times(str_value, 5, 5)  # command,interval,times
            elif str_value == "flow -s":
                self.run_command_interval_times(str_value, 20, 1)  # command,interval,times
            else:
                str_file_name = str_value.replace(' ', '')
                # for vrouter, we have only one container
                container = self._container[0]
                myCmd = sudo_prefix + 'docker exec %s /bin/sh -c "%s" ' % (container, str_value)
                print(myCmd)
                cmd_op = self.get_ssh_cmd_output(myCmd)
                if not cmd_op:
                    continue
                # create file name for for each command
                file_path = self._parent_dir + '/vrouter_logs/' + str_file_name
                try:
                    f = open(file_path, 'a')
                except Exception as e:
                    print('\nError opening file %s: %s' % (file_path, e))
                    continue
                f.write(cmd_op)
                f.close()
        try:
            self.get_per_vrf_logs()
        except Exception as e:
            print('Got exception %s' % e)
        try:
            self.get_virsh_individual_stats()
        except Exception as e:
            print('Got exception %s' % e)
    # end get_vrouter_logs

    def get_per_vrf_logs(self):
        print("\nParsing through the vrfstats dump and getting logs per vrf")
        # for vrouter, we have only one container
        container = self._container[0]
        myCmd = sudo_prefix + 'docker exec %s /bin/sh -c \
                "vrfstats --dump"' % (container)
        print(myCmd)
        cmd_op = self.get_ssh_cmd_output(myCmd)

        if not cmd_op:
            print('No output for command %s' % myCmd)
            return
        # create temp file
        file_name = "VRF_File2.txt"
        file_path = self._parent_dir + '/' + file_name
        try:
            f = open(file_path, 'a')
        except Exception as e:
            print('\nError opening file %s: %s' % (file_path, e))
            return
        f.write(cmd_op)
        f.close()

        with open(file_path) as file:
            data = file.read()
            values = []
            index = 0
            index2 = 0

        while index < len(data):
            index = data.find('Vrf:', index)
            if index == -1:
                break

            value = int(data[index + 5])
            index2 = data.find('\n', index)

            value2 = data[index + 5:index2]
            value3 = int(value2)

            if value3 != None:
                values.append(value3)

            index += 4
            index2 += 4

        family = ['inet', 'inet6', 'bridge']

        for i in range(len(values)):
            if values[i] != None:
                var = (values[i])

                for i in range(len(family)):
                    cmd = family[i]

                    myCmd = sudo_prefix + 'docker exec %s /bin/sh -c \
                        "rt --dump %d --family %s"' % (container, var, cmd)
                    cmd_op = self.get_ssh_cmd_output(myCmd)
                    dest_path = '%s/vrouter_logs/VRF_%d_Family%s' \
                                % (self._parent_dir, var, cmd)
                    # create file
                    try:
                        f = open(dest_path, 'a')
                    except Exception as e:
                        print('\nError opening file %s: %s' % (dest_path, e))
                        continue
                    if not cmd_op:
                        continue
                    f.write(cmd_op)
                    f.close()

        file.close()
        myCmd = sudo_prefix + 'rm -rf %s' % file_path
        cmd_op = self.get_ssh_cmd_output(myCmd)
        subprocess.call(myCmd, shell=True)
    # end get_per_vrf_logs

    def get_virsh_individual_stats(self):
        print("\nParsing through the virsh list and getting logs per virsh")

        # for vrouter, we have only one container
        container = self._container[0]
        myCmd = sudo_prefix + 'docker exec %s /bin/sh -c \
            "virsh list"' % (container)
        cmd_op = self.get_ssh_cmd_output(myCmd)

        if not cmd_op:
            print('No output for the command [%s]' % myCmd)
            return
        # create temp file
        file_name = "VIRSH_File2.txt"
        file_path = self._parent_dir + '/' + file_name
        try:
            f = open(file_path, 'a')
        except Exception as e:
            print('\nError opening file %s: %s' % (file_path, e))
            return
        f.write(cmd_op)
        f.close()

        with open(file_path, 'r') as file:
            data = file.read()
            values = []
            index = 0
            index2 = 0

        while index < len(data):
            index = data.find('instance-', index)
            if index == -1:
                break

            value = data[index]
            index2 = data.find(' ', index)

            value2 = data[index:index2]
            value3 = str(value2)

            if value3 != None:
                values.append(value3)

            index += 9
            index2 += 9

        commands = ['domstats', 'domiflist']

        for i in range(len(values)):
            if values[i] != None:
                var = (values[i])

                for i in range(len(commands)):
                    cmd = commands[i]
                    myCmd = sudo_prefix + 'docker exec %s /bin/sh -c \
                            "virsh %s %s"' % (container, cmd, var)
                    print(myCmd)
                    cmd_op = self.get_ssh_cmd_output(myCmd)
                    dest_path = '%s/vrouter_logs/virsh_%s_%s' \
                                % (self._parent_dir, cmd, var)

                    # create file
                    try:
                        f = open(dest_path, 'a')
                    except Exception as e:
                        print('\nError opening file %s: %s' % (dest_path, e))
                        continue
                    f.write(cmd_op)
                    f.close()

        file.close()
        myCmd = sudo_prefix + 'rm -rf %s' % file_path
        cmd_op = self.get_ssh_cmd_output(myCmd)
        subprocess.call(myCmd, shell=True)
    # end get_virsh_individual_stats

    def run_command_interval_times(self, cmd, interval, times):
        for i in range(times):
            file_num = i + 1
            str_file_name = cmd.replace(' ', '')
            # for vrouter, we have only one container
            container = self._container[0]
            myCmd = sudo_prefix + 'timeout %ds docker exec %s /bin/sh -c "%s"' \
                        % (interval, container, cmd)
            print(myCmd)
            cmd_op = self.get_ssh_cmd_output(myCmd)
            time.sleep(2)
            if not cmd_op:
                print('No output for the command %s' % myCmd)
                continue
            # create file name
            file_path = self._parent_dir + '/vrouter_logs/' + str_file_name + str(file_num)
            try:
                f = open(file_path, 'a')
            except Exception as e:
                print('\nError opening file %s: %s' % (file_path, e))
                continue
            f.write(cmd_op)
            f.close()
    # end run_command_interval_times

    @staticmethod
    def compress_folder(name):
        print("\nCompressing folder %s" % Debug._base_dir)
        Debug._compress_file = '/var/log/%s-%s.tar.gz' \
                               % (name, time.strftime("%Y%m%d-%H%M%S"))
        cmd = 'tar -zcf %s %s > /dev/null 2>&1' \
              % (Debug._compress_file, Debug._base_dir)
        subprocess.call(cmd, shell=True)
        print('\nComplete logs copied at %s' % Debug._compress_file)
    # end compress_folder

    def delete_tmp_dir(self):
        # delete tmp directory
        myCmd = sudo_prefix + 'rm -rf %s' % self._tmp_dir
        ssh_stdin, ssh_stdout, ssh_stderr = self._ssh_client.exec_command(myCmd)
    # end cleanup

    @staticmethod
    def delete_base_dir():
        # delete this directory as we have zipped it now
        myCmd = sudo_prefix + 'rm -rf %s' % Debug._base_dir
        subprocess.call(myCmd, shell=True)
    # end delete_base_dir


class Introspect(object):
    def __init__(self, host, port):
        self.host_url = "http://" + host + ":" + str(port) + "/"
    # end __init__

    def get(self, path):
        """ get introspect output """
        self.output_etree = None
        url = self.host_url + path.replace(' ', '%20')
        try:
            response = urlopen(url)
        except HTTPError as e:
            print('The server couldn\'t fulfill the request.')
            print('URL: ' + url)
            print('Error code: ', e.code)
            return 0
        except URLError as e:
            print('Failed to reach destination')
            print('URL: ' + url)
            print('Reason: ', e.reason)
            return 0
        else:
            ISOutput = response.read()
            response.close()
        self.output_etree = ET.fromstring(ISOutput)
        return 1
    # end get

    def getTraceBufferList(self, xpathExpr):
        """ get trace buffer list which contains all the trace names """
        trace_buffer_list = []
        if self.output_etree is not None:
            for element in self.output_etree.iter(xpathExpr):
                elem = Introspect.elementToStr('', element).rstrip()
                res = elem.split(':')[1].strip()
                trace_buffer_list.append(res)
        return trace_buffer_list
    # end getTraceBufferList

    @staticmethod
    def elementToStr(indent, etreenode):
        """ convernt etreenode sub-tree into string """
        elementStr = ''
        if etreenode.tag == 'more':  # skip more element
            return elementStr

        if etreenode.text and etreenode.tag == 'element':
            return indent + etreenode.text + "\n"
        elif etreenode.text:
            return indent + etreenode.tag + ': ' + \
                   etreenode.text.replace('\n', '\n' + \
                                          indent + (len(etreenode.tag) + 2) * ' ') + "\n"
        elif etreenode.tag != 'list':
            elementStr += indent + etreenode.tag + "\n"

        if 'type' in etreenode.attrib:
            if etreenode.attrib['type'] == 'list' and \
                    etreenode[0].attrib['size'] == '0':
                return elementStr

        for element in etreenode:
            elementStr += Introspect.elementToStr(indent + '  ', element)

        return elementStr
    # end elementToStr


USAGE_TEXT = __doc__


def usage():
    print(USAGE_TEXT)
    sys.exit(1)
# end usage

def parse_yaml_file(file_path):
    with open(file_path) as stream:
        try:
            yaml_data = yaml.safe_load(stream)
        except yaml.YAMLError as exc:
            print('Error[%s] while parsing file %s' % (exc, file_path))
            return None
        else:
            return yaml_data
# end parse_yaml_file

def collect_vrouter_node_logs(data):
    deployment_method = data['provider_config']['deployment_method']
    vim_type = data['provider_config']['vim']
    sub_dirs = ['docker_logs', 'docker_inspect', 'logs', 'gcore', 'libraries', 'introspect',
                'sandesh_trace', 'vrouter_logs']
    for item in data['provider_config']['vrouter']:
        try:
            gcore = data['provider_config']['vrouter'][item]['gcore_needed']
        except Exception as e:
            gcore = False
        host = data['provider_config']['vrouter'][item]['ip']
        user = data['provider_config']['vrouter'][item]['ssh_user']
        ssh_key_file = data['provider_config']['vrouter'][item].get('ssh_key_file')
        pw = data['provider_config']['vrouter'][item].get('ssh_pwd')
        port = 8085
        print('\nCollecting vrouter-agent logs for node : %s' % host)
        obj = Debug(dir_name='vrouter',
                    sub_dirs=sub_dirs,
                    process_name=deployment_map[deployment_method][vim_type]['vrouter']['process_name'],
                    container_name=deployment_map[deployment_method][vim_type]['vrouter']['container_name'],
                    gcore_container_name=deployment_map[deployment_method][vim_type]['vrouter']['gcore_container_name'],
                    kafka_container_name = None,
                    contrail_stats_container_name=None,
                    log_path=deployment_map[deployment_method][vim_type]['log_path'],
                    lib_path=deployment_map[deployment_method][vim_type]['lib_path'],
                    cli='contrail-vrouter-agent-cli',
                    host=host,
                    port=port,
                    user=user,
                    pw=pw,
                    ssh_key_file=ssh_key_file)
        obj.create_sub_dirs()
        try:
            obj.copy_contrail_logs('vrouter')
        except Exception as e:
            print('Error [%s] collecting vrouter node contrail logs' % e)
        try:
            obj.copy_docker_logs()
        except Exception as e:
            print('Error [%s] collecting docker logs' % e)
        try:
            obj.copy_docker_inspect_info()
        except Exception as e:
            print('Error [%s] collecting docker inspect info' % e)
        try:
            obj.copy_contrail_status()
        except Exception as e:
            print('Error [%s] collecting contrail-status logs' % e)
        lib_list = ['libc', 'libstdc++']
        try:
            obj.copy_libraries(lib_list)
        except Exception as e:
            print('Error [%s] collecting libraries' % e)
        try:
            obj.copy_introspect()
        except Exception as e:
            print('Error [%s] collecting introspect' % e)
        try:
            obj.copy_sandesh_traces('Snh_SandeshTraceBufferListRequest')
        except Exception as e:
            print('Error [%s] collecting sandesh traces' % e)
        try:
            obj.get_vrouter_logs()
        except Exception as e:
            print('Error [%s] collecting vrouter logs' % e)
        try:
            if gcore and obj.generate_gcore():
                obj.copy_gcore()
        except Exception as e:
            print('Error [%s] collecting gcore' % e)
        obj.delete_tmp_dir()
# end collect_vrouter_node_logs

def collect_control_node_logs(data):
    deployment_method = data['provider_config']['deployment_method']
    vim_type = data['provider_config']['vim']
    sub_dirs = ['docker_logs', 'docker_inspect', 'logs', 'gcore']
    for item in data['provider_config']['control']:
        try:
            gcore = data['provider_config']['control'][item]['gcore_needed']
        except Exception as e:
            gcore = False
        host = data['provider_config']['control'][item]['ip']
        user = data['provider_config']['control'][item]['ssh_user']
        ssh_key_file = data['provider_config']['control'][item].get('ssh_key_file')
        pw = data['provider_config']['control'][item].get('ssh_pwd')
        print('\nCollecting controller logs for control node : %s' % host)
        obj = Debug(dir_name='control',
                    sub_dirs=sub_dirs,
                    process_name=deployment_map[deployment_method][vim_type]['control']['process_name'],
                    container_name=deployment_map[deployment_method][vim_type]['control']['container_name'],
                    gcore_container_name=deployment_map[deployment_method][vim_type]['control']['gcore_container_name'],
                    kafka_container_name=None,
                    contrail_stats_container_name=None,
                    log_path=deployment_map[deployment_method][vim_type]['log_path'],
                    lib_path=None,
                    cli=None,
                    host=host,
                    port=None,
                    user=user,
                    pw=pw,
                    ssh_key_file=ssh_key_file)
        obj.create_sub_dirs()
        try:
            obj.copy_contrail_logs('control')
        except Exception as e:
            print('Error [%s] collecting control node contraillogs' % e)
        try:
            obj.copy_contrail_status()
        except Exception as e:
            print('Error [%s] collecting contrail-status logs' % e)
        try:
            obj.copy_docker_logs()
        except Exception as e:
            print('Error [%s] collecting docker logs' % e)
        try:
            obj.copy_docker_inspect_info()
        except Exception as e:
            print('Error [%s] collecting docker inspect info' % e)
        try:
            if gcore and obj.generate_gcore():
                obj.copy_gcore()
        except Exception as e:
            print('Error [%s] collecting gcore' % e)
        obj.delete_tmp_dir()
# end collect_control_node_logs

def collect_analytics_node_logs(data):
    deployment_method = data['provider_config']['deployment_method']
    vim_type = data['provider_config']['vim']
    sub_dirs = ['docker_logs', 'docker_inspect', 'logs', 'gcore', 'introspect']
    for item in data['provider_config']['analytics']:
        try:
            gcore = data['provider_config']['analytics'][item]['gcore_needed']
        except Exception as e:
            gcore = False
        host = data['provider_config']['analytics'][item]['ip']
        user = data['provider_config']['analytics'][item]['ssh_user']
        ssh_key_file = data['provider_config']['analytics'][item].get('ssh_key_file')
        pw = data['provider_config']['analytics'][item].get('ssh_pwd')
        print('\nCollecting analytics logs for analytics node : %s' % host)
        obj = Debug(dir_name='analytics',
                    sub_dirs=sub_dirs,
                    process_name=deployment_map[deployment_method][vim_type]['analytics']['process_name'],
                    container_name=deployment_map[deployment_method][vim_type]['analytics']['container_name'],
                    gcore_container_name=deployment_map[deployment_method][vim_type]['analytics']['gcore_container_name'],
                    kafka_container_name=deployment_map[deployment_method][vim_type]['analytics']['kafka_container_name'],
                    contrail_stats_container_name=deployment_map[deployment_method][vim_type]['analytics']['contrail_stats_container_name'],
                    log_path=deployment_map[deployment_method][vim_type]['log_path'],
                    lib_path=None,
                    cli=None,
                    host=host,
                    port=None,
                    user=user,
                    pw=pw,
                    ssh_key_file=ssh_key_file)
        obj.create_sub_dirs()
        try:
            obj.copy_contrail_logs('analytics')
        except Exception as e:
            print('Error [%s] collecting analytics node contrail logs' % e)
        try:
            obj.copy_analytics_node_cassandra_db_storage_space()
        except Exception as e:
            print('Error [%s] collecting analytics node cassandra db storage space' % e)
        try:
            obj.copy_analytics_node_contrail_stats()
        except Exception as e:
            print('Error [%s] collecting analytics node contrail stats' % e)
        try:
            obj.copy_analytics_node_kafka_topics()
        except Exception as e:
            print('Error [%s] collecting analytics node kafka topics' % e)
        try:
            obj.copy_contrail_status()
        except Exception as e:
            print('Error [%s] collecting contrail-status logs' % e)
        try:
            obj.copy_docker_logs()
        except Exception as e:
            print('Error [%s] collecting docker logs' % e)
        try:
            obj.copy_docker_inspect_info()
        except Exception as e:
            print('Error [%s] collecting docker inspect info' % e)
        try:
            if gcore and obj.generate_gcore():
                obj.copy_gcore()
        except Exception as e:
            print('Error [%s] collecting analytics gcore' % e)
        obj.delete_tmp_dir()
# end collect_analytics_node_logs


def collect_config_node_logs(data):
    deployment_method = data['provider_config']['deployment_method']
    vim_type = data['provider_config']['vim']
    sub_dirs = ['docker_logs', 'docker_inspect', 'logs', 'introspect']
    container_type = 'config'
    for item in data['provider_config'][container_type]:
        try:
            dbmanage = data['provider_config'][container_type][item]['db_manage']
        except Exception as e:
            dbmanage = False
        host = data['provider_config'][container_type][item]['ip']
        user = data['provider_config'][container_type][item]['ssh_user']
        ssh_key_file = data['provider_config'][container_type][item].get('ssh_key_file')
        pw = data['provider_config'][container_type][item].get('ssh_pwd')
        object_port = data['provider_config'][container_type][item]['object_port']
        object_cache = data['provider_config'][container_type][item]['cache_count']
        print('\nCollecting config logs for node : %s' % host)
        obj = Debug(dir_name='config',
                    sub_dirs=sub_dirs,
                    process_name=None,
                    container_name=deployment_map[deployment_method][vim_type][container_type]['container_name'],
                    gcore_container_name=None,
                    kafka_container_name=None,
                    contrail_stats_container_name=None,
                    log_path=deployment_map[deployment_method][vim_type]['log_path'],
                    lib_path=None,
                    cli=None,
                    host=host,
                    port=None,
                    user=user,
                    pw=pw,
                    ssh_key_file=ssh_key_file)
        obj.create_sub_dirs()
        try:
            obj.copy_contrail_logs(container_type)
        except Exception as e:
            print('Error [%s] collecting analytics node contrail logs' % e)
        try:
            obj.copy_contrail_status()
        except Exception as e:
            print('Error [%s] collecting contrail-status logs' % e)
        try:
            obj.copy_docker_logs()
        except Exception as e:
            print('Error [%s] collecting docker logs' % e)
        try:
            obj.copy_docker_inspect_info()
        except Exception as e:
            print('Error [%s] collecting docker inspect info' % e)
        try:
            obj.copy_config_object_info(object_port)
        except Exception as e:
            print('Error [%s] collecting config object port: %s' % (e,object_port))
        try:
            obj.copy_cached_object_info(object_port,object_cache)
        except Exception as e:
            print('Error [%s] collecting cached object for object port: %s' % (e,object_port))
        if dbmanage:
            print('Allowed to access DB!')
            try:
               obj.copy_db_manage_dry_run('clean')
            except Exception as e:
               print('Error [%s] running DB manage clean dry run' % e)
            try:
               obj.copy_db_manage_dry_run('heal')
            except Exception as e:
               print('Error [%s] running DB manage heal dry run' % e)
            try:
               obj.copy_config_node_cassandra_db()
            except Exception as e:
               print('Error [%s] collecting cassandra info' % e)
        obj.delete_tmp_dir()
# end collect_config_node_logs

def main():
    argv = sys.argv[1:]
    try:
        input_file = argv[argv.index('-i') + 1]
    except ValueError:
        usage()
        return
    yaml_data = parse_yaml_file(input_file)
    if yaml_data is None:
        print('Error parsing yaml file. Exiting!!!')
        return
    name = 'vrouter-agent-debug-info'
    Debug.create_base_dir(name)
    vrouter_error = control_error = analytics_error = config_error = False
    try:
        if yaml_data['provider_config']['vrouter']:
            collect_vrouter_node_logs(yaml_data)
    except Exception as e:
        print('Error [%s] while collecting vrouter logs' % e)
        vrouter_error = True
    try:
        if yaml_data['provider_config']['control']:
            collect_control_node_logs(yaml_data)
    except Exception as e:
        print('Error [%s] while collecting control node logs' % e)
        control_error = True
    try:
        if yaml_data['provider_config']['analytics']:
            collect_analytics_node_logs(yaml_data)
    except Exception as e:
        print('Error [%s] while collecting analytics node logs' % e)
        analytics_error = True
    try:
        if yaml_data['provider_config']['config']:
            collect_config_node_logs(yaml_data)
    except Exception as e:
        print('Error [%s] while collecting config node logs' % e)
        config_error = True
    if vrouter_error and control_error and analytics_error and config_error:
        print('No logs collected for vrouter, control, config and analytics node. Exiting!!!')
        return
    Debug.compress_folder(name)
    Debug.delete_base_dir()
# end main

if __name__ == '__main__':
    main()
