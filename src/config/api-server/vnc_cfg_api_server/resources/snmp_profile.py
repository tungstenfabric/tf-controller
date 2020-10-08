#
# Copyright (c) 2018 Juniper Networks, Inc. All rights reserved.
#

from vnc_api.gen.resource_common import SnmpProfile

from vnc_cfg_api_server.resources._resource_base import ResourceMixin


class SnmpProfileServer(ResourceMixin, SnmpProfile):
    @staticmethod
    def is_crud_allowed(is_default_profile, sp_fq_name):
        if is_default_profile:
            return (False, (400, "One of the following non-permitted "
                                 "operations was attempted on "
                                 "snmp profile %s: \n"
                                 "1. Marking profile as default \n"
                                 "2. Creating or Editing or Deleting a "
                                 "default profile "
                            % sp_fq_name))
        return True, ''
    # end is_crud_allowed

    @staticmethod
    def check_if_predefined(sp_fq_name):

        predef_fq_names_list = [

            ["default-domain", "default-project",
             "snmp-default-profile"]
        ]
        return sp_fq_name in predef_fq_names_list
    # end check_if_predefined

    @classmethod
    def pre_dbe_create(cls, tenant_name, obj_dict, db_conn):

        is_default_profile = obj_dict.get(
            'snmp_profile_is_default')

        sp_fq_name = obj_dict.get('fq_name')

        # check if its a predefined default profile
        # exempt predefined default profiles from crud check
        is_predef_profile = cls.check_if_predefined(sp_fq_name)

        if is_predef_profile:
            return True, ''

        return cls.is_crud_allowed(is_default_profile, sp_fq_name)
    # end pre_dbe_create

    @classmethod
    def pre_dbe_update(cls, id, fq_name, obj_dict, db_conn, **kwargs):

        ok, db_obj_dict = db_conn.dbe_read(
            obj_type='snmp_profile',
            obj_id=obj_dict['uuid'],
            obj_fields=['snmp_profile_is_default'])
        if not ok:
            return ok, (400, db_obj_dict)

        already_default = db_obj_dict.get('snmp_profile_is_default')

        is_default_profile = already_default if already_default is True \
            else obj_dict.get('snmp_profile_is_default')

        sp_fq_name = obj_dict.get('fq_name')
        return cls.is_crud_allowed(is_default_profile, sp_fq_name)
    # end pre_dbe_update

    @classmethod
    def pre_dbe_delete(cls, id, obj_dict, db_conn):

        is_default_profile = obj_dict.get('snmp_profile_is_default')

        sp_fq_name = obj_dict.get('fq_name')
        ok, result = cls.is_crud_allowed(is_default_profile, sp_fq_name)
        return ok, result, None
    # end pre_dbe_delete
