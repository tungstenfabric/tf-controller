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
    def is_profile_editable(obj_dict):
        is_default_profile = obj_dict.get('telemetry_profile_is_default')
        if is_default_profile:
            return (False, (400, "Default profile %s is non-editable " % (
                            obj_dict.get('fq_name'))))
        return True, ''
    # end is_profile_editable

    @classmethod
    def pre_dbe_create(cls, tenant_name, obj_dict, db_conn):
        return cls.validate_sub_profile_back_refs(obj_dict)
    # end pre_dbe_create

    @classmethod
    def pre_dbe_update(cls, id, fq_name, obj_dict, db_conn, **kwargs):
        ok, result = cls.validate_sub_profile_back_refs(obj_dict)
        if not ok:
            return ok, result

        return cls.is_profile_editable(obj_dict)
    # end pre_dbe_update
