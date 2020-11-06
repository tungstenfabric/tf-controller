#!/usr/bin/python

#
# Copyright (c) 2019 Juniper Networks, Inc. All rights reserved.
#

from builtins import object
import json

from jinja2 import Template
from vnc_api.vnc_api import VncApi

# Specifies the type of load operation to be performed by
# juniper_junos_config role based on template type.
LOAD_TYPE = {"set": "set", "xml": "merge"}


class FilterModule(object):

    def filters(self):
        return {
            'push_config_template': self.push_config_template
        }
    # end filters

    @classmethod
    def push_config_template(cls, job_ctx, device_uuid):

        out = dict()
        job_input = job_ctx.get('job_input', None)
        template_uuid = job_input.get('template_uuid', '')
        api = VncApi(auth_type=VncApi._KEYSTONE_AUTHN_STRATEGY,
                     auth_token=job_ctx.get('auth_token'))
        template_obj = api.config_template_read(id=template_uuid)
        template_dict = api.obj_to_dict(template_obj)
        content = template_dict['template_content']
        tmpl_type = template_dict['template_type'].lower()

        device_input = job_input.get('device_input', [])
        device = [device for device in device_input
                  if device.get('device_uuid', '') == device_uuid][0]
        global_vars = json.loads(job_input.get('global_vars', '{}'))
        device_vars = json.loads(device.get('device_vars', '{}'))
        new_vars = global_vars.copy()
        new_vars.update(device_vars)

        tm = Template(content)
        config = tm.render(new_vars)
        out['config'] = config
        out['format'] = tmpl_type
        out['load'] = LOAD_TYPE.get(tmpl_type)
        return out
    # end push_config_template
# end FilterModule
