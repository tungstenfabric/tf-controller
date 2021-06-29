#
# Copyright (c) 2021 Juniper Networks, Inc. All rights reserved.
#

from __future__ import print_function
from future import standard_library
standard_library.install_aliases()
from builtins import str
from builtins import range
from builtins import object
import sys
import os
import argparse
import datetime
import paramiko
import warnings
import subprocess
import time
import yaml
import warnings
import xml.dom.minidom
warnings.filterwarnings(action='ignore',module='.*paramiko.*')
from urllib.request import urlopen
from urllib.error import URLError, HTTPError
import xml.etree.ElementTree as ET

#
# Base Class for Control-node debug tool.
# All the functionalities that need to be implemented to collect data from 
# control-node need to be non-static functions. All the global functionalities 
# are implemented as static functions.
#
class CNDebug:
	input_file = ""
	yaml_data = ""
	base_dir_name = "control-node-debug-tool"
	base_dir = ""
	gcore = False
	compress = False
	compress_file = ""
	path = ""

	def __init__(self, dir_name, sub_dirs, host, user, pwd, port):
		self.dir_name = dir_name
		self.sub_dirs = sub_dirs
		self.host = host
		self.user = user
		self.pwd = pwd
		self.port = port
		self.tmp_dir = ""
		self.parent_dir = ""
		self.introspect = Introspect(host, port)
		self.process_name= "contrail-control"
		self.container = "control_control_1" ## Need to figure this out for cn2
		self.cli = "contrail-control-cli"

		self.ssh_client = self.create_ssh_connection(self.host,
					self.user, self.pwd)
		if self.ssh_client is None:
			sys.exit()

	# 
	# Parses the arguments passed to the script. Any and all new arguments
	# that need to be added can be added here.
	#
	@staticmethod
	def parse_arguments():
		parser = argparse.ArgumentParser()
		required = parser.add_argument_group('Mandatory Arguments')
		required.add_argument('-i', '--input_file', help='Input file containing'
			' information of all control-nodes', required=True)
		parser.add_argument('-p', '--path', help='Provide the path where the '
			'collected output of the tool will be saved', default='/var/log')
		parser.add_argument('-g', '--gcore_file', action='store_true',
			help='Generate and copy Gcore file')
		parser.add_argument('-u', '--usage', help='This tool collects all information '
			'w.r.t control-nodes. The list of control-nodes should be given as an '
			'input yamp file. See Readme file and Sample.yaml for more info')
		parser.add_argument('-c', '--compress_folder', action='store_true',
			help='Compress output folder ')
		args = parser.parse_args()
		CNDebug.input_file = args.input_file
		CNDebug.gcore = args.gcore_file
		CNDebug.compress = args.compress_folder
		CNDebug.path = args.path

	# Check if the Input file provided can be parsed and is in right format..
	@staticmethod
	def parse_input_file():
		with open(CNDebug.input_file) as stream:
			try:
				CNDebug.yaml_data = yaml.safe_load(stream)
			except yaml.YAMLError as exc:
				print("Error[%s] while parsing file %s \n" %(exc, CNDebug.input_file))

	#
	# Create the base directory where all the logs pertainaing to the debug
	# tool can be saved.
	#
	@staticmethod
	def create_base_dirs():
		name = CNDebug.base_dir_name
		CNDebug.base_dir = CNDebug.path+"/"+name+"-"+str(datetime.datetime.now()).replace(" ","_")
		if not os.path.exists(CNDebug.base_dir):
			os.makedirs(CNDebug.base_dir)

	@staticmethod
	def check_all_nodes():
		for item in CNDebug.yaml_data['control']:
			if CNDebug.yaml_data['control'][item]['ip'] == "" :
				print("IP Address of control-node can not be NULL \n")
				return false

	# Compresses all the logs collected using the tool in the base directory into a single folder.
	@staticmethod
	def compress_folder():
		print("Compressing folder %s \n" %CNDebug.base_dir)
		CNDebug.compress_file = CNDebug.path+"/"+CNDebug.base_dir_name+"-"+str(datetime.datetime.now()).replace(" ","_")+".tar.gz"
		cmd = "tar -zcf "+CNDebug.compress_file+" "+CNDebug.base_dir+" > /dev/null 2>&1"
		subprocess.call(cmd, shell=True)
		print("Complete logs compressed and copied at %s \n" %CNDebug.compress_file)

	@staticmethod
	def delete_base_dir():
		cmd = "rm -rf "+CNDebug.base_dir
		subprocess.call(cmd, shell=True)

	def delete_tmp_dir(self):
		cmd = "rm -rf "+self.tmp_dir
		ssh_stdin, ssh_stdout, ssh_stderr = self.ssh_client.exec_command(cmd)

	# Create an SSH connection to the host(control-node) and use the client for any further interaction.
	def create_ssh_connection(self, host, user, pwd):
		try:
			client = paramiko.SSHClient()
			client.load_system_host_keys()
			client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
			client.connect(host, username=user, password=pwd)
			return client
		except Exception as e:
			print("SSH connection failed for host %s:%s" %(self.host, e))
			return None

	# Get the command output from the host using ssh_client.
	def get_ssh_cmd_output(self, cmd):
		ssh_stdin, ssh_stdout, ssh_stderr = self.ssh_client.exec_command(cmd)
		exit_status = ssh_stdout.channel.recv_exit_status()
		if exit_status != 0:
			return
		out = ""
		stdout = ssh_stdout.readlines()
		for line in stdout:
			out = out + line
		if out != "":
			return out
		else:
			return "There was no output for this command"

	# Copy files from host to local machine using the ssh_client
	def do_ftp(self, src_file, dest_file):
		sftp_client = self.ssh_client.open_sftp()
		max_tries = 10
		for i in range(max_tries):
			try:
				sftp_client.get(src_file, dest_file)
			except Exception as e:
				print("Error:%s while copying file %s. Retry attempt %s of %s \n"\
					%(e, src_file, count, max_count))
				time.sleep(5)
				continue
			else:
				sftp_client.close()
				return 1
		sftp_client.close()
		return 0

	# Create different directories under the base directory of the host to save logs for that host.
	def create_sub_dirs(self):
		timestamp = str(datetime.datetime.now()).replace(" ","_")
		self.parent_dir = CNDebug.base_dir+"/"+self.dir_name
		self.tmp_dir = "/tmp/"+self.dir_name+timestamp
		cmd = "mkdir "+self.tmp_dir
		ssh_stdin,ssh_stdout,ssh_stderr = self.ssh_client.exec_command(cmd)
		if not os.path.exists(self.parent_dir):
			os.makedirs(self.parent_dir)
		for item in self.sub_dirs:
			dir = self.parent_dir+"/"+item
			if not os.path.exists(dir):
				os.makedirs(dir)

	# Copy control-node log files from /var/log/contrail for the host.
	def copy_logs(self):
		print("Copying Control-node logs from %s \n" %self.host)
		sftp_client = self.ssh_client.open_sftp()
		remote_dir = "/var/log/contrail/"
		for filename in sftp_client.listdir(remote_dir):
			if ".log" not in filename:
				continue
			src_file = remote_dir + filename
			dest_file = self.parent_dir+"/logs/"+filename
			sftp_client.get(src_file, dest_file)
		sftp_client.close()
		print("Successfully copied Control-node logs \n")

	# This function copies contrail-status of the host using ssh_client.
	def copy_contrail_status(self):
		print("Copying contrail status for host %s \n" %self.host)
		file_path = self.parent_dir+"/status/contrail_status.txt"
		try:
			f = open(file_path, 'a')
		except Exception as e:
			print("Error opening file %s:%s \n" %(file_path, e))
			print("Failed to copy contrail-status \n")
			return
		cmd = "contrail-status"
		cmd_output = self.get_ssh_cmd_output(cmd)
		f.write(cmd_output)
		f.close()
		print("Successfully copied contrail status \n")

	#
	# This function copies the Introspect logs of the control-node using the contrail-control-cli.
	# We use the ssh_client and docker commands to execute all the contrail-control-cli commands
	# on the control-node and collect the introspect output.
	#
	def copy_introspect_logs(self):
		print("Copying Intropsect logs from %s \n" %self.host)
		cmd = "docker exec "+self.container+" "+self.cli+" read "
		cmd_list = self.get_ssh_cmd_output(cmd).split('\n')
		del cmd_list[0]
		if len(cmd_list) > 0:
			del cmd_list[-1]
		if not cmd_list:
			print("Error running cmd: %s \n" %cmd)
			print("Copying introspect logs : Failed \n")
			return
		for i in range(len(cmd_list)):
			cmd_list[i] = cmd_list[i].strip()
			tmp_str = cmd_list[i].split()
			file_name = '_'.join(tmp_str)
			file_path = self.parent_dir + '/introspect/' + file_name
			cmd = 'docker exec %s %s %s' %(self.container, self.cli, cmd_list[i])
			cmd_op = self.get_ssh_cmd_output(cmd)
			try:
				f = open(file_path, 'a')
			except Exception as e:
                                print("Error opening file %s: %s \n" %(file_path, e))
                                print("Copying Intropsect logs : Failed \n")
                                return
			if cmd_op is None:
				cmd_op = "Null output for the command"
			f.write(cmd_op)
			f.close()
		print("Copying introspect logs : Success \n")

	#
	# This function copies all the sandesh traces for the control-node from the Introspect page.
	# It uses the Introspect class object to retrieve information from the intropsect page 
	# and parse them.
	#
	def copy_sandesh_traces(self, path):
		print("Copying Sandesh Traces for host %s \n" %self.host)
		if self.introspect.get(path) == 0:
			print("Copying sandesh traces : Failed \n")
			return
		trace_buffer_list = self.introspect.getList("trace_buf_name")
		for i in range(len(trace_buffer_list)):
			tmp_str = trace_buffer_list[i].split()
			file_name = '_'.join(tmp_str)
			file_path = self.parent_dir + '/sandesh/' + file_name
			try:
				f = open(file_path, 'a')
			except Exception as e:
				print("Error opening file %s: %s \n" %(file_path, e))
				print("Copying sandesh traces : Failed \n")
				return
			self.introspect.get('Snh_SandeshTraceRequest?x='+trace_buffer_list[i])
			if self.introspect.output_etree is not None:
				for element in self.introspect.output_etree.iter('element'):
					f.write(Introspect.elementToStr('', element).rstrip())
					f.write('\n')
			f.close()
		print("Copying sandesh traces : Success \n")

	#
	# This function copies the ifmap dp dump for the control-node from the Introspect page.
	# It uses the Introspect class object to retrieve information from the intropsect page 
        # and parse them.
        #
	def copy_ifmap_db(self, path):
		print("Copying IFMap DB for host %s \n" %self.host)
		if self.introspect.get(path) == 0:
			print("Copying IFMap DB : Failed \n")
			return
		table_name = self.introspect.getList("table_name")
		for i in range(len(table_name)):
			tmp_str = table_name[i].split()
			file_name = '_'.join(tmp_str)
			file_path = self.parent_dir + '/ifmap/' + file_name
			try:
				f = open(file_path, 'a')
			except Exception as e:
				print("Error opening file %s: %s \n" %(file_path, e))
				print("Copying IFMap DB : Failed \n")
				return
			self.introspect.get('Snh_IFMapTableShowReq?x='+table_name[i])
			if self.introspect.output is not None:
				out = xml.dom.minidom.parseString(self.introspect.output)
				f.write(out.toprettyxml())
			f.close()
		print("Copying IFMap DB : Success \n")

	#
	# This function copies the route summanry for the control-node from the Introspect page.
	# It uses the Introspect class object to retrieve information from the intropsect page 
        # and parse them.
        #
	def copy_route_summary(self, path):
		print("Copying Route Summary for host %s \n" %self.host)
		if self.introspect.get(path) == 0:
			print("Copying Route Summary : Failed \n")
			return
		table_name = self.introspect.getList("name")
		for i in range(len(table_name)):
			tmp_str = table_name[i].split()
			file_name = '_'.join(tmp_str)
			file_path = self.parent_dir + '/route/' + file_name
			try:
				f = open(file_path, 'a')
			except Exception as e:
				print("Error opening file %s: %s \n" %(file_path, e))
				print("Copying Route Summary : Failed to create file \n")
				return
			self.introspect.get('Snh_ShowRouteReq?x='+table_name[i])
			if self.introspect.output is not None:
				out = xml.dom.minidom.parseString(self.introspect.output)
				f.write(out.toprettyxml())
			f.close()
		print("Copying Route Summary : Success \n")

	#
	# This function uses ssh_client and docker commands to first generate and 
	# then copy the gcore file for the control-node.
	#
	def copy_gcore(self):
		if CNDebug.gcore == True:
			print("Generating gcore files for host %s \n" %self.host)
			cmd = 'docker exec %s gcore $(pidof %s)' %(self.container, self.process_name)
			ssh_stdin, ssh_stdout, ssh_stderr = self.ssh_client.exec_command(cmd)
			exit_status = ssh_stdout.channel.recv_exit_status()
			if exit_status != 0:
				print("Generating gcore : Failed. Error %s \n" %exit_status)
		print("Copying gcore files for host %s \n" %self.host)
		cmd = "docker exec "+self.container+" ls core.$(pidof "+self.process_name+")"
		ssh_stdin, ssh_stdout, ssh_stderr = self.ssh_client.exec_command(cmd)
		core_name = ssh_stdout.readline().strip('\n')
		if "core" not in core_name:
			print("Unable to copy gcore. Gcore not found \n")
			return
		self.core_file_name = core_name

		print("Copying core files \n")
		cmd = "docker cp %s:%s %s"%(self.container, self.core_file_name, self.tmp_dir)
		ssh_stdin, ssh_stdout, ssh_stderr = self.ssh_client.exec_command(cmd)
		exit_status = ssh_stdout.channel.recv_exit_status()
		if exit_status != 0:
			print("Copying gcore : Failed. Error %s \n" %exit_status)
			return
		src_file = self.tmp_dir+"/"+self.core_file_name
		dest_file = self.parent_dir+"/gcore/"+self.core_file_name
		if self.do_ftp(src_file, dest_file):
			print("Sucessfully copied Gcore files \n")
		else:
			print("Error copying Gcore files \n")

#
# Class to access the Introspect page for the control-node. All the interactions
# to the Introspect page and the parsing of the introspect data is handled in this class.
#
class Introspect(object):
	def __init__ (self, host, port):
		self.host_url = "http://" + host + ":" + str(port) + "/"

	def get (self, path):
		""" get introspect output """
		self.output_etree = None
		url = self.host_url + path.replace(' ', '%20')
		try:
			response = urlopen(url)
		except HTTPError as e:
			print("The server couldn\'t fulfill the request. \n")
			print("URL: %s" %url)
			print("Error code: %s \n" %e.code)
			return 0
		except URLError as e:
			print("Failed to reach destination \n")
			print("URL: %s \n" %url)
			print("Reason: %s \n" %e.reason)
			return 0
		else:
			ISOutput = response.read()
			response.close()
		self.output = ISOutput
		self.output_etree = ET.fromstring(ISOutput)
		return 1

	def getList(self, xpathExpr):
		""" get list which contains all the element names for sandesh/ifmap"""
		tlist = []
		if self.output_etree is not None:
			for element in self.output_etree.iter(xpathExpr):
				elem = Introspect.elementToStr('', element).rstrip()
				res = elem.split(' ')[1].strip()
				tlist.append(res)
		return tlist

	@staticmethod
	def elementToStr(indent, etreenode):
		""" convernt etreenode sub-tree into string """
		elementStr=''
		if etreenode.tag == 'more':   #skip more element
			return elementStr

		if etreenode.text and etreenode.tag == 'element':
			return indent + etreenode.text + "\n"
		elif etreenode.text:
			return indent + etreenode.tag + ': ' + \
					etreenode.text.replace('\n', '\n' + \
					indent + (len(etreenode.tag)+2)*' ') + "\n"
		elif etreenode.tag != 'list':
			elementStr += indent + etreenode.tag + "\n"

		if 'type' in etreenode.attrib:
			if etreenode.attrib['type'] == 'list' and \
					etreenode[0].attrib['size'] == '0':
				return elementStr

		for element in etreenode:
			elementStr += Introspect.elementToStr(indent + '  ', element)

		return elementStr

#
# This function creates a CNDebug class object for each control-node passed in the 
# input file and calls the respective functions to retrieve all the debug logs and save 
# them locally.
#
def collect_control_node_info(data):
	sub_dirs = ['logs', 'gcore', 'introspect', 'ifmap', 'route', 'sandesh', 'status']
	print("Copying all debug data to %s \n" %CNDebug.base_dir)
	for item in data['control']:
		host = data['control'][item]['ip']
		user = data['control'][item]['ssh_user']
		pwd = data['control'][item]['ssh_pwd']
		obj = CNDebug(dir_name=item, sub_dirs=sub_dirs,
			host=host, user=user, pwd=pwd, port=8083)
		obj.create_sub_dirs()
		obj.copy_logs()
		obj.copy_contrail_status()
		obj.copy_introspect_logs()
		obj.copy_sandesh_traces("Snh_SandeshTraceBufferListRequest")
		obj.copy_ifmap_db("Snh_IFMapNodeTableListShowReq")
		obj.copy_route_summary("Snh_ShowRouteSummaryReq")
		obj.copy_gcore()
		obj.delete_tmp_dir()
	if CNDebug.compress is True:
		CNDebug.compress_folder()
		CNDebug.delete_base_dir()

def main():
	CNDebug.parse_arguments()
	CNDebug.parse_input_file()
	if not os.path.exists(CNDebug.path):
		print("Error: Provided path[%s] to script is not present \n" %(CNDebug.path))
		return
	if CNDebug.yaml_data is None:
		print("Null Yaml file passed. Please check the file \n")
		return
	CNDebug.create_base_dirs()
	CNDebug.check_all_nodes()
	collect_control_node_info(CNDebug.yaml_data)

if __name__ == '__main__':
    main()
