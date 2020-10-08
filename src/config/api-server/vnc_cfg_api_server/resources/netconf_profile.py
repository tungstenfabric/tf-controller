#
# Copyright (c) 2018 Juniper Networks, Inc. All rights reserved.
#

from vnc_api.gen.resource_common import NetconfProfile

from vnc_cfg_api_server.resources._resource_base import ResourceMixin


class NetconfProfileServer(ResourceMixin, NetconfProfile):
    @staticmethod
    def is_crud_allowed(is_default_profile, np_fq_name):
        if is_default_profile:
            return (False, (400, "One of the following non-permitted "
                                 "operations was attempted on "
                                 "netconf profile %s: \n "
                                 "1. Marking profile as default \n"
                                 "2. Creating or Editing or Deleting a "
                                 "default profile "
                            % np_fq_name))
        return True, ''
    # end is_crud_allowed

    @staticmethod
    def check_if_predefined(np_fq_name):

        predef_fq_names_list = [

            ["default-domain", "default-project",
             "netconf-default-profile"]
        ]
        return np_fq_name in predef_fq_names_list
    # end check_if_predefined

    @classmethod
    def pre_dbe_create(cls, tenant_name, obj_dict, db_conn):

        is_default_profile = obj_dict.get(
            'netconf_profile_is_default')

        np_fq_name = obj_dict.get('fq_name')

        # check if its a predefined default profile
        # exempt predefined default profiles from crud check
        is_predef_profile = cls.check_if_predefined(np_fq_name)

        if is_predef_profile:
            return True, ''

        return cls.is_crud_allowed(is_default_profile, np_fq_name)
    # end pre_dbe_create

    @classmethod
    def pre_dbe_update(cls, id, fq_name, obj_dict, db_conn, **kwargs):

        ok, db_obj_dict = db_conn.dbe_read(
            obj_type='netconf_profile',
            obj_id=obj_dict['uuid'],
            obj_fields=['netconf_profile_is_default'])
        if not ok:
            return ok, (400, db_obj_dict)

        is_default_profile = obj_dict.get(
            'netconf_profile_is_default',
            db_obj_dict.get('netconf_profile_is_default')
        )
        np_fq_name = obj_dict.get('fq_name')
        return cls.is_crud_allowed(is_default_profile, np_fq_name)
    # end pre_dbe_update

    @classmethod
    def pre_dbe_delete(cls, id, obj_dict, db_conn):

        ok, db_obj_dict = db_conn.dbe_read(
            obj_type='netconf_profile',
            obj_id=obj_dict['uuid'],
            obj_fields=['netconf_profile_is_default'])
        if not ok:
            return ok, (400, db_obj_dict)

        is_default_profile = db_obj_dict.get('netconf_profile_is_default')

        np_fq_name = obj_dict.get('fq_name')
        return cls.is_crud_allowed(is_default_profile, np_fq_name)
    # end pre_dbe_delete
