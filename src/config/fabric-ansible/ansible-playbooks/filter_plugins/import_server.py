#!/usr/bin/python

from builtins import map
from past.builtins import basestring
from builtins import object
import logging
import traceback
import json
import yaml
import sys
import base64
import uuid
import collections
import pprint

sys.path.append('/opt/contrail/fabric_ansible_playbooks/filter_plugins')
sys.path.append('/opt/contrail/fabric_ansible_playbooks/common')

from common.contrail_command import CreateCCResource, CreateCCNodeProfile
import jsonschema

from job_manager.job_utils import JobVncApi

type_name_translation_dict = {
    ("ipmi_port", int): ("ipmi_port", str),
    ("switch_name", str): ("switch_info", str),
    ("port_name", str): ("port_id", str),
    ("mac_address", str): ("address", str),
    ("cpus", str): ("cpus", int),
    ("local_gb", str): ("local_gb", int),
    ("memory_mb", str): ("memory_mb", int)
}

class ImportLog(object):
    _instance = None

    @staticmethod
    def instance():
        if not ImportLog._instance:
            ImportLog._instance = ImportLog()
        return ImportLog._instance
    # end instance

    @staticmethod
    def _init_logging():
        """
        :return: type=<logging.Logger>
        """
        logger = logging.getLogger('ServerFilter')
        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.INFO)

        formatter = logging.Formatter(
            '%(asctime)s %(levelname)-8s %(message)s',
            datefmt='%Y/%m/%d %H:%M:%S'
        )
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)
        return logger

    # end _init_logging

    def __init__(self):
        self._msg = None
        self._logs = []
        self._logger = ImportLog._init_logging()

    # end __init__

    def logger(self):
        return self._logger

    # end logger

    def msg_append(self, msg):
        if msg:
            if not self._msg:
                self._msg = msg + ' ... '
            else:
                self._msg += msg + ' ... '

    # end log

    def msg_end(self):
        if self._msg:
            self._msg += 'done'
            self._logs.append(self._msg)
            self._logger.warning(self._msg)
            self._msg = None

    # end msg_end

    def dump(self):
        retval = ""
        for msg in self._logs:
            retval += msg + '\n'
        return retval
        # end dump
# end ImportLog


class FilterModule(object):
    @staticmethod
    def _init_logging():
        logger = logging.getLogger('ImportServerFilter')
        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.WARN)

        formatter = logging.Formatter('%(asctime)s %(levelname)-8s %(message)s',
                                      datefmt='%Y/%m/%d %H:%M:%S')
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)

        return logger

    def __init__(self):
        self._logger = FilterModule._init_logging()

    # end __init__

    @staticmethod
    def _validate_job_ctx(job_ctx):
        vnc_api = JobVncApi.vnc_init(job_ctx)
        job_template_fqname = job_ctx.get('job_template_fqname')
        if not job_template_fqname:
            raise ValueError('Invalid job_ctx: missing job_template_fqname')

        job_input = job_ctx.get('input')
        if not job_input:
            raise ValueError('Invalid job_ctx: missing job_input')

        # retrieve job input schema from job template to validate the job input
        import_server_template = vnc_api.job_template_read(
            fq_name=job_template_fqname
        )
        input_schema = import_server_template.get_job_template_input_schema()
        input_schema = json.loads(input_schema)
        jsonschema.validate(job_input, input_schema)
        return job_input

    def filters(self):
        return {
            'import_nodes_from_file': self.import_nodes_from_file
        }

    @staticmethod
    def translate(dict_to_trans):
        for k in list(dict_to_trans):
            if (k, type(dict_to_trans[k])) in \
                    type_name_translation_dict:
                trans_name, trans_type = type_name_translation_dict[
                    (k, type(dict_to_trans[k]))
                ]
                dict_to_trans[str(trans_name)] = trans_type(
                    dict_to_trans.pop(k)
                )
        return dict_to_trans

    def get_cc_tag_payload(self, tag_value):
        name = "label={}".format(tag_value)

        return {"kind": "tag",
            "data": {
                "name": name,
                "fq_name": [name],
                "tag_value": tag_value,
                "tag_type_name": "label"
            }
        }

    def get_cc_port_payload(self, port_dict, local_link_dict):
        cc_port = {"kind": "port",
            "data": {
                "parent_type": "node",
                "parent_uuid": port_dict['node_uuid'],
                "name": port_dict['name'],
                "uuid": port_dict.get('uuid', None),
                "fq_name": port_dict['fq_name'],
                "bms_port_info": {
                    "pxe_enabled": port_dict.get('pxe_enabled',False),
                    "address": port_dict['address'],
                    "local_link_connection": local_link_dict
                }
            }
        }
        if port_dict.get('dvs_name'):
            cc_port['data']['esxi_port_info'] = {'dvs_name': port_dict.get('dvs_name') }

        return cc_port

    def get_cc_node_payload(self, node_dict):
        cc_node = [{
                    "kind": "node",
                    "data": {
                        "node_type": node_dict.get('node_type', "baremetal"),
                        "name": node_dict['name'],
                        "uuid": node_dict.get('uuid', None),
                        "display_name": node_dict['display_name'],
                        "hostname": node_dict['hostname'],
                        "parent_type": "global-system-config",
                        "fq_name": ["default-global-system-config",
                                    node_dict['name']],
                        "bms_info": {
                            "name": node_dict['name'],
                            "network_interface": "neutron",
                            "type": node_dict.get('type', "baremetal"),
                            "properties": node_dict.get('properties', {}),
                            "driver": node_dict.get('driver', "pxe_ipmitool"),
                            "driver_info": node_dict.get("driver_info", {})
                        }
                    }
                  }]

        return cc_node

    def convert_port_format(self, port_list, parent_uuid, parent_name, existing_ports):
        cc_port_list = []

        for p in port_list:
            p['node_uuid'] = parent_uuid
            mac_addr = p['mac_address']

            if not p.get('name', None):
                p['name'] = "p-" + mac_addr.replace(":", "")[6:]

            p['fq_name'] = [
                'default-global-system-config', parent_name, p['name']
            ]

            existing_port_uuid = self.__get_existing_port_uuid(
                existing_ports, p['fq_name'], mac_addr
            )

            if existing_port_uuid is not None:
                p['uuid'] = existing_port_uuid

            p = self.translate(p)

            if 'tags' in p and len(p['tags']) > 0:
                p['tag_refs'] = self.__tag_values_to_tag_refs(p['tags'])

            local_link_dict = {k: v for k, v in list(p.items()) if k in
                               ['port_id', 'switch_info', 'switch_id']}

            self._logger.warning("dvs-name:: " + str(p.get('dvs_name')))
            cc_port = self.get_cc_port_payload(p, local_link_dict)
            cc_port_list.append(cc_port)
        return cc_port_list

    def __get_existing_port_uuid(self, ports, fq_name, mac_address):
        parent_fq_name = fq_name[:-1]
        for p in ports:
            if p['fq_name'] == fq_name:
                return p['uuid']
            if p['fq_name'][:-1] != parent_fq_name:
                continue
            if p['bms_port_info'].get('address') == mac_address:
                return p['uuid']
        return None

    def convert(self, data):
        if isinstance(data, basestring):
            return str(data)
        elif isinstance(data, collections.Mapping):
            return dict(list(map(self.convert, iter(list(data.items())))))
        elif isinstance(data, collections.Iterable):
            return type(data)(list(map(self.convert, data)))
        else:
            return data

    def __tag_values_to_tag_refs(self, tag_values):
        refs = []
        for v in tag_values:
            refs.append({"to": ["label={}".format(v)]})
        return refs

    def import_nodes(self, data, cc_client):
        if not (isinstance(data, dict) and "nodes" in data):
            return []
        created_updated_nodes = []
        nodes = data['nodes']

        existing_nodes = cc_client.list_cc_resources("node")['nodes']
        existing_ports = cc_client.list_cc_resources("port")['ports']
        existing_tags = cc_client.list_cc_resources("tag")['tags']

        #self._logger.warning("Creting Job INPUT:" + pformat(node_list))

        for node in nodes:
            payload, response = self.__create_cc_node(node, existing_nodes, cc_client)
            if payload is None or len(response) != 1:
                self._logger.warning("IGNORING Creation of : " + pprint.pformat(node))
                continue

            created_updated_nodes.append(payload)

            ports = node.get('ports',[])

            tags = self.__collect_tag_values_from_port_list(ports)
            self.__create_cc_tags(tags, existing_tags, cc_client)

            node_uuid = response[0]['data']['uuid']
            self.__create_cc_ports(
                ports, existing_ports, node_uuid, node['name'], cc_client
            )

        return created_updated_nodes

    def __create_cc_node(self, node, existing_nodes, cc_client):
        if node.get("name", None) is None:
            new_name = self.generate_node_name(node)
            if new_name is None:
                return None, None
            node["name"] = new_name

        if not node.get('hostname', None):
            node['hostname'] = node['name']

        if not node.get('display_name', None):
            node['display_name'] = node['name']

        existing_node = self.__find_resource_from_list(
            existing_nodes, ['default-global-system-config', node['name']]
        )

        if existing_node is not None:
            node["uuid"] = existing_node["node"]["uuid"]

        for sub_dict in ['properties', 'driver_info']:
            node_sub_dict = node.get(sub_dict, {})
            if node_sub_dict:
                node[sub_dict] = self.translate(node_sub_dict)

        node_payload = {'resources': self.get_cc_node_payload(node)}

        self._logger.warning("Creating : " + str(node["name"]))
        self._logger.warning("Creating : " + pprint.pformat(node_payload))

        response = cc_client.create_cc_resource(node_payload)

        if existing_node is None:
            if 'data' in response[0]:
                existing_nodes.append({'node': response[0]['data']})
        return node_payload, response

    def __find_resource_from_list(self, resources, resource_fq_name):
        for r in resources:
            if not isinstance(r, dict):
                continue
            if len(r.keys()) != 1:
                continue
            kind = list(r.keys())[0]
            if not "fq_name" in r[kind]:
                continue
            if r[kind]["fq_name"] == resource_fq_name:
                return r
        return None

    def generate_node_name(self, node):
        if node.get('hostname', None):
            return node['hostname']

        port_list = node.get('ports',[])

        if len(port_list) == 0:
            return None

        for port in port_list:
            mac = port['mac_address']
            if port.get('pxe_enabled',False):
                return "auto-" + mac.replace(":", "")[6:]

        return "auto-" + port_list[0]['mac_address'].replace(":", "")[6:]

    def __create_cc_ports(
        self, ports, existing_ports, parent_node_id, parent_node_name, cc_client
    ):
        print(existing_ports)
        converted_ports = self.convert_port_format(
            ports, parent_node_id, parent_node_name, existing_ports
        )

        if len(converted_ports) == 0:
            return None

        response = cc_client.create_cc_resource({"resources": converted_ports})

        for r in response:
            if 'data' in r:
                print(r)
                existing_ports.append(r['data'])

        return response

    def __collect_tag_values_from_port_list(self, port_list):
        collected_tags = []
        if not isinstance(port_list, list):
            return

        for p in port_list:
            if not isinstance(p, dict) or "tags" not in p:
                continue
            tags = p.get('tags',[])
            for t in tags:
                if t not in collected_tags:
                    collected_tags.append(t)
        return collected_tags


    def __create_cc_tags(self, tag_values, existing_tags, cc_client):
        tags_to_create = []

        # remove duplicates
        tag_values = list(dict.fromkeys(tag_values))

        for v in tag_values:
            existing_tag = self.__find_resource_from_list(
                existing_tags, ["label={}".format(v)]
            )
            if existing_tag is None:
                tags_to_create.append(self.get_cc_tag_payload(v))

        if len(tags_to_create) == 0:
            return None

        response = cc_client.create_cc_resource({"resources": tags_to_create})

        for r in response:
            if 'data' in r:
                existing_tags.append(r['data'])

        return response





    # ***************** import_nodes_from_file filter *********************************

    def import_nodes_from_file(self, job_ctx):
        """
        :param job_ctx: Dictionary
            example:
            {
                "auth_token": "EB9ABC546F98",
                "job_input": {
                    "encoded_nodes": "....",
                    "contrail_command_host": "....",
                    "encoded_file": "...."
                }
            }
        :return: Dictionary
            if success, returns
            [
                <list: imported nodes>
            ]
            if failure, returns
            {
                'status': 'failure',
                'error_msg': <string: error message>,
                'import_log': <string: import_log>
            }
            """
        try:
            job_input = FilterModule._validate_job_ctx(job_ctx)
            self._logger.info("Job INPUT:\n" + str(job_input))

            encoded_file = job_input.get("encoded_file")
            file_format = job_input.get("file_format")
            decoded = base64.decodestring(encoded_file)

            cluster_id = job_ctx.get('contrail_cluster_id')
            cluster_token = job_ctx.get('auth_token')

            cc_host = job_input.get('contrail_command_host')
            cc_username = job_input.get('cc_username')
            cc_password = job_input.get('cc_password')

            self._logger.warning("Starting Server Import")

            cc_client = CreateCCResource(cc_host, cluster_id, cluster_token,
                                       cc_username, cc_password)

            if file_format.lower() == "yaml":
                data = yaml.load(decoded)

            elif file_format.lower() == "json":
                data = self.convert(json.loads(decoded))
            else:
                raise ValueError('File format not recognized. Only yaml or '
                                 'json supported')
            added_nodes = self.import_nodes(
                data, cc_client)
        except Exception as e:
            errmsg = "Unexpected error: %s\n%s" % (
                str(e), traceback.format_exc()
            )
            self._logger.error(errmsg)
            return {
                'status': 'failure',
                'error_msg': errmsg,
                'import_log': ImportLog.instance().dump()
            }

        return {
            'status': 'success',
            'added_nodes': added_nodes,
            'import_log': ImportLog.instance().dump()
        }
