#
# Copyright (c) 2018 Juniper Networks, Inc. All rights reserved.
#

from vnc_api.gen.resource_common import TelemetryProfile

from vnc_cfg_api_server.resources._resource_base import ResourceMixin


class TelemetryProfileServer(ResourceMixin, TelemetryProfile):

    @staticmethod
    def validate_len_of_refs(tp_fq_name, obj_type, obj_refs):
        if obj_refs and len(obj_refs) > 1:
            ref_list = [ref.get('to') for ref in obj_refs]
            return (False, (400, "Telemetry profile %s has more than one "
                                 "%s refs %s" % (tp_fq_name, obj_type,
                                                 ref_list)))
        return True, ''
    # end validate_len_of_refs

    @staticmethod
    def validate_sub_profile_back_refs(obj_dict):

        tp_fq_name = obj_dict.get('fq_name')

        sflow_profile_refs = obj_dict.get('sflow_profile_refs')
        sflow_chk, result = TelemetryProfileServer.validate_len_of_refs(
            tp_fq_name,
            'sflow_profile',
            sflow_profile_refs
        )

        if not sflow_chk:
            return sflow_chk, result

        grpc_profile_refs = obj_dict.get('grpc_profile_refs')
        grpc_chk, result = TelemetryProfileServer.validate_len_of_refs(
            tp_fq_name,
            'grpc_profile',
            grpc_profile_refs
        )

        if not grpc_chk:
            return grpc_chk, result

        snmp_profile_refs = obj_dict.get('snmp_profile_refs')
        snmp_chk, result = TelemetryProfileServer.validate_len_of_refs(
            tp_fq_name,
            'snmp_profile',
            snmp_profile_refs
        )

        if not snmp_chk:
            return snmp_chk, result

        netcnf_profile_refs = obj_dict.get('netconf_profile_refs')
        netcnf_chk, result = TelemetryProfileServer.validate_len_of_refs(
            tp_fq_name,
            'netconf_profile',
            netcnf_profile_refs
        )

        if not netcnf_chk:
            return netcnf_chk, result

        return True, ''
    # end validate_sub_profile_back_refs

    @staticmethod
    def is_crud_allowed(is_default_profile, tp_fq_name):
        if is_default_profile:
            return (False, (400, "One of the following non-permitted "
                                 "operations was attempted on "
                                 "telemetry profile %s: \n"
                                 "1. Marking profile as default \n"
                                 "2. Creating or Editing or Deleting a "
                                 "default profile "
                            % tp_fq_name))
        return True, ''
    # end is_crud_allowed

    @staticmethod
    def check_if_predefined(tp_fq_name):

        predef_fq_names_list = [

            ["default-domain", "default-project",
             "default-telemetry-profile-1"],
            ["default-domain", "default-project",
             "default-telemetry-profile-2"],
            ["default-domain", "default-project",
             "default-telemetry-profile-3"],
            ["default-domain", "default-project",
             "default-telemetry-profile-4"],
            ["default-domain", "default-project",
             "default-telemetry-profile-5"],
            ["default-domain", "default-project",
             "default-telemetry-profile-6"]

        ]
        return tp_fq_name in predef_fq_names_list
    # end check_if_predefined

    @classmethod
    def pre_dbe_create(cls, tenant_name, obj_dict, db_conn):

        is_default_profile = obj_dict.get(
            'telemetry_profile_is_default')

        tp_fq_name = obj_dict.get('fq_name')

        # check if its a predefined default profile
        # exempt predefined default profiles from crud check
        is_predef_profile = cls.check_if_predefined(tp_fq_name)

        if not is_predef_profile:
            ok, result = cls.is_crud_allowed(is_default_profile, tp_fq_name)
            if not ok:
                return ok, result

        return cls.validate_sub_profile_back_refs(obj_dict)
    # end pre_dbe_create

    @classmethod
    def pre_dbe_update(cls, id, fq_name, obj_dict, db_conn, **kwargs):

        ok, db_obj_dict = db_conn.dbe_read(
            obj_type='telemetry_profile',
            obj_id=obj_dict['uuid'],
            obj_fields=['telemetry_profile_is_default'])
        if not ok:
            return ok, (400, db_obj_dict)

        already_default = db_obj_dict.get('telemetry_profile_is_default')

        is_default_profile = already_default if already_default is True \
            else obj_dict.get('telemetry_profile_is_default')

        tp_fq_name = db_obj_dict.get('fq_name')

        # check if its a predefined default profile
        # exempt predefined default profiles from crud check
        is_predef_profile = cls.check_if_predefined(tp_fq_name)

        if not is_predef_profile:
            ok, result = cls.is_crud_allowed(is_default_profile, tp_fq_name)
            if not ok:
                return ok, result

        return cls.validate_sub_profile_back_refs(obj_dict)
    # end pre_dbe_update

    @classmethod
    def pre_dbe_delete(cls, id, obj_dict, db_conn):

        is_default_profile = obj_dict.get('telemetry_profile_is_default')

        tp_fq_name = obj_dict.get('fq_name')
        ok, result = cls.is_crud_allowed(is_default_profile, tp_fq_name)
        return ok, result, None
    # end pre_dbe_delete
