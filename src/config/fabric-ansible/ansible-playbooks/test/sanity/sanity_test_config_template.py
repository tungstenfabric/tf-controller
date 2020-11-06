#!/usr/bin/python

#
# Copyright (c) 2013 Juniper Networks, Inc. All rights reserved.
#

from __future__ import absolute_import
import json
from cfgm_common import rest
from cfgm_common.exceptions import NoIdError

from builtins import str
from .sanity_base import SanityBase
from . import config
from vnc_api.gen.resource_client import ConfigTemplate


# pylint: disable=E1101
class SanityTestConfigTemplate(SanityBase):

    def __init__(self, cfg):
        SanityBase.__init__(self, cfg, 'sanity_test_config_template')
        self._namespaces = cfg['namespaces']
        self._prouter = cfg['prouter']
        self._fab_name = cfg['config_template']['fabric']
    # end __init__

    def create_template(self, tmpl_type):
        """create_template"""
        tmpl_name = 'test-tmpl'
        device_family = 'juniper-QFX'
        tmpl_content = ''

        self._logger.info("Config Template ...")
        if tmpl_type.lower() == 'set':
            tmpl_content = '''set system login message "{{motd}}"
                          set vlans vlan-new vlan-id {{vlan.id}}'''
        elif tmpl_type.lower() == 'xml':
            tmpl_content = '''<configuration>
                <vlans>
                    <vlan>
                        <name>vlan-new1</name>
                        <vlan-id>{{vlan.id}}</vlan-id>
                    </vlan>
                </vlans>
                <system>
                    <login>
                        <message>{{motd}}</message>
                    </login>
                </system>
            </configuration>
            '''

        data = json.dumps({
            "template_name": tmpl_name,
            "template_content": tmpl_content,
            "device_family": device_family,
            "template_type": tmpl_type,
        })

        url = '/validate-template'
        msg = self._api._request_server(rest.OP_POST, url, data)

        ret_data = json.loads(msg)
        vars = ret_data['template_vars']

        tmpl = ConfigTemplate(
            template_name=tmpl_name,
            template_content=tmpl_content,
            template_type=tmpl_type,
            device_family=device_family,
            device_vars=str(vars),
            global_vars=''
        )
        self._api.config_template_create(tmpl)

        payload = dict()
        payload['template_uuid'] = tmpl.get_uuid()
        payload['global_vars'] = '{"motd": "this is a test ' + tmpl_type + '"}'
        device_input = list()
        device_list = list()
        i = 6
        fab_fq_name = ["default-global-system-config", self._fab_name]
        fabric_obj = self.read_fabric_obj(fab_fq_name)
        device_refs = fabric_obj.get_physical_router_back_refs() or []
        device_uuids = [ref.get('uuid', '') for ref in device_refs]
        for device in list(device_uuids):
            device_list.append(device)
            d_input = dict()
            d_input['device_uuid'] = device
            d_input['device_vars'] = '{"vlan": {"id":'+str(i)+'}}'
            device_input.append(d_input)
            i += 1
        payload['device_input'] = device_input

        job_template_fq_name = [
            'default-global-system-config', 'push_config_template']
        job_execution_info = self._api.execute_job(
            job_template_fq_name=job_template_fq_name,
            job_input=payload,
            device_list=device_list
        )
        job_execution_id = job_execution_info.get('job_execution_id')
        self._logger.debug(
            "Push config template job started with execution id: %s", job_execution_id)
        self._wait_and_display_job_progress('Push config template', job_execution_id,
                                            self._fab_name, job_template_fq_name)
        self._logger.info("... Config Template workflow complete")
        # self._api.config_template_delete(id=tmpl.get_uuid())
    # end create_template

    def read_fabric_obj(self, fq_name):
        try:
            fabric_obj = self._api.fabric_read(
                fq_name=fq_name
            )
        except NoIdError:
            fabric_obj = None
        return fabric_obj
    # end read_fabric_obj

    def test(self, tmpl_type):
        try:
            self.create_template(tmpl_type)
        except Exception as ex:
            self._exit_with_error(
                "Test failed due to unexpected error: %s" % str(ex))
    # end test


if __name__ == "__main__":
    SanityTestConfigTemplate(config.load('sanity/config/test_config.yml')).test('XML')
    # SanityTestConfigTemplate(config.load('sanity/config/test_config.yml')).test('SET')
# end __main__
