#
# Copyright (c) 2018 Juniper Networks, Inc. All rights reserved.
#

import os

from cfgm_common import _obj_serializer_all
from cfgm_common import get_bgp_rtgt_max_id
from cfgm_common import get_bgp_rtgt_min_id
from cfgm_common import get_lr_internal_vn_name
from cfgm_common import jsonutils as json
from cfgm_common.exceptions import HttpError
from cfgm_common.exceptions import NoIdError
from cfgm_common.exceptions import ResourceExistsError
from cfgm_common.utils import _DEFAULT_ZK_FABRIC_LR_PATH_PREFIX
from cfgm_common.zkclient import ZookeeperLock
from vnc_api.gen.resource_common import LogicalRouter
from vnc_api.gen.resource_common import Project
from vnc_api.gen.resource_common import VirtualNetwork
from vnc_api.gen.resource_xsd import IdPermsType
from vnc_api.gen.resource_xsd import LogicalRouterVirtualNetworkType
from vnc_api.gen.resource_xsd import RouteTargetList
from vnc_api.gen.resource_xsd import VirtualNetworkType

from vnc_cfg_api_server.context import get_context
from vnc_cfg_api_server.resources._resource_base import ResourceMixin


class LogicalRouterServer(ResourceMixin, LogicalRouter):
    @classmethod
    def is_port_in_use_by_vm(cls, obj_dict, db_conn):
        for vmi_ref in obj_dict.get('virtual_machine_interface_refs') or []:
            vmi_id = vmi_ref['uuid']
            ok, read_result = cls.dbe_read(
                db_conn, 'virtual_machine_interface', vmi_ref['uuid'])
            if not ok:
                return ok, read_result
            if (read_result['parent_type'] == 'virtual-machine' or
                    read_result.get('virtual_machine_refs')):
                msg = ("Port(%s) already in use by virtual-machine(%s)" %
                       (vmi_id, read_result['parent_uuid']))
                return False, (409, msg)
        return True, ''

    @classmethod
    def _format_lr_vn_znode(cls, vn_uuid, fabric_uuid):
        return os.path.join(
            _DEFAULT_ZK_FABRIC_LR_PATH_PREFIX,
            'virtual-network:%s' % vn_uuid,
            'fabric:%s' % fabric_uuid)

    @classmethod
    def is_vn_not_in_another_lr(cls, db_conn, vn_refs,
                                fabric_uuid, lr_fqname_str):

        # try to create validation znode with vn_uuid/fab_uuid
        # and value as lr_fq_name list. if successful --> OK,
        # if not --> shared vn or validation condition or stale.
        # If shared, append to the existing list. If stale,
        # delete the old value for this znode path and replace
        # it with new value

        for vn_ref in vn_refs:
            is_shared = cls._check_if_shared_across_all_lrs(
                db_conn, vn_ref)
            validation_znode = cls._format_lr_vn_znode(
                vn_uuid=vn_ref['uuid'], fabric_uuid=fabric_uuid)
            try:
                cls.db_conn._zk_db._zk_client.create_node(
                    validation_znode, value=[lr_fqname_str])

                def undo_create_lr_validation_node():
                    cls.db_conn._zk_db._zk_client.delete_node(
                        validation_znode, True)
                    return True, None
                get_context().push_undo(undo_create_lr_validation_node)
            except ResourceExistsError:

                exis_lr_fqname_list = \
                    cls.db_conn._zk_db._zk_client.read_node(
                        validation_znode)
                if lr_fqname_str in exis_lr_fqname_list:
                    return True, None

                # check if shared
                if is_shared:
                    exis_lr_fqname_list.append(lr_fqname_str)
                    cls.db_conn._zk_db._zk_client.update_node(
                        validation_znode, repr(
                            exis_lr_fqname_list).encode('ascii'))
                # Might be validation error or stale
                else:
                    try:
                        # assuming it is not shared, there can be only
                        # one lr_fqname_str in the list
                        exis_lr_fqname_str = exis_lr_fqname_list[-1]
                        # NOT STALE chk
                        _ = db_conn.uuid_to_fq_name(exis_lr_fqname_str)
                        try:
                            vn_fq_name = db_conn.uuid_to_fq_name(
                                vn_ref['uuid'])
                        except NoIdError as exc:
                            msg = ("Error while trying to obtain fq_name "
                                   "for vn id %s: %s " % (vn_ref['uuid'],
                                                          str(exc)))
                            return False, (404, msg)

                        # check if the znode path - vn and fabric are still
                        # referred by the existing lr fqname str, if yes,
                        # validation error else still stale although LR
                        # exists in vnc db

                        is_vn_referred, err_obj = \
                            cls.is_vn_fab_referred_by_lr(
                                db_conn, vn_ref, fabric_uuid,
                                exis_lr_fqname_str)

                        if is_vn_referred:
                            # validation error as vn and fab is referred in
                            # vnc db itself
                            return False, (exis_lr_fqname_str, vn_fq_name)
                        elif err_obj:
                            return is_vn_referred, err_obj
                        else:
                            # vn or fabric is not referred; stale condition
                            raise NoIdError("vn or fabric in znode is "
                                            "no longer referred to by "
                                            "logical router")

                    except NoIdError:  # STALE
                        lr_lock_args = {
                            'zookeeper_client': db_conn._zk_db._zk_client,
                            'path': validation_znode,
                            'name': lr_fqname_str, 'timeout': 60}
                        with ZookeeperLock(**lr_lock_args):
                            cls.db_conn._zk_db._zk_client.update_node(
                                validation_znode, repr(
                                    [lr_fqname_str]).encode('ascii'))

        return True, None

    @classmethod
    def is_vn_fab_referred_by_lr(cls, db_conn, vn_ref, fabric_uuid,
                                 lr_fqname_str):
        try:
            lr_uuid = db_conn.fq_name_to_uuid(lr_fqname_str.split(':'))
            lr_dict = dict()
            lr_dict['uuid'] = lr_uuid
            zk_kwargs = cls._check_and_delete_vn_map(lr_dict, db_conn)

            if zk_kwargs:
                vn_uuids = []
                for vn in zk_kwargs.get('vns_to_del', []):
                    vn_uuids.append(vn['uuid'])
                if zk_kwargs.get('fab_to_del') == fabric_uuid and \
                        vn_ref['uuid'] in vn_uuids:
                    return True, None
        except Exception as exc:
            msg = ("An error occurred while trying to check if logical"
                   "router: %s is stale: %s" % (lr_fqname_str, str(exc)))
            return False, (404, msg)
        return False, None

    @classmethod
    def _check_if_shared_across_all_lrs(cls, db_conn, vn_ref):
        vn_uuid = vn_ref['uuid']

        if vn_uuid:
            ok, read_result = cls.dbe_read(db_conn, 'virtual_network',
                                           vn_uuid)
            if ok:
                vn_routed_props_shared = read_result.get(
                    'virtual_network_routed_properties', {}).get(
                    'shared_across_all_lrs')
                if vn_routed_props_shared:
                    return True

        return False
    # end _check_if_shared_across_all_lrs

    @classmethod
    def _check_and_associate_logical_router_vn(cls, db_conn, obj_dict,
                                               lr_id=None):
        vn_refs = []
        existing_vn_refs = []
        fab_refs = []
        pr_refs_exis = []
        fab_uuid_to_be_del = None
        fabric_uuid = None
        delete_znode_kwargs = {}

        if 'virtual_machine_interface_refs' in obj_dict:
            vmi_refs = obj_dict.get('virtual_machine_interface_refs')
            for vmi_ref in vmi_refs:
                ok, read_result = cls.dbe_read(db_conn,
                                               'virtual_machine_interface',
                                               vmi_ref['uuid'])
                if not ok:
                    return ok, read_result, None

                vn_refs.extend(read_result.get('virtual_network_refs', []))
        else:
            vn_refs = None

        # update
        if lr_id:
            ok, read_result = cls.dbe_read(db_conn, 'logical_router',
                                           lr_id)
            if not ok:
                return ok, read_result, None

            lr_fq_name = read_result.get('fq_name')
            pr_refs_exis = read_result.get('physical_router_refs', [])
            fab_refs = obj_dict.get('fabric_refs',
                                    read_result.get('fabric_refs', []))
            # fabric ref update as part of LR update
            if fab_refs != read_result.get('fabric_refs', []):
                if read_result.get('fabric_refs'):
                    fab_uuid_to_be_del = read_result.get(
                        'fabric_refs')[-1].get('uuid')

            existing_vmi_refs = read_result.get(
                'virtual_machine_interface_refs', []
            )
            for existing_vmi_ref in existing_vmi_refs:
                ok, existing_vmi_ref_obj = cls.dbe_read(
                    db_conn,
                    'virtual_machine_interface',
                    existing_vmi_ref['uuid'])
                if not ok:
                    return ok, existing_vmi_ref_obj, None
                existing_vn_refs.extend(
                    existing_vmi_ref_obj.get('virtual_network_refs', []))

        # create
        else:
            lr_fq_name = obj_dict['fq_name']
            fab_refs = obj_dict.get('fabric_refs', [])

        if vn_refs is None:
            vn_refs = existing_vn_refs

        # try to get fab_refs from pr if not obtained
        # already through obj_dict (user input) or
        # read through vnc db (already existing)

        if not fab_refs:
            fab_refs_new = []
            pr_refs_inp = obj_dict.get('physical_router_refs',
                                       pr_refs_exis)

            if (pr_refs_inp == pr_refs_exis) or not pr_refs_exis:
                if pr_refs_inp:
                    pr_uuid = pr_refs_inp[-1].get('uuid')
                    if not pr_uuid:
                        pr_uuid = db_conn.fq_name_to_uuid(
                            'physical_router',
                            pr_refs_inp[-1].get('to')
                        )
                    (ok, pr_obj) = cls.dbe_read(db_conn,
                                                'physical_router',
                                                pr_uuid)
                    fab_refs = pr_obj.get('fabric_refs', [])
            else:
                # pr_refs_exis is not [] and is different
                # from pr_refs_inp --> may be a case of fab update
                pr_uuid = pr_refs_exis[-1].get('uuid')
                if not pr_uuid:
                    pr_uuid = db_conn.fq_name_to_uuid(
                        'physical_router',
                        pr_refs_exis[-1].get('to')
                    )
                (ok, pr_obj) = cls.dbe_read(db_conn,
                                            'physical_router',
                                            pr_uuid)
                fab_refs_exis = pr_obj.get('fabric_refs', [])
                if pr_refs_inp:
                    pr_uuid = pr_refs_inp[-1].get('uuid')
                    if not pr_uuid:
                        pr_uuid = db_conn.fq_name_to_uuid(
                            'physical_router',
                            pr_refs_inp[-1].get('to')
                        )
                    (ok, pr_obj) = cls.dbe_read(db_conn,
                                                'physical_router',
                                                pr_uuid)
                    fab_refs_new = pr_obj.get('fabric_refs', [])
                    fab_refs = fab_refs_new
                if fab_refs_new != fab_refs_exis:
                    if fab_refs_exis:
                        fab_uuid_to_be_del = fab_refs_exis[-1].get(
                            'uuid')
        lr_fq_name_str = ':'.join(lr_fq_name)
        if fab_refs:
            fabric_uuid = str(fab_refs[-1].get('uuid'))

            vns_not_in_another_lr, results = \
                cls.is_vn_not_in_another_lr(
                    db_conn,
                    vn_refs,
                    fabric_uuid,
                    lr_fq_name_str)
            if not vns_not_in_another_lr:
                result = results[0]
                vn_fq_name = results[1]

                # check for uuid not present
                if result == 404:
                    return vns_not_in_another_lr, results, None

                # Error case when fabric uuid already has some
                # LR fq names against it
                err_msg = ("Virtual Network %s already exists"
                           " in LogicalRouter(s)(%s)"
                           % (vn_fq_name, str(result)))
                return vns_not_in_another_lr, (400, err_msg), None

        # clean up of any previous fabric keys must happen
        # irrespective of if there is a new fabric update
        # or not. Eg. if there is a VMI update but no fabric
        # update and if there is a fabric update.

        if lr_id:
            if fab_uuid_to_be_del:
                delete_znode_kwargs['fab_to_del'] = fab_uuid_to_be_del
                delete_znode_kwargs['vns_to_del'] = existing_vn_refs
            else:
                vn_refs_to_be_deleted = []
                for exis_vn_ref in existing_vn_refs:
                    if exis_vn_ref not in vn_refs:
                        vn_refs_to_be_deleted.append(exis_vn_ref)
                delete_znode_kwargs['vns_to_del'] = vn_refs_to_be_deleted
                delete_znode_kwargs['fab_to_del'] = fabric_uuid

        return True, '', delete_znode_kwargs

    @classmethod
    def is_port_gateway_in_same_network(cls, db_conn, vmi_refs, vn_refs):
        interface_vn_uuids = []
        for vmi_ref in vmi_refs:
            ok, vmi_result = cls.dbe_read(
                db_conn, 'virtual_machine_interface', vmi_ref['uuid'])
            if not ok:
                return ok, vmi_result

            if vmi_result.get('virtual_network_refs'):
                interface_vn_uuids.append(
                    vmi_result['virtual_network_refs'][0]['uuid'])
            for vn_ref in vn_refs:
                if vn_ref['uuid'] in interface_vn_uuids:
                    msg = ("Logical router interface and gateway cannot be in"
                           "VN(%s)" % vn_ref['uuid'])
                    return False, (400, msg)
        return True, ''

    @classmethod
    def check_port_gateway_not_in_same_network(cls, db_conn, obj_dict,
                                               lr_id=None):
        if ('virtual_network_refs' in obj_dict and
                'virtual_machine_interface_refs' in obj_dict):
            ok, result = cls.is_port_gateway_in_same_network(
                db_conn,
                obj_dict['virtual_machine_interface_refs'],
                obj_dict['virtual_network_refs'])
            if not ok:
                return ok, result
        # update
        if lr_id:
            if ('virtual_network_refs' in obj_dict or
                    'virtual_machine_interface_refs' in obj_dict):
                ok, read_result = cls.dbe_read(db_conn, 'logical_router',
                                               lr_id)
                if not ok:
                    return ok, read_result
            if 'virtual_network_refs' in obj_dict:
                ok, result = cls.is_port_gateway_in_same_network(
                    db_conn,
                    read_result.get('virtual_machine_interface_refs') or [],
                    obj_dict['virtual_network_refs'])
                if not ok:
                    return ok, result
            if 'virtual_machine_interface_refs' in obj_dict:
                ok, result = cls.is_port_gateway_in_same_network(
                    db_conn,
                    obj_dict['virtual_machine_interface_refs'],
                    read_result.get('virtual_network_refs') or [])
                if not ok:
                    return ok, result
        return True, ''

    @classmethod
    def is_vxlan_routing_enabled(cls, db_conn, obj_dict):
        # The function expects the obj_dict to have
        # either the UUID of the LR object or the
        # parent's uuid (for the create case)
        if 'parent_uuid' not in obj_dict:
            if 'uuid' not in obj_dict:
                msg = "No input to derive parent for Logical Router"
                return False, (400, msg)
            ok, lr = db_conn.dbe_read('logical_router', obj_dict['uuid'])
            if not ok:
                return False, (400, 'Logical Router not found')
            project_uuid = lr.get('parent_uuid')
        else:
            project_uuid = obj_dict['parent_uuid']

        ok, project = db_conn.dbe_read('project', project_uuid)
        if not ok:
            return ok, (400, 'Parent project for Logical Router not found')
        vxlan_routing = project.get('vxlan_routing', False)

        return True, vxlan_routing

    @staticmethod
    def _check_vxlan_id_in_lr(obj_dict):
        # UI as of July 2018 can still send empty vxlan_network_identifier
        # the empty value is one of 'None', None or ''.
        # Handle all these scenarios
        if ('vxlan_network_identifier' in obj_dict):
            vxlan_network_identifier = obj_dict['vxlan_network_identifier']
            if (vxlan_network_identifier != 'None' and
                    vxlan_network_identifier is not None and
                    vxlan_network_identifier != ''):
                return vxlan_network_identifier
            else:
                obj_dict['vxlan_network_identifier'] = None
                return None
        else:
            return None

    @staticmethod
    def check_lr_type(obj_dict):
        if 'logical_router_type' in obj_dict:
            return obj_dict['logical_router_type']

        return None

    @classmethod
    def _ensure_lr_dci_association(cls, lr):
        # if no DCI refs, no need to validate LR - Fabric relationship
        if not lr.get('data_center_interconnect_back_refs'):
            return True, ''

        # make sure lr should have association with only one fab PRs
        fab_list = []
        for pr_ref in lr.get('physical_router_refs') or []:
            pr_uuid = pr_ref.get('uuid')
            status, pr_result = cls.dbe_read(cls.db_conn, 'physical_router',
                                             pr_uuid, obj_fields=[
                                                 'fabric_refs'])
            if not status:
                return False, pr_result
            if pr_result.get("fabric_refs"):
                fab_id = pr_result["fabric_refs"][0].get('uuid')
                if fab_id in fab_list:
                    msg = ("LR can not associate with PRs from different "
                           "Fabrics, if DCI is enabled")
                    return False, (400, msg)
                else:
                    fab_list.append(fab_id)
            else:
                msg = ("DCI LR can not associate to PRs which are not part of "
                       "any Fabrics")
                return False, (400, msg)
        return True, ''

    @classmethod
    def _check_type(cls, obj_dict, read_result=None):
        logical_router_type = cls.check_lr_type(obj_dict)
        if read_result is None:
            if logical_router_type is None:
                # If logical_router_type not specified in obj_dict,
                # set it to default 'snat-routing'
                obj_dict['logical_router_type'] = 'snat-routing'
        else:
            logical_router_type_in_db = cls.check_lr_type(read_result)

            if (logical_router_type and
                    logical_router_type != logical_router_type_in_db):
                msg = ("Cannot update logical_router_type for a "
                       "Logical Router")
                return False, (400, msg)
        return (True, '')

    @classmethod
    def _check_route_targets(cls, obj_dict):
        rt_dict = obj_dict.get('configured_route_target_list')
        if not rt_dict:
            return True, ''

        route_target_list = rt_dict.get('route_target')
        if not route_target_list:
            return True, ''

        global_asn = cls.server.global_autonomous_system
        for idx, rt in enumerate(route_target_list):
            ok, result, new_rt = cls.server.get_resource_class(
                'route_target').validate_route_target(rt)
            if not ok:
                return False, result
            user_defined_rt = result
            if not user_defined_rt:
                return (False, "Configured route target must use ASN that is "
                        "different from global ASN or route target value must"
                        " be less than %d and greater than %d" %
                        (get_bgp_rtgt_min_id(global_asn),
                         get_bgp_rtgt_max_id(global_asn)))
            if new_rt:
                route_target_list[idx] = new_rt
        return (True, '')

    @classmethod
    def pre_dbe_create(cls, tenant_name, obj_dict, db_conn):
        ok, result = cls._ensure_lr_dci_association(obj_dict)
        if not ok:
            return ok, result

        ok, result = cls.check_port_gateway_not_in_same_network(db_conn,
                                                                obj_dict)
        if not ok:
            return ok, result

        ok, result = cls.is_port_in_use_by_vm(obj_dict, db_conn)
        if not ok:
            return ok, result

        (ok, error) = cls._check_route_targets(obj_dict)
        if not ok:
            return (False, (400, error))

        ok, result = cls._check_type(obj_dict)
        if not ok:
            return ok, result

        ok, result, _ = cls._check_and_associate_logical_router_vn(
            db_conn, obj_dict)
        if not ok:
            return ok, result

        vxlan_id = cls._check_vxlan_id_in_lr(obj_dict)
        logical_router_type = cls.check_lr_type(obj_dict)

        if vxlan_id and logical_router_type == 'vxlan-routing':
            # If input vxlan_id is not None, that means we need to reserve it.

            # First, if vxlan_id is not None, set it in Zookeeper and set the
            # undo function for when any failures happen later.
            # But first, get the internal_vlan name using which the resource
            # in zookeeper space will be reserved.

            vxlan_fq_name = '%s:%s_vxlan' % (
                ':'.join(obj_dict['fq_name'][:-1]),
                get_lr_internal_vn_name(obj_dict['uuid']),
            )

            try:
                # Now that we have the internal VN name, allocate it in
                # zookeeper only if the resource hasn't been reserved already
                cls.vnc_zk_client.alloc_vxlan_id(vxlan_fq_name, int(vxlan_id))
            except ResourceExistsError:
                msg = ("Cannot set VXLAN_ID: %s, it has already been set"
                       % vxlan_id)
                return False, (400, msg)

            def undo_vxlan_id():
                cls.vnc_zk_client.free_vxlan_id(int(vxlan_id), vxlan_fq_name)
                return True, ""
            get_context().push_undo(undo_vxlan_id)

        # Check if type of all associated BGP VPN are 'l3'
        ok, result = cls.server.get_resource_class(
            'bgpvpn').check_router_supports_vpn_type(obj_dict)
        if not ok:
            return ok, result

        # Check if we can reference the BGP VPNs
        return cls.server.get_resource_class(
            'bgpvpn').check_router_has_bgpvpn_assoc_via_network(obj_dict)

    @classmethod
    def pre_dbe_update(cls, id, fq_name, obj_dict, db_conn, **kwargs):

        zk_update_kwargs = {}
        ok, result = cls._ensure_lr_dci_association(obj_dict)
        if not ok:
            return ok, result, zk_update_kwargs

        ok, result = cls.check_port_gateway_not_in_same_network(
            db_conn, obj_dict, id)
        if not ok:
            return ok, result, zk_update_kwargs

        ok, result = cls.is_port_in_use_by_vm(obj_dict, db_conn)
        if not ok:
            return ok, result, zk_update_kwargs

        (ok, error) = cls._check_route_targets(obj_dict)
        if not ok:
            return (False, (400, error), zk_update_kwargs)

        ok, result, zk_update_kwargs = \
            cls._check_and_associate_logical_router_vn(db_conn, obj_dict, id)

        if not ok:
            return ok, result, zk_update_kwargs

        # To get the current vxlan_id, read the LR from the DB
        ok, result = cls.dbe_read(cls.db_conn,
                                  'logical_router',
                                  id,
                                  obj_fields=['virtual_network_refs',
                                              'logical_router_type',
                                              'vxlan_network_identifier'])
        if not ok:
            return ok, result, zk_update_kwargs

        read_result = result

        ok, result = cls._check_type(obj_dict, read_result)
        if not ok:
            return ok, result, zk_update_kwargs

        logical_router_type_in_db = cls.check_lr_type(read_result)

        if ('vxlan_network_identifier' in obj_dict and
                logical_router_type_in_db == 'vxlan-routing'):

            new_vxlan_id = cls._check_vxlan_id_in_lr(obj_dict)
            old_vxlan_id = cls._check_vxlan_id_in_lr(read_result)

            if new_vxlan_id != old_vxlan_id:
                int_fq_name = None
                for vn_ref in read_result['virtual_network_refs']:
                    if (vn_ref.get('attr', {}).get(
                            'logical_router_virtual_network_type') ==
                            'InternalVirtualNetwork'):
                        int_fq_name = vn_ref.get('to')
                        break

                if int_fq_name is None:
                    msg = "Internal FQ name not found"
                    return False, (400, msg), zk_update_kwargs

                vxlan_fq_name = ':'.join(int_fq_name) + '_vxlan'
                if new_vxlan_id is not None:
                    # First, check if the new_vxlan_id being updated exist for
                    # some other VN.
                    new_vxlan_fq_name_in_db = cls.vnc_zk_client.get_vn_from_id(
                        int(new_vxlan_id))
                    if new_vxlan_fq_name_in_db is not None:
                        if new_vxlan_fq_name_in_db != vxlan_fq_name:
                            msg = ("Cannot set VXLAN_ID: %s, it has already "
                                   "been set" % new_vxlan_id)
                            return False, (400, msg), zk_update_kwargs

                    # Second, set the new_vxlan_id in Zookeeper.
                    cls.vnc_zk_client.alloc_vxlan_id(vxlan_fq_name,
                                                     int(new_vxlan_id))

                    def undo_alloc():
                        cls.vnc_zk_client.free_vxlan_id(
                            int(old_vxlan_id), vxlan_fq_name)
                    get_context().push_undo(undo_alloc)

                # Third, check if old_vxlan_id is not None, if so, delete it
                # from Zookeeper
                if old_vxlan_id is not None:
                    cls.vnc_zk_client.free_vxlan_id(int(old_vxlan_id),
                                                    vxlan_fq_name)

                    def undo_free():
                        cls.vnc_zk_client.alloc_vxlan_id(
                            vxlan_fq_name, int(old_vxlan_id))
                    get_context().push_undo(undo_free)

        # Check if type of all associated BGP VPN are 'l3'
        ok, result = cls.server.get_resource_class(
            'bgpvpn').check_router_supports_vpn_type(obj_dict)
        if not ok:
            return ok, result, zk_update_kwargs

        # Check if we can reference the BGP VPNs
        ok, result = cls.dbe_read(
            db_conn,
            'logical_router',
            id,
            obj_fields=['bgpvpn_refs', 'virtual_machine_interface_refs'])
        if not ok:
            return ok, result, zk_update_kwargs

        ok, res = cls.server.get_resource_class(
            'bgpvpn').check_router_has_bgpvpn_assoc_via_network(
                obj_dict, result)
        return ok, res, zk_update_kwargs

    @classmethod
    def get_parent_project(cls, obj_dict, db_conn):
        proj_uuid = obj_dict.get('parent_uuid')
        ok, proj_dict = cls.dbe_read(db_conn, 'project', proj_uuid)
        return ok, proj_dict

    @classmethod
    def post_dbe_update(cls, uuid, fq_name, obj_dict, db_conn,
                        prop_collection_updates=None, **kwargs):

        if kwargs:
            if kwargs.get('fab_to_del') and kwargs.get('vns_to_del'):
                cls._del_validation_znodes(
                    fabric_uuid=kwargs.get('fab_to_del'),
                    vn_refs=kwargs.get('vns_to_del')
                )

        ok, result = db_conn.dbe_read(
            'logical_router',
            obj_dict['uuid'],
            obj_fields=['virtual_network_refs', 'logical_router_type'])
        if not ok:
            return ok, result
        lr_orig_dict = result

        if (obj_dict.get('configured_route_target_list') is None and
                'vxlan_network_identifier' not in obj_dict):
            return True, ''

        logical_router_type_in_db = cls.check_lr_type(lr_orig_dict)
        if logical_router_type_in_db == 'vxlan-routing':
            # If logical_router_type was set to vxlan-routing in DB,
            # it means that an existing LR used for VXLAN
            # support was updated to either change the
            # vxlan_network_identifer or configured_route_target_list

            vn_int_name = get_lr_internal_vn_name(obj_dict.get('uuid'))
            vn_id = None
            for vn_ref in lr_orig_dict.get('virtual_network_refs') or []:
                if (vn_ref.get('attr', {}).get(
                        'logical_router_virtual_network_type') ==
                        'InternalVirtualNetwork'):
                    vn_id = vn_ref.get('uuid')
                    break
            if vn_id is None:
                return True, ''
            ok, vn_dict = db_conn.dbe_read(
                'virtual_network',
                vn_id,
                obj_fields=['route_target_list',
                            'fq_name',
                            'uuid',
                            'parent_uuid',
                            'virtual_network_properties'])
            if not ok:
                return ok, vn_dict
            vn_rt_dict_list = vn_dict.get('route_target_list')
            vn_rt_list = []
            if vn_rt_dict_list:
                vn_rt_list = vn_rt_dict_list.get('route_target', [])
            lr_rt_list_obj = obj_dict.get('configured_route_target_list')
            lr_rt_list = []
            if lr_rt_list_obj:
                lr_rt_list = lr_rt_list_obj.get('route_target', [])

            vxlan_id_in_db = vn_dict.get('virtual_network_properties', {}).get(
                'vxlan_network_identifier')

            if(vxlan_id_in_db != obj_dict.get('vxlan_network_identifier') or
                    set(vn_rt_list) != set(lr_rt_list)):
                ok, proj_dict = db_conn.dbe_read('project',
                                                 vn_dict['parent_uuid'])
                if not ok:
                    return ok, proj_dict
                proj_obj = Project(name=vn_dict.get('fq_name')[-2],
                                   parent_type='domain',
                                   fq_name=proj_dict.get('fq_name'))

                vn_obj = VirtualNetwork(name=vn_int_name, parent_obj=proj_obj)

                if (set(vn_rt_list) != set(lr_rt_list)):
                    vn_obj.set_route_target_list(lr_rt_list_obj)

                # If vxlan_id has been set, we need to propogate it to the
                # internal VN.
                if vxlan_id_in_db != obj_dict.get('vxlan_network_identifier'):
                    prop = vn_dict.get('virtual_network_properties', {})
                    if obj_dict.get('vxlan_network_identifier'):
                        prop['vxlan_network_identifier'] =\
                            obj_dict['vxlan_network_identifier']
                        vn_obj.set_virtual_network_properties(prop)

                vn_int_dict = json.dumps(vn_obj, default=_obj_serializer_all)
                status, obj = cls.server.internal_request_update(
                    'virtual-network',
                    vn_dict['uuid'],
                    json.loads(vn_int_dict))
        return True, ''

    @classmethod
    def create_intvn_and_ref(cls, obj_dict):
        vn_fq_name = (obj_dict['fq_name'][:-1] +
                      [get_lr_internal_vn_name(obj_dict['uuid'])])
        kwargs = {'id_perms': IdPermsType(user_visible=False, enable=True)}
        kwargs['display_name'] = 'LR::%s' % obj_dict['fq_name'][-1]
        vn_property = VirtualNetworkType(forwarding_mode='l3')
        if 'vxlan_network_identifier' in obj_dict:
            vn_property.set_vxlan_network_identifier(
                obj_dict['vxlan_network_identifier'])
        kwargs['virtual_network_properties'] = vn_property
        rt_list = obj_dict.get(
            'configured_route_target_list', {}).get('route_target')
        if rt_list:
            kwargs['route_target_list'] = RouteTargetList(rt_list)
        ok, result = cls.server.get_resource_class(
            'virtual_network').locate(vn_fq_name, **kwargs)
        if not ok:
            return False, result

        attr_obj = LogicalRouterVirtualNetworkType('InternalVirtualNetwork')
        attr_dict = attr_obj.__dict__
        api_server = cls.server

        try:
            api_server.internal_request_ref_update(
                'logical-router',
                obj_dict['uuid'],
                'ADD',
                'virtual-network',
                result['uuid'],
                result['fq_name'],
                attr=attr_dict)
        except HttpError as e:
            return False, (e.status_code, e.content)
        return True, ''

    @classmethod
    def post_dbe_create(cls, tenant_name, obj_dict, db_conn):
        logical_router_type = cls.check_lr_type(obj_dict)

        # If VxLAN routing is enabled for this LR
        # then create an internal VN to export the routes
        # in the private VNs to the VTEPs.
        if logical_router_type == 'vxlan-routing':
            ok, result = cls.create_intvn_and_ref(obj_dict)
            if not ok:
                return ok, result

        return True, ''

    @classmethod
    def _del_validation_znodes(cls, fabric_uuid,
                               vn_refs):
        fabric_uuid = str(fabric_uuid)
        for vn_ref in vn_refs:
            validation_znode = cls._format_lr_vn_znode(vn_uuid=vn_ref['uuid'],
                                                       fabric_uuid=fabric_uuid)
            cls.db_conn._zk_db._zk_client.delete_node(
                validation_znode, True)

    @classmethod
    def _check_and_delete_vn_map(cls, obj_dict, db_conn):

        vn_refs = []
        delete_znode_kwargs = {}
        ok, result = db_conn.dbe_read(
            'logical_router',
            obj_dict['uuid'],
            obj_fields=['virtual_machine_interface_refs',
                        'fabric_refs',
                        'physical_router_refs'])
        if ok and result.get('virtual_machine_interface_refs'):
            fabric_uuid = None
            if result.get('fabric_refs'):
                fabric_uuid = result.get('fabric_refs')[-1].get('uuid')
            elif result.get('physical_router_refs'):
                pr_ref = result.get('physical_router_refs')[-1]
                pr_uuid = pr_ref.get('uuid',
                                     db_conn.fq_name_to_uuid(
                                         'physical_router',
                                         pr_ref.get('to')
                                     ))
                ok, pr = db_conn.dbe_read('physical_router',
                                          pr_uuid,
                                          obj_fields=['fabric_refs'])
                if ok and pr.get('fabric_refs'):
                    fabric_uuid = pr.get('fabric_refs')[-1].get('uuid')
            if fabric_uuid:
                for vmi_ref in result.get(
                        'virtual_machine_interface_refs'):
                    ok, res = db_conn.dbe_read(
                        'virtual_machine_interface',
                        vmi_ref['uuid'])
                    if ok:
                        vn_refs.extend(
                            res.get('virtual_network_refs', []))

                delete_znode_kwargs['fab_to_del'] = fabric_uuid
                delete_znode_kwargs['vns_to_del'] = vn_refs

        return delete_znode_kwargs

    @classmethod
    def pre_dbe_delete(cls, id, obj_dict, db_conn):

        zk_kwargs = cls._check_and_delete_vn_map(obj_dict, db_conn)

        logical_router_type = cls.check_lr_type(obj_dict)
        if logical_router_type == 'vxlan-routing':
            vn_int_fqname = (obj_dict['fq_name'][:-1] +
                             [get_lr_internal_vn_name(obj_dict['uuid'])])
            vn_int_uuid = db_conn.fq_name_to_uuid('virtual_network',
                                                  vn_int_fqname)

            api_server = cls.server
            try:
                api_server.internal_request_ref_update(
                    'logical-router',
                    obj_dict['uuid'],
                    'DELETE',
                    'virtual-network',
                    vn_int_uuid,
                    vn_int_fqname)
                api_server.internal_request_delete('virtual-network',
                                                   vn_int_uuid)
            except HttpError as e:
                if e.status_code != 404:
                    return False, (e.status_code, e.content), None
            except NoIdError:
                pass

            def undo_int_vn_delete():
                return cls.create_intvn_and_ref(obj_dict)
            get_context().push_undo(undo_int_vn_delete)

        return True, '', zk_kwargs

    @classmethod
    def post_dbe_delete(cls, id, obj_dict, db_conn, **kwargs):

        if kwargs:
            if kwargs.get('fab_to_del') and kwargs.get('vns_to_del'):
                cls._del_validation_znodes(
                    fabric_uuid=kwargs.get('fab_to_del'),
                    vn_refs=kwargs.get('vns_to_del')
                )

        return True, '', None
