#
# Copyright (c) 2015 Juniper Networks, Inc. All rights reserved.
#

from sandesh_common.vns.constants import API_SERVER_KEYSPACE_NAME
from sandesh_common.vns.constants import DEVICE_MANAGER_KEYSPACE_NAME
from sandesh_common.vns.constants import USERAGENT_KEYSPACE_NAME
from sandesh_common.vns.constants import SCHEMA_KEYSPACE_NAME
from sandesh_common.vns.constants import SVC_MONITOR_KEYSPACE_NAME

class ConfigKeyspaceMap(object):
    _KEYSPACES = {
        API_SERVER_KEYSPACE_NAME: {
            "OBJ_UUID_CF": {
                "name": "obj_uuid_table",
                "issu": True,
            },
            "OBJ_FQ_NAME_CF": {
                "name": "obj_fq_name_table",
                "issu": True,
            },
            "OBJ_SHARED_CF": {
                "name": "obj_shared_table",
                "issu": True,
            },
        },
        DEVICE_MANAGER_KEYSPACE_NAME: {
            "PR_VN_IP_CF": {
                "name": "dm_pr_vn_ip_table",
                "issu": True,
            },
            "PR_ASN_CF": {
                "name": "dm_pr_asn_table",
                "issu": True,
            },
            "NI_IPV6_LL_CF": {
                "name": "dm_ni_ipv6_ll_table",
                "issu": True,
            },
            "PNF_RESOURCE_CF": {
                "name": "dm_pnf_resource_table",
                "issu": True,
            }
        },
        USERAGENT_KEYSPACE_NAME: {
            "USERAGENT_KV_CF": {
                "name": "useragent_keyval_table",
                "issu": True,
            },
        },
        SCHEMA_KEYSPACE_NAME: {
            "RT_CF": {
                "name": "route_target_table",
                "issu": True,
            },
            "SC_IP_CF": {
                "name": "service_chain_ip_address_table",
                "issu": True,
            },
            "SERVICE_CHAIN_CF": {
                "name": "service_chain_table",
                "issu": True,
            },
            "SERVICE_CHAIN_UUID_CF": {
                "name": "service_chain_uuid_table",
                "issu": True,
            },
        },
        SVC_MONITOR_KEYSPACE_NAME: {
            "SVC_SI_CF": {
                "name": "service_instance_table",
                "issu": True,
            },
            "POOL_CF": {
                "name": "pool_table",
                "issu": True,
            },
            "LB_CF": {
                "name": "loadbalancer_table",
                "issu": True,
            },
            "HM_CF": {
                "name": "healthmonitor_table",
                "issu": True,
            }
        }
    }

    @classmethod
    def get_cf_name(cls, keyspace, cf_key):
        return cls._KEYSPACES[keyspace][cf_key]['name']

    @classmethod
    def get_issu_cfs(cls, keyspace):
        issu_cfs = []
        for cf_key, cf in cls._KEYSPACES[keyspace].items():
            if cf['issu']:
                issu_cfs.append(cf['name'])
        return issu_cfs
