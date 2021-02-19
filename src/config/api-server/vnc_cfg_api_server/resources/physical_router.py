#
# Copyright (c) 2018 Juniper Networks, Inc. All rights reserved.
#

from vnc_api.gen.resource_common import PhysicalRouter

from vnc_cfg_api_server import utils
from vnc_cfg_api_server.resources._resource_base import ResourceMixin


class PhysicalRouterServer(ResourceMixin, PhysicalRouter):

    @classmethod
    def _encrypt_password(cls, obj_dict, db_dict=None):
        # encrypt password before updating to DB
        if obj_dict.get('physical_router_user_credentials') and \
                obj_dict.get('physical_router_user_credentials', {}).get(
                    'password'):
            dict_password = obj_dict.get('physical_router_user_credentials',
                                         {}).get('password')
            encryption_type = obj_dict.get('physical_router_encryption_type',
                                           None)
            # if 'physical_router_encryption_type' is not found in dict,
            # default for create case is encrypt password but for update check
            # physical_router_encryption_type in db object and if not set or
            # set to 'none' encrypt.
            if not encryption_type:
                encryption_type = 'none'
                if db_dict:
                    # check to see if its a case of password update
                    # If its a case of password update, then unset
                    # encryption_type to none in order for it to be
                    # encrypted

                    old_encrypted_psswd = db_dict.get(
                        'physical_router_user_credentials', {}).get(
                        'password'
                    )
                    if dict_password == old_encrypted_psswd:
                        # no password update, do not encrypt again
                        encryption_type = db_dict.get(
                            'physical_router_encryption_type',
                            'none')
            # if pwd is not encrypted, do it now
            if encryption_type == 'none':
                password = utils.encrypt_password(obj_dict['uuid'],
                                                  dict_password)
                obj_dict['physical_router_user_credentials']['password'] =\
                    password
                obj_dict['physical_router_encryption_type'] = 'local'

    @staticmethod
    def validate_telemetry_back_refs(obj_dict):
        telemetry_profile_refs = obj_dict.get('telemetry_profile_refs')
        if telemetry_profile_refs and len(telemetry_profile_refs) > 1:
            ref_list = [ref.get('to') for ref in telemetry_profile_refs]
            return (False, (400, "Physical router %s has more than one "
                            "telemetry profile refs %s" % (
                                obj_dict.get('fq_name'),
                                ref_list)))

        return True, ''
    # end validate_telemetry_back_refs

    @classmethod
    def pre_dbe_create(cls, tenant_name, obj_dict, db_conn):
        if obj_dict.get('physical_router_managed_state'):
            state = obj_dict.get('physical_router_managed_state')
            if state == 'rma' or state == 'activating':
                msg = "Managed state cannot be %s for router %s" % (
                    state, obj_dict.get('fq_name'))
                return False, (400, msg)

        # encrypt password before writing to DB
        cls._encrypt_password(obj_dict)

        ok, result = cls.validate_telemetry_back_refs(obj_dict)
        if not ok:
            return ok, result

        return True, ''
    # end pre_dbe_create

    @classmethod
    def pre_dbe_update(cls, id, fq_name, obj_dict, db_conn, **kwargs):
        # read object from DB
        pr_uuid = db_conn.fq_name_to_uuid('physical_router', fq_name)
        obj_fields = [
            'physical_router_encryption_type',
            'physical_router_user_credentials']
        (ok, pr_dict) = db_conn.dbe_read(obj_type='physical_router',
                                         obj_id=pr_uuid,
                                         obj_fields=obj_fields)

        # encrypt password before writing to DB
        cls._encrypt_password(obj_dict, pr_dict)

        ok, result = cls.validate_telemetry_back_refs(obj_dict)
        if not ok:
            return ok, result

        return True, ''
    # end pre_dbe_update
